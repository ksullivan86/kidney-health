Status: in progress (Part A of design note 10: weight and blood pressure)

# body-part-a progress

Worktree: `.claude/worktrees/agent-aae9e61be21e48de0`, branch `worktree-agent-aae9e61be21e48de0`, based on `0cd8344` (the note).
Local WIP commits only, never push / PR / tag. Delete this file in the last commit.

## Setup notes
* The first worktree was removed by the harness after a Step-0 stop; recreated with
  `git worktree add -b worktree-agent-aae9e61be21e48de0 .claude/worktrees/agent-aae9e61be21e48de0 0cd8344` (same as the ff-merge the coordinator asked for).
* Handbook venv (hash-locked): `python3 -m venv $SP/venv-hb && $SP/venv-hb/bin/pip install --require-hashes -r handbook/requirements.lock`
  where `SP=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad`.

## Done (and how verified)
* m018 `app/migrations/m018_body_measurements.py` + `tests/test_migration_m018.py` (6 tests pass).
* Models (`app/models.py` "Weight and blood pressure log"), `app/body.py` (routes, pure functions, RED_FLAGS), `app/main.py`,
  `app/auth/ratelimit.py` (`body_batch` 60/h), settings (`user.units.weight`, `body.weight_alarm`, `body.bp_goal` in `settings_registry.py`).
* Handbook: two Get help now lines, source `NHLBI-BPS`, wallet card, REVIEW.md, note 10 text. Checked: `build_handbook.py --check`,
  `tests/test_handbook_content.py`, `mkdocs build --strict`, `check_links.py` all pass.
* Export/import: `app/account.py`, `app/data_import.py` (weights, blood_pressures; IMPORTED_SETTINGS gained the 3 settings).
* `tests/test_body.py` (143 tests pass), isolation matrix, auth coverage, export/import tests updated.

## Next
1. JS: `js/engine/body.js`, `js/mock/body.js`, seed, core.js helpers, `js/engine/settings.js` DEFS (+ float type), `js/mock/export.js`, `js/mock/import.js`,
   script tags in `index.html` and `sw.js` SHELL_URLS (needed for the demo to load them; no screens).
2. Vectors: `tests/data/gen_body_vectors.py`, `gen_settings_vectors.py` (body values), `gen_import_vectors.py`, `tests/js/run_vectors.mjs`, `tests/test_body_vectors.py`.
3. `tools/e2e/parity.py`, then docs (ARCHITECTURE, docs/body.md, docs/README.md, CHANGELOG), note 10 section "Decisions while building Part A".
4. All checks, then delete this file in the last commit.

## Decisions
* Batch routes answer 200 `{added, skipped}`; first invalid row refuses all with `rows.N.field: msg` (all that row's problems).
* `AUTOINCREMENT` ids (as symptoms); notes stored as '' (never NULL); `source_key` is not in the API row, it is in the export.
* The import has no "replace data" mode in this codebase: an account with weights/readings is a 409 unless `merge=1`; rows with a
  `source_key` dedupe on it, typed rows on their content.
* Dry weight for `between_sessions` is the Profile weight only when `dialysis = hemodialysis`.
* BP goal setting refuses systolic <= diastolic (like a reading).
* No activity row for weights/readings (symptoms record none).
