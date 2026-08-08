from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import Any

from balcony_watering.atom_client import AtomConnectionError, AtomHTTPError
from balcony_watering.public_gateway import PublicGateway
from balcony_watering.public_state import PublicActionStore, PublicLimits


class FakeAtom:
    def __init__(self) -> None:
        self.status_payload: dict[str, Any] = {
            "state": "IDLE",
            "pump": False,
            "armed": True,
            "remaining_ms": 0,
            "moisture_adc": 1500,
            "firmware_version": "0.4.1",
            "wifi_rssi": -50,
            "last_request_id": "private-request-id",
        }
        self.water_calls: list[tuple[str, int | None]] = []
        self.stop_calls = 0
        self.status_calls = 0
        self.status_error: Exception | None = None
        self.water_errors: list[Exception] = []

    def status(self) -> dict[str, Any]:
        self.status_calls += 1
        if self.status_error is not None:
            raise self.status_error
        return dict(self.status_payload)

    def water(self, request_id: str, *, duration_sec: int | None = None) -> dict[str, Any]:
        self.water_calls.append((request_id, duration_sec))
        if self.water_errors:
            raise self.water_errors.pop(0)
        return {"accepted": True, "request_id": request_id, "state": "WATERING"}

    def stop(self) -> dict[str, Any]:
        self.stop_calls += 1
        return {"stopped": True, "state": "IDLE"}


def make_gateway(
    tmp_path: Path,
    atom: FakeAtom,
    *,
    times: list[int] | None = None,
    monotonic_times: list[int] | None = None,
    request_ids: list[str] | None = None,
) -> PublicGateway:
    clock_values = iter(times or [1_000_000] * 20)
    monotonic_values = iter(monotonic_times or [0] * 20)
    id_values = iter(request_ids or [f"pub-{index}" for index in range(20)])
    return PublicGateway(
        atom=atom,
        store=PublicActionStore(tmp_path / "public.db"),
        limits=PublicLimits(
            duration_sec=10,
            cooldown_sec=60,
            hourly_limit=6,
            daily_limit=24,
        ),
        now_ms=lambda: next(clock_values),
        monotonic_ms=lambda: next(monotonic_values),
        request_id_factory=lambda: next(id_values),
    )


def test_status_rejects_invalid_remaining_time(tmp_path: Path) -> None:
    for index, invalid in enumerate((None, "1000", -1, True)):
        atom = FakeAtom()
        atom.status_payload["remaining_ms"] = invalid
        gateway = make_gateway(tmp_path / str(index), atom)

        reply = gateway.status()

        assert reply.status_code == 503
        assert reply.body == {"online": False, "error": "device_unavailable"}


def test_status_exposes_only_public_safe_device_fields(tmp_path: Path) -> None:
    atom = FakeAtom()
    gateway = make_gateway(tmp_path, atom)

    reply = gateway.status()

    assert reply.status_code == 200
    assert reply.body == {
        "online": True,
        "state": "IDLE",
        "pump": False,
        "armed": True,
        "remaining_sec": 0,
        "moisture_adc": 1500,
        "public_duration_sec": 10,
        "hourly_used": 0,
        "hourly_limit": 6,
        "daily_used": 0,
        "daily_limit": 24,
        "retry_after_sec": 0,
    }
    assert "wifi_rssi" not in reply.body
    assert "last_request_id" not in reply.body
    assert "firmware_version" not in reply.body


def test_status_uses_a_short_shared_cache_to_protect_the_device(tmp_path: Path) -> None:
    atom = FakeAtom()
    gateway = make_gateway(
        tmp_path,
        atom,
        times=[1_000_000, 1_001_001],
        monotonic_times=[10_000, 10_999, 11_001],
    )

    first = gateway.status()
    cached = gateway.status()
    refreshed = gateway.status()

    assert first.status_code == cached.status_code == refreshed.status_code == 200
    assert atom.status_calls == 2


def test_status_reports_offline_without_internal_error_details(tmp_path: Path) -> None:
    atom = FakeAtom()
    atom.status_error = AtomConnectionError("private network detail")
    gateway = make_gateway(tmp_path, atom)

    reply = gateway.status()

    assert reply.status_code == 503
    assert reply.body == {"online": False, "error": "device_unavailable"}
    assert "private" not in str(reply.body)


def test_water_sends_exactly_the_fixed_public_duration(tmp_path: Path) -> None:
    atom = FakeAtom()
    gateway = make_gateway(tmp_path, atom, request_ids=["pub-fixed"])

    reply = gateway.water()

    assert reply.status_code == 202
    assert reply.body == {
        "accepted": True,
        "state": "WATERING",
        "duration_sec": 10,
    }
    assert atom.water_calls == [("pub-fixed", 10)]


