# The iOS app

A small iPhone app that sends new weights and blood pressure readings from Apple Health to your own server
([design note 15](../docs/dev/research/15-native-ios-app.md)). The web app stays the place for every screen.

What is here:

* `KidneyHealthCore/`: a Swift package with the rules the app must share with the server. They cover the plausible ranges, the time of
  day a reading gets, the watch rule, kilogram rounding, the key that stops a reading being added twice, and requests of at most 50 rows.
  It checks each row the way `POST /push/v1/body` does before the app sends it, because one refused row makes the whole request fail.
  It also holds one sync: what to send, when to stop, and the status line. It has no dependencies and no HealthKit code.
* `KidneyHealthSync/`: the app, one screen with three parts.
  * **Your server**: the address (HTTPS only) and the phone token from Settings → Phone shortcuts. The token is kept in the Keychain
    for this phone only. **Test connection** asks the server whether the saved token works (`GET /push/v1/check`) and sends nothing else.
  * **Pairing by QR code**: Settings → Phone shortcuts shows a QR code with a new token. The iPhone Camera opens the app with its
    `kidneyhealthsync://pair?…` link (registered in `KidneyHealthSync-Info.plist`). The app asks "Pair with …?" and saves the address and
    the token only when the person taps **Pair**. `Pairing.parse` in the package reads the link exactly as the server makes it.
  * **Apple Health**: one button asks to read weight and blood pressure. The app never asks to write.
  * **Sending**: what the last sync did, and **Send now**. Health wakes the app when it saves a new weight or reading.
* `KidneyHealthSyncTests/`: tests that run in the iPhone simulator.
* `KidneyHealthSync.xcodeproj`: the Xcode project. It names folders, not files, so a new `.swift` file needs no project change.

How a sync works:

* The first sync starts three months back, as the Health export import does. Older readings stay out, so years of data do not run
  into the server's limit of 60 requests an hour.
* New samples are read in rounds of at most 500 of each kind. A round's place in Health is kept only after the server accepted all of
  it. A round that failed is sent again later, and the server counts what it already has as already there.
* A refused token stops sending until a new one is saved. "Too many requests" waits as long as the server says.
* Readings deleted in Health stay on the server. In the web app, Settings → Phone shortcuts → "Delete what it sent" removes them.

Signing, TestFlight and a real iPhone come next, with the owner's Apple Developer account (step 3 of the design note).

## Running the tests

You need Swift 6.4 on Linux or a Mac. From the repository root:

```bash
swift test --package-path ios/KidneyHealthCore
```

The tests replay `tests/data/body_vectors.json`, `apple_health_vectors.json`, `push_vectors.json` and `pairing_vectors.json`, which hold the
server's own answers.
If a replay fails, fix the Swift code, not the vectors. When the server's rules change, regenerate the vectors first
(`python3 tests/data/gen_push_vectors.py` and the others in [`tests/data/README.md`](../tests/data/README.md)).

To build the app and run its tests in the simulator you need a Mac with Xcode 26:

```bash
xcodebuild test -project ios/KidneyHealthSync.xcodeproj -scheme KidneyHealthSync \
  -destination "platform=iOS Simulator,name=iPhone 17"
```

CI does both on every pull request (the `swift` and `ios-app` jobs in `.github/workflows/ci.yml`). No Apple account or signing is
needed for either.

## Rules for this folder

* No third-party packages.
* The app reads weight and the two blood pressure numbers from Health, and nothing else. It never reads glucose, insulin or medicines,
  and it never writes to Health. `SafetyTests.swift` and `tests/test_ios_app.py` check this.
* No analytics, and no network but the person's own server.
