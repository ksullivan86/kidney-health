Status: complete (part A: assistant access tokens; part B, the MCP server, is the next PR)

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
