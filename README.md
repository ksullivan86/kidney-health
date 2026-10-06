# Kidney Health food log

A small, self-hosted food log for **people living with chronic kidney disease (CKD) and type 1
diabetes**, and for the household around them. You log what you eat; the app totals the nutrients
a renal diet restricts (potassium, phosphorus, sodium, protein, fluid) and the one a person with
type 1 diabetes counts (carbohydrate per meal), compares them with targets set together with your
care team, and warns when a single food or the day's running total needs careful consideration.
It also lets you plan meals ahead, see weekly averages and, on hemodialysis, the totals since your
last session.

It runs as one rootless container with one SQLite file, serves a phone-friendly web page that can
be installed on a phone's home screen, and makes no external requests unless you turn a lookup
on. Each person in the household has their own account and their own log.

**Who it is for:** the people doing the logging and, through the CSV export, their renal
dietitian. It is **not** a medical device and gives no medical advice; every target in it should
come from a nephrologist or renal dietitian (see [Disclaimer](#disclaimer)).

> **Status:** version 0.3 is in development (`0.3.0.dev0`). Its first milestone (accounts,
> security, installable app, hardened deployment) is in this branch; personalised targets, meal
> guidance, optional AI, barcode lookups and the patient handbook at `/learn` follow. See
> [CHANGELOG.md](CHANGELOG.md).

## Features

* **Accounts for a household.** A one-time setup code makes the first admin; the admin invites
  everyone else with a link. Each person sees only their own log, foods, saved meals, profile and
  keys; an admin cannot read anyone else's data. Sign-in can also come from a reverse proxy
  (Authelia, Authentik, `tailscale serve`) or be switched off for a single trusted device.
* **Food logging** by servings or grams, per meal (breakfast, lunch, dinner, snack), with a
  395-food builtin database built from USDA SR Legacy plus your own custom foods and a
  "quick add" from a nutrition label. Entries keep a nutrient snapshot, so later edits to a
  food never rewrite history.
* **Per-serving warnings** (`medium` / `high`) for potassium, phosphorus, sodium, carbohydrate
  and protein, plus flags for phosphate additives, high glycaemic index, star fruit
  (`avoid_ckd`) and hypo treatments. Each food and entry gets a green / yellow / red rating;
  the warnings are shown *before* you save.
* **Daily targets and status bars** per nutrient (`ok` / `caution` / `over`, with an adjustable
  warning threshold), a prominent carbohydrate total per meal, and **"Suggest targets"** that
  fills guideline-based starting points from your weight, CKD stage and dialysis mode, labelled
  "discuss with your care team".
* **Meal planning**: log a food as *planned* for any day, see the projected total (eaten +
  planned), "If you eat what's planned…" alerts, one-tap "Eaten", a 7-day **Plan** grid, **Copy
  day**, **saved meals** ("Usual breakfast") and a **shopping list** for the week.
* **Weekly / period summaries** and, with hemodialysis days set, **interdialytic totals** of
  potassium, sodium and fluid since the last session.
* **Settings** for each person (name, password, signed-in devices, theme, own USDA key, export of
  all your data as a zip, delete account, recent sign-in activity) and for the admin (people and
  invites, server settings, shared keys, usage, activity log, server health).
* **Installable app**: add it to the home screen of an iPhone, Android phone or computer; over
  HTTPS it opens offline and tells you when an update is ready.
* **USDA FoodData Central lookup** (optional, with your own free key or one the admin shares) and
  **CSV export** for your dietitian.
* **No CDN, no tracking:** plain HTML/JS/CSS served by the app, light and dark themes, keyboard and
  screen-reader friendly.

## Quick start

### Try it on your computer

Python 3.11 or newer.

```bash
git clone https://github.com/ksullivan86/kidney-health.git
cd kidney-health
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-dev.lock
python -m pytest                                   # no network needed
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

The first start prints a **one-time setup code** in the log (valid for 60 minutes):

```
WARNING kidney_health.auth: FIRST-RUN SETUP: open https://<this server>/#/setup and enter the code 7KQ2-M9XD-PL4R-T6WN (valid 60 min; restart or run "python -m app.admin setup-code" for a new one)
```

Open <http://localhost:8000>, enter the code, and choose the admin's user name and a password of
at least 15 characters (a few unrelated words work well). Then fill in **Profile** (weight,
stage, dialysis), save, press **Suggest targets**, review them with your care team, save again and
start logging. Invite the rest of the household from **Settings → Admin**. The database lands in
`./data-local/kidney.db`.

Without the code: set `ADMIN_USERNAME` and `ADMIN_PASSWORD_FILE` before the first start, or run
`python -m app.admin create-admin NAME` (password on stdin).

### Run it for real: rootless Podman (recommended)

The image runs as UID 10001 with no shell, a read-only root filesystem and no capabilities. The
Quadlet unit turns it into a systemd user service that starts at boot and auto-updates:

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/kidney-health.container deploy/quadlet/kidney-health.volume ~/.config/containers/systemd/
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | podman secret create kidney-secret-key -
$EDITOR ~/.config/containers/systemd/kidney-health.container     # PUBLIC_URL, TRUSTED_PROXIES
systemctl --user daemon-reload && systemctl --user start kidney-health
sudo loginctl enable-linger "$USER"                                  # keep it running after logout
journalctl --user -u kidney-health | grep 'FIRST-RUN SETUP'          # the setup code
```

The app listens on `127.0.0.1:8000` only; put HTTPS in front of it ([docs/https.md](docs/https.md))
so phones can install it and passwords travel encrypted.

### Other runtimes

```bash
# Compose (podman-compose or docker compose); secrets are files in deploy/secrets/
install -d -m 0700 deploy/secrets
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > deploy/secrets/secret_key
: > deploy/secrets/usda_api_key && chmod 0644 deploy/secrets/*
cp deploy/.env.example deploy/.env && $EDITOR deploy/.env
podman-compose -f deploy/compose.yaml up -d

# Rootless Docker: every hardening flag spelled out; refuses a rootful daemon
deploy/docker-rootless-run.sh

# Kubernetes (Talos or any other distribution): Pod Security "restricted", one replica;
# create the secret first (deploy/k8s/secret.example.yaml, docs/deployment.md)
kubectl apply -k deploy/k8s/
```

Prerequisites (subordinate IDs, linger, cgroup v2, pasta), volumes and SELinux labels, every
setting, backups, upgrades and troubleshooting are in **[docs/deployment.md](docs/deployment.md)**.
Verify a released image before you run it with `scripts/verify-image.sh` ([SECURITY.md](SECURITY.md)).

### Upgrading from v0.2

**If your v0.2 host auto-updates** (the v0.2 Quadlet unit: `Image=...:latest`, `AutoUpdate=registry`),
change it before v0.3.0 is released: `:latest` will move to v0.3, whose image has no shell, and the old
unit's shell `HealthCmd=` would kill and restart it every couple of minutes. Install the v0.3 unit from
`deploy/quadlet/` (`Image=...:0.3`) or pin the v0.2 image by digest and stop
`podman-auto-update.timer` until you upgrade ([docs/deployment.md](docs/deployment.md#from-v02-to-v03)).

Back up `kidney.db`, then start v0.3 on the same data. The first start copies the database to
`kidney.db.pre-v3.bak` (mode 0600, deleted automatically after 30 days), and all existing data
becomes the first account's. If `APP_PASSWORD` was set, it is imported once as the password of the
admin `admin` (or `ADMIN_USERNAME`); a password shorter than today's rules must be changed at the
first sign-in. HTTP Basic sign-in is gone; remove `APP_PASSWORD` afterwards. Without
`APP_PASSWORD`, finish setup with the code from the log and the data is yours.

## Security in short

The full operator guide is **[docs/security.md](docs/security.md)** (threat model, defaults,
`TRUSTED_PROXIES` per topology, checklists per runtime); how to report a vulnerability is in
[SECURITY.md](SECURITY.md).

* **Runtime:** rootless engine with the default user namespace (never `keep-id`), UID 10001,
  Chainguard Python base with no shell and no package manager, read-only root filesystem,
  `cap_drop: ALL`, `no-new-privileges`, 512 MiB / 128 PIDs, published on `127.0.0.1` only. Secrets
  (`SECRET_KEY_FILE`, `USDA_API_KEY_FILE`, ...) are files from the engine's secret store, never
  environment variables.
* **Accounts:** local accounts by default with a one-time setup code (no "first visitor becomes
  admin"), passwords of 15–128 characters checked against a list of common passwords (NIST SP
  800-63B), Argon2id, sign-in throttling per account and per address, re-entering the password
  for sensitive changes. Sessions are opaque server-side tokens in an `HttpOnly`, `SameSite=Lax`
  cookie (`__Host-kh_session`, `Secure`, over HTTPS); sign-out clears the device's cached data.
* **Isolation:** every query is scoped to the signed-in person; someone else's entry, food or meal
  answers 404. API keys are encrypted at rest and never shown again (only the last 4 characters).
  An append-only activity log records sign-ins, settings and key changes, never health data.
* **Browser:** strict Content Security Policy with Trusted Types and no inline script, `X-Frame-Options:
  DENY`, `no-referrer`, HSTS over HTTPS, a Host allowlist against DNS rebinding, CSRF checks
  (`Sec-Fetch-Site`, `Origin` and a required `X-Requested-With` header), `Cache-Control: no-store`
  on the API. Nothing is loaded from a CDN.
* **Proxies:** `X-Forwarded-*` are believed only from `TRUSTED_PROXIES`; proxy sign-in additionally
  needs a shared secret (`TRUSTED_PROXY_SECRET_FILE`).
* **Supply chain:** hash-locked Python wheels, base images pinned by digest, GitHub Actions pinned
  to commit SHAs, a vulnerability gate in CI, and signed release images with SBOM and provenance.
* **Outbound traffic:** none until you turn on USDA lookups (and, later, Open Food Facts or AI);
  the hosts are listed in [docs/network-allowlist.md](docs/network-allowlist.md).

More: [docs/accounts.md](docs/accounts.md) (sign-in modes, adding people, lost passwords, keys),
[docs/privacy.md](docs/privacy.md) (what is stored and who can see it),
[docs/https.md](docs/https.md) (HTTPS for a homelab: own domain + Caddy, Tailscale, a private CA,
cert-manager) and [docs/install-on-your-phone.md](docs/install-on-your-phone.md) (for the people
using the app).

## Configuration

All settings are environment variables; secrets are files given by their `*_FILE` variable. The
ones most installs touch:

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_URL` | unset | The address people type, e.g. `https://food.home.example.net`. Set it whenever you use a host name: it passes the Host check, and invite links and the setup line use it. |
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Addresses whose `X-Forwarded-For`/`-Proto` are believed. Depends on your engine ([docs/security.md §4](docs/security.md#4-proxy-trust-trusted_proxies-per-topology)). |
| `AUTH_MODE` | `local` | `local` (accounts with passwords), `proxy` (identity header from your sign-in proxy), `none` (no sign-in: one trusted device only; the app shows a red banner). |
| `SECRET_KEY_FILE` | auto-generated `$DATA_DIR/secret.key` with a warning | Encrypts stored API keys. Keep it outside the data volume. |
| `USDA_API_KEY_FILE` | unset | A shared key for "Search USDA" (people can also add their own in Settings). |
| `DATA_DIR` | `/data` in the image, `./data-local` outside | Where `kidney.db` lives. |

The complete list (sessions, password rules, size limits, HSTS, proxy headers, ...) is in
[docs/deployment.md](docs/deployment.md#configuration) and at the top of
[`app/config.py`](app/config.py). Settings that are not set in the environment can be changed in
the app (Settings → Admin → Server settings).

## How targets and warnings work

* **Suggested targets** come from `app/nutrients.py::suggest_targets()`, which encodes the
  fact-checked table in `docs/research/targets_by_stage.json`: protein 0.6–0.8 g/kg at CKD
  stages 3–5 (0.8–1.0 at stages 1–2, 1.0–1.2 on dialysis), potassium review ceilings of
  4000 → 3500 → 3000 → 2500 mg from stage 3a to stage 5 / hemodialysis (3500 on peritoneal
  dialysis), phosphorus 1000 mg (900 at stage 5 before dialysis), sodium 2000 mg, calcium 1000 mg,
  30 kcal/kg with 45 % of calories as carbohydrate split per meal, and a fluid limit only on
  dialysis (1500 mL hemodialysis, 2000 mL peritoneal). Per kg means per kg of **ideal** body
  weight when a height is saved. Every suggestion carries the note *"Only restrict potassium if
  your blood potassium is high; your care team sets the number."* Nothing is saved until you press
  **Save profile**. (v0.3's personalised targets raise the protein floor to 0.8 g/kg for people
  with diabetes at stages 3a–5 before dialysis: KDIGO 2022 Rec 3.1.1, KDIGO 2024 Rec 3.3.1.1 and
  ADA 2026 Rec 11.3 all say 0.8 g/kg; see `ARCHITECTURE.md` decision 10 and
  `docs/dev/research/05-personalized-targets.md`, finding H1.)
* **Per-serving warnings** use renal-dietitian conventions: potassium 101–200 mg medium,
  > 200 mg high; phosphorus 101–150 mg medium, > 150 mg high, or **any** food flagged
  `phosphate_additive`; sodium 141–400 mg medium, > 400 mg high; carbohydrate 15–30 g
  medium ("1–2 carb choices"), > 30 g high, with `high_gi` upgrading to high from one carb choice
  (≥ 15 g) upwards; protein 15–25 g medium, > 25 g high. Foods flagged `avoid_ckd` (star fruit,
  potassium-chloride salt substitutes) are always high. Foods flagged `hypo_treatment` (glucose
  tablets, apple juice …) get **no carbohydrate warning**: treating a low is never warned against;
  their potassium warning stays so the lowest-potassium rescue can be chosen.
* **Daily status**: `ok` below 80 % of a target (the profile's `warn_fraction`), `caution`
  between 80 and 100 %, `over` above. Potassium, sodium, fluid and carbohydrate are judged
  **day by day**; phosphorus, protein, calories and calcium on the **weekly average**.

The reasoning and the sources behind every number, the eat / limit / avoid food lists, carb
counting with renal swaps, treating a low on a kidney diet and label reading are in the **patient
handbook**: in the app under **Learn** (served at `/learn/` with no internet needed), source in
[`handbook/docs/`](handbook/docs/index.md), how to build it in [`handbook/README.md`](handbook/README.md).
Research notes for contributors are in `docs/research/`.

## Development

```bash
python -m pytest                       # the whole suite, no network
node tests/js/run_vectors.mjs          # the browser's copies of the rules match the server's
python scripts/build_preview.py        # build/kidney-diet-log.html: the self-contained demo
```

The demo (preview) mode runs the whole UI against an in-page copy of the server's logic; shared
vector files in `tests/data/` keep the two in step. Three browser harnesses in
[`tools/e2e/`](tools/e2e/README.md) check the demo against the real server (`parity.py`), the demo
inside an emulated sandbox host (`sandbox.py`) and the installed app end to end, including first-run
setup (`regress.py`). Read [`ARCHITECTURE.md`](ARCHITECTURE.md) (the contract) and
[`CLAUDE.md`](CLAUDE.md) (the rules every change keeps) before changing code.

### Regenerating the food database

`data/foods.json` is generated and committed. To add or change foods, edit the curated
list in `scripts/curated_foods.py` (look up `fdc_id`s in USDA SR Legacy's `food.csv`;
never guess them) and run

```bash
python3 scripts/build_food_db.py            # add --version 2026-10-05.2 when regenerating on the same day
```

The script downloads the USDA SR Legacy CSV zip once into `scripts/.cache/`, scales the 12
tracked nutrients to each curated household serving, derives `fluid_ml` for foods flagged
`counts_as_fluid`, validates categories and flags, runs sanity checks and writes the JSON. The
server re-imports builtin foods on the next start because the `version` changed, keeping row ids
so existing log entries stay attached.

## Project layout

```
ARCHITECTURE.md           the contract: API shapes, data model, rules, UI behaviour, v0.3 decisions
app/
  main.py                 FastAPI app factory: security middleware, routers, static mount, start-up
  config.py               settings from the environment (secrets from *_FILE)
  security.py             headers, CSP, Host allowlist, trusted proxies, CSRF, body limits
  auth/                   accounts, sessions, throttling, invites, /api/auth, /api/me, /api/admin
  settings_registry.py    every setting with its scope and default; settings_store.py resolves them
  crypto.py, credentials.py   encrypted API keys and per-request key resolution
  audit.py, account.py    activity log; data export and account deletion
  admin.py                admin CLI (python -m app.admin ...)
  db.py, migrations/      SQLite connection + append-only schema steps
  nutrients.py, periods.py    pure rules: thresholds, daily status, targets, period maths
  foods.py, log.py, meals.py, profile.py   the data routes, scoped to the signed-in person
  pwa.py                  service worker and install manifest headers
  handbook.py             the patient handbook at /learn: mount, its own CSP, /api/handbook
  static/                 index.html, js/ (KH modules), css/, icons, sw.js (no build step)
data/foods.json           builtin food database (generated)
deploy/                   Containerfile(s), compose, Quadlet, Kubernetes, Caddy example
docs/                     operator guides (deployment, security, https, accounts, privacy, ...)
handbook/                 patient handbook (MkDocs); built into the image and served at /learn
scripts/                  food database, preview, icons, lock files, image verification
tests/                    pytest suite; tests/js and tests/data hold the JS parity vectors
tools/e2e/                browser harnesses (parity, sandbox, regress, learn)
```

## Disclaimer

This software is a logging aid, not medical advice and not a medical device. Nutrient
targets, limits and warnings must come from your nephrologist and renal dietitian, insulin
decisions from your diabetes care team; the suggested targets are published guideline
starting points that your care team should overwrite. The food database is reference data
(USDA SR Legacy and manual entries): check labels and portions. Never delay or under-treat
low blood glucose because of a potassium or phosphorus number.

## License

The code is licensed under the **PolyForm Noncommercial License 1.0.0**: you may use, copy,
modify and share it for personal and other noncommercial purposes, free of charge. **Any
commercial use requires the written permission of the author.** The full text is in
[LICENSE](LICENSE). The handbook's text is licensed under CC BY-NC-SA 4.0. The food data comes
from USDA FoodData Central (public domain).
