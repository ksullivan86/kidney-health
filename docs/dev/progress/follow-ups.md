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

* Merged today: #13–#18 (the whole v0.3.1 batch) and #19 (kidney-only profile, part 1, 13:48 UTC).
* "Explain the AI setup in plain words", last part: Settings → AI ideas intro, PR from the branch (built in worktree
  `scratchpad/kh8`). Same PR, separate commit: `tools/e2e/regress.py` compares warnings without the handbook's
  "Learn: …" links (with a built handbook every preview comparison failed; found by a QA run today).
  Verified: full suite in the worktree, `tests/test_ai_setup_intro.py`, `tests/test_learn_links.py`, Chromium
  walk AI on/off at 375/1280, `regress.py --only 1280-dark` with and without a built handbook (121/121 each).
* QA of today's merges (worktree `scratchpad/khqa` at the #19 head): `upgrade.py` 71/71 (v0.2 and schema v3 to
  schema 9), `regress.py` all four configurations pass once the handbook artifact is excluded (see above);
  `sandbox.py` and `device.py` running at the time of writing (logs in `scratchpad/qa/`).

## Next (in order)

1. Kidney-only part 2 (owner-run prompt change and handbook framing), then the assistant back end (ROADMAP).

## Commands that reproduce the checks

```
python -m pytest -q tests/test_deploy.py
zizmor --offline .github/workflows/release.yml
python -m pytest -q            # full suite before any app-behaviour PR
node tests/js/run_vectors.mjs  # when server logic with a JS twin changes
```
