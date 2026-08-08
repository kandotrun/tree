# AGENTS.md

## Goal

Build a fail-safe balcony watering system. The highest-priority invariant is
that the pump turns off locally even if Wi-Fi, the bridge, or Hermes fails.

## Safety invariants

- Set GPIO 26 to `OUTPUT` and `LOW` before Wi-Fi or any other peripheral setup.
- Never accept a client-supplied volume. An interactive request may include only
  an integer `duration_sec` bounded to 1-180 seconds and `MAX_RUN_MS`; keep the
  independent local cutoff authoritative. Bridge/Hermes commands stay fixed and
  do not expose a runtime argument.
- Never retry `POST /v1/water` automatically after an ambiguous network result.
- Persist the accepted request ID before physically enabling the pump.
- Keep the API LAN-only. Never add port forwarding, public ingress, or secrets.
- Keep automatic scheduling disabled until calibration, 72-hour power testing,
  siphon/drainage/leak checks, and a two-week supervised pilot pass.
- Do not use moisture ADC values as an automatic start condition until real
  calibration data exists.
- Keep dashboard calibration browser-local and non-actuating. Never persist the
  bearer token beyond `sessionStorage` or embed it in dashboard assets.

## Public repository rules

- Commit examples only. Never commit Wi-Fi credentials, bearer tokens, private
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
- `bridge/`: Linux CLI, SQLite state, and tests
- `docs/`: design and staged commissioning procedure
- `scripts/`: flashing and serial-monitor helpers
