from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import TracebackType

import pytest

from balcony_watering.state import (
    DuplicateRequest,
    ScheduleNotDue,
    StateError,
    StateStore,
    UnresolvedRequest,
)


def make_store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "watering.db", tank_usable_ml=18_000)
    store.initialize()
    return store


def test_initialize_creates_full_tank_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.tank_remaining_ml() == 18_000

    store.refill(12_000, updated_at="2026-08-05T00:00:00Z")
    store.initialize()

    assert store.tank_remaining_ml() == 12_000


def test_read_operations_close_their_sqlite_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    connection = store._connect()
    close_called = False
    original_close = connection.close

    class TrackingConnection:
        def __enter__(self) -> sqlite3.Connection:
            return connection.__enter__()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return connection.__exit__(exc_type, exc_value, traceback)

        def close(self) -> None:
            nonlocal close_called
            close_called = True
            original_close()

        def __getattr__(self, name: str) -> object:
            return getattr(connection, name)

    tracking_connection = TrackingConnection()
    monkeypatch.setattr(store, "_connect", lambda: tracking_connection)

    assert store.tank_remaining_ml() == 18_000
    assert close_called is True


def test_duplicate_request_id_is_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-1",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
        moisture_before=1500,
    )

    with pytest.raises(DuplicateRequest):
        store.reserve_request(
            "request-1",
            dose_ml=800,
            requested_at="2026-08-05T00:00:01Z",
            moisture_before=1501,
        )


def test_unresolved_request_is_rejected_atomically(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-1",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
    )

    with pytest.raises(UnresolvedRequest) as captured:
        store.reserve_request(
            "request-2",
            dose_ml=800,
            requested_at="2026-08-05T00:00:01Z",
        )

    assert captured.value.request_id == "request-1"
    assert captured.value.result == "PENDING"


def test_concurrent_reservations_create_exactly_one_pending_event(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    def reserve(index: int) -> str:
        try:
            store.reserve_request(
                f"request-{index}",
                dose_ml=800,
                requested_at=f"2026-08-05T00:00:{index:02d}Z",
            )
            return "reserved"
        except UnresolvedRequest:
            return "blocked"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(reserve, range(16)))

    assert outcomes.count("reserved") == 1
    assert outcomes.count("blocked") == 15
    assert store.unresolved_event() is not None


def test_scheduled_reservation_rechecks_last_success_in_transaction(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "manual-request",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
    )
    store.mark_accepted("manual-request", started_at="2026-08-05T00:00:00Z")
    store.complete_success(
        "manual-request",
        completed_at="2026-08-05T00:00:00Z",
        runtime_ms=10_000,
    )

    with pytest.raises(ScheduleNotDue):
        store.reserve_request(
            "scheduled-request",
            dose_ml=800,
            requested_at="2026-08-05T00:00:01Z",
            schedule_success_cutoff="2026-08-02T00:00:01Z",
        )

    assert store.unresolved_event() is None


def test_unresolved_event_blocks_until_definitive_result(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-unknown",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
    )
    store.mark_accepted("request-unknown", started_at="2026-08-05T00:00:01Z")
    store.mark_unknown("request-unknown", detail="connection lost after acceptance")

    event = store.unresolved_event()

    assert event is not None
    assert event.request_id == "request-unknown"
    assert event.result == "UNKNOWN"
    assert store.tank_remaining_ml() == 18_000


def test_rejected_request_does_not_decrement_tank(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-rejected",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
    )
    store.mark_rejected("request-rejected", detail="COOLDOWN")

    assert store.unresolved_event() is None
    assert store.get_event("request-rejected").result == "REJECTED"
    assert store.tank_remaining_ml() == 18_000


def test_success_decrements_tank_exactly_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-success",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
        moisture_before=1500,
    )
    store.mark_accepted("request-success", started_at="2026-08-05T00:00:01Z")

    remaining_first = store.complete_success(
        "request-success",
        completed_at="2026-08-05T00:01:15Z",
        runtime_ms=74_000,
        moisture_after=1400,
    )
    remaining_second = store.complete_success(
        "request-success",
        completed_at="2026-08-05T00:01:16Z",
        runtime_ms=74_000,
        moisture_after=1400,
    )

    assert remaining_first == 17_200
    assert remaining_second == 17_200
    event = store.get_event("request-success")
    assert event.result == "SUCCESS"
    assert event.runtime_ms == 74_000
    assert event.moisture_before == 1500
    assert event.moisture_after == 1400


def test_concurrent_success_finalization_decrements_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-race",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
    )
    store.mark_accepted("request-race", started_at="2026-08-05T00:00:01Z")

    def finalize() -> int:
        return store.complete_success(
            "request-race",
            completed_at="2026-08-05T00:01:15Z",
            runtime_ms=74_000,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: finalize(), range(16)))

    assert set(results) == {17_200}
    assert store.tank_remaining_ml() == 17_200


def test_success_requires_an_accepted_request(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-pending",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
    )

    with pytest.raises(StateError, match="cannot transition"):
        store.complete_success(
            "request-pending",
            completed_at="2026-08-05T00:01:15Z",
            runtime_ms=74_000,
        )


def test_last_success_and_refill_are_explicit(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.reserve_request(
        "request-success",
        dose_ml=800,
        requested_at="2026-08-05T00:00:00Z",
    )
    store.mark_accepted("request-success", started_at="2026-08-05T00:00:01Z")
    store.complete_success(
        "request-success",
        completed_at="2026-08-05T00:01:15Z",
        runtime_ms=74_000,
    )

    assert store.last_success_at() == "2026-08-05T00:01:15Z"
    assert store.refill(updated_at="2026-08-06T00:00:00Z") == 18_000
    assert store.tank_remaining_ml() == 18_000
