// What the settings screen accepts, and the words it answers with.
import KidneyHealthCore
import XCTest
@testable import KidneyHealthSync

@MainActor
final class SettingsScreenTests: XCTestCase {
    private func model(transport: PushTransport = URLSessionTransport(), health: HealthReading? = nil) -> SyncModel {
        let defaults = UserDefaults(suiteName: "SettingsScreenTests")!
        defaults.removePersistentDomain(forName: "SettingsScreenTests")
        return SyncModel(defaults: defaults, health: health, transport: transport)
    }

    override func tearDown() async throws {
        Keychain.delete(.token)
        Keychain.delete(.anchors)
    }

    func testAnAddressMustBeHTTPSAndATokenMustBeAPhoneToken() {
        let m = model()
        XCTAssertEqual(m.save(address: "http://kidney.example.org", token: ""),
                       "Type the address of your server. It starts with https://.")
        XCTAssertEqual(m.save(address: "https://kidney.example.org", token: "kha_" + String(repeating: "a", count: 43)),
                       "That is not a phone token. Make one in Settings → Phone shortcuts. It starts with khd_.")
        XCTAssertFalse(m.hasToken)
        XCTAssertNil(m.save(address: " https://kidney.example.org ", token: "khd_" + String(repeating: "a", count: 43)))
        XCTAssertTrue(m.hasToken)
        XCTAssertEqual(m.address, "https://kidney.example.org")
        XCTAssertEqual(m.appURL?.absoluteString, "https://kidney.example.org/")
    }

    func testAQRCodeIsSavedOnlyAfterTheQuestionAndSaysWhatItReplaces() throws {
        let m = model()
        let token = "khd_" + String(repeating: "b", count: 43)
        let link = try XCTUnwrap(Pairing.parse("kidneyhealthsync://pair?v=1&server=https%3A%2F%2Fkidney.example.org&token=" + token))
        XCTAssertFalse(m.hasToken)  // reading the link saves nothing
        XCTAssertEqual(m.pairingQuestion(link), "This phone will send your weight and blood pressure to https://kidney.example.org. "
                       + "Pair only with a QR code from your own server, under Settings → Phone shortcuts.")
        XCTAssertNil(m.save(address: link.server, token: link.token))
        XCTAssertTrue(m.hasToken)
        XCTAssertEqual(m.address, "https://kidney.example.org")
        XCTAssertTrue(m.pairingQuestion(link).hasSuffix(" The token saved on this phone now is replaced."))
        XCTAssertNil(Pairing.parse("kidneyhealthsync://pair?v=1&server=http%3A%2F%2Fkidney.example.org&token=" + token))
    }

    func testAnotherServerStartsAgainFromThreeMonthsBack() throws {
        let m = model()
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        try Keychain.save(Data("anchor".utf8), as: .anchors)
        XCTAssertNil(m.save(address: "https://one.example.org/", token: ""))
        XCTAssertNotNil(Keychain.read(.anchors))
        XCTAssertNil(m.save(address: "https://two.example.org", token: ""))
        XCTAssertNil(Keychain.read(.anchors))
    }

    func testRemovingTheTokenForgetsTheAnchorsToo() throws {
        let m = model()
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        try Keychain.save(Data("anchor".utf8), as: .anchors)
        m.removeToken()
        XCTAssertFalse(m.hasToken)
        XCTAssertNil(Keychain.read(.anchors))
        XCTAssertEqual(m.status, "The token was removed from this phone.")
    }

