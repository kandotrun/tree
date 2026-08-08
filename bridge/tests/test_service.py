from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from balcony_watering.atom_client import AtomConnectionError, AtomHTTPError
from balcony_watering.config import Settings
from balcony_watering.service import WateringService
from balcony_watering.state import StateStore


class FakeTime:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
        self.elapsed = 0.0

    def now(self) -> datetime:
        return self.current + timedelta(seconds=self.elapsed)

    def monotonic(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


class FakeAtomClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.health_result: dict[str, Any] | Exception = {
            "ok": True,
            "device": "balcony-watering",
        }
        self.status_results: list[dict[str, Any] | Exception] = [
            {
                "state": "IDLE",
                "pump": False,
                "moisture_adc": 1500,
                "last_request_id": "",
            }
        ]
        self.water_result: dict[str, Any] | Exception = {
            "accepted": True,
            "request_id": "request-1",
            "state": "WATERING",
            "scheduled_ms": 10_000,
        }
        self.stop_result: dict[str, Any] | Exception = {
            "stopped": True,
            "state": "COOLDOWN",
        }

    @staticmethod
    def _resolve(value: dict[str, Any] | Exception) -> dict[str, Any]:
        if isinstance(value, Exception):
            raise value
        return value

    def health(self) -> dict[str, Any]:
        self.calls.append(("health", None))
        return self._resolve(self.health_result)

    def status(self) -> dict[str, Any]:
        self.calls.append(("status", None))
        if len(self.status_results) > 1:
            value = self.status_results.pop(0)
        else:
            value = self.status_results[0]
        return self._resolve(value)

    def water(self, request_id: str) -> dict[str, Any]:
        self.calls.append(("water", request_id))
        return self._resolve(self.water_result)

    def stop(self) -> dict[str, Any]:
        self.calls.append(("stop", None))
        return self._resolve(self.stop_result)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        atom_url="http://127.0.0.1",
        dose_ml=800,
        tank_usable_ml=18_000,
        low_tank_doses=3,
        connect_timeout_sec=1,
        request_timeout_sec=2,
        status_poll_interval_sec=1,
        status_poll_timeout_sec=4,
        min_water_interval_hours=72,
        database_path=tmp_path / "watering.db",
    )


def make_service(
    tmp_path: Path,
    *,
    client: FakeAtomClient | None = None,
    clock: FakeTime | None = None,
    settings: Settings | None = None,
) -> tuple[WateringService, StateStore, FakeAtomClient, FakeTime]:
    active_settings = settings or make_settings(tmp_path)
    store = StateStore(active_settings.database_path, tank_usable_ml=active_settings.tank_usable_ml)
    store.initialize()
    active_client = client or FakeAtomClient()
    active_clock = clock or FakeTime()
    service = WateringService(
        active_settings,
        active_client,
        store,
        now=active_clock.now,
        monotonic=active_clock.monotonic,
        sleep=active_clock.sleep,
        request_id_factory=lambda: "request-1",
    )
    return service, store, active_client, active_clock


def successful_status_sequence(client: FakeAtomClient) -> None:
    client.status_results = [
        {"state": "IDLE", "pump": False, "moisture_adc": 1500, "last_request_id": ""},
        {
            "state": "WATERING",
            "pump": True,
            "moisture_adc": 1490,
            "last_request_id": "request-1",
            "remaining_ms": 9000,
        },
        {
            "state": "COOLDOWN",
            "pump": False,
            "moisture_adc": 1400,
            "last_request_id": "request-1",
            "last_runtime_ms": 10_000,
            "last_stop_reason": "DOSE_COMPLETE",
            "remaining_ms": 0,
        },
    ]


def test_successful_water_request_decrements_tank_once(tmp_path: Path) -> None:
    client = FakeAtomClient()
    successful_status_sequence(client)
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result == {
        "ok": True,
        "result": "SUCCESS",
        "request_id": "request-1",
        "dose_ml": 800,
        "runtime_ms": 10_000,
        "tank_remaining_ml": 17_200,
        "message_ja": "水やりを完了しました。約0.8L、推定残量は17.2Lです。",
    }
    assert store.get_event("request-1").result == "SUCCESS"
    assert [call for call in client.calls if call[0] == "water"] == [("water", "request-1")]


def test_manual_stop_after_acceptance_is_unknown_and_does_not_decrement_tank(
    tmp_path: Path,
) -> None:
    client = FakeAtomClient()
    client.status_results = [
        {"state": "IDLE", "pump": False, "last_request_id": ""},
        {
            "state": "COOLDOWN",
            "pump": False,
            "last_request_id": "request-1",
            "last_runtime_ms": 5_000,
            "last_stop_reason": "MANUAL_STOP",
        },
    ]
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "UNKNOWN"
    assert store.get_event("request-1").result == "UNKNOWN"
    assert store.tank_remaining_ml() == 18_000


