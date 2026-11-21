// Serves the app's own packed web files to a WKWebView under one fixed origin, kidneyhealth-app://local/ (design note 38 §5.1).
// Step 0 of note 38 uses it for the storage test page only. Nothing here reaches the network: the handler answers from the app
// bundle, and only for the file names listed below.
import Foundation
import WebKit

enum LocalFiles {
    static let scheme = "kidneyhealth-app"
    static let host = "local"

    /// The page's rules: scripts and styles from this origin only, no inline script, and no network at all.
    static let contentSecurityPolicy = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        + "connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

    /// The only files the handler serves: path → (resource name, extension, MIME type).
    static let allowed: [String: (name: String, ext: String, mime: String)] = [
        "/storage-check.html": ("storage-check", "html", "text/html; charset=utf-8"),
        "/storage-check.js": ("storage-check", "js", "text/javascript; charset=utf-8"),
        "/storage-check.css": ("storage-check", "css", "text/css; charset=utf-8"),
    ]

    static func url(_ path: String) -> URL {
        URL(string: "\(scheme)://\(host)\(path)")!
    }

    /// The file for a request, or nil for anything else: another host, another scheme, a query, or a path not in the list.
    static func resource(for url: URL) -> (name: String, ext: String, mime: String)? {
        guard url.scheme == scheme, url.host == host, url.query == nil, url.fragment == nil else { return nil }
        return allowed[url.path]
    }
}

final class LocalSchemeHandler: NSObject, WKURLSchemeHandler {
    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url,
              let file = LocalFiles.resource(for: url),
              let fileURL = Bundle.main.url(forResource: file.name, withExtension: file.ext)
                  ?? Bundle.main.url(forResource: file.name, withExtension: file.ext, subdirectory: "StorageCheck"),
              let data = try? Data(contentsOf: fileURL) else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let headers = ["Content-Type": file.mime, "Content-Length": String(data.count),
                       "Content-Security-Policy": LocalFiles.contentSecurityPolicy, "Cache-Control": "no-store"]
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}
}
