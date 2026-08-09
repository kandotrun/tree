import SwiftUI

@main
struct TreeWateringApp: App {
    @StateObject private var model = DashboardViewModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .task { model.activate() }
                .onChange(of: scenePhase) { _, newPhase in
                    if newPhase == .active {
                        model.activate()
                    } else {
                        model.handleSceneInactive()
                    }
                }
        }
    }
}
