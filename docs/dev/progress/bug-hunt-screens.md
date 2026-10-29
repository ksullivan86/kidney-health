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

## Found, not changed (for the report)

- offline.js: an edit or delete of an entry still waiting on this device, made while that entry's batch is being sent,
  is lost: the batch sends the old body and then deletes the outbox row. Fixing it needs a design choice (turn the edit
  into a PUT of the new server entry), so it is left for a decision.
- sharing.js load(): two overlapping loads (Stop sharing, then Make a link at once) can render without the new link,
  which is shown only once. Narrow timing; sharing.js is partly owned by another fix.

## How to check

node --test tests/js/<file>.test.mjs; the venv python -m pytest tests/test_<name>.py
