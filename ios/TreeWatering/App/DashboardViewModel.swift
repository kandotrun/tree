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
    @Published var notice: AppNotice?

    private let defaults: UserDefaults
    private let isPreviewMode: Bool
    private var api: AtomAPIClient?
    private var coordinator: WateringCoordinator?
    private var pollingTask: Task<Void, Never>?
    private var holdStartTask: Task<Void, Never>?
    private var pendingEndpoint: DeviceEndpoint?
    private var isSceneActive = false
    private var holdOperationGeneration = 0
    private var endpointGeneration = 0
    private var activeRefreshGeneration: Int?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
#if DEBUG
        let wateringPreview = ProcessInfo.processInfo.arguments.contains("-ui-preview-watering")
        let previewMode = wateringPreview
            || ProcessInfo.processInfo.arguments.contains("-ui-preview")
#else
        let wateringPreview = false
        let previewMode = false
#endif
        isPreviewMode = previewMode
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
        stopRecommended || status?.pump == true || status?.state == .watering
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

    func activate() {
        isSceneActive = true
        if isPreviewMode {
            connectionState = .online
            return
        }
        guard api != nil else {
            connectionState = .unconfigured
            return
        }
        startPolling()
    }

    func handleSceneInactive() {
        isSceneActive = false
        pollingTask?.cancel()
        pollingTask = nil
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
        isActionInFlight = true
        notice = nil

        Task {
            defer { isActionInFlight = false }
            do {
                try await coordinator.startDose(
                    durationSeconds: duration,
                    maximumDurationSeconds: maximum
                )
                notice = AppNotice(level: .success, text: "給水を開始しました")
            } catch {
                notice = AppNotice(level: .warning, text: actionErrorMessage(error))
            }
            await syncSafetyState()
            await refresh()
        }
    }

    func stopNow() {
        guard !isStopping, let coordinator else { return }
        holdOperationGeneration += 1
        let generationAtStop = holdOperationGeneration
        holdStartTask?.cancel()
        holdStartTask = nil
        isStopping = true
        holdGestureActive = false
        notice = nil
        Task {
            defer { isStopping = false }
            do {
                try await coordinator.stop(operationGeneration: generationAtStop)
                notice = AppNotice(level: .success, text: "停止を確認しました")
            } catch {
                notice = AppNotice(
                    level: .warning,
                    text: "停止を確認できません。端末とポンプを直接確認してください"
                )
            }
            await syncSafetyState()
            await refresh()
        }
    }

    func holdGestureBegan() {
        guard canStartWatering, !holdGestureActive, let coordinator else { return }
        holdGestureActive = true
        holdStartInFlight = true
        notice = nil
        let generationAtStart = holdOperationGeneration

        holdStartTask = Task {
            defer {
                holdStartInFlight = false
                holdStartTask = nil
            }
            guard holdOperationGeneration == generationAtStart, !isStopping else {
                return
            }
            do {
                try await coordinator.beginHold(operationGeneration: generationAtStart)
            } catch {
                if holdOperationGeneration == generationAtStart, !isStopping {
                    notice = AppNotice(level: .warning, text: actionErrorMessage(error))
                }
            }
            await syncSafetyState()
            if holdOperationGeneration != generationAtStart {
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
        holdOperationGeneration += 1
        let operationGeneration = holdOperationGeneration
        holdStartTask?.cancel()
        holdEndInFlight = true
        Task { await performHoldEnd(operationGeneration: operationGeneration) }
    }

    private func applyEndpoint(_ endpoint: DeviceEndpoint) -> Bool {
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
        guard activeRefreshGeneration == nil, let api else { return }
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

        do {
            let latest = try await api.fetchStatus()
            guard endpointGeneration == generationAtStart,
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
            await coordinator?.reconcile(status: latest)
            guard endpointGeneration == generationAtStart else { return }
            await syncSafetyState()
        } catch is CancellationError {
            return
        } catch {
            if endpointGeneration == generationAtStart, isSceneActive {
                connectionState = .offline
            }
        }
    }

    private func performHoldEnd(operationGeneration: Int) async {
        defer { holdEndInFlight = false }
        guard let coordinator else { return }
        do {
            try await coordinator.endHold(operationGeneration: operationGeneration)
        } catch {
            notice = AppNotice(
                level: .warning,
                text: "停止を確認できません。端末とポンプを直接確認してください"
            )
        }
        await syncSafetyState()
        if isSceneActive {
            await refresh()
        }
    }

    private func syncSafetyState() async {
        let generationAtStart = endpointGeneration
        guard let coordinator else { return }
        let snapshot = await coordinator.snapshot()
        guard endpointGeneration == generationAtStart else { return }
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
