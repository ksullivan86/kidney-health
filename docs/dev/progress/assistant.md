Status: complete (step 2, part C: the Ask chat can save, with a trust setting; steps 1 and 2 part A below are complete too; step 2, part B (voice) is complete too, see its section at the end)

# Assistant, step 2, part C: the Ask chat can save, with a trust setting

Spec: `docs/dev/plans/assistant-step2.md` "Part C". Worktree branch `worktree-agent-a447dbaad57f4d90f`, fast-forwarded to
the branch that holds part A (`935930c`); commit only: no push, no PR from here. Migration is **step 13** (the voice work
uses 14). Keep `ask.js` edits in self-contained functions (the voice agent hooks into the same file).

## Plan (sub-steps; each ends with a commit)

1. Backend: admin switch + `trust` in the person's `ai` setting (registry, JS twin, vectors), schema step 13
   (`assistant_ask_keys`), `Asker` identity in `app/mcp/tools.py`, `app/ai/chat_save.py`, loop changes in `chat.py`,
   prompt + `PROMPT_VERSION` 2026-10-15.2, `routes.py` (body fields, effective trust, status, me view, audit of the choice).
2. Backend tests (`tests/test_ai_chat_save.py`, `tests/test_migration_m013.py`, isolation matrix, prompt pin).
3. UI: Settings -> AI trust choice + warning sheet (`ai.js`, `index.html`), Ask screen cards (`ask.js`, `ask.css`),
   activity-log labels (`settings.js`), static UI tests.
4. `tools/e2e/ask.py`, docs (ARCHITECTURE, ai.md, assistant.md, privacy, handbook AI page, CHANGELOG, ROADMAP).
5. Full test run; final report.

## Done

* Sub-step 1 + 2 (backend and its tests): see the plan. Verified: `tests/test_ai_chat_save.py` (55 tests),
  `tests/test_migration_m013.py`, `tests/test_migration_m012.py` (now "step 12 and any later step"),
  `tests/test_ai_chat.py` (two assertions updated: `safety_check` is the never-offered tool; the prompt offers the saving
  tools; the small-budget test uses 6500 tokens because the system prompt grew), `tests/test_ai_prompts.py` (pin recorded
  with `KH_UPDATE_SNAPSHOTS=1`), `tests/test_isolation_v03.py` (matrix row for `assistant_ask_keys`), the settings vectors
  (`node tests/js/run_vectors.mjs`, `python tests/data/gen_settings_vectors.py --check`).

* Sub-step 3 (UI): Settings -> AI ideas "How much do you trust the assistant?" with the warning sheet (`ai.js`
  `confirmTrust`, `trustPart`; `#sheet-ai-trust` in `index.html`; the focus starts on "Keep asking me"), the Ask screen
  (`ask.js` section "Saving from the chat": trust line, confirm card, saved card with Undo, questions; `#ask-trust`),
  `ask.css`, the activity-log label (`settings.js`), the demo's `/api/me/ai` mock keys, the Settings intro sentence
  ("It cannot ... save anything by itself" became "by default nothing is saved until you press Save"; its test updated).
  Verified: `tests/test_ask_ui.py` (7 new static tests), `tests/test_ai_setup_intro.py`, `tests/test_settings_ui.py`,
  `tests/test_ai_ui.py` and the other shell tests; `python tools/e2e/ask.py` (104 checks: confirm card + Save as eaten +
  Undo + Cancel, trusted conversation, New conversation ends trust, always, the warning sheet in Settings with "Keep
  asking me" and "I understand, trust it", the activity row; 375 px light and 1280 px dark, no sideways scroll, no console
  errors) after teaching its fake provider a `log_food` call.

* Sub-step 4 (docs, eval, e2e): ARCHITECTURE ("Saving from the chat", schema step 13, routes, registry, frontend, file
  ownership), `docs/ai.md` (G12 reworded, G16, "Saving from Ask", the switch), `docs/assistant.md` (the trust table),
  `docs/privacy.md`, the handbook AI page, CHANGELOG, ROADMAP status line, the plan file (Part C), `tools/e2e/README.md`;
  `scripts/ai_eval.py --chat` has a tenth case ("Log a banana for breakfast" must be a card, nothing saved).
