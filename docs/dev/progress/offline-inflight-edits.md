Status: in progress

# Offline outbox: edits and deletes while a send is in flight

Branch: worktree-agent-a8e1fe8d00a75d007 (merged claude/adoring-sagan-th5swr at 289c2b3). Local commits only, never pushed.

## The bug
`syncRun` in `app/static/js/offline.js` sends a batch with the bodies it read, then deletes the outbox rows. An edit
(`editWaiting`) or delete (`deleteWaiting`) of a waiting entry made while the batch is in flight is lost: the server keeps the
old entry. The same happens to a second edit that joins a change (`enqueueChange`) while that change's PUT is in flight.

## Plan / design
* A create row gets `sent: true` (stored) just before it is sent; the body sent is read in the same step.
* `editWaiting` on a sent row also sets `edited_after_send`; `deleteWaiting` on a sent row keeps it as a tombstone
  (`deleted: true`, hidden from Today) instead of removing it.
* After a create reply, the row is updated in one store step: a tombstone becomes a queued `delete` of the entry the server
  made (found by client_id, with its version); an edited row becomes a queued `edit` with what differs (`changedFields`);
  otherwise it is removed. The existing change replay (If-Match, 412, 404) then sends it.
* Change rows carry `rev`; a row merged while its PUT is in flight is rebased on the reply instead of removed.
* Outbox writes in the sync use a read-modify-write in one IndexedDB transaction (`store.update`).

## Steps
1. [x] Reproduce: tests/js/outbox_inflight.test.mjs + tests/test_outbox_inflight.py. On the old code 11 of 26 checks fail (every scenario except "sent without changes"): the server keeps the old entry or the deleted one.
2. [ ] Fix in offline.js.
3. [ ] Existing tests: outbox_changes.mjs, pytest, tools/e2e/device.py.
4. [ ] Docs: ARCHITECTURE.md, docs page, handbook, CHANGELOG.

## Commands
* `node tests/js/outbox_inflight.test.mjs`
* `$PY -m pytest -q tests/test_outbox_inflight.py tests/test_offline_edits_ui.py` with
  `PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
