# The iOS app

The iPhone app. It runs the whole web app on the phone with no server ([design note 38](../docs/dev/research/38-iphone-app-without-a-server.md)),
and it can send new weights and blood pressure readings from Apple Health to your own server
([design note 15](../docs/dev/research/15-native-ios-app.md)).

## The app with no server

* `KidneyHealth/WebShell/` shows the web app full screen in a web view. It knows nothing about kidneys or food: a second app built
  on this code changes only `WebShellConfig.swift`.
* The web files are packed by `python3 scripts/build_preview.py --device ios/WebApp`, which CI and the TestFlight workflow run
  before Xcode. `ios/WebApp/` is not committed. Run that command once before building in Xcode.
* The page is served from the app under its own scheme, `kidneyhealth-app://app/`. It loads only those files and never reaches the
  network. A link to the handbook opens in Safari.
* The page runs in **device mode**: it starts empty, keeps its data on the phone from the first start, and has one person who is not
  an admin. The data lives in a web data store with a fixed identifier, so it comes back after every restart.
* After each change the page sends its export to the app, which writes it to Documents as `Kidney Health safety copy.json`. The
  Files app shows it under On My iPhone. To get the data back, import that file in Settings → Your data.
* Export in Settings opens the share sheet, so the person chooses where the file goes.
* Settings → This device → **Apple Health and server** opens the app's own settings, described below. There:
  * **Keys and services** (`Services/`): USDA FoodData Central with the person's own key and Open Food Facts, each off until turned
    on. The page asks the app through its `bridge` handler; the app fetches from fixed hosts and the page maps the answer with the
    server's rules.
  * **Health in this phone's log** (`Phone/LocalLog.swift`): once Health is allowed, new weights and readings go into the log on the
    phone when the app is open, with the server's rules and source keys.
  * **Lock with Face ID or passcode** (`Phone/AppLock.swift`): off by default.

## Apple Health and your server

What is here:

* `KidneyHealthCore/`: a Swift package with the rules the app must share with the server. They cover the plausible ranges, the time of
  day a reading gets, the watch rule, kilogram rounding, the key that stops a reading being added twice, and requests of at most 50 rows.
  It checks each row the way `POST /push/v1/body` does before the app sends it, because one refused row makes the whole request fail.
  It also holds one sync: what to send, when to stop, and the status line. It has no dependencies and no HealthKit code.
* `KidneyHealth/`: the app. Its settings screen has three parts.
  * **Your server**: the address (HTTPS only) and the phone token from Settings → Account → Your data → Phone shortcuts. The token is kept in the Keychain
    for this phone only. **Test connection** asks the server whether the saved token works (`GET /push/v1/check`) and sends nothing else.
  * **Pairing by QR code**: Settings → Account → Your data → Phone shortcuts shows a QR code with a new token. The iPhone Camera opens the app with its
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
* Readings deleted in Health stay on the server. In the web app, Settings → Account → Your data → Phone shortcuts → "Delete what it sent" removes them.

## Putting it on an iPhone (TestFlight)

The `TestFlight` workflow (`.github/workflows/testflight.yml`) builds the app with Xcode 27.2 on GitHub's Mac runner, signs it and uploads it to
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
