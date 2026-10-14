# Assistant, step 1: the app as an MCP server for an external chat front end

Status: in progress (2026-10-14). The owner's main AI wish is "an assistant you can talk to" (`docs/ROADMAP.md`,
Ideas from the owner). Step 1 there: a per-person API token, a "check this meal" back end, exposed as an **MCP
server**, so a chat client (Open WebUI with voice, or a Hermes Agent profile *with* tools) can ask the app for every
number. Design note 04 already planned this as H5 (§3.3, §9: "Streamable HTTP, a per-user bearer token, read-only
tools that return guarded results only"). Budget for this step: about 5M tokens, one PR per part below.

## Rules that do not change

* Numbers never come from a model: every food is resolved by the app (own foods and the built-in list, then USDA
  FoodData Central when a key is set) and every total is computed by the app. Unknown potassium or phosphorus stays
  unknown (null with a count), never 0.
* No insulin or medicine doses, no medicine advice, no lab interpretation in anything the app returns. Treating a
  low is never blocked, delayed or warned against.
* Off by default. Nothing new is reachable until an admin switches the assistant on.
* Personal data never leaves the server except in answers to the person's own token.

## Part A: assistant access tokens (PR 1)

* Admin switch `assistant.enabled` (settings registry, bool, default false, env `ASSISTANT_ENABLED`), shown in
  Server administration → Server settings with the AI switches. Off: no token can be made or used, `/mcp` is 404.
* Table `api_tokens` (new migration step 10): id, user_id (FK, cascade), name (1–60 chars), token_hash
  (SHA-256 of the whole token; tokens carry 32 random bytes), prefix (the first 12 characters, for display),
  scopes (text; only `assistant:read` in this step), created_at, last_used_at, expires_at, revoked_at.
* Token format `kha_` + 43 base64url characters. Shown once at creation (secrets are write-only), never again.
* Routes (cookie session + CSRF, like every `/api/me` route): `GET /api/me/tokens` (list: id, name, prefix,
  scopes, created, last used, expires, revoked), `POST /api/me/tokens` {name, expires_in_days: 30|90|365}
  → the token once, `DELETE /api/me/tokens/{id}` (revoke; another person's id is 404). At most 5 active tokens.
* A bearer token is accepted **only** by the assistant surface (`/mcp` in part B), never by the rest of `/api`, which
  stays cookie-only. One dependency, for example `app/auth/tokens.py: assistant_user(request) -> User`, checks:
  the switch is on, `Authorization: Bearer kha_…`, hash match, not revoked, not expired, the person is active (not
  disabled or deleted, not waiting for a password change), scope. Failure: 401 with `WWW-Authenticate: Bearer`,
  the same body for every reason. `last_used_at` is written at most once a minute. Failed attempts count toward the
  existing sign-in throttle for the client address.
* A password change, a password reset by an admin, disabling or deleting the person revoke all their tokens.
* Activity log: token created, revoked (by the person, or by one of the events above).
* Settings → **Assistant access** card (only when the switch is on): what a token allows in one sentence, the
  list with Revoke (inline confirm), and New token (name, expiry) showing the token once with Copy and "It is not
  shown again". The demo says it exists in the installed app (no mock tokens).
* Tests: token lifecycle, hash at rest (no plain token in the database), expiry, revocation, isolation (another
  person's token id is 404), disabled person, password change revokes, every other `/api` route ignores a bearer
  header (`tests/test_auth_coverage.py`), switch off. Docs: ARCHITECTURE (contract), `docs/accounts.md` or a new
  `docs/assistant.md`, CHANGELOG.

## Part B: the MCP server, read-only (PR 2)

* `POST /mcp`: MCP Streamable HTTP transport, JSON-RPC 2.0, answers with `application/json` (no SSE needed),
  stateless (no `Mcp-Session-Id`). Protocol versions 2025-06-18 and 2025-03-26 (answer the client's if supported,
  else the newest). Methods: `initialize`, `notifications/initialized` (202, no body), `ping`, `tools/list`,
  `tools/call`; anything else is the JSON-RPC "method not found" error. `GET`/`DELETE /mcp` → 405. Batch arrays
  are refused. An `Origin` header that is not this server's origin → 403 (the spec's DNS-rebinding rule). Body
  limit as the rest of the API. Bearer token from part A on every request; a per-token rate limit (60 calls a
  minute).
* Tools, all read-only, each answer a structured JSON object (`structuredContent`) plus the same as text:
  * `get_today(date?)`: the person's targets (with which are "about"), eaten and planned totals, what is left of
    each limit, unknown potassium/phosphorus counts, per-meal carbohydrate goals only when the profile has diabetes,
    dialysis day if any. Uses the same functions as Today (`app.log.day_figures`), never a copy of the maths.
  * `search_foods(query, limit≤10)`: the person's foods and the built-in list (the existing search), then USDA when
    a key is set; each result with id, name, source, serving and nutrients (unknown stays null).
  * `check_meal(items: [{food: text, amount?: number, unit?: text, food_id?: id}], date?, meal?)`: resolve each item
    (food_id first, else the best search match, with the alternatives named so the model can ask), scale by the
    amount (servings, grams, or a household measure the food knows), return per item and in total, the existing
    per-serving warnings (`app.nutrients` rules) and what the day would look like if it were eaten (projected,
    like a planned entry), unresolved items listed with what to ask the person. Nothing is saved.
  * `safety_check(message)`: rule-based only, for the system prompt to call on each message: low-glucose wording
    returns the Treating a low card from `app.guidance.hypo` (the person's own hypo_dose_g, the existing cited
    text) and "treat first, then talk"; emergency wording returns the Get help now page link. Otherwise "none".
* Every tool result carries `source: "kidney-health"` and a one-line reminder that numbers must be fetched again
  after any change; no tool returns doses, medicine advice or lab interpretation.
* Tests: protocol (initialize, list, call, errors, Origin, 405, batch), auth (no/invalid/revoked token, switch off,
  another person's data never appears), tools (unknown stays unknown, kidney-only profile has no meal carb goals,
  safety_check wording, amounts and household measures), rate limit. A small `tools/e2e/mcp_smoke.py` that speaks
  the protocol to a real server.
* Docs: `docs/assistant.md` (switch on, make a token, connect **Open WebUI** (MCP tool server, voice) and a
  **Hermes Agent** profile with `tools.include`, the system prompt template: call `safety_check` on every message,
  call the tools for every number, never give doses, the memory rule from the ROADMAP), ARCHITECTURE, the handbook's
  AI page (a short "Talk to an assistant" section for people), CHANGELOG, ROADMAP.

## Part C, if the budget allows: writes with a separate scope (PR 3)

A second scope, `assistant:log`, ticked when the token is made: `log_food` (items as in `check_meal`, meal, date,
`status: planned|eaten`, returns what was saved) and `save_recipe` (name, ingredients, servings, source URL →
a saved meal). Foods found in USDA are added to the person's list as a side effect, as the ROADMAP decided. Every
write goes to the activity log with the token's name.
