Status: complete (2026-10-28): steps 1 and 2 and Test connection are merged (#100, #101, #102). Step 3 waits for the owner's Apple account.

# iOS app (design note 15)

## Done

* Step 1 (merged in #100): `ios/KidneyHealthCore` (rules, SHA-256, push checks), `tests/data/push_vectors.json`, the `swift` CI job.
* Step 2 (PR #101):
  * `KidneyHealthCore/Sync.swift`: samples to rows, `Sync.run` (requests of 50, stop at the first non-200, keep the anchor only when
    all were accepted, 401 stops, 429 waits for Retry-After), `Sync.describe` (the status line), `Settings.pushURL/appURL/isDeviceToken`.
    `Push.defaultSince` (three months back, from apple_health_vectors `default_since`). Linux tests: `SyncTests.swift` (34 tests in all).
  * `ios/KidneyHealthSync.xcodeproj` (hand-written, objectVersion 77, folder-synced groups, local package reference, shared scheme).
  * App: `KidneyHealthSyncApp`, `ContentView`, `SyncModel` (rounds of 500, at most 10 rounds a sync, `since` kept in UserDefaults),
    `HealthSource` (anchored query descriptors, observer queries with background delivery, preferred weight unit), `Keychain`
    (this device only), `URLSessionTransport` (ephemeral, no cookies, no redirects).
  * Simulator tests (12): HealthMapping, Transport (URLProtocol stub), Keychain, settings screen. HealthKit refuses to build half a
    blood pressure pair and gives an unsaved sample no source name, so neither is tested there.
  * `tests/test_ios_app.py` (safety set): entitlements, no write usage text, only three read types, no other Health type in the code,
    no third-party packages, HTTPS only, Keychain this-device-only.
  * CI job `ios-app` on macos-15 with Xcode 26.3: `xcodebuild test` on the newest iPhone simulator (`ios/pick_simulator.py`).

* Test connection (after step 2):
  * Server: `GET /push/v1/check` in `app/push.py` (the device token, the shared `push_body` hour, `{"ok": true}`, `no-store`; 405 for
    other methods), in `security.BEARER_PATHS` and `openapi_doc.BEARER_OPERATIONS`. Tests: the check section of `tests/test_push.py`.
  * Package: `PushTransport.get`, `ConnectionCheck.run` and `.text`, `Settings.checkURL`, `Push.checkPath`. Linux test
    `testTestConnectionSaysWhetherTheTokenWorks` (35 tests in all).
  * App: `URLSessionTransport.get`, `SyncModel.testConnection` (a 429 also sets `waitUntil`), the button under the token in
    `ContentView`. Simulator tests: `testTheCheckIsAGetWithTheBearerTokenAndNoBody`, `testTestConnectionSaysWhatTheServerAnswered`.
  * Linux compile check of the app files: the scratch package `appcheck` (stubs for Keychain, HealthSource, Combine); the copy of
    `URLSessionTransport.swift` needs `import FoundationNetworking` there.

## Decisions

* macos-15, not macos-26: actionlint 1.7.12 does not know the macos-26 label yet.
* The app and its tests use Swift 5 language mode (`SWIFT_VERSION = 5.0`) to keep HealthKit's non-Sendable types from blocking the
  build. The package stays Swift 6.
* The token check is its own GET route, because `POST /push/v1/body` refuses a request with no rows. It shares the token's hour so a
  leaked token gains nothing from it. A 200 that is not `{"ok": true}` (an older server's app shell, another site) reads as "not this
  app".
* The Health observers start only once a server and token are saved, so nothing of Health is touched before setup (and the test host
  starts clean).

## Next

* Step 3 waits for the owner: Apple Developer Program, signing secrets, TestFlight, real-phone checks (value text vs the Health export).

## Reproduce

```bash
swift test --package-path ios/KidneyHealthCore
python -m pytest tests/test_ios_app.py tests/test_push_vectors.py tests/test_safety_set.py
```
