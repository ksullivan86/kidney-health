Status: complete (code, tests, docs and handbook done; full suite and `node tests/js/run_vectors.mjs` green; not walked in a real browser)

# Import of `export.json` (`POST /api/me/import`)

Role: `import`. Worktree branch `worktree-agent-adc19798867a9f2f2`. Spec: note 07 §4.14 and §6 "Later (v0.4)"; ROADMAP item
"Import of `export.json` into another instance" (removed from the ROADMAP; the contract is ARCHITECTURE.md "Import of `export.json`").

## Done (and how it was checked)

* `app/data_import.py`: strict models (`extra="forbid"`, strict types, bounded lists and strings, the API's own limits and
  validators), `parse_export`, the `Importer` (foods first, then entries, saved meals, labs, "Not for me", profile and
  settings), `run_import`/`handle`, and the route `POST /api/me/import?dry_run=&merge=&replace_profile=`.
  The dry run does the real work inside the transaction and rolls it back, so its answer equals the real import's.
* `MAX_IMPORT_BYTES` (16 MiB) registered for exactly `/api/me/import` (`app/config.py`, `register_body_limit`). Measured: a year at
  8 entries a day is 3.5 MB pretty-printed, 2.2 MB minified (the default 1 MiB is passed after about 100 days); a 15.3 MB file with
  13,000 entries imports in 1.5 s with about 90 MB of extra memory (containers are limited to 512 MB).
* Exporter (`app/account.py`) now also writes `builtin_foods` (`[{id, name, fdc_id}]` of the built-in foods the person uses) and
  `linked_foods[].gtin` / `.food` (the whole record), because the v0.3 file could not say which built-in food an id was nor
  carry a shared food's data. Additions to version 1; files without them still import (id + name for built-ins; a shared
  food the server lacks is skipped and reported).
* Small shared helpers: `insert_entry` / `insert_template` take optional `created_at` / `updated_at`; `profile.apply_profile_changes`
  (extracted from `PUT /api/profile`, `replace_targets`); audit action `data.imported` (user visible); rate limit `import` (20/hour).
* UI: Settings -> Account -> Your data -> "Import from a file" (`js/views/settings.js`, `css/settings.css`); the demo explains.
* Tests: `tests/test_data_import.py` (57), `tests/test_data_import_ui.py` + `tests/js/import_page.mjs` (the block run against a
  fake page), `test_export_delete.py` key set, `test_auth_coverage.py` route walk, `test_isolation_v03.py` matrix.
  Reproduce: `python -m pytest tests/test_data_import.py tests/test_data_import_ui.py tests/test_export_delete.py tests/test_auth_coverage.py tests/test_isolation_v03.py -q`
  Full: `python -m pytest -q -x -p no:cacheprovider > /tmp/import-full.txt 2>&1; echo $?` (0) and `node tests/js/run_vectors.mjs` (0).
* Docs: ARCHITECTURE.md (route contract, export shape, layout), docs/privacy.md, handbook `app/privacy.md` ("Move to another
  server") and `reports-for-your-team.md`, CHANGELOG.md, docs/ROADMAP.md, docs/security.md, docs/deployment.md, docs/accounts.md,
  README.md, note 07 §4.14 (status line).

## Decisions (and why)

* Nutrient numbers of an entry are recomputed from its food and servings (never taken from the file): every number stays traceable
  to a food row, and an imported entry is what the API would have made. Its `food_name` is the food's name now.
* Profile, targets, guidance preferences and three display settings are replaced only with `replace_profile=1` (default off): they are
  clinical settings the person may have agreed with their care team on this server. Consents (`food.off_consent`, `ai`) are never imported.
* Account with entries / own foods / saved meals / labs: refused (409; the dry run answers 200 `can_import:false`) unless `merge=1`.
  With `merge=1`, count-based duplicate skipping (entry: date, meal, food, servings, grams, status, created time; own food: name,
  brand, serving, values, flags; meal: name + foods; lab: test, date, shown value).
* A shared USDA/OFF food the server lacks is kept as the person's own copy (like `POST /api/foods/{id}/copy`), never created as a shared row from a file.
* A saved meal that loses a food keeps the rest and says so in its note (totals must not read as complete).
* Dry run and import both need the recent password (`RecentUser`); the UI uses the existing re-auth sheet through `request()`.
* The page takes `export.json`, not the `.zip` (it says so); reading the zip is on the ROADMAP.
* The sections the import never reads are not even sent by the page; the server accepts and ignores them if they are sent.

## Left undone

* No Playwright step in `tools/e2e/journey.py` (Playwright is not installed where this was built); walk Settings -> Your data once by hand.
* Choosing the `.zip` directly (ROADMAP).
