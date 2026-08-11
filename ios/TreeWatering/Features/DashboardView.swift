import SwiftUI
import TreeCore

struct DashboardView: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        NavigationStack {
            ZStack {
                TreeGlassBackdrop()

                ScrollView {
                    LazyVStack(spacing: 18) {
                        dashboardHeader
                        StatusCard(model: model)

                        if let notice = model.notice {
                            NoticeBanner(notice: notice)
                                .transition(.move(edge: .top).combined(with: .opacity))
                        }

                        DoseCard(model: model)
                        HoldCard(model: model)
                        deviceFooter
                    }
                    .padding(.horizontal, 18)
                    .padding(.top, 12)
                    .padding(.bottom, model.shouldShowStop ? 136 : 28)
                    .frame(maxWidth: 620)
                    .frame(maxWidth: .infinity)
                }
                .refreshable { model.refreshNow() }
                .safeAreaInset(edge: .bottom, spacing: 0) {
                    if model.shouldShowStop {
                        StopCard(model: model)
                            .frame(maxWidth: 620)
                            .padding(.horizontal, 18)
                            .padding(.vertical, 10)
                            .frame(maxWidth: .infinity)
                            .background(Color.treeCanvas.opacity(0.94))
                    }
                }
            }
            .toolbar(.hidden, for: .navigationBar)
        }
        .alert("給水を開始しますか", isPresented: $model.showDoseConfirmation) {
            Button("キャンセル", role: .cancel) {}
            Button("給水する", role: .destructive) {
                model.startConfirmedDose()
            }
        } message: {
            Text("ポンプを\(model.selectedDurationSeconds)秒動かします。開始操作は通信エラーでも自動再送しません。")
        }
        .animation(.easeOut(duration: 0.22), value: model.notice)
    }

    private var dashboardHeader: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("木のみず")
                    .font(.system(size: 30, weight: .heavy, design: .rounded))
                    .foregroundStyle(Color.treeInk)
                Text("BALCONY WATERING")
                    .font(.caption2.weight(.bold))
                    .tracking(1.6)
                    .foregroundStyle(Color.treeInk.opacity(0.58))
            }

            Spacer()
            GlassEffectContainer(spacing: 10) {
                HStack(spacing: 10) {
                    ConnectionPill(state: model.connectionState)
                    Button {
                        model.showSettings = true
                    } label: {
                        Image(systemName: "slider.horizontal.3")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color.treeInk)
                            .frame(width: 42, height: 42)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .accessibilityLabel("接続設定")
                }
            }
        }
        .padding(.horizontal, 2)
    }

    private var deviceFooter: some View {
        HStack(spacing: 8) {
            Image(systemName: "dot.radiowaves.left.and.right")
            Text(model.endpointHost)
            Spacer()
            if let version = model.status?.firmwareVersion {
                Text("FW \(version)")
            }
        }
        .font(.caption.monospaced().weight(.medium))
        .foregroundStyle(Color.treeInk.opacity(0.64))
        .padding(.horizontal, 6)
        .padding(.top, 4)
    }
}

private struct StatusCard: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        VStack(spacing: 20) {
            HStack(alignment: .center, spacing: 18) {
                StatusOrb(
                    availability: model.status?.wateringAvailability,
                    isOnline: model.isOnline,
                    isRefreshing: model.isRefreshing,
                    remainingFraction: model.status.flatMap { status in
                        WateringCountdownProgress.remainingFraction(
                            remainingMilliseconds: status.remainingMilliseconds,
                            scheduledMilliseconds: status.scheduledMilliseconds
                        )
                    }
                )

                VStack(alignment: .leading, spacing: 6) {
                    Text(statusTitle)
                        .font(.system(size: 25, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.treeInk)
                    Text(statusDetail)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(Color.treeInk.opacity(0.64))
                        .fixedSize(horizontal: false, vertical: true)

                    if let remaining = model.status?.remainingMilliseconds,
                       remaining > 0 {
                        Text("あと約 \(max(1, Int(ceil(Double(remaining) / 1_000))))秒")
                            .font(.headline.monospacedDigit())
                            .foregroundStyle(Color.treeWater)
                            .padding(.top, 3)
                    }
                }
                Spacer(minLength: 0)
            }

            HStack(spacing: 10) {
                MetricTile(
                    icon: "sensor.fill",
                    value: model.status.map { String($0.moistureADC) } ?? "—",
                    label: "土センサー · ADC"
                )
                MetricTile(
                    icon: "wifi",
                    value: model.status.map { "\($0.wifiRSSI)" } ?? "—",
                    label: "電波 · dBm"
                )
            }
        }
        .treeCard()
    }

    private var statusTitle: String {
        switch model.connectionState {
        case .unconfigured: "接続先が未設定です"
        case .connecting: "端末を探しています"
        case .offline: "端末に接続できません"
        case .online: model.status?.wateringAvailability.japaneseTitle ?? "状態を取得中"
        }
    }

    private var statusDetail: String {
        switch model.connectionState {
        case .unconfigured: "設定から端末アドレスを入力してください"
        case .connecting: "同じWi-Fiにいるか確認しています"
        case .offline: "電源・Wi-Fi・端末アドレスを確認してください"
        case .online: model.status?.wateringAvailability.japaneseDetail ?? "少し待ってください"
        }
    }
}