    func testTestConnectionSaysWhatTheServerAnswered() async throws {
        let m = model(transport: URLSessionTransport(session: URLSessionTransport.makeSession(protocolClasses: [StubProtocol.self])))
        await m.testConnection()
        XCTAssertEqual(m.checkResult, "Save the address and a token first.")
        XCTAssertNil(m.save(address: "https://kidney.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        StubProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(#"{"ok": true}"#.utf8))
        }
        await m.testConnection()
        XCTAssertEqual(m.checkResult, "Connected. The server took the token.")
        StubProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!, Data())
        }
        await m.testConnection()
        XCTAssertEqual(m.checkResult, ConnectionCheck.badToken.text)
        XCTAssertNil(m.save(address: "https://kidney.example.org", token: ""))
        XCTAssertNil(m.checkResult)  // a new save clears the old answer
    }

    func testTheDayIsThePhonesCalendarDay() {
        XCTAssertEqual(SyncModel.day(Date(timeIntervalSince1970: 0)).count, 10)
    }

    func testANewTokenAtTheSameServerStartsWithItsOwnSyncPosition() throws {
        let m = model()
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        try Keychain.save(Data("old-token-anchor".utf8), as: .anchors)
        let defaults = UserDefaults(suiteName: "SettingsScreenTests")!
        defaults.set("2026-01-01", forKey: "since")
        XCTAssertNil(m.save(address: "https://one.example.org/", token: "khd_" + String(repeating: "b", count: 43)))
        XCTAssertNil(Keychain.read(.anchors))
        XCTAssertNil(defaults.string(forKey: "since"))
    }

    func testSavingTheSameTokenAndServerKeepsTheSyncPosition() throws {
        let m = model()
        let token = "khd_" + String(repeating: "a", count: 43)
        XCTAssertNil(m.save(address: "https://one.example.org", token: token))
        let anchor = Data("same-token-anchor".utf8)
        try Keychain.save(anchor, as: .anchors)
        XCTAssertNil(m.save(address: "https://one.example.org/", token: token))
        XCTAssertEqual(Keychain.read(.anchors), anchor)
    }

    func testALateConnectionAnswerCannotRestoreTheResultAfterRemovingTheToken() async throws {
        let transport = HeldCheck()
        let m = model(transport: transport)
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        let check = Task { await m.testConnection() }
        try await transport.waitForRequest()
        m.removeToken()
        await transport.answer(HTTPReply(status: 200, body: Data(#"{"ok": true}"#.utf8)))
        await check.value
        XCTAssertNil(m.checkResult)
        XCTAssertFalse(m.hasToken)
        XCTAssertEqual(m.status, "The token was removed from this phone.")
    }

    func testALateRateLimitCannotPauseTheNewServer() async throws {
        let transport = HeldCheck()
        let m = model(transport: transport)
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        let check = Task { await m.testConnection() }
        try await transport.waitForRequest()
        XCTAssertNil(m.save(address: "https://two.example.org", token: "khd_" + String(repeating: "b", count: 43)))
        await transport.answer(HTTPReply(status: 429, headers: ["Retry-After": "3600"]))
        await check.value
        XCTAssertNil(m.checkResult)
        XCTAssertNil(UserDefaults(suiteName: "SettingsScreenTests")!.object(forKey: "waitUntil"))
    }

    private func batch() -> SampleBatch {
        SampleBatch(weights: [WeightSample(start: Date(), zone: TimeZone(secondsFromGMT: 0)!, value: 70,
                                          unit: .kg, source: "Health")], readings: [], anchor: Data("old-sync-anchor".utf8))
    }

    func testRemovingTheTokenDuringASyncDoesNotRestoreAnchorsOrStatus() async throws {
        let transport = HeldCheck(), samples = batch()
        let m = model(transport: transport, health: SampleSource { (samples, false) })
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        let sync = Task { await m.syncNow() }
        try await transport.waitForRequest()
        m.removeToken()
        await transport.answer(accepted(1))
        await sync.value
        XCTAssertNil(Keychain.read(.anchors))
        XCTAssertNil(m.lastSent)
        XCTAssertEqual(m.status, "The token was removed from this phone.")
        XCTAssertFalse(m.syncing)
        XCTAssertNil(UserDefaults(suiteName: "SettingsScreenTests")!.string(forKey: "since"))
    }

    func testReplacingTheTokenDuringASyncIgnoresTheOldRateLimit() async throws {
        let transport = HeldCheck(), samples = batch()
        let m = model(transport: transport, health: SampleSource { (samples, false) })
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        let sync = Task { await m.syncNow() }
        try await transport.waitForRequest()
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "b", count: 43)))
        await transport.answer(HTTPReply(status: 429, headers: ["Retry-After": "3600"]))
        await sync.value
        XCTAssertNil(Keychain.read(.anchors))
        XCTAssertNil(m.lastSent)
        XCTAssertEqual(m.status, "Nothing sent yet.")
        XCTAssertNil(UserDefaults(suiteName: "SettingsScreenTests")!.object(forKey: "waitUntil"))
    }

    func testRemovingTheTokenWhileHealthIsReadingPreventsTheFirstPost() async throws {
        let samples = batch(), read = HeldSamples(), transport = CountingTransport()
        let m = model(transport: transport, health: SampleSource { await read.read() })
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        let sync = Task { await m.syncNow() }
        try await read.waitForRead()
        m.removeToken()
        await read.answer(samples)
        await sync.value
        let count = await transport.count
        XCTAssertEqual(count, 0)
        XCTAssertNil(Keychain.read(.anchors))
        XCTAssertEqual(m.status, "The token was removed from this phone.")
    }

    func testARefusedTokenPausesAutomaticSendingUntilSettingsAreSaved() async {
        let transport = CountingTransport(status: 401), samples = batch()
        let m = model(transport: transport, health: SampleSource { (samples, false) })
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        await m.syncNow()
        await m.syncNow()
        let count = await transport.count
        XCTAssertEqual(count, 1)
        XCTAssertNil(Keychain.read(.anchors))
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "b", count: 43)))
        await m.syncNow()
        let afterSave = await transport.count
        XCTAssertEqual(afterSave, 2)
    }

    func testASuccessfulConnectionCheckAllowsSendingAgain() async {
        let transport = CountingTransport(status: 401), samples = batch()
        let m = model(transport: transport, health: SampleSource { (samples, false) })
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        await m.syncNow()
        await transport.setStatus(200)
        await m.testConnection()
        await m.syncNow()
        XCTAssertEqual(Keychain.read(.anchors), samples.anchor)
        let count = await transport.count
        XCTAssertEqual(count, 2)
    }

    func testChangingSettingsBetweenRequestsStopsTheRestOfASyncBatch() async {
        let flag = CurrentSettings()
        let base = CountingTransport(afterPost: { await flag.stop() })
        let transport = SettingsTransport(base: base, isCurrent: { await flag.current() })
        let weights = (0..<51).map { index in
            WeightSample(start: Date().addingTimeInterval(-86400 * Double(index)), zone: TimeZone(secondsFromGMT: 0)!,
                         value: 70, unit: .kg, source: "Health")
        }
        let outcome = await Sync.run(SampleBatch(weights: weights, readings: [], anchor: Data("anchor".utf8)),
                                     to: URL(string: "https://one.example.org/push/v1/body")!, token: "old-token",
                                     today: SyncModel.day(Date()), transport: transport)
        let count = await base.count
        XCTAssertEqual(count, 1)
        XCTAssertEqual(outcome.addedWeights, 50)
        XCTAssertNil(outcome.anchorToKeep)
    }
}

