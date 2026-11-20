# The iOS app

A small iPhone app that sends new weights and blood pressure readings from Apple Health to your own server
([design note 15](../docs/dev/research/15-native-ios-app.md)). The web app stays the place for every screen.

What is here:

* `KidneyHealthCore/`: a Swift package with the rules the app must share with the server. They cover the plausible ranges, the time of
  day a reading gets, the watch rule, kilogram rounding, the key that stops a reading being added twice, and requests of at most 50 rows.
  It checks each row the way `POST /push/v1/body` does before the app sends it, because one refused row makes the whole request fail.
  It also holds one sync: what to send, when to stop, and the status line. It has no dependencies and no HealthKit code.
* `KidneyHealth/`: the app, one screen with three parts.
  * **Your server**: the address (HTTPS only) and the phone token from Settings → Phone shortcuts. The token is kept in the Keychain
    for this phone only. **Test connection** asks the server whether the saved token works (`GET /push/v1/check`) and sends nothing else.
  * **Pairing by QR code**: Settings → Phone shortcuts shows a QR code with a new token. The iPhone Camera opens the app with its
    `kidneyhealth://pair?…` link (registered in `KidneyHealth-Info.plist`). The app asks "Pair with …?" and saves the address and
    the token only when the person taps **Pair**. `Pairing.parse` in the package reads the link exactly as the server makes it.
  * **Apple Health**: one button asks to read weight and blood pressure. The app never asks to write.
  * **Sending**: what the last sync did, and **Send now**. Health wakes the app when it saves a new weight or reading.
* `KidneyHealthTests/`: tests that run in the iPhone simulator.
* `KidneyHealth.xcodeproj`: the Xcode project. It names folders, not files, so a new `.swift` file needs no project change.

How a sync works:

* The first sync starts three months back, as the Health export import does. Older readings stay out, so years of data do not run
  into the server's limit of 60 requests an hour.
* New samples are read in rounds of at most 500 of each kind. A round's place in Health is kept only after the server accepted all of
  it. A round that failed is sent again later, and the server counts what it already has as already there.
* A refused token stops sending until a new one is saved. "Too many requests" waits as long as the server says.
* Changing the server or token starts a fresh sync position; saving the same address and token keeps it. Older
  connection checks and sync replies cannot change the new settings' status or position. Removing a token stops
  further requests with it; a request already sent may still finish. A successful **Test connection** also allows
  sending again after a refused token.
* Readings deleted in Health stay on the server. In the web app, Settings → Phone shortcuts → "Delete what it sent" removes them.

## Putting it on an iPhone (TestFlight)

The `TestFlight` workflow (`.github/workflows/testflight.yml`) builds the app on GitHub's Mac runner, signs it and uploads it to
TestFlight. No Mac is needed. It runs only when someone starts it from main, under the `release` environment.

Signing is Apple's cloud signing: `xcodebuild` signs in with an App Store Connect API key and makes the certificate and profile
itself, so none are stored. The project's team is `579992SASJ`.

Once, in Apple's websites:

1. Register one iPhone under Devices (its UDID). Apple needs a device on the team to make the profile used while archiving.
2. Register the App ID `io.github.ksullivan86.kidneyhealth` with the **HealthKit** capability (Certificates, Identifiers &
   Profiles → Identifiers).
3. Create the app in App Store Connect with that bundle ID.
4. Make a Team API key with the **Admin** role (Users and Access → Integrations → App Store Connect API). Only Admin keys may use
   cloud-managed certificates. Download the `.p8` file; Apple offers it once.
5. In GitHub, Settings → Environments → `release`, add three secrets: `ASC_KEY_ID`, `ASC_ISSUER_ID`, and `ASC_KEY_P8` (the whole
   file, with its BEGIN and END lines).

Each time: Actions → TestFlight → Run workflow. The build number is the run number. Apple takes 5 to 30 minutes to process a build,
then it appears in the TestFlight app for internal testers. A build lasts 90 days.

Family or friends as testers, or an App Store listing, need Apple's review and a privacy policy first (design note 15, out of scope).

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
xcodebuild test -project ios/KidneyHealth.xcodeproj -scheme KidneyHealth \
  -destination "platform=iOS Simulator,name=iPhone 17"
```

CI does both on every pull request (the `swift` and `ios-app` jobs in `.github/workflows/ci.yml`). No Apple account or signing is
needed for either.

## Rules for this folder

* No third-party packages.
* The app reads weight and the two blood pressure numbers from Health, and nothing else. It never reads glucose, insulin or medicines,
  and it never writes to Health. `SafetyTests.swift` and `tests/test_ios_app.py` check this.
* No analytics, and no network but the person's own server.
