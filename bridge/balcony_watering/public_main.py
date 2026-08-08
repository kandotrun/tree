from __future__ import annotations

import logging
import secrets
import sys
import time

from .atom_client import AtomClient
from .config import ConfigError, load_public_settings
from .public_gateway import PublicGateway
from .public_server import create_server
from .public_state import PublicActionStore, PublicLimits


def build_gateway() -> tuple[PublicGateway, str, int, str]:
    settings = load_public_settings()
    atom = AtomClient(
        settings.atom_url,
        connect_timeout_sec=settings.connect_timeout_sec,
        request_timeout_sec=settings.request_timeout_sec,
    )
    gateway = PublicGateway(
        atom=atom,
        store=PublicActionStore(settings.database_path),
        limits=PublicLimits(
            duration_sec=settings.duration_sec,
            cooldown_sec=settings.cooldown_sec,
            hourly_limit=settings.hourly_limit,
            daily_limit=settings.daily_limit,
        ),
        now_ms=lambda: time.time_ns() // 1_000_000,
        monotonic_ms=lambda: time.monotonic_ns() // 1_000_000,
        request_id_factory=lambda: f"pub-{secrets.token_hex(16)}",
    )
    return gateway, settings.listen_host, settings.listen_port, settings.public_origin


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        gateway, host, port, public_origin = build_gateway()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    server = create_server(
        (host, port),
        gateway=gateway,
        public_origin=public_origin,
    )
    logging.getLogger(__name__).info("public gateway listening on loopback port %d", port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
