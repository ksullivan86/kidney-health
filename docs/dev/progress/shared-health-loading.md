Status: complete

Base: main bf7436b (#117, Other choices now merged). Refreshed all branch tips before starting.
This branch changes only symptom and body Trends loading, not the food-chart or dry-weight fixes
on the previous branches. Claude's last fetched feature branch did not change these modules.

Reproduced with real views/engines: seven of nine Node regressions fail on unchanged main.
Both cards retain the previous person's data while loading. The body chart also retains its redraw
cache, so resize can restore old readings under the new heading. Handled errors currently leave stale content.

Fix clears before reads and resets the body redraw cache. Failures show Retry for the same person/period.
Request guards discard late results and errors; unshared areas retain their explicit unavailable wording.
No server, clinical arithmetic, or data-write behavior changes.

Focused validation: `python -m pytest tests/test_shared_health_loading.py tests/test_sharing_ui.py
tests/test_body_ui.py tests/test_symptoms_ui.py tests/test_handbook_content.py`: 647 passed, existing
unused-sources warning. Nine new Node cases pass (seven reproduced failures before the fix).
Parity vectors, Ruff, both module syntax checks, demo build and git diff --check passed.
Full suite: 6,497 passed, two skipped, one existing unused-sources warning; one setup failure in
test_upgrade_starting_points_exist because the full clone did not contain the old pre-squash M1 commit.
Resolved its full SHA via GitHub and fetched `9ef9151faa1491281f5f6009401d07b3156d0ec1`; reran
`python -m pytest tests/test_e2e_tools.py::test_upgrade_starting_points_exist`: passed. No test disabled
or assertion changed. Retained the object locally at refs/upgrade-fixtures/schema-v3 (not pushed).
Run log: /tmp/kidney-full-health-loading.log (883.44 seconds). No remaining unexplained test failure.
User stopping target: October 29, 2026, about 10 a.m. America/Los_Angeles (17:00 UTC).
Pushed checkpoint 38877d3 to fix/shared-health-loading without a PR; no deployment or environment publication.

Additional validation while the full suite runs (checkout source kept unchanged): Chromium sharing
walk 39/39 passed; reliability walk 10/10 passed; passkey walk 31/31 passed. Strict handbook build
and 14,963 internal links passed. Phone regression: 140 passed, two diagnostic-only failures because
regress.py recognizes the old Chromium "Refused to apply inline style" prefix but the installed
Chromium says "Applying inline style violates ..." for the known malformed-XML parser documents.
Keep the strict CSP and error assertions; update the narrow test matcher on a separate branch.

Queued reproductions (temporary scripts, no app source changed during the full suite):
1. /tmp/kidney-shared-day-review.mjs: real sharing module, yesterday overwrites today's rendered food.
   /tmp/kidney-shared-day-browser-review.py confirms the same in Chromium (39 passed, one expected failure;
   /tmp/kidney-shared-day-race-before-20261029/report.json). Needs a per-box request guard, and Visit should
   start the shared day read on entry rather than after all other summary reads finish.
2. /tmp/kidney-ai-context-review.mjs: real AI module; pending breakfast ideas render as Dinner after setMeal,
   and Add to plan sends dinner despite the answer having been checked for breakfast. Needs request/context
   guards in mountIdeas and openRecipes, including resets and late errors; no AI server needed for Node regression.
3. /tmp/kidney-lab-cache-review.mjs: load + invalidate + load reuses the pre-save promise (one list request,
   expected two). Needs cache generation protection and refresh request guards; stale reads must not repopulate it.
4. /tmp/kidney-share-link-review.mjs: opening a second link while first info is pending lets old info replace
   the newer question and accept code. Needs question generation, clearing old dataset while checking, and close handling.
