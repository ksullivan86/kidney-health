// Withings and Whoop from the iPhone app (owner, 2026-11-26: "Should Withings and Whoop be set up from the phone?" "yes").
// The pure parts, so they build and test on Linux: the companies' fixed addresses, the sign-in address, the way back, the token
// and data requests, and reading a token answer. The app (Services/Devices.swift) sends them; the page reads the data with the
// server's rules (js/engine/device_map.js). The rules are the server's (app/devices/withings.py, whoop.py).
//
// The way back: Withings accepts only an https callback address it can match (its FAQ: no localhost, no IP address; it says
// nothing of custom URL schemes), so both companies send the person back to a small static page on the handbook's site
// (handbook/oauth/), which only forwards `code`, `state` and `error` to this app's own scheme. It keeps and logs nothing, and the
// code is useless without the client secret, which never leaves this iPhone.
import Foundation

public enum DeviceCompany: String, CaseIterable, Sendable {
    case withings
    case whoop

    public var name: String { self == .withings ? "Withings" : "Whoop" }

    /// The only host the app talks to for this company (the sign-in page is opened in Apple's sign-in sheet, not fetched).
    public var apiHost: String { self == .withings ? "wbsapi.withings.net" : "api.prod.whoop.com" }
    public var authorizeURL: String {
        self == .withings ? "https://account.withings.com/oauth2_user/authorize2" : "https://api.prod.whoop.com/oauth/oauth2/auth"
    }
    public var tokenURL: URL {
        URL(string: self == .withings ? "https://wbsapi.withings.net/v2/oauth2" : "https://api.prod.whoop.com/oauth/oauth2/token")!
    }
    /// What is asked for: the server's scopes, never a profile, an email or body measurements.
    public var scope: String { self == .withings ? "user.metrics" : "offline read:cycles read:recovery read:sleep read:workout" }
    /// The scope without which there is nothing to fetch.
    public var requiredScope: String { self == .withings ? "user.metrics" : "read:cycles" }
}

public enum DeviceLinks {
    /// The handbook's relay page (handbook/oauth/index.html), the callback address registered in each developer portal.
    public static let relayURL = "https://ksullivan86.github.io/kidney-health/oauth/"
    /// The app's own scheme the relay page forwards to. Only Apple's sign-in sheet listens for it.
    public static let callbackScheme = "kidneyhealth-devices"
    /// Withings: the measures, their types and pages (withings.py).
    public static let withingsMeasureURL = URL(string: "https://wbsapi.withings.net/measure")!
    public static let withingsSignatureURL = URL(string: "https://wbsapi.withings.net/v2/signature")!
    public static let withingsTypes = "1,9,10,11"
    public static let withingsMaxPages = 50
    /// Whoop: the four v2 collections, 25 a page, at most 40 pages each (whoop.py).
    public static let whoopCollections = ["cycles": "/developer/v2/cycle", "recoveries": "/developer/v2/recovery",
                                          "sleeps": "/developer/v2/activity/sleep", "workouts": "/developer/v2/activity/workout"]
    public static let whoopRevokePath = "/developer/v2/user/access"
    public static let whoopPageSize = 25
    public static let whoopMaxPages = 40
    public static let maxTokenChars = 4096

    /// The paired server's own web app at Settings → Connected devices, ready to connect `company` (js/views/devices.js reads
    /// `#/devices/open/<provider>`). Nil when the address is not https.
    public static func serverPage(_ address: String, company: DeviceCompany) -> URL? {
        guard let app = Settings.appURL(address), var parts = URLComponents(url: app, resolvingAgainstBaseURL: false) else { return nil }
        parts.fragment = "/devices/open/\(company.rawValue)"
        return parts.url
    }

    /// The sign-in address at the company, with the relay page as the way back and a fresh `state`.
    public static func authorize(_ company: DeviceCompany, clientID: String, state: String) -> URL? {
        var parts = URLComponents(string: company.authorizeURL)
        parts?.queryItems = [URLQueryItem(name: "response_type", value: "code"), URLQueryItem(name: "client_id", value: clientID),
                             URLQueryItem(name: "scope", value: company.scope), URLQueryItem(name: "redirect_uri", value: relayURL),
                             URLQueryItem(name: "state", value: state)]
        return parts?.url
    }

