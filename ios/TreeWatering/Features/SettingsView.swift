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
                        Label("アカウント・認証なし", systemImage: "person.crop.circle.badge.xmark")
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
        .onAppear { endpointFocused = false }
        .presentationDetents([.medium, .large])
    }
}
