# body-part-c2 — the Apple Health weights and blood pressure import sheet

Status: in progress (code, tests, harness, handbook and docs written; running the full checks)

Branch: worktree-agent-accbb476ac892ccf6 (local commits only; never push, no PR). Base: d52f4fe (fast-forwarded).

## Done (and how it was checked)
- Step 0: `git merge --ff-only d52f4fe` ok; app/body.py and engine/apple_health.js exist.
- `app/static/js/views/body_import.js` (KH.bodyImport.open, trimDays), the sheet `#sheet-body-import` in index.html, the engine and view script tags,
  sw.js entries, css block at the end of css/sheets.css (no new CSS file). `pytest tests/test_frontend_shell.py` passes.
- `tests/js/body_import_page.mjs` + `tests/test_body_import_ui.py` (32 tests pass).
- `tools/e2e/body_import.py` (port 8087): 4 server passes + 2 demo passes, 250 checks pass.
- Reader header comment: the `<!DOCTYPE ` line reworded (it tripped tests/test_preview_build.py once index.html lists the reader); the
  reader's own preview test rewritten in tests/test_apple_health.py (index.html lists the module now).
- Handbook: section "Weights and blood pressure from the Health app" in handbook/docs/app/targets-and-warnings.md (no F4 sentence on purpose,
  see decisions). venv-hb is in the scratchpad (not in the repo): build_handbook --check ok, test_handbook_content 587 passed, mkdocs --strict ok,
  check_links 0 broken. REMOVE handbook/site before parity.py.
- Docs: ARCHITECTURE (section + module map), docs/body.md, CHANGELOG (two bullets), tools/e2e/README.md, tests/test_e2e_tools.py,
  docs/maintainers.md.

## Next steps
1. Full `python -m pytest -q`, `node tests/js/run_vectors.mjs`, `ruff check .`
2. Harnesses one at a time: body_import.py (twice), parity.py (rm -rf handbook/site first), regress.py --no-pytest, sandbox.py, demo_local.py, device.py
3. Delete this file in the last commit; report.

## Decisions
- Sheet lives in css/sheets.css (no new stylesheet, so index.html/sw.js link lists stay the other agent's to merge).
- `source: 'apple_health'` set by the sheet (the reader's forUpload leaves it out); no server change needed (BodyImportSource accepts it).
- Per-day: trimDays keeps the first rows of a day in time order up to limit - stored rows (list routes, windows of 366 days). Stored rows that
  are not manual and match (time and numbers) take no room (a re-import must not call them left out). Review shows "n or more will be left
  out" (file alone); result shows the exact "n more on m days were left out".
- Refusal: any error stops the import, shows the server's words (+ the day of the row it names) and the number already added; Import again
  carries on. 401 (handled) closes the sheet. Closing the sheet mid-import stops after the request in flight and toasts.
- Watch rule applies to readings only (note 10 F4 is about blood pressure); sheet shows F4's line with "(2025 AHA/ACC guideline)".
- Handbook section does not state the device sentence (so no source id needed): the other agent adds AHA25BP/AHA-CUFFLESS to sources.yml
  in their worktree; adding the same ids here would conflict on merge. Integrator may link to their page and cite there.
- Reloading: caches in KH.state cleared + router.show of a showing today/trends view (as settings import does for caches).

## Reproduce
- `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/body_import.py --out <scratch dir>`
- `python -m pytest -q tests/test_body_import_ui.py`; `node tests/js/body_import_page.mjs`
- handbook: venv at <scratchpad>/venv-hb (python3.11 -m venv; pip install --require-hashes -r handbook/requirements.lock)
