from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from balcony_watering.atom_client import AtomClient
from balcony_watering.config import Settings
from balcony_watering.service import WateringService
from balcony_watering.state import StateStore


class ContractHandler(BaseHTTPRequestHandler):
    status_calls: ClassVar[int] = 0
    water_requests: ClassVar[list[dict[str, object]]] = []

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(200, {"ok": True, "device": "balcony-watering"})
            return
        if self.path != "/v1/status":
            self._send_json(404, {"error": "not_found"})
            return

        type(self).status_calls += 1
        if type(self).status_calls == 1:
            self._send_json(
                200,
                {
                    "state": "IDLE",
                    "pump": False,
                    "moisture_adc": 1500,
                    "remaining_ms": 0,
                    "last_request_id": "",
                    "last_runtime_ms": 0,
                    "last_stop_reason": "",
                },
            )
            return
        if type(self).status_calls == 2:
            self._send_json(
                200,
                {
                    "state": "WATERING",
                    "pump": True,
                    "moisture_adc": 1450,
                    "last_request_id": "request-1",
                    "last_runtime_ms": 0,
                    "last_stop_reason": "",
                    "remaining_ms": 9_000,
                },
            )
            return
        self._send_json(
            200,
            {
                "state": "COOLDOWN",
                "pump": False,
                "moisture_adc": 1400,
                "last_request_id": "request-1",
                "last_runtime_ms": 10_000,
                "last_stop_reason": "DOSE_COMPLETE",
                "remaining_ms": 600_000,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/water":
            self._send_json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        type(self).water_requests.append(
            {
                "authorization": self.headers.get("Authorization"),
                "body": request,
            }
        )
        self._send_json(
            202,
            {
                "accepted": True,
                "request_id": request["request_id"],
                "state": "WATERING",
                "scheduled_ms": 10_000,
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def test_real_client_and_service_accept_full_firmware_cooldown_contract(tmp_path: Path) -> None:
    handler = type("IsolatedContractHandler", (ContractHandler,), {})
    handler.status_calls = 0
    handler.water_requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        settings = Settings(
            atom_url=f"http://127.0.0.1:{server.server_port}",
            dose_ml=800,
            tank_usable_ml=18_000,
            low_tank_doses=3,
            connect_timeout_sec=1,
            request_timeout_sec=2,
            status_poll_interval_sec=0.01,
            status_poll_timeout_sec=1,
            min_water_interval_hours=72,
            database_path=tmp_path / "state.db",
        )
        store = StateStore(settings.database_path, tank_usable_ml=settings.tank_usable_ml)
        store.initialize()
        client = AtomClient(
            settings.atom_url,
            connect_timeout_sec=settings.connect_timeout_sec,
            request_timeout_sec=settings.request_timeout_sec,
        )
        service = WateringService(
            settings,
            client,
            store,
            request_id_factory=lambda: "request-1",
            now=lambda: datetime(2026, 8, 5, tzinfo=UTC),
        )

        result = service.water()

        assert result["result"] == "SUCCESS"
        assert result["runtime_ms"] == 10_000
        assert result["tank_remaining_ml"] == 17_200
        assert store.get_event("request-1").result == "SUCCESS"
        assert handler.water_requests == [
            {
                "authorization": None,
                "body": {"request_id": "request-1"},
            }
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
