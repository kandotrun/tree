import Foundation
import SwiftUI
import TreeCore

enum DeviceConnectionState: Equatable {
    case unconfigured
    case connecting
    case online
    case offline
}

struct AppNotice: Identifiable, Equatable {
    enum Level {
        case info
        case warning
        case success
    }

    let id = UUID()
    let level: Level
    let text: String
}

@MainActor
final class DashboardViewModel: ObservableObject {
    private static let endpointDefaultsKey = "tree.deviceEndpoint"

    @Published var endpointInput: String
    @Published var selectedDurationSeconds = 10
    @Published var showDoseConfirmation = false
    @Published var showSettings = false
    @Published var showForceEndpointConfirmation = false
    @Published private(set) var endpointValidationMessage: String?
    @Published private(set) var status: AtomStatus?
    @Published private(set) var connectionState: DeviceConnectionState = .unconfigured
    @Published private(set) var isRefreshing = false
    @Published private(set) var isActionInFlight = false
    @Published private(set) var isStopping = false
    @Published private(set) var holdGestureActive = false
    @Published private(set) var holdStartInFlight = false
    @Published private(set) var holdEndInFlight = false
    @Published private(set) var holdActive = false
    @Published private(set) var stopRecommended = false
    @Published private(set) var isDiscovering = false
    @Published private(set) var discoveryMessage = "同じWi-Fi内を検索中です…"
    @Published var notice: AppNotice?

