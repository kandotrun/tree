import Foundation
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

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
        let validationHost: String
        if host.hasPrefix("["), host.hasSuffix("]") {
            validationHost = String(host.dropFirst().dropLast())
        } else {
            validationHost = host
        }
        guard Self.isLocalHost(validationHost) else {
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
            guard parts.allSatisfy({ part in
                !part.isEmpty
                    && (part.count == 1 || part.first != "0")
                    && part.utf8.allSatisfy { byte in byte >= 48 && byte <= 57 }
            }) else { return false }
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
        return host.contains(":") && isLocalIPv6(host)
    }

    private static func isLocalIPv6(_ host: String) -> Bool {
#if canImport(Darwin) || canImport(Glibc)
        var address = in6_addr()
        let parsed = host.withCString { pointer in
            inet_pton(AF_INET6, pointer, &address)
        }
        guard parsed == 1 else { return false }

        let bytes = withUnsafeBytes(of: &address) { Array($0) }
        guard bytes.count == 16 else { return false }
        let isLoopback = bytes.dropLast().allSatisfy { $0 == 0 }
            && bytes.last == 1
        let isUniqueLocal = (bytes[0] & 0xfe) == 0xfc
        let isLinkLocal = bytes[0] == 0xfe && (bytes[1] & 0xc0) == 0x80
        return isLoopback || isUniqueLocal || isLinkLocal
#else
        return false
#endif
    }
}
