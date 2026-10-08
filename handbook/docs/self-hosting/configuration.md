---
title: Configuration
description: "Every environment variable kidney-health reads, with defaults: network, secrets, sign-in, proxy mode, food data, AI, guidance and the handbook."
slug: configuration
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [NOTE01, NOTE03, NOTE04, NOTE06, NOTE07, NOTE08, DEPLOY, SECDOC, NIST-63B4, FDC-API, OFF-API]
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
  cannot be changed in **Settings** ([design note 07][NOTE07]).
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
| `ENABLE_API_DOCS` | `false` | Serves `/docs` and `/openapi.json` (alias `DOCS_ENABLED`). |
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
| `AI_PROVIDER`, `AI_BASE_URL`, `AI_MODEL` | unset | The server's shared provider: a preset (`openai`, `openrouter`, `nous_portal`, `ollama`, `lmstudio`, `llamacpp`, `vllm`, `litellm`, `hermes`, `openai_compatible`). Admins can add more in **Settings → AI ideas**. |
| `AI_API_KEY_FILE` | unset | The shared provider's key (`AI_API_KEY` also works; `OPENAI_API_KEY_FILE` for `openai`). Never stored in the database. |
| `AI_VISION_MODEL` | empty | Set it to enable label and plate photos. |
| `AI_PRIVATE_HOSTS` | empty | `host:port` list that **shared** providers may reach on private addresses, for example `ollama:11434`. No wildcard; the old `ALLOW_PRIVATE_AI_HOSTS` is refused. |
| `AI_DENY_CIDRS` | empty | Addresses AI calls may never reach: add your own public (WAN) address. |
| `AI_ALLOW_USER_KEYS` / `AI_ALLOW_USER_BASE_URL` | `true` / `false` | Whether people may add their own key, or their own (public, HTTPS, port 443) address. |
| `AI_SHARED_DAILY_LIMIT` | 30 | Shared AI calls per person per day (photos and connection tests count). |
| `AI_MAX_CONCURRENCY` | 2 | AI calls at the same time on the whole server (one per person). |
| `AI_AUDIT_RETENTION_DAYS` | 30 | How long request and response bodies are kept (0 = metadata only). |
| `AI_VISION_PLATE_ENABLED` / `AI_VISION_ALLOW_AGENT` | `false` / `false` | Plate photos; photos to a Hermes agent (which must also pass its tool check before every photo). |
| `AI_HTTP_PROXY` | unset | Explicit egress proxy; `HTTP(S)_PROXY` is ignored for AI on purpose. |

Also `AI_TIMEOUT_S`, `AI_VISION_TIMEOUT_S` (120), `AI_MAX_TOKENS` (1500), `AI_STRUCTURED_OUTPUT` (`auto`),
`AI_REASONING_EFFORT`, `AI_CONTEXT_TOKENS`, `AI_MAX_RESPONSE_BYTES`, `AI_OPENROUTER_ZDR` and `MAX_IMAGE_BYTES`
([design note 04][NOTE04]). Setup recipes (Ollama next to the app, Kubernetes, a dedicated tool-free Hermes
Agent profile, OpenAI, OpenRouter), the address rules and troubleshooting are in the repository's
[AI guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/ai.md).

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
- **A setting is grayed out in the app**: it is set here; change it here and restart.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Users and keys](users-and-keys.md) · [Security](security.md) · [Network allowlist](network-allowlist.md) · [HTTPS for phones](https.md)

## Sources

- [Design note 01][NOTE01] §5.5 and [design note 07][NOTE07] §4.3: the variables and their rules.
- [Design note 03][NOTE03] R10; [design note 04][NOTE04] R4; [design note 06][NOTE06] §4.14; [design note 08][NOTE08] §4.6.
- [Deployment guide][DEPLOY]; [operator security guide][SECDOC].
- [NIST SP 800-63B-4][NIST-63B4]; [USDA FoodData Central API guide][FDC-API]; [Open Food Facts API][OFF-API].
