from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlsplit

from .network_policy import is_allowed_local_address


class AtomError(RuntimeError):
    """Base error for ATOM communication."""


class AtomConnectionError(AtomError):
    """The bridge could not complete the network exchange."""


class AtomProtocolError(AtomError):
    """The ATOM returned a response that violated the API contract."""


_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_DURATION_SEC = 180
_VALID_STATES = frozenset({"BOOT_GUARD", "IDLE", "WATERING", "COOLDOWN", "ERROR"})
_STATUS_INTEGER_FIELDS = {
    "uptime_ms": (0, 0xFFFFFFFF),
    "wifi_rssi": (-127, 0),
    "moisture_adc": (0, 4095),
    "remaining_ms": (0, 0xFFFFFFFF),
    "last_runtime_ms": (0, 0xFFFFFFFF),
}


class AtomHTTPError(AtomError):
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload
        raw_code = payload.get("error")
        self.code = (
            raw_code
            if isinstance(raw_code, str) and _ERROR_CODE_RE.fullmatch(raw_code)
            else "unexpected_response"
        )
        super().__init__(f"ATOM returned HTTP {status}: {self.code}")


class AtomClient:
    _MAX_RESPONSE_BYTES = 64 * 1024

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        connect_timeout_sec: float,
        request_timeout_sec: float,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("base_url must be an HTTP origin")
        self._host = parsed.hostname
        self._port = parsed.port or 80
        display_host = f"[{self._host}]" if ":" in self._host else self._host
        self._host_header = display_host if self._port == 80 else f"{display_host}:{self._port}"
        self._token = api_token
        self._connect_timeout_sec = connect_timeout_sec
        self._request_timeout_sec = request_timeout_sec

    def _resolve_local_endpoint(self) -> str:
        try:
            addresses = socket.getaddrinfo(
                self._host,
                self._port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise AtomConnectionError("ATOM hostname resolution failed") from exc
        if not addresses:
            raise AtomConnectionError("ATOM hostname did not resolve")

        resolved: list[str] = []
        for address_info in addresses:
            raw_address = str(address_info[4][0])
            address_without_scope = raw_address.split("%", 1)[0]
            try:
                address = ipaddress.ip_address(address_without_scope)
            except ValueError as exc:
                raise AtomProtocolError("ATOM resolved to an invalid IP address") from exc
            if not is_allowed_local_address(address):
                raise AtomProtocolError("ATOM must resolve only to a private or local IP address")
            resolved.append(raw_address)
        return resolved[0]

    @staticmethod
    def _decode_json(raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AtomProtocolError("ATOM response was not valid JSON") from exc
        if not isinstance(value, dict):
            raise AtomProtocolError("ATOM response JSON must be an object")
        return value

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        authenticated: bool,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "balcony-watering-bridge/0.1.0",
            "Connection": "close",
            "Host": self._host_header,
        }
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        resolved_host = self._resolve_local_endpoint()
        connection = http.client.HTTPConnection(
            resolved_host,
            self._port,
            timeout=self._connect_timeout_sec,
        )
        try:
            connection.connect()
            if connection.sock is not None:
                connection.sock.settimeout(self._request_timeout_sec)
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(self._MAX_RESPONSE_BYTES + 1)
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise AtomConnectionError(
                f"ATOM network exchange failed ({type(exc).__name__})"
            ) from exc
        finally:
            connection.close()

        if len(raw) > self._MAX_RESPONSE_BYTES:
            raise AtomProtocolError("ATOM response exceeded the 64 KiB safety limit")

        if response.status != expected_status:
            try:
                error_payload = self._decode_json(raw)
            except AtomProtocolError:
                error_payload = {"error": "invalid_json_response"}
            raise AtomHTTPError(response.status, error_payload)
        return self._decode_json(raw)

    def health(self) -> dict[str, Any]:
        return self._request(
            "GET",
            "/healthz",
            expected_status=200,
            authenticated=False,
        )

    def status(self) -> dict[str, Any]:
        payload = self._request(
            "GET",
            "/v1/status",
            expected_status=200,
            authenticated=True,
        )
        state = payload.get("state")
        pump = payload.get("pump")
        if not isinstance(state, str) or state not in _VALID_STATES:
            raise AtomProtocolError("ATOM status state was invalid")
        if type(pump) is not bool:
            raise AtomProtocolError("ATOM status pump flag was invalid")

        sanitized: dict[str, Any] = {"state": state, "pump": pump}
        for field, (minimum, maximum) in _STATUS_INTEGER_FIELDS.items():
            if field not in payload:
                continue
            value = payload[field]
            if type(value) is not int or not minimum <= value <= maximum:
                raise AtomProtocolError(f"ATOM status {field} was invalid")
            sanitized[field] = value

        if "last_request_id" in payload:
            request_id = payload["last_request_id"]
            valid_request_id = request_id == "" or (
                isinstance(request_id, str)
                and _REQUEST_ID_RE.fullmatch(request_id) is not None
                and request_id != self._token
            )
            if not valid_request_id:
                raise AtomProtocolError("ATOM status last_request_id was invalid")
            sanitized["last_request_id"] = request_id

        for field in ("last_stop_reason", "error_reason", "firmware_version"):
            if field not in payload:
                continue
            value = payload[field]
            if (
                not isinstance(value, str)
                or len(value) > 31
                or not value.isascii()
                or not value.isprintable()
                or value == self._token
            ):
                raise AtomProtocolError(f"ATOM status {field} was invalid")
            sanitized[field] = value
        return sanitized

    def water(
        self,
        request_id: str,
        *,
        duration_sec: int | None = None,
    ) -> dict[str, Any]:
        if not request_id:
            raise ValueError("request_id must not be empty")
        payload: dict[str, Any] = {"request_id": request_id}
        if duration_sec is not None:
            if type(duration_sec) is not int or not 1 <= duration_sec <= _MAX_DURATION_SEC:
                raise ValueError("duration_sec must be an integer from 1 through 180")
            payload["duration_sec"] = duration_sec
        return self._request(
            "POST",
            "/v1/water",
            expected_status=202,
            authenticated=True,
            payload=payload,
        )

    def stop(self) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/v1/stop",
            expected_status=200,
            authenticated=True,
            payload={},
        )
        stopped = payload.get("stopped")
        state = payload.get("state")
        if stopped is not True:
            raise AtomProtocolError("ATOM stop acknowledgement was invalid")
        if not isinstance(state, str) or state not in _VALID_STATES:
            raise AtomProtocolError("ATOM stop state was invalid")
        return {"stopped": True, "state": state}
