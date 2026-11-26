# phone-devices: Withings and Whoop from the iPhone app

Status: in progress (2026-11-26)

## Plan
1. Paired with a server: Settings → Connected devices on the phone shows the server's status, Sync now, Disconnect
   through the gateway; Connect opens the server's own page (`/#/devices/open/<provider>`) in an in-app Safari sheet.
2. No server: the person's own developer app (client ID and secret in Keys and services, Keychain), OAuth with
   ASWebAuthenticationSession through an https relay page on the handbook's Pages site, Swift fetches raw JSON, the page maps
   it with the twin (`js/engine/device_map.js`) and adds rows with twins of `store.add_readings` / `add_activity`.

## Done
* Gateway: `/api/devices` taken out of `NEVER_PREFIXES`; `start` and `callback` are in `NEVER`; ALLOWED gains `GET /api/devices`,
  `POST /api/devices/{provider_id}/sync`, `DELETE /api/devices/{provider_id}`, `GET /api/activity`, `PUT /api/activity/extra`.
  Tests: `tests/test_devices_gateway.py` (passes; also proves Withings rows reach the phone through the change feed with
  source and source_key, and deletes too). `tests/test_app_gateway.py` pin updated (my hunk only).
* Swift allow-list (`ServerAPI.swift`): exact paths per company (no `{provider}` placeholder, so `matches()` is unchanged);
  `DeviceRouteTests.swift`; `tests/test_ios_app.py` list updated.
* Twin `app/static/js/engine/device_map.js` + `tests/data/gen_device_map_vectors.py` + `device_map_vectors.json` + run_vectors
  group "device map" (53 checks pass) + README section + `tests/test_device_map.py`. index.html and sw.js load it.

* Page side (committed): `js/mock/devices.js` device branch (server's via gateway, else the phone's own; twins of
  store.add_readings/add_activity; sync when the app opens/comes back, at most every 10 min), `js/mock/activity.js` (server's
  Whoop days and extra cached in `_activityServer`), `js/views/devices.js` (where text, consent text, `#/devices/open/<p>`).
  `tests/js/phone_devices.mjs` (44 checks) run by `tests/test_phone_devices.py`.
* base.css / settings.js: Connected devices shown in device mode (committed).
* Swift (committed): `Services/Devices.swift` (SFSafariViewController for the server page; ASWebAuthenticationSession
  ephemeral; state 32 random bytes checked in constant time; token exchange/refresh; Withings pages, Whoop 4 collections;
  revoke: Whoop DELETE, Withings signed nonce with CryptoKit), `KidneyHealthCore/DeviceLinks.swift` + `DeviceLinksTests.swift`,
  Keychain items, FoodServices bridge cases, KeysView sections. pytest pins in `tests/test_phone_devices.py`.
* Relay page `handbook/oauth/` (index.html, relay.js, relay.css; CSP meta, no inline script) copied to the Pages site by
  `.github/workflows/handbook-pages.yml` (committed).

* Docs (committed): ARCHITECTURE.md (gateway list, Connected devices "The iPhone app", Device mode bullet), docs/push.md,
  docs/devices.md ("The iPhone app", what to register), handbook weight-and-blood-pressure.md `#devices-iphone` and
  settings-and-keys.md, CHANGELOG Unreleased, note 39 out-of-scope line. (My CHANGELOG commit 3799c8f also carried another agent's
  one-line "handbook is inside the iPhone app" entry, which was in the file at that moment.)
* e2e: `tools/e2e/device_mode.py` `devices_walk` (10 checks pass; run alone with a small driver that builds `--device` and
  calls `devices_walk`).
* Swift cleanups: no tuple optional bindings, helper names that do not clash with locals.

## Waiting to commit (other agents' hunks in the same files)
* `app/static/index.html` (device_map.js script line), `tests/js/run_vectors.mjs` (device map group),
  `tests/test_app_gateway.py` (pin), `tests/test_ios_app.py` (route list + frameworks). Check `git diff <file>`.

## Decisions
* Whoop days on the phone with a server: NOT a new change-feed kind (would need a migration, versions twin, read-only kind in
  server_changes.js). Instead the gateway lists `GET /api/activity` (read-only) and `PUT /api/activity/extra`; the phone caches
  the server's answer. Simpler and safe: same route, same user scoping.
* Withings: no official word that a custom URL scheme is accepted as callback; the FAQ forbids localhost and IPs. So both
  companies use one https relay page on the handbook's GitHub Pages site, which forwards ?code&state to the app's scheme.
  Whoop's docs do allow custom schemes (`whoop://example/redirect`), but one way for both is simpler for the person.
* Whoop's docs say the client secret should not be in a mobile app: that is about an app given to many people. Here it is the
  person's own developer app and secret, on their own phone only, in the Keychain. Written in the handbook.

* Phone's own readings while paired: sent to the server by step 4 like any row (source_key `withings:<grpid>:weight` matches
  the server's own Withings row if it has one, so nothing doubles). Phone's own Whoop days are not sent (no route for them).

## Next
* Docs: handbook connected-devices page, docs/push.md, docs/devices.md, ARCHITECTURE.md, CHANGELOG.md Unreleased.
* Full pytest; e2e only if time allows.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
$PY -m pytest -q tests/test_devices_gateway.py tests/test_device_map.py tests/test_ios_app.py tests/test_app_gateway.py
node tests/js/run_vectors.mjs
