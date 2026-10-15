Status: complete (started 12:42 UTC, finished about 14:05 UTC; deadline was 15:05)

# demo-local: "Keep my data in this browser" demo mode

Base: origin/claude/adoring-sagan-th5swr, merged twice: first 6a2d12f (offline edits), then 50c05e9 (#47 offline edits, #48 privacy tier 3, #49 C-CDA import). Paths I own: `app/static/js/mock/persist.js`,
`mock/export.js`, `mock/import.js`, `views/demo_local.js`, `css/demo-local.css`, banner markup in `index.html`,
`tests/data/gen_import_vectors.py` + `import_vectors.json`, `tests/test_demo_local*.py`, `tests/js/demo_local*.mjs`,
`tools/e2e/demo_local.py`, docs.

Rules from the coordinator: regexes that look for HTML tags in Python tests are case-insensitive (re.IGNORECASE); never test a
host name with `in`, compare exact sets with `==`. Re-fetch and merge origin/claude/adoring-sagan-th5swr before reporting.

## Plan
1. Storage layer (mock/persist.js): IndexedDB wrapper (injectable), snapshot/restore of the whole MockApi, debounced save after
   each successful write, version field, newer version never loaded or overwritten.
2. Export (mock/export.js): GET /api/me/export.json in the server's export.json shape.
3. Import twin (mock/import.js): POST /api/me/import, same refusals as app/data_import.py; vectors in tests/data.
4. UI: banner button, opt-in sheet, manage sheet, settings export/import enabled in the mode.
5. Tests (static UI, node storage with fake IDB, vectors, e2e harness), docs.

## Done
- 12:58 Storage layer `mock/persist.js` (KH.mock.local: boot/probe/enable/disable/flush, rev check for two tabs, newer/unreadable copy
  blocked, only in the demo build = KH.flags.PREVIEW), `MockApi({seed:false})`, `KH.mock.onWrite` hook in `mock/core.js` request().
  Verified: `node tests/js/demo_local_storage.mjs` (fake IndexedDB in tests/js/fake_idb.mjs, 70 checks).
- Export `mock/export.js`: GET /api/me/export.json (server's key order). Checked in the same script and by tests/test_demo_local_storage.py.
- UI: banner button + `<dialog id="sheet-demo-local">` in index.html, `views/demo_local.js`, `css/demo-local.css`, main.js boot hook,
  Settings -> Your data export/import enabled while the mode is on (+ a "Keep my data in this browser" button there for when the banner was
  dismissed), offline.js offlineNow() false while the mode is on, sw.js shell list.
- 13:08 Import twin `mock/import.js` + `tests/data/gen_import_vectors.py` / `import_vectors.json` (240 requests, 246 checks, replayed in
  `node tests/js/run_vectors.mjs` section "import"), `tests/test_import_vectors.py`, `tests/test_demo_local_ui.py`, `tests/test_demo_local_storage.py`.
  FOUND AND FIXED a server bug: the import refused `fdc_id < 1` but the built-in glucose tablets (and gel, shots, salt substitutes) have negative
  curated ids, so an export of a log that used them could not be imported (`FdcId` in app/data_import.py, regression test in
  tests/test_data_import.py on the real foods list).
- 13:20 e2e `tools/e2e/demo_local.py` (static server, no kidney server): 90 checks pass (keep x2 configs, export, stop, import, tabs, private, newer).
  `tools/e2e/sandbox.py --only top-phone-light-none`: no console/CSP error; 8 low tap-target issues, all the pre-existing symptoms "Add" button (36 px).
- 13:25 Docs: docs/demo.md (new), ROADMAP (done), CHANGELOG (Unreleased x3 places), ARCHITECTURE (new section at the end + ownership row),
  docs/privacy.md, docs/README.md, README.md, handbook self-hosting pages, scripts/build_preview.py docstring, tools/e2e/README.md.

- 13:40 `tools/e2e/parity.py` section 15 (demo export.json vs the server's export.zip after the other sections): 20 checks, 4160 leaf comparisons, 0 failed
  (`python tools/e2e/parity.py --sections 4,5,9,11,12,13,15`).
- Hardening: no spread of long arrays in the import's depth walk; disable() waits for a running save and blocks new ones.

## Verification (all with no network)
- `node tests/js/run_vectors.mjs` (import vectors: 248 checks; others unchanged), `node tests/js/demo_local_storage.mjs` (70 checks).
- `python tools/e2e/demo_local.py` (90 checks, 3 full runs in a row after making its waits null-safe); `python tools/e2e/parity.py --sections 4,5,9,11,12,13,15`
  (section 15: demo export.json vs the server's, 20 checks, 4160 leaf comparisons); `sandbox.py --only top-phone-light-none` (no console/CSP error; 8 low
  tap-target notes about the symptoms Add button, not this change); `regress.py --only 375-light` (131 passed); `device.py --only changes` and
  `--only demo,outbox` pass (`--only demo,outbox,changes` together fails 5 checks of the offline-edits section on the base commit too).
- A throw-away differential fuzz against the real server (not committed): 5,000 random mutations of the import vectors' file as dry runs and two
  sequences of about 7,000 real imports with merge (answers, then the final export and seven read-back views): 0 mismatches after the fixes.
- Full suite in 4 parallel shards (`timeout 900 python -m pytest -q -x -p no:cacheprovider <files>`): all exit 0.

## Left (not done, on purpose)
- The demo gives `export.json` only (no zip with CSV files); the import page does not take the zip (neither does the server's page).
- A saved copy keeps the built-in foods it was made with (docs/demo.md says how to refresh).

## Decisions
- Mode is gated on `KH.flags.PREVIEW` (the Pages/preview build), not on `?mock=1`: a development server's mock page never stores.
- IndexedDB is the only source of truth (no localStorage hint): boot() looks for a copy without creating a database (aborted upgrade).
- Turning on offers "empty log of my own" (default; reloads the page from the stored empty copy) or "sample data as it is now".
- Stop deletes the database and reloads: the sample demo starts again (the confirm says so).
- A save is one transaction that checks the stored `rev`; a second tab that saved first makes this page stop saving and say so.
- Export is `GET /api/me/export.json` (mock-only route; the server's is a zip); download name `export.json`.

## Reproduce
- `node tests/js/run_vectors.mjs`
- `python -m pytest -q -p no:cacheprovider tests/test_demo_local*.py`
