Status: complete

# zip-reader progress

Task: build design note 11 (`docs/dev/research/11-reading-a-zip-in-the-browser.md`): `app/static/js/engine/zip.js` (`KH.zip`), the three views taking a `.zip`, tests, walks, docs. Worktree branch: not pushed (the caller integrates).

## Done (and how it was verified)
- `app/static/js/engine/zip.js` (`KH.zip`: supported, open, find, list, stream, text, ZipError, RULES, constants). `python -m pytest tests/test_zip_reader.py -q` (56 tests, ~10 s): the 15 cases of note 11 section 5, the rules, file hygiene. Mutation checks (no size guard, no CRC check, no local name check) each fail the tests.
- `index.html` script tag (after `apple_health.js`, before every view) and `sw.js` SHELL_URLS entry (the cache key is a hash of the static files, nothing to bump).
- The three views: `settings.js` (`textFromZip`), `body_import.js` (`startScan(file, zipped)`, `exportXmlOf`), `lab_fhir.js` (`readZip`, `readEntry`, `readAll`); sheet/card text and `accept` lists in `index.html`.
- Tests: `tests/js/zip_reader.mjs`, `tests/test_zip_reader.py`, `tests/zip_support.py` (archive builder), `tests/js/zip_writer.mjs` (in-memory archives for the page tests); page tests extended: `import_page.mjs` + `test_data_import_ui.py`, `body_import_page.mjs` + `test_body_import_ui.py`, `fhir_labs_page.mjs` + `test_fhir_labs_ui.py`.
- Browser walks in real Chromium (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`): `tools/e2e/import_walk.py` 109 passed, 0 failed; `tools/e2e/body_import.py` 310 passed, 0 failed. (`import_walk.py` had 3 stale expectations from schema step 18: the zip's file list and the "not chosen" sentence; fixed.)
- Docs: ARCHITECTURE.md (new "Reading a .zip in the browser" + the three imports), `docs/body.md`, `docs/privacy.md`, `docs/targets-and-labs.md`, `docs/demo.md`, `docs/maintainers.md`, `docs/ROADMAP.md` (item removed; real-export re-verify added), note 10 pointer, `tools/e2e/README.md`, CHANGELOG (Unreleased), handbook `app/privacy.md` and `app/targets-and-warnings.md`. `python scripts/build_handbook.py --check`: up to date.
- Final checks: `python -m pytest -q` exit 0 (about 5,100 tests, no failure, no skip, no network); `node tests/js/run_vectors.mjs` exit 0; `ruff check .` clean.

## Decisions (and why)
- Cancel reaches the file by hand (`fileStream().cancel`), not only through the pipe chain: Node's DecompressionStream does not pass a cancel upstream.
- Compressed input goes to the inflater in 16 KiB pieces (`pieces()`), so a browser that inflates a whole input chunk before handing any out (1032:1 worst case) holds at most ~16 MiB.
- Lowest local header offset must be 0 (note 7.2 "data before the first entry is damaged"), so an SFX with adjusted offsets is refused too.
- A zip64 field is read only when a classic end-record field is at its maximum (as the note says); disk fields at 0xFFFF defer to the zip64 record.
- Node missing -> the new pytest fails with a message (the repo's pattern `assert shutil.which("node")`), it does not skip.
- A browser without `DecompressionStream` gets the unzip advice before the archive is opened (even for a stored zip).
- Lab clinical records: a `.zip` picked together with other files is refused ("Choose either one .zip or the .json files, not both."); more than 2,000 entries get a zip-specific message (not "choose fewer files").

## Commands
- `python -m pytest tests/test_zip_reader.py tests/test_data_import_ui.py tests/test_body_import_ui.py tests/test_fhir_labs_ui.py -q`
- `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/import_walk.py` and `python tools/e2e/body_import.py`
- `node tests/js/run_vectors.mjs`; `ruff check .`; `python scripts/build_handbook.py --check`
