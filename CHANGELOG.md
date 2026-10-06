# Changelog

All notable changes to this project. Dates are UTC. The project follows semantic versioning from
0.3.0 on; until then minor versions may change the API.

## 0.3.0 (in development: `0.3.0.dev0`)

Version 0.3 turns the single-person log into a household app that is safe to run on a home server
and install on a phone. It is built in milestones (see `ARCHITECTURE.md`, "v0.3 contract"); this
section lists what has landed so far.

### Milestone 1: accounts, security, installable app, hardened deployment

**Upgrading from 0.2: read this first**

* Back up `kidney.db`. The first start migrates it in place (schema 2 → 3) and keeps a copy as
  `kidney.db.pre-v3.bak` (mode 0600), deleted automatically 30 days later
  (`python -m app.admin purge-pre-v3-backup` deletes it at once). All existing data becomes the
  first account's.
* **HTTP Basic sign-in is gone.** A set `APP_PASSWORD` is imported once as the password of the admin
  `admin` (or `ADMIN_USERNAME`); if it is shorter than today's rules, a new password must be chosen
  at the first sign-in. After that `APP_PASSWORD` is ignored (and logged as deprecated): remove it.
  Without it, the log shows a one-time **setup code** for the first admin.
* Every `/api` route now needs a signed-in person (`401` otherwise; `503 setup_required` before
  first-run setup), and every POST/PUT/PATCH/DELETE must send `X-Requested-With: kidney-health`
  with a same-origin `Origin` (scripts calling the API must add them).
* Run uvicorn with `--no-proxy-headers` (the image does): the app applies `X-Forwarded-*` itself,
  only from `TRUSTED_PROXIES`. Set `PUBLIC_URL` when the app is reached by a host name, or the Host
  check answers `400 Unknown host`.
* `/docs` and `/openapi.json` are off unless `ENABLE_API_DOCS=true`.

**Accounts and privacy**

* Local accounts (`AUTH_MODE=local`, default): first admin from the logged setup code,
  `ADMIN_USERNAME` + `ADMIN_PASSWORD_FILE`, or `python -m app.admin create-admin`; invites by link,
  admin-created accounts with a one-time setup link, reset links, registration modes
  (invite/closed/open).
* Sign-in proxy mode (`AUTH_MODE=proxy`: Authelia, Authentik, `tailscale serve`) with a required
  shared secret (`TRUSTED_PROXY_SECRET_FILE`), optional admin group; and `AUTH_MODE=none` for a
  single trusted device, with a red banner.
* Passwords of 15–128 characters, NFC, checked against the 10,000 most common passwords and
  against the name, Argon2id (scrypt fallback); sign-in throttling per account and per address,
  instance-wide limits, a lock after 100 failures; re-entering the password for sensitive changes;
  forced password change.
* Opaque server-side sessions (`__Host-kh_session` over HTTPS, `kh_session` on plain HTTP; 30 days
  absolute, 14 idle), a list of signed-in devices with sign-out per device or everywhere; sign-out
  sends `Clear-Site-Data`.
* Every query is scoped to the signed-in person; someone else's data answers 404. Builtin foods are
  shared, custom foods are private, USDA imports are shared but visible only to whoever imported
  them. `GET /healthz` counts builtin foods only. CSV cells that start like a formula are escaped.
* `GET /api/me/export.zip`: everything a person entered as JSON and CSV; `DELETE /api/me` deletes
  the account and all its data.
* An append-only activity log (sign-ins, invites, settings and key changes; ids only, never health
  data or secrets) for each person and for the admin.
* Admin CLI `python -m app.admin`: `create-admin`, `reset-password`, `list-users`, `setup-code`,
  `revoke-sessions`, `purge-pre-v3-backup`, `vacuum`, `backup`, `check`, `restore-check`,
  `rotate-secret-key`, `reencrypt`, `settings`.

**Settings and keys**

* One settings registry with clear precedence (server environment → admin → person → default);
  every setting in the UI says where its value comes from, and values set in the environment are
  locked.
* API keys (USDA now) are write-only: encrypted at rest under `SECRET_KEY` (Fernet), shown only as
  "ends in 9xQz". People can add their own key or use a key the admin shares, with a daily limit
  per person; a missing or unusable key answers `503` with a reason the UI explains.

