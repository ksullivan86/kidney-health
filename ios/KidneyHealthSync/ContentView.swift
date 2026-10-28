// The one screen: your server, Apple Health, and what was sent. Every other screen is in the web app.
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: SyncModel
    @State private var address = ""
    @State private var token = ""
    @State private var problem: String?
    @State private var saved = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
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
                        Button("Remove the token from this phone", role: .destructive) { model.removeToken() }
                    }
                } header: {
                    Text("Your server")
                } footer: {
                    Text("Make a token in the web app under Settings → Phone shortcuts. It is kept on this phone only and is never shown again.")
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
            }
            .navigationTitle("Kidney Health Sync")
        }
        .onAppear { address = model.address }
    }
}
