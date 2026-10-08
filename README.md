# Kidney Health food log

A self-hosted food log for **people living with chronic kidney disease (CKD) and type 1 diabetes**,
and for the household around them. You log what you eat; the app totals the nutrients a kidney diet
restricts (potassium, phosphorus, sodium, protein, fluid) and the carbohydrate a person with type 1
diabetes counts per meal, compares them with the targets set with your care team, and warns when a
single food or the day's running total needs careful consideration. It suggests what fits your next
meal, plans the rest of the day, reads barcodes, keeps logging without a connection, and comes with a
plain-language patient handbook.

It runs as one rootless container with one SQLite file on your own server, installs on a phone's home
screen, and makes no outbound request until someone turns a lookup on (an admin, or a person adding
their own key). Each person in the household has their own account and their own log.

**What it is not:**

* **Not a medical device and not medical advice.** Every target should come from a nephrologist or
  renal dietitian; the app's suggestions are guideline starting points labelled "discuss with your care
  team" ([Disclaimer](#disclaimer)).
* **Never a dose calculator.** It gives no insulin or medicine doses, ratios or corrections, and it never
  warns against, limits or delays treating a low blood sugar.
* **Not a cloud service.** There is no account with the project, no telemetry and nothing loaded from a
  CDN: your data stays on your server.

