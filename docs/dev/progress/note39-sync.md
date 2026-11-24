Status: in progress

# note39-sync: the phone receives and sends edits (design note 39, steps 6 and 7)

Role: `note39-sync`. Worktree branch `worktree-agent-a576689c6f00d2f36`, fast-forwarded to `local/note39-server` (de8672e), which
has the server side and the phone's steps 1, 3, 4. Commit own paths only; no push, no PR.
Venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
Avoid editing app/static/js/mock/{foods,lists,meals,labs,symptoms,body}.js (another helper works there).

## Done
- Read note 39, app/sync_feed.py (contract), server_sync.js, server_api.js, offline.js conflictCard.
- New `app/static/js/mock/server_changes.js` (M.serverChanges): gate (account check), afterSend (match, first sync, send edits,
  receive), decide (card choices), choose (account question), status. Saved state `_serverChanges` (shape in the file header).
- server_sync.js: run() = gate → step-4 runOnce → afterSend; planned entries sent at once when two-way is active.
- index.html + sw.js list server_changes.js after server_sync.js.
- Swift allow-list: GET /push/v1/changes (after, limit), POST /push/v1/changes, POST /push/v1/match; ServerAPITests; test_ios_app.
- tests/js/server_sync.mjs: two checks adjusted for the about request the gate makes first (94 pass).

## Next
- tests/js/server_changes.mjs (fake server), pytest round trip with the real server (line protocol), Settings UI (review cards,
  account question), e2e device_mode case, docs.

## Decisions
- Non-entry rows keep their client_id in step 4's queue mark `c` (mock files untouched).
- Saved meals (`meal` kind) are skipped by the feed reader until step 8.
- Per row: b = server version agreed, l = phone version when the two agreed but differ (twin rounding), so a done edit never
  loops; a put with version b and an unchanged phone row takes the server's copy (its way of saving it).
- The first-sync rule is also used for any row with no agreed version (step 4's new rows echoing back).
