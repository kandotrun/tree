from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

from .atom_client import AtomClient
from .config import ConfigError, load_settings
from .service import WateringService
from .state import StateError, StateStore

_COMMANDS = {"water", "status", "stop", "refill", "schedule"}
_POTENTIALLY_ACTUATING_COMMANDS = {"water", "schedule"}
_FIXED_COMMAND_ERROR = "".join(
    (
        "固定コマンドを1つだけ指定してください。",
        "任意の水量や運転時間は指定できません。",
    )
)
_EXIT_CODES = {
    "OFFLINE": 3,
    "REJECTED": 4,
    "TANK_EMPTY": 4,
    "FAILED": 4,
    "UNKNOWN": 5,
}


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _report_database_error(*, outcome_unknown: bool) -> int:
    if outcome_unknown:
        result = "UNKNOWN"
        exit_code = 5
        message = (
            "ローカル状態DBを安全に更新できず、給水結果を確定できません。"
            "安全のため再実行せず、現物を確認してください。"
        )
    else:
        result = "DB_ERROR"
        exit_code = 6
        message = "ローカル状態DBを安全に更新できないため、操作を中止しました。"
    _print_result({"ok": False, "result": result, "message_ja": message})
    return exit_code


def _report_unexpected_error(exc: Exception, *, outcome_unknown: bool) -> int:
    print(f"unexpected internal error: {type(exc).__name__}", file=sys.stderr)
    if outcome_unknown:
        result = "UNKNOWN"
        exit_code = 5
        message = (
            "予期しない内部エラーが発生し、給水結果は未確定です。"
            "安全のため再実行せず、現物を確認してください。"
        )
    else:
        result = "INTERNAL_ERROR"
        exit_code = 1
        message = "予期しない内部エラーのため、操作を中止しました。"
    _print_result({"ok": False, "result": result, "message_ja": message})
    return exit_code


def build_service() -> WateringService:
    settings = load_settings()
    store = StateStore(settings.database_path, tank_usable_ml=settings.tank_usable_ml)
    store.initialize()
    client = AtomClient(
        settings.atom_url,
        settings.atom_api_token,
        connect_timeout_sec=settings.connect_timeout_sec,
        request_timeout_sec=settings.request_timeout_sec,
    )
    return WateringService(settings, client, store)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or arguments[0] not in _COMMANDS:
        _print_result(
            {
                "ok": False,
                "result": "CONFIG_ERROR",
                "message_ja": _FIXED_COMMAND_ERROR,
            }
        )
        return 2

    command = arguments[0]
    try:
        service = build_service()
        operation = getattr(service, command)
    except ConfigError as exc:
        _print_result(
            {
                "ok": False,
                "result": "CONFIG_ERROR",
                "message_ja": f"設定が不正です: {exc}",
            }
        )
        return 2
    except StateError:
        return _report_database_error(outcome_unknown=False)
    except Exception as exc:
        return _report_unexpected_error(exc, outcome_unknown=False)

    try:
        result = operation()
    except StateError:
        return _report_database_error(outcome_unknown=command in _POTENTIALLY_ACTUATING_COMMANDS)
    except Exception as exc:
        return _report_unexpected_error(
            exc,
            outcome_unknown=command in _POTENTIALLY_ACTUATING_COMMANDS,
        )

    _print_result(result)
    return _EXIT_CODES.get(str(result.get("result")), 0)


def _fixed_main(command: str) -> int:
    return main([command, *sys.argv[1:]])


def water_main() -> int:
    return _fixed_main("water")


def status_main() -> int:
    return _fixed_main("status")


def stop_main() -> int:
    return _fixed_main("stop")


def refill_main() -> int:
    return _fixed_main("refill")


def schedule_main() -> int:
    return _fixed_main("schedule")


if __name__ == "__main__":
    raise SystemExit(main())
