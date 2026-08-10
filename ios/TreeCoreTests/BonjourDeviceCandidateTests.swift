import XCTest
@testable import TreeCore

final class BonjourDeviceCandidateTests: XCTestCase {
    func testBuildsLocalEndpointFromDNSSafeServiceName() throws {
        let candidate = try XCTUnwrap(BonjourDeviceCandidate(serviceName: "balcony-watering"))

        XCTAssertEqual(candidate.name, "balcony-watering")
        XCTAssertEqual(candidate.endpoint.baseURL.absoluteString, "http://balcony-watering.local/")
    }

    func testRejectsDifferentDeviceName() {
        XCTAssertNil(BonjourDeviceCandidate(serviceName: "other-watering"))
    }

    func testRejectsServiceNamesThatCannotBeLocalHostLabels() {
        for name in [
            "",
            "-balcony-watering",
            "balcony-watering-",
            "balcony watering",
            "balcony.watering",
            String(repeating: "a", count: 64),
        ] {
            XCTAssertNil(BonjourDeviceCandidate(serviceName: name), name)
        }
    }
}