    private let defaults: UserDefaults
    private let isPreviewMode: Bool
    private let discovery = BonjourDeviceDiscovery()
    private var api: AtomAPIClient?
    private var coordinator: WateringCoordinator?
    private var pollingTask: Task<Void, Never>?
    private var holdStartTask: Task<Void, Never>?
    private var pendingEndpoint: DeviceEndpoint?
    private var isSceneActive = false
    private var operationGeneration = 0
    private var activeStopRequests = 0
    private var endpointGeneration = 0
    private var lastSafetySnapshotRevision: UInt = 0
    private var statusAdoptionGate = StatusAdoptionGate()
    private var activeRefreshGeneration: Int?
    private var discoveryGeneration = 0
    private var discoveryTimeoutTask: Task<Void, Never>?
    private var discoveryValidationTasks: [String: Task<Void, Never>] = [:]

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
#if DEBUG
        let setupPreview = ProcessInfo.processInfo.arguments.contains("-ui-preview-setup")
        let wateringPreview = ProcessInfo.processInfo.arguments.contains("-ui-preview-watering")
        let previewMode = setupPreview
            || wateringPreview
            || ProcessInfo.processInfo.arguments.contains("-ui-preview")
#else
        let setupPreview = false
        let wateringPreview = false
        let previewMode = false
#endif
        isPreviewMode = previewMode
        if setupPreview {
            endpointInput = ""
            isDiscovering = true
            connectionState = .unconfigured
            return
        }
        if previewMode,
           let endpoint = try? DeviceEndpoint("http://127.0.0.1") {
            endpointInput = endpoint.baseURL.absoluteString
            install(endpoint: endpoint)
            status = wateringPreview
                ? Self.makeWateringPreviewStatus()
                : Self.makePreviewStatus()
            stopRecommended = wateringPreview
            connectionState = .online
            return
        }
        let saved = defaults.string(forKey: Self.endpointDefaultsKey) ?? ""
        endpointInput = saved
        if let endpoint = try? DeviceEndpoint(saved) {
            install(endpoint: endpoint)
        }
    }

    var hasEndpoint: Bool { api != nil }
    var isOnline: Bool { connectionState == .online }

    var endpointHost: String {
        if isPreviewMode { return "プレビュー" }
        guard let value = defaults.string(forKey: Self.endpointDefaultsKey),
              let host = URL(string: value)?.host else { return "未設定" }
        return host
    }

    var durationOptions: [Int] {
        WateringDurationPolicy.options(
            maximumSeconds: status?.maximumDurationSeconds ?? 180,
            including: selectedDurationSeconds
        )
    }

    var canStartWatering: Bool {
        isOnline
            && status?.canStartWatering == true
            && !isActionInFlight
            && !isStopping
            && !holdStartInFlight
            && !holdEndInFlight
            && !holdActive
            && !stopRecommended
            && !durationOptions.isEmpty
    }

    var shouldShowStop: Bool {
        stopRecommended
            || status?.pump == true
            || status?.state == .watering
            || isActionInFlight
            || isStopping
            || holdStartInFlight
            || holdEndInFlight
            || holdActive
    }

    var canAttemptEndpointChange: Bool {
        !isActionInFlight
            && !isStopping
            && !holdGestureActive
            && !holdStartInFlight
            && !holdEndInFlight
            && !holdActive
            && (!shouldShowStop || connectionState == .offline)
    }

    func saveEndpoint() -> Bool {
        guard canAttemptEndpointChange else {
            endpointValidationMessage = "給水操作が完了してから接続先を変更してください"
            return false
        }
        do {
            let endpoint = try DeviceEndpoint(endpointInput)
            if shouldShowStop {
                guard connectionState == .offline else {
                    endpointValidationMessage = "停止を確認してから接続先を変更してください"
                    return false
                }
                pendingEndpoint = endpoint
                endpointValidationMessage = nil
                showForceEndpointConfirmation = true
                return false
            }
            return applyEndpoint(endpoint)
        } catch {
            endpointValidationMessage = endpointErrorMessage(error)
            return false
        }
    }

    func confirmOfflineEndpointChange() -> Bool {
        defer {
            pendingEndpoint = nil
            showForceEndpointConfirmation = false
        }
        guard connectionState == .offline,
              shouldShowStop,
              canAttemptEndpointChange,
              let endpoint = pendingEndpoint else {
            endpointValidationMessage = "状態が変わりました。接続先をもう一度確認してください"
            return false
        }
        return applyEndpoint(endpoint)
    }

    func cancelOfflineEndpointChange() {
        pendingEndpoint = nil
        showForceEndpointConfirmation = false
    }

    func startDiscovery() {
        guard !isPreviewMode, isSceneActive, !isDiscovering else { return }
        guard api == nil else { return }
        guard canAttemptEndpointChange else {
            discoveryMessage = "給水操作が完了してから端末を探してください"
            return
        }

        stopDiscovery(invalidate: true)
        let generationAtStart = discoveryGeneration
        isDiscovering = true
        discoveryMessage = "同じWi-Fi内を検索中です…"
        endpointValidationMessage = nil

        discovery.start(
            onCandidate: { [weak self] candidate in
                self?.beginDiscoveryValidation(
                    candidate,
                    generation: generationAtStart
                )
            },
            onState: { [weak self] state in
                self?.handleDiscoveryState(state, generation: generationAtStart)
            }
        )

        discoveryTimeoutTask = Task { [weak self] in
            do {
                try await Task.sleep(nanoseconds: 8_000_000_000)
            } catch {
                return
            }
            guard let self,
                  discoveryGeneration == generationAtStart,
                  api == nil else { return }
            stopDiscovery(invalidate: true)
            discoveryMessage = "端末が見つかりませんでした"
        }
    }

    func activate() {
        isSceneActive = true
        if isPreviewMode {
            connectionState = hasEndpoint ? .online : .unconfigured
            return
        }
        guard api != nil else {
            connectionState = .unconfigured
            startDiscovery()
            return
        }
        startPolling()
    }

    func handleSceneInactive() {
        isSceneActive = false
        pollingTask?.cancel()
        pollingTask = nil
        stopDiscovery(invalidate: true)
        if holdGestureActive || holdStartInFlight || holdActive {
            holdGestureEnded()
        }
    }

    func refreshNow() {
        Task { await refresh() }
    }

    func requestDoseConfirmation() {
        guard canStartWatering else { return }
        showDoseConfirmation = true
    }

    func startConfirmedDose() {
        showDoseConfirmation = false
        guard canStartWatering,
              let coordinator,
              let maximum = status?.maximumDurationSeconds else { return }
        let duration = selectedDurationSeconds
        operationGeneration += 1
        let generationAtStart = operationGeneration
        isActionInFlight = true
        statusAdoptionGate.beginOperation()
        notice = nil

        Task {
            do {
                try await coordinator.startDose(
                    durationSeconds: duration,
                    maximumDurationSeconds: maximum,
                    operationGeneration: generationAtStart
                )
                notice = AppNotice(level: .success, text: "給水を開始しました")
            } catch {
                notice = AppNotice(level: .warning, text: actionErrorMessage(error))
            }
            await syncSafetyState()
            statusAdoptionGate.endOperation()
            isActionInFlight = false
            await refresh()
        }
    }

    func stopNow() {
        guard let coordinator else { return }
        operationGeneration += 1
        let generationAtStop = operationGeneration
        holdStartTask?.cancel()
        holdStartTask = nil
        activeStopRequests += 1
        isStopping = true
        statusAdoptionGate.beginOperation()
        holdGestureActive = false
        notice = nil
        Task {
            do {
                try await coordinator.stop(operationGeneration: generationAtStop)
                if generationAtStop == operationGeneration {
                    notice = AppNotice(level: .success, text: "停止を確認しました")
                }
            } catch {
                if generationAtStop == operationGeneration {
                    notice = AppNotice(
                        level: .warning,
                        text: "停止を確認できません。端末とポンプを直接確認してください"
                    )
                }
            }
            await syncSafetyState()
            statusAdoptionGate.endOperation()
            activeStopRequests -= 1
            isStopping = activeStopRequests > 0
            await refresh()
        }
    }

    func holdGestureBegan() {
        guard canStartWatering, !holdGestureActive, let coordinator else { return }
        holdGestureActive = true
        holdStartInFlight = true
        statusAdoptionGate.beginOperation()
        notice = nil
        let generationAtStart = operationGeneration

        holdStartTask = Task {
            defer {
                statusAdoptionGate.endOperation()
                holdStartInFlight = false
                holdStartTask = nil
            }
            guard operationGeneration == generationAtStart, !isStopping else {
                return
            }
            do {
                try await coordinator.beginHold(operationGeneration: generationAtStart)
            } catch {
                if operationGeneration == generationAtStart, !isStopping {
                    notice = AppNotice(level: .warning, text: actionErrorMessage(error))
                }
            }
            await syncSafetyState()
            if operationGeneration != generationAtStart {
                return
            }
            if !holdGestureActive, !isStopping {
                holdGestureEnded()
            }
        }
    }

    func holdGestureEnded() {
        let shouldEndHold = holdGestureActive || holdStartInFlight || holdActive
        holdGestureActive = false
        guard !isStopping, shouldEndHold, !holdEndInFlight else { return }
        operationGeneration += 1
        let generationAtEnd = operationGeneration
        holdStartTask?.cancel()
        holdEndInFlight = true
        statusAdoptionGate.beginOperation()
        Task { await performHoldEnd(operationGeneration: generationAtEnd) }
    }

    private func handleDiscoveryState(
        _ state: BonjourDeviceDiscovery.State,
        generation: Int
    ) {
        guard discoveryGeneration == generation, api == nil else { return }
        switch state {
        case .ready:
            discoveryMessage = "同じWi-Fi内を検索中です…"
        case .waiting:
            discoveryMessage = "ローカルネットワークの許可を確認しています…"
        case .failed:
            stopDiscovery(invalidate: true)
            discoveryMessage = "自動検出を開始できませんでした"
        }
    }

    private func beginDiscoveryValidation(
        _ candidate: BonjourDeviceCandidate,
        generation: Int
    ) {
        guard discoveryGeneration == generation,
              api == nil,
              discoveryValidationTasks[candidate.name] == nil else { return }
        discoveryMessage = "端末を確認しています…"
        discoveryValidationTasks[candidate.name] = Task { [weak self] in
            guard let self else { return }
            await validateDiscoveredCandidate(candidate, generation: generation)
            discoveryValidationTasks[candidate.name] = nil
        }
    }

    private func stopDiscovery(invalidate: Bool) {
        if invalidate {
            discoveryGeneration += 1
        }
        discovery.stop()
        discoveryTimeoutTask?.cancel()
        discoveryTimeoutTask = nil
        for task in discoveryValidationTasks.values {
            task.cancel()
        }
        discoveryValidationTasks.removeAll()
        isDiscovering = false
    }

    private func validateDiscoveredCandidate(
        _ candidate: BonjourDeviceCandidate,
        generation: Int
    ) async {
        let client = AtomAPIClient(endpoint: candidate.endpoint, requestTimeout: 2)
        do {
            let verifiedStatus = try await client.fetchStatus()
            guard !Task.isCancelled,
                  discoveryGeneration == generation,
                  api == nil,
                  isSceneActive else { return }
            guard verifiedStatus.isCompatibleDiscoveryTarget,
                  verifiedStatus.deviceName?.lowercased() == candidate.name else {
                discoveryMessage = "対応する端末を確認できません。探し続けています…"
                return
            }

            guard applyEndpoint(candidate.endpoint),
                  let statusToken = statusAdoptionGate.beginStatusRequest(),
                  let coordinator else { return }
            let endpointGenerationAtStart = endpointGeneration
            let statusObservation = await coordinator.beginStatusObservation()
            guard endpointGeneration == endpointGenerationAtStart,
                  statusAdoptionGate.canAdopt(statusToken) else { return }
            status = verifiedStatus
            connectionState = .online
            if let normalized = WateringDurationPolicy.normalized(
                currentSeconds: selectedDurationSeconds,
                maximumSeconds: verifiedStatus.maximumDurationSeconds
            ) {
                selectedDurationSeconds = normalized
            }
            await coordinator.reconcile(
                status: verifiedStatus,
                observation: statusObservation
            )
            guard endpointGeneration == endpointGenerationAtStart,
                  statusAdoptionGate.canAdopt(statusToken) else { return }
            await syncSafetyState(statusToken: statusToken)
            guard endpointGeneration == endpointGenerationAtStart,
                  statusAdoptionGate.canAdopt(statusToken) else { return }
            notice = AppNotice(level: .success, text: "端末を自動検出して接続しました")
        } catch is CancellationError {
            return
        } catch {
            guard discoveryGeneration == generation, api == nil else { return }
            discoveryMessage = "応答を確認できません。探し続けています…"
        }
    }

    private func applyEndpoint(_ endpoint: DeviceEndpoint) -> Bool {
        stopDiscovery(invalidate: true)
        let normalized = endpoint.baseURL.absoluteString
        defaults.set(normalized, forKey: Self.endpointDefaultsKey)
        endpointInput = normalized
        endpointValidationMessage = nil
        pendingEndpoint = nil
        showForceEndpointConfirmation = false
        install(endpoint: endpoint)
        activate()
        return true
    }

    private func install(endpoint: DeviceEndpoint) {
        endpointGeneration += 1
        lastSafetySnapshotRevision = 0
        activeRefreshGeneration = nil
        isRefreshing = false
        pollingTask?.cancel()
        let client = AtomAPIClient(endpoint: endpoint)
        api = client
        coordinator = WateringCoordinator(api: client)
        status = nil
        connectionState = .connecting
        stopRecommended = false
        holdActive = false
    }

    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            guard let self else { return }
            await self.refresh()
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                } catch {
                    return
                }
                await self.refresh()
            }
        }
    }

    private func refresh() async {
        let generationAtStart = endpointGeneration
        guard activeRefreshGeneration == nil,
              let api,
              let coordinator,
              let statusToken = statusAdoptionGate.beginStatusRequest() else { return }
        activeRefreshGeneration = generationAtStart
        isRefreshing = true
        if status == nil {
            connectionState = .connecting
        }
        defer {
            if activeRefreshGeneration == generationAtStart {
                activeRefreshGeneration = nil
                isRefreshing = false
            }
        }

        let statusObservation = await coordinator.beginStatusObservation()
        guard endpointGeneration == generationAtStart,
              statusAdoptionGate.canAdopt(statusToken),
              !Task.isCancelled,
              isSceneActive else { return }

        do {
            let latest = try await api.fetchStatus()
            guard endpointGeneration == generationAtStart,
                  statusAdoptionGate.canAdopt(statusToken),
                  !Task.isCancelled,
                  isSceneActive else { return }
            status = latest
            connectionState = .online
            if let normalized = WateringDurationPolicy.normalized(
                currentSeconds: selectedDurationSeconds,
                maximumSeconds: latest.maximumDurationSeconds
            ) {
                selectedDurationSeconds = normalized
            }
            await coordinator.reconcile(
                status: latest,
                observation: statusObservation
            )
            guard endpointGeneration == generationAtStart,
                  statusAdoptionGate.canAdopt(statusToken) else { return }
            await syncSafetyState(statusToken: statusToken)
        } catch is CancellationError {
            return
        } catch {
            if endpointGeneration == generationAtStart,
               statusAdoptionGate.canAdopt(statusToken),
               isSceneActive {
                connectionState = .offline
            }
        }
    }

    private func performHoldEnd(operationGeneration: Int) async {
        if let coordinator {
            do {
                try await coordinator.endHold(operationGeneration: operationGeneration)
            } catch {
                notice = AppNotice(
                    level: .warning,
                    text: "停止を確認できません。端末とポンプを直接確認してください"
                )
            }
            await syncSafetyState()
        }
        statusAdoptionGate.endOperation()
        holdEndInFlight = false
        if isSceneActive {
            await refresh()
        }
    }

    private func syncSafetyState(
        statusToken: StatusAdoptionGate.Token? = nil
    ) async {
        let generationAtStart = endpointGeneration
        guard let coordinator else { return }
        let snapshot = await coordinator.snapshot()
        guard endpointGeneration == generationAtStart else { return }
        if let statusToken {
            guard statusAdoptionGate.canAdopt(statusToken) else { return }
        }
        guard snapshot.revision > lastSafetySnapshotRevision else { return }
        lastSafetySnapshotRevision = snapshot.revision
        stopRecommended = snapshot.stopRecommended
        holdActive = snapshot.holdActive
    }

    private func endpointErrorMessage(_ error: Error) -> String {
        switch error as? DeviceEndpointError {
        case .nonLocalHost:
            "LAN内のIPアドレス、または.localホスト名を入力してください"
        case .unsupportedScheme:
            "http:// から始まるアドレスを入力してください"
        case .unexpectedComponents:
            "パスやログイン情報を含めず、端末のアドレスだけ入力してください"
        default:
            "端末アドレスを確認してください"
        }
    }

    private func actionErrorMessage(_ error: Error) -> String {
        guard let safetyError = error as? WateringSafetyError else {
            return "端末と通信できませんでした"
        }
        switch safetyError {
        case .invalidDuration:
            return "給水時間が端末の上限外です"
        case let .rejected(code):
            return firmwareErrorMessage(code)
        case .ambiguousStart:
            return "開始結果が不明です。再実行せず、状態を確認して必要なら停止してください"
        case .ambiguousHoldStart:
            return "長押し給水の確認に失敗したため、停止指示を送りました"
        case .stopUnconfirmed:
            return "停止を確認できません。端末とポンプを直接確認してください"
        case .holdAlreadyActive:
            return "長押し給水はすでに開始処理中です"
        case .holdStartInvalidated:
            return "停止操作を優先し、長押し給水を開始しませんでした"
        case .doseStartInvalidated:
            return "停止操作を優先しました。状態を確認し、必要ならもう一度停止してください"
        }
    }

    private func firmwareErrorMessage(_ code: String) -> String {
        switch code {
        case "boot_guard": "起動直後の安全待機中です"
        case "not_armed": "端末が給水可能状態ではありません"
        case "pump_busy": "ポンプはすでに動作中です"
        case "duration_out_of_range": "給水時間が端末の上限外です"
        default: "端末が操作を拒否しました（\(code)）"
        }
    }

    private static func makePreviewStatus() -> AtomStatus? {
        let data = Data(#"{"state":"IDLE","pump":false,"armed":true,"watering_mode":"NONE","moisture_adc":1688,"default_duration_sec":10,"max_duration_sec":180,"scheduled_ms":0,"remaining_ms":0,"hold_lease_ms":1500,"hold_max_run_ms":600000,"hold_lease_remaining_ms":0,"uptime_ms":571900,"wifi_rssi":-54,"firmware_version":"0.4.1","last_request_id":"preview","last_runtime_ms":0,"last_stop_reason":"NONE","error_reason":null}"#.utf8)
        return try? JSONDecoder().decode(AtomStatus.self, from: data)
    }

    private static func makeWateringPreviewStatus() -> AtomStatus? {
        let data = Data(#"{"state":"WATERING","pump":true,"armed":true,"watering_mode":"TIMED","moisture_adc":1688,"default_duration_sec":10,"max_duration_sec":180,"scheduled_ms":10000,"remaining_ms":6500,"hold_lease_ms":1500,"hold_max_run_ms":600000,"hold_lease_remaining_ms":0,"uptime_ms":575400,"wifi_rssi":-54,"firmware_version":"0.4.1","last_request_id":"preview-water","last_runtime_ms":0,"last_stop_reason":"NONE","error_reason":null}"#.utf8)
        return try? JSONDecoder().decode(AtomStatus.self, from: data)
    }
}
