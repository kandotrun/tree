import Foundation

public enum WateringSafetyError: Error, Equatable, Sendable {
    case invalidDuration
    case rejected(String)
    case ambiguousStart
    case stopUnconfirmed
    case ambiguousHoldStart
    case holdAlreadyActive
    case holdStartInvalidated
    case doseStartInvalidated
}

public struct WateringStatusObservation: Equatable, Sendable {
    fileprivate let revision: UInt
}

public struct WateringSnapshot: Equatable, Sendable {
    public let revision: UInt
    public let stopRecommended: Bool
    public let holdActive: Bool
    public let holdStarting: Bool
}

public actor WateringCoordinator {
    private static let expectedHoldLeaseMilliseconds = 1_500
    private static let expectedHoldMaximumRunMilliseconds = 600_000

    private let api: any AtomAPI
    private let requestID: @Sendable () -> String
    private let heartbeatIntervalNanoseconds: UInt64

    private var stopRecommended = false
    private var holdPressed = false
    private var holdStarting = false
    private var activeHoldRequestID: String?
    private var latestInvalidationGeneration = 0
    private var stopConfirmationRevision = 0
    // A STOP acknowledgement can clear the warning only when no later start
    // outcome could have re-armed the pump after that STOP was dispatched.
    private var actuationRiskRevision: UInt = 0
    private var snapshotRevision: UInt = 0
    private var statusObservationRevision: UInt = 0
    private var heartbeatTask: Task<Void, Never>?

    public init(
        api: any AtomAPI,
        requestID: @escaping @Sendable () -> String = {
            "ios-\(UUID().uuidString.lowercased())"
        },
        heartbeatIntervalNanoseconds: UInt64 = 500_000_000
    ) {
        self.api = api
        self.requestID = requestID
        self.heartbeatIntervalNanoseconds = heartbeatIntervalNanoseconds
    }

    deinit {
        heartbeatTask?.cancel()
    }

    public func snapshot() -> WateringSnapshot {
        snapshotRevision &+= 1
        return WateringSnapshot(
            revision: snapshotRevision,
            stopRecommended: stopRecommended,
            holdActive: activeHoldRequestID != nil,
            holdStarting: holdStarting
        )
    }

    public func beginStatusObservation() -> WateringStatusObservation {
        WateringStatusObservation(revision: statusObservationRevision)
    }

    public func startDose(
        durationSeconds: Int,
        maximumDurationSeconds: Int,
        operationGeneration: Int = 0
    ) async throws {
        let upperBound = min(180, maximumDurationSeconds)
        guard upperBound >= 1,
              (1 ... upperBound).contains(durationSeconds) else {
            throw WateringSafetyError.invalidDuration
        }
        guard registerStartOperation(operationGeneration) else {
            throw WateringSafetyError.doseStartInvalidated
        }
        invalidateStatusObservations()

        let id = requestID()
        let acknowledgement: WateringAcknowledgement
        do {
            acknowledgement = try await api.startWatering(
                requestID: id,
                durationSeconds: durationSeconds
            )
            guard isCurrentStartOperation(operationGeneration) else {
                markActuationRisk()
                await bestEffortStop()
                throw WateringSafetyError.doseStartInvalidated
            }
        } catch let error as WateringSafetyError {
            throw error
        } catch let error as AtomAPIError {
            if case let .http(_, code) = error {
                throw WateringSafetyError.rejected(code)
            }
            markActuationRisk()
            throw WateringSafetyError.ambiguousStart
        } catch {
            markActuationRisk()
            throw WateringSafetyError.ambiguousStart
        }

        guard acknowledgement.accepted,
              acknowledgement.requestID == id,
              acknowledgement.state == .watering,
              acknowledgement.scheduledMilliseconds == durationSeconds * 1_000 else {
            markActuationRisk()
            throw WateringSafetyError.ambiguousStart
        }
        markActuationRisk()
    }

    public func stop(operationGeneration: Int) async throws {
        invalidateHoldStarts(upTo: operationGeneration)
        invalidateStatusObservations()
        holdPressed = false
        activeHoldRequestID = nil
        heartbeatTask?.cancel()
        heartbeatTask = nil
        let confirmationRevisionAtStart = stopConfirmationRevision
        let actuationRiskRevisionAtStart = actuationRiskRevision

        do {
            let acknowledgement = try await api.stop()
            guard acknowledgement.stopped,
                  acknowledgement.state == .idle else {
                if stopConfirmationRevision == confirmationRevisionAtStart {
                    stopRecommended = true
                }
                throw WateringSafetyError.stopUnconfirmed
            }
            stopConfirmationRevision &+= 1
            if actuationRiskRevision == actuationRiskRevisionAtStart {
                stopRecommended = false
            }
        } catch let error as WateringSafetyError {
            throw error
        } catch {
            if stopConfirmationRevision == confirmationRevisionAtStart {
                stopRecommended = true
            }
            throw WateringSafetyError.stopUnconfirmed
        }
    }

    public func beginHold(operationGeneration: Int) async throws {
        guard registerStartOperation(operationGeneration) else {
            throw WateringSafetyError.holdStartInvalidated
        }
        invalidateStatusObservations()
        guard !holdStarting, activeHoldRequestID == nil else {
            throw WateringSafetyError.holdAlreadyActive
        }

        holdPressed = true
        holdStarting = true
        let id = requestID()
        let acknowledgement: HoldAcknowledgement
        do {
            acknowledgement = try await api.startHold(requestID: id)
        } catch let error as AtomAPIError {
            holdStarting = false
            holdPressed = false
            if case let .http(_, code) = error {
                throw WateringSafetyError.rejected(code)
            }
            markActuationRisk()
            await bestEffortStop()
            throw WateringSafetyError.ambiguousHoldStart
        } catch {
            holdStarting = false
            holdPressed = false
            markActuationRisk()
            await bestEffortStop()
            throw WateringSafetyError.ambiguousHoldStart
        }

        guard isCurrentStartOperation(operationGeneration) else {
            holdStarting = false
            holdPressed = false
            markActuationRisk()
            await bestEffortStop()
            throw WateringSafetyError.holdStartInvalidated
        }

        guard acknowledgement.accepted,
              acknowledgement.requestID == id,
              acknowledgement.state == .watering,
              acknowledgement.wateringMode == "HOLD",
              acknowledgement.leaseMilliseconds == Self.expectedHoldLeaseMilliseconds,
              acknowledgement.maximumRunMilliseconds == Self.expectedHoldMaximumRunMilliseconds else {
            holdStarting = false
            holdPressed = false
            markActuationRisk()
            await bestEffortStop()
            throw WateringSafetyError.ambiguousHoldStart
        }

        holdStarting = false
        markActuationRisk()
        guard holdPressed else {
            await bestEffortStop()
            throw WateringSafetyError.holdStartInvalidated
        }
        activeHoldRequestID = id
        startHeartbeatLoop()
    }

    public func endHold(operationGeneration: Int) async throws {
        let hadHoldContext = holdPressed || holdStarting || activeHoldRequestID != nil
        invalidateHoldStarts(upTo: operationGeneration)
        invalidateStatusObservations()
        holdPressed = false
        activeHoldRequestID = nil
        heartbeatTask?.cancel()
        heartbeatTask = nil
        guard hadHoldContext else { return }
        try await stop(operationGeneration: operationGeneration)
    }

    public func reconcile(
        status: AtomStatus,
        observation: WateringStatusObservation
    ) {
        guard observation.revision == statusObservationRevision else { return }
        if status.pump {
            stopRecommended = true
        } else if status.state == .idle, !holdStarting, activeHoldRequestID == nil {
            stopRecommended = false
        }
        if let holdID = activeHoldRequestID,
           status.lastRequestID == holdID,
           status.pump == false {
            holdPressed = false
            activeHoldRequestID = nil
            heartbeatTask?.cancel()
            heartbeatTask = nil
        }
    }

    private func startHeartbeatLoop() {
        heartbeatTask?.cancel()
        let interval = heartbeatIntervalNanoseconds
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: interval)
                } catch {
                    return
                }
                guard let self else { return }
                if !(await self.sendHeartbeat()) {
                    return
                }
            }
        }
    }

    private func sendHeartbeat() async -> Bool {
        guard holdPressed, let id = activeHoldRequestID else {
            return false
        }
        do {
            let acknowledgement = try await api.renewHold(requestID: id)
            guard acknowledgement.renewed,
                  acknowledgement.requestID == id,
                  acknowledgement.leaseMilliseconds == Self.expectedHoldLeaseMilliseconds else {
                throw WateringSafetyError.ambiguousHoldStart
            }
            return true
        } catch {
            guard activeHoldRequestID == id else { return false }
            invalidateStatusObservations()
            holdPressed = false
            activeHoldRequestID = nil
            heartbeatTask = nil
            stopRecommended = true
            await bestEffortStop()
            return false
        }
    }

    private func bestEffortStop() async {
        _ = try? await api.stop()
    }

    private func invalidateHoldStarts(upTo generation: Int) {
        latestInvalidationGeneration = max(latestInvalidationGeneration, generation)
    }

    private func registerStartOperation(_ generation: Int) -> Bool {
        guard generation >= latestInvalidationGeneration else { return false }
        latestInvalidationGeneration = generation
        return true
    }

    private func isCurrentStartOperation(_ generation: Int) -> Bool {
        generation == latestInvalidationGeneration
    }

    private func invalidateStatusObservations() {
        statusObservationRevision &+= 1
    }

    private func markActuationRisk() {
        invalidateStatusObservations()
        actuationRiskRevision &+= 1
        stopRecommended = true
    }
}
