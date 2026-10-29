# Changelog

All notable changes to this project, written for the people who run it. Dates are UTC. The project
follows [semantic versioning](https://semver.org/) from 0.3.0 on; until then minor versions could change
the API. Security fixes are released as patch versions of the newest minor version
([SECURITY.md](SECURITY.md#supported-versions)).

## Unreleased

### For people who run a server

* **Two-step sign-in.** Anyone with a password can turn it on in **Settings → Account → Two-step sign-in**. Signing in then needs a
  6-digit code from an authenticator app on their phone too, and ten recovery codes cover a lost phone. It is off until a person turns
  it on. A lost phone and lost codes: **Server administration → People → Remove two-step sign-in**, or
  `python -m app.admin remove-two-step USERNAME`. The QR code is drawn in the browser from a vendored library, so the secret goes to
  no other site. Schema step 22 adds two tables and changes nothing else. See [`docs/accounts.md`](docs/accounts.md#two-step-sign-in)
  and [design note 17](docs/dev/research/17-two-step-sign-in.md).
* **Admins can be made to use two-step sign-in.** A new switch, **Server administration → Server settings → Admins must use two-step
  sign-in**, or `AUTH_REQUIRE_TWO_STEP_ADMINS=true`. While it is on, an admin without two-step sign-in can still use the app, but
  Server administration only shows a note sending them to turn it on. You can turn the switch on only after turning on your own.
  It is off by default.
* **Passkeys.** Anyone with a password can add passkeys in **Settings → Account → Passkeys** and then use **Sign in with a passkey**:
  the phone or computer asks for a fingerprint, face or PIN, and no password or code is typed. The password keeps working. Passkeys
  need the server's name, not an IP address: set `PUBLIC_URL` to the address people open. A lost device: **Server administration →
  People → Remove passkeys**, or `python -m app.admin remove-passkeys USERNAME`. No new dependency; the checks are tested against the
  W3C test vectors and Chromium's virtual authenticator. Schema step 23 adds one table and changes nothing else. See
  [`docs/accounts.md`](docs/accounts.md#passkeys) and [design note 18](docs/dev/research/18-passkeys.md).

### For contributors

* **The first part of the iOS app.** `ios/KidneyHealthCore` is a Swift package with the rules the Health sync app must share with the
  server: ranges, the time of day a reading gets, the watch rule, kilogram rounding, the key that stops a reading being added twice,
  and requests of at most 50 rows. It checks each row the way the phone route does before sending, because one refused row would block the
  whole request. It has no dependencies. CI runs `swift test` on Linux against `tests/data/body_vectors.json`,
  `apple_health_vectors.json` and the new `push_vectors.json` (`tests/data/gen_push_vectors.py`). See
  [note 15](docs/dev/research/15-native-ios-app.md).
* **The iPhone app, ready to sign.** `ios/KidneyHealthSync` reads new weights and blood pressure readings from Apple Health and sends
  them to your server with a phone token. It reads nothing else and never writes to Health. The first sync starts three months back.
  CI builds it and runs its tests in the iPhone simulator. Putting it on a phone needs the owner's Apple Developer account, which is the
  next step. See [`ios/README.md`](ios/README.md).
* **Test connection in the iPhone app.** A new route, `GET /push/v1/check`, tells a phone whether its token works without sending
  anything. It takes the same token as `POST /push/v1/body` and counts toward the same 60 requests an hour. If a reverse proxy lists
  the paths it passes on, `/push/v1/` already covers it. The second host name in `deploy/caddy/Caddyfile.example` now passes it too.
  See [`docs/push.md`](docs/push.md#testing-a-token).

## 0.8.0 — 2026-10-28

Version 0.8 adds recipes from AI. If your server offers it, the AI can suggest a recipe for a meal or rework one of yours. The AI
only picks foods and amounts from a list the app's rules made. The app works out every number, fits the recipe to your targets the
same way **Fit to my targets** does, and lists what it changed. Nothing is saved until you tap.

**Before you upgrade, read [Upgrading from 0.7](#upgrading-from-07-read-this-first).** There is no schema step, and nothing new is
switched on.

### Highlights

* **Suggest recipes with AI** in Plan, and **Rework with AI** in the Fit to my targets sheet. Each card shows the foods for the
  whole pot and one serving's numbers. **Save recipe**, **Add to plan** and **Dismiss** do what they say.
* **What is never sent:** a recipe's name, note, steps and link. A saved recipe with a food you use to treat a low is never sent.
* **Low treatments, alcohol, foods to avoid with kidney disease, "Not for me" foods, table salt and salt substitutes** are never
  offered to the AI, and the app checks the answer for them again.
* **Cooking steps written by AI are off** until an admin turns them on after a live test run.

### Upgrading from 0.7 (read this first)

1. **Back up first** (`podman exec kidney-health python -m app.admin backup /data/before-0.8.0.db`). This release has no schema
   step, but keep the habit.
2. **Coming from 0.6**, schema step 21 runs at the first start; from 0.5, steps 20 and 21 do. Read
   [Upgrading from 0.6 or 0.5](#upgrading-from-06-or-05-read-this-first) too.
3. **Change the tag** to `:0.8`, or pin a digest from the release notes. The shipped files already say `:0.8`.
4. **Nothing new is switched on.** The new AI feature `recipes` runs on the local AI by default (`AI_ROUTE_RECIPES=local`), and only
   for people who agree to Meal data. AI cooking steps stay off until you set `AI_RECIPE_STEPS=true`.
5. **Everyone who uses AI is asked to agree to Meal data again** (`POLICY_VERSION` `2026-10-27.1`), because it now covers a
   recipe's foods and amounts.
6. **New `PROMPT_VERSION` (`2026-10-27.2`).** Run `scripts/ai_eval.py` again for each model you use. The report now measures
   recipes too, with three new gates.

### Known limitations

* AI cooking steps stay off until the owner's live run of `scripts/ai_eval.py` on the cloud chain shows no unsafe step and a
  surviving recipe in at least 70 % of cases.
* The recipe rules, like the rest of Fit to my targets, wait for a dietitian's review (`handbook/REVIEW.md`).
* Values are estimates from the foods in the recipe. Cooking losses are not counted.

### For people using the app

* **Recipes from AI (optional).** If your server offers it, Plan has **Suggest recipes with AI** and the Fit to my targets sheet
  has **Rework with AI**. The AI picks foods the app's rules chose; the app works out every number, fits the recipe to your
  targets and lists what it changed. **Save recipe** adds it to your saved meals; nothing is saved before you tap. Your
  recipe's name, note, steps and link are never sent. See
  [Planning and menus](handbook/docs/app/planning-and-menus.md#recipes-from-ai-optional).

### For people who run a server

* **AI recipes.** `POST /api/ai/recipes` suggests up to two recipes for a meal, or reworks one of yours, from
  foods the rules chose. The app works out every number, fits the recipe to your targets as Fit to my targets does, and saves
  nothing. It is a new feature `recipes`: `AI_ROUTE_RECIPES` (default `local`) says where it runs, and it is agreed under the
  Meal data consent. Cooking steps written by AI stay off until you set `AI_RECIPE_STEPS=true` after a live run. See
  [docs/ai.md](docs/ai.md#recipes-that-fit).
* **Everyone is asked to agree to Meal data again**, because it now covers a recipe's foods and amounts (`POLICY_VERSION`
  2026-10-27.1).
* **New `PROMPT_VERSION` (`2026-10-27.2`).** Run `scripts/ai_eval.py` again for the models you use. The report now measures
  recipes too, with three new gates.

### For contributors

* 21 new golden cases (`tests/ai_golden/recipes-*.json` and one privacy case), `tests/test_ai_recipes.py`,
  `tests/test_ai_recipe_steps.py`, `tests/test_recipes_ai_ui.py`, and the Chromium walk `tools/e2e/recipes_ai.py`.

## 0.7.0 — 2026-10-27

Version 0.7 is about recipes. A saved meal can now be a recipe that makes several servings, with steps and a link. **Fit to my
targets** checks one serving against a meal today or against what is left today. If it does not fit, the app changes the recipe
itself and lists every change: it lowers amounts, swaps a food or offers a smaller serving. No AI is involved, and nothing new is
sent anywhere.

**Before you upgrade, read [Upgrading from 0.6 or 0.5](#upgrading-from-06-or-05-read-this-first).** The first start migrates the
database (schema step 21); take a backup first.

### Highlights

* **Recipes.** A saved meal can hold the amounts for the whole pot, how many servings it makes, cooking steps and a source link. The
  list shows one serving's numbers.
* **Fit to my targets.** Amounts go down (never protein, never below half), at most 2 foods are swapped (never one you use to treat a
  low), or a smaller serving is offered. Save the result as a new recipe, or replace yours with a confirm and Undo.
* **What fits now judges a recipe one serving at a time.** A 4-serving stew saved by Ask is no longer judged as one meal.

### Upgrading from 0.6 or 0.5 (read this first)

1. **Back up first** (`podman exec kidney-health python -m app.admin backup /data/before-0.7.0.db`). The first start runs schema step
   21: saved meals gain three columns for recipes. A recipe saved by Ask or an assistant gets its servings and link copied from its
   note; no note changes.
2. **Coming from 0.5**, step 20 runs in the same start. Read [Upgrading from 0.5](#upgrading-from-05-read-this-first) too.
3. **Change the tag** to `:0.7`, or pin a digest from the release notes. The shipped files already say `:0.7`.
4. **Nothing new is switched on, and there is no new setting.**
5. **New `RULES_VERSION` (`2026-10-27.1`)** for the six recipe numbers. Earlier guidance answers keep their old version.

### Known limitations

* Recipes from the AI (phase 3 of [note 16](docs/dev/research/16-recipes-that-fit.md)) are not built yet.
* The half floor, the protein rule and the order of changes wait for a dietitian's review (`handbook/REVIEW.md`).
* Values are estimates from the foods you entered. Cooking losses, such as potassium that leaches into boiling water, are not counted.

### For people using the app

* **Recipes, and "Fit to my targets".** A saved meal can now be a recipe: put the amounts for the whole pot in its foods, how many
  servings it makes in **Makes**, and if you like the cooking steps and a link to where it came from. The list shows one serving's
  numbers. **Fit to my targets** on any saved meal checks one serving against a meal today or against what is left today. If it does
  not fit, the app lowers amounts (never protein, never below half), swaps a food (never one you use to treat a low) or offers a
  smaller serving, and lists every change. **Save as a new recipe** keeps yours and adds "<name> (fitted)"; **Replace this recipe**
  asks first, shows carbohydrate per serving before and after, and can be undone. It works in the demo too. See
  [Planning and menus](handbook/docs/app/planning-and-menus.md#fit-to-my-targets).

* **A recipe saved by Ask or a connected assistant is now judged one serving at a time in What fits now.** Such a recipe holds the
  amounts for the whole pot. Until now What fits now judged the whole pot as one meal, so a 4-serving stew almost never fitted. It now
  divides by the number of servings first. Plain saved meals are unchanged.

### For people who run a server

* **Schema step 21.** Saved meals gain three columns for recipes: how many servings the items make, cooking steps and a source link
  (never opened). A recipe saved by Ask or MCP before this release has its count and link in the note as "Makes 4 servings. Source:
  …"; the step copies them into the new columns and leaves the note as it is. Take a backup before the first start.
* **API.** `POST` and `PUT /api/meals` accept `servings_made`, `steps` and `source_url`; a `PUT` that leaves one out keeps it, and
  `null` clears it. Every saved meal now also gives `per_serving` (null when no food lists a nutrient, never 0) and `unknown` (how
  many foods do not list it). The export and import carry the three fields. `save_recipe` (Ask and MCP) writes the columns and no
  longer writes the sentence into the note. Nothing existing was removed.

* **`POST /api/guidance/fit-recipe`, new.** It checks one serving of a recipe against a meal or against what is left today. When it
  does not fit, it lowers amounts (never a protein food, never below half), swaps a food (at most 2) or suggests a smaller serving,
  and lists every change in plain words with the app's figures. It computes only and saves nothing.
  `RULES_VERSION` is `2026-10-27.1`; the six new numbers are in [docs/guidance.md](docs/guidance.md#recipes-that-fit).

### For contributors

* `app/static/js/engine/guidance/recipes.js` is the demo's twin of the engine; 11 recipe cases are in
  `tests/data/guidance_vectors.json` and replay in Node. `handbook/REVIEW.md` lists the half floor, the protein rule and the order for
  a dietitian to confirm.
* New tests: `tests/test_recipes_ui.py`, `tests/guidance/test_recipe_fit.py` (the engine and the route), `tests/test_migration_m021.py`, `tests/test_recipes_api.py`, and a What fits now case in
  `tests/guidance/test_api_guidance.py`. Phases 0 to 2 of [note 16](docs/dev/research/16-recipes-that-fit.md), the fit without AI.
  AI recipes (phase 3) come next.

## 0.6.0 — 2026-10-27

Version 0.6 is about the AI helpers. A server can now have a local AI and a cloud AI, both set from the environment, and the cloud
one can be a proxy that tries one company and then another. The consent sheet names every company that may see a request. Server
administration shows how well each AI is doing, so a model that answers "nothing fits" to every meal idea is easy to spot. The
answer format now asks for the ideas before "nothing fits", which helps small local models. Two access fixes came out of a review
of who can reach what. As before, everything that sends data off your server is **off until an admin turns it on**, and lab report
photos go only to the local AI.

**Before you upgrade, read [Upgrading from 0.5](#upgrading-from-05-read-this-first).** The first start migrates the database (schema
step 20); take a backup first.

### Highlights

* **A local AI and a cloud AI, both from the environment** (`AI_CLOUD_PROVIDER` and the other `AI_CLOUD_` settings).
* **The consent sheet names the company behind a proxy**, or each company of a chain, in the order they are tried.
* **How well each AI is doing**, in Server administration → AI providers: counts of usable answers, and whether the model passed
  `scripts/ai_eval.py`. It only advises; it never turns a feature off or moves it to another AI.
* **The answer comes before "nothing fits"** in meal ideas, re-order, swaps, plans and describe a meal.
* **Security:** changing `AUTH_MODE` ends every assistant and phone-shortcut token, and the database files are `0600` whatever the umask.

### Upgrading from 0.5 (read this first)

1. **Back up first** (`podman exec kidney-health python -m app.admin backup /data/before-0.6.0.db`). The first start runs schema step
   20: the AI provider list gains `env_slot` and `upstream`. The provider you have keeps every setting.
2. **Change the tag** from `:0.5` to `:0.6`, or pin a digest from the release notes. The shipped files already say `:0.6`.
3. **Nothing new is switched on.** `AI_CLOUD_PROVIDER` and `AI_EVAL_REPORTS_DIR` do nothing until you set them. If you set
   `AI_CLOUD_PROVIDER` next to `AI_PROVIDER`, `AI_PROVIDER_ROLE=local` is required.
4. **A changed `AUTH_MODE` revokes tokens.** A start with a different mode than the last start already signed everyone out. It now
   also ends every assistant and phone-shortcut token, and people make new ones in Settings. Starting 0.6.0 with the mode you had
   on 0.5 revokes nothing.
5. **Outside a container**, `DATA_DIR` becomes `0770` and `kidney.db` with its `-wal` and `-shm` files `0600`. A backup tool that
   reads the file as another user needs the app's user, or use `python -m app.admin backup`. The images do not change.
6. **New `PROMPT_VERSION` (`2026-10-27.1`).** Reports from `scripts/ai_eval.py` for the old version show as "for an older version".
   Run it again for the models you use.

### Known limitations

* The new answer order was tested with the recorded answers in the test suite, not yet with a real small local model. Run
  `scripts/ai_eval.py` on 0.5.1 and on 0.6.0 to see the difference for yours.
* A chain of companies behind one proxy is one provider to the app: the activity list, the counts, the evaluation and `ai_eval` cannot
  tell which company answered. To judge each one, point `ai_eval` at a proxy alias that uses only that company.

### For people using the app

* **A cloud AI that goes through your admin's own server says so.** If your admin runs a LiteLLM proxy (or another server) that passes
  your request on to a company's model, the consent sheet and the provider list now name the company: "Goes through your admin's LiteLLM
  proxy to Anthropic. Anthropic receives what is sent, under its own terms; your admin can read it too." Nothing else you have agreed to
  changes, and nobody is asked again for an AI they already agreed to. You are asked again for this one if your admin names a different
  company.

* **Assistant and phone shortcut tokens end when your admin changes how the server signs people in.** If you see a token as revoked in
  Settings, and "sign-in mode changed" in your activity, this is why. Make a new token. Nothing else about your account changes.

### For people who run a server

* **A chain of companies behind one proxy.** `AI_CLOUD_UPSTREAM` can name up to 3 companies in the order the proxy tries them, separated by
  `;` (`OpenAI (ChatGPT); Anthropic (Claude)`), and brackets are allowed. The consent sheet then names each one and says when the next is
  used. One name works as before. The activity list, usage counts, "How well each AI is doing" and `ai_eval` see the chain as one provider
  ([docs/ai.md](docs/ai.md#a-proxy-that-falls-back-from-one-company-to-another)).
* **Meal ideas and describe a meal: the answer comes before "nothing fits".** The answer format now lists the ideas (or the order, the
  swaps, the plan, the foods) before the status and the refusal. A model that writes the keys in order then works out its ideas before it
  decides that nothing fits. With the refusal first, a small local model often took that exit at once. `PROMPT_VERSION` is `2026-10-27.1`,
  so run `scripts/ai_eval.py` again for the models you use; reports for the old version show as "for an older version".
* **Security: tokens made while sign-in was off no longer survive switching it on.** With `AUTH_MODE=none` anyone who can reach the server is
  user 1, an admin, and can make assistant (`kha_`) and phone shortcut (`khd_`) tokens that last up to a year. After you switched to `local`,
  those tokens still worked. Now any change of `AUTH_MODE` since the last start revokes every active token of both kinds, for every person.
  The log says how many, each person's activity gets one "Tokens revoked" row (reason `auth_mode_changed`), and people make new tokens in
  Settings. Starting with the same mode revokes nothing. No schema step.
* **Security: the database is no longer readable by every user on the computer.** Outside a container, `DATA_DIR` and `kidney.db` took their
  modes from the umask, usually `0755` and `0644`. The app now makes `DATA_DIR` `0770` and sets `kidney.db` and its `-wal` and `-shm` files
  to `0600` at every start, and removes "other" access from an existing data folder it owns. The start never fails over this: a mode the app
  cannot change is a log warning that names the command to run. `secret.key`, backups and exports were already `0600`. The images are
  unchanged (`/data` is `10001:0`, mode `0770`).
* **Docs.** [`docs/ai.md`](docs/ai.md) says how to make the two LiteLLM keys really limited (one virtual key for each use, allowed models,
  never the master key, budgets, the admin screen off the open network), warns that the promise about lab report photos depends on it, and
  has a section on model servers on another machine (firewall 11434 and 4000, no plain `http://` across a LAN). The Caddy example shows how to
  expose only `POST /mcp` and `POST /push/v1/body`. `ENABLE_API_DOCS` now says it is for development machines only. `docs/privacy.md` says that
  the AI quality section may let an admin guess whose calls they were on a very small server.
* **A local AI and a cloud AI, both from the environment.** Until now only one provider could come from the environment (`AI_PROVIDER`);
  a second one had to be added in the app. `AI_CLOUD_PROVIDER` adds the second one, and it is **always the cloud AI**: `AI_CLOUD_BASE_URL`,
  `AI_CLOUD_API_KEY_FILE` (or `AI_CLOUD_API_KEY`), `AI_CLOUD_MODEL`, `AI_CLOUD_VISION_MODEL`, `AI_CLOUD_TIMEOUT_S`, `AI_CLOUD_MAX_TOKENS`,
  `AI_CLOUD_CONTEXT_TOKENS`, `AI_CLOUD_STRUCTURED_OUTPUT`, `AI_CLOUD_REASONING_EFFORT` and `AI_CLOUD_UPSTREAM`, read, defaulted and checked like
  the `AI_` variables of the same names. It is a second "Set by the server" row in Server administration → AI providers; it cannot be
  edited or deleted there, and the cloud role cannot be changed there either (`409`, naming `AI_CLOUD_PROVIDER`). A server with only the
  `AI_CLOUD_` variables is fine. With both set, `AI_PROVIDER` needs `AI_PROVIDER_ROLE=local`; `cloud` there, or no role, stops the start with a
  message. `hermes` is refused for the cloud AI. The cloud AI may be on your LAN (a LiteLLM proxy with a cloud-only key); it is then listed in
  `AI_PRIVATE_HOSTS` like every shared provider, and the start stops with a message saying so if it is not. Listing it does not make it the
  local AI. **Lab report photos still go only to the local AI**: with the local AI unreachable, switched off or gone they fail, and they are
  never sent to the cloud key; tests with two environment providers pin this. `AI_CLOUD_` variables without `AI_CLOUD_PROVIDER` give a start-up
  warning. The [recipe in `docs/ai.md`](docs/ai.md#a-local-ai-and-a-cloud-ai-both-from-the-environment) has a full example (one LiteLLM proxy,
  a local key and a cloud key, every `AI_ROUTE_*`), and says why photos stay `local` when they may show names. `deploy/.env.example`,
  `deploy/compose.yaml`, the Quadlet and Kubernetes examples and the handbook's configuration page list the new variables.
* **`AI_CLOUD_UPSTREAM` names the company a proxy forwards to.** A server you run (`litellm`, `vllm`, `ollama`, `lmstudio`, `llamacpp`,
  `openai_compatible`) as the cloud AI forwards to a company, so "Runs on your admin's hardware" would be untrue. The company's plain name is
  therefore required for it (letters, digits, spaces and `.` `&` `-`, at most 60 characters); the start stops without it. For `openai`,
  `openrouter` and `nous_portal` it is ignored, with a warning. Changing it asks everyone again, as a new host does. No existing consent line
  changed and `POLICY_VERSION` is the same, so nobody is asked again for a provider they already agreed to.
* **The cloud AI's prompt budget is 32,768 tokens** (`AI_CLOUD_CONTEXT_TOKENS`) even when its preset is self-hosted, so a cloud model behind
  LiteLLM is not held to the local 8,192 and keeps more candidate foods. The first provider's budget is as before.
* **Schema step 20.** `ai_providers` gains `env_slot` (`main` for `AI_PROVIDER`, `cloud` for `AI_CLOUD_PROVIDER`) and `upstream`; the one-row unique
  index for the provider the environment defines becomes one row per slot. The row you have today becomes `main` and nothing in it changes.
  Take a backup before the first start, as for any release with a schema step.
* **API.** `GET /api/admin/ai-providers` gives each provider `env` (`AI_PROVIDER` or `AI_CLOUD_PROVIDER` for a locked one) and `upstream`, and
  the list `env_cloud_provider`; `GET /api/admin/ai-routing` gives `env_cloud` and `env` on each provider. A consent request carries `upstream`.
  Nothing existing was removed.
* **Server administration now shows how well each AI is doing.** **AI providers** has a new section under "Which AI does each feature use?".
  It has a row for each feature that is on, with the AI and model it uses and two facts. *In use* counts the last 20 calls of that feature
  to that model in the last 14 days, from everyone: usable answers, "nothing fits", could not read, refused, dropped by the checks, invalid
  and errors. With 8 calls or more, a caution appears when 70 % or more had no usable result. This is how a small model that answers
  "nothing fits" to every meal idea becomes visible. Only counts are shown, never what anyone asked or got back. *Evaluation* says whether the
  model passed `scripts/ai_eval.py` for the current prompts. The same two facts are in `GET /api/admin/ai-quality` (admins, read only).
* **`AI_EVAL_REPORTS_DIR`, new and optional.** A folder, mounted read-only, with the reports `scripts/ai_eval.py` writes. The app reads it
  at start-up and each time the section is refreshed: at most 200 files of 1 MiB, and never a link that leads out of the folder. With it set,
  the start-up log gets one `AI quality:` warning for each feature that is on and whose model failed the evaluation or has no report for
  the current prompts. Lab report photos are not covered by the evaluation, so the section says to check a real report by hand. Unset, the section
  says there is no reports folder. The mount for Podman, compose and Kubernetes is in [docs/ai.md](docs/ai.md#how-well-each-ai-is-doing).
* **One more number in the AI activity row.** A described meal or a plate photo now records how many items were offered (`shown`), so "every
  item was dropped by the checks" can be told from "some were". No schema step; earlier rows are counted by their status.

### For contributors

* **`scripts/ai_eval.py --role local|cloud` and `--upstream NAME`.** `cloud` (the default for `openai`, `openrouter` and `nous_portal`) configures
  the `AI_CLOUD_` provider, reads the key from `AI_CLOUD_API_KEY`, pins the features to `cloud` and uses the cloud prompt budget, so a run sends
  what the server's cloud route sends (a test compares the two request bodies). A self-hosted preset with `--role cloud` needs `--upstream`.
  The report's `provider` block records the `role` and the `upstream`, and the slowest-answer limit follows the role. See
  [`docs/dev/ai-eval/README.md`](docs/dev/ai-eval/README.md).
* New tests: `tests/test_ai_cloud_env.py`, `tests/test_ai_cloud_routing.py`, `tests/test_migration_m020.py`.

## 0.5.1 — 2026-10-27

A security release. Nothing in the app changed: the image is rebuilt on a newer Chainguard Python base, which fixes a critical
bug in the Brotli compression library that the base image carries.

### Upgrading from 0.5.0

Nothing to do but pull the new image. A host that tracks `:0.5` or `:latest` gets it at its next pull. There is no schema step and
no setting changed, so going back to 0.5.0 only means the old image.

### Security

* **CVE-2026-111497 (Critical) in Brotli.** The weekly image scan found it on 2026-10-26 (issue
  [#85](https://github.com/ksullivan86/kidney-health/issues/85)). The base image moves from `libbrotli` 1.2.0-r6 to 1.2.1-r2, which
  has the fix. The app itself does not decode Brotli: its own requests ask for plain or gzip answers, and no Python Brotli package
  is installed. The library comes with the base image, so this update is a precaution, and it clears the scan.
* The same base update brings a newer certificate bundle (`ca-certificates-bundle` 20261020), Python 3.15.1 and point releases of
  glibc, OpenSSL and SQLite.
* Not in this release: `opentelemetry-api` 1.45.1 (a Medium advisory, GHSA-xcq7-p3pf-p88h, pulled in by FastAPI). The weekly lock
  refresh picks it up once it is 7 days old.

## 0.5.0 — 2026-10-22

Version 0.5 adds a log of weights and blood pressure, and three ways to fill it: type it, bring it in from the iPhone Health app, or send it
from an iPhone Shortcut. It also reads lab results from a PDF report, opens an export `.zip` without unzipping it first, and lets a chat
assistant you have connected remember your tastes if you allow it. We looked at every screen on a phone and on a computer and fixed what
looked wrong. As in 0.4, everything that sends data off your server is **off until an admin turns it on**, and each person decides for
themselves.

**Before you upgrade, read [Upgrading from 0.4](#upgrading-from-04-read-this-first).** The first start migrates the database (schema
steps 18 and 19); take a backup first.

### Highlights

* **Weight and blood pressure.** **Today** has a card to add a weight or a blood pressure reading, and **Trends** has a chart for each, with
  7-day averages. You can enter the two numbers your care team gives you, a weight-gain alarm and a blood pressure goal; the app suggests
  neither. A very high reading shows the handbook's own words for when to get help. **Get ready for a visit** includes your latest numbers.
  The app records and shows. It says nothing about why a number is what it is and never suggests a medicine. You can also bring in past
  weights and readings from the iPhone Health app: the file is read on your phone, nothing is uploaded, and readings from a watch are listed
  apart and left unticked.
* **Choose the `.zip` itself.** **Import from a file**, the Health app import and **Labs → Import from Apple Health** take the `.zip` as it is.
  It is opened on your device, and only the file each import needs is read out of it.
* **Lab results from a PDF.** **Labs → Read a lab report photo or PDF** takes the PDF your lab's website gives you. The PDF is opened on your
  device. Only the pages you tick, drawn as pictures, go to the AI on your own network, and you tick which rows to keep.
* **Phone shortcuts** (an admin turns them on). A token you make in Settings lets an iPhone Shortcut add your latest weight or blood
  pressure to your own log. It can only add: it reads nothing and changes nothing. You can revoke it, and delete what it sent, at any time.
* **Your assistant can remember a taste, if you let it.** A chat assistant you have connected can remember that you like a food or do not
  want it, when you tick a separate box on its token. Every change is in your activity list, and there is a daily limit. It cannot take a
  food that treats a low out of the Treating a low options.
* **Tidier screens.** The app's name no longer shows as "K…", warning lines are no longer pushed apart by a link, the two number boxes
  on the blood pressure sheet line up, and a few boxes take the whole row on a phone so their words are not cut off.
* **For people who run a server.** One new switch, `PUSH_ENABLED`, off by default; two schema steps; a checked-in API document
  (`docs/api/openapi.json`) and `GET /api/meta` for anyone who builds their own client.

### Upgrading from 0.4 (read this first)

1. **Back up `kidney.db` first.** The first start migrates the database in place (schema 17 → 19: steps 18 and 19), each step in its own
   transaction. Nothing for you to run: they happen when the server starts. As in 0.4, neither step makes an automatic copy. For example,
   with the running container: `podman exec kidney-health python -m app.admin backup /data/before-0.5.0.db` (or `backup --dir DIR --keep N`
   for a backup tool). What the steps add, nothing removed: 18 two tables, `weights` and `blood_pressures`, for the weight and blood
   pressure log (deleted with the account); 19 a column on both that records which phone-shortcut token sent a row (empty for every
   earlier row). No value that exists changes. To go back to 0.4, restore the backup you took; 0.4 is not tested on a database that 0.5 has
   migrated, and anything entered after the upgrade is lost.
2. **Change the image tag from `:0.4` to `:0.5`.** The minor tag does not move to the next minor on its own, so a host that tracks `:0.4`
   stays on 0.4.x until you change it. The shipped Quadlet unit, compose file and Kubernetes base already say `:0.5`; or pin the digest in
   the release notes after `scripts/verify-image.sh 0.5.0`. **`:latest` moves to 0.5.0 with this release**, as it does with every release
   from 0.4.0 on, so a host that auto-updates `:latest` upgrades itself, and migrates its database, at its next pull
   ([docs/deployment.md, "From v0.4 to v0.5"](docs/deployment.md#from-v04-to-v05)).
3. **Headers.** The app's Content-Security-Policy now ends `trusted-types kh-sw kh-xml kh-pdf` (it was `kh-sw kh-xml`). If a reverse proxy
   sets your CSP instead of the app, add `kh-pdf` there, or choosing a PDF lab report says "This browser cannot read a PDF here". If your
   proxy lists the paths it passes on and you want phone shortcuts, add `/push/v1/` next to `/mcp`. Nothing else in the headers changed.
4. **Nothing new is switched on.** Phone shortcuts (`PUSH_ENABLED`) are off until an admin turns them on, and a token that can remember
   tastes exists only when a person ticks the box for it. Tokens made before the upgrade keep what they could do and gain nothing. Nothing
   leaves your server for any of this. Reading a PDF uses the same local-only lab report AI as a photo (`AI_ROUTE_LABS`), so it stays off
   while no local AI exists.
5. **Things that behave differently without you changing anything:**
   * Everyone gets a weight and blood pressure card on Today, two charts in Trends, "Latest in your log" hints in Profile and a section in
     the visit page. They are empty until someone adds a number. Weights are typed and shown in pounds unless you change the default for
     everyone (Server administration → Server settings → Default for everyone → Units for weight) or a person changes their own.
   * Get help now gained two lines about a blood pressure of 180/120 or higher, in the handbook's words.
   * The data export gains `weights` and `blood_pressures` (and `weights.csv`, `blood_pressure.csv`); the export version stays 1 and older
     files still import.
   * In Server administration → People, the button is now **Revoke tokens** and ends assistant tokens and phone-shortcut tokens alike.
   * The API document changed shape: operation ids are `<first tag>_<route function>` (`auth_login`), and validation errors are
     listed as the 400 the routes always sent, not FastAPI's 422 (the routes answer as before). If you generated a client from the
     live `/openapi.json`, generate it again. The live `/openapi.json` and `/docs` stay off unless `ENABLE_API_DOCS` is on.

**New optional settings and permissions** (all off or at a safe default; the full list is in
[docs/deployment.md](docs/deployment.md#configuration) and `app/config.py`; settings not set in the environment can be changed in
Server administration → Server settings):

| Area | Setting |
|---|---|
| Phone shortcuts | `PUSH_ENABLED` (off): device tokens and `POST /push/v1/body`. Also in Server administration → Server settings → Phone shortcuts. `deploy/.env.example` lists it, `compose.yaml` passes it through, and the Quadlet and Kubernetes examples have a commented line |
| Weight and blood pressure | `user.units.weight` (`lb` or `kg`, default `lb`; the default for everyone, and each person can set their own); `body.weight_alarm` and `body.bp_goal` (personal, empty until a person enters their care team's numbers). None is an environment variable |
| Token permission | `assistant:prefs`: a new permission on an assistant token, off by default and ticked per token in Settings → Assistant access (**Also let it remember tastes (likes and dislikes)**). It needs `ASSISTANT_ENABLED`. Phone-shortcut tokens hold the fixed permission `body:write` |
| Limits | A person may hold 5 phone-shortcut tokens besides 5 assistant tokens; a shortcut token: 50 rows a request, 60 requests an hour; weight and blood pressure imports: 60 requests an hour per person; an assistant token that remembers tastes: 30 changes a day |

**Anything an admin must do:** the backup and the tag in steps 1 and 2, and the `kh-pdf` and `/push/v1/` lines in step 3 if they apply to
your proxy. Nothing else is required. Phone shortcuts are the one new thing you may want to turn on.

### For people using the app

* **Weight and blood pressure.** **Today** has a card for the day's weights and blood pressure readings, with **Add weight** and **Add blood
  pressure**. Nothing is saved until you press Save, and you can edit or delete an entry. A weight is typed in pounds or kilograms (your
  choice in **Settings → Weight and blood pressure**, pounds first), and the sheet shows the other unit under the box. You say when it was
  taken: morning, before or after dialysis, or other (the dialysis choices show only if your Profile says dialysis). A reading has the top
  number, the bottom number and an optional pulse, with one line on how to measure. What you typed is repeated back ("Top 180, bottom 95")
  so a slip shows before you save. Both need the connection to your server and say so when you are offline.
* **The two numbers your care team gives you, and nothing else.** In **Settings → Weight and blood pressure** you can enter a weight-gain
  alarm ("call my team if my weight goes up by more than ... between sessions, or in n days"; between sessions only on hemodialysis) and a
  blood pressure goal ("under ... / ..."). The app never suggests either. With an alarm, Today says how your weight changed and names the
  two weights it compared. With a goal, it shows your last 7 days' average against it. With neither, you see your numbers and no verdict.
* **The handbook's own words for a warning sign.** **Get help now** has two new lines about a blood pressure of 180/120 or higher. With a
  sudden severe headache, trouble breathing, pain in the chest, belly or back, numbness or weakness, a sudden change in vision or trouble
  talking, call 911 at once, without measuring again. Without those signs, rest 5 minutes and check again, and call your care team today if
  it is still that high. The lines come from the US National Heart, Lung, and Blood Institute and MedlinePlus, and the printable wallet
  card carries them in a few words. When you save (or are about to save) a reading with a top number of 180 or more or a bottom number of
  120 or more, Today shows these lines in a red block at the top of the card, the 911 line first, with a link to the page. A weight over
  your alarm shows the page's line about weight gain above the alarm number. The app says nothing about why and never suggests a medicine.
* **Charts, Profile hints and the visit page.** **Trends** has a weight chart and a blood pressure chart, each with a table under it and
  the 7-day averages. On hemodialysis the weight chart also shows your dry weight as a dashed line and marks the weights after dialysis.
  The blood pressure chart shows your goal as dashed lines. **Profile** shows "Latest in your log" under Weight (not on dialysis) and "In
  your log" under Weight 6 months ago, each with **Use this**: it only fills the box, and nothing changes until you press Save profile.
  **Get ready for a visit** gains a section with your latest weight, the change over six months, on hemodialysis the gains between your
  last sessions, your blood pressure averages for 7 and 30 days, how many readings were at or above your goal, and any reading the
  handbook points to.
* **A new handbook page, Weight and blood pressure** (Using the app): what to record, how to measure at home, which device (a validated
  upper-arm cuff; cuffless watches and rings are not recommended), that the alarm and the goal are your care team's numbers (and why the
  app has none of its own), and what the app shows and does not. First setup no longer says the app has no field for your weight-gain
  limit. **Settings → Your data → Import from a file** now counts weights and blood pressure readings in what it would add, what is already
  there and what it skips.
* **Bring weights and blood pressure in from the iPhone Health app.** **Import from Apple Health** (the buttons in Trends and in
  Settings → Your data) reads your Health export **on your phone**. Nothing is uploaded while it is read. You see what was found, what was
  left out and why, and the dates it covers, and only the weights and readings you keep are sent, in batches. You choose the last 3 months
  (the default) or everything. **Readings from a watch are listed apart and not ticked**, because cuffless devices are not recommended for
  checking blood pressure: you decide. Nothing else in the file is read (not heart rate, steps, glucose or insulin). The app keeps at most
  20 weights and 30 readings a day, so for a day with more it keeps the earliest and says how many were left out. If the server refuses a
  batch, the import stops, shows the server's words and how many were already added, and pressing Import again carries on. The handbook's
  "Using the app" page has the steps.
* **A reading is never added twice, whichever way it arrives.** Importing the same file again adds nothing. A weight or reading is also
  skipped when your log already holds one that you did not type, with the same day, the same minute and the same numbers. A reading you
  typed yourself never counts as a match, because you may have meant to record it twice.
* **Send weights and blood pressure from an iPhone Shortcut** (your admin turns it on). In **Settings → Account → Your data → Phone
  shortcuts**, give a token a name, choose when it ends (30 days, 90 days or 1 year) and press Make token. It is shown once, with **Copy**
  and the address to send to; you paste both into a Shortcut on your iPhone, and the Shortcut sends your latest weight or blood pressure
  to your own server. The handbook's Weight and blood pressure page has the recipe ("From a phone shortcut"). A token can only **add**
  weights and readings to your own log; it reads nothing and changes nothing. A reading from a watch is not stored. The list shows each
  token's last use and what it sent, with **Revoke** and **Delete what it sent** (it asks first, naming how many weights and readings
  go, and removes only what that token sent, never what you typed or imported). Rows a shortcut sent say "from a shortcut (name)" on Today
  and in a new "From" column in the Trends tables; rows from the Health app and from a file say so too. Until your admin turns phone
  shortcuts on, the block says "Your admin has not turned this on" (tokens that exist can still be revoked and their rows deleted). The
  app does not watch what a shortcut sends: a 180/120 reading shows its flag, with Get help now, the next time you open the app. The
  recipe is written from Apple's guide and has not been tried on a real iPhone yet. The demo has no server to send to and says so.
* **Choose the `.zip` itself: nobody has to unzip it first.** **Settings → Account → Your data → Import from a file** takes the `.zip` of an
  export of yours (or the `export.json` inside it, as before). **Import from Apple Health** (weights and blood pressure) takes the Health
  app's `export.zip`. **Labs → Import from Apple Health (clinical records)** takes the same `export.zip` and reads only the lab-result files
  in its `clinical-records` folder. The `.zip` is opened **on your device** with the browser's own tools and is never uploaded. Only the one
  file each import needs is read out of it (the Health `export.xml` in pieces, so a file of hundreds of megabytes is fine; Cancel stops
  it). A file that is damaged, not finished downloading or not an export from the Health app or this app is turned away with a plain
  reason. A browser that cannot do this (Safari before 16.4) shows the old advice to unzip the file first; choosing the unzipped files
  still works everywhere.
* **Read a lab report from the PDF your lab's website gives you.** **Lab results → Read a lab report photo or PDF** takes the PDF itself,
  not only a photo or a screenshot. The PDF is opened **on your device** and never sent anywhere. You see "Page 1", "Page 2", ... (pages 1
  to 6 start ticked, up to 10 can be ticked). Only the pages you tick are drawn on your device and sent as pictures to the AI at home, with
  the same local AI, consent and checks as a photo (the consent sheet says so), a "Reading page 2 of 4..." line and a Cancel button. The
  rows from all the pages come in one table, all unticked, each saying which page it came from. A row that repeats is shown once, and a
  page that cannot be read says so while the others still count. A PDF with a password, one over 20 MB or 50 pages, a damaged file and a
  browser too old to open it are each refused with the reason (a screenshot of each page still works). A scan made of JPEG 2000 or JBIG2
  pictures can come out blank. The handbook's AI page has the steps.
* **Let a chat assistant remember your tastes, if you choose to.** **Settings → Assistant access → New token** has a second box, **Also let
  it remember tastes (likes and dislikes)**. It is off by default and separate from **Can also save food and recipes**: neither gives the
  other. A token made with it lets the assistant you connected remember that you like a food or a kind of food, want it less often or do
  not want it, and forget one, the way **Ask** does but without a card to press. So it is limited to **30 changes a day per token**, every
  change is listed in your activity ("Assistant remembered a taste", with what it was, what it became and the token's name), and a food it
  sets shows in **Settings → Meal guidance → Your food preferences** as "from your assistant" with the usual **Remove**. A taste only
  changes what the app suggests. **It never changes Treating a low:** the assistant cannot mark a food that treats a low, or a kind of
  food that has one, as Not for me (that takes it out of the Treating a low options, as it does when you do it yourself), so only you can,
  in the app. Tokens you already have keep what they could do, and **Ask is unchanged**: it still shows a card for every taste. The
  handbook's AI page and its Settings and keys page say it in plain words.
* **Tidier screens.** We looked at every screen, on a phone and on a computer, in light and dark, and fixed what looked wrong. The top bar
  shows the app's name whole or not at all, never cut to "K…", and no longer runs past the edge of a narrow window. A handbook link under a
  warning no longer pushes the lines above it apart, and its arrow stays with the last word; the same goes for the links next to a
  sentence ("Check them in Profile", "How to make the shortcut"). On the blood pressure sheet the two number boxes line up. The **Include**
  box in Copy a day and the **Note** box in Lab results take the whole row on a phone, so their words are not cut off. In Lab results
  every row puts the date above the value. A long name under **Meals that fit** wraps to two lines. On Trends, the message about missing
  targets has its padding back. In Settings the buttons under **Your data** and **Signed-in devices** no longer touch the box above them.
* **Import from a file: choosing the same file again after closing the password prompt works.** Before, the file box kept the file, so
  choosing it again did nothing until you left Settings and came back. Closing the prompt now empties the box.

### For people who run a server

* **Phone shortcuts (off until you turn it on).** `POST /push/v1/body` takes a few weights and blood pressure readings from an iPhone
  Shortcut, with a **device token** (`khd_…`) a person makes for their own account. Turn it on with **Server administration → Server
  settings → Phone shortcuts** or `PUSH_ENABLED=true`; while off, the route answers `401` to everyone. The phone must reach the server (home
  network or your VPN), and a reverse proxy that lists the paths it passes on needs `/push/v1/`. A token can only **add** plausible weights
  and readings to its owner's log: up to 50 rows a request, 60 requests an hour, 20 weights and 30 readings a day, the same ranges as typed
  rows. It reads, changes and deletes nothing, and the answer is counts only. Readings whose source name contains "Watch" are refused
  (cuffless readings are not recommended; a Shortcut cannot ask), and the same reading sent twice, or sent and then imported from the
  Health export, is one row. Each person may hold 5 device tokens besides 5 assistant tokens. A password change and a disabled or deleted
  account end both kinds, and rows a token sent can be deleted together (`DELETE /api/me/tokens/{id}/body-rows`). In Server
  administration, **Revoke tokens** in People counts and ends both kinds, and the Activity log says "Phone shortcut token created / revoked" and "Phone shortcut data deleted". The handbook's configuration page lists
  `PUSH_ENABLED`. Details: [docs/push.md](docs/push.md).
* **Schema steps 18 and 19.** Step 18 (`m018_body_measurements.py`) adds the tables `weights` and `blood_pressures`, deleted with the
  account. Step 19 (`m019_body_token.py`) adds `api_token_id` to both, the device token that sent a row (empty for every earlier row, and
  set to empty when the token is purged, which keeps the row). The rows `GET /api/body/*` returns gain `via` (the token's name or `null`),
  `source` can now be `shortcut`, and `GET /api/admin/users` gains `device_tokens` next to `assistant_tokens`. They run at the first start
  of this version and change no value that exists (take a backup first, as for any upgrade).
* **Weight and blood pressure on the server.** The export gains `weights` and `blood_pressures` (and `weights.csv`, `blood_pressure.csv`);
  the export version stays 1 and older files still import. Three new personal settings (`user.units.weight`, `body.weight_alarm`,
  `body.bp_goal`) are carried over by an import with "Also replace my profile, targets and settings"; the unit's default for everyone is in
  Server administration. The routes under `/api/body` allow 60 batch requests an hour per person. Nothing leaves the server: weights and
  readings are never sent to an AI provider or the assistant ([docs/privacy.md](docs/privacy.md)).
* **A third assistant permission, `assistant:prefs`, and the MCP tool `set_food_preference`.** A person ticks it when making an assistant
  token (`can_prefs` on `POST /api/me/tokens`, off by default). It gives `assistant:read` and nothing else: `assistant:log` does not give
  it, it does not give `assistant:log`, and a phone-shortcut token can never hold it. `/mcp` lists the tool only for a token with the
  permission (anyone else is told "Unknown tool"). The tool takes one food or food group and `like`, `less`, `not_for_me` or `clear`, and a
  required `request_key`. It is limited to **30 changes a day per token** (`429` with `Retry-After`; counted in memory, so a restart
  empties it) on top of the 60 requests a minute, and it writes through the same function as the preferences screen with `source =
  'assistant'`. It refuses `not_for_me` for a food that treats a low and for a food group that holds one. Audit action
  `assistant.preference_set`; `export.json` carries `source: assistant` and an import accepts it. No new setting (`assistant.enabled`
  covers it), no schema step, no dependency. Details: [docs/assistant.md](docs/assistant.md).
* **Reading a PDF lab report needs nothing from you: no setting, route or schema step, and the server never sees a PDF.** It uses the local
  AI, `ai.route.labs`, the consent and the limits that lab report photos already have (each ticked page is one call). The one change is in
  the page's headers: the Content-Security-Policy now ends `trusted-types kh-sw kh-xml kh-pdf`. The new policy, `kh-pdf`, lets the page
  start the bundled pdf.js worker from `/vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs` and nothing else; `script-src`, `worker-src` and the
  rest are unchanged, with no `'unsafe-eval'` and no `blob:`. **If you set your own CSP at a reverse proxy, add `kh-pdf` to its
  `trusted-types` list.** The image carries 1.8 MB more of vendored files (`app/static/vendor/pdfjs-dist-6.4.299/`, Apache-2.0, pinned by
  SHA-256 in `vendor/README.md`); a browser fetches them only when a person picks a PDF.
* **Choosing a `.zip` in the imports changes nothing on the server**: no route, setting or migration, and the server still never receives
  an archive (the page opens it on the person's device and sends the same JSON or rows as before). The page ships one more script
  (`js/engine/zip.js`), so the app's update prompt appears once after the upgrade, as for any release.

### For contributors

* **A checked-in OpenAPI document** ([design note 14](docs/dev/research/14-reuse-map.md) change 2; guide: [`docs/api/README.md`](docs/api/README.md)).
  `python scripts/gen_openapi.py` writes `docs/api/openapi.json` (sorted keys, 2-space indent) from `create_app()` in-process, with no
  server and no network. `--check` exits 1 with a short list of what differs, and `tests/test_openapi_snapshot.py` runs it, so **changed
  a route? run the script** (one line in CONTRIBUTING). `ENABLE_API_DOCS` is unchanged: the live `/openapi.json` and `/docs` stay off by
  default. The document was wrong in four ways and `app/openapi_doc.py` now builds it: operation ids are `<first tag>_<route function>`
  (`auth_login`, `log_create_entry`) instead of `login_api_auth_login_post`, and a test holds them unique; validation errors are the
  **400** `{detail, errors: [{type, loc, msg}]}` the handler really sends (FastAPI's 422 is gone; the one real 422, the out-of-scope refusal
  of suggested targets, stays); every error status points at a shared `components.responses` entry with the one `Problem` shape
  (`{detail, ...}`), with a `default` on every `/api` operation; and the `securitySchemes` `session` (the cookie and the `X-Requested-With`
  header it needs), `assistantToken` (`kha_`, `/mcp`) and `deviceToken` (`khd_`, `/push/v1/body`) are applied from each route's
  dependencies. `info.version` is the app's version and the new `info.x-api-version` is `API_VERSION` (`app/api_version.py`, `1`): raise it
  on a breaking change only. No route behaves differently; `POST /mcp` gained `operation_id="mcp_post"`.
* **`GET /api/meta`** (design note 14 change 4; `app/meta.py`): signed in only, it answers `{app_version, api_version, capabilities,
  nutrients, meals}`. The capabilities are booleans for what the signed-in person can use now (`ai` and each AI feature, `chat`, `voice`,
  `assistant`, `push`, `barcode`, `barcode_off`, `barcode_usda`, `handbook`), each read from the switch or status function that already
  exists (the AI ones from the new `status_view` behind `GET /api/ai/status`, the barcode ones from the new `barcode.providers_available`).
  The nutrient registry (`key`, `label`, `unit`, `role`) comes in the server's order, then the meal names. It holds no secret, host or
  other person's data. The demo answers it from `js/mock/meta.js` (nothing optional switched on), pinned by `tests/data/meta_vectors.json`
  (`gen_meta_vectors.py`; `node tests/js/run_vectors.mjs`) and compared by `tools/e2e/parity.py` section 10. The screens do not read it yet
  (ROADMAP "Open items"). New tests: `tests/test_openapi_snapshot.py`, `tests/test_meta.py`.
* **A guide to the test vector files** ([design note 14](docs/dev/research/14-reuse-map.md) change 6, the documentation half).
  [`tests/data/README.md`](tests/data/README.md) says, for each `*_vectors.json` file, what it covers, which server code and browser twin
  it ties together, how to regenerate it, its shape, and what a replayer in another language must get right (rounding, tolerances, dates,
  text shown to people). `tests/test_vectors_readme.py` fails when a file has no section or a section lists the wrong keys. The Swift test
  target waits for the iOS design note.
* **The brand strings are in one place** ([design note 14](docs/dev/research/14-reuse-map.md) change 3). `app/brand.py` holds the product's
  names and the strings that identify it: the cookie names, the `X-Requested-With` value, the token prefixes `kha_` and `khd_`, the
  bearer realm, the database file name `kidney.db`, the export `format`, the User-Agent texts, the HKDF labels and the logger root, each
  with a note on whether changing it would break an install in use. The page reads the ones it uses from `KH.brand`
  (`app/static/js/engine/brand.js`). No value changed. `tests/test_brand.py` pins them all, checks that the Python and browser copies agree
  and fails when a main literal shows up again outside those two files and a short, explained allowlist.
* **The kidney and type 1 diabetes rules moved out of `app/nutrients.py` into `app/rules_kidney.py`** (design note 14 §2.2 and §4 change 5;
  no behaviour change, no vector change). The thresholds, `food_warnings`, `kidney_rating`, the per-meal carbohydrate alerts,
  `dosing_weight`, `suggest_targets`, the CKD, dialysis and diabetes choices and the food flags are the same code in a new module. The
  registry, rounding and number formatting both modules need are in `app/nutrient_core.py`, so there is no import cycle.
  `app/nutrients.py` re-exports every moved name, so each `from .nutrients import X` and `nutrients.X` still works.
* **The safety set: `python -m pytest -m safety`** (design note 14 §4 change 7). The tests that enforce the health-data rules of CLAUDE.md
  (no insulin or medicine dosing, a low is never blocked or warned against, handbook text quoted word for word, the AI guard and the
  prefilter, nothing about weights, readings or symptoms sent to an AI) carry a registered `safety` marker, including the AI golden
  `safety-*` and `prefilter-*` cases. `tests/test_safety_set.py` collects the set and fails if it is empty or a listed file loses its last
  safety test; CONTRIBUTING.md "Tests" explains it. No behaviour change.
* **Weight and blood pressure** (note 10). The server: `app/body.py` (routes `/api/body/weights`, `/blood-pressure`, their `/batch` imports
  and `/summary`; pure functions for pounds and kilograms, the weight-gain alarm, the 7-day means against the goal, the six-month change
  and the flags), the `Weight*`, `BloodPressure*` and `Body*` models, `user.units.weight`, `body.weight_alarm` and `body.bp_goal` in the
  settings registry, and `weights` / `blood_pressures` in the export and the import. The browser twin is `js/engine/body.js` and
  `js/mock/body.js` (with sample data in the demo), checked by `tests/data/body_vectors.json` (`tests/data/gen_body_vectors.py`) and
  `tools/e2e/parity.py` section 16. The settings twin gained a float type with null (`engine/settings.js`). The screens:
  `js/engine/body_ui.js` (`KH.bodyUi`, pure), `js/views/body.js`, `js/views/body_trends.js`, `css/body.css` and the body section of
  `js/engine/visitprep.js`. Tests: `tests/test_body_ui.py` and `tests/test_body_ui_numbers.py` (with `tests/js/body_ui_runner.mjs`: what a
  person types is accepted and refused as the server's models and settings do, and the visit prep sums equal `app/body.py`'s), and the
  browser harness `python tools/e2e/body.py`. New handbook sources are `K21BP`, `AHA25BP`, `AHA-CUFFLESS`, `NOTE10` and `NHLBI-BPS`; an
  open clinician question is in `handbook/REVIEW.md`. [docs/body.md](docs/body.md) and ARCHITECTURE.md "Weight and blood pressure"
  describe it.
* **The Health app import sheet** (`js/views/body_import.js`, `KH.bodyImport.open()`, the sheet `#sheet-body-import` in `index.html`; the
  reader `js/engine/apple_health.js` is loaded by the page after `engine/rules.js`, with `sw.js` precaching both): the review, the period,
  the watch readings unticked, batches of 1,000 with `source: "apple_health"` and no source name, a per-day trim against the rows the
  person already has (`trimDays`), and a stop on any refusal that says what was already added. No server change.
  `tests/test_body_import_ui.py` and `tests/js/body_import_page.mjs` test it in Node against a fake backend that keeps the batch rules.
  `tools/e2e/body_import.py` (port 8087, Chromium at 375 px and 1280 px, light and dark, a real server and the demo, about 2 minutes)
  imports a generated `export.xml` and checks the server's rows through the API, a 25-weight day, a refused batch, Cancel and the second
  import that adds 0. The reader's header comment no longer spells out the `<!DOCTYPE` line, which tripped the preview test for a page with
  no doctype once the reader was inlined. The handbook section is in `handbook/docs/app/targets-and-warnings.md`.
* **Reading a `.zip` in the browser: `js/engine/zip.js` (`KH.zip`)**, design note 11
  (`docs/dev/research/11-reading-a-zip-in-the-browser.md`). A plain script (no DOM, no library, no new vendored file, no server code, no
  schema step) over `Blob.slice`, `Blob.stream` and `DecompressionStream('deflate-raw')`: `supported, open, find, list, stream, text,
  ZipError`, the rules `RULES.exportJson`, `healthXml`, `healthCda`, `clinicalRecords`, and the caps `MAX_DIRECTORY_BYTES` (32 MiB) and
  `MAX_ENTRIES` (200,000). It is strict: the end record, zip64 and the directory are checked before anything is believed, an entry's local
  header must agree with the directory, and the bytes are counted and checksummed (CRC-32) **while they are inflated**, so an entry that
  outgrows its declared size is stopped after its first chunk, whatever the archive claims; a cancel reaches the file's own stream. It is
  listed in `index.html` (before the three views) and `sw.js`. The three views take it: `settings.js` (`textFromZip`), `body_import.js`
  (`startScan(file, zipped)`) and `lab_fhir.js` (`readZip`, `readEntry`). Tests: `tests/test_zip_reader.py` with `tests/js/zip_reader.mjs`
  and the archive builder `tests/zip_support.py` (every archive is built at test time: `zipfile`, plus a hand-written byte builder for
  zip64, a fake end record, lying sizes, a flipped CRC, a cut deflate stream, an encrypted entry; the fifteen cases of note 11, a 64 MB
  entry under a memory bound, abort, no `DecompressionStream`). The three page tests run each view on archives made in memory
  (`tests/js/zip_writer.mjs`), and `tools/e2e/import_walk.py` and `tools/e2e/body_import.py` choose the `.zip` itself in Chromium (and
  keep a check that the bare `export.json` and `export.xml` still work). What stays open is a run with a real iPhone `export.zip`
  (`docs/maintainers.md`).
* **`tools/e2e/import_walk.py`: a browser walk of Settings → Account → Your data → Import from a file against a real server** (port 8086,
  Chromium at 375×812 light and 1280×800 dark, about 20 seconds). Person A is filled through the API and exports a zip in the page; a
  fresh person B signs in on the page and imports A's `export.json`. It covers the files a person can pick by mistake (a text file, a JSON
  list, JSON that is not an export, another version), the recent-password sheet (Cancel, a wrong password, the right one, and again at
  Import), the preview, Import without and with "Add to my existing data" (counts, no duplicate, only what is missing is added back) and
  "Also replace my profile, targets and settings", with B's state checked through the API against A's. It is listed in
  `tools/e2e/README.md`, CONTRIBUTING.md and the release checklist (`docs/maintainers.md`), which now leaves only a phone's own file
  picker to a person.
* **PDF lab reports** (design note 13): `js/engine/pdf_pages.js` (`KH.pdfPages`) opens a PDF with the vendored **pdfjs-dist 6.4.299,
  `legacy/build`** (`pdf.min.mjs`, `pdf.worker.min.mjs`, `LICENSE` in `app/static/vendor/pdfjs-dist-6.4.299/`; the choice and its evidence,
  pdf.js's own browser support statement and the calls the default build makes without a polyfill, are in `app/static/vendor/README.md`)
  and draws the pages the person ticked as JPEGs in a module Worker. The module makes that worker under the one Trusted Types policy
  `kh-pdf` (`app/security.py` now says `trusted-types kh-sw kh-xml kh-pdf`; `tests/test_frontend_shell.py` allows exactly three
  policy-creating files and one `Worker` constructor). The options passed to `getDocument` are the audited list in the file's header
  (`data`, `isEvalSupported: false`, `enableXfa: false`, `disableAutoFetch`, `disableStream`, `disableRange`, `stopAtErrors: false`; no
  URL, `cMapUrl`, `standardFontDataUrl`, `iccUrl` or `wasmUrl`). **Against pdf.js 6.4 two names differ from note 13:** `isEvalSupported` no
  longer exists (the library has no eval path left; the option is passed anyway and `tests/test_vendor.py` fails if an update brings it
  back, so the page can be re-audited) and `render()` takes `canvas` instead of the deprecated `canvasContext`. pdf.js makes no worker of
  its own when `GlobalWorkerOptions.workerPort` is set, but a worker that fails to start only fires `error` and the load promise never
  settles, so the module listens for it and also refuses a pdf.js that did not post to our worker. `lab_photo.js` gained the page list,
  page-by-page reading with Cancel, the merged table (`KH.labPhoto.mergePages`) and the messages; `KH.ai.uploadPhoto` takes an optional
  `AbortSignal`.
* **`scripts/vendor_barcode.py` vendors both the barcode decoder and pdf.js** (same name and options; new `--only barcode|pdfjs`, which
  downloads nothing of the other group; the download cap is per package because the pdfjs-dist tarball is 8.5 MB; the tarball address the
  registry names must be the expected one; the weekly `vendor-check.yml` `--check-latest` covers pdf.js through npm's small dist-tags
  answer). `tests/test_vendor.py` runs the fetch against a fake registry. **A comment in `sw.js` that contained `*/` stopped the service
  worker from starting** (found by the browser walk, not by a test): `tests/test_pdf_pages.py` now runs `node --check` on `sw.js`,
  `pdf_pages.js`, `lab_photo.js` and `ai.js`.
* **`tools/e2e/lab_pdf.py`: a browser walk of a PDF lab report** (ports 8089 and 8090, Chromium at 375×812 light and 1280×800 dark with the
  service worker allowed on the second, about a minute). A tiny PDF writer in the harness (no new dependency) makes a two-page report, a
  password-protected one (a security handler whose check never passes, so no cipher is needed), a damaged one, a 51-page one and a 21 MB
  one; a fake local AI answers lab report photos with scripted rows. It checks the page list, the consent sheet's extra line, that each
  page reached the AI as its own drawn JPEG (no EXIF, within 2048 px, dark pixels, the two different) and that no request body starts with
  `%PDF-`, the merged table, the date entry and Save through `POST /api/labs/import`, Cancel, the five refusals (including pdf.js's real
  `PasswordException`), that only the library and its worker were requested from `/vendor/pdfjs-dist-6.4.299/` and one closed Worker was
  made per run, 0 CSP or Trusted Types violations, and the service worker's `/vendor/` cache. It is listed in `tools/e2e/README.md` and
  `tests/test_e2e_tools.py`.
* **Device tokens and `/push/v1`** (design note 12): the `khd_` family lives in `app/auth/api_tokens.py` (family, scope and switch checked
  before any lookup; `/mcp` refuses `khd_` and `/push` refuses `kha_`; `family` on `GET`/`POST /api/me/tokens`, audited), the route and
  "Delete what it sent" in `app/push.py` (outside `/api`, in `security.BEARER_PATHS`), and `context_for`, `is_watch_source` and the
  same-reading check in `app/body.py`. `KH.appleHealth.contextOf` and `isWatchSource` are checked against the server's by new
  `context_cases` and `watch_cases` in `tests/data/body_vectors.json`; the demo's batch routes (`js/mock/body.js`) keep the same-reading
  rule and return `via: null`. The screens: `pushBlock` in `js/views/settings.js` (every word from the server through `textContent`; the
  token is held in one variable until a draw has shown it once), `KH.bodyUi.originText` and the origin span and "From" column in
  `js/views/body.js` and `body_trends.js`, and the demo's token routes in `js/mock/auth.js`. The self-revoke audit row carries `family`, so
  the activity list can name it. One line (a "Phone shortcuts" group for `push.enabled`) was added to `js/views/settings.js` because
  `tests/test_settings_ui.py` requires every server setting to be in a group. New tests: `tests/test_push.py`,
  `tests/test_device_tokens.py`, `tests/test_migration_m019.py`, `tests/test_push_ui.py` (with `tests/js/push_page.mjs`), a device token in
  the two tests that every `/api` route ignores `Authorization`, additions to `tests/test_settings_ui.py` and `tests/test_body_ui.py`
  (whose Apple Health button test expected `KH.bodyImport.open()`; the code calls `open(button)`: the stale expectation is corrected),
  `tools/e2e/push.py` (a real Chromium, the harness posting like a Shortcut) and the token routes in `tools/e2e/parity.py` section 10.
* **`set_food_preference` over MCP** (note 09 §4.8b): `app/mcp/preference_tool.py` (in `server.all_tools()`, not in `tools.TOOLS`, because
  it reuses Ask's checks, which import `tools`; `Tool.needs` says which scope a tool needs), `api_tokens.PREFS`,
  `parse_scopes`/`scopes_for`, `TokenCreate.can_prefs`, `guidance.api.apply_preference` and `drop_preference` (the PUT and DELETE routes
  now call them), and `chat_preference.resolve_food`, `resolve_group`, `held_preference`, `group_state` and the room checks extracted from
  Ask's code with its behaviour unchanged. `PreferenceBody.source`, `PreferenceFood.source` and `ImportFoodPreference.source` allow
  `assistant` (Ask's Undo puts a row back with the source it had; `mock/guidance.js`, `mock/import.js` and
  `tests/data/import_vectors.json` follow). New tests: `tests/test_mcp_prefs.py` (with a `@pytest.mark.safety` test that the Treating a
  low options, card, insights and `safety_check` do not change; the file is in `tests/test_safety_set.py`), `tests/test_assistant_ui.py`
  with `tests/js/assistant_page.mjs`, and a taste section in `tools/e2e/mcp_smoke.py`. The test that pinned "the MCP server cannot list or
  call `set_food_preference`" now pins the new rule.
* **A look at every screen, and checks that keep the fixes.** `tests/test_layout_ui.py` pins each layout fix in the stylesheets and the
  page. `tools/e2e/sandbox.py` gained two probes: the header at 19 widths with the Preview pill, the admin shield, the Ask tab and the
  offline badge on and off (the name whole or hidden, nothing overlapping, no sideways scroll), and the Plan week's badges. The four README
  screenshots were taken again, because they showed the cut name and the spread-out warning lines.
* **A new README.** It is shorter and in plain words, with a link to try the demo in the browser right under the introduction and four
  screenshots from the demo (`docs/screenshots/`). `tools/e2e/readme_shots.py` takes them again after a change to those screens.
  `CLAUDE.md` and `AGENTS.md` gain a "Write for people" rule.
* **`ruff check .` runs in CI.** The `lint` job downloads ruff 0.17.0 (the release binary, with `RUFF_VERSION` and `RUFF_SHA256` beside the
  other tool pins, checked by the job's `fetch` helper) and runs `ruff check --no-cache --output-format=github .`, so findings show up as
  annotations on the pull request. ruff is not in the lock files. ruff 0.17 widened its default rules to about 400 (1,052 findings in the
  tree then), so `pyproject.toml` selects the earlier default explicitly (`[tool.ruff.lint] select = ["E4", "E7", "E9", "F"]`:
  pycodestyle errors and pyflakes), which keeps the tree clean and means a ruff upgrade cannot change what CI checks; `target-version`
  comes from `requires-python` (3.11). CONTRIBUTING.md asks for `ruff check .` before a push. `tests/test_deploy.py` keeps the pin, the
  checked download, the step and the lock files free of ruff.
* **The release run no longer goes red over long release notes.** GitHub refuses release notes over 125,000 characters, and 0.4.0's
  (pasted from the rendered changelog, with its HTML) reached that cap, so the `release notes (image digest)` job's `gh release edit` got
  a 422 after the image had already been built, scanned, signed and tagged. The job now counts the notes with the Image section first and,
  if they would be too long, warns and prints the block to paste by hand. A test in `tests/test_deploy.py` runs the job's script against a
  fake `gh` (short notes, too long, already there), and `docs/maintainers.md` says to paste the section as Markdown.
* The GitHub Actions group was bumped (CodeQL's `init` and `analyze`, 4.38.2 to 4.38.3). pydantic 2.14's behaviour changes were read
  against the app's models: none applies (no enum, `multiple_of`, `NameEmail`, `ByteSize`, `ZoneInfo`, `Decimal` or `Fraction` field, URL
  type, or stdlib dataclass or `TypedDict` schema), and the locked 2.14.0 already passes the suite and the AI schema snapshots.

### Security

No entry in this release fixes a vulnerability that was reported against 0.4.0 or any released version. The security-relevant changes,
collected from the entries above, are these; the model and the checks are in [docs/security.md](docs/security.md).

* **A second kind of token, with its own scope.** Phone-shortcut tokens (`khd_`) are a separate family from assistant tokens (`kha_`). A
  device token holds exactly one scope, `body:write`, which the person does not choose, and only `POST /push/v1/body` accepts it. `/mcp`
  refuses a `khd_` token, `/push` refuses a `kha_` token, and every other route ignores the `Authorization` header (a device token is in
  the tests that walk every `/api` route). It is stored as a SHA-256 hash, shown once, expires (30 days, 90 days or 1 year), and a person
  holds at most 5. Making one needs a recent password and is limited to 20 tokens an hour. A password change or reset, a disabled or
  deleted account, or an admin's **Revoke tokens** ends it at once, and the person can revoke it any time. The route can only add up to 50
  plausible rows a request, 60 requests an hour, and answers with counts alone, so a leaked token reads nothing. The rows it added are
  marked with the token, so the person can see them and delete them all in one step. It refuses a foreign `Origin`, a wrong token counts
  as a failed sign-in for its address, with the switch off every request gets the same `401`, and `khd_` tokens are redacted from logs.
* **The assistant's taste tool sits behind its own permission.** `set_food_preference` needs `assistant:prefs`, a separate tick that is off
  by default; the tick gives no other power, saving food does not give it, and a phone-shortcut token can never hold it. `/mcp` does not
  list the tool for any other token. A change needs a `request_key`, and repeating a key inside 24 hours changes nothing. At most 30
  changes a day per token (counted in memory, so a restart empties it). Every change writes an audit row in the same transaction ("Assistant
  remembered a taste": what it was, what it became, the token's name). The tool refuses Not for me for a food that treats a low and for a
  kind of food that holds one, because that would take it out of the Treating a low options; a test in the safety set pins this. The app
  cannot check that the assistant asked you first (see Known limitations).
* **Reading a PDF adds a library, with its own gate.** pdf.js is vendored, not fetched: Apache-2.0, pinned by SHA-256 and checked weekly by
  `vendor-check.yml`. The Content-Security-Policy gains a third named Trusted Types policy, `kh-pdf`, which starts the one bundled worker
  file and nothing else; there is still no `'unsafe-eval'` and no `blob:`. The options given to pdf.js are an audited list (no URL, no
  font or colour-profile downloads). The PDF stays on the device; only the pages a person ticks, drawn as pictures, go to the local AI,
  under the consent and checks a photo already has. A lab report never reaches a cloud AI.
* **Archives are opened on the device, and strictly.** The `.zip` reader checks the end record, zip64 and the directory before it believes
  anything, requires an entry's local header to agree with the directory, caps the directory (32 MiB, 200,000 entries), refuses an
  encrypted entry, and counts and checksums (CRC-32) the bytes as they are inflated, so an entry that outgrows its declared size is
  stopped. The server receives no archive and gained no route for one.
* **Header changes.** `trusted-types kh-sw kh-xml kh-pdf` (it was `kh-sw kh-xml`). `/push/v1/body` joins `/mcp` as a path that reads a
  bearer token and never the sign-in cookie, and gets the same `Origin` check on every method. Everything else in the headers is unchanged.
* **Health numbers stay on your server, and the shortcut route takes nothing else.** Weights, blood pressure readings and what a shortcut
  sends are never sent to an AI provider or the assistant ([docs/privacy.md](docs/privacy.md)). The shortcut route refuses any field other
  than weights and readings (`glucose`, `insulin`, a medicine) with a `400`, and the Health import reads only weights and blood pressure.
* **The API document and `GET /api/meta` expose no secret.** `GET /api/meta` is for signed-in people only and holds no secret, host or
  other person's data. The checked-in OpenAPI document lists routes and shapes. The live `/openapi.json` and `/docs` stay off unless
  `ENABLE_API_DOCS` is on.

### Known limitations

What is built and tested here but not yet verified outside it. The things marked *owner* need the maintainer's own hardware, keys or
accounts; the list of checks is in [docs/maintainers.md](docs/maintainers.md) and everything deferred is in
[docs/ROADMAP.md](docs/ROADMAP.md).

* **Not yet tried on a real iPhone (*owner*).**
  * **The Shortcut recipe.** The handbook's "From a phone shortcut" is written from Apple's guide. The Shortcuts action names and their
    order, that a personal automation runs without asking, and that the phone reaches the server from where it is used have not been
    checked on a real iPhone. The tests and the browser walk (`tools/e2e/push.py`) post the way a Shortcut would.
  * **A real Health `export.zip`.** The `.zip` reader, the weights and blood pressure import and the lab-record import were written
    against archives and files that the tests build, in the formats Apple documents. What Apple's archiver really writes (its methods,
    zip64, the `__MACOSX` extras) and what a real `export.xml` holds that the reader skips (units, a watch's readings) are not known. The
    reader turns away what it does not understand with a plain reason.
  * **Real files from a patient portal.** The C-CDA importer was written against hand-made samples that follow the published formats.
    Real downloads from MyChart and one more portal have not been tried, so a code, unit or section a real file has may be skipped (the
    headline counts what was skipped).
  * **Real lab PDFs on a local model.** Reading a PDF is tested with generated PDFs and a fake AI. A real report from a portal (Quest,
    Labcorp, a hospital) on a real local vision model, in Safari on an iPhone and in a desktop browser, has not been tried, so which
    units and dates a model misreads is unmeasured. A scan made of JPEG 2000 or JBIG2 pictures can come out blank, and the PDF's own text
    layer is not read.
  * **The device matrix.** Installing, the live camera, the offline outbox, offline edits and a conflict from a second device, the Ask
    microphone, a phone's own file picker for the imports, VoiceOver and TalkBack were checked in Chromium (fake camera and microphone,
    emulated offline), not on an iPhone, an iPad or an Android phone. The Trusted Types policies are exercised only by Chromium here.
* **Screens that are still a little off.** On a phone, **Profile**'s two-box rows (Daily targets, About you) can sit at different heights
  when one label wraps; an attempt to fix it crowded the hints under the boxes, so it was left. For an admin (the shield button next to
  Settings), and in the demo with its Preview pill, the header on a phone has no room for the app's name, so only the logo shows. On Today with an empty log, the
  full stop after "...enter them in Settings" sits a little apart from its link.
* **Left open by the entries above.**
  * A shortcut's reading of 180/120 or higher is flagged, with Get help now, only the next time the app is opened; the app does not watch
    what a shortcut sends.
  * The assistant's taste tool: asking you first is the assistant's job, and the app cannot enforce it (the tool's description and the
    server's instructions tell the model to). A taste set for a *kind* of food has no "from your assistant" mark in the preferences screen
    (only in your activity list). The 30-a-day limit is counted in memory.
  * The screens do not read `GET /api/meta` yet; they keep their own copies of the nutrient lists.
  * Safari before 16.4 cannot open a `.zip` and shows the unzip advice. The Health `export.xml`'s `ClinicalRecord` entries and a "pick a
    folder" chooser are not built.
  * The demo has no server to send a phone shortcut to.
* **Still true from 0.4:**
  * **The handbook is still a draft, and the rules still await review.** Every handbook page shows "Draft: not yet reviewed by a
    clinician" until a named reviewer signs it off (the open questions are in `handbook/REVIEW.md`). The rules marked "Expert opinion"
    in the target suggestions, the meal guidance's per-meal caps and score weights, the potassium-additive rule, the default
    carbohydrate tolerance (10 g) and the 10 % ceiling of the "about" tolerance also wait for a renal dietitian or nephrologist. The
    plausible ranges of weights and blood pressure readings are the project's own choice, not clinical numbers, and the handbook's blood
    pressure lines are as unreviewed as the rest of it. Keep `targets.lab_rules_enabled` off on a public demo server.
  * **No AI model is recommended yet.** Every AI feature was tested against fake providers through the real network code, not against a
    live Ollama, OpenAI, OpenRouter or Hermes Agent. The live evaluations for the current `PROMPT_VERSION` (`2026-10-21.1`),
    `python scripts/ai_eval.py` and `python scripts/ai_eval.py --chat` with the model in use, have not been run (*owner*). Speech to text
    is untested against a real server, and the local whisper overlay ships with a placeholder image digest.
  * **Raspberry Pi speed is estimated, not measured** (*owner*). `scripts/bench_guidance.py` has not been run on a Raspberry Pi 4 or 5.
  * **Python 3.15 is in the image only.** `deploy/Containerfile.debian` (the fallback) and the throw-away handbook build stage stay on
    Python 3.14 until PyYAML publishes a cp315 wheel. The handbook is still built with MkDocs and Material; moving to Zensical waits for
    a Zensical release that passes the CI canary, before Material's security fixes end (November 2026 at the earliest).
  * **Signatures need a public repository.** Release signing, provenance and SBOM attestations, and CodeQL run only while the GitHub
    repository is public; `scripts/verify-image.sh` fails for an image released while it was private.
  * **Offline is for the food log.** New entries, and edits and deletes of entries, work without a connection. Profile and target
    changes (on purpose: a care team's targets must not be overwritten by a stale copy), weights and blood pressure, lab results,
    symptoms, food preferences, settings, barcode lookups, AI and new guidance answers need a connection; the Treating a low card still
    works, and handbook pages work offline only once opened on that device.
  * **The kidney-only profile is partly done.** The app and the AI prompts follow a profile with *Diabetes: None*, but the handbook's
    framing and the app's one-line description in the page metadata and the web app manifest ("for a renal diet with type 1 diabetes")
    are the owner's wording to choose.
  * English only; one SQLite file per server; no reminders or notifications; no OIDC sign-in and no second factor yet
    ([docs/ROADMAP.md](docs/ROADMAP.md) lists what is planned, and the owner's next step, a native iPhone app that syncs Apple Health).

## 0.4.0 — 2026-10-22

Version 0.4 adds an assistant you can talk to (the **Ask** chat inside the app, with your voice if you set up speech to text, and
an MCP server for a chat assistant you already use), health data you can bring in (lab results from a spreadsheet, the iPhone
Health app, a patient-portal file or a photo of a report; your own export into another server), a symptoms log and a one-page
visit prep, edits and deletes that work offline, an AI whose reach you choose per feature (your own network, the cloud, or off), and
meal guidance that learns what you like. It also folds in the follow-ups made after 0.3.0 (Server administration on its own page,
carbohydrate and "about" tolerances, "Not chosen yet" in the profile, the online demo). As in 0.3, everything that sends data off your server is
**off until an admin turns it on**, and each person decides for themselves.

**Before you upgrade, read [Upgrading from 0.3](#upgrading-from-03-read-this-first).** The first start migrates the database
(schema steps 8 to 17); take a backup first.

### Highlights

* **Ask: a chat inside the app, by text or voice** (an admin turns it on). Type "How much potassium do I have left today?" and the
  assistant looks up your own targets and log with the app's read-only tools. A low or an emergency in your message is answered by
  the app's own Treating a low or Get help now card without asking the AI, and every answer is checked in code before you see it
  ([docs/assistant.md](docs/assistant.md#the-ask-screen-the-chat-inside-the-app)). With a speech-to-text server you set up, a
  microphone turns your words into text for you to read and fix; the reply can be read aloud with a voice built into your device.
* **Save from the chat, with a trust setting you control.** By default Ask shows a card and saves only when you press Save. If you
  would rather not confirm every time, an admin can allow "Trust it for this conversation" or "Trust it always"; every save then
  shows Undo, and the app's numbers, the low and emergency rules and the dose checks stay on.
* **An assistant of your own, through MCP** (an admin turns it on). Settings → Assistant access makes personal tokens so a chat assistant you already use
  (Open WebUI, a Hermes Agent profile) can ask the app for your numbers instead of guessing them: today's figures, a food search,
  "check this meal", and a safety check. It reads only, unless you tick "Can also save food and recipes" for that token.
* **Symptoms log and visit prep.** Write down a symptom with a severity; the app records and shows it and never says what it
  means (the two handbook warning signs show the handbook's own words). **Trends → Get ready for a visit** makes one page to print or
  save as a PDF: averages against your targets, your latest lab results, your symptoms, your own questions and the handbook's
  checklist. Nothing is sent anywhere.
* **Bring your results in.** Lab results from a spreadsheet (CSV), from the iPhone Health app's clinical records, from a
  patient-portal C-CDA file (all read on your device; nothing is uploaded) and from a photo of a report (only on an AI on your own
  network); you tick what to keep. **Import from a file** also takes the `export.json` of your own export into another server.
* **Edit and delete without a connection.** Changing or deleting an entry that is already on your server now waits on the device
  and is sent in order; if it was changed on another device meanwhile, nothing is overwritten and you choose.
* **Privacy tiers for the optional AI.** An admin can keep two AIs, one on your own network and one in the cloud, and pin each
  feature (photos, meal ideas, describe a meal, Ask) to local, cloud or off; the default is the least trusting one (local). Photos,
  meal ideas and describe a meal can also try the local AI first and go to the cloud only when the local answer fails the app's
  checks. Reading a lab report photo never goes to a cloud AI.
* **Meal guidance learns what you like.** *More like this*, *Less often* and *Not for me* on any suggestion, likes and dislikes by
  kind of food, and what the app notices in your log ("Eaten on 6 of the last 14 days"), each with its reason and each removable.
  Tastes only reorder what already fits your limits; they never relax a limit, hide a warning or touch the Treating a low card. Ask
  can offer to remember a taste you mention (always as a card), and the optional AI is told, by name, what you marked.
* **No diabetes, no carbohydrate goals.** A profile with *Diabetes: None* shows no per-meal carbohydrate goal or alert, and the AI
  instructions follow your profile instead of assuming type 1 diabetes. A new account's kidney stage and diabetes type read "Not
  chosen yet" until you choose.
* **Everyday improvements.** Carbohydrate and "about" tolerances; warnings when potassium, sodium or fluid run high over several
  days; Server administration on its own page; "Add this day to my plan" on the handbook's sample menus; handbook pages you have
  opened work offline; an online demo beside the handbook that can keep your data in your browser if you choose.
* **For people who run a server.** The image now runs Python 3.15 (and is about 1 MB smaller); the Kubernetes base is
  cluster-neutral with an example overlay; `app.admin backup --dir --keep` for backup tools; each release's notes carry the image
  digest; an optional local speech-to-text overlay with no route to the internet.

### Upgrading from 0.3 (read this first)

1. **Back up `kidney.db` first.** The first start migrates the database in place (schema 7 → 17: steps 8 to 17), each step in its
   own transaction. Unlike the 0.2 → 0.3 step, none of them makes an automatic copy. For example, with the running container:
   `podman exec kidney-health python -m app.admin backup /data/before-0.4.0.db` (or `backup --dir DIR --keep N` for a backup tool).
   What the steps add, nothing removed: 8 "Not chosen yet" in the profile (existing profiles count as chosen), 9 the tolerance for
   "about" targets, 10 assistant tokens, 11 and 13 the duplicate guards of the assistant's and Ask's saves (hashes only), 12, 14 and 16
   rebuild `ai_consents` so the consent purposes `chat`, `voice` and `labs` can be stored (every consent is kept), 15 symptoms, 17 the
   source and update time of food preferences. To go back to 0.3, restore the backup you took; 0.3 is not tested on a database that
   0.4 has migrated, and anything entered after the upgrade is lost.
2. **Change the image tag from `:0.3` to `:0.4`.** The minor tag does not move to the next minor on its own, so a host that tracks
   `:0.3` stays on 0.3.x until you change it. The shipped Quadlet unit, compose file and Kubernetes base already say `:0.4`; or pin
   the digest in the release notes after `scripts/verify-image.sh 0.4.0`. `:latest` follows releases, so a host that auto-updates
   `:latest` upgrades itself at its next pull ([docs/deployment.md, "From v0.3 to v0.4"](docs/deployment.md#from-v03-to-v04)).
3. **The image base moved to Python 3.15** (Chainguard's free `python:latest` moved up from 3.14, and the old 3.14 digests no longer
   get security updates). Nothing to do when you pull. If you build the image yourself, `deploy/Containerfile` has the new digests;
   `deploy/Containerfile.debian` (the fallback) and the throw-away handbook build stage stay on Python 3.14 for now.
4. **Kubernetes:** the base in `deploy/k8s` is cluster-neutral now. If you applied it directly after editing it, copy
   `deploy/k8s-overlays/example/`, move your values (`PUBLIC_URL`, `TRUSTED_PROXIES`, the ingress namespace, the route) into it
   and apply the overlay: the base alone now lets no traffic in and trusts only loopback.
5. **Headers.** The app's Content-Security-Policy now ends `trusted-types kh-sw kh-xml` (it was `kh-sw`), and `Permissions-Policy`
   allows the microphone for the app's own origin (`microphone=(self)`, it was `microphone=()`). If a reverse proxy sets your CSP
   instead of the app, add `kh-xml` there, or the patient-portal lab import cannot read any file; if it sets your
   `Permissions-Policy`, allow `microphone=(self)` there for voice input.
6. **Nothing new is switched on.** Assistant access, Ask, voice input, trusted saves and local-then-cloud routing are all off until
   an admin turns them on. On a server that already had a shared AI provider, every AI feature keeps the old rule (`any`: the
   provider each person chose) until an admin picks a route, and the admin table says "Routing is not set up yet"; a new server
   starts every feature on `local`, which is off until a local AI exists. Reading a lab report photo starts on `local` everywhere,
   which is off while no local AI exists.
7. **Things that behave differently without you changing anything:**
   * Meal guidance learns from the log: **Settings → Meal guidance → Learn from my log** is on by default, so suggestions can be
     reordered a little by foods eaten often or planned and passed over, and by anything a person marks *More like this*, *Less
     often* or *Not for me*. A person switches it off there; it never changes a limit or the Treating a low card.
   * Today: a meal's carbohydrate is "over" only more than the carbohydrate tolerance (10 g by default) above the meal's goal, and
     carbohydrate eaten to treat a low is left out of the meal's goal. New warnings appear when planned food runs potassium,
     sodium or fluid over your limit again after 2 of the 3 days before, or phosphorus or protein above the target over a week.
   * A new account's Profile shows "Not chosen yet" for the kidney stage and diabetes type (the app keeps using stage 3b and type 1
     for targets until then); existing profiles count as chosen.
   * Server administration is its own page (the shield button next to Settings), Settings holds personal settings only, and the
     text for AI ideas moved from Settings → AI ideas to Settings → Meal guidance → Your food preferences.
   * The AI instructions changed (`PROMPT_VERSION` is `2026-10-21.1`): they follow the profile, a taste list is added for meal ideas
     and Ask, and a stage or diabetes type not chosen yet is sent as "not chosen yet". Nothing about lows or doses changed.
   * The data export gains `builtin_foods`, `symptoms` (and `symptoms.csv`) and all four food-preference values; the export version
     stays 1 and older files still import. Every log entry in an API answer carries a `version`; `PUT` and `DELETE /api/log/{id}`
     take an optional `If-Match`, and without it behave as before.
   * `requirements.txt` and `requirements-dev.txt` are gone; install from the hash-locked files
     (`pip install --require-hashes --no-deps -r requirements-dev.lock`).

**New optional settings** (all off or at a safe default; the full list is in
[docs/deployment.md](docs/deployment.md#configuration) and `app/config.py`; settings not set in the environment can be changed in
Server administration → Server settings):

| Area | Settings |
|---|---|
| Assistant access | `ASSISTANT_ENABLED` (off): personal tokens and `POST /mcp` |
| Ask | `AI_CHAT_ENABLED` (off), `AI_ALLOW_TRUSTED_SAVES` (off) |
| Voice for Ask | `AI_VOICE_ENABLED` (off), `STT_BASE_URL`, `STT_MODEL`, `STT_API_KEY_FILE` (write-only), `STT_TIMEOUT_S` (60), `STT_DAILY_LIMIT` (100 recordings per person per day), `STT_MAX_AUDIO_BYTES` (1.5 MiB); all `STT_*` values are environment-only |
| Which AI each feature uses | `AI_PROVIDER_ROLE` (`local` or `cloud`, environment only), `AI_ROUTE_PHOTOS`, `AI_ROUTE_MEAL_IDEAS`, `AI_ROUTE_DESCRIBE` (`local`, `cloud`, `off`, `any` or `local_then_cloud`), `AI_ROUTE_CHAT` (no `local_then_cloud`), `AI_ROUTE_LABS` (`local` or `off` only); defaults `local` |
| Limits | `MAX_IMPORT_BYTES` (16 MiB, only for `POST /api/me/import`) |
| Tools | `python -m app.admin backup --dir DIR --keep N`; `deploy/compose.stt-whisper.yaml` (optional local speech to text) |

`deploy/compose.yaml` passes `ASSISTANT_ENABLED`, `AI_PROVIDER_ROLE` and the `AI_ROUTE_*` settings through; the other switches are
changed in Server administration, and the `STT_*` values go in your own environment (or come from the whisper overlay).

### For people using the app

* **Ask can remember what you tell it you like, and the optional AI knows your tastes.** Tell Ask "I don't really like
  salmon" (or "I like lentils", "fewer sweets") and it may offer to remember it for your meal suggestions. This is **always
  a card, even if you chose to trust Ask**: "Remember this for your suggestions? Salmon: less often." with **Remember** and
  **Cancel**. Nothing changes until you press **Remember**; **Undo** puts back exactly what was there. It works for one
  food or a whole food group, and Ask only offers it when you say a taste, never from what you log or ask about. A taste
  only changes the order of suggestions, never a limit, a warning or the Treating a low card, and it is not an allergy
  filter. Meal ideas and Ask are now told, by name, the foods and food groups **you** marked *More like this*, *Less
  often* or *Not for me* (at most 10 of each), only with the consent you already gave for them and shown in "What will be
  sent?"; what the app learned from your log is never sent, and describe a meal, photos and lab report photos get none of it.
  An AI idea may say "uses a food you said you like" only for a food you marked, and an idea that uses a food you said *Not
  for me* is dropped. A chat assistant connected with a token cannot do any of this. Fixed on the way: an AI idea's "uses
  foods you often have" was removed when the food's suggestion card already showed two other reasons (a card shows at most
  two); it now holds for every food you had on at least 2 of the last 14 days, as the card's own rule says.
* **Food preferences and what the app learns from your log.** Meal guidance can now take your
  taste into account. For each food you can say *More like this*, *Less often*, *Not for me* or *Stop using what you
  learned about this food*; for each kind of food (fruits, grains, …) *Like* or *Less often* next to the existing *Never
  suggest*. A like lifts a food a little in the suggestions and a "less often" lowers it; neither can make a food fit
  that does not fit your limits, and neither hides anything (only *Not for me* and *Never suggest* do). A liked food shows
  "You said you like this." It is not an allergy filter: the app cannot tell whether a food contains an allergen, so check
  labels. The app also reads your log and can tell you what it saw ("Eaten on 6 of the last 14 days", "Usually at
  breakfast", "Eaten together at lunch on 3 days", and one new one: "Planned 4 times in 30 days, eaten once" for a food you plan
  again and again but pass over, which lowers it slightly); each can be stopped, and a switch, *Learn from my log*, turns
  every learned signal off. Nothing learned is stored; it is worked out each time from your log. It works in the app and in
  the online demo, and your choices are part of your export and import.
* **Tell the app what you like, and see what it learned.** The **⋯** next to a suggestion, a swap idea or a food in a plan now
  has **More like this**, **Less often** and **Not for me**; the one you chose shows a check mark, choosing it again takes it
  back, and a message confirms each change. **Settings → Meal guidance → Your food preferences** lists your choices (change or
  remove each), lets you set every kind of food to **None**, **Like**, **Less often** or **Never suggest**, and shows what the
  app learned from your log with the reason: **Keep** or **Stop using this** for a food, **Save as a meal** or **Not this meal**
  for a meal you often have, and the **Learn from my log** switch. The text for AI ideas ("Food preferences for AI ideas") moved
  there from **Settings → AI ideas**. Less often and Not for me are about taste, not an allergy filter: the app cannot tell
  whether a food contains an allergen, so check labels. Changing a choice needs a connection to your server (nothing is queued).
  Treating a low never shows these buttons.
* **Meals you usually have, or the starter meals, no longer come up when they hold a food you marked *Not for me* or a kind
  of food you never want.** Before, only single foods were left out. A meal you saved yourself is still offered (you built
  it; edit it to change it).
* **The *Treating a low* options are never empty.** If you had marked every low-treatment food *Not for me* (or their food
  groups *Never suggest*), the options list came up empty. Now the whole list is shown with one line, "Shown although you
  marked them Not for me.", because you must always have something to take. Taste (likes, "less often", what the app
  learned) never changes the low-treatment options, the card or its swaps. Nothing delays or blocks treating a low.
* **A message at the bottom of the screen no longer blocks a tap.** The short message that appears for a few seconds
  (for example "2 entries were changed on another device" after you come back online) could cover the conflict
  card's buttons on a phone and swallow the tap; taps now go through to what is under it.
* **The online demo can keep your data in your browser (you choose).** The demo's banner has a new button, **Keep my data in
  this browser**. It opens a sheet that says plainly that your data stays only in this browser on this device and nothing is
  sent anywhere; that clearing site data, private browsing, or the browser deciding to free up space can delete it; that you
  should export regularly; that on a shared device others can see it; and that for real use you should run your own server.
  Nothing is stored until you tick **I understand** and press the button; you start from an empty log of your own or from the
  sample data, and the page asks the browser to keep the data and tells you whether it agreed. After that the demo works like
  a small log with no server: each change is saved in the browser a moment later and is there the next time you open the demo.
  **Settings → Your data** then downloads `export.json` (the same file a server's export holds, so you can import it into a
  real server later) and **Import from a file** takes an `export.json` from this demo or from a server, with the same checks
  and refusals as a server's import. **Stop keeping data here** deletes the stored copy after asking. In a private window, or
  where the browser blocks storage, the sheet says so and the demo stays in memory; a copy saved by a newer version of the
  demo is never loaded or overwritten; a second tab that finds the stored copy changed stops saving and says so. The mode
  exists only in the online demo; the installed app never uses it. See [docs/demo.md](docs/demo.md).
* **Import lab results from a patient-portal file (C-CDA .xml).** Many patient portals (MyChart and others) can download a
  "health summary" or "visit summary" as a C-CDA XML file. **Lab results → Import from a patient portal file (C-CDA .xml)** reads the
  lab results in it: download the file in the portal (choose the XML or C-CDA format, not the PDF) and choose it in the app. **The file
  is read on your device and nothing is uploaded**; your server never sees the XML. The app shows a line such as "12 results found in
  2 files; 3 results of tests the app does not track; 1 not completed", then the same review table as the other imports: the new
  results start ticked (they come from your health system, not from an AI), ones you already have do not, and only the ticked rows are
  saved, through the same save as a spreadsheet (so the potassium warning works the same). It reads the Results section only, completed
  results of the nine tests the app keeps (matched by LOINC code, the same table as the Apple Health import), converts units only with
  the app's own table, and lists what it cannot read (a result like "<0.5", an unknown unit, no usable date) with the reason. Your
  name, address, record numbers, doctors and notes in the file are never read. A file that contains a DOCTYPE or ENTITY declaration
  (a real health summary has none) is refused, up to 20 files of 5 MB each. See
  [the handbook](handbook/docs/app/targets-and-warnings.md#import-lab-results-from-a-patient-portal-file).
* **Edit and delete an entry without a connection.** Changing an entry that is already on your server (its amount, meal,
  day, **eaten** or **planned**, or note, and the **Eaten** button) or deleting it now works offline, like adding food does:
  Today shows the change at once, marked **waiting to sync**, and it is sent, in order, when your server can be reached.
  **Nothing is overwritten silently.** If the same entry was changed on another device while yours was offline, your change
  is **not** sent: **Settings → This device** shows a card, "This entry was changed on another device while you were
  offline", with what your server has and your change side by side, and two buttons: **Keep the saved one** (your change
  is dropped) or **Use mine** (it is sent on top of what is there now). If the entry was deleted elsewhere, the app says "This
  entry no longer exists" and drops your change. An entry you added offline and that has not been sent yet is edited or
  deleted right on the phone. Treating a low is edited and deleted like any other entry. **Your profile and targets still
  need a connection** (a care team's targets must never be overwritten by a copy that waited on a phone). See
  [Install on your phone](docs/install-on-your-phone.md#offline) and [Logging food](handbook/docs/app/logging.md#offline).
* **Import lab results from the iPhone Health app (clinical records).** If you linked your health system in the Health app,
  **Lab results → Import from Apple Health (clinical records)** reads those results from the Health export: you unzip the
  export in Files, open `apple_health_export/clinical-records`, and choose all the files there. **The files are read on your
  phone and nothing is uploaded**: the app shows a line such as "41 results found in 380 files; 12 results of tests the app
  does not track; 3 results in a unit the app cannot convert", then the same review table as a spreadsheet import. The new
  results start ticked (they come from your health system, not from an AI), ones you already have do not, and only the ticked
  rows are saved, through the same save as a spreadsheet (so the potassium warning works the same). It reads final, amended or
  corrected lab results of the nine tests the app keeps (matched by LOINC code, listed with their loinc.org links in
  [docs/targets-and-labs.md](docs/targets-and-labs.md)), converts units only with the app's own
  table, and lists what it cannot read (a result like "<0.5", an unknown unit, no usable date) with the reason. Names, record
  numbers, doctors and notes in the files are never read; it reads up to 2,000 files of 1 MB each. See
  [the handbook](handbook/docs/app/targets-and-warnings.md#import-lab-results-from-the-iphone-health-app).
* **Local first, cloud only when the local answer fails (if your admin chooses it).** For photos, meal ideas and describing a
  meal, an admin can set the route to **Local, then cloud**. Your request goes to the AI on your own network first; a
  cloud company sees it **only if** that answer failed the app's checks (it was not usable, or the app's rules threw all of it
  out) **and** you agreed to send that kind of data to that company. If the local AI is switched off, slow, over its limit or
  declines the question, the cloud is not asked. The consent sheet names both hosts, says when the cloud one is used and has its
  own tick box (**Also allow the cloud AI (host) as the fallback**; leave it off and the cloud is never asked, and agree later
  from Settings → AI ideas or from the answer that says it was not asked); "What will be sent?"
  shows both requests and says the second goes only if the first fails the checks; and an answer that came from the cloud says so:
  *The local AI's answer did not pass the app's checks, so the cloud AI (host) answered.* AI activity lists both calls, and each
  counts in your daily limit. Settings → AI ideas reads *Runs on your local AI (host); if its answer fails the app's checks, on
  the cloud AI (host).* Ask and lab report photos never work this way. See
  [docs/ai.md](docs/ai.md#local-first-cloud-only-when-the-local-answer-fails).
* **Read lab results from a photo of a report (only with an AI on your own network).** On **Lab results**, below "Import
  from a spreadsheet", **Read a lab report photo** takes a photo or screenshot of a lab report (a PDF can be screenshotted)
  and copies the printed results of the tests the app keeps (potassium, phosphate, albumin, bicarbonate, urine
  albumin-to-creatinine ratio, creatinine, cystatin C, eGFR, HbA1c). **Every row starts unticked** under "Read by AI from
  your photo. Check each value against the report before you tick it."; you enter any date it could not read, tick what
  matches, and only the ticked rows are saved (through the same save as a spreadsheet import, so the potassium warning
  works the same). The AI only copies: it never says whether a result is normal, high or low. A report can show your name,
  date of birth and record numbers, which cannot be removed from a photo, so this runs **only on the local AI**: never on
  a cloud AI and never on a key of your own, and it is **off** (with the reason on the card) when your admin has no local
  AI. It has its own consent ("Lab report photos"), the photo is not kept (the AI activity list holds its fingerprint
  only), and it needs no network from your browser. See [docs/ai.md](docs/ai.md#lab-report-photos).
* **Settings → AI ideas says where each AI feature runs.** When your admin keeps an AI at home as well as one in the
  cloud, one line per feature (photos, meal ideas, describing a meal, Ask) says "Runs on your local AI (host)", "Runs on
  a cloud AI outside your network", or that your admin switched it off (off is off for everyone). A feature that moves
  to another AI asks for your consent again for that AI. Your own key stays your own choice. See
  [docs/ai.md](docs/ai.md#which-ai-does-each-feature-use).
* **Visit prep: one page for an appointment.** **Trends → Get ready for a visit** opens a page you can **print or save as a
  PDF** (your browser's own print): choose the last 2 weeks, 4 weeks or 3 months and it shows your **average sodium,
  potassium, phosphorus and protein** (and fluid, if you have a target) per day against your targets, the same numbers as the
  period summary, with how many days had entries (a value some foods do not list reads "at least" or "Not listed", never 0);
  the **latest result of each lab test** with its date, the one before it and an arrow (↑ ↓ →) that only compares the two
  numbers; the **symptoms** you recorded, with the handbook's own words for the warning signs; **your own questions**; and the
  handbook's checklist for visits to tick. Printed, it is black on white without the menus and fits one sheet of A4 or Letter
  for a typical month. **Nothing is sent anywhere, and your questions are not saved at all**: they stay in the open page and are
  gone when you leave or reload it, so print or save the PDF first. Your name is printed only if you gave the app a display
  name. The page says what you recorded and never what it means. See
  [Reports for your care team](handbook/docs/app/reports-for-your-team.md#visit-prep-one-page-for-an-appointment).
* **Write down a symptom.** **Today → Symptoms → Add** records a symptom for a day: pick it (swelling, itching, tiredness,
  cramps, nausea, breathlessness, poor appetite, or **Other** with a name of your own), choose **Mild**, **Moderate** or
  **Severe** and add a note if you like. **Edit** and **Delete** are on each entry; **Trends → Symptoms** lists what you
  recorded in the days on screen (how many days, the worst severity, the dates), and your export holds them
  (`symptoms.csv` and `export.json`; **Import from a file** brings them back). **The app only records and shows them: it
  never says what a symptom means, what causes it or what to do about it.** The two symptoms that the handbook's
  [Get help now](handbook/docs/get-help-now.md) page lists as warning signs, breathlessness ("Call 911 now") and new
  swelling ("Call your care team today"), show the handbook's own words and a link to that page, and a severe one stands
  out and comes first. Symptoms are never sent to an AI provider or an assistant. They need your server (they are not
  saved while you are offline). See [Reports for your care team](handbook/docs/app/reports-for-your-team.md) and
  [docs/privacy.md](docs/privacy.md).
* **Talk to Ask (when the admin sets up speech to text).** A **microphone** button next to Send: tap, speak, tap again
  (a minute at most). The first time, a sheet says where your recording goes ("Your recording is sent to <host> to turn it
  into text, then deleted. Nothing is kept.") and nothing is recorded before you agree. **The words appear in the question
  box for you to read and fix; nothing goes to the AI until you press Send.** **Read answers aloud** (a switch, off by
  default, remembered on this device) speaks the answer with a voice built into your device, never an online voice. The
  browser's own speech recognition is not used. See [docs/assistant.md](docs/assistant.md#talking-to-ask-voice).
* **Ask: a chat inside the app (when the admin turns it on).** A new **Ask** tab, for people who use AI ideas: type
  a question ("How much potassium do I have left today?", "Can I have a banana as a snack?") and press Enter. The
  assistant looks up your own targets and food log with the app's read-only tools and answers in a few plain
  sentences, with **From the app** under the answer showing the figures the app itself worked out. **A low or an
  emergency in your message is answered by the app's own Treating a low or Get help now card at once, without asking
  the AI**, and nothing in Ask ever tells you to wait or skip a low treatment. The app checks every answer before you
  see it: one that touches on insulin or medicine doses, or has a number the app did not work out, is replaced by a
  notice and the app's own numbers; links are removed; lab words add "Lab results are for your care team to
  interpret." The conversation stays in the page (**New conversation**, reloading or signing out clears it; the server
  keeps no transcript). Ask has its own consent ("What will be sent?" shows the exact request) and one question can
  use up to 7 AI calls, each counted in the daily limit. Speaking a question is the "Talk to Ask" item above. The demo shows the tab with a note and
  no input. See [docs/assistant.md](docs/assistant.md#the-ask-screen-the-chat-inside-the-app).
* **Ask can save food and recipes, with a trust setting you control.** Ask the assistant to "log a banana for
  breakfast" or to save a recipe. By default (**Settings → AI ideas → How much do you trust the assistant? → Ask me
  before every save**) it shows a **card**: the foods the app found, the amounts, the app's totals and "Nothing has been
  saved yet", with **Save as eaten**, **Save as planned** and **Cancel**. Only your press saves, through the same route
  as any other save. If you would rather not confirm every time, you can choose **Trust it for this conversation** (you
  switch it on in Ask; it ends with **New conversation**, a reload or after 12 hours) or **Trust it always**, after a
  warning: the assistant can pick the wrong food or the wrong amount. Then it saves at once, all or nothing, and every
  save shows what was saved with **Undo**. Both options need your admin to allow them; with that off, Ask always asks
  first. The app's numbers, the low and emergency rules and the dose checks stay on in every mode; a message about a low
  never saves; a food eaten to treat a low is saved and never warned about; photo and label readings are always shown to
  you to check. Every change of your choice, and every save by Ask, is in your activity list (saves read "with Ask").
* **Assistant access tokens** (when the admin turns assistant access on). **Settings → Assistant access** makes
  personal tokens for a chat assistant you connect: it may read your own food log and targets and cannot change
  anything unless you tick **Can also save food and recipes** (off by default; see the next entry). Give a token a name
  and an expiry (30 days, 90 days or 1 year); it is shown once, with **Copy token**, and never again. The list shows when each token was made, last used and expires; **Revoke** ends one
  at once, and you can have 5 at a time. Changing your password, a password reset, or your account being
  disabled or deleted revokes all of them; your activity list shows when tokens were made and revoked; see
  [docs/assistant.md](docs/assistant.md).
* **Talk to an assistant (optional).** With a token, a chat assistant you already use (Open WebUI, with voice if
  you like, or a Hermes Agent profile with tools) can ask the app for your numbers instead of guessing them: your
  targets and what is left of today, a food search, "check this meal" (each food found in the app, scaled to the
  amount, its warnings, the totals and your day as if you had planned it; nothing is saved), and a safety check
  of every message that shows the app's **Treating a low** card (with your own grams) or **Get help now** first.
  Unknown values stay unknown, and the assistant gets no doses or medicine advice from the app. A token reads
  only, unless you tick **Can also save food and recipes** when you make it (the list then says "Read and save"
  instead of "Read only"; a token cannot be changed later): the assistant can then add food to your log, eaten or
  planned, for a meal and day, and save a recipe as a saved meal (the ingredients for the whole recipe; its note says
  how many servings it makes and keeps the source link as text, which the app never opens). It is told to read the
  items back and wait for your yes, and to say what it saved. If any food is unclear nothing at all is saved and it
  asks you. Food you say you ate to treat a low is saved like any other entry and never delayed or warned about. A USDA
  food it finds is added to your food list first, as the Food screen's import would. Everything it saves is an ordinary
  entry or saved meal you can edit or delete, and your activity list shows each save with the token's name. It cannot
  edit or delete anything. [docs/assistant.md](docs/assistant.md) explains how to connect it, the system prompt to give
  it, and its honest limits: the app cannot check what the chat model finally says, and a cloud model sees what you type
  and what the app answers.
* Opening a sheet (Quick add, an entry, the scanner) no longer pulls the cursor out of a field you have
  already started typing in: the first field gets the focus a moment after the sheet opens only if you
  have not moved to another one.
* **Import your data into another server.** **Settings → Account → Your data → Import from a file**: choose the
  `export.json` from an export of yours (open the `.zip` first) and the app reads it in your browser and asks the
  server to check it. You see what would be added (log entries, your own foods, saved meals, lab results,
  "Not for me" foods), what is left out and why (a food that is not in the file and not built in is listed, never
  guessed; a saved meal that loses a food says so in its note), and what is never imported, before anything
  changes; **Import** then adds it all or nothing. It needs your password again. Passwords, sign-in sessions,
  assistant tokens, keys, AI activity and your Open Food Facts and AI choices are never imported, even if a
  file has them. An account that already has entries, foods,
  saved meals or lab results is refused unless you tick **Add to my existing data**; then whatever is already
  there is left out, so importing the same file twice adds nothing. Your profile, targets and meal-guidance
  settings are replaced only if you also tick **Also replace my profile, targets and settings** (off by
  default: you may have agreed them with your care team on this server). The numbers of an imported entry are
  recalculated from its food and servings, as for any entry. The demo explains this and, with **Keep my data in this browser** on, imports like a server
  ([docs/privacy.md](docs/privacy.md), handbook *Your data*).
* **Handbook pages work offline once opened.** The app keeps a copy of each handbook page you open (and
  what it needs to show), so **Learn** pages you have read before open without a connection, for example
  on a flight or when the home server is down. A page you have not opened on this device says so instead
  of showing the browser's error page. Nothing personal is kept: the handbook is the same for everyone.
  **Settings → This device → Clear offline data on this device** removes the copy.
* **"Not chosen yet" for the kidney stage and the diabetes type.** A new account's Profile no longer
  shows stage 3b and type 1 diabetes as if the person had picked them: both read "Not chosen yet" until
  they choose, and Today shows a one-line prompt meanwhile. The app keeps using stage 3b and type 1
  diabetes for its targets and guidance until then, so the Treating a low card stays available. Target
  suggestions wait until both are chosen. Existing profiles count as chosen (schema step 8).
* **Carbohydrate tolerance on Today.** A meal's carbohydrate shows as over only when it is more than your
  carbohydrate tolerance above the meal's goal: 10 g unless you change it in Settings → Meal guidance
  (5–20 g), the number the meal suggestions already used. A 60.6 g dinner planned as "close to your goal"
  for a 60 g goal no longer shows "Projected over". Carbohydrate you ate to treat a low is left out of the
  meal's goal, so treating a low never makes a meal over; it still counts in the day's totals.
* **A tolerance for "about" targets.** Profile → *"About" targets: on target up to (% above)*, 0–10 %, sets
  how far above a one-number target, such as protein "about 56 g", still counts as on target (Today, the
  plan, the period summary). It starts at 0, the earlier behaviour: no guideline gives a number, so it is
  yours to set with your dietitian. Alerts now call such a number "today's target" instead of "today's
  maximum" (schema step 9).
* **Running high over several days.** When you plan food, Today warns if potassium, sodium or fluid goes over
  your limit again after being over on 2 of the 3 days before (on hemodialysis with dialysis days set: the
  total since your last dialysis day), and if phosphorus or protein would average above your target over the
  past week. It names the planned foods that add the most, and the Plan week marks the day. It uses your own
  targets, only looks at planned food, and never blocks anything.
* **Server administration has its own page.** Admins open it with the new shield button next to the
  Settings gear (or Settings → Admin): People, Server settings, Shared keys, Usage, the Activity log,
  About this server and AI providers, with chips to jump between them. Settings now holds only personal
  settings. Members never see the button or the page, and the server still refuses every admin request
  from a member.
* **Settings → AI ideas explains the setup first.** When AI is on, the page opens with *How AI help is set up:
  three questions*: which model answers, what it may do, and whose key pays and who can read the request,
  with a link to the handbook's *Optional AI* page.
* **No diabetes, no meal carbohydrate goals.** If your profile says *Diabetes: None*, meals have no
  carbohydrate goal: Today no longer shows a carbohydrate line in each meal or warns that a meal is over its
  carbohydrate goal, Settings → Meal guidance explains instead of showing the carbohydrate tolerance and
  the carbs taken for a low, and Profile hides the per-meal and per-snack carbohydrate targets (their values
  are kept). The day's carbohydrate still counts like any nutrient. The "Not medical advice" note below
  Profile and in Settings → About no longer mentions insulin decisions. Until you choose a
  diabetes type the app keeps using type 1, as before.
* **The AI no longer assumes you have type 1 diabetes.** The instructions meal ideas and Ask start with used to say
  "chronic kidney disease and type 1 diabetes" for everyone. They now describe you from your profile: your kidney stage
  (or "not chosen yet"), dialysis if you have it, and a diabetes type only if your profile has one. With *Diabetes:
  None* they say kidney disease only; until you choose, they say not to assume either way. **Nothing else changes: the
  rules about lows, doses and medicines are the same text for everyone** (a profile with "None" can still have a low), and
  a message about a low still gets the app's Treating a low card without an AI call. The data changes a little: a stage or
  type you have not chosen yet is sent as "not chosen yet" instead of the stored default, and with *Diabetes: None* the
  per-meal and per-snack carbohydrate goals are not sent. Describe a meal and the photo features still send no profile data.
  See [docs/ai.md](docs/ai.md#the-instructions-follow-your-profile).
* **Lab results from a spreadsheet.** Lab results → *Import from a spreadsheet* reads a CSV file with a date
  column and one column per test ("Date, Potassium (mmol/L), Creatinine (umol/L)", with other names such as K,
  CO2 or HbA1c understood). The file is read on your device: every result is shown converted before
  anything is saved, you tick the ones to keep, and only those are sent, never the file or its other
  columns. Values that are not one number ("<0.5", ">90"), dates in the future, results outside the
  plausible range and results already saved are listed and left out. New route: `POST /api/labs/import`.
* **"Add this day to my plan" on the handbook's sample menus.** Under each day of the seven-day menus is a link
  that opens the app at a sheet for that day: the day's foods, each with the app's own name and numbers, grouped by
  meal with a tick box, a date (tomorrow, or the next day with nothing logged or planned) and what the day adds up
  to together with what you have already planned. Untick what you do not want and press **Add to plan**; the foods
  are added as **planned**. **Nothing is saved until you press Add to plan**, and pressing it twice adds nothing
  twice. The link only names foods from the app's own list and how many servings; a food that is not in that list,
  an amount that makes no sense or a link that was changed is listed under **Not added** with the reason, or the
  whole link is refused. If you are signed out, the app keeps the link in memory while you sign in and then shows the
  sheet (a page reload or an outside sign-in page forgets it: open the link again). A food that treats a low is
  planned like any other food and gets no warning of its own. On the GitHub Pages copy of the handbook the link opens
  the app's demo. See [Planning meals and using the menus](handbook/docs/app/planning-and-menus.md#using-the-handbooks-sample-menus).
* **Try the app without installing it.** When the handbook is published on GitHub Pages, the app's demo is
  published beside it, at `demo/`, and every handbook page links to it ("Try the app (demo)"). It is the real
  app with a sample person and a month of meals, running entirely in your browser: nothing you type leaves
  the page, and reloading starts over. Its Learn links open the handbook pages next to it.

### For people who run a server

* **The AI instructions changed: `PROMPT_VERSION` is `2026-10-21.1` (it was `2026-10-07.1`).** The meal-ideas and Ask instructions are
  worded from the person's profile, Ask has a chat protocol and saving tools, lab report photos have a task line, and food preferences
  add a taste list. The rules about lows, doses and medicines are the same text for every profile. If you choose a model for Ask or
  meal ideas, run the golden set with it (`python scripts/ai_eval.py` and `python scripts/ai_eval.py --chat`,
  [docs/ai.md](docs/ai.md#for-contributors)); the project's own live run for this version is still to do.
* **Schema step 17** (`food_preferences.source` and `updated_at`, back-filled; nothing is removed) runs at the next start,
  in one transaction. Take a backup first as for any upgrade. The "Not for me" routes keep their shapes; new routes are
  `GET /api/guidance/preferences`, `PUT` and `DELETE /api/guidance/preferences/{food_id}` and `GET /api/guidance/learned`.
  `export.json` → `food_preferences` now carries all four values with `source` and `updated_at`, and the import reads files
  from before the change. The guidance rules version is `2026-10-21.1`. Per request the ranking reads one more indexed query
  (the entries still planned on the last 30 days); the guidance performance budget is unchanged.
* **The Content-Security-Policy names one more Trusted Types policy: `trusted-types kh-sw kh-xml`.** The patient-portal
  (C-CDA) lab import parses the .xml file in the browser, and the browser's XML parser is a Trusted Types sink; the new
  `kh-xml` policy is created once by the app and passes only files without a DOCTYPE or ENTITY declaration. If you set
  your own CSP at a reverse proxy instead of using the app's header, add `kh-xml` there too, or that import cannot read
  any file. See [docs/security.md](docs/security.md).
* **Importing an export that holds glucose tablets (or gel, shots or a salt substitute) works.** The built-in list gives
  glucose tablets, gel and shots and the two salt substitutes a negative food number of their own (where a USDA food has its
  FoodData Central id), and a copy of such a food keeps it. An export of a log that used one wrote that number in
  `builtin_foods` (and in `custom_foods` for a copy), and the import refused the whole file with "builtin_foods[0].fdc_id: Input
  should be greater than or equal to 1". It now reads them; a number that matches no food here is reported as a built-in food this
  server does not have, as before. (Found while building the demo's import: a log kept in the online demo with the built-in glucose
  tablets is the common case.)
* **Entries have a `version`, and `PUT` / `DELETE /api/log/{id}` take `If-Match`.** Every entry in an API answer carries
  `version`, a short hash of what is stored (nothing new is stored: no schema step). A `PUT` or `DELETE` with
  `If-Match: "<version>"` that does not match answers **412** with `{"detail", "current": <the entry>}` and changes nothing;
  an entry that is not yours is a 404 first, with or without a valid version. Without the header both routes behave as
  before. The data export leaves `version` out and the import accepts and ignores it. See
  [ARCHITECTURE.md](ARCHITECTURE.md#offline-edits-and-deletes-roadmap-note-02-r5-queueable-offline-actions).
* **Privacy tier 3: `local_then_cloud`.** `ai.route.photos`, `ai.route.meal_ideas` and `ai.route.describe`
  (`AI_ROUTE_PHOTOS`, `AI_ROUTE_MEAL_IDEAS`, `AI_ROUTE_DESCRIBE`) accept a fifth value, `local_then_cloud`: the call goes to the
  local AI, and the cloud AI (the provider with the role `cloud`) is sent the same request, prepared exactly as the route `cloud`
  would, **only when the local answer fails the schema or the app's rules**, and only for a person who agreed to send that purpose
  to the cloud host. It is not used when the local AI is unreachable, slow, erroring, over quota or declines. Both roles are
  needed (with no cloud AI it behaves as `local`; with no local AI it is off). The admin table has a **Local, then cloud** column
  with the one-line rule and a warning; `PUT /api/admin/ai-routing` and the settings refuse it for Ask (`400 no_fallback`) and
  for lab report photos (still `local` or `off` only). Defaults and the upgrade rule are unchanged, so nothing changes until an
  admin picks it. No schema change. Each call is counted in `ai.shared_daily_limit` and has its own AI activity row. See
  [docs/ai.md](docs/ai.md#local-first-cloud-only-when-the-local-answer-fails) and [docs/privacy.md](docs/privacy.md).
* **Lab report photos: a new routed feature that is local or off only.** `ai.route.labs` (`AI_ROUTE_LABS`) takes `local` or
  `off` and refuses `cloud` and `any` (in the setting, the admin table, `PUT /api/admin/ai-routing` and the environment).
  The default is `local`: with no local AI (a shared provider with the role `local`, a vision model, a private host) the
  feature is off. A server upgraded from an earlier version starts it on `local` even though its other features start on
  `any`. **Schema step 16** rebuilds `ai_consents` so the new consent purpose `labs` is allowed (every existing consent is
  kept; back up before upgrading, as always). `POST /api/ai/read-lab-report` is the new route (raw JPEG body, `?dry_run=true`);
  it counts in `ai.shared_daily_limit`; the AI activity row keeps no copy of the AI's answer. The admin's routing table shows
  only Local and Off for that row. See [docs/ai.md](docs/ai.md#which-ai-does-each-feature-use).
* **Which AI does each feature use? (privacy tiers, tier 1).** You can now keep **two shared AI providers at once**, a
  *local* one on your own network (Ollama on a home GPU) and a *cloud* one, and pin each feature (**photos**, **meal
  ideas**, **describe a meal**, **Ask**) to *local*, *cloud* or *off*: Server administration → AI providers → *Which AI
  does each feature use?*, the settings `ai.route.*`, or `AI_ROUTE_PHOTOS`, `AI_ROUTE_MEAL_IDEAS`, `AI_ROUTE_DESCRIBE`,
  `AI_ROUTE_CHAT`. **The default is the least-trusting one: every feature is local, so with no local AI a feature is off
  until you pin it to cloud.** Only a provider on a private host (`AI_PRIVATE_HOSTS`; a name must be listed by name) can be
  the local AI, the server re-checks that before each call and refuses to connect to the local AI on a public address,
  and the table warns "this sends … to <host>, outside your network" before a feature is pinned to the cloud. The
  environment provider takes a role with `AI_PROVIDER_ROLE=local|cloud` (the Ollama overlay `deploy/compose.ai-ollama.yaml`
  sets `local`). **Upgrading changes nothing:** a server that already has a shared provider starts every feature on
  `any` (the old rule: the provider each person chose), and the table says "Routing is not set up yet" until you
  choose; a new server starts on the defaults. A person's own key stays their choice; `off` is off for everyone. Consent,
  quota and the AI activity list follow the provider a feature uses, so a feature moved to another provider asks for
  consent again. The Ask microphone is not routed: it belongs to Ask (its recording goes to the transcription server, and
  Ask `off` takes it along). No schema change. [docs/ai.md](docs/ai.md#which-ai-does-each-feature-use),
  [docs/privacy.md](docs/privacy.md).
* **Voice input for Ask** is a new switch, **off by default**: Server administration → Server settings → Optional AI →
  *Voice input for Ask (a microphone button)*, or `AI_VOICE_ENABLED=true`. It needs Ask on and **a transcription server you
  set up**: `STT_BASE_URL` (one OpenAI-compatible `/v1/audio/transcriptions` endpoint, base ending in `/v1`), `STT_MODEL`,
  `STT_API_KEY_FILE` if it wants a key (write-only, never returned), `STT_TIMEOUT_S`, `STT_DAILY_LIMIT` (100 recordings per
  person per day) and `STT_MAX_AUDIO_BYTES` (1.5 MiB). The address follows **the same rules as an AI provider** (the pinned
  SSRF transport; a LAN host such as `stt:8000` only when `AI_PRIVATE_HOSTS` lists it); there is no new outbound path.
  **Recordings are transcribed and deleted: never written to disk or the database, never logged, and the transcript is not
  stored either.** The AI activity list gets one row per recording (host, model, a length bucket, the outcome; no words).
  Server administration → AI providers → *Speech to text* shows the host and model (never the key) with **Test
  transcription** (one second of silence). **`Permissions-Policy` now allows the microphone for the app's own origin
  (`microphone=(self)`, it was `microphone=()`)**; everything else in the header is unchanged. **Schema step 14**: `ai_consents` is
  rebuilt so a consent for the new purpose `voice` can be stored (every consent is kept; as always, back up before
  upgrading). `deploy/compose.stt-whisper.yaml` is an optional overlay with a local speech-to-text container on an internal
  network with **no route to the internet** (read-only, no capabilities, non-root, limits, a health check): put the model in the
  volume once beforehand, and **replace the digest placeholder with a digest you verified** before using it. The browser's own
  speech recognition is never used (Chrome would send the audio to Google, Safari to Apple). See
  [docs/ai.md](docs/ai.md#voice-input-speech-to-text).
* **Ask (a chat with the AI inside the app)** is a new switch, **off by default**: Server administration → Server
  settings → Optional AI → *Ask (a chat with the AI inside the app)*, or `AI_CHAT_ENABLED=true`. It needs
  `AI_ENABLED` and a provider; people who opted in then get the **Ask** tab. While it is off, `POST /api/ai/chat`
  answers 404 and nobody sees the tab. A question takes up to 7 model calls (at most 6 tool calls, then the answer),
  each counted in `ai.shared_daily_limit` (30 by default, so it runs out faster), each through the concurrency
  gate, the timeout and the AI activity list. **The AI activity rows of Ask keep no request, answer or message
  text** (only the step, the tool name and the outcome), whatever `AI_AUDIT_RETENTION_DAYS` says, and the
  conversation is not stored on the server. **Schema step 12**: the table `ai_consents` is rebuilt so a consent for
  the new purpose `chat` can be stored (every consent is kept; as always, back up before upgrading). Run
  `python scripts/ai_eval.py --chat` with your provider to see how well its model follows the one-JSON-step protocol.
  Small local models may not; see [docs/ai.md](docs/ai.md).
* **Let people trust Ask to save without asking** is a new switch, **off by default**: Server administration → Server
  settings → Optional AI → *Let people trust Ask to save without asking*, or `AI_ALLOW_TRUSTED_SAVES=true`. It needs Ask
  on. While it is off, every save the assistant asks for in Ask is a card the person presses Save on, whatever people
  chose before (their choice is kept and applies again if you turn it on). **Schema step 13**: a new table,
  `assistant_ask_keys`, remembers for 24 hours (as hashes) which chat request already saved, so a request sent twice
  saves once; nothing existing changes (as always, back up before upgrading).
* **Assistant access** is a new switch, **off by default**: Server administration → Server settings → Optional
  AI → *Assistant access (personal tokens for a chat assistant)*, or `ASSISTANT_ENABLED=true` (passed through by
  `deploy/compose.yaml`). While it is off nothing changes for anyone (members do not see the Settings card) and
  no token can be made or used; turning it off later stops every token at once without deleting any. Schema step
  10 adds the `api_tokens` table (SHA-256 hashes only, deleted with the account); the upgrade runs by itself.
  New routes: `GET`/`POST /api/me/tokens`, `DELETE /api/me/tokens/{id}`. A token is accepted only by the
  assistant's own endpoint, never by the rest of `/api`; a refused token counts as a failed sign-in for its
  address. `python -m app.admin reset-password --stdin` and `disable-user` revoke the account's tokens.
  [docs/assistant.md](docs/assistant.md) has the details. `POST /api/me/tokens` takes `can_log` (default false):
  true gives the token the scopes `assistant:read assistant:log`; an existing token stays read-only.
* **Import of a person's export, `POST /api/me/import`** (cookie session, CSRF header, password entered recently;
  `?dry_run=1` checks and counts and keeps nothing; `merge=1` and `replace_profile=1` are the two choices
  above). The file is untrusted input: every record kind is checked against the API's own limits (unknown fields,
  NaN, a wrong version, a bad date or a food id that points nowhere refuse the whole file, naming the record
  and its position), and ids are remapped (built-in foods are found by their FoodData Central id; a shared USDA
  or Open Food Facts food is linked when this server already has the row, and otherwise kept as the person's own
  copy, never written as a shared row from a file). It runs in one transaction, writes one `data.imported`
  activity row with counts only, and is limited to 20 requests per person per hour. Its body limit is its own,
  **`MAX_IMPORT_BYTES` (16 MiB)**, for this one path; every other route keeps `MAX_BODY_BYTES` (1 MiB). A year
  at eight entries a day is about 3.5 MB as the export writes it, and a 15 MB file needs about 90 MB of extra
  memory for a moment (the containers are limited to 512 MB). No schema change. The export (`export.json`) now
  also lists the built-in foods a person uses (`builtin_foods`) and carries the whole record of each shared
  food they linked, so that it can be imported elsewhere; version stays 1 and older files still import.
* **The assistant's MCP server, `POST /mcp`** (only while assistant access is on; otherwise `404`). MCP Streamable
  HTTP with JSON answers, stateless, protocol versions 2025-06-18 and 2025-03-26, four read-only tools
  (`safety_check`, `get_today`, `search_foods`, `check_meal`). It takes only an assistant token (never the sign-in
  cookie), refuses a foreign `Origin` (`403`) and `GET`/`DELETE` (`405`), and allows 60 requests a minute per
  token (`429`). `search_foods` asks USDA FoodData Central (the person's own key, or the shared key within its
  daily quota) when the app's own foods do not fill the results; nothing it finds is saved. Pass the
  `Authorization` header through your reverse proxy. Connecting Open WebUI
  and a Hermes Agent profile, the system prompt and the limits are in [docs/assistant.md](docs/assistant.md).
  A token with `assistant:log` also lists and may call `log_food` and `save_recipe` (not read-only; each save is
  one transaction and one activity-log row, and counts in the same 60 requests a minute); with any other token
  those two are not listed and calling one is an error result that saves nothing. `search_foods` results from
  USDA can be named by `fdc_id` in `check_meal` (read only), `log_food` and `save_recipe` (added to the person's
  list). No schema change. `ASSISTANT_ENABLED` is listed (commented out) in the Quadlet and Kubernetes examples.
* **A retried save is not saved twice; an admin can revoke a person's assistant tokens.** `log_food` and
  `save_recipe` take an optional `request_key`: a second call with the same key by the same token within 24 hours
  saves nothing and answers with what the first call saved (as it is in the app now). Schema step 11 adds
  `assistant_request_keys` (hashes only; rows older than 24 hours are deleted). Server administration → People →
  Manage gains **Revoke assistant tokens (n)**, shown while assistant access is on and the person has active tokens
  (`POST /api/admin/users/{id}/revoke-tokens`); it appears in that person's activity. See
  [docs/assistant.md](docs/assistant.md).
* The image is about 1 MB smaller: the handbook's search support for other languages
  (`/learn/assets/javascripts/lunr/`: lunr-languages, TinySegmenter, wordcut; 964 KB) is left out of the
  image and the GitHub Pages copy, as the source maps already were. The handbook searches in English only,
  so its search worker never loaded those files; `tests/test_deploy.py` keeps the two in step.
* `python scripts/build_preview.py --pages DIR` writes the demo as a small static site (the scripts and
  stylesheets as files, the app's Content-Security-Policy as a `<meta>` element, no inline script); the
  GitHub Pages workflow builds it into the handbook site's `demo/` and checks its links with the rest.
* `python -m app.admin backup --dir DIR --keep N` writes a timestamped copy
  (`kidney-YYYYMMDDTHHMMSSZ.db`, UTC) into DIR and keeps only the newest N of them, so a backup tool on
  the host (restic, borg, Duplicati) can copy a separate folder of finished files instead of the live
  database. Plain `backup FILE` and `backup -` are unchanged.
* Pulling the image without logging in needs the GHCR package to be public; a repository's visibility
  does not carry over to its packages. Release notes now say so.
* Each GitHub release's notes gain an **Image** section with the multi-arch index digest to pin
  (`:X.Y.Z@sha256:…`), added by a new `release notes (image digest)` job of the release workflow when
  the release exists by then (publishing the release in the GitHub UI creates the tag, so it does);
  otherwise the job prints the block to paste. The deployment guide and the Quadlet unit show the
  digest form first, for hosts managed from git with Renovate or Dependabot.
* **Kubernetes: the base in `deploy/k8s` is now cluster-neutral** and renders unchanged on any cluster;
  cluster-specific values moved to an example overlay, `deploy/k8s-overlays/example/` (kustomize
  patches: `PUBLIC_URL` and `TRUSTED_PROXIES`, the NetworkPolicy's ingress namespace, the HTTPRoute,
  an optional storage class and the image pin). **Upgrade note:** if you applied `deploy/k8s` directly
  after editing it, copy the example overlay, move your values into it and apply the overlay: the base
  alone now lets no traffic in and trusts only loopback. Own overlays under `deploy/k8s-overlays/` are
  ignored by git; a GitOps repository can use the base remotely (`//deploy/k8s?ref=v0.4.0`). CI renders
  and validates both.
* Docs: the optional AI is introduced in three questions (which model answers, what it may do, whose
  key pays and who can read the request), with a recommended starting setup for a home server with
  and without a GPU (`docs/ai.md`, and the handbook's AI page in plain words).
* Docs: Litestream (WAL streaming) works; the two commands that force a full checkpoint and a new
  generation are named (`docs/deployment.md`). A `TRUSTED_PROXIES` row for a proxy container on a
  shared rootless Podman network, and what trusting the whole subnet risks (`docs/security.md`). With
  more than one person signing in, `AUTH_MODE=proxy` behind an SSO provider with MFA is recommended
  until local accounts get a second factor.
* **The published image now runs Python 3.15.** Chainguard's free `python:latest` moved from 3.14 to 3.15,
  and the old 3.14 digests no longer get security updates, so `deploy/Containerfile` follows (builder and
  runtime digests; nothing to do when you pull the new image). Still wheels only, hash-locked, nothing built
  from source. `pydantic` 2.13.5 → 2.14.0 and `pydantic-core` 2.46.5 → 2.50.0 are the only pins that
  moved: 2.46.5 has no Python 3.15 wheel (2.48.0 and later do). No change to what the app does. The
  handbook build stage (a throw-away stage that only produces the static pages) stays on a Python 3.14
  digest for now because PyYAML has no 3.15 wheel yet, and `deploy/Containerfile.debian` stays on
  `python:3.14-slim-trixie` (new digest). CI now tests Python 3.12, 3.14 and 3.15; on 3.15 the two test
  files that read YAML skip, since PyYAML is left out of `requirements-dev.lock` there.

### For contributors

* **Learn my food preferences, part C** ([note 09](docs/dev/research/09-food-preferences.md) §4.7, §4.8; the optional AI and
  Ask). `PROMPT_VERSION` is `2026-10-21.1` (the owner's live `python scripts/ai_eval.py --chat` for it is still to do).
  `prompts.person_block` gains `likes`, `less_often` and `not_for_me` (`taste_names`: NFKC, no `Cc`/`Cf`, 60 characters, at most
  10, null when empty) from `context.explicit_preferences`, read by `routes._person` for meal ideas and Ask only; candidates
  carry `liked` next to `often` (`ai_bridge` now sets both from the person's Like and `HabitStats.days_14 >= OFTEN_MIN_DAYS`
  themselves, not from whether the card had room to show `you_like` or `you_eat_often`; `prompts.candidate_block` and
  `guard.often_ids` read the bit); `you_like` joins `schemas.REASON_CODES`, the `Code` literal and `guard.REASON_TEXT`, and
  `guard.true_reasons` / `check_claims` / `liked_ids` keep it only for a liked candidate; `guard.person_excluded` drops an idea
  with a Not for me food or a never-suggest group (also when the food came from a saved meal). Rule 9 of the meal prompt and
  the "Tastes" paragraph of Ask's rule 10. `set_food_preference` (`app/ai/chat_preference.py`: `{food_id | category, preference:
  like | less | not_for_me | clear}`, in `chat.SAVE_TOOLS`, counted in `MAX_SAVES`) is always a card in every trust mode:
  `chat_save.run_save` dispatches it before the mode, `save_now` refuses it, `propose` writes nothing, `foods.visible_categories`
  is shared with `GET /api/foods/categories`; it is **not** in `app/mcp/tools.py`, so `tools/list` never shows it and
  `tools/call` says "unknown tool" for every token scope. The page applies Remember through `api.setFoodPreference` /
  `clearFoodPreference` (`js/core.js`) or the whole `guidance` setting, and Undo restores the state read at that moment
  (`js/views/ask.js`, tested in Node by `tests/js/ask_taste_page.mjs`). Golden: ten `preferences-*` / `injection-preference-name`
  cases, `feature: "chat"` support in `tests/test_ai_golden.py` (`nothing_saved`, `pending`); `scripts/ai_eval.py` skips the
  `chat` golden cases, gains four `chat-taste-*` questions in `CHAT_SET` and reports `taste_first_violations`. New tests:
  `tests/test_ai_preferences.py`, `test_ai_guard_preferences.py`, `test_ai_chat_preference.py`, `test_ask_taste_ui.py`.
* **Learn my food preferences, part A** ([note 09](docs/dev/research/09-food-preferences.md); server and engine). Schema step
  17; `GuidancePreferences` gains `learn_from_log`, `like_categories`, `less_categories` and `hidden_usual_meals` (a model
  validator keeps a group in one list); the preference term `pref(f) = clamp(P_food + P_group + L, -2.5, +1.0)` in
  `score.py` (`PrefTerms`, `pref_terms`, `skip_stats`, `HabitStats.pref`, `Scorer.pref`, the clamped mean in `score_meal`),
  added after the hard filters and reported as the explain component `preference`; `neutral` and `learn_from_log` gate the
  habit history in `habit_stats`; `you_like` in `fits.reasons_for`; `fits.usual_meal_entries` (key, filters), `fits.learned`;
  the low-treatment floor in `swaps.hypo_options`; `context.load` reads `planned30` (and `eaten30`),
  `context.explicit_preferences` is the helper for the AI step. The browser twin (`engine/guidance/*.js`, `mock/guidance.js`,
  `mock/export.js`, `mock/import.js`) and the vectors (`guidance_vectors.json` +43 cases, `settings_vectors.json`,
  `import_vectors.json`) follow; `RULES_VERSION` is `2026-10-21.1`. `ai_bridge` keeps `you_like` out of the candidates'
  `reasons` and passes a `liked` bit. New tests: `tests/guidance/test_preferences.py`, `test_preferences_api.py`,
  `tests/test_migration_m017.py`, and additions to the import, isolation, export and parity tests.
* **Demo: keep the data in the browser** (`app/static/js/mock/persist.js`, `mock/export.js`, `mock/import.js`,
  `views/demo_local.js`, `css/demo-local.css`; [docs/demo.md](docs/demo.md), [ARCHITECTURE.md](ARCHITECTURE.md#keep-my-data-in-this-browser-demo-only)).
  The mode is reachable only where `window.KDL_PREVIEW` is set (the Pages build and the preview). `MockApi` takes `seed: false`
  (an empty account) and `KH.mock.onWrite` is called after each write that went through. `GET /api/me/export.json` and
  `POST /api/me/import` are demo-only routes; the import twin is checked against the real server by
  `tests/data/import_vectors.json` (generated by `tests/data/gen_import_vectors.py`, replayed by `node tests/js/run_vectors.mjs`,
  about 250 checks: every refusal in its words, the dry run, merge, replacing the profile, an older file, and what the account holds
  afterwards). Tests: `tests/test_demo_local_ui.py` (wording, no inline script or style, reachable only in the demo build),
  `tests/test_demo_local_storage.py` running `tests/js/demo_local_storage.mjs` against a fake IndexedDB
  (`tests/js/fake_idb.mjs`), `tests/test_import_vectors.py`; the browser walk is `python tools/e2e/demo_local.py`.
* Lab results from a patient-portal C-CDA file are browser-only (no route, setting, dependency, network request or schema step), with
  **one CSP change: `trusted-types kh-sw kh-xml`** (`app/security.py`). The browser's `DOMParser` is a Trusted Types sink, so
  `app/static/js/engine/ccda_labs.js` (`KH.ccdaLabs`) creates a second named policy, `kh-xml`, whose `createHTML` accepts only a string
  without a DOCTYPE or ENTITY; `tests/test_frontend_shell.py` now allows exactly two policy-creating files and one parser call, and
  `tests/test_security.py` pins the CSP. The reader reuses `KH.fhirLabs` (the LOINC table, `unitOf`, `dayOf`, and a new exported
  `collector()` for the counting, collapsing, 1,000-row cap and headline; the FHIR reader's behaviour and vectors are unchanged);
  `app/static/js/views/lab_ccda.js` (`KH.labCcda`) is the card and draws `KH.labFhir.review`, which now takes an id `prefix`. The XML parser
  is injected (`parseXml`): Node tests use the dev-only `tests/js/mini_xml.mjs`, real Chromium runs in `tools/e2e/regress.py`. Tests:
  `tests/data/ccda_labs_vectors.json` (hand-written C-CDA documents and expectations; `node tests/js/gen_ccda_labs_vectors.mjs`
  regenerates it and stops if the module disagrees) in `node tests/js/run_vectors.mjs`, `tests/test_ccda_labs.py` (the OIDs, the shared
  table, every row converts like `units.convert`, DTD refusal before parsing, no identity in an answer) and `tests/test_ccda_labs_ui.py` (with
  `tests/js/ccda_labs_page.mjs`: no inline script, no network call, only fixed element and attribute names read, a file over 5 MB never
  read, more than 20 files refused, new rows ticked, only ticked rows saved, text drawn as text, one policy created once).
* Offline edits and deletes (`js/offline.js`, `js/core.js`, `app/log.py`). One outbox item per entry (`edit` or `delete`,
  with the `version` and the entry as the person saw it), replayed with `If-Match`; a 412 whose entry equals the one the change
  was made on (the person's own queued "mark eaten" went first) is sent once more, any other is a conflict card; a 404 drops
  the change; editing or deleting an entry that waits on the device rewrites or removes the queued create. `KH.net` gained
  `intercept` and `onConflict`; `KH.request` takes `{ ifMatch, base }`; the demo API's `request`/`handle` take request headers
  and `js/mock/log.js` has `entryVersion`, `versionMatches` and the 412. Parity vectors: `tests/data/entry_version_vectors.json`
  (`python3 tests/data/gen_entry_version_vectors.py`, replayed by `node tests/js/run_vectors.mjs`). Checks:
  `tests/test_log_if_match.py`, `tests/test_offline_edits_ui.py`, `node tests/js/outbox_changes.mjs` (the queue logic in Node
  against the demo API), and `python tools/e2e/device.py --only changes` in Chromium. `tests/js/demo_loader.mjs` can load more
  scripts (`extra`) and take the page's `navigator`.
* Lab results from Apple Health clinical records are browser-only: no route, setting, dependency, network request or schema step.
  `app/static/js/engine/fhir_labs.js` (`KH.fhirLabs`: the LOINC table, `start()`/`add()`/`finish()`) reads FHIR `Observation`s and
  Bundles; `app/static/js/views/lab_fhir.js` (`KH.labFhir`) is the card and review table and saves through the shared
  `KH.views.labs.saveImported`. Every LOINC code was looked up in LOINC 2.82 and cites its loinc.org page in the code and in
  [docs/targets-and-labs.md](docs/targets-and-labs.md). Tests: `tests/data/fhir_labs_vectors.json` (hand-written resources and
  expectations; `node tests/js/gen_fhir_labs_vectors.mjs` regenerates it and stops if the module disagrees) in
  `node tests/js/run_vectors.mjs`, `tests/test_fhir_labs.py` (every code's test and unit exist in `app/units.py`, check digits, the docs
  list every code, every proposed row converts like `units.convert` and is accepted by `POST /api/labs/import`) and
  `tests/test_fhir_labs_ui.py` (with `tests/js/fhir_labs_page.mjs`: no inline script, no network call, a file over 1 MB never read, more
  than 2,000 files refused, new rows ticked, only ticked rows saved, text drawn as text).
* Privacy tier 3 (`local_then_cloud`): `routing.FALLBACK_ROUTE` / `FALLBACK_FEATURES` / `allowed_routes`; `Resolved.fallback`;
  `Prepared.cloud` (the same prepare function called with the cloud `ProviderConfig`) and `features.judge_rejected`;
  `routes.run_call` is built around `Attempt` (`failed_checks`, `usable`), `_clear_fallback` (consent, tool check, quota),
  `_fallback_view` and `dry_run_of`; `config.consent_request(fallback=...)` and `FALLBACK_RULE`; the type `AiStructuredRoute` in
  the registry with the JS twin and vectors (`tests/data/gen_settings_vectors.py` adds `local_then_cloud` as a bad value for
  `ai.route.chat` and `ai.route.labs`). Tests: `tests/test_ai_fallback.py`, `tests/js/routing_page.mjs` scenario 7 with
  `tests/test_ai_routing_ui.py`; the browser harness `tools/e2e/fallback.py`. `PROMPT_VERSION` is unchanged.
* The meal ideas and Ask prompts follow the profile (kidney-only profile, part 3). `app/ai/prompts.py`: `SYSTEM_PROMPT` and
  `CHAT_SYSTEM_PROMPT` are templates whose only profile-dependent part is `[[CONDITION]]`, rendered by `system_prompt(person)`
  and `chat_prompt(person)` from `condition_text(person)`, which words only whitelisted profile values. The low-treatment
  rules and the `hypo` purpose note are the same text for every profile (a test compares them across three profiles);
  `TASK_SYSTEM_PROMPT` (describe a meal, label, plate) is one fixed sentence with no profile data. `person_block` sends null
  for a stage or diabetes type not chosen yet; `targets_block(meal_carbs=False)` leaves the per-meal and per-snack carbohydrate
  goals out for diabetes "None". This made `PROMPT_VERSION` `2026-10-15.3` (lab report photos made it `.4`, food preferences `2026-10-21.1`): the owner runs the golden set
  with a live model for the current one (command in [docs/ai.md](docs/ai.md#for-contributors)). Tests: `tests/test_ai_prompts.py` (snapshots
  `tests/fixtures/ai/prompts_*.txt` for type 1 with CKD 4, kidney-only stage 3b and not chosen yet),
  `tests/test_ai_profile_prompts.py`, the golden cases `tests/ai_golden/kidney-only-*.json` (one per feature) and the
  `chat-kidney-only-*` questions of `scripts/ai_eval.py`. No code path of the safety rules changed.
* Privacy tiers, tier 1: `app/ai/routing.py` (roles, `resolve_feature`, the status and admin views, the once-only
  `initialise`), the network scope `local` in `app/ai/netpolicy.py` (`is_private_host`) with `ProviderConfig.local_only`,
  `GET`/`PUT /api/admin/ai-routing`, six `ai.route.*` registry keys (with their twin and vectors), `js/views/ai_routing.js`.
  Every feature resolves through `routes._resolve(request, conn, user, feature)`. The older AI tests set the routing to `any`
  with `tests/ai_support.py` `LEGACY_ROUTING`; the new ones are `tests/test_ai_routing.py`, `tests/test_ai_routing_ui.py` and
  `tests/js/routing_page.mjs`.
* Visit prep is front end only (no route, table, migration or server code): `js/views/visit.js` (the view `#visit`, no tab; Trends'
  period card opens it), `js/engine/visitprep.js` (`KH.visitPrep`, pure: the averages are picked from `GET /api/log/summary`, the lab
  rows and arrows from `GET /api/labs`, the question limits, the handbook checklist word for word), `css/visit.css` (screen and
  `@media print`), the `#view-visit` section of `index.html`, `visit` in `VIEWS`, and `KH.symptoms.flagEl` exported from
  `js/views/symptoms.js`. The questions live in the page's memory only. Tests: `tests/test_visit_prep_ui.py`,
  `tests/test_visit_prep_numbers.py` (with `tests/js/visitprep_runner.mjs`); `python tools/e2e/visitprep.py` drives it in Chromium
  and writes the A4 and Letter PDFs. No parity vectors: there is no server logic with a twin.
* The symptoms log is `app/symptoms.py` (`/api/symptoms`, the red-flag table `RED_FLAGS`, row shape), the `Symptom*` models in
  `app/models.py`, `app/migrations/m015_symptoms.py` (**schema step 15**: `symptoms`, no CHECK on the key), `symptoms` in the
  export (`app/account.py`, plus `symptoms.csv`) and the import (`app/data_import.py`, `ImportSymptom`), and in the browser
  `js/engine/symptoms.js` (`KH.symptomRules`), `js/mock/symptoms.js`, `js/views/symptoms.js` and `css/symptoms.css`.
  Parity: `tests/data/gen_symptoms_vectors.py` writes `tests/data/symptoms_vectors.json` from the server (a request script
  run on a fresh server and a fresh demo), `node tests/js/run_vectors.mjs` replays it (`tests/js/demo_loader.mjs` loads the
  whole demo), `tests/test_symptoms_vectors.py` fails when it is stale. Tests: `tests/test_symptoms.py` (routes,
  validation, the handbook page checked against the red-flag quotes, isolation, deletion, export and import),
  `tests/test_migration_m015.py`, `tests/test_symptoms_ui.py`; `python tools/e2e/symptoms.py` drives it in Chromium.
  `tests/test_isolation_v03.py` lists the table in its matrix. Export version stays 1 (`symptoms` is an optional list).
* Voice for Ask is `app/ai/stt.py` (configuration, clip checks, the multipart call, consent and limit helpers; pure),
  `app/ai/voice.py` (`POST /api/ai/transcribe`, the admin test), `send_json(content=...)` in `app/ai/transport.py`,
  `js/views/ask-voice.js` and `css/ask-voice.css` (attached to Ask by two hook lines in `ask.js`), the voice consent text and
  the Speech to text panel in `js/views/ai.js`, `app/migrations/m014_ai_consent_voice.py` (step 14, after step 13's
  `assistant_ask_keys`). Tests: `tests/test_ai_voice.py`,
  `tests/test_migration_m014.py`, `tests/test_ask_voice_ui.py` (a static test fails if any shipped file names the
  browser's speech recognition), `tests/test_deploy_stt.py`; `python tools/e2e/ask_voice.py` drives it in Chromium with a
  fake audio device and a fake transcription server. Plan: `docs/dev/plans/assistant-step2.md` (part B).
* The Ask chat is `app/ai/chat.py` (the step loop, the text policy, the dose and number checks, the "From the app"
  figures; pure but for the callbacks the route gives it), `ChatStep` in `app/ai/schemas.py`, the prompt in
  `app/ai/prompts.py`, `POST /api/ai/chat` in `app/ai/routes.py`, `js/views/ask.js`. It reuses `complete_json`, the
  gate, the quota, the consent flow and the step-1 tool functions (`app.mcp.tools.run`) instead of copying them, and
  `guard.MEDICINE_NAMES` is now shared by the names blocklist (its pattern is unchanged) and the dose check. Tests:
  `tests/test_ai_chat_checks.py`, `tests/test_ai_chat.py`, `tests/test_migration_m012.py`, `tests/test_ask_ui.py`;
  `scripts/ai_eval.py --chat` is the live check (manual, owner). Plan: `docs/dev/plans/assistant-step2.md`.
* Saving from the chat (part C) is `app/ai/chat_save.py` (trust, the confirm card, trusted saves), `run_save` and
  `SaveStep` in `app/ai/chat.py`, `trust` in the person's `ai` setting and `ai.allow_trusted_saves` in
  `app/settings_registry.py` (with the JS twin and vectors), `Asker` in `app/mcp/tools.py` (the saving tools' own code runs
  for the chat, audited as `via: "Ask"`), `token_id=None` in `app/mcp/request_keys.py` (table `assistant_ask_keys`),
  `ai.trust_changed` in `app/audit.py`, the choice and warning sheet in `js/views/ai.js` and the cards in `js/views/ask.js`
  (self-contained section). Tests: `tests/test_ai_chat_save.py`, `tests/test_migration_m013.py`, `tests/test_ask_ui.py`,
  `tools/e2e/ask.py`.
* `app.auth.api_tokens.AssistantUser` is the only dependency that reads `Authorization: Bearer`; a route on the
  assistant surface takes `user: AssistantUser` and gets `request.state.api_token` for its own limits.
  `current_user` stays cookie-only, and `tests/test_auth_coverage.py` walks every `/api` route with a valid
  token to keep it that way.
* `app/data_import.py` holds the import: strict pydantic models with `extra="forbid"`, `parse_export` and the
  `Importer`. The dry run does the real work inside the transaction and rolls it back, so its answer is exactly
  the real import's. `insert_entry` and `insert_template` take optional `created_at` / `updated_at`;
  `profile.apply_profile_changes` is the body of `PUT /api/profile` (no commit) and can replace the targets.
  `tests/test_data_import.py` is the matrix (round trip, dry run, all-or-nothing, extra fields, NaN, versions,
  secrets in a crafted file, another person's ids, duplicates); `test_isolation_v03.py` lists it for every table
  the import writes.
* `app/mcp/` is the MCP server (JSON-RPC by hand, no new dependency). Its tools call the app's own functions:
  `app.log.day_summary` (now also behind `GET /api/log`), `day_figures` for the projection, `food_warnings`,
  `guidance.hypo.prefilter`, `ai.features.red_flag`, and the new `app.foods.usda_search_records`. `/mcp` is the one
  exact path in `app.security.BEARER_PATHS` (no cookie CSRF checks, the Origin rule kept), and
  `tests/test_auth_coverage.py` holds it to being the only write route outside `/api`. `tests/test_mcp.py` covers
  the protocol, auth and every tool; `python tools/e2e/mcp_smoke.py` speaks the protocol to a real server.
* **Menu days to the app (note 08 §4.10).** `scripts/build_handbook.py` writes a plain link under each
  generated menu day, `#plan-menu?items=b173905x1,…` (`<meal letter><fdc_id>x<servings>`: built-in foods only, at most
  40, no personal data, no numbers the app would trust) and fails a day the link cannot carry. The MkDocs hook
  `handbook/tools/menu_links.py` points it at the app (`HANDBOOK_APP_LINK`), at the Pages demo or drops it.
  `js/engine/menu_link.js` reads it strictly (`tests/data/menu_link_vectors.json`, `node tests/js/run_vectors.mjs`) and
  `js/views/menuplan.js` shows the confirmation sheet; foods resolve through `GET /api/foods/builtin` (no new route, no
  schema change) and only **Add to plan** writes, through `POST /api/log/batch` with a `client_id` per food. Contract:
  [ARCHITECTURE.md](ARCHITECTURE.md#menu-days-in-the-app-add-this-day-to-my-plan-v04); tests `tests/test_menu_plan.py`;
  `python tools/e2e/menuplan.py` in Chromium. `handbook/tools/check_links.py` no longer reads a `#route?x=y` fragment as
  a page anchor.
* `requirements.txt` and `requirements-dev.txt`, kept through 0.3.0 so older instructions still worked,
  are gone. Install from the hash-locked files instead:
  `pip install --require-hashes --no-deps -r requirements-dev.lock` (or `requirements.lock` for the app
  alone).
* The constraints between lock files (dev on the runtime pins, the Zensical canary on the handbook
  build, Playwright on dev) moved from `-c ….lock` lines in the `*.in` files to the pip-compile command
  line in `scripts/lock.sh`; the locks themselves are unchanged. GitHub's Dependabot dependency graph
  reads every `requirements*.txt` and `*.in` file and failed on lines naming a `*.lock` file, which it
  never fetches. A test now keeps those files free of such lines.

### Security

No entry in this release fixes a vulnerability that was reported against 0.3.0 or any released version. The security-relevant
changes, collected from the entries above, are these; the model and the checks are in [docs/security.md](docs/security.md).

* **Two header changes.** `trusted-types kh-sw kh-xml` (a second named policy, created in one file, that passes only XML without
  a DOCTYPE or ENTITY declaration: the browser's XML parser is a Trusted Types sink) and `Permissions-Policy: microphone=(self)`
  (it was `microphone=()`; the camera was already allowed for the app's own origin). Everything else in the headers is unchanged.
* **A new credential, built to be small.** Assistant tokens are stored as SHA-256 hashes, shown once, expire (30 days, 90 days or 1
  year) and are revoked at once by changing or resetting the password, disabling or deleting the account, or an admin's
  **Revoke assistant tokens**. Only `POST /mcp` accepts one (never the rest of `/api`, never the sign-in cookie), it refuses a
  foreign `Origin`, it allows 60 requests a minute per token, and a refused token counts as a failed sign-in for its address.
  Saving needs a second scope that is off by default. `tests/test_auth_coverage.py` walks every `/api` route with a valid token.
* **The Ask chat is checked in code.** The app answers a low or an emergency itself, and checks every answer (text policy, dose
  check, number check, links removed); the activity rows keep no request or answer text; saving without asking needs an admin
  switch, a warning and gives Undo; a taste Ask offers to remember is always a card.
* **Untrusted files are validated, not trusted.** `POST /api/me/import` checks every record against the API's own limits and
  refuses the whole file on the first problem, needs a recent password, is limited to 20 requests an hour and has its own body limit
  (`MAX_IMPORT_BYTES`); passwords, sessions, tokens, keys and AI activity are never imported even if a file has them. Health files
  (the CSV, Apple Health and C-CDA imports) are read on the device and nothing is uploaded; the server has no XML parser.
* **Outbound calls keep one gate.** The speech-to-text server is called through the same SSRF-checked transport and private-host rules
  as AI providers, so there is no new outbound path; the *local* AI role is limited to private addresses, re-checked before each call;
  a lab report photo never reaches a cloud AI or a person's own provider; recordings are never written to disk or logged.
* **A supported base image.** The image moved to Python 3.15 because the 3.14 digests of Chainguard's free tier no longer get
  security updates.

### Known limitations

What is built and tested here but not yet verified outside it. The things marked *owner* need the maintainer's own hardware, keys or
accounts; the list of checks is in [docs/maintainers.md](docs/maintainers.md) and everything deferred is in
[docs/ROADMAP.md](docs/ROADMAP.md).

* **The handbook is still a draft, and the rules still await review.** Every handbook page shows "Draft: not yet reviewed by a
  clinician" until a named reviewer signs it off (the open questions are in `handbook/REVIEW.md`). The rules marked "Expert opinion"
  in the target suggestions, the meal guidance's per-meal caps and score weights, the potassium-additive rule, the default
  carbohydrate tolerance (10 g) and the 10 % ceiling of the "about" tolerance also wait for a renal dietitian or nephrologist. The
  red-flag words of the symptoms log are the handbook's own and are as unreviewed as it is. Keep `targets.lab_rules_enabled` off
  on a public demo server.
* **No AI model is recommended yet.** Every AI feature was tested against fake providers through the real network code, not against
  a live Ollama, OpenAI, OpenRouter or Hermes Agent. The live evaluations for the current `PROMPT_VERSION` (`2026-10-21.1`),
  `python scripts/ai_eval.py` and `python scripts/ai_eval.py --chat` with the model in use, have not been run (*owner*), so how well
  a model follows Ask's one-JSON-step protocol, keeps tastes out of first place or reads a real lab report (units and dates a
  vision model misreads) is unmeasured. `scripts/ai_eval.py` does not exercise the routes, so the local-then-cloud fallback was only
  tried with two fake providers. Hermes Agent's tool check follows its documented API and was not tried against a live agent.
* **Not yet tried on real devices.** Installing, the live camera, HEIC photos, the offline outbox, **offline edits and a conflict
  made from a second device**, the Ask microphone (iOS Safari, Android Chrome), VoiceOver and TalkBack were checked in Chromium (fake
  camera and microphone, emulated offline), not on an iPhone, an iPad or an Android phone (*owner*). The `kh-xml` Trusted Types
  policy is exercised only by Chromium here. The live camera still needs HTTPS.
* **Real health exports have not been read.** The Apple Health and patient-portal C-CDA importers were written against
  hand-made samples that follow the published formats; a real Health export from an iPhone and real files from MyChart and one more
  portal have not been tried (*owner*), so a code, unit or section a real file has may be skipped (the headline counts what was
  skipped). The "entries optional" results template (`…2.3`) rests on HL7's own example and a second source, because its R2.1
  definition page could not be fetched; a result a portal puts only on the organizer's `effectiveTime` is not read.
* **Speech to text is untested against a real server.** The local whisper overlay (`deploy/compose.stt-whisper.yaml`) ships with a
  placeholder image digest that the person deploying it must verify, and has not been run with a real container.
* **Lab reports: photos, not PDFs.** The photo or a screenshot works (on the local AI only); uploading the PDF itself is not built.
  Importing the export `.zip` directly is not built either: **Import from a file** takes the `export.json` inside it (the demo's
  export gives the JSON only).
* **Offline is for the food log.** New entries, and now edits and deletes of entries, work without a connection. Profile and target
  changes (on purpose: a care team's targets must not be overwritten by a stale copy), lab results, symptoms, food preferences,
  settings, barcode lookups, AI and new guidance answers need a connection; the Treating a low card still works, and handbook
  pages work offline only once opened on that device.
* **Raspberry Pi speed is estimated, not measured.** Guidance requests take tens of milliseconds on an x86 machine (food
  preferences added one indexed query per request) and the browser copy stays under its 200 ms budget with the CPU slowed down 4×, but
  `scripts/bench_guidance.py` has not been run on a real Raspberry Pi 4 or 5 (*owner*; lower `GUIDANCE_POOL_PER_ROLE` if a Pi 4 is
  too slow, [docs/guidance.md](docs/guidance.md#performance)).
* **Python 3.15 is in the image only.** `deploy/Containerfile.debian` (the fallback) and the throw-away handbook build stage stay on
  Python 3.14 until PyYAML publishes a cp315 wheel; on 3.15 CI skips the two test files that read YAML. The handbook is still built
  with MkDocs and Material; moving to Zensical waits for a Zensical release that passes the CI canary, before Material's security
  fixes end (November 2026 at the earliest).
* **The kidney-only profile is partly done.** The app and the AI prompts follow a profile with *Diabetes: None*, but the handbook's
  framing (reviewed content) and the app's one-line description in the page metadata and the web app manifest ("for a renal diet with
  type 1 diabetes") are the owner's wording to choose.
* **Signatures need a public repository.** Release signing, provenance and SBOM attestations, and CodeQL run only while the GitHub
  repository is public; `scripts/verify-image.sh` fails for an image released while it was private.
* English only; one SQLite file per server; no reminders or push notifications; no OIDC sign-in and no second factor yet
  ([docs/ROADMAP.md](docs/ROADMAP.md) lists what is planned).

## 0.3.0 — 2026-10-07

Version 0.3 turns the single-person food log into a household app that is safe to run on a home
server, installs on a phone and keeps logging without a connection. It adds personalised targets
from lab results, rule-based meal guidance, barcode lookups, optional AI helpers and a patient
handbook served by the app. Everything that sends data off your server is **off until an admin turns
it on**, and each person decides for themselves.

**Before you upgrade a v0.2 server, read [Upgrading from 0.2](#upgrading-from-02-read-this-first).**
An auto-updating v0.2 Quadlet host needs its unit file replaced *before* the update.

### Highlights

* **Accounts and sign-in.** Every person in the household has their own account, log, foods, saved
  meals, profile and keys; an admin cannot read anyone else's data. The first admin is created with a
  one-time setup code from the server log, everyone else joins by invite link. Sign-in can also come
  from a reverse proxy (Authelia, Authentik, `tailscale serve`) or be switched off for one trusted
  device ([docs/accounts.md](docs/accounts.md)).
* **Shared and personal keys, encrypted.** API keys (USDA FoodData Central, AI providers) are
  encrypted at rest under `SECRET_KEY` and never shown again ("Set · ends in 9xQz"). An admin can
  share a key with a daily limit per person, and each person can add their own; a failing personal
  key never falls back to the shared one.
* **Security hardening.** Strict Content Security Policy with Trusted Types, a Host allowlist,
  CSRF checks, trusted-proxy handling, sign-in throttling, request size limits, an append-only
  activity log, and an SSRF-checked transport for every outbound call
  ([docs/security.md](docs/security.md)).
* **Rootless, signed images with an SBOM.** The image runs as UID 10001 with no shell, no package
  manager and a read-only root filesystem, on a digest-pinned Chainguard base. Releases are scanned
  before any tag moves, signed with cosign and published with SLSA provenance and an SPDX SBOM; check
  them with `scripts/verify-image.sh` ([SECURITY.md](SECURITY.md#verifying-the-image-before-you-run-it)).
* **A home-screen app that logs offline.** Install it on an iPhone, Android phone or computer. Over
  HTTPS it opens without a connection; food you log offline waits on the device and is sent exactly
  once when the server is back ([docs/install-on-your-phone.md](docs/install-on-your-phone.md)).
* **Personalised targets and lab results with eGFR.** Suggested targets now use age, sex, activity,
  dialysis details, a transplant date and recent lab results; each number explains its rule and
  source. A Lab results view converts units, warns about a dangerously high potassium, and works out
  eGFR (CKD-EPI 2021) and the albuminuria category ([docs/targets-and-labs.md](docs/targets-and-labs.md)).
* **Rule-based meal guidance.** "What fits now" for the next meal, lower-potassium, -phosphorus and
  -sodium swaps with the same carbohydrate, "Plan the rest of my day", end-of-day and weekly
  insights, and a "Treating a low" card that is never filtered or warned against. No AI needed; it
  runs on a Raspberry Pi ([docs/guidance.md](docs/guidance.md)).
* **Optional AI ideas and label photos.** An admin can connect an OpenAI-compatible provider (a local
  Ollama, LM Studio, llama.cpp, vLLM or LiteLLM server; OpenAI, OpenRouter or Nous Portal; a Hermes
  Agent profile). Each person opts in, agrees per destination, and can see the exact request first.
  AI picks only among foods the rules already allowed, reads nutrition labels into a draft you check,
  and never gives doses ([docs/ai.md](docs/ai.md)).
* **Barcode lookup, with Open Food Facts optional.** Scan with the camera, a photo or typed digits;
  the code is read on the device and only the digits reach your server. Your own foods are always
  found; USDA branded foods need a USDA key; Open Food Facts is off by default and needs each
  person's consent ([docs/barcode-and-photos.md](docs/barcode-and-photos.md)).
* **The patient handbook at `/learn`.** A plain-language handbook about kidney disease with type 1
  diabetes (stages, eating, labs, lows, medicines, preparing for treatment, living well, using and
  hosting the app), built into the image and served without sign-in or internet. Food warnings,
  alerts and target notes link to the page that explains them. Every page is still a draft awaiting
  clinical review (see [Known limitations](#known-limitations)).

### Upgrading from 0.2 (read this first)

1. **Replace an auto-updating v0.2 Quadlet unit before the update.** v0.2's unit uses
   `Image=ghcr.io/ksullivan86/kidney-health:latest`, `AutoUpdate=registry`, `HealthOnFailure=kill`
   and a plain-string `HealthCmd=` that runs through `/bin/sh`. `:latest` moves to 0.3.0 when it is
   tagged (no hold: the owner decided on 2026-10-06 not to keep `:latest` on 0.2). The 0.3 image has
   no shell, so under the old unit the health check always fails, the container is killed and systemd
   restarts it, about every two minutes. **Before** `podman-auto-update` runs, copy the 0.3
   `deploy/quadlet/kidney-health.container` (and `kidney-health.volume`) over the old files, adjust
   them, `systemctl --user daemon-reload` and restart; or pin the running 0.2 image by digest and
   `systemctl --user disable --now podman-auto-update.timer` until you upgrade. A host already in the
   loop: stop the service, install the 0.3 unit, reload, start
   ([docs/deployment.md, "From v0.2 to v0.3"](docs/deployment.md#from-v02-to-v03)). The 0.2 compose
   file and Kubernetes manifests have health checks that need no shell, so they do not loop, but
   replace them with the 0.3 files as well (secrets as files, `PUBLIC_URL`, the port on `127.0.0.1`,
   the hardened runtime flags) before you move them to the new image.
2. **Back up `kidney.db` first.** The first start migrates the database in place (schema 2 → 7). Before
   it changes anything it also copies the database to `kidney.db.pre-v3.bak` (mode 0600), which is
   deleted automatically 30 days later (`python -m app.admin purge-pre-v3-backup` deletes it at once;
   Settings → Admin → About shows it while it exists). That copy is the rollback path: do not roll
   back to 0.2 after a second person has an account. All existing data becomes the first account's.
3. **Finish first-run setup.** The log prints a **one-time setup code** (valid 60 minutes):
   `journalctl --user -u kidney-health | grep 'FIRST-RUN SETUP'`. Open the app, enter the code and
   choose the admin's user name and a password of at least 15 characters. Alternatives:
   `ADMIN_USERNAME` + `ADMIN_PASSWORD_FILE`, or `python -m app.admin create-admin NAME` (password on
   stdin).
4. **`APP_PASSWORD` is deprecated; HTTP Basic sign-in is gone.** A set `APP_PASSWORD` is imported once
   as the password of the admin `admin` (or `ADMIN_USERNAME`); a password shorter than today's rules
   must be changed at the first sign-in. After that it is ignored and logged as deprecated: remove it.
5. **Give the app a `SECRET_KEY_FILE`.** It encrypts stored API keys. Without it the app generates
   `$DATA_DIR/secret.key` and warns, but a key on the same volume as the data protects little. Create
   one in your engine's secret store (`podman secret create kidney-secret-key -`, a compose secret
   file or a Kubernetes Secret; every shipped profile mounts it) and keep a copy with your backups:
   without it, stored keys cannot be read and must be entered again. Move `USDA_API_KEY` into a file
   as well (`USDA_API_KEY_FILE`).
6. **Image tags changed.** Pushes to `main` now publish `:edge` and `:sha-<short>` (in 0.2, `main`
   published `:latest`). Version tags publish `:0.3.0`, `:0.3` and `:latest`. Track **`:0.3`** (the
   shipped unit does) or a digest you verified, not `:latest` or `:edge`.
7. **Set `PUBLIC_URL` when people use a host name** (e.g. `https://food.home.example.net`); unknown host
   names now get `400 Unknown host`. Reach the app through your HTTPS proxy (the port is published on
   `127.0.0.1` only) and list that proxy in `TRUSTED_PROXIES`; `--forwarded-allow-ips=*` is gone and
   uvicorn runs with `--no-proxy-headers` ([docs/security.md §4](docs/security.md#4-proxy-trust-trusted_proxies-per-topology)).
8. **Scripts that call the API** must sign in, and every POST, PUT, PATCH and DELETE must send
   `X-Requested-With: kidney-health` with a same-origin `Origin`. `/docs` and `/openapi.json` are off
   unless `ENABLE_API_DOCS=true`.
9. **CSV export** gains columns at the end: `purpose` (an entry that treated a low), `source` and
   `source_license`. Spreadsheet cells that start like a formula are escaped with a leading `'`.
10. **Running an `:edge` build from before this release?** Its schema 3 database is upgraded to 7 with no
    automatic copy: back it up first with the running container, for example
    `podman exec kidney-health python -m app.admin backup /data/before-0.3.0.db`.

**New optional settings** (all off or at a safe default; the full list is in
[docs/deployment.md](docs/deployment.md#configuration) and `app/config.py`; settings not set in the
environment can be changed in Settings → Admin → Server settings):

| Area | Settings |
|---|---|
| Accounts | `AUTH_MODE`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_FILE`, `REGISTRATION_MODE`, `INSTANCE_NAME`, `PASSWORD_MIN_LENGTH`, `PASSWORD_BREACH_CHECK`, `SESSION_IDLE_DAYS`, `SESSION_MAX_DAYS`, `REAUTH_MINUTES`, `LOGIN_IP_MAX_FAILURES`, `ALLOW_INSECURE_HTTP`, `AUDIT_RETENTION_DAYS`; proxy sign-in: `TRUSTED_PROXY_USER_HEADER`, `TRUSTED_PROXY_SECRET_FILE`, `TRUSTED_PROXY_ADMIN_GROUP`, `PROXY_LOGOUT_URL` |
| Network and limits | `PUBLIC_URL`, `ALLOWED_HOSTS`, `TRUSTED_PROXIES`, `MAX_BODY_BYTES`, `MAX_IMAGE_BYTES`, `HSTS_MAX_AGE`, `ENABLE_API_DOCS`, `PWA_ENABLED` |
| Keys | `SECRET_KEY_FILE`, `USDA_API_KEY_FILE`, `USDA_SHARED_DAILY_LIMIT` |
| Barcodes | `OFF_ENABLED` (off), `OFF_CONTACT`, `OFF_RATE_PER_MINUTE`, `OFF_BASE_URL` (env only), `BARCODE_NEGATIVE_TTL_HOURS`, `USDA_BRANDED_BARCODE` |
| Meal guidance | `GUIDANCE_ENABLED` (on), `GUIDANCE_POOL_PER_ROLE`, `GUIDANCE_BEAM_WIDTH` |
| AI | `AI_ENABLED` (off) and the other `AI_*` switches; the provider (`AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY_FILE`, `AI_MODEL`, `AI_VISION_MODEL`, …) and its network policy (`AI_PRIVATE_HOSTS`, `AI_DENY_CIDRS`, `AI_HTTP_PROXY`) are env only ([docs/ai.md](docs/ai.md#switches)) |
| Handbook | `HANDBOOK_DIR` (`/app/learn` in the image), `HANDBOOK_PUBLIC_URL` |

### What's new in detail

**Accounts and privacy**

* Local accounts (`AUTH_MODE=local`, the default): first admin from the setup code, invites by link,
  admin-created accounts with a one-time setup link, reset links, registration modes
  (invite / closed / open). Sign-in proxy mode (`AUTH_MODE=proxy`) needs a shared secret
  (`TRUSTED_PROXY_SECRET_FILE`) and can map an admin group; `AUTH_MODE=none` (one trusted device)
  shows a red banner.
* Passwords of 15–128 characters, checked against the 10,000 most common passwords and the account's
  names (NIST SP 800-63B), hashed with Argon2id (scrypt fallback). Throttling per account and per
  address (IPv6 per /64), instance-wide limits, a lock after 100 failures, re-entering the password
  for sensitive changes, forced password change.
* Opaque server-side sessions (`__Host-kh_session` over HTTPS; 30 days absolute, 14 idle), a list of
  signed-in devices with sign-out per device or everywhere; sign-out sends `Clear-Site-Data`.
* Every query is scoped to the signed-in person; someone else's data answers 404. Builtin foods are
  shared, custom foods are private, USDA and Open Food Facts rows are shared but visible only to
  whoever imported or scanned them. `GET /healthz` counts builtin foods only.
* **Export and deletion:** `Settings → Account` downloads everything you entered as a zip
  (`export.json`, `log.csv`, `foods.csv`, `meals.csv`, `labs.csv`, a README; also lab results, AI
  activity and "Not for me" foods; never passwords, sessions or keys). Deleting your account deletes
  all of it.
* An append-only activity log (sign-ins, invites, settings and key changes; ids only, never health
  data or secrets) for each person and for the admin.
* Admin CLI `python -m app.admin`: `create-admin`, `reset-password`, `list-users`, `setup-code`,
  `revoke-sessions`, `purge-pre-v3-backup`, `vacuum`, `backup`, `check`, `restore-check`,
  `rotate-secret-key`, `reencrypt`, `settings`, `remap-barcodes`, `purge-barcode-cache`.

**Settings and keys**

* One settings registry with a clear order (server environment → admin → person → default). Every
  setting in the UI says where its value comes from, and values set in the environment are locked.
* Keys are write-only: encrypted with Fernet under keys derived from `SECRET_KEY`, shown only as
  "ends in 9xQz" (for keys of 20 characters or more), never returned, logged or audited. A missing,
  unusable or exhausted key answers `503` with a reason the UI explains. `python -m app.admin
  rotate-secret-key` and `reencrypt` change the key without losing stored secrets.

**Security layer**

* Strict Content Security Policy with Trusted Types and no inline script or style, `X-Frame-Options:
  DENY`, `no-referrer`, COOP/CORP, `nosniff`, HSTS and `upgrade-insecure-requests` over HTTPS only,
  `Cache-Control: no-store` on the API. The handbook at `/learn` has its own policy that allows the
  theme's inline scripts by hash only.
* Host allowlist against DNS rebinding; `X-Forwarded-*` and identity headers only from
  `TRUSTED_PROXIES`; CSRF checks (`Sec-Fetch-Site`, `Origin`, required `X-Requested-With`); request
  body limits; validation errors never echo the submitted value; secrets are redacted from logs.
* Plain-HTTP sign-in from other machines is allowed only while a single account exists.
* Every outbound request (USDA, Open Food Facts, AI providers) goes through a transport that resolves
  the host on each request and refuses cloud-metadata, link-local, reserved and (unless the operator
  allowed it) private addresses, never follows redirects and caps the answer's size.

**Installable app and offline logging**

* Web app manifest, icons and a service worker that keeps the app shell for offline start over HTTPS
  (never `/api`), an "Update ready" prompt, and the `PWA_ENABLED=false` kill switch.
* **Offline outbox:** entries, quick adds and "mark all eaten" made without a connection are kept on
  the device (IndexedDB, per person), shown as "waiting to sync", and sent in order when the server is
  reachable; each carries a `client_id`, so a lost answer never creates a second row. Today, the last
  two weeks and the next week open from the device's saved copy; food search uses the foods the
  device has seen. A header badge shows what is waiting; Settings → This device lists it with Retry and
  Discard; signing out with entries waiting asks first.

**Personalised targets and lab results**

* Profile → About you: birth month, the sex used in medical formulas, activity, transplant date,
  frailty, weight 6 months ago, pregnancy, a history of high potassium, urine output and peritoneal
  dialysis details. All optional; only the birth month is asked, not the date.
* Suggestions combine the 2023 Dietary Reference Intakes with KDIGO, KDOQI and ADA ranges; each
  target has "Why this number?" (rule, source, grade, an "Expert opinion" badge for the project's own
  choices) and nothing is saved until you press Save profile. Protein for people with diabetes at
  stages 3a–5 before dialysis no longer goes below 0.8 g/kg (KDIGO 2022 and 2024, ADA 2026). The app
  does not suggest targets in pregnancy, under 18 or in the first 12 weeks after a transplant.
* **Lab results** (`#labs`, from Profile): potassium, phosphate, albumin, bicarbonate, urine
  albumin-to-creatinine ratio, creatinine, cystatin C, a lab-reported eGFR and HbA1c, in US or SI
  units with the conversion shown before saving and implausible values refused. Fresh results adjust
  the potassium and phosphorus suggestions (`targets.lab_rules_enabled`). Potassium of 6.0 mmol/L or
  more shows an urgent banner (6.5 or more: emergency) even with the lab rules off.
* **Kidney function card:** eGFR from creatinine with or without cystatin C (CKD-EPI 2021; cystatin C
  alone: CKD-EPI 2012) or the lab's value,
  the G and A categories, and whether they match the saved stage. It never changes the stage itself.
* Today shows goals (fiber "at least X") and ranges ("about X").

**Meal guidance**

* **What fits now** (Add view, and "What fits" under each meal on Today): the room left for the meal,
  foods by group with a portion and a reason, saved and usual meals that fit, and tips. "Not for me"
  hides a food from suggestions (Settings → Meal guidance lists them).
* **Swap ideas** under a potassium, phosphorus or sodium warning keep the carbohydrate the same, or
  offer a smaller portion ("the carbs change, so count the new amount").
* **Treating a low:** entries can be marked "Used to treat a low" (pre-ticked for low-treatment foods);
  such entries count toward potassium, phosphorus, sodium and fluid but never toward a meal's
  carbohydrate. The card and your low treatments at your dose are available from Today, even with
  guidance switched off and offline. Low treatments are never warned against, limited or sent to AI.
* **Plan the rest of my day** (Today, or Plan → "Plan a day…"): one option per open meal, "Show
  another", and "Use this plan" adds them as planned entries.
* **Insights** at the end of a day (Today) and for 7, 14 or 30 days (Trends), in plain words with
  numbers. Guidance computes only; nothing is written without a tap.
* Guidance never suggests alcoholic drinks: with insulin, alcohol can cause a low hours later (ADA
  Standards of Care 2026, §5). Builtin beers, wines and spirits carry a new `alcohol` flag, Open Food Facts
  and USDA alcoholic products get it on import, and anyone can set it on a custom food; it changes no
  warning, and a saved meal keeps its drink.
* Settings → Meal guidance: carbohydrate tolerance, low-treatment amount, categories to leave out, and
  switches for the plan builder, insights and AI ideas. Admins can switch guidance off for the server.

**Optional AI and photos** (off unless an admin turns it on)

* Presets for OpenAI, OpenRouter, Nous Portal, Ollama, LM Studio, llama.cpp, vLLM, LiteLLM, Hermes
  Agent (only a dedicated tool-free profile; the app checks) and any OpenAI-compatible server. The
  server-defined provider comes from the environment; admins can add shared providers, and people
  their own with their own key when allowed.
* Features: AI meal ideas and re-ordering inside "What fits now", AI picks among rule swaps and plans,
  "Describe a meal" (typed text split into searches of your food list), "Read a label" (a photo of a
  nutrition label becomes a draft custom food that you check and save) and "Plate photo" (names the
  foods on a plate; off by default).
* Guardrails: no free text from the model reaches you (fixed themes and reason codes, sentences from
  the app's own templates, claims checked against recomputed numbers); food ids only from the rule
  candidates; text that may describe a low gets the "Treating a low" card and red-flag symptoms a "Get
  help now" card **instead of** an AI call; no doses, no medicine advice, no AI nutrient estimates.
* Consent per person, provider, destination host and purpose (meal data and photos separately);
  "What will be sent?" shows the exact request; an AI activity list with "Delete my AI history"
  (bodies kept 30 days by default; admins see counts only); a shared daily limit per person.
* Photos are redrawn on the device (no location data) and checked and stripped of all metadata again on
  the server; they are never stored or logged.

**Barcodes and packaged foods**

* Add → **Scan**: live camera (needs HTTPS), a photo of a barcode, or typed digits (or a scanner that
  types). Decoding happens on the device with the browser's `BarcodeDetector` or the vendored ZXing
  WebAssembly reader, pinned by SHA-256 in `app/static/vendor/README.md`.
* Lookups: your own custom foods with that barcode first, then Open Food Facts (off by default; the
  admin turns it on, each person consents in Settings → Food data), then USDA FoodData Central branded
  foods (with a usable USDA key). Results are cached for the server, never with who scanned them.
* The food shows where its data came from (attribution and licence, the barcode, quality notes such as
  "potassium not listed", the additives found, the ingredient list). A missing potassium or phosphorus
  value reads "not listed", never 0.
* Ingredient lists are scanned for phosphate and potassium additives. A food with a potassium additive
  and no potassium value gets a **medium** warning ("contains a potassium additive; potassium not
  listed"). Quick add takes a barcode, an ingredient list and a label photo to read from.
* Not found: "Enter from the label" opens Quick add with the barcode, plus a link to add the product to
  Open Food Facts.

**The patient handbook at `/learn`**

* The image builds the handbook in a throw-away stage from the hash-locked
  `handbook/requirements.lock`; the app serves it at `/learn/` with no sign-in and no internet. A
  **Learn** entry (book icon) sits in the header and in Settings → About & privacy; warnings, alerts
  and target notes link to the page that explains them.
* Sections: Start here, Get help now, kidney disease and its stages, eating well (potassium,
  phosphorus, sodium, protein, fluid, carb counting, labels, menus and recipes), lab results, type 1
  diabetes with CKD (treating a low, sick days, insulin and dialysis), medicines, preparing for
  treatment, living well, using the app, and self-hosting. Fact-checked against primary sources
  (`handbook/REVIEW.md`); text under CC BY-NC-SA 4.0.
* `docs/diet-guide.md` moved into the handbook's "Eating well" pages. An opt-in workflow publishes a
  public copy to GitHub Pages (repository variable `HANDBOOK_PAGES`).

**Interface**

* Sign-in, first-run setup (with the Open Food Facts opt-in), invite, reset and new-password screens;
  a Settings view (account, preferences, food data, meal guidance, AI ideas, this device, admin, about
  & privacy) reached from the header gear. The theme and install panel moved from Profile to Settings.
* The frontend is split into plain scripts under one `window.KH` namespace with per-view stylesheets;
  no bundler, nothing loaded from a CDN. Every new control has a label, errors appear under the field
  at fault, and tap targets are at least 44 px.

**Deployment and supply chain**

* Image on Chainguard Python pinned by digest, with a Debian-based fallback
  (`deploy/Containerfile.debian`); amd64 and arm64.
* Rootless profiles with the same hardening: Quadlet unit and volume, compose (plus Caddy HTTPS and
  local Ollama overlays), a rootless Docker script, and Kubernetes manifests for Pod Security
  "restricted" with NetworkPolicy and an HTTPRoute; secrets as files everywhere.
* CI: pytest on Python 3.12 and 3.14, JS parity vectors, actionlint, hadolint, kubeconform,
  shellcheck, zizmor, CodeQL (public repositories), dependency review, an image smoke test, a Grype
  gate, and the handbook build with a browser check of `/learn`. Weekly jobs scan the published image,
  refresh the hash-locked dependencies, check the vendored barcode decoder and Open Food Facts'
  answers, and check the handbook's external links.
* Releases are built by digest, scanned, then signed and attested (SBOM, provenance) before any tag
  moves. Every action is pinned to a commit SHA; Python dependencies are hash-locked
  (`requirements*.lock`).
* Moved from `httpx` to `httpx2`; new runtime dependency `cryptography`. Schema changes are
  append-only steps in `app/migrations/` (steps 3–7 are new).
* Docs: [deployment](docs/deployment.md), [security](docs/security.md), [HTTPS](docs/https.md),
  [accounts](docs/accounts.md), [privacy](docs/privacy.md), [AI](docs/ai.md),
  [barcodes and photos](docs/barcode-and-photos.md), [meal guidance](docs/guidance.md),
  [targets and labs](docs/targets-and-labs.md), [network allowlist](docs/network-allowlist.md);
  every document is listed in [docs/README.md](docs/README.md).

**For contributors**

* [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [AGENTS.md](AGENTS.md),
  [docs/maintainers.md](docs/maintainers.md) (release process and repository settings),
  [docs/ROADMAP.md](docs/ROADMAP.md), issue and pull request templates.
* The demo (preview) mode runs as a signed-in demo admin; its copies of server logic are checked
  against the server by shared vector files (`node tests/js/run_vectors.mjs`) and by browser
  harnesses in `tools/e2e/` (`parity.py`, `sandbox.py`, `regress.py`, `learn.py`, `device.py`,
  `guidance_perf.py`).

### Security fixes from review

Found by the security reviews of the 0.3 design notes (`docs/dev/research/*`, "Security review"
sections) and of the pre-release code, including CodeQL. None of them affected a released version;
the code-review fixes affected only `:edge` builds.

* Removing an admin contains them: demoting, disabling or deleting an admin deletes every unused
  invite and reset/setup link they created; a password change or disabling voids the account's open
  reset links; Admin → People lists open links with who made them and a Revoke button.
* Sign-in floods: every refused sign-in counts toward the per-address block, one address may try 30
  sign-ins a minute, the instance-wide budget is taken only right before the hash, and waits no longer
  hold worker threads, so one client cannot lock everybody out or stall the app. IPv6 clients count
  per /64.
* Two admins removing each other at once can no longer leave the server without an admin; a reset
  link cannot be redeemed twice by racing requests.
* `AUTH_MODE=none`: deleting "your account" is refused (it would have removed user 1); a missing user 1
  is recreated at start-up and reported by `app.admin check`.
* The service worker ignores messages that do not come from the app's own origin; the USDA hourly
  guard is keyed by whose key it is, so no key material is handled outside the request.
* The optional breached-password check (`PASSWORD_BREACH_CHECK`) now goes through the same SSRF-checked
  transport as every other outbound call (no redirects, no proxy variables), and a test fails if any
  outbound client in the app is created without one.
* Safety review: meal guidance and AI ideas no longer offer alcoholic drinks (the new `alcohol` flag,
  above); the "no targets yet" message points to Profile, where targets are set.
* Barcodes: a shared product or cached answer is given only to someone who could fetch it now or
  already has it (no "someone scanned this" oracle); another person's custom food is never matched;
  product links are built from a constant, never copied from a provider's answer; provider text is
  cleaned of invisible and control characters before it is stored; ingredient lists never enter an AI
  prompt, and product names enter only as escaped data.
* AI: the model's own words are never shown (fixed codes and server templates instead), keys are never
  part of a person's settings object, the AI switches are environment-only with `AUTH_MODE=none`, and
  photos are rewritten without metadata and with size and dimension limits before they leave.
* Backups are written in rollback-journal mode and `restore-check` opens read-only files as immutable,
  so the documented restore works on a read-only mount.
* Deployment: rootless Docker with a same-host HTTPS proxy must trust the gateway address;
  podman-compose 1.5.0 or later; cosign 3 or later to verify images; Cilium Gateway needs an
  `ingress`-entity policy; Dependabot cannot update the `*.lock` files, so a weekly workflow refreshes
  them with a 7-day cooldown.

### Fixes from the release review

Found by the v0.3.0 review of the pre-release build; none affected a released version.

**Numbers and safety**

* **Values a food does not list are never shown as 0.** Today, Plan, Trends, the 7-day strip and the
  entry sheet say "≥ 55 mg · + 2 not listed" and "Not complete" when a logged food (often a scanned
  product) does not list potassium or phosphorus; meal ideas say "at most" and why. The server counts
  them per day, meal, range and period. Insights no longer call a day or period "all good" for a
  nutrient some foods do not list (a period insight says so instead), and compare two periods only
  when both have the values.
* **Guidance never suggests raw eggs.** The builtin "Egg white, raw" is now "Egg white" with a cooking
  note, and "Egg, whole, raw" is a recipe ingredient that guidance never offers on its own
  (`data/foods.json` 2026-10-07.2).
* AI ideas, saved meals and usual meals are scaled down to what is left of the day, so they never tip
  potassium, sodium or fluid over the day's limit.
* The "better low treatment" insight says the portion it means ("5 × 1 tablet, 20 g carbs").
* The low-glucose pre-filter (which answers with the "Treating a low" card instead of AI) catches more
  phrasings: past tenses and CGM wording ("sugar dropped", "cgm says 3,4"), bare readings ("I'm at
  58", "down to 61") and glucose units; kitchen amounts such as "sugar 2 tsp" are not readings.
* Target notes: the calorie note always states the calorie target it explains; the potassium note no
  longer says "relaxed one step" when nothing was relaxed; the low-BMI note names its age-70 cut-off.
  Lab dates in notes, alerts and the kidney-function card read "Oct 7, 2026", like the history.

**Targets and guidance in the app**

* **Guidance says which targets it used** ("Using the targets in your profile, saved …", with a link to
  Profile) in What fits now and the plan.
* **Snack carbohydrate goal:** Profile → *Carbohydrate per snack* (from your diabetes team); Today, its
  alerts and meal ideas use it for the snack.
* "About" targets (the same minimum and maximum, such as protein "about 56 g") read *Near target* /
  *Above target*, never "limit".
* The red very-high-potassium banner follows the admin's lab freshness setting, like the suggestion.
* The fiber target's note, Lab results and an Open Food Facts quality note say "fiber", like the rest of
  the app (they said "fibre").
* An impossible transplant date (such as 2026-02-30) is refused in the app's own words on every Python
  version (Python 3.14, the image's, words its date errors differently), and the demo says the same.

**Barcodes and packaged foods**

* With Open Food Facts switched on but your agreement not given yet, a product only Open Food Facts
  knows now opens the agreement panel instead of answering "not found"; "not found" names only the
  databases that answered so.
* Products with values only "as prepared" are logged in servings (no grams field, and the reason); a
  label given per serving without the serving's weight asks you to enter the food from the label
  instead of storing the values as per 100 g.
* Salt substitutes (potassium chloride) keep their real potassium value and warn high: the plausibility
  limits are now 60 g potassium and 32 g phosphorus per 100 g. Drinks labelled per 100 mL count as
  fluid. The bare word "phosphorus" in an ingredient list is no longer read as a phosphate additive.
* Scanning starts the camera when Scan opens (HTTPS only; switch it off in Settings → Food data).
* `GET /api/foods/builtin` with an ETag: a device refreshes its offline food list only when it changed.

**AI and photos**

* Photo uploads are refused (AI off, too large, no consent, no free slot) before the photo is read, and
  an upload slower than 60 seconds stops with `408 upload_timeout`: many uploads at once no longer
  hold hundreds of megabytes.
* The AI guard keeps a "low in potassium / phosphorus / sodium" reason only when every portion is low
  by the app's own per-portion threshold, and never shows a wider list of words (shot, pen, skip or
  delay, pills and medicines, binder brands, "extra", "more" or "double" as advice).
* A label photo marks the serving as read from the photo, or as estimated when it falls back to 100 g.
* The AI activity list captions the provider's raw answer as unchecked and hides words the app never
  shows; AI order, Ask AI to pick and Let AI choose each have *What will be sent?* and say which picks
  the rules left out; the same question within 10 minutes is answered again without a new call or a
  daily call spent.
* AI activity bodies are cleared on schedule by the app's daily housekeeping, also while AI is off or
  unused; AI servers on internationalised domain names are checked, resolved and pinned by their ASCII
  form.

**Installable app, settings and admin**

* Every API answer carries `X-KDL-Version`: a page still running an older cached app shell offers
  *Update ready · Reload* after its first request.
* iPhone and iPad show the Home Screen steps once, after the third visit.
* Settings → This device no longer draws twice on a first visit, says once whether the app is
  installed and works offline, and no longer mentions reminders (they come with Web Push in v0.4);
  the AI switches have their own group in Admin → Server settings and refresh the AI panel at once;
  the *Server name* help says where the name is shown; the demo runs with lab rules off (note 05).
* The first-run setup line never prints an `https://` address the server cannot know (it uses
  `PUBLIC_URL` when set).
* Admin CLI: `python -m app.admin export-user` (the same zip as the web export) and `disable-user`.

**Handbook and documentation**

* Link and header colours meet WCAG AA contrast in the light scheme; Learn links are at least 24 px tall
  (44 px on touch screens); the dead DG47 citation is replaced (American Kidney Fund Kidney Kitchen,
  Satellite Healthcare); the mmol/L phosphate table gives the edges the app uses.
* The research notes in `docs/research/` carry a "superseded in part by design note 05" banner, with
  the protein rows (0.8 g/kg with diabetes), the published KDOQI numbering and the weight basis
  corrected.

### Known limitations

* **The handbook is a draft.** Every page shows "Draft: not yet reviewed by a clinician" until a named
  reviewer signs it off; the open questions for clinicians are listed in `handbook/REVIEW.md`. The
  rules marked "Expert opinion" in the target suggestions, the meal guidance's per-meal caps and score
  weights, and the potassium-additive rule (medium rather than high) are also awaiting review by a
  renal dietitian or nephrologist. Keep `targets.lab_rules_enabled` off on a public demo server until
  then.
* **No AI model is recommended yet.** The AI features were tested against fake providers through the
  real network code, not against live Ollama, OpenAI, OpenRouter or Hermes servers; the reference
  evaluations (`scripts/ai_eval.py`) still have to be run. Hermes Agent's tool check follows its
  documented API and was not tried against a live agent.
* **Not yet tried on real phones.** Installing, the live camera, photo decoding, HEIC photos and the
  offline outbox were checked in Chromium (fake camera, emulated offline), not on an iPhone or Android
  device. The live camera needs HTTPS; over plain HTTP use a photo of the barcode or type it.
* **A meal alert has no tolerance yet.** A planned meal the plan calls "close to your goal" (within your
  carbohydrate tolerance) can still show "Projected over" on Today by a fraction of a gram, and an "about"
  target reads *Above target* just over its number: no cited guideline gives a tolerance, so it waits for
  the clinical review (`handbook/REVIEW.md`, "Food targets").
* **Offline is for new entries only.** Edits, deletions, profile and settings changes, barcode
  lookups, AI and new guidance answers need a connection (the "Treating a low" card still works);
  handbook pages at `/learn` are not kept for offline use.
* **Raspberry Pi speed is estimated, not measured.** Guidance requests take 26–42 ms (p95) on an x86
  cloud machine and the browser copy stays under its 200 ms budget with the CPU slowed down 4×, but
  `scripts/bench_guidance.py` has not been run on a real Raspberry Pi 4 or 5. If a Pi 4 is too slow,
  lower `GUIDANCE_POOL_PER_ROLE` ([docs/guidance.md](docs/guidance.md#performance)).
* **Signatures need a public repository.** Release signing, provenance and SBOM attestations, and CodeQL
  run only while the GitHub repository is public; `scripts/verify-image.sh` fails for an image
  released while it was private.
* English only; one SQLite file per server; no reminders or push notifications; no OIDC or passkeys
  yet ([docs/ROADMAP.md](docs/ROADMAP.md) lists what is planned).

## 0.2.0 — 2026-10-05

First release.

* Food log with a 395-food builtin database from USDA SR Legacy, custom foods and quick add from a
  label, per-serving warnings and kidney ratings, daily targets and status bars, suggested targets
  by CKD stage and dialysis mode, USDA lookup, CSV export, an optional HTTP Basic password, one
  container with one SQLite file. (Schema steps 1 and 2 are the "v0.1" and "v0.2" layouts of the
  development history; a v0.1 database still upgrades in place.)
* Meal planning: planned entries, projected totals and alerts, "Eaten" and "Mark all eaten", a
  7-day Plan grid, copy day; saved meals (templates) with apply and scaling; a shopping list.
* Weekly / period summaries and interdialytic totals for hemodialysis days; dialysis days and
  week start in the profile.
* After the release: a self-contained preview build of the UI with a demo API that matches the
  server (`scripts/build_preview.py`).
