import Foundation
import XCTest
@testable import TreeCore

private enum APIStubError: Error {
    case transport
}

private final class RequestIDSequence: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String]

    init(_ values: [String]) {
        self.values = values
    }

    func next() -> String {
        lock.lock()
        defer { lock.unlock() }
        return values.removeFirst()
    }
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
    private var suspendNextHold = false
    private var holdContinuation: CheckedContinuation<HoldAcknowledgement, Error>?
    private var suspendNextRenewal = false
    private var renewalContinuation: CheckedContinuation<HoldRenewalAcknowledgement, Error>?

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
        if suspendNextHold {
            suspendNextHold = false
            return try await withCheckedThrowingContinuation { continuation in
                holdContinuation = continuation
            }
        }
        return try holdResult.get()
    }

    func renewHold(requestID: String) async throws -> HoldRenewalAcknowledgement {
        renewalCalls.append(requestID)
        if suspendNextRenewal {
            suspendNextRenewal = false
            return try await withCheckedThrowingContinuation { continuation in
                renewalContinuation = continuation
            }
        }
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

    func suspendNextHoldCall() {
        suspendNextHold = true
    }

    func succeedSuspendedHold(_ acknowledgement: HoldAcknowledgement) {
        holdContinuation?.resume(returning: acknowledgement)
        holdContinuation = nil
    }

    func suspendNextRenewalCall() {
        suspendNextRenewal = true
    }

    func failSuspendedRenewal() {
        renewalContinuation?.resume(throwing: APIStubError.transport)
        renewalContinuation = nil
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

        for maximum in [0, -1] {
            do {
                try await coordinator.startDose(
                    durationSeconds: 1,
                    maximumDurationSeconds: maximum
                )
                XCTFail("Expected invalid maximum duration")
            } catch {
                XCTAssertEqual(error as? WateringSafetyError, .invalidDuration)
            }
        }

        let wateringCallCount = await api.wateringCalls.count
        XCTAssertEqual(wateringCallCount, 0)
    }

    func testStopRequiresIdleAcknowledgement() async {
        let api = AtomAPIStub()
        await api.setStopResult(
            .success(StopAcknowledgement(stopped: true, state: .watering))
        )
        let coordinator = WateringCoordinator(api: api)

        do {
            try await coordinator.stop(operationGeneration: 0)
            XCTFail("Expected stopUnconfirmed")
        } catch {
            XCTAssertEqual(error as? WateringSafetyError, .stopUnconfirmed)
        }

        let snapshot = await coordinator.snapshot()
        XCTAssertTrue(snapshot.stopRecommended)
    }

    func testConfirmedStopClearsRecommendation() async throws {
        let api = AtomAPIStub()
        await api.setWateringResult(.success(Self.wateringAck(requestID: "ios-stop")))
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-stop" })
        try await coordinator.startDose(durationSeconds: 10, maximumDurationSeconds: 180)

        try await coordinator.stop(operationGeneration: 0)

        let stopCallCount = await api.stopCallCount
        let snapshot = await coordinator.snapshot()
        XCTAssertEqual(stopCallCount, 1)
        XCTAssertFalse(snapshot.stopRecommended)
    }

    func testAmbiguousHoldStartSendsBestEffortStop() async {
        let api = AtomAPIStub()
        let coordinator = WateringCoordinator(api: api, requestID: { "ios-hold" })

        do {
            try await coordinator.beginHold(operationGeneration: 0)
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

    func testStopInvalidatesOlderHoldStartBeforeRequest() async throws {
        let api = AtomAPIStub()
        await api.setHoldResult(.success(Self.holdAck(requestID: "stale-hold")))
        let coordinator = WateringCoordinator(api: api, requestID: { "stale-hold" })

        try await coordinator.stop(operationGeneration: 1)

        do {
            try await coordinator.beginHold(operationGeneration: 0)
            XCTFail("Expected stale hold start to be invalidated")
        } catch {
            XCTAssertEqual(error as? WateringSafetyError, .holdStartInvalidated)
        }

        let holdCalls = await api.holdCalls
        let stopCallCount = await api.stopCallCount
        XCTAssertEqual(holdCalls, [])
        XCTAssertEqual(stopCallCount, 1)
    }

    func testReleaseInvalidatesOlderHoldStartBeforeRequest() async throws {
        let api = AtomAPIStub()
        await api.setHoldResult(.success(Self.holdAck(requestID: "released-hold")))
        let coordinator = WateringCoordinator(api: api, requestID: { "released-hold" })

        try await coordinator.endHold(operationGeneration: 1)

        do {
            try await coordinator.beginHold(operationGeneration: 0)
            XCTFail("Expected released hold start to be invalidated")
        } catch {
            XCTAssertEqual(error as? WateringSafetyError, .holdStartInvalidated)
        }

        let holdCalls = await api.holdCalls
        let stopCallCount = await api.stopCallCount
        XCTAssertEqual(holdCalls, [])
        XCTAssertEqual(stopCallCount, 0)
    }

    func testStopDuringHoldStartPreventsLateAcknowledgementFromWinning() async throws {
        let api = AtomAPIStub()
        await api.suspendNextHoldCall()
        let coordinator = WateringCoordinator(api: api, requestID: { "pending-hold" })
        let startTask = Task {
            try await coordinator.beginHold(operationGeneration: 0)
        }
        try await waitUntil(timeoutNanoseconds: 500_000_000) {
            await api.holdCalls == ["pending-hold"]
        }

        try await coordinator.stop(operationGeneration: 1)
        await api.succeedSuspendedHold(Self.holdAck(requestID: "pending-hold"))

        do {
            try await startTask.value
            XCTFail("Expected late acknowledgement to be invalidated")
        } catch {
            XCTAssertEqual(error as? WateringSafetyError, .holdStartInvalidated)
        }

        let snapshot = await coordinator.snapshot()
        let stopCallCount = await api.stopCallCount
        XCTAssertFalse(snapshot.holdActive)
        XCTAssertTrue(snapshot.stopRecommended)
        XCTAssertEqual(stopCallCount, 2)
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

        try await coordinator.beginHold(operationGeneration: 0)
        try await waitUntil(timeoutNanoseconds: 500_000_000) {
            await api.stopCallCount == 1
        }

        let renewalCalls = await api.renewalCalls
        let snapshot = await coordinator.snapshot()
        XCTAssertEqual(renewalCalls, ["ios-hold"])
        XCTAssertFalse(snapshot.holdActive)
        XCTAssertTrue(snapshot.stopRecommended)
    }

    func testStaleHeartbeatFailureDoesNotStopNewHold() async throws {
        let api = AtomAPIStub()
        let ids = RequestIDSequence(["hold-1", "hold-2"])
        await api.setHoldResult(.success(Self.holdAck(requestID: "hold-1")))
        await api.suspendNextRenewalCall()
        let coordinator = WateringCoordinator(
            api: api,
            requestID: { ids.next() },
            heartbeatIntervalNanoseconds: 50_000_000
        )

        try await coordinator.beginHold(operationGeneration: 0)
        try await waitUntil(timeoutNanoseconds: 500_000_000) {
            await api.renewalCalls == ["hold-1"]
        }
        try await coordinator.endHold(operationGeneration: 1)

        await api.setHoldResult(.success(Self.holdAck(requestID: "hold-2")))
        await api.setRenewalResult(
            .success(
                HoldRenewalAcknowledgement(
                    renewed: true,
                    requestID: "hold-2",
                    leaseMilliseconds: 1_500,
                    remainingMilliseconds: 1_500
                )
            )
        )
        try await coordinator.beginHold(operationGeneration: 1)
        await api.failSuspendedRenewal()
        try await waitUntil(timeoutNanoseconds: 500_000_000) {
            await api.renewalCalls.contains("hold-2")
        }

        let snapshot = await coordinator.snapshot()
        let stopCallCount = await api.stopCallCount
        XCTAssertTrue(snapshot.holdActive)
        XCTAssertTrue(snapshot.stopRecommended)
        XCTAssertEqual(stopCallCount, 1)

        try await coordinator.endHold(operationGeneration: 2)
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

    private static func holdAck(requestID: String) -> HoldAcknowledgement {
        HoldAcknowledgement(
            accepted: true,
            requestID: requestID,
            state: .watering,
            wateringMode: "HOLD",
            leaseMilliseconds: 1_500,
            maximumRunMilliseconds: 600_000
        )
    }
}
