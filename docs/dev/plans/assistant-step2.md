# Assistant, step 2, part A: the in-app Ask chat (text)

Status: part A built (2026-10-15); voice and the follow-ups below are not. Step 1 (`assistant-step1.md`) made the app an MCP server for an external chat
front end. Step 2 puts a chat inside the app, behind the same rules: the model never supplies a number, lows and
red flags are answered by rules without a model call, and the answer is checked in code before it is shown.
Part A is the text chat. Part B (voice) and the follow-ups are listed under "Next".

## Rules that do not change

* Numbers never come from a model: every figure is a tool result or the person's own words, and the answer is
  checked for that in code (the chat's V6 below). Unknown (null) is unknown, never 0.
* No insulin or medicine doses, no medicine advice, no lab interpretation. Treating a low is never blocked,
  delayed, questioned or warned against; the rule-based low and emergency cards come first on every message.
* Off by default. The Ask screen is not shown, and the route answers 404, until an admin switches the chat on.
* No new clinical numbers: no threshold is added anywhere. The only constants are sizes of the chat itself.
* Reuse, never duplicate: the AI client (`complete_json`, one repair turn), the concurrency gate, the quota, the
  consent flow, the text cleaning and the step-1 tool functions.

## 1. The route

`POST /api/ai/chat` (cookie session + CSRF, `current_user`, like every `/api/ai` route; `?dry_run=true` returns the
first request exactly as it would be sent, like the other features). Body:
`{"messages": [{"role": "user"|"assistant", "text": str}, ...]}`: the conversation so far, kept only in the page
(the server stores no transcript). 1 to 20 items, each 1 to 2000 characters, the last one from the person.

Answer (shape after the other AI answers, V9):

```
{"kind": "answer" | "withheld" | "unfinished" | "error" | "treat_low" | "get_help_now",
 "text": str | null, "cards": [ {title, lines, handbook, url}, ... ],
 "numbers": [ {title, rows: [{label, value, detail}]}, ... ],     # "From the app"
 "notes": [str, ...],
 "label": {source, provider_label, model, checked, notice},        # null when no model was called
 "provider": {id, label, model, host} | null, "ai_called": bool, "model_calls": int, "tool_calls": int,
 "prompt_version": str, "audit_id": int | null}
```

`cards` is a list (not one card) because a message with emergency wording and low wording gets both cards, and
the Treating a low card is never left out. Errors that other AI features also raise keep their HTTP codes: 409
`consent_required` (with what the person would agree to), 429 quota or busy, 503 not configured.

## 2. Availability, consent, schema

* Only when AI is on, configured and allowed for this person (opted in), like the other features, plus the admin
  switch `ai.chat_enabled` (settings registry, bool, default false, env `AI_CHAT_ENABLED`, Server administration →
  Server settings → Optional AI, with its JS twin and vectors). Off: 404 `{"detail": "Not Found"}`, as when AI is
  off; `GET /api/ai/status` says `features.chat` false and the Ask tab is not shown.
* New consent purpose `chat` with its own "What will be sent?" text: the messages in this conversation and the
  app's own numbers the assistant looks up (targets, totals, food names and nutrients); never the name, user name,
  e-mail, weight, height, exact age or notes. Once per provider, like `text` and `photos`.
* **Schema step 12** (step 11 belongs to the assistant request-keys change that merges first). `ai_consents.purpose` has `CHECK (purpose IN ('text','photos'))` (step 6), so a `chat` consent
  cannot be stored. SQLite cannot alter a CHECK, so `m012_ai_consent_chat.py` rebuilds `ai_consents` (copy, drop,
  rename, recreate the index) with the purposes `text`, `photos` and `chat`. Idempotent (it looks at the stored
  table definition), atomic, with `foreign_key_check`. This is the only schema change.

## 3. Rules first, every message, no model call

The `safety_check` tool function (step 1: `hypo.prefilter` with the person's own `hypo_dose_g`, and
`features.red_flag`) runs on the newest message before anything else, before the provider is even resolved.

* Emergency wording → `kind: "get_help_now"` with the red-flag card and its link (`/learn/get-help-now/`); if low
  wording is also present the Treating a low card follows in `cards`.
* Low wording → `kind: "treat_low"`, the Treating a low card (the person's own grams) and the text "Treat the low
  first. When you feel better, ask again."
* The model is not called, no quota is spent, no consent is needed. Nothing warns against, delays or questions a
  low treatment.
* An earlier message in the conversation that matched a rule is not sent to the model on later turns (nor the
  answer that followed it): low talk never reaches a provider.

## 4. The model loop: a JSON step protocol

Not provider-native tool calling, so it works with every configured provider through `complete_json` (parse,
schema validation with `extra="forbid"` models, one repair turn). Each step the model returns exactly one of
`{"call": {"tool": "<name>", "arguments": {...}}}` or `{"answer": "<text>"}`.

* Allowed tools: `get_today`, `search_foods`, `check_meal` (the step-1 `Tool` objects and `run`; read-only; the
  saving tools and `safety_check` are never offered). The tool runs for this person through the same functions as
  `POST /mcp`, in the thread pool, and its result is appended to the conversation sent next as a labelled data
  block (untrusted text cleaned, `<`, `>` and `&` escaped, like every other prompt).
* An unknown tool or bad arguments are not a schema failure: the model is told ("TOOL ERROR: ...") and may try
  again; the attempt counts toward the limit.
* At most 6 tool calls per message. After the sixth result the model is told it must answer; if it still calls,
  the loop stops with `kind: "unfinished"`, the numbers gathered and the fixed text "The assistant could not
  finish; here are the app's numbers." So a message makes at most 7 model calls.
* Every model call: consent (once, before the first), the person's single AI slot and the server's concurrency
  slot held for the whole message, the Hermes tool check, one unit of the per-person quota (a quota that runs out
  after the first call ends the loop with `unfinished`; before the first call it is the usual 429), the provider's
  timeout, and a row in the AI activity log. The activity rows keep **no message text and no request bodies**
  (`keep_bodies` false; verdict = step, tool name, outcome): the server stores no transcript. "What will be sent?"
  (the dry run) shows the first request.
* The structured mode is `json_object` when the provider's mode is `json_schema` (a strict schema cannot describe
  free-form tool arguments); the protocol and its schema are in the system prompt in every mode.
* Prompt text in `app/ai/prompts.py` (`PROMPT_VERSION` bumped to 2026-10-15.1): the person block the existing
  prompts use (stage, dialysis, diabetes, preferences, age band and sex only with consent; no identity), the tool
  list with their argument schemas (read from the step-1 tools, so they cannot drift) and the rules: every number
  from a tool and never from memory, fetch again each turn, null is unknown and not zero, no insulin or medicine
  doses, no medicine advice, no lab interpretation, a plain warning and "check with your care team" for salt
  substitutes, NSAIDs and big changes in protein or fluid, short answers in plain words.
* History that does not fit `context_tokens` is trimmed from the oldest end (the newest message is always kept);
  if even that does not fit, 503 `context_too_small` as for the other features.

## 5. The answer is checked in code before it is shown (the chat's V6)

In this order, on the model's `answer` text; every failure replaces the text, never the numbers:

1. **Text policy**: NFKC, `Cc`/`Cf` removed (line breaks kept), URLs and e-mail addresses removed except the
   app's own `/learn/...` paths, cut at 1200 characters at a sentence end. Empty after cleaning → `kind: "error"`.
2. **Dose check** → `kind: "withheld"`, text "This answer was not shown because it touched on medicine or insulin
   doses. Ask your care team about doses." plus the tools' numbers. Patterns (`app/ai/chat.py`, built on the
   binder and medicine names of `guard.py`): insulin, bolus, basal, units of insulin, correction or carb ratio,
   dose/dosing/dosage, the binder brand names of `guard.BLOCKLIST`, advice to change or take medicine, and advice to
   skip, delay or avoid insulin, medicine or a low treatment (a sentence about a low blood sugar that also
   restricts something). Narrower than the blocklist for names: ordinary words such as "more", "extra", "unit",
   "supplement" or "pills" alone do not withhold.
