Status: in progress

# note39-twins: the demo's twins of note 39's server rules, and step 9 on the phone

Branch: `worktree-agent-af1bb2a8826027962`, fast-forwarded to `local/note39-server` (de8672e) at the start, because the worktree
began at main (b7c6b6b) without the gateway or the change feed.

Avoid (another helper's): `app/static/js/mock/server_sync.js`, `ios/KidneyHealth/Services/ServerSync.swift`, `app/sync_feed.py`.

## Findings at the start

* The offline outbox (`js/offline.js`) queues only food log entries (POST /api/log, /quick, mark-eaten, PUT/DELETE of an entry).
  Foods, saved meals, symptoms, weights, readings and labs are not queued: offline they fail with "Cannot reach the server". So
  the outbox needs no change for these kinds.
* The demo's import (`js/mock/import.js`) refused `client_id` on foods, meals, labs, symptoms, weights and readings, which the
  server's export now writes: a server export could not be imported into the demo or the phone. Fixed with part 1.
* In device mode with no server, the demo routes of `js/mock/lists.js` answered as if Instacart and recipe pages were on (a fake
  Instacart link, the sample recipe page). Step 9 makes them off there unless the paired server offers them both ways.

## Plan

1. Mock twins: versions in 412 bodies, If-Match on PUT/DELETE of foods, meals, symptoms, weights, readings and DELETE of labs; a
   `client_id` for every new row (entries too, as the server's trigger does); export and import carry it.
2. Vectors: `tests/data/gen_row_version_vectors.py` gets a request `script` run against the server and the demo.
3. Gateway: recipe import (GET, POST /page), Instacart (GET, preview, send), list sync (GET, preview, send) on ALLOWED, pinned.
4. Phone: Swift allow-list, the page's device-mode routes through `serverApi`, tests.
5. Docs: ARCHITECTURE, docs/push.md, handbook, CHANGELOG, note 39 status.

## Done

1. **Mock twins** (checkpoint 1). `js/mock/core.js`: `newClientId`, `withVersion`, `checkIfMatch` (the twin of
   `row_versions.check_if_match`, same 412 detail and `current`), `_fillClientIds` (schema step 38's `_fill_ids` for a stored log,
   keeping the ID the phone's queue sent a row with); `persist.js` calls it after reading a log back. foods, meals, symptoms,
   body, labs: If-Match in the same place as the server (after the 404 and the 409s, before the day limits and the meal's foods);
   a food's and a saved meal's 412 `current` holds `client_id`, as the server's row does. Every new row gets a `client_id`
   (entries too: the server's trigger gives one; a shared or built-in food none). Export carries `client_id` for every kind (and
   no longer writes `added_by` on entries, which the server's file never had and the demo's own import refused); import accepts
   and keeps it when free (`free_id`). Verified: `node tests/js/run_vectors.mjs` (all pass), `node tests/js/row_ids_demo.mjs`
   (50 checks), every pytest file that runs node (pass).
2. **Vectors**: `gen_row_version_vectors.py` has a 40-request `script` (every kind's PUT/DELETE with If-Match, 412, 400 before
   412, 404); `run_vectors.mjs` replays it on a fresh demo account. `tests/test_row_versions.py` pins its coverage and runs
   `row_ids_demo.mjs`.
3. **Gateway**: `ALLOWED` gains GET /api/recipe-import, POST /page, GET /api/instacart, POST /preview, /send, GET /api/list-sync,
   POST /preview, /send. Never the list app's PUT, DELETE or /test, nor /recipe-import/text (the phone parses pasted text itself).
   `tests/test_app_gateway.py`: the pin, and three tests (recipe page through the checked transport, token not sent to the site,
   private address blocked, off is 404; Instacart only the token owner's plan; list app set up only in the web app, key never
   shown, only the owner's list). Verified: `pytest tests/test_app_gateway.py` (41 pass), ruff clean.
4. **Phone** (checkpoint 2). `ServerAPI.swift` carries the eight routes (tests in `ServerAPITests.swift`, pinned by
   `tests/test_ios_app.py`, which now also checks every carried route is on the server's `ALLOWED`). `server_api.js` reads
   `services.recipe_import/instacart/list_sync` from `about`. `lists.js` in device mode: off without a both-ways server (no more
   demo stand-ins on the phone: before, Instacart showed a fake link and a recipe link gave the sample page); through the gateway
   when offered; a page's lines re-matched with the phone's foods; the server's food ids shown as the phone's (by name) and mapped
   back on send; list app set-up 404 on the phone. `views/instacart.js`: the demo text only when `MOCK && !DEVICE`. Tests:
   `tests/js/server_lists.mjs` (63 checks) run by `tests/test_server_services_phone.py`. Swift not compiled (no Xcode here).
5. **Docs**: ARCHITECTURE (the gateway list, "The demo's twins" under the change feed, device mode step 9 and its tests),
   `docs/push.md` (the list table, the services' switches, the page's twins), `docs/privacy.md`, the handbook
   (`app/install.md`, "With a token both ways"), CHANGELOG Unreleased (Added and Fixed), note 39 (status and "as built").

## For the helper on steps 6 and 7 (server_sync.js)

* Every row in the page now has `row.client_id` (entries before too). `server_sync.js` still keeps its own `c` for non-entry rows;
  for a row it has not sent yet it could use `row.client_id` instead of a new UUID, so the phone, the export and the server share
  one ID. `_fillClientIds` already prefers the queue's `c` for rows the queue knows, so existing phones line up.
* Instacart and the list app read the server's Plan: plans made on the phone reach it only when step 7 sends planned entries.

## Commands

    PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
    node tests/js/run_vectors.mjs
    $PY -m pytest -q tests/test_row_versions.py tests/test_app_gateway.py tests/test_ios_app.py
