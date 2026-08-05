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
            status = self.client.status()
        except AtomError:
            return None
        return status

    def water(self) -> dict[str, Any]:
        return self._water()

    def _water(self, *, schedule_success_cutoff: str | None = None) -> dict[str, Any]:
        unresolved = self.store.unresolved_event()
        if unresolved is not None:
            return self._unknown_previous(unresolved)

        status = self._preflight_status()
        if status is None:
            return self._offline()
        state = status.get("state")
        if state != "IDLE" or status.get("pump") is not False:
            rejected_message = "".join(
                (
                    f"ATOM Liteが{state or '不明な状態'}のため、",
                    "水やりは実行していません。",
                )
            )
            return {
                "ok": False,
                "result": "REJECTED",
                "state": state,
                "message_ja": rejected_message,
            }

        tank_remaining = self.store.tank_remaining_ml()
        if tank_remaining < self.settings.dose_ml:
            empty_message = "".join(
                (
                    "推定タンク残量が1回分未満のため、水やりは実行していません。",
                    "補充してください。",
                )
            )
            return {
                "ok": False,
                "result": "TANK_EMPTY",
                "tank_remaining_ml": tank_remaining,
                "message_ja": empty_message,
            }

        request_id = self._request_id_factory()
        moisture_before = status.get("moisture_adc")
        if not isinstance(moisture_before, int) or isinstance(moisture_before, bool):
            moisture_before = None
        try:
            self.store.reserve_request(
                request_id,
                dose_ml=self.settings.dose_ml,
                requested_at=_timestamp(self._now()),
                moisture_before=moisture_before,
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
            latest_success = self.store.last_success_at()
            return self._skipped_recent(latest_success)

        try:
            acceptance = self.client.water(request_id)
        except AtomHTTPError as exc:
            detail = f"HTTP {exc.status}: {exc.code}"
            definitive_rejections = {400, 401, 413, 423}
            if exc.status in definitive_rejections:
                self.store.mark_rejected(request_id, detail=detail)
                rejection_message = "ATOM Liteが給水要求を拒否したため、水やりは実行していません。"
                return {
                    "ok": False,
                    "result": "REJECTED",
                    "request_id": request_id,
                    "http_status": exc.status,
                    "message_ja": rejection_message,
                }
            self.store.mark_unknown(request_id, detail=detail)
            return {
                "ok": False,
                "result": "UNKNOWN",
                "request_id": request_id,
                "http_status": exc.status,
                "message_ja": (
                    "命令後にATOM Liteの異常応答を受けたため結果は未確定です。"
                    "安全のため再実行していません。"
                ),
            }
        except (AtomConnectionError, AtomProtocolError):
            self.store.mark_unknown(
                request_id,
                detail="network or protocol failure after POST /v1/water",
            )
            return {
                "ok": False,
                "result": "UNKNOWN",
                "request_id": request_id,
                "message_ja": (
                    "命令後に通信が切れたため結果を確定できません。安全のため再実行していません。"
                ),
            }

        if (
            acceptance.get("accepted") is not True
            or acceptance.get("request_id") != request_id
            or acceptance.get("state") != "WATERING"
        ):
            self.store.mark_unknown(request_id, detail="invalid acceptance response")
            return {
                "ok": False,
                "result": "UNKNOWN",
                "request_id": request_id,
                "message_ja": (
                    "ATOM Liteの受付応答を確認できないため結果は未確定です。"
                    "安全のため再実行していません。"
                ),
            }

        self.store.mark_accepted(request_id, started_at=_timestamp(self._now()))
        started_monotonic = self._monotonic()
        deadline = started_monotonic + self.settings.status_poll_timeout_sec
        last_detail = "status poll timed out"

        while True:
            try:
                current = self.client.status()
                current_state = current.get("state")
                current_request_id = current.get("last_request_id")
                pump = current.get("pump")
                if (
                    current_request_id == request_id
                    and current_state in {"COOLDOWN", "IDLE"}
                    and pump is False
                ):
                    stop_reason = current.get("last_stop_reason")
                    if stop_reason != "DOSE_COMPLETE":
                        self.store.mark_unknown(
                            request_id,
                            detail="watering stopped without dose completion confirmation",
                        )
                        return {
                            "ok": False,
                            "result": "UNKNOWN",
                            "request_id": request_id,
                            "message_ja": (
                                "ポンプ停止は確認しましたが、標準1回分の完了を確認できません。"
                                "安全のため残量を減算せず、再実行していません。"
                            ),
                        }
                    raw_runtime = current.get("last_runtime_ms")
                    if (
                        isinstance(raw_runtime, int)
                        and not isinstance(raw_runtime, bool)
                        and raw_runtime >= 0
                    ):
                        runtime_ms = raw_runtime
                    else:
                        runtime_ms = max(
                            0,
                            round((self._monotonic() - started_monotonic) * 1000),
                        )
                    moisture_after = current.get("moisture_adc")
                    if not isinstance(moisture_after, int) or isinstance(moisture_after, bool):
                        moisture_after = None
                    remaining = self.store.complete_success(
                        request_id,
                        completed_at=_timestamp(self._now()),
                        runtime_ms=runtime_ms,
                        moisture_after=moisture_after,
                    )
                    low_tank = self._low_tank(remaining)
                    message = (
                        f"水やりを完了しました。約{self.settings.dose_ml / 1000:.1f}L、"
                        f"推定残量は{remaining / 1000:.1f}Lです。"
                    )
                    success_result: dict[str, Any] = {
                        "ok": True,
                        "result": "SUCCESS",
                        "request_id": request_id,
                        "dose_ml": self.settings.dose_ml,
                        "runtime_ms": runtime_ms,
                        "tank_remaining_ml": remaining,
                        "message_ja": message,
                    }
                    if low_tank:
                        success_result["low_tank"] = True
                        success_result["message_ja"] = message + " タンクを補充してください。"
                    return success_result
                if (
                    current_state == "WATERING"
                    and current_request_id == request_id
                    and pump is True
                ):
                    last_detail = "watering still active at poll timeout"
                else:
                    last_detail = "unexpected status after acceptance"
            except AtomHTTPError as exc:
                last_detail = f"status HTTP {exc.status} after acceptance"
            except (AtomConnectionError, AtomProtocolError):
                last_detail = "status unavailable after acceptance"

            if self._monotonic() >= deadline:
                break
            self._sleep(self.settings.status_poll_interval_sec)

        self.store.mark_unknown(request_id, detail=last_detail)
        return {
            "ok": False,
            "result": "UNKNOWN",
            "request_id": request_id,
            "message_ja": (
                "命令後に完了を確認できないため結果は未確定です。安全のため再実行していません。"
            ),
        }

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
            offline_message = "".join(
                (
                    "ATOM Liteへ接続できず、停止を確認できません。",
                    "現物を確認してください。",
                )
            )
            return {
                "ok": False,
                "result": "OFFLINE",
                "message_ja": offline_message,
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
