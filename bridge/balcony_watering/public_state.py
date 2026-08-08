from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_COUNTED_OUTCOMES = ("REQUESTING", "ACCEPTED", "UNKNOWN")
_VALID_OUTCOMES = frozenset((*_COUNTED_OUTCOMES, "REJECTED"))
_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class PublicLimits:
    duration_sec: int
    cooldown_sec: int
    hourly_limit: int
    daily_limit: int

    def __post_init__(self) -> None:
        if self.duration_sec != 10:
            raise ValueError("duration_sec must be exactly 10")
        if not 60 <= self.cooldown_sec <= 3_600:
            raise ValueError("cooldown_sec must be from 60 through 3600")
        if not 1 <= self.hourly_limit <= 6:
            raise ValueError("hourly_limit must be from 1 through 6")
        if not self.hourly_limit <= self.daily_limit <= 24:
            raise ValueError("daily_limit must be from hourly_limit through 24")


@dataclass(frozen=True, slots=True)
class PublicUsage:
    hourly_used: int
    daily_used: int
    retry_after_sec: int
    reason: str | None


@dataclass(frozen=True, slots=True)
class PublicReservation:
    accepted: bool
    hourly_used: int
    daily_used: int
    retry_after_sec: int
    reason: str | None


class PublicActionStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS public_watering_requests (
                    request_id TEXT PRIMARY KEY,
                    requested_at_ms INTEGER NOT NULL CHECK (requested_at_ms >= 0),
                    duration_sec INTEGER NOT NULL CHECK (duration_sec BETWEEN 1 AND 30),
                    outcome TEXT NOT NULL CHECK (
                        outcome IN ('REQUESTING', 'ACCEPTED', 'UNKNOWN', 'REJECTED')
                    )
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS public_watering_requests_time_idx
                ON public_watering_requests (requested_at_ms)
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _counted_clause() -> tuple[str, tuple[str, ...]]:
        placeholders = ",".join("?" for _ in _COUNTED_OUTCOMES)
        return f"outcome IN ({placeholders})", _COUNTED_OUTCOMES

    @classmethod
    def _usage(
        cls,
        connection: sqlite3.Connection,
        *,
        now_ms: int,
        limits: PublicLimits,
    ) -> PublicUsage:
        clause, outcomes = cls._counted_clause()
        hourly_start = now_ms - _HOUR_MS
        daily_start = now_ms - _DAY_MS
        hourly_rows = connection.execute(
            f"""
            SELECT requested_at_ms
            FROM public_watering_requests
            WHERE {clause} AND requested_at_ms > ?
            ORDER BY requested_at_ms
            """,
            (*outcomes, hourly_start),
        ).fetchall()
        daily_rows = connection.execute(
            f"""
            SELECT requested_at_ms
            FROM public_watering_requests
            WHERE {clause} AND requested_at_ms > ?
            ORDER BY requested_at_ms
            """,
            (*outcomes, daily_start),
        ).fetchall()

        blockers: list[tuple[int, str]] = []
        latest_row = connection.execute(
            f"SELECT MAX(requested_at_ms) FROM public_watering_requests WHERE {clause}",
            outcomes,
        ).fetchone()
        latest = latest_row[0] if latest_row is not None else None
        if latest is not None:
            remaining_ms = int(latest) + limits.cooldown_sec * 1_000 - now_ms
            if remaining_ms > 0:
                blockers.append((math.ceil(remaining_ms / 1_000), "cooldown"))

        if len(hourly_rows) >= limits.hourly_limit:
            remaining_ms = int(hourly_rows[0][0]) + _HOUR_MS - now_ms + 1
            blockers.append((max(1, math.ceil(remaining_ms / 1_000)), "hourly_limit"))
        if len(daily_rows) >= limits.daily_limit:
            remaining_ms = int(daily_rows[0][0]) + _DAY_MS - now_ms + 1
            blockers.append((max(1, math.ceil(remaining_ms / 1_000)), "daily_limit"))

        retry_after_sec, reason = max(blockers, default=(0, None))
        return PublicUsage(
            hourly_used=len(hourly_rows),
            daily_used=len(daily_rows),
            retry_after_sec=retry_after_sec,
            reason=reason,
        )

    def reserve(
        self,
        request_id: str,
        *,
        now_ms: int,
        limits: PublicLimits,
    ) -> PublicReservation:
        if not request_id or len(request_id) > 64 or not request_id.isascii():
            raise ValueError("request_id must be non-empty ASCII with at most 64 characters")
        if now_ms < 0:
            raise ValueError("now_ms must not be negative")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            usage = self._usage(connection, now_ms=now_ms, limits=limits)
            if usage.reason is not None:
                return PublicReservation(
                    accepted=False,
                    hourly_used=usage.hourly_used,
                    daily_used=usage.daily_used,
                    retry_after_sec=usage.retry_after_sec,
                    reason=usage.reason,
                )
            connection.execute(
                """
                INSERT INTO public_watering_requests (
                    request_id, requested_at_ms, duration_sec, outcome
                ) VALUES (?, ?, ?, 'REQUESTING')
                """,
                (request_id, now_ms, limits.duration_sec),
            )
            return PublicReservation(
                accepted=True,
                hourly_used=usage.hourly_used + 1,
                daily_used=usage.daily_used + 1,
                retry_after_sec=0,
                reason=None,
            )

    def usage(self, *, now_ms: int, limits: PublicLimits) -> PublicUsage:
        with self._connect() as connection:
            return self._usage(connection, now_ms=now_ms, limits=limits)

    def set_outcome(self, request_id: str, outcome: str) -> None:
        if outcome not in _VALID_OUTCOMES:
            raise ValueError("invalid public watering outcome")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE public_watering_requests SET outcome = ? WHERE request_id = ?",
                (outcome, request_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("public watering request was not found")

    def get_outcome(self, request_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT outcome FROM public_watering_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return None if row is None else str(row[0])
