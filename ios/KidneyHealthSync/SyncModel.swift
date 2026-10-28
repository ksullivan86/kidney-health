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

    private let defaults: UserDefaults
    private let health: HealthSource?
    private let transport: PushTransport
    private var observing = false

    init(defaults: UserDefaults = .standard, health: HealthSource? = HealthSource.available ? HealthSource() : nil,
         transport: PushTransport = URLSessionTransport()) {
        self.defaults = defaults
        self.health = health
        self.transport = transport
        address = defaults.string(forKey: Key.address) ?? ""
        hasToken = Keychain.read(.token) != nil
        status = defaults.string(forKey: Key.status) ?? "Nothing sent yet."
        lastSent = defaults.object(forKey: Key.lastSent) as? Date
    }

    var appURL: URL? { Settings.appURL(address) }

    /// Saves the address and, when one is typed, the token. Nil when saved, else the problem in plain words.
    func save(address newAddress: String, token: String) -> String? {
        guard Settings.pushURL(newAddress) != nil else {
            return "Type the address of your server. It starts with https://."
        }
        let pasted = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if !pasted.isEmpty {
            guard Settings.isDeviceToken(pasted) else {
                return "That is not a phone token. Make one in Settings → Phone shortcuts. It starts with khd_."
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
        if Settings.pushURL(cleaned) != Settings.pushURL(address) {
            // Another server: start again from three months back.
            Keychain.delete(.anchors)
            defaults.removeObject(forKey: Key.since)
        }
        address = cleaned
        defaults.set(cleaned, forKey: Key.address)
        return nil
    }

    /// Removes the token and the anchors from this phone. Rows already sent stay on the server ("Delete what it sent" removes them).
    func removeToken() {
        Keychain.delete(.token)
        Keychain.delete(.anchors)
        defaults.removeObject(forKey: Key.since)
        hasToken = false
        setStatus("The token was removed from this phone.")
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
        startObserving()
        await syncNow()
    }

    func startObserving() {
        guard let health, !observing else { return }
        observing = true
        health.observe { await SyncModel.shared.syncNow() }
    }

    /// Sends what is new, in rounds of at most 500 samples of each kind. A round's anchor is kept only when the server took all of
    /// it, so a failed round is sent again next time; the server counts the repeats as already there.
    func syncNow() async {
        guard !syncing, let health, let url = Settings.pushURL(address),
              let tokenData = Keychain.read(.token), let token = String(data: tokenData, encoding: .utf8) else { return }
        if let until = defaults.object(forKey: Key.waitUntil) as? Date, until > Date() { return }
        syncing = true
        defer { syncing = false }
        let today = Self.day(Date())
        if defaults.string(forKey: Key.since) == nil {
            defaults.set(Push.defaultSince(today), forKey: Key.since)
        }
        let since = defaults.string(forKey: Key.since)
        var total = SyncOutcome(state: .done)
        for _ in 0..<Self.maxRounds {
            let round: (batch: SampleBatch, more: Bool)
            do {
                round = try await health.newSamples(since: Keychain.read(.anchors))
            } catch {
                setStatus("Health data could not be read. Check that the app may read weight and blood pressure.")
                return
            }
            let outcome = await Sync.run(round.batch, to: url, token: token, today: today, since: since, transport: transport)
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
    }
}
