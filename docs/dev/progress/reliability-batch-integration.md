Status: in progress

Verification branch test/reliability-batch-integration, based on Claude cbc48fc and main 84330f3.
Branches refreshed immediately before starting. No PR, deployment or environment publication.
Claude's base already includes the shared-cache fix and its Settings-comment compatibility fix,
Chromium XML diagnostics and the external-backup reminder work.

Merged these tested branches without rewriting their history, preserving every fix when resolving
overlapping docs/harness edits:

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
Claude changes present in its base.

All seven merges are complete, preserving their original commits. Code snapshot: 12523c2.
Resolved conflicts by keeping both changes in docs and all steps in reliability.py; no source fix
was dropped. Ruff and diff checks pass. Fixed validation checkout:
/tmp/kidney-reliability-batch-validation. Full pytest: 6551 passed, 2 skipped, one existing
unused-handbook-sources warning, 904.41 seconds. Log /tmp/kidney-reliability-batch-full-suite.log.
All scripts ran from that checkout so concurrent work could not affect the tested code.

Combined browser results at 12523c2: reliability 35, Profile 8, health retry 30, body 366,
Symptoms 79, AI recipes 40, sharing 43, import 109: 710 passed, no failures. Their reports are
/tmp/kidney-batch-<name>-20261029/report.json (health retry: health-retry; AI: recipes-ai).
Node parity and demo build pass. Handbook: 24 generated files current, 6 menus checked;
strict build passed, 120 pages, 14803 internal links, 0 broken, 312 external URLs (not fetched).
No app source changed since the tested 12523c2 snapshot; subsequent commits only update this note.

Main advanced to 6fa43ab (#120) while tests ran; its app/tests/tools match the Claude base already
included here. Claude 289c2b3 also has new Scan/USDA/Ask/admin fixes in different files; those later
changes are not in this snapshot. The recipe-apply serving improvement is on a separate branch
and is not part of these results. No PR or deployment; this branch is ready for Claude's review.

Follow-up integration: refresh to main 6fa43ab and Claude 289c2b3 (Scan/USDA/Ask/admin fixes),
and add recipe-apply-serving-preview e866a04. The earlier results above remain for 12523c2 only.
Also finish the matching parent-loader timing for weight/BP: the body module clears on start,
but Today still waits for food before calling it. Symptoms already starts independently.
Next: merge current work, isolate that small timing fix, then verify the new combined snapshot.
