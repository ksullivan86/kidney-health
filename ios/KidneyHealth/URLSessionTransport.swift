// Talks to the person's server: a request body, or the token check. No cookies, no cache, no redirects: a redirect could carry the token to another
// host, so it is answered as the redirect status and the sync stops.
import Foundation
import KidneyHealthCore

struct URLSessionTransport: PushTransport {
    let session: URLSession

    init(session: URLSession = URLSessionTransport.makeSession()) {
        self.session = session
    }

    /// `wait`: how long one answer may take. The server's AI can take minutes (design note 39, the serverApi bridge).
    static func makeSession(protocolClasses: [AnyClass]? = nil, wait: TimeInterval = 30) -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = wait
        configuration.timeoutIntervalForResource = max(60, wait * 2)
        if let protocolClasses { configuration.protocolClasses = protocolClasses }
        return URLSession(configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
    }

    func post(_ body: Data, to url: URL, token: String) async throws -> HTTPReply {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return try await send(request, token: token)
    }

    func get(_ url: URL, token: String) async throws -> HTTPReply {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        return try await send(request, token: token)
    }

    /// One request of the page to its server's gateway (design note 39 §5.4): any method the allow-list has, a JSON or JPEG body,
    /// and `If-Match` when the page sends one.
    func send(_ method: String, to url: URL, body: Data?, contentType: String?, ifMatch: String?, token: String) async throws -> HTTPReply {
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let body {
            request.httpBody = body
            request.setValue(contentType ?? "application/json", forHTTPHeaderField: "Content-Type")
        }
        if let ifMatch { request.setValue(ifMatch, forHTTPHeaderField: "If-Match") }
        return try await send(request, token: token)
    }

    private func send(_ request: URLRequest, token: String) async throws -> HTTPReply {
        var request = request
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        var headers: [String: String] = [:]
        for (name, value) in http.allHeaderFields {
            if let name = name as? String, let value = value as? String { headers[name] = value }
        }
        return HTTPReply(status: http.statusCode, headers: headers, body: data)
    }
}

/// Refuses every redirect, so the answer is the 3xx itself.
final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
