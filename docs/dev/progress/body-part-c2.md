# body-part-c2 — the Apple Health weights and blood pressure import sheet

Status: in progress (Step 0 done: fast-forward to d52f4fe)

Branch: worktree-agent-accbb476ac892ccf6 (local commits only; never push, no PR)

## Done
- Step 0: `git merge --ff-only d52f4fe` ok; app/body.py and engine/apple_health.js exist.

## In progress
- Reading the specs (note 10 4.8 and 4.12, the reader's header, app/body.py batch routes, mock/body.js, lab_fhir.js). Done reading.

## Next steps
1. js/views/body_import.js + the sheet in index.html + css/body-import.css + sw.js (+ tests/test_frontend_shell.py passes)
2. tests/js/body_import_page.mjs + tests/test_body_import_ui.py
3. tools/e2e/body_import.py (+ tools/e2e/README.md, tests/test_e2e_tools.py, docs/maintainers.md)
4. handbook section, ARCHITECTURE, docs/body.md, CHANGELOG
5. full checks; delete this file in the last commit

## Decisions
- (filled in as made)

## Reproduce
- `python -m pytest -q`, `node tests/js/run_vectors.mjs`, `ruff check .`
