// One sync of the iOS app (design note 15 §4.2): new samples from Health, checked and sent to POST /push/v1/body in requests of at
// most 50 rows. HealthKit, the Keychain and the network are behind the protocols below, so the rules are tested on Linux.
import Foundation

/// A weight as Health holds it: when it was taken, in which time zone, the number in its unit, and the app or device it came from.
public struct WeightSample: Equatable, Sendable {
    public enum Unit: String, Sendable { case kg, lb }

    public let start: Date
    public let zone: TimeZone
    public let value: Double
    public let unit: Unit
    public let source: String

    public init(start: Date, zone: TimeZone, value: Double, unit: Unit, source: String) {
        self.start = start; self.zone = zone; self.value = value; self.unit = unit; self.source = source
    }

    /// The row the request sends. A value the server would not take as text becomes an empty text, which the check refuses.
    public var row: Push.Weight {
        Push.Weight(at: Push.at(start, in: zone), value: Push.valueText(value) ?? "", unit: unit.rawValue, source: source)
    }
}

/// A blood pressure reading as Health holds it: the two numbers of one correlation, in mmHg.
public struct ReadingSample: Equatable, Sendable {
    public let start: Date
    public let zone: TimeZone
    public let systolic: Double
    public let diastolic: Double
    public let source: String

    public init(start: Date, zone: TimeZone, systolic: Double, diastolic: Double, source: String) {
        self.start = start; self.zone = zone; self.systolic = systolic; self.diastolic = diastolic; self.source = source
    }

    /// The row the request sends, with the numbers rounded half up to whole numbers. A number that is not finite becomes -1,
    /// which the check refuses.
    public var row: Push.Reading {
        Push.Reading(at: Push.at(start, in: zone), systolic: Push.wholeMmHg(systolic) ?? -1, diastolic: Push.wholeMmHg(diastolic) ?? -1,
                     source: source)
    }
}

/// What Health has that is new since the last anchor, and the anchor to keep once all of it reached the server.
public struct SampleBatch: Sendable {
    public let weights: [WeightSample]
    public let readings: [ReadingSample]
    /// Opaque to the sync: the app's encoded HealthKit anchors.
    public let anchor: Data?

    public init(weights: [WeightSample], readings: [ReadingSample], anchor: Data?) {
        self.weights = weights; self.readings = readings; self.anchor = anchor
    }
}

/// The answer of one HTTP request.
public struct HTTPReply: Sendable {
    public let status: Int
    public let headers: [String: String]
    public let body: Data

    public init(status: Int, headers: [String: String] = [:], body: Data = Data()) {
        self.status = status; self.headers = headers; self.body = body
    }

    /// A header by name, in any letter case.
    public func header(_ name: String) -> String? {
        headers.first { $0.key.caseInsensitiveCompare(name) == .orderedSame }?.value
    }
}

/// Sends one request body. Implementations post JSON with `Authorization: Bearer <token>` and throw only when the server could not be
/// reached.
public protocol PushTransport: Sendable {
    func post(_ body: Data, to url: URL, token: String) async throws -> HTTPReply
}

/// The server's answer to an accepted request: counts only (app/push.py).
public struct PushResult: Codable, Equatable, Sendable {
    public struct Kinds: Codable, Equatable, Sendable {
        public let weights: Int
        public let readings: Int
    }

    public struct Refused: Codable, Equatable, Sendable {
        public let watch: Int
    }

    public let added: Kinds
    public let alreadyThere: Kinds
    public let refused: Refused

    enum CodingKeys: String, CodingKey {
        case added, refused
        case alreadyThere = "already_there"
    }
}

/// What one sync did, and whether the app may keep the new anchor.
public struct SyncOutcome: Equatable, Sendable {
    public enum State: Equatable, Sendable {
        /// Every request was accepted (or there was nothing to send).
        case done
        /// The server answered 401: the token was revoked, mistyped or the phone switch is off. Sync stops until a new token.
        case needsNewToken
        /// The server answered 429: try again after this many seconds.
        case wait(seconds: Int)
        /// The server answered 400 or 413 with this text. The app's check and the server disagree; the app needs an update.
        case refused(String)
        /// The server answered with another error status.
        case serverError(Int)
        /// The server could not be reached.
        case offline
    }

    public var state: State
    public var addedWeights = 0
    public var addedReadings = 0
    public var alreadyThere = 0
    /// Readings from a watch: left out by the app, or counted and not stored by the server.
    public var watchReadings = 0
    /// Rows the app left out because the server would refuse them.
    public var leftOut = 0
    /// The anchor to keep: set only when every request was accepted, so nothing new is ever skipped.
    public var anchorToKeep: Data?
}

public enum Sync {
    /// The seconds to wait after a 429 without a usable `Retry-After`.
    public static let defaultWait = 3600

