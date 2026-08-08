from __future__ import annotations

from pathlib import Path

import pytest

from balcony_watering.config import ConfigError, Settings, load_settings

BASE_ENV = {
    "ATOM_URL": "http://192.168.1.50",
    "DOSE_ML": "800",
    "TANK_USABLE_ML": "18000",
    "LOW_TANK_DOSES": "3",
    "ATOM_CONNECT_TIMEOUT_SEC": "3",
    "ATOM_REQUEST_TIMEOUT_SEC": "5",
    "STATUS_POLL_INTERVAL_SEC": "2",
    "STATUS_POLL_TIMEOUT_SEC": "240",
    "MIN_WATER_INTERVAL_HOURS": "72",
    "BALCONY_WATERING_DB_PATH": "/tmp/watering.db",
}


def test_settings_accept_safe_lan_configuration() -> None:
    settings = Settings.from_mapping(BASE_ENV)

    assert settings.atom_url == "http://192.168.1.50"
    assert not hasattr(settings, "atom_api_token")
    assert settings.dose_ml == 800
    assert settings.tank_usable_ml == 18_000
    assert settings.database_path == Path("/tmp/watering.db")


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("ATOM_URL", "https://example.com", "LAN-only HTTP"),
        ("ATOM_URL", "http://watering.example.com", "private or local host"),
        ("ATOM_URL", "http://192.0.2.1", "private or local host"),
        ("ATOM_URL", "http://198.18.0.1", "private or local host"),
        ("ATOM_URL", "http://255.255.255.255", "private or local host"),
        ("ATOM_URL", "http://0.0.0.0", "private or local host"),
        ("ATOM_URL", "http://192.168.1.50/v1", "origin only"),
        ("ATOM_URL", "http://user:pass@192.168.1.50", "credentials"),
        ("ATOM_URL", "http://192.168.1.50?debug=1", "origin only"),
        ("DOSE_ML", "0", "positive"),
        ("TANK_USABLE_ML", "400", "at least DOSE_ML"),
        ("LOW_TANK_DOSES", "100", "usable tank capacity"),
        ("STATUS_POLL_INTERVAL_SEC", "0", "positive"),
        ("STATUS_POLL_TIMEOUT_SEC", "1", "at least the poll interval"),
        ("ATOM_URL", "http://192.168.1.50:99999", "invalid port"),
        ("BALCONY_WATERING_DB_PATH", "", "must not be empty"),
    ],
)
def test_settings_reject_unsafe_or_invalid_values(key: str, value: str, message: str) -> None:
    env = BASE_ENV | {key: value}

    with pytest.raises(ConfigError, match=message):
        Settings.from_mapping(env)


@pytest.mark.parametrize(
    "url",
    [
        "http://balcony-watering.local",
        "http://balcony-watering:8080",
        "http://127.0.0.1:8080",
        "http://100.64.0.1",
        "http://169.254.1.2",
        "http://[fd00::50]",
        "http://[fe80::1]",
    ],
)
def test_settings_accept_local_host_forms(url: str) -> None:
    assert Settings.from_mapping(BASE_ENV | {"ATOM_URL": url}).atom_url == url


def test_load_settings_uses_environment_over_file(tmp_path: Path) -> None:
    env_file = tmp_path / "watering.env"
    env_file.write_text(
        "\n".join(
            [
                "# local configuration",
                "ATOM_URL=http://192.168.1.10",
                "DOSE_ML=700",
                "TANK_USABLE_ML=18000",
                "LOW_TANK_DOSES=3",
                "ATOM_CONNECT_TIMEOUT_SEC=3",
                "ATOM_REQUEST_TIMEOUT_SEC=5",
                "STATUS_POLL_INTERVAL_SEC=2",
                "STATUS_POLL_TIMEOUT_SEC=240",
                "MIN_WATER_INTERVAL_HOURS=72",
                "BALCONY_WATERING_DB_PATH=/tmp/from-file.db",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(
        env_file=env_file,
        environ={"ATOM_URL": "http://192.168.1.20", "DOSE_ML": "900"},
    )

    assert settings.atom_url == "http://192.168.1.20"
    assert settings.dose_ml == 900
