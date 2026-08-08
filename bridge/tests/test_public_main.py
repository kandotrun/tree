from __future__ import annotations

import logging

import pytest

import balcony_watering.public_main as public_main
import balcony_watering.public_server as public_server
from balcony_watering.config import ConfigError


def test_main_logs_configuration_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail_build() -> None:
        raise ConfigError("bad public settings")

    monkeypatch.setattr(public_main, "build_gateway", fail_build)

    with caplog.at_level(logging.ERROR):
        result = public_main.main()

    assert result == 2
    assert "configuration error: bad public settings" in caplog.text


def test_main_logs_bind_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        public_main,
        "build_gateway",
        lambda: (object(), "127.0.0.1", 8787, "https://tree.example.com"),
    )

    def fail_bind(*args: object, **kwargs: object) -> None:
        raise OSError("address already in use")

    monkeypatch.setattr(public_main, "create_server", fail_bind)

    with caplog.at_level(logging.ERROR):
        result = public_main.main()

    assert result == 3
    assert "cannot bind loopback port 8787" in caplog.text
    assert "address already in use" in caplog.text


def test_main_distinguishes_asset_load_failure_from_bind_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        public_main,
        "build_gateway",
        lambda: (object(), "127.0.0.1", 8787, "https://tree.example.com"),
    )

    def fail_assets() -> None:
        raise OSError("missing app.js")

    monkeypatch.setattr(public_server, "_load_assets", fail_assets)

    with caplog.at_level(logging.ERROR):
        result = public_main.main()

    assert result == 3
    assert "cannot load public assets" in caplog.text
    assert "cannot bind loopback port" not in caplog.text
