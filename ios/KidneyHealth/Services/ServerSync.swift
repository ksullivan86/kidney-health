// Sending what the person adds on the phone to their own server (design note 38 §5.5, step 4; docs/push.md "Sending from the
// iPhone app"). The page owns the queue and the rules (js/mock/server_sync.js): it works out which rows are new, builds the
// POST /push/v1/sync body and reads the answer. This file only carries the request:
//
// * { kind: "serverInfo" }                  → { ok, paired, server }: whether a server and a token are saved, and the server's host.
// * { kind: "serverSyncCheck" }             → GET /push/v1/sync (may this token send rows?)
// * { kind: "serverSync", body: "<json>" }  → POST /push/v1/sync with that body
//
// Both requests go only to the paired server's /push/v1/sync, over HTTPS (Settings.syncURL refuses anything else), with the token
// from the Keychain, through URLSessionTransport: no cookies, no cache, no redirects. They answer { ok, status, json, retryAfter? }
// or { error: "not_paired" | "offline" | "bad_request" }. The token never goes to the page, and nothing here is logged.
import Foundation
import KidneyHealthCore

@MainActor
enum ServerSync {
    /// The server's own limit (app/app_sync.py MAX_BODY_BYTES); a larger body is not sent.
    static let maxBody = 256 * 1024
    /// The longest answer handed to the page (the server answers counts, or a short refusal).
    static let maxAnswer = 64 * 1024
    static let transport: PushTransport = URLSessionTransport()

    static func answer(_ kind: String, _ request: [String: Any]) async -> [String: Any] {
        switch kind {
        case "serverInfo":
            guard let target = paired() else { return ["ok": true, "paired": false] }
            return ["ok": true, "paired": true, "server": target.url.host ?? ""]
        case "serverSyncCheck":
            guard let target = paired() else { return ["error": "not_paired"] }
            return await reply { try await transport.get(target.url, token: target.token) }
        case "serverSync":
            guard let text = request["body"] as? String else { return ["error": "bad_request"] }
            let body = Data(text.utf8)
            guard !body.isEmpty, body.count <= maxBody,
                  (try? JSONSerialization.jsonObject(with: body)) is [String: Any] else { return ["error": "bad_request"] }
            guard let target = paired() else { return ["error": "not_paired"] }
            return await reply { try await transport.post(body, to: target.url, token: target.token) }
        default:
            return ["error": "bad_request"]
        }
    }

    /// The paired server's https://…/push/v1/sync and the token in the Keychain, or nil when either is missing.
    private static func paired() -> (url: URL, token: String)? {
        guard let url = Settings.syncURL(SyncModel.shared.address), url.scheme == "https",
              let data = Keychain.read(.token), let token = String(data: data, encoding: .utf8), Settings.isDeviceToken(token) else { return nil }
        return (url, token)
    }

    private static func reply(_ send: () async throws -> HTTPReply) async -> [String: Any] {
        let answer: HTTPReply
        do {
            answer = try await send()
        } catch {
            return ["error": "offline"] // no answer came back: the page keeps its queue
        }
        var out: [String: Any] = ["ok": true, "status": answer.status,
                                  "json": answer.body.count <= maxAnswer ? String(decoding: answer.body, as: UTF8.self) : ""]
        if let wait = answer.header("Retry-After").flatMap({ Int($0.trimmingCharacters(in: .whitespaces)) }), wait > 0 {
            out["retryAfter"] = wait
        }
        return out
    }
}
