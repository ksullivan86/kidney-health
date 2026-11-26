// The page's requests to the person's own server through the token gateway (design note 39 §5.2 to §5.4, plan steps 3, 4, 6 and 7).
// The page builds each request and reads each answer; the app only carries it, and only when it is on this list. The list
// matches what note 39 lets the phone use so far: `GET /push/v1/about`, the server's food lookups (§7), its AI (§6.4), its
// recipe pages, Instacart and list app (§7, step 9), and sync both ways (§8): the change feed, the phone's edits and deletes,
// matching the phone's row IDs, the profile, targets, account settings and food preferences (step 8), and the Care team's notes
// and suggestions for the person.
// Never on it: anything that needs the password, keys and providers, tokens, sessions, admin routes, import and export, and setting
// up the list app (its address and key are typed in the server's web app).
import Foundation

public enum ServerAPI {
    /// One request the app may carry: the method, the exact path, the query names it may have, whether its body is a photo, and
    /// for a route that changes a setting the only keys its JSON body may hold.
    public struct Route: Equatable, Sendable {
        public let method: String
        public let path: String
        public let query: Set<String>
        public let photo: Bool
        public let bodyKeys: Set<String>?

        public init(_ method: String, _ path: String, query: Set<String> = [], photo: Bool = false, bodyKeys: Set<String>? = nil) {
            self.method = method; self.path = path; self.query = query; self.photo = photo; self.bodyKeys = bodyKeys
        }

        /// The path segments that stand for one row's id: 1 to 18 digits and nothing else.
        public static let idSegments: Set<Substring> = ["{food_id}", "{note_id}", "{suggestion_id}"]

        /// True when `plain` (a path with no query) is this route's path. A segment of `idSegments` (`{food_id}`, `{note_id}`,
        /// `{suggestion_id}`) stands for one row's id: 1 to 18 digits and nothing else.
        public func matches(_ plain: String) -> Bool {
            guard path.contains("{") else { return path == plain }
            let want = path.split(separator: "/", omittingEmptySubsequences: false)
            let got = plain.split(separator: "/", omittingEmptySubsequences: false)
            guard want.count == got.count else { return false }
            for (w, g) in zip(want, got) {
                if Route.idSegments.contains(w) {
                    guard (1...18).contains(g.count), g.allSatisfy({ ("0"..."9").contains($0) }) else { return false }
                } else if w != g {
                    return false
                }
            }
            return true
        }

        /// True when a JSON body may go with this route: an object, and only the keys a settings route allows.
        public func allows(_ body: [String: Any]) -> Bool {
            guard let bodyKeys else { return true }
            return !body.isEmpty && Set(body.keys).isSubset(of: bodyKeys)
        }
    }

    public static let about = Route("GET", "/push/v1/about")

