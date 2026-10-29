Status: complete

# Offline outbox: edits and deletes while a send is in flight

Branch: worktree-agent-a8e1fe8d00a75d007 (merged claude/adoring-sagan-th5swr at 289c2b3). Local commits only, never pushed.

## The bug
`syncRun` in `app/static/js/offline.js` sent a batch with the bodies it read, then deleted the outbox rows. An edit
(`editWaiting`) or delete (`deleteWaiting`) of a waiting entry made while the batch was in flight was lost: the server kept the
old entry. The same happened to quick adds, to an edit made after a lost answer (the resend answers `existing`, old content),
and to a second edit or a delete that joined a change (`enqueueChange`) while that change's PUT was in flight.

## Design (done)
* `store.update(name, key, fn)`: read-modify-write in one IndexedDB transaction (memory: synchronous). The in-memory outbox
  is now copied in and out like IndexedDB, so a row read for a send never changes under it.
* `startSend`: a create row gets `sent: true` in the same step that reads the body sent.
* `editWaiting` on a sent row also sets `edited_after_send`; `deleteWaiting` on a sent row keeps it as `deleted: true`
  (hidden from Today, "Delete: …" in lists). Unsent or refused rows are removed as before.
* `settleCreate` after a create answer: deleted → the row becomes a queued `delete` of the server entry (found by
  client_id in the batch answer, with its version); edited → a queued `edit` with `changedFields(serverEntry, body)`; else
  removed. The existing change replay (If-Match, 412, 404) sends it next in the same run.
* Change rows carry `rev` (raised on every join in `enqueueChange`); on a 2xx with a newer `rev` the row is rebased on the
  answered entry (new version, only what still differs) instead of removed.
* `markFailed`, conflicts, new versions, `markExpected`: all through `store.update`. A deleted row the server refuses is removed.
* `withWaiting` hides the server's copy of an entry that is still being sent (by client_id), so it shows once.
* No server change.

## Steps
1. [x] Reproduce: tests/js/outbox_inflight.test.mjs + tests/test_outbox_inflight.py. Old code: 16 of 33 checks fail
   (11 of the first 26). Commit ef1766d.
2. [x] Fix in offline.js. New code: 33 of 33 pass; outbox_changes.mjs 79 pass.
3. [x] Existing tests: full `python -m pytest` exits 0 with no failures; `tools/e2e/device.py` (every section) 189 passed,
   0 failed. Static tests updated: `row.state = 'conflict'` in test_offline_edits_ui.py; test_device_ui.py checks
   `/api/log/${id}` templates with a number. device.py step 5b holds the batch answer with page.route, edits one entry and
   deletes another meanwhile, and checks the server. 5b first used pear at dinner, and the `changes` section opens its own pear
   row by name, so it opened the wrong one; 5b now logs peach and mango at breakfast.
4. [x] Docs: ARCHITECTURE.md (Offline edits and deletes: "Changes made while a send is on its way", checks, code map, M2
   checks), docs/install-on-your-phone.md, handbook/docs/app/logging.md, CHANGELOG.md.

## Commands
* `node tests/js/outbox_inflight.test.mjs` and `node tests/js/outbox_changes.mjs`
* `$PY -m pytest -q` with `PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
  (no xdist installed: no `-n`)
* `python3 tools/e2e/device.py --only outbox,changes --port 8471 --ai-port 8472 --out <scratch dir>`
* To see the old behaviour: `git show ef1766d:app/static/js/offline.js` into place, run the Node test, put the new file back.
