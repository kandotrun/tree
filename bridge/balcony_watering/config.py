from __future__ import annotations

import ipaddress
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .network_policy import is_allowed_local_address


class ConfigError(ValueError):
    """Raised when bridge configuration is missing or unsafe."""


_LOCAL_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _required(mapping: Mapping[str, str], key: str) -> str:
    value = str(mapping.get(key, "")).strip()
    if not value:
        raise ConfigError(f"{key} is required")
    return value


def _positive_int(mapping: Mapping[str, str], key: str) -> int:
    raw = _required(mapping, key)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be positive")
    return value


def _positive_float(mapping: Mapping[str, str], key: str) -> float:
    raw = _required(mapping, key)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{key} must be positive")
    return value


def _is_local_hostname(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        lowered = hostname.lower().rstrip(".")
        return (
            lowered == "localhost"
            or lowered.endswith(".local")
            or ("." not in lowered and _LOCAL_HOST_RE.fullmatch(lowered) is not None)
        )
    return is_allowed_local_address(address)


def _validate_atom_url(raw: str) -> str:
    parsed = urlsplit(raw)
    if parsed.scheme != "http":
        raise ConfigError("ATOM_URL must use LAN-only HTTP")
    if not parsed.hostname or not _is_local_hostname(parsed.hostname):
        raise ConfigError("ATOM_URL must target a private or local host")
    if parsed.username or parsed.password:
        raise ConfigError("ATOM_URL must not contain credentials")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ConfigError("ATOM_URL has an invalid port") from exc
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ConfigError("ATOM_URL must contain the origin only")
    return raw.rstrip("/")


def _bounded_int(
    mapping: Mapping[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(mapping.get(key, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be from {minimum} through {maximum}")
    return value


def _positive_float_default(
    mapping: Mapping[str, str],
    key: str,
    default: float,
) -> float:
    raw = str(mapping.get(key, default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{key} must be positive")
    return value


def _validate_public_origin(raw: str) -> str:
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConfigError("PUBLIC_ORIGIN must be an HTTPS origin")
    if parsed.username or parsed.password:
        raise ConfigError("PUBLIC_ORIGIN must not contain credentials")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ConfigError("PUBLIC_ORIGIN has an invalid port") from exc
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ConfigError("PUBLIC_ORIGIN must contain the origin only")
    return raw.rstrip("/")


@dataclass(frozen=True, slots=True)
class Settings:
    atom_url: str
    dose_ml: int
    tank_usable_ml: int
    low_tank_doses: int
    connect_timeout_sec: float
    request_timeout_sec: float
    status_poll_interval_sec: float
    status_poll_timeout_sec: float
    min_water_interval_hours: float
    database_path: Path

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> Settings:
        atom_url = _validate_atom_url(_required(mapping, "ATOM_URL"))
        dose_ml = _positive_int(mapping, "DOSE_ML")
        tank_usable_ml = _positive_int(mapping, "TANK_USABLE_ML")
        if tank_usable_ml < dose_ml:
            raise ConfigError("TANK_USABLE_ML must be at least DOSE_ML")
        low_tank_doses = _positive_int(mapping, "LOW_TANK_DOSES")
        if low_tank_doses > tank_usable_ml // dose_ml:
            raise ConfigError("LOW_TANK_DOSES exceeds the usable tank capacity")

        poll_interval = _positive_float(mapping, "STATUS_POLL_INTERVAL_SEC")
        poll_timeout = _positive_float(mapping, "STATUS_POLL_TIMEOUT_SEC")
        if poll_timeout < poll_interval:
            raise ConfigError("STATUS_POLL_TIMEOUT_SEC must be at least the poll interval")

        raw_database_path = str(
            mapping.get("BALCONY_WATERING_DB_PATH", "/var/lib/balcony-watering/state.db")
        ).strip()
        if not raw_database_path:
            raise ConfigError("BALCONY_WATERING_DB_PATH must not be empty")
        database_path = Path(raw_database_path).expanduser()

        return cls(
            atom_url=atom_url,
            dose_ml=dose_ml,
            tank_usable_ml=tank_usable_ml,
            low_tank_doses=low_tank_doses,
            connect_timeout_sec=_positive_float(mapping, "ATOM_CONNECT_TIMEOUT_SEC"),
            request_timeout_sec=_positive_float(mapping, "ATOM_REQUEST_TIMEOUT_SEC"),
            status_poll_interval_sec=poll_interval,
            status_poll_timeout_sec=poll_timeout,
            min_water_interval_hours=_positive_float(mapping, "MIN_WATER_INTERVAL_HOURS"),
            database_path=database_path,
        )


@dataclass(frozen=True, slots=True)
class PublicSettings:
    atom_url: str
    database_path: Path
    listen_host: str
    listen_port: int
    public_origin: str
    duration_sec: int
    cooldown_sec: int
    hourly_limit: int
    daily_limit: int
    connect_timeout_sec: float
    request_timeout_sec: float

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> PublicSettings:
        raw_database_path = str(
            mapping.get("PUBLIC_DATABASE_PATH", "/var/lib/balcony-watering/public.db")
        ).strip()
        if not raw_database_path:
            raise ConfigError("PUBLIC_DATABASE_PATH must not be empty")

        listen_host = str(mapping.get("PUBLIC_LISTEN_HOST", "127.0.0.1")).strip()
        if listen_host not in {"127.0.0.1", "::1"}:
            raise ConfigError("PUBLIC_LISTEN_HOST must be a loopback address")

        hourly_limit = _bounded_int(
            mapping,
            "PUBLIC_HOURLY_LIMIT",
            default=6,
            minimum=1,
            maximum=6,
        )
        daily_limit = _bounded_int(
            mapping,
            "PUBLIC_DAILY_LIMIT",
            default=24,
            minimum=1,
            maximum=24,
        )
        if daily_limit < hourly_limit:
            raise ConfigError("PUBLIC_DAILY_LIMIT must be at least PUBLIC_HOURLY_LIMIT")

        return cls(
            atom_url=_validate_atom_url(_required(mapping, "ATOM_URL")),
            database_path=Path(raw_database_path).expanduser(),
            listen_host=listen_host,
            listen_port=_bounded_int(
                mapping,
                "PUBLIC_LISTEN_PORT",
                default=8787,
                minimum=1,
                maximum=65_535,
            ),
            public_origin=_validate_public_origin(_required(mapping, "PUBLIC_ORIGIN")),
            duration_sec=_bounded_int(
                mapping,
                "PUBLIC_WATER_DURATION_SEC",
                default=10,
                minimum=10,
                maximum=10,
            ),
            cooldown_sec=_bounded_int(
                mapping,
                "PUBLIC_COOLDOWN_SEC",
                default=60,
                minimum=60,
                maximum=3_600,
            ),
            hourly_limit=hourly_limit,
            daily_limit=daily_limit,
            connect_timeout_sec=_positive_float_default(
                mapping,
                "ATOM_CONNECT_TIMEOUT_SEC",
                3,
            ),
            request_timeout_sec=_positive_float_default(
                mapping,
                "ATOM_REQUEST_TIMEOUT_SEC",
                5,
            ),
        )


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"invalid environment line {line_number} in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not key:
            raise ConfigError(f"empty environment key on line {line_number} in {path}")
        values[key] = value
    return values


def load_settings(
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    source = os.environ if environ is None else environ
    selected_path = env_file
    if selected_path is None:
        selected_path = Path(source.get("BALCONY_WATERING_ENV_FILE", "/etc/balcony-watering.env"))
    values = _read_env_file(selected_path)
    values.update(source)
    return Settings.from_mapping(values)


def load_public_settings(
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> PublicSettings:
    source = os.environ if environ is None else environ
    selected_path = env_file
    if selected_path is None:
        selected_path = Path(source.get("PUBLIC_ENV_FILE", "/etc/tree-public.env"))
    values = _read_env_file(selected_path)
    values.update(source)
    return PublicSettings.from_mapping(values)
