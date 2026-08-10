import XCTest
@testable import TreeCore

final class WateringDurationPolicyTests: XCTestCase {
    func testOptionsRespectFirmwareMaximum() {
        XCTAssertEqual(WateringDurationPolicy.options(maximumSeconds: 25), [5, 10])
        XCTAssertEqual(WateringDurationPolicy.options(maximumSeconds: 3), [3])
        XCTAssertEqual(WateringDurationPolicy.options(maximumSeconds: 0), [])
        XCTAssertEqual(
            WateringDurationPolicy.options(maximumSeconds: 25, including: 3),
            [3, 5, 10]
        )
    }

    func testNormalizationAlwaysReturnsDisplayedOption() {
        XCTAssertEqual(
            WateringDurationPolicy.normalized(currentSeconds: 30, maximumSeconds: 25),
            10
        )
        XCTAssertEqual(
            WateringDurationPolicy.normalized(currentSeconds: 1, maximumSeconds: 25),
            1
        )
        XCTAssertEqual(
            WateringDurationPolicy.normalized(currentSeconds: 10, maximumSeconds: 25),
            10
        )
        XCTAssertNil(
            WateringDurationPolicy.normalized(currentSeconds: 10, maximumSeconds: 0)
        )
    }
}
