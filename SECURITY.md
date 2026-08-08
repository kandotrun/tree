# Security policy

## Safety first

This repository controls a physical water pump. If a deployed device behaves
unexpectedly, disconnect its power and close or remove the water source before
debugging. Do not rely on a network stop command as the only response to an
active leak or uncontrolled flow.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** private reporting flow for this
repository. Do not open a public issue containing credentials, private network
details, or an exploit that could activate a pump.

Include the affected commit/version, impact, reproduction steps that do not
operate a real pump where possible, and a proposed mitigation. Never include a
real Wi-Fi password, private IP inventory, SSH key, runtime DB, or
production log.

## Supported version

Only the latest `main` branch is supported before the first stable release.
Hardware operation remains experimental until the commissioning checklist in
`docs/development-guide.md` is complete.

## Public gateway boundary

The ATOM Lite remains LAN-only. Do not expose its port, embedded dashboard, or
`/v1/*` routes directly to the Internet. The supported public path terminates at
the NAS gateway described in `docs/public-gateway.md`. It intentionally permits
anonymous use but exposes only a fixed short dose, status, and stop, with
persistent global cooldown and rolling quotas. Reports that bypass those bounds,
reach hold mode, select a duration, race the reservation, or disclose private
device/network data are security issues.
