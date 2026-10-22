# Assistant, step 2, parts A and C: the in-app Ask chat (text) and saving from it

Status: done, shipped in 0.4.0: part A (the text chat), part C (saving from the chat, with a trust setting) and part B (voice, below) were built on 2026-10-15; the follow-ups under "Next" that are not built are in `docs/ROADMAP.md`. Step 1 (`assistant-step1.md`) made the app an MCP server for an external chat
front end. Step 2 puts a chat inside the app, behind the same rules: the model never supplies a number, lows and
red flags are answered by rules without a model call, and the answer is checked in code before it is shown.
Part A is the text chat. Part B (voice) is described after the tests below; the follow-ups are listed under "Next".

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

## Part C: the Ask chat can save, with a trust setting

The owner's words: "I want to have a few options to 'trust AI' or not, so I don't have to babysit it by confirming every
response. I would like this to be a toggle with a warning." Least trust stays the default: the chat only proposes, and
the person presses Save. Trusting it is a person's own choice, behind an admin switch, behind a warning.

### C1. The two switches

* **Admin**: `ai.allow_trusted_saves` (bool, default false, env `AI_ALLOW_TRUSTED_SAVES`, in Server administration next
  to the other AI switches; in `NO_SIGNIN_ENV_ONLY` like them). Off: nobody can trust the assistant to save; every save
  is a card to confirm.
