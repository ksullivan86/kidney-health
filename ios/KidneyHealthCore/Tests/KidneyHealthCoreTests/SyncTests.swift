// One sync against a fake server: what is sent, when the anchor may be kept, and the status line a person reads.
import Foundation
import XCTest
@testable import KidneyHealthCore

/// Answers each post with the next reply in its list and records what it was sent.
final class FakeTransport: PushTransport, @unchecked Sendable {
    private let lock = NSLock()
    private var replies: [Result<HTTPReply, Error>]
    private(set) var sent: [(body: Push.Request, url: URL, token: String)] = []

    init(_ replies: [Result<HTTPReply, Error>]) { self.replies = replies }

    func post(_ body: Data, to url: URL, token: String) async throws -> HTTPReply {
        let request = try JSONDecoder().decode(Push.Request.self, from: body)
        let next: Result<HTTPReply, Error> = lock.withLock {
            sent.append((request, url, token))
            return replies.isEmpty ? .success(ok()) : replies.removeFirst()
        }
        return try next.get()
    }
}

func ok(added: (Int, Int) = (0, 0), there: (Int, Int) = (0, 0), watch: Int = 0) -> HTTPReply {
    let json = #"{"added": {"weights": \#(added.0), "readings": \#(added.1)}, "already_there": {"weights": \#(there.0), "readings": \#(there.1)}, "refused": {"watch": \#(watch)}}"#
    return HTTPReply(status: 200, headers: ["Content-Type": "application/json"], body: Data(json.utf8))
}

struct Offline: Error {}

final class SyncTests: XCTestCase {
    let url = URL(string: "https://kidney.example.org/push/v1/body")!
    let token = "khd_" + String(repeating: "a", count: 43)
    let zone = TimeZone(identifier: "America/New_York")!
    let anchor = Data("anchor-2".utf8)

    private func weights(_ count: Int) -> [WeightSample] {
        (0..<count).map { i in
            WeightSample(start: Date(timeIntervalSince1970: 1_792_667_700 + Double(i) * 60), zone: zone, value: 70 + Double(i) / 10,
                         unit: .kg, source: "Withings")
        }
    }

    private func reading(_ systolic: Double = 122, source: String = "Omron") -> ReadingSample {
        ReadingSample(start: Date(timeIntervalSince1970: 1_792_668_000), zone: zone, systolic: systolic, diastolic: 78, source: source)
    }

    func testASampleBecomesTheRowTheServerTakes() {
        let w = WeightSample(start: Date(timeIntervalSince1970: 1_792_667_700), zone: zone, value: 154.29999999999998, unit: .lb, source: "Health")
        XCTAssertEqual(w.row, Push.Weight(at: "2026-10-22T07:15:00-04:00", value: "154.3", unit: "lb", source: "Health"))
        XCTAssertEqual(reading(119.5).row.systolic, 120)
        XCTAssertEqual(reading(.nan).row.systolic, -1)
    }

    func testEverythingAcceptedKeepsTheAnchorAndAddsUpTheCounts() async {
        let transport = FakeTransport([.success(ok(added: (50, 0))), .success(ok(added: (19, 1), there: (1, 0)))])
        let batch = SampleBatch(weights: weights(70), readings: [reading()], anchor: anchor)
        let outcome = await Sync.run(batch, to: url, token: token, today: "2026-10-28", transport: transport)
        XCTAssertEqual(outcome.state, .done)
        XCTAssertEqual(outcome.anchorToKeep, anchor)
        XCTAssertEqual(transport.sent.map { $0.body.weights.count + $0.body.readings.count }, [50, 21])
        XCTAssertEqual(transport.sent.map(\.token), [token, token])
        XCTAssertEqual(outcome.addedWeights, 69)
        XCTAssertEqual(outcome.addedReadings, 1)
        XCTAssertEqual(outcome.alreadyThere, 1)
        XCTAssertEqual(Sync.describe(outcome), "Sent 69 weights and 1 reading. 1 was already on the server.")
    }

    func testNothingNewSendsNothingAndKeepsTheAnchor() async {
        let transport = FakeTransport([])
        let outcome = await Sync.run(SampleBatch(weights: [], readings: [], anchor: anchor), to: url, token: token, today: "2026-10-28",
                                     transport: transport)
        XCTAssertEqual(outcome.state, .done)
        XCTAssertEqual(outcome.anchorToKeep, anchor)
        XCTAssertTrue(transport.sent.isEmpty)
        XCTAssertEqual(Sync.describe(outcome), "Nothing new to send.")
    }

    func testARevokedTokenStopsTheSyncAndTheAnchorIsNotKept() async {
        let transport = FakeTransport([.success(ok(added: (50, 0))), .success(HTTPReply(status: 401))])
        let outcome = await Sync.run(SampleBatch(weights: weights(120), readings: [], anchor: anchor), to: url, token: token,
                                     today: "2026-10-28", transport: transport)
        XCTAssertEqual(outcome.state, .needsNewToken)
        XCTAssertNil(outcome.anchorToKeep)
        XCTAssertEqual(transport.sent.count, 2)
        XCTAssertTrue(Sync.describe(outcome).contains("Settings → Phone shortcuts"))
    }

