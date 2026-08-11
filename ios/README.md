# 木のみず — iOS

SwiftUI client for the LAN-only ATOM Lite watering controller. The app talks
straight to the firmware API; it has no cloud service, login, analytics, or
embedded installed-device address.

## Safety behavior

- Only `http://` private IPv4, loopback/link-local, IPv6 local, and `.local`
  endpoints are accepted.
- On first launch the app browses only `_tree-watering._tcp` on the local
  network and accepts only the fixed `balcony-watering` service instance. A
  discovered endpoint is saved only after a read-only `/v1/status` response
  identifies `device_type=tree-watering`, API version 1, the same device name,
  and the expected firmware safety limits. Discovery never calls
  a watering or stop endpoint.
- A bounded dose is confirmed by the user and sent exactly once. Transport or
  malformed-acknowledgement failures are treated as ambiguous and are never
  retried automatically.
- The stop control remains visible while the pump is reported active or an
  action result is ambiguous. It deliberately stays opaque red instead of
  Liquid Glass, appears without a transition, and remains retryable while a
  previous stop confirmation is still pending.
- Endpoint changes are blocked during watering operations. If the old endpoint
  is unreachable after an unconfirmed stop, switching requires explicit
  confirmation that the pump is physically stopped or powered off.
- Press-and-hold watering renews the firmware's 1,500 ms lease every 500 ms.
  Releasing the touch, backgrounding the app, a heartbeat error, or an
  ambiguous hold acknowledgement sends a best-effort stop. The firmware lease
  and ten-minute absolute cutoff remain the physical authority.
- Raw moisture ADC is displayed without inventing a percentage before dry/wet
  calibration exists.
- Firmware checks and installs are manual only. The app never installs on launch
  and never retries an ambiguous upload. Pairing requires a three-second press
  on the ATOM button; the resulting device-scoped key stays in the iOS Keychain.
- OTA is available only while the controller is idle and the pump is reported
  off. Use stable power, verify the target/version/hash, and confirm the
  destructive action before upload.

## Requirements

- Xcode 26 or later
- iOS 26 or later（native Liquid Glass対応。緊急停止面のみ安全上不透明）
- [XcodeGen](https://github.com/yonaskolb/XcodeGen)

## Generate and run

```bash
brew install xcodegen
xcodegen generate --spec ios/project.yml
open ios/TreeWatering.xcodeproj
```

The generated app icons under `TreeWatering/Resources/Assets.xcassets` are
committed, so normal builds do not require Pillow or the generator script.
To regenerate the icons from the `ios/` directory:

```bash
python3 -m venv .venv-icon
source .venv-icon/bin/activate
python3 -m pip install -r scripts/requirements.txt
python3 scripts/generate_icon.py
```

Choose a Development Team in Xcode before installing on a physical iPhone.
Firmware 0.5.0 or later advertises `balcony-watering.local` through Bonjour;
on first launch the app scans the trusted local Wi-Fi, validates the read-only
status contract, and connects automatically. Manual `http://<ATOM_LAN_IP>`
entry remains under **手動で設定** for recovery. The app requests iOS Local
Network permission when discovery starts. Older firmware does not qualify for
automatic connection and must be updated or configured manually.

Firmware 0.5.x and earlier need one USB flash before the app can perform later
OTA updates. See [`docs/firmware-ota.md`](../docs/firmware-ota.md) for physical
pairing, release packaging, failure handling, and the hardware verification
checklist.

## Test

Core API and control safety tests run as a cross-platform Swift package:

```bash
swift test --package-path ios
python3 -m unittest discover -s ios/tests -v
```

The `iOS` GitHub Actions workflow additionally generates the Xcode project on
macOS 26, builds and launches the app in an iPhone Simulator, captures setup,
dashboard, and watering screens, and uploads the unsigned simulator `.app` as
an artifact.

`TreeWatering.xcodeproj`, SwiftPM build state, DerivedData, and local endpoint
settings are generated/local-only and must not be committed.
