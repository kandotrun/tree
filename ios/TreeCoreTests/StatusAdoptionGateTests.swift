import XCTest
@testable import TreeCore

final class StatusAdoptionGateTests: XCTestCase {
    func testPreDoseStatusCannotBeAdoptedAfterSuccessfulDoseFinishes() throws {
        var gate = StatusAdoptionGate()
        let preDoseStatus = try XCTUnwrap(gate.beginStatusRequest())

        gate.beginOperation()
        gate.endOperation()

        XCTAssertFalse(gate.canAdopt(preDoseStatus))
    }

    func testPreStopStatusCannotBeAdoptedAfterFailedStopFinishes() throws {
        var gate = StatusAdoptionGate()
        let preStopStatus = try XCTUnwrap(gate.beginStatusRequest())

        gate.beginOperation()
        gate.endOperation()

        XCTAssertFalse(gate.canAdopt(preStopStatus))
    }

    func testStatusRequestCannotStartWhileOperationIsInFlight() {
        var gate = StatusAdoptionGate()

        gate.beginOperation()

        XCTAssertNil(gate.beginStatusRequest())
    }

    func testStatusStartedAfterOperationCanBeAdopted() throws {
        var gate = StatusAdoptionGate()

        gate.beginOperation()
        gate.endOperation()
        let postOperationStatus = try XCTUnwrap(gate.beginStatusRequest())

        XCTAssertTrue(gate.canAdopt(postOperationStatus))
    }

    func testStatusRemainsBlockedUntilAllConcurrentStopsFinish() throws {
        var gate = StatusAdoptionGate()
        let preStopStatus = try XCTUnwrap(gate.beginStatusRequest())

        gate.beginOperation()
        gate.beginOperation()
        gate.endOperation()

        XCTAssertNil(gate.beginStatusRequest())
        XCTAssertFalse(gate.canAdopt(preStopStatus))

        gate.endOperation()
        let postStopStatus = try XCTUnwrap(gate.beginStatusRequest())
        XCTAssertTrue(gate.canAdopt(postStopStatus))
    }
}
