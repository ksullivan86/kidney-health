// Food services the person can turn on (design note 38, step 2, §5.3): USDA FoodData Central with their own key, and Open Food
// Facts. The page never reaches the network; it asks the app through the "bridge" message handler, and the app fetches from a fixed
// list of hosts and answers the service's raw JSON, which the page maps with the server's rules (js/engine/off.js, usda.js).
//
// Rules, as on the server: every service is off until the person turns it on; the USDA key is written once to the Keychain (this
// device only) and never shown again; requests send only the words typed or the barcode, never anything about the person; the
// services' own rate limits are kept here so a person is never blocked; no cookies, no cache, no redirects.
import Foundation
import WebKit

enum FoodService: String, CaseIterable {
    case usda
    case openFoodFacts

    var host: String {
        switch self {
        case .usda: "api.nal.usda.gov"
        case .openFoodFacts: "world.openfoodfacts.org"
        }
    }
}

@MainActor
final class FoodServices: ObservableObject {
    static let shared = FoodServices()

    /// The project's contact, not the person's (Open Food Facts asks apps for one in the User-Agent; CLAUDE.md: the person's email is
    /// never sent).
    static let userAgent = "KidneyHealth-iPhone/1.0 (https://github.com/ksullivan86/kidney-health)"
    /// Below USDA's 1,000 an hour per key and Open Food Facts' 15 product reads a minute (design note 38, F6 and F7).
    static let limits: [FoodService: (count: Int, seconds: TimeInterval)] = [.usda: (900, 3600), .openFoodFacts: (12, 60)]

    @Published private(set) var usdaOn: Bool
    @Published private(set) var offOn: Bool
    @Published private(set) var hasUsdaKey: Bool

    private let defaults: UserDefaults
    private var recent: [FoodService: [Date]] = [:]
    private let session: URLSession

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        usdaOn = defaults.bool(forKey: "service.usda")
        offOn = defaults.bool(forKey: "service.off")
        hasUsdaKey = Keychain.read(.usdaKey) != nil
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        configuration.httpAdditionalHeaders = ["User-Agent": Self.userAgent, "Accept": "application/json"]
        configuration.timeoutIntervalForRequest = 20
        // NoRedirects (URLSessionTransport.swift): a service that moves must not take the key or the request somewhere else.
        session = URLSession(configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
    }

    func setOn(_ service: FoodService, _ on: Bool) {
        defaults.set(on, forKey: service == .usda ? "service.usda" : "service.off")
        if service == .usda { usdaOn = on } else { offOn = on }
    }

    /// Saves a pasted key. Nil when saved, else the problem in plain words.
    func saveUsdaKey(_ text: String) -> String? {
        let key = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.isPlausibleKey(key) else { return "That does not look like a key from api.data.gov. Paste the whole key." }
        do { try Keychain.save(Data(key.utf8), as: .usdaKey) } catch { return "The key could not be saved on this phone." }
        hasUsdaKey = true
        return nil
    }

    func removeUsdaKey() {
        Keychain.delete(.usdaKey)
        hasUsdaKey = false
    }

