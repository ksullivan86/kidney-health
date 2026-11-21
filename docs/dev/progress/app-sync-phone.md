Status: complete

# app-sync-phone: the phone side of note 38 step 4 (sending to your server)

Role: `app-sync-phone`. Branch: the worktree branch (no push, no PR). Server side: PR #188 (`app/app_sync.py`).

## Plan / state
1. [x] Page module `app/static/js/mock/server_sync.js` (queue, batches, answers), loaded after `mock/device.js` (index.html, sw.js).
   Verified by `node tests/js/server_sync.mjs` (72 checks).
2. [x] Swift: `ios/KidneyHealth/Services/ServerSync.swift`, bridge kinds in `FoodServices.answer`, `Settings.syncURL` in Core (+ an
   XCTest), the pairing question and the "Your server" footer name the iPhone app token. Static checks in `tests/test_ios_app.py`.
   Swift is not compiled here (no toolchain): CI's macOS job builds it.
3. [x] Settings → This device: "Sending to your server" (`serverSyncBlock` in `views/settings.js`).
4. [x] Tests: `tests/js/server_sync.mjs`, `tests/test_server_sync_phone.py` (runs it, and posts the page's body to the real route),
   `tests/test_ios_app.py`, `tools/e2e/device_mode.py` (Send now with a stub bridge; 44 PASS).
5. [x] Docs: ARCHITECTURE "Device mode" (+ file ownership row), docs/push.md ("What the app does", contributors), handbook
   install and weight-and-blood-pressure pages, CHANGELOG Unreleased, note 38 status and §5.5.
6. [x] Final run: node server_sync (75), device_mode (44), run_vectors; 894 pytest in the related files; e2e 44 PASS; ruff clean.

## Left for later
* Swift is not compiled here (no toolchain); CI's macOS job builds and runs the XCTests (`testTheSyncURLIsTheSameServersPushV1Sync`,
  the changed pairing sentence in `SettingsScreenTests`).
* Restoring from the safety copy loses the sent marks; rows are sent again and the server finds them by client_id (entries),
  created_at (labs, symptoms), the Health key or same time (weights, readings) or same content (foods). A hand-typed weight or
  reading with no time could be added twice.
* Stuck and refused rows have no "try again" button.

## Decisions (and why)
* **USDA and Open Food Facts foods go in `foods`** (source usda/off with fdc_id/gtin) and the entry names them by client_id, as
  docs/push.md recommends, instead of the `usda`/`off` FoodRef forms: the server then never skips them (it keeps the phone's copy
  when it lacks the shared row). Built-in foods use `{builtin: {fdc_id, name}}` (name only when no fdc_id).
* **Skipped rows are not named by the server** (counts only). Per list, sent − (added + already there) = skipped. Only rows that
  can be skipped are suspects (entries with a built-in food; symptoms, weights, readings). When the count cannot say which, the
  suspects get `g` (a group size, halved each time) and are sent again alone in smaller groups until it can (resending a row that
  was added is "already there"). A row skipped alone 3 times is `stuck`.
* **Client IDs**: entries keep their own `client_id` (written onto the row, so the export/safety copy carries it); other kinds
  get one in `_serverSync.rows[kind][rowId].c`. The log is saved before a row with a new ID is sent.
* **A planned entry waits until its day is over**, so marking it eaten before then is what gets sent (edits are never sent).
* **Another server host** resets the sent marks (everything goes there too); the server's receipts and created_at checks keep
  repeats from adding twice.
* **When**: 10 s after a save (persist's subscribe), 1 s after the page becomes visible, at start (boot's save status). Only
  when paired (`serverInfo`) and the token check (`GET /push/v1/sync`, cached a day) passed. After a 401, automatic runs check
  again at most once an hour; Send now checks at once. After an unexpected answer, a 5 minute pause.
* A run that reaches 10 requests schedules the rest a minute later.
* No change to `KidneyHealthApp.swift`, `WebShell/*` or `main.js` (the main session edits them): all triggers are in the page.
* Timer `unref()` when present (Node), so the test pages exit promptly.

## Commands
```
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
node tests/js/server_sync.mjs; node tests/js/device_mode.mjs; node tests/js/run_vectors.mjs
$PY -m pytest -q -p no:cacheprovider -o addopts="" tests/test_server_sync_phone.py tests/test_ios_app.py tests/test_app_sync.py \
  tests/test_settings_ui.py tests/test_device_mode.py tests/test_frontend_shell.py tests/test_pwa_routes.py tests/test_meta.py
$PY tools/e2e/device_mode.py --out <scratch>/e2e-device
ruff check .
```
