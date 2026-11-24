Status: complete

# note39-sync: the phone receives and sends edits (design note 39, steps 6 and 7)

Role: `note39-sync`. Worktree branch `worktree-agent-a576689c6f00d2f36`, fast-forwarded to `local/note39-server` (de8672e), which
has the server side and the phone's steps 1, 3, 4. Commit own paths only; no push, no PR.
Venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
Did not edit app/static/js/mock/{foods,lists,meals,labs,symptoms,body}.js (another helper works there).

## Done
- `app/static/js/mock/server_changes.js` (M.serverChanges): `gate` (account check, §8.8), `afterSend` (match + first sync §8.7,
  send edits/deletes, read the feed §8.5, 410 full resync), `decide` (card answers), `choose` (send / replace / cancel),
  `status`, `takeChanged`. Saved state `_serverChanges` (shape in the file header and ARCHITECTURE "Device mode").
- `server_sync.js`: `run()` = gate → step-4 runOnce → afterSend; a planned entry is sent at once while two-way is active.
- `server_api.js`: `readAbout` also reads `changes` (`sync.changes` / `features.changes`); two-way needs it not false.
- index.html + sw.js list server_changes.js after server_sync.js.
- Settings → This device → **Your server** (was "Sending to your server"; button **Sync now**, same id): Both ways lines, the
  review / conflict cards (note 02 layout and classes), notices with OK, refused changes, the account question card.
- `js/main.js`: Today reloads when rows came from the server.
- Swift allow-list: GET /push/v1/changes (after, limit), POST /push/v1/changes, POST /push/v1/match; ServerAPITests; test_ios_app.
- Tests: tests/js/server_changes.mjs (117 checks, fake feed), tests/test_server_changes_phone.py (the same page against the real
  routes through a stdio relay, allow-list enforced, plays the web app; plus the fake run and a static check),
  tools/e2e/device_mode.py `sync_walk` (71 e2e checks pass), server_sync.mjs and server_services.mjs adjusted.
- Docs: ARCHITECTURE (change feed reader, Device mode bullets, file map row), docs/push.md ("What the iPhone app does with it"),
  handbook app/install.md and app/weight-and-blood-pressure.md (`build_handbook.py --check` up to date), CHANGELOG, note 39 status.

## Checks that pass
node tests/js/{server_changes,server_sync,server_services,device_mode,run_vectors}.mjs;
pytest tests/test_settings_ui.py tests/test_device_ui.py tests/test_device_mode.py tests/test_push_ui.py tests/test_ai_ui.py
tests/test_ios_app.py tests/test_server_sync_phone.py tests/test_server_services_phone.py tests/test_server_changes_phone.py
tests/test_sync_feed.py tests/test_row_versions.py tests/test_preview_build.py tests/test_security.py tests/test_handbook_content.py
tests/test_push.py tests/test_app_gateway.py tests/test_brand.py tests/test_auth_coverage.py tests/test_offline_edits_ui.py
tests/test_demo_local_ui.py; ruff on the changed Python; tools/e2e/device_mode.py. Full suite not run (slow).

## Decisions
- Non-entry rows keep their client_id in step 4's queue mark `c` (mock files untouched).
- Saved meals (`meal` kind) are skipped by the feed reader until step 8 (cursor moves past them; step 8 will need to read from 0
  for meals, or a full resync).
- Per row: b = server version agreed, l = phone version when the two agreed but differ (twin rounding), so a done edit never
  loops; a put with version b and an unchanged phone row takes the server's copy (its way of saving it).
- The first-sync rule is also used for any row with no agreed version (step 4's new rows echoing back).
- Conflict (steady state): the person's change stays in the log, the server's copy in the card. First-sync `differ`: the server's
  copy is shown and the phone's kept in the card (§8.7).
- Replace keeps profile, settings and saved meals (they do not sync yet); the Files safety copy is made by the save before.

## Left for later
- The badge "N to review" and the "needs review" mark on Today (§8.6): the count is in Settings only.
- Profile/targets card of §8.7 point 5, saved meals, settings (step 8). Ask on the phone.
- Swift not compiled here (only three Route lines and tests added).
