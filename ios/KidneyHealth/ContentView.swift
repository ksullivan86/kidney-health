// The one screen: your server, Apple Health, and what was sent. Every other screen is in the web app.
import KidneyHealthCore
import SwiftUI

struct ContentView: View {
    /// A pairing link the Camera opened the app with while this sheet was closed: asked about as the sheet opens.
    var openedURL: URL? = nil
    @EnvironmentObject private var model: SyncModel
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var lock = AppLock.shared
    @State private var address = ""
    @State private var token = ""
    @State private var problem: String?
    @State private var saved = false
    /// The address and token of a QR code the Camera opened the app with, until the person says yes or no.
    @State private var pairing: Pairing.Link?
    @State private var scanning = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if QRScanner.available {
                        Button("Scan the QR code") { scanning = true }
                    }
                    TextField("https://kidney.example.org", text: $address)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .textContentType(.URL)
                    SecureField(model.hasToken ? "A token is saved" : "Paste the phone token", text: $token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("Save") {
                        problem = model.save(address: address, token: token)
                        saved = problem == nil
                        if saved { token = "" }
                    }
                    if let problem {
                        Text(problem).foregroundStyle(.red)
                    } else if saved {
                        Text("Saved.")
                    }
                    if model.hasToken {
                        if let kind = model.tokenKindText {
                            Text(kind) // both ways or add only (design note 39 §5.1)
                        }
                        Button(model.testing ? "Testing…" : "Test connection") {
                            Task { await model.testConnection() }
                        }
                        .disabled(model.testing)
                        if let result = model.checkResult {
                            Text(result)
                        }
                        Button("Remove the token from this phone", role: .destructive) { model.removeToken() }
                    }
                } header: {
                    Text("Your server")
                } footer: {
                    Text("To connect: in the web app, open Settings → Account → Your data → Phone shortcuts and make a token for the iPhone app, "
                         + "so the app can also send what you add in it. A token for the iPhone app, both ways, also lets the app use your "
                         + "server's AI and food services. "
                         + "Tap Scan the QR code and point it at the code, or type your server's address and paste the token here, then tap Save. "
                         + "If there is no Phone shortcuts form, ask whoever runs your server to turn phone shortcuts on. "
                         + "The token is kept on this phone only and is never shown again. "
                         + "Test connection checks the saved address and token, says which kind of token it is, and sends nothing else.")
                }

                Section {
                    Button("Allow weight and blood pressure") {
                        Task { await model.requestHealthAccess() }
                    }
                } header: {
                    Text("Apple Health")
                } footer: {
                    Text("The app reads your weight and blood pressure, and nothing else. It never writes to Health.")
                }

                Section {
                    Text(model.status)
                    if let lastSent = model.lastSent {
                        Text("Last sent \(lastSent.formatted(date: .abbreviated, time: .shortened))")
                            .foregroundStyle(.secondary)
                    }
                    Button(model.syncing ? "Sending…" : "Send now") {
                        Task { await model.syncNow() }
                    }
                    .disabled(model.syncing || !model.hasToken)
                } header: {
                    Text("Sending")
                } footer: {
                    Text("New readings are sent when Health saves them. Readings you delete in Health stay on the server. Blood pressure from a watch is not sent.")
                }

                if let url = model.appURL {
                    Section {
                        Link("Open the app", destination: url)
                    }
                }

                Section {
                    Text(model.phoneStatus)
                } header: {
                    Text("Health in this phone's log")
                } footer: {
                    Text("Once you allow Health above, new weights and blood pressure readings are added to the log on this phone when the app is open. Readings from a watch are not added.")
                }

                Section {
                    NavigationLink("Keys and services") { KeysView() }
                    Toggle("Lock with Face ID or passcode", isOn: Binding(get: { lock.enabled },
                                                                         set: { on in Task { await lock.setEnabled(on) } }))
                } footer: {
                    Text("Keys and services finds more foods with your own USDA key or Open Food Facts. The lock asks for Face ID or your passcode each time you come back to the app.")
                }

                Section {
                    NavigationLink("Storage test") { StorageCheckView() }
                } footer: {
                    Text("A test for a later version that works without a server. It keeps only the dates you open it.")
                }
            }
            .navigationTitle("Kidney Health")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .onAppear {
            address = model.address
            if let url = openedURL { handle(url) }
        }
        .onOpenURL { url in handle(url) }
        .sheet(isPresented: $scanning) {
            QRScanner { text in
                scanning = false
                if let url = URL(string: text) { handle(url) } else { problem = SyncModel.notAPairingLink }
            }
            .ignoresSafeArea()
        }
        .alert("Pair with \(pairing?.host ?? "this server")?",
               isPresented: Binding(get: { pairing != nil }, set: { if !$0 { pairing = nil } }), presenting: pairing) { link in
            Button("Pair") {
                problem = model.save(address: link.server, token: link.token)
                saved = problem == nil
                if saved {
                    address = model.address
                    token = ""
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: { link in
            Text(model.pairingQuestion(link))
        }
    }

    /// A pairing link only shows the question: nothing is saved until the person taps Pair.
    private func handle(_ url: URL) {
        if let link = Pairing.parse(url.absoluteString) {
            pairing = link
        } else {
            problem = SyncModel.notAPairingLink
            saved = false
        }
    }
}
