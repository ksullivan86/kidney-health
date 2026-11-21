// Serves the packed web app from the app bundle to the web view (design note 38 §5.1). Product-neutral: see WebShellConfig.
// Nothing here reaches the network. A request is answered only when it names a file inside the packed folder.
import Foundation
import WebKit

enum WebAppFiles {
    static let mimeTypes: [String: String] = [
        "html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "mjs": "text/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8", "json": "application/json", "svg": "image/svg+xml", "png": "image/png",
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "ico": "image/x-icon", "woff2": "font/woff2",
        "wasm": "application/wasm", "txt": "text/plain; charset=utf-8", "webmanifest": "application/manifest+json",
    ]

    /// The relative path of the file a request names, or nil: another scheme or host, a query or fragment, no path, a path that
    /// steps out of the folder, or a type the app does not serve.
    static func relativePath(for url: URL) -> String? {
        guard url.scheme == WebShellConfig.scheme, url.host == WebShellConfig.host, url.query == nil, url.fragment == nil else {
            return nil
        }
        let path = url.path
        guard path.hasPrefix("/"), path.count > 1, !path.contains("\\") else { return nil }
        let parts = path.dropFirst().split(separator: "/", omittingEmptySubsequences: false)
        guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.hasPrefix(".") }) else { return nil }
        guard let ext = parts.last?.split(separator: ".").last.map(String.init), mimeTypes[ext.lowercased()] != nil else { return nil }
        return parts.joined(separator: "/")
    }

    /// The file on disk for a request, checked to be inside `root` after the path is resolved.
    static func fileURL(for url: URL, root: URL) -> URL? {
        guard let relative = relativePath(for: url) else { return nil }
        let file = root.appendingPathComponent(relative).standardizedFileURL.resolvingSymlinksInPath()
        let base = root.standardizedFileURL.resolvingSymlinksInPath().path
        guard file.path.hasPrefix(base + "/") else { return nil }
        return file
    }

    static var bundleRoot: URL? {
        Bundle.main.url(forResource: WebShellConfig.folder, withExtension: nil)
    }
}

final class WebAppSchemeHandler: NSObject, WKURLSchemeHandler {
    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url,
              let root = WebAppFiles.bundleRoot,
              let file = WebAppFiles.fileURL(for: url, root: root),
              let data = try? Data(contentsOf: file) else {
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
