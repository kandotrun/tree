from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar


class FakeAtomHandler(BaseHTTPRequestHandler):
    water_bodies: ClassVar[list[dict[str, object]]] = []

    def _send(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/v1/status":
            self._send(
                200,
                {
                    "state": "IDLE",
                    "pump": False,
                    "armed": True,
                    "remaining_ms": 0,
                    "moisture_adc": 1510,
                    "firmware_version": "0.4.1",
                },
            )
            return
        if self.path == "/healthz":
            self._send(200, {"ok": True, "device": "fake-atom"})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        if self.path == "/v1/water":
            type(self).water_bodies.append(body)
            self._send(
                202,
                {
                    "accepted": True,
                    "request_id": body["request_id"],
                    "state": "WATERING",
                },
            )
            return
        if self.path == "/v1/stop":
            self._send(200, {"stopped": True, "state": "IDLE"})
            return
        self._send(404, {"error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def fake_atom() -> Iterator[tuple[str, type[FakeAtomHandler]]]:
    handler = type("E2EFakeAtomHandler", (FakeAtomHandler,), {})
    handler.water_bodies = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def reserve_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def http_json(
    port: int,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    encoded = None if body is None else json.dumps(body).encode()
    headers = (
        {}
        if encoded is None
        else {
            "Content-Type": "application/json",
            "Origin": "https://tree.2-38.com",
        }
    )
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def test_public_gateway_runs_as_a_real_process_and_forwards_fixed_duration(
    tmp_path: Path,
) -> None:
    with fake_atom() as (atom_url, atom_handler):
        port = reserve_port()
        env = os.environ.copy()
        env.update(
            {
                "ATOM_URL": atom_url,
                "PUBLIC_DATABASE_PATH": str(tmp_path / "public.db"),
                "PUBLIC_ORIGIN": "https://tree.2-38.com",
                "PUBLIC_LISTEN_HOST": "127.0.0.1",
                "PUBLIC_LISTEN_PORT": str(port),
                "PYTHONUNBUFFERED": "1",
            }
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "balcony_watering.public_main"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            for _ in range(50):
                if process.poll() is not None:
                    break
                try:
                    status, _ = http_json(port, "GET", "/healthz")
                    if status == 200:
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise AssertionError("public gateway did not become ready")

            assert process.poll() is None
            status_code, status = http_json(port, "GET", "/api/status")
            water_code, water = http_json(port, "POST", "/api/water", {})

            assert status_code == 200
            assert status["state"] == "IDLE"
            assert water_code == 202
            assert water["duration_sec"] == 10
            assert len(atom_handler.water_bodies) == 1
            assert atom_handler.water_bodies[0]["duration_sec"] == 10
            assert set(atom_handler.water_bodies[0]) == {"request_id", "duration_sec"}
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

        if process.returncode not in {0, -15}:
            stdout, stderr = process.communicate()
            raise AssertionError(f"gateway failed: stdout={stdout!r} stderr={stderr!r}")
