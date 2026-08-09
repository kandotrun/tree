# 木のみず — iOS

SwiftUI client for the LAN-only ATOM Lite watering controller. The app talks
straight to the firmware API; it has no cloud service, login, analytics, or
embedded installed-device address.

## Safety behavior

- Only `http://` private IPv4, loopback/link-local, IPv6 local, and `.local`
  endpoints are accepted.
- A bounded dose is confirmed by the user and sent exactly once. Transport or
  malformed-acknowledgement failures are treated as ambiguous and are never
  retried automatically.
- The stop control remains visible while the pump is reported active or an
  action result is ambiguous.
- Press-and-hold watering renews the firmware's 1,500 ms lease every 500 ms.
  Releasing the touch, backgrounding the app, a heartbeat error, or an
  ambiguous hold acknowledgement sends a best-effort stop. The firmware lease
  and ten-minute absolute cutoff remain the physical authority.
- Raw moisture ADC is displayed without inventing a percentage before dry/wet
  calibration exists.

## Requirements

- Xcode 15 or later
- iOS 17 or later
- [XcodeGen](https://github.com/yonaskolb/XcodeGen)

## Generate and run

```bash
brew install xcodegen
xcodegen generate --spec ios/project.yml
open ios/TreeWatering.xcodeproj
```

Choose a Development Team in Xcode before installing on a physical iPhone. On
first launch, enter the ATOM's current LAN address, such as
`http://192.168.1.50`. The iPhone and ATOM must be on the same trusted Wi-Fi.
The app requests iOS Local Network permission on the first connection.

## Test

Core API and control safety tests run as a cross-platform Swift package:

```bash
swift test --package-path ios
python3 -m unittest discover -s ios/tests -v
```

The `iOS` GitHub Actions workflow additionally generates the Xcode project,
builds and launches the app in an iPhone Simulator, captures the first-run
screen, and uploads the unsigned simulator `.app` as an artifact.

`TreeWatering.xcodeproj`, SwiftPM build state, DerivedData, and local endpoint
settings are generated/local-only and must not be committed.