* Sub-step 5 (checks): full suite `python -m pytest -q -x -p no:cacheprovider` exit 0 (no network); the UI tests re-run on
  the final JS (247 passed); `python tools/e2e/ask.py` 108 checks pass (it also checks that Today shows a trusted save and
  stops showing it after Undo); `python tools/e2e/parity.py --sections 14` 15/15; `node tests/js/run_vectors.mjs` and
  `gen_settings_vectors.py --check` current. Not run: the live `scripts/ai_eval.py --chat` (owner, with a live model; the
  prompt is now 2026-10-15.2), `mkdocs build --strict` (mkdocs not installed; CI builds the handbook).

## Next

* Nothing pending for part C. Owner: the live `--chat` run, and the decisions below. Other agents: the `export.json`
  import must not restore `trust` other than `ask` (it is a field of the exported `ai` setting).

## Decisions (and why)

* **Trust is the `trust` field of the person's `ai` setting**, not a column: no schema change for the choice itself.
  Step 13 is only the duplicate guard's table (step 11's table needs a token).
* **`conversation` needs the stored choice and the page's claim**; the page alone (or `always` sent by a page) never grants
  anything. A page claiming `trust: "always"` is a 400.
* **Ask mode ends the loop at the first resolvable save** with fixed app text; the model's words are not used because
  nothing was saved and a model could say it was.
* **After a repeat of a request's save the model may not save again in that message** (a non-deterministic model replaying a
  retried request must not turn it into a second, different save).
* The audit row of a food save by Ask has no target (`target_type` null); a recipe's targets the meal like the MCP one.
* `PATCH /api/me/settings` with an `ai` object lacking `trust` resets it to `ask` (safe direction) and is audited.
* **Undo and the Save press share one card.** After a pressed Save the card becomes a "Saved" card with Undo (same as a
  trusted save); a save or an Undo makes Today, Plan and Trends reload their day (`KH.ai.refreshDayCaches`).
