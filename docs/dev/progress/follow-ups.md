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

## Next (in order)

1. Homelab review 5: cluster-neutral Kubernetes manifests (`deploy/k8s/deployment.yaml`
   `TRUSTED_PROXIES` back to the loopback default; gateway name/namespace, hostname and the
   NetworkPolicy's ingress namespace into `deploy/k8s/overlays/example/` with kustomize patches;
   docs in `docs/deployment.md` "Kubernetes"); `tests/test_deploy.py` and CI's kubeconform must pass.
2. "Explain the AI setup in plain words": overview at the top of `docs/ai.md`, Settings → AI ideas
   intro copy, handbook `app/` page.
3. v0.3.1 batch, items 1–6 of `docs/dev/plans/v0.3.1.md`, then the kidney-only profile.

## Commands that reproduce the checks

```
python -m pytest -q tests/test_deploy.py
zizmor --offline .github/workflows/release.yml
python -m pytest -q            # full suite before any app-behaviour PR
node tests/js/run_vectors.mjs  # when server logic with a JS twin changes
```
