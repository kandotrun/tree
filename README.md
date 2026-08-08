# Balcony Watering

[![CI](https://github.com/kandotrun/tree/actions/workflows/ci.yml/badge.svg)](https://github.com/kandotrun/tree/actions/workflows/ci.yml)

A fail-safe, LAN-only watering controller for one balcony tree, built with an
M5Stack ATOM Lite, Unit Watering U101, and a small Linux bridge.

> [!CAUTION]
> This project controls a real water pump. Keep the outlet over a measuring
> container until flow calibration, timeout, power, drainage, leak, and siphon
> tests all pass. Automatic scheduling must remain disabled during the initial
> two-week supervised pilot.

## Architecture

```mermaid
flowchart LR
    W[LAN browser] -->|dashboard + bounded manual request| A[ATOM Lite]
    H[Hermes Agent] -->|fixed command| B[Linux bridge]
    B -->|LAN-only HTTP + bearer token| A[ATOM Lite]
    A -->|GPIO 26 / ADC 32| U[Unit Watering U101]
```

The ATOM Lite owns the physical safety boundary: pump-off boot, an independent
one-shot cutoff plus watchdog, five-minute boot guard, authenticated bounded-duration
requests, request deduplication, and emergency stop. The bridge owns
request IDs, SQLite history, tank estimation, scheduling decisions, and
machine-readable results.

## Safety model

- GPIO 26 is configured as `OUTPUT` and driven `LOW` before Wi-Fi, NVS, LED, or
  sensor setup. U101's official schematic also shows a 10 kΩ gate-to-source
  pull-down (`R1`) on its active-high N-MOSFET switch, keeping the pump off while
  the host GPIO is high-impedance during reset.
- The dashboard may request an integer `duration_sec` from 1 to 180. Firmware
  validates it against `MAX_RUN_MS` and retains an independent 180-second local
  cutoff. No client can request volume or bypass the cutoff. Bridge/Hermes
  commands intentionally omit duration and use the configured default dose.
- The accepted request ID is persisted before the physical pump pin goes high.
- The default cooldown is zero: after a dose completes or is manually stopped,
  a new request with a distinct ID can start immediately. The active dose still
  stops at its accepted duration and never becomes an unbounded run.
- An ambiguous `POST /v1/water` is never retried automatically. The event stays
  `UNKNOWN` and blocks later watering until an operator investigates.
- Firmware starts **unarmed**. `WATERING_ARMED` must remain `false` until the
  outlet points into a measuring container and commissioning checks pass.
- The bridge refuses public destinations, and the ATOM API must not be exposed
  through port forwarding or public ingress.
- HTTP bearer authentication assumes a trusted WPA2/WPA3 LAN. Do not place the
  ATOM on a guest or otherwise untrusted network; rotate both token copies after
  any LAN credential compromise.

Software safety controls reduce risk; they do not replace drainage, leak,
siphon, power, weatherproofing, and physical inspection.

## Repository map

```text
firmware/  ESP32 firmware and host-side state-machine tests
bridge/    Fixed-command Linux CLI, SQLite state, and tests
docs/      Japanese design and staged commissioning guide
scripts/   Flash and serial-monitor helpers
```

## Build and test

### Firmware

Install PlatformIO Core, then build with the checked-in safe placeholder config:

```bash
uv tool install --with pip 'platformio==6.1.19'
cp firmware/include/config.example.h firmware/include/config.h
cd firmware
pio test -e native
pio run -e m5stack-atom
```

`config.h` is ignored by Git. Replace the placeholders locally and use a random
32-byte-or-longer API token. Keep `WATERING_ARMED false` for the first flash.
See [the development guide](docs/development-guide.md) before connecting U101.

### Embedded dashboard

After flashing firmware v0.2 or later, open the ATOM Lite's LAN address in a
browser. The device serves a mobile-first dashboard with live ADC history,
browser-local dry/wet calibration, bounded 1-180 second manual watering,
confirmation, and emergency stop. Enter the bearer token when prompted; it is
kept in `sessionStorage` for the current tab only. Moisture percentages are
reference-only and never trigger watering automatically.

When editing `firmware/web/index.html`, regenerate and verify the compressed
flash asset:

```bash
python3 firmware/scripts/generate_dashboard_header.py
python3 firmware/scripts/generate_dashboard_header.py --check
```

### Bridge

```bash
uv sync --project bridge --extra test --locked
uv run --project bridge pytest bridge/tests
uv run --project bridge ruff check bridge
uv run --project bridge ruff format --check bridge
```

The installed package exposes only fixed commands:

```text
water-tree           Request one configured dose
water-tree-status    Read ATOM and tank state
water-tree-stop      Stop the pump immediately
water-tree-refill    Reset estimated usable tank volume
water-tree-schedule  Water only when the configured interval is due
```

There is deliberately no runtime or volume argument. See
[`bridge/README.md`](bridge/README.md) for configuration, JSON output, exit
codes, and the optional systemd timer.

## Current status

- Firmware compiles for `m5stack-atom` and its pure safety state machine has
  native tests.
- Bridge behavior, SQLite transitions, HTTP handling, and no-retry semantics
  have automated tests.
- Firmware v0.1 was physically flashed and verified for boot guard, authentication,
  unarmed refusal, one 10-second dose, and local `DOSE_COMPLETE` stop. The v0.2
  variable-duration API and embedded dashboard are built and browser-tested but
  still require the next USB flash and physical commissioning run.
- Measured flow, waterproofing, power endurance, drainage, siphon behavior, and
  the supervised pilot remain incomplete.
- Automatic scheduling remains disabled by default.

## Documentation

- [System design (Japanese)](docs/system-design.md)
- [Development and commissioning guide (Japanese)](docs/development-guide.md)
- [Agent and contributor rules](AGENTS.md)
- [Security policy](SECURITY.md)

## Public repository policy

Commit examples only. Never commit Wi-Fi credentials, bearer tokens, private
network inventories, SSH/Tailscale material, runtime databases, or real logs.
Use a staged-file secret scan before every push.

## License

[MIT](LICENSE)
