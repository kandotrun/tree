from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .atom_client import AtomClient, AtomError

_PRUNE_INTERVAL_MS = 86_400_000


@dataclass(frozen=True)
class LoggerSettings:
    atom_url: str
    database_path: Path
    interval_sec: int = 10
    retention_days: int = 90
    timeout_sec: float = 2.0


class LoggerConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MoistureSample:
    observed_at_ms: int
    online: bool
    moisture_adc: int | None = None
    state: str | None = None
    pump: bool | None = None
    uptime_ms: int | None = None
    wifi_rssi: int | None = None
    armed: bool | None = None
    last_request_id: str | None = None
    last_runtime_ms: int | None = None
    last_stop_reason: str | None = None
    firmware_version: str | None = None
    error: str | None = None


class MoistureStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS moisture_samples (
                    observed_at_ms INTEGER PRIMARY KEY,
                    online INTEGER NOT NULL CHECK (online IN (0, 1)),
                    moisture_adc INTEGER,
                    state TEXT,
                    pump INTEGER CHECK (pump IS NULL OR pump IN (0, 1)),
                    uptime_ms INTEGER,
                    wifi_rssi INTEGER,
                    armed INTEGER CHECK (armed IS NULL OR armed IN (0, 1)),
                    last_request_id TEXT,
                    last_runtime_ms INTEGER,
                    last_stop_reason TEXT,
                    firmware_version TEXT,
                    error TEXT
                )
                """
            )
        os.chmod(self._path, 0o600)

    def record(self, sample: MoistureSample) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO moisture_samples (
                    observed_at_ms, online, moisture_adc, state, pump, uptime_ms,
                    wifi_rssi, armed, last_request_id, last_runtime_ms,
                    last_stop_reason, firmware_version, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample.observed_at_ms,
                    int(sample.online),
                    sample.moisture_adc,
                    sample.state,
                    None if sample.pump is None else int(sample.pump),
                    sample.uptime_ms,
                    sample.wifi_rssi,
                    None if sample.armed is None else int(sample.armed),
                    sample.last_request_id,
                    sample.last_runtime_ms,
                    sample.last_stop_reason,
                    sample.firmware_version,
                    sample.error,
                ),
            )

    def latest(self, limit: int) -> list[MoistureSample]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM moisture_samples ORDER BY observed_at_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._sample_from_row(row) for row in rows]

    def prune(self, *, before_ms: int) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM moisture_samples WHERE observed_at_ms < ?",
                (before_ms,),
            )
        return cursor.rowcount

    @staticmethod
    def _sample_from_row(row: sqlite3.Row) -> MoistureSample:
        return MoistureSample(
            observed_at_ms=row["observed_at_ms"],
            online=bool(row["online"]),
            moisture_adc=row["moisture_adc"],
            state=row["state"],
            pump=None if row["pump"] is None else bool(row["pump"]),
            uptime_ms=row["uptime_ms"],
            wifi_rssi=row["wifi_rssi"],
            armed=None if row["armed"] is None else bool(row["armed"]),
            last_request_id=row["last_request_id"],
            last_runtime_ms=row["last_runtime_ms"],
            last_stop_reason=row["last_stop_reason"],
            firmware_version=row["firmware_version"],
            error=row["error"],
        )


def collect_once(
    atom_url: str,
    store: MoistureStore,
    *,
    observed_at_ms: int,
    timeout_sec: float,
) -> MoistureSample:
    client = AtomClient(
        atom_url,
        connect_timeout_sec=timeout_sec,
        request_timeout_sec=timeout_sec,
    )
    try:
        status = client.status()
        sample = MoistureSample(
            observed_at_ms=observed_at_ms,
            online=True,
            moisture_adc=status.get("moisture_adc"),
            state=status["state"],
            pump=status["pump"],
            uptime_ms=status.get("uptime_ms"),
            wifi_rssi=status.get("wifi_rssi"),
            armed=status.get("armed"),
            last_request_id=status.get("last_request_id"),
            last_runtime_ms=status.get("last_runtime_ms"),
            last_stop_reason=status.get("last_stop_reason"),
            firmware_version=status.get("firmware_version"),
        )
    except AtomError as exc:
        sample = MoistureSample(
            observed_at_ms=observed_at_ms,
            online=False,
            error=f"{type(exc).__name__}: {exc}"[:255],
        )
    store.record(sample)
    return sample


def _bounded_int(
    environ: Mapping[str, str],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = environ.get(key, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise LoggerConfigError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise LoggerConfigError(f"{key} must be from {minimum} through {maximum}")
    return value


def _bounded_float(
    environ: Mapping[str, str],
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = environ.get(key, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise LoggerConfigError(f"{key} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise LoggerConfigError(f"{key} must be from {minimum} through {maximum}")
    return value


def load_logger_settings(environ: Mapping[str, str] | None = None) -> LoggerSettings:
    source = os.environ if environ is None else environ
    atom_url = source.get("MOISTURE_ATOM_URL") or source.get("ATOM_URL")
    if not atom_url:
        raise LoggerConfigError("ATOM_URL is required")
    database_path = Path(
        source.get(
            "MOISTURE_DATABASE_PATH",
            "~/.local/share/balcony-watering/moisture.db",
        )
    ).expanduser()
    return LoggerSettings(
        atom_url=atom_url,
        database_path=database_path,
        interval_sec=_bounded_int(source, "MOISTURE_INTERVAL_SEC", 10, 5, 3600),
        retention_days=_bounded_int(source, "MOISTURE_RETENTION_DAYS", 90, 1, 3650),
        timeout_sec=_bounded_float(source, "MOISTURE_TIMEOUT_SEC", 2.0, 0.1, 30.0),
    )


def run_logger(
    settings: LoggerSettings,
    *,
    sample_limit: int | None = None,
    now_ms: Callable[[], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if sample_limit is not None and sample_limit < 1:
        raise ValueError("sample_limit must be positive")
    clock = now_ms or (lambda: time.time_ns() // 1_000_000)
    store = MoistureStore(settings.database_path)
    count = 0
    retention_ms = settings.retention_days * 86_400_000
    next_prune_ms: int | None = None
    while True:
        observed_at_ms = clock()
        if next_prune_ms is None or observed_at_ms >= next_prune_ms:
            store.prune(before_ms=observed_at_ms - retention_ms)
            next_prune_ms = observed_at_ms + _PRUNE_INTERVAL_MS
        collect_once(
            settings.atom_url,
            store,
            observed_at_ms=observed_at_ms,
            timeout_sec=settings.timeout_sec,
        )
        count += 1
        if sample_limit is not None and count >= sample_limit:
            return count
        sleep(settings.interval_sec)


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Record ATOM moisture telemetry to SQLite")
    parser.add_argument("--once", action="store_true", help="collect one sample and exit")
    args = parser.parse_args(argv)
    try:
        settings = load_logger_settings(environ)
        run_logger(settings, sample_limit=1 if args.once else None)
    except LoggerConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
