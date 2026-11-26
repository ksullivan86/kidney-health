// The web shell (design note 38, step 1): the web app packed inside this iPhone app, running with no server.
//
// This folder (WebShell/) knows nothing about kidneys or food. A second app built on this code (the owner's meal planner)
// copies the folder and changes only this file: the scheme, the store's identifier and the safety copy's file name. The web
// app itself takes its names from app/brand.py and js/engine/brand.js.
import Foundation
import WebKit

enum WebShellConfig {
    /// The app's own URL scheme for its packed web files (never a scheme another app or the web uses).
    static let scheme = "kidneyhealth-app"
    /// The host of the web app's origin, kidneyhealth-app://app. Data the page keeps belongs to this origin, so it never changes.
    static let host = "app"
    /// The folder of packed web files in the app bundle, written by `scripts/build_preview.py --device ios/WebApp`.
    static let folder = "WebApp"
    /// The page the app opens.
    static let startPath = "/index.html"
    /// The folder of help pages packed with the web app (`--handbook`), shown in a sheet of their own (HelpPages.swift), or nil.
    static let helpFolder: String? = "learn"
    /// A fixed identifier, so the app gets the same web data store back after every restart (iOS 17). Never change it: a new one
    /// starts with no data.
    static let storeID = UUID(uuidString: "9C1E4B7A-3D52-4F6B-8A10-5E2C7D9B4F61")!
    /// The safety copy in the app's Documents folder, which the Files app shows under On My iPhone.
    static let safetyCopyName = "Kidney Health safety copy.json"

    /// The app's handler for the page's "bridge" messages (its food services), or nil for an app without one.
    static func bridge() -> WKScriptMessageHandlerWithReply? { FoodBridgeHandler() }

    /// The page has loaded / gone: the app's own code that talks to the page hears it here.
    @MainActor static func pageLoaded(_ view: WKWebView) {
        PageBridge.shared.pageLoaded(view)
        QuickActions.shared.run() // a Home Screen shortcut that opened the app
        LocalReminders.shared.run() // a reminder that was tapped
        Task { await SyncModel.shared.syncToPhone() } // Apple Health readings that came in while the app was closed
    }

    @MainActor static func pageGone() { PageBridge.shared.pageGone() }

    static func url(_ path: String) -> URL {
        URL(string: "\(scheme)://\(host)\(path)")!
    }
}
