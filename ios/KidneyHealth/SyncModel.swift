// What the screen shows and what a sync does: settings, Health access, and sending new samples in rounds. The rules of a sync are in
// KidneyHealthCore (Sync.run); this file only wires Health, the Keychain and the network to them.
import Foundation
import KidneyHealthCore

@MainActor
final class SyncModel: ObservableObject {
    static let shared = SyncModel()

    /// At most this many rounds of new samples in one sync. A long history continues at the next sync.
    static let maxRounds = 10

    @Published private(set) var address: String
    @Published private(set) var hasToken: Bool
    @Published private(set) var status: String
    @Published private(set) var lastSent: Date?
    @Published private(set) var syncing = false
    @Published private(set) var testing = false
    /// The answer of the last **Test connection**, until the settings change.
    @Published private(set) var checkResult: String?
    /// What the last sync into the log on this phone did (design note 38, step 3).
    @Published private(set) var phoneStatus: String
    @Published private(set) var phoneSyncing = false
    /// What the saved token can do on its server (design note 39 §5.1): both ways, add only, or not known yet.
    @Published private(set) var tokenKind: ServerAPI.TokenKind

    private let defaults: UserDefaults
    private let health: HealthReading?
    private let transport: PushTransport
    private var observing = false
    private var settingsGeneration: UInt64 = 0

    private func generationIsCurrent(_ generation: UInt64) -> Bool { generation == settingsGeneration }

    init(defaults: UserDefaults = .standard, health: HealthReading? = HealthSource.available ? HealthSource() : nil,
         transport: PushTransport = URLSessionTransport()) {
        self.defaults = defaults
        self.health = health
        self.transport = transport
        address = defaults.string(forKey: Key.address) ?? ""
        hasToken = Keychain.read(.token) != nil
        status = defaults.string(forKey: Key.status) ?? "Nothing sent yet."
        lastSent = defaults.object(forKey: Key.lastSent) as? Date
        phoneStatus = defaults.string(forKey: Key.phoneStatus) ?? "Nothing added from Health yet."
        tokenKind = ServerAPI.TokenKind(rawValue: defaults.string(forKey: Key.serverOffers) ?? "") ?? .unknown
    }

    /// The pairing screen's line about the saved token, or nil while it is not known.
    var tokenKindText: String? { hasToken ? ServerAPI.text(tokenKind) : nil }

    var appURL: URL? { Settings.appURL(address) }

    /// Saves the address and, when one is typed, the token. Nil when saved, else the problem in plain words.
    func save(address newAddress: String, token: String) -> String? {
        guard Settings.pushURL(newAddress) != nil else {
            return "Type the address of your server. It starts with https://."
        }
        let pasted = token.trimmingCharacters(in: .whitespacesAndNewlines)
        let tokenChanged = !pasted.isEmpty && Data(pasted.utf8) != Keychain.read(.token)
        if !pasted.isEmpty {
            guard Settings.isDeviceToken(pasted) else {
                return "That is not a phone token. Make one in Settings → Account → Your data → Phone shortcuts. It starts with khd_."
            }
            do {
                try Keychain.save(Data(pasted.utf8), as: .token)
            } catch {
                return "The token could not be saved on this phone."
            }
            hasToken = true
            defaults.removeObject(forKey: Key.waitUntil)
        }
        let cleaned = newAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        if Settings.pushURL(cleaned) != Settings.pushURL(address) || tokenChanged {
            // A different server or token may belong to another account: start again from three months back.
            Keychain.delete(.anchors)
            defaults.removeObject(forKey: Key.since)
            defaults.removeObject(forKey: Key.waitUntil)
            defaults.removeObject(forKey: Key.lastSent)
            lastSent = nil
            setStatus("Nothing sent yet.")
            setTokenKind(.unknown)
        }
        settingsGeneration &+= 1
        defaults.removeObject(forKey: Key.sendingPaused)
        address = cleaned
        defaults.set(cleaned, forKey: Key.address)
        checkResult = nil
        startObserving()
        if hasToken { Task { await checkTokenKind() } }
        return nil
    }

    /// Said when the app is opened with a link that is not a pairing link the server made.
    static let notAPairingLink = "That is not a pairing code from Settings → Account → Your data → Phone shortcuts. Make a new phone token there and scan its QR code."

    /// What the app asks before it saves the address and token of a QR code, so a code made by someone else is not taken quietly.
    func pairingQuestion(_ link: Pairing.Link) -> String {
        var text = "This phone will send your weight and blood pressure, and with a token for the iPhone app what you add in the app, to \(link.server). "
            + "With a token for the iPhone app, both ways, the app also uses that server's AI and food services. "
            + "Pair only with a QR code from your own server, under Settings → Account → Your data → Phone shortcuts."
        if hasToken { text += " The token saved on this phone now is replaced." }
        return text
    }

