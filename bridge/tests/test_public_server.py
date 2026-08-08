from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPResponse
from typing import Any

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
def running_server(gateway: Any) -> Iterator[tuple[str, int]]:
    server = create_server(
        ("127.0.0.1", 0),
        gateway=gateway,
        public_origin="https://tree.2-38.com",
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
    origin: str | None = "https://tree.2-38.com",
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


def test_handler_hides_unexpected_internal_error_details() -> None:
    class ExplodingGateway(FakeGateway):
        def water(self) -> GatewayReply:
            raise RuntimeError("database path and private detail")

    with running_server(ExplodingGateway()) as address:
        response, payload = json_request(address, "POST", "/api/water", {})

    assert response.status == 503
    assert payload == {"error": "gateway_unavailable"}
    assert "private" not in str(payload)
