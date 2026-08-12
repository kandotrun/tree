import SwiftUI
import TreeCore

struct DashboardView: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        NavigationStack {
            List {
                Section {
                    DeviceStatusHeader(model: model)
                }

                if let notice = model.notice {
                    Section {
                        InlineNotice(notice: notice)
                    }
                }

                if !model.shouldShowStop {
                    WateringControlsSection(model: model)
                }

                if !model.shouldShowStop || model.shouldKeepHoldControlVisible {
                    HoldControlSection(model: model)
                }

                if !model.shouldShowStop {
                    Section {
                        NavigationLink {
                            DeviceInfoView(model: model)
                        } label: {
                            Label("デバイス情報", systemImage: "sensor.tag.radiowaves.forward")
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .refreshable { await model.refreshAndWait() }
            .navigationTitle("木のみず")
            .toolbar {
                if !model.shouldShowStop {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            model.showSettings = true
                        } label: {
                            Image(systemName: "gearshape")
                        }
                        .accessibilityLabel("設定")
                    }
                }
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if model.shouldShowStop {
                EmergencyStopBar(model: model)
            }
        }
        .alert("給水を開始しますか", isPresented: $model.showDoseConfirmation) {
            Button("キャンセル", role: .cancel) {}
            Button("給水する", role: .destructive) {
                model.startConfirmedDose()
            }
        } message: {
            Text("ポンプを\(model.selectedDurationSeconds)秒動かします。開始操作は通信エラーでも自動再送しません。")
        }
    }
}

private struct DeviceStatusHeader: View {
    @ObservedObject var model: DashboardViewModel

    private var availability: WateringAvailability? {
        model.status?.wateringAvailability
    }

    private var title: String {
        switch model.connectionState {
        case .unconfigured: "未設定"
        case .connecting: "接続中"
        case .offline: "オフライン"
        case .online: availability?.japaneseTitle ?? "状態を確認中"
        }
    }

    private var detail: String {
        switch model.connectionState {
        case .unconfigured: "給水デバイスを追加してください"
        case .connecting: "デバイスの応答を待っています"
        case .offline: "電源とWi-Fiを確認してください"
        case .online: availability?.japaneseDetail ?? "少しお待ちください"
        }
    }

    private var symbolName: String {
        switch model.connectionState {
        case .unconfigured: "plus.circle.fill"
        case .connecting: "antenna.radiowaves.left.and.right"
        case .offline: "wifi.slash"
        case .online: availability?.symbolName ?? "ellipsis.circle.fill"
        }
    }

    private var tint: Color {
        switch model.connectionState {
        case .unconfigured, .connecting: .orange
        case .offline: .secondary
        case .online: availability?.tint ?? .secondary
        }
    }

    private var remainingSeconds: Int? {
        guard let milliseconds = model.status?.remainingMilliseconds,
              milliseconds > 0 else { return nil }
        return max(1, Int(ceil(Double(milliseconds) / 1_000)))
    }

    private var remainingFraction: Double? {
        guard let status = model.status else { return nil }
        return WateringCountdownProgress.remainingFraction(
            remainingMilliseconds: status.remainingMilliseconds,
            scheduledMilliseconds: status.scheduledMilliseconds
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: symbolName)
                    .font(.title2)
                    .foregroundStyle(tint)
                    .frame(width: 30)
                    .symbolEffect(.pulse, options: .repeating, isActive: availability == .watering)
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.title2.weight(.semibold))
                    Text(detail)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 8)

                if model.isRefreshing {
                    ProgressView()
                        .controlSize(.small)
                        .accessibilityLabel("状態を更新中")
                }
            }

            if let remainingSeconds {
                VStack(alignment: .leading, spacing: 8) {
                    Text("残り \(remainingSeconds)秒")
                        .font(.system(.largeTitle, design: .rounded, weight: .semibold))
                        .monospacedDigit()
                        .contentTransition(.numericText())
                    if let remainingFraction {
                        ProgressView(value: remainingFraction)
                            .tint(.blue)
                            .accessibilityLabel("給水の残り時間")
                            .accessibilityValue("残り\(remainingSeconds)秒")
                    }
                }
            }

            if !model.shouldShowStop {
                Label(connectionLabel, systemImage: connectionSymbol)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 8)
        .accessibilityElement(children: .combine)
    }

    private var connectionLabel: String {
        switch model.connectionState {
        case .online: "デバイスに接続済み"
        case .connecting: "接続を確認中"
        case .offline: "デバイスに接続できません"
        case .unconfigured: "デバイスが未設定です"
        }
    }

    private var connectionSymbol: String {
        switch model.connectionState {
        case .online: "checkmark.circle.fill"
        case .connecting: "arrow.triangle.2.circlepath"
        case .offline: "exclamationmark.circle.fill"
        case .unconfigured: "circle.dashed"
        }
    }
}

