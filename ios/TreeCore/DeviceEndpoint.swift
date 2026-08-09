import Foundation

public enum DeviceEndpointError: Error, Equatable, Sendable {
    case invalidURL
    case unsupportedScheme
    case nonLocalHost
    case unexpectedComponents
}

public struct DeviceEndpoint: Equatable, Sendable {
    public let baseURL: URL

    public init(_ value: String) throws {
        guard var components = URLComponents(string: value.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = components.scheme?.lowercased(),
              let host = components.host?.lowercased(),
              !host.isEmpty else {
            throw DeviceEndpointError.invalidURL
        }
        guard scheme == "http" else {
            throw DeviceEndpointError.unsupportedScheme
        }
        guard components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil,
              components.path.isEmpty || components.path == "/" else {
            throw DeviceEndpointError.unexpectedComponents
        }
        guard Self.isLocalHost(host) else {
            throw DeviceEndpointError.nonLocalHost
        }

        components.scheme = scheme
        components.host = host
        components.path = "/"
        guard let normalized = components.url else {
            throw DeviceEndpointError.invalidURL
        }
        baseURL = normalized
    }

    public func url(for path: String) -> URL {
        baseURL.appending(path: path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }

    private static func isLocalHost(_ host: String) -> Bool {
        if host == "localhost" || host == "::1" || host.hasSuffix(".local") {
            return true
        }
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        if parts.count == 4 {
            let parsed = parts.map { UInt8($0) }
            guard parsed.allSatisfy({ $0 != nil }) else { return false }
            let octets = parsed.compactMap { $0 }
            switch (octets[0], octets[1]) {
            case (10, _), (127, _), (192, 168), (169, 254):
                return true
            case (172, 16 ... 31):
                return true
            default:
                return false
            }
        }
        let lowercase = host.lowercased()
        guard lowercase.contains(":"),
              lowercase.allSatisfy({ $0.isHexDigit || $0 == ":" }) else {
            return false
        }
        return lowercase.hasPrefix("fc")
            || lowercase.hasPrefix("fd")
            || lowercase.hasPrefix("fe8")
            || lowercase.hasPrefix("fe9")
            || lowercase.hasPrefix("fea")
            || lowercase.hasPrefix("feb")
    }
}
