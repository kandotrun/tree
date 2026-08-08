# Balcony Watering Bridge

The bridge turns small, fixed command surfaces into LAN-only requests to the
ATOM Lite. It provides JSON CLI commands for Hermes and a loopback-only public
gateway for a Cloudflare Tunnel running on the same NAS.

## Safety behavior

- No bridge command accepts runtime or volume arguments. The interactive device
  dashboard can send a bounded duration, but Bridge/Hermes deliberately omits it
  and receives the firmware's configured default dose.
- `POST /v1/water` is sent once. A timeout, server error, malformed acceptance,
  or post-preflight conflict response becomes `UNKNOWN`; the bridge does not
  retry. Optional/legacy firmware cooldown responses are handled the same way.
- An unresolved `PENDING`, `ACCEPTED`, or `UNKNOWN` event blocks later watering.
- Tank volume is decremented only after `DOSE_COMPLETE` is confirmed. A manual
  or safety stop remains `UNKNOWN` and does not subtract the full configured dose.
- Hostnames are resolved before connection and every resolved address must be an
  explicitly allowed RFC1918, loopback, link-local, IPv6 ULA, or Tailscale/shared
  address. Requests are never sent to public, documentation, benchmarking,
  multicast, or unspecified address ranges.
- A schedule with no successful manual history skips rather than issuing the
  first dose automatically.
- Reservation, unresolved-event exclusion, and the scheduler's latest-success
  check are committed in one SQLite transaction.
- The anonymous public endpoint fixes every request to 10 seconds, never exposes
  hold mode or a duration field, and atomically applies a global 60-second
  cooldown plus rolling six-per-hour and 24-per-day limits.
- A public POST with an ambiguous result is sent exactly once and remains
  `UNKNOWN`, consuming quota. A definitive 4xx rejection releases the reservation.
- The public HTTP listener accepts loopback only. A foreign browser Origin and
  simple cross-site form content type are rejected before a device request.

## Development

```bash
uv sync --project bridge --extra test --locked
uv run --project bridge pytest bridge/tests
uv run --project bridge ruff check bridge
uv run --project bridge ruff format --check bridge
```

For a local dry status check, copy `config.example.env` and point
`BALCONY_WATERING_ENV_FILE` at the copy. Do not commit it.

## Configuration

Copy [`config.example.env`](config.example.env) to
`/etc/balcony-watering.env`, replace every placeholder, and restrict it to the
service account:

```bash
sudo useradd --system --home /var/lib/balcony-watering \
  --shell /usr/sbin/nologin balcony-watering
sudo install -o balcony-watering -g balcony-watering -m 600 \
  bridge/config.example.env /etc/balcony-watering.env
sudoedit /etc/balcony-watering.env
```

`ATOM_URL` must be an `http://` origin on a private/local address. Set
`DOSE_ML` only after flow calibration; it is an estimate for tank accounting,
not a pump duration. The low-level `AtomClient.water()` mirrors the firmware API
and accepts an optional bounded `duration_sec`, but the shipped bridge service,
CLI, and Hermes commands do not expose or send it. Firmware therefore uses
`DOSE_MS` for every bridge-triggered dose.
The ATOM API intentionally has no application-layer authentication and does not
terminate TLS. Use a trusted WPA2/WPA3 LAN or isolated IoT VLAN. Never expose
the ATOM itself through public ingress. Anonymous Internet access must terminate
at `tree-public-gateway`, which forwards only the bounded surface above.

## NAS public gateway

Copy [`public.example.env`](public.example.env) to a mode-600 runtime file and
set `PUBLIC_ORIGIN` to the public HTTPS origin. Start
`tree-public-gateway` with the included user service, then run cloudflared with
the separate `tree-public-tunnel.service`. Both services are intended for a
long-running NAS account with user lingering enabled; neither requires Docker or
root at runtime.

See [`../docs/public-gateway.md`](../docs/public-gateway.md) for the directory
layout, Tunnel configuration, external verification, and rollback. Do not enable
the public route until `GET /api/status` reports `IDLE`, `armed=true`, and
`pump=false`.

## Moisture telemetry

The package also installs `tree-moisture-logger`, a read-only status poller that
stores ADC and device-state history in SQLite. It never invokes water, stop,
hold, or scheduling endpoints, and its ADC records must not trigger automatic
watering. See [`../docs/moisture-telemetry.md`](../docs/moisture-telemetry.md)
for the NAS user service, retention, verification, and shutdown procedure.

## Production install

The following layout matches the included systemd unit:

```bash
sudo install -d -o root -g root /opt/balcony-watering
sudo python3 -m venv /opt/balcony-watering/venv
sudo /opt/balcony-watering/venv/bin/pip install ./bridge
sudo install -d -o balcony-watering -g balcony-watering \
  /var/lib/balcony-watering
sudo install -m 644 bridge/systemd/balcony-watering-daily.service \
  bridge/systemd/balcony-watering-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

Run fixed commands as the service account:

```bash
sudo -u balcony-watering /opt/balcony-watering/venv/bin/water-tree-status
sudo -u balcony-watering /opt/balcony-watering/venv/bin/water-tree
sudo -u balcony-watering /opt/balcony-watering/venv/bin/water-tree-stop
sudo -u balcony-watering /opt/balcony-watering/venv/bin/water-tree-refill
```

Do **not** enable the timer during commissioning. After flow calibration,
72-hour power testing, siphon/drainage/leak checks, and the two-week supervised
manual pilot all pass:

```bash
sudo systemctl enable --now balcony-watering-daily.timer
```

The timer intentionally does not catch up a missed 07:30 run after reboot. A
late boot skips that day instead of initiating unattended watering at an
unexpected time.

## Output and exit codes

Every invocation prints one UTF-8 JSON object. `message_ja` is suitable for
direct display by Hermes.

| Exit | Meaning |
|---:|---|
| 0 | Success or a safe schedule skip |
| 2 | Invalid/missing configuration |
| 3 | ATOM offline |
| 4 | Definitively rejected, or estimated tank below one dose |
| 5 | Result unknown after `water`/`schedule` operation dispatch, including DB/internal errors; inspect hardware and DB, do not retry |
| 6 | Local SQLite failure before operation dispatch or in a non-actuating command |
| 1 | Unexpected internal error before operation dispatch or in a non-actuating command |

The SQLite DB defaults to `/var/lib/balcony-watering/state.db`. Back it up only
while commands are stopped, or use SQLite's online backup facilities.
