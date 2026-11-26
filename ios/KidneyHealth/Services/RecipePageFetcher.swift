// A recipe page read on this iPhone, with no server or while the paired one cannot be reached (owner, 2026-11-26; design note 30
// §3; ARCHITECTURE.md "Device mode"). The page asks with the bridge kind `fetchRecipePage` and the link the person typed; the app
// fetches that page and answers its text. The page reads the recipe from it with the twin of the server's parser
// (js/engine/recipe_import.js); nothing on the page runs and it is never shown.
//
// The server's rules (app/recipe_import/fetch.py, app/egress.py), kept here with KidneyHealthCore/RecipePage.swift:
// * only the link typed: https, ports 443 or 80, plain ASCII, no user name; a redirect is followed by hand, at most 3, and each new
//   link is checked again the same way;
// * the host is looked up first and every address it has must be a public one (no home, local, link-local or cloud-internal
//   address); after the request, the address the connection used is checked again (a second look-up cannot slip one in);
// * at most 2 MiB of page and 15 seconds in all; HTML only; 20 pages an hour, as the server allows one person;
// * no cookies, no cache, a plain User-Agent; the request carries nothing about the person. The page is not kept and nothing is
//   logged.
import Foundation
import KidneyHealthCore

@MainActor
final class RecipePageFetcher {
    static let shared = RecipePageFetcher()

    /// The server's own (app/brand.py USER_AGENT_RECIPES): plain, nothing about the person or the phone.
    nonisolated static let userAgent = "kidney-health (recipe import)"

    private var recent: [Date] = []

    /// { kind: "fetchRecipePage", url } → { ok: true, html } or { error: code }, with the server's codes (bad_link, blocked,
    /// unreachable, timeout, too_large, not_html, http_error, too_many_redirects) and rate_limited.
    func answer(_ request: [String: Any]) async -> [String: Any] {
        guard let url = request["url"] as? String, let link = RecipePage.checkLink(url) else { return ["error": "bad_link"] }
        let now = Date()
        recent = recent.filter { now.timeIntervalSince($0) < 3600 }
        guard recent.count < RecipePage.pagesPerHour else { return ["error": "rate_limited"] }
        recent.append(now)
        let outcome = await Self.withDeadline(RecipePage.deadline, onTimeout: Result<String, RecipePageError>.failure(RecipePageError("timeout"))) {
            await Self.fetch(url, first: link)
        }
        switch outcome {
        case .success(let html): return ["ok": true, "html": html]
        case .failure(let problem): return ["error": problem.code]
        }
    }

    // MARK: - Fetching

    private nonisolated static func fetch(_ start: String, first: RecipePage.Link) async -> Result<String, RecipePageError> {
        var current = start
        var link = first
        for _ in 0...RecipePage.maxRedirects {
            if Task.isCancelled { return .failure(RecipePageError("timeout")) }
            guard let url = URL(string: current), url.scheme?.lowercased() == "https", sameHost(url, link) else {
                return .failure(RecipePageError("bad_link"))
            }
            if let problem = await checkAddresses(link) { return .failure(problem) }
            let outcome = await RecipePageLoad().run(url)
            switch outcome {
            case .failure(let problem):
                return .failure(problem)
            case .success(.page(let data, let contentType)):
                return .success(decode(data, contentType: contentType))
            case .success(.redirect(let location)):
                guard let next = URL(string: location.trimmingCharacters(in: .whitespaces), relativeTo: url)?.absoluteString,
                      let nextLink = RecipePage.checkLink(next) else { return .failure(RecipePageError("bad_link")) }
                current = next
                link = nextLink
            }
        }
        return .failure(RecipePageError("too_many_redirects"))
    }

    /// The URL the request goes to names the host that was checked.
    private nonisolated static func sameHost(_ url: URL, _ link: RecipePage.Link) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        return host.trimmingCharacters(in: CharacterSet(charactersIn: "[]")) == link.host
    }

    /// Nil when every address of the host may be opened; else `blocked` (a private, local or reserved address) or `unreachable`
    /// (the name does not resolve: most often no connection).
    private nonisolated static func checkAddresses(_ link: RecipePage.Link) async -> RecipePageError? {
        let addresses: [[UInt8]]
        if let literal = link.address {
            addresses = [literal]
        } else {
            addresses = await withCheckedContinuation { (done: CheckedContinuation<[[UInt8]], Never>) in
                DispatchQueue.global(qos: .userInitiated).async { done.resume(returning: resolve(link.host, port: link.port)) }
            }
        }
        if addresses.isEmpty { return RecipePageError("unreachable") }
        return addresses.allSatisfy({ RecipePage.classify($0) == .global }) ? nil : RecipePageError("blocked")
    }

    /// Every address `host` resolves to (getaddrinfo), as 4 or 16 bytes.
    private nonisolated static func resolve(_ host: String, port: Int) -> [[UInt8]] {
        var hints = addrinfo()
        hints.ai_family = AF_UNSPEC
        hints.ai_socktype = SOCK_STREAM
        var list: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, String(port), &hints, &list) == 0, let first = list else { return [] }
        defer { freeaddrinfo(first) }
        var out: [[UInt8]] = []
        var node: UnsafeMutablePointer<addrinfo>? = first
        while let info = node {
            if let address = info.pointee.ai_addr {
                if info.pointee.ai_family == AF_INET {
                    address.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { sin in
                        var raw = sin.pointee.sin_addr
                        withUnsafeBytes(of: &raw) { out.append(Array($0)) }
                    }
                } else if info.pointee.ai_family == AF_INET6 {
                    address.withMemoryRebound(to: sockaddr_in6.self, capacity: 1) { sin6 in
                        var raw = sin6.pointee.sin6_addr
                        withUnsafeBytes(of: &raw) { out.append(Array($0)) }
                    }
                }
            }
            node = info.pointee.ai_next
        }
        return out
    }

    /// The page as text: the charset of the header or a <meta> (fetch._charset), else UTF-8; a byte that does not fit becomes U+FFFD.
    private nonisolated static func decode(_ data: Data, contentType: String?) -> String {
        for name in RecipePage.charsetNames(contentType: contentType, head: Array(data.prefix(4096))) {
            let cf = CFStringConvertIANACharSetNameToEncoding(name as CFString)
            guard cf != kCFStringEncodingInvalidId else { continue }
            let encoding = String.Encoding(rawValue: CFStringConvertEncodingToNSStringEncoding(cf))
            if encoding == .utf8 { break }
            if let text = String(data: data, encoding: encoding) { return text }
            break
        }
        return String(decoding: data, as: UTF8.self)
    }

    /// `work`, or `onTimeout` once `seconds` have passed (the work is then cancelled).
    private static func withDeadline<T>(_ seconds: TimeInterval, onTimeout: T, _ work: @escaping () async -> T) async -> T {
        let once = RecipePageOnce()
        return await withCheckedContinuation { (done: CheckedContinuation<T, Never>) in
            let task = Task.detached {
                let value = await work()
                if once.claim() { done.resume(returning: value) }
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + seconds) {
                if once.claim() {
                    task.cancel()
                    done.resume(returning: onTimeout)
                }
            }
        }
    }
}