> **Version 0.3.0** (2026-10-07): accounts, personalised targets and lab results, meal guidance,
> barcodes, optional AI, offline logging and the handbook at `/learn`. See [CHANGELOG.md](CHANGELOG.md).
> **Upgrading an auto-updating v0.2 server? Read [Upgrading from v0.2](#upgrading-from-v02) first.**

## Contents

* [Features](#features)
* [Quick start](#quick-start): [rootless Podman](#run-it-with-rootless-podman-recommended),
  [phone](#install-it-on-your-phone), [from source](#try-it-on-your-computer),
  [other runtimes](#other-runtimes), [upgrading from v0.2](#upgrading-from-v02)
* [Learn: the patient handbook](#learn-the-patient-handbook)
* [Optional: barcode lookups and AI](#optional-barcode-lookups-and-ai)
* [Security in short](#security-in-short) · [Configuration](#configuration) ·
  [How targets and warnings work](#how-targets-and-warnings-work)
* [Documentation](#documentation) · [Contributing](#contributing) · [Project layout](#project-layout)
* [Disclaimer](#disclaimer) · [Licences](#licences)

## Features

* **Accounts for a household.** A one-time setup code makes the first admin; the admin invites everyone
  else by link. Each person sees only their own log, foods, saved meals, profile, lab results and keys;
  an admin cannot read anyone else's data. Sign-in can also come from a reverse proxy (Authelia,
  Authentik, `tailscale serve`) or be switched off for a single trusted device.
* **Food logging** by servings or grams, per meal, from a 395-food builtin database built from USDA SR
  Legacy, your own custom foods, a quick add from a nutrition label, or a **barcode**. Entries keep a
  nutrient snapshot, so later edits to a food never rewrite history.
* **Per-serving warnings** (`medium` / `high`) for potassium, phosphorus, sodium, carbohydrate and
  protein, plus flags for phosphate and potassium additives, high glycaemic index, star fruit and
  potassium-chloride salt substitutes (`avoid_ckd`) and low treatments. Each food gets a green / yellow /
  red rating, shown *before* you save, with a link to the handbook page that explains it.
* **Personalised targets.** "Suggest targets" works out starting points from your weight, height, age,
  sex, activity, CKD stage, dialysis or transplant, and recent lab results; every number has "Why this
  number?" with its rule and source, and nothing is saved until you save it.
* **Lab results and kidney function.** Enter potassium, phosphate, albumin, bicarbonate, urine
  albumin-to-creatinine ratio, creatinine, cystatin C, eGFR and HbA1c in US or SI units; see eGFR
  (CKD-EPI 2021) and the albuminuria category. A potassium of 6.0 mmol/L or more always shows an urgent
  banner.
* **Meal guidance without AI**: "What fits now" for your next meal, lower-potassium, -phosphorus or
  -sodium swaps with the same carbohydrate, "Plan the rest of my day", end-of-day and weekly insights,
  and a "Treating a low" card that works even offline. Arithmetic on your care team's targets; it never
  writes anything without your tap.
* **Meal planning**: planned entries, the projected day, a 7-day Plan grid, copy day, saved meals
  ("Usual breakfast") and a shopping list; **weekly summaries** and, on hemodialysis, the totals since
  your last session.
* **Installable and offline**: add it to the home screen of an iPhone, Android phone or computer. Over
  HTTPS it opens without a connection, and food you log offline waits on the device and syncs exactly
  once when the server is back.
* **Learn**: the patient handbook at `/learn`, served by your server with no internet needed.
* **Optional, off by default**: barcode lookups in Open Food Facts and USDA FoodData Central, and AI
  meal ideas and label photos through a provider your admin chooses ([below](#optional-barcode-lookups-and-ai)).
* **Your data, your choice**: export everything you entered as a zip (JSON and CSV for your dietitian),
  delete your account, see your own sign-in and AI activity.
* **No CDN, no tracking**: plain HTML/JS/CSS served by the app, light and dark themes, keyboard and
  screen-reader friendly, 44-pixel tap targets.

## Quick start

### Run it with rootless Podman (recommended)

The image runs as UID 10001 with no shell, a read-only root filesystem and no capabilities, on Linux
amd64 or arm64 (which includes the Raspberry Pi 4 and 5). The Quadlet unit turns it into a systemd user service
that starts at boot and follows the `:0.3` tag:

```bash
git clone https://github.com/ksullivan86/kidney-health.git && cd kidney-health
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/kidney-health.container deploy/quadlet/kidney-health.volume ~/.config/containers/systemd/
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | podman secret create kidney-secret-key -
$EDITOR ~/.config/containers/systemd/kidney-health.container     # PUBLIC_URL, TRUSTED_PROXIES
systemctl --user daemon-reload && systemctl --user start kidney-health
sudo loginctl enable-linger "$USER"                                  # keep it running after logout
journalctl --user -u kidney-health | grep 'FIRST-RUN SETUP'          # the setup code
```

The log line looks like this (the code is valid for 60 minutes; restart or run
`podman exec kidney-health python -m app.admin setup-code` for a new one):

```
FIRST-RUN SETUP: open https://food.home.example.net/#/setup and enter the code 7KQ2-M9XD-PL4R-T6WN (valid 60 min; restart or run "python -m app.admin setup-code" for a new one)
```

Open the app, enter the code, choose the admin's user name and a password of at least 15 characters (a
few unrelated words work well), and decide whether barcode lookups may use Open Food Facts. Then fill in
**Profile**, press **Suggest targets**, review them with your care team, save, and start logging. Invite
the rest of the household from **Server administration** (the shield button next to Settings, admins only).

The app listens on `127.0.0.1:8000` only; put HTTPS in front of it ([docs/https.md](docs/https.md)) so
phones can install it, scan with the camera and keep your password encrypted. Verify a released image
before you run it with `scripts/verify-image.sh 0.3.0` ([SECURITY.md](SECURITY.md#verifying-the-image-before-you-run-it)).
Prerequisites (subordinate IDs, linger, cgroup v2, pasta), volumes, every setting, backups, upgrades and
troubleshooting: **[docs/deployment.md](docs/deployment.md)**.

### Install it on your phone

Open the app's HTTPS address on the phone and sign in, then: **iPhone and iPad**: Safari → Share → **Add
to Home Screen**; **Android**: Chrome → **Install app**; **computer**: the install icon in Chrome or
Edge's address bar, or File → Add to Dock in Safari. Step by step, what works over plain HTTP, and how
offline logging behaves: [docs/install-on-your-phone.md](docs/install-on-your-phone.md).

### Try it on your computer

Python 3.11 or newer:

```bash
git clone https://github.com/ksullivan86/kidney-health.git && cd kidney-health
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-dev.lock
python -m pytest                                   # the test suite, no network needed
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open <http://localhost:8000> and enter the setup code from the terminal. The database lands in
`./data-local/kidney.db`. Without the code: set `ADMIN_USERNAME` and `ADMIN_PASSWORD_FILE` before the
first start, or run `python -m app.admin create-admin NAME` (password on stdin). The handbook at
`/learn` appears once you build it ([handbook/README.md](handbook/README.md#build-and-check)).

### Other runtimes

```bash
# Compose (podman-compose 1.5+ or docker compose); secrets are files in deploy/secrets/
install -d -m 0700 deploy/secrets
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > deploy/secrets/secret_key
: > deploy/secrets/usda_api_key && chmod 0644 deploy/secrets/*
cp deploy/.env.example deploy/.env && $EDITOR deploy/.env
podman-compose -f deploy/compose.yaml up -d

# Rootless Docker: every hardening flag spelled out; refuses a rootful daemon
deploy/docker-rootless-run.sh

# Kubernetes (Talos or any other distribution): Pod Security "restricted", one replica; a
# cluster-neutral base plus your overlay (host, Gateway, TRUSTED_PROXIES). Create the secret first
# (deploy/k8s/secret.example.yaml, docs/deployment.md)
cp -r deploy/k8s-overlays/example deploy/k8s-overlays/home && $EDITOR deploy/k8s-overlays/home/*.yaml
kubectl apply -k deploy/k8s-overlays/home
```

A local AI model can run next to the app with `deploy/compose.ai-ollama.yaml` ([docs/ai.md](docs/ai.md#recipes)).

### Upgrading from v0.2

**If your v0.2 host auto-updates** (the v0.2 Quadlet unit: `Image=...:latest`, `AutoUpdate=registry`),
replace its `.container` file with the v0.3 one **before** the next update. `:latest` moves to v0.3.0,
whose image has no shell, and the old unit's shell `HealthCmd=` would kill and restart it every couple
of minutes. Install the v0.3 unit from `deploy/quadlet/` (`Image=...:0.3`, an exec-form `HealthCmd`), or
pin the v0.2 image by digest and stop `podman-auto-update.timer` until you upgrade
([docs/deployment.md](docs/deployment.md#from-v02-to-v03)).

Back up `kidney.db`, then start v0.3 on the same data. The first start copies the database to
`kidney.db.pre-v3.bak` (mode 0600, deleted automatically after 30 days) and all existing data becomes
the first account's. If `APP_PASSWORD` was set, it is imported once as the password of the admin `admin`
(or `ADMIN_USERNAME`); a password shorter than today's rules must be changed at the first sign-in. HTTP
Basic sign-in is gone; remove `APP_PASSWORD` afterwards. Without `APP_PASSWORD`, finish setup with the
code from the log and the data is yours. Add a `SECRET_KEY_FILE`, set `PUBLIC_URL` when you use a host
name, and note the new image tags (`main` → `:edge`, releases → `:X.Y.Z`, `:X.Y` and `:latest`). Every
step: [CHANGELOG.md](CHANGELOG.md#upgrading-from-02-read-this-first).

## Learn: the patient handbook

The app serves a plain-language handbook at **`/learn/`**, with no sign-in and no internet needed: kidney
disease and its stages, eating well (potassium, phosphorus, sodium, protein, fluid, carb counting,
reading labels, menus and recipes), lab results, type 1 diabetes with CKD (treating a low, sick days,
insulin and dialysis), medicines, preparing for dialysis or a transplant, living well, using the app and
running your own server. It opens from the **Learn** (book) icon at the top of the app; warnings, alerts
and target notes link straight to the page that explains them.

Every clinical statement cites its source (KDIGO, KDOQI, ADA, FDA labels and others) and was
fact-checked against it ([handbook/REVIEW.md](handbook/REVIEW.md)). **Every page is still a draft that
no clinician has reviewed yet**, and says so at the top. Clinicians who would review a section are very
welcome ([CONTRIBUTING.md](CONTRIBUTING.md#clinical-content-policy-and-sign-off)). Source and build
instructions: [handbook/](handbook/README.md).

## Optional: barcode lookups and AI

Nothing leaves your server until a feature is turned on: by an admin for the server, or by a person who
adds their own USDA or AI key where the admin allows it. Each person then decides for themselves.
Every outbound call is made by the server (never the browser) through a transport that refuses private
and cloud-metadata addresses unless the operator listed them. All hosts: [docs/network-allowlist.md](docs/network-allowlist.md).

**Barcodes** ([docs/barcode-and-photos.md](docs/barcode-and-photos.md)). **Add → Scan** reads a barcode
with the camera (HTTPS), from a photo, or as typed digits; decoding happens on the device and only the
digits reach your server. Your own foods with that barcode are always found. Two optional sources:

| Source | Turn it on | What it receives |
|---|---|---|
| **Open Food Facts** (product data under ODbL) | `OFF_ENABLED=true`, the first-run checkbox or Server administration; then each person agrees in Settings → Food data | the barcode digits and the server's User-Agent |
| **USDA FoodData Central** branded foods (public domain) | a USDA key: `USDA_API_KEY_FILE` (shared) or each person's own in Settings → Food data | the barcode digits and the key |

Scanned foods show where their data came from, the quality notes ("potassium not listed") and the
additives found in the ingredients; a potassium additive with no potassium value gets a warning.

**AI** ([docs/ai.md](docs/ai.md)). Off unless the admin sets `AI_ENABLED=true` and a provider: a local
Ollama, LM Studio, llama.cpp, vLLM or LiteLLM server, OpenAI, OpenRouter, Nous Portal, a tool-free Hermes
Agent profile, or any OpenAI-compatible server. Each person opts in under Settings → AI ideas, agrees per
destination before anything is sent, and can see the exact request first ("What will be sent?"). AI can
pick and order meal ideas among foods the rules already allowed, split a typed meal into searches,
read a nutrition-label photo into a draft you check, and name the foods on a plate photo (off by
default). Its own words are never shown, every number comes from the food list, and text that may
describe a low or an emergency gets the rule-based card instead of an AI call. No model is recommended
yet: the live evaluations are still to be run ([docs/ROADMAP.md](docs/ROADMAP.md)).

## Security in short

The full operator guide is **[docs/security.md](docs/security.md)** (threat model, defaults,
`TRUSTED_PROXIES` per topology, checklists per runtime); how to report a vulnerability is in
[SECURITY.md](SECURITY.md).

* **Runtime:** rootless engine with the default user namespace (never `keep-id`), UID 10001, Chainguard
  Python base with no shell and no package manager, read-only root filesystem, `cap_drop: ALL`,
  `no-new-privileges`, 512 MiB / 128 PIDs, published on `127.0.0.1` only. Secrets (`SECRET_KEY_FILE`,
  `USDA_API_KEY_FILE`, `AI_API_KEY_FILE`, ...) are files from the engine's secret store, never
  environment variables.
* **Accounts:** local accounts by default with a one-time setup code (no "first visitor becomes admin"),
  passwords of 15–128 characters checked against a list of common passwords (NIST SP 800-63B),
  Argon2id, sign-in throttling per account and per address, re-entering the password for sensitive
  changes. Sessions are opaque server-side tokens in an `HttpOnly`, `SameSite=Lax` cookie
  (`__Host-kh_session`, `Secure`, over HTTPS); sign-out clears the device's cached and offline data.
* **Isolation:** every query is scoped to the signed-in person; someone else's entry, food, meal or lab
  result answers 404. API keys are encrypted at rest and never shown again (only the last 4
  characters). An append-only activity log records sign-ins, settings and key changes, never health data.
* **Browser:** strict Content Security Policy with Trusted Types and no inline script, `X-Frame-Options:
  DENY`, `no-referrer`, HSTS over HTTPS, a Host allowlist against DNS rebinding, CSRF checks
  (`Sec-Fetch-Site`, `Origin` and a required `X-Requested-With` header), `Cache-Control: no-store` on the
  API. Nothing is loaded from a CDN; the barcode decoder is vendored and pinned by SHA-256.
* **Outbound traffic:** none until you turn on USDA, Open Food Facts or AI; every call goes through an
  SSRF-checked transport that never follows redirects. Photos for AI are stripped of all metadata on the
  server and never stored.
* **Supply chain:** hash-locked Python wheels, base images pinned by digest, GitHub Actions pinned to
  commit SHAs, a vulnerability gate before any tag moves, and release images signed with cosign and
  published with SLSA provenance and an SBOM.

More: [docs/accounts.md](docs/accounts.md) (sign-in modes, adding people, lost passwords, keys),
[docs/privacy.md](docs/privacy.md) (what is stored and who can see it) and
[docs/https.md](docs/https.md) (HTTPS for a homelab: own domain + Caddy, Tailscale, a private CA,
cert-manager).

## Configuration

All settings are environment variables; secrets are files given by their `*_FILE` variable. The ones
most installs touch:

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_URL` | unset | The address people type, e.g. `https://food.home.example.net`. Set it whenever you use a host name: it passes the Host check, and invite links and the setup line use it. |
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Addresses whose `X-Forwarded-For`/`-Proto` are believed. Depends on your engine ([docs/security.md §4](docs/security.md#4-proxy-trust-trusted_proxies-per-topology)). |
| `AUTH_MODE` | `local` | `local` (accounts with passwords), `proxy` (identity header from your sign-in proxy), `none` (no sign-in: one trusted device only; the app shows a red banner). |
| `SECRET_KEY_FILE` | auto-generated `$DATA_DIR/secret.key` with a warning | Encrypts stored API keys. Keep it outside the data volume and with your backups. |
| `USDA_API_KEY_FILE` | unset | A shared key for USDA search and branded barcode lookups (people can also add their own in Settings). |
| `OFF_ENABLED` | `false` | Barcode lookups in Open Food Facts (each person still agrees). Related: `OFF_CONTACT` (the contact in the User-Agent; an admin e-mail address is best), `OFF_RATE_PER_MINUTE` (10), `BARCODE_NEGATIVE_TTL_HOURS` (24), `USDA_BRANDED_BARCODE` (`true`), and the env-only `OFF_BASE_URL`. |
| `AI_ENABLED` | `false` | The optional AI layer; the provider comes from `AI_PROVIDER`, `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY_FILE` and friends ([docs/ai.md](docs/ai.md#switches)). |
| `GUIDANCE_ENABLED` | `true` | Rule-based meal guidance for the whole server (each person can also switch it off). |
| `DATA_DIR` | `/data` in the image, `./data-local` outside | Where `kidney.db` lives. |

The complete list (sessions, password rules, size limits, HSTS, proxy headers, AI network policy,
handbook, ...) is in [docs/deployment.md](docs/deployment.md#configuration) and at the top of
[`app/config.py`](app/config.py). Settings that are not set in the environment can be changed in the app
(Server administration → Server settings); the ones set in the environment are shown as locked.

## How targets and warnings work

* **Suggested targets** are starting points from published guidelines, worked out in
  [`app/targets.py`](app/targets.py) with every number, source and note in
  [`app/target_rules.py`](app/target_rules.py) (all of it explained in
  [docs/targets-and-labs.md](docs/targets-and-labs.md)). In short: calories from the 2023 Dietary
  Reference Intakes kept within 25–35 kcal/kg; protein 0.8 g/kg with diabetes at stages 3a–5 before
  dialysis (never lower; ADA 2026, KDIGO 2022 and 2024), 0.8–1.0 at stages 1–2 and after a transplant,
  1.0–1.2 on dialysis; potassium review ceilings of 4,000 → 3,500 → 3,000 → 2,500 mg from stage 3a to
  stage 5 and hemodialysis (3,500 on peritoneal dialysis), adjusted by a recent blood potassium;
  phosphorus 1,000 mg (900 at stage 5 before dialysis, 800 with a high phosphate); sodium 2,000 mg;
  carbohydrate 45 % of calories split over the meals; a fluid limit only on dialysis. Per kg means per
  kg of a reference weight (the actual weight between BMI 18.5 and 25). Every potassium note says *"Only
  restrict potassium if your blood potassium is high; your care team sets the number."* No targets are
  suggested in pregnancy, under 18, or in the first 12 weeks after a transplant.
* **Per-serving warnings** use renal-dietitian conventions: potassium 101–200 mg medium, > 200 mg high
  (and medium for a potassium additive with potassium not listed); phosphorus 101–150 mg medium, > 150
  mg high, or **any** food flagged `phosphate_additive`; sodium 141–400 mg medium, > 400 mg high;
  carbohydrate 15–30 g medium ("1–2 carb choices"), > 30 g high, with `high_gi` upgrading to high from
  one carb choice (≥ 15 g); protein 15–25 g medium, > 25 g high. Foods flagged `avoid_ckd` (star
  fruit, potassium-chloride salt substitutes) are always high. Foods flagged `hypo_treatment` (glucose
  tablets, apple juice …) get **no carbohydrate warning**: treating a low is never warned against; their
  potassium warning stays so the lowest-potassium option can be chosen.
* **Daily status**: `ok` below 80 % of a target (the profile's `warn_fraction`), `caution` between 80
  and 100 %, `over` above. Potassium, sodium, fluid and carbohydrate are judged **day by day**;
  phosphorus, protein, calories and calcium on the **weekly average**.
* **Meal guidance** applies the same numbers to the next meal; its rules of thumb and weights are listed
  with their sources in [docs/guidance.md](docs/guidance.md).

The reasoning in plain words, the eat / limit / avoid lists, carb counting with kidney-friendly swaps and
treating a low on a kidney diet are in the handbook at `/learn`. The rules marked "expert opinion" and
the guidance weights are still waiting for review by a renal dietitian ([docs/ROADMAP.md](docs/ROADMAP.md)).

## Documentation

* **[docs/README.md](docs/README.md)**: every guide in one list (deployment, HTTPS, security, accounts,
  privacy, phone install, targets and labs, meal guidance, AI, barcodes and photos, network allowlist).
* **[docs/ROADMAP.md](docs/ROADMAP.md)**: what is planned for later versions, and the clinical reviews
  still to be done.
* **[CHANGELOG.md](CHANGELOG.md)**: what changed in each version, with upgrade notes.
* **[SECURITY.md](SECURITY.md)**: reporting a vulnerability, supported versions, verifying images.

## Contributing

Contributions are welcome: bug reports, clinical corrections with a source, docs, handbook pages and
code. Start with **[CONTRIBUTING.md](CONTRIBUTING.md)** (setup, tests, the parity rule, safety and
security rules, how to add a food, a handbook page, a guidance rule or an AI preset) and the
[Code of Conduct](CODE_OF_CONDUCT.md). [`ARCHITECTURE.md`](ARCHITECTURE.md) is the contract every change
follows; AI coding agents also read [`AGENTS.md`](AGENTS.md). Maintainers: [docs/maintainers.md](docs/maintainers.md).

```bash
python -m pytest                       # the whole suite, no network
node tests/js/run_vectors.mjs          # the browser's copies of the rules match the server's
python scripts/build_preview.py        # build/kidney-diet-log.html: the self-contained demo
```

## Project layout

```
ARCHITECTURE.md           the contract: API shapes, data model, rules, UI behaviour, v0.3 decisions
app/
  main.py                 FastAPI app factory: security middleware, routers, static mount, start-up
  config.py               settings from the environment (secrets from *_FILE)
  security.py, egress.py  headers, CSP, Host allowlist, proxies, CSRF, limits; the SSRF-checked transport
  auth/                   accounts, sessions, throttling, invites, /api/auth, /api/me, /api/admin
  settings_registry.py    every runtime setting with its scope and default; settings_store.py resolves them
  crypto.py, credentials.py   encrypted API keys and per-request key resolution
  audit.py, account.py    activity log; data export and account deletion
  admin.py                admin CLI (python -m app.admin ...)
  db.py, migrations/      SQLite connection + append-only schema steps (1-7)
  nutrients.py, periods.py    pure rules: warnings, daily status, period maths
  targets.py, target_rules.py, kidney_function.py, units.py, labs.py   personalised targets, eGFR, lab results
  guidance/               rule-based meal guidance (pure engine + routes)
  gtin.py, additives.py, textclean.py, off.py, barcode.py   barcodes, additive scan, Open Food Facts
  ai/, vision.py, imagecheck.py   optional AI (presets, network policy, guard, routes) and photo checks
  foods.py, log.py, meals.py, profile.py   the data routes, scoped to the signed-in person
  pwa.py, handbook.py     service worker and manifest headers; the handbook at /learn
  static/                 index.html, js/ (KH modules: engine twins, mock demo API, views), css/, vendor/
data/                     builtin food database (generated) and starter meal combos
deploy/                   Containerfile(s), compose (+ Caddy, Ollama overlays), Quadlet, Kubernetes
docs/                     operator and feature guides (index: docs/README.md); dev/research: design notes
handbook/                 patient handbook (MkDocs); built into the image and served at /learn
scripts/                  food database, preview, handbook build, locks, image verification, benchmarks
tests/                    pytest suite; tests/data and tests/js hold the parity vectors
tools/e2e/                browser harnesses (parity, sandbox, regress, learn, device, guidance_perf)
```

## Disclaimer

This software is a logging aid, not medical advice and not a medical device. Nutrient targets, limits
and warnings must come from your nephrologist and renal dietitian, insulin decisions from your diabetes
care team; the suggested targets are published guideline starting points that your care team should
overwrite. The food database is reference data (USDA and, when enabled, Open Food Facts, which is
crowd-sourced): check labels and portions. AI ideas are optional suggestions checked against your
targets, not advice. Never delay or under-treat low blood glucose because of a potassium or phosphorus
number.

## Licences

* **Code**: [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, copy, modify and share it for
  personal and other noncommercial purposes, free of charge. **Any commercial use requires the written
  permission of the author.**
* **Handbook text** (`handbook/docs/`, `handbook/includes/`, `handbook/data/`):
  [CC BY-NC-SA 4.0](handbook/LICENSE). Clinics, charities and families may copy, print, translate and
  adapt it for non-commercial use, with credit and under the same licence.
* **Food data**: USDA FoodData Central (SR Legacy and Branded Foods) is in the public domain (CC0 1.0).
  **Open Food Facts** product data, when an admin turns lookups on, is under the
  [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/); the app shows the
  attribution with each product and includes the notice in data exports.
* **Third-party code** keeps its own licence: the vendored barcode decoder is MIT (barcode-detector)
  and Apache-2.0 (ZXing-C++), listed in [app/static/vendor/README.md](app/static/vendor/README.md); the
  handbook's theme, Material for MkDocs, is MIT.
