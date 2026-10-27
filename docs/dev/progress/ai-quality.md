Status: in progress

# ai-quality: "How well each AI is doing" in Server administration → AI providers

Worktree: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/integ-quality`
(branch `wip/ai-quality`, based on main 56869a4 = v0.5.0). Commit locally only. No push, no tag, no PR.

## What it is

Two signals per routed feature, in one admin route and one admin screen section:

1. What happened in real use: the last 20 calls (14 days, all users) of the feature to the provider and model it
   resolves to, from `ai_audit`. Counts only. A warning at 8 or more calls and 70 % or more without a usable result.
2. What the live evaluation said: reports written by `scripts/ai_eval.py`, read from `AI_EVAL_REPORTS_DIR`.

## Design decisions

* New files hold the logic: `app/ai/quality.py` (live counts, evaluation status, the overview, start-up lines) and
  `app/ai/eval_reports.py` (reading and matching the report files). Shared files get small blocks only:
  `app/config.py` (one field), `app/ai/routes.py` (one route, one start-up call, one `shown` count in the activity
  row), `app/static/js/views/ai.js` (an api entry and three lines in `adminPart`).
* Route: `GET /api/admin/ai-quality` (admin only, no re-auth: it only reads). Operation id `admin_read_ai_quality`.
* The provider of a feature comes from the same rules as routing (`routing.role_row`, first usable shared provider
  for `any`). No keyring is needed, so it also works at start-up. A feature that is off, or has no usable provider,
  has no row.
* Model to count: the text model, or the vision model for photos and lab reports (that is what `ai_audit.model` holds).
* `cached` rows are not calls to the model, so they are not counted.
* `shown` (a count) is added to the activity row's verdict so that "every item dropped" is visible for describe and
  plate. Rows from before have no `shown` and count as usable when their status is `ok`.
* No cache for the report files: the folder is read on every request (at most 200 files, 1 MiB each).
* A symlink is followed only when its target stays inside the folder (Kubernetes ConfigMap mounts are symlinks).
* Demo and preview: `renderAdmin` already shows a stub and never calls the admin routes, so the section is simply
  not there. No mock route.
* Gates are judged per feature (a gate that is about another feature is not held against it).
* Reports without Ask gates do not cover Ask.

## Done

* `app/ai/eval_reports.py` (folder reader, report parser, matching) and `app/ai/quality.py` (outcome mapping, thresholds,
  live counts, evaluation status, overview, start-up lines). Checked by `tests/test_ai_quality_live.py` and
  `tests/test_ai_quality_reports.py` (pass).
* `AI_EVAL_REPORTS_DIR` in `app/config.py` (`AiEnv.eval_reports_dir`).
* `app/ai/routes.py`: `GET /api/admin/ai-quality`, the start-up call, and the `shown` count in the activity row.

## In progress

API and start-up tests (`tests/test_ai_quality_api.py`), then the screen.

## Next

* config field, route, start-up lines, `shown` count
* tests: outcome mapping, thresholds, window and cap, counts only, access, reports folder, start-up, UI (fake DOM)
* UI module, CSS, index.html, sw.js
* docs: ai.md, dev/ai-eval/README.md, deployment.md, .env.example, compose/quadlet/k8s comments, handbook, ARCHITECTURE.md,
  CHANGELOG.md
* openapi regeneration, all checks, final commit

## Commands that reproduce the checks

    cd <worktree>
    python -m pytest -q                       # run in the background, wait
    python -m pytest -m safety -q
    node tests/js/run_vectors.mjs
    ruff check .
    python scripts/gen_openapi.py --check
    for g in tests/data/gen_*.py; do python $g --check; done
    python scripts/build_handbook.py --check
    git diff --check
