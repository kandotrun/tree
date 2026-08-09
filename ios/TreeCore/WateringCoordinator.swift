import Foundation

public enum WateringSafetyError: Error, Equatable, Sendable {
    case invalidDuration
    case rejected(String)
    case ambiguousStart
    case stopUnconfirmed
    case ambiguousHoldStart
    case holdAlreadyActive
}

public struct WateringSnapshot: Equatable, Sendable {
    public let stopRecommended: Bool
    public let holdActive: Bool
    public let holdStarting: Bool
}

public actor WateringCoordinator {
    private let api: any AtomAPI
    private let requestID: @Sendable () -> String
    private let heartbeatIntervalNanoseconds: UInt64

    private var stopRecommended = false
    private var holdPressed = false
    private var holdStarting = false
    private var activeHoldRequestID: String?
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
        WateringSnapshot(
            stopRecommended: stopRecommended,
            holdActive: activeHoldRequestID != nil,
            holdStarting: holdStarting
        )
    }

    public func startDose(
        durationSeconds: Int,
        maximumDurationSeconds: Int
    ) async throws {
        let upperBound = min(180, maximumDurationSeconds)
        guard (1 ... upperBound).contains(durationSeconds) else {
            throw WateringSafetyError.invalidDuration
        }

        let id = requestID()
        let acknowledgement: WateringAcknowledgement
        do {
            acknowledgement = try await api.startWatering(
                requestID: id,
                durationSeconds: durationSeconds
            )
        } catch let error as AtomAPIError {
            if case let .http(_, code) = error {
                throw WateringSafetyError.rejected(code)
            }
            stopRecommended = true
            throw WateringSafetyError.ambiguousStart
        } catch {
            stopRecommended = true
            throw WateringSafetyError.ambiguousStart
        }

        guard acknowledgement.accepted,
              acknowledgement.requestID == id,
              acknowledgement.state == .watering,
              acknowledgement.scheduledMilliseconds == durationSeconds * 1_000 else {
            stopRecommended = true
            throw WateringSafetyError.ambiguousStart
        }
        stopRecommended = true
    }

    public func stop() async throws {
        holdPressed = false
        holdStarting = false
        activeHoldRequestID = nil
        heartbeatTask?.cancel()
        heartbeatTask = nil

        do {
            let acknowledgement = try await api.stop()
            guard acknowledgement.stopped else {
                throw WateringSafetyError.stopUnconfirmed
            }
            stopRecommended = false
        } catch {
            stopRecommended = true
            throw WateringSafetyError.stopUnconfirmed
        }
    }

    public func beginHold() async throws {
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
            stopRecommended = true
            await bestEffortStop()
            throw WateringSafetyError.ambiguousHoldStart
        } catch {
            holdStarting = false
            holdPressed = false
            stopRecommended = true
            await bestEffortStop()
            throw WateringSafetyError.ambiguousHoldStart
        }

        guard acknowledgement.accepted,
              acknowledgement.requestID == id,
              acknowledgement.state == .watering,
              acknowledgement.wateringMode == "HOLD",
              acknowledgement.leaseMilliseconds == 1_500,
              acknowledgement.maximumRunMilliseconds == 600_000 else {
            holdStarting = false
            holdPressed = false
            stopRecommended = true
            await bestEffortStop()
            throw WateringSafetyError.ambiguousHoldStart
        }

        holdStarting = false
        guard holdPressed else {
            await bestEffortStop()
            return
        }
        activeHoldRequestID = id
        stopRecommended = true
        startHeartbeatLoop()
    }

    public func endHold() async throws {
        let hadHoldContext = holdPressed || holdStarting || activeHoldRequestID != nil
        holdPressed = false
        activeHoldRequestID = nil
        heartbeatTask?.cancel()
        heartbeatTask = nil
        guard hadHoldContext else { return }
        try await stop()
    }

    public func reconcile(status: AtomStatus) {
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
                  acknowledgement.leaseMilliseconds == 1_500 else {
                throw WateringSafetyError.ambiguousHoldStart
            }
            return true
        } catch {
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
}
