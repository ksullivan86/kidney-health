Status: complete

# Offline outbox: a sheet saved after the entry was sent, and discard while sending

Branch: worktree-agent-aafcc232ea0cbcb38 (fast-forwarded to 501b87e, PR #123). Local commits only, never pushed.

## The two cases
1. The entry sheet of a waiting entry is open; the server's answer settles the row (done, or a follow-up edit/delete).
   Saving said "has just reached your server, open it again" and dropped the change.
2. Discard (Settings list, Discard all, "Sign out and lose them") of an entry being sent left the entry on the server.

## Design
* `settled` (page memory, by client_id): the server's entry of each settled create, updated by its follow-up's answer
  (`{deleted: true}` after a delete or a 404). Cleared by `purge`.
* `editWaiting` / `deleteWaiting` with no create row call `reachedServer`: a follow-up row is joined (`enqueueChange` with
  `joinOnly`, raises `rev`); a delete follow-up means it is gone; else the settled entry (or the day read from the server,
  for another tab) gets a PUT of `changedFields(sheet entry, body)` or a DELETE via `KH.request` with its version
  (If-Match, 412 card, queue when offline).
* `mayBeOnServer(row)`: a create that was sent and not refused. `discard` keeps it as `deleted`; `discardAll` too, and keeps
  a `made_here` delete (set by `settleCreate`). `loseAll` (sign-out sheet): discard all, wait for the run, sync again, and
  return what is left; the sheet names it and offers "Sign out anyway". With nothing that may be on the server, the sheet
  signs out at once, as before.

## Steps
1. [x] Failing tests in tests/js/outbox_inflight.test.mjs (old code: 23 of 64 checks fail). Commit 00a9d0a.
2. [x] Fix in app/static/js/offline.js: 68 of 68 pass; outbox_changes.mjs 79 pass (its old 409 check now expects the edit
   on the server's entry).
3. [x] Settings and sign-out wording; static test in tests/test_outbox_inflight.py; device.py steps 5c (sheet left open)
   and 5d (Discard in Settings while in flight). Old offline.js: 5c fails ("just reached" console error, the sheet stays
   open). New: outbox and changes sections 56 passed, 0 failed. No browser step for the sign-out sheet: the contexts share
   the admin's session cookie, so signing out would end it for later sections.
4. [x] Docs: ARCHITECTURE.md, docs/install-on-your-phone.md, handbook/docs/app/logging.md, CHANGELOG.md.

## Commands
* `node tests/js/outbox_inflight.test.mjs`, `node tests/js/outbox_changes.mjs`, `node --test tests/js/*.test.mjs`, `node tests/js/run_vectors.mjs`
* `python3 tools/e2e/device.py --only outbox,changes --port 8483 --ai-port 8484 --out <scratch dir>`
* `ruff check .`
