# AGENTS.md

## Goal

Build a fail-safe balcony watering system. The highest-priority invariant is
that the pump turns off locally even if Wi-Fi, the bridge, or Hermes fails.

## Safety invariants

- Set GPIO 26 to `OUTPUT` and `LOW` before Wi-Fi or any other peripheral setup.
- Never accept a client-supplied volume. A one-shot interactive request may
  include only an integer `duration_sec` bounded to 1-180 seconds and
  `MAX_RUN_MS`. Bridge/Hermes commands stay fixed and do not expose runtime.
- Longer manual watering is allowed only through the fixed firmware hold mode:
  a 1,500 ms device-local lease, 500 ms browser heartbeat, matching active
  `request_id`, and a 600,000 ms absolute session cap. A keepalive must never
  start or restart a pump, and timer renewal must never re-arm a fired safety
  gate.
- Never retry `POST /v1/water` automatically after an ambiguous network result.
- On ambiguous hold start or failed keepalive, send best-effort stop without
  retrying start; loss of heartbeats must still stop the pump locally.
- Persist the accepted request ID before physically enabling the pump.
- Keep the ATOM API LAN-only. Never route public DNS, port forwarding, or a
  Tunnel directly to the ATOM or its embedded dashboard.
- The only approved public ingress is the NAS gateway. It exposes a fixed
  short dose and stop, binds to loopback behind Cloudflare Tunnel, persists a
  global cooldown and rolling quotas in SQLite, rejects client-selected
  duration, and never exposes hold mode.
- The ATOM watering/status API, embedded dashboard, and public gateway
  intentionally have no application-layer authentication. Firmware maintenance
  is the only exception: physical-button pairing, a device-local key, a fresh
  one-time nonce, and HMAC-SHA256 are required for every OTA upload.
- OTA must cut GPIO 26 `LOW` before flash writes, reject non-idle or active-pump
  states, validate target/version/size/streamed SHA-256 before switching the boot
  partition, and never retry an ambiguous upload automatically.
- Public OTA images must use `config.example.h` with
  `PROVISIONING_REVISION 0`. Never release a binary built from local `config.h`.
  The public gateway remains anonymous by design; its bounded command surface
  and device-local cutoff are the watering safety boundary.
- Keep automatic scheduling disabled until calibration, 72-hour power testing,
  siphon/drainage/leak checks, and a two-week supervised pilot pass.
- Do not use moisture ADC values as an automatic start condition until real
  calibration data exists.
- Keep dashboard calibration browser-local and non-actuating.

## Public repository rules

- Commit examples only. Never commit Wi-Fi credentials, private
  IP inventories, SSH/Tailscale material, runtime databases, or real logs.
- Use placeholders in screenshots and documentation.
- Run a staged-file secret scan before every push.

## Development workflow

Use RED -> GREEN -> REFACTOR for behavior changes.

```bash
# Bridge
uv sync --project bridge --extra test
uv run --project bridge pytest
uv run --project bridge ruff check bridge
uv run --project bridge ruff format --check bridge

# Firmware
cd firmware
pio test -e native
pio run -e m5stack-atom
```

Run `git diff --check` and inspect the full diff before committing. Hardware
claims must be marked unverified until exercised on the physical device.

## Repository map

- `firmware/`: ATOM Lite firmware and host-side state-machine tests
- `bridge/`: NAS CLI/public gateway, SQLite state, and tests
- `docs/`: design and staged commissioning procedure
- `scripts/`: flashing and serial-monitor helpers
