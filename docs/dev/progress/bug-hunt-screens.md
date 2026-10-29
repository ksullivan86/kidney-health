Status: in progress

# Bug hunt: stale data, late replies and lost typing on the remaining screens

Scope: Ask (views/ask.js), Visit prep (views/visit.js except loadDay), data import (Settings), Settings screens
(account, devices, tokens, sharing list, admin), Add search and Quick add (views/add.js, scan.js), offline outbox (offline.js).
Do not touch: today.js, trends.js, symptoms.js, body_trends.js, sharing.js renderDay/question, visit.js loadDay, ai.js context,
labs.js, profile.js, plan.js, core.js, body.js (other helpers).

Worktree branch: worktree-agent-a40343b19796cd750 (merged next-batch first). Commit locally only, never push.

## Survey (done)

Candidates judged real, in order of harm:
1. scan.js: "Read the label for me (AI)" answer arrives after the photo was removed or Quick add was closed and opened
   again, and overwrites what the person typed with another photo's numbers.
2. scan.js: a slow barcode lookup answers after the Scan sheet was closed (or a newer lookup began) and opens the entry
   sheet for that food anyway.
3. add.js: two USDA searches in flight (Enter then the Search button, or a corrected word) both append, so the list
   mixes both answers; an answer after the sheet was reopened lands in the fresh sheet.
4. ask.js: a failed send puts the question back in the box and wipes the next question typed while waiting.
5. settings.js: two overlapping Server administration loads (double tap on the shield) build every section twice.

Looked at, no change: visit.js load (has a request counter and Loading notes), the import block (has a `latest`
counter and an AbortController), loadDevices (checks the box is still on the page), renderAssistant and renderDevice
(tickets).

## Fixes

1. **scan.js: late barcode answers and late AI label readings** (candidates 1 and 2). Done.
   - `lookupTurn`: a new turn per lookup and per opening/closing of the Scan sheet; an older turn's answer or error is dropped.
   - `photo.turn`: a new turn per photo chosen or removed (Quick add closing removes it). The AI answer fills the form only
     for the same turn; the cached JPEG is kept only if the photo did not change while it was made (before, the old
     photo's JPEG could be cached under the new photo and sent).
   - Test: tests/js/scan_late_reply.test.mjs (+ tests/test_scan_late_reply.py). On the old scan.js 5 of 7 fail
     (the two "still works" cases pass); with the fix 7 of 7 pass. Also run: test_device_ui, test_ai_routing_ui,
     test_brand, test_vendor, test_handbook_content, test_handbook_serving.
   - Shared helper for all vm tests: tests/js/fake_page.mjs.
   - Docs: ARCHITECTURE.md (Scan result, Quick add photo), handbook app/barcode-and-photo.md, docs/barcode-and-photos.md,
     CHANGELOG.
2. **add.js: USDA search sheet** (candidate 3). Done.
   - `usdaSearchTurn` per search and `usdaSheetTurn` per opening/closing. Old answers and errors are dropped; an import
     that finishes after the sheet closed shows its toast (success or failure) but opens no entry sheet.
   - Test: tests/js/usda_late_reply.test.mjs (+ tests/test_usda_late_reply.py). Old add.js: 6 of 7 fail; new: 7 of 7.
     Also run: test_demo_servings_only, test_device_ui, test_offline_edits_ui, test_reliability_ui.
   - Docs: ARCHITECTURE.md (Add food), handbook app/logging.md (Search USDA), CHANGELOG.
3. **ask.js: a failed send wiped what was typed meanwhile** (candidate 4). Done.
   - The question goes back first, then a blank line, then what was typed. Box empty: the question alone, as before.
   - Known limit: a combined message is a new request_id, so a trusted save that reached the server before its answer
     was lost could be saved again if the person sends the combined text. Rare (trust on, reply lost, typed meanwhile).
   - Test: tests/js/ask_late_reply.test.mjs (+ tests/test_ask_late_reply.py). Old ask.js: 1 of 3 fail (the bug case);
     new: 3 of 3. Also run: test_ai_cloud_env, test_ask_taste_ui, test_ask_ui, test_ask_voice_ui.
   - Docs: ARCHITECTURE.md (Ask chat), handbook app/ai.md, CHANGELOG.
4. **settings.js: overlapping Server administration loads built every part twice** (candidate 5). Done.
   - `adminRender` ticket in renderAdminFrame; an older load returns after its two-step check. Kept the plain `return;`
     in each branch (tests/test_admin_page.py reads the source for it).
   - Test: tests/js/admin_frame.test.mjs (+ tests/test_admin_frame.py), which cuts the frame out of settings.js like
     tests/js/assistant_page.mjs. Old: 2 of 4 fail (the two overlap cases); new: 4 of 4.
   - Also run 26 Settings-related pytest files: all pass except
     test_settings_ui.py::test_the_ui_never_mentions_reminders_before_they_exist, which already fails on next-batch
     (the BACKUP_REMINDER_DAYS comment from commit dd88a39), not touched here.
   - Docs: ARCHITECTURE.md (Server administration), CHANGELOG. The handbook already describes the right behaviour.
5. **Chromium walk** tools/e2e/late_replies.py (system python3, port 8098): scan-then-close, USDA twice, admin tapped
   twice. With the old scan.js, add.js and settings.js (from 5f51dcd~1): 0 passed, 4 failed. With the fixes: 4 passed.
   Listed in tools/e2e/README.md. Ask and the AI label reading need an AI provider, so they are covered by the vm tests only.

## Pre-existing failures seen on next-batch (not from this work)

- tests/test_settings_ui.py::test_the_ui_never_mentions_reminders_before_they_exist (settings.js comment
  "BACKUP_REMINDER_DAYS=0: the admin turned the reminder off", commit dd88a39).
- tests/test_deploy.py::test_self_hosting_pages_link_to_commands_instead_of_copying_them[backups.md]
  (handbook/docs/self-hosting/backups.md repeats `podman exec`).

## Found, not changed (for the report)

- offline.js: an edit or delete of an entry still waiting on this device, made while that entry's batch is being sent,
  is lost: the batch sends the old body and then deletes the outbox row. Fixing it needs a design choice (turn the edit
  into a PUT of the new server entry), so it is left for a decision.
- sharing.js load(): two overlapping loads (Stop sharing, then Make a link at once) can render without the new link,
  which is shown only once. Narrow timing; sharing.js is partly owned by another fix.

## How to check

node --test tests/js/<file>.test.mjs; the venv python -m pytest tests/test_<name>.py
