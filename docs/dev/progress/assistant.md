Status: complete (part C: the `assistant:log` scope, `log_food`, `save_recipe`; parts A and B below are complete)

# Assistant, step 1, part C: writes with a separate scope (`assistant:log`)

Spec: `docs/dev/plans/assistant-step1.md` part C. Worktree branch `worktree-agent-a43b80dd0f8d1c1d8`. Its HEAD was
only part A (`419e349`); part B (`claude/adoring-sagan-th5swr` at `78bbdca`, rebased on it) was fast-forwarded in, and
the final B progress note taken from `ab319ad` (same tree otherwise). Commit only: no push, no PR from here.

## Plan (files)

1. Scope: `app/auth/api_tokens.py` (`LOG`, `scopes_for`, log implies read), `TokenCreate.can_log` (`schemas.py`),
   Settings card (`index.html`/`settings.js`/`settings.css`): checkbox + "Read only" / "Read and save".
2. `/mcp` (`app/mcp/server.py`): `tools/list` hides the write tools without `assistant:log`; calling one is an
   `isError` result; `WRITE_INSTRUCTIONS` in `initialize` for a saving token.
3. `app/mcp/tools.py`: `fdc_id` on items (USDA foods: `check_meal` reads them, `log_food`/`save_recipe` add them to the
   list first); `place_item`/`place_items` (shared by the three tools); `log_food`, `save_recipe`; `write_once` (one
   `BEGIN IMMEDIATE` transaction: USDA foods, entries or meal, audit, commit; any failure rolls back everything).
4. Shared code, not copies: `app.log.insert_logged` (was `_insert_logged`), `app.meals.insert_template`,
   `app.foods.add_usda_food` (the import route now calls it), `foods.usda_record`, `fetch_user_usda_food`,
   `usda_unsaved_row`.
5. Audit: `assistant.food_logged`, `assistant.recipe_saved` (user-visible; details: `via` = token name, counts).
6. Tests: `tests/test_mcp_write.py`, scope tests in `tests/test_api_tokens.py`; `tools/e2e/mcp_smoke.py` round trip.
7. Docs: `docs/assistant.md`, ARCHITECTURE, handbook `app/ai.md`, privacy, CHANGELOG, ROADMAP; `ASSISTANT_ENABLED` in
   `deploy/` examples.

## Decisions (and why)

* A saved meal has no servings count: `save_recipe` stores the whole recipe's ingredients and
  puts "Makes N servings. Source: URL" in the meal's `note` (no schema change). The note is limited to 1000
  characters by the meals API, so `source_url` is limited to 900 characters (the spec said 2048): a longer one would
  make the saved meal impossible to edit in the app. Owner to confirm.
* Recipe name: 1-60 characters (the spec); the meals API itself allows 200.
* No separate stricter rate limit for writes: they count in the shared 60/min per token. Reason: a rate limit must
  never get in the way of logging food eaten to treat a low.
* Saved entries are returned without `warnings`/`kidney_rating` (a food eaten to treat a low is never warned about).
* An `fdc_id` also finds a built-in food that carries it (search_foods shows `fdc_id` for those too).
* USDA results in `search_foods` now list `units` (they are usable by `fdc_id`); part B's test was updated.

## Done

* Scope and token creation (`can_log`), `/mcp` gating, `log_food`, `save_recipe`, USDA foods by `fdc_id`
  (`check_meal` reads them, the two writers add them first), audit events, Settings card (checkbox, "Read only" /
  "Read and save", activity labels), docs (assistant guide, ARCHITECTURE, handbook AI + settings pages, privacy,
  CHANGELOG, ROADMAP, deployment env rows), `ASSISTANT_ENABLED` in the Quadlet and k8s examples.
