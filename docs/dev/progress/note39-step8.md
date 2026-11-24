Status: complete

# note39-step8: saved meals, profile, targets, settings and food preferences on the phone (design note 39, step 8)

Role: `note39-step8`. Worktree branch `worktree-agent-ab561d90e798d90fa`, reset (--keep) onto `worktree-agent-a576689c6f00d2f36`
(0fbbd57, steps 1-7), then merged `worktree-agent-af1bb2a8826027962` (the demo's twins and step 9; conflicts resolved keeping both).
Commit own paths only; no push, no PR.
Venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python

## Done (each verified by the tests named)
- Server: `meals` in POST /push/v1/sync (`SyncMeal`, items by FoodRef, found again by client_id, no receipt); meal edits in
  POST /push/v1/changes take `SyncMealFields` (foods by reference; a missing food is `refused`); `food_for_ref` also finds an own
  food by its client_id (fixes entries for server-made foods). tests/test_sync_meals.py, test_app_sync.py (counts gain `meals`),
  docs/api/openapi.json regenerated.
- Gateway ALLOWED + GET/PUT /api/profile, GET /api/me/settings, GET /api/guidance/preferences, PUT/DELETE
  /api/guidance/preferences/{food_id}, GET /api/foods, GET /api/foods/{food_id}; BODY_KEYS for PATCH /api/me/settings + user.units.labs,
  user.units.weight, body.weight_alarm, body.bp_goal, guidance; MAX_KEYS_BODY 16384. tests/test_app_gateway.py pins it.
- Swift ServerAPI.swift: the same routes; `Route.matches` with a `{food_id}` digits segment; PATCH settings bodyKeys widened.
  ServerAPITests.swift and tests/test_ios_app.py (list pinned, every gateway route on ALLOWED, BODY_KEYS equal).
- Phone: server_sync.js sends `meals` (only when `mealsReady`), foods used by meals, `refOf`/`_mealFields`, USDA/OFF from the server
  by keys (mark f:'server'), one ID per row (mark `c` = row.client_id until sent). server_changes.js: `meal` kind, catch-up read from 0
  (`meals`, `mcursor`), name match of unsent meals, `mealsReady`, `needsReview`, `_touched`. New js/mock/server_account.js (profile,
  settings, preferences from the server; edits through the gateway only; §8.7 point 5 card). New js/views/server_review.js (badge
  "N to review"); today.js "needs review" mark; settings.js profile card, account line, hint text.
- Tests: tests/js/server_account.mjs (+ --relay) and tests/test_server_account_phone.py (real routes, allow-list enforced, plays web);
  e2e sync_walk additions (profile/target/setting from server, saved meal arrives, badge, Today mark, badge opens cards).
- Docs: ARCHITECTURE (sync table `meals`, food refs, gateway list, Device mode bullets, tests), docs/push.md, handbook app/install.md,
  CHANGELOG (Added + Fixed), note 39 status and "as built".

## Checks
node tests/js/{server_sync,server_changes,server_services,server_lists,server_account,device_mode,run_vectors}.mjs;
pytest tests/test_server_*_phone.py tests/test_sync_meals.py tests/test_sync_feed.py tests/test_app_sync.py tests/test_app_gateway.py
tests/test_ios_app.py tests/test_settings_ui.py tests/test_device_ui.py tests/test_device_mode.py tests/test_preview_build.py
tests/test_security.py tests/test_offline_edits_ui.py tests/test_openapi_snapshot.py tests/test_auth_coverage.py tests/test_isolation.py;
python tools/e2e/device_mode.py --out <scratch>: 77 passed. Full `python -m pytest`: one failure (load order of the new script), fixed: server_review.js loads after feedback.js; test_frontend_shell, test_two_step_ui pass.

## Decisions
- Saved meals: no receipts (m037 CHECK allows six kinds; migrations are append-only); found by client_id.
- The card the coordinator asked about: note 39 describes only §8.7 point 5 (profile and targets differ at the first sync); built.
- Edits to server-owned data stay with the server while offline (needServer uses the saved account, not the live `about` state).
- guidance id lists (repeat_ok_*, hidden_usual_meals) are phone-local; never sent, never overwritten from the server.

## Files touched outside my own (for the merge)
- app/static/js/mock/{foods,meals,labs,symptoms,body,lists}.js: NOT touched.
- app/app_gateway.py: ALLOWED (8 routes appended after list-sync), BODY_KEYS settings keys, MAX_KEYS_BODY.
- ServerAPI.swift / ServerAPITests.swift / tests/test_ios_app.py: merged both sides, then step-8 routes after /push/v1/match.
