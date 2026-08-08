# Balcony Watering Bridge

The bridge turns a small, fixed command surface into authenticated LAN requests
to the ATOM Lite. It records every attempted dose in SQLite and prints exactly
one JSON object for Hermes or another caller.

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
  address. The bearer token is never sent to public, documentation, benchmarking,
  multicast, or unspecified address ranges.
- A schedule with no successful manual history skips rather than issuing the
  first dose automatically.
- Reservation, unresolved-event exclusion, and the scheduler's latest-success
  check are committed in one SQLite transaction.

## Development

```bash
uv sync --project bridge --extra test --locked
uv run --project bridge pytest bridge/tests
uv run --project bridge ruff check bridge
uv run --project bridge ruff format --check bridge
```

For a local dry status check, copy `config.example.env`, use a test-only token,
and point `BALCONY_WATERING_ENV_FILE` at the copy. Do not commit it.

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
Because the initial ATOM firmware does not terminate TLS, use a trusted
WPA2/WPA3 LAN with no guest clients and never expose the API through public
ingress. Rotate the shared token if the LAN credentials may be compromised.

Generate the same API token for firmware and bridge with, for example:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

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
