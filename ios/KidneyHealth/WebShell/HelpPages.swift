// Help pages packed with the web app (owner, 2026-11-26), shown in a sheet of their own. Product-neutral: see WebShellConfig.
//
// `scripts/build_preview.py --device DIR --handbook SITE` packs a static site (the handbook) into WebShellConfig.helpFolder of the
// packed web files. A link to it in the app's page does not leave the page: WebAppView cancels it and shows this sheet, so the app
// keeps its place. The sheet has its own web view, its own scheme handler and a data store that is not kept:
// * it serves only files inside the help folder; a folder address ("eat/potassium/") is its index.html, and a query or fragment
//   only picks a place on the page;
// * a tapped https link opens in Safari, a tel: link in the Phone app; every other navigation is cancelled;
// * nothing here reaches the network, and the pages carry their own Content-Security-Policy.
import SwiftUI
import UIKit
import WebKit

enum HelpPages {
    /// The file a help address names, relative to the packed folder ("learn/eat/potassium/index.html"), or nil.
    static func relativePath(for url: URL) -> String? {
        guard let folder = WebShellConfig.helpFolder, url.scheme == WebShellConfig.scheme, url.host == WebShellConfig.host,
              var path = URLComponents(url: url, resolvingAgainstBaseURL: false)?.path else { return nil } // keeps a final "/"
        guard path.hasPrefix("/\(folder)/"), !path.contains("\\") else { return nil }
        if path.hasSuffix("/") { path += "index.html" }
        let parts = path.dropFirst().split(separator: "/", omittingEmptySubsequences: false)
        guard parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.hasPrefix(".") }) else { return nil }
        guard let last = parts.last, let dot = last.lastIndex(of: "."),
              WebAppFiles.mimeTypes[String(last[last.index(after: dot)...]).lowercased()] != nil else { return nil }
        return parts.joined(separator: "/")
    }

    /// The file on disk, checked to be inside the help folder after the path is resolved.
    static func fileURL(for url: URL) -> URL? {
        guard let folder = WebShellConfig.helpFolder, let root = WebAppFiles.bundleRoot, let relative = relativePath(for: url) else { return nil }
        let file = root.appendingPathComponent(relative).standardizedFileURL.resolvingSymlinksInPath()
        let base = root.appendingPathComponent(folder).standardizedFileURL.resolvingSymlinksInPath().path
        guard file.path.hasPrefix(base + "/") else { return nil }
        return file
    }

    /// Whether the app was packed with help pages.
    static var packed: Bool {
        guard let folder = WebShellConfig.helpFolder, let root = WebAppFiles.bundleRoot else { return false }
        return FileManager.default.fileExists(atPath: root.appendingPathComponent(folder).appendingPathComponent("index.html").path)
    }

    /// Shows the sheet at `url` (a help address checked by relativePath).
    @MainActor static func present(_ url: URL) {
        guard relativePath(for: url) != nil, packed, let top = topController() else { return }
        let pages = HelpPagesController(start: url)
        let wrapper = UINavigationController(rootViewController: pages)
        wrapper.modalPresentationStyle = .pageSheet
        top.present(wrapper, animated: true)
    }

    @MainActor private static func topController() -> UIViewController? {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first,
              var top = scene.keyWindow?.rootViewController else { return nil }
        while let next = top.presentedViewController { top = next }
        return top
    }
}

final class HelpPagesSchemeHandler: NSObject, WKURLSchemeHandler {
    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url, let file = HelpPages.fileURL(for: url), let data = try? Data(contentsOf: file) else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let mime = WebAppFiles.mimeTypes[file.pathExtension.lowercased()] ?? "application/octet-stream"
        let headers = ["Content-Type": mime, "Content-Length": String(data.count), "Cache-Control": "no-store",
                       "X-Content-Type-Options": "nosniff"]
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}
}

final class HelpPagesController: UIViewController, WKNavigationDelegate {
    private let start: URL
    private var webView: WKWebView?

    init(start: URL) {
        self.start = start
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { nil }

    override func loadView() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent() // nothing the pages keep outlives the sheet
        configuration.setURLSchemeHandler(HelpPagesSchemeHandler(), forURLScheme: WebShellConfig.scheme)
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self
        view.allowsBackForwardNavigationGestures = true
        view.backgroundColor = .systemBackground
        webView = view
        self.view = view
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        navigationItem.rightBarButtonItem = UIBarButtonItem(systemItem: .done, primaryAction: UIAction { [weak self] _ in
            self?.dismiss(animated: true)
        })
        navigationItem.leftBarButtonItem = UIBarButtonItem(image: UIImage(systemName: "chevron.backward"), primaryAction: UIAction { [weak self] _ in
            self?.webView?.goBack()
        })
        navigationItem.leftBarButtonItem?.accessibilityLabel = "Back"
        webView?.load(URLRequest(url: start))
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if HelpPages.relativePath(for: url) != nil || url.scheme == "about" {
            decisionHandler(.allow)
            return
        }
        if (url.scheme == "https" || url.scheme == "tel"), action.navigationType == .linkActivated {
            UIApplication.shared.open(url) // sources open in Safari; "call 911" in the Phone app
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        title = webView.title
        navigationItem.leftBarButtonItem?.isEnabled = webView.canGoBack
    }
}
