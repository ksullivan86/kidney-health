// Withings and Whoop from the iPhone app (owner, 2026-11-26: "Should Withings and Whoop be set up from the phone?" "yes").
//
// Two ways, the server's first (the page decides, js/mock/devices.js):
// * Paired with a server that has the company set up: { kind: "serverPage", page: "devices", provider } opens the server's own web
//   app at Settings → Connected devices in Safari's sheet (SFSafariViewController), where the person signs in to their server and
//   connects. The answer comes when they press Done. No token of the app's goes to that page.
// * On this iPhone, with the person's own developer app (its client ID and secret typed in Keys and services, kept in the
//   Keychain on this device only, never shown again and never sent to the page):
//   { kind: "deviceStatus" }                    → { ok, relay, providers: { withings: { app, connected }, whoop: … } }
//   { kind: "deviceConnect", provider }         → Apple's sign-in sheet (ASWebAuthenticationSession, nothing kept between
//                                                  sign-ins) at the company; back through the relay page with the state checked;
//                                                  the code is exchanged here and the tokens kept in the Keychain. { ok } or
//                                                  { error: no_app | busy | cancelled | state | scope | refused | offline }.
//   { kind: "deviceFetch", provider, since }    → the company's raw answers since a Unix time: { ok, now, json } (Withings
//                                                  `{pages: [body]}`, Whoop `{cycles, recoveries, sleeps, workouts}`), or
//                                                  { error: not_connected | auth | rate_limited | scope | offline | provider_error }.
//   { kind: "deviceDisconnect", provider }      → the tokens are deleted here, then the company is asked to end the access.
//
// The rules are the server's (app/devices/withings.py, whoop.py): fixed hosts over HTTPS, no cookies, no cache, no redirects,
// 15 seconds a request, at most 2 MiB an answer; a refresh is kept at once (Whoop ends the old refresh token at once); a refused
// refresh means connect again. Nothing is logged, and nothing about the person is sent to the company.
import AuthenticationServices
import CryptoKit
import Foundation
import KidneyHealthCore
import SafariServices
import Security
import UIKit

@MainActor
final class Devices: NSObject, ObservableObject {
    static let shared = Devices()

    /// The companies whose developer app (client ID and secret) is saved on this iPhone.
    @Published private(set) var apps: Set<DeviceCompany> = []
    @Published private(set) var connected: Set<DeviceCompany> = []

    static let maxAnswer = 2 * 1024 * 1024
    static let maxAll = 8 * 1024 * 1024
    private let session: URLSession
    private var signIn: ASWebAuthenticationSession?
    private var pageClosed: CheckedContinuation<Void, Never>?

    private struct App: Codable {
        let id: String
        let secret: String
    }

    override init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.httpAdditionalHeaders = ["User-Agent": FoodServices.userAgent, "Accept": "application/json"]
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 60
        // NoRedirects (URLSessionTransport.swift): a company that moves must not take a token or a secret somewhere else.
        session = URLSession(configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
        super.init()
        for company in DeviceCompany.allCases {
            if Keychain.read(Self.appItem(company)) != nil { apps.insert(company) }
            if Keychain.read(Self.tokenItem(company)) != nil { connected.insert(company) }
        }
    }

    static func appItem(_ company: DeviceCompany) -> Keychain.Item { company == .withings ? .withingsApp : .whoopApp }
    static func tokenItem(_ company: DeviceCompany) -> Keychain.Item { company == .withings ? .withingsTokens : .whoopTokens }

    // MARK: - Keys and services

    /// Saves a developer app. Nil when saved, else the problem in plain words.
    func saveApp(_ company: DeviceCompany, clientID: String, secret: String) -> String? {
        let id = clientID.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = secret.trimmingCharacters(in: .whitespacesAndNewlines)
        guard DeviceLinks.isPlausibleCredential(id), DeviceLinks.isPlausibleCredential(key) else {
            return "That does not look like a client ID and secret from \(company.name). Paste each one whole."
        }
        guard let data = try? JSONEncoder().encode(App(id: id, secret: key)) else { return "The app could not be saved on this phone." }
        do { try Keychain.save(data, as: Self.appItem(company)) } catch { return "The app could not be saved on this phone." }
        apps.insert(company)
        return nil
    }

    /// Removes the developer app and the sign-in made with it (the company is asked to end the access first).
    func removeApp(_ company: DeviceCompany) async {
        _ = await disconnect(company)
        Keychain.delete(Self.appItem(company))
        apps.remove(company)
    }

    private func developerApp(_ company: DeviceCompany) -> App? {
        Keychain.read(Self.appItem(company)).flatMap { try? JSONDecoder().decode(App.self, from: $0) }
    }