* **The per-conversation grant is one tap without the warning sheet** (the sheet comes when the person chooses the option in
  Settings; the grant button's label and the line under it say what it does). Changing the choice in Settings ends a grant.
* **Residual risk, not closed in code**: a food name from USDA or Open Food Facts reaches the model as untrusted data (cleaned,
  cut, escaped, marked); in a trusted mode a prompt injection could still make it ask for a save. Mitigations: off by default,
  warning, at most 2 saves a message, all or nothing, Undo, the activity row, and the rule that a save follows the person's
  own request (prompt only: a code check for "the person asked to log" would be a brittle word list).
* Trust is not reset when the provider changes or a consent is withdrawn (withdrawing the chat consent stops Ask altogether).

## Checks

    python -m pytest -q -x -p no:cacheprovider tests/test_ai_chat_save.py tests/test_migration_m013.py tests/test_ai_chat.py
    node tests/js/run_vectors.mjs

---


# Assistant, step 2, part A: the in-app Ask chat (text)

Spec: `docs/dev/plans/assistant-step2.md`. Worktree branch `worktree-agent-a231292c156f5e6db` (based on `main` at
`0a54b19`). Commit only: no push, no PR from here.

## Plan (sub-steps; each ends with a commit)

1. Plan document and this note (done).
2. Backend core: migration step 12 (`chat` consent purpose), settings key `ai.chat_enabled` (registry, JS twin,
   vectors), `app/ai/chat.py` (step protocol, answer checks, numbers), prompt text and `PROMPT_VERSION`, the route
   `POST /api/ai/chat`, status/consent changes.
3. Backend tests.
4. Ask screen (`views/ask.js`, `css/ask.css`, tab, consent text, demo note) and its static test.
5. `scripts/ai_eval.py` chat cases; docs (ARCHITECTURE, ai.md, assistant.md, privacy, handbook, CHANGELOG, ROADMAP).
6. Full test run, Chromium check, final report.

## Done

* Sub-step 1 (plan) committed.
* Sub-step 2+3 (backend and its tests): schema step 12 (`m012_ai_consent_chat.py`: `ai_consents` rebuilt so `chat` is a
  purpose), `ai.chat_enabled` (registry, JS twin, vectors, admin list), `app/ai/chat.py` (history, step loop, text
  policy, dose check, number check, lab note, "From the app" figures), `ChatStep` in `schemas.py`, chat prompt text in
  `prompts.py` (`PROMPT_VERSION` 2026-10-15.1, pin recorded), `guard.MEDICINE_NAMES` shared with the blocklist (its
  pattern text is unchanged), `POST /api/ai/chat` in `routes.py`, status `features.chat` and `consent.chat`.
  Verified: `tests/test_ai_chat_checks.py` (pure), `tests/test_ai_chat.py` (route, 48 tests), `tests/test_migration_m012.py`,
  the related existing AI, settings and migration test files, `node tests/js/run_vectors.mjs`.

* Sub-step 4 (Ask screen): `views/ask.js`, `css/ask.css`, the sixth tab and `#view-ask` in `index.html` (tab hidden until
  `GET /api/ai/status` says `features.chat`; always shown in the demo with a note and no input), `core.js` (`TAB_VIEWS`,
  arrow keys skip a hidden tab), `main.js` (refresh after sign-in), `ai.js` (`api.chat`, `cardEl`, the `chat` consent text,
  "Never sent" line, Settings list/withdraw labels, `forget()` refreshes the tab), `sw.js` shell list, `tools/e2e/sandbox.py`
  and `parity.py` (the chat route is 404 while AI is off on both sides). Verified: `tests/test_ask_ui.py`, the UI shell
  tests, `python tools/e2e/parity.py --sections 14` (15/15), and a Chromium script (scratchpad `ask_check.py`) against a
  real server and a fake provider at 375 px light and 1280 px dark: tab shown only with the chat on, Shift+Enter, consent
  sheet before any send, answer with "From the app", a low answered without the provider, a withheld answer, New
  conversation, arrow keys, no sideways scroll, no console errors; the demo at 320 and 375 px (tab fits, note, no input).

* Sub-step 5 (eval and docs): `scripts/ai_eval.py --chat` (nine chat cases, `chat_pass_rate` and
  `chat_no_unsafe_text` gates, only with the flag; `tests/test_ai_eval_script.py` drives it with a scripted model), the
  Settings AI intro no longer says "It cannot chat", ARCHITECTURE ("Ask chat", schema step 12, route table, file map,
  frontend), `docs/ai.md`, `docs/assistant.md` ("The Ask screen"), `docs/privacy.md`, `docs/deployment.md`, the handbook AI
  page and configuration page, CHANGELOG, ROADMAP status line. Handbook/doc tests pass.

* Sub-step 6 (checks): `python -m pytest -q -x -p no:cacheprovider` all pass (3825 tests, exit 0, no network; run with the
  step-11 stand-in described below); `node tests/js/run_vectors.mjs` and `gen_settings_vectors.py --check` current;
  `python tools/e2e/ask.py` (new harness, 38 checks: 375 px light and 1280 px dark, demo at 320 and 375 px), `python
  tools/e2e/parity.py --sections 14` (15/15), `python tools/e2e/sandbox.py --only top-phone-light-none` (0 issues after
  teaching its ready-selector the Ask view), `python tools/e2e/mcp_smoke.py` (26/26). Not run: `mkdocs build --strict`
  (mkdocs is not installed; CI's handbook job runs it), the live `scripts/ai_eval.py --chat` (owner, with a live model).

## Next

* Part B (voice), saving from the chat ("Add to plan"), recipe pages in `check_meal`: see `dev/plans/assistant-step2.md`.

## Dependency on another change (migration numbering)

The coordinator told this branch (during the work) that another change merges first and adds schema step 11
(`m011_assistant_request_keys.py`), so this part's migration is **step 12** (`m012_ai_consent_chat.py`). This branch
therefore has a gap at 11 on its own (`app.migrations` refuses a gap) and needs that change merged or rebased in first.
Verified here with an uncommitted no-op stand-in for step 11 (removed afterwards): the full suite passes with it. The
tests build their "before" database with `steps()[:11]`, whatever step 11 does. Overlapping files (their edits and mine are
in separate paragraphs): `ARCHITECTURE.md` (migration table row 12 and the new "Ask chat" sections), `CHANGELOG.md`, this note.

## Decisions (and why)

* **Schema step 12.** `ai_consents.purpose` had a CHECK for `text` and `photos`; the only way to store a `chat`
  consent is to rebuild the table. Owner to confirm that one schema change is acceptable.
* The activity rows keep no request or response bodies (`keep_bodies` false), whatever `ai.audit_retention_days`
  says: "the server stores no transcript". One row per model call (step, tool name, outcome).
* `cards` is a list: a message with emergency and low wording gets both, so the Treating a low card is never dropped.
* Provider mode `json_schema` is sent as `json_object` for the chat (free-form tool arguments cannot be a strict schema).
* Links in an answer are removed (not withheld); an answer that is nothing but a link is an error.
* A message that matched a safety rule (and the answer that followed it) is left out of the history sent on later turns.
* The number check is unit-agnostic (a number with a unit must be in the results or the person's words; no conversion),
  and an exact rounding tie (22.5) accepts both roundings.
* Validation errors are 400 like the rest of the app (not 422).

## Checks

    python -m pytest -q -x tests/test_ai_chat*.py
    node tests/js/run_vectors.mjs

---


# Assistant follow-up: duplicate guard (`request_key`) and admin revoke of a person's tokens

Status: complete (both changes done and tested; not pushed, no PR from here: the caller opens it). Worktree branch
`worktree-agent-aca1796d63b29f262`, based on `main` at `0a54b19`.

## What

1. `log_food` and `save_recipe` take an optional `request_key` (8-64 of `A-Za-z0-9_-`). A second call by the same
   token with the same key within 24 hours saves nothing and answers `{saved: true, duplicate: true, ...}` with what
   the first call saved, read from the database again for that person (edits show; deleted rows are left out with a
   note; if none is left: `saved: false, duplicate: true`, still nothing saved). Schema step 11 `assistant_request_keys`
   (`m011_assistant_request_keys.py`): `key_hash` = SHA-256 of token id + key, `user_id`, `token_id`, `tool`,
   `saved_json`, `created_at`. Code: `app/mcp/request_keys.py`, `app/mcp/tools.py` (`earlier_save`, `AlreadySaved`,
   `logged_again`, `recipe_again`, `logged_answer`, `recipe_answer`).
2. Server administration -> People -> Manage -> "Revoke assistant tokens (n)" (switch on and n > 0; inline confirm):
   `POST /api/admin/users/{id}/revoke-tokens` (`RecentAdmin`, 404 unknown id, `api_tokens.revoke_all(reason="admin")`
   which audits `api_token.revoked`), `assistant_tokens` (active count) in `GET /api/admin/users`; demo twin in
   `js/mock/auth.js` (always 0, route answers `{revoked: 0}`).

## Decisions (and why)

* The key is written in the save's own transaction (`write_once`), so a failed or unresolved save stores no key. A
  retry that raced the first call is caught inside the write lock (`AlreadySaved` rolls back and answers as a duplicate).
* The same key on the other saving tool is an `isError` result (the model reused a key for something else), never a
  silent mix-up. The items of a repeat are not compared with the first call's; the note tells the model to use a new
  key if it was a different save.
* All gone -> `saved: false` (not `true`) with `duplicate: true` and a note: the model must not tell the person the
  food is in the log when it is not. A new key saves.
* `saved_json` also keeps `added_to_foods` (and, for a recipe, `servings_made`, `source_url`) so the repeat's answer is
  as complete as the first (the model may never have seen the first answer, which is why it retried).
* The admin route reuses `revoke_all` (one audit row `api_token.revoked`, actor the admin, target the person, reason
  `admin`) rather than a new audit action; it works while the switch is off; zero active tokens writes no row.
* `tests/test_migration_m010.py` now expects "step 10 and any later step" (like `test_migration_m007.py`) because step 11
  exists; the released step itself is untouched.

## Verified

    python -m pytest -q -p no:cacheprovider tests/test_mcp_write.py tests/test_migration_m011.py tests/test_api_tokens.py \
        tests/test_auth_coverage.py tests/test_auth_modes.py tests/test_isolation_v03.py tests/test_settings_ui.py
    node tests/js/run_vectors.mjs
    # real browser (scratchpad script admin_revoke_e2e.py, Chromium from /opt/pw-browsers): 375x812 light and
    # 1280x800 dark with the switch on (button with count, confirm, revoke, tokens revoked, activity entry, no console
    # errors, no sideways scroll); switch off: no button.

## Next (not done here)

* Nothing pending for these two changes.

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

# Assistant, step 2, part B: voice for the Ask chat

Status: complete (full suite passed, exit 0, after merging `origin/main` 8936b29: numbers in "Checks"). Worktree `agent-aa91a184a25b62836` (branch
`worktree-agent-aa91a184a25b62836`, first based on `main` at `ec7f670`, then merged with `origin/main` 8936b29). Commit only: no push, no PR from here. Spec:
`docs/dev/plans/assistant-step2.md` ("Part B: voice") and the roadmap item "An assistant you can talk to".

## Design (decided by the owner: least trust)

* Speech to text is a server-side provider, off by default: `STT_BASE_URL` (ends in `/v1`, like `AI_BASE_URL`),
  `STT_MODEL`, `STT_API_KEY[_FILE]` (optional, write-only), `STT_TIMEOUT_S`, `STT_DAILY_LIMIT`, `STT_MAX_AUDIO_BYTES`,
  and the admin switch `ai.voice_enabled` (`AI_VOICE_ENABLED`). The call goes through `send_json` (the SSRF transport)
  with scope `shared`: a LAN host only when `AI_PRIVATE_HOSTS` lists it. The browser's own speech recognition is never
  used (Chrome sends that audio to Google, Safari to Apple); `tests/test_ask_voice_ui.py` keeps every name of it out.
* `POST /api/ai/transcribe` (`app/ai/voice.py`, logic in `app/ai/stt.py`): 404 before the body unless AI, Ask and voice
  are on and configured; 503 if the person cannot use AI; 415/413 by headers; 409 consent `voice`; then the AI slot,
  the body (in memory, at most 1.5 MiB), the first bytes must match the type (400), a WAV over a minute is 413, the
  daily limit (429), the multipart call, `{text}` cleaned by the chat text policy (<= 2000). Audio and transcript are
  never stored or logged; one `ai_audit` row (feature `voice`, no bodies, a length bucket and the outcome).
* Consent: purpose `voice` in `ai_consents` (schema step 14). The row has `host` = the transcription host and
  `provider_id` = the AI provider that serves the person (the Ask screen needs one; the table's foreign key needs a
  row). A changed host, provider or wording asks again. Settings -> AI shows it as "Speech to text". Owner to confirm.
* Daily limit: env `STT_DAILY_LIMIT` (default 100, 0 = unlimited), counted in `ai_usage` under provider 0 with
  `key_scope = 'own'` so the shared AI calls (`ai.shared_daily_limit`) never include voice. Owner to confirm.
* Browser: `js/views/ask-voice.js` + `css/ask-voice.css`, two hook lines in `ask.js` (`KH.askVoice.sync(available)` in
  `refreshTab`, `KH.askVoice.speak(answer)` after an answer), `KH.ai.askConsent` exported from `ai.js`. Consent comes
  before the microphone is opened; the transcript goes into the question box and is never sent by the code.

## Done (each verified as noted)

* Sub-step 1, server: `AiEnv.stt_*` and `Settings.max_audio_bytes` (`app/config.py`), `send_json(content=...)`
  (`app/ai/transport.py`), `app/ai/stt.py`, `app/ai/voice.py` (route, `GET /api/admin/ai-providers` -> `voice`,
  `POST /api/admin/ai-voice/probe`), status `features.voice` + `voice` + `consent.voice`, consent give/withdraw for
  `voice`, `ai.voice_enabled` (registry, JS twin, vectors, admin list), `Permissions-Policy: microphone=(self)`,
  `app/migrations/m014_ai_consent_voice.py`. Verified: `tests/test_ai_voice.py` (83), `tests/test_migration_m014.py`,
  the pinned `tests/test_migration_m012.py`, `tests/test_security.py`, `tests/test_ai_routes.py`, `tests/test_ai_chat.py`,
  `node tests/js/run_vectors.mjs`, `python tests/data/gen_settings_vectors.py --check`.
* Sub-step 2, browser: the files above, `index.html`, `sw.js`, the voice consent text, the activity row and the admin
  Speech to text panel (with "Test transcription") in `ai.js`; fixed a stray "null" in the consent sheet when there is
  no request to preview. Verified: `tests/test_ask_voice_ui.py` (22), `tests/test_ask_ui.py`, `tests/test_ai_ui.py`,
  and `python tools/e2e/ask_voice.py` in Chromium (82 checks: fake audio device, fake transcription server, 375 px light and
  1280 px dark, consent before recording, the Recording row, multipart reaches the server, words in the box and nothing
  reaches the AI before Send, Discard / leaving the tab / Escape release the microphone, the 60 s stop with the page's
  clock moved, a blocked microphone, no MediaRecorder, read aloud with a stubbed engine and only device voices, the admin
  panel and test, the demo, no sideways scroll, no console errors, neither transcript nor key in the server log).
* Sub-step 3, overlay and docs: `deploy/compose.stt-whisper.yaml` (+ `tests/test_deploy_stt.py`), ARCHITECTURE ("Voice
  input", schema step 14, routes, settings, env, file ownership), `docs/ai.md`, `docs/assistant.md`, `docs/privacy.md`,
  `docs/network-allowlist.md`, `docs/deployment.md`, `deploy/README.md`, the handbook AI / configuration / network pages,
  CHANGELOG, ROADMAP, the plan file. Verified: `tests/test_deploy_stt.py`, `tests/test_deploy.py`,
  `tests/test_handbook_content.py`.

## Migration numbering

Step 14 follows the real step 13 (`m013_assistant_ask_keys.py`, part C) since the merge of `origin/main` 8936b29; no stand-in is
needed any more. `m014` rebuilds `ai_consents` from its stored definition, so it does not depend on what 13 did (13 added a table
only). `test_migration_m012.py` takes main's version (it migrates to `db.SCHEMA_VERSION`) with the one test that needs a
12-step database pinned to `steps()[:12]`.

## Decisions and why

* The overlay is not in CI's `compose config` lint: its digest is a marked placeholder (an invalid reference). Add it when
  the owner pins a verified digest.
* The overlay does not set `AI_VOICE_ENABLED`: the admin turns voice on in Server administration (an env value would lock it).
* Read aloud shows whenever the Ask composer is available (it needs no server), the microphone only with `features.voice`.
* Validation errors of the route are 400 like the rest of the app (not 422).

## Not done / for the owner

* Verify the Speaches image tag and digest (`crane digest`), the HF cache path and health check in the overlay, with a real
  container; try the microphone on a real iPhone (Safari) and an Android phone (the first-tap consent then record
  sequence calls `getUserMedia` a moment after the tap).
* `mkdocs build --strict` not run (mkdocs is not installed); CI's handbook job runs it.

## Checks

    python -m pytest tests/test_ai_voice.py tests/test_migration_m014.py tests/test_ask_voice_ui.py tests/test_deploy_stt.py -q
    node tests/js/run_vectors.mjs
    python3 tests/data/gen_settings_vectors.py --check
    python tools/e2e/ask_voice.py

After merging `origin/main` 8936b29 (export import #37, Ask saving with a trust setting #38, step 13): the full suite 4125 passed,
exit 0; `node tests/js/run_vectors.mjs` and the settings generator `--check` current (39 keys); `tools/e2e/ask_voice.py` 82/82;
`tools/e2e/ask.py` 108/108 (one run under a parallel pytest load failed a check that reads the server right after a click: a race
in that harness, green when run alone). Read aloud also speaks the fixed `confirm_save` line (kind added by part C).
