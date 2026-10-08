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

* v0.3.1 items 3, 4 and 5 merged: PR #15 (12:50 UTC), #16 (13:03), #17 (Pages demo, 13:19).
* v0.3.1 item 6 "Lab CSV import": PR from the branch (item 6 cherry-picked from worktree `scratchpad/kh6`).
  The browser reads the file (`js/engine/lab_import.js`, `KH.labImport.analyse`) and only the ticked results
  go to `POST /api/labs/import` (checked like `POST /api/labs`, repeats skipped, refused listed; errors worded by
  `security.flatten_validation_errors`). Demo twin in `js/mock/labs.js`; Labs card "Import from a spreadsheet";
  vectors `tests/data/lab_import_vectors.json` (`tests/js/gen_lab_import_vectors.mjs`, reviewed by hand) in the
  node runner; `tests/test_lab_import.py`. Verified: tests, node vectors, parity harness 6558/6558 (import cases
  added), Chromium walk on a real server and in demo mode at 375/1280 (preview, unit choice, refused rows, save,
  only test/value/unit/date sent, re-import ticks nothing, no console errors).

## Next (in order)

1. After item 6: the kidney-only profile (ROADMAP), then the assistant back end.

## Commands that reproduce the checks

```
python -m pytest -q tests/test_deploy.py
zizmor --offline .github/workflows/release.yml
python -m pytest -q            # full suite before any app-behaviour PR
node tests/js/run_vectors.mjs  # when server logic with a JS twin changes
```