3. **Number check** → `kind: "withheld"`, text "The assistant's answer had a number the app did not work out, so it
   is not shown. Here are the app's own numbers." Every number with a nutrient or energy unit next to it (mg, g,
   mL, l, kcal, %, and their spelled-out forms) must equal, at the precision shown, a number in this message's
   tool results (including numbers inside their text) or in the person's own messages. Thousands separators are
   read; rounding to the precision shown is accepted; no unit conversion. Numbers without such a unit ("2 slices",
   "1 cup") are allowed.
4. **Lab words** (eGFR, creatinine, A1c, "blood potassium", "lab result" ...) in the answer or the question add the
   fixed note "Lab results are for your care team to interpret." to `notes`.
5. `numbers`: what the tools returned, shaped for the screen as "From the app" (the day's totals with target and
   what is left; a checked meal's totals and the day with it; foods found), pre-formatted by the server.

## 6. The Ask screen

`app/static/js/views/ask.js` + `css/ask.css`, a sixth tab ("Ask") shown only when `GET /api/ai/status` says
`features.chat` (it follows `KH.ai.status()`, refreshed after sign-in and whenever the AI choices change). A
message list (answers set with `textContent`, never HTML), an input with Send (Enter sends, Shift+Enter a new line),
"Thinking…", the cards for `treat_low` and `get_help_now` (the existing `ai-card-alert` rendering), "From the app"
numbers under answers, a notice for a withheld answer, "New conversation", the consent sheet on first use (the
existing flow with purpose `chat`, including "What will be sent?"), and the line "Answers come from an AI model;
every number is the app's own. Not medical advice." Works at 375 px with no sideways scroll, light and dark; no
inline scripts or styles. The conversation lives in the page only; reloading starts a new one. The demo and the
preview show the tab with a note that chat works in the installed app with an AI provider (no mock answers).

## Tests

Fake provider as in the other AI tests, no network. Rules without a model call (the fake is asserted unused) for
low and emergency wording, in both orders; consent 409; switch off 404; anonymous 401; the loop with a scripted
model (call, result in the next request, answer); unknown tool and bad arguments; the step limit; quota per model
call; two people's data never mixed; dose check both directions; number check (exact, rounded, thousands separators,
made up, ranges, user-supplied); lab note; no message text in the activity log; no identity in the prompt; the
migration (old table with rows, fresh database, idempotent); a static UI test for the Ask view; settings twin
vectors; chat golden cases in `scripts/ai_eval.py` for the owner's live run.

## Next (not in this part)

* **Part B, voice**: a microphone button using the browser's speech recognition (Chrome sends the audio to Google
  and Safari to Apple, Firefox has none: the consent wording must say so), the transcript shown before it is sent,
  and the reply read aloud with the browser's own voice; later a transcription-provider setting.
* **Saving from chat**: an "Add to plan" button the person presses, calling the normal log API (the model never
  saves); the saving tools stay out of the chat.
* **Recipe pages** in `check_meal` (step 1's follow-up), so the chat can work from a recipe link.
* A live golden run of the chat cases and a prompt wording from the profile (kidney-only) belong to the owner.