    /// The allow-list. A request that is not exactly one of these is refused before anything is sent.
    public static let routes: [Route] = [
        about,
        // Food services (note 39 §7, step 3)
        Route("GET", "/push/v1/api/foods/usda/search", query: ["q"]),
        Route("POST", "/push/v1/api/foods/usda/import"),
        Route("POST", "/push/v1/api/foods/barcode"),
        // Connected devices on the server (owner, 2026-11-26): the person's status, Sync now and Disconnect for each company by
        // name, and the Whoop days and the active-day setting. Connecting is done on the server's own page, in a browser sheet the
        // app opens (Phone/DeviceLinks.swift): never through here.
        Route("GET", "/push/v1/api/devices"),
        Route("POST", "/push/v1/api/devices/withings/sync"),
        Route("POST", "/push/v1/api/devices/whoop/sync"),
        Route("DELETE", "/push/v1/api/devices/withings", query: ["delete_readings"]),
        Route("DELETE", "/push/v1/api/devices/whoop", query: ["delete_readings"]),
        Route("GET", "/push/v1/api/activity", query: ["start", "end"]),
        Route("PUT", "/push/v1/api/activity/extra"),
        // The person's answer to the server's Open Food Facts question (the consent its barcode lookups ask for), and the account
        // settings the server owns (step 8). Never this iPhone's own: its theme, its camera, the AI's trust.
        Route("PATCH", "/push/v1/api/me/settings",
              bodyKeys: ["food.off_consent", "user.units.labs", "user.units.weight", "user.units.height", "body.weight_alarm", "body.bp_goal", "guidance"]),
        // The server's AI (note 39 §6.4, step 4): status, the person's AI switch, consent, and the features
        Route("GET", "/push/v1/api/ai/status"),
        Route("PATCH", "/push/v1/api/me/ai", bodyKeys: ["opt_in"]),
        Route("POST", "/push/v1/api/ai/consent"),
        Route("POST", "/push/v1/api/ai/next-meal", query: ["dry_run"]),
        Route("POST", "/push/v1/api/ai/parse-meal", query: ["dry_run"]),
        Route("POST", "/push/v1/api/ai/recipes", query: ["dry_run"]),
        Route("POST", "/push/v1/api/ai/chat", query: ["dry_run"]),
        // Lab report text and photos: only the server's lab routes, which run on its local AI only (note 39 §6.2)
        Route("POST", "/push/v1/api/ai/read-lab-report-text", query: ["dry_run"]),
        Route("POST", "/push/v1/api/ai/read-lab-report", query: ["dry_run"], photo: true),
        Route("POST", "/push/v1/api/vision/label", query: ["dry_run"], photo: true),
        Route("POST", "/push/v1/api/vision/plate", query: ["dry_run"], photo: true),
        // The server's other services (note 39 §7, step 9): a recipe page it reads, the shopping list at Instacart or in the
        // person's own list app, with the server's keys
        Route("GET", "/push/v1/api/recipe-import"),
        Route("POST", "/push/v1/api/recipe-import/page"),
        Route("GET", "/push/v1/api/instacart"),
        Route("POST", "/push/v1/api/instacart/preview"),
        Route("POST", "/push/v1/api/instacart/send"),
        Route("GET", "/push/v1/api/list-sync"),
        Route("POST", "/push/v1/api/list-sync/preview"),
        Route("POST", "/push/v1/api/list-sync/send"),
        // Sync both ways (note 39 §8.4 to §8.7, steps 6 and 7): read the changes since a cursor, send edits and deletes with the
        // version they were made on (the server answers each one: done, conflict, gone or refused), and the server's ID for each
        // of the phone's rows at the first sync. The page owns every rule; the server checks each change as its own route does.
        Route("GET", "/push/v1/changes", query: ["after", "limit"]),
        Route("POST", "/push/v1/changes"),
        Route("POST", "/push/v1/match"),
        // What the server owns and the phone shows (note 39 §8.1, step 8): the profile and targets, the account settings and the food
        // preferences, read on each sync and changed only while connected. One food, and the food search, find a preference's food.
        Route("GET", "/push/v1/api/profile"),
        Route("PUT", "/push/v1/api/profile"),
        Route("GET", "/push/v1/api/me/settings"),
        Route("GET", "/push/v1/api/guidance/preferences"),
        Route("PUT", "/push/v1/api/guidance/preferences/{food_id}"),
        Route("DELETE", "/push/v1/api/guidance/preferences/{food_id}"),
        Route("GET", "/push/v1/api/foods", query: ["q", "source", "limit"]),
        Route("GET", "/push/v1/api/foods/{food_id}"),
        // The Care team's notes and suggestions for the person (notes 37 and 29; owner, 2026-11-26): read the notes, mark one read
        // with the version shown (If-Match), delete one; add a suggestion to the plan or say no thanks. Never sharing itself.
        Route("GET", "/push/v1/api/me/notes", query: ["before", "limit"]),
        Route("POST", "/push/v1/api/me/notes/{note_id}/read"),
        Route("DELETE", "/push/v1/api/me/notes/{note_id}"),
        Route("GET", "/push/v1/api/me/suggestions"),
        Route("POST", "/push/v1/api/me/suggestions/{suggestion_id}/accept"),
        Route("POST", "/push/v1/api/me/suggestions/{suggestion_id}/decline"),
    ]

