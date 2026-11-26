// The web app in a web view (design note 38 §5.1 and §5.2). Product-neutral: see WebShellConfig.
//
// * The page loads only the packed files (WebAppSchemeHandler); every other navigation is cancelled, except an https link the
//   person taps, which opens in Safari.
// * Its data is kept in a web data store with a fixed identifier, so the same store comes back after every restart.
// * After each save the page sends the export; it is written to the Documents folder as the safety copy (the Files app shows it).
// * A file the page downloads (Export) is offered with the share sheet, so the person chooses where it goes.
// * A link to the packed help pages (the handbook) opens them in a sheet of their own (HelpPages.swift).
// * "Phone settings" in the page asks the app to show its own settings (Apple Health and the server).
import SwiftUI
import UIKit
import WebKit

struct WebAppView: UIViewRepresentable {
    let openPhoneSettings: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(openPhoneSettings: openPhoneSettings) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = WKWebsiteDataStore(forIdentifier: WebShellConfig.storeID)
        configuration.setURLSchemeHandler(WebAppSchemeHandler(), forURLScheme: WebShellConfig.scheme)
        configuration.userContentController.add(context.coordinator, name: "safetyCopy")
        configuration.userContentController.add(context.coordinator, name: "phone")
        if let bridge = context.coordinator.bridge { // the app's own services for the page (WebShellConfig.bridge)
            configuration.userContentController.addScriptMessageHandler(bridge, contentWorld: .page, name: "bridge")
        }
        configuration.allowsInlineMediaPlayback = true // the barcode scanner's camera preview
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = false
        view.isOpaque = false
        view.backgroundColor = .systemBackground
        view.load(URLRequest(url: WebShellConfig.url(WebShellConfig.startPath)))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: "safetyCopy")
        view.configuration.userContentController.removeScriptMessageHandler(forName: "phone")
        view.configuration.userContentController.removeScriptMessageHandler(forName: "bridge", contentWorld: .page)
        Task { @MainActor in WebShellConfig.pageGone() }
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate, WKDownloadDelegate {
        let openPhoneSettings: () -> Void
        let bridge: WKScriptMessageHandlerWithReply? = WebShellConfig.bridge()
        private var downloads: [ObjectIdentifier: URL] = [:]

        init(openPhoneSettings: @escaping () -> Void) { self.openPhoneSettings = openPhoneSettings }

        // MARK: messages from the page

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            // Only the packed page may talk to the app.
            guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.protocol == WebShellConfig.scheme,
                  message.frameInfo.securityOrigin.host == WebShellConfig.host else { return }
            switch message.name {
            case "safetyCopy":
                if let text = message.body as? String { SafetyCopy.write(text) }
            case "phone":
                if (message.body as? String) == "settings" { openPhoneSettings() }
            default:
                break
            }
        }

        // MARK: navigation

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { decisionHandler(.cancel); return }
            if action.shouldPerformDownload { // a link with the download attribute: the page's Export
                decisionHandler(.download)
                return
            }
            if HelpPages.relativePath(for: url) != nil { // a help page: shown in its own sheet, so the app keeps its place
                if HelpPages.packed { HelpPages.present(url) }
                decisionHandler(.cancel)
                return
            }
            if WebAppFiles.relativePath(for: url) != nil || url.scheme == "about" {
                decisionHandler(.allow)
                return
            }
            if url.scheme == "https", action.navigationType == .linkActivated {
                UIApplication.shared.open(url) // the handbook and other pages open in Safari, never inside the app
            }
            decisionHandler(.cancel)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            Task { @MainActor in WebShellConfig.pageLoaded(webView) }
        }

        /// The page's process can be stopped by iOS while the app is in the background: load it again.
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            Task { @MainActor in WebShellConfig.pageGone() }
            webView.load(URLRequest(url: WebShellConfig.url(WebShellConfig.startPath)))
        }

        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
            download.delegate = self
        }

        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
            download.delegate = self
        }

        // MARK: downloads (Export): a temporary file, then the share sheet

        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                      completionHandler: @escaping @MainActor @Sendable (URL?) -> Void) {
            let name = (suggestedFilename as NSString).lastPathComponent
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent("exports", isDirectory: true)
            try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let target = folder.appendingPathComponent(name.isEmpty ? "export.json" : name)
            try? FileManager.default.removeItem(at: target)
            downloads[ObjectIdentifier(download)] = target
            completionHandler(target)
        }

        func downloadDidFinish(_ download: WKDownload) {
            guard let file = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
            Share.present([file])
        }

        func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
            downloads.removeValue(forKey: ObjectIdentifier(download))
        }
    }
}

/// The export the page sends after each save, kept in Documents so the person can find it in the Files app and import it again.
enum SafetyCopy {
    static var fileURL: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent(WebShellConfig.safetyCopyName)
    }

    /// Writes the copy in one step (a half-written file is never left), protected while the phone is locked.
    static func write(_ text: String) {
        guard let data = text.data(using: .utf8), !data.isEmpty, data.count < 64 * 1024 * 1024 else { return }
        try? data.write(to: fileURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
}

enum Share {
    @MainActor static func present(_ items: [Any]) {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first,
              var top = scene.keyWindow?.rootViewController else { return }
        while let next = top.presentedViewController { top = next }
        let sheet = UIActivityViewController(activityItems: items, applicationActivities: nil)
        sheet.popoverPresentationController?.sourceView = top.view
        top.present(sheet, animated: true)
    }
}
