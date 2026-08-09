import SwiftUI

struct SetupView: View {
    @ObservedObject var model: DashboardViewModel
    @FocusState private var endpointFocused: Bool

    var body: some View {
        ZStack {
            Color.treeCanvas.ignoresSafeArea()
            SetupBackdrop()

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Spacer(minLength: 72)

                    ZStack {
                        RoundedRectangle(cornerRadius: 30, style: .continuous)
                            .fill(Color.treeForest)
                            .frame(width: 92, height: 92)
                        Image(systemName: "drop.fill")
                            .font(.system(size: 42, weight: .semibold))
                            .foregroundStyle(Color.treeCanvas)
                        Image(systemName: "leaf.fill")
                            .font(.system(size: 21, weight: .bold))
                            .foregroundStyle(Color.treeWater)
                            .offset(x: 22, y: -22)
                    }
                    .accessibilityHidden(true)

                    Text("木のみず")
                        .font(.system(size: 42, weight: .heavy, design: .rounded))
                        .foregroundStyle(Color.treeInk)
                        .padding(.top, 30)

                    Text("ベランダの端末へ、Wi-Fiから直接つなぎます。クラウドやアカウントは使いません。")
                        .font(.system(size: 18, weight: .medium))
                        .foregroundStyle(Color.treeInk.opacity(0.68))
                        .lineSpacing(5)
                        .padding(.top, 12)

                    VStack(alignment: .leading, spacing: 12) {
                        Text("端末アドレス")
                            .font(.subheadline.weight(.bold))
                            .foregroundStyle(Color.treeInk)

                        TextField("http://192.168.1.50", text: $model.endpointInput)
                            .font(.system(.body, design: .monospaced, weight: .medium))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .submitLabel(.go)
                            .focused($endpointFocused)
                            .padding(16)
                            .background(Color.white.opacity(0.84))
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .overlay {
                                RoundedRectangle(cornerRadius: 16, style: .continuous)
                                    .stroke(Color.treeInk.opacity(0.12), lineWidth: 1)
                            }
                            .onSubmit { connect() }

                        if let message = model.endpointValidationMessage {
                            Label(message, systemImage: "exclamationmark.circle.fill")
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(Color.treeWarning)
                        }

                        Button(action: connect) {
                            HStack {
                                Text("端末につなぐ")
                                Spacer()
                                Image(systemName: "arrow.right")
                            }
                            .font(.headline)
                            .foregroundStyle(Color.treeCanvas)
                            .padding(.horizontal, 20)
                            .frame(height: 58)
                            .background(Color.treeForest)
                            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(.top, 38)

                    Label("同じWi-Fiに接続した状態で設定してください", systemImage: "wifi")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(Color.treeInk.opacity(0.56))
                        .padding(.top, 20)

                    Spacer(minLength: 48)
                }
                .padding(.horizontal, 28)
                .frame(maxWidth: 560, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
        .onAppear { endpointFocused = model.endpointInput.isEmpty }
    }

    private func connect() {
        if model.saveEndpoint() {
            endpointFocused = false
        }
    }
}

private struct SetupBackdrop: View {
    var body: some View {
        GeometryReader { proxy in
            Circle()
                .fill(Color.treeWater.opacity(0.11))
                .frame(width: proxy.size.width * 0.9)
                .offset(x: proxy.size.width * 0.47, y: -proxy.size.width * 0.28)
            Circle()
                .fill(Color.treeLeaf.opacity(0.10))
                .frame(width: proxy.size.width * 0.7)
                .offset(x: -proxy.size.width * 0.30, y: proxy.size.height * 0.72)
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }
}
