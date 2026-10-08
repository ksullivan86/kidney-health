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

* Merged today: #13–#18 (the whole v0.3.1 batch), #19 and #22 (kidney-only profile, parts 1 and 2: no meal
  carbohydrate goals, and the "Not medical advice" note without insulin decisions, for diabetes "None"), #20
  (Settings → AI ideas "How AI help is set up", plus the `regress.py` Learn-link fix), #21 (the `journey.py`
  setup step opens Server administration for the AI switch) and #23 (the image and the Pages copy leave out the
  handbook search's other-language files, 964 KB; both image builds and smoke tests passed in CI).
* QA of today's merges (worktree `scratchpad/khqa` at the #19 head, logs in `scratchpad/qa/`): `upgrade.py` 71/71
  (v0.2 and schema v3 to schema 9); `regress.py` passes in all four configurations (fixed in #20); `sandbox.py`
  passes; `device.py` 151/151; `learn.py` 60/60; `journey.py` 134/134 with #21.
* PR from the branch: offline handbook pages (built in worktree `scratchpad/kh13`). The service worker keeps a
  copy of each /learn page and file opened; a page never opened answers offline with a short 503 note.
  Verified: full suite (exit 0); `tests/test_learn_offline.py` (the real worker in Node); `learn.py` 72/72 with
  the new step 7 (server stopped), also after the `waitUntil` hardening; `device.py` 151/151; `journey.py`
  134/134; `upgrade.py` passes (`regress.py`, `sandbox.py` and `parity.py` were running at the time of writing,
  logs in `scratchpad/qa13/`).
* After it merges: a last QA sweep on main (`scratchpad/final_qa.sh`: strict handbook build pruned like the
  image, then upgrade, regress, sandbox, parity, device, learn and journey), then the final note.

## Next (in order)

1. Kidney-only part 2 (owner-run prompt change and handbook framing), then the assistant back end (ROADMAP).

## Commands that reproduce the checks

```
python -m pytest -q tests/test_deploy.py
zizmor --offline .github/workflows/release.yml
python -m pytest -q            # full suite before any app-behaviour PR
node tests/js/run_vectors.mjs  # when server logic with a JS twin changes
```
