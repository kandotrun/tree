from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from balcony_watering.atom_client import (
    AtomClient,
    AtomConnectionError,
    AtomHTTPError,
    AtomProtocolError,
)


class FakeAtomHandler(BaseHTTPRequestHandler):
    observed_requests: ClassVar[list[dict[str, object]]] = []
    route_responses: ClassVar[dict[tuple[str, str], tuple[int, bytes]]] = {}

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        type(self).observed_requests.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        status, payload = type(self).route_responses.get(
            (self.command, self.path),
            (404, b'{"error":"not_found"}'),
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def fake_atom() -> Iterator[tuple[str, type[FakeAtomHandler]]]:
    handler = type("IsolatedFakeAtomHandler", (FakeAtomHandler,), {})
    handler.observed_requests = []
    handler.route_responses = {
        ("GET", "/healthz"): (200, b'{"ok":true,"device":"balcony-watering"}'),
        ("GET", "/v1/status"): (200, b'{"state":"IDLE","pump":false}'),
        ("POST", "/v1/water"): (
            202,
            b'{"accepted":true,"request_id":"request-1","state":"WATERING"}',
        ),
        ("POST", "/v1/stop"): (200, b'{"stopped":true,"state":"COOLDOWN"}'),
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def make_client(base_url: str) -> AtomClient:
    return AtomClient(
        base_url,
        connect_timeout_sec=1,
        request_timeout_sec=2,
    )


def test_health_is_read_without_authorization(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom

    result = make_client(base_url).health()

    assert result["ok"] is True
    assert handler.observed_requests[-1]["authorization"] is None


def test_status_is_read_without_authorization(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom

    result = make_client(base_url).status()

    assert result["state"] == "IDLE"
    assert handler.observed_requests[-1]["authorization"] is None


def test_status_accepts_empty_last_stop_reason_emitted_before_first_completion(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom
    handler.route_responses[("GET", "/v1/status")] = (
        200,
        b'{"state":"IDLE","pump":false,"last_stop_reason":""}',
    )

    result = make_client(base_url).status()

    assert result["last_stop_reason"] == ""


def test_status_omits_unknown_fields_and_rejects_invalid_state(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom
    secret = "t" * 32
    status_payload = {
        "state": "IDLE",
        "pump": False,
        "debug": secret,
        "uptime_ms": 123,
        "remaining_ms": 600_000,
    }
    handler.route_responses[("GET", "/v1/status")] = (
        200,
        json.dumps(status_payload).encode(),
    )

    result = make_client(base_url).status()

    assert result == {
        "state": "IDLE",
        "pump": False,
        "uptime_ms": 123,
        "remaining_ms": 600_000,
    }
    handler.route_responses[("GET", "/v1/status")] = (
        200,
        json.dumps({"state": secret, "pump": False}).encode(),
    )
    with pytest.raises(AtomProtocolError, match="status state"):
        make_client(base_url).status()


def test_water_sends_only_request_id_when_duration_is_omitted(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom

    result = make_client(base_url).water("request-1")

    assert result["accepted"] is True
    request = handler.observed_requests[-1]
    body = request["body"]
    assert isinstance(body, bytes)
    assert json.loads(body) == {"request_id": "request-1"}
    assert request["authorization"] is None


def test_water_sends_a_bounded_duration_for_each_request(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom

    result = make_client(base_url).water("request-variable", duration_sec=120)

    assert result["accepted"] is True
    request = handler.observed_requests[-1]
    body = request["body"]
    assert isinstance(body, bytes)
    assert json.loads(body) == {
        "request_id": "request-variable",
        "duration_sec": 120,
    }


@pytest.mark.parametrize("duration_sec", [0, 181, True, 1.5, "10"])
def test_water_rejects_an_invalid_duration_before_network_access(
    fake_atom: tuple[str, type[FakeAtomHandler]],
    duration_sec: object,
) -> None:
    base_url, handler = fake_atom

    with pytest.raises(ValueError, match="duration_sec"):
        make_client(base_url).water("request-invalid", duration_sec=duration_sec)  # type: ignore[arg-type]

    assert handler.observed_requests == []


def test_stop_is_sent_without_authorization(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom
    handler.route_responses[("POST", "/v1/stop")] = (
        200,
        json.dumps({"stopped": True, "state": "COOLDOWN", "debug": "t" * 32}).encode(),
    )

    result = make_client(base_url).stop()

    assert result == {"stopped": True, "state": "COOLDOWN"}
    assert handler.observed_requests[-1]["authorization"] is None


def test_http_rejection_preserves_status_and_payload(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom
    handler.route_responses[("POST", "/v1/water")] = (
        429,
        b'{"error":"cooldown","state":"COOLDOWN"}',
    )

    with pytest.raises(AtomHTTPError) as captured:
        make_client(base_url).water("request-1")

    assert captured.value.status == 429
    assert captured.value.payload["error"] == "cooldown"


def test_untrusted_error_code_is_not_copied_into_exception_text(
    fake_atom: tuple[str, type[FakeAtomHandler]],
) -> None:
    base_url, handler = fake_atom
    secret = "t" * 32
    handler.route_responses[("POST", "/v1/water")] = (
        400,
        json.dumps({"error": secret}).encode(),
    )

    with pytest.raises(AtomHTTPError) as captured:
        make_client(base_url).water("request-1")

    assert secret not in str(captured.value)
    assert captured.value.code == "unexpected_response"


def test_malformed_json_is_a_protocol_error(fake_atom: tuple[str, type[FakeAtomHandler]]) -> None:
    base_url, handler = fake_atom
    handler.route_responses[("GET", "/v1/status")] = (200, b"not-json")

    with pytest.raises(AtomProtocolError, match="valid JSON"):
        make_client(base_url).status()


def test_connection_failure_is_reported_without_os_error_details() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        unused_tcp_port = probe.getsockname()[1]

    client = make_client(f"http://127.0.0.1:{unused_tcp_port}")

    with pytest.raises(AtomConnectionError) as captured:
        client.health()

    message = str(captured.value)
    assert message.startswith("ATOM network exchange failed (")
    assert "127.0.0.1" not in message


@pytest.mark.parametrize(
    "resolved_address",
    ["8.8.8.8", "192.0.2.1", "198.18.0.1", "255.255.255.255", "0.0.0.0"],
)
def test_public_or_special_dns_resolution_is_rejected_before_network_access(
    monkeypatch: pytest.MonkeyPatch,
    resolved_address: str,
) -> None:
    def unsafe_resolution(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved_address, 80))]

    monkeypatch.setattr(socket, "getaddrinfo", unsafe_resolution)
    client = make_client("http://watering-host")

    with pytest.raises(AtomProtocolError, match="private or local"):
        client.status()
