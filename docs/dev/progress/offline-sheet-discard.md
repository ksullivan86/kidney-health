# Offline outbox: a sheet saved after the entry was sent, and discard while sending

Branch: worktree-agent-aafcc232ea0cbcb38 (fast-forwarded to 501b87e, PR #123). Local commits only, never pushed.

## The two cases
1. The entry sheet of a waiting entry is open; the server's answer settles the row (done, or a follow-up edit/delete).
   Saving said "has just reached your server, open it again" and dropped the change.
2. Discard (Settings list, Discard all, "Sign out and lose them") of an entry being sent left the entry on the server.

## Steps
1. [x] Failing tests in tests/js/outbox_inflight.test.mjs (old code: 23 of 64 checks fail).
2. [ ] Fix in app/static/js/offline.js.
3. [ ] Sign-out sheet wording; Settings wording; static test; device.py step.
4. [ ] Docs: ARCHITECTURE.md, docs/install-on-your-phone.md, handbook/docs/app/logging.md, CHANGELOG.md.

## Commands
* `node tests/js/outbox_inflight.test.mjs`, `node tests/js/outbox_changes.mjs`
