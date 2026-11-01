---
title: Configuration
description: "Every environment variable kidney-health reads, with defaults: network, secrets, sign-in, proxy mode, food data, AI, guidance and the handbook."
slug: configuration
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-31
fact_checked: 2026-10-05
sources: [NOTE01, NOTE03, NOTE04, NOTE06, NOTE07, NOTE08, NOTE12, NOTE17, NOTE27, NOTE28, WHOOP-API, NOTE30, NOTE20, DEPLOY, SECDOC, NIST-63B4, FDC-API, OFF-API]
---

# Configuration

kidney-health reads its configuration from environment variables once, at start-up. A wrong value stops
the app with a message that names the variable; it never starts half-configured
([design note 01][NOTE01]).

## Rules that apply to every variable

- **Where to set them:** `Environment=` lines in the Quadlet unit, `deploy/.env` for compose, or `env:`
  in the Kubernetes Deployment ([deployment guide][DEPLOY]).
- **Secrets are files.** Every secret has a `NAME_FILE` form that points to a file (a Podman secret,
  compose `secrets:`, a Kubernetes Secret volume). Setting both `NAME` and `NAME_FILE` is a start-up
  error; an empty file means "unset"; trailing newlines are ignored. Environment variables leak through
  `inspect` output and crash dumps, so use files ([operator security guide][SECDOC]).
