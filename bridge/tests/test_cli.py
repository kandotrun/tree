from __future__ import annotations

import json

import pytest

from balcony_watering import cli
from balcony_watering.config import ConfigError
from balcony_watering.state import StateError


class FakeService:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.called: list[str] = []

    def _call(self, command: str) -> dict[str, object]:
        self.called.append(command)
        return self.result

    def water(self) -> dict[str, object]:
        return self._call("water")

    def status(self) -> dict[str, object]:
        return self._call("status")

    def stop(self) -> dict[str, object]:
        return self._call("stop")

    def refill(self) -> dict[str, object]:
        return self._call("refill")

    def schedule(self) -> dict[str, object]:
        return self._call("schedule")


def read_output(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    output = capsys.readouterr().out
    assert output.endswith("\n")
    assert output.count("\n") == 1
    return json.loads(output)


def test_cli_prints_single_json_object_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeService(
        {
            "ok": True,
            "result": "SUCCESS",
            "message_ja": "水やりを完了しました。",
        }
    )
    monkeypatch.setattr(cli, "build_service", lambda: service)

    exit_code = cli.main(["water"])

    assert exit_code == 0
    assert service.called == ["water"]
    assert read_output(capsys)["result"] == "SUCCESS"


def test_cli_maps_operational_results_to_documented_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {
        "OFFLINE": 3,
        "REJECTED": 4,
        "TANK_EMPTY": 4,
        "FAILED": 4,
        "UNKNOWN": 5,
    }

    for result, exit_code in expected.items():
        service = FakeService({"ok": False, "result": result, "message_ja": result})
        monkeypatch.setattr(cli, "build_service", lambda service=service: service)
        assert cli.main(["water"]) == exit_code
        assert read_output(capsys)["result"] == result


def test_cli_reports_configuration_errors_as_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> FakeService:
        raise ConfigError("DOSE_ML is required")

    monkeypatch.setattr(cli, "build_service", fail)

    assert cli.main(["status"]) == 2
    result = read_output(capsys)
    assert result["result"] == "CONFIG_ERROR"
    assert "DOSE_ML" in str(result["message_ja"])


def test_cli_reports_pre_dispatch_database_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_build() -> FakeService:
        raise StateError("database is read-only")

    monkeypatch.setattr(cli, "build_service", fail_build)

    return_code = cli.main(["water"])
    result = read_output(capsys)

    assert return_code == 6
    assert result["result"] == "DB_ERROR"
    assert "database is read-only" not in str(result["message_ja"])
    assert "操作を中止" in str(result["message_ja"])
    assert "結果を確定できません" not in str(result["message_ja"])


@pytest.mark.parametrize("command", ["water", "schedule"])
def test_cli_treats_operation_database_errors_as_unknown(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "database-sensitive-detail"
    service = FakeService({"ok": True, "result": "SUCCESS"})

    def fail_operation() -> dict[str, object]:
        service.called.append(command)
        raise StateError(secret)

    monkeypatch.setattr(service, command, fail_operation)
    monkeypatch.setattr(cli, "build_service", lambda: service)

    return_code = cli.main([command])
    result = read_output(capsys)

    assert return_code == 5
    assert result["result"] == "UNKNOWN"
    assert service.called == [command]
    assert "給水結果を確定できません" in str(result["message_ja"])
    assert "再実行せず" in str(result["message_ja"])
    assert secret not in str(result["message_ja"])


@pytest.mark.parametrize(
    ("error", "expected_result", "expected_exit_code"),
    [
        (StateError("database-sensitive-detail"), "DB_ERROR", 6),
        (RuntimeError("unexpected-sensitive-detail"), "INTERNAL_ERROR", 1),
    ],
)
def test_cli_keeps_status_operation_errors_non_ambiguous(
    error: Exception,
    expected_result: str,
    expected_exit_code: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeService({"ok": True, "result": "SUCCESS"})

    def fail_operation() -> dict[str, object]:
        service.called.append("status")
        raise error

    monkeypatch.setattr(service, "status", fail_operation)
    monkeypatch.setattr(cli, "build_service", lambda: service)

    return_code = cli.main(["status"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert return_code == expected_exit_code
    assert result["result"] == expected_result
    assert service.called == ["status"]
    assert "未確定" not in str(result["message_ja"])
    assert str(error) not in captured.out
    assert str(error) not in captured.err


def test_cli_reports_pre_dispatch_unexpected_errors_as_safe_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "unexpected-sensitive-detail"

    def fail_build() -> FakeService:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "build_service", fail_build)

    return_code = cli.main(["water"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert return_code == 1
    assert result["result"] == "INTERNAL_ERROR"
    assert "未確定" not in str(result["message_ja"])
    assert "RuntimeError" in captured.err
    assert secret not in captured.out
    assert secret not in captured.err


@pytest.mark.parametrize("command", ["water", "schedule"])
def test_cli_treats_unexpected_actuating_error_as_unknown_physical_state(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "unexpected-sensitive-detail"
    service = FakeService({"ok": True, "result": "SUCCESS"})

    def fail_operation() -> dict[str, object]:
        service.called.append(command)
        raise RuntimeError(secret)

    monkeypatch.setattr(service, command, fail_operation)
    monkeypatch.setattr(cli, "build_service", lambda: service)

    return_code = cli.main([command])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert return_code == 5
    assert result["result"] == "UNKNOWN"
    assert service.called == [command]
    assert "給水結果は未確定" in str(result["message_ja"])
    assert "再実行せず" in str(result["message_ja"])
    assert "現物を確認" in str(result["message_ja"])
    assert "RuntimeError" in captured.err
    assert secret not in captured.out
    assert secret not in captured.err


def test_cli_rejects_unknown_commands_and_extra_arguments_as_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["water", "--duration", "999999"]) == 2
    assert read_output(capsys)["result"] == "CONFIG_ERROR"

    assert cli.main(["arbitrary-command"]) == 2
    assert read_output(capsys)["result"] == "CONFIG_ERROR"
