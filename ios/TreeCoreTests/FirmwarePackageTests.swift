import Foundation
import XCTest
@testable import TreeCore

final class FirmwarePackageTests: XCTestCase {
    private static let hello = Data("hello".utf8)
    private static let helloSHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    func testDecodesFirmwareCapabilityContract() throws {
        let capability = try makeCapability()

        XCTAssertEqual(capability.deviceType, "tree-watering")
        XCTAssertEqual(capability.apiVersion, 1)
        XCTAssertEqual(capability.target, "m5stack-atom")
        XCTAssertEqual(capability.currentVersion, try SemanticVersion("1.2.3"))
        XCTAssertTrue(capability.otaSupported)
        XCTAssertTrue(capability.paired)
        XCTAssertFalse(capability.pairingWindowOpen)
        XCTAssertEqual(capability.maxFirmwareBytes, 1_048_576)
    }

    func testCapabilityRejectsNoncanonicalCurrentVersion() throws {
        XCTAssertThrowsError(try makeCapability(currentVersion: "01.2.3"))
    }

    func testPairResponseRequiresExactlyLowercaseSHA256SizedKey() throws {
        let validKey = String(repeating: "ab", count: 32)
        let response = try JSONDecoder().decode(
            FirmwarePairResponse.self,
            from: jsonData(["paired": true, "ota_key": validKey])
        )

        XCTAssertTrue(response.paired)
        XCTAssertEqual(response.otaKey, validKey)

        for invalidKey in [
            String(repeating: "ab", count: 31),
            String(repeating: "ab", count: 33),
            String(repeating: "AB", count: 32),
            String(repeating: "gg", count: 32),
        ] {
            XCTAssertThrowsError(
                try JSONDecoder().decode(
                    FirmwarePairResponse.self,
                    from: jsonData(["paired": true, "ota_key": invalidKey])
                ),
                invalidKey
            )
        }
    }

    func testChallengeRequiresExactlyLowercaseSHA256SizedNonce() throws {
        let validNonce = String(repeating: "01", count: 32)
        let challenge = try JSONDecoder().decode(
            FirmwareChallenge.self,
            from: jsonData(["nonce": validNonce, "expires_in_ms": 30_000])
        )

        XCTAssertEqual(challenge.nonce, validNonce)
        XCTAssertEqual(challenge.expiresInMilliseconds, 30_000)

        for invalidNonce in [
            String(repeating: "01", count: 31),
            String(repeating: "01", count: 33),
            String(repeating: "AF", count: 32),
            String(repeating: "xz", count: 32),
        ] {
            XCTAssertThrowsError(
                try JSONDecoder().decode(
                    FirmwareChallenge.self,
                    from: jsonData(["nonce": invalidNonce, "expires_in_ms": 30_000])
                ),
                invalidNonce
            )
        }
    }

    func testBuildsValidatedFirmwarePackage() throws {
        let manifest = try makeManifest(sourceSHA: "abc123")

        let package = try FirmwarePackage(
            manifest: manifest,
            firmwareData: Self.hello,
            capability: makeCapability()
        )

        XCTAssertEqual(package.manifest.firmwareVersion, try SemanticVersion("1.2.4"))
        XCTAssertEqual(package.manifest.sourceSHA, "abc123")
        XCTAssertEqual(package.firmwareData, Self.hello)
    }

    func testRejectsUnsupportedManifestSchema() throws {
        XCTAssertThrowsError(
            try makePackage(manifest: makeManifest(schemaVersion: 2))
        )
    }

    func testRejectsWrongManifestDeviceType() throws {
        XCTAssertThrowsError(
            try makePackage(manifest: makeManifest(deviceType: "other-device"))
        )
    }

    func testRejectsWrongManifestTarget() throws {
        XCTAssertThrowsError(
            try makePackage(manifest: makeManifest(target: "other-target"))
        )
    }

    func testRejectsFirmwareThatIsNotStrictlyNewer() throws {
        for version in ["1.2.3", "1.2.2"] {
            XCTAssertThrowsError(
                try makePackage(manifest: makeManifest(firmwareVersion: version)),
                version
            )
        }
    }

    func testRejectsUnsafeFirmwareAssetNames() throws {
        for assetName in ["", ".", "..", "../firmware.bin", "dir/firmware.bin", #"dir\firmware.bin"#] {
            XCTAssertThrowsError(
                try makePackage(manifest: makeManifest(firmwareAsset: assetName)),
                assetName
            )
        }
    }

    func testRejectsNonpositiveOrOversizedManifestSize() throws {
        XCTAssertThrowsError(
            try makePackage(manifest: makeManifest(size: 0), firmwareData: Data())
        )
        XCTAssertThrowsError(
            try makePackage(
                manifest: makeManifest(size: 5),
                firmwareData: Self.hello,
                capability: makeCapability(maxFirmwareBytes: 4)
            )
        )
    }

    func testRejectsActualFirmwareSizeMismatch() throws {
        XCTAssertThrowsError(
            try makePackage(manifest: makeManifest(size: 5), firmwareData: Data("hell".utf8))
        )
    }

    func testRejectsActualFirmwareHashMismatch() throws {
        XCTAssertThrowsError(
            try makePackage(manifest: makeManifest(), firmwareData: Data("jello".utf8))
        )
    }

    func testManifestRejectsMalformedSHA256() throws {
        for digest in [
            String(repeating: "0", count: 63),
            String(repeating: "0", count: 65),
            String(repeating: "A", count: 64),
            String(repeating: "z", count: 64),
        ] {
            XCTAssertThrowsError(try makeManifest(sha256: digest), digest)
        }
    }

    private func makePackage(
        manifest: FirmwareManifest,
        firmwareData: Data = hello,
        capability: FirmwareCapability? = nil
    ) throws -> FirmwarePackage {
        try FirmwarePackage(
            manifest: manifest,
            firmwareData: firmwareData,
            capability: capability ?? makeCapability()
        )
    }

    private func makeCapability(
        currentVersion: String = "1.2.3",
        maxFirmwareBytes: Int = 1_048_576
    ) throws -> FirmwareCapability {
        try JSONDecoder().decode(
            FirmwareCapability.self,
            from: jsonData([
                "device_type": "tree-watering",
                "api_version": 1,
                "target": "m5stack-atom",
                "current_version": currentVersion,
                "ota_supported": true,
                "paired": true,
                "pairing_window_open": false,
                "max_firmware_bytes": maxFirmwareBytes,
            ])
        )
    }

    private func makeManifest(
        schemaVersion: Int = 1,
        deviceType: String = "tree-watering",
        target: String = "m5stack-atom",
        firmwareVersion: String = "1.2.4",
        firmwareAsset: String = "firmware.bin",
        sha256: String = helloSHA256,
        size: Int = 5,
        sourceSHA: String? = nil
    ) throws -> FirmwareManifest {
        var object: [String: Any] = [
            "schema_version": schemaVersion,
            "device_type": deviceType,
            "target": target,
            "firmware_version": firmwareVersion,
            "firmware_asset": firmwareAsset,
            "sha256": sha256,
            "size": size,
        ]
        if let sourceSHA {
            object["source_sha"] = sourceSHA
        }
        return try JSONDecoder().decode(FirmwareManifest.self, from: jsonData(object))
    }

    private func jsonData(_ object: Any) throws -> Data {
        try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }
}
