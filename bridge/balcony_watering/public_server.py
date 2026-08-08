from __future__ import annotations

import json
import logging
import math
import socket
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from threading import BoundedSemaphore, Timer
from typing import Any
from urllib.parse import urlsplit

from .public_gateway import GatewayReply, PublicGateway

_LOGGER = logging.getLogger(__name__)
_MAX_REQUEST_BYTES = 1_024
_DEFAULT_REQUEST_TIMEOUT_SEC = 5.0
_DEFAULT_MAX_ACTIVE_REQUESTS = 32
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; base-uri 'none'; connect-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; "
        "object-src 'none'; script-src 'self'; style-src 'self'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_CONTENT_TYPES = {
    "/": "text/html; charset=utf-8",
    "/app.css": "text/css; charset=utf-8",
    "/app.js": "text/javascript; charset=utf-8",
}
_ASSET_NAMES = {
    "/": "index.html",
    "/app.css": "app.css",
    "/app.js": "app.js",
}


class PublicAssetLoadError(RuntimeError):
    """Raised when packaged public assets cannot be loaded."""


def _server_busy_response() -> bytes:
    payload = b'{"error":"server_busy"}'
    headers = {
        "Connection": "close",
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(payload)),
        **_SECURITY_HEADERS,
    }
    head = "HTTP/1.1 503 Service Unavailable\r\n" + "".join(
        f"{name}: {value}\r\n" for name, value in headers.items()
    )
    return head.encode("ascii") + b"\r\n" + payload


class PublicHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        gateway: PublicGateway,
        public_origin: str,
        assets: dict[str, bytes],
        request_timeout_sec: float,
        max_active_requests: int,
    ) -> None:
        if (
            isinstance(request_timeout_sec, bool)
            or not isinstance(request_timeout_sec, (int, float))
            or not math.isfinite(request_timeout_sec)
            or request_timeout_sec <= 0
        ):
            raise ValueError("request_timeout_sec must be finite and positive")
        if type(max_active_requests) is not int or max_active_requests < 1:
            raise ValueError("max_active_requests must be a positive integer")
        self.gateway = gateway
        self.public_origin = public_origin
        self.assets = assets
        self.request_timeout_sec = request_timeout_sec
        self._request_slots = BoundedSemaphore(max_active_requests)
        super().__init__(server_address, handler)

    def get_request(self) -> tuple[socket.socket, Any]:
        request, client_address = super().get_request()
        request.settimeout(self.request_timeout_sec)
        return request, client_address

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            try:
                request.sendall(_server_busy_response())
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class PublicRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tree-public-gateway"
    sys_version = ""

    def handle(self) -> None:
        timer = Timer(
            self.public_server.request_timeout_sec,
            self._expire_request_read,
        )
        timer.daemon = True
        self._request_read_timer: Timer | None = timer
        timer.start()
        try:
            super().handle()
        except ConnectionError:
            self.close_connection = True
        finally:
            self._cancel_request_read_deadline()

    def _expire_request_read(self) -> None:
        self.close_connection = True
        with suppress(OSError):
            self.connection.shutdown(socket.SHUT_RD)

    def _cancel_request_read_deadline(self) -> None:
        timer = self._request_read_timer
        self._request_read_timer = None
        if timer is not None:
            timer.cancel()

    @property
    def public_server(self) -> PublicHTTPServer:
        server = self.server
        if not isinstance(server, PublicHTTPServer):
            raise RuntimeError("invalid public server")
        return server

    def _send(
        self,
        status_code: int,
        payload: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.close_connection = True
        self.send_response(status_code)
        self.send_header("Connection", "close")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        if extra_headers is not None:
            retry_after = extra_headers.get("Retry-After")
            if retry_after is not None and retry_after.isdecimal():
                self.send_header("Retry-After", retry_after)
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(
        self,
        status_code: int,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        self._send(
            status_code,
            payload,
            "application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    def _send_gateway_reply(self, reply: GatewayReply) -> None:
        self._send_json(
            reply.status_code,
            reply.body,
            extra_headers=reply.headers,
        )

    def _path(self) -> str:
        return urlsplit(self.path).path

    def do_GET(self) -> None:
        self._cancel_request_read_deadline()
        path = self._path()
        if path in self.public_server.assets:
            self._send(
                200,
                self.public_server.assets[path],
                _CONTENT_TYPES[path],
            )
            return
        if path == "/healthz":
            self._send_json(200, {"ok": True, "service": "tree-public-gateway"})
            return
        if path == "/api/status":
            self._dispatch(self.public_server.gateway.status)
            return
        self._send_json(404, {"error": "not_found"})

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin == self.public_server.public_origin

    def _read_empty_json_object(self) -> tuple[bool, str | None, int]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return False, "json_content_type_required", 415
        if self.headers.get("Transfer-Encoding") is not None:
            return False, "invalid_request_body", 400
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return False, "invalid_request_body", 400
        if content_length < 0:
            return False, "invalid_request_body", 400
        if content_length > _MAX_REQUEST_BYTES:
            return False, "request_body_too_large", 413
        try:
            raw = self.rfile.read(content_length)
        except TimeoutError:
            return False, "request_timeout", 408
        if len(raw) != content_length:
            return False, "request_timeout", 408
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, "invalid_json", 400
        if not isinstance(body, dict) or body:
            return False, "request_body_must_be_empty_object", 400
        return True, None, 200

    def do_POST(self) -> None:
        path = self._path()
        if path not in {"/api/water", "/api/stop"}:
            self._cancel_request_read_deadline()
            self._send_json(404, {"error": "not_found"})
            return
        if not self._origin_allowed():
            self._cancel_request_read_deadline()
            self._send_json(403, {"error": "origin_not_allowed"})
            return
        try:
            valid, error, status_code = self._read_empty_json_object()
        finally:
            self._cancel_request_read_deadline()
        if not valid:
            self._send_json(status_code, {"error": error})
            return
        operation = (
            self.public_server.gateway.water
            if path == "/api/water"
            else self.public_server.gateway.stop
        )
        self._dispatch(operation)

    def _dispatch(self, operation: Any) -> None:
        try:
            reply = operation()
        except Exception as exc:
            _LOGGER.error("public gateway operation failed (%s)", type(exc).__name__)
            self._send_json(503, {"error": "gateway_unavailable"})
            return
        self._send_gateway_reply(reply)

    def do_OPTIONS(self) -> None:
        self._cancel_request_read_deadline()
        self._send_json(405, {"error": "method_not_allowed"})

    def log_message(self, format: str, *args: object) -> None:
        return


def _load_assets() -> dict[str, bytes]:
    root = files("balcony_watering").joinpath("public")
    return {route: root.joinpath(name).read_bytes() for route, name in _ASSET_NAMES.items()}


def create_server(
    address: tuple[str, int],
    *,
    gateway: PublicGateway,
    public_origin: str,
    request_timeout_sec: float = _DEFAULT_REQUEST_TIMEOUT_SEC,
    max_active_requests: int = _DEFAULT_MAX_ACTIVE_REQUESTS,
) -> PublicHTTPServer:
    host, _ = address
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("public server must bind to a loopback address")
    try:
        assets = _load_assets()
    except OSError as exc:
        raise PublicAssetLoadError("packaged public assets are unavailable") from exc
    server_class = PublicHTTPServer
    if ":" in host:
        server_class = type(
            "IPv6PublicHTTPServer",
            (PublicHTTPServer,),
            {"address_family": socket.AF_INET6},
        )
    return server_class(
        address,
        PublicRequestHandler,
        gateway=gateway,
        public_origin=public_origin,
        assets=assets,
        request_timeout_sec=request_timeout_sec,
        max_active_requests=max_active_requests,
    )