    /// What came back through the relay page.
    public enum Back: Equatable, Sendable {
        case code(String)
        /// The person said no at the company, or closed the page.
        case cancelled
        /// Not the sign-in this app started (another state, or none).
        case wrongState
        case unreadable
    }

    /// Reads `kidneyhealth-devices://callback?code=…&state=…` (or `error=…`). The state must be the one this app made, compared
    /// in full; a code is used only then.
    public static func back(_ url: URL, expectedState: String) -> Back {
        guard url.scheme == callbackScheme, url.host == "callback",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems else { return .unreadable }
        func one(_ name: String) -> String? {
            let found = items.filter { $0.name == name }
            return found.count == 1 ? found[0].value : nil
        }
        guard let state = one("state"), !expectedState.isEmpty, constantTimeEqual(state, expectedState) else { return .wrongState }
        if let error = one("error"), !error.isEmpty { return .cancelled }
        guard let code = one("code"), (1...512).contains(code.count), code.allSatisfy({ $0.isASCII && !$0.isWhitespace }) else {
            return .cancelled
        }
        return .code(code)
    }

    static func constantTimeEqual(_ a: String, _ b: String) -> Bool {
        let x = Array(a.utf8), y = Array(b.utf8)
        guard x.count == y.count else { return false }
        var diff: UInt8 = 0
        for i in 0..<x.count { diff |= x[i] ^ y[i] }
        return diff == 0
    }

    /// A form body (`application/x-www-form-urlencoded`), with every value escaped.
    public static func form(_ fields: [(String, String)]) -> Data {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        let text = fields.map { key, value in
            "\(key.addingPercentEncoding(withAllowedCharacters: allowed) ?? "")=\(value.addingPercentEncoding(withAllowedCharacters: allowed) ?? "")"
        }.joined(separator: "&")
        return Data(text.utf8)
    }

    /// The token request for a code (as the server's `exchange`).
    public static func codeForm(_ company: DeviceCompany, clientID: String, secret: String, code: String) -> Data {
        var fields = [("grant_type", "authorization_code"), ("client_id", clientID), ("client_secret", secret), ("code", code),
                      ("redirect_uri", relayURL)]
        if company == .withings { fields.insert(("action", "requesttoken"), at: 0) }
        return form(fields)
    }

    /// The token request with the refresh token (as the server's `refresh`). Whoop ends the old refresh token at once.
    public static func refreshForm(_ company: DeviceCompany, clientID: String, secret: String, refresh: String) -> Data {
        var fields = [("grant_type", "refresh_token"), ("client_id", clientID), ("client_secret", secret), ("refresh_token", refresh)]
        if company == .withings { fields.insert(("action", "requesttoken"), at: 0) } else { fields.append(("scope", "offline")) }
        return form(fields)
    }

    /// One page of Withings measures changed since `since` (a Unix time).
    public static func withingsMeasureForm(since: Int, offset: Int?) -> Data {
        var fields = [("action", "getmeas"), ("meastypes", withingsTypes), ("category", "1"), ("lastupdate", String(since))]
        if let offset { fields.append(("offset", String(offset))) }
        return form(fields)
    }

    /// One page of a Whoop collection that started from `start` (ISO 8601, UTC).
    public static func whoopPage(_ path: String, start: String, nextToken: String?) -> URL? {
        var parts = URLComponents()
        parts.scheme = "https"
        parts.host = DeviceCompany.whoop.apiHost
        parts.path = path
        var query = [URLQueryItem(name: "limit", value: String(whoopPageSize)), URLQueryItem(name: "start", value: start)]
        if let nextToken { query.append(URLQueryItem(name: "nextToken", value: nextToken)) }
        parts.queryItems = query
        return parts.url
    }

