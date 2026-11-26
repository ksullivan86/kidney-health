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
    @ObservedObject private var own = OwnAI.shared
    @State private var ownProvider: OwnAIProvider = .openai
    @State private var ownModel = ""
    @State private var ownKey = ""
    @State private var ownMessage: String?
    @State private var ownTesting = false

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
            Section {
                Text(own.ready
                     ? "Using \(own.provider?.label ?? "your provider") with your own key. Your server's AI is used first when this iPhone is paired with one both ways."
                     : "Add a key from an AI company to use AI features with no server. Your server's AI is used first when this iPhone is paired with one both ways.")
                Picker("Provider", selection: $ownProvider) {
                    ForEach(OwnAIProvider.allCases) { provider in
                        Text(provider.label).tag(provider)
                    }
                }
                .onChange(of: ownProvider) { _, provider in
                    if provider != own.provider { ownModel = provider.defaultModel ?? "" }
                }
                TextField("Model, as \(ownProvider.label) names it", text: $ownModel)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                SecureField(own.hasKey && own.provider == ownProvider ? "A key is saved" : "Paste your key", text: $ownKey)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button(own.hasKey ? "Save" : "Save the key") {
                    ownMessage = own.save(provider: ownProvider, model: ownModel, key: ownKey)
                        ?? "Saved. The key is kept on this phone only and is not shown again."
                    ownKey = ""
                }
                .disabled(ownModel.isEmpty || (ownKey.isEmpty && !(own.hasKey && own.provider == ownProvider)))
                if own.ready {
                    Button(ownTesting ? "Testing…" : "Test the key") {
                        ownTesting = true
                        Task {
                            ownMessage = await own.test()
                            ownTesting = false
                        }
                    }
                    .disabled(ownTesting)
                    Toggle("Also send meal and label photos to this AI", isOn: Binding(get: { own.photosOn }, set: { own.setPhotos($0) }))
                    Button("Remove the key", role: .destructive) {
                        own.remove()
                        ownMessage = "The key was removed from this phone."
                    }
                }
                if let ownMessage {
                    Text(ownMessage)
                }
            } header: {
                Text("Your own AI key")
            } footer: {
                Text("Talks only to \(ownProvider.host). It is used for describing a meal, and for photos of a meal or a label only if you turn that on. Lab reports, and anything with your name or date of birth, are never sent to it. They stay on this iPhone or your own server. Turn AI features on in Settings → AI features in the app. \(ownProvider.policy)")
            }
            .onAppear {
                if let saved = own.provider {
                    ownProvider = saved
                    ownModel = own.model
                } else if ownModel.isEmpty {
                    ownModel = ownProvider.defaultModel ?? ""
                }
            }
        }
        .navigationTitle("Keys and services")
    }
}
