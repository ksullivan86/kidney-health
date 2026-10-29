Status: in progress

Verification branch test/reliability-batch-integration, based on Claude cbc48fc and main 84330f3.
Branches refreshed immediately before starting. No PR, deployment or environment publication.
Claude's base already includes the shared-cache fix and its Settings-comment compatibility fix,
Chromium XML diagnostics and the external-backup reminder work.

Merge these tested branches without rewriting their history, preserve every fix when resolving
overlapping docs/harness edits, then test the combined result:

* fix/profile-suggestion-context e925af5
* fix/recipe-fit-unknown-nutrients 3a3ff1d
* fix/body-day-loading-state 444d204
* fix/meal-editor-unknown-nutrients fe69c16
* test/health-save-retry 471bc95
* fix/symptom-day-loading-state fc5ba6d
* fix/recipe-fit-save-context 609aaf8

Main alone has already passed 6533 tests (2 skipped, existing warning only), recorded in
current-main-validation.md on the health-save-retry branch. Each fix's note records its own
focused and browser checks. This branch checks their compatibility with each other and current
Claude changes. Next: merge/resolve, combined targeted tests and browser walks, then full suite.

All seven merges are complete, preserving their original commits. Code snapshot: 12523c2.
Resolved conflicts by keeping both changes in docs and all steps in reliability.py; no source fix
was dropped. Ruff and diff checks pass. Fixed validation checkout:
/tmp/kidney-reliability-batch-validation. Full pytest is running there (session 67615), log
/tmp/kidney-reliability-batch-full-suite.log. Browser sessions: reliability 81431, Profile 53376,
health retry 53187; logs /tmp/kidney-batch-{reliability,profile,health-retry}.log. These scripts run
from the validation checkout so subsequent work in /workspace cannot affect the tested code.
Next: inspect outcomes, run body/Symptoms/sharing/import/AI checks, parity and strict handbook build,
record exact results and push this verification branch without PR/deployment.