private func accepted(_ weights: Int) -> HTTPReply {
    HTTPReply(status: 200, body: Data("{\"added\":{\"weights\":\(weights),\"readings\":0},\"already_there\":{\"weights\":0,\"readings\":0},\"refused\":{\"watch\":0}}".utf8))
}

private final class SampleSource: HealthReading {
    let read: () async -> (SampleBatch, Bool)
    init(_ read: @escaping () async -> (SampleBatch, Bool)) { self.read = read }
    func requestAccess() async throws {}
    func observe(_ onChange: @escaping () async -> Void) {}
    func newSamples(since stored: Data?) async throws -> (batch: SampleBatch, more: Bool) { await read() }
}

private actor HeldSamples {
    var reply: CheckedContinuation<(SampleBatch, Bool), Never>?
    func read() async -> (SampleBatch, Bool) { await withCheckedContinuation { reply = $0 } }
    func answer(_ batch: SampleBatch) { reply?.resume(returning: (batch, false)); reply = nil }
    func waitForRead() async throws {
        for _ in 0..<500 {
            if reply != nil { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        throw URLError(.timedOut)
    }
}

private actor CurrentSettings {
    var active = true
    func stop() { active = false }
    func current() -> Bool { active }
}

private actor CountingTransport: PushTransport {
    var count = 0
    var status: Int
    let afterPost: @Sendable () async -> Void
    init(status: Int = 200, afterPost: @escaping @Sendable () async -> Void = {}) {
        self.status = status
        self.afterPost = afterPost
    }
    func setStatus(_ value: Int) { status = value }
    func get(_ url: URL, token: String) async throws -> HTTPReply {
        HTTPReply(status: 200, body: Data(#"{"ok": true}"#.utf8))
    }
    func post(_ body: Data, to url: URL, token: String) async throws -> HTTPReply {
        count += 1
        await afterPost()
        guard status == 200 else { return HTTPReply(status: status) }
        return accepted(try JSONDecoder().decode(Push.Request.self, from: body).weights.count)
    }
}

private actor HeldCheck: PushTransport {
    private var reply: CheckedContinuation<HTTPReply, Never>?

    func get(_ url: URL, token: String) async throws -> HTTPReply {
        await withCheckedContinuation { continuation in
            reply = continuation
        }
    }

    func post(_ body: Data, to url: URL, token: String) async throws -> HTTPReply {
        try await get(url, token: token)
    }

    func waitForRequest() async throws {
        for _ in 0..<500 {
            if reply != nil { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        throw URLError(.timedOut)
    }

    func answer(_ value: HTTPReply) {
        reply?.resume(returning: value)
        reply = nil
    }
}