private struct WateringControlsSection: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        Section {
            Picker("給水時間", selection: $model.selectedDurationSeconds) {
                ForEach(model.durationOptions, id: \.self) { seconds in
                    Text("\(seconds)秒").tag(seconds)
                }
            }
            .pickerStyle(.menu)

            Button {
                model.requestDoseConfirmation()
            } label: {
                HStack {
                    Spacer()
                    if model.isActionInFlight {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Image(systemName: "drop.fill")
                    }
                    Text("\(model.selectedDurationSeconds)秒間給水を開始")
                    Spacer()
                }
                .fontWeight(.semibold)
                .frame(minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(.treeActionFill)
            .disabled(!model.canStartWatering)
        } header: {
            Text("給水")
        } footer: {
            Text("設定した時間が経過すると、デバイス側で自動停止します。")
        }
    }
}

private struct HoldControlSection: View {
    @ObservedObject var model: DashboardViewModel

    private var acceptsTouch: Bool {
        model.canStartWatering
            || model.holdGestureActive
            || model.holdStartInFlight
            || model.holdActive
    }

    private var unavailableMessage: String {
        model.status?.wateringAvailability == .unarmed
            ? "端末が未アームです"
            : "状態確認後に操作できます"
    }

    var body: some View {
        Section {
            HStack(spacing: 12) {
                Image(systemName: model.holdGestureActive ? "hand.tap.fill" : "hand.tap")
                    .foregroundStyle(model.holdGestureActive ? Color.blue : Color.accentColor)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 3) {
                    Text(model.holdGestureActive ? "給水中・離すと停止" : "押している間だけ給水")
                        .fontWeight(model.holdGestureActive ? .semibold : .regular)
                    Text(
                        model.holdStartInFlight
                            ? "開始を確認中…"
                            : (acceptsTouch ? "指を離すと停止します" : unavailableMessage)
                    )
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.vertical, 6)
            .contentShape(Rectangle())
            .opacity(acceptsTouch ? 1 : 0.5)
            .listRowBackground(
                model.holdGestureActive
                    ? Color.blue.opacity(0.12)
                    : Color(uiColor: .secondarySystemGroupedBackground)
            )
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        if acceptsTouch { model.holdGestureBegan() }
                    }
                    .onEnded { _ in model.holdGestureEnded() }
            )
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
            .accessibilityHint(
                acceptsTouch
                    ? "画面を押している間だけポンプが動きます"
                    : unavailableMessage
            )
            .sensoryFeedback(.impact(weight: .medium), trigger: model.holdGestureActive)
        } header: {
            Text("手動給水")
        } footer: {
            Text("通信が途切れても、端末側の安全機構が1.5秒以内に停止します。")
        }
    }
}

private struct DeviceInfoView: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        List {
            Section("デバイス") {
                LabeledContent("名前") {
                    Text(model.status?.deviceName ?? "—")
                }
                LabeledContent("土センサー") {
                    Text(model.status.map { "\($0.moistureADC) ADC" } ?? "—")
                        .monospacedDigit()
                }
                LabeledContent("信号強度") {
                    Text(model.status.map { "\($0.wifiRSSI) dBm" } ?? "—")
                        .monospacedDigit()
                }
                LabeledContent("ファームウェア") {
                    Text(model.status?.firmwareVersion ?? "—")
                }
            }

            Section("接続") {
                LabeledContent("状態", value: connectionTitle)
                LabeledContent("アドレス", value: model.endpointHost)
            }
        }
        .navigationTitle("デバイス情報")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var connectionTitle: String {
        switch model.connectionState {
        case .online: "接続済み"
        case .connecting: "確認中"
        case .offline: "オフライン"
        case .unconfigured: "未設定"
        }
    }
}

private struct EmergencyStopBar: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        VStack(spacing: 6) {
            Button {
                model.stopNow()
            } label: {
                HStack {
                    Spacer()
                    Image(systemName: "stop.fill")
                    Text("給水を停止")
                    if model.isStopping {
                        ProgressView()
                            .tint(.white)
                    }
                    Spacer()
                }
                .fontWeight(.semibold)
                .frame(minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(.red)
            .accessibilityHint("停止確認中でも繰り返し押せます")

            if model.isStopping {
                Text("デバイスからの停止確認を待っています")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(.bar)
    }
}

private struct InlineNotice: View {
    let notice: AppNotice

    private var symbolName: String {
        switch notice.level {
        case .info: "info.circle.fill"
        case .warning: "exclamationmark.triangle.fill"
        case .success: "checkmark.circle.fill"
        }
    }

    private var tint: Color {
        switch notice.level {
        case .info: .blue
        case .warning: .orange
        case .success: .green
        }
    }

    var body: some View {
        Label {
            Text(notice.text)
                .fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: symbolName)
                .foregroundStyle(tint)
        }
        .font(.subheadline)
    }
}
