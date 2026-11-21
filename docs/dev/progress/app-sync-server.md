Status: in progress

# app-sync-server: the server side of note 38 step 4 ("sending to a server")

Role: `app-sync-server`. Branch: the worktree branch `worktree-agent-a9fdde3cc5cf597a1`. Do not push, no PR.

## Decisions (and why)

* **A new scope on device tokens, `app:add`, not a new token kind.** It reuses the device family whole: the `khd_` prefix,
  the `push.enabled` switch (env `PUSH_ENABLED`), the 5-token cap, expiry, revocation, pairing by QR code and "Delete what it
  sent". The person chooses it when making the token (`POST /api/me/tokens` with `family: "device"`, `kind: "app"`).
  An app token stores `body:write app:add`, so the iPhone app can keep sending Health readings to `/push/v1/body` with the
  same token. A shortcut token (`kind: "shortcut"`, the default) is exactly as before: `body:write` only.
* **One route, `POST /push/v1/sync`**, bearer-only like `/push/v1/body`; `GET /push/v1/sync` tests that the token may use it.
* **Rows are checked by the normal create models** (`FoodCreate`, `LogCreate`, `LabCreate`, `SymptomCreate`, `WeightCreate`,
  `BloodPressureCreate`), so limits and refusal texts are the same. A bad row is a 400 that names it; nothing is stored.
* **A receipts table, `app_sync_rows` (schema step 37)**: `(user_id, kind, client_id)` unique, with the token, the row it
  made or matched, and whether it added it. It gives "send twice, add nothing" even after the row was deleted on the server,
  matches custom foods by client ID, and is what "Delete what it sent" reads. All six tables use AUTOINCREMENT, so a row id
  in a receipt is never reused for another row.
* **Foods reuse the import's matching** (`app/data_import.py`): the shared-row match (USDA by `fdc_id`, Open Food Facts by
  barcode, with the serving weight agreeing) and the built-in match (by `fdc_id`, or by name when it has none) are now
  module functions the importer and the sync both call. A shared food this server lacks is kept as the person's own copy,
  as the import does. A shared row is never created from the phone.
* **Rows that depend on what the server holds are skipped, not refused**: a full day (symptoms, weights, readings), or a food
  this server cannot find. They are counted under `skipped` and get no receipt, so sending again tries again.
* **Weights and readings** are stored like `/push/v1/body` rows: `source = 'shortcut'`, `api_token_id` = the token, so the
  body screens say "from a shortcut (token name)" and the existing delete covers them.
* **Not exported**: `app_sync_rows` is server-local (like `api_tokens` and `api_token_id`). Deleting the account cascades.
* **No new setting**: `push.enabled` switches it.

## Plan / state

1. [x] Token scope `app:add` (`app/auth/api_tokens.py`, `app/auth/schemas.py` `kind`).
2. [x] Migration step 37 `app/migrations/m037_app_sync.py` + `tests/test_migration_m037.py` (3 pass).
3. [x] `app/app_sync.py`: the route; `shared_match`, `builtin_match`, `food_key`, `own_food_key` are now module functions in
   `app/data_import.py` (the importer calls them).
4. [x] "Delete what it sent" for all kinds (`app/push.py` + `app_sync.delete_sent`), `sent` counts (`api_tokens.sent_counts`).
5. [x] `security.BEARER_PATHS`, `openapi_doc`, `docs/api/openapi.json` regenerated (`scripts/gen_openapi.py`).
6. [x] Settings → Phone shortcuts: "What it is for" select, the app sentence, counts in words, app delete words, activity label
   `app.rows_added` (audit action, user-visible). `tests/test_push_ui.py` + `tests/js/push_page.mjs` (31 pass).
7. [x] `tests/test_app_sync.py` (55 pass), isolation matrix entry `app_sync_rows`.
8. [x] Docs: `docs/push.md` ("Sending from the iPhone app"), ARCHITECTURE (route tables, step 37 row, file ownership, the family
   table, a new subsection "`POST /push/v1/sync`", screens, security review), CHANGELOG (Unreleased: Added + Upgrading), note 38
   status and §5.5, handbook (weight-and-blood-pressure "Connect the Kidney Health iPhone app", configuration `PUSH_ENABLED`),
   `deploy/caddy/Caddyfile.example` (the bridge name passes `/push/v1/sync`). The `push.enabled` help text names the app token;
   `js/engine/settings.js` and `tests/data/settings_vectors.json` follow (`node tests/js/run_vectors.mjs` passes).
9. [ ] Run the related suites (122 files: names with token/push/isolation/migration/account/import/settings/brand/export/auth/
   security/openapi/device/body/research/deploy/meta, plus files that mention khd_, /push/v1, api_tokens, data_import,
   settings_registry), ruff; final commit.

Tests fixed for the new shape: `tests/test_device_tokens.py` (DEVICE_SCOPES), `tests/test_openapi_snapshot.py` (15 stubs, 4 device
operations), `tests/test_auth_coverage.py` (SYNC_ROUTES + a new test), `tests/test_push_ui.py` (the create call has `...forApp`).

## Commands

```
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
$PY -m pytest -q -p no:cacheprovider -o addopts="" tests/test_app_sync.py
```
