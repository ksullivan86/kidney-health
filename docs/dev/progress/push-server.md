Status: in progress (role push-server; the server half of design note 12)

# push-server: device tokens and POST /push/v1/body (server half)

Spec: `docs/dev/research/12-phone-push-tokens.md` §4.1, §4.2, §4.3, the server parts of §4.4, §5 and the server tests of §6.
Not in this task: Settings "Phone shortcuts" block, the "from a shortcut (name)" label, the handbook recipe, the browser walk
(`js/views/*.js`, `index.html`, `css/*`, `handbook/` are left alone; one exception, below).

## Done (and how it was verified)

1. Tokens (`app/auth/api_tokens.py`): second family `khd_` / `body:write`, `family` on `GET`/`POST /api/me/tokens`, per-family
   `MAX_ACTIVE`, family prefix + scope + switch checked before any lookup, `parse_scopes` never mixes families, `revoke_all` ends both,
   audit `family`, `active_counts(family)`, admin list gains `device_tokens`. Switch `push.enabled` (registry, `js/engine/settings.js`,
   settings vectors regenerated). `BEARER_PATHS` gained `/push/v1/body`, `khd_` redacted in logs.
   Verified: `tests/test_device_tokens.py`, `tests/test_api_tokens.py`, `tests/test_auth_coverage.py`, `tests/test_mcp.py`.
2. `app/body.py`: `context_for`, `is_watch_source`, `known_weight_marks`/`known_reading_marks` (the same-reading check, used by both batch
   routes), `via` in rows (LEFT JOIN on `api_tokens`), PUT clears `api_token_id`. `BodySourceKey` gains `shortcut`. Schema step 19
   (`m019_body_token.py`). JS twin: `engine/body.js` (SOURCES, `via`), `mock/body.js` (same-reading check in both batch routes).
   Vectors: `gen_body_vectors.py` gained `context_cases`, `watch_cases`, rows with `via`, 20 same-reading script steps;
   `run_vectors.mjs` checks `KH.appleHealth.contextOf` / `isWatchSource` against them; import vectors regenerated (source list text).
   Verified: `node tests/js/run_vectors.mjs`, `tests/test_body*.py`, `tests/test_migration_m018.py`, `tests/test_migration_m019.py`.
3. `app/push.py`: `POST /push/v1/body` and `DELETE /api/me/tokens/{id}/body-rows`; mounted in `app/main.py`. Verified: `tests/test_push.py`,
   `tests/test_device_tokens.py`.

## In progress / next

* Docs: ARCHITECTURE.md ("Device tokens and /push/v1", tokens and body sections, migration list), a docs page, CHANGELOG, deploy/env
  docs (`PUSH_ENABLED`), reverse-proxy paths.
* Full `python -m pytest -q`, `node tests/js/run_vectors.mjs`, `ruff check .`.

## Decisions and deviations (reasons)

* `views/settings.js` `GROUPS` got one line (`['Phone shortcuts', ['push.enabled']]`): `tests/test_settings_ui.py` requires every
  admin-editable key to be in a group, and the switch must appear on the admin page. Nothing else in `js/views/` was touched.
* Device list items carry `sent: {weights, readings}` (rows still in the log) so the Settings block can name the count before
  "Delete what it sent"; assistant items are unchanged. The list answer carries `family`.
* No `(user_id, date, time)` index: step 18's `(user_id, date)` serves the same-reading lookup (at most 30 rows per date).
* A pushed row edited with `PUT` becomes `manual` and leaves its token (`api_token_id = NULL`), so "Delete what it sent" never deletes
  something the person changed. Its `source_key` stays, so a re-run of the shortcut does not add it again.
* `at` also accepts a space instead of `T`, no seconds, a fraction of a second (dropped), and an offset as `-0400`/`-04`: the Health
  export's own form works. Digits are ASCII only (`re.ASCII`).
* An empty body (`{}` or no rows) is a 400. Non-JSON `Content-Type` is a 415. Other methods on the path are 405 (`Allow: POST`).
* Auth runs before the size check (a stranger gets 401, never 413); the 60/h limit counts every authenticated request.
* The audit action `body.token_rows_deleted` is also in `USER_VISIBLE_ACTIONS`; the Settings activity list shows the raw action name
  until the UI step adds its label.

## Commands that reproduce the checks

    python -m pytest -q                      # no pytest-xdist here: run it in the background
    node tests/js/run_vectors.mjs
    ruff check .
    python3 tests/data/gen_body_vectors.py --check
    python3 tests/data/gen_settings_vectors.py --check
    python3 tests/data/gen_import_vectors.py --check
