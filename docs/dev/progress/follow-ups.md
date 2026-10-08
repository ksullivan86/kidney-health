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

## In progress

* v0.3.1 item 2 "Adjustable tolerance" (commit on top of main b5cc3e7, PR next):
  `nutrients.over_at` / `is_about` (never a limit) / `about_tolerance` / `carb_tolerance` / `_status_word`,
  per-meal alerts with the tolerance and without low treatments, `periods.summarize_period(about_tolerance_pct=)`,
  `log.day_figures(carb_tolerance_g)` + `carb_tolerance_for` (reads `guidance.carb_tolerance_g`),
  `DaySummary.carb_tolerance_g`, schema step 9 `m009_about_tolerance`, Profile field + form row, twins in
  `js/engine/rules.js`, `js/mock/log.js` / `profile.js`, Today, Plan, the entry sheet. Guidance vectors
  regenerated (one alert now says "today's target"). Verified: `tests/test_tolerance.py` (32 tests), the twin,
  guidance parity and API tests, `node tests/js/run_vectors.mjs`, `tools/e2e/parity.py` (6528 checks; the one
  failure was the harness's own reset profile missing item 1's flags, fixed; sections 0,11 rerun 724/724).

## Next (in order)

1. v0.3.1 items 2–6 of `docs/dev/plans/v0.3.1.md`, then the kidney-only profile.

## Commands that reproduce the checks

```
python -m pytest -q tests/test_deploy.py
zizmor --offline .github/workflows/release.yml
python -m pytest -q            # full suite before any app-behaviour PR
node tests/js/run_vectors.mjs  # when server logic with a JS twin changes
```
