import SwiftUI

struct RootView: View {
    @ObservedObject var model: DashboardViewModel

    var body: some View {
        Group {
            if model.hasEndpoint {
                DashboardView(model: model)
            } else {
                SetupView(model: model)
            }
        }
        .tint(Color.treeAccent)
        .sheet(isPresented: $model.showSettings) {
            SettingsView(model: model)
        }
    }
}