    /// The longest path the page may send, query included.
    public static let maxPath = 1024

    /// The route for a method and a path as the page sends it (`/push/v1/api/foods/usda/search?q=rice`), with its query, or nil
    /// when it is not on the list. The path must be exactly a route's: no host, no fragment, no escapes; only the query may be
    /// percent-encoded, and only with the names the route takes.
    public static func route(method: String, path: String) -> (route: Route, query: [URLQueryItem])? {
        let plain = String(path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first ?? "")
        guard path.count <= maxPath, !plain.contains("%"), !path.contains("\\"), !path.contains("#"),
              let parts = URLComponents(string: path), parts.scheme == nil, parts.host == nil, parts.fragment == nil,
              parts.percentEncodedPath == plain,
              let found = routes.first(where: { $0.method == method && $0.matches(plain) }) else { return nil }
        let items = parts.queryItems ?? []
        guard Set(items.map(\.name)).count == items.count else { return nil } // one value per name
        for item in items {
            guard found.query.contains(item.name), let value = item.value, value.count <= 200 else { return nil }
        }
        // The query goes on as the page encoded it (a "+" stays "%2B"), so the server reads the words the person typed.
        return (found, parts.percentEncodedQueryItems ?? [])
    }

    /// The URL of a route on the paired server: the address's `https://host[:port][/prefix]`, then the route's path and query
    /// (`query` percent-encoded, as `route(method:path:)` answers it).
    public static func url(_ address: String, route: Route, query: [URLQueryItem] = []) -> URL? {
        guard let push = Settings.pushURL(address),
              var parts = URLComponents(url: push, resolvingAgainstBaseURL: false) else { return nil }
        parts.path = String(push.path.dropLast(Push.path.count)) + route.path
        parts.percentEncodedQueryItems = query.isEmpty ? nil : query
        return parts.url
    }

    /// What a token can do on its server, from the answer of `GET /push/v1/about` (note 39 §5.1 and §5.3).
    public enum TokenKind: String, Sendable {
        /// 200: a token "For the iPhone app, both ways": the server's AI and food services too.
        case bothWays
        /// 401 or 403: a token that only adds rows (or both ways is turned off on the server). Sending what is added still works.
        case addOnly
        /// 404 or 405: a server too old to answer `about`. Sending what is added still works.
        case oldServer
        /// No answer yet, or one that says nothing.
        case unknown
    }

    public static func tokenKind(_ reply: HTTPReply?) -> TokenKind {
        guard let reply else { return .unknown }
        switch reply.status {
        case 200:
            return (try? JSONSerialization.jsonObject(with: reply.body)) is [String: Any] ? .bothWays : .unknown
        case 401, 403:
            return .addOnly
        case 404, 405:
            return .oldServer
        default:
            return .unknown
        }
    }

    /// What the pairing screen says about the saved token, or nil when it is not known yet.
    public static func text(_ kind: TokenKind) -> String? {
        switch kind {
        case .bothWays:
            return "This token works both ways. What you add is sent to your server, and the app uses your server's AI and food services."
        case .addOnly:
            return "This token only adds. What you add is sent to your server. To use your server's AI and food services too, make a "
                + "token for the iPhone app, both ways, in Settings → Account → Your data → Phone shortcuts, and pair again. If there is "
                + "no such choice, ask whoever runs your server to turn it on."
        case .oldServer:
            return "Your server takes what you add, but it is too old to share its AI and food services. Ask whoever runs it to update it."
        case .unknown:
            return nil
        }
    }
}
