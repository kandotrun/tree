from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Protocol

from .atom_client import AtomError, AtomHTTPError
from .public_state import PublicActionStore, PublicLimits, PublicUsage

_STATUS_CACHE_MS = 1_000


class PublicAtom(Protocol):
    def status(self) -> dict[str, Any]: ...

    def water(
        self,
        request_id: str,
        *,
        duration_sec: int | None = None,
    ) -> dict[str, Any]: ...

    def stop(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class GatewayReply:
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class PublicGateway:
    def __init__(
        self,
        *,
        atom: PublicAtom,
        store: PublicActionStore,
        limits: PublicLimits,
        now_ms: Callable[[], int],
        monotonic_ms: Callable[[], int],
        request_id_factory: Callable[[], str],
    ) -> None:
        self._atom = atom
        self.store = store
        self._limits = limits
        self._now_ms = now_ms
        self._monotonic_ms = monotonic_ms
        self._request_id_factory = request_id_factory
        self._actuation_lock = Lock()
        self._status_lock = Lock()
        self._cached_status: tuple[int, GatewayReply] | None = None

    def status(self) -> GatewayReply:
        cache_time = self._monotonic_ms()
        with self._status_lock:
            cached = self._cached_status
            if cached is not None and 0 <= cache_time - cached[0] <= _STATUS_CACHE_MS:
                return cached[1]
            reply = self._fresh_status()
            self._cached_status = (cache_time, reply)
            return reply

    def _fresh_status(self) -> GatewayReply:
        try:
            status = self._atom.status()
        except AtomError:
            return GatewayReply(503, {"online": False, "error": "device_unavailable"})

        state = status.get("state")
        pump = status.get("pump")
        armed = status.get("armed")
        if not isinstance(state, str) or type(pump) is not bool or type(armed) is not bool:
            return GatewayReply(503, {"online": False, "error": "device_unavailable"})

        usage = self.store.usage(now_ms=self._now_ms(), limits=self._limits)
        body: dict[str, Any] = {
            "online": True,
            "state": state,
            "pump": pump,
            "armed": armed,
            "remaining_sec": (int(status.get("remaining_ms", 0)) + 999) // 1_000,
            "public_duration_sec": self._limits.duration_sec,
            "hourly_used": usage.hourly_used,
            "hourly_limit": self._limits.hourly_limit,
            "daily_used": usage.daily_used,
            "daily_limit": self._limits.daily_limit,
            "retry_after_sec": usage.retry_after_sec,
        }
        moisture_adc = status.get("moisture_adc")
        if type(moisture_adc) is int:
            body["moisture_adc"] = moisture_adc
        return GatewayReply(200, body)

    def _invalidate_status(self) -> None:
        with self._status_lock:
            self._cached_status = None

    @staticmethod
    def _rate_limit_reply(usage: PublicUsage) -> GatewayReply:
        return GatewayReply(
            429,
            {
                "accepted": False,
                "error": usage.reason,
                "retry_after_sec": usage.retry_after_sec,
            },
            {"Retry-After": str(usage.retry_after_sec)},
        )

    def water(self) -> GatewayReply:
        with self._actuation_lock:
            return self._water_once()

    def _water_once(self) -> GatewayReply:
        now_ms = self._now_ms()
        usage = self.store.usage(now_ms=now_ms, limits=self._limits)
        if usage.reason is not None:
            return self._rate_limit_reply(usage)

        try:
            status = self._atom.status()
        except AtomError:
            return GatewayReply(503, {"accepted": False, "error": "device_unavailable"})
        if (
            status.get("state") != "IDLE"
            or status.get("pump") is not False
            or status.get("armed") is not True
        ):
            return GatewayReply(409, {"accepted": False, "error": "device_not_ready"})

        request_id = self._request_id_factory()
        reservation = self.store.reserve(
            request_id,
            now_ms=now_ms,
            limits=self._limits,
        )
        if not reservation.accepted:
            return self._rate_limit_reply(
                PublicUsage(
                    hourly_used=reservation.hourly_used,
                    daily_used=reservation.daily_used,
                    retry_after_sec=reservation.retry_after_sec,
                    reason=reservation.reason,
                )
            )

        try:
            response = self._atom.water(
                request_id,
                duration_sec=self._limits.duration_sec,
            )
        except AtomHTTPError as exc:
            if 400 <= exc.status < 500:
                self.store.set_outcome(request_id, "REJECTED")
                self._invalidate_status()
                return GatewayReply(
                    409,
                    {"accepted": False, "error": "device_rejected"},
                )
            self.store.set_outcome(request_id, "UNKNOWN")
            self._invalidate_status()
            return self._unknown_reply()
        except AtomError:
            self.store.set_outcome(request_id, "UNKNOWN")
            self._invalidate_status()
            return self._unknown_reply()

        if response.get("accepted") is not True or response.get("request_id") != request_id:
            self.store.set_outcome(request_id, "UNKNOWN")
            self._invalidate_status()
            return self._unknown_reply()
        self.store.set_outcome(request_id, "ACCEPTED")
        self._invalidate_status()
        return GatewayReply(
            202,
            {
                "accepted": True,
                "state": "WATERING",
                "duration_sec": self._limits.duration_sec,
            },
        )

    def _unknown_reply(self) -> GatewayReply:
        return GatewayReply(
            202,
            {
                "accepted": False,
                "state": "UNKNOWN",
                "duration_sec": self._limits.duration_sec,
            },
        )

    def stop(self) -> GatewayReply:
        with self._actuation_lock:
            return self._stop_once()

    def _stop_once(self) -> GatewayReply:
        try:
            response = self._atom.stop()
        except AtomError:
            return GatewayReply(503, {"stopped": False, "error": "device_unavailable"})
        self._invalidate_status()
        state = response.get("state")
        if not isinstance(state, str):
            state = "UNKNOWN"
        return GatewayReply(
            200,
            {
                "stopped": response.get("stopped") is True,
                "state": state,
            },
        )
