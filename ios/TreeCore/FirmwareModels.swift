import Crypto
import Foundation

public enum FirmwareValidationError: Error, Equatable, Sendable {
    case invalidVersion
    case invalidHex
    case invalidCapability
    case invalidPairResponse
    case invalidChallenge
    case invalidManifest
    case invalidPackage
    case invalidAuthorization
}

@inline(__always)
func isLowercaseHex(_ value: String, byteCount: Int) -> Bool {
    value.utf8.count == byteCount * 2
        && value.utf8.allSatisfy { byte in
            (48 ... 57).contains(byte) || (97 ... 102).contains(byte)
        }
}

func hexadecimalString<S: Sequence>(_ bytes: S) -> String where S.Element == UInt8 {
    bytes.map { String(format: "%02x", $0) }.joined()
}

public struct FirmwareCapability: Decodable, Equatable, Sendable {
    public let deviceType: String
    public let apiVersion: Int
    public let target: String
    public let currentVersion: SemanticVersion
    public let otaSupported: Bool
    public let paired: Bool
    public let pairingWindowOpen: Bool
    public let maxFirmwareBytes: Int

    enum CodingKeys: String, CodingKey {
        case deviceType = "device_type"
        case apiVersion = "api_version"
        case target
        case currentVersion = "current_version"
        case otaSupported = "ota_supported"
        case paired
        case pairingWindowOpen = "pairing_window_open"
        case maxFirmwareBytes = "max_firmware_bytes"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        deviceType = try container.decode(String.self, forKey: .deviceType)
        apiVersion = try container.decode(Int.self, forKey: .apiVersion)
        target = try container.decode(String.self, forKey: .target)
        currentVersion = try container.decode(SemanticVersion.self, forKey: .currentVersion)
        otaSupported = try container.decode(Bool.self, forKey: .otaSupported)
        paired = try container.decode(Bool.self, forKey: .paired)
        pairingWindowOpen = try container.decode(Bool.self, forKey: .pairingWindowOpen)
        maxFirmwareBytes = try container.decode(Int.self, forKey: .maxFirmwareBytes)
        guard deviceType == "tree-watering",
              apiVersion == 1,
              target == "m5stack-atom",
              otaSupported,
              maxFirmwareBytes > 0 else {
            throw FirmwareValidationError.invalidCapability
        }
    }
}

public struct FirmwarePairResponse: Decodable, Equatable, Sendable {
    public let paired: Bool
    public let otaKey: String

    enum CodingKeys: String, CodingKey {
        case paired
        case otaKey = "ota_key"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        paired = try container.decode(Bool.self, forKey: .paired)
        otaKey = try container.decode(String.self, forKey: .otaKey)
        guard paired, isLowercaseHex(otaKey, byteCount: 32) else {
            throw FirmwareValidationError.invalidPairResponse
        }
    }
}

public struct FirmwareChallenge: Decodable, Equatable, Sendable {
    public let nonce: String
    public let expiresInMilliseconds: Int

    enum CodingKeys: String, CodingKey {
        case nonce
        case expiresInMilliseconds = "expires_in_ms"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        nonce = try container.decode(String.self, forKey: .nonce)
        expiresInMilliseconds = try container.decode(Int.self, forKey: .expiresInMilliseconds)
        guard isLowercaseHex(nonce, byteCount: 32), expiresInMilliseconds > 0 else {
            throw FirmwareValidationError.invalidChallenge
        }
    }
}

public struct FirmwareManifest: Decodable, Equatable, Sendable {
    public let schemaVersion: Int
    public let deviceType: String
    public let target: String
    public let firmwareVersion: SemanticVersion
    public let firmwareAsset: String
    public let sha256: String
    public let size: Int
    public let sourceSHA: String?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case deviceType = "device_type"
        case target
        case firmwareVersion = "firmware_version"
        case firmwareAsset = "firmware_asset"
        case sha256
        case size
        case sourceSHA = "source_sha"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(Int.self, forKey: .schemaVersion)
        deviceType = try container.decode(String.self, forKey: .deviceType)
        target = try container.decode(String.self, forKey: .target)
        firmwareVersion = try container.decode(SemanticVersion.self, forKey: .firmwareVersion)
        firmwareAsset = try container.decode(String.self, forKey: .firmwareAsset)
        sha256 = try container.decode(String.self, forKey: .sha256)
        size = try container.decode(Int.self, forKey: .size)
        sourceSHA = try container.decodeIfPresent(String.self, forKey: .sourceSHA)
        guard isLowercaseHex(sha256, byteCount: 32) else {
            throw FirmwareValidationError.invalidManifest
        }
    }
}

public struct FirmwarePackage: Equatable, Sendable {
    public let manifest: FirmwareManifest
    public let firmwareData: Data

    public init(
        manifest: FirmwareManifest,
        firmwareData: Data,
        capability: FirmwareCapability
    ) throws {
        let safeAsset = !manifest.firmwareAsset.isEmpty
            && manifest.firmwareAsset != "."
            && manifest.firmwareAsset != ".."
            && !manifest.firmwareAsset.contains("/")
            && !manifest.firmwareAsset.contains("\\")
        let digest = hexadecimalString(SHA256.hash(data: firmwareData))
        guard manifest.schemaVersion == 1,
              manifest.deviceType == capability.deviceType,
              manifest.target == capability.target,
              manifest.firmwareVersion > capability.currentVersion,
              safeAsset,
              manifest.size > 0,
              manifest.size <= capability.maxFirmwareBytes,
              firmwareData.count == manifest.size,
              digest == manifest.sha256 else {
            throw FirmwareValidationError.invalidPackage
        }
        self.manifest = manifest
        self.firmwareData = firmwareData
    }
}

public struct FirmwareUpdateAcknowledgement: Decodable, Equatable, Sendable {
    public let accepted: Bool
    public let firmwareVersion: SemanticVersion
    public let restarting: Bool

    enum CodingKeys: String, CodingKey {
        case accepted
        case firmwareVersion = "firmware_version"
        case restarting
    }
}

public protocol AtomFirmwareAPI: Sendable {
    func fetchFirmwareCapability() async throws -> FirmwareCapability
    func pairFirmware() async throws -> FirmwarePairResponse
    func requestFirmwareChallenge() async throws -> FirmwareChallenge
    func updateFirmware(
        package: FirmwarePackage,
        nonce: String,
        signature: String
    ) async throws -> FirmwareUpdateAcknowledgement
}
