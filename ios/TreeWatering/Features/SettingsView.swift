import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: DashboardViewModel
    @Environment(\.dismiss) private var dismiss
    @FocusState private var endpointFocused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.1.50", text: $model.endpointInput)
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
                    .fontWeight(.bold)
                    .disabled(model.shouldShowStop)
                }
            }
        }
        .onAppear { endpointFocused = false }
        .presentationDetents([.medium, .large])
    }
}