* Verified: `python -m pytest -q -x -p no:cacheprovider` all pass (exit 0, 3652 tests, no network);
  `tests/test_mcp_write.py` (45 tests: scopes, tools/list, all-or-nothing, null K/P, purpose "hypo" counted as Today
  counts it, another person's food_id, USDA add-then-log with a mocked FoodData Central, recipe visible to its owner
  only, activity rows, revoked token / switch off, 60/min counting saves); part A's scope test updated; part B's
  USDA `units` and `note` assertions updated; `node tests/js/run_vectors.mjs` passes and
  `gen_settings_vectors.py --check` is current (the switch's help text changed in the registry and its JS twin);
  `python tools/e2e/mcp_smoke.py` 26 passed (a real server: read-only refusal, `can_log` token, `log_food`,
  unresolved saves nothing, `save_recipe`, activity, revoked token 401); Chromium check of Settings → Assistant access at
  375 px light and 1280 px dark (scratchpad `assistant_card_c.py`): box unticked by default, both labels shown, no
  sideways scroll, no console errors.
* Not run here: `mkdocs build --strict` (mkdocs is not installed; CI's handbook job runs it).

## Next

* Nothing in part C. Later (not this PR): recipe pages in `check_meal`, step 2 (the in-app chat).

## Checks

    python -m pytest -q -x tests/test_mcp*.py tests/test_api_tokens.py tests/test_auth_coverage.py
    node tests/js/run_vectors.mjs

---


# Assistant, step 1, part B: the read-only MCP server (`POST /mcp`)

Spec: `docs/dev/plans/assistant-step1.md` part B. Worktree branch `worktree-agent-aeb3388c42b2e86af`, fast-forwarded
to part A's head `4df02c4` (the worktree had been created at `b2dd99a`, before part A). Commit only; the caller
integrates after part A's PR merges (no push, no PR from here).

## Plan (files)

1. `app/mcp/` (new package): `server.py` (route `POST /mcp`, 405 for GET/DELETE/PUT/PATCH, JSON-RPC 2.0 dispatch,
   switch → 404, bearer via `api_tokens.authenticate`, per-token limit `mcp` 60/min), `tools.py` (the four tools,
   argument validation, schemas), `measures.py` (household measures read from a food's `serving_desc`).
2. `app/log.py`: extract `day_summary(conn, request, user_id, day)` from `get_day` so `get_today` returns exactly the
   `GET /api/log?date=` numbers. `app/foods.py`: public `usda_search_records()` (raw FDC search items, no save).
3. `app/security.py` `CsrfMiddleware`: exact path `/mcp` (`BEARER_PATHS`) skips the cookie checks
   (`Sec-Fetch-Site`, `X-Requested-With`) but keeps the Origin rule on every method (403).
4. `app/main.py`: one import + `include_router` line.
5. Tests: `tests/test_mcp.py`; `/mcp` in `tests/test_auth_coverage.py` (bearer route contract);
   `tools/e2e/mcp_smoke.py` + `tools/e2e/README.md` + `HARNESSES` in `tests/test_e2e_tools.py`.
6. Docs: `docs/assistant.md` (switch on, Open WebUI, Hermes, system prompt template, honest limits), ARCHITECTURE
   (`/mcp` contract + ownership row), CHANGELOG, ROADMAP, handbook `app/ai.md` ("Talk to an assistant (optional)").

## Decisions (and why)

* Switch off → `404` for every method on `/mcp` (plan: "Off: … `/mcp` is 404"), checked before the bearer token.
* Origin rule in the CSRF middleware (one `origin_allowed`, PUBLIC_URL aware); the 403 comes before the switch.
* Rate limit counts every authenticated request (notifications too), key `token:<id>`; 429 + Retry-After.
* `MCP-Protocol-Version` header accepted, never refused (lenient; the server speaks 2025-06-18 and 2025-03-26).
* `check_meal` resolves against the app's foods only (own, built-in, linked); USDA results from `search_foods` are
  shown read-only (mapped with `map_usda_record`, never saved; part C saves). An uncertain match is not guessed:
  it goes to `unresolved` with alternatives and a question (a wrong guess would give wrong totals).
* Per-item warnings use the existing rules (`food_warnings`) on the item's amount, like a log entry.
* No `outputSchema` (optional in MCP; a strict client validating it is a risk with no gain here).

## Done

* Steps 1–4 (code): `app/mcp/{__init__,server,tools,measures}.py`, `app/log.py` `day_summary`, `app/foods.py`
  `usda_search_records`, `app/security.py` `BEARER_PATHS`, `app/main.py` (one import, one include; the 405 route is
  registered once per method so OpenAPI operation ids stay unique).
* Step 5: `tests/test_mcp.py` (43 tests), `BEARER_ROUTES` in `tests/test_auth_coverage.py` (the only write routes
  outside `/api`; 404 off, 401 with a cookie or nothing, 200 with a token), `tools/e2e/mcp_smoke.py` (port 8073) in
  the README and `HARNESSES`.
* Step 6: `docs/assistant.md` (switch on, tools, Open WebUI, a separate Hermes profile, system prompt template,
  check, honest limits, endpoint), ARCHITECTURE ("Assistant MCP server", request rules, layout, ownership),
  CHANGELOG (three audiences), ROADMAP status, `docs/privacy.md`, `docs/README.md`, handbook `app/ai.md` "Talk to an
  assistant (optional)" with source `ASSISTANT-DOC` (`python scripts/build_handbook.py` regenerated the sources).
* Matching rule refined after review: list-style names ("Juice, apple") are read the natural way round, a comma
  name is never matched in its written order ("Chocolate, milk" is not "chocolate milk"), the exact name with commas
  counts, "leave one word out" (≤ 6 words) only gives alternatives.
* Verified: `tests/test_mcp.py` 43 passed; `node tests/js/run_vectors.mjs` passes; `python tools/e2e/mcp_smoke.py`
  16 passed; the official MCP Python SDK 1.28.1 (`streamablehttp_client` + `ClientSession`, scratch script) talks to
  a real server: initialize 2025-06-18, tools/list, calls, isError, McpError for an unknown tool, ping.

* Final: `python -m pytest` 3603 passed (1 pre-existing warning: unused handbook sources).

## Next

* Part C (writes, scope `assistant:log`: `log_food`, `save_recipe`), not this PR.

---

# Assistant, step 1, part A: assistant access tokens

Spec: `docs/dev/plans/assistant-step1.md` part A. Branch `claude/adoring-sagan-th5swr`. Part B (`/mcp`) is
a later PR; it uses `app.auth.api_tokens.AssistantUser` (the bearer dependency built here).

## Plan (files)

1. `app/migrations/m010_api_tokens.py`: table `api_tokens` (cascade from users).
2. `app/auth/api_tokens.py`: create/list/revoke/revoke_all, `assistant_user` dependency (`AssistantUser`),
   router `GET/POST /api/me/tokens`, `DELETE /api/me/tokens/{id}`; registered in `app/auth/__init__.py`.
3. `assistant.enabled` in `app/settings_registry.py` (+ JS twin `js/engine/settings.js`, vectors regenerated).
4. Audit actions `api_token.created`, `api_token.revoked` (user-visible).
5. Revoke all on: own password change (`me.py`), reset link (`routes.py reset`), CLI reset/disable
   (`app/admin.py`), admin disable (`admin_api.py`), delete (`account.delete_user`, then cascade).
6. Settings → Assistant access card (`index.html` `#set-assistant`, `js/views/settings.js`), admin group.
7. Tests: `tests/test_api_tokens.py`, `tests/test_migration_m010.py`, coverage list + bearer-ignored test in
   `tests/test_auth_coverage.py`, isolation MATRIX entry.
8. Docs: ARCHITECTURE, `docs/assistant.md`, docs index, handbook settings page, CHANGELOG, deployment env row.

## Decisions (and why)

* Bearer accepted only by routes depending on `assistant_user`; `current_user` never reads `Authorization`.
* 401 + `WWW-Authenticate: Bearer realm="kidney-health"` (plus `error="invalid_token"` when a bearer credential
  was sent), one body for every reason. Failures with a presented credential call `throttle.ip_failure`
  (the sign-in per-IP limiter); a blocked address gets 429 + Retry-After like sign-in. Switch off or no
  credential: 401, not counted (nothing was guessed, no lookup happens).
* `POST /api/me/tokens` needs a recent password (`RecentUser`), like `PUT /api/me/keys` and the export: a
  stolen session cookie must not mint a year-long credential silently.
* Card visibility: shown when the switch is on; when off, shown to admins (hint where to switch it on) and to
  a person who still has active tokens (list + Revoke, no New form), hidden otherwise. Demo: a note only.
* Ended (revoked/expired) tokens stay listed 30 days, then the daily housekeeping deletes them.

## Done

* Steps 1-5 and the tests of step 7 (backend): `app/migrations/m010_api_tokens.py`, `app/auth/api_tokens.py`
  (router registered in `app/auth/__init__.py`), `TokenCreate` in `app/auth/schemas.py`, `assistant.enabled` in
  the registry + JS twin + admin GROUPS ("Optional AI"), audit actions, revocation hooks (me.py, routes.py reset,
  admin_api.py disable, account.delete_user, CLI reset --stdin / disable-user), `kha_` log redaction pattern.
  Verified: `tests/test_api_tokens.py`, `tests/test_migration_m010.py`, `tests/test_auth_coverage.py`,
  `tests/test_isolation_v03.py`, `tests/test_settings_ui.py` pass; vectors regenerated; node vectors pass.

* Step 6 (UI): `#set-assistant` in `index.html`, `renderAssistant` in `js/views/settings.js` (list, Revoke with
  inline confirm, New token form, token shown once via `linkBox(…, opts)`), activity labels, `.token-row` CSS.
  Verified in Chromium with the scratchpad script `assistant_card_e2e.py` (375x812, 1280x800, 1280 dark: create,
  copy, revoke, reload; member hidden while off; admin sees the off state; switch in the Optional AI group;
  no console errors, no sideways scroll). Static check `test_the_assistant_card_waits_for_the_server…`.
* Step 8 (docs): ARCHITECTURE (migrations row, identity rule, `/api/me` rows, ownership row, new section
  "Assistant access tokens"), `docs/assistant.md`, docs index, privacy, export README text, handbook
  settings-and-keys + self-hosting/configuration, deployment env row, compose pass-through + .env.example,
  CHANGELOG (users, operators, contributors).

* Verification (final): `python -m pytest` 3557 passed (1 pre-existing warning: unused handbook sources);
  `node tests/js/run_vectors.mjs` passes; `gen_settings_vectors.py --check` current; Chromium check of the card
  (scratchpad `assistant_card_e2e.py`) 0 failures; demo card (`?mock=1`) shows the note and makes no request;
  `tools/e2e/sandbox.py` 0 issues; `tools/e2e/regress.py --no-pytest --only 1280-dark` 121 passed.
  `mkdocs build --strict` not run locally (mkdocs not installed; CI's handbook job runs it).

## Next (part B, not this PR)

* `/mcp` route: `user: AssistantUser` (app/auth/api_tokens.py); 404 while `is_enabled()` is false; a per-token
  limit can key on `request.state.api_token.id`. Extend `docs/assistant.md` (connect Open WebUI / Hermes).

## Checks

    python -m pytest -q
    node tests/js/run_vectors.mjs
    python3 tests/data/gen_settings_vectors.py --check
