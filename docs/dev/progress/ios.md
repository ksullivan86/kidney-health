Status: step 2 in progress (2026-10-28): code written, the macOS CI job is being brought to green on draft PR #101.

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
  * Simulator tests: HealthMapping, Transport (URLProtocol stub), Keychain, settings screen.
  * `tests/test_ios_app.py` (safety set): entitlements, no write usage text, only three read types, no other Health type in the code,
    no third-party packages, HTTPS only, Keychain this-device-only.
  * CI job `ios-app` on macos-15 with Xcode 26.3: `xcodebuild test` on the newest iPhone simulator (`ios/pick_simulator.py`).

## Decisions

* macos-15, not macos-26: actionlint 1.7.12 does not know the macos-26 label yet.
* The app and its tests use Swift 5 language mode (`SWIFT_VERSION = 5.0`) to keep HealthKit's non-Sendable types from blocking the
  build. The package stays Swift 6.
* No token check route yet (note 15 §4.3): a wrong token shows on the first sync.

## Next

* Get `ios-app` green; fill in the PR body; mark ready; merge (the owner asked to merge when green).
* Step 3 waits for the owner: Apple Developer Program, signing secrets, TestFlight, real-phone checks (value text vs the Health export).

## Reproduce

```bash
swift test --package-path ios/KidneyHealthCore
python -m pytest tests/test_ios_app.py tests/test_push_vectors.py tests/test_safety_set.py
```
