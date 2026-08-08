from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from balcony_watering.moisture_logger import (
    LoggerSettings,
    MoistureSample,
    MoistureStore,
    collect_once,
    load_logger_settings,
    main,
    run_logger,
)


class _StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path != "/v1/status":
            self.send_error(404)
            return
        body = json.dumps(
            {
                "state": "IDLE",
                "pump": False,
                "uptime_ms": 123_456,
                "wifi_rssi": -61,
                "moisture_adc": 1681,
                "armed": True,
                "last_request_id": "web-example",
                "last_runtime_ms": 180_000,
                "last_stop_reason": "DOSE_COMPLETE",
                "firmware_version": "0.4.1",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_status_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_collect_once_records_status_from_real_http_server(tmp_path: Path) -> None:
    server, thread = _start_status_server()
    store = MoistureStore(tmp_path / "moisture.db")
    try:
        sample = collect_once(
            f"http://127.0.0.1:{server.server_port}",
            store,
            observed_at_ms=1_786_214_400_000,
            timeout_sec=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert sample.online is True
    assert sample.moisture_adc == 1681
    assert sample.state == "IDLE"
    assert sample.pump is False
    assert sample.last_runtime_ms == 180_000
    assert store.latest(1) == [sample]


def test_collect_once_records_connection_failure(tmp_path: Path) -> None:
    store = MoistureStore(tmp_path / "moisture.db")

    sample = collect_once(
        "http://127.0.0.1:1",
        store,
        observed_at_ms=1_786_214_410_000,
        timeout_sec=0.1,
    )

    assert sample.online is False
    assert sample.moisture_adc is None
    assert sample.error is not None
    assert store.latest(1) == [sample]


def test_prune_removes_only_samples_older_than_cutoff(tmp_path: Path) -> None:
    server, thread = _start_status_server()
    store = MoistureStore(tmp_path / "moisture.db")
    try:
        for observed_at_ms in (1_000, 2_000, 3_000):
            collect_once(
                f"http://127.0.0.1:{server.server_port}",
                store,
                observed_at_ms=observed_at_ms,
                timeout_sec=1,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert store.prune(before_ms=2_000) == 1
    assert [sample.observed_at_ms for sample in store.latest(10)] == [3_000, 2_000]


def test_load_logger_settings_reads_bounded_environment(tmp_path: Path) -> None:
    settings = load_logger_settings(
        {
            "ATOM_URL": "http://127.0.0.1",
            "MOISTURE_DATABASE_PATH": str(tmp_path / "samples.db"),
            "MOISTURE_INTERVAL_SEC": "10",
            "MOISTURE_RETENTION_DAYS": "90",
            "MOISTURE_TIMEOUT_SEC": "2",
        }
    )

    assert settings == LoggerSettings(
        atom_url="http://127.0.0.1",
        database_path=tmp_path / "samples.db",
        interval_sec=10,
        retention_days=90,
        timeout_sec=2.0,
    )


def test_run_logger_collects_requested_sample_count(tmp_path: Path) -> None:
    server, thread = _start_status_server()
    database_path = tmp_path / "samples.db"
    settings = LoggerSettings(
        atom_url=f"http://127.0.0.1:{server.server_port}",
        database_path=database_path,
        interval_sec=10,
        retention_days=90,
        timeout_sec=1,
    )
    timestamps = iter((10_000, 20_000))
    sleeps: list[float] = []
    try:
        count = run_logger(
            settings,
            sample_limit=2,
            now_ms=lambda: next(timestamps),
            sleep=sleeps.append,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert count == 2
    assert [sample.observed_at_ms for sample in MoistureStore(database_path).latest(10)] == [
        20_000,
        10_000,
    ]
    assert sleeps == [10]


def test_run_logger_reapplies_retention_during_long_uptime(tmp_path: Path) -> None:
    server, thread = _start_status_server()
    database_path = tmp_path / "samples.db"
    store = MoistureStore(database_path)
    store.record(MoistureSample(observed_at_ms=0, online=False, error="old"))
    settings = LoggerSettings(
        atom_url=f"http://127.0.0.1:{server.server_port}",
        database_path=database_path,
        interval_sec=10,
        retention_days=1,
        timeout_sec=1,
    )
    timestamps = iter((86_400_000, 172_800_000))
    try:
        run_logger(
            settings,
            sample_limit=2,
            now_ms=lambda: next(timestamps),
            sleep=lambda _: None,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert [sample.observed_at_ms for sample in MoistureStore(database_path).latest(10)] == [
        172_800_000,
        86_400_000,
    ]


def test_main_once_collects_one_sample(tmp_path: Path) -> None:
    server, thread = _start_status_server()
    database_path = tmp_path / "samples.db"
    try:
        result = main(
            ["--once"],
            {
                "ATOM_URL": f"http://127.0.0.1:{server.server_port}",
                "MOISTURE_DATABASE_PATH": str(database_path),
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result == 0
    assert MoistureStore(database_path).latest(1)[0].online is True
