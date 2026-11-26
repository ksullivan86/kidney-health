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

## Decisions
* Whoop days on the phone with a server: NOT a new change-feed kind (would need a migration, versions twin, read-only kind in
  server_changes.js). Instead the gateway lists `GET /api/activity` (read-only) and `PUT /api/activity/extra`; the phone caches
  the server's answer. Simpler and safe: same route, same user scoping.
* Withings: no official word that a custom URL scheme is accepted as callback; the FAQ forbids localhost and IPs. So both
  companies use one https relay page on the handbook's GitHub Pages site, which forwards ?code&state to the app's scheme.
  Whoop's docs do allow custom schemes (`whoop://example/redirect`), but one way for both is simpler for the person.
* Whoop's docs say the client secret should not be in a mobile app: that is about an app given to many people. Here it is the
  person's own developer app and secret, on their own phone only, in the Keychain. Written in the handbook.

## Next
* mock/devices.js device-mode branch; views/devices.js `#/devices/open/<provider>`; Swift Devices.swift (server page sheet,
  own-app OAuth, fetch); KeysView section; relay page + workflow copy; docs.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
$PY -m pytest -q tests/test_devices_gateway.py tests/test_device_map.py tests/test_ios_app.py tests/test_app_gateway.py
node tests/js/run_vectors.mjs
