import XCTest
@testable import TreeCore

final class DeviceEndpointTests: XCTestCase {
    func testAcceptsPrivateIPv4Address() throws {
        let endpoint = try DeviceEndpoint("http://192.168.1.50")

        XCTAssertEqual(endpoint.baseURL.absoluteString, "http://192.168.1.50/")
    }

    func testAcceptsLocalHostname() throws {
        let endpoint = try DeviceEndpoint("http://tree.local")

        XCTAssertEqual(endpoint.baseURL.host, "tree.local")
    }

    func testRejectsPublicHost() {
        XCTAssertThrowsError(try DeviceEndpoint("http://example.com")) { error in
            XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
        }
    }

    func testRejectsHostnamesThatMimicPrivateAddresses() {
        for value in [
            "http://192.168.1.50.example.com",
            "http://fc-attacker.example",
        ] {
            XCTAssertThrowsError(try DeviceEndpoint(value)) { error in
                XCTAssertEqual(error as? DeviceEndpointError, .nonLocalHost)
            }
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