def test_unresolved_previous_request_blocks_all_network_calls(tmp_path: Path) -> None:
    service, store, client, _ = make_service(tmp_path)
    store.reserve_request(
        "older-request",
        dose_ml=800,
        requested_at="2026-08-04T00:00:00Z",
    )
    store.mark_unknown("older-request", detail="lost connection")

    result = service.water()

    assert result["result"] == "UNKNOWN"
    assert result["request_id"] == "older-request"
    assert client.calls == []


def test_offline_preflight_never_reserves_or_sends_request(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.health_result = AtomConnectionError("offline")
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "OFFLINE"
    assert store.unresolved_event() is None
    assert all(call[0] != "water" for call in client.calls)


def test_invalid_request_is_definitive_and_does_not_decrement_tank(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.water_result = AtomHTTPError(400, {"error": "invalid_request_body"})
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "REJECTED"
    assert result["http_status"] == 400
    assert store.get_event("request-1").result == "REJECTED"
    assert store.tank_remaining_ml() == 18_000


def test_unexpected_401_is_unknown_and_does_not_decrement_tank(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.water_result = AtomHTTPError(401, {"error": "unexpected_response"})
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "UNKNOWN"
    assert result["http_status"] == 401
    assert store.get_event("request-1").result == "UNKNOWN"
    assert store.tank_remaining_ml() == 18_000


@pytest.mark.parametrize(
    ("status", "code"),
    [(409, "busy"), (409, "duplicate_request_id"), (429, "cooldown")],
)
def test_conflict_or_cooldown_after_post_is_unknown_and_blocks_retry(
    tmp_path: Path,
    status: int,
    code: str,
) -> None:
    client = FakeAtomClient()
    client.water_result = AtomHTTPError(status, {"error": code})
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()
    second_result = service.water()

    assert result["result"] == "UNKNOWN"
    assert result["http_status"] == status
    assert second_result["result"] == "UNKNOWN"
    assert store.get_event("request-1").result == "UNKNOWN"
    assert store.tank_remaining_ml() == 18_000
    assert [call for call in client.calls if call[0] == "water"] == [("water", "request-1")]


def test_server_error_after_post_is_unknown_not_retryable(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.water_result = AtomHTTPError(500, {"error": "internal_error"})
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "UNKNOWN"
    assert store.get_event("request-1").result == "UNKNOWN"
    assert store.unresolved_event() is not None
    assert store.tank_remaining_ml() == 18_000


def test_ambiguous_post_failure_is_unknown_and_is_never_retried(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.water_result = AtomConnectionError("connection reset")
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "UNKNOWN"
    assert store.get_event("request-1").result == "UNKNOWN"
    assert [call for call in client.calls if call[0] == "water"] == [("water", "request-1")]
    assert store.tank_remaining_ml() == 18_000


def test_mismatched_acceptance_id_is_treated_as_unknown(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.water_result = {
        "accepted": True,
        "request_id": "different-request",
        "state": "WATERING",
    }
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "UNKNOWN"
    assert store.get_event("request-1").result == "UNKNOWN"


def test_transient_status_failure_after_acceptance_can_recover(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.status_results = [
        {"state": "IDLE", "pump": False, "moisture_adc": 1500, "last_request_id": ""},
        AtomConnectionError("temporary"),
        {
            "state": "COOLDOWN",
            "pump": False,
            "moisture_adc": 1400,
            "last_request_id": "request-1",
            "last_runtime_ms": 10_000,
            "last_stop_reason": "DOSE_COMPLETE",
        },
    ]
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "SUCCESS"
    assert store.tank_remaining_ml() == 17_200


def test_poll_timeout_is_unknown_without_second_water_request(tmp_path: Path) -> None:
    client = FakeAtomClient()
    client.status_results = [
        {"state": "IDLE", "pump": False, "moisture_adc": 1500, "last_request_id": ""},
        {
            "state": "WATERING",
            "pump": True,
            "last_request_id": "request-1",
            "remaining_ms": 9000,
        },
    ]
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "UNKNOWN"
    assert [call for call in client.calls if call[0] == "water"] == [("water", "request-1")]
    assert store.tank_remaining_ml() == 18_000


def test_untrusted_status_values_are_not_persisted_in_error_detail(tmp_path: Path) -> None:
    client = FakeAtomClient()
    secret = "s" * 32
    client.status_results = [
        {"state": "IDLE", "pump": False, "moisture_adc": 1500, "last_request_id": ""},
        {
            "state": secret,
            "pump": False,
            "last_request_id": "request-1",
        },
    ]
    service, store, _, _ = make_service(tmp_path, client=client)

    result = service.water()

    assert result["result"] == "UNKNOWN"
    detail = store.get_event("request-1").detail
    assert detail is not None
    assert secret not in detail


def test_estimated_empty_tank_blocks_pump_command(tmp_path: Path) -> None:
    service, store, client, _ = make_service(tmp_path)
    store.refill(700)

    result = service.water()

    assert result["result"] == "TANK_EMPTY"
    assert all(call[0] != "water" for call in client.calls)


def test_schedule_without_manual_success_history_is_safe_noop(tmp_path: Path) -> None:
    service, _, client, _ = make_service(tmp_path)

    result = service.schedule()

    assert result["ok"] is True
    assert result["result"] == "SKIPPED_NO_HISTORY"
    assert client.calls == []


def test_schedule_before_minimum_interval_is_safe_noop(tmp_path: Path) -> None:
    service, store, client, _ = make_service(tmp_path)
    store.reserve_request(
        "previous-request",
        dose_ml=800,
        requested_at="2026-08-04T23:00:00Z",
    )
    store.mark_accepted("previous-request", started_at="2026-08-04T23:00:01Z")
    store.complete_success(
        "previous-request",
        completed_at="2026-08-04T23:01:00Z",
        runtime_ms=10_000,
    )

    result = service.schedule()

    assert result["result"] == "SKIPPED_RECENT"
    assert client.calls == []


def test_due_schedule_uses_the_same_single_water_path(tmp_path: Path) -> None:
    client = FakeAtomClient()
    successful_status_sequence(client)
    clock = FakeTime()
    service, store, _, _ = make_service(tmp_path, client=client, clock=clock)
    store.reserve_request(
        "previous-request",
        dose_ml=800,
        requested_at="2026-08-01T00:00:00Z",
    )
    store.mark_accepted("previous-request", started_at="2026-08-01T00:00:01Z")
    store.complete_success(
        "previous-request",
        completed_at="2026-08-01T00:01:00Z",
        runtime_ms=10_000,
    )

    result = service.schedule()

    assert result["result"] == "SUCCESS"
    assert [call for call in client.calls if call[0] == "water"] == [("water", "request-1")]


def test_schedule_rechecks_due_state_atomically_before_reserving(tmp_path: Path) -> None:
    class RacingClient(FakeAtomClient):
        callback: Any = None

        def status(self) -> dict[str, Any]:
            value = super().status()
            if self.callback is not None:
                callback, self.callback = self.callback, None
                callback()
            return value

    client = RacingClient()
    service, store, _, _ = make_service(tmp_path, client=client)
    store.reserve_request(
        "previous-request",
        dose_ml=800,
        requested_at="2026-08-01T00:00:00Z",
    )
    store.mark_accepted("previous-request", started_at="2026-08-01T00:00:01Z")
    store.complete_success(
        "previous-request",
        completed_at="2026-08-01T00:01:00Z",
        runtime_ms=10_000,
    )

    def complete_concurrent_manual_request() -> None:
        store.reserve_request(
            "concurrent-request",
            dose_ml=800,
            requested_at="2026-08-05T00:00:00Z",
        )
        store.mark_accepted("concurrent-request", started_at="2026-08-05T00:00:00Z")
        store.complete_success(
            "concurrent-request",
            completed_at="2026-08-05T00:00:00Z",
            runtime_ms=10_000,
        )

    client.callback = complete_concurrent_manual_request

    result = service.schedule()

    assert result["result"] == "SKIPPED_RECENT"
    assert [call for call in client.calls if call[0] == "water"] == []
    assert store.tank_remaining_ml() == 16_400


def test_stop_and_status_do_not_change_tank_estimate(tmp_path: Path) -> None:
    service, store, client, _ = make_service(tmp_path)

    stop_result = service.stop()
    status_result = service.status()

    assert stop_result["result"] == "STOPPED"
    assert status_result["result"] == "STATUS"
    assert status_result["tank_remaining_ml"] == 18_000
    assert store.tank_remaining_ml() == 18_000
    assert ("stop", None) in client.calls


def test_low_tank_warning_is_included_after_success(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), tank_usable_ml=2400)
    client = FakeAtomClient()
    successful_status_sequence(client)
    service, store, _, _ = make_service(tmp_path, client=client, settings=settings)

    result = service.water()

    assert result["result"] == "SUCCESS"
    assert result["tank_remaining_ml"] == 1600
    assert result["low_tank"] is True
    assert "補充" in result["message_ja"]
    assert store.tank_remaining_ml() == 1600
