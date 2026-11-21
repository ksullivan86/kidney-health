// The optional lock (design note 38, step 3, decision D4): Face ID, Touch ID or the phone's passcode before the app shows anything.
// Off by default. When on, the app covers itself whenever it goes to the background and asks again when it comes back.
import LocalAuthentication
import UIKit
import SwiftUI

@MainActor
final class AppLock: ObservableObject {
    static let shared = AppLock()

    @Published private(set) var enabled: Bool
    @Published private(set) var locked: Bool
    @Published private(set) var problem: String?
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        enabled = defaults.bool(forKey: "lock.enabled")
        locked = defaults.bool(forKey: "lock.enabled")
    }

    /// Whether this phone can lock the app: a passcode is set (Face ID or Touch ID are used when they are set up too).
    var available: Bool {
        LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
    }

    /// Turning the lock on asks once, so a person cannot lock themselves out by mistake.
    func setEnabled(_ on: Bool) async {
        if on {
            guard await ask("Turn on the lock for Kidney Health") else { return }
        }
        enabled = on
        defaults.set(on, forKey: "lock.enabled")
        if !on { locked = false }
    }

    func lockIfEnabled() {
        if enabled { locked = true }
    }

    func unlock() async {
        guard locked else { return }
        if await ask("Unlock Kidney Health") { locked = false }
    }

    private func ask(_ reason: String) async -> Bool {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            problem = "This iPhone has no passcode, so the app cannot be locked."
            return false
        }
        do {
            let ok = try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)
            problem = nil
            return ok
        } catch {
            problem = nil // a cancelled prompt is not a problem worth a sentence; the lock screen stays
            return false
        }
    }
}

/// What covers the app while it is locked: no health data shows, in the app switcher either.
struct LockScreen: View {
    @ObservedObject var lock: AppLock

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "lock.fill").font(.largeTitle)
            Text("Kidney Health is locked").font(.headline)
            Button("Unlock") { Task { await lock.unlock() } }
                .buttonStyle(.borderedProminent)
            if let problem = lock.problem {
                Text(problem).font(.footnote)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
    }
}
