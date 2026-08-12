import SwiftUI

struct SetupView: View {
    @ObservedObject var model: DashboardViewModel
    @State private var showsManualSetup = false

    var body: some View {
        NavigationStack {
            ContentUnavailableView {
                Label(
                    model.isDiscovering ? "デバイスを検索中" : "デバイスが見つかりません",
                    systemImage: model.isDiscovering
                        ? "antenna.radiowaves.left.and.right"
                        : "sensor.tag.radiowaves.forward"
                )
            } description: {
                VStack(spacing: 8) {
                    Text(model.discoveryMessage)
                    if model.isDiscovering {
                        ProgressView()
                            .accessibilityLabel("端末を検索中")
                    }
                }
            } actions: {
                if !model.isDiscovering {
                    Button("もう一度探す", systemImage: "arrow.clockwise") {
                        model.startDiscovery()
                    }
                    .buttonStyle(.borderedProminent)
                }

                Button("デバイスのアドレスを入力") {
                    showsManualSetup = true
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
            }
            .navigationTitle("デバイスを追加")
            .navigationBarTitleDisplayMode(.inline)
            .sheet(isPresented: $showsManualSetup) {
                ManualEndpointView(model: model)
            }
        }
    }
}

private struct ManualEndpointView: View {
    @ObservedObject var model: DashboardViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var endpointDraft: String
    @FocusState private var endpointFocused: Bool

    init(model: DashboardViewModel) {
        self.model = model
        _endpointDraft = State(initialValue: model.endpointInput)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(
                        "端末アドレス",
                        text: $endpointDraft,
                        prompt: Text("例：http://<ATOMのLAN内IP>")
                            .foregroundStyle(.secondary)
                    )
                    .font(.system(.body, design: .monospaced))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .submitLabel(.go)
                    .focused($endpointFocused)
                    .onChange(of: endpointDraft) {
                        model.clearEndpointValidationMessage()
                    }
                    .onSubmit { connect() }
                    .accessibilityHint(
                        model.endpointValidationMessage
                            ?? "自動検出できない場合だけLAN内の端末アドレスを入力してください"
                    )

                    if let message = model.endpointValidationMessage {
                        Label(message, systemImage: "exclamationmark.circle.fill")
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    Button("このアドレスに接続") {
                        connect()
                    }
                    .disabled(!model.canAttemptEndpointChange)
                } header: {
                    Text("接続先")
                } footer: {
                    Text("プライベートIPまたは.localホスト名を入力してください。")
                }
            }
            .navigationTitle("手動で設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("キャンセル") { dismiss() }
                }
            }
        }
        .onAppear {
            model.clearEndpointValidationMessage()
        }
    }

    private func connect() {
        if model.saveEndpoint(endpointDraft) {
            endpointFocused = false
            dismiss()
        }
    }
}