def test_water_rejects_busy_or_unarmed_device_before_reservation(tmp_path: Path) -> None:
    for status in (
        {"state": "WATERING", "pump": True, "armed": True},
        {"state": "IDLE", "pump": False, "armed": False},
    ):
        atom = FakeAtom()
        atom.status_payload = status
        gateway = make_gateway(tmp_path / status["state"], atom)

        reply = gateway.water()

        assert reply.status_code == 409
        assert reply.body["error"] == "device_not_ready"
        assert atom.water_calls == []


def test_second_public_request_is_rate_limited_without_device_post(tmp_path: Path) -> None:
    atom = FakeAtom()
    gateway = make_gateway(
        tmp_path,
        atom,
        times=[1_000_000, 1_001_000],
        request_ids=["pub-first", "pub-second"],
    )

    first = gateway.water()
    second = gateway.water()

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.body["error"] == "cooldown"
    assert int(second.headers["Retry-After"]) > 0
    assert atom.water_calls == [("pub-first", 10)]


def test_concurrent_public_requests_probe_and_dispatch_to_atom_once(tmp_path: Path) -> None:
    atom = FakeAtom()
    gateway = make_gateway(tmp_path, atom)
    barrier = Barrier(8)

    def water() -> int:
        barrier.wait()
        return gateway.water().status_code

    with ThreadPoolExecutor(max_workers=8) as executor:
        status_codes = list(executor.map(lambda _: water(), range(8)))

    assert status_codes.count(202) == 1
    assert status_codes.count(429) == 7
    assert atom.status_calls == 1
    assert len(atom.water_calls) == 1


def test_ambiguous_water_post_is_not_retried_and_remains_unknown(tmp_path: Path) -> None:
    atom = FakeAtom()
    atom.water_errors = [AtomConnectionError("timeout after write")]
    gateway = make_gateway(tmp_path, atom, request_ids=["pub-unknown"])

    reply = gateway.water()

    assert reply.status_code == 202
    assert reply.body == {
        "accepted": False,
        "state": "UNKNOWN",
        "duration_sec": 10,
    }
    assert atom.water_calls == [("pub-unknown", 10)]
    assert gateway.store.get_outcome("pub-unknown") == "UNKNOWN"


def test_definitive_device_rejection_releases_public_quota(tmp_path: Path) -> None:
    atom = FakeAtom()
    atom.water_errors = [AtomHTTPError(409, {"error": "busy"})]
    gateway = make_gateway(
        tmp_path,
        atom,
        times=[1_000_000, 1_000_001],
        request_ids=["pub-rejected", "pub-replacement"],
    )

    rejected = gateway.water()
    accepted = gateway.water()

    assert rejected.status_code == 409
    assert rejected.body == {"accepted": False, "error": "device_rejected"}
    assert accepted.status_code == 202
    assert atom.water_calls == [("pub-rejected", 10), ("pub-replacement", 10)]


def test_stop_serializes_behind_in_flight_water_dispatch(tmp_path: Path) -> None:
    water_entered = Event()
    release_water = Event()
    stop_called = Event()
    stop_thread_started = Event()
    calls: list[str] = []

    class BlockingAtom(FakeAtom):
        def water(
            self,
            request_id: str,
            *,
            duration_sec: int | None = None,
        ) -> dict[str, Any]:
            calls.append("water_start")
            water_entered.set()
            assert release_water.wait(timeout=2)
            calls.append("water_end")
            return {"accepted": True, "request_id": request_id, "state": "WATERING"}

        def stop(self) -> dict[str, Any]:
            calls.append("stop")
            stop_called.set()
            return {"stopped": True, "state": "IDLE"}

    gateway = make_gateway(tmp_path, BlockingAtom())

    def stop() -> Any:
        stop_thread_started.set()
        return gateway.stop()

    with ThreadPoolExecutor(max_workers=2) as executor:
        water_future = executor.submit(gateway.water)
        assert water_entered.wait(timeout=1)
        stop_future = executor.submit(stop)
        assert stop_thread_started.wait(timeout=1)
        try:
            assert not stop_called.wait(timeout=0.1)
        finally:
            release_water.set()
        assert water_future.result(timeout=1).status_code == 202
        assert stop_future.result(timeout=1).status_code == 200

    assert calls == ["water_start", "water_end", "stop"]


def test_stop_is_always_forwarded_without_consuming_quota(tmp_path: Path) -> None:
    atom = FakeAtom()
    gateway = make_gateway(tmp_path, atom)

    first = gateway.stop()
    second = gateway.stop()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.body == {"stopped": True, "state": "IDLE"}
    assert atom.stop_calls == 2
