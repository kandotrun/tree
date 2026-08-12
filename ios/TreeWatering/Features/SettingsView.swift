import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: DashboardViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var endpointDraft: String
    @FocusState private var endpointFocused: Bool

    init(model: DashboardViewModel) {
        self.model = model
        _endpointDraft = State(initialValue: model.endpointInput)
    }

    private var endpointChanged: Bool {
        endpointDraft != model.endpointInput
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("接続") {
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
                    .focused($endpointFocused)
                    .onChange(of: endpointDraft) {
                        model.clearEndpointValidationMessage()
                    }

                    if let message = model.endpointValidationMessage {
                        Label(message, systemImage: "exclamationmark.circle.fill")
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    LabeledContent("接続方式", value: "ローカルネットワーク")
                }

                Section {
                    LabeledContent("ファームウェア", value: model.currentFirmwareVersion)

                    if model.firmwareUpdateSupported {
                        Label(
                            model.isFirmwarePaired ? "更新アクセス設定済み" : "更新アクセス未設定",
                            systemImage: model.isFirmwarePaired
                                ? "lock.shield.fill"
                                : "lock.open.fill"
                        )

                        Button(
                            model.isFirmwarePaired
                                ? "更新アクセスを再設定"
                                : "更新アクセスをペアリング"
                        ) {
                            model.pairFirmwareUpdates()
                        }
                        .disabled(
                            !model.canManageFirmware
                                || model.isFirmwarePairingInFlight
                                || model.isFirmwareUpdateInFlight
                        )

                        Button("更新を確認") {
                            model.checkForFirmwareUpdate()
                        }
                        .disabled(
                            !model.canManageFirmware
                                || model.isCheckingFirmwareUpdate
                                || model.isFirmwareUpdateInFlight
                        )

                        if let version = model.availableFirmwareVersion {
                            LabeledContent("利用可能", value: version)
                            Button("ファームウェア \(version) へ更新") {
                                model.requestFirmwareUpdateConfirmation()
                            }
                            .disabled(
                                !model.canManageFirmware
                                    || !model.isFirmwarePaired
                                    || model.isFirmwareUpdateInFlight
                            )
                        }

                        if model.isFirmwarePairingInFlight
                            || model.isCheckingFirmwareUpdate
                            || model.isFirmwareUpdateInFlight {
                            ProgressView(firmwareProgressLabel)
                                .accessibilityLabel(firmwareProgressLabel)
                        }

                        if let message = model.firmwareUpdateMessage {
                            Text(message)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        Label("最初の1回はUSB書き込みが必要です", systemImage: "cable.connector")
                            .foregroundStyle(.orange)
                    }
                } header: {
                    Text("ファームウェア")
                } footer: {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("ATOM本体のボタンを3秒間長押しし、60秒以内にペアリングしてください。")
                        Text("給水中は更新できません。更新中はUSB電源アダプタなど安定した電源に接続してください。")
                    }
                }
            }
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("キャンセル") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        if model.saveEndpoint(endpointDraft) {
                            dismiss()
                        }
                    }
                    .fontWeight(.semibold)
                    .disabled(!endpointChanged || !model.canAttemptEndpointChange)
                }
            }
        }
        .alert("接続先を強制変更しますか？", isPresented: $model.showForceEndpointConfirmation) {
            Button("キャンセル", role: .cancel) {
                model.cancelOfflineEndpointChange()
            }
            Button("停止を確認して変更", role: .destructive) {
                if model.confirmOfflineEndpointChange() {
                    dismiss()
                }
            }
        } message: {
            Text(
                "現在の端末へ停止確認できません。ポンプが停止していることを直接確認するか、電源を切ってから変更してください。"
            )
        }
        .alert("ファームウェアを更新しますか？", isPresented: $model.showFirmwareUpdateConfirmation) {
            Button("キャンセル", role: .cancel) {}
            Button("更新", role: .destructive) {
                model.installConfirmedFirmware()
            }
        } message: {
            Text(
                "現在 \(model.currentFirmwareVersion) から \(model.availableFirmwareVersion ?? "不明") へ更新します。ポンプが停止し、ATOMが安定した電源へ接続されていることを確認してください。"
            )
        }
        .onAppear {
            endpointFocused = false
            model.clearEndpointValidationMessage()
            model.refreshFirmwareCapability()
        }
    }

    private var firmwareProgressLabel: String {
        if model.isFirmwareUpdateInFlight {
            return "ファームウェアを送信しています"
        }
        if model.isCheckingFirmwareUpdate {
            return "更新を確認しています"
        }
        return "ペアリングしています"
    }
}
