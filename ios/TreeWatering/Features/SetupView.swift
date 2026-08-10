import SwiftUI

struct SetupView: View {
    @ObservedObject var model: DashboardViewModel
    @FocusState private var endpointFocused: Bool
    @State private var showsManualSetup = false

    var body: some View {
        ZStack {
            TreeGlassBackdrop()

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Spacer(minLength: 54)

                    ZStack {
                        Image(systemName: "drop.fill")
                            .font(.system(size: 42, weight: .semibold))
                            .foregroundStyle(Color.white)
                        Image(systemName: "leaf.fill")
                            .font(.system(size: 21, weight: .bold))
                            .foregroundStyle(Color.treeWater)
                            .offset(x: 22, y: -22)
                    }
                    .frame(width: 92, height: 92)
                    .glassEffect(
                        .regular.tint(Color.treeForest),
                        in: RoundedRectangle(cornerRadius: 30, style: .continuous)
                    )
                    .accessibilityHidden(true)

                    Text("木のみず")
                        .font(.system(size: 42, weight: .heavy, design: .rounded))
                        .foregroundStyle(Color.treeInk)
                        .padding(.top, 26)

                    GlassEffectContainer(spacing: 14) {
                        VStack(spacing: 14) {
                            discoveryStatus

                            if !model.isDiscovering {
                                Button(action: model.startDiscovery) {
                                    Label("もう一度探す", systemImage: "arrow.clockwise")
                                        .font(.headline)
                                        .frame(maxWidth: .infinity)
                                        .frame(height: 54)
                                }
                                .buttonStyle(.glassProminent)
                                .buttonBorderShape(.roundedRectangle(radius: 18))
                                .tint(Color.treeForest)
                            }
                        }
                    }
                    .padding(.top, 32)

                    manualSetup
                        .padding(.top, 18)

                    Spacer(minLength: 42)
                }
                .padding(.horizontal, 28)
                .frame(maxWidth: 560, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
    }

    private var discoveryStatus: some View {
        HStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(Color.treeWater.opacity(0.18))
                    .frame(width: 54, height: 54)
                if model.isDiscovering {
                    ProgressView()
                        .controlSize(.regular)
                        .tint(Color.treeForest)
                        .accessibilityLabel("端末を検索中")
                } else {
                    Image(systemName: "sensor.tag.radiowaves.forward.fill")
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(Color.treeForest)
                        .accessibilityHidden(true)
                }
            }

            VStack(alignment: .leading, spacing: 5) {
                Text(model.isDiscovering ? "端末を探しています" : "自動検出")
                    .font(.headline)
                    .foregroundStyle(Color.treeInk)
                Text(model.discoveryMessage)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.treeInk.opacity(0.68))
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassEffect(
            .regular,
            in: RoundedRectangle(cornerRadius: 22, style: .continuous)
        )
    }

    private var manualSetup: some View {
        DisclosureGroup(isExpanded: $showsManualSetup) {
            VStack(alignment: .leading, spacing: 12) {
                Text("端末アドレス")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(Color.treeInk)

                TextField(
                    "",
                    text: $model.endpointInput,
                    prompt: Text("例：http://<ATOMのLAN内IP>")
                        .foregroundStyle(Color.treeInk.opacity(0.55))
                )
                .font(.system(.body, design: .monospaced, weight: .medium))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .submitLabel(.go)
                .focused($endpointFocused)
                .padding(16)
                .glassEffect(
                    .regular.interactive(),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous)
                )
                .onSubmit { connect() }
                .accessibilityLabel("端末アドレス")
                .accessibilityHint(
                    model.endpointValidationMessage
                        ?? "自動検出できない場合だけLAN内の端末アドレスを入力してください"
                )

                if let message = model.endpointValidationMessage {
                    Label(message, systemImage: "exclamationmark.circle.fill")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(Color.treeWarning)
                }

                Button(action: connect) {
                    HStack {
                        Text("このアドレスにつなぐ")
                        Spacer()
                        Image(systemName: "arrow.right")
                    }
                    .font(.headline)
                    .foregroundStyle(Color.white)
                    .padding(.horizontal, 20)
                    .frame(maxWidth: .infinity)
                    .frame(height: 56)
                }
                .buttonStyle(.glassProminent)
                .buttonBorderShape(.roundedRectangle(radius: 18))
                .tint(Color.treeForest)
            }
            .padding(.top, 16)
        } label: {
            Label("手動で設定", systemImage: "keyboard")
                .font(.subheadline.weight(.bold))
                .foregroundStyle(Color.treeInk.opacity(0.78))
        }
        .tint(Color.treeForest)
        .padding(18)
        .background(Color.white.opacity(0.62))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private func connect() {
        if model.saveEndpoint() {
            endpointFocused = false
        }
    }
}