    /// Removes the token and the anchors from this phone. Rows already sent stay on the server ("Delete what it sent" removes them).
    func removeToken() {
        settingsGeneration &+= 1
        Keychain.delete(.token)
        Keychain.delete(.anchors)
        defaults.removeObject(forKey: Key.since)
        defaults.removeObject(forKey: Key.waitUntil)
        defaults.removeObject(forKey: Key.sendingPaused)
        hasToken = false
        checkResult = nil
        setTokenKind(.unknown)
        setStatus("The token was removed from this phone.")
    }

    /// Asks the saved server what the saved token may do (`GET /push/v1/about`, design note 39 §5.3). Sends only the token. With no
    /// answer (offline) what was known stays.
    func checkTokenKind() async {
        guard let url = ServerAPI.url(address, route: ServerAPI.about),
              let tokenData = Keychain.read(.token), let token = String(data: tokenData, encoding: .utf8) else { return }
        let generation = settingsGeneration
        let reply = try? await transport.get(url, token: token)
        guard generationIsCurrent(generation), let reply else { return }
        setTokenKind(ServerAPI.tokenKind(reply))
    }

    private func setTokenKind(_ kind: ServerAPI.TokenKind) {
        tokenKind = kind
        defaults.set(kind.rawValue, forKey: Key.serverOffers)
    }

    /// Asks the saved server whether the saved token works (`GET /push/v1/check`). Nothing of Health is read or sent.
    func testConnection() async {
        guard !testing, let url = Settings.checkURL(address),
              let tokenData = Keychain.read(.token), let token = String(data: tokenData, encoding: .utf8) else {
            checkResult = "Save the address and a token first."
            return
        }
        let generation = settingsGeneration
        testing = true
        defer { testing = false }
        let result = await ConnectionCheck.run(url, token: token, transport: transport)
        guard generationIsCurrent(generation) else { return }
        if result == .ok {
            defaults.removeObject(forKey: Key.sendingPaused)
            defaults.removeObject(forKey: Key.waitUntil)
        } else if result == .badToken {
            defaults.set(true, forKey: Key.sendingPaused)
        }
        if case .wait(let seconds) = result {
            // The check shares the token's hour with sending, so sending would be refused too.
            defaults.set(Date().addingTimeInterval(TimeInterval(seconds)), forKey: Key.waitUntil)
        }
        checkResult = result.text
        if result == .ok { await checkTokenKind() }
    }

    func requestHealthAccess() async {
        guard let health else {
            setStatus("Health is not available on this device.")
            return
        }
        do {
            try await health.requestAccess()
        } catch {
            setStatus("Health access could not be asked for.")
            return
        }
        defaults.set(true, forKey: Key.healthAsked)
        startObserving()
        await syncToPhone()
        await syncNow()
    }

    /// Starts the Health observers once there is somewhere to send: the log on this phone, after the person allowed Health, or a
    /// server. Before that nothing of Health is touched.
    func startObserving() {
        let toServer = hasToken && Settings.pushURL(address) != nil
        guard let health, !observing, defaults.bool(forKey: Key.healthAsked) || toServer else { return }
        observing = true
        health.observe {
            await SyncModel.shared.syncToPhone()
            await SyncModel.shared.syncNow()
        }
    }

    /// Adds what is new in Health to the log on this phone (design note 38, step 3), in rounds like the server sync, through the page
    /// (LocalLogTransport). A round's anchor is kept only when the page saved all of it; while the app is not open the page is not
    /// there, and the next sync adds the round. Has its own anchors and start day, so the server sync is not changed.
    func syncToPhone() async {
        guard !phoneSyncing, let health, defaults.bool(forKey: Key.healthAsked) else { return }
        phoneSyncing = true
        defer { phoneSyncing = false }
        let today = Self.day(Date())
        if defaults.string(forKey: Key.phoneSince) == nil {
            defaults.set(Push.defaultSince(today), forKey: Key.phoneSince)
        }
        let since = defaults.string(forKey: Key.phoneSince)
        let local = LocalLogTransport(today: today)
        var total = SyncOutcome(state: .done)
        for _ in 0..<Self.maxRounds {
            let round: (batch: SampleBatch, more: Bool)
            do {
                round = try await health.newSamples(since: Keychain.read(.phoneAnchors))
            } catch {
                setPhoneStatus("Health data could not be read. Check that the app may read weight and blood pressure.")
                return
            }
            let outcome = await Sync.run(round.batch, to: LocalLogTransport.url, token: "", today: today, since: since, transport: local)
            total = Self.adding(outcome, to: total)
            guard let keep = outcome.anchorToKeep else { break }
            try? Keychain.save(keep, as: .phoneAnchors)
            if !round.more { break }
        }
        switch total.state {
        case .offline:
            setPhoneStatus("New readings are added when the app is open.")
        case .refused(let text):
            setPhoneStatus("Some readings were not added: \(text)")
        default:
            let added = total.addedWeights + total.addedReadings
            setPhoneStatus(added == 0 ? "Up to date with Health." : "Added \(total.addedWeights) weights and \(total.addedReadings) readings from Health.")
        }
    }

