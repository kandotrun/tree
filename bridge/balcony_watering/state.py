from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class StateError(RuntimeError):
    """Raised when local state cannot be read or changed safely."""


class DuplicateRequest(StateError):
    """Raised when a request ID already exists in the local ledger."""


class UnresolvedRequest(StateError):
    """Raised when another command may already have operated the pump."""

    def __init__(self, request_id: str, result: str) -> None:
        self.request_id = request_id
        self.result = result
        super().__init__("an unresolved watering request already exists")


class ScheduleNotDue(StateError):
    """Raised when an atomic schedule reservation sees a recent success."""


@dataclass(frozen=True, slots=True)
class WateringEvent:
    request_id: str
    requested_at: str
    started_at: str | None
    completed_at: str | None
    result: str
    dose_ml: int
    runtime_ms: int | None
    moisture_before: int | None
    moisture_after: int | None
    detail: str | None


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class StateStore:
    def __init__(self, database_path: Path, *, tank_usable_ml: int) -> None:
        self.database_path = Path(database_path)
        self.tank_usable_ml = tank_usable_ml

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS watering_events (
                        request_id TEXT PRIMARY KEY,
                        requested_at TEXT NOT NULL,
                        started_at TEXT NULL,
                        completed_at TEXT NULL,
                        result TEXT NOT NULL CHECK (
                            result IN (
                                'PENDING', 'ACCEPTED', 'SUCCESS',
                                'REJECTED', 'FAILED', 'UNKNOWN'
                            )
                        ),
                        dose_ml INTEGER NOT NULL CHECK (dose_ml > 0),
                        runtime_ms INTEGER NULL CHECK (runtime_ms IS NULL OR runtime_ms >= 0),
                        moisture_before INTEGER NULL,
                        moisture_after INTEGER NULL,
                        detail TEXT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_watering_events_result_requested
                        ON watering_events (result, requested_at DESC);

                    CREATE TABLE IF NOT EXISTS tank_state (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        remaining_ml INTEGER NOT NULL CHECK (remaining_ml >= 0),
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO tank_state (id, remaining_ml, updated_at)
                    VALUES (1, ?, ?)
                    """,
                    (self.tank_usable_ml, utc_now_text()),
                )
                connection.execute(
                    """
                    UPDATE tank_state
                    SET remaining_ml = MIN(remaining_ml, ?), updated_at = ?
                    WHERE id = 1 AND remaining_ml > ?
                    """,
                    (self.tank_usable_ml, utc_now_text(), self.tank_usable_ml),
                )
        except (OSError, sqlite3.Error) as exc:
            raise StateError(f"failed to initialize state database: {exc}") from exc

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> WateringEvent:
        return WateringEvent(
            request_id=row["request_id"],
            requested_at=row["requested_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=row["result"],
            dose_ml=row["dose_ml"],
            runtime_ms=row["runtime_ms"],
            moisture_before=row["moisture_before"],
            moisture_after=row["moisture_after"],
            detail=row["detail"],
        )

    def reserve_request(
        self,
        request_id: str,
        *,
        dose_ml: int,
        requested_at: str,
        moisture_before: int | None = None,
        schedule_success_cutoff: str | None = None,
    ) -> None:
        try:
            with self._immediate_transaction() as connection:
                duplicate = connection.execute(
                    "SELECT 1 FROM watering_events WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if duplicate is not None:
                    raise DuplicateRequest("request_id already exists")

                unresolved = connection.execute(
                    """
                    SELECT request_id, result FROM watering_events
                    WHERE result IN ('PENDING', 'ACCEPTED', 'UNKNOWN')
                    ORDER BY requested_at DESC
                    LIMIT 1
                    """,
                ).fetchone()
                if unresolved is not None:
                    raise UnresolvedRequest(
                        str(unresolved["request_id"]),
                        str(unresolved["result"]),
                    )

                if schedule_success_cutoff is not None:
                    recent_success = connection.execute(
                        """
                        SELECT 1 FROM watering_events
                        WHERE result = 'SUCCESS' AND completed_at > ?
                        LIMIT 1
                        """,
                        (schedule_success_cutoff,),
                    ).fetchone()
                    if recent_success is not None:
                        raise ScheduleNotDue("a successful dose is newer than the schedule cutoff")

                connection.execute(
                    """
                    INSERT INTO watering_events (
                        request_id, requested_at, result, dose_ml, moisture_before
                    ) VALUES (?, ?, 'PENDING', ?, ?)
                    """,
                    (request_id, requested_at, dose_ml, moisture_before),
                )
        except (DuplicateRequest, UnresolvedRequest, ScheduleNotDue):
            raise
        except sqlite3.IntegrityError as exc:
            if "watering_events.request_id" in str(exc):
                raise DuplicateRequest("request_id already exists") from exc
            raise StateError(f"failed to reserve request: {exc}") from exc
        except sqlite3.Error as exc:
            raise StateError(f"failed to reserve request: {exc}") from exc

    def _transition(
        self,
        request_id: str,
        *,
        allowed_from: tuple[str, ...],
        result: str,
        started_at: str | None = None,
        detail: str | None = None,
    ) -> None:
        placeholders = ", ".join("?" for _ in allowed_from)
        parameters: list[object] = [result, detail]
        assignments = "result = ?, detail = ?"
        if started_at is not None:
            assignments += ", started_at = ?"
            parameters.append(started_at)
        parameters.extend((request_id, *allowed_from))
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"""
                    UPDATE watering_events
                    SET {assignments}
                    WHERE request_id = ? AND result IN ({placeholders})
                    """,
                    parameters,
                )
                if cursor.rowcount != 1:
                    raise StateError(
                        f"request {request_id} cannot transition to {result} from its current state"
                    )
        except sqlite3.Error as exc:
            raise StateError(f"failed to update request {request_id}: {exc}") from exc

    def mark_accepted(self, request_id: str, *, started_at: str) -> None:
        self._transition(
            request_id,
            allowed_from=("PENDING",),
            result="ACCEPTED",
            started_at=started_at,
        )

    def mark_rejected(self, request_id: str, *, detail: str) -> None:
        self._transition(
            request_id,
            allowed_from=("PENDING",),
            result="REJECTED",
            detail=detail,
        )

    def mark_failed(self, request_id: str, *, detail: str) -> None:
        self._transition(
            request_id,
            allowed_from=("PENDING",),
            result="FAILED",
            detail=detail,
        )

    def mark_unknown(self, request_id: str, *, detail: str) -> None:
        self._transition(
            request_id,
            allowed_from=("PENDING", "ACCEPTED"),
            result="UNKNOWN",
            detail=detail,
        )

    def complete_success(
        self,
        request_id: str,
        *,
        completed_at: str,
        runtime_ms: int,
        moisture_after: int | None = None,
    ) -> int:
        try:
            with self._immediate_transaction() as connection:
                row = connection.execute(
                    "SELECT result, dose_ml FROM watering_events WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise StateError(f"unknown request_id: {request_id}")
                if row["result"] == "SUCCESS":
                    remaining = connection.execute(
                        "SELECT remaining_ml FROM tank_state WHERE id = 1"
                    ).fetchone()[0]
                    return int(remaining)
                if row["result"] != "ACCEPTED":
                    raise StateError(
                        f"request {request_id} cannot transition to SUCCESS from {row['result']}"
                    )

                connection.execute(
                    """
                    UPDATE tank_state
                    SET remaining_ml = MAX(0, remaining_ml - ?), updated_at = ?
                    WHERE id = 1
                    """,
                    (row["dose_ml"], completed_at),
                )
                connection.execute(
                    """
                    UPDATE watering_events
                    SET result = 'SUCCESS', completed_at = ?, runtime_ms = ?,
                        moisture_after = ?, detail = NULL
                    WHERE request_id = ? AND result = 'ACCEPTED'
                    """,
                    (completed_at, runtime_ms, moisture_after, request_id),
                )
                remaining = connection.execute(
                    "SELECT remaining_ml FROM tank_state WHERE id = 1"
                ).fetchone()[0]
                return int(remaining)
        except StateError:
            raise
        except sqlite3.Error as exc:
            raise StateError(f"failed to complete request {request_id}: {exc}") from exc

    def get_event(self, request_id: str) -> WateringEvent:
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT * FROM watering_events WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StateError(f"failed to read request {request_id}: {exc}") from exc
        if row is None:
            raise StateError(f"unknown request_id: {request_id}")
        return self._event_from_row(row)

    def unresolved_event(self) -> WateringEvent | None:
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    """
                    SELECT * FROM watering_events
                    WHERE result IN ('PENDING', 'ACCEPTED', 'UNKNOWN')
                    ORDER BY requested_at DESC
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.Error as exc:
            raise StateError(f"failed to read unresolved requests: {exc}") from exc
        return None if row is None else self._event_from_row(row)

    def tank_remaining_ml(self) -> int:
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT remaining_ml FROM tank_state WHERE id = 1"
                ).fetchone()
        except sqlite3.Error as exc:
            raise StateError(f"failed to read tank state: {exc}") from exc
        if row is None:
            raise StateError("tank state is not initialized")
        return int(row[0])

    def refill(self, remaining_ml: int | None = None, *, updated_at: str | None = None) -> int:
        target = self.tank_usable_ml if remaining_ml is None else remaining_ml
        if target < 0 or target > self.tank_usable_ml:
            raise StateError("refill amount must be between zero and configured tank capacity")
        timestamp = utc_now_text() if updated_at is None else updated_at
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "UPDATE tank_state SET remaining_ml = ?, updated_at = ? WHERE id = 1",
                    (target, timestamp),
                )
                if cursor.rowcount != 1:
                    raise StateError("tank state is not initialized")
        except sqlite3.Error as exc:
            raise StateError(f"failed to refill tank state: {exc}") from exc
        return target

    def last_success_at(self) -> str | None:
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    """
                    SELECT completed_at FROM watering_events
                    WHERE result = 'SUCCESS'
                    ORDER BY completed_at DESC
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.Error as exc:
            raise StateError(f"failed to read last success: {exc}") from exc
        return None if row is None else str(row[0])
