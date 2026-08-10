import Foundation

public struct BonjourDeviceCandidate: Equatable, Sendable {
    public static let serviceType = "_tree-watering._tcp"
    public static let expectedServiceName = "balcony-watering"

    public let name: String
    public let endpoint: DeviceEndpoint

    public init?(serviceName: String) {
        let normalized = serviceName.lowercased()
        guard normalized == Self.expectedServiceName else {
            return nil
        }
        guard !normalized.isEmpty,
              normalized.utf8.count <= 63,
              normalized.first != "-",
              normalized.last != "-",
              normalized.allSatisfy({ character in
                  character.isASCII && (character.isLetter || character.isNumber || character == "-")
              }),
              let endpoint = try? DeviceEndpoint("http://\(normalized).local") else {
            return nil
        }
        name = normalized
        self.endpoint = endpoint
    }
}
