# Changelog

All notable changes to this project, written for the people who run it. Dates are UTC. The project
follows [semantic versioning](https://semver.org/) from 0.3.0 on; until then minor versions could change
the API. Security fixes are released as patch versions of the newest minor version
([SECURITY.md](SECURITY.md#supported-versions)).

## Unreleased

### For people using the app

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
* **No diabetes, no meal carbohydrate goals.** If your profile says *Diabetes: None*, meals have no
  carbohydrate goal: Today no longer shows a carbohydrate line in each meal or warns that a meal is over its
  carbohydrate goal, Settings → Meal guidance explains instead of showing the carbohydrate tolerance and
  the carbs taken for a low, and Profile hides the per-meal and per-snack carbohydrate targets (their values
  are kept). The day's carbohydrate still counts like any nutrient. Until you choose a
  diabetes type the app keeps using type 1, as before.
* **Lab results from a spreadsheet.** Lab results → *Import from a spreadsheet* reads a CSV file with a date
  column and one column per test ("Date, Potassium (mmol/L), Creatinine (umol/L)", with other names such as K,
  CO2 or HbA1c understood). The file is read on your device: every result is shown converted before
  anything is saved, you tick the ones to keep, and only those are sent, never the file or its other
  columns. Values that are not one number ("<0.5", ">90"), dates in the future, results outside the
  plausible range and results already saved are listed and left out. New route: `POST /api/labs/import`.
* **Try the app without installing it.** When the handbook is published on GitHub Pages, the app's demo is
  published beside it, at `demo/`, and every handbook page links to it ("Try the app (demo)"). It is the real
  app with a sample person and a month of meals, running entirely in your browser: nothing you type leaves
  the page, and reloading starts over. Its Learn links open the handbook pages next to it.

### For people who run a server

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
  ignored by git; a GitOps repository can use the base remotely (`//deploy/k8s?ref=v0.3.1`). CI renders
  and validates both.
* Docs: the optional AI is introduced in three questions (which model answers, what it may do, whose
  key pays and who can read the request), with a recommended starting setup for a home server with
  and without a GPU (`docs/ai.md`, and the handbook's AI page in plain words).
* Docs: Litestream (WAL streaming) works; the two commands that force a full checkpoint and a new
  generation are named (`docs/deployment.md`). A `TRUSTED_PROXIES` row for a proxy container on a
  shared rootless Podman network, and what trusting the whole subnet risks (`docs/security.md`). With
  more than one person signing in, `AUTH_MODE=proxy` behind an SSO provider with MFA is recommended
  until local accounts get a second factor.

### For contributors

* `requirements.txt` and `requirements-dev.txt`, kept through 0.3.0 so older instructions still worked,
  are gone. Install from the hash-locked files instead:
  `pip install --require-hashes --no-deps -r requirements-dev.lock` (or `requirements.lock` for the app
  alone).
* The constraints between lock files (dev on the runtime pins, the Zensical canary on the handbook
  build, Playwright on dev) moved from `-c ….lock` lines in the `*.in` files to the pip-compile command
  line in `scripts/lock.sh`; the locks themselves are unchanged. GitHub's Dependabot dependency graph
  reads every `requirements*.txt` and `*.in` file and failed on lines naming a `*.lock` file, which it
  never fetches. A test now keeps those files free of such lines.

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
