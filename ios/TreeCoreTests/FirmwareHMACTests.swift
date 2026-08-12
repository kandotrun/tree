import XCTest
@testable import TreeCore

final class FirmwareHMACTests: XCTestCase {
    func testCanonicalMessageAndKnownHMACSHA256Vector() throws {
        let sha256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        let nonce = String(repeating: "ab", count: 32)
        let currentVersion = try SemanticVersion("1.2.3")
        let newVersion = try SemanticVersion("1.3.0")
        let expectedMessage = [
            "tree-watering-ota-v1",
            "balcony-watering",
            "m5stack-atom",
            "1.2.3",
            "1.3.0",
            "5",
            sha256,
            nonce,
        ].joined(separator: "\n")

        let message = try FirmwareHMAC.canonicalMessage(
            deviceName: "balcony-watering",
            target: "m5stack-atom",
            currentVersion: currentVersion,
            newVersion: newVersion,
            size: 5,
            sha256: sha256,
            nonce: nonce
        )
        let signature = try FirmwareHMAC.signature(
            otaKeyHex: "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
            deviceName: "balcony-watering",
            target: "m5stack-atom",
            currentVersion: currentVersion,
            newVersion: newVersion,
            size: 5,
            sha256: sha256,
            nonce: nonce
        )

        XCTAssertEqual(message, expectedMessage)
        XCTAssertEqual(signature, "31ea1790019aaa078cd61ae0fe4570ad153c61aa7ecd327367dc27cd45e9fa77")
    }

    func testRejectsMalformedAuthenticationInputs() throws {
        let currentVersion = try SemanticVersion("1.2.3")
        let newVersion = try SemanticVersion("1.3.0")
        let sha256 = String(repeating: "0", count: 64)
        let nonce = String(repeating: "1", count: 64)

        XCTAssertThrowsError(
            try FirmwareHMAC.signature(
                otaKeyHex: String(repeating: "AA", count: 32),
                deviceName: "balcony-watering",
                target: "m5stack-atom",
                currentVersion: currentVersion,
                newVersion: newVersion,
                size: 5,
                sha256: sha256,
                nonce: nonce
            )
        )
        XCTAssertThrowsError(
            try FirmwareHMAC.canonicalMessage(
                deviceName: "balcony\nwatering",
                target: "m5stack-atom",
                currentVersion: currentVersion,
                newVersion: newVersion,
                size: 5,
                sha256: sha256,
                nonce: nonce
            )
        )
        XCTAssertThrowsError(
            try FirmwareHMAC.canonicalMessage(
                deviceName: "balcony-watering",
                target: "m5stack-atom",
                currentVersion: currentVersion,
                newVersion: newVersion,
                size: 0,
                sha256: sha256,
                nonce: nonce
            )
        )
    }
}
