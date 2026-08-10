import XCTest
@testable import TreeCore

final class WateringCountdownProgressTests: XCTestCase {
    func testCalculatesRemainingFractionFromScheduledDuration() throws {
        let fraction = try XCTUnwrap(
            WateringCountdownProgress.remainingFraction(
                remainingMilliseconds: 7_500,
                scheduledMilliseconds: 10_000
            )
        )

        XCTAssertEqual(fraction, 0.75, accuracy: 0.000_001)
    }

    func testClampsRemainingFractionToClosedUnitRange() throws {
        let belowZero = try XCTUnwrap(
            WateringCountdownProgress.remainingFraction(
                remainingMilliseconds: -1,
                scheduledMilliseconds: 10_000
            )
        )
        let aboveTotal = try XCTUnwrap(
            WateringCountdownProgress.remainingFraction(
                remainingMilliseconds: 12_000,
                scheduledMilliseconds: 10_000
            )
        )

        XCTAssertEqual(belowZero, 0)
        XCTAssertEqual(aboveTotal, 1)
    }

    func testReturnsNilWithoutPositiveScheduledDuration() {
        XCTAssertNil(
            WateringCountdownProgress.remainingFraction(
                remainingMilliseconds: 1_000,
                scheduledMilliseconds: 0
            )
        )
        XCTAssertNil(
            WateringCountdownProgress.remainingFraction(
                remainingMilliseconds: 1_000,
                scheduledMilliseconds: -1
            )
        )
    }
}
