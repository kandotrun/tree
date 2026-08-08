from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .atom_client import AtomConnectionError, AtomError, AtomHTTPError, AtomProtocolError
from .config import Settings
from .state import ScheduleNotDue, StateStore, UnresolvedRequest, WateringEvent


class AtomClientProtocol(Protocol):
    def health(self) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def water(self, request_id: str) -> dict[str, Any]: ...

    def stop(self) -> dict[str, Any]: ...


def _default_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class WateringService:
    def __init__(
        self,
        settings: Settings,
        client: AtomClientProtocol,
        store: StateStore,
        *,
        now: Callable[[], datetime] = _default_now,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        request_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.settings = settings
        self.client = client
        self.store = store
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        self._request_id_factory = request_id_factory

    def _low_tank(self, remaining_ml: int) -> bool:
        return remaining_ml < self.settings.low_tank_doses * self.settings.dose_ml

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        return value if type(value) is int else None

    @staticmethod
    def _unknown_previous(event: WateringEvent) -> dict[str, Any]:
        return {
            "ok": False,
            "result": "UNKNOWN",
            "request_id": event.request_id,
            "message_ja": (
                "結果未確定の水やり履歴があるため、新しい水やりは実行していません。"
                "現物と状態を確認してください。"
            ),
        }

    @staticmethod
    def _offline() -> dict[str, Any]:
        return {
            "ok": False,
            "result": "OFFLINE",
            "message_ja": "ATOM Liteへ接続できなかったため、水やりは実行していません。",
        }

    def _preflight_status(self) -> dict[str, Any] | None:
        try:
            health = self.client.health()
            if health.get("ok") is not True:
                return None
            return self.client.status()
        except AtomError:
            return None

    @staticmethod
    def _preflight_rejection(status: dict[str, Any]) -> dict[str, Any] | None:
        state = status.get("state")
        if state == "IDLE" and status.get("pump") is False:
            return None
        return {
            "ok": False,
            "result": "REJECTED",
            "state": state,
            "message_ja": (f"ATOM Liteが{state or '不明な状態'}のため、水やりは実行していません。"),
        }

    def _tank_rejection(self) -> dict[str, Any] | None:
        remaining = self.store.tank_remaining_ml()
        if remaining >= self.settings.dose_ml:
            return None
        return {
            "ok": False,
            "result": "TANK_EMPTY",
            "tank_remaining_ml": remaining,
            "message_ja": (
                "推定タンク残量が1回分未満のため、水やりは実行していません。補充してください。"
            ),
        }

    def _reserve_request(
        self,
        request_id: str,
        status: dict[str, Any],
        *,
        schedule_success_cutoff: str | None,
    ) -> dict[str, Any] | None:
        try:
            self.store.reserve_request(
                request_id,
                dose_ml=self.settings.dose_ml,
                requested_at=_timestamp(self._now()),
                moisture_before=self._optional_integer(status.get("moisture_adc")),
                schedule_success_cutoff=schedule_success_cutoff,
            )
        except UnresolvedRequest as exc:
            return {
                "ok": False,
                "result": "UNKNOWN",
                "request_id": exc.request_id,
                "message_ja": (
                    "同時実行された結果未確定の水やりがあるため、"
                    "新しい水やりは実行していません。現物を確認してください。"
                ),
            }
        except ScheduleNotDue:
            return self._skipped_recent(self.store.last_success_at())
        return None

    def _mark_unknown(
        self,
        request_id: str,
        *,
        detail: str,
        message_ja: str,
        http_status: int | None = None,
    ) -> dict[str, Any]:
        self.store.mark_unknown(request_id, detail=detail)
        result: dict[str, Any] = {
            "ok": False,
            "result": "UNKNOWN",
            "request_id": request_id,
            "message_ja": message_ja,
        }
        if http_status is not None:
            result["http_status"] = http_status
        return result

    def _send_water_request(self, request_id: str) -> dict[str, Any] | None:
        try:
            acceptance = self.client.water(request_id)
        except AtomHTTPError as exc:
            detail = f"HTTP {exc.status}: {exc.code}"
            if exc.status in {400, 413, 423}:
                self.store.mark_rejected(request_id, detail=detail)
                return {
                    "ok": False,
                    "result": "REJECTED",
                    "request_id": request_id,
                    "http_status": exc.status,
                    "message_ja": ("ATOM Liteが給水要求を拒否したため、水やりは実行していません。"),
                }
            return self._mark_unknown(
                request_id,
                detail=detail,
                http_status=exc.status,
                message_ja=(
                    "命令後にATOM Liteの異常応答を受けたため結果は未確定です。"
                    "安全のため再実行していません。"
                ),
            )
        except (AtomConnectionError, AtomProtocolError):
            return self._mark_unknown(
                request_id,
                detail="network or protocol failure after POST /v1/water",
                message_ja=(
                    "命令後に通信が切れたため結果を確定できません。安全のため再実行していません。"
                ),
            )

        if (
            acceptance.get("accepted") is not True
            or acceptance.get("request_id") != request_id
            or acceptance.get("state") != "WATERING"
        ):
            return self._mark_unknown(
                request_id,
                detail="invalid acceptance response",
                message_ja=(
                    "ATOM Liteの受付応答を確認できないため結果は未確定です。"
                    "安全のため再実行していません。"
                ),
            )

        self.store.mark_accepted(request_id, started_at=_timestamp(self._now()))
        return None

    def _completion_result(
        self,
        request_id: str,
        status: dict[str, Any],
        *,
        started_monotonic: float,
    ) -> dict[str, Any] | None:
        if not (
            status.get("last_request_id") == request_id
            and status.get("state") in {"COOLDOWN", "IDLE"}
            and status.get("pump") is False
        ):
            return None

        if status.get("last_stop_reason") != "DOSE_COMPLETE":
            return self._mark_unknown(
                request_id,
                detail="watering stopped without dose completion confirmation",
                message_ja=(
                    "ポンプ停止は確認しましたが、標準1回分の完了を確認できません。"
                    "安全のため残量を減算せず、再実行していません。"
                ),
            )

        runtime_ms = self._optional_integer(status.get("last_runtime_ms"))
        if runtime_ms is None or runtime_ms < 0:
            runtime_ms = max(0, round((self._monotonic() - started_monotonic) * 1000))
        remaining = self.store.complete_success(
            request_id,
            completed_at=_timestamp(self._now()),
            runtime_ms=runtime_ms,
            moisture_after=self._optional_integer(status.get("moisture_adc")),
        )
        message = (
            f"水やりを完了しました。約{self.settings.dose_ml / 1000:.1f}L、"
            f"推定残量は{remaining / 1000:.1f}Lです。"
        )
        result: dict[str, Any] = {
            "ok": True,
            "result": "SUCCESS",
            "request_id": request_id,
            "dose_ml": self.settings.dose_ml,
            "runtime_ms": runtime_ms,
            "tank_remaining_ml": remaining,
            "message_ja": message,
        }
        if self._low_tank(remaining):
            result["low_tank"] = True
            result["message_ja"] = message + " タンクを補充してください。"
        return result

    @staticmethod
    def _poll_detail(status: dict[str, Any], request_id: str) -> str:
        if (
            status.get("state") == "WATERING"
            and status.get("last_request_id") == request_id
            and status.get("pump") is True
        ):
            return "watering still active at poll timeout"
        return "unexpected status after acceptance"

    def _wait_for_completion(self, request_id: str) -> dict[str, Any]:
        started_monotonic = self._monotonic()
        deadline = started_monotonic + self.settings.status_poll_timeout_sec
        last_detail = "status poll timed out"

        while True:
            try:
                status = self.client.status()
                completed = self._completion_result(
                    request_id,
                    status,
                    started_monotonic=started_monotonic,
                )
                if completed is not None:
                    return completed
                last_detail = self._poll_detail(status, request_id)
            except AtomHTTPError as exc:
                last_detail = f"status HTTP {exc.status} after acceptance"
            except (AtomConnectionError, AtomProtocolError):
                last_detail = "status unavailable after acceptance"

            if self._monotonic() >= deadline:
                break
            self._sleep(self.settings.status_poll_interval_sec)

        return self._mark_unknown(
            request_id,
            detail=last_detail,
            message_ja=(
                "命令後に完了を確認できないため結果は未確定です。安全のため再実行していません。"
            ),
        )

    def water(self) -> dict[str, Any]:
        return self._water()

    def _water(self, *, schedule_success_cutoff: str | None = None) -> dict[str, Any]:
        unresolved = self.store.unresolved_event()
        if unresolved is not None:
            return self._unknown_previous(unresolved)

        status = self._preflight_status()
        if status is None:
            return self._offline()
        rejection = self._preflight_rejection(status) or self._tank_rejection()
        if rejection is not None:
            return rejection

        request_id = self._request_id_factory()
        reservation = self._reserve_request(
            request_id,
            status,
            schedule_success_cutoff=schedule_success_cutoff,
        )
        if reservation is not None:
            return reservation
        request_result = self._send_water_request(request_id)
        if request_result is not None:
            return request_result
        return self._wait_for_completion(request_id)

    def status(self) -> dict[str, Any]:
        atom_status = self._preflight_status()
        if atom_status is None:
            offline_result = self._offline()
            offline_result["tank_remaining_ml"] = self.store.tank_remaining_ml()
            return offline_result
        remaining = self.store.tank_remaining_ml()
        return {
            "ok": True,
            "result": "STATUS",
            "atom": atom_status,
            "tank_remaining_ml": remaining,
            "low_tank": self._low_tank(remaining),
            "message_ja": (
                f"ATOM Liteは{atom_status.get('state', 'UNKNOWN')}、"
                f"推定タンク残量は{remaining / 1000:.1f}Lです。"
            ),
        }

    def stop(self) -> dict[str, Any]:
        try:
            response = self.client.stop()
        except AtomError:
            return {
                "ok": False,
                "result": "OFFLINE",
                "message_ja": (
                    "ATOM Liteへ接続できず、停止を確認できません。現物を確認してください。"
                ),
            }
        if response.get("stopped") is not True:
            return {
                "ok": False,
                "result": "UNKNOWN",
                "message_ja": "ATOM Liteから停止確認を取得できません。現物を確認してください。",
            }
        return {
            "ok": True,
            "result": "STOPPED",
            "state": response.get("state"),
            "message_ja": "ポンプ停止命令を確認しました。",
        }

    def refill(self) -> dict[str, Any]:
        remaining = self.store.refill(updated_at=_timestamp(self._now()))
        return {
            "ok": True,
            "result": "REFILLED",
            "tank_remaining_ml": remaining,
            "message_ja": f"推定タンク残量を{remaining / 1000:.1f}Lへ戻しました。",
        }

    def schedule(self) -> dict[str, Any]:
        unresolved = self.store.unresolved_event()
        if unresolved is not None:
            return self._unknown_previous(unresolved)
        last_success = self.store.last_success_at()
        if last_success is None:
            return {
                "ok": True,
                "result": "SKIPPED_NO_HISTORY",
                "message_ja": "手動給水の成功履歴がないため、定期給水は実行していません。",
            }
        now = self._now().astimezone(UTC)
        elapsed = now - _parse_timestamp(last_success)
        minimum = timedelta(hours=self.settings.min_water_interval_hours)
        if elapsed < minimum:
            return self._skipped_recent(last_success)
        cutoff = now - minimum
        return self._water(schedule_success_cutoff=_timestamp(cutoff))

    def _skipped_recent(self, last_success: str | None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": True,
            "result": "SKIPPED_RECENT",
            "message_ja": "前回の成功から設定間隔未満のため、水やりは不要です。",
        }
        if last_success is not None:
            elapsed = self._now().astimezone(UTC) - _parse_timestamp(last_success)
            minimum = timedelta(hours=self.settings.min_water_interval_hours)
            remaining = minimum - max(elapsed, timedelta(0))
            result["remaining_interval_sec"] = max(0, round(remaining.total_seconds()))
        return result
