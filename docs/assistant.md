# The assistant: a chat assistant that reads your own numbers

The owner's main AI wish is an assistant you can talk to about food ("what fits in the rest of today?"), by text
or voice, that takes every number from the app instead of making one up. Step 1 connects a chat front end you
already use (for example Open WebUI, or a Hermes Agent profile with tools) to the app over MCP, with a personal
token. The plan, its rules and its parts are in
[`dev/plans/assistant-step1.md`](dev/plans/assistant-step1.md); the API contract is in `ARCHITECTURE.md`
("Assistant access tokens" and "Assistant MCP server").

**Where this stands.** Step 1 is in place: personal access tokens (part A) and a **read-only MCP server** at
`/mcp` (part B) with four tools. The assistant can read your numbers and check a meal; it cannot log anything.
Logging food and saving recipes through the assistant (part C, its own token scope) and a chat screen inside the
app (step 2) are later steps ([ROADMAP](ROADMAP.md), "An assistant you can talk to").

## Contents

* [Switch it on](#switch-it-on)
* [Access tokens](#access-tokens)
  * [For people using the app](#for-people-using-the-app)
  * [What ends a token](#what-ends-a-token)
  * [What the server keeps](#what-the-server-keeps)
  * [For the person running the server](#for-the-person-running-the-server)
  * [Security rules](#security-rules)
* [What the assistant can ask the app](#what-the-assistant-can-ask-the-app)
* [Connect Open WebUI](#connect-open-webui)
* [Connect a Hermes Agent profile](#connect-a-hermes-agent-profile)
* [System prompt template](#system-prompt-template)
* [Check that it works](#check-that-it-works)
* [Honest limits](#honest-limits)
* [The endpoint, for the person running the server](#the-endpoint-for-the-person-running-the-server)

## Switch it on

1. **The admin** turns on **Server administration → Server settings → Optional AI → Assistant access (personal
   tokens for a chat assistant)**, or sets `ASSISTANT_ENABLED=true` (which locks it). It is off by default; while
   it is off, `/mcp` answers `404` and no token works.
2. **Each person** who wants an assistant makes a token in **Settings → Assistant access** and copies it
   ([below](#for-people-using-the-app)). One token per chat client or device makes it easy to revoke one.
3. **In the chat client**, add an MCP server: Streamable HTTP, URL `https://<your server>/mcp`, and the token as a
   bearer header (`Authorization: Bearer kha_…`). Then give the chat model the
   [system prompt](#system-prompt-template).

The chat client's server must be able to reach the app: on the same machine or private network, or through
your reverse proxy with HTTPS. Exposing the app to the internet so that a vendor's cloud app can reach it is
**not recommended** for health data.

## Access tokens

A token is a long secret, `kha_` followed by 43 letters, digits, `-` and `_`, that you paste into the chat
assistant you connect. It gives that assistant **read-only** access to **your own** food log and targets: it cannot
change anything, and it never sees anyone else's data. Each token has the scope `assistant:read`; a later step may
add a separate scope for logging food, which you would have to tick when making the token.

### For people using the app

**Settings → Assistant access** (it shows once your admin has turned assistant access on):

1. Under **New token**, give the token a **name** (for example the app or device it is for, so you know which one
   to revoke later) and choose when it **expires**: after 30 days, 90 days (the default) or 1 year.
2. Select **Create token**. The app may ask for your password again first, as it does before saving a key.
3. The token appears once, with **Copy token**. Paste it into your assistant's settings now: **it is not shown
   again**. If it is lost, revoke it and make a new one.

The list shows each token's name, its first characters (`kha_AbCd1234…`), when it was made, when it was last used
(or "never used") and when it expires. **Revoke** asks once more and then ends the token at once; the assistant
using it gets "not allowed" from then on. You can have at most **5** active tokens. Revoked and expired tokens stay
in the list for 30 days, then disappear.

Your activity list (Settings → Account → Recent sign-in activity) shows when a token was made and when tokens were
revoked, and why.

### What ends a token

* You revoke it, or it expires.
* You change your password, or it is changed with a reset link (from an admin or the server's command line):
  every token of yours is revoked, because whoever knew the old password might have made one.
* An admin disables or deletes your account (enabling it again brings no token back).
* While an admin requires you to choose a new password, your tokens do not work; the change then revokes them.
* While the admin has assistant access **turned off**, no token works and no new one can be made. You can still
  see and revoke yours. When it is turned on again, tokens that have not expired or been revoked work again.

### What the server keeps

For each token: its name, its first 12 characters, the dates (made, last used, expires, revoked) and a one-way
**hash** of the whole token (SHA-256). The token itself is never stored, logged or sent again; a lost token cannot
be recovered, only replaced. Tokens are not in your data export (like your sign-in sessions, they are a way in, not
your data). Deleting your account deletes them.

### For the person running the server

* **Switch:** Server administration → Server settings → Optional AI → **Assistant access (personal tokens for a
  chat assistant)**, or `ASSISTANT_ENABLED=true` in the environment (which locks it). It is **off** by default.
  Turning it off is the quick way to stop every assistant at once; nothing is deleted.
* Members see the Settings card only while it is on (or while they still have active tokens, so they can revoke
  them); admins also see it while it is off, with a pointer to the switch.
* A token works for the account it was made by, under the server's current sign-in mode: a local account with
  `AUTH_MODE=local`, a proxy account with `AUTH_MODE=proxy`, user 1 with `AUTH_MODE=none`. Changing the mode
  stops tokens of accounts that cannot sign in under the new one.
* Use HTTPS beyond your own computer: the token travels in a request header, like a password.
* `python -m app.admin reset-password <name> --stdin` and `disable-user <name>` revoke the account's tokens too.

### Security rules

* A token counts only on the assistant surface, `POST /mcp`. Every other `/api` route ignores the
  `Authorization` header and keeps using the sign-in cookie, so a token can never reach the admin pages or change
  anything. The other way round, `/mcp` never accepts the sign-in cookie: only a token opens it.
* Every refusal is the same `401` answer with `WWW-Authenticate: Bearer`, whatever the reason (unknown, revoked,
  expired, account disabled, switch off), so an answer tells nothing about a guessed token.
* A refused token counts as a failed sign-in for the address it came from: after `LOGIN_IP_MAX_FAILURES` (20)
  failures in 10 minutes, sign-in and tokens from that address wait 10 minutes (`429`). Requests without a token,
  and requests while the switch is off, do not count.
* Making a token needs your password within the last 10 minutes and is limited to 20 an hour; the server writes
  "last used" at most once a minute; log lines hide anything that looks like a token.

## What the assistant can ask the app

The MCP server offers four **read-only** tools. Every number in their answers comes from the app's own code (the
same functions as the Today screen, the food search and the entry sheet), never from the chat model. Each answer is
one JSON object with `"source": "kidney-health"` and the reminder "Numbers come from the app; fetch them again
after any change." A value a food does not list is `null` (unknown, never 0), and every total says how many foods
it misses (`not_listed_by`). No answer contains insulin or medicine doses, medicine advice or lab interpretation.

| Tool | What it answers |
|---|---|
| `safety_check(message)` | Rule-based, for **every** message from the person (up to 2,000 characters). Words that may describe a low (the app's own low pre-filter) → `action: "treat_low_first"` with the app's **Treating a low** card, using the person's own grams from Settings → Meal guidance. Emergency words (the app's red-flag rule, which follows the handbook's "Call 911 now" list) → `action: "get_help_now"` with the **Get help now** card and the link `/learn/get-help-now/` (when both match, both cards, the low first as the card says). Otherwise `action: "none"`. It never delays or warns against treating a low. |
| `get_today(date?)` | The day's numbers exactly as Today has them (default: today on the server's clock): targets (`about` marks a one-number target such as protein "about 56 g"), eaten, planned and both, what is left of each target or how far over, the unknown counts, the app's alerts and "running high" warnings, **per-meal carbohydrate goals only when the profile has diabetes** (carbohydrate used to treat a low counts in the day, never toward a meal), and on hemodialysis whether the day is a dialysis day and the totals since the last session. |
| `search_foods(query, limit?)` | Up to `limit` (1–10, default 5) foods: the person's own foods and the built-in list first (the app's search), then USDA FoodData Central when the server has a key the person may use. Values are per serving, with the serving's description and grams, the per-serving warnings and the `units` `check_meal` accepts. USDA results are mapped the way an import would map them but **not saved** (`in_app: false`); `check_meal` cannot use them until the person adds the food in the app. |
| `check_meal(items, date?, meal?)` | Up to 20 items, each `{food, amount?, unit?, food_id?}`. The app finds each food (by `food_id`, else by name: certain only when one food is named that way, "apple juice" for "Juice, apple", or the search finds a single food with all the words in that order; otherwise the item comes back in `unresolved` with the alternatives and a question, never a guess), scales it (`unit`: `serving` by default, `g`, or a measure the food's own serving lists, such as "cup" for "1/2 cup (124 g)"; no other conversions), and returns per-item values and warnings, the totals, the day **as if the items were planned** (the same projection Today draws for planned food, with its alerts), and with `meal` that meal's carbohydrate against its goal. **Nothing is saved.** "white rice 1 cup" or "2 slices of toast" in `food` also work. |

## Connect Open WebUI

Recent Open WebUI versions can use an MCP server as a tool server over **Streamable HTTP**. Menus change between
versions, so check your Open WebUI version's docs for where MCP servers are added (an admin setting for tool
servers), then:

* **Type:** MCP (Streamable HTTP). **URL:** `https://<your server>/mcp`, or the app's address on the private
  network both containers share, for example `http://kidney-health:8000/mcp`.
* **Authentication:** a bearer token: the `kha_…` token from Settings → Assistant access.
* Use a model that supports tool calling, and give it the [system prompt](#system-prompt-template) (Open WebUI
  keeps a system prompt per model).
* The connection must come from the Open WebUI **server**. A connection made from the browser on another site
  carries that site's `Origin` and is refused (`403`).
* Voice: Open WebUI's own speech-to-text and text-to-speech work as usual; the app never receives audio.

**One token is one person's log.** A tool server that the Open WebUI admin sets up for everyone uses that one
token for every Open WebUI user who may use it, so they would all read that person's food log. Limit the tool
to the person whose token it is (check your Open WebUI version's docs for tool permissions), or give each person
their own Open WebUI.

## Connect a Hermes Agent profile

A Hermes Agent profile **with tools** can use the app as an MCP server. This is the reverse of the app's `hermes`
AI preset ([ai.md](ai.md#hermes-agent)), where the app calls a **tool-free** Hermes profile as a model: that
profile must stay without `mcp_servers`. Make a **separate** profile for the assistant, for example
`hermes profile create kidney-assistant`, and add an MCP server entry to its `config.yaml` (excerpt; check the
Hermes Agent docs for your version, the names follow its MCP configuration):

```yaml
mcp_servers:
  kidney-health:
    url: "https://food.example.org/mcp"
    headers:
      Authorization: "Bearer kha_your_token_here"
    tools:
      include: [safety_check, get_today, search_foods, check_meal]
```

* `tools.include` lists the four tools, so a later version of the app that offers more tools changes nothing
  until you add them here.
* The token is a password: keep the profile's files readable only by you, and revoke the token in the app if the
  file leaks.
* Put the [system prompt](#system-prompt-template) in the profile's personality or system prompt.
* Hermes's own memory follows the memory rule in the prompt: preferences, routines and recipes that worked, never
  targets, lab values or totals.

## System prompt template

Give the chat model this prompt (edit the first line to the person's situation; keep the rules):

```text
You help one person who lives with chronic kidney disease plan what to eat. The kidney-health tools are your
only source of numbers.

1. Call safety_check first with every message from the person, before anything else, and follow its action:
   - treat_low_first: show the Treating a low card it returns, in full, before anything else. Do not plan food
     until the person says the low is treated. Never tell them to wait, or to skip or change a low treatment
     because of potassium or carbohydrate.
   - get_help_now: show the Get help now card and its link first; the person should call their emergency
     number now. If the Treating a low card is included too, treating the low comes first, as it says.
   - none: carry on.
2. Get every number from the tools: targets, what was eaten or planned, what is left, and the values of any
   food. Never use numbers from memory, from your own knowledge, or from earlier in the conversation after
   anything changed: call the tool again.
3. Before suggesting or approving food, call check_meal and report what it returns: the warnings, the totals and
   the day with those foods. If it returns unresolved items, ask the person its questions; never guess a food or
   an amount. If a value is null, say it is unknown (not listed), never zero.
4. Never give insulin or medicine doses, never suggest changing a medicine, and never interpret lab results:
   say that these belong to the person's care team.
5. You cannot save anything. The person logs food in the app.
6. Memory: remember preferences, foods the person likes or avoids, routines and recipes that worked. Never
   remember targets, lab values or totals: fetch them from the tools every time, because the care team may have
   changed them.
7. Keep answers short and in plain words.
```

## Check that it works

With a token in `TOKEN`, list the tools by hand:

```bash
curl -sS https://food.example.org/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

The answer lists `safety_check`, `get_today`, `search_foods` and `check_meal`. `401` means the token is wrong,
revoked or expired; `404` means assistant access is off. Maintainers can run `python tools/e2e/mcp_smoke.py`,
which starts a server and speaks the protocol to it end to end ([tools/e2e/README.md](../tools/e2e/README.md)).

## Honest limits

* **The app cannot check what the chat model finally says.** The tools answer with the app's numbers and rules,
  and the prompt asks the model to use them; a model can still skip a tool, misread a number or add advice of its
  own. Only the app's own screens enforce the rules in code (and the in-app chat of step 2 will). This is why
  step 1 is meant for one informed person who knows to check numbers in the app.
* **Voice and the transcript stay in the chat client.** Open WebUI or Hermes keep the conversation (and any
  recordings) under their own settings and retention; the app never sees or stores them. The app's activity list
  shows when tokens were made and revoked, and Settings shows when a token was last used, but not what was asked.
* **A cloud model sees what is typed and what the tools answer**: your food log, targets and totals go to that
  model's provider. Use a local model (for example through Ollama behind Open WebUI) if that is not acceptable.
* `safety_check` is rule-based: it can miss unusual wording or fire on harmless words. It never replaces calling
  for help or treating a low.
* The assistant cannot log food (a later step), see lab results, the activity log or settings, or anyone else's
  data.

## The endpoint, for the person running the server

* `POST /mcp`: MCP Streamable HTTP, JSON-RPC 2.0, one JSON object per request and one JSON answer (no SSE),
  stateless (no `Mcp-Session-Id`); protocol versions 2025-06-18 and 2025-03-26. Methods `initialize`, `ping`,
  `tools/list`, `tools/call` and notifications. `GET`, `DELETE`, `PUT` and `PATCH` answer `405`.
* Answers before any tool runs: `403` for a foreign `Origin` (anything but the server's own origin or
  `PUBLIC_URL`), `404` while assistant access is off, `401` with `WWW-Authenticate: Bearer` without a valid token,
  `413` above `MAX_BODY_BYTES`, `429` with `Retry-After` above **60 requests a minute per token** (every request
  counts) or for an address blocked after refused tokens.
* Behind a reverse proxy, pass the `Authorization` header through, and set `PUBLIC_URL` if a client sends an
  `Origin` with the public address. The usual `TRUSTED_PROXIES` rules apply ([security.md](security.md)).
* The server logs neither questions nor answers; a failing tool is logged with its name and the error only.
