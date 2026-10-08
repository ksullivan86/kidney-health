# Progress: owner follow-ups after v0.3.0 (2026-10-08)

Status: in progress. One PR per item, merged when green, then the working branch
`claude/adoring-sagan-th5swr` is reset to `origin/main`. Order: Phase 0 (docs and config), then the
v0.3.1 batch in `docs/dev/plans/v0.3.1.md`, then the assistant back end. Rules: CLAUDE.md (tests with
every behaviour change, JS twins and vectors, append-only migrations, docs and handbook, no network in
tests).

## Done

* Homelab review 1a + 7: `app.admin backup --dir --keep`, package-public note (PR #7).
* Homelab review 2, 3, 6a: Litestream notes, proxy-container `TRUSTED_PROXIES` row, SSO+MFA
  recommendation (PR #10).
* Homelab review 4: `notes` job in `release.yml` appends the index digest to the GitHub release's
  notes; digest form first in `docs/deployment.md` and the Quadlet unit; `tests/test_deploy.py`
  asserts the job's shape. Verified: `pytest tests/test_deploy.py`, `zizmor --offline`, `shellcheck`
  on the extracted script, a dry run of the script.

* PR #11 merged (release digest).
* Homelab review 5: cluster-neutral base `deploy/k8s` + example overlay `deploy/k8s-overlays/example/`
  (beside the base: kustomize refuses an overlay nested inside its base). Verified: kustomize build
  of both, kubeconform strict (18 resources valid), actionlint, zizmor, `pytest tests/test_deploy.py`.
* AI setup in plain words: "The setup in three questions" in `docs/ai.md`, "How the setup fits
  together" in `handbook/docs/app/ai.md` (the Settings intro copy is left for later).
  Both in one PR (#12, merged 2026-10-08 11:16 UTC).

* v0.3.1 item 1 "Not chosen yet": PR #13, merged 2026-10-08 11:34 UTC.
* v0.3.1 item 2 "Adjustable tolerance": PR #14, merged 2026-10-08 12:33 UTC.

## In progress

* v0.3.1 batch merged: #13 "Not chosen yet", #14 tolerances, #15 admin page, #16 running high, #17 Pages demo,
  #18 lab CSV import (13:38 UTC). All six items of `docs/dev/plans/v0.3.1.md` are on main; the owner publishes
  the v0.3.1 release.
* Kidney-only profile, part 1 (ROADMAP item): PR from the branch (built in worktree `scratchpad/kh7`).
  `log.has_meal_carb_goals`: no per-meal carbohydrate alerts with diabetes "none" (twin in `js/mock/log.js`),
  Today hides the meal carbohydrate line and planned-carbs badge, Settings → Meal guidance explains instead of
  showing the carb tolerance and the low dose. Verified: `tests/test_kidney_only.py` (rule, API, twin), Chromium
  walk type1 vs none at 375/1280, full suite and parity harness in the worktree. Also in this PR: Profile hides the
  per-meal and per-snack carbohydrate targets for "None" (values kept; the walk checks hide/show). Left on the
  ROADMAP: AI prompts worded from the profile (needs a PROMPT_VERSION bump and an owner-run golden set) and the
  Settings/handbook framing.
* "Explain the AI setup in plain words", last part: Settings → AI ideas intro (worktree `scratchpad/kh8`, branch
  `item8-wip`, commit "Settings -> AI ideas: How AI help is set up"); PR after the kidney-only one merges.
  Verified: `tests/test_ai_setup_intro.py`, `tests/test_learn_links.py` (new `APP_LINKS.pages.ai`), Chromium walk
  with AI on/off at 375/1280.

## Next (in order)

1. Kidney-only part 2 (owner-run prompt change), then the assistant back end (ROADMAP).

## Commands that reproduce the checks

```
python -m pytest -q tests/test_deploy.py
zizmor --offline .github/workflows/release.yml
python -m pytest -q            # full suite before any app-behaviour PR
node tests/js/run_vectors.mjs  # when server logic with a JS twin changes
```
