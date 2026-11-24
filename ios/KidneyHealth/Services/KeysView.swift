// Settings → This device → Apple Health and server → Keys and services (design note 38, step 2, §5.3).
// Each service is off until the person turns it on, says which host it talks to and what it sends, and a key is never shown again.
import KidneyHealthCore
import SwiftUI

struct KeysView: View {
    @ObservedObject private var services = FoodServices.shared
    @ObservedObject private var pairing = SyncModel.shared
    @State private var key = ""
    @State private var keyMessage: String?
    @State private var testing = false

    var body: some View {
        Form {
            Section {
                // Design note 39 §7: with a token both ways, lookups go through the server, with its keys; no key crosses.
                Text(pairing.hasToken && pairing.tokenKind == .bothWays
                     ? "Using your server's food services while it can be reached. The keys below are used only when it cannot be."
                     : "Using this iPhone's keys.")
                Text("The app's own food list works with nothing turned on. These services find more foods. Each one is off until you turn it on, and sends only the words you type or the barcode you scan, never anything about you. Foods you look up are saved, so they work offline afterwards.")
            }

            Section {
                Toggle("Search USDA FoodData Central", isOn: Binding(get: { services.usdaOn }, set: { services.setOn(.usda, $0) }))
                SecureField(services.hasUsdaKey ? "A key is saved" : "Paste your key from api.data.gov", text: $key)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button(services.hasUsdaKey ? "Replace the key" : "Save the key") {
                    keyMessage = services.saveUsdaKey(key) ?? "Saved. The key is kept on this phone only and is not shown again."
                    key = ""
                }
                .disabled(key.isEmpty)
                if services.hasUsdaKey {
                    Button(testing ? "Testing…" : "Test the key") {
                        testing = true
                        Task {
                            keyMessage = await services.testUsda()
                            testing = false
                        }
                    }
                    .disabled(testing || !services.usdaOn)
                    Button("Remove the key", role: .destructive) {
                        services.removeUsdaKey()
                        keyMessage = "The key was removed from this phone."
                    }
                }
                if let keyMessage {
                    Text(keyMessage)
                }
            } header: {
                Text("USDA FoodData Central")
            } footer: {
                Text("Talks to api.nal.usda.gov. A free key from api.data.gov allows about 1,000 lookups an hour. USDA FoodData Central data is public domain (CC0).")
            }

            Section {
                Toggle("Look up barcodes on Open Food Facts", isOn: Binding(get: { services.offOn }, set: { services.setOn(.openFoodFacts, $0) }))
            } header: {
                Text("Open Food Facts")
            } footer: {
                Text("Talks to world.openfoodfacts.org and sends only the barcode. No key is needed. Product data © Open Food Facts contributors, ODbL. It is written by volunteers, so check it against the package.")
            }
        }
        .navigationTitle("Keys and services")
    }
}
