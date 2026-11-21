// Design note 38, step 0: a test on a real iPhone of where the app could keep a log with no server.
// Each time this screen opens, it adds the time in three places and shows how many times each one remembers:
//   1. a file in the app's own folder (the native control: it should always survive);
//   2. the web page's storage in WebKit's default store;
//   3. the web page's storage in a store of the app's own, with a fixed identifier.
// If 2 or 3 forget while 1 remembers, the web storage is not safe for a log. It stores dates only and sends nothing anywhere.
import SwiftUI
import UIKit
import WebKit

struct StorageCheckView: View {
    @State private var fileResult = ""
    @State private var defaultResult = "Waiting for the page…"
    @State private var ownResult = "Waiting for the page…"
    @State private var copied = false

    var body: some View {
        List {
            Section {
                Text("Open this screen now and then. Then close the app fully, open it and come back. Later, try Offload App in "
                     + "Settings → General → iPhone Storage, reinstall, and come back. Check again after more than a week without "
                     + "opening the app. Each time, tap Copy results and send them.")
            }
            Section("1. A file in the app's folder") {
                Text(fileResult)
            }
            Section("2. Web storage, default store") {
                Text(defaultResult)
                StorageCheckWebView(store: .default()) { defaultResult = $0 }
                    .frame(height: 110)
            }
            Section("3. Web storage, the app's own store") {
                Text(ownResult)
                StorageCheckWebView(store: WKWebsiteDataStore(forIdentifier: StorageCheck.ownStoreID)) { ownResult = $0 }
                    .frame(height: 110)
            }
            Section {
                Button(copied ? "Copied" : "Copy results") {
                    UIPasteboard.general.string = StorageCheck.summary(file: fileResult, defaultStore: defaultResult,
                                                                      ownStore: ownResult)
                    copied = true
                }
            } footer: {
                Text("This test keeps only the dates you opened this screen. It sends nothing anywhere.")
            }
        }
        .navigationTitle("Storage test")
        .onAppear { fileResult = StorageCheck.recordFileOpen() }
    }
}

enum StorageCheck {
    /// A fixed identifier, so the app gets the same store back after every restart (WKWebsiteDataStore(forIdentifier:), iOS 17).
    static let ownStoreID = UUID(uuidString: "6B3A2F0E-6C1D-4E8A-9B57-0D4C8E1A2F38")!

    static var fileURL: URL {
        let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return folder.appendingPathComponent("storage-check.json")
    }

    /// Adds now to the file and says how many opens it holds and the first.
    static func recordFileOpen(now: Date = Date()) -> String {
        let stamp = ISO8601DateFormatter().string(from: now)
        var opens = (try? JSONDecoder().decode([String].self, from: Data(contentsOf: fileURL))) ?? []
        opens.append(stamp)
        do {
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(opens).write(to: fileURL, options: .atomic)
        } catch {
            return "Could not be saved: \(error.localizedDescription)"
        }
        return "Opened \(opens.count) time\(opens.count == 1 ? "" : "s"), first \(opens[0])"
    }

    /// The page's report in plain words.
    static func describe(_ json: String) -> String {
        guard let data = json.data(using: .utf8),
              let report = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return "The page sent no report." }
        func line(_ name: String) -> String {
            guard let part = report[name] as? [String: Any] else { return "\(name): no answer" }
            if let error = part["error"] as? String { return "\(name): could not be used (\(error))" }
            let count = part["count"] as? Int ?? 0
            return "\(name): opened \(count) time\(count == 1 ? "" : "s"), first \(part["first"] as? String ?? "?")"
        }
        let storage = report["storage"] as? [String: Any] ?? [:]
        let persisted = (storage["persisted"] as? Bool).map { $0 ? "yes" : "no" } ?? "unknown"
        return [line("indexedDB"), line("localStorage"), "Kept for good: \(persisted)",
                "Origin: \(report["origin"] as? String ?? "?")"].joined(separator: "\n")
    }

    static func summary(file: String, defaultStore: String, ownStore: String) -> String {
        let version = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        return ["Kidney Health storage test, build \(version), \(ISO8601DateFormatter().string(from: Date()))",
                "1. File: \(file)", "2. Default store:\n\(defaultStore)", "3. Own store:\n\(ownStore)"].joined(separator: "\n")
    }
}

/// The test page in a web view with the given data store, served from the app (LocalFiles) and reporting back by message.
struct StorageCheckWebView: UIViewRepresentable {
    let store: WKWebsiteDataStore
    let onReport: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onReport: onReport) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = store
        configuration.setURLSchemeHandler(LocalSchemeHandler(), forURLScheme: LocalFiles.scheme)
        configuration.userContentController.add(context.coordinator, name: "storageCheck")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.load(URLRequest(url: LocalFiles.url("/storage-check.html")))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: "storageCheck")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        let onReport: (String) -> Void

        init(onReport: @escaping (String) -> Void) { self.onReport = onReport }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let json = message.body as? String else { return }
            onReport(StorageCheck.describe(json))
        }

        /// The page may load only the app's own files: any other navigation is cancelled.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            decisionHandler(action.request.url.flatMap(LocalFiles.resource(for:)) != nil ? .allow : .cancel)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            onReport("The page did not load: \(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            onReport("The page did not load: \(error.localizedDescription)")
        }
    }
}
