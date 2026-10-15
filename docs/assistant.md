# The assistant: a chat assistant that reads your own numbers

The owner's main AI wish is an assistant you can talk to about food ("what fits in the rest of today?"), by text
or voice, that takes every number from the app instead of making one up. Step 1 connects a chat front end you
already use (for example Open WebUI, or a Hermes Agent profile with tools) to the app over MCP, with a personal
token. The plan, its rules and its parts are in
[`dev/plans/assistant-step1.md`](dev/plans/assistant-step1.md); the API contract is in `ARCHITECTURE.md`
("Assistant access tokens" and "Assistant MCP server").

**Where this stands.** Step 1 is in place: personal access tokens (part A), the **MCP server** at `/mcp` with four
tools that read your numbers and check a meal (part B), and, only for a token made with **Can also save food and
recipes**, two tools that save (part C): `log_food` and `save_recipe`. **Step 2, part A** is in place too: an
**Ask** screen inside the app, a text chat that uses the same read tools and checks every answer in code before it
is shown ([The Ask screen](#the-ask-screen-the-chat-inside-the-app); plan
[`dev/plans/assistant-step2.md`](dev/plans/assistant-step2.md)). Voice and "Add to plan" from the chat are later
parts ([ROADMAP](ROADMAP.md), "An assistant you can talk to").

## Contents

* [Switch it on](#switch-it-on)
* [Access tokens](#access-tokens)
  * [For people using the app](#for-people-using-the-app)
  * [What ends a token](#what-ends-a-token)
  * [What the server keeps](#what-the-server-keeps)
  * [For the person running the server](#for-the-person-running-the-server)
  * [Security rules](#security-rules)
* [What the assistant can ask the app](#what-the-assistant-can-ask-the-app)
  * [Tools that save](#tools-that-save)
* [Connect Open WebUI](#connect-open-webui)
* [Connect a Hermes Agent profile](#connect-a-hermes-agent-profile)
* [System prompt template](#system-prompt-template)
* [Check that it works](#check-that-it-works)
* [The Ask screen (the chat inside the app)](#the-ask-screen-the-chat-inside-the-app)
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
assistant you connect. By default it gives that assistant **read-only** access to **your own** food log and
targets (scope `assistant:read`): it cannot change anything. If you tick **Can also save food and recipes** when
you make the token, it also has the scope `assistant:log`: the assistant can then add entries to your food log and
save recipes as saved meals, after it has asked you (see [Tools that save](#tools-that-save)). It never sees
anyone else's data, and it cannot edit or delete anything.

### For people using the app

**Settings → Assistant access** (it shows once your admin has turned assistant access on):

1. Under **New token**, give the token a **name** (for example the app or device it is for, so you know which one
   to revoke later) and choose when it **expires**: after 30 days, 90 days (the default) or 1 year. Tick **Can also
   save food and recipes** only if you want the assistant to be able to save for you; it is off by default, and a
   token cannot be changed later (make a new one instead).
2. Select **Create token**. The app may ask for your password again first, as it does before saving a key.
3. The token appears once, with **Copy token**. Paste it into your assistant's settings now: **it is not shown
   again**. If it is lost, revoke it and make a new one.

The list shows each token's name, whether it is **Read only** or **Read and save**, its first characters
(`kha_AbCd1234…`), when it was made, when it was last used (or "never used") and when it expires. **Revoke** asks once more and then ends the token at once; the assistant
using it gets "not allowed" from then on. You can have at most **5** active tokens. Revoked and expired tokens stay
in the list for 30 days, then disappear.

Your activity list (Settings → Account → Recent sign-in activity) shows when a token was made (and whether it can
save) and when tokens were revoked, and why. It also shows **every time an assistant saved something**: the token's
name, how many entries (or which recipe), the day and the meal.

### What ends a token

* You revoke it, or it expires.
* You change your password, or it is changed with a reset link (from an admin or the server's command line):
  every token of yours is revoked, because whoever knew the old password might have made one.
* An admin disables or deletes your account (enabling it again brings no token back).
* An admin uses **Revoke assistant tokens** on your row in Server administration → People: every active token of
  yours ends at once (your activity says "revoked by an admin"), and you can make new ones.
* While an admin requires you to choose a new password, your tokens do not work; the change then revokes them.
* While the admin has assistant access **turned off**, no token works and no new one can be made. You can still
  see and revoke yours. When it is turned on again, tokens that have not expired or been revoked work again.

### What the server keeps

For each token: its name, its first 12 characters, the dates (made, last used, expires, revoked) and a one-way
**hash** of the whole token (SHA-256). The token itself is never stored, logged or sent again; a lost token cannot
be recovered, only replaced. Tokens are not in your data export (like your sign-in sessions, they are a way in, not
your data). Deleting your account deletes them.

For 24 hours the server also keeps, for each save that carried a `request_key`, a one-way hash of the token's id and
the key (never the key), what was saved (the entry ids or the saved meal's id) and when, so that a retry is
recognised ([Tools that save](#tools-that-save)).

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
* **Revoke a person's tokens:** Server administration → People → Manage → **Revoke assistant tokens (n)** (shown while
  the switch is on and the person has active tokens; `n` is how many; it asks once more). It ends all of that person's
  active tokens, nobody else's, and is listed in their activity. Needs a recent password, like the other actions there.

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

The MCP server offers four **read-only** tools to every token, and two that save to a token that can save. Every number in their answers comes from the app's own code (the
same functions as the Today screen, the food search and the entry sheet), never from the chat model. Each answer is
one JSON object with `"source": "kidney-health"` and the reminder "Numbers come from the app; fetch them again
after any change." A value a food does not list is `null` (unknown, never 0), and every total says how many foods
it misses (`not_listed_by`). No answer contains insulin or medicine doses, medicine advice or lab interpretation.

| Tool | What it answers |
|---|---|
| `safety_check(message)` | Rule-based, for **every** message from the person (up to 2,000 characters). Words that may describe a low (the app's own low pre-filter) → `action: "treat_low_first"` with the app's **Treating a low** card, using the person's own grams from Settings → Meal guidance. Emergency words (the app's red-flag rule, which follows the handbook's "Call 911 now" list) → `action: "get_help_now"` with the **Get help now** card and the link `/learn/get-help-now/` (when both match, both cards come back, and the Get help now card itself says to treat a low first). Otherwise `action: "none"`. It never delays or warns against treating a low. |
| `get_today(date?)` | The day's numbers exactly as Today has them (default: today on the server's clock): targets (`about` marks a one-number target such as protein "about 56 g"), eaten, planned and both, what is left of each target or how far over, the unknown counts, the app's alerts and "running high" warnings, **per-meal carbohydrate goals only when the profile has diabetes** (carbohydrate used to treat a low counts in the day, never toward a meal), and on hemodialysis whether the day is a dialysis day and the totals since the last session. |
| `search_foods(query, limit?)` | Up to `limit` (1–10, default 5) foods: the person's own foods and the built-in list first (the app's search), then USDA FoodData Central when the server has a key the person may use. Values are per serving, with the serving's description and grams, the per-serving warnings and the `units` `check_meal` accepts. USDA results are mapped the way an import would map them but **not saved** (`in_app: false`, `id: null`); name one by its `fdc_id` in `check_meal`, `log_food` or `save_recipe`. |
| `check_meal(items, date?, meal?)` | Up to 20 items, each `{food, amount?, unit?, food_id?, fdc_id?}`. The app finds each food (by `food_id`; else by `fdc_id`, the id `search_foods` gives a USDA result: the person's own copy if they have one, otherwise USDA's record, read and **not saved**; else by name: certain only when one food is named that way, "apple juice" for "Juice, apple", or the search finds a single food with all the words in that order; otherwise the item comes back in `unresolved` with the alternatives and a question, never a guess), scales it (`unit`: `serving` by default, `g`, or a measure the food's own serving lists, such as "cup" for "1/2 cup (124 g)"; no other conversions), and returns per-item values and warnings, the totals, the day **as if the items were planned** (the same projection Today draws for planned food, with its alerts), and with `meal` that meal's carbohydrate against its goal. **Nothing is saved.** "white rice 1 cup" or "2 slices of toast" in `food` also work. |

### Tools that save

Only a token made with **Can also save food and recipes** lists these two tools; with any other token
`tools/list` leaves them out and calling one is an error that says "This token can only read" and saves nothing.
Both place their items **exactly as `check_meal` does** (the same food finding and amounts; an item named by `fdc_id`
works too), so what the assistant checked is what is saved.

| Tool | What it does |
|---|---|
| `log_food(items, meal, date?, status?, purpose?, request_key?)` | Saves up to 20 items as log entries for `meal` (breakfast, lunch, dinner or snack) on `date` (default today; any date the log accepts), `status` `eaten` (default) or `planned`. **All or nothing:** if any item is unresolved or ambiguous, nothing is saved (not even the foods that were found) and the answer is `{"saved": false, "unresolved": [...]}` with the questions to ask the person. Otherwise the answer lists the saved entries (id, food, amount, nutrients with unknown as `null`), the totals of what was saved and **the day's figures after saving** (the same answer as `get_today`). The entries are made by the same function as the log API, so they are ordinary entries: the person can edit or delete them in the app. A USDA food (an item with `fdc_id` that is not in the person's list yet) is **added to the person's food list first**, as the Food screen's USDA import would, in the same all-or-nothing step. `purpose`: `hypo` marks food eaten to treat a low (it counts in the day's totals, never toward a meal's carbohydrate goal, and is saved at once like any other entry: nothing is blocked, delayed or warned about); `none` clears the mark the app would add for a food it knows treats a low. |
| `save_recipe(name, ingredients, servings, source_url?, request_key?)` | Saves a recipe as a **saved meal** (Food → Saved meals). `ingredients` are placed like `check_meal` items; if any is unresolved nothing is saved. `name` is 1–60 characters, `servings` is how many servings the whole recipe makes (more than 0, at most 100). A saved meal has no servings count, so it holds the ingredients **for the whole recipe** and its note says "Makes N servings." and, if `source_url` was given, "Source: <link>". The link must be an `http` or `https` address of at most 900 characters, with no spaces or password; it is kept as text and **never opened** by the server. The answer gives the saved meal and the totals for the whole recipe and per serving (`null` means not listed, never 0). Nothing is eaten: use the app, or `log_food`, to log a share of it. |

Rules for both:

* **The person confirms first.** The tool descriptions and the [system prompt](#system-prompt-template) ask the model
  to read the items back and wait for a yes before saving, and to say what was saved afterwards. The app cannot
  check that the model did; what it can do is list every save in the person's activity and keep each one editable.
* **Every save is in the activity list** with the token's name and what was saved (the entry count or the recipe's
  name), never the token.
* Saves count in the same **60 requests a minute** per token as everything else, so a model that loops on
  `log_food` stops after a minute's worth. There is no stricter limit for saving.
* **Retries do not save twice (`request_key`).** Both tools take an optional `request_key` (8 to 64 letters, digits,
  `-` or `_`). The tool descriptions tell the model to send a fresh one with each save it means to make, and to send
  the same one again only to retry that save after an error or no answer. A second call by the same token with the
  same key within 24 hours saves **nothing** and answers `{"saved": true, "duplicate": true, …}` with what the first
  call saved (the same entry ids or saved meal), read from your data again, so it shows edits. If you deleted what the
  first call saved, the answer says so (`"saved": false`) and still saves nothing; a new key saves. The server keeps
  only a one-way hash of the token's id and the key, for 24 hours. Without a key a repeated call saves again. A bad key
  is an error that saves nothing, and so is the same key on the other tool.
* Neither tool edits or deletes anything, and neither returns insulin or medicine doses, medicine advice or lab
  interpretation.

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
      include: [safety_check, get_today, search_foods, check_meal]  # add log_food, save_recipe to let it save
```

* `tools.include` lists the tools the profile may use, so a later version of the app that offers more tools changes
  nothing until you add them here. `log_food` and `save_recipe` work only with a token made with **Can also save
  food and recipes**.
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
5. Saving (only if log_food and save_recipe are in your tool list; otherwise you cannot save anything and the
   person logs food in the app). Before saving, read the items back (food, amount, meal, day, eaten or planned)
   and ask the person to confirm. After saving, say what was saved. If log_food or save_recipe returns
   unresolved items, nothing was saved: ask the person the questions and try again with all the items. Only the
   person decides what is saved; never save a guess. This confirmation is only about the record: it never comes
   before the person treats a low. When the person ate something to treat a low, save it with purpose "hypo"
   afterwards, and say nothing against it.
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

The answer lists `safety_check`, `get_today`, `search_foods` and `check_meal`, and, for a token that can save,
`log_food` and `save_recipe`. `401` means the token is wrong,
revoked or expired; `404` means assistant access is off. Maintainers can run `python tools/e2e/mcp_smoke.py`,
which starts a server and speaks the protocol to it end to end ([tools/e2e/README.md](../tools/e2e/README.md)).

## The Ask screen (the chat inside the app)

A text chat in the app itself (**Ask**, a sixth tab), for people who want the answer without setting up a chat
client. It asks the same questions of the same app functions as the MCP tools above (`get_today`, `search_foods`,
`check_meal`; never the saving tools), and it adds what an outside chat cannot: **the app checks the answer in code
before you see it.** It uses the AI provider your admin set up for the other AI features ([`ai.md`](ai.md)); the
assistant of this page's token and MCP sections is a separate way in and needs no AI provider on the server.

**Switch it on.** Optional AI must be on and set up ([`ai.md`](ai.md)). Then the admin turns on **Server administration
→ Server settings → Optional AI → Ask (a chat with the AI inside the app)** (`ai.chat_enabled`, `AI_CHAT_ENABLED`; off by
default). Each person who has chosen **Use AI ideas** then sees the **Ask** tab. Switched off, the tab is not shown and
`POST /api/ai/chat` answers 404.

**Using it.** Type a question and press Enter (Shift+Enter starts a new line). The first time, a sheet asks you to agree to
send your messages and the numbers the assistant looks up to the provider, and "What will be sent?" shows the exact
request. The assistant looks up your targets and your day with its tools and answers in a few plain sentences; under the
answer, **From the app** lists the figures the app itself worked out (the day's totals and what is left, a checked meal's
totals, foods found), so you always see the app's own numbers. **New conversation** starts again. The conversation lives in
the page only: reloading or signing out forgets it, and the server keeps no transcript.

**What the app does with each message.**

1. **The rules answer first, with no AI call.** Words that may describe a low get your Treating a low card (with your own
   grams) and "Treat the low first. When you feel better, ask again."; emergency words get the Get help now card. Nothing in
   the chat ever warns against, delays or questions treating a low. Such a message, and the answer after it, is also left
   out of what is sent to the model on later turns.
2. **The model asks, the app answers.** The model replies with one JSON step: a call to a read-only tool, or an answer. The
   app runs the tool for you and sends the result back. At most 6 tool calls per question, then the model must answer; if it
   still asks for more, you get "The assistant could not finish; here are the app's numbers." Each model call counts against
   your daily AI limit and shows in the AI activity list (without any text).
3. **The answer is checked.** Links are removed (except the app's own `/learn/...` pages), the text is cut to 1200
   characters, and the answer is **withheld** (you see a notice and the app's numbers instead) if it touches on insulin or
   medicine doses or advises skipping, delaying or avoiding insulin, medicine or a low treatment ("This answer was not shown
   because it touched on medicine or insulin doses. Ask your care team about doses."), or if it has a number with a unit (mg,
   g, ml, l, kcal, %) that the tools did not return and you did not type ("The assistant's answer had a number the app did not
   work out, so it is not shown. Here are the app's own numbers."). Ordinary food talk ("have more rice", "choose
   low-sodium bread") is not withheld. Lab words add "Lab results are for your care team to interpret."

**What is sent, what is kept.** Your messages in this conversation (the last 20) and the app's own numbers the assistant
looks up: targets, totals, food names and nutrients. Never your name, user name, e-mail, weight, height, exact age or notes
(the person block of the other AI features: stage, dialysis, diabetes, your preferences text, and an age band and sex only if
you chose to share them). The AI activity list keeps no request, no answer and no message text for Ask, only that a call
happened (when, which provider and model, the step and the tool name, the outcome). Details: [`privacy.md`](privacy.md).

**Limits.** One question can take up to 7 model calls, so the shared daily limit (30 by default) goes faster; a limit reached
after the first call ends that question with the numbers gathered so far. Small local models may not follow the one-JSON-step
protocol; `python scripts/ai_eval.py --chat` measures that (the owner runs it with a live model; [`ai.md`](ai.md)).

**Not in this part** (see [`dev/plans/assistant-step2.md`](dev/plans/assistant-step2.md), "Next"): voice (part B: the browser's
speech recognition with its own consent wording, the reply read aloud), saving from the chat (an "Add to plan" button you
press, through the normal log API) and recipe pages.

## Honest limits

* **The app cannot check what the chat model finally says.** The tools answer with the app's numbers and rules,
  and the prompt asks the model to use them; a model can still skip a tool, misread a number or add advice of its
  own. Only the app's own screens enforce the rules in code, and the Ask screen does (below). This is why
  the external chat of step 1 is meant for one informed person who knows to check numbers in the app.
* **Voice and the transcript stay in the chat client.** Open WebUI or Hermes keep the conversation (and any
  recordings) under their own settings and retention; the app never sees or stores them. The app's activity list
  shows when tokens were made and revoked, and Settings shows when a token was last used, but not what was asked.
* **A cloud model sees what is typed and what the tools answer**: your food log, targets and totals go to that
  model's provider. Use a local model (for example through Ollama behind Open WebUI) if that is not acceptable.
* `safety_check` is rule-based: it can miss unusual wording or fire on harmless words. It never replaces calling
  for help or treating a low.
* **A model can save the wrong thing** (a misheard amount, a food of the same name): the confirmation step is only
  as good as the model's following it. Every save is in the activity list, and every entry or saved meal can be
  edited or deleted in the app. If you do not want an assistant to be able to save, make the token without **Can
  also save food and recipes** (the default).
* The assistant cannot edit or delete anything, see lab results, the activity log or settings, or anyone else's
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
* Every request needs `assistant:read`. `tools/list` lists `log_food` and `save_recipe` only for a token that also
  has `assistant:log` (they carry the annotations `readOnlyHint: false`, `destructiveHint: false`,
  `idempotentHint: false`, `openWorldHint: false`: a repeated call saves again unless it carries the same
  `request_key`), and the `initialize` instructions
  of such a token add the confirm-first rule. A call to a saving tool with a read-only token is a tool result with
  `isError: true`, not a protocol error.
* The server logs neither questions nor answers; a failing tool is logged with its name and the error only.
