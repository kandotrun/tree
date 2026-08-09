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
    @Published private(set) var endpointValidationMessage: String?
    @Published private(set) var status: AtomStatus?
    @Published private(set) var connectionState: DeviceConnectionState = .unconfigured
    @Published private(set) var isRefreshing = false
    @Published private(set) var isActionInFlight = false
    @Published private(set) var isStopping = false
    @Published private(set) var holdGestureActive = false
    @Published private(set) var holdStartInFlight = false
    @Published private(set) var holdActive = false
    @Published private(set) var stopRecommended = false
    @Published var notice: AppNotice?

    private let defaults: UserDefaults
    private let isPreviewMode: Bool
    private var api: AtomAPIClient?
    private var coordinator: WateringCoordinator?
    private var pollingTask: Task<Void, Never>?
    private var holdEndInFlight = false
    private var isSceneActive = false

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
#if DEBUG
        let previewMode = ProcessInfo.processInfo.arguments.contains("-ui-preview")
#else
        let previewMode = false
#endif
        isPreviewMode = previewMode
        if previewMode,
           let endpoint = try? DeviceEndpoint("http://127.0.0.1") {
            endpointInput = endpoint.baseURL.absoluteString
            install(endpoint: endpoint)
            status = Self.makePreviewStatus()
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
        let maximum = min(status?.maximumDurationSeconds ?? 180, 180)
        let options = [5, 10, 30, 60, 120].filter { $0 <= maximum }
        return options.isEmpty ? [max(1, maximum)] : options
    }

    var canStartWatering: Bool {
        isOnline
            && status?.canStartWatering == true
            && !isActionInFlight
            && !isStopping
            && !holdStartInFlight
            && !holdActive
    }

    var shouldShowStop: Bool {
        stopRecommended || status?.pump == true || status?.state == .watering
    }

    func saveEndpoint() -> Bool {
        guard !shouldShowStop else {
            endpointValidationMessage = "給水を停止してから接続先を変更してください"
            return false
        }
        do {
            let endpoint = try DeviceEndpoint(endpointInput)
            let normalized = endpoint.baseURL.absoluteString
            defaults.set(normalized, forKey: Self.endpointDefaultsKey)
            endpointInput = normalized
            endpointValidationMessage = nil
            install(endpoint: endpoint)
            activate()
            return true
        } catch {
            endpointValidationMessage = endpointErrorMessage(error)
            return false
        }
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
        isStopping = true
        holdGestureActive = false
        notice = nil
        Task {
            defer { isStopping = false }
            do {
                try await coordinator.stop()
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

        Task {
            do {
                try await coordinator.beginHold()
            } catch {
                notice = AppNotice(level: .warning, text: actionErrorMessage(error))
            }
            holdStartInFlight = false
            await syncSafetyState()
            if !holdGestureActive {
                await performHoldEnd()
            }
        }
    }

    func holdGestureEnded() {
        guard holdGestureActive || holdStartInFlight || holdActive else { return }
        holdGestureActive = false
        Task { await performHoldEnd() }
    }

    private func install(endpoint: DeviceEndpoint) {
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
        guard !isRefreshing, let api else { return }
        isRefreshing = true
        if status == nil {
            connectionState = .connecting
        }
        defer { isRefreshing = false }

        do {
            let latest = try await api.fetchStatus()
            guard !Task.isCancelled && isSceneActive else { return }
            status = latest
            connectionState = .online
            selectedDurationSeconds = min(
                max(1, selectedDurationSeconds),
                min(latest.maximumDurationSeconds, 180)
            )
            await coordinator?.reconcile(status: latest)
            await syncSafetyState()
        } catch is CancellationError {
            return
        } catch {
            if isSceneActive {
                connectionState = .offline
            }
        }
    }

    private func performHoldEnd() async {
        guard !holdEndInFlight, let coordinator else { return }
        holdEndInFlight = true
        defer { holdEndInFlight = false }
        do {
            try await coordinator.endHold()
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
        guard let coordinator else { return }
        let snapshot = await coordinator.snapshot()
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
        let data = Data(#"{"state":"IDLE","pump":false,"armed":true,"watering_mode":"NONE","moisture_adc":1688,"scheduled_ms":0,"remaining_ms":0,"uptime_ms":571900,"wifi_rssi":-54,"firmware_version":"0.4.1","last_request_id":null,"error_reason":null,"max_duration_sec":180}"#.utf8)
        return try? JSONDecoder().decode(AtomStatus.self, from: data)
    }
}