private struct StatusOrb: View {
    let availability: WateringAvailability?
    let isOnline: Bool
    let isRefreshing: Bool
    let remainingFraction: Double?

    var tint: Color {
        guard isOnline else { return Color.treeInk.opacity(0.28) }
        return availability?.tint ?? .orange
    }

    var body: some View {
        ZStack {
            Circle()
                .fill(tint.opacity(0.12))
            if availability == .watering, let remainingFraction {
                Circle()
                    .stroke(tint.opacity(0.16), lineWidth: 7)
                    .padding(5)
                Circle()
                    .trim(from: 0, to: remainingFraction)
                    .stroke(
                        tint,
                        style: StrokeStyle(lineWidth: 7, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))
                    .padding(5)
                    .animation(.linear(duration: 0.25), value: remainingFraction)
            } else {
                Circle()
                    .stroke(tint.opacity(0.20), lineWidth: 6)
                    .padding(5)
            }
            Image(systemName: availability == .watering ? "drop.fill" : "leaf.fill")
                .font(.system(size: 32, weight: .bold))
                .foregroundStyle(tint)
                .symbolEffect(.pulse, options: .repeating, isActive: availability == .watering)
            if isRefreshing {
                Circle()
                    .trim(from: 0.02, to: 0.24)
                    .stroke(tint, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .padding(15)
            }
        }
        .frame(width: 94, height: 94)
        .accessibilityHidden(true)
    }
}

private struct MetricTile: View {
    let icon: String
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: icon)
                .font(.subheadline.weight(.bold))
                .foregroundStyle(Color.treeLeaf)
            Text(value)
                .font(.system(size: 22, weight: .bold, design: .monospaced))
                .foregroundStyle(Color.treeInk)
                .contentTransition(.numericText())
            Text(label)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(Color.treeInk.opacity(0.64))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(15)
        .background(Color.treeCanvas.opacity(0.66))
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

private struct DoseCard: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("時間を決めて給水")
                        .font(.headline)
                        .foregroundStyle(Color.treeInk)
                    Text("指定時間で必ず自動停止")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.treeInk.opacity(0.64))
                }
                Spacer()
                Image(systemName: "timer")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(Color.treeWater)
            }

            HStack(spacing: 8) {
                ForEach(model.durationOptions, id: \.self) { seconds in
                    Button {
                        model.selectedDurationSeconds = seconds
                    } label: {
                        Text("\(seconds)秒")
                            .font(.subheadline.monospacedDigit().weight(.bold))
                            .frame(maxWidth: .infinity)
                            .frame(height: 40)
                            .foregroundStyle(
                                model.selectedDurationSeconds == seconds
                                    ? Color.treeCanvas : Color.treeInk
                            )
                            .glassEffect(
                                .regular
                                    .tint(
                                        model.selectedDurationSeconds == seconds
                                            ? Color.treeForest : nil
                                    )
                                    .interactive(),
                                in: Capsule()
                            )
                    }
                    .buttonStyle(.plain)
                }
            }

            Button {
                model.requestDoseConfirmation()
            } label: {
                HStack {
                    if model.isActionInFlight {
                        ProgressView()
                            .tint(
                                model.canStartWatering
                                    ? Color.treeCanvas : Color.treeInk
                            )
                    } else {
                        Image(systemName: "drop.fill")
                    }
                    Text(model.isActionInFlight ? "開始を確認中…" : "\(model.selectedDurationSeconds)秒給水")
                    Spacer()
                    Image(systemName: "arrow.right")
                }
                .font(.headline)
                .foregroundStyle(
                    model.canStartWatering ? Color.white : Color.treeInk
                )
                .padding(.horizontal, 20)
                .frame(maxWidth: .infinity)
                .frame(height: 58)
            }
            .buttonStyle(.glassProminent)
            .buttonBorderShape(.roundedRectangle(radius: 18))
            .tint(model.canStartWatering ? Color.treeForest : Color.treeInk.opacity(0.22))
            .disabled(!model.canStartWatering)
        }
        .treeCard()
    }
}

