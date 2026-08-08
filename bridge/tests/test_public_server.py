from __future__ import annotations

import json
import socket
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPResponse
from typing import Any

import pytest

from balcony_watering.public_gateway import GatewayReply
from balcony_watering.public_server import create_server


class FakeGateway:
    def __init__(self) -> None:
        self.status_calls = 0
        self.water_calls = 0
        self.stop_calls = 0

    def status(self) -> GatewayReply:
        self.status_calls += 1
        return GatewayReply(
            200,
            {
                "online": True,
                "state": "IDLE",
                "pump": False,
                "armed": True,
                "remaining_sec": 0,
                "public_duration_sec": 10,
                "hourly_used": 0,
                "hourly_limit": 6,
                "daily_used": 0,
                "daily_limit": 24,
                "retry_after_sec": 0,
            },
        )

    def water(self) -> GatewayReply:
        self.water_calls += 1
        return GatewayReply(
            202,
            {
                "accepted": True,
                "request_id": "pub-test",
                "state": "WATERING",
                "duration_sec": 10,
            },
        )

    def stop(self) -> GatewayReply:
        self.stop_calls += 1
        return GatewayReply(200, {"stopped": True, "state": "IDLE"})


@contextmanager
def running_server(
    gateway: Any,
    *,
    request_timeout_sec: float = 5.0,
    max_active_requests: int = 32,
) -> Iterator[tuple[str, int]]:
    server = create_server(
        ("127.0.0.1", 0),
        gateway=gateway,
        public_origin="https://tree.example.com",
        request_timeout_sec=request_timeout_sec,
        max_active_requests=max_active_requests,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(
    address: tuple[str, int],
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[HTTPResponse, bytes]:
    connection = HTTPConnection(*address, timeout=2)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


def json_request(
    address: tuple[str, int],
    method: str,
    path: str,
    body: dict[str, object],
    *,
    origin: str | None = "https://tree.example.com",
) -> tuple[HTTPResponse, dict[str, Any]]:
    encoded = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    response, payload = request(address, method, path, body=encoded, headers=headers)
    return response, json.loads(payload)


def test_static_app_and_assets_are_served_with_locked_down_headers() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        root, html = request(address, "GET", "/")
        stylesheet, css = request(address, "GET", "/app.css")
        script, javascript = request(address, "GET", "/app.js")

    assert root.status == 200
    assert root.getheader("Content-Type") == "text/html; charset=utf-8"
    assert b'id="water-button"' in html
    assert b"/app.css" in html
    assert b"/app.js" in html
    assert stylesheet.status == 200
    assert stylesheet.getheader("Content-Type") == "text/css; charset=utf-8"
    assert b"prefers-reduced-motion" in css
    assert script.status == 200
    assert script.getheader("Content-Type") == "text/javascript; charset=utf-8"
    assert b'fetch("/api/status"' in javascript

    for response in (root, stylesheet, script):
        assert response.getheader("Cache-Control") == "no-store"
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert response.getheader("Referrer-Policy") == "no-referrer"
        assert response.getheader("Connection") == "close"
        policy = response.getheader("Content-Security-Policy")
        assert policy is not None
        assert "default-src 'none'" in policy
        assert "script-src 'self'" in policy
        assert "'unsafe-inline'" not in policy


def test_status_route_returns_gateway_reply() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        response, payload = request(address, "GET", "/api/status")

    assert response.status == 200
    assert json.loads(payload)["state"] == "IDLE"
    assert gateway.status_calls == 1


def test_water_accepts_only_an_empty_json_object() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        accepted, accepted_body = json_request(address, "POST", "/api/water", {})
        rejected, rejected_body = json_request(
            address,
            "POST",
            "/api/water",
            {"duration_sec": 180},
        )

    assert accepted.status == 202
    assert accepted_body["duration_sec"] == 10
    assert rejected.status == 400
    assert rejected_body == {"error": "request_body_must_be_empty_object"}
    assert gateway.water_calls == 1


def test_water_rejects_a_foreign_browser_origin_before_side_effect() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        response, payload = json_request(
            address,
            "POST",
            "/api/water",
            {},
            origin="https://attacker.example",
        )

    assert response.status == 403
    assert payload == {"error": "origin_not_allowed"}
    assert gateway.water_calls == 0
    assert response.getheader("Access-Control-Allow-Origin") is None


def test_non_browser_client_without_origin_can_water() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        response, _ = json_request(
            address,
            "POST",
            "/api/water",
            {},
            origin=None,
        )

    assert response.status == 202
    assert gateway.water_calls == 1


def test_simple_cross_site_form_content_type_is_rejected() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        response, payload = request(
            address,
            "POST",
            "/api/water",
            body=b"duration_sec=180",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status == 415
    assert json.loads(payload) == {"error": "json_content_type_required"}
    assert gateway.water_calls == 0


def test_stop_is_forwarded_without_rate_limit() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        first, _ = json_request(address, "POST", "/api/stop", {})
        second, _ = json_request(address, "POST", "/api/stop", {})

    assert first.status == 200
    assert second.status == 200
    assert gateway.stop_calls == 2


def test_health_does_not_depend_on_device_and_unknown_routes_are_json() -> None:
    gateway = FakeGateway()
    with running_server(gateway) as address:
        health, health_body = request(address, "GET", "/healthz")
        missing, missing_body = request(address, "GET", "/missing")

    assert health.status == 200
    assert json.loads(health_body) == {"ok": True, "service": "tree-public-gateway"}
    assert missing.status == 404
    assert json.loads(missing_body) == {"error": "not_found"}
    assert gateway.status_calls == 0


def test_partial_request_body_times_out_and_server_recovers() -> None:
    gateway = FakeGateway()
    with running_server(gateway, request_timeout_sec=0.1) as address:
        client = socket.create_connection(address, timeout=2)
        client.settimeout(2)
        client.sendall(
            b"POST /api/water HTTP/1.1\r\n"
            b"Host: tree.example.com\r\n"
            b"Origin: https://tree.example.com\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 2\r\n"
            b"Connection: close\r\n\r\n"
            b"{"
        )
        timed_out = HTTPResponse(client)
        timed_out.begin()
        timeout_payload = json.loads(timed_out.read())
        client.close()

        recovered, recovered_payload = request(address, "GET", "/api/status")

    assert timed_out.status == 408
    assert timeout_payload == {"error": "request_timeout"}
    assert recovered.status == 200
    assert json.loads(recovered_payload)["state"] == "IDLE"
    assert gateway.water_calls == 0


def test_slow_trickle_request_cannot_monopolize_only_handler_slot() -> None:
    gateway = FakeGateway()
    stop_trickle = threading.Event()
    trickle_thread: threading.Thread | None = None
    client: socket.socket | None = None

    with running_server(
        gateway,
        request_timeout_sec=0.1,
        max_active_requests=1,
    ) as address:
        client = socket.create_connection(address, timeout=2)

        def trickle() -> None:
            assert client is not None
            try:
                while not stop_trickle.is_set():
                    client.sendall(b"G")
                    time.sleep(0.03)
            except OSError:
                pass

        trickle_thread = threading.Thread(target=trickle)
        trickle_thread.start()
        try:
            time.sleep(0.3)
            recovered, recovered_payload = request(address, "GET", "/healthz")
        finally:
            stop_trickle.set()
            client.close()
            trickle_thread.join(timeout=2)

    assert recovered.status == 200
    assert json.loads(recovered_payload) == {
        "ok": True,
        "service": "tree-public-gateway",
    }


def test_client_reset_during_request_body_is_silent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gateway = FakeGateway()
    with running_server(
        gateway,
        request_timeout_sec=0.1,
        max_active_requests=1,
    ) as address:
        client = socket.create_connection(address, timeout=2)
        client.sendall(
            b"POST /api/water HTTP/1.1\r\n"
            b"Host: tree.example.com\r\n"
            b"Origin: https://tree.example.com\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 2\r\n"
            b"Connection: close\r\n\r\n"
            b"{"
        )
        client.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_LINGER,
            struct.pack("ii", 1, 0),
        )
        client.close()

        deadline = time.monotonic() + 2
        while True:
            recovered, _ = request(address, "GET", "/api/status")
            if recovered.status == 200:
                break
            assert recovered.status == 503
            if time.monotonic() >= deadline:
                pytest.fail("request slot was not released after client reset")
            time.sleep(0.01)

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "ConnectionResetError" not in captured.err
    assert gateway.water_calls == 0


def test_concurrency_limit_rejects_excess_handlers() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingGateway(FakeGateway):
        def status(self) -> GatewayReply:
            entered.set()
            assert release.wait(timeout=2)
            return super().status()

    gateway = BlockingGateway()
    first_result: list[tuple[HTTPResponse, bytes]] = []
    with running_server(gateway, max_active_requests=1) as address:
        first = threading.Thread(
            target=lambda: first_result.append(request(address, "GET", "/api/status"))
        )
        first.start()
        assert entered.wait(timeout=1)
        try:
            overloaded, overloaded_payload = request(address, "GET", "/api/status")
        finally:
            release.set()
            first.join(timeout=2)

    assert overloaded.status == 503
    assert json.loads(overloaded_payload) == {"error": "server_busy"}
    assert first_result[0][0].status == 200


def test_handler_hides_unexpected_internal_error_details() -> None:
    class ExplodingGateway(FakeGateway):
        def water(self) -> GatewayReply:
            raise RuntimeError("database path and private detail")

    with running_server(ExplodingGateway()) as address:
        response, payload = json_request(address, "POST", "/api/water", {})

    assert response.status == 503
    assert payload == {"error": "gateway_unavailable"}
    assert "private" not in str(payload)


@pytest.mark.parametrize("request_timeout_sec", [float("nan"), float("inf")])
def test_server_rejects_non_finite_request_timeouts(request_timeout_sec: float) -> None:
    server = None
    try:
        with pytest.raises(ValueError, match="finite and positive"):
            server = create_server(
                ("127.0.0.1", 0),
                gateway=FakeGateway(),  # type: ignore[arg-type]
                public_origin="https://tree.example.com",
                request_timeout_sec=request_timeout_sec,
            )
    finally:
        if server is not None:
            server.server_close()


@pytest.mark.parametrize("max_active_requests", [True, 1.5])
def test_server_rejects_non_integral_concurrency_limits(
    max_active_requests: object,
) -> None:
    server = None
    try:
        with pytest.raises(ValueError, match="positive integer"):
            server = create_server(
                ("127.0.0.1", 0),
                gateway=FakeGateway(),  # type: ignore[arg-type]
                public_origin="https://tree.example.com",
                max_active_requests=max_active_requests,  # type: ignore[arg-type]
            )
    finally:
        if server is not None:
            server.server_close()


def test_create_server_rejects_non_loopback_bind() -> None:
    server = None
    try:
        with pytest.raises(ValueError, match="loopback"):
            server = create_server(
                ("0.0.0.0", 0),
                gateway=FakeGateway(),  # type: ignore[arg-type]
                public_origin="https://tree.example.com",
            )
    finally:
        if server is not None:
            server.server_close()
