import Foundation

public struct SemanticVersion: RawRepresentable, Codable, Comparable, Hashable, Sendable, CustomStringConvertible {
    public let rawValue: String
    public let major: UInt32
    public let minor: UInt32
    public let patch: UInt32

    public init(_ rawValue: String) throws {
        let parts = rawValue.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3 else {
            throw FirmwareValidationError.invalidVersion
        }
        let components = try parts.map { part -> UInt32 in
            guard !part.isEmpty,
                  part.allSatisfy({ $0.isASCII && $0.isNumber }),
                  part == "0" || part.first != "0",
                  let value = UInt32(part) else {
                throw FirmwareValidationError.invalidVersion
            }
            return value
        }
        self.rawValue = rawValue
        major = components[0]
        minor = components[1]
        patch = components[2]
    }

    public init?(rawValue: String) {
        try? self.init(rawValue)
    }

    public var description: String { rawValue }

    public static func < (lhs: SemanticVersion, rhs: SemanticVersion) -> Bool {
        (lhs.major, lhs.minor, lhs.patch) < (rhs.major, rhs.minor, rhs.patch)
    }

    public init(from decoder: Decoder) throws {
        let rawValue = try decoder.singleValueContainer().decode(String.self)
        try self.init(rawValue)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}
