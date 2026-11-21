// Kidney Health for iPhone. The whole app runs inside it with no server (design note 38): the packed web app in a web view
// (WebShell/). Its own settings, Apple Health and the person's server, open from the web app's Settings (design note 15).
import SwiftUI
import UIKit

@main
struct KidneyHealthApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = SyncModel.shared

    var body: some Scene {
        WindowGroup {
            RootView()
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

/// The web app, full screen. Its Settings → This device → "Apple Health and server" opens the app's own settings as a sheet;
/// so does a pairing link from the Camera, which the sheet then asks about.
struct RootView: View {
    @EnvironmentObject private var model: SyncModel
    @ObservedObject private var lock = AppLock.shared
    @Environment(\.scenePhase) private var scenePhase
    @State private var showSettings = false
    @State private var openedURL: URL?

    var body: some View {
        WebAppView(openPhoneSettings: { showSettings = true })
            .ignoresSafeArea()
            .overlay { if lock.locked { LockScreen(lock: lock) } } // covers the app, the app switcher's picture included
            .task { if lock.locked { await lock.unlock() } }
            .onChange(of: scenePhase) { _, phase in
                switch phase {
                case .background: lock.lockIfEnabled()
                case .active:
                    Task {
                        if lock.locked { await lock.unlock() }
                        await model.syncToPhone()
                    }
                default: break
                }
            }
            .onOpenURL { url in
                openedURL = url
                showSettings = true
            }
            .sheet(isPresented: $showSettings, onDismiss: { openedURL = nil }) {
                ContentView(openedURL: openedURL)
                    .environmentObject(model)
            }
    }
}
