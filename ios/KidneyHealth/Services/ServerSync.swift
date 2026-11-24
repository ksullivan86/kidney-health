// Sending what the person adds on the phone to their own server (design note 38 §5.5, step 4; docs/push.md "Sending from the
// iPhone app"), and the server's food services and AI through its token gateway (design note 39 §5.4, steps 3 and 4). The page
// owns the queue and the rules (js/mock/server_sync.js, js/mock/server_api.js): it builds every request and reads every answer.
// This file only carries the request:
//
// * { kind: "serverInfo" }                  → { ok, paired, server }: whether a server and a token are saved, and the server's host.
// * { kind: "serverSyncCheck" }             → GET /push/v1/sync (may this token send rows?)
// * { kind: "serverSync", body: "<json>" }  → POST /push/v1/sync with that body
// * { kind: "serverApi", method, path, body?: "<json>", jpeg?: "<base64>", ifMatch? }
//                                           → that request on the paired server, only when ServerAPI.route allows the method and
//                                             path (KidneyHealthCore/ServerAPI.swift): GET /push/v1/about, the food lookups,
//                                             the AI routes, and sync both ways (GET and POST /push/v1/changes, POST
//                                             /push/v1/match). Anything else answers { error: "refused" } and nothing is sent.
//
// Every request goes only to the paired server, over HTTPS (Settings refuses anything else), with the token from the Keychain,
// through URLSessionTransport: no cookies, no cache, no redirects. They answer { ok, status, json, retryAfter? } or
// { error: "not_paired" | "offline" | "bad_request" | "refused" }. The token never goes to the page, no key of the phone's
// (Keys and services) is ever sent to the server, and nothing here is logged.
import Foundation
import KidneyHealthCore

@MainActor
enum ServerSync {
    /// The server's own limit (app/app_sync.py MAX_BODY_BYTES); a larger body is not sent.
    static let maxBody = 256 * 1024
    /// The longest answer handed to the page (the server answers counts, or a short refusal).
    static let maxAnswer = 64 * 1024
    /// A gateway request: the longest JSON body (a lab page's text, an Ask conversation), photo and answer (note 39 §5.4).
    static let maxApiBody = 512 * 1024
    static let maxPhoto = 6 * 1024 * 1024
    static let maxApiAnswer = 4 * 1024 * 1024
    static let transport: PushTransport = URLSessionTransport()
    /// The gateway's transport: the same rules, with time for the server's AI to answer.
    static let apiTransport = URLSessionTransport(session: URLSessionTransport.makeSession(wait: 180))

    static func answer(_ kind: String, _ request: [String: Any]) async -> [String: Any] {
        switch kind {
        case "serverInfo":
            guard let target = paired() else { return ["ok": true, "paired": false] }
            return ["ok": true, "paired": true, "server": target.url.host ?? ""]
        case "serverSyncCheck":
            guard let target = paired() else { return ["error": "not_paired"] }
            return await reply(maxAnswer) { try await transport.get(target.url, token: target.token) }
        case "serverSync":
            guard let text = request["body"] as? String else { return ["error": "bad_request"] }
            let body = Data(text.utf8)
            guard !body.isEmpty, body.count <= maxBody,
                  (try? JSONSerialization.jsonObject(with: body)) is [String: Any] else { return ["error": "bad_request"] }
            guard let target = paired() else { return ["error": "not_paired"] }
            return await reply(maxAnswer) { try await transport.post(body, to: target.url, token: target.token) }
        case "serverApi":
            return await gateway(request)
        default:
            return ["error": "bad_request"]
        }
    }

    /// One request of the page to the gateway, checked against the allow-list before anything else.
    private static func gateway(_ request: [String: Any]) async -> [String: Any] {
        guard let method = request["method"] as? String, let path = request["path"] as? String,
              let found = ServerAPI.route(method: method, path: path) else { return ["error": "refused"] }
        var body: Data?
        var type: String?
        if let text = request["body"] as? String {
            let data = Data(text.utf8)
            guard method != "GET", !found.route.photo, !data.isEmpty, data.count <= maxApiBody,
                  let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  found.route.allows(object) else { return ["error": "bad_request"] }
            body = data
            type = "application/json"
        } else if let text = request["jpeg"] as? String {
            guard found.route.photo, text.count <= maxPhoto * 4 / 3 + 4, let data = Data(base64Encoded: text),
                  data.count <= maxPhoto, data.starts(with: [0xFF, 0xD8]) else { return ["error": "bad_request"] }
            body = data
            type = "image/jpeg"
        } else if method != "GET" {
            return ["error": "bad_request"] // every route on the list that is not a GET takes a body
        }
        var ifMatch: String?
        if let tag = request["ifMatch"] as? String {
            guard !tag.isEmpty, tag.count <= 200, tag.allSatisfy({ $0.isASCII && !$0.isNewline }) else { return ["error": "bad_request"] }
            ifMatch = tag
        }
        guard let target = paired(), let url = ServerAPI.url(SyncModel.shared.address, route: found.route, query: found.query) else {
            return ["error": "not_paired"]
        }
        let (sendBody, sendType, tag, token) = (body, type, ifMatch, target.token)
        return await reply(maxApiAnswer) {
            try await apiTransport.send(method, to: url, body: sendBody, contentType: sendType, ifMatch: tag, token: token)
        }
    }

    /// The paired server's https://…/push/v1/sync and the token in the Keychain, or nil when either is missing.
    private static func paired() -> (url: URL, token: String)? {
        guard let url = Settings.syncURL(SyncModel.shared.address), url.scheme == "https",
              let data = Keychain.read(.token), let token = String(data: data, encoding: .utf8), Settings.isDeviceToken(token) else { return nil }
        return (url, token)
    }

    private static func reply(_ limit: Int, _ send: () async throws -> HTTPReply) async -> [String: Any] {
        let answer: HTTPReply
        do {
            answer = try await send()
        } catch {
            return ["error": "offline"] // no answer came back: the page keeps its queue, or uses the phone's own services
        }
        var out: [String: Any] = ["ok": true, "status": answer.status,
                                  "json": answer.body.count <= limit ? String(decoding: answer.body, as: UTF8.self) : ""]
        if let wait = answer.header("Retry-After").flatMap({ Int($0.trimmingCharacters(in: .whitespaces)) }), wait > 0 {
            out["retryAfter"] = wait
        }
        return out
    }
}
