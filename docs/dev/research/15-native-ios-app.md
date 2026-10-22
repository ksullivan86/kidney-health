# 15 · A native iOS app (proposal: a Health sync companion first, the full shell later)

| | |
|---|---|
| Status | **Proposed, 2026-10-22: the owner decides (§7).** Nothing is built. |
| Date researched | 2026-10-22, against `main` with notes 10–14 |
| Scope | What a native iPhone app adds to the Home Screen web app, the smallest first version, how it reuses the server and the tests, what it needs from the owner (an Apple Developer account, signing, TestFlight), and how it is built without a Mac. |
| Out of scope | An App Store listing (a separate decision: review, a privacy policy, Apple's health-data rules and a regulatory opinion, ROADMAP); Android (later, the same pattern with Health Connect); glucose, insulin and medicines (CLAUDE.md: no dosing data, ever; the app never reads those HealthKit types); push notifications from the server. |
| Builds on | Note 02 (the Home Screen web app is the app; §3.1 set a native wrapper aside for v0.x), note 10 (weight and blood pressure, the Health export reader and its `source_key`), note 12 (device tokens and `POST /push/v1/body`, written as the iOS app's sync path), note 14 (reuse map: change 6, a Swift test target that replays the JSON vectors). |
| Re-verify | Every Apple fact in §2 against Apple's current documentation when the build starts (the owner's account, Xcode on the macOS runner); the HealthKit behaviour on a real iPhone (the owner's). |

---

## 1. Context

The owner asked (2026-10-22) where a native iOS app sits on the roadmap, and that what is built now be reusable for it and for a more general AI meal planner. The Home Screen web app already covers the screens, offline entry, the camera and the barcode scanner. What only a native app can do:

* **read Apple Health directly and in the background** (weights and blood pressure as they arrive, with no export, no Shortcut, no unzip);
* later, better scanning (VisionKit), on-device speech and reliable notifications.

Note 12 built the server half of that: a write-only device token and an add-only, counts-only ingest route.

## 2. Facts to rely on (re-verify each when the build starts)

| # | Fact | Source to check |
|---|---|---|
| I1 | HealthKit gives an app read access per data type, asked once per type; the person can refuse or later withdraw any type in Settings; an app cannot tell whether read access was refused (it just sees no samples). | Apple, "Authorizing access to health data" |
| I2 | `HKObserverQuery` plus `enableBackgroundDelivery(for:frequency:)` wakes the app when new samples of a type are saved; `HKAnchoredObjectQuery` returns what is new since the last anchor (and deletions). Background delivery needs the HealthKit background-delivery entitlement. | Apple, "Executing observer queries", "enableBackgroundDelivery" |
| I3 | Body mass and blood pressure are `HKQuantityTypeIdentifier.bodyMass`, `.bloodPressureSystolic`, `.bloodPressureDiastolic` (the pair as an `HKCorrelation` of type `.bloodPressure`); each sample has a start date, a value with a unit and a source revision (the source's name). These are the same records the Health export writes as `HKQuantityTypeIdentifierBodyMass` and so on (note 10 §4.8). | Apple, HealthKit type identifiers |
| I4 | The Keychain stores secrets for one app; an item can be limited to this device (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), which background delivery needs (the phone is often locked). | Apple, "Keychain services" |
| I5 | `WKWebView` runs service workers only for the domains listed as App-Bound Domains in the app's Info.plist (at most 10). A self-hosted server's domain is not known when the app is built, so a WKWebView shell cannot rely on the web app's service worker. | Apple, "App-Bound Domains" (WebKit) |
| I6 | Builds can be made and signed on GitHub's `macos` runners with Xcode; TestFlight builds expire after 90 days; the Apple Developer Program costs USD 99 a year. | GitHub runner images; Apple Developer Program |
| I7 | App Review guideline 4.2 (minimum functionality) rejects apps that are mostly a repackaged website. | Apple, App Review Guidelines 4.2 |

## 3. Options

| Option | What it is | Reuses | Risk | Verdict |
|---|---|---|---|---|
| **A. Health sync companion** | A small SwiftUI app with three screens: the server address and a device token (or a pairing step), what it may read (weight, blood pressure) with Apple's permission sheet, and a status line (last sent, counts). HealthKit background delivery sends new weights and readings to `POST /push/v1/body`. An **Open the app** button opens the web app in Safari (the Home Screen app stays the place for every screen). | The whole server and web app unchanged; note 12's route, limits, same-reading check and watch refusal; the reader's `source_key` text | Small: about 600–1,000 lines of Swift; no web view, so I5 does not apply | **Recommended first** |
| B. WKWebView shell | Option A plus the web app inside the native app | The whole web app | I5 (no service worker for a self-hosted domain, so no offline shell), cookies and sign-in inside a web view, guideline 4.2 for a listing | Later, only if the owner wants one app icon instead of two |
| C. Native screens (SwiftUI over the API) | A second front end | The server and the vectors only | A second copy of every screen and rule; the reuse map's twin cost (note 14 §5 risk 6) | No |

## 4. Design of option A

### 4.1 The Swift package `KidneyHealthCore` (pure, no UI, no HealthKit import)

* The rules that must equal the server's, as plain functions:
  * the plausible ranges and per-day limits (note 10 §4.1);
  * the context from the time of day (`context_for`, note 12);
  * the watch-like source test (`is_watch_source`);
  * `source_key` built from the same text as the Health export reader (note 10 §4.8, note 12 §4.2);
  * the kilogram rounding (half up to 0.01 kg, `0.45359237` per lb);
  * the batch splitting (at most 50 rows a request).
* **Tested on Linux** in CI with the official Swift toolchain image, pinned by digest like every other image. The tests replay `tests/data/body_vectors.json` and `tests/data/apple_health_vectors.json`, which are Python's answers. This is note 14's change 6, and it needs no Mac and no Apple account.
* The same package is what a general meal-tracker app would use for its own HealthKit sync.

### 4.2 The app target (`ios/` in this repository; built on a `macos` runner)

* **Settings screen.**
  * The server address (HTTPS only).
  * The device token, pasted, or (later) paired by scanning a QR code that Settings → Phone shortcuts shows once.
  * The token is stored in the Keychain, this device only (I4), never in `UserDefaults`, and never shown again after saving.
  * A **Test connection** button posts an empty-looking request that the server answers with counts. If the route needs a body, it sends a zero-row request; the server must accept that or offer a dedicated check. Decide this when building.
* **Permissions screen.**
  * Asks for exactly three read types (I3): body mass, systolic and diastolic.
  * Never asks for glucose, insulin or any medication type (CLAUDE.md). A test enforces this by reading the entitlement and the requested type list.
* **Sync.**
  * `HKObserverQuery` with background delivery for the three types (I2). On wake, an `HKAnchoredObjectQuery` returns the new samples since the stored anchor.
  * Samples are mapped with `KidneyHealthCore`. Readings come from `.bloodPressure` correlations, so the pairing is exact.
  * Watch-like sources are left out locally, as the server would refuse them.
  * The result is posted in batches of up to 50. The anchor is saved only after a 200.
  * On a 401, sync stops and the status line says to make a new token. On a 429, it waits for `Retry-After`. Deletions in Health are not sent (the route is add-only), and the status line says so once.
* **Status screen.** The last time sent, and the counts the server returned (added, already there, refused). No values are kept or shown: the server and the web app are where readings are seen.
* **No analytics, no third-party SDK, no network but the person's server.** `NSAppTransportSecurity` keeps the default HTTPS-only rule.

### 4.3 What the server and the web app need (small)

* **Optionally, a QR code for pairing** in Settings → Phone shortcuts, holding the address and the token once. It is drawn on the device by the page, without a vendored library if one fits in a few hundred lines; otherwise vendored and pinned.
* **A way for the app to test a token without sending a reading.** This could be a zero-row body answered with zero counts, or `GET /push/v1/ping` (bearer, counts nothing, rate-limited). Decide it with the build.
* Nothing else. The route, its limits and the same-reading check are the whole server side (note 12 §7).

### 4.4 Build, sign, ship (no Mac)

* **Project.** An Xcode project or Swift Package Manager project under `ios/`. The build runs on GitHub's `macos` runner with the repository's workflow rules: SHA-pinned actions, `permissions: {}` by default, `persist-credentials: false`, and zizmor and actionlint clean.
* **Signing.**
  * The signing certificate and provisioning profile come from the owner's Apple Developer account. They are stored as repository secrets, used only by a `release`-environment job that a person approves.
  * TestFlight upload uses an App Store Connect API key, also a secret.
  * Builds expire after 90 days (I6).
* **Testing.** The owner tests on a real iPhone. CI runs `KidneyHealthCore`'s tests on Linux and the app's unit tests on the macOS runner (simulator).

## 5. Security and safety review (least trust)

| Concern | Answer |
|---|---|
| A lost or shared phone | The token is add-only (note 12), stored for this device only, revoked in Settings, and "Delete what it sent" removes its rows. |
| The app reading more than it needs | Exactly three HealthKit read types; no write access; no glucose, insulin or medicine types (a test). |
| Data at rest on the phone | Only the anchor and the token, in the Keychain. Values are never stored by the app. |
| Supply chain | No third-party Swift packages. The toolchain image is pinned by digest. Signing secrets live only in an approved environment job. |
| Cuffless readings | Left out locally and refused by the server (note 12), with the reason in the status line. |
| Safety rules | No dosing data is read or sent. Treating a low is not affected: the app never touches food or glucose. Every number the app applies comes from the server's vectors. |

## 6. Cost and order

1. **`KidneyHealthCore` and its Linux vector tests**: about 1M tokens. No Apple account is needed, so it can be built at any time.
2. **The app target, built and unit-tested on the macOS runner** (simulator): about 2–3M tokens. No account is needed until signing.
3. **Signing, TestFlight and the owner's phone tests**: the owner's account and time, plus about 1M tokens of workflow and fixes.
4. **(Optional) pairing by QR code** and the test-token route: about 1M tokens.

That totals about 4–6M tokens for option A, below the ROADMAP's 6–10M for the full shell (option B).

## 7. Decisions for the owner

1. **Option A first** (recommended), or the full WKWebView shell (B)?
2. Is building `KidneyHealthCore` and its Linux vector tests now (step 1) fine before there is an Apple account? (Recommended: yes; it also checks the server's rules from a second language.)
3. When to buy the Apple Developer Program membership and add the signing secrets (step 3)?
4. Pairing by QR code, or pasting the token only?