    /// `since` as Whoop's `start`: `YYYY-MM-DDTHH:MM:SS.000000Z`.
    public static func isoUTC(_ since: Int) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss'.000000Z'"
        return formatter.string(from: Date(timeIntervalSince1970: TimeInterval(max(0, since))))
    }

    /// The tokens a company gave, kept in the Keychain (never in the page).
    public struct Tokens: Codable, Equatable, Sendable {
        public var access: String
        public var refresh: String
        public var expiresAt: Int
        public var account: String
        public var scopes: String

        public init(access: String, refresh: String, expiresAt: Int, account: String, scopes: String) {
            self.access = access; self.refresh = refresh; self.expiresAt = expiresAt; self.account = account; self.scopes = scopes
        }
    }

    /// Why a token answer was not taken: `auth` (a refresh refused: connect again), `rate_limited`, `scope`, `refused`.
    public enum TokenProblem: String, Error, Sendable {
        case auth, rateLimited = "rate_limited", scope, refused
    }

    /// Reads a token answer as the server's `_token_set` does. Withings answers HTTP 200 with `{status, body}`; Whoop the tokens
    /// themselves. `now` is a Unix time.
    public static func tokens(_ company: DeviceCompany, httpStatus: Int, body: Data, refreshing: Bool, now: Int) -> Result<Tokens, TokenProblem> {
        let doc = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any]
        var fields: [String: Any]
        switch company {
        case .withings:
            guard httpStatus == 200, let doc, let status = doc["status"] as? Int else {
                return .failure(httpStatus == 429 ? .rateLimited : refreshing && httpStatus == 401 ? .auth : .refused)
            }
            if status == 601 { return .failure(.rateLimited) }
            guard status == 0 else { return .failure(refreshing ? .auth : .refused) }
            fields = doc["body"] as? [String: Any] ?? [:]
        case .whoop:
            if httpStatus == 429 { return .failure(.rateLimited) }
            guard httpStatus == 200 else { return .failure(refreshing && [400, 401, 403].contains(httpStatus) ? .auth : .refused) }
            fields = doc ?? [:]
        }
        func token(_ key: String) -> String? {
            guard let value = fields[key] as? String, (1...maxTokenChars).contains(value.count),
                  value.unicodeScalars.allSatisfy({ $0.value >= 0x20 && $0.value != 0x7F }) else { return nil }
            return value
        }
        guard let access = token("access_token"), let refresh = token("refresh_token") else { return .failure(.refused) }
        var expires = fields["expires_in"] as? Int ?? 0
        if expires <= 0 { expires = company == .withings ? 10800 : 3600 }
        let scopes = ((fields["scope"] as? String) ?? "").replacingOccurrences(of: ",", with: " ")
            .split(separator: " ").joined(separator: " ")
        var account = ""
        if company == .withings {
            if let id = fields["userid"] as? Int { account = String(id) } else if let id = fields["userid"] as? String { account = id }
            guard !account.isEmpty else { return .failure(.refused) }
        }
        if !refreshing {
            let granted = scopes.split(separator: " ").map(String.init)
            if company == .withings ? !granted.contains(company.requiredScope) : (!granted.isEmpty && !granted.contains(company.requiredScope)) {
                return .failure(.scope)
            }
        }
        return .success(Tokens(access: access, refresh: refresh, expiresAt: now + min(expires, 86400 * 30), account: String(account.prefix(64)),
                               scopes: scopes))
    }

    /// A developer app's client ID or secret as pasted: one line of plain text, of a sensible length.
    public static func isPlausibleCredential(_ text: String) -> Bool {
        (8...256).contains(text.count) && text.allSatisfy { $0.isASCII && !$0.isWhitespace && !$0.isNewline }
    }

    /// The Withings request signature: HMAC-SHA256 (hex) of the values joined with commas, keyed with the client secret. The
    /// app computes the HMAC (CryptoKit); this is the text that is signed.
    public static func withingsSigned(_ values: [String]) -> String { values.joined(separator: ",") }
}
