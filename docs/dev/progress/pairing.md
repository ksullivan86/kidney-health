Status: complete (2026-10-29): merged in #108; the macOS CI job built the app and ran its simulator tests.

# Pairing the iPhone app by QR code (design note 15 §4.3)

## Done

* `app/pairing.py`: `link(server, token)` and the reference `parse(text)`. `brand.PAIRING_SCHEME = "kidneyhealthsync"` (pinned in
  `tests/test_brand.py`).
* `POST /api/me/tokens` (device family) answers `pair_url`, from `public_base`; `null` unless `https://` and a plain host.
  `docs/api/openapi.json` regenerated with the locked deps (the docstring changed).
* Vectors: `tests/data/gen_pairing_vectors.py` → `pairing_vectors.json` (43 link cases, 58 parse cases, 50 refused); README section.
* Swift: `KidneyHealthCore/Pairing.swift`, `PairingVectorTests.swift`. Verified locally with the pinned Swift 6.4.1 Linux toolchain
  (all 39 package tests pass).
* App: `ios/KidneyHealthSync-Info.plist` (URL type), `INFOPLIST_FILE` in the app target's two configs, `.onOpenURL` and the
  "Pair with …?" alert in `ContentView.swift`, `pairingQuestion` and `notAPairingLink` in `SyncModel.swift`, a simulator test in
  `SettingsScreenTests.swift`. Not compiled here (no Xcode): the macOS CI job builds and tests it.
* Web: `pushPairBox` in `settings.js` (QR from `KH.twoStep.qrSvg`, now exported with a label), CSS, `tests/js/push_page.mjs` cases.
* Tests: `tests/test_pairing.py`, pairing checks in `tests/test_push_ui.py` and `tests/test_ios_app.py`. Chromium: `tools/e2e/push.py`
  checks the box on a plain-http server and draws a pairing link with the vendored module (101/101; one earlier run had a timing miss
  in the Trends table read, which passed on rerun and on main).
* Docs: ARCHITECTURE (file map, feature row, "Pairing the iPhone app"), `docs/push.md`, `ios/README.md`, note 15 (§4.2, §4.3, §6,
  §7), CHANGELOG, handbook weight-and-blood-pressure.

## Decisions

* Link scheme, not an in-app scanner: no camera code or permission. Universal links need a fixed domain, which a self-hosted app
  does not have. Scheme hijacking risk is written down: the token is add-only and revocable.
* The app takes a link only in the exact form the server makes; both sides check the same rules.

## Reproduce

```bash
python3 tests/data/gen_pairing_vectors.py --check
python -m pytest tests/test_pairing.py tests/test_push_ui.py tests/test_ios_app.py tests/test_brand.py tests/test_vectors_readme.py
swift test --package-path ios/KidneyHealthCore
```