    private func setPhoneStatus(_ text: String) {
        phoneStatus = text
        defaults.set(text, forKey: Key.phoneStatus)
    }

    /// Sends what is new, in rounds of at most 500 samples of each kind. A round's anchor is kept only when the server took all of
    /// it, so a failed round is sent again next time; the server counts the repeats as already there.
    func syncNow() async {
        guard !syncing, !defaults.bool(forKey: Key.sendingPaused), let health, let url = Settings.pushURL(address),
              let tokenData = Keychain.read(.token), let token = String(data: tokenData, encoding: .utf8) else { return }
        if let until = defaults.object(forKey: Key.waitUntil) as? Date, until > Date() { return }
        let generation = settingsGeneration
        let activeTransport = SettingsTransport(base: transport, isCurrent: { [weak self] in
            await self?.generationIsCurrent(generation) ?? false
        })
        syncing = true
        defer { syncing = false }
        let today = Self.day(Date())
        if defaults.string(forKey: Key.since) == nil {
            defaults.set(Push.defaultSince(today), forKey: Key.since)
        }
        let since = defaults.string(forKey: Key.since)
        var total = SyncOutcome(state: .done)
        for _ in 0..<Self.maxRounds {
            guard generationIsCurrent(generation) else { return }
            let round: (batch: SampleBatch, more: Bool)
            do {
                round = try await health.newSamples(since: Keychain.read(.anchors))
            } catch {
                if generationIsCurrent(generation) {
                    setStatus("Health data could not be read. Check that the app may read weight and blood pressure.")
                }
                return
            }
            guard generationIsCurrent(generation) else { return }
            let outcome = await Sync.run(round.batch, to: url, token: token, today: today, since: since, transport: activeTransport)
            guard generationIsCurrent(generation) else { return }
            if case .needsNewToken = outcome.state { defaults.set(true, forKey: Key.sendingPaused) }
            total = Self.adding(outcome, to: total)
            if case .wait(let seconds) = outcome.state {
                defaults.set(Date().addingTimeInterval(TimeInterval(seconds)), forKey: Key.waitUntil)
            }
            guard let keep = outcome.anchorToKeep else { break }
            try? Keychain.save(keep, as: .anchors)
            if !round.more { break }
        }
        if total.addedWeights + total.addedReadings > 0 {
            lastSent = Date()
            defaults.set(lastSent, forKey: Key.lastSent)
        }
        setStatus(Sync.describe(total))
    }

    static func adding(_ outcome: SyncOutcome, to total: SyncOutcome) -> SyncOutcome {
        var sum = outcome
        sum.addedWeights += total.addedWeights
        sum.addedReadings += total.addedReadings
        sum.alreadyThere += total.alreadyThere
        sum.watchReadings += total.watchReadings
        sum.leftOut += total.leftOut
        return sum
    }

    /// `YYYY-MM-DD` on the phone's calendar and clock.
    static func day(_ date: Date) -> String {
        let parts = Calendar(identifier: .gregorian).dateComponents(in: .current, from: date)
        return String(format: "%04ld-%02ld-%02ld", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    private func setStatus(_ text: String) {
        status = text
        defaults.set(text, forKey: Key.status)
    }

    private enum Key {
        static let address = "address"
        static let status = "status"
        static let lastSent = "lastSent"
        static let waitUntil = "waitUntil"
        static let since = "since"
        static let sendingPaused = "sendingPaused"
        static let healthAsked = "healthAsked"
        static let phoneStatus = "phoneStatus"
        static let phoneSince = "phoneSince"
        static let serverOffers = "serverOffers" // what the paired token may do: never the token itself
    }
}


/// A sync may finish an issued request, but must not start another with removed or replaced settings.
struct SettingsTransport: PushTransport {
    let base: PushTransport
    let isCurrent: @Sendable () async -> Bool

    func post(_ body: Data, to url: URL, token: String) async throws -> HTTPReply {
        guard await isCurrent() else { throw CancellationError() }
        return try await base.post(body, to: url, token: token)
    }

    func get(_ url: URL, token: String) async throws -> HTTPReply {
        guard await isCurrent() else { throw CancellationError() }
        return try await base.get(url, token: token)
    }
}
