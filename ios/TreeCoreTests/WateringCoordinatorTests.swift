import Foundation
import XCTest
@testable import TreeCore

private enum APIStubError: Error {
    case transport
}

private actor AtomAPIStub: AtomAPI {
    var statusResult: Result<AtomStatus, Error>
    var wateringResult: Result<WateringAcknowledgement, Error>
    var holdResult: Result<HoldAcknowledgement, Error>
    var renewalResult: Result<HoldRenewalAcknowledgement, Error>
    var stopResult: Result<StopAcknowledgement, Error>

    private(set) var wateringCalls: [(String, Int)] = []
    private(set) var holdCalls: [String] = []
    private(set) var renewalCalls: [String] = []
    private(set) var stopCallCount = 0

    init() {
        statusResult = .failure(APIStubError.transport)
        wateringResult = .failure(APIStubError.transport)
        holdResult = .failure(APIStubError.transport)
        renewalResult = .failure(APIStubError.transport)
        stopResult = .success(StopAcknowledgement(stopped: true, state: .idle))
    }

    func fetchStatus() async throws -> AtomStatus { try statusResult.get() }

    func startWatering(
        requestID: String,
        durationSeconds: Int
    ) async throws -> WateringAcknowledgement {
        wateringCalls.append((requestID, durationSeconds))
        return try wateringResult.get()
    }

    func startHold(requestID: String) async throws -> HoldAcknowledgement {
        holdCalls.append(requestID)
        return try holdResult.get()
    }

    func renewHold(requestID: String) async throws -> HoldRenewalAcknowledgement {
        renewalCalls.append(requestID)
        return try renewalResult.get()
    }

    func stop() async throws -> StopAcknowledgement {
        stopCallCount += 1
        return try stopResult.get()
    }

    func setWateringResult(_ result: Result<WateringAcknowledgement, Error>) {
        wateringResult = result
    }

    func setHoldResult(_ result: Result<HoldAcknowledgement, Error>) {
        holdResult = result
    }

    func setRenewalResult(_ result: Result<HoldRenewalAcknowledgement, Error>) {
        renewalResult = result
    }

    func setStopResult(_ result: Result<StopAcknowledgement, Error>) {
        stopResult = result
    }
}

final class WateringCoordinatorTests: XCTestCase {
    func testSuccessfulDoseUsesOneRequestAndRecommendsStop() async throws {
        let api = AtomAPIStub()
        await api.setWateringResult(.success(Self.wateringAck(requestID: "ios-fixed")))
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-fixed" })

        try await coordinator.startDose(durationSeconds: 10, maximumDurationSeconds: 180)

        let calls = await api.wateringCalls
        XCTAssertEqual(calls.count, 1)
        XCTAssertEqual(calls.first?.0, "ios-fixed")
        XCTAssertEqual(calls.first?.1, 10)
        let snapshot = await coordinator.snapshot()
        XCTAssertTrue(snapshot.stopRecommended)
    }

    func testAmbiguousDoseIsNotRetried() async {
        let api = AtomAPIStub()
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-timeout" })

        do {
            try await coordinator.startDose(durationSeconds: 10, maximumDurationSeconds: 180)
            XCTFail("Expected ambiguous result")
        } catch {
            XCTAssertEqual(error as? WateringSafetyError, .ambiguousStart)
        }

        let wateringCallCount = await api.wateringCalls.count
        let stopCallCount = await api.stopCallCount
        let snapshot = await coordinator.snapshot()
        XCTAssertEqual(wateringCallCount, 1)
        XCTAssertEqual(stopCallCount, 0)
        XCTAssertTrue(snapshot.stopRecommended)
    }

    func testDefinitiveFirmwareRejectionDoesNotRecommendStop() async {
        let api = AtomAPIStub()
        await api.setWateringResult(.failure(AtomAPIError.http(status: 409, code: "boot_guard")))
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-rejected" })

        do {
            try await coordinator.startDose(durationSeconds: 10, maximumDurationSeconds: 180)
            XCTFail("Expected rejection")
        } catch {
            XCTAssertEqual(error as? WateringSafetyError, .rejected("boot_guard"))
        }

        let snapshot = await coordinator.snapshot()
        XCTAssertFalse(snapshot.stopRecommended)
    }

    func testInvalidDurationNeverReachesDevice() async {
        let api = AtomAPIStub()
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-invalid" })

        for duration in [0, 31, 181] {
            do {
                try await coordinator.startDose(
                    durationSeconds: duration,
                    maximumDurationSeconds: 30
                )
                XCTFail("Expected invalid duration")
            } catch {
                XCTAssertEqual(error as? WateringSafetyError, .invalidDuration)
            }
        }

        let wateringCallCount = await api.wateringCalls.count
        XCTAssertEqual(wateringCallCount, 0)
    }

    func testConfirmedStopClearsRecommendation() async throws {
        let api = AtomAPIStub()
        await api.setWateringResult(.success(Self.wateringAck(requestID: "ios-stop")))
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-stop" })
        try await coordinator.startDose(durationSeconds: 10, maximumDurationSeconds: 180)

        try await coordinator.stop()

        let stopCallCount = await api.stopCallCount
        let snapshot = await coordinator.snapshot()
        XCTAssertEqual(stopCallCount, 1)
        XCTAssertFalse(snapshot.stopRecommended)
    }

    func testAmbiguousHoldStartSendsBestEffortStop() async {
        let api = AtomAPIStub()
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-hold" })

        do {
            try await coordinator.beginHold()
            XCTFail("Expected ambiguous hold")
        } catch {
            XCTAssertEqual(error as? WateringSafetyError, .ambiguousHoldStart)
        }

        let holdCalls = await api.holdCalls
        let stopCallCount = await api.stopCallCount
        let snapshot = await coordinator.snapshot()
        XCTAssertEqual(holdCalls, ["ios-hold"])
        XCTAssertEqual(stopCallCount, 1)
        XCTAssertFalse(snapshot.holdActive)
    }

    func testHeartbeatFailureStopsHold() async throws {
        let api = AtomAPIStub()
        await api.setHoldResult(
            .success(
                HoldAcknowledgement(
                    accepted: true,
                    requestID: "ios-hold",
                    state: .watering,
                    wateringMode: "HOLD",
                    leaseMilliseconds: 1_500,
                    maximumRunMilliseconds: 600_000
                )
            )
        )
        await api.setRenewalResult(.failure(APIStubError.transport))
        let coordinator = WateringCoordinator(
            api: api,
            requestID: { "ios-hold" },
            heartbeatIntervalNanoseconds: 10_000_000
        )

        try await coordinator.beginHold()
        try await waitUntil(timeoutNanoseconds: 500_000_000) {
            await api.stopCallCount == 1
        }

        let renewalCalls = await api.renewalCalls
        let snapshot = await coordinator.snapshot()
        XCTAssertEqual(renewalCalls, ["ios-hold"])
        XCTAssertFalse(snapshot.holdActive)
        XCTAssertTrue(snapshot.stopRecommended)
    }

    private func waitUntil(
        timeoutNanoseconds: UInt64,
        condition: @escaping () async -> Bool
    ) async throws {
        let started = ContinuousClock.now
        while !(await condition()) {
            if ContinuousClock.now - started > .nanoseconds(Int64(timeoutNanoseconds)) {
                XCTFail("Timed out waiting for condition")
                return
            }
            try await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    private static func wateringAck(requestID: String) -> WateringAcknowledgement {
        WateringAcknowledgement(
            accepted: true,
            requestID: requestID,
            state: .watering,
            scheduledMilliseconds: 10_000
        )
    }
}
