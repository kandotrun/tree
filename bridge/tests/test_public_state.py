from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import TracebackType

import pytest

import balcony_watering.public_state as state_module
from balcony_watering.public_state import PublicActionStore, PublicLimits


def limits(**overrides: int) -> PublicLimits:
    values = {
        "duration_sec": 10,
        "cooldown_sec": 60,
        "hourly_limit": 6,
        "daily_limit": 24,
    }
    values.update(overrides)
    return PublicLimits(**values)


def test_first_reservation_is_accepted_and_cooldown_is_global(tmp_path: Path) -> None:
    store = PublicActionStore(tmp_path / "public.db")

    first = store.reserve("pub-first", now_ms=1_000_000, limits=limits())
    blocked = store.reserve("pub-second", now_ms=1_059_000, limits=limits())
    next_one = store.reserve("pub-third", now_ms=1_060_000, limits=limits())

    assert first.accepted is True
    assert first.hourly_used == 1
    assert first.daily_used == 1
    assert blocked.accepted is False
    assert blocked.reason == "cooldown"
    assert blocked.retry_after_sec == 1
    assert next_one.accepted is True


def test_parallel_reservations_allow_exactly_one_request(tmp_path: Path) -> None:
    store = PublicActionStore(tmp_path / "public.db")
    barrier = Barrier(8)

    def reserve(index: int) -> bool:
        barrier.wait()
        return store.reserve(
            f"pub-{index}",
            now_ms=2_000_000,
            limits=limits(),
        ).accepted

    with ThreadPoolExecutor(max_workers=8) as executor:
        accepted = list(executor.map(reserve, range(8)))

    assert accepted.count(True) == 1
    assert accepted.count(False) == 7


def test_hourly_limit_uses_a_rolling_window(tmp_path: Path) -> None:
    store = PublicActionStore(tmp_path / "public.db")
    policy = limits(cooldown_sec=60, hourly_limit=3)
    start = 10_000_000
    for index in range(3):
        result = store.reserve(
            f"pub-{index}",
            now_ms=start + index * 60_000,
            limits=policy,
        )
        assert result.accepted is True
        store.set_outcome(f"pub-{index}", "ACCEPTED")

    blocked = store.reserve("pub-blocked", now_ms=start + 180_000, limits=policy)
    after_window = store.reserve(
        "pub-after-window",
        now_ms=start + 3_600_001,
        limits=policy,
    )

    assert blocked.accepted is False
    assert blocked.reason == "hourly_limit"
    assert blocked.retry_after_sec > 0
    assert after_window.accepted is True


def test_daily_limit_uses_a_rolling_window(tmp_path: Path) -> None:
    store = PublicActionStore(tmp_path / "public.db")
    policy = limits(cooldown_sec=60, hourly_limit=3, daily_limit=3)
    start = 20_000_000
    for index in range(3):
        result = store.reserve(
            f"pub-{index}",
            now_ms=start + index * 3_600_001,
            limits=policy,
        )
        assert result.accepted is True
        store.set_outcome(f"pub-{index}", "ACCEPTED")

    blocked = store.reserve(
        "pub-blocked",
        now_ms=start + 3 * 3_600_001,
        limits=policy,
    )
    after_window = store.reserve(
        "pub-after-window",
        now_ms=start + 86_400_001,
        limits=policy,
    )

    assert blocked.accepted is False
    assert blocked.reason == "daily_limit"
    assert blocked.retry_after_sec > 0
    assert after_window.accepted is True


def test_definitive_rejection_does_not_consume_public_quota(tmp_path: Path) -> None:
    store = PublicActionStore(tmp_path / "public.db")
    policy = limits()

    assert store.reserve("pub-rejected", now_ms=1_000, limits=policy).accepted
    store.set_outcome("pub-rejected", "REJECTED")
    replacement = store.reserve("pub-replacement", now_ms=1_001, limits=policy)

    assert replacement.accepted is True
    assert store.get_outcome("pub-rejected") == "REJECTED"


def test_unknown_result_remains_counted_for_safety(tmp_path: Path) -> None:
    store = PublicActionStore(tmp_path / "public.db")
    policy = limits()

    assert store.reserve("pub-unknown", now_ms=5_000, limits=policy).accepted
    store.set_outcome("pub-unknown", "UNKNOWN")
    blocked = store.reserve("pub-next", now_ms=5_001, limits=policy)

    assert blocked.accepted is False
    assert blocked.reason == "cooldown"
    assert store.get_outcome("pub-unknown") == "UNKNOWN"


def test_usage_reports_the_longest_active_blocker(tmp_path: Path) -> None:
    store = PublicActionStore(tmp_path / "public.db")
    policy = limits(cooldown_sec=60, hourly_limit=2, daily_limit=2)
    start = 100_000_000
    for index, offset in enumerate((0, 3_600_001)):
        request_id = f"pub-{index}"
        assert store.reserve(request_id, now_ms=start + offset, limits=policy).accepted
        store.set_outcome(request_id, "ACCEPTED")

    usage = store.usage(now_ms=start + 3_600_002, limits=policy)

    assert usage.hourly_used == 1
    assert usage.daily_used == 2
    assert usage.reason == "daily_limit"
    assert usage.retry_after_sec > 0


def test_store_closes_every_sqlite_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = state_module.sqlite3.connect

    class TrackingConnection:
        def __init__(self, database: str | Path, timeout: float) -> None:
            self.connection = real_connect(database, timeout=timeout)
            self.closed = False

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

        def __enter__(self) -> TrackingConnection:
            self.connection.__enter__()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return self.connection.__exit__(exc_type, exc, traceback)

        def close(self) -> None:
            self.closed = True
            self.connection.close()

    opened: list[TrackingConnection] = []

    def tracking_connect(database: str | Path, timeout: float = 5.0) -> TrackingConnection:
        connection = TrackingConnection(database, timeout)
        opened.append(connection)
        return connection

    monkeypatch.setattr(state_module.sqlite3, "connect", tracking_connect)
    store = PublicActionStore(tmp_path / "public.db")
    store.usage(now_ms=1_000, limits=limits())

    assert opened
    assert all(connection.closed for connection in opened)


def test_limits_reject_a_weaker_public_safety_policy() -> None:
    for changes in (
        {"duration_sec": 11},
        {"cooldown_sec": 59},
        {"hourly_limit": 7, "daily_limit": 7},
        {"daily_limit": 25},
    ):
        values = {
            "duration_sec": 10,
            "cooldown_sec": 60,
            "hourly_limit": 6,
            "daily_limit": 24,
        }
        values.update(changes)

        with pytest.raises(ValueError):
            PublicLimits(**values)