* **Person**: Settings → AI ideas → "How much do you trust the assistant?" (and a short link to it from the Ask screen),
  stored in the person's `ai` setting as `trust` (no new column): `ask` ("Ask me before every save", the default,
  marked recommended) | `conversation` ("Trust it for this conversation") | `always` ("Trust it always"). Choosing
  `conversation` or `always` first opens a warning sheet ("The assistant will save food and recipes without asking you
  first. It can pick the wrong food or the wrong amount. Every number still comes from the app, the low and emergency
  rules and the dose checks always stay on, and each save can be undone from the chat or from Today. Photo and label
  readings are always shown to you to check."), with "I understand, trust it" and "Keep asking me". Every change of
  the choice is a row in the person's activity log (`ai.trust_changed`, old and new), whichever route wrote it
  (`PATCH /api/me/ai` or `PATCH /api/me/settings`). If the admin switch is turned off later the effective choice is
  `ask` and Settings says the admin turned trusted saves off.
* **Effective trust** (`app.ai.chat_save.effective_trust`): `ask` unless the admin switch is on **and** the person
  chose it: `always` is the stored choice alone; `conversation` needs the stored choice **and** the page sending
  `trust: "conversation"` in the chat request. The page holds that grant in memory only: it ends with New
  conversation, a reload, or 12 hours after it was given. The server cannot extend or verify it, only refuse it (a
  page's claim counts for nothing without the stored choice and the admin switch).

### C2. What the model may do

* It may call `log_food` and `save_recipe` (the MCP tools' own arguments and code; the app removes any `request_key` the
  model sends and makes its own). Never `safety_check`, still never doses. `PROMPT_VERSION` 2026-10-15.2. The prompt
  allows a save only when the person asked in the conversation to log, plan or save something, with exactly what they
  asked, and forbids saying anything is saved unless a tool result says `"saved": true`.
* At most 2 save calls per message (a third is told "At most 2 saves..."). A save counts toward the 6 tool calls.
* A message that matched a low or emergency rule is answered by the rules before any of this, so a save never happens
  for it; the save code also refuses a safety message on its own (defence in depth).

### C3. Ask mode (the default): a card, nothing written

The model's save call is not executed. The loop places the items with `place_items` (exactly as the tool would) and ends
at once with `kind: "confirm_save"` and the fixed text "Nothing has been saved yet. Check this, then press a Save
button, or Cancel." (the model's words are not used). `pending_save` carries the resolved foods (name, amount as asked,
servings, grams, whether it is a USDA food not in the list yet), the date, meal and status the model asked for, the
purpose, the app's totals ("This adds"; for a recipe "Whole recipe" and "Per serving"), and `payload`: the exact body of
the normal save route (`POST /api/log/batch` with stable `client_id`s so a double press adds nothing, or `POST
/api/meals`). The page shows **Save as eaten**, **Save as planned** (the model's choice preselected) and **Cancel**; Save
posts the payload with the status chosen, with CSRF, like any other save; for a USDA food the page first adds it to the
person's foods with `POST /api/foods/usda/import`. If an item cannot be placed there is no card: `questions` hold the
app's own questions (the model is told too and may ask in its answer).

### C4. Trusted mode: saved at once, with Undo

The call runs through `log_food` / `save_recipe` themselves (all or nothing, one transaction, USDA foods added in it by
`write_once`). The request key is `<request_id>-<n>` (`n` is the save's number in this message) in the new table
`assistant_ask_keys` (schema step 13: no token, so not step 11's table), so a chat request sent twice saves once and the
second answer still shows the saved card with Undo; after a repeat the model may not save again in that message. The
activity log gets `assistant.food_logged` / `assistant.recipe_saved` with `via: "Ask"` (never a token name). The answer
has `saved`: one card per save with the foods and amounts, the totals, and the ids **Undo** deletes through
`DELETE /api/log/{id}` (each entry) or `DELETE /api/meals/{id}`: scoped to the person, 404 for anyone else's. USDA foods
a save added to the person's list stay in the list. A withheld, unfinished or failed answer keeps its saved cards.

### C5. Unchanged in both modes

`purpose: "hypo"` (food eaten to treat a low) is saved like any other and never warned about, and no card or message
here warns, delays or questions it; the dose check and the number check still run on the answer text (the numbers a save
returns are in the pool); photo and label readings keep their own review screens (trust never covers them); the activity
log of model calls (`ai_audit`) still holds no message text, now with the step `log_food` / `save_recipe` and the outcome
`confirm_save`; the MCP tools and tokens are unchanged (their confirmation is a prompt instruction; the trust setting
applies to the Ask screen only).

### C6. Tests

`tests/test_ai_chat_save.py` (effective-trust matrix, ask mode, trusted mode, retries, Undo, isolation, hypo, safety
messages, audit of the choice), `tests/test_migration_m013.py`, `tests/test_ask_ui.py` (the cards, the warning sheet, no
inline scripts, text set with textContent), the settings twin vectors, and `tools/e2e/ask.py` (a confirm card and a
trusted save with Undo in Chromium).

## Part B: voice (the microphone and read aloud)

Decided by the owner (least trust, high security): **no browser speech recognition** (Chrome sends that audio to Google and Safari to
Apple; a test keeps every name of the API out of the shipped page). Speech to text is a **server-side provider, off by default**.

1. **Provider.** Environment only: `STT_BASE_URL` (an OpenAI-compatible base ending in `/v1`; the app calls `{base}/audio/transcriptions`),
   `STT_MODEL`, `STT_API_KEY[_FILE]` (optional, write-only, never returned by any API), `STT_TIMEOUT_S`, `STT_DAILY_LIMIT`,
   `STT_MAX_AUDIO_BYTES`; the admin switch `ai.voice_enabled` (registry, default false, `AI_VOICE_ENABLED`; needs `ai.chat_enabled`).
   The host goes through the **same SSRF transport and netpolicy** as AI providers (`send_json`, scope `shared`: a LAN host only when
   `AI_PRIVATE_HOSTS` lists it); no new outbound path. Server administration shows the host, model and limits read-only (never the key)
   and a **Test transcription** button (one second of generated silence; cheap, so it is there).
2. **Route.** `POST /api/ai/transcribe` (`app/ai/voice.py`; logic in `app/ai/stt.py`): cookie session and CSRF, `current_user`, **404 when AI,
   Ask or voice is off or `STT_BASE_URL` is unset, before the body**; 503 for a person who cannot use AI; the content type must be
   `audio/webm`, `audio/ogg`, `audio/mp4` or `audio/wav` (415) and the first bytes must be that container (400); at most
   `STT_MAX_AUDIO_BYTES` (1.5 MiB; the body limit is registered for this exact path; 413) and a WAV at most a minute (the other
   containers' minute is the page's limit plus the byte limit); one AI slot per person; the clip is forwarded as multipart (`model`,
   `response_format=json`, `file` under the app's own name) and `{text}` comes back cleaned by the chat's text policy (NFKC, control
   characters out, at most 2000 characters). **The audio and the transcript are never written to disk or the database and never
   logged**; one `ai_audit` row without content (`feature "voice"`, host, model, a length bucket, the outcome). A per-person daily limit
   (`STT_DAILY_LIMIT`, 100; counted in `ai_usage` under provider 0 with `key_scope 'own'`, so `ai.shared_daily_limit` never includes it).
3. **Consent.** Purpose `voice` in `ai_consents` (schema step **14**, the table rebuilt from its stored definition with `'voice'` added, so a
   column added by another step is kept). The row keeps the transcription **host** in `host` and, for its key, the id of the AI
   provider that serves the person (the foreign key needs a provider row; no `ai_providers` row is made for the transcription server).
   Its own sheet: "Your recording is sent to <host> to turn it into text, then deleted. Nothing is kept."; no "show me the request"
   choice (there is no request yet); asked **before the microphone is opened**.
4. **Browser** (`js/views/ask-voice.js`, attached to Ask by two hook lines in `ask.js`). The microphone button appears only when
   `GET /api/ai/status` says `features.voice`. Tap to record (`MediaRecorder`, 32 kbit/s), tap again to stop or at 60 seconds; a visible
   "Recording" row with the time and Discard; leaving the tab or page or pressing Escape discards; the microphone is released after every
   recording; the audio stays in memory. The transcript goes **into the question box** (after anything typed) for the person to read and
   edit, **never sent automatically**. No `MediaRecorder`, no secure context or a refused microphone: one plain line.
5. **Read aloud.** A per-device switch "Read answers aloud" (`localStorage` in `try`, off by default) using `speechSynthesis` **only with
   voices whose `localService === true`**; none: the switch is hidden with a note. Only the checked answer text of an answer, a low or an
   emergency is spoken, links and handbook paths removed; never the cards or the figures.
6. **Header.** `Permissions-Policy: ... microphone=(self) ...`; everything else unchanged.
7. **Deployment.** `deploy/compose.stt-whisper.yaml`: an optional overlay; the container on an `internal` network with no route out, image
   pinned by digest (a marked placeholder until the deployer verifies one), `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, a non-root
   user, a model volume mounted read-only (filled once beforehand), limits, a health check; the app points at it with `AI_PRIVATE_HOSTS`.

**Tests.** `tests/test_ai_voice.py` (the 404s before the body, sign-in, consent 409 and per-person consent, type and first bytes, the size
limit declared and streamed, the multipart form and the key as a bearer token, the cleaned transcript, upstream failures, the address
rules for a private or metadata address, plain http and the allowlist, the daily limit, **nothing stored or logged** by scanning the data
directory, every table and the captured logs, the activity row, the key never returned, the admin view and test, the environment),
`tests/test_migration_m014.py` (built on `steps()[:13]`), `tests/test_ask_voice_ui.py` (static: no speech recognition under any
spelling, transcript to the input and never sent, device voices only, no inline script, text only, no storage of audio, the header),
`tests/test_deploy_stt.py`, the settings vectors (`ai.voice_enabled`), and `python tools/e2e/ask_voice.py` in Chromium (82 checks).

**Open for the owner.** Verify the container image's digest and a real whisper container on the home lab; try the microphone on a real
iPhone (Safari) and an Android phone; decide the daily limit; the owner may prefer to key the voice consent to something other than the AI
provider's id (a schema change for a nullable key) if that is ever needed.

## Next (not in this part)

* ~~**Part B, voice**~~: built; see "Part B: voice" above. (The first idea, the browser's speech recognition, was rejected:
  Chrome sends that audio to Google and Safari to Apple, outside the owner's control.)
* ~~Saving from chat~~: done in part C above (a card the person presses, or trusted saves behind a switch and a warning).
* **Recipe pages** in `check_meal` (step 1's follow-up), so the chat can work from a recipe link.
* A live golden run of the chat cases and a prompt wording from the profile (kidney-only) belong to the owner.
