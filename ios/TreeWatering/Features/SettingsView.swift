import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: DashboardViewModel
    @Environment(\.dismiss) private var dismiss
    @FocusState private var endpointFocused: Bool

    var body: some View {
        NavigationStack {
            ZStack {
                TreeGlassBackdrop()

                Form {
                    Section {
                        TextField(
                            "",
                            text: $model.endpointInput,
                            prompt: Text("例：http://<ATOMのLAN内IP>")
                                .foregroundStyle(Color.treeInk.opacity(0.55))
                        )
                            .font(.system(.body, design: .monospaced))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .focused($endpointFocused)

                        if let message = model.endpointValidationMessage {
                            Label(message, systemImage: "exclamationmark.circle.fill")
                                .font(.footnote)
                                .foregroundStyle(Color.treeWarning)
                        }
                    } header: {
                        Text("端末アドレス")
                    } footer: {
                        Text("private IPまたは.localホスト名のみ保存できます。認証情報やパスは入力しません。")
                    }

                    Section("接続方式") {
                        Label("LAN内で端末へ直接接続", systemImage: "wifi.router")
                        Label("クラウド通信なし", systemImage: "icloud.slash")
                        Label("給水操作はアカウント不要", systemImage: "person.crop.circle.badge.xmark")
                    }

                    Section {
                        LabeledContent("現在", value: model.currentFirmwareVersion)

                        if model.firmwareUpdateSupported {
                            Label(
                                model.isFirmwarePaired ? "更新アクセス設定済み" : "更新アクセス未設定",
                                systemImage: model.isFirmwarePaired
                                    ? "lock.shield.fill"
                                    : "lock.open.fill"
                            )

                            Text("ATOM本体のボタンを3秒間押し、60秒以内にペアリングします。")
                                .font(.footnote)
                                .foregroundStyle(.secondary)

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
                                ProgressView()
                            }

                            if let message = model.firmwareUpdateMessage {
                                Text(message)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                            }
                        } else {
                            Label("最初の1回はUSB書き込みが必要です", systemImage: "cable.connector")
                                .foregroundStyle(Color.treeWarning)
                        }
                    } header: {
                        Text("ファームウェア更新")
                    } footer: {
                        Text("給水中は更新できません。USBなど安定した電源で実行し、再起動後もポンプ停止を確認します。")
                    }
                }
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("接続設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("閉じる") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        if model.saveEndpoint() {
                            dismiss()
                        }
                    }
                    .tint(Color.treeForest)
                    .fontWeight(.bold)
                    .disabled(!model.canAttemptEndpointChange)
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
            model.refreshFirmwareCapability()
        }
        .presentationDetents([.medium, .large])
    }
}
