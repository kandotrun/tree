import XCTest
@testable import TreeCore

final class DeviceEndpointTests: XCTestCase {
    func testAcceptsPrivateIPv4Addresses() {
        for value in [
            "http://10.0.0.1",
            "http://127.0.0.1",
            "http://169.254.1.1",
            "http://172.16.0.1",
            "http://172.31.255.254",
            "http://192.168.1.50",
        ] {
            XCTAssertNoThrow(try DeviceEndpoint(value), "Expected acceptance for \(value)")
        }
    }

    func testRejectsAmbiguousIPv4Representations() {
        for value in [
            "http://010.0.0.1",
            "http://10.00.0.1",
            "http://127.000.000.001",
        ] {
            XCTAssertThrowsError(try DeviceEndpoint(value)) { error in
                XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
            }
        }
    }

    func testAcceptsLocalIPv6Addresses() throws {
        for (value, expected) in [
            ("http://[::1]", "http://[::1]/"),
            ("http://[fd12:3456::1]", "http://[fd12:3456::1]/"),
            ("http://[fe80::1]", "http://[fe80::1]/"),
        ] {
            let endpoint = try DeviceEndpoint(value)
            XCTAssertEqual(endpoint.baseURL.absoluteString, expected)
        }
    }

    func testRejectsNonLocalOrMalformedIPv6Addresses() {
        for value in [
            "http://[fc::1]",
            "http://[fd::1]",
            "http://[fe8::1]",
            "http://[fd00::::1]",
        ] {
            XCTAssertThrowsError(try DeviceEndpoint(value)) { error in
                XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
            }
        }
    }

    func testRejectsPublicIPv6Address() {
        XCTAssertThrowsError(try DeviceEndpoint("http://[2001:db8::1]")) { error in
            XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
        }
    }

    func testAcceptsLocalHostname() throws {
        let endpoint = try DeviceEndpoint("http://tree.local")

        XCTAssertEqual(endpoint.baseURL.host, "tree.local")
    }

    func testRejectsPublicHost() {
        XCTAssertThrowsError(try DeviceEndpoint("http://example.com")) { error in
            XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
        }
        XCTAssertThrowsError(try DeviceEndpoint("http://172.32.0.1")) { error in
            XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
        }
    }

    func testRejectsHostnamesThatMimicPrivateAddresses() {
        for value in [
            "http://192.168.1.50.example.com",
            "http://10.0.0.1.attacker.com",
            "http://fc-attacker.example",
            "http://fdservice.example.com",
            "http://fe8-cdn.example.net",
        ] {
            XCTAssertThrowsError(try DeviceEndpoint(value)) { error in
                XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
            }
        }
    }

    func testRejectsHTTPSForDirectFirmwareConnection() {
        XCTAssertThrowsError(try DeviceEndpoint("https://192.168.1.50")) { error in
            XCTAssertEqual(error as? DeviceEndpointError, .unsupportedScheme)
        }
    }

    func testRejectsCredentialsPathQueryAndFragment() {
        let invalidValues = [
            "http://user:pass@192.168.1.50",
            "http://192.168.1.50/device",
            "http://192.168.1.50?token=secret",
            "http://192.168.1.50#status"
        ]

        for value in invalidValues {
            XCTAssertThrowsError(try DeviceEndpoint(value), "Expected rejection for \(value)")
        }
    }
}