    func testTooManyRequestsWaitsForRetryAfter() async {
        for (header, seconds) in [("120", 120), (" 7 ", 7), ("0", 1), ("999999", 86_400), ("soon", Sync.defaultWait)] {
            let transport = FakeTransport([.success(HTTPReply(status: 429, headers: ["retry-after": header]))])
            let outcome = await Sync.run(SampleBatch(weights: weights(1), readings: [], anchor: anchor), to: url, token: token,
                                         today: "2026-10-28", transport: transport)
            XCTAssertEqual(outcome.state, .wait(seconds: seconds), header)
            XCTAssertNil(outcome.anchorToKeep)
        }
    }

    func testARefusalShowsTheServersTextAndOtherErrorsTryAgainLater() async {
        let refusal = HTTPReply(status: 400, body: Data(#"{"detail": "weights.0.value: must be 20 to 400 kg"}"#.utf8))
        var outcome = await Sync.run(SampleBatch(weights: weights(1), readings: [], anchor: anchor), to: url, token: token,
                                     today: "2026-10-28", transport: FakeTransport([.success(refusal)]))
        XCTAssertEqual(outcome.state, .refused("weights.0.value: must be 20 to 400 kg"))
        XCTAssertNil(outcome.anchorToKeep)

        outcome = await Sync.run(SampleBatch(weights: weights(1), readings: [], anchor: anchor), to: url, token: token,
                                 today: "2026-10-28", transport: FakeTransport([.success(HTTPReply(status: 503))]))
        XCTAssertEqual(outcome.state, .serverError(503))
        XCTAssertNil(outcome.anchorToKeep)

        outcome = await Sync.run(SampleBatch(weights: weights(1), readings: [], anchor: anchor), to: url, token: token,
                                 today: "2026-10-28", transport: FakeTransport([.success(HTTPReply(status: 200, body: Data("<html>".utf8)))]))
        XCTAssertEqual(outcome.state, .serverError(200))
        XCTAssertNil(outcome.anchorToKeep)

        outcome = await Sync.run(SampleBatch(weights: weights(1), readings: [], anchor: anchor), to: url, token: token,
                                 today: "2026-10-28", transport: FakeTransport([.failure(Offline())]))
        XCTAssertEqual(outcome.state, .offline)
        XCTAssertNil(outcome.anchorToKeep)
        XCTAssertEqual(Sync.describe(outcome), "The server could not be reached. The app will try again later.")
    }

    func testWatchReadingsAndRowsTheServerWouldRefuseAreLeftOutAndSaid() async {
        let transport = FakeTransport([.success(ok(added: (0, 1)))])
        let batch = SampleBatch(weights: [], readings: [reading(), reading(source: "Apple Watch"), reading(40)], anchor: anchor)
        let outcome = await Sync.run(batch, to: url, token: token, today: "2026-10-28", transport: transport)
        XCTAssertEqual(transport.sent.count, 1)
        XCTAssertEqual(transport.sent[0].body.readings.count, 1)
        XCTAssertEqual(outcome.anchorToKeep, anchor)
        XCTAssertEqual(Sync.describe(outcome),
                       "Sent 1 reading. 1 blood pressure reading from a watch left out. A cuff is needed for these. "
                       + "1 reading left out because the server would not accept them.")
    }

    func testOlderSamplesAreLeftOutOnTheFirstSync() async {
        let old = WeightSample(start: Date(timeIntervalSince1970: 1_700_000_000), zone: zone, value: 70, unit: .kg, source: "Health")
        let transport = FakeTransport([.success(ok(added: (1, 0)))])
        let batch = SampleBatch(weights: [old] + weights(1), readings: [], anchor: anchor)
        let outcome = await Sync.run(batch, to: url, token: token, today: "2026-10-28", since: Push.defaultSince("2026-10-28"),
                                     transport: transport)
        XCTAssertEqual(transport.sent.map(\.body.weights.count), [1])
        XCTAssertEqual(outcome.leftOut, 0)
        XCTAssertEqual(outcome.anchorToKeep, anchor)
    }

    func testTheServerAddressMustBeHTTPS() {
        XCTAssertEqual(Settings.pushURL("https://kidney.example.org")?.absoluteString, "https://kidney.example.org/push/v1/body")
        XCTAssertEqual(Settings.pushURL(" https://kidney.example.org/ ")?.absoluteString, "https://kidney.example.org/push/v1/body")
        XCTAssertEqual(Settings.pushURL("https://example.org:8443/kidney/")?.absoluteString, "https://example.org:8443/kidney/push/v1/body")
        XCTAssertEqual(Settings.appURL("https://example.org:8443/kidney")?.absoluteString, "https://example.org:8443/kidney/")
        XCTAssertEqual(Settings.appURL("https://kidney.example.org")?.absoluteString, "https://kidney.example.org/")
        for bad in ["http://kidney.example.org", "kidney.example.org", "https://", "https://me:pw@kidney.example.org",
                    "https://kidney.example.org/?a=1", "https://kidney.example.org/#x", "ftp://kidney.example.org", ""] {
            XCTAssertNil(Settings.pushURL(bad), bad)
        }
    }

    func testOnlyADeviceTokenIsTaken() {
        XCTAssertTrue(Settings.isDeviceToken(token))
        XCTAssertTrue(Settings.isDeviceToken(" khd_" + String(repeating: "A-_9", count: 10) + "abc\n"))
        for bad in ["kha_" + String(repeating: "a", count: 43), "khd_" + String(repeating: "a", count: 42),
                    "khd_" + String(repeating: "a", count: 44), "khd_" + String(repeating: "a", count: 42) + "=", ""] {
            XCTAssertFalse(Settings.isDeviceToken(bad), bad)
        }
    }
}
