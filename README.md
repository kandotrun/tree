# Balcony Watering

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
    H[Hermes Agent] -->|fixed command| B[Linux bridge]
    B -->|LAN-only HTTP + bearer token| A[ATOM Lite]
    A -->|GPIO 26 / ADC 32| U[Unit Watering U101]
```

The ATOM Lite owns the physical safety boundary: pump-off boot, local maximum
runtime, boot guard, cooldown, authenticated fixed-dose requests, and emergency
stop. The bridge owns request IDs, SQLite history, tank estimation, scheduling,
and human-readable results.

## Status

Pre-hardware implementation. Firmware and bridge behavior can be built and
tested now; flashing, flow calibration, waterproofing, power endurance, and
live watering require the purchased hardware.

## Documentation

- [System design (Japanese)](docs/system-design.md)
- [Development guide (Japanese)](docs/development-guide.md)
- [Agent and contributor rules](AGENTS.md)

## License

[MIT](LICENSE)