private struct HoldCard: View {
    @ObservedObject var model: DashboardViewModel

    private var acceptsTouch: Bool {
        model.canStartWatering || model.holdGestureActive || model.holdStartInFlight || model.holdActive
    }

    private var unavailableMessage: String {
        model.status?.wateringAvailability == .unarmed
            ? "端末が未アームです"
            : "状態確認後に操作できます"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("微調整")
                .font(.caption.weight(.bold))
                .tracking(1.2)
                .foregroundStyle(Color.treeInk.opacity(0.62))

            HStack(spacing: 14) {
                Image(systemName: model.holdGestureActive ? "hand.tap.fill" : "hand.tap")
                    .font(.title2.weight(.semibold))
                VStack(alignment: .leading, spacing: 2) {
                    Text("押している間だけ給水")
                        .font(.headline)
                    Text(
                        model.holdStartInFlight
                            ? "開始を確認中…"
                            : (acceptsTouch ? "離すとすぐ停止" : unavailableMessage)
                    )
                        .font(.caption.weight(.medium))
                        .opacity(acceptsTouch ? 0.68 : 1)
                }
                Spacer()
            }
            .foregroundStyle(
                model.holdGestureActive
                    ? Color.treeCanvas
                    : Color.treeInk.opacity(acceptsTouch ? 1 : 0.64)
            )
            .padding(.horizontal, 18)
            .frame(height: 70)
            .glassEffect(
                .regular
                    .tint(model.holdGestureActive ? Color.treeWater : nil)
                    .interactive(acceptsTouch),
                in: RoundedRectangle(cornerRadius: 20, style: .continuous)
            )
            .contentShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        if acceptsTouch { model.holdGestureBegan() }
                    }
                    .onEnded { _ in model.holdGestureEnded() }
            )
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
            .accessibilityHint(acceptsTouch ? "画面を押している間だけポンプが動きます" : unavailableMessage)
            .sensoryFeedback(.impact(weight: .medium), trigger: model.holdGestureActive)

            Label("通信が途切れても、端末側の安全機構が1.5秒以内に停止します", systemImage: "shield.checkered")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(Color.treeInk.opacity(0.72))
                .fixedSize(horizontal: false, vertical: true)
        }
        .treeCard()
    }
}

private struct StopCard: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        Button {
            model.stopNow()
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "stop.fill")
                    .font(.headline)
                VStack(alignment: .leading, spacing: 2) {
                    Text("今すぐ停止")
                        .font(.headline)
                    Text("確認が取れるまで再度押せます")
                        .font(.caption.weight(.medium))
                        .opacity(0.78)
                }
                Spacer()
                if model.isStopping {
                    ProgressView().tint(.white)
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 20)
            .frame(maxWidth: .infinity)
            .frame(height: 68)
            .background(Color.treeWarning)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
        .buttonStyle(.plain)
        .contentShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .shadow(color: Color.treeWarning.opacity(0.20), radius: 18, y: 9)
        .accessibilityHint("停止確認中でも繰り返し押せます")
    }
}

private struct NoticeBanner: View {
    let notice: AppNotice

    private var tint: Color {
        switch notice.level {
        case .info: .treeWater
        case .warning: .treeWarning
        case .success: .treeLeaf
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            Image(systemName: notice.level == .warning ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                .foregroundStyle(tint)
            Text(notice.text)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.treeInk)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(16)
        .glassEffect(
            .regular.tint(tint.opacity(0.12)),
            in: RoundedRectangle(cornerRadius: 18, style: .continuous)
        )
    }
}

private struct ConnectionPill: View {
    let state: DeviceConnectionState

    private var color: Color {
        switch state {
        case .online: .treeLeaf
        case .connecting: .orange
        case .offline, .unconfigured: Color.treeInk.opacity(0.35)
        }
    }

    private var title: String {
        switch state {
        case .online: "接続済み"
        case .connecting: "確認中"
        case .offline: "オフライン"
        case .unconfigured: "未設定"
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(title)
                .font(.caption2.weight(.bold))
                .foregroundStyle(Color.treeInk.opacity(0.70))
        }
        .padding(.horizontal, 10)
        .frame(height: 32)
        .glassEffect(.regular.tint(color.opacity(0.08)), in: Capsule())
        .accessibilityLabel("接続状態、\(title)")
    }
}