    static func isPlausibleKey(_ key: String) -> Bool {
        (20...64).contains(key.count) && key.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber) }
    }

    /// One search for "apple", to check the saved key. Sends nothing else.
    func testUsda() async -> String {
        let answer = await fetch(.usda, path: "/fdc/v1/foods/search", query: [URLQueryItem(name: "query", value: "apple"),
                                                                            URLQueryItem(name: "pageSize", value: "1")])
        if answer["ok"] as? Bool == true { return "The key works." }
        return answer["message"] as? String ?? "The key could not be checked."
    }

    // MARK: - The page's requests

    /// Answers one request from the page: { kind: "usdaSearch", q } | { kind: "usdaFood", fdcId } | { kind: "offProduct", code } |
    /// { kind: "services" } | { kind: "enableOff" } | { kind: "fetchRecipePage", url }, and the server kinds of ServerSync.swift
    /// (serverApi: design note 39).
    func answer(_ body: Any) async -> [String: Any] {
        guard let request = body as? [String: Any], let kind = request["kind"] as? String else { return Self.problem("bad_request") }
        switch kind {
        case "services":
            // recipePage: this app reads a recipe page itself (RecipePageFetcher.swift); always on, like opening a link
            return ["ok": true, "usda": usdaOn && hasUsdaKey, "off": offOn, "scan": BarcodeScanner.available, "recipePage": true]
        case "scanBarcode": // the native scanner (Phone/BarcodeScanner.swift); the page looks the code up itself
            return await BarcodeScanner.shared.scan()
        case "speechStatus": // speaking a question for Ask (Phone/Dictation.swift): worked out on the phone only
            return Dictation.status()
        case "dictate":
            return await Dictation.shared.dictate()
        case "aiStatus": // the iPhone's own AI (design note 38, step 5): on the phone only
            return OnDeviceAI.status()
        case "ai":
            return await OnDeviceAI.answer(request)
        case "ownAIStatus": // the person's own AI key (OwnAI.swift): never the key itself
            return OwnAI.shared.status()
        case "ownAI":
            return await OwnAI.shared.answer(request)
        case "reminders": // the iPhone's own notifications (Phone/LocalReminders.swift, design note 35 §7)
            return await LocalReminders.shared.answer(request)
        case "fetchRecipePage": // a recipe page the person typed, read with no server (RecipePageFetcher.swift)
            return await RecipePageFetcher.shared.answer(request)
        case "enableOff":
            setOn(.openFoodFacts, true) // the page asked the person first, naming the host and what is sent (note 38, D5)
            return ["ok": true]
        case "serverInfo", "serverSyncCheck", "serverSync", "serverApi": // the person's own server (ServerSync.swift)
            return await ServerSync.answer(kind, request)
        case "deviceStatus", "deviceConnect", "deviceFetch", "deviceDisconnect", "serverPage": // Withings and Whoop (Devices.swift)
            return await Devices.shared.answer(kind, request)
        case "usdaSearch":
            guard let q = (request["q"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !q.isEmpty, q.count <= 200 else {
                return Self.problem("bad_request")
            }
            return await fetch(.usda, path: "/fdc/v1/foods/search", query: [URLQueryItem(name: "query", value: q),
                                                                           URLQueryItem(name: "pageSize", value: "25")])
        case "usdaFood":
            guard let id = request["fdcId"] as? Int, id > 0, id < 100_000_000 else { return Self.problem("bad_request") }
            return await fetch(.usda, path: "/fdc/v1/food/\(id)", query: [])
        case "offProduct":
            // The server's request (app/off.py product_url): API 3.4 and the page's list of fields, so the answer is what the
            // server's mapping expects.
            guard let code = request["code"] as? String, (8...14).contains(code.count), code.allSatisfy(\.isASCII),
                  code.allSatisfy(\.isNumber) else { return Self.problem("bad_request") }
            let fields = request["fields"] as? String ?? ""
            guard fields.count < 2000, fields.allSatisfy({ $0.isASCII && ($0.isLowercase || $0.isNumber || $0 == "_" || $0 == ",") }) else {
                return Self.problem("bad_request")
            }
            return await fetch(.openFoodFacts, path: "/api/v3.4/product/\(code)",
                               query: fields.isEmpty ? [] : [URLQueryItem(name: "fields", value: fields)])
        default:
            return Self.problem("bad_request")
        }
    }

    static func problem(_ code: String, _ message: String? = nil) -> [String: Any] {
        let text: [String: String] = [
            "bad_request": "The app could not read the request.",
            "off_off": "Open Food Facts lookups are off. Turn them on in Settings → This device → Apple Health and server → Keys and services.",
            "usda_off": "USDA lookups are off. Add your key in Settings → This device → Apple Health and server → Keys and services.",
            "rate_limited": "Too many lookups just now. Try again in a little while.",
            "offline": "The phone could not reach the service. Check the connection and try again.",
            "not_found": "The service does not know this food.",
            "refused": "The service refused the request.",
        ]
        return ["error": code, "message": message ?? text[code] ?? "The lookup did not work."]
    }

    private func fetch(_ service: FoodService, path: String, query: [URLQueryItem]) async -> [String: Any] {
        switch service {
        case .usda: guard usdaOn, hasUsdaKey else { return Self.problem("usda_off") }
        case .openFoodFacts: guard offOn else { return Self.problem("off_off") }
        }
        let now = Date()
        let limit = Self.limits[service]!
        let window = (recent[service] ?? []).filter { now.timeIntervalSince($0) < limit.seconds }
        guard window.count < limit.count else { return Self.problem("rate_limited") }
        recent[service] = window + [now]
        var parts = URLComponents()
        parts.scheme = "https"
        parts.host = service.host
        parts.path = path
        parts.queryItems = query.isEmpty ? nil : query
        guard let url = parts.url else { return Self.problem("bad_request") }
        var request = URLRequest(url: url)
        if service == .usda, let key = Keychain.read(.usdaKey).map({ String(decoding: $0, as: UTF8.self) }) {
            request.setValue(key, forHTTPHeaderField: "X-Api-Key") // a header, so the key is never in a URL or a log
        }
        do {
            let (data, response) = try await session.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard response.url?.host == service.host else { return Self.problem("refused") }
            switch status {
            case 200: break
            case 404: return Self.problem("not_found")
            case 429: return Self.problem("rate_limited")
            case 401, 403: return Self.problem("refused", service == .usda ? "USDA did not accept the key. Check it in Keys and services." : nil)
            default: return Self.problem("refused")
            }
            guard data.count < 5_000_000 else { return Self.problem("refused") }
            return ["ok": true, "json": String(decoding: data, as: UTF8.self)]
        } catch {
            return Self.problem("offline")
        }
    }
}

/// The page's "bridge" handler: answers with a reply, only to the app's own page.
final class FoodBridgeHandler: NSObject, WKScriptMessageHandlerWithReply {
    @MainActor
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) async -> (Any?, String?) {
        guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.protocol == WebShellConfig.scheme,
              message.frameInfo.securityOrigin.host == WebShellConfig.host else { return (nil, "refused") }
        return (await FoodServices.shared.answer(message.body), nil)
    }
}