    /// Checks the batch, sends it in requests of at most 50 rows, and stops at the first request the server does not accept.
    /// Rows already sent are safe to send again: the server counts them as already there.
    public static func run(_ batch: SampleBatch, to url: URL, token: String, today: String,
                           transport: PushTransport) async -> SyncOutcome {
        let plan = Push.plan(weights: batch.weights.map(\.row), readings: batch.readings.map(\.row), today: today)
        var outcome = SyncOutcome(state: .done)
        outcome.leftOut = plan.refused.values.reduce(0, +)
        outcome.watchReadings = plan.watchReadings
        for request in plan.requests {
            let reply: HTTPReply
            do {
                reply = try await transport.post(try Push.encode(request), to: url, token: token)
            } catch {
                outcome.state = .offline
                return outcome
            }
            switch reply.status {
            case 200:
                guard let result = try? JSONDecoder().decode(PushResult.self, from: reply.body) else {
                    outcome.state = .serverError(200)
                    return outcome
                }
                outcome.addedWeights += result.added.weights
                outcome.addedReadings += result.added.readings
                outcome.alreadyThere += result.alreadyThere.weights + result.alreadyThere.readings
                outcome.watchReadings += result.refused.watch
            case 401:
                outcome.state = .needsNewToken
                return outcome
            case 429:
                let seconds = reply.header("Retry-After").flatMap { Int($0.trimmingCharacters(in: .whitespaces)) }
                outcome.state = .wait(seconds: seconds.map { max(1, min($0, 86_400)) } ?? defaultWait)
                return outcome
            case 400, 413:
                outcome.state = .refused(detail(reply.body))
                return outcome
            default:
                outcome.state = .serverError(reply.status)
                return outcome
            }
        }
        outcome.anchorToKeep = batch.anchor
        return outcome
    }

    /// The `detail` text of an error answer, or a plain fallback.
    static func detail(_ body: Data) -> String {
        let object = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
        let text = (object?["detail"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return text.isEmpty ? "The server did not accept the request." : String(text.prefix(300))
    }

    /// The status line shown after a sync, in plain words.
    public static func describe(_ outcome: SyncOutcome) -> String {
        var lines: [String] = []
        switch outcome.state {
        case .done:
            if outcome.addedWeights + outcome.addedReadings == 0 {
                lines.append("Nothing new to send.")
            } else {
                let kinds = [(outcome.addedWeights, "weight"), (outcome.addedReadings, "reading")].filter { $0.0 > 0 }
                lines.append("Sent " + kinds.map { count($0.0, $0.1) }.joined(separator: " and ") + ".")
            }
            if outcome.alreadyThere > 0 {
                lines.append("\(outcome.alreadyThere) \(outcome.alreadyThere == 1 ? "was" : "were") already on the server.")
            }
        case .needsNewToken:
            lines.append("The server did not accept the token. Make a new one in Settings → Phone shortcuts and paste it here.")
        case .wait:
            lines.append("The server asked the app to wait. It will try again later.")
        case .refused(let detail):
            lines.append("The server refused a reading: \(detail) Nothing from that request was saved. Check for an update to the app.")
        case .serverError(let status):
            lines.append("The server had a problem (error \(status)). The app will try again later.")
        case .offline:
            lines.append("The server could not be reached. The app will try again later.")
        }
        if outcome.watchReadings > 0 {
            lines.append("\(count(outcome.watchReadings, "blood pressure reading")) from a watch left out. A cuff is needed for these.")
        }
        if outcome.leftOut > 0 {
            lines.append("\(count(outcome.leftOut, "reading")) left out because the server would not accept them.")
        }
        return lines.joined(separator: " ")
    }

    private static func count(_ n: Int, _ word: String) -> String { "\(n) \(word)\(n == 1 ? "" : "s")" }
}

/// The server address a person types, and the device token they paste.
public enum Settings {
    /// The URL of `POST /push/v1/body` for an address such as `https://kidney.example.org`, or nil. HTTPS only, no user name or
    /// password in it, no query or fragment. A path is kept, for a server behind a path prefix.
    public static func pushURL(_ address: String) -> URL? {
        let text = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parts = URLComponents(string: text), parts.scheme?.lowercased() == "https",
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil else { return nil }
        var path = parts.path
        while path.hasSuffix("/") { path.removeLast() }
        var url = URLComponents()
        url.scheme = "https"
        url.host = host
        url.port = parts.port
        url.path = path + Push.path
        return url.url
    }

    /// The address to open the web app, from the same text.
    public static func appURL(_ address: String) -> URL? {
        guard let push = pushURL(address) else { return nil }
        var parts = URLComponents(url: push, resolvingAgainstBaseURL: false)
        parts?.path = String(push.path.dropLast(Push.path.count)) + "/"
        return parts?.url
    }

    /// True for a device token as Settings → Phone shortcuts makes it: `khd_` and 43 base64url characters.
    public static func isDeviceToken(_ token: String) -> Bool {
        let text = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.hasPrefix("khd_") else { return false }
        let rest = text.dropFirst(4).utf8
        return rest.count == 43 && rest.allSatisfy { byte in
            (byte >= 0x41 && byte <= 0x5a) || (byte >= 0x61 && byte <= 0x7a) || (byte >= 0x30 && byte <= 0x39) || byte == 0x2d || byte == 0x5f
        }
    }
}
