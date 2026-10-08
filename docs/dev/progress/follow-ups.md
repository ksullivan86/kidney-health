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

* v0.3.1 item 3 "Admin settings on their own page": PR #15, merged 2026-10-08 12:50 UTC.
* v0.3.1 item 4 "Running high": PR #16, merged 2026-10-08 13:03 UTC.
* v0.3.1 item 5 "Pages demo": PR opened 13:20 UTC (branch reset to main, item 5 cherry-picked from worktree
  `scratchpad/kh5`). `scripts/build_preview.py --pages DIR` (meta CSP read from app/security.py with ast,
  `preview-flag.js` with `KDL_PREVIEW` and `KDL_DEMO_HANDBOOK` = `{url: "../", links: APP_LINKS}`), the link
  table moved to `app/guidance/topics.py` (`APP_LINKS`; `handbook.LINKS` is an alias), the Pages workflow builds
  the demo into `site/demo/` before the link check, "Try the app (demo)" in the Pages announce bar
  (`extra.demo_link`). Verified: full Pages site built locally (mkdocs pages flavour + demo, 120 pages, 0 broken
  links), Chromium walk handbook -> demo -> Learn links at 375/1280 light/dark (no console errors, no CSP
  violations, no outside requests), tests in `tests/test_preview_build.py` and `tests/test_deploy.py`, full suite.
* v0.3.1 item 6 "Lab CSV import": in worktree `scratchpad/kh6` (branch `item6-wip`, stacked on item 5).
  Design: the browser parses the file (`js/engine/lab_import.js`, `KH.labImport.analyse`), shows every result,
  and sends only the kept ones to a new `POST /api/labs/import` (re-validated like `POST /api/labs`,
  duplicates skipped, refused rows listed). Reason: a portal export can hold names and record numbers; they
  never leave the device. Done: the reader (tried under Node). Next: server route + model + tests, mock twin,
  UI card, vectors `tests/data/lab_import_vectors.json` + node runner section, docs.

## Next (in order)

1. v0.3.1 items 2–6 of `docs/dev/plans/v0.3.1.md`, then the kidney-only profile.

## Commands that reproduce the checks

```
python -m pytest -q tests/test_deploy.py
zizmor --offline .github/workflows/release.yml
python -m pytest -q            # full suite before any app-behaviour PR
node tests/js/run_vectors.mjs  # when server logic with a JS twin changes
```
