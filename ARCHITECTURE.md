# Architecture & API Contract

This file is the contract that every component follows. Backend, frontend, food
database, and deployment are developed against it. If something here must change,
change this file first.

## Purpose

A self-hosted (Podman / Kubernetes) food log for one person living with chronic
kidney disease (CKD) **and type 1 diabetes**. The person logs what they eat; the app
totals the nutrients a renal diet restricts (potassium, phosphorus, sodium,
protein, fluid) and the ones a type 1 diabetic must count (carbohydrate per meal),
compares them to targets set with their dietitian, and warns when a single food or
the day's running total needs careful consideration.

Non-goals (v1): multi-user accounts (v0.3 adds accounts for a household: "M1 API"), insulin dose
calculation, medical advice.
The UI must say that targets come from the person's care team.

## Stack

* Python 3.12, FastAPI, Pydantic v2, SQLite (stdlib `sqlite3`, no ORM), uvicorn.
* Frontend: static `index.html` + plain scripts and styles (v0.3: `js/`, `css/`; "Frontend modules") served by FastAPI.
  **No build step, no CDN, no external requests from the browser.** Works offline on a LAN.
* One container image. All state lives in `DATA_DIR` (default `/data`) as `kidney.db`.
  File modes do not depend on the umask: `Settings.ensure_data_dir` makes `DATA_DIR` `0770` (and removes "other" access from an
  existing folder the process owns); `db.init_db` creates `kidney.db` at `0600` and `db.secure_database_files` sets it and its
  `-wal` and `-shm` files to `0600`, like `secret.key`, backups and exports. A mode the app cannot fix is a log warning, never a failed start.
* Tests: `pytest` with `httpx2` (Starlette `TestClient`; v0.3 moved the app from `httpx` to `httpx2`).

## Repository layout and file ownership

```
ARCHITECTURE.md             this contract
README.md                   overview, quick start, screenshots-less feature list
docs/diet-guide.md          the renal + type 1 diabetes diet write-up (research)
docs/research/*.md          research notes behind the guide
docs/deployment.md          Podman, Quadlet, Kubernetes (Talos) instructions
docs/network-allowlist.md   egress domains the project needs
app/__init__.py
app/main.py                 FastAPI app factory, static mount, routers, startup load
app/openapi_doc.py          the OpenAPI document made honest: operation ids, 400 not 422, the shared error shape, security schemes (design note 14)
app/api_version.py          API_VERSION, the integer that is raised on a breaking change ("The API document and GET /api/meta")
app/meta.py                 GET /api/meta: versions, what the signed-in person can use now, the nutrient registry, the meals
app/brand.py                the brand strings in one place: names, cookie names, token prefixes, CSRF value, DB filename, export format, user agents, HKDF labels ("Brand strings")
app/sharing.py              read-only sharing with a caregiver or dietitian: share links, /api/me/shares, /api/shared and the read routes ("Sharing")
app/pairing.py              the iPhone app's pairing link in the QR code of a new device token: link() and the reference parse() ("Pairing the iPhone app")
scripts/gen_openapi.py      writes / --check docs/api/openapi.json, the checked-in OpenAPI document (docs/api/README.md)
app/config.py               settings from env and *_FILE secrets (v0.3: the full list is at its top; deploy/.env.example)
app/db.py                   sqlite connection helper; runs the ordered steps in app/migrations/ ("Database migrations")
app/models.py               Pydantic request/response models (shapes below)
app/nutrients.py            PURE FUNCTIONS: nutrient registry, daily status, alerts; also the import surface of the two modules below
app/nutrient_core.py        the registry, display rounding and number formatting that nutrients.py and rules_kidney.py share (note 14 §2.2)
app/rules_kidney.py         the kidney/T1D rule pack: per-serving thresholds, food_warnings, kidney_rating, meal-carb alerts, suggested targets
app/foods.py                food search/CRUD, builtin JSON import, USDA proxy
app/log.py                  log entries (eaten/planned), day/range/period summaries, mark-eaten, copy-day, CSV export
app/periods.py              PURE FUNCTIONS (v0.2): period averages, previous period, interdialytic interval, week bounds
app/meals.py                saved meals (templates), from-log, apply, shopping list (v0.2)
app/profile.py              profile + targets (+ dialysis days, week start)
app/data_import.py          import of a person's own export.json: POST /api/me/import ("Import of `export.json`")
app/static/index.html       shell; v0.3 scripts in js/ and styles in css/ ("Frontend modules" below)
data/foods.json             builtin food database (generated, committed)
scripts/build_food_db.py    downloads USDA SR Legacy CSV zip and writes data/foods.json
scripts/curated_foods.py    the curated list (fdc_id, display name, serving, category, flags)
tests/conftest.py           fixture food database + TestClient
tests/test_nutrients.py     pure rules incl. suggest_targets vs docs/research/targets_by_stage.json
tests/test_api.py
tests/test_periods.py       period maths
tests/test_planning.py      planned entries, saved meals, summary, shopping (API)
tests/test_migrations.py    v0.1 database upgrades in place
tests/test_food_db.py       invariants of the committed data/foods.json (flags vs numbers, guide records)
deploy/Containerfile        published image (Chainguard by digest); Containerfile.debian = CI-built fallback
deploy/compose.yaml         rootless compose (+ compose.caddy.yaml, compose.ai-ollama.yaml, compose.stt-whisper.yaml overlays)
deploy/quadlet/kidney-health.container
deploy/k8s/*.yaml (+ kustomization.yaml)   PSA restricted, NetworkPolicy, HTTPRoute
.github/workflows/ci.yml    pytest 3.12+3.14+3.15, JS parity, linters, image smoke test + Grype gate (never pushes)
.github/workflows/release.yml  build by digest -> scan -> sign/attest (public repo) -> tags (v0.3 decision 7)
SECURITY.md, docs/security.md, docs/https.md, scripts/verify-image.sh   (v0.3, deploy owner)
CHANGELOG.md                user-facing changes per version (v0.3)
CONTRIBUTING.md, CODE_OF_CONDUCT.md, AGENTS.md   contributor rules and how-tos; Contributor Covenant 2.1; agents' short rules
docs/README.md, docs/maintainers.md, docs/ROADMAP.md   index of every doc; release process and repo settings; deferred work
.github/ISSUE_TEMPLATE/, .github/pull_request_template.md   issue forms (bug, feature, clinical correction) and the PR checklist
tools/e2e/                  harnesses run by hand: parity.py, sandbox.py, regress.py, device.py, journey.py (whole v0.3 story
                            on a real server), upgrade.py (v0.2 and v3 databases), learn.py, guidance_perf.py, mcp_smoke.py
                            (the assistant's MCP server over HTTP)
                            (+ khserver.py, replay_app.py = the app with USDA answered from tests/fixtures/usda, README.md)
pyproject.toml, requirements{,-dev}.in + .lock (hash-locked by scripts/lock.sh), .gitignore
```

Owners (parallel build): **food-db** owns `scripts/`, `data/`; **backend** owns
`app/*.py`, `tests/`; **frontend** owns `app/static/`; **deploy** owns `deploy/`,
`.github/`, `docs/deployment.md`; **research** owns `docs/diet-guide.md`,
`docs/research/`. Nobody else edits another owner's files.

## Nutrient registry (single source of truth: `app/nutrients.py`)

The registry and the display rounding are defined in `app/nutrient_core.py`; the kidney and type 1 diabetes rules
(thresholds, `food_warnings`, `kidney_rating`, the per-meal carbohydrate alerts, `suggest_targets`, the CKD, dialysis and
diabetes choices and the food flags) in `app/rules_kidney.py` (design note 14 §2.2). `app/nutrients.py` re-exports both,
so `from .nutrients import X` and `nutrients.X` name every one of them, as before.

Keys are used verbatim in JSON, in `data/foods.json`, in SQLite columns and in the UI.

| key              | label         | unit | role        |
|------------------|---------------|------|-------------|
| `calories_kcal`  | Calories      | kcal | goal        |
| `protein_g`      | Protein       | g    | range (min/max; CKD restricts, dialysis requires more) |
| `fat_g`          | Fat           | g    | info        |
| `sat_fat_g`      | Saturated fat | g    | info        |
| `carbs_g`        | Carbohydrate  | g    | track (type 1: counted per meal, daily goal) |
| `fiber_g`        | Fiber         | g    | info (goal) |
| `sugar_g`        | Sugars        | g    | info        |
| `sodium_mg`      | Sodium        | mg   | limit (max) |
| `potassium_mg`   | Potassium     | mg   | limit (max) |
| `phosphorus_mg`  | Phosphorus    | mg   | limit (max) |
| `calcium_mg`     | Calcium       | mg   | info (max)  |
| `fluid_ml`       | Fluid         | mL   | limit (max), only counted for foods with `counts_as_fluid` |

All food nutrient values are **per one serving** of the food (`serving_g` grams).
A log entry multiplies by `servings`.

### Per-serving thresholds (what makes a single food "needs careful consideration")

Returned as `warnings` on every food and log entry. Levels: `"medium"`, `"high"`.

| nutrient        | medium           | high                       | basis |
|-----------------|------------------|----------------------------|-------|
| potassium_mg    | 101–200 mg, or flagged `potassium_additive` with potassium not listed (`null`) | > 200 mg | renal dietitian low/medium/high potassium food convention; additive potassium is ~90 % absorbed (contract item 9) |
| phosphorus_mg   | 101–150 mg       | > 150 mg, or any food flagged `phosphate_additive` | NKF guidance; additive phosphorus is ~90–100 % absorbed |
| sodium_mg       | 141–400 mg       | > 400 mg                   | FDA "low sodium" ≤ 140 mg; 20 % DV ≈ 460 mg |
| carbs_g         | 15–30 g ("1–2 carb choices"), or flagged `high_gi` with < 15 g | > 30 g, or flagged `high_gi` with ≥ 15 g | type 1 carb counting; the GI upgrade needs one carb choice to act on (per-portion glycaemic load), so a condiment's 4 g is a note, not a red |
| protein_g       | 15–25 g          | > 25 g                     | large protein portion for restricted intake |

Flags (strings, set in curated data or by the user on custom foods):
`phosphate_additive`, `high_gi`, `counts_as_fluid`, `avoid_ckd` (e.g. star fruit),
`hypo_treatment` (fast carbs that are also low potassium, e.g. glucose tablets),
`low_potassium_fruit`, `processed`, and (v0.3) `potassium_additive`: set by the additive scan
(`app/additives.py`) on scanned and hand-entered foods that list a potassium salt such as potassium
chloride (E508) or potassium lactate (E326). With potassium unknown it gives the `medium` warning
"Contains a potassium additive; potassium not listed"; with potassium listed the normal thresholds
apply ("M2 API: barcode").
Two flags only steer meal guidance and give no warning: `ingredient` (flour, oil, salt: only ever added to
other food) and (v0.3) `alcohol` (beer, wine, spirits: with insulin, alcohol can cause lows hours later, ADA
Standards of Care 2026 §5, 5.18–5.19). Guidance never suggests either on its own: not in What fits, swaps,
built plans, the energy note, usual meals or AI ideas (a meal the person saved keeps its drink). The curated
beers, wines and spirits carry `alcohol`; Open Food Facts products tagged `en:alcoholic-beverages` and USDA
records with ≥ 0.4 g ethanol per 100 g (about 0.5 % by volume) or named "Alcoholic beverage, …" get it on
import; anyone can set it on a custom food.

Flags must agree with the serving they are shown next to (`scripts/build_food_db.py` and
`tests/test_food_db.py` enforce it): a `low_potassium_fruit` serving stays ≤ 200 mg potassium
(berries and grapes are served at ½ cup, pears as "1 small") and a `hypo_treatment` serving is a
rescue portion of ≤ 20 g carbohydrate (sodas at 4 fl oz, sports drink at 8 fl oz), because the
flag switches the carbohydrate warning off.

`avoid_ckd` always yields a `high` warning with the food's `kidney_notes` text.
`hypo_treatment` foods get **no carbohydrate warning** (neither the 15/30 g thresholds nor
the `high_gi` upgrade): fast carbohydrate is the point of treating a low and the diet guide
says hypo treatments are never warned against. Their potassium / phosphorus / sodium
warnings still apply so the lowest-potassium option can be chosen.

`kidney_rating` is computed, never stored: `"red"` if any high warning,
`"yellow"` if any medium, else `"green"`.

### Daily status

For each nutrient with a target: `fraction = total / target`.
`level = "ok"` if fraction < `warn_fraction` (profile, default 0.8), `"caution"`
if `warn_fraction ≤ fraction ≤ 1.0`, `"over"` if > 1.0. For `protein_g` with a
`min`, also `"low"` if end-of-day and below min is **not** computed server-side —
just report `fraction` against max and include `min` so the UI can show the range.

### Suggested targets (`nutrients.suggest_targets(weight_kg, ckd_stage, dialysis, diabetes, height_cm=None)`, defined in `app/rules_kidney.py`)

*Rewritten in v0.3 (note 05; see "M2 API: targets and labs" at the end of this file and
`docs/targets-and-labs.md`).* Starting points only; the UI labels them "discuss with your care team"
and nothing is saved until the person saves the profile. The rules live in `app/targets.py` (pure,
`today` injected) with every number, source and note text in `app/target_rules.py`;
`suggest_targets()` (`app/rules_kidney.py`, importable as `nutrients.suggest_targets`) keeps its v0.2 signature and `{"targets", "notes"}` shape for existing
callers and applies the same rules without the v0.3 inputs. `dosing_weight()` (same module) returns the
**reference weight** `(kg, basis)`: per kg means per kg of a sex-neutral reference weight (KDOQI 2020
leaves the choice to the care team, 1.1.6): the actual weight between BMI 18.5 and 25 or without a
height, else KDOQI Table 5's adjusted weights on the BMI-25 / BMI-18.5 weight (`adjusted_above_bmi25`,
`adjusted_below_bmi18_5`, `actual`, `actual_no_height`), rounded to 0.1 kg. The first note always
states the weight basis.

Without the v0.3 inputs (`docs/research/targets_by_stage.json` holds these rows and
`tests/test_nutrients.py` compares the code with it row by row):

| stage / dialysis | protein g/kg (min–max) | potassium mg | phosphorus mg | sodium mg | fluid mL | kcal/kg | calcium mg |
|---|---|---|---|---|---|---|---|
| 1, 2 (no dialysis) | 0.8–1.0 | 4000 (informational) | 1000 | 2000 | null | 30 | 1000 |
| 3a | 0.8 with diabetes (0.6–0.8 without) | 4000 | 1000 | 2000 | null | 30 | 1000 |
| 3b | 0.8 with diabetes (0.6–0.8 without) | 3500 | 1000 | 2000 | null | 30 | 1000 |
| 4 | 0.8 with diabetes (0.6–0.8 without) | 3000 | 1000 | 2000 | null | 30 | 1000 |
| 5, no dialysis | 0.8 with diabetes (0.6–0.8 without) | 2500 | 900 | 2000 | null | 30 | 1000 |
| hemodialysis | 1.0–1.2 | 2500 | 1000 | 2000 | 1500 (1000 + ~500 urine) | 30 | 1000 |
| peritoneal | 1.0–1.2 | 3500 | 1000 | 2000 | 2000 | 30 | 1000 |

* protein_g: `{"min", "max"}`, each bound `round_half_up(g_per_kg × reference weight)`; with diabetes at
  stages 3a–5 without dialysis it is 0.8 g/kg (min = max, shown "about X g/day"), never lower (v0.3
  item 10; ADA 2026 Rec 11.3, KDIGO 2022 Rec 3.1.1, KDIGO 2024 Rec 3.3.1.1). Notes cite the published
  KDOQI 2020 numbering: protein 3.0.1–3.0.4, energy 3.1.1.
* potassium_mg: review ceilings; every potassium note ends with "Only restrict potassium if your blood
  potassium is high; your care team sets the number."
* calories_kcal: kcal/kg × reference weight, rounded to 10 kcal. carbs_g: round_half_up(cal × 0.45 / 4);
  carbs_per_meal_g: carbs / 4 rounded to 5 g (minimum 15). fiber_g: `{"min": round(14 × cal / 1000)}`
  (min only: shown as progress toward a goal, never "over").
* sodium_mg 2000; phosphorus_mg and calcium_mg as in the table; fluid_ml `null` (no limit) unless dialysis.

## Data model (SQLite)

```sql
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL DEFAULT '',
  weight_kg REAL,
  height_cm REAL,
  ckd_stage TEXT NOT NULL DEFAULT '3b',        -- '1','2','3a','3b','4','5'
  dialysis TEXT NOT NULL DEFAULT 'none',       -- 'none','hemodialysis','peritoneal'
  diabetes TEXT NOT NULL DEFAULT 'type1',      -- 'none','type1','type2'
  warn_fraction REAL NOT NULL DEFAULT 0.8,
  targets_json TEXT NOT NULL DEFAULT '{}',     -- {"potassium_mg": 2500, "protein_g": {"min": 42, "max": 56}, ...}
  dialysis_days_json TEXT NOT NULL DEFAULT '[]', -- v0.2: weekdays of dialysis sessions, 0=Mon .. 6=Sun, e.g. [0,2,4]
  week_start TEXT NOT NULL DEFAULT 'monday',   -- v0.2: 'monday' | 'sunday' (Plan view grid)
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS foods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  brand TEXT,
  category TEXT,
  source TEXT NOT NULL,                        -- 'builtin','usda','custom'
  fdc_id INTEGER,
  serving_desc TEXT NOT NULL,                  -- "1 medium (118 g)"
  serving_g REAL NOT NULL,
  calories_kcal REAL, protein_g REAL, fat_g REAL, sat_fat_g REAL, carbs_g REAL, fiber_g REAL, sugar_g REAL,
  sodium_mg REAL, potassium_mg REAL, phosphorus_mg REAL, calcium_mg REAL, fluid_ml REAL,
  flags_json TEXT NOT NULL DEFAULT '[]',
  kidney_notes TEXT,
  hidden INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS foods_name ON foods(name);
CREATE UNIQUE INDEX IF NOT EXISTS foods_builtin_fdc ON foods(source, fdc_id) WHERE source='builtin';
CREATE TABLE IF NOT EXISTS log_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,                          -- 'YYYY-MM-DD' local date chosen by the client
  meal TEXT NOT NULL,                          -- 'breakfast','lunch','dinner','snack'
  food_id INTEGER NOT NULL REFERENCES foods(id),
  food_name TEXT NOT NULL,                     -- snapshot
  servings REAL NOT NULL,
  grams REAL,                                  -- optional, if the user entered weight
  note TEXT,
  status TEXT NOT NULL DEFAULT 'eaten',        -- v0.2: 'eaten' | 'planned'
  -- snapshot of nutrients for this entry (already multiplied by servings)
  calories_kcal REAL, protein_g REAL, fat_g REAL, sat_fat_g REAL, carbs_g REAL, fiber_g REAL, sugar_g REAL,
  sodium_mg REAL, potassium_mg REAL, phosphorus_mg REAL, calcium_mg REAL, fluid_ml REAL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_date ON log_entries(date);
CREATE TABLE IF NOT EXISTS meal_templates (   -- v0.2: saved meals
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  note TEXT,
  items_json TEXT NOT NULL,                    -- [{"food_id": 12, "servings": 1.5}, ...]
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- e.g. foods_json_version, schema_version
```

**Migrations.** `CREATE TABLE IF NOT EXISTS` never adds columns to an existing
database. `app/db.py` keeps `meta.schema_version` and an ordered list of migration
steps; each step inspects `PRAGMA table_info(<table>)` and issues `ALTER TABLE ... ADD COLUMN`
only when the column is missing, so a v0.1 `kidney.db` upgrades in place on startup
and a fresh database gets the full schema. Never drop or rename columns.

Builtin foods are loaded from `data/foods.json` at startup (upsert by `fdc_id`
for `source='builtin'`; a `version` string in the JSON is stored in `meta` and the
import is skipped if unchanged). Fluid: `fluid_ml` is the water grams of the
serving for foods flagged `counts_as_fluid`, else 0.

## `data/foods.json` shape

```json
{
  "version": "2026-10-05.1",
  "source": "USDA FoodData Central, SR Legacy (April 2018 release) ...",
  "foods": [
    {
      "fdc_id": 173944,
      "name": "Banana, raw",
      "category": "Fruits",
      "serving_desc": "1 medium (118 g)",
      "serving_g": 118,
      "nutrients": {"calories_kcal": 105, "protein_g": 1.29, "fat_g": 0.39, "sat_fat_g": 0.13,
                    "carbs_g": 26.95, "fiber_g": 3.1, "sugar_g": 14.43, "sodium_mg": 1,
                    "potassium_mg": 422, "phosphorus_mg": 26, "calcium_mg": 6, "fluid_ml": 0},
      "flags": [],
      "kidney_notes": "High potassium; a renal dietitian usually suggests apples, berries or grapes instead."
    }
  ]
}
```

Categories (exact strings): `Fruits`, `Vegetables`, `Grains & Breads`,
`Dairy & Alternatives`, `Meat, Poultry & Eggs`, `Fish & Seafood`, `Legumes, Nuts & Seeds`,
`Beverages`, `Sweets & Snacks`, `Condiments & Sauces`, `Prepared & Fast Food`, `Diabetes supplies`.

## HTTP API (all JSON, prefix `/api`)

Errors: `{"detail": "message"}` with 400/404/409/503.

v0.3 request rules (`app/security.py`, note 01 §5.5 and §10, note 07 §4.8): an unknown `Host` is
`400 {"detail": "Unknown host"}` (localhost, IP literals, the `PUBLIC_URL` host and `ALLOWED_HOSTS`
pass); every unsafe `/api` request (POST/PUT/PATCH/DELETE) must send `X-Requested-With:
kidney-health` and a same-origin `Origin`/`Sec-Fetch-Site`, and cross-site or same-site `/api`
reads are refused, all with `403`; bodies over `MAX_BODY_BYTES` are `413`; `/api` responses are
`Cache-Control: no-store`; `/docs` and `/openapi.json` exist only with `ENABLE_API_DOCS=true` (the checked-in
`docs/api/openapi.json` needs neither: "The API document and `GET /api/meta`" below). The one
bearer-only paths, exactly `/mcp`, `/push/v1/body` and `/push/v1/check` (`security.BEARER_PATHS`, "Assistant MCP server" and "Device tokens
and `/push/v1`" below), skip the cookie checks (`X-Requested-With`, `Sec-Fetch-Site`: they never read a cookie) but answer
`403` to a foreign `Origin` on every method.

### Health
* `GET /healthz` → `{"status":"ok","foods": <count>}`
* `GET /api/meta` (signed in) → the versions, what this person can use now, the nutrient registry and the meal names; see "The API document
  and `GET /api/meta`" below.

### Profile
* `GET /api/profile` → Profile
* `PUT /api/profile` body ProfileUpdate (any subset of fields) → Profile
* `GET /api/profile/suggested-targets` → `{"targets": Targets, "notes": [string]}` computed
  from the stored profile (400 if weight missing); v0.3 adds `rules`, `derived`, `missing_inputs`,
  `alerts` and the 422 refusals ("M2 API: targets and labs")

```json
Profile = {
  "id": 1, "name": "", "weight_kg": 70, "height_cm": null,
  "ckd_stage": "3b", "dialysis": "none", "diabetes": "type1",
  "ckd_stage_chosen": true, "diabetes_chosen": true,   // v0.3.1, schema step 8: false = "Not chosen yet"
  "warn_fraction": 0.8,
  "about_tolerance_pct": 0,   // v0.3.1, schema step 9: 0–10 % above an "about" target still on target
  "dialysis_days": [0, 2, 4],          // v0.2, weekdays 0=Mon..6=Sun; [] when not on hemodialysis
  "week_start": "monday",              // v0.2
  "targets": {
    "calories_kcal": 2100, "protein_g": {"min": 42, "max": 56}, "carbs_g": 236,
    "carbs_per_meal_g": 60, "sodium_mg": 2000, "potassium_mg": 2500,
    "phosphorus_mg": 900, "calcium_mg": 1000, "fluid_ml": null
  },
  "updated_at": "2026-10-05T12:00:00Z"
}
```
Every target may be a number, `{"min","max"}`, or `null` (= not tracked).

### Foods
* `GET /api/foods?q=<text>&category=<cat>&source=<src>&limit=25` → `{"foods":[Food]}`;
  with empty `q` returns most recently logged foods first (then alphabetical).
  Search: case-insensitive substring over `name` and `brand`; every whitespace-separated
  word must match; exact-prefix matches rank first. `q` is at most 200 characters (400 otherwise)
  and only the first 10 words are matched.
* `GET /api/foods/categories` → `{"categories":[string]}`
* `GET /api/foods/builtin` → `{"foods":[Food]}`: every builtin food that is not hidden, in id order, the same for
  everyone, with `ETag: "<data/foods.json version>-<hash of the answer>"`; `If-None-Match` with it → **304** and no
  body (note 02 §6 item 9, R5). Matched before `/api/foods/{id}`. `/api` stays `Cache-Control: no-store`: the device
  keeps the list and its ETag in its own storage (`js/offline.js`)
* `GET /api/foods/{id}` → Food
* `POST /api/foods` body FoodCreate → Food (source forced to `custom`)
* `PUT /api/foods/{id}` body FoodCreate → Food (409 if source is `builtin`; copy instead)
* `POST /api/foods/{id}/copy` → Food (new custom copy of a builtin, editable)
* `DELETE /api/foods/{id}` → 204 (409 if `builtin`; if referenced by log entries set `hidden=1` instead and still return 204)
* `GET /api/foods/usda/search?q=` → `{"foods":[{"fdc_id","description","data_type","brand","category"}]}`;
  503 `{"detail":"USDA_API_KEY not configured"}` if no key. Uses `https://api.nal.usda.gov/fdc/v1/foods/search`.
* `POST /api/foods/usda/import` body `{"fdc_id": 173944}` → Food (source `usda`, serving 100 g unless
  the USDA record supplies a household portion; nutrients mapped by USDA nutrient numbers:
  208/1008 kcal, 203/1003 protein, 204/1004 fat, 606/1258 sat fat, 205/1005 carbs, 291/1079 fiber,
  269/2000 sugar, 307/1093 sodium, 306/1092 potassium, 305/1091 phosphorus, 301/1087 calcium, 255/1051 water)

```json
Food = {
  "id": 12, "name": "Banana, raw", "brand": null, "category": "Fruits", "source": "builtin",
  "fdc_id": 173944, "serving_desc": "1 medium (118 g)", "serving_g": 118,
  "nutrients": { ...all 12 keys, numbers or null... },
  "flags": [], "kidney_notes": "...", "hidden": false,
  "warnings": [ {"nutrient": "potassium_mg", "level": "high", "value": 422, "message": "High potassium: 422 mg per serving"} ],
  "kidney_rating": "red"
}
FoodCreate = { "name", "brand"?, "category"?, "serving_desc", "serving_g", "nutrients": {...subset...}, "flags"?: [], "kidney_notes"? }
```

v0.3 adds `source: "off"`, the `Food` fields `gtin`, `source_url`, `source_license`, `quality`, `additives`,
`ingredients_text`, and `gtin` / `ingredients_text` on `FoodCreate` and `POST /api/log/quick` ("M2 API: barcode").

### Log
* `GET /api/log?date=YYYY-MM-DD` → DaySummary
* `POST /api/log` body `{"date","meal","food_id","servings"?,"grams"?,"note"?}`
  (`servings` default 1; if `grams` given, servings = grams / serving_g) → Entry (201)
* `PUT /api/log/{id}` body any of `meal`, `servings`, `grams`, `note`, `date` → Entry (recomputes snapshot from the food;
  an entry that was logged by weight keeps its grams and re-derives servings from the food's *current* `serving_g`
  unless the body sets `servings`, so grams and servings always agree, as with copy-day). Optional header
  `If-Match: "<version>"`: a version that is not the entry's now answers **412** and changes nothing ("Offline edits and
  deletes" below)
* `DELETE /api/log/{id}` → 204; the same optional `If-Match`
* `POST /api/log/quick` body `{"date","meal","name","serving_desc"?,"serving_g"?,"nutrients":{...},"servings"?,"flags"?}`
  → Entry; creates a `custom` food then logs it.
* `GET /api/log/range?start=YYYY-MM-DD&end=YYYY-MM-DD` → `{"days":[{"date", "totals": {...}, "status": {...}}]}` (one item per day, including empty days)
* `GET /api/log/export.csv?start=&end=` → CSV, one row per entry, all nutrient columns

```json
Entry = { "id": 5, "date": "2026-10-05", "meal": "breakfast", "food_id": 12, "food_name": "Banana, raw",
          "servings": 1, "grams": null, "note": null, "nutrients": {...multiplied...},
          "warnings": [...per-serving-style warnings evaluated on this entry's totals...],
          "kidney_rating": "red", "created_at": "...", "updated_at": "...",
          "version": "9f3a0c5d1e7b2468" }   // v0.4: a hash of the stored content; see "Offline edits and deletes"

DaySummary = {
  "date": "2026-10-05",
  "entries": [Entry],                       // ordered by meal (breakfast, lunch, dinner, snack) then created_at
  "totals": { ...12 nutrient keys... },
  "targets": Profile.targets,
  "status": { "potassium_mg": {"value": 1800, "target": 2500, "fraction": 0.72, "level": "ok"},
              "protein_g":    {"value": 40, "target": 56, "min": 42, "fraction": 0.71, "level": "ok"}, ... },
  "meals": { "breakfast": {"carbs_g": 45, "protein_g": 12, ... all keys ...}, "lunch": {...}, "dinner": {...}, "snack": {...} },
  "alerts": [ {"level": "caution"|"over", "nutrient": "potassium_mg", "message": "Potassium is at 85 % of today's limit (2125 / 2500 mg)"} ],
  "carb_tolerance_g": 10,   // v0.3.1: the person's guidance.carb_tolerance_g, used by the per-meal alerts
  "pattern_alerts": [ {"level": "over"|"caution", "nutrient": "potassium_mg",
                       "kind": "recent_days"|"interdialytic"|"weekly_average", "message": "..."} ]   // v0.3.1
}
```

**Running high (v0.3.1, `periods.pattern_alerts`).** `DaySummary` and each `/api/log/range` day carry
`pattern_alerts`, warnings that join the last few days with what is planned, for today and later days with
planned entries only, and only for a nutrient the plan adds. Each day stands for what was eaten before today
and for eaten + planned from today on (`log.pattern_inputs`; past plans never eaten do not count).
`recent_days` (level `over`): potassium, sodium or fluid over the limit with the plan, and over on at least 2
of the 3 days before. `interdialytic` (level `over`, hemodialysis with dialysis days set, instead of
`recent_days`): the interval's total with the plan over the limit × its days (a dialysis day itself is left to
its own alert). `weekly_average` (level `caution`): the average of the logged days among the last 7 (at least
3), with the plan, over the phosphorus or protein target (an "about" target with its tolerance). Messages name
up to 2 planned foods adding the most, summed per food name, never a low treatment. Every number compared is
the person's own target; the day counts are display rules marked for review in `handbook/REVIEW.md`. Twin:
`js/mock/log.js` (`patternAlerts`, `patternInputs`), compared by `tests/test_running_high.py`. Today shows them
first in the planned block; the Plan week marks the day ("Running high: potassium").

**Kidney-only profile (v0.3.1, part 1).** With `diabetes` "none" a meal has no carbohydrate goal:
`log.has_meal_carb_goals` is false, so `day_figures` sends no per-meal carbohydrate alert, eaten or planned (the
twin in `js/mock/log.js` does the same; `tests/test_kidney_only.py`). Today draws no carbohydrate line or
planned-carbs badge in the meal headers, Settings → Meal guidance explains instead of showing the
carbohydrate tolerance and the carbs taken for a low, and Profile hides the per-meal and per-snack carbohydrate
targets and names no carbohydrate per meal in the suggestion (every value is kept and saved unchanged). The day's carbohydrate is judged
like any nutrient. Before a diabetes type is chosen the app uses type 1, so the meal goals stay. The "Not
medical advice" note follows the profile too (part 2): Profile's note below the form hides its insulin clause
(`#pf-disclaimer-diabetes`) with the form's diabetes select, and Settings → About words the sentence from the
saved profile. **The AI prompts follow the profile too (part 3, `PROMPT_VERSION` 2026-10-15.3, now 2026-10-15.4 with the lab report task line; "Prompts, answers and the guard" below).** Still to do (ROADMAP): the owner's live golden-set run for the current version and the handbook framing.

**Tolerances (v0.3.1).** A meal's carbohydrate alert fires only when the meal is more than the person's
carbohydrate tolerance (`guidance.carb_tolerance_g`, 5–20 g, default 10; Smart et al. 2009/2012, note 06 F4,
the number meal guidance already uses) above its goal: "Dinner carbohydrate is more than 10 g over the
per-meal goal: 75 / 60 g". Carbohydrate of entries that treated a low (`purpose = "hypo"`) is left out of the
meal's goal, because treating a low is never warned against; it still counts in every total, and an alert that
fires anyway says "(not counting 15 g used to treat a low)". An "about" target (minimum = maximum once rounded,
such as protein "about 56 g") is `over` only above `Profile.about_tolerance_pct` (0–10 %, default 0 = the
number itself), in the day status, the projected status and the period summary (`level`, `days_over`); its
alerts name it "today's target". Limits and real ranges keep their line. `nutrients.over_at` /
`carb_tolerance` and their twins in `js/engine/rules.js` (`overAt`, `carbTolerance`) implement it;
`tests/test_tolerance.py` compares the server and the demo.

### Auth (optional)
*v0.2 only; replaced in v0.3 by accounts (see "M1 API" at the end of this file). `APP_PASSWORD`
is now imported once as the first admin's password and HTTP Basic is no longer accepted.*
If `APP_PASSWORD` is set, every route (including static) **except `GET /healthz`**
requires HTTP Basic auth with any username and that password (constant-time compare,
realm `kidney-health`). `/healthz` stays open so container and Kubernetes probes work;
it exposes only the food count. Otherwise no auth (LAN use behind a reverse proxy).

### Validation errors
Request validation failures return **400** with `{"detail": "<message>", "errors": [...]}`
(not FastAPI's default 422), so every error has the `detail` string shape above. `errors`
carries only `type`, `loc` and `msg`: since v0.3 the offending `input` (and `ctx`) is **never**
echoed, because it could be a password, API key or setup code (note 07 §9 N4). The OpenAPI document says the same
(`400`, shared `ValidationProblem`; FastAPI's own 422 is removed from it).

### Numeric bounds (`app/models.py`)
Every numeric request field rejects the JSON literals `NaN` / `Infinity` and has a ceiling, so
no stored snapshot can be infinite and no read can fail on one: `servings` ≤ 1000, `grams` ≤
100 000, `serving_g` 0.1–100 000, apply `scale` ≤ 100, nutrient values and targets ≤ 1 000 000,
ids ≤ 2⁶³ − 1 (a larger path or body id is a 404 / 400, never a 500). The status, alert and
period builders additionally treat a non-finite stored value as unknown (status `fraction`
`null`, level still `over` for +∞, no alert, 0 in period totals) and a non-finite target as
"not tracked", so a database written before these bounds existed stays readable.

## Frontend behaviour (app/static)

Mobile-first single page, five views switched client-side (no router library):

1. **Today** (default): date picker (prev/next day), the day's status bars for each
   targeted nutrient (color by level), per-meal sections with entries, each entry
   showing servings, carbs, K, P, Na and its kidney_rating dot; tap to edit servings /
   meal / delete. A prominent **meal carbohydrate total** for each meal (type 1), against
   `carbs_per_meal_g`; the snack against `carbs_per_snack_g` when set (Profile "Carbohydrate per
   snack"; the alerts too: `rules_kidney.meal_carb_alerts` says "over the snack goal").
   Alerts banner at top when any level is `caution`/`over`.
2. **Add food**: search box (debounced, `GET /api/foods?q=`), results show name, serving,
   kidney_rating dot and the key numbers; choosing one opens a sheet to pick meal,
   servings or grams, shows the warnings *before* saving. Buttons for "Quick add"
   (manual nutrients) and, when USDA is configured, "Search USDA".
3. **Trends**: last 14 days, one small inline-SVG bar chart per limited nutrient
   (K, P, Na, protein, carbs, fluid if set) with target line. Export CSV button.
4. **Profile & targets**: profile fields, targets editor, "Suggest targets" button
   (fills the form from `/api/profile/suggested-targets`, never auto-saves), warn_fraction,
   dialysis days (weekday checkboxes, shown when dialysis is hemodialysis), week start.
   Footer disclaimer: targets come from the person's nephrologist / renal dietitian.
5. **Plan** (v0.2): a 7-day grid starting at the profile's week start (7 columns on desktop,
   a vertical list of day cards on phones). Each day shows projected (eaten + planned) K, P, Na,
   protein, carbs and fluid (when targeted) as small chips colored by `projected_status` level,
   plus counts of planned/eaten items; tapping a day opens it in Today. Actions: "Copy day…"
   (POST /api/log/copy-day), week navigation, a **Saved meals** section (list, create/edit/delete,
   "Add to a day" → POST /api/meals/{id}/apply with date + meal + status), and a **Shopping list**
   for the visible week (GET /api/plan/shopping) with checkboxes kept only in localStorage.

v0.2 changes to the other views:
* Today: planned entries render in their meal section with a dashed outline and a "planned"
  badge, are excluded from the meal's eaten totals but shown in a second line
  ("Planned: +32 g carbs"); each has a one-tap "Eaten" button (PUT status) and each meal has
  "Mark all eaten" (POST /api/log/mark-eaten) and "Save as meal" (POST /api/meals/from-log) and
  "Add saved meal". Status bars draw the projected total as a lighter extension of the bar with
  a marker, and `projected_alerts` show below the eaten alerts in a muted style
  ("If you eat what's planned…"). A compact **"Last 7 days"** strip at the bottom shows the
  average per logged day for K, P, Na, protein vs target (from GET /api/log/summary) so weekly
  trends are visible without leaving the page; when the profile is hemodialysis with dialysis
  days set, it also shows the "since last dialysis" accumulation for potassium and fluid.
* Add: an "Eaten / Planned" toggle in the entry sheet (default Eaten for today or past dates,
  Planned for future dates; the same two labels in the same order in every sheet that has the
  toggle). When Planned is selected the sheet is titled "Plan food" and its button reads
  "Plan for <meal>"; the toast after saving names the day when it is not today. The warnings
  block sits above the "For this amount" preview so it is visible on a phone without scrolling.
  A "Saved meals" shortcut list above the search results (`role="list"` of `role="listitem"`
  wrappers, each holding a plain `<button>`).
* Trends: the period-summary tag reads "weekly average" only for a 7-day range, otherwise
  "<n>-day average"; charts that cross a month boundary label the first bar of each month with
  the month name on a second axis line.
* Profile: "Suggest targets" first checks the form client-side (empty weight → "Enter your weight
  (kg) first…", weight or height differing from the saved profile → "Save profile first so the
  suggestion uses your weight and height") so the server's 400 is never shown; "Last saved" only
  appears once the profile holds a weight, height, name or target.
* Touch targets: on a coarse pointer or below 720 px every control (chips, segments, link
  buttons, checkboxes, `<summary>` toggles, saved-meal actions) is at least `--tap` (44 px) tall.
* Trends: a **Period summary** card at the top (same data as GET /api/log/summary for the
  selected range): per nutrient the average per logged day vs target with level color, days over,
  change vs the previous period, and the interdialytic block when applicable; the explanatory
  `notes` are shown once under the card.

Colors: green `#2e7d32`, yellow `#f9a825`, red `#c62828`, neutral grays; must pass
contrast on both light and dark (`prefers-color-scheme`). Fonts: system stack.
All strings in English. `fetch()` only to same-origin `/api/...`.

## v0.2 additions: meal planning and period summaries

### Why periods matter (drives the copy in the UI and `notes` in the API)
* Potassium, sodium and fluid act within the day: a day well over the limit is a risk on
  its own, there is no "banking" a low day against a high one. Between hemodialysis sessions
  they do accumulate until the next session, so for hemodialysis the app also totals them
  over the current interdialytic interval (the long weekend gap is the dangerous one).
* Phosphorus and protein are judged on the average over several days: serum phosphate and
  nutritional status reflect weeks of intake, so a weekly average above target matters more
  than one high day.
* Carbohydrate is counted per meal and per day for insulin; the weekly average is informational.

### Log entries gain `status`
* `POST /api/log` and `POST /api/log/quick` accept `"status": "eaten" | "planned"` (default `eaten`).
* `PUT /api/log/{id}` accepts `status`.
* `Entry` includes `"status"`.
* `POST /api/log/mark-eaten` body `{"date": "YYYY-MM-DD", "meal"?: Meal}` → `{"updated": n}`
  sets every planned entry of that day (or meal) to `eaten`.
* `POST /api/log/copy-day` body `{"from_date", "to_date", "meals"?: [Meal], "include"?: "all"|"eaten"|"planned" (default all), "status"?: "planned"|"eaten" (default planned)}`
  → `{"created": n, "entries": [Entry]}`; copies entries (snapshot recomputed from current foods) onto `to_date` with the given status. 400 if from_date == to_date.

### DaySummary gains projection fields
```json
DaySummary += {
  "totals": {...eaten only...},
  "planned_totals": {...planned only...},
  "projected_totals": {...eaten + planned...},
  "status": {...on eaten totals...},
  "projected_status": {...same shape, on projected totals...},
  "meals": { "breakfast": {...eaten totals...}, ... },
  "planned_meals": { "breakfast": {...planned totals...}, ... },
  "alerts": [...on eaten...],
  "projected_alerts": [ {"level": "caution"|"over", "nutrient": "potassium_mg", "message": "If you eat what's planned, potassium reaches 104 % of today's limit (2600 / 2500 mg)"} ],
  "counts": {"eaten": 5, "planned": 2}
}
```
`entries` still contains both statuses, ordered by meal, then status (`eaten` before `planned`), then created_at.

### Range gains planned/projected per day
`GET /api/log/range` items become
`{"date", "totals", "planned_totals", "projected_totals", "status", "projected_status", "counts": {"eaten", "planned"}}`.

### Period summary
`GET /api/log/summary?start=YYYY-MM-DD&end=YYYY-MM-DD` (default: the 7 days ending today; max 366 days)
```json
PeriodSummary = {
  "start": "2026-09-29", "end": "2026-10-05", "days": 7,
  "logged_days": 5,                               // days with at least one eaten entry
  "nutrients": {
    "potassium_mg": {
      "role": "limit", "target": 2500,            // target: max for limits/ranges, goal for goals, null → key omitted
      "total": 11200, "average": 2240,            // average per LOGGED day (null when logged_days == 0)
      "fraction": 0.9, "level": "caution",        // average vs target with the profile's warn_fraction
      "days_over": 1, "max_day": {"date": "2026-10-03", "value": 3100},
      "previous_average": 2400, "change_pct": -6.7, // the same-length period immediately before; null when no data
      "assessment": "daily"                        // "daily" (K, Na, fluid, carbs) or "weekly_average" (P, protein, calories, calcium)
    }, ...
  },
  "interdialytic": null,                          // or, when dialysis == hemodialysis and dialysis_days non-empty:
  // { "since": "2026-10-03", "days": 3, "next": "2026-10-06",
  //   "nutrients": { "potassium_mg": {"total": 7200, "limit": 7500, "fraction": 0.96, "level": "caution"},
  //                  "sodium_mg": {...}, "fluid_ml": {...} } }
  "notes": ["Potassium, sodium and fluid are judged day by day ...", "Phosphorus and protein are judged on the weekly average ..."]
}
```
Interdialytic interval: `since` is the most recent dialysis weekday on or before `end`
(intake on a dialysis day counts toward the next session), `days = end - since + 1`,
`limit = per-day target × days`, `next` the next dialysis weekday after `end`.
Only eaten entries count. Include only nutrients that have a numeric target.

### Saved meals (templates), prefix `/api/meals`
* `GET /api/meals` → `{"meals": [MealTemplate]}` (alphabetical)
* `POST /api/meals` body `{"name", "note"?, "items": [{"food_id", "servings"}]}` → MealTemplate (201); 404 if a food id is unknown; 400 if items empty.
* `GET /api/meals/{id}` → MealTemplate; `PUT /api/meals/{id}` (same body) → MealTemplate; `DELETE /api/meals/{id}` → 204.
* `POST /api/meals/from-log` body `{"date", "meal", "name", "note"?}` → MealTemplate (201) built from that day's entries of that meal (both statuses); 400 if none.
* `POST /api/meals/{id}/apply` body `{"date", "meal", "status"?: "planned"|"eaten" (default planned), "scale"?: number > 0 (default 1)}` → `{"entries": [Entry]}` (201).

```json
MealTemplate = {
  "id": 3, "name": "Usual breakfast", "note": null,
  "items": [ {"food_id": 12, "food_name": "Egg white, cooked", "servings": 2, "serving_desc": "1 large (33 g)",
              "nutrients": {...scaled...}, "kidney_rating": "green", "hidden": false} ],
  "totals": {...12 keys...},
  "kidney_rating": "yellow",                      // worst item rating
  "servings_made": null, "steps": null, "source_url": null,   // a recipe (schema step 21, note 16 §5.1)
  "per_serving": {...12 keys...},                // totals ÷ servings_made (÷ 1 when null); null when no item lists it
  "unknown": {"phosphorus_mg": 1},               // how many items do not list a nutrient (only keys with a count)
  "created_at": "...", "updated_at": "..."
}
```
**Recipes** (note 16, schema step 21). `POST` and `PUT /api/meals` accept `servings_made` (> 0, ≤ 100), `steps` (at most 20
strings of at most 500 characters, trimmed, empty ones dropped, no control characters) and `source_url` (an `http` or `https`
link with a host and no password, at most 900 characters, never fetched; `""` is no link). A `PUT` that leaves one out keeps
the stored value, as for `meal_hint`; `null` clears it. The items of a recipe are for the whole pot: `apply` logs them times
`scale`, so one serving is `scale = 1 / servings_made`. What fits now (`context.load_saved_meals`, and the demo's twin) divides
each item by `servings_made`, so a recipe is judged and offered one serving at a time. Export and import carry the three fields;
`per_serving` and `unknown` are worked out again on read. The screens (Plan → saved meals): the editor has **Makes**, **Recipe
link** and **Cooking steps**; the list shows one serving's numbers for a recipe and hides a note equal to the old `save_recipe`
sentence; **Fit to my targets** opens a sheet that calls `POST /api/guidance/fit-recipe` (default target: the recipe's `meal_hint`,
else the next meal today) and offers **Save as a new recipe** (`POST /api/meals`, name "<name> (fitted)", `servings_made` =
`servings_made ÷ serving_fraction` so one saved serving is the size that fits; when that is over 100 it is 100 and every amount is scaled down by the same factor instead) or **Replace this recipe** (`PUT`, after an inline
confirm with carbohydrate per serving before and after, with an Undo that `PUT`s the old body back). The demo answers the route
with `engine/guidance/recipes.js`, the twin of `app/guidance/recipes.py`, checked by the `fit_recipe` cases of
`tests/data/guidance_vectors.json`. **AI recipes** (note 16 phase 3, optional): when `GET /api/ai/status` says `features.recipes`,
Plan shows **Suggest recipes with AI** and the fit sheet **Rework with AI**; both open the AI sheet (`KH.ai.openRecipes` in
`js/views/ai.js`), which calls `POST /api/ai/recipes` through the consent flow of the feature `recipes` and shows each card with
**Save recipe** (`POST /api/meals` with the card's `body`, once), **Add to plan** (one serving as planned entries through
`POST /api/log/batch`) and **Dismiss**. The demo never offers them. AI idea and recipe screens discard old replies and errors
when their meal/date or recipe inputs change, or a newer request starts. Add actions keep the context of the request whose
answer was shown; an answer checked for one meal must not appear as checked for another.
A food referenced by a template may be hidden later; keep the item, return `hidden: true`, and
`apply` still works (the entry snapshot comes from the stored food row).

### Shopping list
`GET /api/plan/shopping?start=&end=` → `{"items": [{"food_id", "food_name", "serving_desc", "servings", "grams", "days": 3}]}`
aggregating **planned** entries in the range by food (servings summed; `grams = servings × serving_g`), ordered by name.


## Conventions

* Timestamps ISO-8601 UTC with `Z`. Dates `YYYY-MM-DD` as provided by the client.
* Round nutrient numbers to 1 decimal in responses (mg values to integers).
* Food rows store per-serving nutrients at that same precision, and `serving_g` to 1 decimal
  (custom, USDA and builtin alike; `data/foods.json` is already rounded), so a client that scales
  a food's shown values gets the numbers and warnings the saved entry gets.
* `python -m pytest` must pass with no network.
* `uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers` runs the server (v0.3: the app applies
  `X-Forwarded-*` itself, only from `TRUSTED_PROXIES`, so uvicorn must not); `DATA_DIR` default
  `./data-local` when running outside a container (gitignored), `/data` in the image.

---

# v0.3 contract: accounts, security, PWA, guidance, AI, barcode, personalised targets, handbook

Written 2026-10-05 after the research round. Everything above still holds unless this
section changes it. **The research notes in `docs/dev/research/` are the normative
specifications**; this section only fixes the cross-cutting decisions, resolves conflicts
between notes, assigns file ownership, and fixes interface names so parallel builders do not
collide.

## Specs and precedence

| Area | Spec |
|---|---|
| Rootless, image, runtime flags, k8s, supply chain, app security middleware | `docs/dev/research/01-rootless-and-security.md` |
| Home-screen install (PWA), service worker, offline, HTTPS guide | `02-ios-pwa.md` |
| Barcode, Open Food Facts, USDA branded, label/plate photos | `03-barcode-and-photo.md` |
| Optional AI (OpenAI-compatible, Ollama, Hermes, OpenRouter, ...) | `04-optional-ai.md` |
| Personalised targets (age, sex, activity, labs, eGFR) | `05-personalized-targets.md` |
| Rule-based meal guidance | `06-meal-guidance.md` |
| Accounts, sessions, settings, secrets, audit, export | `07-accounts-settings-secrets.md` |
| Patient handbook site (`/learn`) | `08-handbook-site.md` |

When notes disagree, apply in this order: (1) this section; (2) the "Security review" and
"Fact-check" sections appended to a note override that note's earlier text; (3) note 07 for
anything about identity, settings or secrets; (4) note 01 for anything about headers, CSP,
proxies, the image and CI; (5) the note that owns the feature.

## Conflict resolutions and owner decisions

1. **Guidance lives in the package `app/guidance/`** (note 06 layout). Note 04's `app/guidance.py`
   means that package. AI lives in the package `app/ai/` (note 04 layout).
2. **Settings and secrets:** one registry (`app/settings_registry.py`, `app/settings_store.py`)
   and one credential resolver (`app/crypto.py`, `app/credentials.py`) from note 07. Notes 03, 04
   and 06 register their keys there; no other settings store. Env names follow note 07 and the
   security review: `AI_PRIVATE_HOSTS` (not `ALLOW_PRIVATE_AI_HOSTS`), `ALLOWED_HOSTS`,
   `PUBLIC_URL`, `TRUSTED_PROXIES`, `TRUSTED_PROXY_SECRET_FILE`.
3. **Identity interface (fixed names):** `app/auth/deps.py` exports `current_user`,
   `CurrentUser`, `require_admin`, `AdminUser`, `require_recent_auth`. `User` is a frozen
   dataclass in `app/auth/models.py` with at least `id: int`, `username: str`, `role:
   Literal["admin","user"]`, `status: str`, `display_name: str | None`. Every data router uses
   `dependencies=[Depends(current_user)]`, and every query takes `user.id` explicitly. Not found
   and not yours are both **404**.
4. **HTTP client:** move the whole app from `httpx` to **`httpx2`** (Starlette's TestClient now
   warns about `httpx`; note 04 F14). No `openai` SDK.
5. **New runtime dependency:** only `cryptography` (note 07 §4.2). Locks with hashes via
   `pip-compile --generate-hashes` (`requirements.in` → `requirements.lock`, same for dev).
   Install with `--require-hashes`. Dependabot cannot read or regenerate `*.lock` files (it handles
   only `.txt`/`.in` requirement files), so `.github/workflows/refresh-locks.yml` runs
   `scripts/lock.sh --upgrade` weekly with a 7-day cooldown (`PIP_UPLOADED_PRIOR_TO=P7D`) and opens a
   pull request; Dependabot's pip ecosystem covers only `/.github`.
6. **Base image:** Chainguard Python pinned by digest for `deploy/Containerfile`, plus
   `deploy/Containerfile.debian` as the fallback (note 01 §5.1). CI tests on **Python 3.12, 3.14 (the Debian
   fallback) and 3.15 (the image's Python at the time of writing)**. The app must stay compatible with 3.11+.
   The handbook build stage temporarily stays on a 3.14 digest (PyYAML has no cp315 wheel; wheels only, so
   the dev lock also leaves PyYAML out on 3.15 and the two YAML-reading test files skip there).
7. **Image tags:** pushes to `main` publish `:edge` and `:sha-<short>`; `v*` tags publish
   `:latest`, `:X.Y.Z`, `:X.Y`. Signing, SBOM and provenance per note 01 §5.4; attestation steps
   that need a public repo are gated on `github.event.repository.private == false`. *(M1 review:)*
   the repository variable `HOLD_LATEST=true` keeps `:latest` where it is on a `v*` tag. v0.2's
   Quadlet unit tracked `:latest` with `AutoUpdate=registry` and a shell `HealthCmd`, which loops
   (kill, restart) under the shell-less v0.3 image. **Owner decision (2026-10-06): no hold.**
   `:latest` moves to v0.3.0 when it is tagged and `HOLD_LATEST` stays unset; v0.2 hosts are
   protected by the upgrade warnings in CHANGELOG.md, README.md and docs/deployment.md (replace the
   v0.2 `.container` file with the v0.3 one before the update). The variable remains for a future
   release that needs a hold (`docs/maintainers.md`).
8. **Open Food Facts** is **off by default** (`food.off_enabled=false`); the admin turns it on in
   Settings, and the first-run setup screen offers a checkbox for it.
9. **`potassium_additive` flag** (note 03 R5): a **medium** warning ("contains a potassium
   additive; potassium not listed") when potassium is unknown; normal thresholds when it is
   listed. Marked for clinical review in the handbook's review list. Not a high warning.
10. **Protein for diabetes at G3a–G5 without dialysis: 0.8 g/kg floor** (note 05 fact-check H1).
    `docs/research/targets_by_stage.json`, `docs/diet-guide.md` and the v0.2 tests are updated to
    match; the old 0.6 lower bound remains only for `diabetes: none` with the supervision note.
11. **Handbook text licence:** CC BY-NC-SA 4.0 (code stays PolyForm Noncommercial 1.0.0). Every
    handbook page shows a "draft, not yet reviewed by a clinician" banner until a named reviewer
    signs it off in front matter.
12. **Links into the handbook** use `/learn/...` (not `/handbook/...`); note 08 §4.10 owns the slug
    list (`app/guidance/topics.py` reads it).
13. **Hermes:** the `hermes` AI preset is supported only against a dedicated tool-free Hermes
    Agent profile (note 04 F1 + security review); the app probes it and refuses otherwise. Users
    who only want a Hermes *model* use the `ollama` or `openrouter` presets.
14. **`AUTH_MODE` default `local`.** `APP_PASSWORD` is deprecated and imported once (note 07).
15. **Preview/demo mode remains a supported feature** (it powers the claude.ai preview and lets
    contributors try the UI without a server). Its twins of server logic must stay in parity
    (see "Frontend modules" below).

## Database migrations

Move schema evolution into `app/migrations/` with one module per step, applied in order by
`app/db.py` and recorded in `meta.schema_version`. Each step is idempotent (checks
`PRAGMA table_info` before `ALTER TABLE`). Fixed numbering so parallel builders do not collide:

| Step | Module | Owner (milestone) | Content |
|---|---|---|---|
| 1, 2 | `m001_base.py`, `m002_planning.py` | backend-core (M1) | v0.1 schema and v0.2 additions, moved verbatim from `db.py` |
| 3 | `m003_accounts.py` | backend-core (M1) | note 07 §4.4 schema v3 (users, sessions, invites, user_profiles, `user_id` columns + triggers, settings tables, secrets, audit, login throttling) + automatic `kidney.db.pre-v3.bak` |
| 4 | `m004_targets_labs.py` | targets (M2) | note 05 §4.6 (profile columns on `user_profiles`, `lab_results`) |
| 5 | `m005_guidance_log.py` | guidance (M2) | note 06 §4.11 (`log_entries.purpose`, `meal_templates.meal_hint`, food preferences) **and** note 02 R5 `log_entries.client_id` + unique index (offline outbox) |
| 6 | `m006_ai.py` | ai (M2) | note 04 (AI provider settings, usage/quota and audit tables with `ON DELETE CASCADE`) |
| 7 | `m007_barcode.py` | barcode (M2) | note 03 R6 (food `gtin`, `source='off'`, `barcode_cache`, attribution fields) |
| 8 | `m008_profile_chosen.py` | v0.3.1 | "Not chosen yet": `user_profiles.ckd_stage_set_at`, `diabetes_set_at` (`docs/dev/plans/v0.3.1.md` item 1) |
| 9 | `m009_about_tolerance.py` | v0.3.1 | `user_profiles.about_tolerance_pct` (`docs/dev/plans/v0.3.1.md` item 2) |
| 10 | `m010_api_tokens.py` | assistant step 1 | `api_tokens`: assistant access tokens, hashes only (`docs/dev/plans/assistant-step1.md` part A; "Assistant access tokens" below) |
| 11 | `m011_assistant_request_keys.py` | assistant step 1 | `assistant_request_keys`: the duplicate guard of `log_food` and `save_recipe`, hashes only ("Retries" under "Assistant MCP server" below) |
| 12 | `m012_ai_consent_chat.py` | assistant step 2 | `ai_consents.purpose` accepts `chat` (table rebuilt; `docs/dev/plans/assistant-step2.md`; "Ask chat" above) |
| 13 | `m013_assistant_ask_keys.py` | assistant step 2, part C | `assistant_ask_keys`: the duplicate guard of the Ask chat's saves, hashes only ("Saving from the chat" below) |
| 14 | `m014_ai_consent_voice.py` | assistant step 2, part B | `ai_consents.purpose` accepts `voice` (table rebuilt from its stored definition; "Voice input" below). |
| 15 | `m015_symptoms.py` | symptoms log | `symptoms`: a person's symptoms by date and severity, no list of keys in the table ("Symptoms log" below). |
| 16 | `m016_ai_consent_labs.py` | lab report photos | `ai_consents.purpose` accepts `labs` (table rebuilt from its stored definition; "Lab report photos" below). Needs step 15 in place (the numbering has no gaps). |
| 17 | `m017_food_preference_source.py` | food preferences | `food_preferences.source` (`person` or `ask`, back-filled `person`; `assistant` later, code only) and `updated_at` (back-filled `created_at`); `preference` takes `like`, `less`, `not_for_me`, `neutral`, still without a `CHECK` ("Food preferences" under "M2 API: guidance" below). |
| 18 | `m018_body_measurements.py` | weight and blood pressure | `weights` and `blood_pressures`: a person's weighings and readings by date, kilograms and mmHg, a `source_key` an import de-duplicates on, no `CHECK` on a context or a source ("Weight and blood pressure" below). |
| 19 | `m019_body_token.py` | phone push (note 12) | `weights.api_token_id` and `blood_pressures.api_token_id` (`REFERENCES api_tokens(id) ON DELETE SET NULL`, NULL for every earlier row) and two partial indexes `(user_id, api_token_id) WHERE api_token_id IS NOT NULL`; no `(user_id, date, time)` index (step 18's `(user_id, date)` serves the same-reading check) ("Device tokens and `/push/v1`" below). |
| 20 | `m020_ai_env_slots.py` | two AI providers from the environment | `ai_providers.env_slot` (`main` or `cloud`; the row locked today becomes `main`) and `ai_providers.upstream` (who a proxy forwards to, at most 60 characters); the one-locked-row unique index is replaced by one locked row per slot ("Environment providers: main and cloud" under "M2 API: AI and photos" below). |
| 21 | `m021_recipes.py` | recipes (note 16) | `meal_templates.servings_made` (REAL, > 0 and ≤ 100, NULL = a plain saved meal of one serving), `steps_json` (a JSON list of strings) and `source_url` (≤ 900 characters, never fetched). A note that is exactly the sentence `save_recipe` wrote (`Makes N serving(s).` with or without ` Source: <link>`) fills `servings_made` and `source_url`; the note itself is left alone and any other note leaves the columns NULL. |
| 22 | `m022_totp.py` | two-step sign-in (note 17) | `totp_factors` (one row per person who started or turned it on: `secret_enc` sealed with the keyring, purpose `totp`, owner the person; `key_id`; `enabled_at`, NULL until the first code; `last_step`, so each code works once) and `totp_recovery_codes` (`code_hash`, the 32-byte SHA-256 of a code, and `used_at`). Both `ON DELETE CASCADE`. Nobody has it on after the upgrade. |
| 24 | `m024_shares.py` | read-only sharing (note 19) | `shares`: a share link until it is accepted (`code_id`, the SHA-256 `verifier_hash`, `expires_at`), then a share (`grantee_user_id`, `accepted_at`; the link's fields cleared); `owner_user_id`, `areas` (a JSON list of `food`, `labs`, `body`, `symptoms`), `ended_at` and `ended_by` (`owner`, `grantee`, `admin`, `replaced`), `last_viewed_at`. `CHECK`s keep the two states apart and forbid sharing with yourself. `ON DELETE CASCADE` on both accounts. Nobody shares anything after the upgrade. |
| 25 | `m025_share_time_limit.py` | a share can end on a date (note 19 §11) | `shares.lasts_days` (1 to 365, or NULL: until stopped) and `shares.ends_at` (set on accept). Existing rows get NULL in both and last until stopped, as before. |
| 23 | `m023_passkeys.py` | passkeys (note 18) | `passkeys` (one row per passkey: `credential_id` BLOB, unique, 1 to 1,023 bytes; `public_key`, the COSE key as sent; `alg`; `user_handle`, 32 random bytes shared by one person's passkeys; `sign_count`; `name`; `backed_up`; `created_at`; `last_used_at`). `ON DELETE CASCADE`. Nothing is sealed: a public key is not a secret. Nobody has a passkey after the upgrade. |

## Backend file ownership

| Milestone / owner | Files |
|---|---|
| M1 backend-core | `app/config.py`, `app/db.py`, `app/migrations/**` (steps 1–3), `app/security.py`, `app/auth/**`, `app/settings_registry.py`, `app/settings_store.py`, `app/crypto.py`, `app/credentials.py`, `app/audit.py`, `app/account.py` (export/delete), `app/admin.py` (CLI), `app/healthcheck.py`, `app/pwa.py` (note 02 R6: `/sw.js`, manifest/icon headers), `app/main.py`, `app/models.py`, user scoping edits in `app/foods.py`, `app/log.py`, `app/meals.py`, `app/profile.py`, `app/periods.py`; `requirements*.in/.lock`, `pyproject.toml`, `scripts/lock.sh`; `tests/**` except frontend-owned tests |
| M1 deploy | `deploy/**`, `.github/**`, `.hadolint.yaml`, `.dockerignore`, `scripts/verify-image.sh`, `SECURITY.md`, `docs/security.md`, `docs/https.md`, `docs/deployment.md`, `docs/network-allowlist.md` |
| M1 frontend | `app/static/**`, `scripts/build_preview.py`, `scripts/build_icons.py`, `requirements-tools.txt`, `tests/test_preview_build.py`, `tests/js/**`, `docs/install-on-your-phone.md` |
| Handbook (parallel) | `handbook/**`, `scripts/build_handbook.py`, `tests/test_handbook_content.py` |
| M2 targets | `app/targets.py`, `app/target_rules.py`, `app/kidney_function.py`, `app/units.py`, `app/labs.py`, `app/migrations/m004_*`, `suggest_targets` wrapper in `app/rules_kidney.py`, profile fields in `app/profile.py`, `docs/research/targets_by_stage.json`, `docs/diet-guide.md`, its tests |
| M2 guidance | `app/guidance/**`, `data/combos.json`, `app/migrations/m005_*`, `POST /api/log/batch` + `purpose`/`client_id` handling in `app/log.py`, `scripts/bench_guidance.py`, `docs/guidance.md`, `tests/guidance/**` |
| M2 ai | `app/ai/**`, `app/vision.py`, `app/imagecheck.py` (photo routes and checks, moved here from barcode-vision so all AI-dependent code is together), `app/migrations/m006_*`, `app/migrations/m020_*`, AI settings keys, `docs/ai.md`, the "Photos" section of `docs/barcode-and-photos.md`, `deploy/compose.ai-ollama.yaml`, `scripts/ai_eval.py`, `docs/dev/ai-eval/`, its tests and fixtures (`tests/test_ai_*.py`, `tests/test_vision_api.py`, `tests/test_imagecheck.py`, `tests/ai_golden/`, `tests/fixtures/ai/`) |
| M2 barcode | `app/gtin.py`, `app/additives.py`, `app/off.py`, `app/barcode.py`, `app/migrations/m007_*`, barcode/source fields in `app/foods.py`, flag + warning rule in `app/rules_kidney.py`, `docs/barcode-and-photos.md` (except "Photos"), their tests and fixtures |
| Symptoms | `app/symptoms.py`, `app/migrations/m015_*`, `SymptomCreate` and the other `Symptom*` models in `app/models.py`, `symptoms` in `app/account.py` and `app/data_import.py`, `js/engine/symptoms.js`, `js/mock/symptoms.js`, `js/views/symptoms.js`, `css/symptoms.css`, `tests/data/gen_symptoms_vectors.py`, `tests/data/symptoms_vectors.json`, `tools/e2e/symptoms.py` |
| Weight and blood pressure | `app/body.py` (router, pure functions, `RED_FLAGS`), `app/migrations/m018_*`, the `Weight*`, `BloodPressure*` and `Body*` models in `app/models.py`, `weights` and `blood_pressures` in `app/account.py` and `app/data_import.py`, the `user.units.weight`, `body.weight_alarm` and `body.bp_goal` keys (`WeightAlarm`, `BpGoal`) in `app/settings_registry.py`, the `body_batch` limit in `app/auth/ratelimit.py`, `js/engine/body.js`, `js/mock/body.js` (and the sample data in `js/mock/seed.js`), the `body*` helpers in `js/core.js`, `tests/test_body*.py`, `tests/test_migration_m018.py`, `tests/data/gen_body_vectors.py`, `docs/body.md`; Part B, the screens: `js/engine/body_ui.js` (`KH.bodyUi`), `js/views/body.js` (`KH.body`: Today, the sheets, the Settings section, the Profile hints), `js/views/body_trends.js` (`KH.bodyTrends`), `css/body.css`, the cards, sheets and `#set-body` in `index.html`, the body section of `js/engine/visitprep.js` and `js/views/visit.js`, `handbook/docs/app/weight-and-blood-pressure.md`, `tests/test_body_ui*.py`, `tests/js/body_ui_runner.mjs`, `tools/e2e/body.py` |
| Offline edits and deletes | `entry_version`, `version_matches`, `require_current_version` and the `If-Match` handling of `PUT` / `DELETE /api/log/{id}` in `app/log.py`, `Entry.version` in `app/models.py`, `entry_fields` in `app/account.py` (the export has no `version`), `version` accepted by `app/data_import.py`, the edit and delete items of the outbox in `js/offline.js`, `intercept` / `onConflict` / `ifMatch` in `js/core.js`, the editable waiting entries in `js/views/today.js` and `js/views/add.js`, the conflict card in `css/device.css`, `entryVersion` / `versionMatches` and the 412 in `js/mock/log.js` (`header` in `js/mock/core.js`), `tests/test_log_if_match.py`, `tests/test_entry_version_vectors.py`, `tests/test_offline_edits_ui.py`, `tests/data/gen_entry_version_vectors.py`, `tests/data/entry_version_vectors.json`, `tests/js/outbox_changes.mjs`, the `changes` section of `tools/e2e/device.py` |
| Keep my data in this browser (demo) | `app/static/js/mock/persist.js`, `mock/export.js`, `mock/import.js`, `js/views/demo_local.js`, `css/demo-local.css`, `#sheet-demo-local` and the banner button in `index.html`, `seed` and `onWrite` in `js/mock/core.js`, `FdcId` in `app/data_import.py`, `tests/data/gen_import_vectors.py`, `tests/data/import_vectors.json`, `tests/js/fake_idb.mjs`, `tests/js/demo_local_storage.mjs`, `tests/test_demo_local_ui.py`, `tests/test_demo_local_storage.py`, `tests/test_import_vectors.py`, `tools/e2e/demo_local.py`, `docs/demo.md` |
| Visit prep | `js/engine/visitprep.js`, `js/views/visit.js`, `css/visit.css`, the `#view-visit` section and the Trends link in `index.html`, `visit` in `VIEWS` (`js/core.js`), `KH.symptoms.flagEl`, `tests/test_visit_prep_*.py`, `tests/js/visitprep_runner.mjs`, `tools/e2e/visitprep.py` (no route, no table, no server code) |
| Assistant step 1 | `app/auth/api_tokens.py` (tokens, `/api/me/tokens`, the bearer dependency), `app/migrations/m010_*` and `m011_*`, the `assistant.enabled` key, Settings → Assistant access in `js/views/settings.js`, `app/mcp/**` (the MCP server, part B; `log_food` and `save_recipe`, part C) with `log.day_summary`, `log.insert_logged`, `foods.usda_search_records`, `foods.add_usda_food` and `security.BEARER_PATHS`, `docs/assistant.md`, `tests/test_api_tokens.py`, `tests/test_migration_m010.py`, `tests/test_migration_m011.py`, `tests/test_mcp.py`, `tests/test_mcp_write.py`, `tools/e2e/mcp_smoke.py` |
| Phone push (design note 12) | `app/push.py` (`POST /push/v1/body`, `DELETE /api/me/tokens/{id}/body-rows`), the device family in `app/auth/api_tokens.py`, `TokenCreate.family` in `app/auth/schemas.py`, the `push.enabled` key (`app/settings_registry.py`, `js/engine/settings.js`, the "Phone shortcuts" group of `js/views/settings.js`), `app/migrations/m019_body_token.py`, `context_for`, `is_watch_source`, `known_weight_marks` / `known_reading_marks` and `via` in `app/body.py`, `shortcut` in `BodySourceKey`, `security.BEARER_PATHS`, `docs/push.md`, `tests/test_push.py`, `tests/test_device_tokens.py`, `tests/test_migration_m019.py`, `context_cases` / `watch_cases` in `tests/data/body_vectors.json` |
| iPhone app pairing (design note 15 §4.3) | `app/pairing.py`, `pair_url` in `create_my_token` (`app/auth/api_tokens.py`), `brand.PAIRING_SCHEME`, `pushPairBox` in `js/views/settings.js` with `KH.twoStep.qrSvg`, `ios/KidneyHealthCore/Sources/KidneyHealthCore/Pairing.swift`, `ios/KidneyHealthSync-Info.plist`, `.onOpenURL` and the pairing alert in `ios/KidneyHealthSync/ContentView.swift`; tests `tests/test_pairing.py`, `tests/data/pairing_vectors.json`, `PairingVectorTests.swift` |
| Read-only sharing (design note 19) | `app/sharing.py` (`/api/me/shares`, `/api/shared`, the `shared_owner(area)` check), `app/migrations/m024_shares.py`, `app/migrations/m025_share_time_limit.py`, `sharing.enabled` (`app/settings_registry.py`, `js/engine/settings.js`), the `share.*` audit actions, `shares` and `DELETE /api/admin/users/{id}/shares` in `app/auth/admin_api.py`; screens: `js/views/sharing.js` (Settings block, the `#/share/<code>` sheet, `KH.sharing.reads`), the shared mode of `js/views/visit.js`, the People badge and End sharing in `js/views/settings.js`, the demo's answers in `js/mock/auth.js`; tests `tests/test_sharing.py`, `tests/test_migration_m024.py`, `tests/test_migration_m025.py`, `tests/test_sharing_ui.py`, `tools/e2e/sharing.py` |
| Two-step sign-in (design note 17) | `app/auth/totp.py` (RFC 6238, recovery codes, storage), `app/auth/totp_api.py` (`/api/me/totp*`), `_second_step` and the reset-link rule in `app/auth/routes.py`, `LoginBody.code` and `TotpCodeBody` in `app/auth/schemas.py`, `DELETE /api/admin/users/{id}/totp` and `two_step` in `app/auth/admin_api.py`, `remove-two-step` in `app/admin.py`, the `totp.*` audit actions, `totp_factors.secret_enc` in `crypto.ENCRYPTED_COLUMNS`, `app/migrations/m022_totp.py`; screens: `js/views/two_step.js` (Settings block, QR code from the vendored `qrcode-generator`), the code field of `#form-login` and the totp_required answers in `js/views/auth.js`, the People badge and removal in `js/views/settings.js`, the demo's answers in `js/mock/auth.js`; tests `tests/test_totp.py`, `tests/test_migration_m022.py`, `tests/test_two_step_ui.py`, `tools/e2e/two_step.py` |
| Passkeys (design note 18) | `app/auth/webauthn.py` (the WebAuthn checks for a Relying Party, a CBOR reader and COSE keys, on `cryptography` only), `app/auth/passkeys.py` (storage, the in-memory challenges), `app/auth/passkeys_api.py` (`/api/me/passkeys*`, `/api/auth/passkey*`), `passkey_challenges` in `app/auth/context.py`, `passkeys` in `GET /api/auth/status`, `DELETE /api/admin/users/{id}/passkeys` and `passkeys` in `app/auth/admin_api.py`, `remove-passkeys` in `app/admin.py`, the `passkey.*` audit actions, `app/migrations/m023_passkeys.py`; screens: `js/views/passkeys.js` (Settings block, `KH.passkeys.signIn`), the passkey button of `#form-login` in `index.html` and `js/views/auth.js`, the People badge and removal in `js/views/settings.js`, the demo's answers in `js/mock/auth.js`; tests `tests/test_webauthn.py` (with `tests/data/webauthn_w3c_vectors.json`), `tests/webauthn_support.py`, `tests/test_passkeys.py`, `tests/test_migration_m023.py`, `tests/test_passkeys_ui.py`, `tools/e2e/passkeys.py` |
| API document and meta (design note 14, changes 2 and 4) | `app/openapi_doc.py` (operation ids, errors, security schemes; wired in `app/main.py` with `generate_unique_id_function` and `openapi_doc.install`), `app/api_version.py`, `app/meta.py` (`GET /api/meta`) with `status_view` in `app/ai/routes.py` and `providers_available` in `app/barcode.py`, `scripts/gen_openapi.py`, `docs/api/**`, `js/mock/meta.js`, `tests/test_openapi_snapshot.py`, `tests/test_meta.py`, `tests/data/gen_meta_vectors.py`, `tests/data/meta_vectors.json`, the meta section of `tools/e2e/parity.py` |
| Brand strings (design note 14, change 3) | `app/brand.py` and the modules that import it (every one that names a cookie, a token prefix, the CSRF value, the database file, the export format, a User-Agent, an HKDF label or a logger), `js/engine/brand.js` (`KH.brand`; registered in `index.html` and `sw.js`) and the scripts that read it, `tests/test_brand.py` |
| Assistant step 2 | `app/ai/chat.py`, `ChatStep` in `app/ai/schemas.py`, the chat prompt in `app/ai/prompts.py`, `guard.MEDICINE_NAMES`, `POST /api/ai/chat` in `app/ai/routes.py`, `app/migrations/m012_*`, the `ai.chat_enabled` key, `js/views/ask.js`, `css/ask.css`, the Ask tab and view in `index.html`, `scripts/ai_eval.py --chat`, `docs/dev/plans/assistant-step2.md`, `tests/test_ai_chat.py`, `tests/test_ai_chat_checks.py`, `tests/test_migration_m012.py`, `tests/test_ask_ui.py`; part C (saving from the chat): `app/ai/chat_save.py`, `app/migrations/m013_*`, the `ai.allow_trusted_saves` key and `trust` in the person's `ai` setting, the `Asker` identity in `app/mcp/tools.py`, `ask_key_hash` in `app/mcp/request_keys.py`, `ai.trust_changed` in `app/audit.py`, the trust choice and warning sheet in `js/views/ai.js`, the cards in `js/views/ask.js`, `tests/test_ai_chat_save.py`, `tests/test_migration_m013.py` |
| Assistant step 2, part B (voice) | `app/ai/stt.py`, `app/ai/voice.py` (`POST /api/ai/transcribe`, the admin test), `send_json(content=...)` in `app/ai/transport.py`, `AiEnv.stt_*` and `max_audio_bytes` in `app/config.py`, the `ai.voice_enabled` key, `app/migrations/m014_*`, `Permissions-Policy: microphone=(self)` in `app/security.py`, `js/views/ask-voice.js`, `css/ask-voice.css`, the Speech to text panel and the voice consent text in `js/views/ai.js`, `deploy/compose.stt-whisper.yaml`, `tools/e2e/ask_voice.py`, `tests/test_ai_voice.py`, `tests/test_migration_m014.py`, `tests/test_ask_voice_ui.py`, `tests/test_deploy_stt.py` |
| M3 integration | `app/handbook.py` (`/learn` mount), README, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `docs/README.md`, `docs/maintainers.md`, `docs/ROADMAP.md` (each feature owner appends its own section), `.github/ISSUE_TEMPLATE/**`, `.github/pull_request_template.md`, `tools/e2e/**` |

Shared files (`app/main.py`, `app/models.py`, `app/nutrients.py`, `app/rules_kidney.py`) may be touched in M2 only for
the listed additions; each M2 owner registers its router in `app/main.py` with one import line and
one `include_router` line and its settings keys in `app/settings_registry.py`.

## Frontend modules (M1 restructure)

`app/static/app.js` is split into plain scripts (no bundler, no ES module imports, so the preview
build can inline them in order). All code hangs off one namespace `window.KH`:

```
app/static/
  index.html            shell only: no inline script or style attributes (CSP), placeholders for every view/sheet
  theme-init.js         loaded in <head> (was the inline theme script)
  manifest.webmanifest, apple-touch-icon.png, icons/, sw.js (template), vendor/ (M2)
  css/base.css, css/<view>.css
  js/core.js            KH.h/s/$, KH.api (fetch wrapper: X-Requested-With, 401 → sign-in, toasts), state, router, sheets, confirm,
                        KH.forms (server "<field>: <message>" errors under their field, aria-describedby + aria-invalid)
  js/engine/rules.js    warnings, ratings, rounding, number formatting (twin of app/nutrients.py, app/nutrient_core.py and app/rules_kidney.py)
  js/engine/settings.js settings registry + precedence (twin of app/settings_registry.py / settings_store.py)
  js/engine/targets.js, js/engine/kidney_function.js        (M2 targets: KH.targets twin of app/targets.py + target_rules.py;
                        KH.kidney twin of app/units.py + app/kidney_function.py; kidney_function.js loads first)
  js/engine/lab_import.js  (v0.3.1: KH.labImport, the CSV reader of Lab results → Import from a spreadsheet; browser only,
                        no Python twin; tests/data/lab_import_vectors.json; loads after kidney_function.js)
  js/engine/fhir_labs.js  (v0.4: KH.fhirLabs, the reader of Lab results → Import from Apple Health, FHIR clinical-records files; browser
                        only, no Python twin; tests/data/fhir_labs_vectors.json; loads after lab_import.js) and js/views/lab_fhir.js (KH.labFhir, its
                        card and review table, after lab_photo.js; "Lab results from Apple Health clinical records" under "M2 API: targets and labs")
  js/engine/apple_health.js  (note 10 part C: KH.appleHealth, the reader of the Health app's export.xml for weights and blood pressure, streamed as text, no XML parser;
                        browser only, no Python twin; tests/data/apple_health_vectors.json; loads right after rules.js) and js/views/body_import.js (KH.bodyImport.open(),
                        the sheet #sheet-body-import: review, period, watch readings unticked, per-day trimming, batches; "Weight and blood pressure" below)
  js/engine/ccda_labs.js  (v0.4: KH.ccdaLabs, the reader of Lab results → Import from a patient portal file, a C-CDA XML health summary parsed in the
                        browser; browser only, no Python twin; tests/data/ccda_labs_vectors.json; reuses KH.fhirLabs's LOINC table, units, day rule and
                        collector, so it loads after fhir_labs.js) and js/views/lab_ccda.js (KH.labCcda, its card, after lab_fhir.js, whose review table
                        it draws; "Lab results from a patient-portal C-CDA file" under "M2 API: targets and labs")
  js/engine/pdf_pages.js  (note 13: KH.pdfPages, the pages of a PDF lab report drawn on the device as JPEGs with the vendored pdf.js in a module
                        Worker under the Trusted Types policy kh-pdf; browser only, no Python twin; tests/js/pdf_pages_page.mjs; read by js/views/lab_photo.js;
                        "PDFs" under "Lab report photos")
  js/engine/guidance/*.js   (M2 guidance) KH.guidanceEngine, the browser twin of app/guidance/ (rules, messages,
                        budget, score, fits, swaps, planner, insights, hypo: one file per Python module, loaded in that order)
  js/engine/brand.js    KH.brand: the strings the page uses (CSRF header value, IndexedDB name, export format, names), the twin of app/brand.py; the last engine file, loaded just before core.js
  js/mock/core.js       MockApi with a route table: KH.mock.route(method, pattern, handler)
  js/mock/<feature>.js  feature twins register their routes (M1: auth/settings; M2: labs, guidance, barcode fixtures)
  js/views/today.js, add.js, plan.js, trends.js, profile.js, settings.js, auth.js   (M1)
  js/views/labs.js, guidance.js                                                    (M2)
  js/views/visit.js     Visit prep (#visit, no tab; opened from Trends): the one-page summary to print ("Visit prep" below); js/engine/visitprep.js:
                        KH.visitPrep, its pure parts; css/visit.css: the page and its print rules
  js/views/symptoms.js  KH.symptoms: the Symptoms card on Today, its add / edit sheet and the Trends list (symptoms log); today.js and
                        trends.js call KH.symptoms.today(date) and KH.symptoms.trends(start, end)
  js/engine/symptoms.js KH.symptomRules: the browser twin of app/symptoms.py (list, severities, limits, the handbook's red flags, the API shape) and
                        the Trends grouping; tests/data/symptoms_vectors.json. js/mock/symptoms.js: the demo's /api/symptoms routes. css/symptoms.css
  js/engine/body.js     KH.bodyRules: the browser twin of the pure part of app/body.py (kg and lb, the weight-gain alarm, the 7-day blood pressure means, the
                        six-month change, the handbook's words, the summary); tests/data/body_vectors.json. js/mock/body.js: the demo's /api/body routes
                        (weight and blood pressure log)
  js/engine/body_ui.js  KH.bodyUi: what the weight and blood pressure screens are made of (entry, echoes, words, chart scales, table rows); js/views/body.js: KH.body,
                        the Today card, the two sheets, Settings → Weight and blood pressure and the Profile hints; js/views/body_trends.js: KH.bodyTrends, the charts.
                        css/body.css; today.js, trends.js, settings.js, profile.js and visit.js call them (weight and blood pressure log, Part B)
                        labs.js: the Lab results view (#labs, no tab; opened from Profile) and KH.labs (helpers Profile uses)
                        guidance.js: KH.guidance, the meal guidance UI (M2 guidance; see "M2 API: guidance" → Frontend)
  css/labs.css          Lab results view, the potassium safety banner, Profile's lab summary (M2 targets)
  js/mock/labs.js       demo /api/labs routes (M2 targets); js/mock/profile.js answers the v0.3 profile fields and suggestion
  css/guidance.css      What fits now, the Meal ideas and insight cards, the guidance sheet, swap ideas, Settings → Meal guidance
  js/mock/guidance.js   demo /api/guidance/* routes over KH.guidanceEngine; js/mock/log.js answers POST /api/log/batch,
                        purpose and client_id; js/mock/meals.js answers meal_hint
  js/pwa.js (M1)        KH.pwa: service worker, update toast, the install panel, and (note 02 R10) the iPhone/iPad Home
                        Screen tip `#install-tip`, shown once after the third signed-in visit (`countVisit`; localStorage
                        `kdl-visits` / `kdl-install-tip`, never health data)
  js/offline.js         KH.offline + KH.net (M2 offline outbox; see "M2: the offline outbox"): IndexedDB `kdl`, the
                        outbox, saved copies of recent days, the header sync badge, Settings → This device list, sign-out sheet
  js/scan.js, css/device.css   KH.scan (M2 barcode; see "M2 API: barcode" → Frontend): the Scan sheet (native
                        BarcodeDetector, else the vendored decoder), Quick add's label photo and ingredients, provenance
  js/engine/textclean.js, gtin.js, additives.js, off.js    (M2 barcode) KH.textclean / KH.gtin / KH.additives / KH.off,
                        twins of app/textclean.py, app/gtin.py, app/additives.py and app/off.py's texts (in that order)
  js/engine/aiguard.js  KH.aiguard: app/ai/guard.py's fold + BLOCKLIST (same pattern and look-alike table), used only to
                        mask the raw provider answer in Settings → AI activity (tests/test_ai_guard_twin.py)
  js/mock/barcode.js    demo POST /api/foods/barcode (three recorded Open Food Facts products); js/mock/foods.js answers
                        gtin, ingredients_text and the v0.3 Food fields
  vendor/barcode-detector-3.2.2/ponyfill.iife.js, vendor/zxing-wasm-3.1.3/zxing_reader.wasm   the WASM barcode
                        reader (MIT, ZXing-C++ Apache-2.0), pinned by SHA-256 in vendor/README.md (scripts/vendor_barcode.py)
  vendor/pdfjs-dist-6.4.299/pdf.min.mjs, pdf.worker.min.mjs, LICENSE   pdf.js (Apache-2.0, the legacy build), imported and started as a Worker
                        by js/engine/pdf_pages.js on the first lab report PDF only; not in sw.js's shell list; same pins and script
  js/learn.js           KH.learn: links into the handbook at /learn (M3; see "M3: the handbook at /learn")
  js/views/ai.js, css/ai.css   KH.ai: the optional AI UI (M2 ai; see "M2 API: AI and photos" → Frontend)
  js/views/ai_routing.js   KH.aiRouting: Server administration's "Which AI does each feature use?" table and a person's
                        "where each feature runs" lines (privacy tiers, tier 1; see "Privacy tiers: roles and routing")
  js/views/ask.js, css/ask.css   the Ask screen: a sixth tab shown only when GET /api/ai/status says features.chat (assistant
                        step 2; see "Ask chat"); in the demo the tab shows a note and no input; the cards for a save and for a
                        taste (Remember, Cancel, Undo; see "Saving from the chat")
  js/mock/ai.js         demo answers: a server with AI off (GET /api/me/ai; /api/ai/* and /api/vision/* 404)
  js/mock/handbook.js   demo answer for GET /api/handbook (none; the Pages demo links to the handbook beside it)
  js/mock/meta.js       demo answer for GET /api/meta (nothing optional switched on; the registry from js/engine/rules.js; tests/data/meta_vectors.json)
  js/main.js            boot
```

`scripts/build_preview.py` inlines the `<link rel="stylesheet">` and `<script src>` tags of
`index.html` in document order. With `--pages DIR` (v0.3.1) it writes the same demo as a static site for
GitHub Pages instead: the stylesheets and scripts as files under their own paths, `index.html` with the
app's policy (`CSP_DIRECTIVES` of `app/security.py`, read from the source, less `frame-ancestors`) as a
`<meta http-equiv="Content-Security-Policy">` before anything it governs, no inline script (the food
database is an `application/json` block), and `preview-flag.js`, which sets `window.KDL_PREVIEW` and
`window.KDL_DEMO_HANDBOOK` (`{url: "../", links: APP_LINKS}`, the table of `app/guidance/topics.py` that
`GET /api/handbook` also serves): `js/mock/handbook.js` then answers like a server with
`HANDBOOK_PUBLIC_URL` set to the handbook one level up, so the demo's Learn links work. The absolute
paths of the markup become relative (`/learn/` → `../`; anything else absolute stops the build). The
handbook Pages workflow builds it into `site/demo/` before the link check, and the Pages handbook's
announce bar links to it (`extra.demo_link` in `handbook/mkdocs.pages.yml`; empty in the `/learn` copy). **Parity rule:** every JS twin of server logic (`js/engine/*`,
`js/mock/*`) is checked against the server by shared vector files in `tests/data/*.json`, run by
pytest on the Python side and by `node tests/js/run_vectors.mjs` on the JS side (CI runs both).
`tests/data/README.md` describes each vector file and how to replay it in another client.
The mock routes as a whole are checked against a real, signed-in server by `tools/e2e/parity.py`
(run by hand; see `tools/e2e/README.md`).
In demo/preview mode the user is a signed-in demo admin; AI, Open Food Facts and USDA calls
answer "available in the installed app" except for a few recorded barcode fixtures.
The demo's state is in memory unless the person turns on **Keep my data in this browser** (IndexedDB, demo build only; see that section at the end of this file).

### Sign-in screens and Settings (M1)

* **Boot** (`js/main.js` → `KH.auth.boot()` in `js/views/auth.js`): `GET /api/auth/status` decides
  between the first-run **setup** screen (setup code from the server log, the first admin, and the
  "Look up barcodes with Open Food Facts" box that sets `food.off_enabled`), **sign-in**, the
  **invite** and **reset** screens (`#/invite/<token>`, `#/reset/<token>`; the page moves the token
  out of the address bar at once, into memory and this tab's `sessionStorage` so a reload keeps the link
  usable, and drops it after use; the reset screen asks `POST /api/auth/reset/info` whose account it
  is and shows the username in a read-only `autocomplete="username"` field, with welcome wording for
  an account an admin created), the **new password** screen (`must_change_password`), the proxy
  "Sign in again" screen (`/?reauth=1`), and the app. Tabs and the header gear carry
  `data-signed-in` and stay hidden until someone is signed in. An error about one field is also
  shown under that field (`.field-error`, linked with `aria-describedby`; a `field: ` prefix in the
  server's message is dropped), because the screen's alert region sits above the fold on a phone. `AUTH_MODE=none` shows a red banner;
  plain HTTP shows a yellow note, and `https_required` a red one.
* **API hooks** (`js/core.js`, one error path for the server and the demo API): `401` → sign-in
  screen, then back to the same view (a different person → a fresh page); `403 reauth_required` →
  the "Enter your password again" sheet, `POST /api/auth/reauth`, and the request is sent again
  once; `403 password_change_required` → new-password screen; `503 setup_required` → setup screen.
  `KH.download()` saves the export zip through the same path.
* **Sign-out** warns about unsynced offline entries when `KH.offline` exists (M2), calls
  `POST /api/auth/logout`, follows `redirect` (proxy `PROXY_LOGOUT_URL`), else reloads the page.
* **Settings view** (`#settings`, no tab; header gear and Profile → Open Settings;
  `js/views/settings.js`): Account (name, password, two-step sign-in from `js/views/two_step.js` (note 17), passkeys from `js/views/passkeys.js` (note 18), sharing from `js/views/sharing.js` (note 19), signed-in devices, export zip, delete account,
  recent activity, sign out), Preferences (theme saved as `ui.theme`, week start saved with the
  profile, units for lab results), Food data (own USDA key, shared-key status, Open Food Facts
  consent), AI ideas (placeholder `#set-ai-slot` for M2), This device (install, offline, storage,
  connection, version, clear offline data; `js/pwa.js` supplies the device state), Admin (admins
  only: a link to Server administration) and About & privacy (licences). Every setting shows its source ("Set by the server
  (ENV), locked" / your choice / admin / app default). Keys are write-only: an empty password
  field, "Set · ends in 9xQz · updated Oct 3", Replace / Remove, never a value from the server.
  The key buttons are **Test and save** and **Save**: `PUT /api/me/keys/{p}` stores the key whatever
  the test says, so a test-only button would mislead. The theme and Install panel moved here from Profile.
  The sign-in screen never hints at an account name (an upgraded v0.2 server's admin is `admin` or
  `ADMIN_USERNAME`; the server log, CHANGELOG and `docs/accounts.md` tell the operator): a public page
  must not reveal who has an account.
* **Server administration** (v0.3.1; `#admin`, no tab; the header shield `#admin-open`, which
  `js/views/auth.js` shows only for `role = "admin"` through `data-admin-only`, and Settings → Admin;
  drawn by `js/views/settings.js`): People (accounts, invites and one-time links), Server settings,
  Shared keys, Usage, Activity log, About this server, and AI providers (`KH.ai.renderAdmin`, moved out
  of Settings → AI ideas), with jump chips like Settings'. A member who opens `#admin` sees a one-line
  note and the page makes no `/api/admin` request; the server's `require_admin` is the real guard
  (`tests/test_admin_page.py`).

## Milestones

* **M1 foundation:** accounts, settings, secrets, security middleware, migrations framework,
  scoping, admin CLI, healthcheck, PWA shell, frontend restructure + sign-in/setup/settings UI,
  rootless/hardened deploy assets, CI/release pipeline. Handbook writing runs in parallel.
* **M2 features:** personalised targets + labs + eGFR; guidance engine; AI; barcode/photo;
  offline outbox; their UI and mock twins.
* **M3 integration:** `/learn` mount and handbook build in the image, contributor docs, e2e
  harnesses in `tools/e2e/`, full review, preview rebuild, PR.

M2 and M3 run as one build (owner's decision, 2026-10-06): one integration pass, one review,
then a single **v0.3.0** release containing M1, M2, M3 and the handbook.

**Status (2026-10-07): v0.3.0 is complete.** Built, integrated, reviewed, and every confirmed review
finding fixed with tests (CHANGELOG.md 0.3.0, "Fixes from the release review"). What this build could
not verify (real phones, live AI providers, a Raspberry Pi, clinical sign-off) is listed under "Known
limitations" there, the checks a maintainer runs before tagging are in `docs/maintainers.md`
("Checks before the tag"), and everything deferred or left open, with its owner, is in
`docs/ROADMAP.md`. The build agents' progress notes were condensed into those files and removed
(`docs/dev/progress/README.md`).

**Status (2026-10-22): v0.4.0 is prepared.** Everything merged after v0.3.0 ships in it: no v0.3.1 was ever tagged, so the
"v0.3.1" batch (tolerances, "Not chosen yet", the admin page, running high, the Pages demo, the CSV lab import), the assistant
(tokens, MCP, Ask, voice, saving), symptoms and visit prep, the health-data imports, offline edits, privacy tiers, food
preferences and the Python 3.15 image. What it could not verify is listed under "Known limitations" in CHANGELOG.md 0.4.0, the
checks a maintainer runs before tagging are in `docs/maintainers.md`, and everything deferred or left open, with its owner, is in
`docs/ROADMAP.md`. The progress notes of this build were condensed into those files and removed
(`docs/dev/progress/README.md`).

**Status (2026-10-29): v0.10.0 is prepared.** It adds read-only sharing (note 19, schema step 24), passkeys for re-entry and in
the sign-in box's autofill (note 18 §10), QR pairing for the iPhone app and first values from the environment (note 20); CHANGELOG.md
0.10.0. **v0.9.0** added two-step sign-in (note 17, schema step 22), "Admins must use two-step
sign-in" (`auth.require_two_step_admins`) and passkeys (note 18, schema step 23); CHANGELOG.md 0.9.0. **v0.8.0** added recipes from AI (note 16 phase 3: the feature `recipes`,
`POST /api/ai/recipes`, steps behind `ai.recipe_steps`; no schema step; CHANGELOG.md 0.8.0). **v0.7.0** added recipes and "Fit to my targets" (note 16 phases 0 to 2, schema
step 21, `POST /api/guidance/fit-recipe`, the twin `engine/guidance/recipes.js`; CHANGELOG.md 0.7.0). **v0.6.0** added a cloud AI from the environment (`AI_CLOUD_*`, schema step 20), a chain of
companies in `AI_CLOUD_UPSTREAM`, "How well each AI is doing", the answer before "nothing fits" and the access fixes from the audit
(CHANGELOG.md 0.6.0). **v0.5.0:** everything merged after v0.4.0 shipped in it: weight and blood pressure (schema
step 18, `/api/body`, the screens and the Health app import), the imports that take the `.zip` itself, lab results from a PDF
report, phone shortcuts (device tokens, `POST /push/v1/body`, schema step 19), the assistant's taste tool behind the
`assistant:prefs` scope, the checked-in OpenAPI document and `GET /api/meta`, the brand strings in one place, the kidney rules
in their own module, and the screen fixes. What it could not verify is listed under "Known limitations" in CHANGELOG.md 0.5.0,
the checks a maintainer runs before tagging are in `docs/maintainers.md`, and everything deferred or left open, with its owner,
is in `docs/ROADMAP.md`. The progress notes of this build were condensed into those files and removed
(`docs/dev/progress/README.md`).

## M1 API

Built in M1 (backend-core accounts) from note 07 §4.4–§4.17 and its §9 security review, plus the
identity items of note 01 §10. Code: `app/auth/` (`deps`, `routes`, `me`, `admin_api`, `sessions`,
`throttle`, `passwords`, `policy`, `proxy`, `tokens`, `ratelimit`, `bootstrap`), `app/account.py`
(export, deletion), `app/admin.py` (CLI), schema step `app/migrations/m003_accounts.py`.

### Identity and request rules

* **Modes** (`AUTH_MODE`): `local` (default; username + password, cookie session), `proxy` (identity
  from `TRUSTED_PROXY_USER_HEADER`, only from `TRUSTED_PROXIES` with a matching `X-Proxy-Secret`;
  `TRUSTED_PROXY_SECRET_FILE` is required and `0.0.0.0/0`/`::/0` are refused at start-up), `none`
  (no sign-in: every request is user 1, an admin; `GET /api/auth/status` says `"no_login": true` so
  the UI shows a red banner).
* **Every `/api` route needs a signed-in, active person** except `GET /api/auth/status` and
  `POST /api/auth/{login,setup,register,reset,reset/info}`. A bearer token is never a sign-in here: the
  `Authorization` header is read only by the two bearer surfaces, `/mcp` and `/push/v1` (`/push/v1/body` and its check; "Assistant access tokens" and "Device tokens and `/push/v1`" below). Anonymous → `401 {"detail": "Sign in required"}`
  (dependencies run before body validation, so an invalid body is still 401). Admin routes →
  `403 {"detail": "Admins only"}` for others. `tests/test_auth_coverage.py` checks every route,
  including ones hidden from the OpenAPI schema.
* **Before first-run setup** every protected route and login/register/reset answer
  `503 {"detail": "Setup required", "setup_required": true}`.
* **`must_change_password`**: every route except `POST /api/me/password` and `POST /api/auth/logout`
  answers `403 {"detail": "Choose a new password first", "password_change_required": true}`.
* **Re-authentication**: sensitive routes need the password entered on this session within
  `REAUTH_MINUTES` (10), else `403 {"detail": "Please enter your password again", "reauth_required":
  true}`; the client calls `POST /api/auth/reauth` and retries once. Signing in counts as entering
  the password. Proxy and none modes have no local password and skip this check. Marked *(re-auth)*
  below.
* **Scoping**: every query takes the signed-in person's `user.id`; not found and not yours are both
  **404**. Admins have no route that reads another person's log, foods, meals, profile or keys.
* **Sessions**: opaque `<selector>.<verifier>` (SHA-256 of the verifier stored). Cookie
  `__Host-kh_session` (`Secure; HttpOnly; SameSite=Lax; Path=/`) when the effective scheme is
  HTTPS, `kh_session` (same, without `Secure`) on plain HTTP; each scheme reads only its own name.
  30 days absolute (`SESSION_MAX_DAYS`), 14 days idle (`SESSION_IDLE_DAYS`); a new session id at
  sign-in, password change and role change. A one-year device cookie (`__Host-kh_device` /
  `kh_device`, `SameSite=Strict`) lets the owner's device skip that account's sign-in delay.
* **Plain HTTP** (`ALLOW_INSECURE_HTTP`, unset = automatic): sign-in, setup and registration over
  non-loopback plain HTTP are allowed while the server has at most one active account (counting the
  one being created); otherwise `400 {"detail": "HTTPS required…", "https_required": true}`. Open
  registration always needs HTTPS.
* **Throttling**: per account name (5 free failures, then 30 s doubling to 15 min, `429` with
  `Retry-After`), per client IP (`LOGIN_IP_MAX_FAILURES` in 10 min → 10-min block; on sign-in every
  refusal counts: a wrong password, the name-delay `429` and `400 https_required`; plus at most 30
  sign-in attempts per minute; IPv6 addresses count per /64, IPv4-mapped ones as IPv4; skipped for
  `TRUSTED_PROXIES` and rootless gateway addresses), 60 sign-ins per minute instance-wide (taken
  only after those cheap checks, right before the hash; queued up to 5 s, then `503`), 2 password
  hashes at a time (`503` + `Retry-After: 1`), 100 consecutive failures lock the account (an admin
  reset link or the CLI unlocks it). `POST /api/auth/login` is an `async` route: both waits are
  awaited on the event loop and only the database work and the hash run in worker threads, so a
  sign-in flood never ties up the thread pool other routes need. Unknown, disabled and locked
  accounts get the same answer after the same single hash. Other limits (`app/auth/ratelimit.py`):
  open registration 3/hour per IP (per /64), key tests 10/hour, exports 10/hour.
* **Last-admin rule**: the check and the write that depends on it run in one `BEGIN IMMEDIATE`
  transaction (`PATCH`/`DELETE /api/admin/users/{id}`, `DELETE /api/me`), so two admins removing each
  other at once leave one admin.
* **Errors** keep the `{"detail": "…"}` shape and may add keys: `reauth_required`, `setup_required`,
  `password_change_required`, `https_required`, `retry_after`, `field`, `problems` (password policy
  messages), `reason` (USDA key resolution), `locked_by_env`.
* **`X-KDL-Version`** (note 02 §5, §6 item 9): every `/api` response, errors included, carries the
  shell version (`app/pwa.py` `ApiVersionMiddleware`; the same 12-hex hash as `/sw.js`). The page asks its
  controlling worker for the version it was served from (`postMessage('VERSION')` → `{type: "kdl-version",
  version}`), `KH.api` passes every answer's header to `KH.pwa.versionSeen`, and on a difference the page
  fetches the new worker at once, whose install shows the "Update ready · Reload" toast. API changes stay
  additive, so the old shell keeps working until the person reloads (a change that is not additive raises `API_VERSION`: "The API document and
  `GET /api/meta`").

```json
Me = {"id": 1, "username": "mum", "display_name": "Mum", "role": "admin",
      "auth_source": "local", "must_change_password": false, "created_at": "2026-10-06T08:00:00.000000Z"}
```

### `/api/auth`

| Method and path | Auth | Body → response |
|---|---|---|
| `GET /api/auth/status` | public | → `{setup_required, auth_mode, registration ("invite"\|"closed"\|"open"\|"disabled"), insecure_http, https_required, password_min_length, password_max_length (128), instance_name, user: Me\|null, logout_url, no_login, passkeys}`; `passkeys` is true in local mode when this address is a name, not an IP address (the sign-in page then offers a passkey, note 18) |
| `POST /api/auth/setup` | public + setup code | `{code, username, display_name?, password, off_enabled?}` (proxy mode: `{code}`, identity from the header) → `{user: Me}`; claims user 1 (keeps the migrated data), signs in. 400 wrong/expired code, 409 already set up. 404 in none mode |
| `POST /api/auth/login` | public | `{username, password, code?}` → `{user: Me, notice}` + cookies; with two-step sign-in on (note 17 §5), the right password and no `code` is a 401 `{detail, totp_required: true, field: "code"}` that is not counted, a wrong code the same 401 counted as a failed sign-in (audit `login.failed` with `via: "code"`), and a recovery code signs in once with a `notice` saying how many are left; 401 `{"detail": "Username or password is incorrect"}`, 429, 400 HTTPS required. 404 in proxy/none mode. `notice` (N12): "Your password was reset with a link from an admin on …" once, at the first password sign-in after an admin's reset link changed the password (compared with the newest `login.succeeded` audit event, not `last_login_at`, which the reset's own sign-in updates) |
| `POST /api/auth/logout` | user | → `{ok: true, redirect?}` (proxy: `PROXY_LOGOUT_URL`); deletes the session, expires both cookie names, `Clear-Site-Data: "cache", "storage"` |
| `POST /api/auth/register` | public + invite token (or open mode) | `{token?, username, display_name?, password}` → 201 `{user: Me}`, signed in. 403 closed/no invite, 400 bad token, 409 username taken |
| `POST /api/auth/reset` | public + reset token | `{token, password}` → `{user: Me}`; claims the single-use link first (two racing requests: one 200, one 400), signs out every other session, voids the account's other open links, clears `locked`, activates a new account. With two-step sign-in on it sets the password but does not sign in: `{user: null, totp_required: true}` |
| `POST /api/auth/reset/info` | public + reset token | `{token}` → `{username, display_name, new_account, expires_at}` for the page the link opens (the owner of an admin-created account never saw its username); 400 (counts as a per-IP failure) when the link is not valid. 404 in proxy/none mode |
| `POST /api/auth/passkey/options` | public | → `{challenge_id, publicKey: {challenge, rpId, timeout, userVerification: "required", allowCredentials: []}}` for `navigator.credentials.get`; a single-use challenge for 5 minutes, kept in memory. 30 a minute per address (`passkey_options`); the per-address sign-in block and HTTPS rule apply. 404 in proxy/none mode (note 18 §5) |
| `POST /api/auth/passkey` | public | `{challenge_id, credential}` (the `PublicKeyCredential.toJSON()` of the answer) → `{user: Me, notice}` + cookies, as a password sign-in but without the two-step code. Every failed check is the same 401 `"That passkey did not work. Try again, or sign in with your password."`, counted against the address (audit `login.failed` with `via: "passkey"` when the passkey is known); a signature counter that did not go up is refused and audited `passkey.counter_went_back`. Success: audit `login.succeeded` with `via: "passkey"`. 404 in proxy/none mode |
| `POST /api/auth/reauth/passkey/options` | user (local) | → `{challenge_id, publicKey}` for `navigator.credentials.get` listing only this person's passkeys (`allowCredentials`), with a challenge tied to them. 409 with no passkey; 30 a minute (`passkey_options`). Note 18 §10 |
| `POST /api/auth/reauth/passkey` | user (local) | `{challenge_id, credential}` → `{ok: true, reauth_until}`, as `/api/auth/reauth` with a password: only this person's own passkey counts, with the checks of a passkey sign-in. A failure is 403 `"That passkey did not work. Try again, or type your password."` and counts toward the same five failures as a wrong password (the fifth signs the device out: 401); audit `login.failed` with `via: "passkey_reauth"` |
| `POST /api/auth/reauth` | user (local) | `{password}` → `{ok: true, reauth_until}`; wrong → 403; 5 wrong in a row revoke the session (401) |

Usernames (local): 3–64 of `a-z 0-9 . _ @ + -` after NFKC + casefold (stored as typed for display).
Passwords: 15–128 code points (`PASSWORD_MIN_LENGTH`, 8–64), NFC, no composition rules; refused when
on the blocklist (10,000 most common NCSC entries ≥ 8 characters), equal to the username, display
name or app/instance name, one repeated character or a straight keyboard/alphabet/digit run;
optional HIBP check (`PASSWORD_BREACH_CHECK`, off by default; the k-anonymity range API through
`app/egress.py`'s `CheckedTransport`, no redirects, `trust_env=False`). Tokens in links travel in the URL fragment:
`/#/setup`, `/#/invite/<id>.<verifier>`, `/#/reset/<id>.<verifier>`; links are built from
`PUBLIC_URL` (else the request's origin).

### `/api/me`

| Method and path | Auth | Body → response |
|---|---|---|
| `GET /api/me` · `PATCH /api/me` | user | → Me; PATCH `{display_name}` |
| `DELETE /api/me` | user + password | `{password, confirm: "DELETE"}` → 204, cookies cleared, `Clear-Site-Data`; 409 for the last active admin, and always 409 with `AUTH_MODE=none` (every request is user 1; start-up also recreates a missing user 1 in that mode). Deletes the account and everything it owns (cascade), after deleting the unused invites and links it created |
| `POST /api/me/password` | user (local) | `{current_password, new_password}` → `{user: Me}`; signs out other devices, voids open reset links for the account, renews this session |
| `GET /api/me/totp` | user | → `{available, enabled, enabled_at, recovery_codes_left, required}` (never the secret); `available` is false outside local mode and for a proxy account; `required` is true for an admin while `auth.require_two_step_admins` is on |
| `POST /api/me/totp/setup` | user (local) *(re-auth)* | → `{secret, uri, issuer, account, digits: 6, period: 30}`: a new pending secret (the only time it leaves the server; replaces an unfinished one). `uri` is the `otpauth://totp/…` link for a QR code. 409 when on |
| `POST /api/me/totp/enable` | user (local) *(re-auth)* | `{code}` → `{recovery_codes: [10], signed_out: n, enabled, enabled_at, recovery_codes_left}`: on when the code is right for the pending secret (that step counts as used); the other sessions are signed out; audit `totp.enabled`. 400 wrong code (`field: code`), 409 nothing pending or already on, 429 after 10 tries in 15 minutes (`totp_enable`) |
| `POST /api/me/totp/recovery-codes` | user (local) *(re-auth)* | → `{recovery_codes: [10], …status}`: a new set, the old one void; audit `totp.recovery_codes_renewed`. 409 when off |
| `DELETE /api/me/totp` | user (local) *(re-auth)* | → 204: off (or an unfinished setup dropped), recovery codes deleted, sessions kept; audit `totp.disabled` (`via: self`) when it was on |
| `GET /api/me/passkeys` | user | → `{available, usable, reason, passkeys: [{id, name, created_at, last_used_at, backed_up}], max: 10}` (never a key or credential ID); `usable` is false, with `reason`, when the server is opened by an IP address |
| `POST /api/me/passkeys/options` | user (local) *(re-auth)* | → `{challenge_id, publicKey}` for `navigator.credentials.create`: the RP (`PUBLIC_URL`'s host, else this request's), the person's user handle, ES256/EdDSA/ES384/ES512/RS256, `residentKey: "required"`, `userVerification: "required"`, `attestation: "none"`, the person's passkeys as `excludeCredentials`. 409 at 10 passkeys or on an IP address; 30 a minute (`passkey_options`) |
| `POST /api/me/passkeys` | user (local) *(re-auth)* | `{challenge_id, name?, credential}` → 201 the new item: the WebAuthn §7.1 checks (`app/auth/webauthn.py`); audit `passkey.added`. 400 with the reason when a check fails or the challenge is used, old or someone else's; 409 at 10 or when the passkey is already stored |
| `PATCH /api/me/passkeys/{id}` | user (local) | `{name}` → the item; 404 if not yours |
| `DELETE /api/me/passkeys/{id}` | user (local) *(re-auth)* | → 204; audit `passkey.removed` (`via: self`); 404 if not yours |
| `GET /api/me/shares` | user | → `{enabled, areas, max: 10, sharing: [{id, name, username, areas, since, until, last_viewed_at, active}], codes: [{id, areas, days, created_at, expires_at}]}` (never a link); `enabled` false while `sharing.enabled` is off; 404 in `AUTH_MODE=none` |
| `POST /api/me/shares` | user *(re-auth)* | `{areas, days?}` (1 to 4 of `food`, `labs`, `body`, `symptoms`; `days` 1 to 365 makes the share end that long after it is accepted, absent or null: until stopped) → 201 `{code, link}`: `/#/share/<id>.<verifier>`, shown only here, works once for 7 days; 409 at 5 unused links or 10 shares; audit `share.code_created` |
| `DELETE /api/me/shares/{id}` | user | → 204: stops a share (audit `share.ended`, `by: owner`) or cancels a link (`share.code_cancelled`); 404 if not yours or already ended |
| `GET /api/me/sessions` | user | → `{sessions: [{id, created_at, last_seen_at, expires_at, user_agent, ip_prefix, current}]}` |
| `DELETE /api/me/sessions/{id}` | user | → 204 (404 if not one of yours) |
| `POST /api/me/sessions/revoke-others` | user *(re-auth)* | → `{revoked: n}` |
| `GET /api/me/settings` · `PATCH /api/me/settings` | user | → `{settings: {key: {value, source ("env"\|"user"\|"instance"\|"default"), editable}}}`; PATCH `{key: value \| null}` (null = back to inherited); 400 invalid/unknown, 403 not a personal key, 409 locked by env |
| `GET /api/me/keys` | user | → `{providers: [KeyItem]}` |
| `PUT /api/me/keys/{provider}` | user *(re-auth)* | `{api_key, test?}` → KeyItem (+ `test: "ok"\|"rejected"\|"unreachable"`); 8–512 printable ASCII, no spaces; 403 when personal keys are off |
| `DELETE /api/me/keys/{provider}` | user *(re-auth)* | → 204 |
| `GET /api/me/usage` | user | → `{days: 30, usage: [{provider, scope, today, last_30_days}], by_day: [...]}` |
| `GET /api/me/activity?before=&limit=` | user | → `{events: [AuditEvent]}` (own sign-in, session, password, key and export events: events about the person's account, whoever acted, and their own actions except those on another account) |
| `GET /api/me/tokens?family=` | user | `family` is `assistant` (default, so the Assistant access screen is unchanged) or `device` (else 400) → `{family, enabled, max_active: 5, expiry_days: [30, 90, 365], default_expiry_days: 90, tokens: [TokenItem]}` for that family only; `enabled` is that family's switch (`assistant.enabled` / `push.enabled`); works while it is off. A device token's item also holds `sent: {weights, readings}` ("Assistant access tokens", "Device tokens and `/push/v1`") |
| `POST /api/me/tokens` | user *(re-auth)* | `{name, expires_in_days?: 30\|90\|365, can_log?: bool = false, can_prefs?: bool = false, family?: "assistant"\|"device" = "assistant"}` → 201 TokenItem + `token` (the only time it is sent); `can_log` adds the scope `assistant:log` (save food and recipes) and `can_prefs` the scope `assistant:prefs` (remember tastes: `set_food_preference`), two separate choices, neither giving the other (both give `assistant:read`); both are a 400 for a device token, whose one scope `body:write` is never chosen; 409 that family's switch is off, 400 five active **in that family**, 429 after 20 in an hour (both families together) |
| `DELETE /api/me/tokens/{id}` | user | → 204 (also while the switch is off; an ended token: no change); 404 if not yours |
| `DELETE /api/me/tokens/{id}/body-rows` | user | "Delete what it sent": → `{deleted: {weights, readings}}` after deleting every weight and reading the person's **device** token `id` sent (`api_token_id`), nothing else; works for a revoked or expired token still listed; audit `body.token_rows_deleted`; 404 if not yours, not a device token or already purged |
| `GET /api/me/export.zip` | user *(re-auth)* | → `application/zip` (`Content-Disposition: attachment; filename="kidney-health-<username>-<date>.zip"`, `Cache-Control: no-store`) with `export.json`, `log.csv`, `foods.csv`, `meals.csv`, `labs.csv`, `symptoms.csv`, `weights.csv`, `blood_pressure.csv`, `README.txt`; no passwords, sessions or keys |
| `POST /api/me/import?dry_run=&merge=&replace_profile=` | user *(re-auth)* | body: the `export.json` file as `application/json` (up to `MAX_IMPORT_BYTES`, 16 MiB, for this path only) → the report below; 400 the file is refused (naming the record kind and position), 409 the account has data and `merge` was not set, 413 too large, 415 not JSON, 429 after 20 in an hour. See "Import of `export.json`" |

```json
KeyItem = {"provider": "usda", "label": "USDA FoodData Central",
           "own": {"set": true, "last4": "9xQz", "updated_at": "…"},          // or {"set": false}; {"set": true, "status": "unreadable"} after a lost SECRET_KEY
           "shared": {"available": true, "remaining_today": 187, "daily_limit": 200},
           "user_keys_allowed": true, "effective": "own" | "shared" | "none"}
export.json = {"format": "kidney-health-export", "version": 1, "exported_at", "app_version",
               "user": {username, display_name, created_at}, "profile", "settings", "log_entries",
               "custom_foods", "linked_foods", "meal_templates", "lab_results",
               "symptoms",           // [{id, date, symptom, label, severity, note, created_at}] oldest day first (schema step 15); an optional list added to version 1
               "weights",            // [{id, date, time, kg, context, note, source, source_key, created_at, updated_at}] oldest day first (schema step 18); optional, likewise
               "blood_pressures",    // [{id, date, time, systolic, diastolic, pulse, context, note, source, source_key, created_at, updated_at}] (schema step 18); optional, likewise
               "ai_audit", "activity",
               "food_preferences",   // [{food_id, name, preference, created_at, source, updated_at}] (schema steps 5 and 17): preference like | less | not_for_me | neutral, source person | ask | assistant
               "ai_usage", "ai_consents", "ai_provider",   // AI (schema step 6), see "Data, export, deletion and retention"
               "builtin_foods"}      // [{id, name, fdc_id}]: the built-in foods the person's entries, meals and food preferences use (import)
// linked_foods items: {id, name, source, fdc_id, linked_at, gtin, food}; food = the whole record, shaped like a custom_foods item (import)
// log_entries items: the API's Entry without "version" (it is worked out from the content, so a new export stays importable by an older
//   server); the import accepts and ignores a "version" key
```

### Import of `export.json` (`POST /api/me/import`, `app/data_import.py`)

The body is the exact JSON file the export wrote. The browser (`js/views/settings.js`, Settings → Account → Your
data → Import from a file) takes the export `.zip` itself or the `export.json` inside it (a `.zip` is opened on the device and
only its `export.json` is read, up to 16 MiB: see "Reading a .zip in the browser" below; the server never gets an archive),
leaves out the sections the import never reads (`user`, `ai_audit`,
`activity`, `ai_usage`, `ai_consents`, `ai_provider`), calls it with `dry_run=1`, shows the report and imports
with a second call. Both calls need the password entered recently, the app header (CSRF) and the signed-in
person; they act on that person only (`user.id`), never on a name or id in the file.

* **Reading the file** (`parse_export`, nothing is written until all of it is good). `json.loads` refuses NaN,
  Infinity and numbers beyond a float. `format` must be `kidney-health-export` and `version` `1` (others: 400 with
  the version named). Then pydantic models with `extra="forbid"`, strict types and bounded lists and strings, built
  on the API's own limits and validators (`FoodCreate`'s bounds and `validate_nutrients`/`validate_flags`/
  `validate_gtin`, `LogCreate`'s servings, grams, date and 500-character note, `MealTemplateCreate`'s name and
  note, `LabCreate` for every lab result, `ProfileUpdate` for the profile with its targets, the settings
  registry's own models for the settings), so an imported record is never one the API would refuse. Lists are
  capped (30,000 entries, 5,000 own foods, 5,000 linked foods, 1,000 saved meals of at most 100 foods, 5,000 labs,
  1,000 food preferences, 200 settings). Timestamps must be real UTC times from 2000 to tomorrow. A source address
  must be an Open Food Facts product page or the FoodData Central address, a licence one the app writes. The first
  problem refuses the whole file: `400 {"detail": "The file was not imported. log_entries[17].servings: …", "kind":
  "log_entries", "index": 17}`; messages are cut at 200 characters and never repeat a value. Food ids must be
  unique across `custom_foods`, `linked_foods` and `builtin_foods`. Top-level keys the export does not write are
  refused. `user`, `ai_audit`, `activity`, `ai_usage`, `ai_consents` and `ai_provider` are accepted and **never read**.
* **Never imported, even if present:** the `user` section, passwords, sessions, assistant tokens, AI keys, providers,
  consents and usage, AI and sign-in activity, other people's data, instance settings, and the personal settings that
  are consents (`food.off_consent`, `ai`). Ids are never taken from the file. The ids of entries, saved meals and labs
  are dropped; `client_id` is dropped (a replay token of the device that made it).
* **Foods first** (`Importer.resolve_foods`), each file id mapped to an id here: an own food equal to one the person
  already has (name, brand, category, serving, values, flags, notes, barcode, hidden) is reused, else inserted by
  `foods.insert_food` after the additive scan of `POST /api/foods`; a linked USDA food (`fdc_id`) or Open Food Facts
  food (barcode) is linked with `foods.link_food` when this server has the same shared row (and its name, or serving
  weight when the file has the record, agrees), otherwise it is kept as an own food made like `POST
  /api/foods/{id}/copy` when the file carries its record, and otherwise reported as skipped. **A shared row is never
  created from a file.** A built-in food is found by `builtin_foods[].fdc_id` (or its name when it has none); in a file
  without `builtin_foods` an id that the file describes nowhere is tried as a built-in food id, and must carry one of
  the names the file gives it. Only `source = 'builtin'` rows are ever matched by id.
* **Then** entries (`insert_entry` with the file's `created_at`/`updated_at`, `purpose` kept as it was, `grams`
  dropped for a food whose serving weight does not describe its values), saved meals (`insert_template`; a food that
  cannot be matched is dropped from the meal, listed, and named in the meal's note ("Imported without 1 food that
  could not be matched: …") so its totals never read as complete; a meal left with none is skipped), labs (the canonical value
  recomputed from `entered_value` and `entered_unit`), food preferences (`like`, `less`, `not_for_me` or `neutral`
  with the file's `source` and `updated_at`; a file from before schema step 17 has neither, and its rows import as
  `person`, changed when made; the app's limits are 1,000 in all and 500 "Not for me"). **The nutrient numbers
  of an entry are recomputed from its food and servings, never taken from the file.** An entry, saved-meal food or
  food preference that cannot be matched is skipped and listed (kind, position, a short label and the reason).
* **Duplicates.** If the account has any log entry, own food, saved meal, lab result, symptom, weight or blood pressure reading and `merge` is not set, nothing is
  imported: a dry run answers `200` with `can_import: false` and `blocked: {code: "account_not_empty", existing}`, the
  import `409`. With `merge=1` what is already there is left out, counted against what the account had before the
  import (so a file with the same entry twice adds one when the account has one): an entry by (date, meal, food,
  servings, grams, status, created time), an own food as above, a saved meal by (name, note, slot, foods and servings),
  a lab result by (test, date, value as shown), a weight or blood pressure reading that came from an import by its `source_key` (a typed one by
  its date, time, numbers, context and note; a 21st weight or 31st reading of a day is skipped and listed), a food preference (by food, whatever
  its value) and a shared-food link by their keys. There is no "replace my data" mode: the choices are the ones above.
* **Profile.** Only with `replace_profile=1` (default off): the profile fields, the targets (replaced, not merged;
  `profile.apply_profile_changes`, the body of `PUT /api/profile`; a stage or diabetes type the file marks "not chosen
  yet" stays unchosen) and the settings `guidance`, `ui.theme`, `user.units.labs`, `food.scan_prefer_camera`, `user.units.weight`,
  `body.weight_alarm` and `body.bp_goal` (the last two are the numbers the person's care team gave them; validated by the registry; a locked one
  is skipped and listed). They are clinical settings the person may have
  agreed with their care team on this server.
* **One transaction.** After parsing, `BEGIN IMMEDIATE`, then everything above, then (import only) the audit row and
  `COMMIT`; any error rolls back. A dry run does the same work and rolls it back, so its answer is exactly what the
  import would do and it writes nothing (no row, no id, no revision). A locked database answers 503.
* **Report** (both calls): `{dry_run, imported, can_import, blocked, file: {format, version, exported_at, app_version,
  records}, options: {merge, replace_profile}, counts: {log_entries, custom_foods, shared_foods_kept_as_own,
  shared_foods_linked, built_in_foods_matched, meal_templates, lab_results, symptoms, weights, blood_pressures, food_preferences, profile, settings},
  already_there: {…}, skipped: {total, shown (≤ 100 of {kind, index, label, reason}), by_kind, more}, not_selected,
  not_imported, rule}`.
* **Activity.** One `data.imported` row (user-visible) with `log_entries`, `custom_foods`, `meal_templates`,
  `lab_results`, `symptoms`, `weights`, `blood_pressures`, `food_preferences`, `merge` and `profile`: counts only, no content.
* **Size and cost.** `MAX_IMPORT_BYTES` (16 MiB) is registered with `security.register_body_limit` for exactly
  `/api/me/import`; every other path keeps `MAX_BODY_BYTES`. Measured: a year at eight entries a day is 3.5 MB as
  the export writes it (2.2 MB minified); a 15 MB file with 13,000 entries imports in about 1.5 s and needs about
  90 MB of extra memory (the shipped containers are limited to 512 MB). Twenty requests per person per hour
  (`import` in `app/auth/ratelimit.py`), dry runs included.
* **Tests:** `tests/test_data_import.py` (round trip into a fresh server, dry run writes nothing, all or nothing,
  extra fields, version, NaN, 413, secrets in a crafted file, another person's rows and colliding ids, duplicates,
  built-in and USDA foods, re-authentication, CSRF, the activity row), `tests/test_data_import_ui.py`,
  `tests/test_auth_coverage.py`, and `test_isolation_v03.py` (every table the import writes).

`last4` is shown only for keys of 20 characters or more. Keys are never returned, logged or
audited; they are sealed with Fernet under keys derived from `SECRET_KEY` (`app/crypto.py`).

### `/api/admin` (admins; every write *(re-auth)*)

| Method and path | Body → response |
|---|---|
| `GET /api/admin/users` | → `{users: [{id, username, display_name, role, status, auth_source, can_use_shared, must_change_password, has_password, created_at, last_login_at, reset_link, assistant_tokens, device_tokens}]}`; `reset_link` is the open reset or setup link (`{id, created_by, created_at, expires_at}`, never the token) or `null`; `assistant_tokens` and `device_tokens` are how many active tokens of each family the person has (numbers, never a token; also in the `user` of the POST/PATCH answers); `two_step`: whether two-step sign-in is on; `passkeys`: how many passkeys the person has |
| `POST /api/admin/users` | `{username, display_name?, role}` → 201 `{user, setup_url, expires_at}`: a `pending_setup` account and a one-time link (`/#/reset/…`, `registration.invite_ttl_days`) where the person sets a password. Proxy mode: pre-creates the proxy identity (`setup_url: null`) |
| `PATCH /api/admin/users/{id}` | any of `{role, status ("active"\|"disabled"), can_use_shared, must_change_password (true), display_name}` → `{user}`. 409 when it would leave no active admin, for disabling yourself, or enabling a locked/new account (use a reset link). A role change or disabling signs the person out. Demoting or disabling an admin deletes every unused invite and reset/setup link they created (audit detail `links_revoked`); disabling also voids the account's own open link |
| `DELETE /api/admin/users/{id}` | `{confirm_username}` → 204 (cascade); 409 for yourself or the last admin. The person's unused invites and links are deleted first (`auth_tokens.created_by` is `ON DELETE SET NULL`) |
| `POST /api/admin/users/{id}/reset-link` | → `{url, expires_at}` (24 h, single use; also unlocks; voids the account's older link) |
| `DELETE /api/admin/users/{id}/reset-link` | → 204, voids the account's open reset or setup link (404 when there is none); audit `user.reset_link_revoked` |
| `POST /api/admin/users/{id}/revoke-sessions` | → `{revoked: n}` |
| `POST /api/admin/users/{id}/revoke-tokens` | → `{revoked: n}`: ends every active token of the person, **assistant and device tokens alike** (`api_tokens.revoke_all`, reason `admin`; works while `assistant.enabled` and `push.enabled` are off; `n: 0` and no audit row when there is none); 404 for an unknown id; audit `api_token.revoked` (actor the admin, target `user`, details `reason`, `count`). The person's Settings then lists them as revoked |
| `DELETE /api/admin/users/{id}/totp` | → `{removed: bool}`: turns off the person's two-step sign-in and deletes their recovery codes, for someone who lost both the phone and the codes (note 17 §2); sessions kept; 404 for an unknown id; audit `totp.disabled` (actor the admin, `via: admin`) |
| `DELETE /api/admin/users/{id}/passkeys` | → `{removed: n}`: deletes all of the person's passkeys, for a lost or stolen device (note 18 §2); sessions kept; 404 for an unknown id; audit `passkey.removed` (actor the admin, `via: admin`, `count`) when there were any |
| `GET /api/admin/invites` · `POST /api/admin/invites` · `DELETE /api/admin/invites/{id}` | POST `{role, note?, ttl_days? (1–90)}` → 201 `{invite, url, expires_at}` (the URL is shown once); list → `{invites: [{id, role, note, created_by, created_at, expires_at, used_at, state}]}`; 409 when registration is `closed` or in proxy mode |
| `GET /api/admin/settings` · `PATCH /api/admin/settings` | → `{settings: {key: {value, source, locked_by_env, scope}}}`; PATCH `{key: value \| null}`, audited with old and new values |
| `GET /api/admin/keys` · `PUT/DELETE /api/admin/keys/{provider}` | shared keys: `{providers: [{provider, label, shared: {set, source ("db"\|"env"), locked, last4?, updated_at?}}]}`; PUT `{api_key, test?}`; an env key (`USDA_API_KEY[_FILE]`) is locked (409); 403 in none mode |
| `GET /api/admin/usage?days=30` | → `{days, usage: [{user_id, username, provider, key_scope, requests}]}` (counts only) |
| `GET /api/admin/audit?before=&limit=` | → `{events: [{id, at, actor_user_id, ip_prefix, action, target_type, target_id, details}]}` |
| `GET /api/admin/about` | → `{version, schema_version, auth_mode, accounts, https, public_url, secret_key: {source, on_data_volume, warning, secrets: {current, older_key, unreadable}}, proxy: {first_forwarded_peer, ignored_identity_headers, …}, pre_v3_backup, last_backup_at}` |

With `AUTH_MODE=none` the users and invites routes answer 404.

**Admins must use two-step sign-in** (`auth.require_two_step_admins`, instance, bool, default false, env
`AUTH_REQUIRE_TWO_STEP_ADMINS`; design note 17 §10). While on, `require_admin` (every `/api/admin` route) answers a local admin in
`AUTH_MODE=local` who has no two-step sign-in with `403 {"detail", "two_step_required": true}`; the person's own routes, `/api/me/totp`
included, keep working. `PATCH /api/admin/settings` turning it on is `409` (`field: auth.require_two_step_admins`) unless the admin
making the change has it on. No effect in proxy or `none` mode. The admin page (`js/views/settings.js` `adminTwoStepBlocked`) and its AI
part (`js/views/ai.js`) ask `GET /api/me/totp` first and show a note with **Open Settings** instead of calling the admin routes.

M1 settings keys (`app/settings_registry.py`, instance scope; env lock in brackets): `instance.name` (Kidney Health
[`INSTANCE_NAME`]), `registration.mode` (`invite` | `closed` | `open` [`REGISTRATION_MODE`]),
`registration.invite_ttl_days` (7 [`INVITE_TTL_DAYS`]), `audit.retention_days` (365 [`AUDIT_RETENTION_DAYS`]),
`providers.usda.shared_enabled` (`true` [`USDA_SHARED_ENABLED`]), `providers.usda.user_keys_allowed` (`true`
[`USDA_ALLOW_USER_KEYS`]), `providers.usda.daily_limit_per_user` (200 [`USDA_SHARED_DAILY_LIMIT`]). An empty env value counts
as unset.

**First values from the environment** (design note 20). Every instance and `user_default` setting has an env name except
`ai.route.local_provider` and `ai.route.cloud_provider` (they name a provider row; `tests/test_settings_initial.py` keeps this
true). `SETTINGS_INITIAL_ONLY` (a comma list of those names, or `*`) turns the listed ones from locks into first values:
`SettingsStore.env_value` ignores them, and `app/main.py` `_initial_settings` runs `SettingsStore.apply_initial` after the
migrations on every start. For each first value it has never seen (no `meta` row `settings_initial:<key>`), it writes the
instance row unless one exists, audits `settings.changed` with no actor and `env: <NAME>`, and writes the `meta` row, so a
value changed or reset in the app survives restarts. A name that is not a setting's variable, `*` with names, or a bad value
stops the start (`validate_env_locks`); `python -m app.admin check` lists locks and first values, and `env-template` prints every setting's variable as a `.env` file (`app/admin.py` `env_template`, from the registry). The JavaScript twin
(`js/engine/settings.js` `effective`) treats a listed variable as no lock, checked by two precedence vectors.

### Changes to existing routes

* All of `/api/profile`, `/api/foods`, `/api/log`, `/api/meals`, `/api/plan` act on the signed-in
  person. `Profile.id` is the user id. `GET /healthz` counts only builtin foods.
* **Foods**: `builtin` rows are shared; `custom` rows belong to their owner; `usda` and `off`
  rows are shared but visible to a person only after they imported or scanned them.
  Search, categories and "recently logged first" use only visible foods and the caller's own log.
  `PUT /api/foods/{id}` on a `usda`/`off` row → **409** (copy first). `DELETE` on a shared row
  removes only the caller's link (404 if none); a custom food is hidden when the owner's entries or
  saved meals use it, else deleted. `POST /api/log`, `/api/meals` and `/apply` answer 404 for a food
  that is not visible.
* **USDA**: the key is resolved per request: own key → shared key (if allowed, `can_use_shared`, and
  within `providers.usda.daily_limit_per_user`) → `503 {"detail", "reason": "not_configured" |
  "not_allowed" | "quota_exhausted" | "own_key_unreadable"}`. A rejected own key is reported and never
  retried with the shared key. A key whose `X-RateLimit-Remaining` drops below 50 is paused for an
  hour (429). `POST /api/foods/usda/import` reuses the shared row for that `fdc_id` and links it.
* **CSV** (`/api/log/export.csv` and the export archive): text cells starting with `= + - @`, tab or
  newline get a leading `'` so spreadsheets do not run them as formulas.

### Admin CLI (`python -m app.admin`)

`create-admin USERNAME` (password on stdin; claims user 1 while setup is pending), `reset-password
USERNAME [--stdin]` (prints a 24-hour link, or sets the password from stdin and unlocks; either way
older links for the account stop working), `list-users [--json]`, `setup-code`, `revoke-sessions
USERNAME|--all`, `remove-two-step USERNAME` (turns off two-step sign-in, also for the only admin; audited `totp.disabled` via `cli`;
note 17), `remove-passkeys USERNAME` (deletes the account's passkeys; audited `passkey.removed` via `cli`; note 18), `export-user USERNAME FILE|-` (that person's export `.zip`, as `GET /api/me/export.zip`; a new
file with mode 0600, never overwritten; audited `export.created` via `cli`), `disable-user USERNAME` (as
`PATCH /api/admin/users/{id}` `status: disabled`: never the only active admin; signs out the account's
sessions, voids its reset links and, for an admin, the invites and links it issued; audited `user.disabled`
via `cli`), `purge-pre-v3-backup`, `vacuum`, plus the platform's `backup`, `check`,
`restore-check`, `rotate-secret-key`, `reencrypt`, `settings`. `backup` (to a file or `-`) writes the
copy in rollback-journal mode, so it opens read-only anywhere; `restore-check` opens a read-only file
with `immutable=1` (unless a `-wal` file sits next to it) and says when it could not check the stored
keys because no `SECRET_KEY[_FILE]` was given; `check` warns when user 1 is missing.

### Schema v3 summary (`m003_accounts.py`)

`users`, `sessions` (hashed verifiers), `auth_tokens` (setup code, invites, reset links; hashed),
`login_failures` (HMAC of the name), `user_profiles` (the v0.2 `profile` row copied to user 1; the
old table is kept and never read), `user_food_links`, `instance_settings`, `user_settings`,
`secrets`, `usage_daily`, `audit_log` (append-only trigger); `log_entries.user_id`,
`meal_templates.user_id`, `foods.owner_user_id` (nullable `REFERENCES users(id) ON DELETE CASCADE`,
back-filled to user 1, NULL refused by triggers; a `custom` food needs an owner). The first start on
an existing database copies it to `kidney.db.pre-v3.bak` (mode 0600, once), which is deleted 30
days after the upgrade (`python -m app.admin purge-pre-v3-backup` does it now). User 1 starts as a
`pending_setup` admin and is claimed by first-run setup, `ADMIN_USERNAME` + `ADMIN_PASSWORD[_FILE]`,
the deprecated `APP_PASSWORD` (imported once; user `ADMIN_USERNAME` or `admin`; must change it if it
fails the policy) or `create-admin`.

## M2 API: targets and labs

Built in M2 (targets) from note 05 §4.2–§4.9 and its §10 fact-check. Code: `app/targets.py` (pure
rules), `app/target_rules.py` (rule catalogue, numbers, note texts), `app/kidney_function.py` (CKD-EPI
eGFR, G/A categories, the card), `app/units.py` (analytes, units, plausibility), `app/labs.py` (router),
profile fields in `app/profile.py`, schema step `app/migrations/m004_targets_labs.py`. People-facing
explanation: `docs/targets-and-labs.md`. Every route needs a signed-in person, reads and writes only
that person's rows, and answers 404 for a result that is not theirs.

### Profile fields (`GET`/`PUT /api/profile`)

`Profile` gains (all optional; `PUT` merges; an empty string or `null` clears a field: back to `null`,
or to the default for `sex` and the yes/no fields):

```json
Profile += {
  "birth_month": "1971-03",            // YYYY-MM, not in the future, within 120 years
  "sex": "unspecified",                // "female" | "male" | "unspecified" (used only in formulas)
  "activity": null,                    // "inactive" | "low_active" | "active" | "very_active"; null = not chosen
  "transplant_date": null,             // YYYY-MM-DD, not in the future; with dialysis "none" = transplant mode
  "frail_or_sarcopenic": false,
  "weight_6_months_ago_kg": null,      // 20–400
  "pregnant_or_breastfeeding": false,
  "hyperkalemia_history": false,
  "urine_output_ml": null,             // 0–5000 (24 h)
  "pd_uf_ml": null,                    // 0–4000 (net ultrafiltration per day)
  "pd_dialysate_kcal": null            // 0–1000
}
```

"Not in the future" allows one day ahead of the server's date (the client's time zone). Validation
failures are the usual `400 {"detail": "<field>: <message>", "errors"}`.

### `GET /api/profile/suggested-targets`

* `400` without a weight (unchanged).
* `422 {"detail": "<message>", "code": "out_of_scope_pregnancy" | "out_of_scope_under_18" |
  "out_of_scope_early_transplant"}` (note 05 §4.5 texts; `detail` stays a string per this contract's
  error shape, `code` is added). Under 18 counts from the **last** day of the birth month; the
  transplant cut-off is 84 days.
* otherwise (additive keys; v0.2 clients keep working):

```json
{
  "targets": {"calories_kcal": 2280, "protein_g": {"min": 56, "max": 56}, "carbs_g": 257, "carbs_per_meal_g": 65,
              "fiber_g": {"min": 32}, "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000,
              "calcium_mg": 1000, "fluid_ml": null},          // calcium may be {"min","max"} at stages 1–2
  "notes": ["Weight basis: …", "Calories: …", "…", "These are starting points only — …"],
  "rules": [{"id": "E-1", "source": "NASEM 2023 DRI Energy Table S-1; KDOQI 2020 3.1.1", "grade": "DRI; 1C (range)",
             "opinion": true, "opinion_note": "combining the energy equation with the kidney range",
             "url": "https://doi.org/10.17226/26818"}],      // in application order S → W → N → E → P → K → PH → NA → CA → F → C → FB → L
  "derived": {"mode": "ckd", "age": 55, "sex": "male", "activity": "inactive", "bmi": 22.9,
              "reference_weight_kg": 70.0, "weight_basis": "actual", "eer_kcal": 2282, "eer_kcal_per_kg": 32.6,
              "kcal_per_kg": 32.6, "nutrition_risk": [], "lab_rules_enabled": true,
              "labs_used": {"potassium": {"value": 4.4, "unit": "mmol/L", "taken_on": "2026-10-01"}, "phosphate": null,
                            "albumin": null, "bicarbonate": null, "uacr": null, "a1c": null}},
  "missing_inputs": ["activity"],     // of height_cm, birth_month, sex, activity, urine_output_ml, pd_uf_ml, pd_dialysate_kcal
  "alerts": [{"level": "urgent" | "emergency", "code": "potassium_very_high", "analyte": "potassium", "value": 6.3,
              "taken_on": "2026-10-05", "message": "Potassium 6.3 mmol/L on Oct 5, 2026 is dangerously high. …"}]
}
```

Labs used: the newest result of potassium, phosphate, albumin, bicarbonate, UACR and HbA1c, only while
fresh (`targets.lab_fresh_days.*`: 90/90/180/180 days; UACR and HbA1c 365). Thresholds are judged on the
shown value (one decimal). The potassium alert (≥ 6.0 mmol/L; `emergency` from 6.5) is returned even
when `targets.lab_rules_enabled` is off.

### `/api/labs`

| Method and path | Body → response |
|---|---|
| `POST /api/labs` | `{analyte, value, unit, taken_on, note?}` → 201 `LabResult + {"alerts": [SafetyAlert]}`; 400 for an unknown analyte or unit, a value outside the plausible range (message names the entered unit and the converted value), a negative or non-finite value, a date after tomorrow or before 1900, a note over 500 characters, or an unknown field |
| `GET /api/labs?analyte=&limit=` | → `{"labs": [LabResult], "alerts": [SafetyAlert]}` newest first (`taken_on`, then entry order); `limit` 1–1000, default 200. `alerts`: the newest potassium's safety alert while fresh under `targets.lab_fresh_days.potassium` (whatever the filters), the window the suggestions use |
| `POST /api/labs/import` | v0.3.1. `{"results": [{analyte, value, unit, taken_on, note?}, …]}` (1–1,000 items) → 200 `{"saved": int, "duplicates": int, "refused": [{"index", "reason"}], "alerts": [SafetyAlert]}`. Each item is checked like `POST /api/labs`: a refused one is listed with the same message (`flatten_validation_errors`, as the 400 handler words it) and the others are saved in one transaction. An item that repeats a saved result of the same person (same test, date and value as shown) or an earlier item is skipped and counted in `duplicates`. `alerts` is what `GET /api/labs` returns. 400 only for the request's shape (no `results`, an empty or over-long list, an item that is not an object, an unknown field) |
| `DELETE /api/labs/{id}` | → 204; 404 when it is not yours or does not exist |
| `GET /api/labs/kidney-function` | → `KidneyFunction` (below); never changes the saved stage |

**Import from a spreadsheet (v0.3.1).** The CSV file is read in the browser (`js/engine/lab_import.js`,
`KH.labImport.analyse`): a date column (Date, Taken on, Collected …) and every column whose header names a
test (`app/units.py` keys and labels, plus aliases such as K, CO2, ACR, HbA1c), the unit from the header
("Potassium (mmol/L)", "Creatinine [umol/L]") or chosen per column; a test whose units all convert the same
(potassium, bicarbonate) or have one unit (cystatin C, eGFR) needs none. Values such as "<0.5", ">90" or
"1,200" (1200 or 1.2?) are listed as not imported with the reason; dates like 03/04/2026 follow the order the
person picks unless a day above 12 settles it; other columns (names, record numbers) are never sent. The
person ticks the results to keep and only those go to `POST /api/labs/import` (`KH.labImport.requestBody`:
test, value, unit and date). The reader has no Python twin: `tests/data/lab_import_vectors.json`
(`tests/js/gen_lab_import_vectors.mjs`, reviewed by hand) pins it in `node tests/js/run_vectors.mjs`, and
`tests/test_lab_import.py` checks every converted value against `app/units.py`. The demo twin is in
`js/mock/labs.js`. The same import is the only way a result read from a photo of a lab report is saved ("Lab report photos" under "M2 API: AI and photos"):
the person ticks rows (all start unticked) and the page sends the ticked ones, through the shared `KH.views.labs.saveImported`.

```json
LabResult = {"id": 7, "analyte": "phosphate", "label": "Phosphate", "value": 6.0, "unit": "mg/dL",
             "entered_value": 1.94, "entered_unit": "mmol/L", "display": "1.94 mmol/L = 6.0 mg/dL",
             "taken_on": "2026-10-01", "note": "", "created_at": "…Z"}
KidneyFunction = {
  "egfr": {"value": 55, "method": "lab" | "ckd_epi_2021_cr_cys" | "ckd_epi_2021_cr" | "ckd_epi_2012_cys",
           "method_label": "CKD-EPI 2021, creatinine", "category": "G3a",   // "G3aT" after a transplant; null if the two formulas disagree
           "suggested_stage": "3a", "matches_profile": false, "female": null, "male": null,   // both set when sex is unspecified
           "taken_on": "2026-10-01"} | null,
  "albuminuria": {"value_mg_g": 26.5, "category": "A2", "label": "moderately increased",
                  "entered_value": 3.0, "entered_unit": "mg/mmol", "taken_on": "2026-10-01"} | null,
  "profile_stage": "3b", "mode": "ckd" | "transplant" | "hemodialysis" | "peritoneal",
  "message": "Your eGFR on 2026-10-01 is 55 mL/min/1.73 m² (CKD-EPI 2021, creatinine), which is stage G3a. …"
}
```

Analytes, canonical units, accepted units and plausible ranges: `app/units.py` (`potassium`,
`phosphate`, `albumin`, `bicarbonate`, `uacr`, `creatinine`, `cystatin_c`, `egfr`, `a1c`). `value` is
stored unrounded in the canonical unit; the API rounds it to the analyte's shown decimals. The card uses
results of the last 365 days: newest date first, then lab eGFR > creatinine + cystatin C that day >
creatinine > cystatin C; nothing on dialysis, in pregnancy or under 18; albuminuria in the entered unit.

### Lab results from Apple Health clinical records (browser only; `js/engine/fhir_labs.js`, `js/views/lab_fhir.js`; ROADMAP "Ideas from the owner")

**No new route, no new setting, no new dependency, no new network request, no schema step.** The Health app's "Export All Health Data" zip
holds `apple_health_export/clinical-records/` with one FHIR JSON resource per file. The person chooses the `export.zip` itself in the Labs
view (card `#lab-fhir`, below "Import from a spreadsheet"), or, if it was already unzipped in the Files app, those files. A `.zip` is opened
on the device by `KH.zip` (see "Reading a .zip in the browser" below): its `clinical-records/*.json` entries go through the same loop,
caps and engine as picked files, each read with `KH.zip.text` (a damaged, encrypted or unreadable entry is counted as a file that could not
be read; one over 1 MB is not read; a `.zip` with no such folder says so; 2,001 entries or more are refused before any is read).
**Least trust: the files are read on the device and never
uploaded.** Each file is opened with `File.text()` (a file over 1 MB is not opened), handed to `KH.fhirLabs.start().add()` and let go of;
`finish()` returns the rows, the refusals and the counts; the page shows the headline ("41 results found in 380 files; …") and the CSV
import's review table; only the ticked rows go to `POST /api/labs/import` through `KH.views.labs.saveImported` (the shared save: test,
value, unit and day, nothing else). Names, ids, providers and notes in a file are never read (only the fixed paths below are), file names
appear only on the page, in the list of refusals, and no file or file name is stored or sent. Contract points:

* **Records.** `Observation`, or `Bundle` entries that are Observations (one level; a nested Bundle is "not a lab result"); every other
  record is counted as not a lab result. `status` must be `final`, `amended` or `corrected`.
* **Test.** `code.coding[]` with system `http://loinc.org` looked up in the table in `js/engine/fhir_labs.js` (`KH.fhirLabs.LOINC_LIST`,
  26 codes for the nine tests of `app/units.py`; the table with each code's `https://loinc.org/<code>` page is in
  `docs/targets-and-labs.md`). Every code was looked up in LOINC 2.82 (tx.fhir.org and the NLM Clinical Tables) on 2026-10-15; only
  "Serum or Plasma" and "Serum, Plasma or Blood" specimens (HbA1c in blood, the urine albumin/creatinine ratio) are mapped, never
  blood-gas, urine (potassium, creatinine), 24-hour, race-specific, MDRD or paediatric codes. Two codes for different tests, or none
  in the table, skip the record (counted). `tests/test_fhir_labs.py` fails when a code names a test or a unit `app/units.py` lacks, when a
  check digit is wrong, or when the docs do not list a code.
* **Value and unit.** One number in `valueQuantity.value` (a `comparator` other than `=`, a text result or a missing number is refused);
  the unit from the UCUM `code` (system `http://unitsofmeasure.org` or none) and the unit text, both must name the same unit when both
  are known; read through `KH.kidney.canonicalUnitName` (the twin of `units.canonical_unit_name`) after dropping UCUM annotations and
  a few spellings of the same unit (`UNIT_ALIASES`: `ug/mg` is `mg/g`, `mL/min/1.73m*2` and similar are the eGFR unit). An unknown unit is refused,
  never guessed. Conversion and the plausible range are `KH.kidney.convert` (`units.convert`): the same checks and messages as
  `POST /api/labs` and the CSV import; no clinical number is added here.
* **Day.** First of `effectiveDateTime`, `effectiveInstant`, `effectivePeriod.start`, `issued`. A date alone is taken as written; a time
  with a zone is converted to the calendar day on the device (the zone offset at that instant); a month or year alone, a date that does
  not exist, a day before 1900 or after tomorrow (the server's allowance) is refused.
* **Rows.** The same test, day and shown value collapse to one; results already saved (same key as the server's duplicate check) are
  marked and start unticked; **new rows start ticked** (the data come from the person's health system, not from an AI); at most the
  newest 1,000 are shown, because `POST /api/labs/import` takes 1 to 1,000 (the rest is counted as left out).
* **Limits.** 2,000 files per pick (more are refused before any file is read), 1 MB per file, depth 40 and 300,000 values per file,
  5,000 entries per Bundle, 50,000 records and 5,000 collected rows per pick, 100 listed refusals (counts stay exact); `JSON.parse` in
  try/catch; the depth/size walk is iterative; no `eval`; all text from a file reaches the page through the `h()` helper (text nodes).
* **Safety.** Nothing here gives advice or says whether a result is normal; the potassium banner and "what this result changed" come
  from the shared save exactly as for a typed result.
* **Parity.** The reader has no Python twin: `tests/data/fhir_labs_vectors.json` (hand-written sample resources and hand-written
  expectations; `tests/js/gen_fhir_labs_vectors.mjs` stops if the module disagrees) is replayed by `node tests/js/run_vectors.mjs`, and
  `tests/test_fhir_labs.py` converts every proposed row with `app/units.py` and posts them to `POST /api/labs/import`.
  `tests/test_fhir_labs_ui.py` (with `tests/js/fhir_labs_page.mjs`) checks the page: no inline script or handler, no network call, nothing
  stored in the browser, a file over 1 MB never read, new rows ticked, only ticked rows saved, text drawn as text. The demo has the same
  card (`js/mock/labs.js` answers the import route).

### Reading a .zip in the browser (`js/engine/zip.js`, `KH.zip`; design note `docs/dev/research/11-reading-a-zip-in-the-browser.md`)

**No new route, setting, schema step, dependency, vendored file or network request, no server code and no twin to keep in step.** Three imports take
the archive itself, so that nobody has to unzip it first: **Import from a file** (`export.json` in this app's own export `.zip`; Settings, `js/views/settings.js`),
**Weights and blood pressure from the Health app** (`apple_health_export/export.xml`; `js/views/body_import.js`) and **Lab results from Apple Health clinical
records** (`clinical-records/*.json`; `js/views/lab_fhir.js`). **The archive is read on the device, never uploaded, and the server never takes one** (the same JSON or
rows reach the same routes as before). The module is a plain script with no DOM and no other module (`index.html` and `sw.js` list it with the engines, before the
three views) and uses what the browser has: `Blob.slice`, `Blob.stream` and `DecompressionStream('deflate-raw')` (Chrome 103, Safari 16.4, Firefox 113). A browser
without it (`KH.zip.supported()` false) gets the old "open the .zip first" advice. API: `supported, open, find, list, stream, text, ZipError` and the constants
`MAX_DIRECTORY_BYTES`, `MAX_ENTRIES`, `DEFAULT_TEXT_BYTES` and the rules `RULES.exportJson, healthXml, healthCda, clinicalRecords`.

* **The archive is not trusted.** `open` reads only the last 65,577 bytes and the central directory: the end record is searched backwards and must have a comment
  that reaches exactly the end of the file; disk numbers 0; zip64 through its locator and record (64-bit values with `getBigUint64`, above 2^53 - 1 refused); the
  directory must end exactly at the end record, hold at most 200,000 entries and be at most 32 MiB, and the lowest local header offset must be 0 (data in front of
  the first entry, as in a self-extracting archive, is damaged). An encrypted entry, a method other than stored or deflate and an entry on another disk are recorded
  and refused **only when a rule selects them**, so one odd file in `workout-routes/` does not stop the weights.
* **Choosing entries** (`RULES`): the name is split at `/` with empty parts dropped, never used as a path (a `.` or `..` part never matches); `__MACOSX/` entries,
  names starting `._` and folders are ignored; the base name is compared exactly; depth is the number of folders above the file (`export.json` and `export.xml`: 0 or 1;
  `clinical-records/*.json`: the folder is exactly `clinical-records`, depth 1 or 2). `find` wants exactly one match (`missing`, `ambiguous`), `list` gives every one.
* **Reading an entry** (`stream`, `text`): the declared size against `maxBytes` first (`too_big`, nothing read); the local header must agree with the directory (signature,
  name bytes, method) and the data must end before the directory; the bytes come from `blob.slice().stream()`, in pieces of 16 KiB into the inflater, through a checking
  `TransformStream` that counts and keeps a CRC-32 and fails with `damaged` **the moment the count passes the declared size, without passing that chunk on** (a
  "zip bomb" is stopped after its first chunk), and at the end on a short count or a CRC mismatch. Memory stays bounded whatever the archive claims; an abort or a cancel
  cancels the file's own stream (it does not rely on the pipe chain to do it) and rejects with an `AbortError`. Reads use `getReader()` loops, never `for await` (Safari).
  `text` is for small entries (`export.json` at most 16 MiB, a clinical record 1 MB): one buffer of the declared size, decoded as UTF-8 with `fatal: true`.
* **Errors** (`ZipError.code`): `not_zip`, `unsupported`, `missing`, `ambiguous`, `too_big`, `damaged`, `browser`. Each view has its own plain-word table for them and shows
  nothing the archive says (the archive's words never reach the page, except a clinical record's own file name in the list of refusals, drawn as text).
* **Checks**: `tests/test_zip_reader.py` (with `tests/js/zip_reader.mjs` and the archive builder `tests/zip_support.py`): every archive is built at test time, with `zipfile`
  and with a small byte builder for the shapes `zipfile` cannot make, and the fifteen cases of note 11 section 5 are asserted (the app's own export, stored/deflated/empty/UTF-8
  entries, a data descriptor, zip64, a fake end record in a comment, a re-zipped folder, a Health-shaped archive with an encrypted entry, a 64 MB entry under a memory bound,
  and every refusal with its code, abort, and no `DecompressionStream`); each page test (`test_data_import_ui.py`, `test_body_import_ui.py`, `test_fhir_labs_ui.py`) runs its
  view on archives; the walks `tools/e2e/import_walk.py` and `tools/e2e/body_import.py` choose the `.zip` itself in Chromium. Re-verify with a real iPhone `export.zip`
  (Safari on the phone and a desktop browser): the tests build their own archives.

### Lab results from a patient-portal C-CDA file (browser only; `js/engine/ccda_labs.js`, `js/views/lab_ccda.js`; ROADMAP "Ideas from the owner")

**No new route, no new setting, no new dependency, no new network request, no schema step; one CSP change (below).** Patient portals
(MyChart and others) let a person download a C-CDA (HL7 Consolidated CDA R2.1) "health summary" as an XML file. The person chooses the
`.xml` file(s) in the Labs view (card `#lab-ccda`, below "Import from Apple Health"). **Least trust: the XML is parsed in the browser,
never uploaded, and the server has no XML parser** (the roadmap's first plan was `defusedxml` on the server; a browser parse needs no
dependency and sends nothing, and the file holds the patient's name, address and ids). Each file is opened with `File.text()` (a file
over 5 MB is not opened), refused if it contains `<!DOCTYPE` or `<!ENTITY` (checked on the text, before any parser sees it; a real C-CDA
has no DTD; counted, never cleaned), parsed by `new DOMParser().parseFromString(…, 'application/xml')` (a browser never loads an
external entity or DTD), refused on a `parsererror` or a root that is not a `ClinicalDocument` of `urn:hl7-org:v3`, read, and let go of
before the next file. `KH.ccdaLabs.start({today, existing, tzOffsetMinutes, parseXml}).add(file)` / `finish()` return the rows, the
refusals and the counts exactly like `KH.fhirLabs`; the page draws them with `KH.labFhir.review` (id prefix `lab-ccda`) and only the ticked
rows go to `POST /api/labs/import` through `KH.views.labs.saveImported` (test, value, unit and day, nothing else). `parseXml` is a
parameter (default: the browser's `DOMParser`); Node tests pass the dev-only `tests/js/mini_xml.mjs`, which no page file loads. Contract:

* **Reuse.** The LOINC table, `unitOf` (units through `KH.kidney`), the day rule (`dayOf`), the counting, repeat-collapsing, "already
  saved" marking, 1,000-row cap and headline (`collector`) are `KH.fhirLabs`'s, exported from `js/engine/fhir_labs.js`; nothing is
  copied (`tests/test_ccda_labs.py` fails on a second table or unit list). The FHIR reader's behaviour is unchanged (its vectors).
* **Sections and entries.** Walk `ClinicalDocument/component/structuredBody/component/section` (and sections nested by `component`); keep
  sections whose `templateId/@root` is `2.16.840.1.113883.10.20.22.2.3.1` (Results, entries required) or `…2.3` (entries optional); from a
  Results section follow only `entry`, `organizer`, `component` to `observation` (Result Organizer `…4.1` is read through, not required); an
  observation with `templateId/@root` `…4.2` (Result Observation) is a record, any other is "not a lab result", and an observation's own
  children are never walked. Other sections are ignored. The OIDs are cited with their HL7 sources, and what could not be verified (the
  R2.1 definition page of `…2.3`), in `docs/targets-and-labs.md`; `tests/test_ccda_labs.py` pins them.
* **Test.** `code/@code` with `@codeSystem` `2.16.840.1.113883.6.1`, and each `code/translation` the same way, through `KH.fhirLabs.LOINC`;
  two codes for different tests, none, or a `nullFlavor` code skip the record (counted).
* **Status, value, unit, day.** `statusCode/@code` = `completed`; `value` with `xsi:type` `PQ`, a plain number in `@value` (`<5`, `>100`,
  `IVL_PQ`, text, a second value, a `nullFlavor` are refused with the reason) and the UCUM `@unit` read through `unitOf` (unknown or missing
  unit refused); `effectiveTime/@value` else `effectiveTime/low/@value`, an HL7 TS `YYYYMMDD[HHMM[SS[.S]]][+/-ZZZZ]` read by `dayOf` (the
  FHIR reader's rules: a time with a zone is the device's calendar day, a date alone as written, nothing before 1900 or after tomorrow).
* **Limits.** 20 files per pick (more are refused before any is read), 5 MB per file, 200,000 elements and depth 64 walked per file (all or
  nothing: a file over the budget keeps no row), only structural elements walked (never the narrative, names, addresses, ids, authors,
  performers or notes, which are not read at all: `tests/test_ccda_labs_ui.py` pins the exact element and attribute names the code asks
  for), 1,000 rows, 100 listed refusals; counts stay exact; text from a file reaches the page only through `h()` (text nodes).
* **Trusted Types (the CSP change).** `require-trusted-types-for 'script'` makes `DOMParser.parseFromString` a sink that throws on a plain
  string, so `app/security.py` lists `kh-xml` (the list is now `trusted-types kh-sw kh-xml kh-pdf`; `kh-pdf` is "PDFs" under "Lab report
  photos"). `kh-xml` is created once, in `ccda_labs.js` only; its `createHTML`
  accepts a string with no DOCTYPE or ENTITY and returns it unchanged, and the result is passed straight to the parser. No default policy,
  no `allow-duplicates`; `tests/test_frontend_shell.py` allows exactly three files to create a policy (`pwa.js`: `kh-sw`; `ccda_labs.js`:
  `kh-xml`; `pdf_pages.js`: `kh-pdf`), exactly one parser call and no other `parseFromString`; `tests/test_security.py` pins the CSP. Without Trusted Types, or when a
  host page's CSP does not list the name (the Artifact-hosted preview), the string is used or the file is counted "could not be read".
* **Safety.** Nothing here gives advice or says whether a result is normal; the potassium banner and "what this result changed" come from
  the shared save as for a typed result. A real portal export has not been tried (hand-written samples only).
* **Parity and tests.** No Python twin: `tests/data/ccda_labs_vectors.json` (hand-written C-CDA documents and expectations;
  `tests/js/gen_ccda_labs_vectors.mjs` stops if the module disagrees) is replayed by `node tests/js/run_vectors.mjs`; `tests/test_ccda_labs.py`
  converts every proposed row with `app/units.py` and posts them to `POST /api/labs/import`; `tests/test_ccda_labs_ui.py` (with
  `tests/js/ccda_labs_page.mjs`, whose fake parser throws on a plain string as Chromium does) checks the page; `tools/e2e/regress.py` runs a
  sample through real Chromium (the real `DOMParser` and the policy). The demo has the same card (`js/mock/labs.js` answers the import route).

### Settings (registered in `app/settings_registry.py`)

`targets.lab_rules_enabled` (instance, `true`), `targets.lab_fresh_days.{potassium,phosphate,albumin,
bicarbonate}` (instance, 90/90/180/180, 1–365), `targets.default_activity` (instance, `inactive`),
`user.units.labs` (`user_default`, `us` | `si`: the unit offered first; note 05 §4.9 lists it as a
personal key, the admin default is added for servers outside the US).

### Data, export and deletion

Schema step 4 adds the profile columns to `user_profiles` and `lab_results (id, user_id → users ON
DELETE CASCADE, analyte, value, entered_value, entered_unit, taken_on, note, created_at)` with index
`lab_results_lookup (user_id, analyte, taken_on DESC, id DESC)`. The export archive carries the new
profile fields in `export.json` → `profile`, every result in `export.json` → `lab_results`
(`id, analyte, value, unit, entered_value, entered_unit, taken_on, note, created_at`, unrounded) and
`labs.csv` (same columns, formula-escaped). Deleting the account deletes them.

### Parity (demo/preview mode)

The browser twins `js/engine/targets.js` and `js/engine/kidney_function.js` are checked against
`tests/data/targets_vectors.json` and `tests/data/kidney_function_vectors.json` (generated by
`tests/data/gen_targets_vectors.py` and `gen_kidney_function_vectors.py` from the Python modules;
`tests/test_targets_vectors.py` fails when a file is stale). Inputs are plain JSON (profile, stored lab
rows, settings, `today`); outputs include every note word for word. The demo routes (`js/mock/profile.js`,
`js/mock/labs.js`) are compared with a real server by `tools/e2e/parity.py` section 11 (profile-field and
lab validation messages, history, deletion, the kidney-function card, ~150 suggestions including the 422
`code`, and the `targets.*` settings).

### Frontend (M2 targets; `docs/targets-and-labs.md` "In the app")

* **Profile**: cards *About you* (the §4.2 fields; activity as five radios, "not chosen" first),
  *Kidneys and diabetes* (transplant date only without dialysis; dialysis days and urine on
  hemodialysis; urine, ultrafiltration and dialysate calories on peritoneal; weight relabelled dry
  weight on dialysis), *Blood and urine tests* (newest results, eGFR line, *Lab results*), *Daily
  targets* (protein and calcium as ranges, fiber as a goal `{min}`). *Suggest targets* still needs the
  form to match the saved profile; its panel shows the alert, the changes against the saved targets
  (reason: the deciding rule's first sentence), the derived values, every target with *Why this
  number?* (note, rule id, grade, *Expert opinion* badge with `opinion_note`, source link), lab notes,
  buttons for `missing_inputs`, and the END note. Each rule is paired with its note by position
  (`notes.length === rules.length + 1`). Refusals are recognised with `KH.targets` before the request
  (no 422 round trip) and render their message instead of numbers.
* **Lab results** (`#labs`): unit picker defaulting from `user.units.labs`, the conversion echo and
  plausibility check before POST (the twin), *What this result changed* (suggestion before vs after),
  the cumulative *Review suggested targets* notice in Profile (`state.targetsReview`; never applied),
  the potassium banner (POST alert, else `GET /api/labs` `alerts`: the newest potassium while fresh under
  `targets.lab_fresh_days.potassium`, the suggestions' window; the browser applies no window of its own),
  the kidney-function card and the history with in-page delete confirmation. Saving, deleting, importing or changing Profile
  invalidates the shared lab/kidney-function cache and pending reads. An older reply cannot restore the pre-change cache
  or replace a newer Lab results/Profile summary. Concurrent readers share one read until invalidated; older readers then
  converge on the fresh result.
* **Today**: a `{min}`-only target (fiber) is a goal bar ("of at least X", no over state); a range with
  `min === max` reads "about X". **Settings**: Preferences → *Units for lab results* (`user.units.labs`);
  Admin → server settings group *Personalised targets and lab results* (`targets.*`, `user.units.labs` default).

## M2 API: guidance

Built in M2 (guidance) from note 06 §4.1–§4.15 and §6, with the Layer-0 duties of note 04 R2 and G7.
Code: the package `app/guidance/` — pure modules `rules`, `vectors`, `state`, `budget`, `score`, `fits`,
`swaps`, `planner`, `insights`, `messages`, `topics`, `hypo`, `ai_bridge`; I/O in `context` (loads one
person's data) and `api` (the routes); response shapes in `app/guidance/models.py` (package-owned; the
log-side models are in `app/models.py`). Schema step 5 (`app/migrations/m005_guidance_log.py`). People-
and contributor-facing explanation: `docs/guidance.md`. Every route needs a signed-in person, reads only
that person's rows, writes nothing except the person's food preferences, and answers 404 for a food or entry
that is not theirs. Responses are `Cache-Control: no-store` like every `/api` route.

### Routes (`/api/guidance`)

| Method and path | Query / body → response |
|---|---|
| `GET /api/guidance/next-meal` | `meal` (required), `date` (default today), `limit` 1–20 (11), `explain`, `exclude` (a comma list of at most 60 food ids, left out before ranking: **Show other foods**; 400 otherwise) → `NextMeal` |
| `GET /api/guidance/swaps` | `food_id` + `meal` + `servings` or `grams` (+ `date`), **or** `entry_id`; `purpose` `hypo`\|`none` (default: `hypo` for a `hypo_treatment` food, else the entry's); `explain` → `Swaps`. 400 without exactly one of `food_id`/`entry_id`; 404 for a food or entry that is not the person's |
| `GET /api/guidance/hypo-options` | → `{status, rules_version, dose_g, options: [FoodPortion + text], card: LowCard, notes}`. Never filtered by a budget; answers even when guidance is switched off; reads no soft preference and is never empty while a low treatment exists (the floor under "Food preferences" below) |
| `POST /api/guidance/plan-day` | `{date, meals?: [Meal] (1–4, unique), use_saved_meals?, use_usual?, use_starters?, variant? 0–4, explain?}` → `Plan`; computes only |
| `POST /api/guidance/fit-recipe` | `{meal_id}` **or** `{items: [{food_id, servings ≤ 40}] (1–30), servings_made?}`, with `target?: {kind: meal\|day (meal), meal?, date?}` → `{status: fits\|fits_after_changes\|fits_smaller_serving\|does_not_fit\|unavailable, rules_version, target: {kind, meal, date}, servings_made, before, after, fitted, closest, changes, still_over, notes}`; computes only (note 16 §7, "Recipes that fit" in `docs/guidance.md`). `before`/`after` are `{per_serving, unknown, checks: [{nutrient, used, room, ok}]}`; `fitted` (or `closest` when it does not fit, with no Save) is `{items: [{food_id, name, servings, serving_desc, portion_text}], serving_fraction, log_scale}`, the pot amounts and the `scale` for `apply`. 400 without exactly one of `meal_id`/`items`; 404 for a recipe or food that is not the person's; `unavailable` when a food of the recipe is gone |
| `GET /api/guidance/insights/day` | `date` → `{status, rules_version, date, insights: [Insight] (≤ 6), planned_excluded, notes}` |
| `GET /api/guidance/insights/period` | `start`, `end` (default the 7 days ending yesterday; ≤ 92 days; 400 for `end < start`) → `{status, rules_version, start, end, days, logged_days, insights, notes, previous: {start, end}}` |
| `GET /api/guidance/rules` | → `{rules_version, rules_hash, rules: {NAME: value}, notes: {NAME: basis}, topic_pages: {slug: {slug, title, url}}, tips}` |
| `GET /api/guidance/preferences` | → `{rules_version, limit: 1000, not_for_me_limit: 500, foods: [{food_id, name, category, preference, source, created_at, updated_at}] (by name), groups: {like, less, never}, learn_from_log}`; `groups.never` is `exclude_categories` |
| `PUT /api/guidance/preferences/{food_id}` | `{preference: like\|less\|not_for_me\|neutral, source?: person\|ask\|assistant (person)}` → the row (`assistant` is written by the MCP tool `set_food_preference` with an `assistant:prefs` token; the page sends it only when Ask's Undo puts back a row it replaced, with the source that row had); the same value again changes nothing; 404 for a food the person cannot use; 409 at 1,000 preferences or 500 "Not for me" foods; one `BEGIN IMMEDIATE` transaction |
| `DELETE /api/guidance/preferences/{food_id}` | → 204; 404 when the person has no preference on the food |
| `GET /api/guidance/learned` | → `{rules_version, learn_from_log, items: [{kind: often\|slot\|usual_meal\|planned_not_eaten, food_id \| null, name, meal \| null, key \| null, reason, effect: more\|less}]}` (≤ 30 items of each kind); computed on the spot, never stored; `items` is empty with `learn_from_log` off |
| `GET /api/guidance/not-for-me` | alias: → `{rules_version, limit: 500, foods: [{food_id, name, category, created_at}]}`, the `not_for_me` rows only |
| `PUT /api/guidance/not-for-me/{food_id}` | alias: → the list (idempotent; replaces another preference on the food); 404 for a food the person cannot use; 409 at 500 foods |
| `DELETE /api/guidance/not-for-me/{food_id}` | alias: → 204; 404 when the food is not on the "Not for me" list (another preference on it stays) |

Instead of a result, `next-meal`, `swaps`, `plan-day` and the insights answer 200
`{"status": "no_targets" | "disabled", "rules_version", "message"}`: `no_targets` when the profile has no
numeric potassium, phosphorus or sodium target and no `carbs_per_meal_g`; `disabled` when the instance
setting `guidance.enabled` is off ("Meal guidance is switched off on this server.") or the person's
`guidance.enabled` / `show_plan_builder` / `show_insights` is off. `explain=true` adds score components,
`why_not` and `not_eligible` reason codes and evaluation counts (contributors; never shown by default).

```json
NextMeal = {"status": "ok", "rules_version": "2026-10-05.1", "date", "meal", "open_meals": [Meal],
  "room": {"potassium_mg": NutrientRoom | null, "phosphorus_mg": …, "sodium_mg": …, "fluid_ml": …,
           "carbs_g": {"goal", "in_meal", "gap", "tolerance", "hypo_excluded_g", "unknown"} | null,
           "protein_g": {"aim", "aim_min"} | null},
  "room_text": "Left for dinner: 750 mg potassium · 167 mg phosphorus · 600 mg sodium · 60 g carbs to reach 60 g",
  "meal_has": {"protein", "starch", "veg_fruit"},
  "foods": [FoodPortion + {"score", "fit_text", "reasons": [{"code", "text"}], "handbook": [{"slug", "title", "url"}]}],
  "saved_meals": [{"template_id" | null, "name", "source": "saved" | "usual", "scale", "score",
                   "items": [{"food_id", "name", "servings"}], "totals", "note"}],
  "tips": [{"code", "text", "handbook", "url"}], "notes": ["Suggestions compare foods with the targets your care team set. They are not medical advice."],
  "ai": {"available", "provider_label"}, "targets": {"values": {…}, "profile_updated_at"}}
NutrientRoom = {"room", "cap" | null, "share", "in_meal", "remaining_today", "allowance_today",
                "level": "ok" | "caution" | "over", "basis": "day" | "week_average" | "interdialytic",
                "unknown": int}   // entries of the day without this value: the room is then "at most" (room_text says why)
FoodPortion = {"food_id", "name", "group": "protein" | "starch" | "veg_fruit" | "extra",
               "role": "protein" | "mixed" | "starch" | "veg_fruit" | "drink" | "extra", "servings",
               "serving_desc", "grams", "portion_text": "¾ × 1 cup (158 g)", "nutrients": {12 keys},
               "warnings": [Warning], "renal_rating": "green" | "yellow" | "red"}
Swaps = {"status": "ok", "rules_version", "date", "meal", "mode": "normal" | "hypo" | "avoid",
  "food": {"food_id", "name", "servings", "serving_desc", "nutrients"},
  "triggers": [{"nutrient", "reasons": ["high_per_portion" | "over_meal_room" | "phosphate_additive" | …], "value", "room"}],
  "match": "carbs" | "protein" | "serving" | null,
  "swaps": [FoodPortion + {"same_category", "fits_meal", "score", "deltas", "text"}] (≤ 5),
  "portion_option": {"servings", "fraction", "fits_meal", "nutrients", "text"} | null,
  "tips": [Tip], "widened", "notes", "reason": "no_warning" | "no_swap_found" | null,
  "card": LowCard | null (hypo mode), "entry_id": int | null}
LowCard = {"title": "Treating a low", "lines": [str], "handbook": "treating-a-low", "url": "/learn/t1d/treating-a-low/"}
Plan = {"status": "ok", "rules_version", "date", "variant",
  "meals": [{"meal", "status": "ok" | "partial" | "no_fit", "source": "saved" | "usual" | "starter" | "built" | null,
             "name", "template_id", "scale", "score", "items": [FoodPortion], "totals", "why": [str],
             "room": Room, "reason", "message"?, "closest"? (no_fit), "apply_saved"? {"endpoint", "body"}}],
  "protein_topup": [Meal], "day_after": {"projected_totals", "projected_status", "new_alerts": [Alert]},
  "energy_note": {"kcal", "goal", "text", "foods": [FoodPortion], "handbook"} | null,
  "apply": {"endpoint": "/api/log/batch", "entries": [{"date", "meal", "food_id", "servings", "status": "planned", "purpose": "none"}]},
  "notes", "targets", "explain"?}
Insight = {"id": "day.potassium_mg.over" | …, "severity": "warning" | "attention" | "info" | "good",
           "nutrient" | null, "message", "numbers": {…}, "sources": [{"name", "short_name", "value", "share_pct"}],
           "handbook": [{"slug", "title", "url"}]}
```

Handbook links use the `/learn/...` URLs of note 08 §4.10 (`app/guidance/topics.py`;
`tests/guidance/test_topics.py` checks every URL is an existing page with that slug and title).

### Log changes (`app/log.py`, `app/meals.py`)

* `Entry` gains `purpose` (`"hypo"` | `null`) and `client_id` (`string` | `null`). `POST /api/log`,
  `/quick`, `/batch` and `PUT /api/log/{id}` accept `purpose`: `"hypo"` (the entry treated a low) or
  `"none"`; left out on a create, an entry of a `hypo_treatment` food (or a quick add flagged so) is
  `"hypo"` (the entry sheet's pre-ticked "Used to treat a low"); left out or `null` on `PUT` keeps it.
  `copy-day` keeps it. The CSV export gains a last column `purpose`.
* **`client_id`** (offline outbox, note 02 R5): a UUID in its 36-character text form, stored lower-case,
  unique per person (`log_client_id` partial index). `POST /api/log` and `/quick` answer a repeat with
  the entry already created and **200** instead of 201 (`/quick` creates no second food); two people
  may use the same id; a concurrent duplicate is resolved the same way.
* **`POST /api/log/batch`** `{"entries": [LogCreate] (1–40)}` → **201** `{"entries": [Entry], "results":
  [{"index", "id", "result": "created" | "existing"}]}` in request order, **200** when every item already
  existed. Each item is validated exactly as `POST /api/log` (400 with `entries[i]…` in the message;
  repeated `client_id`s in one batch are a 400), then each food must be visible (404 `entries[i]: food N
  not found`). One transaction: the first failing item rolls the whole batch back. Items whose
  `client_id` the person already used are not added again. The body is bounded by the 40 items and
  `MAX_BODY_BYTES` (413).
* Saved meals gain `meal_hint` (a `Meal` or `null`): `POST /api/meals` accepts it, `PUT` keeps the stored
  one when the field is left out (a v0.2 client) and clears it on `null`, `POST /api/meals/from-log` sets
  it to the source meal and leaves low-treatment entries out.

### Schema step 5 (`m005_guidance_log.py`)

`log_entries.purpose TEXT`, `log_entries.client_id TEXT` + `CREATE UNIQUE INDEX log_client_id ON
log_entries(user_id, client_id) WHERE client_id IS NOT NULL`, `meal_templates.meal_hint TEXT`,
`food_preferences (user_id → users, food_id → foods, both ON DELETE CASCADE; preference 'not_for_me';
created_at; PRIMARY KEY (user_id, food_id))`, and `meta.foods_rev` bumped by `AFTER INSERT/UPDATE/DELETE`
triggers on `foods` and `AFTER INSERT/DELETE` on `user_food_links` (the guidance vector cache key, so
every write path invalidates it). Existing entries keep `purpose` empty. Note 06's `guidance_json`
profile column is superseded by the settings registry (below).

### Schema step 17 (`m017_food_preference_source.py`)

`food_preferences.source TEXT` (`person` or `ask`; existing rows `person`; the MCP tool later writes `assistant` with no new step: the column
is free text, validated by the code) and `food_preferences.updated_at TEXT` (existing rows
their `created_at`), added with `add_column_if_missing` and a back-fill that touches only `NULL`s, so a re-run changes
nothing. `preference` is validated by the API (`like`, `less`, `not_for_me`, `neutral`), not by a `CHECK`. The key
`(user_id, food_id)` and both cascades stay, so a person has one state per food and deleting an account or a food removes the row.

### Settings (registered in `app/settings_registry.py`)

`guidance.enabled` (instance, `true`, env `GUIDANCE_ENABLED`), `guidance.pool_per_role` (instance, 200,
20–2000, env `GUIDANCE_POOL_PER_ROLE`), `guidance.beam_width` (instance, 16, 1–64, env
`GUIDANCE_BEAM_WIDTH`), and the person's object `guidance` (scope `user`): `{enabled: true,
carb_tolerance_g: 10 (5–20), hypo_dose_g: 15 (5–30), exclude_categories: [] (≤ 50), show_plan_builder:
true, show_insights: true, ai_enrich: false, learn_from_log: true, like_categories: [] (≤ 50),
less_categories: [] (≤ 50), hidden_usual_meals: [] (≤ 50 usual-meal keys of at most 400 characters)}`, unknown
fields refused, each list de-duplicated. A food group may be in at most one of `like_categories`,
`less_categories` and `exclude_categories`; otherwise the update is refused with `guidance: Value error, a food group
can be in only one of Like, Less often and Never suggest: <groups>` (`400` like every invalid setting). A usual-meal key
is `<meal>:<food id>x<quarter servings>,…` over the items sorted by food id, e.g. `lunch:12x4,30x2`
(`rules.usual_meal_key` and `fits.usualMealKey`: whole numbers only, so both sides write the same text). Food
preferences are `food_preferences` rows (≤ 1,000 in all, ≤ 500 of them "Not for me"), exported as `export.json` →
`food_preferences`.

### Food preferences and what the log teaches (note 09, part A)

Taste ranks; it never filters, and it never touches a low. Everything below is in the pure engine and its browser twin.

* **Inputs** (`state.Prefs`, `GE.makeContext`): `food_pref` (food id → `like` | `less` | `neutral`; "Not for me" stays in
  `exclude_food_ids`), `like_categories`, `less_categories`, `learn_from_log`, `hidden_usual_meals`; `planned30` (the
  entries still `planned` on `date-30 … date-1`: food, date, meal; low treatments left out) and, only when the 60-day
  history was not loaded, `eaten30` (the eaten rows of the same days). `context.load` reads one more narrow query
  (`log_user_date`) for `planned30`, and the eaten rows only when something is planned.
* **The term**: `pref(f) = clamp(P_food + P_group + L, -2.5, +1.0)` with `P_food` like +1.0 / less -2.0 / neutral 0,
  `P_group` +0.5 in `like_categories` / -1.0 in `less_categories`, and `L` = -0.5 for a skipped food (below). It is computed
  once per request (`score.pref_terms`, held by `HabitStats.pref`), cached per food with the static term, added in
  `Scorer.evaluate` **after** every hard filter (so a food that fails a filter fails it whatever its preference) and
  reported as the explain component `preference`. `score_meal` adds `clamp(mean(pref of the items), -1.5, +1.0)`, so saved,
  usual and starter meals follow the same taste. Swaps add the same term to their score (the swap's kidney test is
  unchanged); the plan builder's pool pre-ranking adds it to the static term. A person with no preference and no
  skipped food has an inactive term and pays nothing.
* **Skipped food** (`score.skip_stats`; the owner's decision Q5, refined because the log cannot say which eaten entries were
  planned): a food is *skipped on a date* when an entry of it is still `planned` for a past day of the last 30 and, on that
  date and meal slot, the person ate (`eaten`, not a low treatment) something else. `L = -0.5` when it was skipped on at
  least 2 different dates and eaten (any meal) on fewer than half of the dates it was planned. Nothing is inferred for a
  person who does not log what they eat.
* **`neutral`** ("stop using this"): for that food the history part of the habit term, the slot habit, the "You often have
  this" reason and `L` are 0. **`learn_from_log` off**: the same for every food, and no usual meals; the saved-meal bonus
  and the variety penalties (today, the previous two days, the same family) stay. Both are in `score.habit_stats`.
* **Reason**: `you_like` ("You said you like this."), only for a food the person marked, ranked after the kidney reasons
  and before `you_eat_often`; a suggestion still shows at most two positive reasons. The AI bridge keeps it out of the
  candidates' `reasons` (the AI layer's closed list) and passes it as a `liked` bit.
* **Familiar meals** (§4.6): a usual meal or a starter combo that holds a "Not for me" food or a food of a "Never suggest"
  group is never offered; a saved meal still is. A usual meal whose key is in `hidden_usual_meals` is never offered.
  `fits.usual_meal_entries` returns the key, the number of dates and the items.
* **Low treatments** (§4.9, decision Q1): `hypo.prefilter`, the card and `safety_check` read no preference. `swaps.hypo_options`,
  `insights.best_hypo_food` and the hypo mode of `find_swaps` read no `food_pref`, group, `learn_from_log`, hidden meal or
  learned signal; only "Not for me" and "Never suggest" leave `hypo_options`, and when they would leave it empty while
  a low treatment exists the whole list is returned with the note "Shown although you marked them Not for me." (`notes`
  are plain sentences; the code `shown_despite_exclusions` is the key of `messages.NOTE_TEXTS`).
* **Learned list** (`fits.learned`, `GET /learned`): `often` (eaten on at least 2 of the last 14 days: "Eaten on 6 of the last
  14 days"), `slot` ("Usually at breakfast"), `usual_meal` ("Eaten together at lunch on 3 days", with the key for
  `hidden_usual_meals`) and `planned_not_eaten` ("Planned 4 times in 30 days, eaten once"); only foods that can be
  suggested, none for a `neutral` food or a hidden meal, at most `LEARNED_MAX` (30) of each kind.
* **For the AI** (part C, built): `context.explicit_preferences(conn, user_id)` returns `{likes, less_often, not_for_me}` as
  names, foods (newest change first) then groups, each list at most 10, never a learned signal and never a `neutral` row.
  `prompts.person_block` sends them (null when empty) in the `person` object of meal ideas and Ask only, the AI bridge's
  `liked` bit is the person's own Like (`food id in habit.pref.liked`, not whether the card had room to show the reason),
  and Ask can propose a change as a card: "Prompts, answers and the guard" and "Saving from the chat" below.
* **Parity**: `tests/data/guidance_vectors.json` carries the new inputs (`prefs.food_pref` as `[id, value]` pairs,
  `like_categories`, `less_categories`, `learn_from_log`, `hidden_usual_meals`, `planned30`) and the call `learned`;
  `RULES_VERSION` is `2026-10-21.1`.

### Targets

Guidance reads the targets through one function, `app.guidance.context.load_profile`, which calls
`app.profile.get_profile` — the profile the Today screen (`GET /api/log`) shows — so guidance and the
day's status always use the same effective targets. `next-meal` and `plan-day` return them with
`profile_updated_at` (note 06 R10).

### Optional AI hook (note 06 §4.13, note 04 R2)

`app/ai/` may use only `app.guidance.ai_bridge`: `candidates_for_ai(ctx, meal, mode)` (`rerank` |
`ideas` | `swap` | `plan`; ≤ 40 candidate foods with refs, ≤ 5 familiar meals, the room, levels, allowed
handbook slugs, `rules_hash`; never a low treatment), `validate_ai_items(ctx, meal, ideas)` (the same
`check_meal()` and `score_meal()`; drops with `not_a_candidate`, `quarters_out_of_range`,
`would_exceed:<k>`, `too_many_carbs`, `hypo_treatment`, …), `validate_ai_plan(ctx, picks)` and
`register_ai_status(provider)` (feeds `next-meal`'s `ai` block; a failing provider reads as unavailable).
`app.guidance.hypo.prefilter(text, dose_g)` returns the "Treating a low" card that must be shown
**instead of** calling AI when free text may describe a low (note 04 G7).

### Parity (demo/preview mode)

The browser twin (`js/engine/guidance.js` + `js/mock/guidance.js`, frontend builder) is checked against
`tests/data/guidance_vectors.json`, generated by `tests/data/gen_guidance_vectors.py` from the pure
engine (`tests/guidance/test_parity_vectors.py` fails when it is stale): plain-JSON inputs (a fixed food
subset, the person's profile, preferences, day, history, saved meals, combos) and the engine's JSON
answers for `meal_room`, `what_fits`, `find_swaps`, `hypo_options`, `plan_day`, `day_insights`,
`period_insights`, `learned` and `prefilter`. The engine is `js/engine/guidance/*.js` (one file per Python module,
`KH.guidanceEngine`); `tools/e2e/parity.py` section 12 compares every guidance route, `POST /api/log/batch`,
`purpose`/`client_id` and `meal_hint` with a real server, and `tests/test_guidance_ui.py` keeps the demo's
texts, limits and starter-meal copy equal to the server's. `tools/e2e/guidance_perf.py` holds the twin to
note 06 §4.12's 200 ms p95 in Chromium with 4× CPU throttling (numbers in `docs/guidance.md`).

### Frontend (`js/views/guidance.js`, `KH.guidance`; note 06 §4.16)

* **Add**: "What fits now" (`#guidance-fits`) above the search: a meal picker (set by Today's "Add to …" /
  "What fits"), the `room_text`, the targets the answer used and when they were saved (`targets.values`,
  `profile_updated_at`: "Using the targets in your profile, saved …" with *Check them in Profile*; note 06 R10),
  foods by group (two per group, then "Show more"), each with portion,
  `fit_text`, the first reason, the renal dot, **Add** / **Plan** (the entry sheet, prefilled) and a "⋯"
  disclosure with **More like this**, **Less often** and **Not for me** (below); saved/usual meals that fit as chips (a sheet: add or plan them, saved
  ones through `/apply`, usual ones through `/api/log/batch`); tips; `KH.ai.mountIdeas` when `ai.available`.
* **Entry sheet** (`js/views/add.js` calls `KH.guidance.entry`): **Used to treat a low** (`#entry-hypo`) shows
  for low-treatment foods, entries stored as one and people with diabetes; pre-ticked for low-treatment
  foods; sent as `purpose` `hypo`/`none` (on edit only when changed). Ticked: the warnings become a plain
  note with the numbers, the rating pill is hidden, and "For your next low" (`/swaps?purpose=hypo`: the card
  and lower-potassium low treatments) replaces swap ideas. Otherwise a K/P/Na warning (or day overflow)
  shows "Lower-… ideas" (`/swaps`, fetched when opened): **Use this instead** (new entries) and **Use this
  amount** (`portion_option`). Each normal swap row has the same "⋯" menu; the options for the next low (`mode: "hypo"`) never do.
* **Today**: the Meal ideas card (`#guidance-today`: What fits <meal>, Plan the rest of my day, Treating a
  low for people with diabetes), "What fits" under each meal, a "treated a low" badge, and end-of-day
  insights (`#guidance-day-insights`) for a past day or today once breakfast, lunch and dinner are eaten or
  after 19:00 local.
* **Plan sheet** (`#sheet-guidance`, from Today or Plan → "Plan a day…"): date, meals to plan (the
  server's open slots first), where ideas come from (saved / usual / starters), each meal with its items,
  totals and why-lines, the day with the plan, the targets it used (as in What fits now), the energy note; **Show another** cycles `variant` 0–4;
  **Use this plan** sends `apply.entries` to `POST /api/log/batch` with a fresh `client_id` each (one retry
  after a network error is answered `existing`). Each food of a plan meal (and of the energy note) has the "⋯" menu; *Not for me*
  on one plans the day again (same option number) without it.
* **Treating a low** (`GET /hypo-options`): the card, the person's options at their dose with **Log it**
  (`purpose: "hypo"`); never filtered, never warned against, available with guidance off; offline the card
  is drawn from `KH.guidanceEngine.M.treatingALowCard`.
* **Trends**: period insights (`#guidance-period`) for the chosen 7/14/30 days ending yesterday.
* **Settings → Meal guidance** (`#set-guidance`): the `guidance` object's first fields (labelled, errors under the field), then
  **Your food preferences** (`prefsSection`, note 09 part B; walked by `tools/e2e/prefs.py`); Admin → Server settings groups
  `guidance.*`. The section reads `GET /preferences` and `GET /learned` together and draws, in order: the sentence of note 09
  §4.10 ("Less often and Not for me are about taste. They are not an allergy filter: …", the only place the UI says it), the
  foods under **More like this**, **Less often** and **Not for me** (a row each with **Remove** / **Suggest again**, the "⋯" menu
  and the counts against 1,000 and 500), **Kinds of food** (a radio group per category: *None*, *Like*, *Less often*, *Never
  suggest*; each change saves the whole `guidance` object with `PATCH /api/me/settings`, `like_categories`, `less_categories` and
  `exclude_categories`; this replaces the old "Never suggest" checkboxes), the **Learn from my log** switch ("Off: suggestions use
  only your limits and variety, not what you usually eat."), **Learned from your log** (items by kind with their `reason` and
  effect; a food has **Keep** (`PUT like`, or `less` when the effect is `less`) and **Stop using this** (`PUT neutral`); a usual
  meal has **Save as a meal** (`KH.views.plan.openMealEditor(null, trigger, draft)`: the foods and servings are read from the
  item's `key`, `<meal>:<food id>x<quarters>,…`, each food fetched with `GET /api/foods/{id}`) and **Not this meal** (the key joins
  `hidden_usual_meals`); a kept food shows "Kept: …"; **Not learning about** lists the `neutral` rows with **Learn again**
  (`DELETE`); "You hid N usual meals" with **Show them again**), and the text for AI ideas (`KH.ai.preferencesField()`, setting
  `ai.preferences`, `PATCH /api/me/ai`, only when the server offers AI; Settings → AI ideas keeps one line that points here).
* **The "⋯" menu** (`rowMenu` in `js/views/guidance.js`; a suggestion, a normal swap row, a plan item, a row in Settings):
  **More like this**, **Less often** and **Not for me** are toggles (`aria-pressed`, a check mark in the pressed one); the state is
  read from `GET /preferences` when the menu opens (Settings passes it in), a press `PUT`s `{preference}` or, on the pressed
  one, `DELETE`s the row, and a toast confirms. *Not for me* reloads what it came from; a like or a "less often" waits for the
  next load. Never on a low-treatment row (note 09 §4.9). Preferences are saved online only: offline the change is refused with
  the outbox's message ("Your server cannot be reached, so this change was not saved: …"), nothing is queued, and the lists say
  "Guidance needs a connection to your server." (`KH.guidance.openPreferences()` takes a person to the section).
* **Optional AI** (only with `ai_enrich` and AI available; `KH.ai.withConsent`): "AI order" (rerank) over the
  same list, "Ask AI to pick" under rule swaps (never for a low), "Let AI choose" in the plan ("AI's pick").
  Each has its own "What will be sent?" (the same body with `dry_run`, shown by `KH.ai.showSent`; the plan's
  sits above the plan as a link) and shows the dropped picks with their reasons (`KH.ai.droppedNotes`, G13).
* **Offline**: the last answer of each kind is kept in memory with its time ("Saved at …"); without one,
  "Guidance needs a connection to your server." Nothing goes to browser storage. Lists carry
  `role="list"`, async results are announced through `role="status"` regions.

## M2 API: barcode

Built in M2 (barcode) from note 03 R1–R6, R10, R11, §6 and its §9 security review (incl. §9.3), with
contract items 8 and 9. Code: `app/gtin.py` (normalise, classify), `app/additives.py` (E-number
tiers, ingredient scan), `app/textclean.py` (NFKC, `Cf`/`Cc`/`Cs` removal, whitespace, caps; used for
every provider text before it is stored or scanned), `app/off.py` (client, token bucket, trimming,
mapping, quality, API 3.5+ parser; the ODbL §4.6 method file), `app/egress.py` (the SSRF-checked
transport for USDA and Open Food Facts), USDA branded and provenance in `app/foods.py`, the route in
`app/barcode.py`, schema step `app/migrations/m007_barcode.py`. People and operators:
`docs/barcode-and-photos.md`. The photo routes (note 03 R8–R9) belong to the AI layer.

### `POST /api/foods/barcode` (signed in)

Body `BarcodeLookup = {"code": "049000028911", "format": "ean_13" | "ean_8" | "upc_a" | "upc_e" |
"unknown" (default), "refresh": false}` (unknown fields refused; `code` 1–64 characters, spaces and
hyphens ignored). Order: normalise → classify → the person's own custom food with that GTIN → a shared
food the person already has (linked) → per-person limit (60/hour, `429`) → Open Food Facts (if
`food.off_enabled` **and** the person's `food.off_consent`; the shared `barcode_cache` first) → USDA
FoodData Central Branded (if a USDA key is usable for the person and `food.usda_branded_barcode`, when
OFF has no answer, no nutrition facts, or lacks potassium or sodium on a US/CA label) → merge → store one
shared read-only row (`off` per GTIN, or the `usda` row of the record) → link it to the person.

```json
BarcodeResult = {"food": Food, "gtin": "00049000028911", "source": "off" | "usda" | "local",
                 "attribution": Attribution | null,      // the primary source; null for a person's own food without provenance
                 "attributions": [Attribution],          // every source the stored values came from
                 "quality": [QualityNote]}               // = food.quality
Attribution = {"text": "Product data © Open Food Facts contributors, ODbL",
               "url": "https://world.openfoodfacts.org/product/0049000028911", "license": "ODbL-1.0"}
            | {"text": "Product data: USDA FoodData Central (public domain, CC0)", "url": "https://fdc.nal.usda.gov/", "license": "CC0-1.0"}
QualityNote = {"code": "crowd_sourced" | "potassium_unknown" | "phosphorus_unknown" | "sodium_from_salt" | "carbs_available"
                       | "prepared_values" | "ml_as_g" | "no_serving" | "serving_weight_unknown" | "energy_mismatch"
                       | "implausible" | "no_nutrition"
                       | "filled_from_usda" | "filled_from_off", "message": "..."}
```

* **Always `200`** for a found product, cached or not; `source: "local"` only for the person's own
  custom food. A shared row or a cached product is given only when the person could fetch it now (the
  provider is on and usable for them) or already has it: no "someone scanned this" oracle (§9 B7);
  another person's custom food is never matched (§9 B8).
* `400 {"detail", "reason": "check_digit" | "format" | "restricted" | "isbn" | "issn" | "coupon" |
  "reserved", "gtin"?}`: before any lookup, not counted against the limit. `restricted` = GS1
  restricted-circulation prefixes 020–029, 040–049, 200–299 (and GTIN-8 000–099, 200–299; indicator 9);
  `reserved` = GTIN-8 977–999.
* `404 {"detail", "gtin", "name": null | "<product name>", "contribute_url", "checked": {"off", "usda"}}`:
  `detail` names only the databases that answered "not found"; `name` is set when Open Food Facts knows the
  product without nutrition facts; `contribute_url` is the
  Open Food Facts "add a product" page for the code.
* `429` with `Retry-After` and `retry_after`: the per-person limit, the server-wide Open Food Facts bucket
  (`food.off_rate_per_minute`; never a silent queue), Open Food Facts' own 429 (the bucket pauses 60 s),
  or the USDA key's hourly guard.
* `502 {"detail", "gtin", "checked"}`: a provider failed (timeout, refused address, HTTP error, invalid
  or oversize answer) and no other answer exists. Upstream bodies are never echoed.
* `503 {"detail", "reason": "lookups_off" | "off_consent_required" | <USDA key reason>, "gtin", "checked"}`:
  no provider is on or usable for this person, or (`off_consent_required`) Open Food Facts is on, the person has
  not agreed to it yet and USDA (when usable) did not find the product: Open Food Facts is offered rather than
  a 404 for a database that was never asked.
* `refresh: true` asks the providers again only if the cached product is at least a day old; on a
  person's own custom food it has no effect.

### Open Food Facts client (`app/off.py`)

`GET {OFF_BASE_URL}/api/v3.4/product/{off_code}?fields=<note 03 R3 list>` (API 3.5+ also asks for
`nutrition`), `User-Agent: KidneyHealth/<version> (<food.off_contact>)`, `Accept: application/json`,
`Accept-Encoding: gzip`; 8 s timeout, no redirects, 1 MiB decoded cap, one retry after 2 s on 503, never
a retry on 404, JSON only. `off_code` is 13 digits (8 for EAN-8). Mapping: `<n>_serving` when the label
is per serving (3.4 `nutrition_data_per` or the 3.5+ aggregated set), else `<n>_100g` × serving; a
per-serving label **without a serving weight** is `no_nutrition` with `serving_weight_unknown` (never stored
as per 100 g; the 404 says why); prepared values only when nothing as sold exists, then the serving text
ends "as sold, prepared" and the food takes **servings only** (`foods.weight_known`: grams → 400 on
`POST`/`PUT /api/log`, `/api/log/batch` and guidance swaps; copy-day and edits keep the servings); kJ ÷
4.184; sodium from salt ÷ 2.5; absent → `null`; plausibility per 100 g (sodium ≤ 40 g except salts,
potassium ≤ 60 g and phosphorus ≤ 32 g, what a food-grade salt can hold, so salt substitutes and cream of
tartar keep their number; macros ≤ 100 g, energy ≤ 950 kcal, model bounds); energy mismatch > 25 % and
> 40 kcal; category by an ordered tag map; flags from `app/additives.py` plus `counts_as_fluid` with
`fluid_ml` = the serving for a liquid (`off.is_liquid`: an mL serving, a label per 100 mL or
`en:beverages`, not drink powders; the same test gives the "100 mL" serving text), `processed` (NOVA 4),
`high_gi` (`en:sweetened-beverages` with ≥ 5 g sugars/100 mL), `alcohol` (`en:alcoholic-beverages`); never
`hypo_treatment` or `low_potassium_fruit`. `source_url` is built from a constant
(`https://world.openfoodfacts.org/product/<off_code>`), never copied from a payload (§9 B4).

### USDA FoodData Central Branded by barcode (`app/foods.py`)

`usda_find_by_gtin`: `GET /foods/search?query=<form>&dataType=Branded&pageSize=10` for the 12-, 13- and
14-digit forms (`app.gtin.usda_candidates`), stopping at the first result whose `gtinUpc` padded to 14
digits equals the GTIN-14, then `GET /food/{fdcId}`. Same key resolution, daily quota (one per lookup)
and hourly guard (`guard_id`) as the other USDA routes; 2 MiB decoded cap. `map_usda_record` prefers
`labelNutrients` per serving (`potassium` or the API's `postassium`), else scales `foodNutrients`; it
also runs the additive scan, so `POST /api/foods/usda/import` sets additive flags too, and sets `alcohol` for
≥ 0.4 g ethanol per 100 g (nutrient 221/1018) or an "Alcoholic beverage, …" name. Merge (both
found): nutrients from USDA when the OFF label is US/CA (or its country is unknown), else from OFF; a
`null` is filled from the other source through per-gram values (never mixing prepared and as-sold
values), noted `filled_from_<src>:<key>`; flags and additives are the union.

### Foods and log changes

* `FOOD_SOURCES` gains `off`; `FLAGS` gains `potassium_additive` (rule in "Per-serving thresholds").
  `off` rows are shared and read-only like `usda` rows (`PUT` → 409, copy to edit; `DELETE` removes only
  the caller's link).
* `Food` gains `gtin` (GTIN-14 or `null`), `source_url`, `source_license` (`ODbL-1.0`, `CC0-1.0`,
  `CC0-1.0 AND ODbL-1.0`, or `null`), `quality: [QualityNote]`, `additives: ["e338", "potassium lactate", …]`
  (why an additive flag was set) and `ingredients_text`.
* `FoodCreate` (`POST`/`PUT /api/foods`) and `POST /api/log/quick` accept `gtin` (8, 12, 13 or 14 digits,
  valid check digit; stored as GTIN-14; 400 otherwise) and `ingredients_text` (≤ 4,000 characters). On
  save the additive scan adds `phosphate_additive` / `potassium_additive` / `avoid_ckd` (with the
  salt-substitute note when no notes were given). A `PUT` that leaves `gtin` or `ingredients_text` out
  keeps the stored value. `POST /api/foods/{id}/copy` keeps `gtin`, `ingredients_text`, `additives`,
  `source_url` and `source_license` (the ODbL notice travels with copied data), not `quality`.
* CSV (`/api/log/export.csv` and the export archive's `log.csv`) gains the last columns `source` and
  `source_license`; the archive's `foods.csv` gains `gtin`, `source_license`, `source_url`, and its
  README carries the ODbL notice.
* **Unknown values are counted, never shown as 0** (v0.3.0 review; note 03 R7, F1; note 06 R4). A total
  adds only known values (`nutrients.add_totals`), so every total says how many entries it misses
  (`nutrients.count_unknown`; maps are `{nutrient: entries}`, only nutrients with a count):
  `DaySummary += {"unknown", "planned_unknown", "projected_unknown", "meal_unknown": {meal: {...}},
  "planned_meal_unknown": {meal: {...}}}`; every `status` / `projected_status` item gains `"unknown": n`
  (0 when all are known; the `level` is judged on what is known, so with `n > 0` the true total may be
  higher); `/api/log/range` days gain `unknown`, `planned_unknown`, `projected_unknown`;
  `PeriodSummary.nutrients[key]` gains `unknown_entries` and `unknown_days` (logged days of the period with
  at least one such entry) and each interdialytic nutrient `unknown_entries`. The UI shows such a total
  with "+ n not listed" (never a bare `0` or `–`); the demo twin (`js/mock/log.js`) returns the same fields.
  In detail (`KH.ui.unknownOf`, `notListed`, `foodsNotListing`, `atLeast` in `js/core.js`): a status bar reads
  "≥ 55 / 3,500 mg" ("not listed" when nothing known), its level **Not complete** (`level-unknown`, grey, never
  the green OK; caution and over keep their warning), no "… left", and "1 food does not list potassium, so the
  total may be higher"; meal lines "K ≥ 55 (+ 1 not listed)" or "K not listed"; entry rows "not listed"; the
  all-totals list, the 7-day strip, "since last dialysis", Trends (days, averages, the period card; a dashed bar
  edge), Plan's day chips, the saved-meal cards on Plan, the saved-meal shortcuts on Add and the "Add a saved meal" sheet (from
  the meal's `unknown` and `per_serving`) the same. The guidance meals (`FamiliarMeal`, `PlanMeal`, `Closest`) and AI ideas carry
  `unknown`, the keys of `totals` some food does not list (`unknown_json` in `app/guidance/fits.py`, `unknownJson` in the twin):
  their chips, the meal sheet, the plan and the idea cards show those totals as "≥ …" or "… not listed"; the entry sheet's impact says "would reach at least …". The twin uses
  `KH.rules.countUnknown` / `mergeUnknown` / `markUnknown` (twins of `nutrients.count_unknown` / `merge_unknown` /
  `mark_unknown`) and is compared with the server by `tests/test_unknown_values_twin.py` and `tools/e2e/parity.py`.

### Schema step 9 (`m009_about_tolerance.py`, v0.3.1)

`user_profiles.about_tolerance_pct INTEGER NOT NULL DEFAULT 0`: how far above an "about" target (minimum =
maximum) still counts as on target, 0–10 %. `PUT /api/profile` takes an integer 0–10 (`null` resets it to 0;
anything else is a 400); a stored value outside the range reads as 0. No guideline gives a tolerance, so the
default keeps the earlier behaviour and the value is the person's, from their care team (`handbook/REVIEW.md`,
"Food targets"). See "Tolerances (v0.3.1)" under the day summary.

### Schema step 8 (`m008_profile_chosen.py`, v0.3.1)

`user_profiles.ckd_stage_set_at` and `diabetes_set_at` (TEXT, UTC; NULL = "not chosen yet"). A
`PUT /api/profile` that sends a non-null `ckd_stage` (or `diabetes`) records the time; null or an
omitted field leaves the choice open. `Profile` gains `ckd_stage_chosen` and `diabetes_chosen`
(booleans). A new account's row starts unchosen; rows that existed before the step are marked chosen
at their `updated_at`. While unchosen, the stored defaults (stage 3b, type 1 diabetes) keep driving
targets, guidance and the Treating a low card; the Profile form shows "Not chosen yet", Today shows a
one-line prompt, and the form refuses to fetch suggested targets until both are chosen. The API's
`GET /api/profile/suggested-targets` itself is unchanged.

### Schema step 7 (`m007_barcode.py`)

`foods.gtin`, `source_url`, `source_license`, `retrieved_at`, `ingredients_text`, `additives_json`
(`NOT NULL DEFAULT '[]'`), `quality_json` (`NOT NULL DEFAULT '[]'`; stored codes may name a nutrient:
`implausible:sodium_mg`); index `foods_gtin` (partial, `gtin IS NOT NULL`) and unique `foods_off_gtin`
(one `off` row per GTIN); `barcode_cache (gtin CHECK length 14, provider 'off'|'usda', status
'found'|'not_found'|'no_nutrition', payload_json, fetched_at, PRIMARY KEY (gtin, provider)) WITHOUT
ROWID` with a partial index on negative rows. The cache holds trimmed product data only (never who
scanned); found rows stay until a refresh, negative rows expire after
`food.barcode_negative_ttl_hours` and are purged daily. `python -m app.admin remap-barcodes` re-maps
cached products into the shared rows without the network; `purge-barcode-cache` purges now.

### Settings (registered in `app/settings_registry.py`) and configuration

`food.off_enabled` (instance, `false`, `OFF_ENABLED`; M1), `food.off_consent` (user, `false`; M1),
`food.scan_prefer_camera` (user, `true`; note 03 R10 "Prefer live camera": the Scan sheet starts the live camera as it
opens, in a secure context only, unless the person already chose a photo or typed digits),
`food.off_contact` (instance, the project URL, `OFF_CONTACT`; printable ASCII without round brackets or backslash: it goes
into the User-Agent), `food.off_rate_per_minute` (instance, 10, 1–15, `OFF_RATE_PER_MINUTE`),
`food.barcode_negative_ttl_hours` (instance, 24, 1–720, `BARCODE_NEGATIVE_TTL_HOURS`),
`food.usda_branded_barcode` (instance, `true`, `USDA_BRANDED_BARCODE`). **`OFF_BASE_URL`** is env only
(`app/config.py`, never a runtime setting, §9 B5): `https://` (plain `http://` only for localhost), no
path, query or credentials; a host other than the default may resolve to a private address.

### Outbound HTTP (`app/egress.py`)

`CheckedTransport` resolves the host on every request and checks every address (IPv4 inside IPv6
unwrapped: mapped, 6to4, Teredo, NAT64, compatible): unspecified, multicast, reserved, link-local, cloud
metadata (169.254.169.254, 169.254.170.2, fd00:ec2::254, 100.100.100.200) and the Kubernetes API
service address are always refused; private, loopback, CGNAT and ULA only for an operator-chosen host;
it connects to the checked IP with the original `Host` and SNI. Clients never follow redirects. When the
standard `HTTPS_PROXY`/`ALL_PROXY` variables name a proxy (honouring `NO_PROXY`), requests go to the proxy
and pinning is its job. `read_capped` counts decoded bytes. Every outbound client in the app uses it (USDA
`app/foods.py`, Open Food Facts `app/off.py`, the breached-password check `app/auth/policy.py`) or, for AI,
`app/ai/transport.py`'s `PinnedTransport`; `tests/test_egress.py` fails on any other client.

### Parity

The browser rules twin (`js/engine/rules.js`) has the `potassium_additive` flag and warning; the
vectors (`tests/data/rules_vectors.json`, generator `tests/data/gen_rules_vectors.py`) cover it. The new
`food.*` settings are in `tests/data/settings_vectors.json` (a string key's `pattern` too, with cases
that break it), which `js/engine/settings.js` must match (frontend).

`js/engine/gtin.js`, `textclean.js`, `additives.js` and `off.js` (quality sentences, attribution) are checked
by `tests/data/barcode_vectors.json` (generator `tests/data/gen_barcode_vectors.py`: every GTIN form and
class, text cleaning incl. Python's `\s`/`casefold` semantics, every fixture's ingredient list and 500
generated ones, the three demo products produced by the real route over the recorded fixtures).
`js/mock/barcode.js` answers `POST /api/foods/barcode` with the server's validation, reasons and texts; in
the demo Open Food Facts is "on" (locked) with **three recorded products** (Diet Coke 049000028911,
Kraft macaroni 021000658831, Nutella 3017624010701, from `tests/fixtures/off/`), consent is still asked, and
any other barcode answers 404 naming the samples. `tools/e2e/parity.py` section 13 compares foods with a
`gtin` and ingredient list and every lookup answer (with `reason`, `gtin`, `checked`) against a real server
with lookups off on both sides.

### Frontend (`js/scan.js` = `KH.scan`, `css/device.css`; note 03 R7, R8 client side, R9, R11)

* **Add view → Scan** (first action) opens `#sheet-scan` (the live camera starting at once with `food.scan_prefer_camera`,
  read from `GET /api/me/settings` at each opening; Settings → Food data → *Scanning*): *Camera* (live), *Photo of a barcode*, *Type the
  barcode* (digits or a USB/Bluetooth scanner; the check digit is checked in the browser with `KH.gtin`,
  errors under the field with `aria-describedby`/`aria-invalid`). Decoding is on the device only: the
  native `BarcodeDetector` when it supports `ean_13`, else the vendored ponyfill (`window.BarcodeDetectionAPI`,
  a static deferred script) whose 1 MB WebAssembly reader is fetched from `/vendor/zxing-wasm-3.1.3/` on
  first use (`locateFile` override; CSP `script-src 'self' 'wasm-unsafe-eval'`; never cached by the service
  worker's shell list, kept in its vendor cache after first use). The preview build omits the ponyfill
  (`data-preview="omit"`): there a photo is read only by a native `BarcodeDetector`, the camera is off,
  and addresses of other sites are shown as text (its sandboxed frame cannot open new windows).
* **Live camera** only in a secure context (HTTPS or `localhost`); on plain HTTP the button is replaced by
  why and the photo route. `getUserMedia({video: {facingMode: "environment"}})`, ~8 detections a second,
  a result after **two identical reads**, a 4-second no-frame watchdog, tracks stopped on close, Escape,
  `visibilitychange` (hidden), `pagehide` and navigation.
* **Result:** `POST /api/foods/barcode` → the entry sheet (`KH.views.add.openEntrySheet`) with the food's
  provenance under its name: the attribution line (link only when `https:`, `target=_blank`, `rel=noopener
  noreferrer`), "Barcode <digits>", the quality notes, "Additives found: …", the ingredient list; missing
  potassium/phosphorus read **"not listed"** (never 0). A food with values only as prepared is logged in servings:
  the entry sheet hides **Grams** and says why (`KH.off.weightKnown`, twin of `foods.weight_known`; the demo's log
  and swaps refuse grams with the server's text, `tests/test_demo_servings_only.py` through `tests/js/demo_api.mjs`).
  404 → *Enter from the label* (Quick add with the barcode and the photo prompt) and the Open Food Facts contribute link; 503 `off_consent_required` → the
  consent panel (`PATCH /api/me/settings {"food.off_consent": true}` then the lookup again); 503 lookups off,
  429 (with the wait), 502, 400 (the reason's text) each have their own panel and a way forward.
* **Quick add** gains *Barcode* (optional, checked like the scan), *Ingredients* (optional; the browser
  additive scan shows "Phosphate additives / Potassium additives / …" before saving and the server stores
  the same flags) and *Use a photo of the label*: shown beside the form on wide screens (above it on
  phones), zoom 1×/2×/3×, an object URL revoked when removed or closed, never uploaded unless the person
  presses *Read the label for me (AI)* (offered when `KH.ai` reports the `label` feature): the browser
  re-encodes it to a JPEG with the long edge ≤ 1600 px through a canvas (no EXIF), asks consent once per
  destination, and fills the fields marked "from photo" (the mark goes when a field is edited).
* **Settings → About** lists the data sources (Open Food Facts ODbL notice and method file, USDA FoodData
  Central citation, the decoder's licences); Admin → Server settings groups the `food.*` keys.

## M2: the offline outbox (`js/offline.js` = `KH.offline`, `KH.net`; note 02 R5)

* **Storage:** IndexedDB database `kdl` (version 1) with stores `meta`, `snapshots` (key `[user_id, path]`),
  `foods` (key `[user_id, id]`) and `outbox` (key `client_id`, index `created_at`), no library; in the demo,
  the preview or a browser without IndexedDB the same stores live in memory. Health data never goes to
  `localStorage`. Everything is per person (`user_id`); another person's items are never sent. Sign-out and
  *Clear offline data on this device* delete the database (the server's logout also sends `Clear-Site-Data`).
* **Hooks in `KH.request`** (`KH.net`): `prepare` gives every `POST /api/log` and `/quick` a fresh
  `client_id` (UUID v4) from its first try; `timeoutFor` aborts a log write or a snapshot read after 6 s;
  on a network failure (or a 502/503/504 that is not the app's JSON) a log write is **queued** and answered
  with a pending entry (`id: "pending:<client_id>"`, warnings from the rules twin), a `GET` of a saved path
  is answered from this device's copy (`/api/auth/status`, `/api/profile`, `/api/me`, `/api/handbook`,
  `/api/foods/categories`, `/api/meals`, `/api/log?date=` for 13 days back to 7 ahead, `/api/log/range`,
  `/api/log/summary`), and food search from the foods this device has seen (refreshed daily: the builtin list
  from `GET /api/foods/builtin` with the last ETag, 304 while unchanged, builtin foods no longer listed dropped;
  the person's own and scanned foods ≤ 200 per source); `afterResponse` saves copies and merges waiting entries into the day (totals recomputed with the
  mock's day maths).
* **Sync:** on `online`, page show, visibility, every 30 s while something waits, and on start; one at a time
  (Web Locks `kdl-sync` across tabs). FIFO: consecutive entries go through `POST /api/log/batch` (≤ 40), a
  quick add or mark-eaten alone; a batch the server refuses is retried without the item its message names
  (`entries[i]` / `entries.i.`), or one by one when none is named. A refused item is kept as **not saved**
  with the server's reason (Retry / Discard in Settings → This device); a network error, 5xx, 429, 401 or 403
  stops the run and the items keep waiting. A repeated `client_id` answers `existing`, so a lost answer
  never makes a second row.
* **UI:** the header badge (`#sync-badge`: "Offline · 2 to sync" / "1 not saved"; on phones the number, the
  full words in its `aria-label`) opens Settings → This device; Today marks waiting entries "waiting to
  sync" and says when it shows this device's saved copy; Add's search says "Offline: saved
  on this device"; sign-out with items waiting opens `#sheet-unsynced` (Try to sync now / Stay signed in /
  Sign out and lose them). Announcements go through `#sync-live` (`role=status`). **Edits and deletes of entries already on
  the server wait too** ("Offline edits and deletes" below). Any other change made without a connection (the profile,
  targets, settings) fails with "… this change was not saved: it needs a connection. Food you log still waits on this
  device and syncs later."
* **Checks:** `tests/test_device_ui.py` (static), `tools/e2e/device.py` (Chromium with
  `context.set_offline`: log offline, reload offline from the service worker, reconnect synced once, a lost
  batch answer resent without a second row, Retry/Discard, the sign-out sheet; the demo's outbox).

## M2 API: AI and photos

Built in M2 (ai) from note 04 R1, R3–R9, R11, R13 (with this contract's corrections: guidance is the
package `app/guidance/`, AI calls it only through `app.guidance.ai_bridge`), its §6 checklist and §9
security review, contract items 2 and 13, and note 03 R8, R9 and §9 B1, B10 for the photo routes.
Code: the package `app/ai/` — `presets` (preset table), `netpolicy` (pure URL/IP policy,
`AI_PRIVATE_HOSTS`/`AI_DENY_CIDRS` parsers), `transport` (pinned `httpx2` transport, decoded-byte cap,
error categories, CA-store self-check), `client` (request bodies, parsing, JSON extraction, one
retry or repair, concurrency gate, "Test connection" with the Hermes tool check), `prompts`
(`SYSTEM_PROMPT` and `CHAT_SYSTEM_PROMPT` as templates with `system_prompt(person)` and `chat_prompt(person)`, `TASK_SYSTEM_PROMPT`, `PROMPT_VERSION`, the data block), `schemas` (wire schemas and
answer models, and `ChatStep` for the Ask chat), `guard` (V1–V9, pure), `chat` (the Ask chat's step loop, answer checks and
figures; "Ask chat" below), `lab_report` (the checks on a lab report photo's copied lines; "Lab report photos" below), `features` (prepare/judge for each feature, the G7/G8
pre-filters, the label draft), `config` (provider rows, resolution, quota, consent, AI activity,
retention), `routing` (provider roles and per-feature routing; "Privacy tiers" below), `quality` and `eval_reports` (how well each AI is doing; "How well each AI is doing" below), `routes` (the routers below, the call pipeline, the daily re-test); `app/vision.py` (photo
routes), `app/imagecheck.py` (JPEG check and rewrite, pure); schema step 6
(`app/migrations/m006_ai.py`). People and operators: `docs/ai.md`; photos also in
`docs/barcode-and-photos.md` "Photos".

### Switches and configuration (contract item 2: one registry, one credential resolver)

* **Registry keys** (`app/settings_registry.py`, "Note 04"): `ai.enabled` (instance, `false`,
  `AI_ENABLED`), `ai.user_keys_allowed` (`true`, `AI_ALLOW_USER_KEYS`), `ai.allow_user_base_url`
  (`false`, `AI_ALLOW_USER_BASE_URL`), `ai.shared_daily_limit` (30, 0–100000, 0 = unlimited,
  `AI_SHARED_DAILY_LIMIT`), `ai.max_concurrency` (2, 1–32, `AI_MAX_CONCURRENCY`), `ai.audit_retention_days`
  (30, 0–365, `AI_AUDIT_RETENTION_DAYS`), `ai.vision_plate_enabled` (`false`, `AI_VISION_PLATE_ENABLED`),
  `ai.vision_allow_agent` (`false`, `AI_VISION_ALLOW_AGENT`), `ai.chat_enabled` (`false`, `AI_CHAT_ENABLED`; the Ask screen,
  "Ask chat" below), `ai.allow_trusted_saves` (`false`, `AI_ALLOW_TRUSTED_SAVES`; lets a person trust the Ask chat to save
  without asking, "Saving from the chat" below), `ai.voice_enabled` (`false`, `AI_VOICE_ENABLED`; the Ask microphone,
  "Voice input" below), the seven routing keys `ai.route.*` ("Privacy tiers: roles and routing" below; `ai.route.labs` takes only `local` or `off`), and the person's object `ai` (scope `user`):
  `{opt_in: false, provider: "auto" | "own" | "shared:<id>", share_age_sex: false, preferences: "" (≤ 200), trust: "ask" |
  "conversation" | "always" ("ask")}` with **no key field** (§9 A6; unknown fields refused). With `AUTH_MODE=none` the eighteen
  `ai.*` instance keys are env-only: `PATCH /api/admin/settings` answers `403` for them (§9 A7).
* **Environment only** (`app/config.py` `AiEnv`; never runtime-editable): `AI_PROVIDER` (a preset),
  `AI_PROVIDER_ROLE` (`local` or `cloud`: the role of that provider; `local` needs a private host, checked at start-up),
  `AI_BASE_URL`, `AI_API_KEY[_FILE]` (`OPENAI_API_KEY[_FILE]` accepted when `AI_PROVIDER=openai`),
  `AI_MODEL` (default `gpt-6-luna` for `openai`, required otherwise), `AI_VISION_MODEL` (empty = photo
  features off), `AI_TIMEOUT_S` (preset read timeout), `AI_VISION_TIMEOUT_S` (120), `AI_MAX_TOKENS` (1500,
  64–32768), `AI_STRUCTURED_OUTPUT` (`auto` | `json_schema` | `json_object` | `prompt`), `AI_REASONING_EFFORT`,
  `AI_CONTEXT_TOKENS` (8192 self-hosted/agent/custom, 32768 cloud), `AI_PRIVATE_HOSTS`, `AI_DENY_CIDRS`,
  `AI_HTTP_PROXY`, `AI_MAX_RESPONSE_BYTES` (262144), `AI_OPENROUTER_ZDR`, `AI_EVAL_REPORTS_DIR` (a read-only folder of `ai_eval` reports; "How well each AI is doing" below), `MAX_IMAGE_BYTES` (4 MiB); the **second environment
  provider, always the cloud AI** (`AiCloudEnv`, `AiEnv.cloud`; "Environment providers: main and cloud" below):
  `AI_CLOUD_PROVIDER`, `AI_CLOUD_BASE_URL`, `AI_CLOUD_API_KEY[_FILE]`, `AI_CLOUD_MODEL`, `AI_CLOUD_VISION_MODEL`,
  `AI_CLOUD_TIMEOUT_S` (5–600), `AI_CLOUD_MAX_TOKENS` (1500, 64–32768), `AI_CLOUD_CONTEXT_TOKENS` (32768, 1024–2000000),
  `AI_CLOUD_STRUCTURED_OUTPUT` (`auto`), `AI_CLOUD_REASONING_EFFORT`, `AI_CLOUD_UPSTREAM`; and the speech-to-text
  server of the Ask microphone, `STT_BASE_URL`, `STT_MODEL`, `STT_API_KEY[_FILE]`, `STT_TIMEOUT_S` (60), `STT_DAILY_LIMIT` (100),
  `STT_MAX_AUDIO_BYTES` (1.5 MiB; `Settings.max_audio_bytes`; "Voice input" below). A bad
  value stops the start with a message naming the variable; `ALLOW_PRIVATE_AI_HOSTS` is refused (no alias,
  no wildcard). An https env provider without CA certificates stops the start (R12 self-check); CI's image smoke test runs the same check inside the built image.
* **Presets** (`app/ai/presets.py`): `openai`, `openrouter`, `nous_portal` (cloud; a person may use them
  with their own key), `ollama`, `lmstudio`, `llamacpp`, `vllm`, `litellm` (self-hosted), `hermes` (agent,
  `http://host.containers.internal:8643/v1`, prompt-only JSON, tool check; contract item 13),
  `openai_compatible` (custom). Each fixes the token field, structured mode, temperature, reasoning
  effort, read timeout and extra body (OpenAI `store: false`; OpenRouter `provider: {data_collection:
  "deny", require_parameters: true}` and `zdr` with `AI_OPENROUTER_ZDR`).
* **Providers** are rows of `ai_providers`: the env providers (`locked = 1`, at most one per `env_slot`, kept in step with the
  environment at start-up; their keys stay in the environment, `probe_json.key_fp` is an HMAC that tells a
  changed key), admins' shared providers, and at most one per person (`scope = 'user'`). Keys are sealed
  with `Keyring.seal(purpose="ai_provider:<id>", owner=<owner id or None>)` and shown only as
  `{set, last4}` (last 4 for keys of ≥ 20 characters), `{set, source: "env", locked: true}` or
  `{set, status: "unreadable"}`.
* **Resolution** (`config.resolve`, the rule before routing; every feature now calls `routing.resolve_feature`, which
  uses it for `any` and for a person's own provider): the person's own provider when they chose `own` and it is usable and
  allowed; else the shared provider they chose (`shared:<id>`) or the first usable shared one (if
  `users.can_use_shared`); else none. A failing own provider **never** falls back to a shared one. With routing,
  a feature pinned to `local` or `cloud` takes the shared provider that holds that role instead of the person's
  shared choice ("Privacy tiers: roles and routing" below).

* **Environment providers: main and cloud** (schema step 20, `m020_ai_env_slots.py`). Two providers can come from the
  environment. `ai_providers.env_slot` is `main` for the row `AI_PROVIDER` defines and `cloud` for the row `AI_CLOUD_PROVIDER`
  defines (NULL for every other row; the step makes the row that is locked today `main`); `locked` keeps its meaning (read-only here),
  and the unique index `ai_providers_one_per_env_slot` allows one locked row per slot (a locked row without a slot counts as `main`).
  `ai_providers.upstream` holds `AI_CLOUD_UPSTREAM`. `config.env_slot(settings, slot)` gives the values of a slot with the defaults
  applied (the cloud slot: `AI_CLOUD_MAX_TOKENS` 1500, `AI_CLOUD_STRUCTURED_OUTPUT` `auto`, **`AI_CLOUD_CONTEXT_TOKENS` 32768 whatever the
  preset's kind**; the main slot is unchanged: `AI_CONTEXT_TOKENS`, else the preset's), `config.check_env` checks them and
  `config.sync_env_provider` writes the rows at start-up (`routes.startup`). The key of a locked row is read from the environment by
  slot (`config.env_key`), never stored; the connection test's `key_fp` is the fingerprint of that key.
  * *Start-up checks* (`ConfigError` unless a warning is named): `AI_CLOUD_PROVIDER` with `AI_PROVIDER_ROLE=cloud` (two cloud
    providers); `AI_PROVIDER` without `AI_PROVIDER_ROLE` while `AI_CLOUD_PROVIDER` is set (it must be `local`); `hermes` in the cloud
    slot; an unknown preset, a missing address, model or key, a bad structured mode or reasoning effort (each naming the `AI_CLOUD_`
    variable); an address `netpolicy.check_url(…, "shared", …)` refuses, so a private address or plain `http://` that is not in
    `AI_PRIVATE_HOSTS` stops the start with a message naming it (the cloud AI may sit on a private host, subject to
    `AI_PRIVATE_HOSTS` like every shared provider; `AI_DENY_CIDRS` and `AI_HTTP_PROXY` apply as to every shared provider);
    `AI_CLOUD_UPSTREAM` missing when the preset `can_proxy` (kind `self_hosted` or `custom`); `AI_CLOUD_UPSTREAM` that is not a plain
    name (`config.UPSTREAM_PATTERN`: a letter or digit, then letters, digits, spaces and `.&-`, at most 60 characters). Warnings: an
    `AI_CLOUD_` value without `AI_CLOUD_PROVIDER`; `AI_CLOUD_UPSTREAM` with a cloud-kind preset (ignored, stored as NULL).
  * *Sync* (`_sync_slot`): an unset variable deletes its row (consents cascade); a changed host (`host:port`) or a changed
    `upstream` deletes that provider's consents; any changed value, or a key whose fingerprint differs from the stored test's, clears
    the connection test; a restart with the same environment changes nothing.
  * *Roles*: `routing.role_row` gives the `cloud` role to the `cloud` slot's row whenever it exists, the role `AI_PROVIDER_ROLE` names to
    the main row, and never lets a setting give a locked row another role. `routing.plan` answers `409` (`locked`) for any change of
    `cloud_provider` while `AI_CLOUD_PROVIDER` is set (the message names it), and for naming that row as the local AI. The cloud row is
    never the local AI, so `labs` (local-only) can never be served by it: with no usable local AI the feature is off
    (`no_local_provider`); `tests/test_ai_cloud_routing.py` pins this with two environment providers and a transport that records
    connections.
  * *Consent line*: `presets.policy_line(preset, scope, upstream)` returns, for a shared self-hosted or custom preset with an
    upstream, the new line `PROXY_POLICY` ("Goes through your admin's LiteLLM proxy to Anthropic. Anthropic receives what is sent,
    under its own terms; your admin can read it too."; other presets say "your admin's proxy"). No existing line changed, so
    `POLICY_VERSION` is the same and nobody is asked again; `ProviderConfig.upstream` carries the name to `consent_request` and
    `routing.provider_summary`, `provider_view` gives `env` (`AI_PROVIDER` or `AI_CLOUD_PROVIDER`) and `upstream`.

### Routes

Every `/api/ai/*` and `/api/vision/*` route needs a signed-in person and answers **`404 {"detail": "Not
Found"}` while `ai.enabled` is off**, exactly as if it were not registered (checked per request after
the identity check, so anonymous callers still get `401` and an admin can switch AI on without a
restart). `/api/me/ai` is always there (Settings shows the "off" state); its probe needs AI on. Every
query takes `user.id`; another person's provider, consent or AI activity is never visible (`404`).

| Method and path | Body / query → response |
|---|---|
| `GET /api/ai/status` | → `{enabled, opted_in, available, reason, message, provider: {id, label, host, model, vision_model, scope, kind, policy} \| null, consent: {text, photos, chat, labs, voice?}, routing: {mode: "routed" \| "as_before"}, routes: {photos, meal_ideas, describe, chat, labs, recipes: {feature, label, purpose, route, role: "local" \| "cloud" \| "own" \| null, available, reason, message, text, runs_on: {id, label, host, model, vision_model, scope, kind, policy} \| null, consent}}, policy_version, daily_limit, remaining_today, features: {next_meal, parse_meal, label, plate, chat, voice, lab_report, recipes, recipe_steps}, voice: {host, model, max_seconds, max_bytes, remaining_today, consent, request} \| null, trust: {setting, allowed, effective}, prompt_version}`; `provider` and the `reason` are those of the first feature that resolves (meal ideas, describe, photos, chat); `consent.text` is meal ideas'; `features.voice` (and `voice`, and `consent.voice`) only with the chat available (the chat route resolves and is not `off`), `ai.voice_enabled` on and `STT_BASE_URL` set; `features.chat` is true only with the person set up for AI, a provider for the chat route **and** `ai.chat_enabled` on; `features.lab_report` is true only with the person opted in and the `labs` route resolving to the local AI (role `local`, pinned to the private network) with a vision model ("Lab report photos" below); `routes.labs.text` says why not ("Needs a local AI on your own network, which is not set up on this server, so it is off."); `trust.setting` is the person's choice, `allowed` the admin switch `ai.allow_trusted_saves`, `effective` the choice when allowed and `ask` when not |
| `POST /api/ai/next-meal` | `{meal, date?, mode: "ideas" \| "rerank" \| "swap" \| "plan", entry_id? \| food_id? + servings?, exclude_food_ids? (ideas only, ≤ 60: the foods of ideas already shown, left out of the candidates for **Other ideas**; 400 in another mode)}` (`?dry_run=true`) → `AiAnswer` |
| `POST /api/ai/recipes` | `{mode: "suggest" \| "change", target?: "meal" \| "day" ("meal"), meal?, date?, dish? (suggest: one of the fixed dishes), makes? (1, 2, 4 or 6; suggest), meal_id? (change), exclude_food_ids? (≤ 60: foods of recipes already shown, left out of the candidates for **Other recipes** unless flagged `ingredient`)}` (`?dry_run=true`) → `AiAnswer` with `recipes: [{title, dish, theme, reason_codes, why, makes, fit: {status, before, after, changes, still_over}, fitted, items, per_serving, unknown, steps, steps_label, steps_note, steps_dropped, differences, body}]` (≤ 2; 1 for `change`), `steps_dropped`, `claims_corrected`, `dropped`; `body` is the exact `POST /api/meals` body. AI recipes (note 16 §8, docs/ai.md "Recipes that fit"): route `recipes`, consent `text`; a recipe with a low-treatment food answers `{status: "not_sent", ai_called: false}`; 404 for another person's `meal_id`; never saves |
| `POST /api/ai/parse-meal` | `{text (1–300), meal?, date?}` (`?dry_run=true`) → `AiAnswer` with `items: [{text, search, amount, unit, matches: [{food, servings \| null}] (≤ 3)}]`, or the pre-filter answer |
| `POST /api/ai/chat` | `{messages: [{role: "user" \| "assistant", text (1–2000)}] (1–20, the last from the person), request_id? (8–48 of A–Z a–z 0–9 _ -), trust? ("ask" \| "conversation")}` (`?dry_run=true`) → the Ask answer, or the rule-based card for a low or an emergency; 404 while `ai.chat_enabled` is off ("Ask chat" below; `request_id` and `trust`: "Saving from the chat") |
| `POST /api/ai/transcribe` | the body is one clip (`Content-Type` `audio/webm`, `audio/ogg`, `audio/mp4` or `audio/wav`, at most `STT_MAX_AUDIO_BYTES`), `?seconds=0..60` (the page's own length, for the activity row only) → `{text}`; 404 before the body unless voice is on and configured ("Voice input" below) |
| `POST /api/ai/consent` | `{provider_id, purpose: "text" \| "photos" \| "chat" \| "voice" \| "labs", skip_preview}` → `{consent: {host, policy_version, skip_preview, at}, provider_id, provider_label, host, purpose, policy, policy_version, kind}`; `409` when no feature of that purpose is served by `provider_id` any more (`text` covers meal ideas and describe, which may run on different providers; `voice` is not routed: it rides with Ask, so `provider_id` is the provider the chat route resolves to, and the consent names the transcription host); the consent request also carries `local` (the provider is the local AI) and, for `labs`, `notice` (the plain-words lines of the consent sheet: where the photo goes, what the report may show, that it is not kept, to crop it) |
| `DELETE /api/ai/consent/{provider_id}` | `?purpose=text\|photos\|chat\|voice\|labs` (all when left out) → 204; 404 when there is none |
| `GET /api/ai/audit` | `before`, `limit` 1–200 (50) → `{events: [{id, created_at, feature, provider_id, model, destination_host, prompt_version, request_json, response_text, verdict_json, latency_ms, status}]}` (the person's own) |
| `DELETE /api/ai/audit` | → 204 ("Delete my AI history"; usage counts stay) |
| `POST /api/vision/label` | raw `image/jpeg` body (`?dry_run=true`) → `AiAnswer` with `{draft: FoodCreate-shaped (flags empty), from_photo (fields the AI read, the serving included), estimated (from % Daily Value or salt, or the 100 g / 100 mL serving of a per-100 label), needs, checks, notice}` or `{status: "not_a_label" \| "unreadable", draft: null}`; never saves |
| `POST /api/vision/plate` | raw `image/jpeg` body (`?dry_run=true`) → `AiAnswer` with `{items: [{name, search, grams_estimate, portion_text, confidence, ticked, candidates: [{food, servings}] (≤ 3)}], banner, notice}`; off unless `ai.vision_plate_enabled` |
| `POST /api/ai/read-lab-report` | raw `image/jpeg` body (`?dry_run=true`) → `{status: "ok" \| "no_results" \| "not_a_lab_report" \| "unreadable", rows: [{analyte, label, value, unit, display, taken_on \| null, printed_date \| null, date_problem \| null, date_note \| null}], dropped: {unknown_analyte, unknown_unit, out_of_range}, dropped_notes: [text], message?, notice, provider: {id, label, model, host}, …}` (the `AiAnswer` fields). **Local AI only** and its own consent purpose `labs`; never saves ("Lab report photos" below) |
| `GET /api/me/ai` | → `{enabled, settings, chat_enabled, trusted_saves_allowed, user_keys_allowed, allow_user_base_url, own: Provider \| null, shared: [{id, label, host, kind, policy, photos, usable}], routing: {mode, features: [{feature, label, role, route, available, reason, text, runs_on}]} \| null, presets, consents, daily_limit, remaining_today}` |
| `PATCH /api/me/ai` | any of `{opt_in, provider, share_age_sex, preferences, trust}` → the view above; a change of `trust` writes one `ai.trust_changed` activity row (so does `PATCH /api/me/settings` with an `ai` object) |
| `PUT /api/me/ai/provider` *(re-auth)* | `{preset, model, base_url?, vision_model?, api_key?, remove_key?}` → the view; `403` when personal providers are off; `api_key` write-only |
| `DELETE /api/me/ai/provider` *(re-auth)* | → 204 (`provider` falls back to `auto`) |
| `POST /api/me/ai/probe` | → `{probe}`: Test connection for the person's own provider (5 per hour; counted in the usage) |
| `GET /api/admin/ai-providers` | → `{providers: [Provider (+ `env`: `AI_PROVIDER` \| `AI_CLOUD_PROVIDER` \| null, `upstream`)], presets, private_hosts, deny_cidrs, proxy, env_provider, env_cloud_provider, writable, voice: {configured, enabled, host?, model?, key_set?, local?, daily_limit?, max_seconds?, max_bytes?, problem?}}` (the transcription server read-only; its key never) |
| `POST /api/admin/ai-voice/probe` *(re-auth)* | → `{probe: {ok, latency_ms} \| {ok: false, error, message}}`: one second of silence through the transcription transport (20 per hour with the other tests; 404 unless AI is on and `STT_BASE_URL` is set; the answer's text is neither returned nor kept) |
| `POST /api/admin/ai-providers` *(re-auth)* | `{preset, model, label?, base_url?, vision_model?, api_key?, timeout_s?, max_tokens?, context_tokens?, structured, reasoning_effort?, enabled}` → 201 `Provider` |
| `PUT /api/admin/ai-providers/{id}` *(re-auth)* | same body (+ `remove_key`) → `Provider`; `409` for an env provider (the message names `AI_PROVIDER` or `AI_CLOUD_PROVIDER`); a new host deletes its consents |
| `DELETE /api/admin/ai-providers/{id}` *(re-auth)* | → 204; `409` for an env provider |
| `POST /api/admin/ai-providers/{id}/probe` *(re-auth)* | → `{probe, provider}` (20 per hour; may show the first 300 characters of an error body, shared providers only) |
| `GET /api/admin/ai-routing` | → `{features: [{feature, label, sends, route, source, locked_by_env, allowed}], roles: {local, cloud: {id, label, host, private} \| null}, providers: [{id, label, host, private, role, photos, usable, locked, env}], env_role, env_cloud, as_before, defaults, writable}` |
| `PUT /api/admin/ai-routing` *(re-auth)* | any of `{photos, meal_ideas, describe: "local" \| "cloud" \| "off" \| "any" \| "local_then_cloud", chat: "local" \| "cloud" \| "off" \| "any", labs: "local" \| "off", local_provider, cloud_provider: shared provider id (0 clears)}` → the view above. `400 not_private` (a local AI must be a private host), `400 no_fallback` (`local_then_cloud` for `chat`), `400 local_only` (`cloud`, `any` or `local_then_cloud` for `labs`), `400 same_provider`, `404` (not a shared provider), `409 locked` (an env lock, or the env provider's role from `AI_PROVIDER_ROLE`), `403` with `AUTH_MODE=none`; each changed key is audited as `settings.changed` |
| `GET /api/admin/ai-quality` | → `{enabled, window_days: 14, last_calls: 20, min_calls: 8, warn_percent: 70, prompt_version, reports: {configured, readable, files, reports, ignored: {malformed, too_big, outside_folder, unreadable, over_limit}}, features: [{feature, label, route, provider: {id, label, preset, host, model}, live: {calls, window_days, counts: {usable, no_fit, unread, refused, dropped, invalid, error}, unusable, warn, summary, message}, evaluation: {state, warn, message, date, prompt_version, file, failed, role, upstream}}]}` (admins; read only; counts only, never content, a user or a path; a feature that is off or has no usable AI has no row) |
| `GET /api/admin/ai-usage` | `days` 1–366 (30) → `{days, usage: [{user_id, username, provider_id, key_scope, requests, prompt_tokens, completion_tokens}]}` (counts only, never content) |

```json
AiAnswer = {"status": "ok" | "refused" | "dropped_all" | "no_fit" | "error" | "not_a_label" | "unreadable" | "no_food" | "unsure",
  "message"?, "reason"? (error: a coarse category), "fallback"? (the rule result: {note, meals, foods}),
  "ideas"? | "order"? + "rest"? | "pick"? | "plan"? + "ai_picks"? | "items"? | "draft"?,
  "dropped": [{"index", "reason"}], "claims_corrected", "repaired", "retried", "trimmed",
  "feature", "mode", "provider": {"id", "label", "model", "host"}, "prompt_version", "audit_id", "cached", "notes"}
// "cached": true when next-meal reused the provider's answer to the same question from the last 10 minutes
// (note 06 §4.13; app/ai/cache.py): nothing sent, no daily call spent, the rules checked it again on the current
// day, and AI activity has a metadata-only row with status "cached" and verdict.cached_from = the original call.
Idea = {"source": "ai", "provider_label", "model", "checked": true,
        "notice": "AI idea · {label} · {model} · checked against your targets · not medical advice",
        "index", "theme": "light" | "hearty" | "familiar" | "new_idea", "title" (server template),
        "reason_codes": [code] (1–3, checked against the recomputed numbers), "why" (server template),
        "items": [FoodPortion], "totals", "score", "after": {nutrient: {"used", "left_today_after"}, "carbs_g": {"meal_after", "goal"}},
        "handbook": [{"slug", "title", "url"}] (≤ 2), "handbook_dropped"}
Provider = {"id", "scope", "preset", "label", "base_url", "host", "model", "vision_model", "timeout_s", "max_tokens",
            "context_tokens", "structured", "reasoning_effort", "locked", "enabled", "disabled_reason", "key", "policy",
            "kind", "photos", "probe": {"ok", "structured", "vision", "tools", "models", "warnings", "errors"} | null,
            "probed_at", "created_at", "updated_at"}
// GET /api/admin/ai-providers adds "role": "local" | "cloud" | null and "private_host": bool to each Provider
```

* **Instead of calling AI**, next-meal answers like guidance (`{status: "no_targets" | "disabled"}`), and a
  low treatment in swap mode or describe-a-meal text that may describe a low gets `{status:
  "treating_a_low", cards: [LowCard], ai_called: false}` (G7); red-flag symptoms get `{status: "red_flag",
  cards: [{title: "Get help now", …}], ai_called: false}` (G8). Describe-a-meal text that asks about a dose, a supplement amount, a
  lab result or a diagnosis (`features.medicine_question`: the Ask chat's `dose_reason`, then those words) gets `{status:
  "medicine_question", cards: [{title: "Ask your care team", …}], ai_called: false}` (G2, G3), also for a dry run; only when no low
  or red-flag card applies, so nothing sits beside a low's card.
* **Errors:** `503 {"detail", "reason"}` when no provider serves the person (`not_opted_in`,
  `not_configured`, `not_allowed`, `own_unavailable`, `own_key_unreadable`, `provider_disabled`,
  `hermes_tools`, `hermes_check_failed`, `context_too_small`, `vision_not_configured`, `plate_disabled`,
  `agent_not_allowed`, and from routing `feature_off`, `no_local_provider`, `no_cloud_provider`, `local_not_private`); `409 {"detail", "consent_required": true, "consent": ConsentRequest}` before the first
  call to a host for that purpose; `429 {"detail", "reason": "quota_exhausted" | "busy_person" |
  "busy_server"}` with `Retry-After`; photo uploads `413` (over `MAX_IMAGE_BYTES`, declared or streamed),
  `415 not_jpeg`, `422 truncated | malformed | unsupported | dimensions`, `408 upload_timeout` (the body
  took longer than 60 s). An upstream failure is `200`
  with `status: "error"` and the rule `fallback` for the meal features, and `502 {"detail", "reason",
  "audit_id"}` for photos. Reasons are coarse (`dns_failed`, `blocked_address`, `connect_failed`,
  `timeout`, `http_401`, `http_403`, `http_404`, `http_429`, `http_4xx`, `http_5xx`, `invalid_response`,
  `schema`, `no_json`, `empty`, `truncated`); upstream bodies are never echoed.
* **Dry run** (`?dry_run=true`, R9): `{dry_run, feature, mode, destination, host, provider, method,
  provider: {id, label, preset, scope, local}, headers (key shown as "[your key, not shown]"), body (byte-identical to what is sent; images as
  "[N base64 characters]"), image_bytes, images: [{image_sha256, bytes, width, height}],
  trimmed_candidates}`; it sends nothing, takes no quota and writes no audit row.

### Privacy tiers: roles and routing (ROADMAP "Privacy tiers", tier 1)

Code: `app/ai/routing.py`; the scope `local` in `app/ai/netpolicy.py` and `ProviderConfig.local_only` in
`app/ai/client.py`; the hooks in `app/ai/routes.py` and `app/vision.py`; the screen `js/views/ai_routing.js`. People and
operators: `docs/ai.md` "Which AI does each feature use?"; what goes where: `docs/privacy.md`.

* **Features and consent purposes.** `photos` (label, plate; purpose `photos`), `meal_ideas` (next-meal in every mode;
  purpose `text`), `describe` (parse-meal; purpose `text`), `chat` (Ask; purpose `chat`), and the local-only `labs` (a lab report
  photo; purpose `labs`; "Lab report photos" below). Consent stays per person,
  provider and purpose, so moving a feature to another provider asks again for that provider.
* **Settings** (instance scope; `app/settings_registry.py`, the twin `js/engine/settings.js` and
`tests/data/settings_vectors.json`): `ai.route.photos|meal_ideas|describe|chat` (`local` \| `cloud` \| `off` \| `any`, and for
  `photos`, `meal_ideas` and `describe` also `local_then_cloud` (tier 3, below),
  default `local`; env locks `AI_ROUTE_PHOTOS`, `AI_ROUTE_MEAL_IDEAS`, `AI_ROUTE_DESCRIBE`, `AI_ROUTE_CHAT`), `ai.route.labs`
  (`local` \| `off` only, default `local`, env lock `AI_ROUTE_LABS`) and
  `ai.route.local_provider`, `ai.route.cloud_provider` (a shared provider id, 0 = none; ids are never reused because
  `ai_providers.id` is `AUTOINCREMENT`). The environment provider `AI_PROVIDER` holds the role `AI_PROVIDER_ROLE` names and no other; the one `AI_CLOUD_PROVIDER` defines holds `cloud` and no other.
  All seven are in `NO_SIGNIN_ENV_ONLY`; Server settings shows a pointer for them (`ROUTING_GROUP`), the table is the
  place to edit.
* **Resolution** (`routing.resolve_feature(feature)`): AI off or not opted in as before; route `off` → `feature_off`
  for everyone (Ask: 404 through `require_chat_enabled`); the person's `own` provider, or route `any`, → `config.resolve`
  unchanged, **except for the local-only feature `labs`, which never takes that branch** (an own provider has role `own`; a shared one is annotated with the role it holds); route `local` / `cloud` →
  the shared provider that holds the role (`no_local_provider` / `no_cloud_provider` when none, `provider_disabled` when
  switched off or its key is unreadable). The result is a `config.Resolved` with `feature`, `route` and `role`; consent,
  quota (`ai_usage.provider_id`), the answer cache key, `ai_audit`, the dry run and "What will be sent?" all use its
  `cfg`.
* **Why "local" stays local.** `netpolicy.is_private_host`: an IP literal that is private and listed in
  `AI_PRIVATE_HOSTS`, or a name listed there by name and port (no DNS; a name resolving into a listed network does not
  count). A role `local` is refused by `PUT /api/admin/ai-routing` and by editing the provider's address when that
  fails; it is checked again at every resolution (`local_not_private`); and the call runs with `cfg.local_only`, which
  makes `net_scope` `local`: `check_url` requires a private host and `check_address` a private verdict for **every**
  resolved address, so a name that comes to resolve publicly is refused as `blocked_address`. Connection tests of the
  local provider (`routing.pin_if_local`) use the same scope.
* **Upgrade rule, no schema change.** `routes.startup` calls `routing.initialise` before the environment provider is
  synced and records the verdict in `meta.ai_routing_initialised`: a database that already has a shared provider
  gets `ai.route.*` = `any` for the features not locked by the environment (nothing changes until an admin chooses), except
  `labs`, which starts on `local`;
  a database with none keeps the defaults (`local`: off until a local AI exists). It runs once, so a provider added
  later never flips a new server to `any`. (A migration step was not used: the brief's step 15 would leave a gap
  below it while the voice step 14 is unmerged, and `app/migrations` refuses gaps.)
* **Not routed.** A person's own provider (their choice; `off` still applies; it never serves `labs`), the Assistant/MCP tools (they call no
  provider), and the admin's "Test connection" (it names the provider). **Voice** (`app/ai/voice.py`) is part of Ask, not a
  fifth feature: its recording goes to `STT_BASE_URL`, `voice_config` is `None` (404) while the chat route is `off`, the
  transcribe route resolves the `chat` feature, and the `voice` consent row (`ai_consents`, purpose `voice`, host = the
  transcription host) is keyed to the provider the chat route resolves to; `POST /api/ai/consent` with purpose `voice`
  therefore checks `provider_id` against the chat route, and moving Ask to another provider asks about voice again.

### Privacy tiers, tier 3: local first, cloud only when the local answer fails (route `local_then_cloud`)

Code: `routing.FALLBACK_ROUTE` / `FALLBACK_FEATURES` / `allowed_routes`, `Resolved.fallback` (`app/ai/config.py`),
`Prepared.cloud` and `features.judge_rejected` (`app/ai/features.py`), `routes.run_call` / `Attempt` / `_with_cloud` /
`dry_run_of`, `vision._vision_config`, `config.consent_request(fallback=...)` and `FALLBACK_RULE`. People and operators:
`docs/ai.md` "Local first, cloud only when the local answer fails"; what goes where: `docs/privacy.md`.

* **The route.** `ai.route.photos|meal_ideas|describe` also accept `local_then_cloud` (the type is `AiStructuredRoute` in
  `app/settings_registry.py`, mirrored in `js/engine/settings.js` and the vectors; `tests/data/gen_settings_vectors.py` adds
  `local_then_cloud` as a bad value for `ai.route.chat` and `ai.route.labs`). **Not** `chat` (several calls in a row; `plan`
  refuses it with `400 no_fallback`, the registry type, the settings route and the environment refuse it too) and **never** `labs`:
  `LOCAL_ONLY` and `LOCAL_ONLY_ROUTES` are unchanged, `allowed_routes("labs")` is still `("local", "off")`. Defaults (`local`),
  `initialise` (`any` for an upgraded server, `local` for `labs`) and every existing route are unchanged: nothing changes until
  an admin picks it.
* **Resolution.** `resolve_feature` resolves a `local_then_cloud` feature exactly as `local` (same reasons: `no_local_provider`,
  `provider_disabled`, `local_not_private`, the call pinned to scope `local`) and, only when that succeeds, looks up the shared
  provider holding the role `cloud` as `Resolved.fallback` (None when there is none, it is switched off, its key cannot be read, or
  it is the local provider). A person's own provider (or `any`) takes the old branch: no local first, never a fallback. So both
  roles are needed for the fallback; with no cloud provider the feature behaves as `local`, with no local provider it is off.
  `runs_on_text` reads "Runs on your local AI (host); if its answer fails the app's checks, on the cloud AI (host)."
* **Preparing both requests.** The prepare step builds the request for the local provider and, when `Resolved.fallback` is set,
  `Prepared.cloud`: the same prepare function called with the cloud `ProviderConfig`, so the cloud request is exactly what route
  `cloud` sends (its model or vision model, structured mode and prompt budget; the same data and photo). A cloud prompt budget the
  request does not fit, or a cloud provider with no vision model (photos), means no fallback for that request.
* **When the cloud is asked** (`run_call`, `Attempt.failed_checks`). After the local call: `result.status == "invalid"` (the
  validator rejected the reply after the one repair turn: no JSON, wrong shape, empty, truncated) or `result.status == "ok"` and
  `features.judge_rejected(verdict)` (`dropped_all`, or a food list whose items were all dropped by the text policy). **Not** for
  `error` (unreachable, timeout, `http_*`, `blocked_address`), a refusal (`refused`, or the model's own `no_fit`), a judge crash,
  nor when the local call never started (quota, busy, consent): those answer as with `local`. Then `_clear_fallback` requires the
  person's `ai_consents` row for the cloud provider, the **same purpose** and the current policy version (`no_consent` otherwise:
  nothing is sent), the Hermes tool check and one unit of quota (`quota_exhausted` or the tool-check reason otherwise). The second
  call runs inside the same concurrency slot.
* **Result.** `provider` names the AI that gave the shown answer. The cloud's answer is shown when it is usable (`ok` or
  `refused`, `Attempt.usable`); otherwise the local failure is shown. `cloud_fallback` is added to the answer only when the local
  answer failed the checks: `used`, `answered`, `reason`, `message` (the plain line), `local` and `cloud` providers, `local_audit_id`,
  `audit_id`, and for `no_consent` a `consent` request (with `as_fallback` and the rule) so the page can offer to agree. Photo
  routes answer a failure on both as `502` with the message appended to `detail` and `cloud_fallback` in the body. A usable cloud
  answer is kept for the 10-minute reuse under its own key (`_cache_key(..., fallback=True)`: the scope carries `:fallback`, so
  an answer the route `cloud` got is never shown as a fallback; `_kept_cloud_answer` shows it again only while the cloud consent
  stands).
* **Activity and quota.** Two `ai_audit` rows (the local one with `verdict_json.cloud_fallback` = `asked` or the reason it was
  not asked, the cloud one with `fallback_for` = the local row's id) and two quota units (`ai_usage` per provider).
* **Consent sheet and dry run.** `check_consent(..., fallback=cloud_cfg)` adds `consent.fallback` (the cloud provider's request,
  `given`, `rule`) to a `409 consent_required`; the cloud consent is requested but **not required** for the local call. The
  sheet (`askConsent`) names both hosts, states the rule and has its own tick box; `POST /api/ai/consent` accepts the cloud
  provider's id for the feature's purpose. `?dry_run=true` returns the local request and `cloud_fallback` (host, model, the second
  request's exact body, `consent` true/false/null, and the message "a second request with the same content may go to <host>,
  but only if the local AI's answer fails the app's checks"); nothing is sent by looking.
* **Frontend.** `js/views/ai_routing.js`: the column "Local, then cloud" (only where `allowed` has it), the one-line rule, the
  warning, the role hints; `personLines` adds, for a feature whose `route_view.fallback.given` is false, "Allow the cloud AI
  (host) as the fallback" (it opens the consent sheet with `fallback.request`, `as_fallback`). `route_view` always carries
  `fallback: {runs_on, rule, given, request}` for such a feature (and `consent` in the status endpoint). `js/views/ai.js`: `fallbackDryRun`, the consent sheet, `fallbackNotes` (shown by `droppedNotes`, so
  also in guidance's AI order, pick and plan, and by `js/scan.js` for a label), the activity row line.
* **Unchanged.** SSRF policy, scopes, auth, user scoping (consent and cache keys carry the person), what is sent (the cloud
  request is the one route `cloud` would send), `PROMPT_VERSION`.

### How well each AI is doing (`app/ai/quality.py`, `app/ai/eval_reports.py`)

Server administration → AI providers shows two signals per routed feature, from `GET /api/admin/ai-quality`; no table or schema step is added. **In use:** the
newest `LAST_CALLS` (20) rows of `ai_audit` for the feature (`AUDIT_FEATURES`), the provider it resolves to for a person on the shared AI
(`quality.routed_row`: the choice of `routing.resolve_feature` without a person or a keyring) and the model in use (the vision model for photos and lab
reports: that is the row's `model`), from the last `WINDOW_DAYS` (14) days, all people together; `cached` rows are not calls and are left out. Only
`status` and `verdict_json` are read. `quality.classify` reads a status per feature (`OUTCOMES`, from `routes._verdict_of`, `_finish_chat` and the judges)
as `usable`, `no_fit`, `unread`, `refused`, `dropped`, `invalid` or `error`; `routes._finish` keeps `verdict.shown`, the number of items offered for a
described meal or plate photo, so that an `ok` with every item dropped counts as `dropped` (rows from before have no `shown` and count by their status).
`MIN_CALLS` (8) calls with `WARN_PERCENT` (70) or more without a usable result is a warning; fewer calls give counts and no verdict. **Evaluation:**
`AI_EVAL_REPORTS_DIR` is read on every request and at start-up (at most 200 `*.json` files of 1 MiB, newest name first; a link is followed only to
a target inside the folder and opened with `O_NOFOLLOW`; anything malformed, too big, outside or not a plain file is counted, never fatal). A report
matches by `provider.preset`, the `host:port` of `provider.base_url`, `provider.model` and, for photos, `provider.vision_model`
(`provider.role` and `provider.upstream` are carried when present, never needed); only a report with `prompt_version == PROMPT_VERSION` can pass or
fail, an older one is `older`. Each feature is judged on the gates about it (`GATES_FOR`); `labs` is `not_covered` (the evaluation has no lab report
cases) and Ask needs a report run with `--chat`. `quality.log_startup` logs one `AI quality:` warning per routed feature whose state is `failed`, `none` or
`older`, only with the variable set and AI on. The demo and preview have no AI admin (`renderAdmin` shows a note), so there is no twin and no vector.
Screen: `js/views/ai_quality.js` (`KH.aiQuality`), mounted by `ai.js` under the routing table. People and operators: `docs/ai.md` "How well each AI is
doing".

### The call pipeline (`app/ai/routes.py` `run_call`)

Consent (per person, provider, purpose `text`/`photos`/`chat`, destination host and `POLICY_VERSION`) → a
concurrency slot (`ai.max_concurrency` on the server, one per person; refused at once with `429`;
`routes.ai_slot`) → the Hermes tool check inside the slot (≤ 5 minutes old for text, **before every
photo**; a failed check sets `disabled_reason` until a check passes) → the daily quota (`BEGIN IMMEDIATE`; shared keys only; probes
and photos count) → the call (at most one extra request: a retry after 429/5xx/connect errors or one
repair turn) → the judge (V3–V9; a judge error shows nothing) → an `ai_audit` row → a log line with
metadata only. Shared providers whose last test is missing or a day old are tested again in a
background task after the response (at most once an hour per provider; nobody's quota). With the route `local_then_cloud` the
steps from the tool check to the audit row run a second time for the cloud provider, in the same slot, only if the first answer
failed the schema or the judge and the person agreed to that host ("Privacy tiers, tier 3" above). AI routes are
`async`; their database work runs in the thread pool.

### Outbound HTTP (`app/ai/netpolicy.py`, `app/ai/transport.py`; note 04 R5, §9 A5)

Base URLs: `https` (or `http` only for an `AI_PRIVATE_HOSTS` entry), no user info, query or fragment, a
path of plain segments ending in `/v1` (≤ 100 characters), IDNA host, numeric hosts only as strict
dotted quads. Every request resolves the host again and checks **every** address (IPv4 inside IPv6
unwrapped, incl. NAT64 and IPv4-compatible): unspecified, multicast, broadcast, reserved, cloud metadata,
the Kubernetes API, `AI_DENY_CIDRS` and this server's own port on loopback are always refused; private,
loopback, CGNAT, ULA and link-local only for a shared provider listed in `AI_PRIVATE_HOSTS`; a person's own
URL must be https on port 443 to public addresses (off when `AI_HTTP_PROXY` is set). The connection goes
to the checked address with the original `Host` and SNI; redirects are errors; `trust_env=False`;
`Accept-Encoding: identity` and a cap of `AI_MAX_RESPONSE_BYTES` decoded bytes; the answer must be JSON;
total deadline = read timeout + 10 s. Images go only as `data:image/jpeg;base64,…`.

### Prompts, answers and the guard

The meal features send no free text to people (§9 A2; the Ask chat is the one exception, with its own checks in "Ask chat" above): an idea is `{theme, items: [{food_id (enum of the
candidates), quarters 1–12}] (1–5), reason_codes (enum, 1–3), handbook (enum of slugs, ≤ 2)}`; the server
checks every claim against the recomputed numbers and writes the title and sentence from templates
(`guard.THEME_TITLE`, `guard.REASON_TEXT`). A `low_*` claim holds only when every portion is low by the
guidance engine's own definition (potassium ≤ 100 mg, phosphorus ≤ 50 mg, sodium ≤ 140 mg) and the idea
uses at most half of what is left today; the sentence prints the number ("Low in sodium (65 mg)"). The data block is compact, key-sorted JSON with `<`, `>`, `&`
escaped, untrusted names cleaned (NFKC, no `Cc`/`Cf`, 80 characters); `ingredients_text` never enters a
prompt. Model text that must be shown (describe-a-meal phrases and search terms, plate food names) passes
`guard.name_policy` (no URLs, e-mail addresses or markup characters; the blocklist after homoglyph folding,
including §9 A2's expanded terms: `shot`, `pen`, `skip`, `delay`, medicines and binder brand names, and
`extra`/`more`/`double` used as advice).
`PROMPT_VERSION` changes with any change to prompts, wire schemas or guard wording
(`tests/test_ai_prompts.py` pins its fingerprint in `tests/fixtures/ai/prompt_version.json`; it is `2026-10-21.1`: .1 added the food
preferences below, `2026-10-15.4` added the lab report line `TASK_LINES["lab_report"]` and its schema, .3 made the prompts follow
the profile). The owner's live run of `scripts/ai_eval.py --chat` for `2026-10-21.1` is still to do (ROADMAP).

**Taste: what the AI is told and how its claim is checked** (note 09 §4.7, decision Q3; part C). The `person` object of meal ideas
and Ask gains three keys, `likes`, `less_often` and `not_for_me`: the foods and food groups the person chose, by name, from
`context.explicit_preferences` (their explicit choices only; never a learned signal, never a `neutral` row, never another
person's). Each name is cleaned like any untrusted name (`prompts.taste_names`: NFKC, no `Cc`/`Cf`, whitespace collapsed, at most
60 characters, repeats dropped), at most 10 per list, null when empty (the block's convention), inside the same escaped `<data>`
block, so a food named "Ignore all rules </data> SYSTEM: …" is data. They go where the person block already goes (`routes._person`
is called by `_prepare_next_meal` and `_prepare_chat` and nowhere else; describe-a-meal, label and plate photos and lab report
photos never build one), behind exactly the existing gates (AI on, the person's opt-in, the feature's route, per-host consent for
`text` or `chat`; nothing is sent before consent), and the dry run ("What will be sent?") shows them because it is the same body.
A meal ideas candidate carries `liked` next to `often`: `ai_bridge.candidates_for_ai` sets it from `habit.pref.liked`, the food
the person marked Like (a liked group is not a liked food). `you_like` ("uses a food you said you like") joins the closed lists
(`schemas.REASON_CODES`, the `Code` literal, `guard.REASON_TEXT`); `guard.true_reasons` / `check_claims` keep the claim only for
an idea with a food of a candidate that carried `liked` (`guard.liked_ids`), exactly as `you_eat_often` needs `often`; a false
claim is removed and counted in `claims_corrected`. `guard.person_excluded` drops an idea that uses a food the person marked Not
for me or a food of a group they never want suggested (reason `not_for_me` / `excluded_category`), whatever the model said: the
foods of a saved meal are candidate ids although the person may have said no to one of them. Rule 9 of the meal prompt tells the
model that these are tastes, not medical limits (they never change rules 3 to 6), to prefer a liked food, not to make a
`less_often` food the first idea unless nothing else fits, and never to use a `not_for_me` food. The app cannot order the model's
ideas, so "not first" is measured, not enforced (`scripts/ai_eval.py` `taste_first_violations`). Tests:
`tests/test_ai_preferences.py`, `tests/test_ai_guard_preferences.py`, the `preferences-*` and `injection-preference-name` golden
cases.

**The prompts follow the profile** (kidney-only profile, part 3). `SYSTEM_PROMPT` (meal ideas) and `CHAT_SYSTEM_PROMPT` (Ask)
are templates whose only profile-dependent part is `[[CONDITION]]`, filled by `system_prompt(person)` and `chat_prompt(person)`
from `prompts.condition_text(person)`, built from the `person` block (`person_block`) and only from whitelisted values
(`CKD_STAGES`, `DIALYSIS_TEXT`, `DIABETES_TEXT`; anything else reads as "not chosen yet" or a plain "diabetes"): "chronic
kidney disease (CKD, stage 4) and type 1 diabetes", "chronic kidney disease only (CKD, stage 3b)" for diabetes "none", and
"…; whether they also have diabetes is not chosen yet, so do not assume that they do or that they do not" when the type is
not chosen. **Everything else in the prompts is the same text for every profile, the low-treatment rules included** (the app
handles a low, a low is never questioned or delayed, the `hypo` purpose note of log_food): a person with "none" can still
have a low or log for someone who does. `TASK_SYSTEM_PROMPT` (describe a meal, label, plate photo) carries one fixed sentence
and no profile data. `person_block` sends null for a stage or diabetes type the person has not chosen (the stored defaults 3b
and type 1 are not their answer), and `targets_block(meal_carbs=False)` leaves out `carbs_per_meal_g` and `carbs_per_snack_g`
for "none". The pre-filters (`hypo.prefilter`, `features.red_flag`), the guard and the Ask chat's answer checks do not read the
prompt and are untouched; `tests/test_ai_prompts.py` fails if a profile changes more than the condition sentence.

### Photos (`app/vision.py`, `app/imagecheck.py`; note 03 R8, R9, §9 B1, B10; note 04 §9 A4)

One set of routes (`/api/vision/label`, `/api/vision/plate`; the lab report photo route is the one exception under `/api/ai`,
"Lab report photos" below). Off unless the
provider has a vision model; plate photos off unless `ai.vision_plate_enabled`; a Hermes provider only
with `ai.vision_allow_agent` **and** a passing tool check before every photo. The body is the raw JPEG
(`Content-Type: image/jpeg`, no multipart): `MAX_IMAGE_BYTES` from `Content-Length` and while streaming
(`app/security.py` gives `/api/vision` that limit), `FF D8 FF`, one SOF0/1/2 frame (8-bit, 1 or 3
components), 16–2048 px per side, aspect ≤ 4:1, ≤ 4 megapixels; APP1–APP15, COM and bytes after EOI
removed; only the rewritten bytes leave. Photos are never written to disk, stored or logged (the audit
copy keeps SHA-256, size and dimensions). **Nothing is read before the refusals that need no photo:**
switches → headers (415/413) → photo consent (409) → the person's and a server AI slot (429) → only then
the body, into one buffer within 60 s (408), held in that slot through the call; so the photos in memory
are bounded by `ai.max_concurrency`, not by open connections (the shipped profiles cap the container at
512 MiB).

### Lab report photos (`POST /api/ai/read-lab-report`; ROADMAP "Lab results from a PDF report", photo version)

Code: `app/vision.py` (`lab_router`, the route), `app/ai/lab_report.py` (the checks, pure), `features.prepare_read_lab_report`,
`schemas.lab_report_schema` / `LabReportAnswer`, `prompts.TASK_LINES["lab_report"]`, `routing` (`LOCAL_ONLY`), schema step 16;
browser `js/views/lab_photo.js` (`KH.labPhoto`), `js/engine/pdf_pages.js` (`KH.pdfPages`, a PDF's pages drawn on the device: "PDFs" below) and
`KH.views.labs.saveImported` (`js/views/labs.js`). People and operators:
`docs/ai.md` "Lab report photos"; what goes where: `docs/privacy.md`.

* **Local AI only (least trust).** A lab report can show a name, a date of birth, record numbers and a clinic, and the app
  cannot take them out of an image. The feature is the routed feature `labs` (consent purpose `labs`), whose setting
  `ai.route.labs` is `local` or `off` only (default `local`; `AI_ROUTE_LABS`; `cloud` and `any` are refused by the registry type,
  by `PUT /api/admin/ai-routing` and `PATCH /api/admin/settings` (`400`, "Input should be 'local' or 'off'"), by `routing.plan` (`400`, reason `local_only`) and by the environment, which stops the start).
  `routing.resolve_feature` skips a person's own provider and the rule `any` for a local-only feature, resolves it to the
  shared provider holding the role `local` (so `no_local_provider` when there is none: the feature is off and the status says
  "Needs a local AI on your own network, which is not set up on this server, so it is off."), and refuses a result that is not
  `role == "local"` with `cfg.local_only` (`local_not_private`). `prepare_read_lab_report` raises `LocalOnlyRequired` and
  `routes.run_call` answers `503 local_not_private` for any `Prepared.local_only` call on a provider that is not pinned, so the
  call uses the network scope `local` (every resolved address private at call time) however it was reached.
  `routing.initialise` starts `labs` on `local` (written out) even on an upgraded server whose other features start on `any`.
* **The request.** Raw `image/jpeg` body like the label route (no multipart, nothing spooled; `register_body_limit` gives
  `/api/ai/read-lab-report` the image limit), `?dry_run=true`. Order of refusals: sign-in `401` → AI off `404` → the `labs` route and
  the vision model `503` (`feature_off`, `no_local_provider`, `local_not_private`, `not_opted_in`, `not_allowed`,
  `vision_not_configured`, `agent_not_allowed`) → content type and declared size `415`/`413` → consent for `labs` `409` → the
  person's and a server AI slot `429` → only then the body (`408`), checked and rewritten by `imagecheck.check_jpeg` like every
  photo. The call counts in `ai.shared_daily_limit`. The photo is never written to disk, stored or logged; the dry run shows the
  destination (`provider.local` true) and `[N base64 characters]`, never bytes, takes the slot and no quota and writes no row.
* **The model only copies.** `TASK_LINES["lab_report"]` (with the unchanged `TASK_SYSTEM_PROMPT`) asks for the printed lines of
  the app's nine tests, in the codes of `app/units.py`, the number and unit exactly as printed, the date as printed or `null`;
  no judgement, range, flag, advice or identity. The answer schema is strict (`additionalProperties: false`, every property
  required): `{status: "ok" | "not_a_lab_report" | "unreadable", rows: [{analyte, value, unit, taken_on}] (≤ 60)}`; `analyte` is
  the nine codes or `other` on the wire and any short string in the answer model (so a backend that does not enforce the enum
  loses a line, not the answer).
* **The app decides** (`lab_report.judge`, pure; in this order per line): `analyte` not one of `units.ANALYTES` → dropped,
  `dropped.unknown_analyte`; `unit` not accepted by `units.canonical_unit_name` for that test (an empty unit too; nothing is
  guessed) → `dropped.unknown_unit`; the value fails the very validation of `POST /api/labs` (`models.LabCreate`: a
  non-negative number, converted, inside the plausible range) → `dropped.out_of_range`; a repeated line is one row. The unit is
  returned in the app's spelling (`µmol/L`) with `display` from `units.convert` ("1.2 mmol/L = 3.7 mg/dL"). The date is read
  only when it cannot mean two days (`YYYY-MM-DD`, month names, `d/m/y` or `m/d/y` when a part is above 12 or both are equal);
  otherwise, and for a date in the future or before 1900 (`models.validate_past_date`), `taken_on` is `null` with `date_problem`
  (`missing`, `ambiguous`, `unreadable`, `future`, `too_old`) and `date_note` (the app's sentence); the row is kept for the
  person to date. `printed_date` is echoed only if it is digits, month names and `/ . , : -`. **No text the model wrote reaches the person**: the test is a code the app labels, the value a number, the unit the app's
  spelling, the date a parsed day. The response is `{status: "ok" | "no_results" | "not_a_lab_report" | "unreadable", rows,
  dropped: {unknown_analyte, unknown_unit, out_of_range}, dropped_notes: ["3 lines were not recognised: …"], notice: "Read by AI
  from your photo. Check each value against the report before you tick it.", provider, …}`; `502` for an answer that fails
  the schema after the one repair.
* **Consent.** Purpose `labs` (schema step 16), keyed to the local provider and its host and `POLICY_VERSION` like the others;
  `POST /api/ai/consent` with `labs` is `409` for any provider but the one the `labs` route resolves to. The consent request
  carries `notice` (`config.labs_notice(host)`): the photo is sent to <host> (your local AI, on your own network) to read the
  results; the report may show your name, date of birth and record numbers and the app cannot remove them from a photo, so crop
  it to the results table; the photo is not kept; every row starts unticked and nothing is saved until the person ticks it and
  presses Save.
* **Nothing is kept.** The AI activity row (`feature` `read_lab_report`) has the request with the photo replaced by its SHA-256,
  size and dimensions (the prompt text is fixed) and **no copy of the model's answer** (`Prepared.keep_response = False`, even
  with `ai.audit_retention_days > 0`); the verdict holds the counts. The answer cache never holds it (`_cache_key` is for next-meal
  only). The log line has feature, provider, model, host, latency, tokens and status only.
* **Nothing is written by this route.** A saved result is the person's tick and the ordinary `POST /api/labs/import`
  (`LabImport`, each row checked again like `POST /api/labs`, duplicates skipped, the potassium alert returned as for a CSV file).
* **Browser.** The card `#lab-photo` ("Read a lab report photo or PDF") in the Labs view (below "Import from a spreadsheet") is hidden unless `GET /api/ai/status`
  says `features.lab_report`; with AI on but the feature unavailable it shows only the server's sentence (`routes.labs.text`; the
  person not opted in; a local AI without a vision model); with AI off, and in the demo and preview, it is not there at all
  (`js/mock/ai.js` answers every `/api/ai/*` route `404`). The photo is redrawn on the device (`KH.ai.prepareJpeg`), sent through
  `KH.ai.withConsent('labs', …, 'labs')` and `KH.ai.uploadPhoto('lab-report', …)`; "What will be sent?" is the dry run. The result is
  drawn with the CSV import's table (same classes, `lab-photo-list` besides), **every checkbox unchecked**, the notice line and
  the dropped counts above it; a row without a date shows a date input and its checkbox is disabled until a valid date
  (1900-01-01 to tomorrow) is entered (clearing it unticks the row); "already saved" marks a result with the same test, date and
  shown value. Save sends only the ticked rows through `KH.views.labs.saveImported` (the CSV import's own save: `POST
  /api/labs/import`, counts, refusals, the potassium banner, "what this changed"). Everything from the server is set with
  `textContent`; the photo is held in memory until Save or Discard. `tests/js/lab_photo_page.mjs` runs the file against a fake page.
* **PDFs (design note 13; `js/engine/pdf_pages.js` = `KH.pdfPages`, the page list and the page-by-page reading in `js/views/lab_photo.js`).** The
  PDF a lab's website hands out is chosen in the same card (the input takes `image/*,application/pdf,.pdf`), opened and drawn **on the device**,
  and read one page at a time through the route above exactly as a photo is. **The server never receives or parses a PDF**: no route, setting,
  migration or server code changed, `local_only=True` stands, and each page is one checked JPEG request like any photo.
  * *Reading the file* (`KH.pdfPages.open(file, {maxBytes, maxPages, signal})`). At most **20 MiB** (checked from `file.size` before the file
    is read) and **50 pages**; the first five bytes must be `%PDF-`. The vendored pdf.js is loaded with a dynamic `import()` only when a PDF is
    chosen and runs in a module Web Worker that `pdf_pages.js` makes itself: `GlobalWorkerOptions.workerPort` is set first, then
    `getDocument({data, isEvalSupported: false, enableXfa: false, disableAutoFetch: true, disableStream: true, disableRange: true,
    stopAtErrors: false})` and nothing else: no `url`, `cMapUrl`, `standardFontDataUrl`, `iccUrl`, `wasmUrl`, `password` or `onPassword`, so nothing
    is fetched (fonts the PDF does not embed fall back to the browser's; JPEG 2000 and JBIG2 images and ICC profiles are not decoded, because
    no WebAssembly decoder is vendored; a scan made of such images can draw blank). Against pdf.js 6.4.299 `isEvalSupported` is gone (the
    library has no eval path left; the option is passed anyway, harmlessly) and `render()` takes `canvas` (the old `canvasContext` is deprecated).
    A password-protected file is refused (`PasswordException` → `password`); the app never asks for a password. Error codes: `too_big`, `not_pdf`,
    `password`, `damaged`, `too_many_pages`, `browser`; Cancel is `AbortError`. `render(n)` draws a white page with no annotations, form fields or text
    layer at the largest scale that keeps the longer side at most 2048 px and the area at most 4 MP (`app/imagecheck.py`'s limits; never above
    4× the page's size, at least 16 px a side), as a JPEG (quality 0.9) that the view passes to `KH.ai.prepareJpeg` (the photo helper: redrawn on
    the device at most 1600 px on the longer side, no camera data). `close()` destroys the pdf.js task and terminates the worker.
  * *CSP and Trusted Types.* The page's policy gained one name and nothing else: `trusted-types kh-sw kh-xml kh-pdf`. `kh-pdf` is created once, in
    `pdf_pages.js` only, never as a default policy and never allowed twice; its `createScriptURL` returns its input only when it is exactly
    `/vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs` and throws for anything else, and the one `new Worker(...)` (a Trusted Types sink) is called
    there with its output. `script-src 'self' 'wasm-unsafe-eval'` and `worker-src 'self'` are unchanged: no `'unsafe-eval'` (CVE-2024-4367, pdf.js
    before 4.2.67, ran font code through `new Function`; this CSP would refuse it and 6.4 has no such path), no `blob:`. With a port pdf.js makes no
    worker of its own and has no main-thread "fake worker" to fall back to; the module also checks that pdf.js posted to its worker before it hands
    over any bytes, and refuses (`browser`) if it did not, and when the worker fails to start (it only fires `error`). Without Trusted Types
    (an older browser) the URL string is used. `tests/test_frontend_shell.py` allows exactly three files to create a policy (`pwa.js`: `kh-sw`;
    `ccda_labs.js`: `kh-xml`; `pdf_pages.js`: `kh-pdf`), each named in the comment above the directive in `app/security.py`, and one `Worker`
    constructor; `tests/test_security.py` pins the whole string.
  * *Vendored files and the service worker.* `scripts/vendor_barcode.py` vendors both groups (the barcode decoder and pdf.js; `--only barcode`
    or `--only pdfjs`; the weekly `--check-latest` covers both): `pdf.min.mjs` and `pdf.worker.min.mjs` from the **`legacy/build`** of `pdfjs-dist`
    6.4.299 (the default build is "intended for the latest browsers" and calls `Promise.try`, `Math.sumPrecise` and `Uint8Array.fromBase64` without a
    polyfill; the evidence is in `app/static/vendor/README.md`) and its `LICENSE`, pinned by SHA-256, the npm tarball checked against its
    `dist.integrity` first. `tests/test_vendor.py` pins them and checks that neither file has an `eval`, a source-map comment or an address it
    fetches, that main file and worker name one version, and that `getDocument` still takes every option the page passes. `sw.js` precaches
    `js/engine/pdf_pages.js` but not the 1.8 MB of pdf.js: the first PDF fetches both files and the existing runtime rule for `/vendor/` (the one
    the barcode WebAssembly uses) keeps them.
  * *The screen.* A PDF pick opens the file here (nothing is sent) and lists "Page 1" … "Page N": pages 1 to 6 start ticked and at most 10 can be
    ticked ("Reading a page takes a while on your own AI; choose the pages with results."), with the line "Each page you tick is drawn on this
    device and sent as a picture; the PDF file itself is not sent." (also added to the consent sheet's notice before it is drawn). "Read the
    report" goes through the ticked pages in order: draw, redraw as a photo, `KH.ai.withConsent('labs', …)` and `KH.ai.uploadPhoto('lab-report', …)`
    for that page alone (so the photo's consent and, if the person asked for it, "What will be sent?" apply to each page), "Reading page 2 of 4…",
    and Cancel, which stops between pages and aborts the request in flight (`uploadPhoto` takes an `AbortSignal`). The rows of all pages are one review
    table, every row unticked and saying which page it came from; a row the same as an earlier one (test, value, unit, date) is shown once, with the
    first page's number. A page that fails ("Page 3 could not be read: …": the route's own message, or that it could not be drawn) or has no result
    ("Page 2: …", the route's sentence) is a line and the other pages still count; a refusal that would repeat for every page (offline, signed out,
    `403`, `404`, `429`, `503`) stops the run and says so. Save sends only the ticked rows through `saveImported` ("saved from your PDF"). The messages
    for a file that cannot be used are fixed sentences in `lab_photo.js`. The pdf.js document and its worker are closed as soon as a run ends (the
    chosen file stays chosen), and the PDF, its pages and the document are let go on Discard, Save and a new pick; nothing is stored, and the browser
    asks no other host (`tools/e2e/lab_pdf.py` checks the requests, the Worker, the CSP report and the service worker's cache).
* **Tests.** `tests/test_lab_photo.py` (routing, consent, filters and counts, "same validation as POST /api/labs", dates, nothing
  written, nothing kept, two people), `tests/test_migration_m016.py`, `tests/test_lab_photo_ui.py`, the golden category `lab_report`
  (`tests/ai_golden/lab-report-*.json`; `scripts/ai_eval.py` skips them: they are local-only). For a PDF: `tests/test_pdf_pages.py` (the module in
  Node against a fake pdf.js, `tests/js/pdf_pages_page.mjs`: the exact `getDocument` options, `workerPort` before `getDocument`, the policy, the
  scale for Letter, A4, a receipt and a tiny page, every error code, `close()`, Cancel), `tests/test_lab_photo_ui.py` with
  `tests/js/lab_photo_page.mjs` (the page list, one request a page, the merge, failures, messages, release), `tests/test_vendor.py`, and the
  browser walk `tools/e2e/lab_pdf.py` (a two-page PDF from a tiny PDF writer, through the server with a fake local AI, real Chromium).

### Ask chat (assistant step 2, parts A and C)

Spec `docs/dev/plans/assistant-step2.md`; code `app/ai/chat.py` (pure but for the callbacks the route gives it),
`ChatStep` and `chat_step_schema` in `app/ai/schemas.py`, the chat prompt in `app/ai/prompts.py`, `POST /api/ai/chat` in
`app/ai/routes.py`, schema step 12; the screen `js/views/ask.js` ("Frontend" below); people: `docs/assistant.md` "The Ask
screen", `docs/ai.md`, the handbook's AI page; tests `tests/test_ai_chat.py`, `tests/test_ai_chat_checks.py`,
`tests/test_migration_m012.py`, `tests/test_ask_ui.py`. The chat reuses, and never copies, the AI client
(`complete_json`: one repair turn), the concurrency gate, the quota, the consent flow, the activity log and the step-1
tool functions of `app/mcp/tools.py`.

* **Request.** `{"messages": [{"role": "user" | "assistant", "text": 1–2000 characters}]}`: 1 to 20 items, the last from
  the person. The conversation is kept only in the page; the server stores no transcript. `?dry_run=true` returns the
  first model request exactly as it would be sent (`{dry_run, feature: "chat", destination, host, provider, headers,
  body, …}`), takes no quota and writes no activity row. A body that does not fit is `400` like every other body.
* **Checks, in order.** Signed in (401) → `ai.enabled` (404 `Not Found`) → `ai.chat_enabled` (404, before the body is
  read) → the body → **the rules** (below; no provider is looked up, no consent or quota is needed) → a provider serves the
  person (503 with the reasons of the other features, `not_opted_in` first) → the dry run → consent for purpose `chat`
  (`409 consent_required` with the sheet's text) → the person's single slot and the server's slot (`429 busy_person` /
  `busy_server`) → the Hermes tool check → the loop. A first model call refused for quota is `429 quota_exhausted`.
* **Rules first, every message.** The `safety_check` tool function (step 1) runs on the newest message: emergency wording
  → `kind: "get_help_now"` with the Get help now card (its link `/learn/get-help-now/`); low wording → `kind: "treat_low"`
  with the Treating a low card (the person's own `hypo_dose_g`) and the text "Treat the low first. When you feel better, ask
  again."; both → `get_help_now` with both cards. `ai_called` is false, `label.source` is `app`, and nothing is spent or
  logged. A message that matched a rule, and the answer after it, is left out of the history sent to the model on later
  turns. Nothing in the chat warns against, delays or questions a low treatment.
* **Answer** (`label` after V9): `{feature: "chat", kind, text, cards: [{title, lines, handbook, url}], numbers:
  [{title, rows: [{label, value, detail}]}], notes: [str], label: {source: "ai" | "app", provider_label, model, checked,
  notice}, provider: {id, label, model, host} | null, ai_called, model_calls, tool_calls, prompt_version, audit_id, trust,
  pending_save, saved: [card], questions: [{food, question}]}` (the last four: "Saving from the chat"). `kind`:
  `answer` (a checked answer), `withheld` (the dose or number check failed; `text` is the fixed sentence), `unfinished`
  (the step limit or the quota ended the loop, or the conversation no longer fit the prompt budget; the text is "The
  assistant could not finish; here are the app's numbers."), `error` (the provider failed or refused; the sentence of the
  other features), `confirm_save` (ask mode: the model asked to save and the card in `pending_save` waits for the person's
  Save), `treat_low`, `get_help_now`. `cards` is a list because a message may need both cards.
* **The loop** (`chat.converse`; not provider-native tool calling, so it works with every provider). Each step the model
  returns exactly one JSON object, `{"call": {"tool", "arguments"}}` or `{"answer"}`, validated by `ChatStep`
  (`extra="forbid"`; one repair turn inside `complete_json`). Allowed tools: `get_today`, `search_foods`, `check_meal`
  run for the person through `app.mcp.tools.run` in the thread pool and put into the next request as a labelled, cleaned,
  escaped data block; since part C the model may also call `log_food`, `save_recipe` and (food preferences) `set_food_preference`,
  which `run_save` handles ("Saving from the chat" below), and never `safety_check`. An unknown tool or bad arguments are told to the model
  (it counts toward the limit) and it may try again. At most 6 tool calls; after the sixth result the model is told to
  answer, and a call after that ends the loop as `unfinished`. So a message makes at most 7 model calls. Each model call
  takes one unit of the person's quota (a quota that runs out after the first call ends the loop as `unfinished`), the
  provider's timeout and one `ai_audit` row (`feature: "chat"`; **no request or response body and no message text**,
  whatever `ai.audit_retention_days` says; the verdict names the step, the tool and the outcome). JSON mode: a provider
  in `json_schema` mode is asked for `json_object` (free-form arguments cannot be a strict schema); the protocol and its
  schema are in the system prompt in every mode. History that does not fit `context_tokens` is trimmed from the oldest end;
  not even the newest message fitting is `503 context_too_small`.
* **The prompt** (`PROMPT_VERSION` 2026-10-21.1; .1 added the "Tastes" paragraph of rule 10 and the `set_food_preference` tool, see "Saving from the chat"; 2026-10-15.4 only added the lab report line, which Ask does not use; .3 words the person from the profile, see "Prompts, answers and the guard"; .2 added the saving tools and rule 10, which allows a save only when the person
  asked in the conversation and forbids saying anything is saved unless a tool result says `"saved": true`): the rules (every number from a tool, null is unknown and not zero, fetch
  again each turn, no insulin or medicine doses, no medicine advice, no lab interpretation, a plain warning and "check with
  your care team" for salt substitutes, anti-inflammatory pain medicines and big protein or fluid changes, short plain
  words), the step schema, the tools with their argument schemas read from the step-1 tools (`chat_save.tool_schemas()`; the
  schema of `set_food_preference` is `chat_preference.INPUT_SCHEMA`), and the person block
  of the other prompts (stage, dialysis, diabetes, preferences, the foods and groups they marked Like, Less often and Not for
  me, age band and sex only with `share_age_sex`; the user id
  is the keyed hash of the other features). Never the name, user name, e-mail, weight, height, exact age or notes, and never a
  learned signal.
* **The checked answer** (the chat's V6, `chat.check_answer`, in this order): the *text policy* (NFKC, `Cc`/`Cf` removed with
  line breaks kept, links and e-mail addresses removed except the app's own `/learn/...` paths, cut at 1200 characters at a
  sentence end; nothing left is `kind: "error"`); the *dose check* (insulin, bolus, basal, correction and carbohydrate
  ratios, dose/dosing/dosage, `N units`, the binder names of `guard.MEDICINE_NAMES`, advice to skip, delay or change
  insulin or medicine, and a sentence about a low blood sugar that also restricts, delays or avoids something) →
  `withheld` with "This answer was not shown because it touched on medicine or insulin doses. Ask your care team about
  doses."; the *number check* (every number with a unit of mg, mcg, g, ml, l, kcal, kJ, % or their spelled-out forms must equal,
  at the precision shown, a number in this message's tool results, including numbers inside their text, or in the
  person's own messages; thousands separators are read, no units are converted, "per 100 g" is a basis; numbers without such a
  unit pass) → `withheld` with "The assistant's answer had a number the app did not work out, so it is not shown. Here are
  the app's own numbers."; then *lab words* (eGFR, creatinine, A1c, "blood potassium", "lab result" ... in the answer or the
  question) add the note "Lab results are for your care team to interpret." to `notes`. A withheld answer keeps `numbers`.
* **`numbers`** ("From the app"): what this message's tools returned, formatted by the server: the day's figures with
  target and what is left (`get_today`), a checked meal's totals and the day with it (`check_meal`), and foods found with
  their potassium, phosphorus and sodium per serving (`search_foods`); the latest look-up of each kind, at most four groups.
  Unknown is shown as "not listed" and a total with unknown parts as "… or more", never as 0.
* **Consent purpose `chat`** has its own "What will be sent?" text (`js/views/ai.js`): the messages in this conversation
  and the app's own numbers the assistant looks up (targets, totals, food names and nutrients); never the name, user name,
  e-mail, weight, height, exact age or notes; each question can take several AI calls. Once per provider and host, like
  `text` and `photos`.
* **No new clinical numbers.** The chat adds no threshold of its own; every figure it shows is a tool result. Its limits
  (20 messages, 2000 characters, 6 tool calls, 1200 characters of answer) are sizes of the conversation.

### Saving from the chat (assistant step 2, part C)

Spec `docs/dev/plans/assistant-step2.md` "Part C"; code `app/ai/chat_save.py` (the database-facing half), `run_save`,
`SaveStep` and the loop changes in `app/ai/chat.py`, `AiPreferences.trust` and `ai.allow_trusted_saves` in
`app/settings_registry.py`, `app/mcp/tools.py` (`Asker`), `app/mcp/request_keys.py`, schema step 13; the screens
`js/views/ai.js` (the choice and the warning sheet) and `js/views/ask.js` (the cards); people: `docs/assistant.md`, `docs/ai.md`,
the handbook's AI page; tests `tests/test_ai_chat_save.py`, `tests/test_migration_m013.py`, `tests/test_ask_ui.py`. The
owner's words: "I want to have a few options to 'trust AI' or not, so I don't have to babysit it by confirming every response.
I would like this to be a toggle with a warning." Least trust is the default. **One tool is the exception to the trust
setting: `set_food_preference` is always a card** (the last bullet, "Tastes").

* **Two switches.** The admin's `ai.allow_trusted_saves` (default off) and the person's `trust` (`ask` default, `conversation`,
  `always`; a field of the `ai` setting, so no column). `chat_save.effective_trust`: `ask` unless the admin switch is on **and**
  the person chose it; `always` is the stored choice alone; `conversation` also needs the chat request to carry `trust:
  "conversation"` (the page says so only while the person has trusted this conversation: it ends with New conversation, a
  reload and 12 hours, all page memory, nothing stored). A page claiming more than the stored choice gets `ask`; the body
  refuses `trust: "always"` (400). Turning the admin switch off ends trusted saves at once (the stored choice is kept and
  applies again when it is switched on). Every change of the choice, from `PATCH /api/me/ai` or `PATCH /api/me/settings`,
  is one `ai.trust_changed` row (`old`, `new`) in the person's own activity (`config.audit_trust_change`); an unchanged
  value writes none. Choosing `conversation` or `always` in Settings opens the warning sheet first ("The assistant will save
  food and recipes without asking you first. It can pick the wrong food or the wrong amount. Every number still comes from the
  app. The low and emergency rules and the dose checks always stay on. You can undo each save, from the chat or from Today.
  Photo and label readings are always shown to you to check first."; the focus starts on "Keep asking me").
  The stored choice is not reset when the AI provider changes or a consent is withdrawn (withdrawing the `chat` consent stops
  Ask altogether).
* **Residual risk, not closed in code.** A food name from USDA or Open Food Facts reaches the model as untrusted data (cleaned,
  cut, escaped and marked as data), and in a trusted mode a prompt injection could still make the model ask for a save. What limits
  it: both trusted modes are off by default and behind an admin switch and a warning, at most 2 saves a message, all or nothing,
  Undo on every save, the activity row, the app's own numbers (the model cannot choose a nutrient value), and the prompt rule that a
  save follows the person's own request. That last rule is prompt-only: a code check for "the person asked to log" would be a
  brittle word list. `scripts/ai_eval.py --chat` has an injection attempt among its questions and checks that logging a banana comes back as a card with nothing saved; it needs a live model (the owner's run).
* **What the model may call.** `log_food` and `save_recipe` with the MCP tools' own arguments (`CH.OFFERED_TOOLS`); the system
  prompt shows their schemas without `request_key`, and a `request_key` the model sends anyway is dropped: the app makes the
  key. And `set_food_preference` (below). At most `MAX_SAVES` (2) save calls per message, a taste included, each also a tool
  call of the 6. `run_save` refuses outright when the newest message matches a safety rule (it never gets that far: the rules
  answer first and the model is not called).
* **Ask mode.** The save call is **not executed**. `chat_save.propose` validates the arguments like the tool does, places
  the items with `place_items` and writes nothing (no entry, no meal, no food, no key). The loop ends at once:
  `kind: "confirm_save"`, `text` the fixed sentence "Nothing has been saved yet. Check this, then press a Save button, or
  Cancel.", and `pending_save`: `{tool, date, meal, status, purpose, items: [{name, brand, as_asked, servings, grams, food_id,
  fdc_id, new_food, counted_as_treating_a_low}], imports: [fdc_id], numbers: [{title, rows}], payload}`; `payload` is the
  exact body of the normal route (`POST /api/log/batch` `{entries: [...]}` with a stable `client_id` per entry, or `POST
  /api/meals` `{name, note, items}`). The page posts it with the status the person chose (Save as eaten / Save as planned; the
  model's choice is the primary button) through the shared API object with the CSRF header, like any save; a USDA food not in
  the person's list yet is first added with `POST /api/foods/usda/import`. An item the app cannot place gives no card: `questions`
  (the app's own words, `chat_save.person_questions`) and the model is told as the tool tells it.
* **Trusted mode** (`conversation` or `always`, switch on). `chat_save.save_now` runs the MCP tool with `request_key =
  "<request_id>-<n>"` (`n`: the save's number in this message; no `request_id` from the page: a random one). The tool's own code
  does the rest: all or nothing in one transaction (`write_once`; USDA foods added in it), and the key is written inside it.
  Activity rows are the MCP ones (`assistant.food_logged`, `assistant.recipe_saved`) with `via: "Ask"` (`tools.Asker`; never
  a token name; a food save has no target). The answer's `saved` holds one card per save: `{tool, date, meal, status, items,
  numbers, added_to_foods, duplicate, undo: {entry_ids} | {meal_id}}`, built from the tool's own answer (read back from the
  database). **Undo** is the page calling `DELETE /api/log/{id}` for each id (or `DELETE /api/meals/{id}`): the normal routes,
  scoped to the person, so another person's id is a 404; USDA foods a save added stay in the list. A withheld, unfinished or
  failed answer keeps its `saved` cards. The tool result the model sees is the MCP result; numbers in it are in the number
  check's pool (`entry_id`, `entry_ids` and `meal_id` are not figures).
* **A request sent twice saves once.** The key lives in `assistant_ask_keys` (schema step 13) as the SHA-256 of the person's id and
  the key; `request_keys.find` / `remember` take `token_id=None` for it. A repeat answers with what the first save made, read from
  the database again (`duplicate: true`, the card still has Undo), and the model is told it may not save again in that
  message (`SaveStep.closes`; its note without the "send a new request_key" advice). The page keeps the `request_id` of a send
  that got no answer and reuses it when the same text is sent again. Keys older than 24 hours are ignored and purged with
  step 11's.
* **Unchanged in both modes.** `purpose: "hypo"` is saved like any other and no card or message warns about it; the dose and
  number checks run on the model's text; photo and label readings are not touched (trust never covers them); the activity log
  of model calls still holds no message text (its `tool` is now `log_food` / `save_recipe` and its outcome may be
  `confirm_save`); the MCP server and tokens are unchanged (their confirmation is a prompt instruction; the trust setting
  applies to the Ask screen only).
* **Tastes: `set_food_preference` is always a card** (note 09 §4.8, decision Q2; `app/ai/chat_preference.py`, tests
  `tests/test_ai_chat_preference.py`, `tests/test_ask_taste_ui.py`). Arguments `{food_id | category, preference: like | less |
  not_for_me | clear}`, exactly one of `food_id` (a food the person may use, normally from a `search_foods` result; another
  person's or an unknown id is "not one of the person's foods") and `category` (one of the person's food groups,
  `foods.visible_categories`; matched ignoring case and spacing). Whatever the trust setting: `run_save` hands the call to
  `chat_preference.propose` before it looks at the mode, `effective_trust` decides nothing for it, `save_now` raises for it, and
  `propose` writes **nothing** (no preference, no setting, no key, no audit row). The loop ends with `kind: "confirm_save"`, the
  fixed text "Nothing has been remembered yet. Check this, then press Remember, or Cancel." (`CONFIRM_PREFERENCE_TEXT`) and
  `pending_save` `{tool: "set_food_preference", target: {kind: "food", food_id, name, category} | {kind: "group", name},
  preference, previous, previous_source, payload}`: `previous` is the state now (`none | like | less | not_for_me | neutral` for
  a food, without `neutral` for a group), `payload` for a food is `{preference, source: "ask"}` (null for `clear` and for a
  group). A request that changes nothing (already so; `clear` with nothing saved; `clear` over a `neutral` row, which is not a
  taste and stays) gets no card: the model is told `saved: false, changed: false`. A full list (1,000 preferences, 500 Not for
  me, 50 food groups per list) is told to the model, not offered as a card. On **Remember** the page (not the model) reads the
  current state and applies it through the normal routes: a food `PUT /api/guidance/preferences/{food_id}` (`clear` =
  `DELETE`); a food group `GET /api/me/settings`, move only that group among `like_categories`, `less_categories` and
  `exclude_categories`, `PATCH /api/me/settings` with the whole `guidance` object (`js/core.js` `api.foodPreferences`,
  `setFoodPreference`, `clearFoodPreference`; `ask.js` section "tastes"). **Undo** puts back exactly the state it read when
  Remember was pressed, from the same source (a group is read again then, so another edit stays). Afterwards the page
  forgets the guidance screens' remembered answers. The card's words are the app's own ("Remember this for your suggestions?
  Salmon: less often." with Remember and Cancel; a group is "Fish & Seafood (food group)", Not for me on a group is "never
  suggest"), with the line that less often and not for me are tastes, not an allergy filter. The tool is **not** in
  `app/mcp/tools.py`: an assistant connected with a token gets the same-named MCP tool only with the separate scope
  `assistant:prefs` ("Remembering a taste" under "Assistant MCP server"; `app/mcp/preference_tool.py` reuses this module's checks),
  and a token's tool never changes Ask, which stays a card (`tests/test_ai_chat_preference.py`). Rule 10 of the Ask prompt
  names it: only when the person states a taste in this conversation, never inferred from what they log or ask, never claimed
  as remembered, never for an allergy. The model never sees a learned signal (the person block holds explicit choices only).
  The rule-based answers for a low or an emergency run before any model and read no preference; nothing here touches
  `hypo.prefilter`, the Treating a low card, its options or its swaps.
* **Frontend.** Settings → AI ideas shows the choice (three radios, "Ask me before every save (recommended)" first; the two others
  disabled with a note while the admin switch is off) only while `ai.chat_enabled` is on. The Ask screen shows one line (what
  is in force, and the admin's switch when it is off), "Change this in Settings", and, for a person who chose `conversation`,
  "Trust it for this conversation" / "Stop trusting". Cards are built with `h()` text nodes only.

### Voice input (assistant step 2, part B)

Spec `docs/dev/plans/assistant-step2.md` (part B); code `app/ai/stt.py` (pure), `app/ai/voice.py` (the route), the screen part
`js/views/ask-voice.js` and `css/ask-voice.css`, the consent text in `js/views/ai.js`, schema step 14; people: `docs/ai.md`
"Voice input", `docs/assistant.md`, `docs/privacy.md`, the handbook's AI page; operators: `docs/deployment.md`,
`docs/network-allowlist.md`, `deploy/compose.stt-whisper.yaml`; tests `tests/test_ai_voice.py`, `tests/test_migration_m014.py`,
`tests/test_ask_voice_ui.py`, `tests/test_deploy_stt.py`, and the Chromium harness `tools/e2e/ask_voice.py`.

* **One provider, chosen by the admin, never by the browser.** The page records with `MediaRecorder` and the app forwards the
  clip to **one OpenAI-compatible transcription endpoint**: `POST {STT_BASE_URL}/audio/transcriptions` (so
  `STT_BASE_URL` ends in `/v1`, like `AI_BASE_URL`), multipart with `model` (`STT_MODEL`), `response_format=json` and `file`
  (the app's own file name and type, never the browser's). A local Speaches or whisper.cpp-style server and the cloud services
  (OpenAI, Groq) all speak it. **The browser's own speech recognition is never used**: Chrome sends that audio to Google
  and Safari to Apple, outside the owner's control (a static test fails if any shipped file names it). Environment only:
  `STT_BASE_URL`, `STT_MODEL`, `STT_API_KEY[_FILE]` (optional; redacted in logs, never returned by any API: the admin view
  says only `key_set`), `STT_TIMEOUT_S` (60), `STT_DAILY_LIMIT` (100 recordings per person per day, 0 = unlimited),
  `STT_MAX_AUDIO_BYTES` (1.5 MiB; the body limit of this exact path, `register_body_limit`). The admin switch
  `ai.voice_enabled` (default off) must be on, and `ai.chat_enabled` too (the microphone lives in Ask).
* **The same address rules, no second outbound path.** The call is `app.ai.transport.send_json` (resolve at request time,
  check every address, connect to the checked one, no redirects, answer size cap `AI_MAX_RESPONSE_BYTES`, no
  `HTTP(S)_PROXY`) with scope `shared`: a private or LAN address, and plain `http`, only when `AI_PRIVATE_HOSTS` lists
  the host (`stt:8000`), exactly as an Ollama host. `send_json` gained `content` and `content_type` for the multipart body.
  Start-up validates the URL (a wrong value stops the start; a host the policy would refuse is a warning; the admin view
  shows it as `problem`). Failures are coarse categories with plain messages; no response body is echoed, and a recording
  is sent once (no retry).
* **Checks, in order** (all before the audio is read). Signed in (401) → `ai.enabled` (404) → `ai.voice_enabled`,
  `ai.chat_enabled` and `STT_BASE_URL` (404 `Not Found`) → the person can use AI (503 with the reasons of the other
  features, `not_opted_in` first) → the content type (415) and a declared size (413) → consent for purpose `voice` to this
  host (`409 consent_required` with the sheet's text) → the person's single AI slot (`429 busy_*`) → the body is read in
  memory within 30 seconds (`408`; over the limit `413`) → the first bytes must be the declared container (EBML for webm,
  `OggS`, `ftyp` for mp4, `RIFF`..`WAVE`; `400`; under 64 bytes is `400 empty`) and a WAV longer than a minute is `413` (the
  other containers' minute is the page's limit and the byte limit; the server cannot read it without decoding) → the daily
  limit (`429 quota_exhausted`; a refused clip is not counted) → the transcription → `{text}`.
* **Nothing is kept.** The audio and the transcript are never written to disk or to the database and never logged (the
  log line holds host, model, a length bucket and the outcome). The transcript is cleaned by the chat's text policy (NFKC,
  `Cc`/`Cf` removed, spaces collapsed, at most 2000 characters). One `ai_audit` row per recording, **no request or response body
  whatever `ai.audit_retention_days` says**: `feature "voice"`, `provider_id` NULL, the transcription model and host, and a
  verdict `{duration: "under 10 s" | "10 to 30 s" | "30 to 60 s" | "unknown", outcome}` (the length is the page's `seconds`, or
  a WAV's own header). The admin's "Test transcription" sends one second of generated silence and writes no row.
* **Daily limit.** Counted in `ai_usage` under provider id 0 with `key_scope = 'own'`, so `ai.shared_daily_limit` (the shared AI
  calls) never includes voice and the admin's usage list shows the row as "speech to text". Counted when the clip is
  forwarded, whether the server answers or not.
* **Consent purpose `voice`.** Its own sheet: "Your recording is sent to <host> to turn it into text, then deleted. Nothing
  is kept." (plus whether the host is on the operator's own network); no "show me the request" choice, since there is no
  request before the recording exists; consent is asked **before the microphone is opened**. The row in `ai_consents` keeps
  the transcription **host** in `host` and, for its key, the id of the AI provider that serves the person (the table's
  foreign key needs a provider row; no row is made for the transcription server). A changed host, AI provider or
  wording (`stt.POLICY_VERSION`) asks again; Settings lists it as "Voice recordings → Speech to text (host)" and can
  withdraw it.
* **Headers.** `Permissions-Policy: camera=(self), microphone=(self), geolocation=(), payment=(), usb=(), browsing-topics=()`:
  the microphone for this origin only (it was `microphone=()`); everything else is unchanged. `connect-src 'self'` already
  covers the upload.
* **The page** (`js/views/ask-voice.js`, attached by two hook lines in `ask.js`). The microphone button appears only when
  `GET /api/ai/status` says `features.voice`. Tap to record, tap again to stop (or at 60 seconds); a visible "Recording"
  row shows the time with Discard; leaving the tab or the page, or Escape, discards a recording; every track is stopped
  after each recording; the audio stays in memory and is dropped after the upload (no file, no object URL, no playback). The
  text goes **into the question box**, after anything already typed, for the person to read and edit; nothing in the code
  presses Send. Without `MediaRecorder` (or a secure context) or with the microphone refused, one plain line explains.
  **Read answers aloud** is a per-device switch (`localStorage`, in `try`) that speaks the checked answer text with
  `speechSynthesis` using only voices with `localService === true` (an online voice would send the answer to the browser's
  maker); with none, the switch is hidden and a note says why. Only `answer.text` of an answer, a low, an emergency or
  a save card (the app's fixed "Nothing has been saved yet. Check this, then press a Save button, or Cancel.") is spoken,
  with links, handbook paths and addresses removed; never the cards themselves, the figures or the notices. Saving stays a
  button press: nothing in the voice code presses a Save button or changes the trust choice.
* **No new clinical numbers and no dosing.** Voice adds no threshold or advice; the transcript is only the person's words,
  and the rules (a low, an emergency) still run first on whatever is sent.
* **Deployment example.** `deploy/compose.stt-whisper.yaml`: a speech-to-text container on an `internal` network with no
  route out, pinned by digest (a marked placeholder until the owner verifies one), read-only, no capabilities, no new
  privileges, a non-root user, limits and a health check, the model put in a volume once beforehand.

### Schema step 6 (`m006_ai.py`)

`ai_providers` (scope/owner `CHECK`, `locked` only for shared, one per person, one env row,
`AUTOINCREMENT`; `api_key_enc` sealed, `api_key_hint`, `probe_json`, `probed_at`, `disabled_reason`),
`ai_consents (user_id, provider_id, purpose)` (both foreign keys cascade), `ai_usage (user_id, day,
provider_id)` with `key_scope`, and `ai_audit`. Every user reference has `ON DELETE CASCADE`.

### Schema step 12 (`m012_ai_consent_chat.py`)

`ai_consents.purpose` was `CHECK (purpose IN ('text','photos'))`; SQLite cannot change a CHECK, so the step rebuilds the table
(copy, drop, rename, recreate `ai_consents_provider`) with the purposes `text`, `photos` and `chat`. Same columns, key and
cascades; every row is kept; atomic, `foreign_key_check`, idempotent (a table that already allows `chat` is left alone).

### Schema step 13 (`m013_assistant_ask_keys.py`)

`assistant_ask_keys (key_hash PRIMARY KEY CHECK (length = 64), user_id → users ON DELETE CASCADE, tool, saved_json, created_at)` with
indexes on `created_at` and `user_id`: the duplicate guard of the Ask chat's trusted saves (step 11's table needs a token and an Ask
save has none). `key_hash` is the SHA-256 of the person's id and the key; the plain key is never stored. Atomic,
`foreign_key_check`, idempotent (`IF NOT EXISTS`). The trust choice itself is not in the schema (it is a field of the person's
`ai` setting).

### Schema step 14 (`m014_ai_consent_voice.py`)

`ai_consents.purpose` accepts `voice` besides `text`, `photos` and `chat`. SQLite cannot change a CHECK, so the table is rebuilt
as step 12 did, but from the **stored definition** of the old table with `'voice'` added to that one list (not a second copy
of the DDL), so a column or constraint that a step between 12 and 14 added is kept; every row is copied; atomic,
`foreign_key_check`, idempotent. A voice row keeps the transcription host in `host` and the AI provider's id in
`provider_id` ("Voice input" above).

### Schema step 16 (`m016_ai_consent_labs.py`)

`ai_consents.purpose` accepts `labs` besides `text`, `photos`, `chat` and `voice`. SQLite cannot change a CHECK, so the table is
rebuilt as steps 12 and 14 did: from the **stored definition** of the old table with `'labs'` added to that one list, so a
column or constraint that a step between 14 and 16 added is kept; every row is copied (a person who agreed to photos, chat or
voice is not asked again); atomic, `foreign_key_check`, idempotent. A `labs` row keeps the local provider's host and id.

### Data, export, deletion and retention

`export.json` carries `ai_audit` (the person's rows), `ai_usage`, `ai_consents` and `ai_provider` (their
own provider without its key: `key_set`). Deleting an account deletes all four. Bodies in `ai_audit` are
cleared after `ai.audit_retention_days` (0 keeps metadata only), rows and usage after
`audit.retention_days`; the purge runs at start-up and as a step of the app's daily housekeeping
(`app/auth/housekeeping.register_daily`, any signed-in request), whether AI is on, off or unused. Logs carry feature,
provider id, preset, model, host, latency, tokens and status only.

### Guidance hook

`register_ai_status` feeds `GET /api/guidance/next-meal`'s `ai` block: `{available, provider_label}` is
true when AI is on, the person opted in and a provider resolves (no quota, nothing sent).

### Frontend (`js/views/ai.js` = `KH.ai`, `css/ai.css`; `docs/ai.md` "For people using the app")

* **Settings → AI ideas** fills the `#set-ai-slot` that `js/views/settings.js` leaves for M2 (a
  `MutationObserver` re-renders it whenever the Settings view is shown): "Use AI ideas", the provider
  (each shared one with its policy line, or "My own provider and key"), share age band and sex,
  preferences, calls left today, "My own AI provider" (preset, model, vision model, a public https
  address for a custom server when allowed, the write-only key through `KH.views.settings.keyWidget`,
  Test connection, Remove), "What you agreed to send" (Withdraw), "AI activity" (sent / received /
  verdict while kept; the received text captioned as the provider's answer before the app's checks and shown
  through `KH.aiguard.maskForDisplay`, blocklist words as `[hidden]`; "Delete my AI history"). For admins,
  **Server administration → AI providers** (v0.3.1; before, the end of Settings → AI ideas): each provider with its
  key status, badges and last test, Test connection, Edit, Delete; Add a shared provider (preset, name,
  address, model, vision model, key, advanced options); `AI_PRIVATE_HOSTS` read-only; AI usage (counts).
  The `ai.*` switches are in Server administration → Server settings like every registry key. At the top of that
  section `js/views/ai_routing.js` draws "Which AI does each feature use?" (privacy tiers): a table of the features (four with
  Local / Cloud / Off, and "As before" while a feature is still on `any`; "Local, then cloud" for photos, meal ideas and describe a meal,
  with its one-line rule under the table; the lab report row only Local and Off, from `allowed`), the local-AI and cloud-AI selects (the
  local one lists only private providers), a warning for every feature that goes to the cloud ("this sends … to
  <host>, outside your network"), and Save routing (`PUT /api/admin/ai-routing`, only the changes). Settings → AI ideas
  adds "Where each AI feature runs", one line per feature from `GET /api/me/ai`'s `routing`, and, once routing is set
  up, the provider choice is "The server's AI" or "My own provider".
* **Labs view**: the card "Read a lab report photo or PDF" (`js/views/lab_photo.js`, "Lab report photos" above); `KH.ai.uploadPhoto`
  takes the kind `lab-report` for `POST /api/ai/read-lab-report`, and the consent sheet shows the server's `notice` lines for the
  purpose `labs` instead of the generic text.
* **Add view**: `#ai-add-slot` shows the features `GET /api/ai/status` reports (AI meal ideas, Describe a
  meal, Read a label, Plate photo) and the shared calls left; "AI ideas are off for you" with a link to
  Settings when the person has not opted in; nothing when AI is off.
* **Sheets** (`#sheet-ai`, `#sheet-ai-consent`, `#sheet-ai-sent` in `index.html`): every call goes through
  `KH.ai.withConsent(purpose, send, preview, trigger, feature)` (`feature` picks whose provider's consent applies; describe
  passes `describe`): a `409 consent_required` opens the consent sheet (provider,
  host, policy line, the dry run, "Show me the request before every AI call to this server" =
  `skip_preview: false`), then `POST /api/ai/consent` and one retry; with `skip_preview` false the dry run
  is shown first with a Send button. Pre-filter answers (cards) are shown instead and need no consent.
  Photos are redrawn on the device (`createImageBitmap` → canvas, long edge ≤ 1600 px, JPEG 0.85, no EXIF)
  and sent as the raw `image/jpeg` body. The label draft is editable, fields read by AI are marked "from
  photo" or "estimated", and "Save as my food" uses `POST /api/foods` (then optionally `POST /api/log`).
  Meal ideas, described meals and plate items are added with `POST /api/log/batch` only on a tap.
* **For guidance's UI**: `KH.ai.mountIdeas(element, {date, meal})` renders the AI ideas block (button,
  "What will be sent?", results) inside "What fits now" when `next-meal`'s `ai.available` is true;
  `KH.ai.openIdeas({date, meal, trigger})` opens it in a sheet; `KH.ai.withConsent('text', () =>
  KH.ai.api.nextMeal(body), () => KH.ai.api.nextMeal(body, true))` runs the other modes (`rerank`, `swap`
  with `entry_id` or `food_id` + `servings`, `plan`).
* Model output is set with `textContent` only; links only through `KH.learn.href` (handbook pages);
  `tests/test_ai_ui.py` checks the routes it calls, the demo answer's shape and these rules.
* **Ask screen** (`js/views/ask.js`, `#view-ask`, tab `#tab-ask`): the tab is hidden until `KH.views.ask.refreshTab()` (after
  sign-in and whenever `KH.ai.forget()` runs) sees `features.chat`; a message list in `role="log"` (answers are text nodes;
  `/learn/...` paths become links through `KH.learn.href`), an input where Enter sends and Shift+Enter makes a new line,
  "Thinking…", the existing alert cards (`KH.ai.cardEl`) for `treat_low` and `get_help_now`, "From the app" under every
  answer with `numbers`, a plain notice for `withheld`, `unfinished` and `error`, "New conversation", the consent sheet on
  first use (`KH.ai.withConsent('chat', …)`, with "What will be sent?"), and the line "Answers come from an AI model; every
  number is the app's own. Not medical advice." The last 20 messages are sent each time; nothing is stored in the browser.
  A question that was not answered (consent declined, 429, 503) goes back into the box. Demo and preview: the tab shows a
  note that the chat works in the installed app with an AI provider, and no input (no mock answers).
  Saving (part C, the self-contained section "Saving from the chat" of `ask.js`): the trust line `#ask-trust`, the confirm card
  (`pending_save`: Save as eaten / Save as planned / Cancel), the saved card with Undo, and the app's questions; Save, import and
  Undo use only `KH.ai.api` (`logBatch`, `createMeal`, `importUsda`, `deleteEntry`, `deleteMeal`: the app's normal routes), so the page
  has no URL of its own. The warning sheet `#sheet-ai-trust` is `KH.ai.confirmTrust`.
  `tests/test_ask_ui.py` checks the shell, the CSP rules and these behaviours.

### Parity (demo/preview mode)

The `ai.*` keys are in `tests/data/settings_vectors.json` and `js/engine/settings.js`. Demo mode never
calls a provider: `js/mock/ai.js` answers like a server with AI off (`GET /api/me/ai` → `enabled: false`;
every `/api/ai/*` (`/api/ai/chat` and `/api/ai/transcribe` too) and `/api/vision/*` route 404), and Settings → AI ideas says AI runs in the installed
app. `ai.chat_enabled`, `ai.voice_enabled` and the seven `ai.route.*` keys are registry keys like the others (vectors and twin; the demo's `GET /api/me/ai` has `routing: null`). The Ask screen and the routing table have no twin: the demo shows its note, and no microphone or read-aloud switch. The lab report reader has no twin either: in the demo `/api/ai/read-lab-report` answers `404` like every AI route and the card is not shown.

## M3: the handbook at `/learn`

Built in M3 (handbook integration) from note 08 §4.6–§4.8, §4.10 and §4.11. **`/learn` is live**: the
image builds the handbook and the app serves it. Code: `app/handbook.py`, `HANDBOOK_DIR` and
`HANDBOOK_PUBLIC_URL` in `app/config.py`, path policies in `app/security.py`, the `handbook` stage of both
Containerfiles, `js/learn.js`. People-facing: `handbook/docs/app/index.md`,
`handbook/docs/self-hosting/configuration.md`; operators: `docs/deployment.md` (Configuration),
`docs/security.md` ("The handbook at `/learn`").

### Serving

* `HANDBOOK_DIR`: `/app/learn` in the image, `<repo>/handbook/site` from source (`load_settings`);
  `Settings` built in code default to `None` (no handbook), so tests stay hermetic. The site is served
  only when `HANDBOOK_DIR/index.html` exists, else `/learn` is 404 (and nothing else changes).
* Mounted before `/` (`handbook.mount`): `StaticFiles(html=True)`, read-only, `GET`/`HEAD` only;
  `/learn` → `308 /learn/`; a directory serves its `index.html` (missing slash: 307); an unknown path
  serves the site's `404.html` with status 404; never a directory listing; `..`, encoded separators,
  absolute paths and symlinks that leave `HANDBOOK_DIR` → 404.
* **Public**: no sign-in, like the app shell (static, no personal data; note 07 §4.10).
* Cache: `assets/**/<name>.<8 hex>.min.(js|css)` → `public, max-age=31536000, immutable`; everything
  else under `/learn` → `no-cache` (ETag revalidation); `.gz` files are labelled `application/gzip`.
* **CSP for `/learn` only** (`handbook_csp`; `security.install(path_policies=…)` applies it to `/learn`
  and `/learn/*`, the app's policy stays unchanged everywhere else, `upgrade-insecure-requests` is added
  over HTTPS as for the app, every other header is the same):
  `default-src 'self'; script-src 'self' 'sha256-…'×N; style-src 'self'; img-src 'self' data:; font-src
  'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none';
  form-action 'self'; frame-ancestors 'none'`. No Trusted Types, never `'unsafe-inline'`. The hashes
  are computed once at start-up from every inline script (no `src`; JavaScript, module, importmap or
  speculationrules type) of every HTML file the mount can serve, after line-break normalisation.
  More than 64 distinct scripts, or a page that is not UTF-8: the handbook is not served, an ERROR names
  the reason, the app starts normally. `python -m app.handbook csp [DIR]` prints the policy (for
  operators serving the handbook from its own host name).
* The service worker answers `/learn` network-first (v0.3.1): every plain 200 answer from this server (a page or
  a file it loads; never a redirect, another origin or a partial answer) is copied into `kdl-learn-<version>`,
  and when the network fails that copy is served (pages match without the query string, so a search result's
  `?h=` link opens the saved page). A page never opened on the device answers offline with a short 503 note made
  by the worker (`learnOffline`: no script or style, CSP `default-src 'none'`). The handbook is static and the
  same for everyone, so nothing personal enters the cache; a new release starts with an empty copy (activate
  removes old `kdl-` caches), **Clear offline data on this device** removes it, signing out keeps it.
  `tests/test_learn_offline.py` runs the real worker in Node; `tools/e2e/learn.py` step 7 checks it in Chromium
  with the server stopped.

### `GET /api/handbook` (signed in)

```json
{"available": true,                   // this server serves the built handbook at /learn/
 "url": "/learn/",                    // where Learn links go: "/learn/", HANDBOOK_PUBLIC_URL, or null (hide them)
 "public_url": null,                  // HANDBOOK_PUBLIC_URL (http(s), normalised to end with "/"), for Settings → About
 "links": {"nutrients": {"potassium_mg": {"path": "eat/potassium/", "title": "Potassium"}, …},
           "flags": {"phosphate_additive": {…}, "avoid_ckd": {…}, "high_gi": {…}, "hypo_treatment": {…}, "potassium_additive": {…}},
           "pages": {"home": {"path": "", …}, "targets": {…}, "first_setup": {…}, "get_help_now": {…}, "blood_potassium": {…}, "treating_a_low": {…}}}}
```

`links` is `app/handbook.py` `LINKS`, built from `app/guidance/topics.py` (`TOPIC_PAGES`,
`NUTRIENT_TOPIC`: the one slug table). Paths are relative to `url` and end with `/`. Demo mode
(`js/mock/handbook.js`): `available: false, url: null` (no Learn links in the preview).

### Frontend (`js/learn.js`, `KH.learn`)

* `load()` (once per signed-in page, with the profile; never throws), `href(path)` (a table path or a
  server URL `/learn/…` → the href for this server, or `null`: no handbook, or not a handbook path),
  `link(group, key)` and `forWarning({nutrient, flag})` (an `<a>` "Learn: <page title>" or `null`),
  `info()`, `available()`, `publicUrl()`.
* The header entry `#learn-link` (book icon, accessible name "Learn") and Settings → About & privacy
  open the handbook **in the same window** (the handbook's "Back to the food log" returns to `/`).
  Links inside warnings (`KH.ui.renderWarnings`), Today's alerts and projected alerts, and the
  suggested-target notes open in a **new tab** ("opens in a new tab" for screen readers), so an entry
  being typed is not lost.
* **Rule for every view:** link into the handbook only through `KH.learn` (server texts carry
  `/learn/<path>/` URLs from `topics.py`; pass them to `KH.learn.href`). `tests/test_learn_links.py`
  scans `app/static` and every Python module for `/learn/…` links, adds `TOPIC_PAGES` and `LINKS`, and
  fails unless each resolves to a page in `handbook/docs` (and, in CI's handbook job, in the built site),
  anchors included.

### Menu days in the app (add this day to my plan, v0.4)

Note 08 §4.10 ("Idea for v0.4"). Every generated menu day in the handbook ends with a plain link that opens the app
at a confirmation sheet for that day. Nothing is saved until the person presses **Add to plan**.

**The link (the contract between `scripts/build_handbook.py` and `js/engine/menu_link.js`):**

```text
<app address>#plan-menu?items=b173905x1,b167755x0.5,l170187x1,d171267x2,s173944x0.6667
```

* One entry per food: `<meal><fdc_id>x<servings>`, entries separated by `,`. `<meal>` is one letter: `b` breakfast,
  `l` lunch, `d` dinner, `s` snack (all snack blocks of a day are `s`). `<fdc_id>` is the USDA number of a **built-in**
  food (`data/foods.json`, which is what `menus.yml` already uses); `<servings>` is a number of servings of the food's
  own `serving_desc`, above 0, at most 1000 (`MAX_SERVINGS`), up to 4 decimals (`0.6667`), without a sign, exponent or
  leading dot. The link is in the URL **fragment**, so the browser never sends it to any server, and it carries no
  name, date, unit, nutrient or total: the app looks each food up and works out every number itself.
* Limits: at most 40 entries (`MAX_LOG_BATCH`, so one confirmation is one batch), at most 1500 characters in all,
  only `[A-Za-z0-9.,_-]` after `items=`, exactly one parameter. The build fails a menu day that does not fit (more than
  40 foods, the same food twice for one meal, servings the link cannot carry), so a generated link is always readable.
* The reader refuses the **whole link** (the sheet says why, no Add button) when it is too long, has another
  character or parameter, has no entry or more than 40; it **skips one entry** (listed under "Not added" with the
  reason) for an unknown meal letter, an amount outside the limits, an empty entry, the same meal and food twice (the
  first is kept), or a food number that is not a built-in food of this server.

**Handbook side.** `menu_plan_paragraph()` writes the link as one raw HTML paragraph under each day's table
(`<p class="kh-plan-day"><a class="kh-plan-link" href="@KH_APP@#plan-menu?items=…">Add this day to my plan</a> …`; raw
HTML so MkDocs does not read the hash as a page anchor). The committed pages hold the placeholder `@KH_APP@`; the
MkDocs hook `handbook/tools/menu_links.py` (`hooks:` in `mkdocs.yml`, inherited by `mkdocs.pages.yml`) replaces it at
build time: with `extra.app_link` (the image build, `HANDBOOK_APP_LINK=/`) the link is `/#plan-menu?items=…`, the same
origin as the app that serves `/learn/`; else with `extra.demo_link` (the Pages build) a path relative to the page,
`../../../demo/#plan-menu?items=…`, with the text "Try this day in the app's demo"; with neither the paragraph is
dropped. No script runs on the handbook side (`/learn` is served under a hash-only CSP) and the handbook never sees the
app's session. `handbook/tools/check_links.py` skips a fragment that holds `?` (an app route, not a page anchor).

**App side.** No new server route and no schema change: the reader runs in the browser and resolves through existing
routes.

1. `js/engine/menu_link.js` (`KH.menuLink`, pure, no DOM) parses the hash strictly, `resolve()` matches the entries with
   `GET /api/foods/builtin` (the same list for everyone: `source` must be `builtin`, so a custom food, a food another
   person scanned or imported, a hidden food or a row id of the app never resolves, and its name is never looked up or
   shown), and `batchEntries()` builds the body of `POST /api/log/batch`.
2. `js/views/menuplan.js` shows `#sheet-menuplan`: each food with the app's own name, rating, serving text and
   nutrients, grouped by meal with a tick box; the date (default tomorrow, or the first of the next 14 days with
   nothing logged or planned, from `GET /api/log/range`); the menu's own totals; the day's projected totals (the server's
   `projected_status` for that date plus the ticked foods, from `GET /api/log`) with the same near / over lines as the
   other planning sheets (`impactOn`, `statusLevel`, `overAt`). A food that treats a low is planned like any food
   and gets no wording of its own; it is left out of a meal's carbohydrate line, as for every entry.
3. Only **Add to plan** writes: `POST /api/log/batch` with the ticked foods as `status: "planned"` on the chosen date,
   through the normal request wrapper (`X-Requested-With`, session cookie, re-authentication prompt). One `client_id`
   per food is made when the sheet opens, so a second press or a retry after a lost answer adds nothing twice (the
   batch answers 200 with every item `existing`).
4. **Signed out:** the link is taken out of the address bar into a variable in memory at page load (`takeLink()`), never
   into any storage, so the sign-in screens, which rewrite the address, do not lose it and the list does not stay in the
   history. `main.js start()` (first start after sign-in) and `auth.js enterApp` (signing in again on an open page) call
   `KH.menuPlan.openPending()`. A page reload, an outside sign-in page (proxy or single sign-on) or another person
   signing in on the same page forgets it: open the link again. A session that ended while the sheet was loading the
   food list sends the person to the sign-in screen; open the link again.
5. **Demo:** the mock API answers `GET /api/foods/builtin` and `POST /api/log/batch`, so the sheet works in the
   preview; the Pages demo has the whole food list (the `?mock=1` page of a live server has 24 foods, so most foods are
   listed as not added there).

Tests: `tests/data/menu_link_vectors.json` (`node tests/js/run_vectors.mjs`, section "menu link");
`tests/test_menu_plan.py` (every generated day has its link and it says what `menus.yml` says; the reader run over all
42 links against the real `GET /api/foods/builtin` of the shipped list resolves every food; a tampered link; the batch
creates planned entries and a second post adds nothing; the hook's three modes; no inline script; the view writes only
from its submit handler and keeps the list in memory); `tools/e2e/menuplan.py` (Chromium, by hand).

### Build, CI and publishing

* Image: a throw-away `handbook` stage (same base as the builder) installs `handbook/requirements.lock`
  (`--require-hashes --only-binary=:all: --no-deps`), runs `mkdocs build --strict -d /out/learn` with
  `HANDBOOK_SITE_URL=http://localhost/learn/` and `HANDBOOK_APP_LINK=/`, drops `*.map`; the runtime copies
  only `/out/learn` to `/app/learn` (root-owned, `go=rX`). Licence label: `PolyForm-Noncommercial-1.0.0
  AND CC-BY-NC-SA-4.0`. The container smoke test fetches `/learn/` (CSP, 404 page, immutable bundle).
* CI job `handbook` (the image jobs need it): `build_handbook.py --check`, the strict build, the link
  checker, `tests/test_handbook_content.py`, `tests/test_learn_links.py` against the built site, and
  `tools/e2e/learn.py` (real app + built site in the runner's Chrome at 375×812 and 1280×800; fails on
  any CSP/Trusted Types violation, page or console error, failed or outside request). `handbook-zensical`
  is an allowed-to-fail canary. `handbook-pages.yml` publishes to GitHub Pages only when the repository
  variable `HANDBOOK_PAGES` is `true`; `handbook-links.yml` checks external links weekly.
* Docs: `docs/deployment.md`, `docs/security.md`, `docs/https.md` and `SECURITY.md` hold the commands;
  `handbook/docs/self-hosting/` explains and links to their sections (`tests/test_deploy.py` checks the
  anchors and that those pages carry no shell blocks). `docs/diet-guide.md` is a pointer to
  `/learn/eat/` with a map from its old sections to the handbook pages.

## Symptoms log (schema step 15)

Was the ROADMAP item "Symptoms log" (done 2026-10-15, so no longer listed there). A person records a symptom with a date and a severity; Today and Trends show it and the export
holds it. **The app records and shows. It never suggests a cause, a treatment or a dose**; the one thing it adds is a
pointer to the handbook for the symptoms that page lists as warning signs. Code: `app/symptoms.py` (router, tables, row
shape), the `Symptom*` models in `app/models.py`, `app/migrations/m015_symptoms.py`.

### Table `symptoms` (schema step 15, `m015_symptoms.py`)

`symptoms (id, user_id → users ON DELETE CASCADE, date TEXT 'YYYY-MM-DD', symptom TEXT, label TEXT '' (≤ 60), severity
INTEGER 1..3, note TEXT '' (≤ 300), created_at)` with index `symptoms_user_date (user_id, date, id)`. There is **no CHECK
on the symptom key**: a later key must not need a table rebuild (steps 12 and 14 had to); the API validates it, and a row
with a key this version does not know is kept, left out of the lists and included in the export. The table checks what
never changes (severity 1 to 3, the lengths, a 10-character date). Deleting an account deletes its symptoms.

### Routes (`/api/symptoms`; every one `current_user`, scoped by `user.id`, not yours is 404, CSRF header on writes)

| Route | Answer |
|---|---|
| `GET /api/symptoms?start=&end=` | `{symptoms: [SymptomOut]}` oldest day first, then entry order; `start` and `end` (`YYYY-MM-DD`) are required, at most 366 days (the log's range rules and messages) |
| `POST /api/symptoms` `SymptomCreate` | 201 `SymptomOut` |
| `PUT /api/symptoms/{id}` `SymptomCreate` | 200 `SymptomOut`: replaces the editable fields, keeps `created_at`; the body is checked before the id is looked up |
| `DELETE /api/symptoms/{id}` | 204 |

`SymptomCreate` (`extra="forbid"`, strings stripped): `date` (not in the future with a day of time-zone slack, 1900 or
later: `validate_past_date`), `symptom` (`swelling`, `itching`, `tiredness`, `cramps`, `nausea`, `breathlessness`,
`poor_appetite`, `other`), `severity` (1 mild, 2 moderate, 3 severe), `label` (≤ 60 characters, one line of plain text;
**required for `other`, refused for every other symptom**) and `note` (≤ 300 characters, plain text: control characters
refused, tab, newline and carriage return allowed). A `null` label or note is empty. One person holds at most 30
symptoms per date (`MAX_SYMPTOMS_PER_DAY`, a bound on storage, not a clinical number; a 31st, or a move into a full day,
is a 400). `SymptomOut`: `{id, date, symptom, label, name, severity, severity_label, note, created_at, red_flag}`; `name` is
"Swelling" or, for `other`, the label; `severity_label` is `Mild`, `Moderate` or `Severe`.

### Red flags (what the app says, and where it comes from)

`red_flag` is `null` except for the symptoms that `handbook/docs/get-help-now.md` sorts as warning signs, where it is
`{level, text, href: "/learn/get-help-now/", link_text: "Get help now", prominent}` (`prominent`: severity 3). The table
is `app.symptoms.RED_FLAGS`, and each line is built only from phrases copied from the page:

| Symptom | Page group (`level`) | Quoted from the page |
|---|---|---|
| `breathlessness` | "Call 911 now" (`emergency`) | "Severe breathlessness"; "sudden breathlessness or fainting with no clear cause" |
| `swelling` | "Call your care team today" (`today`) | "new swelling of the legs, ankles or face" |

Itching, tiredness, cramps, nausea and poor appetite are under "Mention at your next visit" on that page and carry no
`red_flag`; `other` never does (the app does not read a person's own words). `tests/test_symptoms.py` reads the page and
fails when a quoted phrase is no longer under its heading, when a symptom outside the table appears under a warning
heading, and when a line names a cause, a treatment or a dose. The people-facing wording is in
`handbook/docs/app/reports-for-your-team.md` ("Symptoms you write down"). Changing the list needs the clinical review
that `handbook/REVIEW.md` tracks for the page itself.

### Where it shows

* **Today** (`js/views/symptoms.js`, `KH.symptoms.today(date)`): a compact **Symptoms** card under Daily status: the
  day's entries (name, severity word, note, **Edit**, **Delete** asking in the page), **Add** opening the bottom sheet
  `#sheet-symptom` (symptom, a name for `other`, severity with nothing chosen at first, date, optional note; nothing is
  saved until **Save**; choosing a red-flag symptom shows the handbook's line in the sheet). A severe red flag is a block
  that stands out and is listed first; the handbook link is `KH.learn.href(red_flag.href)` (no handbook, no link; the line
  stays), opening in a new tab so a sheet in use is not lost. Days after today cannot be added to. Symptoms are not
  queued offline: a save needs the server and the card says so when it cannot load.
* **Trends** (`KH.symptoms.trends(start, end)`): one row per symptom (an `other` per label) with the number of days, the
  worst severity, a strip of marks over the period (decoration, `aria-hidden`; a mark's height is the severity), the dates
  written out with their severity, and the same handbook line. No chart library.
* **Export and import**: `export.json` → `symptoms` and `symptoms.csv` (formula-escaped); the import
  (`ImportSymptom`, `app/data_import.py`) checks every record like `POST /api/symptoms`, never uses the id in the file,
  counts `symptoms` in the report, treats an account with symptoms as having data (409 without `merge=1`), leaves out a
  symptom with the same date, name, severity and note that is already there, and skips (and lists) one beyond 30 on a day.
* **Privacy**: never logged; never read by `app/ai/`, `app/mcp/`, `app/guidance/` or `app/vision.py` (a test greps
  them), so no AI provider and no assistant ever receives a symptom. A later feature that wants to must change
  `docs/privacy.md` first. In the isolation matrix (`tests/test_isolation_v03.py`).

### Parity (demo/preview mode)

`js/engine/symptoms.js` (`KH.symptomRules`) and the demo routes `js/mock/symptoms.js` are checked against
`tests/data/symptoms_vectors.json`, generated by `tests/data/gen_symptoms_vectors.py` from the server itself: the tables,
rows in their API shape, and **one request script run against a fresh server and a fresh demo** (every route, every
refusal and its exact text, the 30-a-day limit, ids that pydantic reads as numbers, and `{{today:N}}` dates for the
"not in the future" boundary), then the Trends grouping (hand-written: only the browser draws it). `node
tests/js/run_vectors.mjs` replays them (`tests/js/demo_loader.mjs` loads the whole demo); `tests/test_symptoms_vectors.py`
fails when the file is stale. The demo has no sample symptoms: its ids start at 1 so the request script replays on it unchanged.
fails when the file is stale. `python tools/e2e/symptoms.py` drives the screens in Chromium (375 px light, 1280 px dark,
the demo): no sideways scroll, no console error, no request to another host.

## Weight and blood pressure (schema step 18)

Design note: `docs/dev/research/10-weight-and-blood-pressure.md` (the facts F1 to F7 each number traces to, the decisions Q1 to Q8). **Part A is the server, the
demo's twin, the settings, the export and import and the handbook's two lines; Part B (below, "Where it shows") is the screens: the Today card and its sheets, the
Trends charts, the Settings section, the Profile helpers, the visit prep section and the handbook page;** Part C the import from the iPhone Health app
(`export.xml`). A person records a weight (when it was taken: morning, before or after dialysis, other) and a blood pressure reading (top and bottom
number, optional pulse); the app records and shows, works out a few plain numbers, and points to the handbook when a number is past a limit. **It never
suggests a weight-gain alarm, a blood pressure goal or a dry weight (those are the care team's, entered in Settings), and says nothing about a cause, a
treatment or a medicine.** Code: `app/body.py` (router, pure functions, the handbook's words), the `Weight*`, `BloodPressure*` and `Body*` models in
`app/models.py`, `app/migrations/m018_body_measurements.py`. A guide for people who run or change the code: `docs/body.md`.

### Tables (schema step 18, `m018_body_measurements.py`)

`weights (id AUTOINCREMENT, user_id → users ON DELETE CASCADE, date 'YYYY-MM-DD', time 'HH:MM' or NULL, kg REAL (kilograms, two decimals), context TEXT, note
TEXT, source TEXT 'manual', source_key TEXT or NULL, created_at, updated_at)` and `blood_pressures (…, systolic INTEGER, diastolic INTEGER, pulse INTEGER or
NULL, context, note, source, source_key, created_at, updated_at)` (and, from schema step 19, `api_token_id → api_tokens ON DELETE SET NULL`: the device token
that sent the row, NULL otherwise), each with the index `(user_id, date)` and a **unique index `(user_id, source_key)
WHERE source_key IS NOT NULL`** (the key an import de-duplicates on; NULL for a typed row). `weights.context` is `morning`, `before_dialysis`,
`after_dialysis` or `other`; `blood_pressures.context` also has `evening`; `source` is `manual`, `apple_health`, `import` or `shortcut` (a phone shortcut's device token). **No `CHECK`** beyond `NOT NULL`:
the lists and the ranges live in the models (a later context or source must not need a table rebuild), and a row with a value this version does not know is
kept, left out of the lists and the summary, and included in the export. The unit the person types and sees (`user.units.weight`) is display and entry
only: storage is kilograms. The note is stored as text (`''`, never NULL).

### Routes (`/api/body`; every one `current_user`, scoped by `user.id`, not yours is 404, CSRF header on writes)

| Route | Answer |
|---|---|
| `GET /api/body/weights?start=&end=` | `{weights: [WeightOut]}` oldest day first, then by time (a row with no time last), then id; `start` and `end` required, at most 366 days (the log's range rules and messages) |
| `POST /api/body/weights` `WeightCreate` | 201 `WeightOut` (`source: manual`) |
| `PUT /api/body/weights/{id}` `WeightCreate` | 200 `WeightOut`: replaces the editable fields; the row becomes `manual`, leaves its device token (`api_token_id` NULL, so "Delete what it sent" never removes what the person edited) and keeps `created_at` and its `source_key` (so a second import does not bring the old value back); the body is checked before the id is looked up |
| `DELETE /api/body/weights/{id}` | 204 |
| `POST /api/body/weights/batch` `{rows: [WeightBatchRow]}` | 200 `{added, skipped}`: 1 to 1,000 rows, each the `WeightCreate` fields plus `source` (`apple_health` or `import`, default `import`) and a `source_key` (1 to 64 characters, one line); **the whole request is checked first and refused, writing nothing, on the first row that is not valid** (`400 "rows.3.kg: Input should be …; rows.3.context: …"`: all of that row's problems) or would be the 21st weight of its day (`rows.N: too many weights for one day (max 20)`); rows whose `source_key` the person has, rows that are **the same reading** as one the person has from any source but `manual` (the same date, `HH:MM` and kilograms; for a reading the same two numbers; a row with no time never matches), and repeats inside the request, are skipped and counted |
| `GET`, `POST`, `PUT`, `DELETE /api/body/blood-pressure…` | the same for readings: `{readings: [BloodPressureOut]}`, `BloodPressureCreate`, `POST /api/body/blood-pressure/batch` (the 31st reading of a day is the limit) |
| `GET /api/body/summary?date=` | `BodySummary` (below) |

`WeightCreate` (`extra="forbid"`, strings stripped): `date` (not in the future with a day of time-zone slack, 1900 or later: `validate_past_date`), `time`
(optional, `HH:MM` 00:00 to 23:59; blank or null is no time), `kg` (20 to 400), `context`, `note` (≤ 200 characters, plain text: control characters refused, tab,
newline and carriage return allowed; null is empty). `BloodPressureCreate`: the same `date`, `time`, `context` (five values) and `note`, `systolic` (50 to
300), `diastolic` (20 to 200), **`systolic > diastolic`** (a model rule: `400 "systolic must be greater than diastolic"`) and an optional `pulse` (20 to
250). **The ranges are the project's own plausibility choice** (they keep a typing error out of the log), not clinical numbers (note 10 §3); `kg` is the
profile's `weight_6_months_ago_kg` range. One person holds at most 20 weights and 30 readings per date (`MAX_WEIGHTS_PER_DAY`, `MAX_READINGS_PER_DAY`:
bounds on storage; a 21st / 31st, or a move into a full day, is a 400). `kg` is stored rounded half up to 0.01. `WeightOut`: `{id, date, time, kg, context,
note, source, via, created_at, updated_at}` (`via` is the name of the device token that sent a `shortcut` row, else `null`; read with a `LEFT JOIN` on the row's token and owner);
`BloodPressureOut` adds `systolic`, `diastolic`, `pulse` and **`flag`**. `source_key` is internal (it is in the export).
The two batch routes share one limit, `body_batch`: **60 requests an hour per person** (`app/auth/ratelimit.py`; 60,000 rows an hour, room for years of daily
weights; the project's own number) and keep the default 1 MiB body limit.

### What the app works out (pure functions in `app/body.py`; the browser twin is `js/engine/body.js`)

* **Units.** `kg = lb × 0.45359237` (exactly: the international pound, NIST SP 811), stored rounded half up to 0.01 kg (`round_kg`, `lb_to_kg`); shown in the
  person's unit to one decimal, **half up** (`shown_weight`, `format_weight`: 154.25 lb shows 154.3, where Python's `round()` would give 154.2), through
  `nutrients._half_up` and `KH.rules.halfUp`, the project's pair.
* **Weight gain against the alarm** (`weight_alarm_check`; only with an alarm number): `between_sessions` (hemodialysis) compares the latest weight with the
  latest `after_dialysis` weight **before it** dated in the 7 days before (the same day counts when it is earlier in time); without one, with the profile's dry
  weight ("Compared with your dry weight in Profile"; used **only while `dialysis` is `hemodialysis`**, because only then is the profile weight a dry weight);
  without either, "Add a weight after a session to compare". `days` compares with the latest weight **with the same context** dated on or before the
  latest date minus `days`, looking back at most `2 × days` days; without one, "Not enough weights to compare yet". The gain is the difference rounded to
  0.01 kg and is **over the alarm only when it is more than** `amount_kg` (strictly). The answer names the two weights (`reference`, `message`).
* **Blood pressure week** (`blood_pressure_week`): the readings dated the day and the 6 days before it; count, the mean top and bottom number (each rounded
  half up to a whole number) and whether a mean is **at or above** the person's goal number ("under 130/80": 130 is not under) per number (`above`) and
  together (`above_goal`). Fewer than 3 readings: the means with `few: true` and no verdict.
* **Six-month change** (`six_month_change`; visit prep and the Profile helper in Part B): the latest weight against the weight dated closest to 182 days
  before it, within ±30 days (a tie goes to the earlier day, then to the later weight of that day): kg and percent (one decimal). No alert (GLIM's 5 % rule
  reads it only if the person copies it into Profile).
* **`GET /api/body/summary?date=`** (`summarise`): `{date, units, weight: {latest, previous, gain: {kg, since} | null, alarm | null}, bp: {latest, week: {count,
  systolic, diastolic, above_goal, above, few}, goal: {systolic, diastolic}, flagged_today}}`. `latest` is the last row dated on or before `date`;
  `alarm` is null with no alarm number (`status` is `compared` or `no_reference`); `flagged_today` is the latest flagged reading dated exactly `date`.
  The server reads the newest 400 weights and 250 readings on or before the date (enough for the widest window).

### Settings (registered in `app/settings_registry.py`)

`user.units.weight` (`user_default`, `kg` or `lb`, default `lb`), `body.weight_alarm` (`user`; `{amount_kg: 0.2 to 10 or null, over: "between_sessions" |
"days", days: 1 to 7}`, default `{null, "days", 1}`) and `body.bp_goal` (`user`; `{systolic: 80 to 200 or null, diastolic: 40 to 130 or null}`, default both
null; **the top number must be above the bottom one** when both are set). There is **no default alarm and no default goal**: the right numbers are the
care team's (note 10 §2 and F3: KDIGO's 120 is for standardized office readings). They are in the export's `settings` and carried over by an import with
`replace_profile`. The unit's default for everyone is in Admin → Server settings → Default for everyone. The browser twin is `js/engine/settings.js` (a `num`
type for the float, `nullable` fields), checked by `tests/data/settings_vectors.json`.

### The handbook's words (what the app says, and where it comes from)

A weight over the alarm carries `flag` in the summary's `alarm`; a reading with a top number of 180 or more **or** a bottom number of 120 or more carries `flag`
(NHLBI's "180/120", read as either number: the project's cautious choice, an open item in `handbook/REVIEW.md`). A flag is `{level, text, href:
"/learn/get-help-now/", link_text: "Get help now", prominent}`; the table is `app.body.RED_FLAGS`, each line built only from phrases copied from the page:

| Flag | Page group (`level`) | Quoted from the page | `prominent` |
|---|---|---|---|
| weight over the alarm | "Call your care team today" (`today`) | "weight gain above the alarm number your team gave you" | no (the person set the number) |
| blood pressure at 180 or 120 | both; `level` is `emergency` | "A blood pressure of 180/120 or higher that is still that high when you check again after resting 5 minutes" (today); "A blood pressure of 180/120 or higher with a sudden severe headache, trouble breathing, sudden severe pain in the chest, belly or back, numbness or weakness, a sudden change in vision or problems talking" (911) | yes; the 911 quote comes first, then, without those signs, rest 5 minutes and measure again |

Part A added the two blood pressure lines to `handbook/docs/get-help-now.md` (source `NHLBI-BPS`, read 2026-10-22; the page's clause about a medicine or a
dose change is deliberately not repeated), to the shared wallet card and to `handbook/REVIEW.md` for the clinician review. `tests/test_body.py` reads the page
and fails when a quoted phrase is no longer under its heading, and when a line names a cause, a treatment or a dose.

### Where it shows (Part B)

Every screen reads and writes only the routes above (no new route, no table, no migration); the pure parts are `js/engine/body_ui.js` (`KH.bodyUi`: what
a person types and how it is worded, the chart scales, the table rows) and, for the visit prep page, `js/engine/visitprep.js`.

* **Today** (`js/views/body.js`, `KH.body.today(date)`, called by `today.js`): a **Weight and blood pressure** card under Symptoms with the day's weights and
  readings (**Edit**, **Delete** asking in the page), **Add weight** and **Add blood pressure** opening the bottom sheets `#sheet-weight` and `#sheet-bp`
  (nothing is saved until **Save**; a refusal keeps what was typed). A **very high reading is the first block of the card and prominent**: the block draws the
  server's `flag.text` as it is (the 911 line first, a link to Get help now through `KH.learn.href`, no handbook means no link and the words stay), headed
  "Reading 185/95 at 7:10 PM"; the same block shows **in the sheet before Save** from the twin (`KH.bodyRules.bpFlag`). Under it the **alarm line** (from
  `summary.weight.alarm`: "Weight up 1.8 lb. Over your alarm. Your alarm: more than 2.2 lb in 1 day.", the latest weight and the server's `message` that names the
  weight compared, and for a weight over the alarm the handbook's weight line, not prominent) and the **goal line** (the goal as the care team gave it and
  the server's 7-day average against it). With neither set, a line says where to enter them. While another day loads the card says "Loading…" and never
  keeps the other day's weights (`S.drawnDate`); only the newest request draws (`S.req`). Days after today cannot be added to; the card needs the
  connection and says so (a save offline says "need a connection to your server ... Nothing was saved" in the sheet).
  Changing the date clears the card and its summary immediately, including old alarm/goal lines.
  Loading has its own message; failed reads offer **Try again**, including a handled sign-in failure.
  Late replies or errors cannot replace the newest day's card.
* **The sheets**: the weight in the person's unit (`user.units.weight`, pounds until the server says otherwise) with the other unit echoed ("154.3 lb = 70.0 kg"),
  and **when it was taken** as radio choices that the page makes (morning / before dialysis / after dialysis / other; the two dialysis ones only when the
  profile's `dialysis` is not `none`, and always the row's own choice when editing); **no choice is pre-ticked**. A note-only edit keeps the stored weight to
  the hundredth. The reading sheet has the **top number (systolic)** then the **bottom number (diastolic)**, an optional pulse, the one line from MedlinePlus
  ("Rest about 5 minutes first, sit with your feet flat, and put the cuff on your upper arm." and a link "How to measure" into the handbook page), the echo
  ("Top 180, bottom 95") and the same choices (morning / evening / ... / other). The ranges are the server's (`WeightCreate`, `BloodPressureCreate`), checked in the
  page by `KH.bodyUi` so a typing slip is refused in words before a request.
* **Settings → Weight and blood pressure** (`KH.body.renderSettings()`, called by `js/views/settings.js`; the section `#set-body` after Preferences): the unit; the
  alarm as "Call my team if my weight goes up by more than [ ] [kg|lb] [between sessions | in a number of days]" (**between sessions only on hemodialysis**, or
  when that is already the saved choice) with a live sentence; the goal as "My blood pressure goal from my team: under [ ] / [ ]". Each says the number is the care
  team's and that the app suggests none, shows where the value comes from and saves its own setting (`PATCH /api/me/settings`), in kilograms whatever the unit;
  a link to the handbook page through the server's link table (`pages.weight_and_blood_pressure` in `app/guidance/topics.py`).
* **Settings → Your data**: `IMPORT_KINDS`, `importSizes`, the skipped-row names and the "Data imported" activity line count weights and blood pressure readings,
  and **Import from Apple Health** is a button that exists only when a module `KH.bodyImport` (Part C, not in Part B) provides `open()`; the same button on
  Trends. Part B builds neither the reader nor its sheet.
* **Trends** (`js/views/body_trends.js`, `KH.bodyTrends.show(start, end)`, called by `trends.js`; the card `#body-trends` under the symptoms list): a **weight chart**
  (one line, a marker per weight, a diamond for a weight after dialysis, on hemodialysis a dashed line for the profile's dry weight) and a **blood pressure chart**
  (the top and bottom numbers as two lines with a circle and a square per reading, the goal as two dashed lines when set, a heavier outline for a flagged
  reading), both **plain SVG built with the DOM** (`KH.s`: no chart library, no `innerHTML`, no inline style: classes and `css/body.css`), each with a **table under
  it** (`<details>`, every row, a flagged reading says "Yes, see Today") and a legend that names every line and marker, so nothing depends on seeing the chart or on
  colour. The dashed lines are named in the legend with their numbers ("Top goal: under 130 (dashed)", "Dry weight in Profile (…)"), not by text on the line, where
  it sat on the readings. The two series colours are the first two steps of the dataviz palette (tokens `--body-top` and `--body-bottom`, light and dark, validated for the
  colour-blind separation and 3:1 against the surface). The stats above them: the latest weight, the mean of **each kind of weight** over the last 7 days
  (`weekAverages`: morning is never averaged with after dialysis) and the server's 7-day blood pressure average with the goal verdict.
* **Profile** (`js/views/profile.js`, `KH.body.profileHints()`: `bodySummary` and one `bodyWeights` list): under **Weight** "Latest in your log: 70.2 kg on Oct 20 — Use
  this" (**not shown when the form says dialysis**, where the field is the dry weight; it follows the Dialysis box live), under **Weight 6 months ago** "In your log:
  74.0 kg on Apr 21 — Use this" (the six-month rule of the section above: the weight dated closest to 182 days before the latest, within 30). **Use this fills the box and
  nothing else**; Save profile saves it, and the profile is never changed by the log.
* **Visit prep** (`js/views/visit.js`): the section "Weight and blood pressure I recorded" (`V.bodyPage`): the latest weight, the six-month change, on hemodialysis the
  gains between the last 6 sessions (`sessionGains`: each weight before dialysis against the latest weight after dialysis in the 7 days before it, else the dry
  weight in Profile, the server's `between_sessions` comparison; "over your alarm" only against a between-sessions alarm), the 7-day and 30-day blood pressure
  averages (`readingsWindow`, the server's week rule with another length), how many readings had a top number at or above the goal's or a bottom number at or above its
  (the server's "at or above"), and the readings with `flag` in the period with their dates and the handbook's block once. A read that failed says so.
* **The handbook page** `handbook/docs/app/weight-and-blood-pressure.md` ("Using the app"): what to record and when, how to measure (MedlinePlus `MEDLINE-BPM`), which
  device (a validated upper-arm cuff; cuffless watches and rings are not recommended: `AHA25BP`, `AHA-CUFFLESS`), that the alarm and the goal are the care team's
  numbers (`K21BP`: KDIGO 2021 recommendations 1.2 and 3.1.1, for adults not on dialysis), what the app shows and does not, and a pointer to Get help now. First setup
  no longer says the app has no field for the weight-gain limit; the hemodialysis page links "enter them in the app" to it.
* **Security and privacy**: no route is added (every one is `current_user`, scoped by `user.id`); all text goes in through `h()` children; no inline script, handler or
  style; nothing is stored in the browser and nothing is sent anywhere but the app's own `/api/body`, `/api/me/settings` and `/api/profile`; weights and readings are
  never sent to an AI provider or the assistant (the views do not touch `KH.ai`).
* **Tests**: `tests/test_body_ui.py` (shell, markup, no inline code, the sheets' fields, the flag block quoting the server's text, Profile and Settings and visit
  prep wiring, the buttons hidden without `KH.bodyImport`), `tests/test_body_ui_numbers.py` with `tests/js/body_ui_runner.mjs` (what a person types is accepted and
  refused as the server's models and settings do; the words and the chart maths; the visit prep numbers against `app/body.py`), `python tools/e2e/body.py` (Chromium at
  375 px light and 1280 px dark with the other two combinations in a shorter walk, a real server and the demo, and `?mock=1&hd=1`).

### Export, import, deletion, privacy

* **Export and import**: `export.json` → `weights` and `blood_pressures` (after `symptoms`, oldest day first, `source_key` kept) and `weights.csv` /
  `blood_pressure.csv` (formula-escaped, README lines); the version stays 1. The import (`ImportWeight`, `ImportBloodPressure`, `app/data_import.py`) checks
  every record like the API (`WeightCreate` / `BloodPressureCreate`, text cleaned the same way), never uses the id in the file, counts `weights` and
  `blood_pressures` in the report, treats an account with either as having data (409 without `merge=1`), leaves out rows as the Import section says, and keeps
  the file's `source`, `source_key`, `created_at` and `updated_at`.
* **Deleted with the account** (`ON DELETE CASCADE`); in the isolation matrix (`tests/test_isolation_v03.py`).
* **Never logged** (no activity row either, as for symptoms; a test greps the logs), **never read** by `app/ai/`, `app/mcp/`, `app/guidance/` or `app/vision.py`
  (a test greps them), so no AI provider and no assistant ever receives a weight or a reading. A later feature that wants to must change `docs/privacy.md`
  first (a ROADMAP line).
* No offline outbox for them in this version (like symptoms): a save needs the connection.

### Import from the iPhone Health app (Part C: `js/engine/apple_health.js`, `js/views/body_import.js`, the sheet `#sheet-body-import`)

Browser only: no route, setting or schema step of its own, no dependency and no new network host. The person exports from the Health app (their picture,
Export All Health Data) and picks `export.zip` itself in the sheet (or `apple_health_export/export.xml`, if it was already unzipped in the Files app); the
sheet is opened by the buttons of
Trends (Weight and blood pressure → Import from Apple Health) and Settings → Your data with `KH.bodyImport.open()` (Part B). A `.zip` is opened on the device by
`KH.zip` ("Reading a .zip in the browser" below): the sheet streams its `export.xml` (`KH.zip.stream`, checked against its size and CRC-32 as it comes out) through
`TextDecoderStream` into the same scan, with the same `AbortController` and a progress line counted in the unzipped size; a `.zip` with no `export.xml` (the
clinical documents file `export_cda.xml` gets its own words), a damaged or cut-off one, and a browser without `DecompressionStream` are told so in plain words
(`ZIP_MESSAGE`, the old "unzip it in Files" advice for the last). Note 10 §4.8 is the
specification; the reader's header comment has its details and `tests/data/apple_health_vectors.json` pins each.

* **The reader** (`KH.appleHealth.scan(source, {today, signal, onProgress})`, loaded after `engine/rules.js`): the file can be hundreds of megabytes and
  starts with an internal DTD, so it is **never given to an XML parser** (no `DOMParser`, no entity expansion): it is streamed as text
  (`file.stream().pipeThrough(new TextDecoderStream())`, or the zip entry's stream), each `<Record ` start tag is cut out with a bounded buffer (a tag over 8 KiB is skipped and
  counted) and read by a hand-written scanner. It keeps `HKQuantityTypeIdentifierBodyMass` in kg or lb (a weight) and the systolic and diastolic
  `…BloodPressure…` records in mmHg paired by identical `startDate` and `sourceName` (a reading); **nothing else is read** (no heart rate, steps, glucose
  or insulin). Rows carry `date`/`time` as written, `context` by time of day, `source_key` (the first 32 hex characters of the SHA-256 of
  `type|startDate|value|sourceName`, so a second import adds nothing) and `sourceName`, which is for the sheet only.
* **The sheet** has five steps. *Choose*: the export steps and a picker for one `.zip` or `.xml` file (`export_cda.xml` and an empty file are refused
  with a reason, and so is a `.zip` that cannot be used). *Reading*: a progress line from `onProgress` (about every 10 MB) and **Cancel**, which aborts the scan and cancels the file stream.
  *Review*: the headline in words (found, kept), the date range, **what was left out and why** (a unit the app does not read, half a reading, outside the
  plausibility range, unreadable, repeats), the sources, the period (**the last 3 months by default** (`defaultSince`), or everything in the file; no
  picker when all of the file is recent) with the counts of each, and **readings from a watch listed apart and unticked** (a source whose `sourceName`
  contains "Watch", `isWatchSource`; the sheet quotes note 10 F4: cuffless devices are not recommended for checking blood pressure; the person decides;
  a watch-named source's *weights* are not held back). The Import button says what it will send ("Import 11 weights and 7 readings"). *Importing*: Stop
  ends it after the request in flight. *Done*: "Added a weights and b readings; c were already here" (the server's `added` and `skipped`).
* **What goes up**: the reader's rows without `sourceName` (`forUpload`) with **`source: "apple_health"`** (the batch model accepts `apple_health` or `import`),
  in batches of 1,000 (`batches`) to `POST /api/body/weights/batch` and then `/blood-pressure/batch` through `KH.api.importWeights` and
  `importBloodPressures`. `today` is passed to `scan` so a row dated more than a day ahead is unreadable here and not a refused request there. While the
  file is read and reviewed nothing is sent.
* **Days over the limit.** A batch with a row that would be the 21st weight (31st reading) of a day is refused whole, so the sheet trims first
  (`trimDays`): for each day it keeps the **first rows in time order, as many as the day can still take** (`KH.bodyRules.LIMITS`: 20 and 30, minus what the
  person already has that day, read from `GET /api/body/weights` and `/blood-pressure` for the days of the file in windows of 366 days, only where the file has
  rows; if they cannot be read, the limit alone). Rows an earlier import of this file stored (a stored row that is not typed in by hand with the same time and
  numbers) take no room: they are sent again and skipped as "already here", so importing the same file twice does not call them "left out". The result says
  "n more on m days were left out (the app keeps at most 20 weights and 30 readings a day)"; the review says "n or more will be left out" from the file alone.
* **A refusal never loses rows silently.** The server's answer to any request that fails (a 400 for a row, the 429 of the hourly `body_batch` limit, a gateway
  error) **stops the import**: the sheet shows the server's own words (with the day of the row it names), how many weights and readings were already added, and
  that pressing Import again carries on, skipping what is already here. A 401 closes the sheet for the sign-in screen. Closing the sheet during an import stops it
  after the request in flight and says so in a message.
* **After rows were added** the caches of Today and Trends (`state.dayLoadedFor`, `trends`, `summary`) are cleared and a showing Today or Trends is shown again,
  as the other imports do.
* **Checks**: `tests/test_body_import_ui.py` with `tests/js/body_import_page.mjs` (the view against a fake page, a fake backend that keeps the batch rules and
  fake files: the review, the watch rows, the default period, the trimming, a refusal in the middle, Cancel and Stop, text from the file drawn as text, no
  network call of its own; and an `export.zip` made in memory by `tests/js/zip_writer.mjs`: the same review and rows as the bare file, each message, Cancel while
  a `.zip` is read), `tests/test_frontend_shell.py` (the script lines, `sw.js`, no HTML sink) and the browser harness `tools/e2e/body_import.py`
  (a real server and the demo, a generated `export.xml` chosen inside an `export.zip` and bare, 375 px and 1280 px, light and dark; the server's rows read back through the API). The sample files are
  hand-written: look at a real iPhone export before calling the import done (note 10, "Re-verify").

### Parity (demo/preview mode)

`js/engine/body.js` (`KH.bodyRules`) and the demo routes `js/mock/body.js` are checked against `tests/data/body_vectors.json`, generated by
`tests/data/gen_body_vectors.py` from the server itself: the tables, one call of each pure function with what the server answers (units and rounding, 35 alarm
cases, the week and the goal boundary, the six-month match, the flag boundaries, rows in their API shape, summaries), and **one request script run against a
fresh server and a fresh demo account** (every route, every refusal and its exact text, the per-day limits, the batch rules, ids that pydantic reads as numbers,
`{{today:N}}` dates for the "not in the future" boundary, the settings the summary reads). `node tests/js/run_vectors.mjs` replays them and checks that a row of
another person is invisible and a 404 and the shape of the demo's sample data; `tests/test_body_vectors.py` fails when the file is stale;
`tools/e2e/parity.py` section 16 runs the same script against the live server and the demo in Chromium. The demo differs in two ways: no rate limit on the batch
routes, no body-size limit. **The demo's sample data** (`js/mock/seed.js`, note 10 §4.7): two weeks of morning weights (on hemodialysis the weights before and
after sessions) and readings, a sample alarm of 1 kg in a day (2 kg between sessions) and a sample goal of 130/80 "from the care team", today's weight over the
alarm and **no reading at 180/120**, so the demo never shows the emergency block unasked. The screens' own engine, `js/engine/body_ui.js` (`KH.bodyUi`), has no
server twin to keep in step (the server never parses what a person types or draws a chart); `tests/test_body_ui_numbers.py` runs it through `tests/js/body_ui_runner.mjs`
against the server's own models, settings and functions instead (a weight or reading is accepted or refused as `WeightCreate`, `BloodPressureCreate` and the settings
registry do, the units are `app.body.lb_to_kg` and `format_weight`, the visit prep sums are `app.body.six_month_change`, `blood_pressure_week` and `weight_alarm_check`).

## Visit prep

Was the ROADMAP item "Visit prep" (done 2026-10-15, so no longer listed there). A printable one-page summary for an appointment, made **in the browser from reads the app already
has**: no route, no table, no migration, no new server code, no twin to keep in step. Code: `js/views/visit.js` (the view
`#visit`), `js/engine/visitprep.js` (`KH.visitPrep`, pure), `css/visit.css`, the `#view-visit` section of `index.html`,
`visit` in `VIEWS` (`js/core.js`). It is reached from **Trends** (the period summary card's "Get ready for a visit" button);
it has no tab, so the bottom bar keeps its six. The demo shows it from its own data.

### What the page holds

* **The head**: "Visit summary", the person's **display name** only when they chose one (the name Settings already shows; never
  the username or anything else), the period (`Last 2 weeks`, `Last 4 weeks` (the default) or `Last 3 months`, as 14, 28 or 90
  days ending today) and the date it was made.
* **Averages** of sodium, potassium, phosphorus, protein and, when it has a target, fluid, **against the person's targets**:
  `GET /api/log/summary?start=&end=` (`app/periods.py summarize_period`, the numbers Trends shows) and nothing else. The page
  does no sum, average or percentage of its own (`averageRows` picks and words the server's `average`, `target`, `fraction`,
  `days_over`, `level`, `assessment`, `unknown_days` and `unknown_entries`; `tests/test_visit_prep_numbers.py` checks each
  against the endpoint for a seeded person and that the function has no arithmetic). It says how many of the days had food
  entries. A value that some foods do not list is **"≥ 1,433" with "N days with foods that do not list potassium (M foods): the
  average may be higher"**, and, when no food listed it at all, **"Not listed"** with the same counts: never 0, never "OK" (the
  level becomes `unknown`, "Not complete", as in Trends). A nutrient with no target is named under the list ("No target is
  set for ..."), not guessed.
* **Latest lab results**: `GET /api/labs?limit=1000`; per test (in `KH.labs.ANALYTE_ORDER`) the newest result as the Labs screen
  writes it (`display`: the entered value and unit and, when different, the converted one), its date, the result before it with
  its date, and an **arrow**: ↑ the newest value is higher than the one before, ↓ lower, → the same (compared on the server's
  rounded canonical `value`). The arrow has a screen-reader text and a line under the list says it does not say whether the
  change matters. **No interpretation and no ranges**: the page adds no normal range and no judgement of a result. The one
  existing warning is kept: the server's potassium alert (`alerts` of the same answer, the window the Labs screen uses) is
  drawn with `KH.labs.alertBanner`, as on the Labs screen, so a printed page never hides a current urgent potassium.
* **Symptoms**: `GET /api/symptoms?start=&end=`, grouped with `KH.symptomRules.summarise` (the Trends grouping): per symptom
  the days, the worst severity and the dates, a severe red flag first, and the handbook's line for the warning signs **drawn by
  `KH.symptoms.flagEl`**, the function the Today and Trends lists use (exported for this page), so the words are exactly the
  ones in "Symptoms log" above. Notes stay in the log.
* **Weight and blood pressure** (note 10 Part B): `GET /api/body/summary?date=` (the units, the alarm the person's care team gave, the goal, the latest weight),
  `GET /api/body/weights` for the last 366 days (the six-month change needs the half year before the latest weight) and `GET /api/body/blood-pressure` for
  the longer of the period and 30 days, with the profile's dialysis setting and dry weight (`KH.loadProfile`). `bodyPage` in `js/engine/visitprep.js` is plain arithmetic on
  the person's own rows, with the server's rules from `KH.bodyRules`: the **latest weight** and the **six-month change** (`sixMonthChange`; no verdict), on
  hemodialysis the **gains between the last sessions** (up to 6, newest first; each weight before dialysis against the latest weight after dialysis in the 7 days
  before it, else the dry weight in Profile; "over your alarm" only for a between-sessions alarm), the **7-day and 30-day averages** (whole numbers, half up) and the
  number of readings, **how many were at or above the goal** (a top number at or above the goal's or a bottom number at or above its) and the **readings the handbook
  points to** in the period with their dates and, once, the same block Today draws (`KH.body.flagBlock`, the server's words). `tests/test_body_ui_numbers.py`
  checks each against `app/body.py`. A read that failed says so.
* **My questions** and **a checklist**. See below.

A section whose read failed says so in the page ("The lab results could not be loaded ... Try again before you print"), so a
printed page never silently leaves a section out.

### Questions and the checklist: memory only

The person's questions (one line of plain text each, at most 300 characters, at most 20, no duplicates: `cleanQuestion`,
`addQuestion`) and the ticks of the checklist live in **the page's memory and nowhere else**: not `localStorage`,
`sessionStorage`, IndexedDB or a cookie, not the server, not the outbox, not the address bar, never the AI. They are gone on
reload and for another person who signs in on the same page (`S.owner`), and the page says so where they are written. This is
the least-trust option: a shared or lost device keeps nothing of them. (The cost is that a list must be printed or saved as a
PDF before leaving; a later opt-in "keep on this device" would be a decision for `docs/privacy.md` first.) A question that is
typed but not added is added when **Print / Save as PDF** is pressed. With no questions, the printed page shows three ruled
lines to write on.

The checklist is the "What to do" list of `handbook/docs/living/appointments.md`, word for word
(`KH.visitPrep.CHECKLIST`; `tests/test_visit_prep_ui.py` compares each line with the page), with a link to the page
(`/learn/living/appointments/`, through `KH.learn.href`, so no handbook means no link; `tests/test_learn_links.py` checks the path).
The app adds no clinical content of its own.

### Printing

**Print / Save as PDF** is `window.print()`, called from `js/views/visit.js` (no inline handler). `css/visit.css` `@media print`
(used only while `#view-visit` is the view showing, through `:root:has(#view-visit:not([hidden]))`) hides the skip link, header,
tabs, banners, toasts and dialogs and everything marked `screen-only` (the period buttons, the question box, Remove, the
handbook link), sets `color-scheme: light`, **black text on white whatever the theme** (the level icons black with white
glyphs), 9 pt text, 9 mm page margins and rows that are not split; the head puts the name and the period beside the title, the checklist
is three across, and the weight and blood pressure sentences run on as short paragraphs (the sub-headings and the closing note are for the screen).
For a typical person (five targets, four tests, a few symptoms) the page is **one sheet on A4 and on Letter**; with weights and readings logged it is
still one sheet on A4, and on the shorter Letter sheet the checklist and the closing line go **together** to a second one (a break rule keeps the
closing line from standing alone) (`tools/e2e/visitprep.py` makes the PDFs both ways and counts the sheets); a long symptoms or questions list
runs on to a second sheet. On screen it follows the light and dark theme and works at 375 px.

### Security and privacy

* Six reads of the app's own API, each already `current_user` and scoped by `user.id` (summary, labs, symptoms and the weight and blood pressure summary and lists), and
  the profile through `KH.loadProfile`; the view sends **no write and no other request** (`tests/test_visit_prep_ui.py` checks the code has no `fetch`, XHR or beacon and
  calls only `api.summary`, `api.labs`, `api.symptoms`, `api.bodySummary`, `api.bodyWeights`, `api.bloodPressures`; the Chromium harness checks that no write and no other host is asked).
* Nothing is sent to a provider: the view does not touch `KH.ai` or `/api/ai`, and `app/ai/`, `app/mcp/` and `app/guidance/`
  still never read symptoms, weights or readings, so the page adds no path for a symptom, a lab result, a weight, a reading or a question to an AI.
* Text goes in through `h()` children (`textContent`), never as HTML; no inline script, handler or style (CSP).
* No dosing, no insulin or medicine content, no new clinical number. Treating a low is not touched.

### Tests

`tests/test_visit_prep_ui.py` (shell, service worker, no inline code, `textContent` only, `window.print` wired from the file,
the print rules, no network and no storage in the view, the checklist against the handbook), `tests/test_visit_prep_numbers.py`
with `tests/js/visitprep_runner.mjs` (the endpoint's numbers through the engine, unknown values, labs, grouped symptoms, the
questions' limits), `tests/test_body_ui_numbers.py` for the weight and blood pressure section (against `app/body.py`), `python tools/e2e/visitprep.py` (Chromium at
375 px light and 1280 px dark, the demo, print emulation and PDFs), and `python tools/e2e/body.py` for the section with data.

## Assistant access tokens (assistant step 1, part A)

Spec `docs/dev/plans/assistant-step1.md` part A; code `app/auth/api_tokens.py`; schema step 10; operator and
user guide `docs/assistant.md`. A person makes a token for a chat assistant they connect; the assistant surface
(the MCP server at `/mcp`, part B) is the only place an **assistant** token is accepted. The same table, code and
rules also hold the **device** family (`khd_`, scope `body:write`, accepted only at `POST /push/v1/body`): see
"Device tokens and `/push/v1`" below for what differs. Where this section says "token" without a family it means
an assistant token.

### Switch

`assistant.enabled` (instance, bool, default **false**, env `ASSISTANT_ENABLED`; Server administration → Server
settings → "Optional AI"). Off: `GET /api/me/tokens` still lists (`enabled: false`) and `DELETE` still revokes,
`POST` answers `409`, and every bearer request is refused (`401`) before any lookup. On again: tokens that have
neither expired nor been revoked work again. Settings → **Assistant access** shows while the switch is on; while it
is off only to admins (where to turn it on) and to a person who still has active tokens (list and Revoke). The demo
shows one line saying the feature is in the installed app (no mock tokens).

### Table `api_tokens` (schema step 10, `m010_api_tokens.py`)

`id INTEGER PRIMARY KEY AUTOINCREMENT`, `user_id → users(id) ON DELETE CASCADE`, `name` (1–60 characters after
cleaning: NFC, no control characters, single spaces), `token_hash` (`UNIQUE`, the SHA-256 hex of the whole token),
`prefix` (its first 12 characters), `scopes` (space-separated known scopes: `assistant:read`; `assistant:log` for a
token made with `can_log` and `assistant:prefs` for one made with `can_prefs`, each always with `assistant:read` too and neither
giving the other; `body:write` for a device token; an unknown word
grants nothing, and a row that names scopes of both families grants nothing; a token's scopes are fixed when it is
made), `created_at`, `last_used_at`, `expires_at`, `revoked_at`. Index on `user_id`.

```json
TokenItem = {"id": 3, "name": "Open WebUI", "prefix": "kha_AbCd1234", "scopes": ["assistant:read"],
             "created_at": "…", "last_used_at": null, "expires_at": "…", "revoked_at": null,
             "state": "active" | "expired" | "revoked"}
```

* **Scopes of an assistant token** (`SCOPES`: `assistant:read`, `assistant:log`, `assistant:prefs`; `scopes_for(can_log, can_prefs)`).
  `parse_scopes` adds `assistant:read` for `assistant:log` and for `assistant:prefs` and implies nothing else: `log` does not give `prefs`
  and `prefs` does not give `log`. Each is a separate tick when the token is made (Settings → Assistant access: "Can also save food and
  recipes", "Also let it remember tastes (likes and dislikes)", both off by default; `POST /api/me/tokens` takes `can_log` and
  `can_prefs`, booleans; a scope is never sent by name). The family rules are as strict as before: `assistant:prefs` is an
  assistant-family scope, so a device token can never hold it, a row naming it together with `body:write` grants nothing, and
  `create_my_token` refuses `can_prefs` for a device token (400, `field: can_prefs`). Tokens made before the scope existed keep exactly
  the scopes in their row. The list item says what a token can do ("Read only", "Read and save", "Read and tastes", "Read, save
  and tastes"); `api_token.created` records `scopes`.
* A token is `kha_` + 43 base64url characters (`secrets.token_urlsafe(32)`). The plain token is in the `POST`
  answer only; no route returns it or its hash again, and log lines redact `kha_…` (`app/security.py`).
* At most 5 active (not revoked, not expired) tokens a person **in each family**; expiry 30, 90 (default) or 365 days; making one
  needs a recent password (like keys and the export) and is limited to 20 an hour (`ratelimit` `api_tokens`).
* The list holds active tokens and those that ended in the last 30 days, newest first; the daily housekeeping
  deletes older ended rows. Tokens are not in the export (a credential, like sessions).

### The bearer rule (`authenticate`, dependency `AssistantUser`)

* `Authorization: Bearer kha_…` is read **only** by `app.auth.api_tokens.authenticate`. `current_user` never reads
  it, so every `/api` route treats a request that carries only a token as anonymous (`tests/test_auth_coverage.py`
  walks every route with a valid token), and a token next to a session cookie changes nothing.
* Accepted when the switch is on, the token is well formed, its SHA-256 is stored, it is neither revoked nor
  expired, it has the route's scope, and its owner could use the app now under `AUTH_MODE` (`local`: a local
  account; `proxy`: a proxy account; `none`: user 1), active and not waiting for a password change.
* Every refusal is `401 {"detail": "A valid assistant token is required (Settings → Assistant access)."}` with
  `WWW-Authenticate: Bearer realm="kidney-health"` (plus `error="invalid_token"` when a bearer credential was
  sent): the same for every reason. A refused credential counts as a sign-in failure of the client address
  (`Throttle.ip_failure`: `LOGIN_IP_MAX_FAILURES` in 10 minutes block sign-in and tokens from that address for
  10 minutes; skipped for `TRUSTED_PROXIES` and gateway addresses); a blocked address gets `429` with
  `Retry-After`. No bearer header, or the switch off: `401`, not counted (nothing was guessed or looked up).
* On success `last_used_at` is written at most once a minute, and the route gets `request.state.user` and
  `request.state.api_token` (`TokenInfo`: id, user_id, name, scopes) for its own limits and logs.

### Revocation and the activity log

`revoke_all(conn, user_id, reason=…, actor_id=…)` ends every active token of a person on their own password change
(`password_changed`), a reset link or `python -m app.admin reset-password --stdin` (`password_reset`), an admin's or
the CLI's disable (`account_disabled`, enabling again brings none back), account deletion (`account_deleted`,
then the cascade removes the rows) and an admin's "Revoke tokens" in Server administration → People
(`POST /api/admin/users/{id}/revoke-tokens`, reason `admin`); all of these end **both families**. A change of `AUTH_MODE`
since the last start (`meta.auth_mode`) ends every active token of **every** person, both families, at start-up
(`revoke_everyone` in `app/auth/bootstrap.py`'s `_auth_mode_changed`; reason `auth_mode_changed`, one `api_token.revoked` row per person with no actor, one log warning with the
count), because with `AUTH_MODE=none` anyone who can reach the server is user 1 and can make tokens. An admin's "must change password" stops tokens until the change, which revokes
them. Activity (both in the person's own activity list): `api_token.created` (target `api_token` id; details
`expires_in_days`, `scopes`, `family`) and `api_token.revoked` (by the person: target `api_token`, `reason: "self"`; by an
event: target `user`, `reason`, `count`). Never the token, its prefix or its name: audit rows keep ids. (The saves of
part C are the one place a token's name is kept: `assistant.food_logged` and `assistant.recipe_saved` below, and
`assistant.preference_set` for a taste.)

## Assistant MCP server (assistant step 1, parts B and C)

Spec `docs/dev/plans/assistant-step1.md` parts B and C; code `app/mcp/` (`server.py`: transport and JSON-RPC; `tools.py`:
the four read tools and, for a token with `assistant:log`, `log_food` and `save_recipe`; `measures.py`: household
measures; `preference_tool.py`: `set_food_preference`, below); guide `docs/assistant.md`; tests `tests/test_mcp.py`,
`tests/test_mcp_write.py`, `tests/test_mcp_prefs.py` and `tools/e2e/mcp_smoke.py`. No schema change, no new dependency, no JS twin (the
demo has no assistant). The in-app Ask chat's `set_food_preference` (food preferences, "Saving from the chat") stays in
`app/ai/chat_preference.py` and stays a card. An external assistant gets the same-named tool only with the separate scope
`assistant:prefs` (note 09 §4.8b): it lives in `app/mcp/preference_tool.py`, not in `tools.TOOLS`, because it reuses Ask's checks
(which import `tools`); `server.all_tools()` puts the list together and `Tool.needs` says which scope each tool needs.

### Transport

`POST /mcp` only: MCP Streamable HTTP, JSON-RPC 2.0, one JSON object in and one `application/json` answer out (no
SSE), stateless (no `Mcp-Session-Id`), `Cache-Control: no-store`. Protocol versions `2025-06-18` (newest) and
`2025-03-26`: `initialize` answers the client's `protocolVersion` when it is one of them, else `2025-06-18`. The
`MCP-Protocol-Version` header is accepted, never required or refused. Checks, in order (each answers before the
next runs):

| Check | Answer |
|---|---|
| Body over `MAX_BODY_BYTES` (as everywhere) | `413` |
| `Origin` present and neither the request's own origin nor `PUBLIC_URL` (`CsrfMiddleware`, exact path `/mcp`, every method) | `403 {"detail": "Cross-site request refused"}` |
| `assistant.enabled` off | `404 {"detail": "Not Found"}`, every method |
| `GET`, `DELETE`, `PUT`, `PATCH` | `405`, `Allow: POST` |
| A bearer token with `assistant:read` ("The bearer rule" above); a session cookie is never read | `401` with `WWW-Authenticate: Bearer`, or `429` for a blocked address |
| Per-token limit (`ratelimit` `mcp`): 60 requests a minute, every request counts (saving ones too), key `token:<id>` | `429` with `Retry-After` |

JSON-RPC:

* Not JSON (NaN, Infinity and invalid UTF-8 included) → HTTP 400, `{"jsonrpc": "2.0", "id": null, "error":
  {"code": -32700, "message": …}}`. Not one request object (a batch array, a string, no `"jsonrpc": "2.0"`, no
  method, an `id` that is null, a boolean or neither a string nor an integer) → HTTP 400, `-32600`.
* A notification (no `id`) or a client's response (`id` with `result` or `error`) → `202` without a body.
* `initialize` → `{protocolVersion, capabilities: {tools: {listChanged: false}}, serverInfo: {name: "kidney-health",
  title, version: <app version>}, instructions}` (call `safety_check` first, every number from the tools, never doses
  or lab interpretation; a token with `assistant:log` also gets `WRITE_INSTRUCTIONS`: read the items back and ask the
  person to confirm before saving, say what was saved after, and the confirmation never comes before treating a low).
  `ping` → `{}`. `tools/list` → the four read tools, `log_food` and `save_recipe` **only for a token that has
  `assistant:log`**, and `set_food_preference` **only for a token that has `assistant:prefs`**, with `name`, `title`, `description`, `inputSchema` (`additionalProperties: false`) and
  `annotations: {title, readOnlyHint: true, openWorldHint: false}` (the read tools) or `{title, readOnlyHint: false,
  destructiveHint: false, idempotentHint: false, openWorldHint: false}` (the two that save) or `{title, readOnlyHint: false,
  destructiveHint: true, idempotentHint: true, openWorldHint: false}` (the taste tool: it replaces or removes what was there); no
  `outputSchema`. A token with `assistant:prefs` also gets `PREFS_INSTRUCTIONS` in `initialize` (use it only when the person says a
  taste in this conversation, after reading it back; never infer one; never for an allergy; a new `request_key` per change; it has
  no part in treating a low).
* `tools/call` → `{content: [{type: "text", text: <the result as JSON>}], structuredContent: <the result>,
  isError: false}`. Wrong arguments (strict types, unknown keys refused) or a failing tool → `{content: [{type:
  "text", text: <short message>}], isError: true}`: the field and the rule, never a value (the server log has the
  exception). An unknown tool or `params` that are not an object → `-32602`; any other method → `-32601` (HTTP 200).
  Calling `log_food` or `save_recipe` with a token that lacks `assistant:log` → a tool result with `isError: true` and
  the text "This token can only read. The person can make a token that can also save in Settings → Assistant
  access." (checked before the arguments; nothing is saved). Calling `set_food_preference` with a token that lacks
  `assistant:prefs` → `-32602` "Unknown tool: set_food_preference", as if there were no such tool (nothing is said about the scope).
  A failure inside a saving tool answers "…could not save this time and nothing was saved…": every save is one transaction. A limit
  refusal inside a tool (the daily cap of `set_food_preference`) is that limit's own `429` with `Retry-After`, not a tool result.

### Tools

Every result is one object with `source: "kidney-health"` and `reminder: "Numbers come from the app; fetch them
again after any change."`. `Amount = {"value": number | null, "not_listed_by": n}`: `n` entries or items do not
list the value; `value` is `null` when `n > 0` and nothing that counts lists it (unknown is never 0).

* `safety_check {message: string ≤ 2000}` → `{action: "treat_low_first" | "get_help_now" | "none", say_first,
  matched: {low, emergency}, cards: [card with full_url], link?: "/learn/get-help-now/", full_link?}`. A low:
  `guidance.hypo.prefilter(message, hypo_dose_g)` with the person's `guidance.hypo_dose_g`; an emergency:
  `ai.features.red_flag` (note 04 G8, the words of the handbook's "Call 911 now" list) with `RED_FLAG_CARD`. Both →
  `get_help_now` with both cards in the AI pre-filter's order (Get help now, Treating a low). Absolute links use
  `PUBLIC_URL`, else the request's origin.
* `get_today {date?: YYYY-MM-DD}` (default `log.today_local()`, as `GET /api/log`) → built from
  `log.day_summary`, the function behind `GET /api/log?date=`: `{date, is_today, entries: {eaten, planned},
  targets_set, nutrients: {key: {name, unit, eaten, planned, eaten_and_planned: Amount, target?: {max, min, about,
  kind}, eaten_vs_target?, eaten_and_planned_vs_target? (when something is planned): {level, percent, left,
  over_by, within_tolerance?}}}, alerts, alerts_if_planned_food_is_eaten, pattern_alerts, about_tolerance_pct?,
  meal_carbohydrate?, dialysis?}`. `left = target − value` only when no entry misses the value and the total is not
  above the target (as Today's bar); `over_by = value − target`. `meal_carbohydrate` only when
  `log.has_meal_carb_goals(profile)`: `{goals_set, tolerance_g, meals: {meal: {goal_g, eaten_g, not_listed_by,
  treating_a_low_g, planned_g, left_g, over, over_if_planned_food_is_eaten}}, note}` (`over` from the app's own
  meal alerts; carbohydrate that treated a low never counts toward a meal). `dialysis` unless "none": `{type}`;
  hemodialysis adds `dialysis_days` (names), `is_dialysis_day`, `since_last_dialysis` (equal to `GET
  /api/log/summary`'s `interdialytic` for that end date) and `notes`.
* `search_foods {query: 1–100 characters, limit: 1–10 = 5}` → `{query, results: [{id, fdc_id, name, brand, source,
  in_app, serving: {description, grams}, units, nutrients_per_serving, warnings_per_serving, kidney_rating,
  notes}], usda: {searched, found? | detail?}, note?}`. First `foods.search_foods` (the person's own and linked
  foods and the built-in list); then, for the remaining room, FoodData Central through `foods.usda_credential` (own
  key, else the shared key and its quota; the hourly guard) and `foods.usda_search_records` (one search, never
  saved: `id: null`, `in_app: false`), each record mapped by `map_usda_record` and
  `stored_food_values`; a record whose `fdc_id` is already listed is skipped. `units`: `serving`, `g` when the
  serving weight describes the values (`foods.weight_known`), and the measures the serving description lists.
* `check_meal {items: [{food: 1–100, amount?: > 0, unit?: 1–40, food_id?, fdc_id?}] (1–20), date?, meal?: breakfast |
  lunch | dinner | snack}` → `{date, meal, saved: false, items: [{food, matched: {food_id, name, brand, source,
  in_app, fdc_id?}, how_matched: food_id | fdc_id | name | only_match, amount: {as_asked, servings, grams}, serving,
  nutrients, warnings, kidney_rating, counted_as_treating_a_low, note?}], unresolved: [{food, reason, question, alternatives?, units?,
  food_id?, name?}], totals: {key: Amount} | null, day_with_these_items?: {key: {name, unit, total: Amount, target?,
  level?, percent?, left?, over_by?}}, alerts?, pattern_alerts?, meal_carbohydrate?, notes}`.
  * Finding the food: `food_id` (`foods.fetch_user_food`; another person's own food is `unknown_food_id`), else
    `fdc_id` (a USDA food from `search_foods`; see "USDA foods by `fdc_id`" below), else the
    app's search on the words (filler words dropped; plural and singular merged; then, for up to 6 words, one word
    left out at a time, which is never certain). Certain only when exactly one candidate is named by the words: its
    exact name (commas included), a name without a comma, the first part of a "Noun, kind" name or its two first
    parts the natural way round ("Juice, apple" is apple juice; "Chocolate, milk" is milk chocolate, never
    "chocolate milk"); or when the search finds a single food with every word, whole and in that natural order
    (the brand before or after). Otherwise `several_matches` with up to 5 alternatives (the named ones first),
    never a guess. Other reasons: `no_match`,
    `unknown_unit`, `servings_only` (a food whose serving weight does not describe its values), `amount_too_large`
    (above `MAX_SERVINGS` or `MAX_GRAMS`).
  * The amount: `serving` (default 1), `g` (`log.resolve_servings`), or a measure the food's `serving_desc` lists
    (`measures.food_measures`: "1/2 cup, 4 fl oz (124 g)" → cup = 2 servings, fl oz = ¼ serving; a size serving
    such as "1 medium" also answers to a word of the food's name, "banana"). No other conversion: no cups to
    tablespoons, no mL to g, and "oz" never means "fl oz". A quantity and measure inside `food` ("white rice 1
    cup", "2 slices of toast") count when `amount` and `unit` are absent.
  * Values: `scale_nutrients(raw, servings)` (the log's snapshot rule) and `food_warnings(…, scope="in this
    amount")`. A `hypo_treatment` food counts as treating a low (`log.resolve_purpose`, the entry sheet's default):
    no carbohydrate warning and no meal carbohydrate.
  * Projection: the items as planned rows (meal `unassigned` when no `meal` is given) next to the day's own rows
    → `log.day_figures` (projected totals, status and alerts) and `log.day_pattern_alerts`; the same numbers as
    planning those entries (`tests/test_mcp.py`). `meal_carbohydrate` (a profile with diabetes, `meal` given):
    `{meal, goal_g, these_items_g, meal_with_these_items_g (eaten + planned + items, low treatments left out),
    treating_a_low_g, not_listed_by, left_g, over (the projected meal alert), tolerance_g}`.

### USDA foods by `fdc_id`

An item may name a USDA food by the `fdc_id` `search_foods` shows (`in_app: false`). `place_item` looks for the food
in the person's list first (`foods.fetch_user_usda_food`: a built-in food carrying that id, or a USDA food they
imported; nothing is fetched). Otherwise it fetches FoodData Central's record for that id through the same key
resolution, hourly guard and SSRF-checked transport as `search_foods` (`foods.usda_credential`, `foods.usda_record`)
and maps it as an import would (`map_usda_record`, `foods.usda_unsaved_row`: the `foods` row it would store, as a
dict, `id: null`). `check_meal` stops there: nothing is added, the item says it is not in the person's list yet.
`log_food` and `save_recipe` add it to the list inside their transaction with `foods.add_usda_food` (the code
behind `POST /api/foods/usda/import`: the one shared `usda` row for the id, updated in place or inserted, linked to
the person) and then use the saved row by its new food id. A failed lookup is an `unresolved` item
(`usda_unavailable`: no key, not shared, quota or hourly guard, USDA error; `unknown_fdc_id`: USDA has no such
food). `food_id` wins over `fdc_id` when both are given.

### Writes (scope `assistant:log`)

Both tools place their items with `place_items` (the code `check_meal` uses; an unresolved or ambiguous item is
never guessed) and are all or nothing: if any item is unresolved the answer is `{saved: false, unresolved: […],
notes}` (plus the date, meal and status, or the recipe's name) and **nothing** is written, USDA additions included. Otherwise `write_once` runs one `BEGIN IMMEDIATE`
transaction: USDA foods added to the list, the rows saved by the existing code, one audit row, commit; any exception
rolls everything back. Nothing is edited or deleted; a repeated call saves again unless it carries the same
`request_key` ("Retries" below).

* `log_food {items: (1–20, as check_meal), meal: breakfast | lunch | dinner | snack, date?, status?: eaten |
  planned = eaten, purpose?: hypo | none}` → `{saved: true, date, meal, status, entries: [{entry_id, date, meal,
  status, food_id, food_name, servings, grams, nutrients (unknown null), purpose, counted_as_treating_a_low}],
  added_to_foods: [{food_id, fdc_id, name}], totals: {key: Amount}, day: <get_today's answer for that date>, notes}`.
  Each entry is made by `log.insert_logged`, the function behind `POST /api/log` and `/api/log/batch`, from a
  `LogCreate` (so the date, amount and food-visibility rules are the log API's: `validate_date`, no future limit,
  `servings`/`grams` bounds; an amount in `g` is stored as grams like the API). `purpose` goes through
  `log.resolve_purpose` as in the API: `hypo` marks food eaten to treat a low (counted in the day's totals, never
  toward a meal's carbohydrate goal, never warned about or held back), `none` clears the automatic mark of a
  `hypo_treatment` food, and left out keeps that automatic mark. Saved entries carry no `warnings` or
  `kidney_rating`. `day` is `get_today` run after the commit; if it fails the answer still says `saved: true`
  (`day: null`, with a note).
* `save_recipe {name: 1–60, ingredients: (1–30, as check_meal items), servings: > 0 and ≤ 100, source_url?}` →
  `{saved: true, meal: {id, name, note, items: [{food_id, food_name, servings, serving_desc, nutrients}]},
  servings_made, source_url, totals_whole_recipe: {key: Amount}, totals_per_serving: {key: Amount},
  added_to_foods, notes}`. The saved meal (`meals.insert_template`, `meal_hint` null) holds the ingredients for the
  **whole recipe** in `items_json`, the count in `servings_made` and the link in `source_url` (schema step 21; before it
  the count and the link were the note `Makes N serving(s). Source: <url>`, and step 21 reads them back from that
  sentence). `source_url` is an `http`/`https` address with a host, at most 900 characters, with no whitespace, control
  character, user name or password; it is stored as text and **never fetched**. The note is left empty. `totals_per_serving` is the whole-recipe total divided by
  `servings` (arithmetic only; unknown stays unknown).
* Activity: `assistant.food_logged` (target `api_token` id; details `via` (the token's name), `entries`, `status`,
  `meal`, `date`, `foods_added`) and `assistant.recipe_saved` (target `meal` id; details `via`, `name`,
  `ingredients`, `servings`, `foods_added`), both in the person's own activity list. They keep the token's name
  because the person needs to know which assistant saved; never the token or its prefix. A refused or unresolved
  call writes no row.

### Remembering a taste (scope `assistant:prefs`; note 09 §4.8b)

Code `app/mcp/preference_tool.py`; tests `tests/test_mcp_prefs.py`, `tests/test_assistant_ui.py`, `tools/e2e/mcp_smoke.py`. One tool,
`set_food_preference {food_id | category, preference: like | less | not_for_me | clear, request_key}`: exactly one of `food_id` and
`category`, `request_key` required (the same 8 to 64 characters as `log_food`'s), `neutral` not offered (the person's "stop learning"
switch is not a taste). The schema is Ask's (`chat_preference.INPUT_SCHEMA`) plus `request_key`.

* **Checks** are Ask's own, extracted from `chat_preference` and shared (`resolve_food`, `resolve_group`, `held_preference`,
  `group_state`, `check_food_room`, `check_group_room`, `unchanged`): a food the person may use (`foods.fetch_user_food`: another
  person's food and an unknown id give the same words), a category of the person's (`foods.visible_categories`, matched ignoring case
  and spacing), the 1,000 / 500 / 50 limits told to the model, and a request that changes nothing changes nothing.
* **A low treatment is never narrowed.** `not_for_me` is refused (an `isError` result that says only the person can do it, in the app;
  nothing written, no key, no audit row, not counted) for a food flagged `hypo_treatment` and for a food group that holds such a
  food visible to the person. The person's own "Not for me" and "Never suggest" leave `hypo_options` and `best_hypo_food` (note 09 §8
  Q1, with its floor), so an assistant's would have changed what a person reads when they are low. `like`, `less` and `clear` are
  allowed (never read there). The module reads no low-treatment code (`hypo`, `swaps`, `insights`, `messages`; a test reads its names).
* **The write** is one `BEGIN IMMEDIATE` transaction (`begin_immediate`): a food through `guidance.api.apply_preference(conn, user_id,
  food_id, preference, 'assistant')`, the code `PUT /api/guidance/preferences/{id}` runs (it returns the previous value and does not
  commit; `_store_preference` is it plus the transaction), `clear` through `drop_preference` (`DELETE`); a food group by reading the
  person's `guidance` setting and writing it whole through `SettingsStore.update_user`, moving only that group among the three lists
  (what the page does with `PATCH /api/me/settings`; an env lock or an invalid value is told to the model); then, only if something
  changed, the audit row; then the `request_key`; then commit. A group has no `source` (the setting does not carry one).
* **Audit** `assistant.preference_set` (target `api_token` id, actor the person, in the person's own activity list): details `via` (the
  token's name), `kind` (`food` or `group`), `name`, `old` and `new` (`none | like | less | not_for_me | neutral`; `new` is `none` for
  `clear`), `food_id` for a food. A request that changes nothing writes no row and leaves the person's own row (and its `source`) as it was.
* **Retries.** The key is stored as for `log_food` (`assistant_request_keys`, tool `set_food_preference`, `saved_json` `{kind, name,
  preference}`; no migration). A second call by the same token with the same key within 24 hours is looked up first (before the
  checks and the cap): `{saved: true, duplicate: true, target, preference, note}` where the note says nothing was changed again; it is
  not a new change, and the same key on another tool is refused as before.
* **Limits.** The per-token 60 requests a minute (every request counts), and **30 changes a day per token**: `ratelimit`
  `mcp_prefs`, a sliding 24 hours keyed `token:<id>`, taken after validation, the low-treatment rule and the duplicate lookup, before
  the write (so refused calls and retries do not count; a repeat of the same value that passes does). Past it: `429`, `Retry-After`, `{"detail":
  "Too many changes from this assistant today. Try again later.", "retry_after": n}`. In memory, so a restart empties it, like the other limits.
* **The answer** is `{saved: true, target: {kind, name}, preference, note}` (plus `duplicate: true` for a retry), about 400 characters:
  what was set (`Remembered: Salmon (food): less often.`, a group's `not_for_me` is "never suggest"; `Cleared: nothing is saved for the food
  Salmon now.`) and where to undo it (Settings → Meal guidance → Your food preferences, or "→ Kinds of food" for a group). It carries
  no other food, no preference list and no previous value, and no `source` or `reminder` key (there are no numbers in it).
* **Seen in the app.** Settings → Meal guidance → Your food preferences lists a row with `source = 'assistant'` as "from your
  assistant" (the list shows no token name) with the usual Remove / Suggest again (`views/guidance.js` `SOURCE_NOTE`); the activity list
  says "Assistant remembered a taste" with the name, `old → new` and the token's name (`views/settings.js`). `GET /api/guidance/preferences`
  answers `source: assistant`, `export.json` carries it and `ImportFoodPreference` accepts it (`mock/import.js` and
  `tests/data/import_vectors.json` follow). The browser sees no new route and the demo no new shape.
* Ask never runs this tool (`Call.asker` set → refused) and a token never changes Ask. Ask's **Undo** of a card that replaced a row the
  assistant set puts that row back with `source: assistant` (the PUT takes the three sources), so the label survives an undo.

### Retries (`request_key`, schema step 11)

Chat clients retry tool calls, so `log_food` and `save_recipe` take an optional `request_key` (string, 8–64 characters
of `A–Z a–z 0–9 _ -`; anything else is an `isError` result and saves nothing). The tool descriptions and the server
instructions tell the model to send a fresh key per intended save and to reuse it only to retry that save. Code
`app/mcp/request_keys.py`; without a key nothing changes.

* Table `assistant_request_keys` (`m011_assistant_request_keys.py`): `key_hash` (`PRIMARY KEY`, 64 hex characters:
  the SHA-256 of the token's id and the key, never the key), `user_id → users` and `token_id → api_tokens` (both
  `ON DELETE CASCADE`), `tool`, `saved_json` (`{"entry_ids": […], "added_to_foods": […]}` for `log_food`,
  `{"meal_id", "servings_made", "source_url", "added_to_foods"}` for `save_recipe`), `created_at`.
* The key is written **inside the save's transaction** (`write_once`), so a failed or unresolved save stores no key and
  a successful one always does. A second call by the **same token** with the same key within **24 hours** saves
  nothing, writes no audit row and answers `{saved: true, duplicate: true, …}` in the shape of the first answer, with a
  note ("a call with this request_key already saved this; if this was a different save, call again with a new
  request_key"). The entries (or the saved meal) are read from the database again for that person
  (`fetch_entry` / `fetch_template` are scoped by `user.id`), so it shows edits; deleted rows are left out with a note,
  and when none is left the answer is `{saved: false, duplicate: true, notes}` and **nothing is saved again** (a new
  key saves). `day` is `get_today` for the entries' date, as for a fresh save. The items of the repeat are not
  compared with the first call's.
* A retry that raced the first call and was waiting for the write lock finds the key inside the transaction, rolls
  back and answers the same way. The same key on the other tool is an `isError` result.
* Every lookup is scoped by `user_id`, `token_id` and the hash, so another token or another person with the same key
  text is independent. Rows older than 24 hours are ignored, deleted by the next keyed save and by the daily
  housekeeping (`purge_old`, like `api_tokens.purge_ended`). The person's activity is unchanged: a duplicate is not a save.
* The in-app Ask chat saves through the same two functions with `request_key` made from its own `request_id` and no token:
  `request_keys.find` / `remember` with `token_id=None` use `assistant_ask_keys` (schema step 13, "Saving from the chat"
  above); the MCP side is unchanged.

### Not in parts B and C

The assistant (through a token) cannot edit or delete anything, apart from the one value `set_food_preference` replaces or clears
for a token with `assistant:prefs`; no MCP resources or prompts; no
activity-log row per read call (the token's `last_used_at` is the trace); the demo has no assistant.


## Device tokens and `/push/v1` (phone shortcuts; design note 12, schema step 19)

Spec `docs/dev/research/12-phone-push-tokens.md`; code `app/push.py`, the device family in `app/auth/api_tokens.py`, `context_for`,
`is_watch_source` and the same-reading check in `app/body.py`, `app/migrations/m019_body_token.py`; guide `docs/push.md`; tests
`tests/test_push.py`, `tests/test_device_tokens.py`, `tests/test_migration_m019.py`. A person makes a **device token** in Settings and
pastes it into a Shortcut on their phone; the Shortcut sends the latest weight and blood pressure to the person's own server. The
token can **only add** weights and readings to its owner's log: it reads nothing, changes nothing and deletes nothing. The server is
described first; "The screens" below is the Settings "Phone shortcuts" block, the "from a shortcut (name)" label on the weight and blood
pressure screens, the admin's "Revoke tokens" and the demo's twin (code `js/views/settings.js`, `js/views/body.js`, `js/views/body_trends.js`,
`js/engine/body_ui.js`, `js/mock/auth.js`; tests `tests/test_push_ui.py` with `tests/js/push_page.mjs`, `tests/test_settings_ui.py`,
`tests/test_body_ui.py`, `tools/e2e/push.py`; the handbook recipe is "From a phone shortcut" on `handbook/docs/app/weight-and-blood-pressure.md`).
No new dependency, no JS twin of `/push` (no browser code calls it: the Shortcut does).

### The second token family (`app/auth/api_tokens.py`)

Same table `api_tokens`, same hash-only storage, expiry, housekeeping, `revoke_all` and generic 401; no schema change for the tokens.

| | assistant | device |
|---|---|---|
| prefix and pattern | `kha_` + 43 base64url characters | `khd_` + 43 base64url characters |
| scopes | `assistant:read`; `assistant:log` and `assistant:prefs` (each implies read only) | exactly `body:write`; never the person's choice |
| instance switch | `assistant.enabled` (`ASSISTANT_ENABLED`) | `push.enabled` (`PUSH_ENABLED`) |
| accepted at | `POST /mcp` | `POST /push/v1/body`, and `GET /push/v1/check` to test it |
| made in | Settings → Assistant access | Settings → Phone shortcuts |

* **Families do not mix.** `authenticate(request, conn, scope)` derives the family from the scope the route asks for and, before any
  lookup, checks that family's switch and that the presented token has that family's prefix pattern. A `kha_` token at `/push` and a
  `khd_` token at `/mcp` are the generic 401 of their surface and count toward the address's sign-in limit like any wrong token.
  `parse_scopes` never lets one family's scope imply the other's, and a stored row naming scopes of both grants nothing. The 401 text
  differs by surface (`A valid device token is required (Settings → Phone shortcuts).` at `/push`).
* **Per family**: at most 5 active tokens a person (`MAX_ACTIVE`), expiry 30, 90 (default) or 365 days. The 20-an-hour limit on making
  tokens (`api_tokens`) and the recent-password rule are shared by both.
* **Routes**: `GET /api/me/tokens?family=assistant|device`, `POST /api/me/tokens` with `family` (default `assistant`: the Assistant
  access screen is unchanged), `DELETE /api/me/tokens/{id}` (either family), `DELETE /api/me/tokens/{id}/body-rows` (below). A device
  token's list item is a `TokenItem` plus `sent: {weights, readings}`: how many rows it sent that are still in the log (the Settings block
  names the count before "Delete what it sent"). A device token's `POST` answer carries `"sent": {"weights": 0, "readings": 0}` and
  `pair_url` (below).
* **Revoking**: `revoke_all` (password change or reset, account disabled or deleted, the admin's "Revoke tokens") ends **both families**;
  `GET /api/admin/users` shows `assistant_tokens` and `device_tokens` counts. `api_token.created` is audited with `family`.
* **The switch** `push.enabled` (instance, bool, default **false**, env `PUSH_ENABLED`; Server administration → Server settings →
  "Phone shortcuts"; the group is the one line added to `js/views/settings.js`). Off: `GET` still lists (`enabled: false`) and `DELETE` still
  revokes, `POST /api/me/tokens` with `family: "device"` answers `409`, and `/push/v1/body` gives the generic `401` to every request with
  no lookup and no count toward the sign-in limit. On again: tokens that have not expired or been revoked work again.

### `GET /push/v1/check` (the token check, note 15 §4.3)

The iPhone app's **Test connection**. The same checks as `POST /push/v1/body` up to the per-token limit: `Origin` (`403`, the path is in
`BEARER_PATHS`), any method but `GET` (`405`, `Allow: GET`), the device token with `body:write` (the generic `401`; switch off: the same,
no lookup) and the shared `push_body` hour of the token (`429`). Then `200 {"ok": true}` with `Cache-Control: no-store`. It reads no body,
stores nothing but the token's `last_used_at`, and names nothing of the person. Tests: the check section of `tests/test_push.py`.

### Sharing (`app/sharing.py`, design note 19)

A person (the owner) makes a link in Settings → Account → Sharing; someone with an account on the same server (the grantee) accepts
it, then reads the areas the owner ticked. Every route needs a session and answers 404 while `sharing.enabled` (instance, default
**off**, env `SHARING_ENABLED`) is off and in `AUTH_MODE=none`.

| Method and path | Auth | Body → response |
|---|---|---|
| `GET /api/shared` | user | → `{people: [{id, name, username, areas, since, until}]}`: who shares with you, while their account is active |
| `DELETE /api/shared/{id}` | user | → 204: stop seeing it; audit `share.ended` (`by: grantee`) in the owner's activity; 404 if not yours |
| `POST /api/shared/info` | user | `{code}` → `{name, username, areas, days, expires_at}` without using the link up; a wrong, used, cancelled or expired link (or one from a turned-off account) is the generic 404 "That link does not work. Ask for a new one."; your own link is 400; 20 tries an hour per account and per address (`share_link`) |
| `POST /api/shared/accept` | user | `{code}` → 201 the item of `GET /api/shared`; a newer link from someone who already shares with you ends the old share (`ended_by: replaced`); 409 when the owner already shares with 10 people; audit `share.accepted` in the owner's activity |
| `GET /api/shared/{id}/profile` | any area | → `{name, ckd_stage, dialysis, diabetes, dialysis_days, week_start, weight_kg, targets}` (`SharedProfile`: no date of birth or other profile field) |
| `GET /api/shared/{id}/log?date=`, `/log/range?start=&end=`, `/log/summary?start=&end=` | `food` | as `GET /api/log`, `/api/log/range` and `/api/log/summary` answer the owner |
| `GET /api/shared/{id}/labs` | `labs` | as `GET /api/labs` |
| `GET /api/shared/{id}/body/summary`, `/body/weights`, `/body/blood-pressure` | `body` | as the owner's `/api/body/*` |
| `GET /api/shared/{id}/symptoms` | `symptoms` | as `GET /api/symptoms` |

* **One check.** Every `/api/shared/{id}/…` read goes through `shared_owner(area)`: the row is the signed-in person's share, active,
  both accounts active, and the area was shared. It returns the owner's `User`, and the handler calls the owner's own route function
  with it, so the answer is exactly the owner's and no query is written twice. Anything else is one 404 `"Not shared with you."`.
  There is no write route under `/api/shared` (`tests/test_sharing.py` lists the methods).
* **The link** is in the URL fragment, like invites: 16 hex characters of id and a 256-bit verifier, only the SHA-256 of which is
  stored (`hmac.compare_digest`). Accepting clears the link's fields, so it works once.
* **Activity.** The first read of a share each UTC day sets `last_viewed_at` and writes `share.viewed`. Rows that concern the owner
  target the owner (`target_type: user`), so they land in the owner's activity; the owner's own actions target the share.
* **Shared day loading.** The shared food-day read starts when the Visit page opens, independently of other summary reads.
  A per-box request guard discards older success and failure replies when changing date or person. Failure offers Retry for
  that person and date. Separate day boxes can load independently.
* **End date.** `accept` sets `ends_at` from the link's `lasts_days` (schema step 25). `expire(conn)`, run by every sharing route
  and the admin's count, ends each share past it (`ended_by: owner`, the owner chose the date) with `share.ended` (`by: time`, no
  actor) in the owner's activity. A newer link that replaces a share brings its own end date.
* **Health-card loading.** Trends' symptom and weight/blood-pressure cards clear old content before a new read,
  including when changing people or periods. The body-chart redraw cache clears too. Failed reads show Retry;
  only the latest request can replace the loading, error or completed state.
* **Admin.** `GET /api/admin/users` has `shares` (active shares and unused links the person is on either side of);
  `DELETE /api/admin/users/{id}/shares` *(re-auth)* ends them all → `{ended: n}`.
* **Screens.** `js/views/sharing.js` draws the Settings block and takes `#/share/<code>` into memory at page load (the address bar is
  cleared), then asks in `#sheet-share` once someone is signed in; nothing is accepted before **Accept**.
  Checking another link clears the old Accept code; late info/accept responses or focus callbacks cannot change a newer
  or closed question. **Open** shows the Visit
  prep page (`js/views/visit.js`) in its shared mode: the reads come from `KH.sharing.reads(id)`, headings and the banner name the
  owner, parts that were not shared say so, and a day card lists one day's food. The page has no control that writes.
  **Trends** opens `js/views/trends.js` in its shared mode (`KH.views.trends.openShared`): the charts and period summary read
  `reads.range` / `reads.summary`, `KH.symptoms.trends` and `KH.bodyTrends.show` take the share as `source`, the `#trends-shared`
  banner names the owner, and the CSV export, the insights card and the Visit prep link are hidden. The Trends tab, or any other way
  in, shows the signed-in person's own data. Shared weight charts use only the owner's profile for the dry-weight line.
  If that profile cannot be loaded, omit the line; never fall back to the viewer's profile, including on resize.
  A new Trends food request clears the old charts, tooltip and period summary
  before loading, including when changing people or periods. Failure shows an unavailable message and Retry; an older
  request may not replace the latest loading, error or completed state.

### Pairing the iPhone app (`app/pairing.py`, note 15 §4.3)

A device token's `POST /api/me/tokens` answer has `pair_url`: `kidneyhealthsync://pair?v=1&server=<origin>&token=khd_…` (scheme
`brand.PAIRING_SCHEME`, every value percent-escaped). `server` is `public_base` (`PUBLIC_URL`'s origin, else the request's). It is `null`
unless that is `https://` and a host of letters, digits, dots and hyphens with an optional port, the only form the app takes. It is shown
once, like the token, and is never in the list. Settings → Phone shortcuts draws it as a QR code with `KH.twoStep.qrSvg` (the vendored
`qrcode-generator`), or says why there is none. The iPhone Camera opens the app with it (`CFBundleURLTypes` in
`ios/KidneyHealthSync-Info.plist`); the app asks "Pair with <host>?" and saves only on **Pair**. `KidneyHealthCore` `Pairing.parse`
must read a link exactly as `pairing.parse` does: `tests/data/pairing_vectors.json` (`tests/data/gen_pairing_vectors.py`) has the links
the server makes and 50 it refuses (another scheme or fixed part, a fragment, a field twice, missing or extra, another version, a server
with a path, user, query or IPv6 literal, a token of the wrong shape, spaces or controls). Tests: `tests/test_pairing.py`, the pairing
checks of `tests/test_push_ui.py` and `tests/test_ios_app.py`, `PairingVectorTests.swift`.

### `POST /push/v1/body` (`app/push.py`, router outside `/api`, like `/mcp`)

`Authorization: Bearer khd_…`, `Content-Type: application/json`:

```json
{"weights":  [{"at": "2026-10-22T07:15:00-04:00", "value": 154.3, "unit": "lb", "source": "Health"}],
 "readings": [{"at": "2026-10-22T07:20:00-04:00", "systolic": 122, "diastolic": 78, "source": "Omron Connect"}]}
```

Checks, in order (each answers before the next runs):

| Check | Answer |
|---|---|
| Body over `MAX_BODY_BYTES` (1 MiB, the middleware); `Origin` present and not this server's own or `PUBLIC_URL` (`CsrfMiddleware`, exact path `/push/v1/body`, every method; the cookie checks do not apply: no cookie is read) | `413` / `403 {"detail": "Cross-site request refused"}` |
| Any method but `POST` | `405`, `Allow: POST` |
| A device token with `body:write` ("The second token family"); a session cookie is never read | the generic `401` with `WWW-Authenticate: Bearer` (switch off: the same, no lookup), or `429` with `Retry-After` for a blocked address |
| Per-token limit (`ratelimit` `push_body`): **60 requests an hour**, key `token:<id>`, every request that got this far counts | `429` with `Retry-After` |
| `Content-Type: application/json` | `415` |
| Body of at most **32 KiB** (from `Content-Length` before anything is read, and counted while it streams) | `413` |
| One JSON object (strict: NaN, Infinity, invalid UTF-8 refused); **at most 50 rows** in `weights` and `readings` together; unknown fields refused (`extra="forbid"`: `pulse`, `glucose`, `insulin` and every other kind are 400s); at least one row | `400` |
| Every row valid, **all or nothing**: the first invalid row is a `400 {"detail": "weights.0.at: …"}` naming it | `400` |
| Per-day limits (20 weights, 30 readings per person and date), counting rows the person typed or imported | `400 "weights.8: too many weights for one day (max 20)"`, nothing written |

* **`at`**: ISO 8601 date and time **with its zone** (`2026-10-22T07:15:00-04:00` or `Z`; a space for the `T`, no seconds, a fraction of a
  second (dropped) and an offset such as `-0400` or `-04` are also read, so the Health export's own `2026-10-22 07:15:00 -0400` works).
  The row's `date` and `time` are the **wall clock as written**, not converted. No zone is a `400` ("send the time with its zone"): its
  wall clock would be a guess. A date more than one day after the server's today, or before 1900, is a `400` (the models'
  `validate_past_date`). Digits are ASCII only.
* **`value`** (weights): a JSON number (read as it is, so `154.29999999999998` works), or a plain decimal string, 1 to 3 digits, optionally a point
  and 1 to 3 more (`"154.3"`; not `"1e2"`, `"-5"`, `"1,5"`); `unit` is exactly `kg` or `lb`; `kg = lb × 0.45359237`, rounded half up to 0.01 kg (`lb_to_kg`, `round_kg`), then
  the range of `WeightCreate` (20 to 400 kg). **`systolic` and `diastolic`**: a JSON integer or a string of 1 to 3 digits (`122.0` is read as
  122; a fraction is a `400`); the ranges and `systolic > diastolic` are those of `BloodPressureCreate`. Each row is checked **by the same model
  classes as `POST /api/body/weights` and `/blood-pressure`**, so the rules cannot drift.
* **`source`**: 1 to 60 characters after cleaning (NFC, no control characters, single spaces). It is not stored; it goes into the
  `source_key` and tells a watch from a cuff.
* **Context from the clock time** (`body.context_for(kind, time)`, the Apple Health reader's rule; not the person's choice here):
  weight `morning` from 04:00 to 10:59, else `other`; reading `morning` 04:00 to 10:59, `evening` 17:00 to 23:59, else `other`.
  `KH.appleHealth.contextOf` is held to it by `context_cases` in `tests/data/body_vectors.json`.
* **Watch-like readings are refused, not stored**: a reading whose `source` contains "watch" in any letter case
  (`body.is_watch_source`, the reader's `isWatchSource`; `watch_cases` hold both to the same answers) is counted as `refused.watch`. The import
  sheet starts such readings unticked; a Shortcut has no review step, and note 10 does not recommend cuffless devices for checking blood
  pressure. A weight from a watch is kept. A watch reading must still be a valid reading (else `400`).
* **Rows written** (one transaction, `BEGIN IMMEDIATE`): `source = 'shortcut'`, `api_token_id` = the token, no note, `context` as above.
  `source_key` = the first 32 hex characters of the SHA-256 of **the text the Health export reader builds** (note 10 §4.8):
  `HKQuantityTypeIdentifierBodyMass|<at as YYYY-MM-DD HH:MM:SS +HHMM>|<value as sent>|<source>` or
  `BloodPressure|<at>|<systolic>/<diastolic>|<source>`. When the Shortcut's value and source text match the export's, a later import of
  the export skips the row by key (`tests/test_push.py` rebuilds every key text of `tests/data/apple_health_vectors.json`).
* **The same reading** (`known_weight_marks`, `known_reading_marks`): a row is "already there" when the person has the same `source_key`, or
  a row **not `manual`** with the same date, `HH:MM` and kilograms (a reading: the same two numbers), whatever its key. Rows of the
  request count for later rows of the same request. The two batch import routes apply the same check and count such a row as `skipped`,
  so push-then-import and import-then-push each leave one row. A `manual` row never matches (a person may type the same reading twice on
  purpose) and a row with no time cannot match. The browser twin is in `js/mock/body.js` (checked by the body vectors).
* **The answer is counts only**: `{"added": {"weights": n, "readings": n}, "already_there": {"weights": n, "readings": n}, "refused":
  {"watch": n}}`, `Cache-Control: no-store`. No row, id, flag, name or value is echoed, so a token reads nothing. **Values are never logged**: the
  log line is `push: token <id> added … weights and … readings, … already there, … refused`.

### Storage and "Delete what it sent" (schema step 19, `m019_body_token.py`)

`weights.api_token_id` and `blood_pressures.api_token_id` (`INTEGER REFERENCES api_tokens(id) ON DELETE SET NULL`; NULL for every earlier row
and every row not sent by a token) and two partial indexes `(user_id, api_token_id) WHERE api_token_id IS NOT NULL`. Purging a token 30 days
after it ended sets the column to NULL and **keeps the row** (still `source: shortcut`, with `via: null`); deleting the account deletes rows
and tokens. `GET /api/body/*` rows carry `via` (the token's name, joined on the token **and** its owner); `PUT` on a row makes it `manual`
and clears `api_token_id`.

`DELETE /api/me/tokens/{id}/body-rows` (`current_user`, scoped by `user.id`, a token that is not the person's own **device** token is
`404`; no recent password needed) deletes the rows whose `api_token_id` is that token and the person's id, in both tables, in one
transaction: `{"deleted": {"weights": n, "readings": n}}`, audit `body.token_rows_deleted` (target `api_token`, details `weights`, `readings`;
in the person's own activity list). It works for a revoked or expired token that is still in the list. The token that sent the rows cannot
call it (it is a session route).

### Export, import, privacy

`api_token_id` and `via` are **not exported** (server-local ids); `source: "shortcut"` and the `source_key` are, and import like the other
sources (`BodySourceKey` accepts it; imported rows have no token). Rows sent by a token are never read by `app/ai/`, `app/mcp/` or
`app/guidance/` (the same test as for the rest of the log), and are never sent to an AI provider.

### The screens (note 12 §4.4 to §4.6)

* **Settings → Account → Your data → Phone shortcuts** (`pushBlock` in `js/views/settings.js`, after the Apple Health import block; ids
  `set-push`, `set-push-body`, `set-push-name`, `set-push-expiry`, `set-push-create`, `set-push-list`): in the style of Assistant access, but
  always present. It says what it is for ("A shortcut on your iPhone can send your latest weight and blood pressure here. Its token can only
  add readings: it cannot see your log."), links the handbook's recipe (`KH.learn`, `…/weight-and-blood-pressure/#from-a-phone-shortcut`; the plain
  words where the handbook is not served), lists the person's device tokens (name, `khd_` start, created, last used or "never used", expires,
  and "sent 1 weight and 1 blood pressure reading" from `sent`) and, while the switch is on, the form: a name (60 characters), an expiry
  (30 days, 90 days, 1 year; 90 to start) and Make token. Making a token is `POST /api/me/tokens` with `family: "device"`; the recent
  password rule is the one `request()` already handles (the "Enter your password again" sheet opens and the call is repeated). **The token is
  in that answer only**: the page keeps it in one variable until a draw has put it on screen, shows it once with **Copy token** and the
  address to send to (`location.origin` + `/push/v1/body`, with its own Copy address), and a later draw never has it. A token that could not
  be drawn because the list failed to load is still shown. At 5 active tokens the form is replaced by one line.
* **Revoke** asks in the page (`confirm.inline`) and says what stays; **Delete what it sent** is offered for any listed token with rows
  still in the log (an ended token too: the lost-phone order is Revoke, then Delete), asks naming the count and the token ("Delete the 1 weight
  and 1 blood pressure reading that “Morning weight” sent? Weights and readings you typed or imported yourself stay. This cannot be undone."),
  calls `DELETE /api/me/tokens/{id}/body-rows`, forgets the loaded Today and Trends data and says what it deleted.
* **Switch off** (`enabled: false` in the list): "Turned off on this server" and "Your admin has not turned this on."; no form; tokens that
  are still listed can be revoked and their rows deleted (and the block says they do not work while it is off); an admin sees where the switch
  is. Turning the switch on or off in Server administration redraws the block and the People list.
* **Weight and blood pressure rows**: `KH.bodyUi.originText(row)` words the origin from `source` and `via`: "from a shortcut (NAME)" (or "from a
  shortcut" when `via` is null: the token was purged), "from the Health app", "from a file"; nothing for a typed row. Today draws it as a
  `.body-origin` span next to the time, and the Trends tables add a "From" column while some row of the period has an origin. Every word
  goes through `textContent` (`h()`), so a token named with markup shows the markup. Visit prep shows no per-row sources and is unchanged.
* **Admin** (Server administration → People): the revoke button shows while `assistant.enabled` or `push.enabled` is on and the person
  has an active token of either family (`assistant_tokens + device_tokens` of `GET /api/admin/users`), labelled "Revoke tokens (n)". The
  Activity log labels `api_token.created` / `api_token.revoked` by `details.family` ("Phone shortcut token created / revoked"; the
  self-revoke audit row now carries `family`) and `body.token_rows_deleted` ("Phone shortcut data deleted", with the counts).
* **The demo** (`?mock=1`, `js/mock/auth.js`): the block says "The preview has no server to send readings to…" and draws no form and no
  list, and makes no request. For parity the mock answers `GET /api/me/tokens?family=assistant|device` like a server with the switches off
  (`enabled: false`, no tokens, a bad family is 400), `POST /api/me/tokens` is refused with 409 and the preview's words, and
  `DELETE /api/me/tokens/{id}` and `…/body-rows` are 404. `tools/e2e/parity.py` section 10 compares all of these with the server; the admin
  user list of the mock has `device_tokens: 0`.
* **Not built**: a webhook out, push notifications and any watching of the readings by the app. A reading sent by a shortcut is checked
  when the app is opened, like any other; the handbook says so and points to Get help now.

### Security review

| Threat | Answer |
|---|---|
| A token leaks (a shared Shortcut, a lost phone) | add-only: 50 rows a request, 60 requests an hour, plausible ranges, 20 and 30 rows a day; last use is visible; Revoke, then Delete what it sent; expiry at most 365 days; every token ends on a password change |
| False readings planted to alarm or mislead | only inside the ranges and day limits; each row is marked `shortcut` with the token's name; nothing is acted on automatically; the 180/120 flag is shown when the app is opened, as for any reading |
| A token used elsewhere | prefix pattern and scope checked before lookup: `/mcp` refuses `khd_`, `/push` refuses `kha_`, every `/api` route ignores `Authorization` (`tests/test_auth_coverage.py`, `tests/test_api_tokens.py` use a token of each family) |
| Guessing | 256-bit tokens, hash lookup, the generic 401, the address throttle (`429`) |
| CSRF / a web page posting | no cookie is read; a cookie-only request is `401`; a foreign `Origin` is `403`; no CORS |
| A leak through the answer or the log | counts only; the log line holds the token's id and counts |
| Health-data rules | only weights and blood pressure; every other kind is a `400` by `extra="forbid"`; no glucose, insulin or medicines; nothing goes to an AI provider or the assistant |

### Versioning and what comes later

`/push/v1` is a promise: a breaking change gets `/push/v2` and v1 keeps working for at least one release. Later scopes (`log:write`,
`labs:write`, `symptoms:write`) would follow the same pattern: one family or scope, one versioned route under `/push/`, add-only, counts-only
answers. The ROADMAP's native iOS app would post HealthKit samples to this route with a `khd_` token kept in the Keychain. Its rules
are in the Swift package `ios/KidneyHealthCore` (design note 15 §4.1): the ranges, the context, the watch rule, the kilogram rounding, the
`source_key` and requests of at most 50 rows. It has no dependencies and no HealthKit code, so CI tests it on Linux against
`tests/data/body_vectors.json`, `apple_health_vectors.json`, `push_vectors.json` and `pairing_vectors.json`. The app checks each row as
this route does before sending, because one refused row makes the whole request a `400`.

## The API document and `GET /api/meta` (design note 14 changes 2 and 4)

Design note 14 (§3, §4 changes 2 and 4, decided in §6) asks for what a second client needs first: a document of the API that is true, kept in
the repository and checked, and a route that tells a client what this server offers. Nothing else about any route changes; the ids and the
document are the only things rewritten. The guide for people who write programs against the server is [`docs/api/README.md`](docs/api/README.md).

### The document (`app/openapi_doc.py`, `scripts/gen_openapi.py`, `docs/api/openapi.json`)

* **A snapshot, checked.** `python scripts/gen_openapi.py` builds the app in-process (a temporary `DATA_DIR`, no server, no network, the
  caller's environment left out) and writes `docs/api/openapi.json`: sorted keys, 2-space indent, a trailing newline. `--check` exits `1` with a
  short list of what differs (operations and components added, removed or changed) when the committed file is stale, like the vector
  generators' `--check`; `tests/test_openapi_snapshot.py` runs it, so a changed route fails the suite until the file is regenerated and committed.
  `ENABLE_API_DOCS` is unchanged: the live `/openapi.json` and `/docs` stay off by default, and when on they serve the same document.
* **Operation ids** (`generate_unique_id_function=openapi_doc.operation_id`): `<first tag>_<route function name>`, the tag left off when the
  name already starts with it (`auth_login`, `log_create_entry`, `meta_info`). The default (`login_api_auth_login_post`) carried the path and
  the method and changed when a route moved. A test asserts they are unique; the two routes that register one function for several methods
  (`/mcp`, `/push/v1/body`) name their ids with `operation_id=`.
* **Validation errors are `400`**, with the body `security.validation_error_handler` sends (`{detail, errors: [{type, loc, msg}]}`,
  schema `ValidationProblem`). FastAPI's 422 (`HTTPValidationError`) is removed from every operation; the one 422 a route really returns
  (`GET /api/profile/suggested-targets`, out of scope, `{detail, code}`) is declared by the route and stays.
* **One error shape.** `Problem` is `{detail: string, ...}` with the keys routes add (`reason`, `field`, `code`, `problems`, `retry_after`,
  `reauth_required`, `password_change_required`, `setup_required`, `https_required`, `locked_by_env`). Shared `components.responses` carry it:
  `BadRequest` (400), `Unauthorized` and `BearerUnauthorized` (401; the second has `WWW-Authenticate`), `Forbidden` (403), `NotFound` (404),
  `Conflict` (409), `PayloadTooLarge` (413), `UnsupportedMediaType` (415), `TooManyRequests` (429, `Retry-After`), `MethodNotAllowed` (405) and
  `Error` (the `default` of every `/api` operation and of `POST /push/v1/body`). A log entry's `412` keeps its own words and gains
  `EntryConflictProblem` (`{detail, current: Entry}`); `POST /mcp`'s `400` is a JSON-RPC error object (`JsonRpcError`).
  Which operation lists which status follows from how the app is built, not from a guess per route: `400` where FastAPI would have added its
  422 (the operation has parameters or a body); `401` and `403` on every route that depends on `current_user` (the CSRF and `Origin` checks
  make `403` true of every unsafe `/api` call and of both bearer routes); `404` where the path has a parameter, where `require_ai_enabled`
  gates the route, and on `/mcp`; `413` on `POST`/`PUT`/`PATCH` (the body limit); and a short reviewed table in `openapi_doc.py` (`CONFLICT`,
  `UNSUPPORTED_MEDIA`, `RATE_LIMITED`, by operation id) for the `409`, `415` and `429` that only a handler knows. A status a handler raises that
  these rules miss is still described by `default`. The 405 stubs of `/mcp` and `/push/v1/body` say `405` (and `404` for `/mcp` while assistant
  access is off), not the `200` FastAPI would show.
* **Security schemes** (`components.securitySchemes`; an operation's `security` is read from its dependencies, not from its path):

  | Scheme | Type | Routes | Notes |
  |---|---|---|---|
  | `session` | `apiKey` in a cookie, `kh_session` (`__Host-kh_session` over HTTPS, named in the text) | every `/api` operation that depends on `current_user`: all of them except `GET /api/auth/status` and `POST /api/auth/{login,setup,register,reset,reset/info}` | the text also says every unsafe `/api` request needs `X-Requested-With: kidney-health` |
  | `assistantToken` | `http` bearer, `kha_` + 43 characters | `POST /mcp` | while `assistant.enabled` is on; no cookie is read |
  | `deviceToken` | `http` bearer, `khd_` + 43 characters | `POST /push/v1/body`, `GET /push/v1/check` | while `push.enabled` is on; no cookie is read |

  The 405 stubs, `/healthz` and `/sw.js` have none. `openapi_doc.BEARER_OPERATIONS` is held equal to `security.BEARER_PATHS` by a test, and the
  routes without `security` under `/api` are held equal to the public list of `tests/test_auth_coverage.py`.
* **Versions.** `info.version` is `APP_VERSION`; `info.x-api-version` is `API_VERSION` (`app/api_version.py`, `1`). **Raise it on a breaking
  change** (removing or renaming a route, a field, an enum value or an id; making an optional request field required; narrowing what a request
  may hold; changing a type, a meaning or a status), never for an additive one (a new route, an optional request field, a field or enum value in
  an answer, a capability key, a documented error). `/push/v1` has its own version in its path. The rule is written in `app/api_version.py` and
  `docs/api/README.md`.
* **Not covered yet**, and said so in the guide: no request schema for the routes that read a raw body (`/mcp`, `/push/v1/body`, the photo
  routes, `/api/ai/transcribe`, `/api/me/import`), and some answers are untyped objects. Filling them in is additive.

### `GET /api/meta` (`app/meta.py`)

Signed in only (`current_user`; an anonymous caller gets the generic `401`, so a server's features are not listed to strangers). Not cached
(`no-store` like every `/api` answer). The answer:

```json
{"app_version": "0.10.0", "api_version": 1,
 "capabilities": {"ai": false, "ai_next_meal": false, "ai_parse_meal": false, "ai_label": false, "ai_plate": false, "ai_lab_report": false,
                  "chat": false, "voice": false, "assistant": false, "push": false,
                  "barcode": false, "barcode_off": false, "barcode_usda": false, "handbook": false},
 "nutrients": [{"key": "calories_kcal", "label": "Calories", "unit": "kcal", "role": "goal"}, "... 12 in all, in registry order"],
 "meals": ["breakfast", "lunch", "dinner", "snack"]}
```

* `capabilities` are booleans: true when **this person can use the thing now**. Each is read from an existing switch or status function and
  worked out nowhere else: `ai`, `ai_next_meal`, `ai_parse_meal`, `ai_label`, `ai_plate`, `ai_lab_report`, `chat`, `voice` from
  `app.ai.routes.status_view` (the body of `GET /api/ai/status`: `available` and `features`; all `false` while `ai.enabled` is off, when that route
  is a `404`), so they follow the admin switches, the person's opt-in, each feature's route, `ai.chat_enabled`, `ai.voice_enabled` and the speech
  server; `assistant` and `push` from `api_tokens.is_enabled` (`assistant.enabled`, `push.enabled`); `barcode_off` (the admin switch `food.off_enabled`
  **and** this person's `food.off_consent`) and `barcode_usda` (`food.usda_branded_barcode` **and** a USDA key this person can use) from
  `barcode.providers_available`, `barcode` being either (a person's own foods are found by barcode with neither); `handbook` from
  `handbook.info(...)["available"]` (the server serves the built handbook at `/learn`; a `HANDBOOK_PUBLIC_URL` alone is `false`).
  A new capability is a new key: an additive change.
* `nutrients` is `nutrient_core.NUTRIENTS` in the server's order (`key`, `label`, `unit` `kcal`/`g`/`mg`/`mL`, `role` `goal`/`range`/`track`/`limit`/`info`);
  `meals` is `nutrient_core.MEALS`.
* **No secret, no host, no key and nothing of another person.** There are no provider names, addresses, models, counts, tokens or settings values,
  only the booleans above; two people on one server get the same answer until their own choices (opt-in, consent) differ. `tests/test_meta.py`
  configures every kind of key and token and greps the answer for them and for the words `key`, `token`, `secret` and `password` (the only `key`
  is the name of a nutrient's field).
* **Not used by the screens yet.** The pages still read the nutrient labels and order from `js/engine/rules.js` and `js/core.js`; moving them to
  this route is the second step of design note 14 change 4 (ROADMAP "Open items").
* **Parity.** The demo answers the same route from `js/mock/meta.js`: no AI, no assistant or phone-shortcut tokens, no USDA key, no handbook of
  its own; Open Food Facts follows the demo's own settings, as its barcode lookup does; the nutrients and meals come from `js/engine/rules.js`.
  `tests/data/meta_vectors.json` (`tests/data/gen_meta_vectors.py`, pytest `--check`-style) is the server's answer on a fresh server (the API version, the
  capability keys and values, the registry and the meals; `app_version` left out) and `node tests/js/run_vectors.mjs` replays it on the demo;
  `tools/e2e/parity.py` section 10 compares the shape, the registry and the capabilities of both sides on a real server.

## Brand strings (design note 14, change 3)

The strings that say which product this is are in one file, `app/brand.py`. The page uses a few of them, and their copy is
`app/static/js/engine/brand.js` (`KH.brand`). A second product built on this code changes them there and does not have to search
for them. Gathering them changed no value.

* **Compatibility surface.** Some strings are already stored, sent or remembered by something outside the process. Each constant in
  `app/brand.py` says whether it is one. They are the cookie names (`kh_session` and its `__Host-` form, `kh_device`), the
  `X-Requested-With` value, the `X-KDL-Version` header, the token prefixes `kha_` and `khd_`, the iPhone app's link scheme, the bearer realm, the database file
  `kidney.db`, the backup prefix, the `format` of `export.json`, the MCP server name and `source`, the HKDF labels (`kidney-health/v1/...`),
  the logger root and, in the browser, the IndexedDB name `kdl`. Changing one on an install in use signs people out, breaks tokens, makes
  stored API keys unreadable, starts an empty database or turns away the export files people kept. Names and display texts (`NAME`, `SCREEN_NAME`, `SLUG`, the User-Agent
  texts, the CSV file name) are not.
* **Written out in full.** No value is built from another, so changing the product name never moves a compatibility string. A new
  product picks its values before its first start and keeps them.
* **No imports.** `app/brand.py` imports nothing, so `config`, `crypto` and `security` can use it. Where `brand` is also a food's field
  (`foods.py`, `off.py`, `data_import.py`, `mcp/tools.py`) the module imports the names, not the module. The old module-level names
  (`sessions.COOKIE_HTTP`, `api_tokens.PREFIX`, `account.EXPORT_FORMAT` and so on) stay and now point at the constants.
* **The browser's copy.** `KH.brand` holds `name`, `screenName`, `slug`, `logCsvPrefix`, `csrfHeaderValue`, `versionHeader`, `exportFormat`
  and `idbName`. It loads last of the engine files in `index.html`, right before `js/core.js`, and is in the `sw.js`
  precache list; `scripts/build_preview.py` reads `index.html` and needs no list. `idbName` is the one value Python does not have.
* **Left alone, on purpose.** Migration steps (released steps are never edited); the three AI prompts, which say "Kidney Health" (prompt
  text is pinned by the golden tests); `APP_WORDS` in `app/auth/policy.py` and `js/mock/auth.js`; the `Literal` of `ExportFile.format`
  (it needs the text itself); the MCP `INSTRUCTIONS` sentence; the start-up password self-test text; the Trusted Types policy names
  (`kh-sw`, `kh-xml`, `kh-pdf`), which `security.py` and three scripts name together; the other `kdl-` names in the browser (local storage
  keys, cache names, the Web Lock, `kdl-demo-local`), because `sw.js` and `theme-init.js` run outside `KH` and those names are in people's
  browsers already; the vector-checked twins `js/engine/settings.js` and `js/engine/off.js`; and the static files (`index.html`,
  `manifest.webmanifest`, the style sheets), which cannot import anything.
* **Tests.** `tests/test_brand.py` pins every constant, checks that each site still produces its value (the HKDF labels against a known
  answer, the cookie and token names, the export README and file name, the API document), checks that `KH.brand` agrees with `app/brand.py`
  where they overlap and loads before its readers, and fails when one of the main literals (`kh_session`, `kha_`, `khd_`, `kidney.db`,
  `kidney-health`, ...) appears in `app/` or `app/static/js/` outside the two brand files and an allowlist of the places above.

## Offline edits and deletes (ROADMAP; note 02 R5 "Queueable offline actions")

Editing an entry already on the server (its amount, meal, day, eaten or planned, note) and deleting it wait in the outbox like
a new entry does. The rule is **never overwrite silently**. Profile, target, lab and settings changes stay online-only (least
trust: a care team's targets must never be overwritten by a stale offline copy); they say "… it needs a connection" as before.
No schema step: nothing is stored for any of this.

### Entry version and `If-Match` (`app/log.py`, `Entry` in `app/models.py`)

* **`Entry.version`** (every route that answers an entry: the day, `POST`, `PUT`, `/batch`, `/quick`, copy-day, saved meals
  apply and from-log): 16 hex digits, FNV-1a (64 bit) over a canonical text of what the person sees and edits.
  The text is, in order, `date`, `meal`, `food_name`, `servings`, `grams`, `note`, `status`, `purpose` and the 12 nutrient values
  (registry order), taken from the entry JSON (so already rounded: servings 3 decimals, grams 1, nutrients as shown), each as
  `~` for none, `n<number>;` (a whole number without a point, else Python's shortest repr) or `s<UTF-8 byte length>:<text>`.
  The same content has the same version on every device and server: `id` (the address), `food_id` (never changes for an
  entry, and differs between servers), `client_id`, `created_at` and `updated_at` are not in it, so an edit that is undone
  elsewhere is no conflict. It is a change token, not a secret. FNV and not SHA because the demo (`js/mock/log.js`
  `entryVersion`, synchronous, no Web Crypto) must give the identical value.
* **`PUT /api/log/{id}` and `DELETE /api/log/{id}`** take an optional **`If-Match: "<version>"`** (RFC 9110 §13.1.1, strong
  comparison: a quoted or bare tag, a comma list, or `*` for "any entry that exists"; a weak `W/"…"` or an empty value never
  matches). Order of the checks: sign-in and CSRF, the body (400), the entry is the person's and exists (**404, with or without
  a valid version, so another person's entry is not revealed**), then the version. A mismatch answers **412
  `{"detail": "This entry was changed on another device", "current": <Entry as stored now>}`** and changes nothing. With the
  header the write is `… WHERE id = ? AND user_id = ? AND updated_at = <the row that was checked>`, so a request that gets in
  between the check and the write also answers 412 (or 404 when it deleted the entry). **Without the header both routes behave
  exactly as before** (last write wins), so every existing client works.
* The export (`export.json`) drops `version` (derived, so a new export stays importable by an older server); the import accepts
  and ignores it. The CSV is unchanged. Documented in the OpenAPI schema (`If-Match` header parameter, the 412 response).

### The outbox (`js/offline.js`, hooks in `js/core.js`)

* **What the client sends.** `api.updateEntry(id, body, entry)` / `api.deleteEntry(id, entry)` pass the entry as the person
  saw it: `KH.request` sends `If-Match: "<entry.version>"` (only a hex string is ever put in a header) and hands `entry` to the
  hooks as `opts.base`. An entry without a `version` (an old saved copy) is sent without the header, as before.
* **Queueing.** A failed or timed-out (6 s) edit or delete is queued, kind `edit` or `delete`:
  `{client_id, user_id, kind, method, path: "/api/log/<id>", entry_id, body, version, base: <entry as seen>, state, …}`; the
  caller gets the entry as it will look (`pending: true`) or `{pending: true}` for a delete. Without `opts.base` nothing is
  queued (there is no version to check) and the usual "needs a connection" message stands. The Ask chat's **Undo**
  is such a call (`deleteEntry(id)` with no entry), so it is never queued (`tests/test_ask_ui.py` pins the exact text of that API line). The queued body is cut to **what
  differs from the entry the person saw** (the entry sheet always sends the meal, day, status and note; `changedFields`), so
  "Use mine" never rewrites a field the person did not change, and a save that changes nothing queues nothing. **One item per entry:** a second
  edit joins the first (bodies merged, the original version kept, moved to the end of the queue so it still goes after a
  "mark eaten" queued in between), a delete replaces it, an edit of an entry with a delete waiting is "This entry no longer
  exists". `KH.net.intercept` sends an edit made while a change for that entry already waits into the queue even when online
  (the order the person acted in holds), and handles `pending:<client_id>` entries locally.
* **An entry that was made offline and is still waiting** (id `pending:<client_id>`): editing it **rewrites the queued create**
  (the same `client_id`, so it is still created exactly once) and deleting it **removes the queued create** with no request.
  If it has just been sent the person is told to open it again.
* **Today** draws what waits: an edited entry in its new form (amount and nutrients worked out from the food this device knows,
  else by scaling the entry's own numbers; warnings from the rules twin), a deleted one gone, one moved to another day on both
  days, all marked "waiting to sync" and counted in the totals (`withWaiting`, the same day maths as the demo). A waiting
  entry opens the editor like any other.
* **Replay** is FIFO under the same lock, one request per change, and stops at the first network error, 5xx, 429, 401 or 403
  like every other item. Each change is sent with its stored `version` as `If-Match`:
  * **2xx**: done and removed (the day is read again).
  * **404**: the entry is gone (or never was the person's; the server does not say which, nor does the app): "This entry no
    longer exists (<name>), so your change was dropped", the item is removed.
  * **412**: the entry changed on the server. If the server's `current` still equals the entry the change was made on (the
    eight fields above; this is the person's own queued "mark eaten" having been sent first, and queueing a mark updates the
    expected entries of the changes already waiting), the change is sent again **once** with `current.version`. Otherwise the
    item becomes a **conflict** (`state: 'conflict'`, `server: current`): nothing is sent, nothing is retried, the badge says
    "N to review", Today marks the entry "needs review" with the server's version (it opens Settings → This device, not the
    editor), and a toast says what happened.
  * **another 4xx** (for example 400): kept as "not saved" with the server's reason, Retry / Discard, as for a new entry.
* **A copy saved before versions existed** (an entry in this device's saved days that has no `version`, from before the
  upgrade) is queued without one. A change with no version is never sent unchecked: at replay the app reads that day from the
  server first (`GET /api/log?date=`, answered as the server has it, without what waits drawn on it) and compares the entry
  with the one the change was made on. Equal: the server's `version` is sent as `If-Match`. Different: a conflict card. Gone:
  "This entry no longer exists". The read failing: "not saved".
* **The conflict card** (Settings → This device, `conflictCard` in `js/offline.js`): "This entry was changed on another device
  while you were offline", the entry as the server has it ("Saved on your server") and the person's change ("Your change":
  the server's entry with the person's changes on top, which is what "Use mine" leaves) side by side (food, day, meal, amount,
  status, note; a value that differs is bold and underlined and said so to a screen reader; a delete shows "Delete <name>"),
  and two buttons. **Keep the saved one** drops the change. **Use mine** sends it again with
  the version the server has now; if the entry changed again meanwhile that is a new conflict, never an overwrite. All text goes
  in as text nodes (notes are the person's own words). An edit made online that gets a 412 (the entry was changed elsewhere
  since the day was read) becomes the same card (`KH.net.onConflict`) and the sheet closes with a message.
* The queue holds this person's items only; sign-out and **Clear offline data** remove it as before. Items are in the badge
  ("Offline · 2 to sync", "1 to review", the aria-label says "2 changes are waiting to sync") and the list.
* **Safety.** A low treatment (`purpose` `hypo`) is edited and deleted offline like any other entry: nothing in the queue, the
  card or the replay looks at the purpose, and nothing warns about or blocks treating a low. No clinical number is added.

### Parity and checks

* `entryVersion`, `versionMatches` and the `PUT` / `DELETE` routes of the demo (`js/mock/log.js`; `js/mock/core.js` passes the
  request headers to routes as `header(name)`) are checked against the server by `tests/data/entry_version_vectors.json`
  (generated by `tests/data/gen_entry_version_vectors.py`: 23 entries and their versions, 19 `If-Match` headers, one request
  script with its answers: match, 412 with the current entry, no header, `*`, a list, a weak tag, a bad body, a missing entry,
  deletes), replayed by `node tests/js/run_vectors.mjs`; `tests/test_entry_version_vectors.py` fails when the file is stale.
  `tools/e2e/parity.py` compares entries as before (`version` is the same on both sides).
* `tests/test_log_if_match.py` (server: version, match, 412, no header, 404 first, the race, export and import),
  `tests/test_offline_edits_ui.py` (static: queueable kinds, `If-Match`, the card's words and text-only rule, no inline script or
  style) and `tests/js/outbox_changes.mjs` (the queue logic in Node, with the demo API as the server: queue, coalesce, rewrite,
  replay with `If-Match`, 412 and both answers, 404, a mark queued first, profile and targets still online-only), and the
  `changes` section of `tools/e2e/device.py` (Chromium with `context.set_offline`: edit and delete offline, reload offline,
  reconnect, the conflict card and both buttons, a deleted entry, an entry made offline, "Eaten", a low treatment).

## Keep my data in this browser (demo only)

ROADMAP "Ideas from the owner"; user page [docs/demo.md](docs/demo.md). The Pages demo (`scripts/build_preview.py --pages`) answers every
`/api` call from the demo API in the page (`js/mock/*`). Normally that state is in memory and gone on reload. An **opt-in** mode stores
the whole state in the browser's IndexedDB so a person can use the demo as a small log without a server, with **export** and **import** of
`export.json` (the server's export format) so the data can later move to a real server through `POST /api/me/import`. The self-hosted
server stays the full version; this mode never exists in the installed app.

* **Off unless chosen, and only in the demo build.** `KH.mock.local.allowed()` is true only when `window.KDL_PREVIEW === true` (the Pages
  build and the self-contained preview) and the demo API is running; a development server's `?mock=1` page and the installed app never
  use it, never open the database (`boot`, `probe` and `enable` all start with `if (!allowed())`), and `KH.demoLocal` is an inert stub
  there. `js/main.js` calls `KH.mock.local.boot()` once, inside `if (MOCK)`, before the first request. Starting the demo only **looks**
  for a saved copy and never leaves a database behind (an upgrade means there was none, and is aborted); nothing is written until the
  person ticks **I understand** in the sheet and presses the button. `tests/test_demo_local_ui.py` checks the gating in the source and
  that the files that name `indexedDB` are exactly `offline.js`, `pwa.js` and `mock/persist.js`; `tests/js/demo_local_storage.mjs` checks it at
  run time (no database call at all with the flag off).
* **The sheet** (`index.html` `#sheet-demo-local`, `js/views/demo_local.js`, `css/demo-local.css`; opened from the banner's **Keep my data in
  this browser** button or from Settings → Your data) says, in this wording (checked by the static test): the data stays only in this browser
  on this device and nothing is sent anywhere; clearing site data, private browsing or the browser freeing space can delete it, export regularly;
  on a shared device others can see it (the demo has no real sign-in); for real use run your own server. "I understand" must be ticked.
  The person chooses to start from an **empty log** (`new MockApi({seed: false})`: a fresh server's account) or from the **sample data as it is
  now**. `navigator.storage.persist()` is asked for when it is turned on and the answer is shown (`persisted()` is read back at each start).
  **Stop keeping data here** asks in the page (`KH.confirm.inline`, no browser dialog), deletes the database and reloads into the in-memory
  sample demo. The banner reads "kept in this browser only" while it is on, shows a save error or conflict, and says why a copy was not loaded.
* **Storage** (`js/mock/persist.js`, `KH.mock.local`). One record, key `current` of object store `state` in database `kdl-demo-local`:
  `{format: "kidney-health-demo-local", schema: 1, rev, savedAt, foodsVersion, state}`; `state` is the own properties of the `MockApi` instance
  (Maps and Sets included, by structured clone; `_guidanceVectors`, a derived cache, is left out). `KH.mock.onWrite(api, method, path)` is called from
  `MockApi.request` after every non-`GET` that did not throw (an import's dry run does not count) and schedules a **debounced save** (1.5 s; also
  when the page is hidden). A copy is read at start (`applyState` replaces the instance's properties) before the first request. Rules:
  * `schema` is the shape of `state`. A copy with a **newer** schema, or one that cannot be read, is **not loaded and never overwritten or deleted**
    by this page (`status().blocked`; the banner and sheet say why; no turn-on, no stop). Changing the state's shape in a way an old copy cannot
    satisfy bumps `SCHEMA` and adds a step to `migrate()`; properties the mock creates lazily (`_auth`, `_labs`, `_symptoms`, `_weights`, `_readings`, `_settings`, ...) need none.
  * `rev` counts the saves. A save is **one transaction** that reads the stored record and writes the next revision only if the stored `rev` is the
    one this page loaded or wrote last (`'none'` when turning on): a second tab that saved first makes this page set `conflict`, **stop saving**
    and say so, so a tab never overwrites another's data. A failed save (quota, a refusing browser) sets `error`, keeps the data in the page and
    tries again after the next change.
  * **Every IndexedDB call is inside try/catch** and rejects with a plain sentence; with no IndexedDB, a `SecurityError` (private browsing, blocked
    site data, a sandboxed frame such as the claude.ai preview host) or a full disk the sheet says so and the demo stays in memory.
  * While the mode is on `KH.net.offlineNow()` is false (there is no server to be offline from), so writes go straight into the stored copy and
    never wait in the demo's in-memory outbox.
* **Export** (`js/mock/export.js`): `GET /api/me/export.json` is a demo-only route returning the document of `app/account.py export_data`: the
  same keys in the same order (`tests/test_demo_local_storage.py` compares them), `log_entries` without the derived `version`, `custom_foods`,
  `linked_foods` (`linked_at: null`), `meal_templates`, `lab_results`, `symptoms`, `weights` and `blood_pressures` in the export shapes, `food_preferences`, `builtin_foods`, the
  person's own settings and the activity list; the AI sections are empty and nothing secret is ever in it. The page downloads it as `export.json`
  (`KH.demoLocal.exportFile()`; Settings → Your data shows **Export my data (export.json)** while the mode is on, and says what is needed
  otherwise). The server's zip also has CSV files and a README; the demo gives the JSON only.
* **Import** (`js/mock/import.js`): `POST /api/me/import?dry_run=&merge=&replace_profile=` is the twin of `app/data_import.py` for the existing
  "Import from a file" screen (`js/views/settings.js`, which shows it instead of "no server to import into" while the mode is on). The same
  rules: `format` `kidney-health-export` version 1; **depth limit 32**; NaN/Infinity refused; every record kind a small schema (the server's pydantic models
  with `extra="forbid"`, strict types, bounded lists and strings) checked in the same order, so the **first problem is the same one**, named by record
  kind and position and never repeating a value; the `user` and AI sections accepted but never read; **`settings` carries over only the seven
  allowlisted keys** (`guidance`, `ui.theme`, `user.units.labs`, `food.scan_prefer_camera`, `user.units.weight`, `body.weight_alarm`, `body.bp_goal`) and only with `replace_profile` (`ai` and the consents never);
  ids remapped; an own food identical to one already there is reused; built-in foods found by FoodData Central id (older files: id and name);
  shared foods linked or kept as the person's own copy or reported; an account that has data is refused (409, or `can_import: false` on a dry
  run) unless `merge`; what is already there is left out; the profile and targets are replaced, not merged; a dry run runs the same code and puts
  every table back (`snapshotTables`/`restoreTables`). Size: the page's 16 MiB limit and a 413 in the route. **Parity:** `tests/data/import_vectors.json`
  is generated by `tests/data/gen_import_vectors.py` against the real server (about 240 requests: every kind of refusal, the flow, an older file, and
  what the account holds afterwards through the ordinary routes) and replayed by `node tests/js/run_vectors.mjs`; `tests/test_import_vectors.py`
  fails when it is stale and checks the twin's limits against `app/data_import.py`. Differences the browser cannot avoid (it has already run
  `JSON.parse`): a float written `2.0` is the integer 2, an integer beyond 2**53 is rounded, case folding uses `toLowerCase`.
* **A server fix found on the way:** the built-in list gives glucose tablets, gel and shots and the salt substitutes a negative `fdc_id`
  (`data/foods.json`), a copy keeps it, and `ImportFood` / `ImportBuiltinRef` required `fdc_id >= 1`, so an export of a log that used glucose tablets
  was refused by the import. `FdcId` in `app/data_import.py` accepts any database integer (a number that matches no food is "a built-in food this
  server does not have"); `tests/test_data_import.py` runs the round trip on the real list.
* **Files:** `js/mock/persist.js`, `js/mock/export.js`, `js/mock/import.js`, `js/views/demo_local.js`, `css/demo-local.css`, the banner button and the
  `#sheet-demo-local` dialog in `index.html` (all in `sw.js`'s shell list), `MockApi({seed})` and the `KH.mock.onWrite` call in `js/mock/core.js`, the boot
  hook in `js/main.js`, the Settings → Your data entry points in `js/views/settings.js`, `offlineNow()` in `js/offline.js`, `tests/js/fake_idb.mjs`,
  `tests/js/demo_local_storage.mjs`, `tests/test_demo_local_ui.py`, `tests/test_demo_local_storage.py`, `tests/test_import_vectors.py`,
  `tests/data/gen_import_vectors.py`, `tests/data/import_vectors.json`, `tools/e2e/demo_local.py`, `docs/demo.md`.
  The browser walk (`python tools/e2e/demo_local.py`, no server): nothing stored before the choice, the sheet's wording, turn on, add an entry, reload and it
  is still there, export, stop (confirm, cancel, delete), import into an empty log, two tabs, a browser that refuses IndexedDB, a newer copy, no request to
  another host, no console or CSP error, no sideways scroll.

## When a day fails to load (the 2026-10-29 review)

`loadDay` in `js/views/today.js` numbers each request (`dayRequest`); only the newest may draw. When it fails and the chosen day
was never drawn (`state.dayLoadedFor !== state.date`), `renderUnavailable` clears everything that belongs to a day (meals, alerts,
projected alerts, status bars, the all-totals list, the guidance cards) and shows a `role="alert"` card, "<date> could not be
loaded, so nothing is shown for it", with **Retry** (`#day-retry`, which calls `loadDay` again). A failed reload of a day already
on the page keeps it and shows a toast, as before. Symptoms and weight load on their own for the chosen day. Checked by
`tests/test_reliability_ui.py` and in Chromium by `tools/e2e/reliability.py`, which also checks the saved-meal "not listed"
values and the 100-serving limit of a fitted recipe.

## A failed save on a sheet (ROADMAP item 1)

Sheets open with `showModal()`, so an open sheet is in the top layer and the page under it is inert. A toast left in `body` was
drawn under the sheet and not read out. `toast()` in `js/core.js` now puts `#toast` into the open modal dialog (`toastHost`, the
last one when sheets are stacked), and `setupDialog` moves it back to `body` when that dialog closes. A failed save on a sheet
keeps the sheet open, what was typed and the button. Checked by `tests/js/reliability_ui.test.mjs` (run by
`tests/test_reliability_ui.py`) and in Chromium by `tools/e2e/reliability.py`, on the entry sheet, Plan's saved meal editor and
"Add to a day", Labs, Profile and the weight and blood pressure sheets.