/// Why a page was not read: one of the server's codes (app/recipe_import/fetch.py PageError).
struct RecipePageError: Error, Sendable {
    let code: String
    init(_ code: String) { self.code = code }
}

/// A flag that is claimed once, from any thread.
final class RecipePageOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var claimed = false

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if claimed { return false }
        claimed = true
        return true
    }
}

/// One request of one page: its own session with no cookies and no cache, no redirect followed, at most 2 MiB kept.
final class RecipePageLoad: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    enum Answer {
        case page(Data, String?)
        case redirect(String)
    }

    private let lock = NSLock()
    private var data = Data()
    private var answer: Result<Answer, RecipePageError>?
    private var contentType: String?
    private var wrongAddress = false
    private var done: CheckedContinuation<Result<Answer, RecipePageError>, Never>?

    func run(_ url: URL) async -> Result<Answer, RecipePageError> {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.httpCookieAcceptPolicy = .never
        configuration.urlCache = nil
        configuration.urlCredentialStorage = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.timeoutIntervalForRequest = RecipePage.deadline
        configuration.timeoutIntervalForResource = RecipePage.deadline
        configuration.httpAdditionalHeaders = ["User-Agent": RecipePageFetcher.userAgent,
                                               "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"]
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.httpShouldHandleCookies = false
        let task = session.dataTask(with: request)
        return await withTaskCancellationHandler {
            await withCheckedContinuation { (continuation: CheckedContinuation<Result<Answer, RecipePageError>, Never>) in
                lock.lock()
                done = continuation
                lock.unlock()
                task.resume()
            }
        } onCancel: {
            task.cancel()
        }
    }

    private func settle(_ value: Result<Answer, RecipePageError>) {
        lock.lock()
        if answer == nil { answer = value }
        lock.unlock()
    }

    // A redirect is never followed here: the 3xx comes back as the answer and its Location is checked as a new link.
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let http = response as? HTTPURLResponse else {
            settle(.failure(.init("unreachable")))
            return completionHandler(.cancel)
        }
        let status = http.statusCode
        if (300..<400).contains(status), let location = http.value(forHTTPHeaderField: "Location"), !location.isEmpty {
            settle(.success(.redirect(location)))
            return completionHandler(.cancel)
        }
        let type = http.value(forHTTPHeaderField: "Content-Type")
        if status != 200 {
            settle(.failure(.init("http_error")))
        } else if !RecipePage.isHTML(type) {
            settle(.failure(.init("not_html")))
        } else if http.expectedContentLength > RecipePage.maxPageBytes, http.value(forHTTPHeaderField: "Content-Encoding") == nil {
            settle(.failure(.init("too_large")))
        } else {
            lock.lock()
            contentType = type
            lock.unlock()
            return completionHandler(.allow)
        }
        completionHandler(.cancel)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive chunk: Data) {
        lock.lock()
        data.append(chunk)
        let tooLarge = data.count > RecipePage.maxPageBytes  // counted after decompression, as on the server
        lock.unlock()
        if tooLarge {
            settle(.failure(.init("too_large")))
            dataTask.cancel()
        }
    }

    // Apple reports the metrics just before the task completes: the address the connection really used must be a public one too.
    func urlSession(_ session: URLSession, task: URLSessionTask, didFinishCollecting metrics: URLSessionTaskMetrics) {
        let wrong = metrics.transactionMetrics.contains { m in
            guard !m.isProxyConnection, let remote = m.remoteAddress else { return false }
            guard let bytes = RecipePage.parseAddress(remote) else { return true }
            return RecipePage.classify(bytes) != .global
        }
        if wrong {
            lock.lock()
            wrongAddress = true
            lock.unlock()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock()
        var result: Result<Answer, RecipePageError>
        if wrongAddress {
            result = .failure(.init("blocked"))
        } else if let answer {
            result = answer
        } else if let error = error as? URLError {
            result = .failure(.init(error.code == .timedOut || error.code == .cancelled ? "timeout" : "unreachable"))
        } else if error != nil {
            result = .failure(.init("unreachable"))
        } else {
            result = .success(.page(data, contentType))
        }
        let continuation = done
        done = nil
        data = Data()
        lock.unlock()
        continuation?.resume(returning: result)
    }
}
