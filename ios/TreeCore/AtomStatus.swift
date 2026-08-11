import Foundation

public enum AtomState: Equatable, Sendable {
    case bootGuard
    case idle
    case watering
    case error
    case unknown(String)
}

public enum WateringAvailability: Equatable, Sendable {
    case bootGuard
    case ready
    case unarmed
    case watering
    case error
    case unknown
}

extension AtomState: Codable {
    public init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "BOOT_GUARD": self = .bootGuard
        case "IDLE": self = .idle
        case "WATERING": self = .watering
        case "ERROR": self = .error
        default: self = .unknown(value)
        }
    }

    public func encode(to encoder: Encoder) throws {
        let value: String
        switch self {
        case .bootGuard: value = "BOOT_GUARD"
        case .idle: value = "IDLE"
        case .watering: value = "WATERING"
        case .error: value = "ERROR"
        case let .unknown(rawValue): value = rawValue
        }
        var container = encoder.singleValueContainer()
        try container.encode(value)
    }
}

public struct AtomStatus: Codable, Equatable, Sendable {
    public let deviceType: String?
    public let apiVersion: Int?
    public let deviceName: String?
    public let state: AtomState
    public let pump: Bool
    public let uptimeMilliseconds: UInt64
    public let wifiRSSI: Int
    public let moistureADC: Int
    public let armed: Bool
    public let defaultDurationSeconds: Int
    public let maximumDurationSeconds: Int
    public let scheduledMilliseconds: Int
    public let wateringMode: String
    public let holdLeaseMilliseconds: Int
    public let holdMaximumRunMilliseconds: Int
    public let holdLeaseRemainingMilliseconds: Int
    public let lastRequestID: String
    public let remainingMilliseconds: Int
    public let lastRuntimeMilliseconds: Int
    public let lastStopReason: String
    public let firmwareVersion: String
    public let errorReason: String?

    public var wateringAvailability: WateringAvailability {
        switch state {
        case .bootGuard:
            return .bootGuard
        case .idle:
            guard armed else { return .unarmed }
            return pump ? .unknown : .ready
        case .watering:
            return .watering
        case .error:
            return .error
        case .unknown:
            return .unknown
        }
    }

    public var canStartWatering: Bool {
        state == .idle && pump == false && armed
    }

    public var isCompatibleDiscoveryTarget: Bool {
        guard deviceType == "tree-watering",
              apiVersion == 1,
              let deviceName,
              !deviceName.isEmpty,
              !firmwareVersion.isEmpty,
              (1 ... 180).contains(maximumDurationSeconds),
              (1 ... maximumDurationSeconds).contains(defaultDurationSeconds) else {
            return false
        }
        return holdLeaseMilliseconds == 1_500
            && holdMaximumRunMilliseconds == 600_000
    }

    enum CodingKeys: String, CodingKey {
        case deviceType = "device_type"
        case apiVersion = "api_version"
        case deviceName = "device_name"
        case state
        case pump
        case uptimeMilliseconds = "uptime_ms"
        case wifiRSSI = "wifi_rssi"
        case moistureADC = "moisture_adc"
        case armed
        case defaultDurationSeconds = "default_duration_sec"
        case maximumDurationSeconds = "max_duration_sec"
        case scheduledMilliseconds = "scheduled_ms"
        case wateringMode = "watering_mode"
        case holdLeaseMilliseconds = "hold_lease_ms"
        case holdMaximumRunMilliseconds = "hold_max_run_ms"
        case holdLeaseRemainingMilliseconds = "hold_lease_remaining_ms"
        case lastRequestID = "last_request_id"
        case remainingMilliseconds = "remaining_ms"
        case lastRuntimeMilliseconds = "last_runtime_ms"
        case lastStopReason = "last_stop_reason"
        case firmwareVersion = "firmware_version"
        case errorReason = "error_reason"
    }
}
