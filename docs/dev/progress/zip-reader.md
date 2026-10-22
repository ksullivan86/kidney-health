Status: in progress

# zip-reader progress

Task: build design note 11 (`docs/dev/research/11-reading-a-zip-in-the-browser.md`): `app/static/js/engine/zip.js` (`KH.zip`), the three views taking a `.zip`, tests, walks, docs. Worktree branch: do NOT push (the caller integrates).

## Done
- Step 0: fast-forwarded the worktree to a300da6.
- `app/static/js/engine/zip.js` (KH.zip: supported, open, find, list, stream, text, ZipError, RULES, constants). Verified by `python -m pytest tests/test_zip_reader.py -q` (56 tests, ~10 s): note cases 1-15 + rules + file hygiene.
- `index.html` script tag (after apple_health.js, before every view) and `sw.js` SHELL_URLS entry (the cache key is a hash of the static files, nothing to bump).
- `tests/js/zip_reader.mjs` (observes only; `--large` for case 8 and abort) + `tests/test_zip_reader.py` (builds every archive in tmp_path; hand-written byte builder `build()`).

## In progress
- (nothing yet) next: the three views.

## Next
1. settings.js importBlock (.zip path, accept list, label, paragraph, messages), tests/js/import_page.mjs + tests/test_data_import_ui.py
2. body_import.js (+ index.html sheet text/accept), tests/js/body_import_page.mjs + tests/test_body_import_ui.py
3. lab_fhir.js (+ index.html card text/accept), tests/js/fhir_labs_page.mjs + tests/test_fhir_labs_ui.py
4. browser walks: tools/e2e/import_walk.py, tools/e2e/body_import.py (+ tests/test_e2e_tools.py if it pins step names)
5. docs: ARCHITECTURE.md, handbook pages, docs/*.md, ROADMAP, CHANGELOG; handbook build check
6. full pytest, node tests/js/run_vectors.mjs, ruff check .

## Decisions (and why)
- Cancel reaches the file by hand (`fileStream().cancel`), not only through the pipe chain: Node's DecompressionStream does not pass a cancel upstream, and Chromium/Safari behaviour was not to be relied on.
- Compressed input goes to the inflater in 16 KiB pieces (`pieces()`): a browser that inflates a whole input chunk before handing any out (1032:1 worst case) then holds at most ~16 MiB.
- Lowest local header offset must be 0 (note 7.2 "data before the first entry is damaged"), so an SFX whose offsets were adjusted is refused too.
- A zip64 field is read only when a classic end-record field is at its maximum (as the note says); disk fields at 0xFFFF defer to the zip64 record.
- Node missing -> the new pytest fails with a message (the repo's pattern: `assert shutil.which("node")`), not skip.

## Commands
- `python -m pytest tests/test_zip_reader.py -q`
- `node tests/js/zip_reader.mjs <folder>` (folder of archives made by the pytest file)