    private func savedTokens(_ company: DeviceCompany) -> DeviceLinks.Tokens? {
        Keychain.read(Self.tokenItem(company)).flatMap { try? JSONDecoder().decode(DeviceLinks.Tokens.self, from: $0) }
    }

    private func keep(_ tokens: DeviceLinks.Tokens, _ company: DeviceCompany) -> Bool {
        guard let data = try? JSONEncoder().encode(tokens), (try? Keychain.save(data, as: Self.tokenItem(company))) != nil else { return false }
        connected.insert(company)
        return true
    }

    private func forget(_ company: DeviceCompany) {
        Keychain.delete(Self.tokenItem(company))
        connected.remove(company)
    }

    // MARK: - The page's requests

    func answer(_ kind: String, _ request: [String: Any]) async -> [String: Any] {
        if kind == "deviceStatus" {
            var providers: [String: Any] = [:]
            for company in DeviceCompany.allCases {
                providers[company.rawValue] = ["app": apps.contains(company), "connected": connected.contains(company)]
            }
            return ["ok": true, "relay": DeviceLinks.relayURL, "providers": providers]
        }
        guard let name = request["provider"] as? String, let company = DeviceCompany(rawValue: name) else { return ["error": "bad_request"] }
        switch kind {
        case "serverPage":
            guard request["page"] as? String == "devices" else { return ["error": "bad_request"] }
            return await openServerPage(company)
        case "deviceConnect":
            return await connect(company)
        case "deviceFetch":
            guard let since = request["since"] as? Int, since >= 0, since < 10_000_000_000 else { return ["error": "bad_request"] }
            return await fetch(company, since: since)
        case "deviceDisconnect":
            return await disconnect(company)
        default:
            return ["error": "bad_request"]
        }
    }

    // MARK: - The server's own page

    private func openServerPage(_ company: DeviceCompany) async -> [String: Any] {
        let address = SyncModel.shared.address
        guard Keychain.read(.token) != nil, let url = DeviceLinks.serverPage(address, company: company), url.scheme == "https" else {
            return ["error": "not_paired"]
        }
        guard pageClosed == nil, let top = BarcodeScanner.topController() else { return ["error": "busy"] }
        let page = SFSafariViewController(url: url)
        page.dismissButtonStyle = .done
        page.delegate = self
        page.modalPresentationStyle = .pageSheet
        page.presentationController?.delegate = self // a swipe down closes it too, without safariViewControllerDidFinish
        await withCheckedContinuation { (next: CheckedContinuation<Void, Never>) in
            pageClosed = next
            top.present(page, animated: true)
        }
        return ["ok": true]
    }

    fileprivate func closed() {
        pageClosed?.resume()
        pageClosed = nil
    }

    // MARK: - Connecting on this iPhone

    private func connect(_ company: DeviceCompany) async -> [String: Any] {
        guard let app = developerApp(company) else { return ["error": "no_app"] }
        guard signIn == nil else { return ["error": "busy"] }
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { return ["error": "refused"] }
        let state = Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        guard let url = DeviceLinks.authorize(company, clientID: app.id, state: state) else { return ["error": "refused"] }
        let back: URL? = await withCheckedContinuation { (next: CheckedContinuation<URL?, Never>) in
            let sheet = ASWebAuthenticationSession(url: url, callbackURLScheme: DeviceLinks.callbackScheme) { url, _ in
                next.resume(returning: url) // closed or refused: no URL
            }
            sheet.prefersEphemeralWebBrowserSession = true // the company's sign-in is not kept in Safari
            sheet.presentationContextProvider = self
            signIn = sheet
            if !sheet.start() {
                signIn = nil
                next.resume(returning: nil)
            }
        }
        signIn = nil
        guard let back else { return ["error": "cancelled"] }
        let code: String
        switch DeviceLinks.back(back, expectedState: state) {
        case .code(let value): code = value
        case .cancelled: return ["error": "cancelled"]
        case .wrongState, .unreadable: return ["error": "state"]
        }
        var request = URLRequest(url: company.tokenURL)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = DeviceLinks.codeForm(company, clientID: app.id, secret: app.secret, code: code)
        guard let reply = await send(request, company) else { return ["error": "offline"] }
        let (status, data) = reply
        switch DeviceLinks.tokens(company, httpStatus: status, body: data, refreshing: false, now: Self.now()) {
        case .success(let tokens):
            return keep(tokens, company) ? ["ok": true] : ["error": "refused"]
        case .failure(let problem):
            return ["error": problem == .scope ? "scope" : problem == .rateLimited ? "offline" : "refused"]
        }
    }

    // MARK: - Fetching

    private static func now() -> Int { Int(Date().timeIntervalSince1970) }

