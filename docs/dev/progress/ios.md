Status: step 1 complete (2026-10-28). Step 2 (the app target on the macOS runner) not started.

# iOS app (design note 15)

## Done

* `ios/KidneyHealthCore`, a Swift package (tools 6.0, no dependencies, no HealthKit):
  * `Body.swift`: ranges, per-day limits, `halfUp`/`roundKg`/`lbToKg`, `context`, `isWatchSource`, `isPlausible`, `batches`, `readTypes`.
  * `SHA256.swift`: plain SHA-256 (CryptoKit is not on Linux).
  * `Push.swift`: `at(instant, zone)`, `moment(at)` (the route's `parse_at`), `valueText`, `cleanSource`, `wholeMmHg`, `plan(row)` in the
    route's check order, `plan(weights:readings:today:)` into requests of at most 50 rows, `encode`.
* `tests/data/gen_push_vectors.py` writes `tests/data/push_vectors.json` from `app/push.py`; `tests/test_push_vectors.py` keeps it current.
* Swift tests (23): replay body, apple_health and push vectors; plan tests; the read-types safety test.
* CI job `swift` in `ci.yml`: the swift.org 6.4.1 tarball, pinned by SHA-256 (its `.sig` checked against the Swift 6.x release key
  when the hash was taken), then `swift test`.
* Docs: `ios/README.md`, `tests/data/README.md` (push_vectors section), ARCHITECTURE (push section), CONTRIBUTING, note 15 status,
  ROADMAP "Next", CHANGELOG Unreleased.

## Decisions

* The toolchain is a pinned tarball, not a Docker image: Docker Hub answered 429 here, and the repository already pins downloaded tools by hash.
* The app sends `value` as text (`valueText`): the same text the route would build from the JSON number, so the key is the same either way.
* Blood pressure numbers are rounded half up to whole numbers (`wholeMmHg`), as the Health export import does.
* Per-day limits are left to the server: they count rows already stored.

## Next (step 2)

* The app target under `ios/` on the `macos` runner (simulator tests), using this package. Settings (server address, token in the Keychain),
  permissions (exactly `Body.readTypes`), sync (observer and anchored queries, anchor saved only after a 200, 401 stops, 429 waits).
* Decide the token check (note 15 §4.3): a zero-row body is a 400 today ("Send at least one weight or reading."), so a check needs
  `GET /push/v1/ping` or a change to the route.
* Re-verify on a real iPhone that the value text HealthKit gives matches what the Health export writes, so the keys agree.

## Reproduce

```bash
python3 tests/data/gen_push_vectors.py --check
python -m pytest tests/test_push_vectors.py tests/test_push.py tests/test_deploy.py
swift test --package-path ios/KidneyHealthCore    # Swift 6.4.1
```
