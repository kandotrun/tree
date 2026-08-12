import Crypto
import Foundation

public enum FirmwareHMAC {
    public static func canonicalMessage(
        deviceName: String,
        target: String,
        currentVersion: SemanticVersion,
        newVersion: SemanticVersion,
        size: Int,
        sha256: String,
        nonce: String
    ) throws -> String {
        guard !deviceName.isEmpty,
              !target.isEmpty,
              !deviceName.contains("\n"),
              !deviceName.contains("\r"),
              !target.contains("\n"),
              !target.contains("\r"),
              size > 0,
              isLowercaseHex(sha256, byteCount: 32),
              isLowercaseHex(nonce, byteCount: 32) else {
            throw FirmwareValidationError.invalidAuthorization
        }
        return [
            "tree-watering-ota-v1",
            deviceName,
            target,
            currentVersion.rawValue,
            newVersion.rawValue,
            String(size),
            sha256,
            nonce,
        ].joined(separator: "\n")
    }

    public static func signature(
        otaKeyHex: String,
        deviceName: String,
        target: String,
        currentVersion: SemanticVersion,
        newVersion: SemanticVersion,
        size: Int,
        sha256: String,
        nonce: String
    ) throws -> String {
        guard isLowercaseHex(otaKeyHex, byteCount: 32),
              let keyData = data(fromLowercaseHex: otaKeyHex) else {
            throw FirmwareValidationError.invalidAuthorization
        }
        let message = try canonicalMessage(
            deviceName: deviceName,
            target: target,
            currentVersion: currentVersion,
            newVersion: newVersion,
            size: size,
            sha256: sha256,
            nonce: nonce
        )
        let code = HMAC<SHA256>.authenticationCode(
            for: Data(message.utf8),
            using: SymmetricKey(data: keyData)
        )
        return hexadecimalString(code)
    }

    private static func data(fromLowercaseHex value: String) -> Data? {
        var bytes: [UInt8] = []
        bytes.reserveCapacity(value.utf8.count / 2)
        var index = value.startIndex
        while index < value.endIndex {
            let next = value.index(index, offsetBy: 2)
            guard let byte = UInt8(value[index ..< next], radix: 16) else {
                return nil
            }
            bytes.append(byte)
            index = next
        }
        return Data(bytes)
    }
}