**Security layer**

* Strict Content Security Policy with Trusted Types and no inline script or style, `X-Frame-Options:
  DENY`, `no-referrer`, COOP/CORP, `nosniff`, HSTS and `upgrade-insecure-requests` over HTTPS only,
  `Cache-Control: no-store` on the API.
* Host allowlist against DNS rebinding (`localhost`, IP literals, the `PUBLIC_URL` host,
  `ALLOWED_HOSTS`); `X-Forwarded-*` and identity headers only from `TRUSTED_PROXIES`; CSRF checks
  (`Sec-Fetch-Site`, `Origin`, required `X-Requested-With`); request body limits; validation errors
  never echo the submitted value; secrets are redacted from logs.
* Plain-HTTP sign-in from other machines is allowed only while a single account exists.

**Installable app (PWA)**

* Web app manifest, icons (including maskable and Apple touch icons), and a service worker that
  keeps the app shell for offline start over HTTPS (never `/api`), with an "Update ready" prompt and
  a `PWA_ENABLED=false` kill switch. Settings → This device shows install, offline and storage state.
* [docs/install-on-your-phone.md](docs/install-on-your-phone.md) for iPhone, Android and computers.

**Interface**

* Sign-in, first-run setup (with an opt-in for Open Food Facts lookups, which stay off by default),
  invite, reset and new-password screens; a Settings view (account, preferences, food data, this
  device, admin, about & privacy) reached from the header gear. The theme and install panel moved
  from Profile to Settings.
* The frontend is split into plain scripts under one `window.KH` namespace (`js/core.js`,
  `js/engine/*`, `js/views/*`, `js/mock/*`) and per-view stylesheets; no bundler.
* The demo (preview) mode runs as a signed-in demo admin; its copies of server logic are checked
  against the server by shared vector files (`node tests/js/run_vectors.mjs`).

**Deployment and supply chain**

* Image on Chainguard Python pinned by digest (no shell, no package manager), with a Debian-based
  fallback (`deploy/Containerfile.debian`); runs as UID 10001 with a read-only root filesystem.
* Rootless profiles with the same hardening: Quadlet unit and volume, compose (plus Caddy HTTPS and
  local Ollama overlays), a rootless Docker script, and Kubernetes manifests for Pod Security
  "restricted" with NetworkPolicy and an HTTPRoute; secrets as files everywhere.
* CI: pytest on Python 3.12 and 3.14, JS parity vectors, actionlint, hadolint, kubeconform,
  shellcheck, zizmor, CodeQL, dependency review, an image smoke test and a Grype gate. Releases are
  built by digest, scanned, signed and attested (SBOM, provenance); `scripts/verify-image.sh`
  checks an image before use. Every action is pinned to a commit SHA; Python dependencies are
  hash-locked (`requirements*.lock`).
* Moved from `httpx` to `httpx2`; new runtime dependency `cryptography`.
* Schema changes are append-only steps in `app/migrations/`.
* Docs: [deployment](docs/deployment.md), [security](docs/security.md), [HTTPS](docs/https.md),
  [accounts](docs/accounts.md), [privacy](docs/privacy.md),
  [network allowlist](docs/network-allowlist.md), [SECURITY.md](SECURITY.md).

**Patient handbook (drafts)**

* `handbook/`: a patient handbook site in plain language (stages, eating, labs, type 1 diabetes,
  medicines, preparing for treatment, living well, the app, self-hosting), fact-checked against
  primary sources and marked "draft, not yet reviewed by a clinician". Text under CC BY-NC-SA 4.0.
  It will be served at `/learn` in a later milestone.

**Development**

* `tools/e2e/`: browser harnesses for demo-vs-server parity, the sandboxed preview, and the
  installed app end to end, now signing in first ([tools/e2e/README.md](tools/e2e/README.md)).

### Still to come in 0.3

Personalised targets (age, sex, activity, lab results, eGFR) with lab history; rule-based meal
guidance; optional AI ideas (OpenAI-compatible, Ollama, OpenRouter); barcode lookups (Open Food
Facts, USDA branded) and label photos; an offline outbox for logging without a connection; the
handbook at `/learn`.

## 0.2.0 (2026-10-05): first release

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
