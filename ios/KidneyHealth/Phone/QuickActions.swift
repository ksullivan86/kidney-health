// Home Screen shortcuts (owner, 2026-11-21: make the most-used parts quicker). Touch and hold the app's icon: Scan a barcode,
// Add food, Quick add. Each one only opens that screen in the web app (KH.quickAction in js/main.js); nothing is saved without
// the person. A shortcut chosen while the app was closed waits until the page has started.
import UIKit
import WebKit

enum QuickAction: String, CaseIterable {
    case scan
    case add
    case quick

    var title: String {
        switch self {
        case .scan: "Scan a barcode"
        case .add: "Add food"
        case .quick: "Quick add"
        }
    }

    var symbol: String {
        switch self {
        case .scan: "barcode.viewfinder"
        case .add: "magnifyingglass"
        case .quick: "square.and.pencil"
        }
    }

    static let typePrefix = "io.github.ksullivan86.kidneyhealth."

    init?(_ item: UIApplicationShortcutItem) {
        guard item.type.hasPrefix(Self.typePrefix) else { return nil }
        self.init(rawValue: String(item.type.dropFirst(Self.typePrefix.count)))
    }

    var item: UIApplicationShortcutItem {
        UIApplicationShortcutItem(type: Self.typePrefix + rawValue, localizedTitle: title, localizedSubtitle: nil,
                                  icon: UIApplicationShortcutIcon(systemImageName: symbol))
    }
}

/// Holds the shortcut until the page can take it.
@MainActor
final class QuickActions {
    static let shared = QuickActions()
    private var pending: QuickAction?

    /// The shortcuts on the Home Screen icon. Set at every launch, so they appear after the app has been opened once.
    static func install() {
        UIApplication.shared.shortcutItems = QuickAction.allCases.map(\.item)
    }

    func handle(_ action: QuickAction) {
        pending = action
        run()
    }

    /// Called when the page has loaded, and when a shortcut arrives.
    func run() {
        guard let action = pending, PageBridge.shared.ready, let view = PageBridge.shared.webView else { return }
        pending = nil
        Task {
            _ = try? await view.callAsyncJavaScript("return await window.KH.quickAction(name);", arguments: ["name": action.rawValue],
                                                    in: nil, contentWorld: .page)
        }
    }
}

/// The scene's delegate: a shortcut chosen while the app runs, or the one that opened it.
@MainActor
final class SceneDelegate: NSObject, UIWindowSceneDelegate {
    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        if let item = connectionOptions.shortcutItem, let action = QuickAction(item) {
            QuickActions.shared.handle(action)
        }
    }

    func windowScene(_ windowScene: UIWindowScene, performActionFor shortcutItem: UIApplicationShortcutItem,
                     completionHandler: @escaping (Bool) -> Void) {
        guard let action = QuickAction(shortcutItem) else { completionHandler(false); return }
        QuickActions.shared.handle(action)
        completionHandler(true)
    }
}
