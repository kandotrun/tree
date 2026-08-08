from __future__ import annotations

from pathlib import Path

import pytest

from balcony_watering.config import (
    ConfigError,
    PublicSettings,
    load_public_settings,
)

BASE_ENV = {
    "ATOM_URL": "http://192.168.50.50",
    "PUBLIC_DATABASE_PATH": "/tmp/tree-public.db",
    "PUBLIC_ORIGIN": "https://tree.2-38.com",
}


def test_public_settings_have_safe_anonymous_gateway_defaults() -> None:
    settings = PublicSettings.from_mapping(BASE_ENV)

    assert settings.atom_url == "http://192.168.50.50"
    assert settings.database_path == Path("/tmp/tree-public.db")
    assert settings.listen_host == "127.0.0.1"
    assert settings.listen_port == 8787
    assert settings.public_origin == "https://tree.2-38.com"
    assert settings.duration_sec == 10
    assert settings.cooldown_sec == 60
    assert settings.hourly_limit == 6
    assert settings.daily_limit == 24
    assert settings.connect_timeout_sec == 3
    assert settings.request_timeout_sec == 5


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("ATOM_URL", "https://example.com", "LAN-only HTTP"),
        ("PUBLIC_DATABASE_PATH", "", "must not be empty"),
        ("PUBLIC_LISTEN_HOST", "0.0.0.0", "loopback"),
        ("PUBLIC_LISTEN_PORT", "0", "from 1 through 65535"),
        ("PUBLIC_LISTEN_PORT", "65536", "from 1 through 65535"),
        ("PUBLIC_ORIGIN", "http://tree.2-38.com", "HTTPS origin"),
        ("PUBLIC_ORIGIN", "https://user:pass@tree.2-38.com", "credentials"),
        ("PUBLIC_ORIGIN", "https://tree.2-38.com/path", "origin only"),
        ("PUBLIC_WATER_DURATION_SEC", "9", "from 10 through 10"),
        ("PUBLIC_WATER_DURATION_SEC", "11", "from 10 through 10"),
        ("PUBLIC_COOLDOWN_SEC", "59", "from 60 through 3600"),
        ("PUBLIC_HOURLY_LIMIT", "7", "from 1 through 6"),
        ("PUBLIC_DAILY_LIMIT", "25", "from 1 through 24"),
        ("PUBLIC_DAILY_LIMIT", "5", "at least PUBLIC_HOURLY_LIMIT"),
        ("ATOM_CONNECT_TIMEOUT_SEC", "0", "positive"),
        ("ATOM_REQUEST_TIMEOUT_SEC", "nan", "positive"),
    ],
)
def test_public_settings_reject_unsafe_values(key: str, value: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        PublicSettings.from_mapping(BASE_ENV | {key: value})


def test_public_settings_accept_only_loopback_listener_forms() -> None:
    assert (
        PublicSettings.from_mapping(BASE_ENV | {"PUBLIC_LISTEN_HOST": "::1"}).listen_host == "::1"
    )


def test_public_settings_allow_only_tighter_operational_limits() -> None:
    settings = PublicSettings.from_mapping(
        BASE_ENV
        | {
            "PUBLIC_COOLDOWN_SEC": "120",
            "PUBLIC_HOURLY_LIMIT": "3",
            "PUBLIC_DAILY_LIMIT": "12",
        }
    )

    assert settings.cooldown_sec == 120
    assert settings.hourly_limit == 3
    assert settings.daily_limit == 12


def test_load_public_settings_uses_environment_over_file(tmp_path: Path) -> None:
    env_file = tmp_path / "public.env"
    env_file.write_text(
        "\n".join(
            [
                "ATOM_URL=http://192.168.1.10",
                "PUBLIC_DATABASE_PATH=/tmp/from-file.db",
                "PUBLIC_ORIGIN=https://tree.2-38.com",
                "PUBLIC_WATER_DURATION_SEC=9",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_public_settings(
        env_file=env_file,
        environ={
            "ATOM_URL": "http://192.168.1.20",
            "PUBLIC_WATER_DURATION_SEC": "10",
        },
    )

    assert settings.atom_url == "http://192.168.1.20"
    assert settings.duration_sec == 10
    assert settings.database_path == Path("/tmp/from-file.db")