    /// One request to the company's fixed host; nil when it could not be reached (or answered from elsewhere, or too much).
    private func send(_ request: URLRequest, _ company: DeviceCompany) async -> (Int, Data)? {
        guard let url = request.url, url.scheme == "https", url.host == company.apiHost else { return nil }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, http.url?.host == company.apiHost, data.count <= Self.maxAnswer else { return nil }
            return (http.statusCode, data)
        } catch {
            return nil
        }
    }

    private enum Failure: String, Error {
        case notConnected = "not_connected", auth, rateLimited = "rate_limited", scope, offline, providerError = "provider_error"
    }

    /// A working access token: refreshed first when under 5 minutes are left, or when `force`. The new pair is kept at once.
    /// One refresh per company at a time: a refresh token works once, so a second refresh started meanwhile (Sync now during
    /// a background sync) would be refused and the person signed out. A caller that finds one running waits for its token.
    private func access(_ company: DeviceCompany, force: Bool = false) async throws -> String {
        guard developerApp(company) != nil, let current = savedTokens(company) else { throw Failure.notConnected }
        if let pending = refreshing[company] { return try await pending.value }
        if !force && current.expiresAt - Self.now() > 300 { return current.access }
        let task = Task { try await self.refreshNow(company) }
        refreshing[company] = task
        defer { refreshing[company] = nil }
        return try await task.value
    }

    private var refreshing: [DeviceCompany: Task<String, Error>] = [:]

    private func refreshNow(_ company: DeviceCompany) async throws -> String {
        guard let app = developerApp(company), var current = savedTokens(company) else { throw Failure.notConnected }
        var request = URLRequest(url: company.tokenURL)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = DeviceLinks.refreshForm(company, clientID: app.id, secret: app.secret, refresh: current.refresh)
        guard let reply = await send(request, company) else { throw Failure.offline }
        let (status, data) = reply
        switch DeviceLinks.tokens(company, httpStatus: status, body: data, refreshing: true, now: Self.now()) {
        case .success(let fresh):
            current = DeviceLinks.Tokens(access: fresh.access, refresh: fresh.refresh, expiresAt: fresh.expiresAt,
                                         account: fresh.account.isEmpty ? current.account : fresh.account,
                                         scopes: fresh.scopes.isEmpty ? current.scopes : fresh.scopes)
            guard keep(current, company) else { throw Failure.providerError }
            return current.access
        case .failure(.auth):
            forget(company) // refused: the person connects again
            throw Failure.auth
        case .failure(.rateLimited):
            throw Failure.rateLimited
        case .failure:
            throw Failure.providerError
        }
    }

    private func fetch(_ company: DeviceCompany, since: Int) async -> [String: Any] {
        do {
            let doc: [String: Any]
            do {
                doc = try await fetchAll(company, token: try await access(company), since: since)
            } catch Failure.auth {
                doc = try await fetchAll(company, token: try await access(company, force: true), since: since) // one refresh, one retry
            }
            let json = try JSONSerialization.data(withJSONObject: doc)
            guard json.count <= Self.maxAll else { return ["error": "provider_error"] }
            return ["ok": true, "now": Self.now(), "json": String(decoding: json, as: UTF8.self)]
        } catch let failure as Failure {
            if failure == .auth { forget(company) }
            return ["error": failure.rawValue]
        } catch {
            return ["error": "provider_error"]
        }
    }

    private func fetchAll(_ company: DeviceCompany, token: String, since: Int) async throws -> [String: Any] {
        // An if, not a ternary: Swift refuses `try` and `await` to the right of an operator.
        if company == .withings { return try await withingsPages(token, since: since) }
        return try await whoopCollections(token, since: since)
    }

    private func withingsPages(_ token: String, since: Int) async throws -> [String: Any] {
        var pages: [Any] = []
        var offset: Int?
        for _ in 0..<DeviceLinks.withingsMaxPages {
            var request = URLRequest(url: DeviceLinks.withingsMeasureURL)
            request.httpMethod = "POST"
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            request.httpBody = DeviceLinks.withingsMeasureForm(since: since, offset: offset)
            guard let reply = await send(request, .withings) else { throw Failure.offline }
            let (http, data) = reply
            if http == 429 { throw Failure.rateLimited }
            if http == 401 { throw Failure.auth }
            guard http == 200, let doc = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  let status = doc["status"] as? Int else { throw Failure.providerError }
            if status == 601 { throw Failure.rateLimited }
            if [100, 101, 102, 401, 214, 277, 2553, 2554, 2555].contains(status) { throw Failure.auth }
            guard status == 0 else { throw Failure.providerError }
            let body = doc["body"] as? [String: Any] ?? [:]
            pages.append(body)
            guard body["more"] as? Bool == true || (body["more"] as? Int ?? 0) != 0, let next = body["offset"] as? Int, next != offset else { break }
            offset = next
        }
        return ["pages": pages]
    }

    private func whoopCollections(_ token: String, since: Int) async throws -> [String: Any] {
        var out: [String: Any] = [:]
        let start = DeviceLinks.isoUTC(since)
        for name in ["cycles", "recoveries", "sleeps", "workouts"] {
            let path = DeviceLinks.whoopCollections[name]!
            var records: [Any] = []
            var next: String?
            pages: for _ in 0..<DeviceLinks.whoopMaxPages {
                guard let url = DeviceLinks.whoopPage(path, start: start, nextToken: next) else { throw Failure.providerError }
                var request = URLRequest(url: url)
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                guard let reply = await send(request, .whoop) else { throw Failure.offline }
                let (http, data) = reply
                switch http {
                case 401: throw Failure.auth
                case 429: throw Failure.rateLimited
                case 403 where name != "cycles": break pages // the person did not allow this kind of data
                case 403: throw Failure.scope
                case 200: break
                default: throw Failure.providerError
                }
                guard let doc = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { throw Failure.providerError }
                records += doc["records"] as? [Any] ?? []
                guard let more = doc["next_token"] as? String, !more.isEmpty, more.count <= 1024, more != next else { break }
                next = more
            }
            out[name] = records
        }
        return out
    }

    // MARK: - Disconnecting

    /// The tokens are deleted here whatever the company answers; then it is asked to end the access (best effort).
    private func disconnect(_ company: DeviceCompany) async -> [String: Any] {
        guard savedTokens(company) != nil else { return ["ok": true, "revoked": false] }
        let token = try? await access(company)
        let current = savedTokens(company)
        forget(company)
        guard let app = developerApp(company), let current else { return ["ok": true, "revoked": false] }
        let revoked: Bool
        if company == .withings { revoked = await revokeWithings(app, account: current.account) } else { revoked = await revokeWhoop(token) }
        return ["ok": true, "revoked": revoked]
    }

    private func revokeWhoop(_ token: String?) async -> Bool {
        guard let token, var parts = URLComponents(string: "https://\(DeviceCompany.whoop.apiHost)") else { return false }
        parts.path = DeviceLinks.whoopRevokePath
        guard let url = parts.url else { return false }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        guard let reply = await send(request, .whoop) else { return false }
        let (status, _) = reply
        return status == 200 || status == 204
    }

    private func revokeWithings(_ app: App, account: String) async -> Bool {
        guard !account.isEmpty else { return false }
        let sign = { (values: [String]) -> String in
            let mac = HMAC<CryptoKit.SHA256>.authenticationCode(for: Data(DeviceLinks.withingsSigned(values).utf8), using: SymmetricKey(data: Data(app.secret.utf8)))
            return mac.map { String(format: "%02x", $0) }.joined()
        }
        let stamp = String(Self.now())
        var nonceRequest = URLRequest(url: DeviceLinks.withingsSignatureURL)
        nonceRequest.httpMethod = "POST"
        nonceRequest.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        nonceRequest.httpBody = DeviceLinks.form([("action", "getnonce"), ("client_id", app.id), ("timestamp", stamp),
                                                  ("signature", sign(["getnonce", app.id, stamp]))])
        guard let data = await send(nonceRequest, .withings)?.1,
              let doc = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], doc["status"] as? Int == 0,
              let nonce = (doc["body"] as? [String: Any])?["nonce"] as? String, !nonce.isEmpty else { return false }
        var request = URLRequest(url: DeviceCompany.withings.tokenURL)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = DeviceLinks.form([("action", "revoke"), ("client_id", app.id), ("nonce", nonce), ("userid", account),
                                             ("signature", sign(["revoke", app.id, nonce]))])
        guard let answer = await send(request, .withings)?.1,
              let done = (try? JSONSerialization.jsonObject(with: answer)) as? [String: Any] else { return false }
        return done["status"] as? Int == 0
    }
}

extension Devices: ASWebAuthenticationPresentationContextProviding {
    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first?.keyWindow ?? ASPresentationAnchor()
        }
    }
}

extension Devices: SFSafariViewControllerDelegate {
    /// Done in the server's page: the page reads the status again.
    nonisolated func safariViewControllerDidFinish(_ controller: SFSafariViewController) {
        Task { @MainActor in self.closed() }
    }
}

extension Devices: UIAdaptivePresentationControllerDelegate {
    /// The server's page swiped away. closed() answers once, whichever of the two comes first.
    nonisolated func presentationControllerDidDismiss(_ presentationController: UIPresentationController) {
        Task { @MainActor in self.closed() }
    }
}
