# Contributing to Kidney Health

Thank you for helping. This app is used by people living with chronic kidney disease (CKD) and type 1
diabetes, so a wrong number or a confusing screen can lead to an unsafe meal. The rules below exist for
that reason; please read them before your first change.

Ways to help: report a bug, suggest a feature, correct clinical content in the handbook or the app
(with a source), improve the docs, or send code. Use the issue forms
([bug](.github/ISSUE_TEMPLATE/bug_report.yml), [feature](.github/ISSUE_TEMPLATE/feature_request.yml),
[clinical content correction](.github/ISSUE_TEMPLATE/clinical_correction.yml)). **Security problems go
to a private report, never a public issue: see [SECURITY.md](SECURITY.md).**

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Contents

* [Read first](#read-first)
* [Set up](#set-up)
* [Tests](#tests)
* [The parity rule (demo mode)](#the-parity-rule-demo-mode)
* [Browser harnesses](#browser-harnesses)
* [The preview build](#the-preview-build)
* [Database migrations](#database-migrations)
* [Safety rules (health data)](#safety-rules-health-data)
* [Security rules](#security-rules)
* [How to …](#how-to-): [add a food](#add-a-food-to-the-builtin-database),
  [add a handbook page](#add-or-change-a-handbook-page), [change a guidance rule](#change-a-meal-guidance-rule),
  [add an AI preset](#add-an-ai-provider-preset), [add a setting](#add-a-setting)
* [Clinical content: policy and sign-off](#clinical-content-policy-and-sign-off)
* [Pull requests](#pull-requests)
* [Licensing of contributions](#licensing-of-contributions)

## Read first

* [`ARCHITECTURE.md`](ARCHITECTURE.md) is **the contract**: API shapes, data model, rules, file
  ownership and the v0.3 decisions. If something in it must change, change it first, in the same pull
  request.
* [`docs/dev/research/`](docs/dev/research/) holds the design notes behind the contract (01 security
  and images, 02 phone app and offline, 03 barcodes and photos, 04 optional AI, 05 personalised targets,
  06 meal guidance, 07 accounts and settings, 08 the handbook). Each ends with a security review and
  a fact-check that override its earlier text.
* [`CLAUDE.md`](CLAUDE.md) lists the rules every change keeps; AI coding agents also read
  [`AGENTS.md`](AGENTS.md).
* [`docs/README.md`](docs/README.md) lists every document; [`docs/ROADMAP.md`](docs/ROADMAP.md) lists
  what is planned for later versions, with the design note that defers it.

For anything bigger than a small fix, open an issue first and say which part of the contract or which
note it touches.

## Set up

Python 3.11 or newer (CI runs 3.12 and 3.14, the image's Python) and, for the parity check, Node 22.

```bash
git clone https://github.com/ksullivan86/kidney-health.git
cd kidney-health
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-dev.lock     # hash-locked; no other source
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers  # DATA_DIR defaults to ./data-local
```

The first start prints a one-time setup code (`FIRST-RUN SETUP: … enter the code …`); open
<http://localhost:8000>, enter it and create the first admin. `./data-local/` is gitignored; delete it
to start over. To see the patient handbook at `/learn` as well, build it first
([`handbook/README.md`](handbook/README.md#build-and-check)).

Dependencies are hash-locked: `requirements.in` → `requirements.lock` (runtime) and
`requirements-dev.in` → `requirements-dev.lock`, regenerated only with `scripts/lock.sh`. The only
runtime dependency v0.3 added is `cryptography`; propose any new one in an issue first.

## Tests

```bash
python -m pytest                    # the whole suite; must pass with no network
node tests/js/run_vectors.mjs       # the browser's copies of the server logic match the server
```

* **Every behaviour change ships with tests**, including failure paths, limits and edge cases, not
  only the happy path. Tests never use the network: outbound calls go through fakes and recorded
  fixtures (`tests/fixtures/`).
* Useful subsets: `python -m pytest tests/test_auth_coverage.py tests/test_isolation.py` (every route
  needs sign-in; nobody sees another person's data), `tests/guidance/`, `tests/test_ai_*.py`,
  `tests/test_handbook_content.py`.
* CI (`.github/workflows/ci.yml`) also runs actionlint, hadolint, kubeconform, shellcheck and zizmor,
  builds and smoke-tests both images, and builds and checks the handbook. Run the tools you have
  locally when you touch `.github/`, `deploy/` or `handbook/`.

## The parity rule (demo mode)

The demo (`?mock=1`) and the self-contained preview run the whole UI against an in-page copy of the
server: JavaScript twins of server logic in `app/static/js/engine/*` and the demo API in
`app/static/js/mock/*`. **When you change server logic that has a twin, change the twin in the same
pull request** and keep them equal with the shared vector files:

| Server | Twin | Vectors (generator) |
|---|---|---|
| `app/nutrients.py` (warnings, ratings, rounding) | `js/engine/rules.js` | `tests/data/rules_vectors.json` (`gen_rules_vectors.py`) |
| `app/settings_registry.py`, `app/settings_store.py` | `js/engine/settings.js` | `settings_vectors.json` (`gen_settings_vectors.py`) |
| `app/targets.py`, `app/target_rules.py` | `js/engine/targets.js` | `targets_vectors.json` (`gen_targets_vectors.py`) |
| `app/units.py`, `app/kidney_function.py` | `js/engine/kidney_function.js` | `kidney_function_vectors.json` (`gen_kidney_function_vectors.py`) |
| `app/guidance/*` | `js/engine/guidance/*.js` | `guidance_vectors.json` (`gen_guidance_vectors.py`) |
| `app/gtin.py`, `app/textclean.py`, `app/additives.py`, `app/off.py` texts | `js/engine/gtin.js`, `textclean.js`, `additives.js`, `off.js` | `barcode_vectors.json` (`gen_barcode_vectors.py`) |

```bash
python3 tests/data/gen_guidance_vectors.py           # regenerate after a server change, then review the diff
python3 tests/data/gen_guidance_vectors.py --check   # what the tests do: fail when the file is stale
node tests/js/run_vectors.mjs                         # the JS side; fix the twin until it passes
```

Both sides run in CI. Never edit a vector file by hand, and never "fix" a parity failure by changing
the harness or the vectors: fix the twin (or the server, if the server is wrong).

## Browser harnesses

[`tools/e2e/`](tools/e2e/README.md) holds browser harnesses run by hand before a release or after a
change to the frontend, the demo API or the server's routes (Playwright for Python and a Chromium; see
their README): `parity.py` (the demo API against a real server, about 6,500 comparisons), `sandbox.py`
(the preview inside an emulated sandboxed host), `regress.py` (the installed app end to end),
`learn.py` (the handbook at `/learn`, also in CI), `device.py` (barcodes, photos, AI cards, the offline
outbox) and `guidance_perf.py` (the guidance twin's speed with a slowed-down CPU). Say in your pull
request which ones you ran.

## The preview build

```bash
python3 scripts/build_preview.py      # writes build/kidney-diet-log.html (gitignored)
python3 scripts/build_preview.py --pages build/demo   # the GitHub Pages demo: the same app as a static site
```

It inlines `app/static/index.html`'s stylesheets and scripts in order, plus `data/foods.json`, into one
HTML fragment that runs with no server and no network. `tests/test_preview_build.py` builds it on every
test run. Keep every new script loadable this way: plain scripts under `window.KH`, no bundler, no ES
module imports, no inline scripts (the builder refuses them). The Pages demo keeps the files as files
under the app's CSP (a `<meta>` element), so markup links must not be absolute paths either: the builder
rewrites the known ones (`/learn/`) and refuses any other.

## Database migrations

Schema changes are steps in `app/migrations/` (`mNNN_<topic>.py`, applied in order and recorded in
`meta.schema_version`; the rules are in the package docstring, the numbering in `ARCHITECTURE.md`,
"Database migrations").

* **Append-only.** Never edit, renumber or delete a released step; add the next one.
* **Idempotent.** Check `PRAGMA table_info` (`app.db.add_column_if_missing`) before `ALTER TABLE`, use
  `IF NOT EXISTS`, and never put an index or trigger on a column added by a later `ALTER TABLE` into
  `SCHEMA` (put it in `migrate()`).
* **Tested by upgrading a populated previous schema**: build a database at the step before yours with
  real-looking rows (two people, log entries, foods, saved meals), run the migration, and check the data
  survived and the new constraints hold. See `tests/test_migration_v3.py`, `test_migration_m004.py`,
  `m006`, `m007`.
* Every table that holds a person's data has `user_id … REFERENCES users(id) ON DELETE CASCADE`, and
  the export (`app/account.py`) and account deletion cover it.

## Safety rules (health data)

* **No insulin or medication dosing**, anywhere: no doses, units, ratios, correction factors or "stop
  taking". Carbohydrate is shown in grams only.
* **Never block, delay or warn against treating a low.** Low-treatment foods get no carbohydrate
  warning, are never limited by a budget, and the "Treating a low" card stays available with guidance
  switched off and offline. Text that may describe a low never goes to AI.
* **Every clinical number is traceable to a cited source** (the handbook's `sources.yml`,
  `docs/research/`, `app/target_rules.py`, `app/guidance/rules.py`). The project's own choices are
  labelled as such ("expert opinion", "design choice").
* **Targets come from the person's care team.** Suggestions are starting points, labelled "discuss
  with your care team", never saved without the person's tap; AI never changes a number.

## Security rules

* Every `/api` route except the public auth routes depends on `current_user` (`app/auth/deps.py`);
  every query takes the signed-in person's `user.id`; another person's row answers **404**, exactly like
  a missing one. `tests/test_auth_coverage.py` walks every route.
* Secrets are write-only in the API (never returned, logged or audited; shown as "ends in 9xQz"), sealed
  with `app/crypto.py`, resolved by `app/credentials.py`. Log lines carry ids and metadata only, never
  health data or secrets.
* Configuration only through `app/config.py` (environment) and the settings registry
  (`app/settings_registry.py`); no other settings store.
* The browser loads nothing from another origin: no CDN, no inline scripts or `style=` attributes
  (CSP with Trusted Types). Third-party browser code is vendored in `app/static/vendor/` with SHA-256
  pins in its README.
* Outbound HTTP only through the SSRF-checked transports (`app/egress.py` for USDA and Open Food Facts,
  `app/ai/transport.py` for AI), never following redirects, with capped answers. Every new outbound host
  goes into `docs/network-allowlist.md`.
* State-changing requests need `X-Requested-With: kidney-health` and a same-origin `Origin`
  (`app/security.py`); keep using `KH.api`/`KH.request` in the frontend.
* Workflows: `permissions: {}` at the top, every action pinned to a full commit SHA, no
  `pull_request_target`, no caches (`tests/test_deploy.py` checks).

## How to …

### Add a food to the builtin database

1. Find the food in USDA SR Legacy's `food.csv` and note its `fdc_id` (never guess one). Items USDA
   does not carry (glucose tablets, salt substitutes) use `manual_id` with label-derived nutrients.
2. Add an entry to `scripts/curated_foods.py` (name, category, household serving, flags, a one-line
   `kidney_notes` for limit/avoid foods; a guidance `role` only when the derived one is wrong).
3. Run `python3 scripts/build_food_db.py` (add `--version YYYY-MM-DD.N` when regenerating twice on one
   day) and commit `data/foods.json`. `tests/test_food_db.py` checks flags against the numbers.
4. The rules vectors embed every builtin food and the guidance vectors a subset: run each generator
   in `tests/data/` with `--check`, regenerate the stale ones, and run `node tests/js/run_vectors.mjs`.
   The handbook's menus and tables come from the same file (`scripts/build_handbook.py --check`).

### Add or change a handbook page

Follow [`handbook/README.md`](handbook/README.md#edit-a-page): start from a template, fill every front
matter key, cite each fact from `handbook/sources.yml`, add the page to `nav`, and run the four checks
(`scripts/build_handbook.py --check`, `tests/test_handbook_content.py`, `mkdocs build --strict`, the
link checker). New pages start as `status: draft`. Pages the app links to are listed in
`app/guidance/topics.py`; `tests/test_learn_links.py` fails if a link has no page.

### Change a meal-guidance rule

Follow [`docs/guidance.md`, "Changing a rule"](docs/guidance.md#changing-a-rule): change the number in
`app/guidance/rules.py` with its basis in `RULE_DOCS`, bump `RULES_VERSION`, regenerate
`tests/data/guidance_vectors.json` and the rules table (`python3 scripts/guidance_rules_doc.py`), update
the JavaScript twin until the vectors pass, and update the golden tests in `tests/guidance/` with the
evidence (or say it is a design choice). A rule may shape suggestions; it must never create a warning,
hide one, or touch a low treatment.

### Add an AI provider preset

1. Add a `Preset` to `PRESETS` in `app/ai/presets.py`: `kind` (`cloud`, `self_hosted`, `agent`,
   `custom`), default base URL, token field, structured-output mode, temperature, timeout, extra body
   fields, and `user_allowed` only for a cloud API a person may use with their own key.
2. A new cloud service needs its own consent line in `POLICY_LINES`; changing any line bumps
   `POLICY_VERSION` (everyone is asked to agree again).
3. Record a real answer as a fixture in `tests/fixtures/ai/` and add the preset to the request-body and
   parsing tests in `tests/test_ai_client.py`; the golden set (`tests/test_ai_golden.py`) must still
   pass.
4. Document it in [`docs/ai.md`](docs/ai.md) (presets table and a recipe) and add its host to
   [`docs/network-allowlist.md`](docs/network-allowlist.md). The UI lists presets from the server, so
   no frontend change is needed. A model is listed as recommended only after a live evaluation that
   meets the gates in `docs/ai.md` ("For contributors").

### Add a setting

Register it once in `app/settings_registry.py` (type, default, scope, optional env lock, label and
help), add the same entry to the twin `app/static/js/engine/settings.js`, regenerate
`tests/data/settings_vectors.json` (`gen_settings_vectors.py`), and document it (the feature's page in
`docs/`, and `docs/deployment.md` when it has an environment variable). Settings → Admin → Server
settings lists every admin-editable key by itself (add it to a group in `GROUPS` in
`app/static/js/views/settings.js`, or it appears under "Other"); a personal setting needs its own
labelled control in the Settings view.

## Clinical content: policy and sign-off

* The handbook and the app support the care team and never replace it: education, not medical advice,
  not a medical device.
* Every clinical statement cites a source with the exact place (guideline recommendation, table, label
  section). Prefer primary sources (KDIGO, KDOQI, ADA, ISPD), then labels and government pages, then
  charity patient pages; paraphrase, never copy.
* Shared numbers (treating a low, potassium tiers, ketones, sodium, protein) are identical everywhere;
  change one only together with every page and the code that uses it, and record why in
  `handbook/REVIEW.md` ([house style](handbook/README.md#house-style)).
* **Sign-off:** every page shows "Draft: not yet reviewed by a clinician" until a named reviewer with the
  right qualification (renal dietitian, nephrologist, diabetes specialist or CDCES, as listed in
  [`handbook/README.md`](handbook/README.md#clinical-review-and-sign-off)) sets `status: reviewed`,
  `reviewed_by` and `reviewed_on`. A reviewed page goes back to draft when its clinical content
  changes. The open decisions for clinicians are indexed at the top of `handbook/REVIEW.md`.
* A correction to clinical content (handbook, warnings, targets, guidance rules) needs a source; use the
  [clinical content correction](.github/ISSUE_TEMPLATE/clinical_correction.yml) form or say it in the
  pull request. Clinicians reviewing pages are very welcome: say so in an issue.

## Pull requests

* One topic per pull request; describe what and why, link the issue, and fill in the
  [template](.github/pull_request_template.md) (test plan and safety checklist).
* CI must be green; the maintainer may ask for the browser harnesses.
* Update the docs a person can see change: `ARCHITECTURE.md` (the contract), the relevant page in
  `docs/`, the handbook's "Using the app" pages, and a line in `CHANGELOG.md` under `## Unreleased` (add
  the heading at the top if it is missing).
* Keep the existing style: plain words, type hints and docstrings on public functions, clear error
  messages that say what to do, accessibility (labels, focus, 44 px targets, contrast) and privacy as
  requirements.

## Licensing of contributions

By contributing you agree that your contribution is licensed under the project's licences: code under
the [PolyForm Noncommercial License 1.0.0](LICENSE), and handbook text (everything under
`handbook/docs/`, `handbook/includes/` and `handbook/data/`) under
[CC BY-NC-SA 4.0](handbook/LICENSE). Only contribute work you have the right to license this way;
copied third-party text, recipes, tables or figures are not accepted (cite and paraphrase instead).
