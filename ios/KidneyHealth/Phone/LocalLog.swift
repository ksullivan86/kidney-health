// Apple Health into the log on this phone (design note 38, step 3).
//
// The same sync that sends weights and readings to a server (KidneyHealthCore.Sync) sends them to the web app on this phone
// instead: LocalLogTransport takes each request the sync makes, plans its rows with the server's own rules (Push.plan, checked by
// the push vectors), and adds them through the page's batch routes, with the same source key the server and the Health export
// import use. A reading from a watch is counted and not stored, as the server does. The anchor moves on only after the page saved
// the rows, so nothing is lost when the app is not open: the next sync sends it.
import Foundation
import KidneyHealthCore
import WebKit

/// The page the app shows, when it is loaded and ready for rows. Set by WebAppView.
@MainActor
final class PageBridge {
    static let shared = PageBridge()
    weak var webView: WKWebView?
    private(set) var ready = false

    func pageLoaded(_ view: WKWebView) {
        webView = view
        ready = true
    }

    func pageGone() { ready = false }

    struct Unavailable: Error {}

    /// Adds planned rows through the page (`window.KHDevice.addBody`), which saves them before it answers.
    func addBody(_ rows: [String: Any]) async throws -> [String: Any] {
        guard ready, let webView else { throw Unavailable() }
        let data = try JSONSerialization.data(withJSONObject: rows)
        let json = String(decoding: data, as: UTF8.self)
        let answer = try await webView.callAsyncJavaScript("return await window.KHDevice.addBody(rows);", arguments: ["rows": json],
                                                           in: nil, contentWorld: .page)
        guard let text = answer as? String, let parsed = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else {
            throw Unavailable()
        }
        return parsed
    }
}

/// A PushTransport that delivers to the log on this phone. Its answers have the server's shape, so Sync works unchanged.
struct LocalLogTransport: PushTransport {
    /// The address Sync is given: never fetched, it only names where the rows go.
    static let url = URL(string: "kidneyhealth-app://app/health")!
    let today: String

    func post(_ body: Data, to url: URL, token: String) async throws -> HTTPReply {
        let request = try JSONDecoder().decode(Push.Request.self, from: body)
        let rows = Self.rows(request, today: today)
        let answer: [String: Any]
        do {
            answer = try await PageBridge.shared.addBody(rows.body)
        } catch {
            throw URLError(.cannotConnectToHost) // the page is not open: Sync reports "offline" and keeps the old anchor
        }
        if let problem = answer["error"] as? String {
            let detail = try JSONSerialization.data(withJSONObject: ["detail": problem])
            return HTTPReply(status: answer["status"] as? Int ?? 400, body: detail)
        }
        let added = answer["added"] as? [String: Int] ?? [:]
        let skipped = answer["skipped"] as? [String: Int] ?? [:]
        let result: [String: Any] = [
            "added": ["weights": added["weights"] ?? 0, "readings": added["readings"] ?? 0],
            "already_there": ["weights": skipped["weights"] ?? 0, "readings": skipped["readings"] ?? 0],
            "refused": ["watch": rows.watch],
        ]
        return HTTPReply(status: 200, body: try JSONSerialization.data(withJSONObject: result))
    }

    func get(_ url: URL, token: String) async throws -> HTTPReply {
        HTTPReply(status: 200, body: Data("{}".utf8))
    }

    /// The page's batch rows for one request, planned with the server's rules; watch readings are counted, not sent.
    static func rows(_ request: Push.Request, today: String) -> (body: [String: Any], watch: Int) {
        var weights: [[String: Any]] = []
        var readings: [[String: Any]] = []
        var watch = 0
        for row in request.weights {
            if case .success(let planned) = Push.plan(row, today: today) {
                weights.append(["date": planned.date, "time": planned.time, "kg": planned.kg, "context": planned.context,
                                "source": "apple_health", "source_key": planned.key])
            }
        }
        for row in request.readings {
            guard case .success(let planned) = Push.plan(row, today: today) else { continue }
            if planned.watch { watch += 1; continue }
            readings.append(["date": planned.date, "time": planned.time, "systolic": planned.systolic, "diastolic": planned.diastolic,
                             "context": planned.context, "source": "apple_health", "source_key": planned.key])
        }
        return (["weights": weights, "readings": readings], watch)
    }
}