- **Set by the server means locked.** A setting given here shows in the app as "Set by the server" and
  cannot be changed in **Settings** ([design note 07][NOTE07]), unless you list it in
  `SETTINGS_INITIAL_ONLY` ([below](#set-it-up-by-code)).
- Booleans accept `true/false`, `1/0`, `yes/no`, `on/off`.

## Address and network

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_URL` | unset | The address people type, scheme included, for example `https://food.home.example.net`. Its host passes the Host check, browsers' `Origin` must match it, and invite and reset links use it. **Set it whenever you use a host name.** |
| `ALLOWED_HOSTS` | localhost, IP literals and the `PUBLIC_URL` host | Extra host names (comma list; `*.example.org` wildcards). Any other `Host` gets `400 Unknown host` (DNS-rebinding defense). |
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Addresses whose `X-Forwarded-For` and `-Proto` are believed. Depends on your engine ([Security](security.md)). `FORWARDED_ALLOW_IPS` is ignored. |
| `MAX_BODY_BYTES` | 1 MiB | Largest JSON request. |
| `MAX_IMAGE_BYTES` | 4 MiB | Largest photo upload (v0.3 photo features). |
| `HSTS_MAX_AGE` | 31536000 | Sent only over HTTPS; `0` turns HSTS off. |
| `ENABLE_API_DOCS` | `false` | Serves `/docs`, `/redoc` and `/openapi.json` (alias `DOCS_ENABLED`). For a development machine only: they answer without a sign-in and load scripts from a CDN. |
| `PWA_ENABLED` | `true` | `false` is the kill switch for the offline service worker. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Secrets are redacted either way. |
| `DATA_DIR` | `/data` in the image, `./data-local` outside | Where `kidney.db` lives. |
| `FOODS_JSON` | the image's `data/foods.json` | The builtin food list. |

## Secrets

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY_FILE` | auto-generated `$DATA_DIR/secret.key`, with a warning | Encrypts stored API keys. One key per line, at least 32 characters; the first line is current. Mount it from the engine's secret store, **outside** the data volume ([Backups](backups.md)). |
| `USDA_API_KEY_FILE` | unset | The shared USDA FoodData Central key; enables "Search USDA" (free key; `DEMO_KEY` allows 30 requests an hour) ([USDA][FDC-API]). |

## Sign-in and accounts

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_MODE` | `local` | `local`: accounts with passwords. `proxy`: identity from your reverse proxy. `none`: no sign-in; everything is one admin user and a red banner says so. |
| `ADMIN_USERNAME` + `ADMIN_PASSWORD_FILE` | unset | First run only: create the admin from a file instead of the setup code (GitOps). Ignored once an admin exists. |
| `APP_PASSWORD_FILE` | unset | **Deprecated** (v0.2 HTTP Basic). On the first v0.3 start with no admin it becomes the admin's password; then it is ignored. |
| `SETUP_CODE_TTL_MINUTES` | 60 | Lifetime of the first-run setup code (5–1440). |
| `SESSION_IDLE_DAYS` / `SESSION_MAX_DAYS` | 14 / 30 | Sign-in lifetime (1–30 each). |
| `REAUTH_MINUTES` | 10 | How long a password re-entry unlocks sensitive actions. |
| `BACKUP_REMINDER_DAYS` | 7 | Server administration reminds an admin when the last backup is older than this (0–365; `0` turns it off). See [Backups](backups.md). |
| `PASSWORD_MIN_LENGTH` | 15 | 8–64. Below 15 logs a warning: 15 is the NIST minimum for a password used alone ([NIST][NIST-63B4]). |
| `PASSWORD_BREACH_CHECK` | `false` | `true` checks new passwords against Have I Been Pwned (5 hash characters leave the server). |
| `PASSWORD_HASH` | `argon2id` | `scrypt` only where Argon2id is unavailable. |
| `LOGIN_IP_MAX_FAILURES` | 20 | Failed sign-ins per address per 10 minutes before a 10-minute block. |
| `ALLOW_INSECURE_HTTP` | automatic | Plain-HTTP sign-in from other machines is allowed while one account exists and refused from the second. |
| `INSTANCE_NAME` | `Kidney Health` | Shown in the app. |
| `REGISTRATION_MODE` | `invite` | `invite` (single-use links), `closed` (admin creates accounts), `open` (anyone who reaches the page; HTTPS required). |
| `AUDIT_RETENTION_DAYS` | 365 | How long security events are kept. |
| `USDA_SHARED_DAILY_LIMIT` | 200 | Shared-key USDA lookups per person per day (0 = unlimited). |

## Proxy sign-in (`AUTH_MODE=proxy`)

| Variable | Purpose |
|---|---|
| `TRUSTED_PROXY_USER_HEADER` | The identity header your proxy sets, for example `Remote-User`. Required. |
| `TRUSTED_PROXY_SECRET_FILE` | A long random value your proxy sends as `X-Proxy-Secret`. **Required**: without it the app refuses to start. |
| `TRUSTED_PROXY_SECRET_OPTIONAL` | `true` only for `tailscale serve`, which cannot add headers; logged as a warning. |
| `TRUSTED_PROXY_GROUPS_HEADER`, `TRUSTED_PROXY_ADMIN_GROUP` | Members of the admin group become admins. |
| `TRUSTED_PROXY_NAME_HEADER` | Display name. |
| `PROXY_AUTO_CREATE_USERS` | `false`: the admin creates each account first. |
| `PROXY_LOGOUT_URL` | Where "Sign out" goes. |

Proxy mode refuses to start if `TRUSTED_PROXIES` contains `0.0.0.0/0` or `::/0`
([design note 07][NOTE07]).

## Food data

| Variable | Default | Purpose |
|---|---|---|
| `OFF_ENABLED` | `false` | Barcode lookups contact Open Food Facts. The admin can also switch it on in Settings or on the setup screen. |
| `OFF_CONTACT` | the project URL | Goes in the User-Agent, as Open Food Facts asks ([Open Food Facts][OFF-API]); an email address is better. |
| `OFF_BASE_URL` | `https://world.openfoodfacts.org` | Env only (never editable in the app); `https://` required. |
| `OFF_RATE_PER_MINUTE` | 10 (at most 15) | Server-wide lookup pace. |
| `BARCODE_NEGATIVE_TTL_HOURS` | 24 | How long "not found" is remembered. |
| `USDA_BRANDED_BARCODE` | `true` | Also look barcodes up in USDA FoodData Central (needs a USDA key). |

Each of these except `OFF_BASE_URL` is also a server setting an admin can change in **Settings**; setting
the variable locks it. Each person still decides whether their own scans go to Open Food Facts
(**Settings → Food data**).

([design note 03][NOTE03])

## AI

| Variable | Default | Purpose |
|---|---|---|
| `AI_ENABLED` | `false` | Master switch (also **Server administration → Server settings**). While off, every AI route answers "not found" and nothing is sent anywhere. |
| `AI_PROVIDER`, `AI_BASE_URL`, `AI_MODEL` | unset | The server's shared provider: a preset (`openai`, `openrouter`, `nous_portal`, `ollama`, `lmstudio`, `llamacpp`, `vllm`, `litellm`, `hermes`, `openai_compatible`). Admins can add more in **Settings → AI features**. |
| `AI_API_KEY_FILE` | unset | The shared provider's key (`AI_API_KEY` also works; `OPENAI_API_KEY_FILE` for `openai`). Never stored in the database. |
| `AI_VISION_MODEL` | empty | Set it to enable label and plate photos. |
| `AI_PROVIDER_ROLE` | unset | `local` or `cloud`: which role the `AI_PROVIDER` provider has. `local` needs a private host (listed in `AI_PRIVATE_HOSTS`, a name by name) and is checked at start-up. Each AI feature (photos, meal ideas, describing a meal, Ask) uses the local or the cloud AI, whichever you pin it to; the default is local, so a feature stays off until a local AI exists. |
| `AI_CLOUD_PROVIDER`, `AI_CLOUD_BASE_URL`, `AI_CLOUD_MODEL`, `AI_CLOUD_VISION_MODEL` | unset | A second shared provider that is **always the cloud AI**, set the same way as `AI_PROVIDER` (any preset except `hermes`). With it set, `AI_PROVIDER_ROLE` must be `local`, and the cloud role cannot be changed in the app. It may sit on your LAN (a LiteLLM proxy with a cloud-only key); it is then listed in `AI_PRIVATE_HOSTS` too, and the start stops if it is not. Lab report photos never go to it. |
| `AI_CLOUD_API_KEY_FILE` | unset | Its key (`AI_CLOUD_API_KEY` also works). Never stored in the database. |
| `AI_CLOUD_UPSTREAM` | unset | **Required** when the cloud AI is a server you run (`litellm`, `vllm`, `openai_compatible` and the other non-cloud presets): the plain name of the company it forwards to, for example `Anthropic`. People are told "Goes through your admin's LiteLLM proxy to Anthropic. Anthropic receives what is sent, under its own terms; your admin can read it too." A new name asks everyone again. Ignored, with a warning, for `openai`, `openrouter` and `nous_portal`. |
| `AI_CLOUD_TIMEOUT_S`, `AI_CLOUD_MAX_TOKENS`, `AI_CLOUD_CONTEXT_TOKENS`, `AI_CLOUD_STRUCTURED_OUTPUT`, `AI_CLOUD_REASONING_EFFORT` | the preset's, `1500`, `32768`, `auto`, the preset's | Like the `AI_` variables of the same name. The prompt budget is 32,768 tokens even for a self-hosted preset such as `litellm`. |
| `AI_ROUTE_RECIPES` | unset (`local`) | AI recipes, which send a recipe's foods and amounts (never its name, note, steps or link). The same values as `AI_ROUTE_MEAL_IDEAS`. |
| `AI_RECIPE_STEPS` | `false` | Cooking steps written by AI in AI recipes. Leave it off until a live run of `scripts/ai_eval.py` on your model shows no unsafe step. |
| `AI_ROUTE_LABS` | unset (`local`) | Reading a photo of a lab report: `local` or `off` only (`cloud` and `any` stop the start): a report can show a name and a date of birth, so it is read only by your local AI and is off without one. |
| `AI_ROUTE_PHOTOS`, `AI_ROUTE_MEAL_IDEAS`, `AI_ROUTE_DESCRIBE`, `AI_ROUTE_CHAT` | unset (`local`) | Pin a feature to `local`, `cloud`, `off` or `any` (the older rule: whichever shared provider a person chose). Photos, meal ideas and describing a meal also take `local_then_cloud`: the local AI first, and the cloud AI only when the local answer fails the schema or the app's rules (never when the local AI is unreachable, slow, over quota or declines; only for people who agreed to the cloud host); Ask does not (a value of `local_then_cloud` for `AI_ROUTE_CHAT` stops the start). Leave empty to choose in **Server administration → AI providers → Which AI does each feature use?**; a value here locks the choice. A server that already had a provider keeps `any` until an admin chooses. |
| `AI_PERSON_ROUTE_CHOICE_ENABLED` | `false` | Lets the people you tick in **Server administration → Users** (**May choose the server's local or cloud AI**) pick, for each AI feature, your local AI or your cloud AI in Settings → AI features. A feature you set to `off` stays off, and lab report photos always stay on the local AI. Off: everyone uses your routing. |
| `AI_EVAL_REPORTS_DIR` | unset | A folder, mounted read-only, with the `*.json` reports that `scripts/ai_eval.py` writes. **Server administration → AI providers → How well each AI is doing** then says, for each feature that is on, whether the model it uses passed the evaluation for the current prompts, and the start-up log warns about each one that failed or has no report. Unset: the screen says there is no reports folder. Mount the folder with `Volume=...:ro` (Quadlet), `volumes:` (compose) or a read-only `volumeMount` (Kubernetes); see the [AI guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/ai.md#how-well-each-ai-is-doing). |
| `AI_PRIVATE_HOSTS` | empty | `host:port` list that **shared** providers may reach on private addresses, for example `ollama:11434`. No wildcard; the old `ALLOW_PRIVATE_AI_HOSTS` is refused. |
| `AI_DENY_CIDRS` | empty | Addresses AI calls may never reach: add your own public (WAN) address. |
| `AI_ALLOW_USER_KEYS` / `AI_ALLOW_USER_BASE_URL` | `true` / `false` | Whether people may add their own key, or their own (public, HTTPS, port 443) address. |
| `AI_SHARED_DAILY_LIMIT` | 30 | Shared AI calls per person per day (photos and connection tests count). |
| `AI_MAX_CONCURRENCY` | 2 | AI calls at the same time on the whole server (one per person). |
| `AI_AUDIT_RETENTION_DAYS` | 30 | How long request and response bodies are kept (0 = metadata only). |
| `AI_VISION_PLATE_ENABLED` / `AI_VISION_ALLOW_AGENT` | `false` / `false` | Plate photos; photos to a Hermes agent (which must also pass its tool check before every photo). |
| `AI_CHAT_ENABLED` | `false` | The **Ask** chat (also **Server administration → Server settings**): needs AI on; people who opted in get an Ask tab where the AI looks up their own numbers and the app checks every answer. One question can use up to 7 AI calls, each counted in the daily limit. While off, the Ask tab is not shown. |
| `AI_VOICE_ENABLED` | `false` | The Ask **microphone** (also **Server administration → Server settings**): needs Ask on and a transcription server (`STT_BASE_URL`). While off, there is no microphone. |
| `STT_BASE_URL`, `STT_MODEL`, `STT_API_KEY_FILE` | unset | The speech-to-text server for the microphone: one OpenAI-compatible server (a local container such as `deploy/compose.stt-whisper.yaml`, or a cloud service), its model name and, if it wants one, its key as a file. A server on your network must be listed in `AI_PRIVATE_HOSTS`, like an Ollama host. Recordings are turned into text and deleted, never stored. `STT_TIMEOUT_S` (60), `STT_DAILY_LIMIT` (100 per person per day) and `STT_MAX_AUDIO_BYTES` (1.5 MiB) tune it. |
| `AI_HTTP_PROXY` | unset | Explicit egress proxy; `HTTP(S)_PROXY` is ignored for AI on purpose. |
| `ASSISTANT_ENABLED` | `false` | Assistant access (also **Server administration → Server settings**): each person may make personal tokens for a chat assistant that reads their own food log and targets and, if the person ticks "Can also save food and recipes" for that token, saves food and recipes, and, if the person ticks "Also let it remember tastes" for that token, remembers likes and dislikes (at most 30 changes a day per token; never anything about treating a low). While off, no token works and none can be made. |

Also `AI_TIMEOUT_S`, `AI_VISION_TIMEOUT_S` (120), `AI_MAX_TOKENS` (1500), `AI_STRUCTURED_OUTPUT` (`auto`),
`AI_REASONING_EFFORT`, `AI_CONTEXT_TOKENS`, `AI_MAX_RESPONSE_BYTES`, `AI_OPENROUTER_ZDR` and `MAX_IMAGE_BYTES`
([design note 04][NOTE04]). Setup recipes (Ollama next to the app, Kubernetes, a dedicated tool-free Hermes
Agent profile, OpenAI, OpenRouter), the address rules and troubleshooting are in the repository's
[AI guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/ai.md).

## Phone shortcuts

| Variable | Default | Purpose |
|---|---|---|
| `PUSH_ENABLED` | `false` | Phone shortcuts (also **Server administration → Server settings**): each person may make device tokens (**Settings → Account → Your data → Phone shortcuts**) for an iPhone Shortcut that adds their weight and blood pressure to their own log at `POST /push/v1/body`. A token can only add; it reads nothing. While off, the route answers `401` to everyone. The phone must reach the server (home network or your VPN); if a reverse proxy lists the paths it passes on, add `/push/v1/`. Nothing leaves the server for it ([design note 12][NOTE12]; [From a phone shortcut](../app/weight-and-blood-pressure.md#from-a-phone-shortcut)). |
| `TOKENS_ALLOW_NEVER_EXPIRING` | `true` | Whether people may choose "Never (until you remove it)" when making a token for an outside AI app or a phone shortcut (also **Server administration → Server settings**). Off: every new token expires; tokens made before keep working until revoked. |
| `DEVICES_ENABLED`, `DEVICES_SYNC_HOURS` | `false`, `4` | Connected devices (also **Server administration → Server settings**): each person may connect their own Withings scale or blood pressure monitor, or their Whoop strap, in **Settings → Connected devices**, and the server fetches their data every few hours. Nothing about the person is sent to Withings or Whoop ([design note 27][NOTE27]; [From a Withings scale or monitor](../app/weight-and-blood-pressure.md#from-withings)). |
| `WITHINGS_ENABLED`, `WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET_FILE` | off | Your free Withings developer app. Its return address is `<PUBLIC_URL>/api/devices/withings/callback`; the client secret only as a file. The server then talks to `wbsapi.withings.net`. Step-by-step setup in the repository's [devices guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/devices.md). |
| `WHOOP_ENABLED`, `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET_FILE` | off | Your Whoop developer app (up to 10 Whoop members without Whoop's approval). Its return address is `<PUBLIC_URL>/api/devices/whoop/callback`; the client secret only as a file. The server then talks to `api.prod.whoop.com`. Same [devices guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/devices.md); Whoop's own [developer documentation][WHOOP-API]; [design note 28][NOTE28]. |
| `LIST_SYNC_ENABLED` | `false` | Your own list app (also **Server administration → Server settings**): each person may add their own Grocy, KitchenOwl or Mealie in **Settings → Shopping list app** and send the Plan's shopping list to it. Only the foods' names and amounts are sent ([design note 30][NOTE30]; [Send it to your own list app](../app/planning-and-menus.md#send-it-to-your-own-list-app)). |
| `LIST_SYNC_ALLOWED_HOSTS` | empty | The home addresses a list app may be on: host names, addresses or networks, comma-separated (`grocy.lan,192.168.1.0/24`). Every other private address is refused, cloud metadata addresses always; plain `http` only to these; redirects never followed. Env only. Behind an outbound proxy, put them in `NO_PROXY` too. Setup in the repository's [list app guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/list-sync.md). |
| `RECIPE_IMPORT_ENABLED` | `false` | Recipe pages (also **Server administration → Server settings**): a person may paste a recipe page's link in **Plan → Import a recipe**, and the server opens that page from the internet (never a private address; at most 2 MiB, 15 seconds, 3 redirects) and keeps only the link. Pasting the ingredients works without it ([Import a recipe](../app/planning-and-menus.md#import-a-recipe)). |
| `OIDC_ENABLED`, `OIDC_PROVIDERS`, `OIDC_ONLY` | `false`, empty, `false` | Sign in with Authentik, Google or another provider, up to four at once, and optionally only with them. See [Accounts and keys](users-and-keys.md#sign-in-with-authentik-or-google) and the operator guide for every variable. |
| `AUTH_REQUIRE_TWO_STEP_ADMINS` | `false` | Admins must use two-step sign-in (also **Server administration → Server settings**): an admin opens Server administration only after turning it on in **Settings → Account → Two-step sign-in**. You can switch it on there only once your own two-step sign-in is on. No effect with a sign-in proxy ([design note 17][NOTE17]). |

## Meal guidance

`GUIDANCE_ENABLED` (`true`), `GUIDANCE_POOL_PER_ROLE` (200), `GUIDANCE_BEAM_WIDTH` (16)
([design note 06][NOTE06]).

## The handbook at `/learn`

| Variable | Default | Purpose |
|---|---|---|
| `HANDBOOK_DIR` | `/app/learn` in the image; `handbook/site` in a checkout | The built handbook, served at `/learn/` with no sign-in. Without an `index.html` there, `/learn` answers 404 and the app's **Learn** links go to `HANDBOOK_PUBLIC_URL`, or are hidden when that is not set. |
| `HANDBOOK_PUBLIC_URL` | empty | A published copy (for example on GitHub Pages), `https://` or `http://` only: where the Learn links go when this server has no handbook, and the "public copy" link in **Settings → About**. |

The image builds the handbook in a separate stage, so it needs no internet at runtime
([design note 08][NOTE08]; [Building the handbook](building-the-handbook.md)). The app reads the site
once when it starts, to compute the handbook's security policy, so restart it after rebuilding the
handbook in place. A broken build (a page that is not UTF-8, or far more inline scripts than the theme
uses) is not served: the log says why, and the food log itself keeps working. To serve the handbook
from its own host name instead, see [Security](security.md#serving-learn-from-its-own-origin-optional)
and the [operator security guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/security.md#the-handbook-at-learn-its-own-policy-and-its-own-origin).

## Set it up by code

Every setting in **Server administration → Server settings** has a variable, so a script or an AI agent
can set a server up with no clicks. With `ADMIN_USERNAME` and `ADMIN_PASSWORD_FILE` the first admin is
made from a file too ([Users and keys](users-and-keys.md)).

A variable locks its setting. To give only a **first value**, list the variable in
`SETTINGS_INITIAL_ONLY` (a comma list, or `*` for all). On the first start that sees it, the server
writes the value and notes it in the activity log. After that an admin can change it in the app, and a
restart keeps their choice; changing the variable later does nothing ([design note 20][NOTE20]).

| Variable | Default | Purpose |
|---|---|---|
| `SETTINGS_INITIAL_ONLY` | empty | The variables that are first values, not locks. A name that is not a setting's variable stops the start. |
| `INSTANCE_NAME`, `REGISTRATION_MODE`, `INVITE_TTL_DAYS`, `AUDIT_RETENTION_DAYS` | Kidney Health, `invite`, 7, 365 | The server's name, who may make an account, how long an invite link works, how long the activity log is kept. |
| `USDA_SHARED_ENABLED`, `USDA_ALLOW_USER_KEYS`, `USDA_SHARED_DAILY_LIMIT` | `true`, `true`, 200 | The server's USDA key: shared or not, people's own keys allowed or not, searches per person per day. |
| `LAB_RULES_ENABLED`, `LAB_FRESH_DAYS_POTASSIUM`, `_PHOSPHATE`, `_ALBUMIN`, `_BICARBONATE`, `DEFAULT_ACTIVITY` | `true`, 90, 90, 180, 180, `inactive` | Whether lab results change suggested targets, how long each result counts, and the activity level used until a person picks theirs. |
| `UI_THEME`, `LAB_UNITS`, `WEIGHT_UNITS` | `system`, `us`, `lb` | The theme and units for people who have not picked their own. A lock stops people picking, so list these in `SETTINGS_INITIAL_ONLY`. |

`python -m app.admin env-template` prints all of these as a `.env` file to fill in, with each one's values and
default (`--initial-only` starts it with `SETTINGS_INITIAL_ONLY=*`). Run `python -m app.admin check` in the container
before the first start: it stops on any mistake and
lists which settings are locked and which are first values. Each person's own choices, like their
targets and whether they use AI, stay theirs to make in the app.

## Example: Quadlet behind Caddy on the same host

```ini
Environment=SECRET_KEY_FILE=/run/secrets/secret_key
Environment=PUBLIC_URL=https://food.home.example.net:8443
Environment=TRUSTED_PROXIES=<address>          # the peer address the app's log shows for Caddy
Environment=AUTH_MODE=local
```

## If something goes wrong

- **The app exits at start with a message naming a variable**: fix that variable; the message says how.
- **`SECRET_KEY_FILE points to ..., which does not exist`**: create the secret, or fix its file mode.
- **A setting is grayed out in the app**: it is set here; change it here and restart, or list it in
  `SETTINGS_INITIAL_ONLY` to make it a first value.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Users and keys](users-and-keys.md) · [Security](security.md) · [Network allowlist](network-allowlist.md) · [HTTPS for phones](https.md)

## Sources

- [Design note 01][NOTE01] §5.5 and [design note 07][NOTE07] §4.3: the variables and their rules.
- [Design note 03][NOTE03] R10; [design note 04][NOTE04] R4; [design note 06][NOTE06] §4.14; [design note 08][NOTE08] §4.6.
- [Design note 12][NOTE12] §4.4: the `PUSH_ENABLED` switch.
- [Design note 20][NOTE20]: first values from the environment.
- [Deployment guide][DEPLOY]; [operator security guide][SECDOC].
- [NIST SP 800-63B-4][NIST-63B4]; [USDA FoodData Central API guide][FDC-API]; [Open Food Facts API][OFF-API].
