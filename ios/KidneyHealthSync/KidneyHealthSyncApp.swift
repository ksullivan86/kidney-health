// Kidney Health Sync: sends new weights and blood pressure readings from Apple Health to the person's own server
// (design note 15, option A). Every screen of the food log stays in the web app; this app only syncs.
import SwiftUI
import UIKit

@main
struct KidneyHealthSyncApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = SyncModel.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
    }
}

/// Health wakes the app in the background when a new sample is saved. The observer queries must be set up at every launch,
/// including a launch in the background, or the wake-up is lost.
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        Task { @MainActor in SyncModel.shared.startObserving() }
        return true
    }
}
