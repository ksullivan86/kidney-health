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

Non-goals (v1): multi-user accounts, insulin dose calculation, medical advice.
The UI must say that targets come from the person's care team.

## Stack

* Python 3.12, FastAPI, Pydantic v2, SQLite (stdlib `sqlite3`, no ORM), uvicorn.
* Frontend: static `index.html` + `app.js` + `style.css` served by FastAPI.
  **No build step, no CDN, no external requests from the browser.** Works offline on a LAN.
* One container image. All state lives in `DATA_DIR` (default `/data`) as `kidney.db`.
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
app/config.py               settings from env: DATA_DIR, USDA_API_KEY, APP_PASSWORD, FOODS_JSON
app/db.py                   sqlite connection helper + schema (idempotent CREATE TABLE IF NOT EXISTS)
app/models.py               Pydantic request/response models (shapes below)
app/nutrients.py            PURE FUNCTIONS: nutrient registry, per-serving thresholds, daily status, suggested targets
app/foods.py                food search/CRUD, builtin JSON import, USDA proxy
app/log.py                  log entries (eaten/planned), day/range/period summaries, mark-eaten, copy-day, CSV export
app/periods.py              PURE FUNCTIONS (v0.2): period averages, previous period, interdialytic interval, week bounds
app/meals.py                saved meals (templates), from-log, apply, shopping list (v0.2)
app/profile.py              profile + targets (+ dialysis days, week start)
app/static/index.html
app/static/app.js
app/static/style.css
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
deploy/compose.yaml         rootless compose (+ compose.caddy.yaml, compose.ai-ollama.yaml overlays)
deploy/quadlet/kidney-health.container
deploy/k8s/*.yaml (+ kustomization.yaml)   PSA restricted, NetworkPolicy, HTTPRoute
.github/workflows/ci.yml    pytest 3.12+3.14, JS parity, linters, image smoke test + Grype gate (never pushes)
.github/workflows/release.yml  build by digest -> scan -> sign/attest (public repo) -> tags (v0.3 decision 7)
SECURITY.md, docs/security.md, docs/https.md, scripts/verify-image.sh   (v0.3, deploy owner)
CHANGELOG.md                user-facing changes per version (v0.3)
tools/e2e/                  browser harnesses run by hand: parity.py, sandbox.py, regress.py (+ khserver.py, README.md)
pyproject.toml, requirements.txt, requirements-dev.txt, .gitignore
```

Owners (parallel build): **food-db** owns `scripts/`, `data/`; **backend** owns
`app/*.py`, `tests/`; **frontend** owns `app/static/`; **deploy** owns `deploy/`,
`.github/`, `docs/deployment.md`; **research** owns `docs/diet-guide.md`,
`docs/research/`. Nobody else edits another owner's files.

## Nutrient registry (single source of truth: `app/nutrients.py`)

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
| potassium_mg    | 101–200 mg       | > 200 mg                   | renal dietitian low/medium/high potassium food convention |
| phosphorus_mg   | 101–150 mg       | > 150 mg, or any food flagged `phosphate_additive` | NKF guidance; additive phosphorus is ~90–100 % absorbed |
| sodium_mg       | 141–400 mg       | > 400 mg                   | FDA "low sodium" ≤ 140 mg; 20 % DV ≈ 460 mg |
| carbs_g         | 15–30 g ("1–2 carb choices"), or flagged `high_gi` with < 15 g | > 30 g, or flagged `high_gi` with ≥ 15 g | type 1 carb counting; the GI upgrade needs one carb choice to act on (per-portion glycaemic load), so a condiment's 4 g is a note, not a red |
| protein_g       | 15–25 g          | > 25 g                     | large protein portion for restricted intake |

Flags (strings, set in curated data or by the user on custom foods):
`phosphate_additive`, `high_gi`, `counts_as_fluid`, `avoid_ckd` (e.g. star fruit),
`hypo_treatment` (fast carbs that are also low potassium, e.g. glucose tablets),
`low_potassium_fruit`, `processed`.

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

### Suggested targets (`nutrients.suggest_targets(weight_kg, ckd_stage, dialysis, diabetes, height_cm=None)`)

*Rewritten in v0.3 (note 05; see "M2 API: targets and labs" at the end of this file and
`docs/targets-and-labs.md`).* Starting points only; the UI labels them "discuss with your care team"
and nothing is saved until the person saves the profile. The rules live in `app/targets.py` (pure,
`today` injected) with every number, source and note text in `app/target_rules.py`;
`nutrients.suggest_targets()` keeps its v0.2 signature and `{"targets", "notes"}` shape for existing
callers and applies the same rules without the v0.3 inputs. `nutrients.dosing_weight()` returns the
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
`Cache-Control: no-store`; `/docs` and `/openapi.json` exist only with `ENABLE_API_DOCS=true`.

### Health
* `GET /healthz` → `{"status":"ok","foods": <count>}`

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
  "warn_fraction": 0.8,
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

### Log
* `GET /api/log?date=YYYY-MM-DD` → DaySummary
* `POST /api/log` body `{"date","meal","food_id","servings"?,"grams"?,"note"?}`
  (`servings` default 1; if `grams` given, servings = grams / serving_g) → Entry (201)
* `PUT /api/log/{id}` body any of `meal`, `servings`, `grams`, `note`, `date` → Entry (recomputes snapshot from the food;
  an entry that was logged by weight keeps its grams and re-derives servings from the food's *current* `serving_g`
  unless the body sets `servings`, so grams and servings always agree, as with copy-day)
* `DELETE /api/log/{id}` → 204
* `POST /api/log/quick` body `{"date","meal","name","serving_desc"?,"serving_g"?,"nutrients":{...},"servings"?,"flags"?}`
  → Entry; creates a `custom` food then logs it.
* `GET /api/log/range?start=YYYY-MM-DD&end=YYYY-MM-DD` → `{"days":[{"date", "totals": {...}, "status": {...}}]}` (one item per day, including empty days)
* `GET /api/log/export.csv?start=&end=` → CSV, one row per entry, all nutrient columns

```json
Entry = { "id": 5, "date": "2026-10-05", "meal": "breakfast", "food_id": 12, "food_name": "Banana, raw",
          "servings": 1, "grams": null, "note": null, "nutrients": {...multiplied...},
          "warnings": [...per-serving-style warnings evaluated on this entry's totals...],
          "kidney_rating": "red", "created_at": "...", "updated_at": "..." }

DaySummary = {
  "date": "2026-10-05",
  "entries": [Entry],                       // ordered by meal (breakfast, lunch, dinner, snack) then created_at
  "totals": { ...12 nutrient keys... },
  "targets": Profile.targets,
  "status": { "potassium_mg": {"value": 1800, "target": 2500, "fraction": 0.72, "level": "ok"},
              "protein_g":    {"value": 40, "target": 56, "min": 42, "fraction": 0.71, "level": "ok"}, ... },
  "meals": { "breakfast": {"carbs_g": 45, "protein_g": 12, ... all keys ...}, "lunch": {...}, "dinner": {...}, "snack": {...} },
  "alerts": [ {"level": "caution"|"over", "nutrient": "potassium_mg", "message": "Potassium is at 85 % of today's limit (2125 / 2500 mg)"} ]
}
```

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
echoed, because it could be a password, API key or setup code (note 07 §9 N4).

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
   meal / delete. A prominent **meal carbohydrate total** for each meal (type 1).
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
  "created_at": "...", "updated_at": "..."
}
```
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
   `deploy/Containerfile.debian` as the fallback (note 01 §5.1). CI tests on **Python 3.12 and
   the image's Python** (3.14 at the time of writing). The app must stay compatible with 3.11+.
7. **Image tags:** pushes to `main` publish `:edge` and `:sha-<short>`; `v*` tags publish
   `:latest`, `:X.Y.Z`, `:X.Y`. Signing, SBOM and provenance per note 01 §5.4; attestation steps
   that need a public repo are gated on `github.event.repository.private == false`. *(M1 review:)*
   the repository variable `HOLD_LATEST=true` keeps `:latest` where it is on a `v*` tag. v0.2's
   Quadlet unit tracked `:latest` with `AutoUpdate=registry` and a shell `HealthCmd`, which loops
   (kill, restart) under the shell-less v0.3 image; **owner decision before tagging v0.3.0**: hold
   `:latest` on the last v0.2 digest for a while, or rely on the upgrade warnings in CHANGELOG.md,
   README.md and docs/deployment.md.
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
| 7 | `m007_barcode.py` | barcode-vision (M2) | note 03 R6 (food `gtin`, `source='off'`, `barcode_cache`, attribution fields) |

## Backend file ownership

| Milestone / owner | Files |
|---|---|
| M1 backend-core | `app/config.py`, `app/db.py`, `app/migrations/**` (steps 1–3), `app/security.py`, `app/auth/**`, `app/settings_registry.py`, `app/settings_store.py`, `app/crypto.py`, `app/credentials.py`, `app/audit.py`, `app/account.py` (export/delete), `app/admin.py` (CLI), `app/healthcheck.py`, `app/pwa.py` (note 02 R6: `/sw.js`, manifest/icon headers), `app/main.py`, `app/models.py`, user scoping edits in `app/foods.py`, `app/log.py`, `app/meals.py`, `app/profile.py`, `app/periods.py`; `requirements*.in/.lock`, `pyproject.toml`, `scripts/lock.sh`; `tests/**` except frontend-owned tests |
| M1 deploy | `deploy/**`, `.github/**`, `.hadolint.yaml`, `.dockerignore`, `scripts/verify-image.sh`, `SECURITY.md`, `docs/security.md`, `docs/https.md`, `docs/deployment.md`, `docs/network-allowlist.md` |
| M1 frontend | `app/static/**`, `scripts/build_preview.py`, `scripts/build_icons.py`, `requirements-tools.txt`, `tests/test_preview_build.py`, `tests/js/**`, `docs/install-on-your-phone.md` |
| Handbook (parallel) | `handbook/**`, `scripts/build_handbook.py`, `tests/test_handbook_content.py` |
| M2 targets | `app/targets.py`, `app/target_rules.py`, `app/kidney_function.py`, `app/units.py`, `app/labs.py`, `app/migrations/m004_*`, `suggest_targets` wrapper in `app/nutrients.py`, profile fields in `app/profile.py`, `docs/research/targets_by_stage.json`, `docs/diet-guide.md`, its tests |
| M2 guidance | `app/guidance/**`, `data/combos.json`, `app/migrations/m005_*`, `POST /api/log/batch` + `purpose`/`client_id` handling in `app/log.py`, `scripts/bench_guidance.py`, `docs/guidance.md`, `tests/guidance/**` |
| M2 ai | `app/ai/**`, `app/migrations/m006_*`, AI settings keys, `docs/ai.md`, its tests and fixtures |
| M2 barcode-vision | `app/gtin.py`, `app/additives.py`, `app/off.py`, `app/barcode.py`, `app/vision.py`, `app/imagecheck.py`, `app/migrations/m007_*`, barcode/source fields in `app/foods.py`, flag + warning rule in `app/nutrients.py`, `docs/barcode-and-photos.md`, their tests and fixtures |
| M3 integration | `app/handbook.py` (`/learn` mount), README, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/README.md`, `tools/e2e/**` |

Shared files (`app/main.py`, `app/models.py`, `app/nutrients.py`) may be touched in M2 only for
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
  js/core.js            KH.h/s/$, KH.api (fetch wrapper: X-Requested-With, 401 → sign-in, toasts), state, router, sheets, confirm
  js/engine/rules.js    warnings, ratings, rounding, number formatting (twin of app/nutrients.py)
  js/engine/settings.js settings registry + precedence (twin of app/settings_registry.py / settings_store.py)
  js/engine/targets.js, js/engine/kidney_function.js        (M2 targets)
  js/engine/guidance.js (or js/engine/guidance/*.js)        (M2 guidance)
  js/mock/core.js       MockApi with a route table: KH.mock.route(method, pattern, handler)
  js/mock/<feature>.js  feature twins register their routes (M1: auth/settings; M2: labs, guidance, barcode fixtures)
  js/views/today.js, add.js, plan.js, trends.js, profile.js, settings.js, auth.js   (M1)
  js/views/labs.js, guidance.js                                                    (M2)
  js/pwa.js (M1), js/offline.js, js/scan.js (M2)
  js/learn.js           KH.learn: links into the handbook at /learn (M3; see "M3: the handbook at /learn")
  js/mock/handbook.js   demo answer for GET /api/handbook (no handbook in the demo)
  js/main.js            boot
```

`scripts/build_preview.py` inlines the `<link rel="stylesheet">` and `<script src>` tags of
`index.html` in document order. **Parity rule:** every JS twin of server logic (`js/engine/*`,
`js/mock/*`) is checked against the server by shared vector files in `tests/data/*.json`, run by
pytest on the Python side and by `node tests/js/run_vectors.mjs` on the JS side (CI runs both).
The mock routes as a whole are checked against a real, signed-in server by `tools/e2e/parity.py`
(run by hand; see `tools/e2e/README.md`).
In demo/preview mode the user is a signed-in demo admin; AI, Open Food Facts and USDA calls
answer "available in the installed app" except for a few recorded barcode fixtures.

### Sign-in screens and Settings (M1)

* **Boot** (`js/main.js` → `KH.auth.boot()` in `js/views/auth.js`): `GET /api/auth/status` decides
  between the first-run **setup** screen (setup code from the server log, the first admin, and the
  "Look up barcodes with Open Food Facts" box that sets `food.off_enabled`), **sign-in**, the
  **invite** and **reset** screens (`#/invite/<token>`, `#/reset/<token>`; the page moves the token
  out of the address bar at once; the reset screen asks `POST /api/auth/reset/info` whose account it
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
  `js/views/settings.js`): Account (name, password, signed-in devices, export zip, delete account,
  recent activity, sign out), Preferences (theme saved as `ui.theme`, week start saved with the
  profile, units placeholder), Food data (own USDA key, shared-key status, Open Food Facts
  consent), AI ideas (placeholder `#set-ai-slot` for M2), This device (install, offline, storage,
  connection, version, clear offline data; `js/pwa.js` supplies the device state), Admin (admins:
  people, invites and one-time links, server settings, shared keys, usage, activity log, about this
  server) and About & privacy (licences). Every setting shows its source ("Set by the server
  (ENV), locked" / your choice / admin / app default). Keys are write-only: an empty password
  field, "Set · ends in 9xQz · updated Oct 3", Replace / Remove, never a value from the server.
  The theme and Install panel moved here from Profile.

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
  `POST /api/auth/{login,setup,register,reset,reset/info}`. Anonymous → `401 {"detail": "Sign in required"}`
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

```json
Me = {"id": 1, "username": "mum", "display_name": "Mum", "role": "admin",
      "auth_source": "local", "must_change_password": false, "created_at": "2026-10-06T08:00:00.000000Z"}
```

### `/api/auth`

| Method and path | Auth | Body → response |
|---|---|---|
| `GET /api/auth/status` | public | → `{setup_required, auth_mode, registration ("invite"\|"closed"\|"open"\|"disabled"), insecure_http, https_required, password_min_length, password_max_length (128), instance_name, user: Me\|null, logout_url, no_login}` |
| `POST /api/auth/setup` | public + setup code | `{code, username, display_name?, password, off_enabled?}` (proxy mode: `{code}`, identity from the header) → `{user: Me}`; claims user 1 (keeps the migrated data), signs in. 400 wrong/expired code, 409 already set up. 404 in none mode |
| `POST /api/auth/login` | public | `{username, password}` → `{user: Me, notice}` + cookies; 401 `{"detail": "Username or password is incorrect"}`, 429, 400 HTTPS required. 404 in proxy/none mode. `notice` (N12): "Your password was reset with a link from an admin on …" once, at the first password sign-in after an admin's reset link changed the password (compared with the newest `login.succeeded` audit event, not `last_login_at`, which the reset's own sign-in updates) |
| `POST /api/auth/logout` | user | → `{ok: true, redirect?}` (proxy: `PROXY_LOGOUT_URL`); deletes the session, expires both cookie names, `Clear-Site-Data: "cache", "storage"` |
| `POST /api/auth/register` | public + invite token (or open mode) | `{token?, username, display_name?, password}` → 201 `{user: Me}`, signed in. 403 closed/no invite, 400 bad token, 409 username taken |
| `POST /api/auth/reset` | public + reset token | `{token, password}` → `{user: Me}`; claims the single-use link first (two racing requests: one 200, one 400), signs out every other session, voids the account's other open links, clears `locked`, activates a new account |
| `POST /api/auth/reset/info` | public + reset token | `{token}` → `{username, display_name, new_account, expires_at}` for the page the link opens (the owner of an admin-created account never saw its username); 400 (counts as a per-IP failure) when the link is not valid. 404 in proxy/none mode |
| `POST /api/auth/reauth` | user (local) | `{password}` → `{ok: true, reauth_until}`; wrong → 403; 5 wrong in a row revoke the session (401) |

Usernames (local): 3–64 of `a-z 0-9 . _ @ + -` after NFKC + casefold (stored as typed for display).
Passwords: 15–128 code points (`PASSWORD_MIN_LENGTH`, 8–64), NFC, no composition rules; refused when
on the blocklist (10,000 most common NCSC entries ≥ 8 characters), equal to the username, display
name or app/instance name, one repeated character or a straight keyboard/alphabet/digit run;
optional HIBP check (`PASSWORD_BREACH_CHECK`). Tokens in links travel in the URL fragment:
`/#/setup`, `/#/invite/<id>.<verifier>`, `/#/reset/<id>.<verifier>`; links are built from
`PUBLIC_URL` (else the request's origin).

### `/api/me`

| Method and path | Auth | Body → response |
|---|---|---|
| `GET /api/me` · `PATCH /api/me` | user | → Me; PATCH `{display_name}` |
| `DELETE /api/me` | user + password | `{password, confirm: "DELETE"}` → 204, cookies cleared, `Clear-Site-Data`; 409 for the last active admin, and always 409 with `AUTH_MODE=none` (every request is user 1; start-up also recreates a missing user 1 in that mode). Deletes the account and everything it owns (cascade), after deleting the unused invites and links it created |
| `POST /api/me/password` | user (local) | `{current_password, new_password}` → `{user: Me}`; signs out other devices, voids open reset links for the account, renews this session |
| `GET /api/me/sessions` | user | → `{sessions: [{id, created_at, last_seen_at, expires_at, user_agent, ip_prefix, current}]}` |
| `DELETE /api/me/sessions/{id}` | user | → 204 (404 if not one of yours) |
| `POST /api/me/sessions/revoke-others` | user *(re-auth)* | → `{revoked: n}` |
| `GET /api/me/settings` · `PATCH /api/me/settings` | user | → `{settings: {key: {value, source ("env"\|"user"\|"instance"\|"default"), editable}}}`; PATCH `{key: value \| null}` (null = back to inherited); 400 invalid/unknown, 403 not a personal key, 409 locked by env |
| `GET /api/me/keys` | user | → `{providers: [KeyItem]}` |
| `PUT /api/me/keys/{provider}` | user *(re-auth)* | `{api_key, test?}` → KeyItem (+ `test: "ok"\|"rejected"\|"unreachable"`); 8–512 printable ASCII, no spaces; 403 when personal keys are off |
| `DELETE /api/me/keys/{provider}` | user *(re-auth)* | → 204 |
| `GET /api/me/usage` | user | → `{days: 30, usage: [{provider, scope, today, last_30_days}], by_day: [...]}` |
| `GET /api/me/activity?before=&limit=` | user | → `{events: [AuditEvent]}` (own sign-in, session, password, key and export events: events about the person's account, whoever acted, and their own actions except those on another account) |
| `GET /api/me/export.zip` | user *(re-auth)* | → `application/zip` (`Content-Disposition: attachment; filename="kidney-health-<username>-<date>.zip"`, `Cache-Control: no-store`) with `export.json`, `log.csv`, `foods.csv`, `meals.csv`, `labs.csv`, `README.txt`; no passwords, sessions or keys |

```json
KeyItem = {"provider": "usda", "label": "USDA FoodData Central",
           "own": {"set": true, "last4": "9xQz", "updated_at": "…"},          // or {"set": false}; {"set": true, "status": "unreadable"} after a lost SECRET_KEY
           "shared": {"available": true, "remaining_today": 187, "daily_limit": 200},
           "user_keys_allowed": true, "effective": "own" | "shared" | "none"}
export.json = {"format": "kidney-health-export", "version": 1, "exported_at", "app_version",
               "user": {username, display_name, created_at}, "profile", "settings", "log_entries",
               "custom_foods", "linked_foods", "meal_templates", "lab_results", "ai_audit", "activity",
               "food_preferences"}   // food_preferences: v0.3 guidance "Not for me" foods (schema step 5)
```

`last4` is shown only for keys of 20 characters or more. Keys are never returned, logged or
audited; they are sealed with Fernet under keys derived from `SECRET_KEY` (`app/crypto.py`).

### `/api/admin` (admins; every write *(re-auth)*)

| Method and path | Body → response |
|---|---|
| `GET /api/admin/users` | → `{users: [{id, username, display_name, role, status, auth_source, can_use_shared, must_change_password, has_password, created_at, last_login_at, reset_link}]}`; `reset_link` is the open reset or setup link (`{id, created_by, created_at, expires_at}`, never the token) or `null` (also in the `user` of the POST/PATCH answers) |
| `POST /api/admin/users` | `{username, display_name?, role}` → 201 `{user, setup_url, expires_at}`: a `pending_setup` account and a one-time link (`/#/reset/…`, `registration.invite_ttl_days`) where the person sets a password. Proxy mode: pre-creates the proxy identity (`setup_url: null`) |
| `PATCH /api/admin/users/{id}` | any of `{role, status ("active"\|"disabled"), can_use_shared, must_change_password (true), display_name}` → `{user}`. 409 when it would leave no active admin, for disabling yourself, or enabling a locked/new account (use a reset link). A role change or disabling signs the person out. Demoting or disabling an admin deletes every unused invite and reset/setup link they created (audit detail `links_revoked`); disabling also voids the account's own open link |
| `DELETE /api/admin/users/{id}` | `{confirm_username}` → 204 (cascade); 409 for yourself or the last admin. The person's unused invites and links are deleted first (`auth_tokens.created_by` is `ON DELETE SET NULL`) |
| `POST /api/admin/users/{id}/reset-link` | → `{url, expires_at}` (24 h, single use; also unlocks; voids the account's older link) |
| `DELETE /api/admin/users/{id}/reset-link` | → 204, voids the account's open reset or setup link (404 when there is none); audit `user.reset_link_revoked` |
| `POST /api/admin/users/{id}/revoke-sessions` | → `{revoked: n}` |
| `GET /api/admin/invites` · `POST /api/admin/invites` · `DELETE /api/admin/invites/{id}` | POST `{role, note?, ttl_days? (1–90)}` → 201 `{invite, url, expires_at}` (the URL is shown once); list → `{invites: [{id, role, note, created_by, created_at, expires_at, used_at, state}]}`; 409 when registration is `closed` or in proxy mode |
| `GET /api/admin/settings` · `PATCH /api/admin/settings` | → `{settings: {key: {value, source, locked_by_env, scope}}}`; PATCH `{key: value \| null}`, audited with old and new values |
| `GET /api/admin/keys` · `PUT/DELETE /api/admin/keys/{provider}` | shared keys: `{providers: [{provider, label, shared: {set, source ("db"\|"env"), locked, last4?, updated_at?}}]}`; PUT `{api_key, test?}`; an env key (`USDA_API_KEY[_FILE]`) is locked (409); 403 in none mode |
| `GET /api/admin/usage?days=30` | → `{days, usage: [{user_id, username, provider, key_scope, requests}]}` (counts only) |
| `GET /api/admin/audit?before=&limit=` | → `{events: [{id, at, actor_user_id, ip_prefix, action, target_type, target_id, details}]}` |
| `GET /api/admin/about` | → `{version, schema_version, auth_mode, accounts, https, public_url, secret_key: {source, on_data_volume, warning, secrets: {current, older_key, unreadable}}, proxy: {first_forwarded_peer, ignored_identity_headers, …}, pre_v3_backup, last_backup_at}` |

With `AUTH_MODE=none` the users and invites routes answer 404.

### Changes to existing routes

* All of `/api/profile`, `/api/foods`, `/api/log`, `/api/meals`, `/api/plan` act on the signed-in
  person. `Profile.id` is the user id. `GET /healthz` counts only builtin foods.
* **Foods**: `builtin` rows are shared; `custom` rows belong to their owner; `usda` (and later
  `off`) rows are shared but visible to a person only after they imported or scanned them.
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
USERNAME|--all`, `purge-pre-v3-backup`, `vacuum`, plus the platform's `backup`, `check`,
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
              "taken_on": "2026-10-05", "message": "Potassium 6.3 mmol/L on 2026-10-05 is dangerously high. …"}]
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
| `GET /api/labs?analyte=&limit=` | → `{"labs": [LabResult]}` newest first (`taken_on`, then entry order); `limit` 1–1000, default 200 |
| `DELETE /api/labs/{id}` | → 204; 404 when it is not yours or does not exist |
| `GET /api/labs/kidney-function` | → `KidneyFunction` (below); never changes the saved stage |

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
rows, settings, `today`); outputs include every note word for word.

## M2 API: guidance

Built in M2 (guidance) from note 06 §4.1–§4.15 and §6, with the Layer-0 duties of note 04 R2 and G7.
Code: the package `app/guidance/` — pure modules `rules`, `vectors`, `state`, `budget`, `score`, `fits`,
`swaps`, `planner`, `insights`, `messages`, `topics`, `hypo`, `ai_bridge`; I/O in `context` (loads one
person's data) and `api` (the routes); response shapes in `app/guidance/models.py` (package-owned; the
log-side models are in `app/models.py`). Schema step 5 (`app/migrations/m005_guidance_log.py`). People-
and contributor-facing explanation: `docs/guidance.md`. Every route needs a signed-in person, reads only
that person's rows, writes nothing except the "Not for me" list, and answers 404 for a food or entry
that is not theirs. Responses are `Cache-Control: no-store` like every `/api` route.

### Routes (`/api/guidance`)

| Method and path | Query / body → response |
|---|---|
| `GET /api/guidance/next-meal` | `meal` (required), `date` (default today), `limit` 1–20 (11), `explain` → `NextMeal` |
| `GET /api/guidance/swaps` | `food_id` + `meal` + `servings` or `grams` (+ `date`), **or** `entry_id`; `purpose` `hypo`\|`none` (default: `hypo` for a `hypo_treatment` food, else the entry's); `explain` → `Swaps`. 400 without exactly one of `food_id`/`entry_id`; 404 for a food or entry that is not the person's |
| `GET /api/guidance/hypo-options` | → `{status, rules_version, dose_g, options: [FoodPortion + text], card: LowCard, notes}`. Never filtered by a budget; answers even when guidance is switched off |
| `POST /api/guidance/plan-day` | `{date, meals?: [Meal] (1–4, unique), use_saved_meals?, use_usual?, use_starters?, variant? 0–4, explain?}` → `Plan`; computes only |
| `GET /api/guidance/insights/day` | `date` → `{status, rules_version, date, insights: [Insight] (≤ 6), planned_excluded, notes}` |
| `GET /api/guidance/insights/period` | `start`, `end` (default the 7 days ending yesterday; ≤ 92 days; 400 for `end < start`) → `{status, rules_version, start, end, days, logged_days, insights, notes, previous: {start, end}}` |
| `GET /api/guidance/rules` | → `{rules_version, rules_hash, rules: {NAME: value}, notes: {NAME: basis}, topic_pages: {slug: {slug, title, url}}, tips}` |
| `GET /api/guidance/not-for-me` | → `{rules_version, limit: 500, foods: [{food_id, name, category, created_at}]}` |
| `PUT /api/guidance/not-for-me/{food_id}` | → the list (idempotent); 404 for a food the person cannot use; 409 at 500 foods |
| `DELETE /api/guidance/not-for-me/{food_id}` | → 204; 404 when not on the list |

Instead of a result, `next-meal`, `swaps`, `plan-day` and the insights answer 200
`{"status": "no_targets" | "disabled", "rules_version", "message"}`: `no_targets` when the profile has no
numeric potassium, phosphorus or sodium target and no `carbs_per_meal_g`; `disabled` when the instance
setting `guidance.enabled` is off ("Meal guidance is switched off on this server.") or the person's
`guidance.enabled` / `show_plan_builder` / `show_insights` is off. `explain=true` adds score components,
`why_not` and `not_eligible` reason codes and evaluation counts (contributors; never shown by default).

```json
NextMeal = {"status": "ok", "rules_version": "2026-10-05.1", "date", "meal", "open_meals": [Meal],
  "room": {"potassium_mg": NutrientRoom | null, "phosphorus_mg": …, "sodium_mg": …, "fluid_ml": …,
           "carbs_g": {"goal", "in_meal", "gap", "tolerance", "hypo_excluded_g"} | null,
           "protein_g": {"aim", "aim_min"} | null},
  "room_text": "Left for dinner: 750 mg potassium · 167 mg phosphorus · 600 mg sodium · 60 g carbs to reach 60 g",
  "meal_has": {"protein", "starch", "veg_fruit"},
  "foods": [FoodPortion + {"score", "fit_text", "reasons": [{"code", "text"}], "handbook": [{"slug", "title", "url"}]}],
  "saved_meals": [{"template_id" | null, "name", "source": "saved" | "usual", "scale", "score",
                   "items": [{"food_id", "name", "servings"}], "totals", "note"}],
  "tips": [{"code", "text", "handbook", "url"}], "notes": ["Suggestions compare foods with the targets your care team set. They are not medical advice."],
  "ai": {"available", "provider_label"}, "targets": {"values": {…}, "profile_updated_at"}}
NutrientRoom = {"room", "cap" | null, "share", "in_meal", "remaining_today", "allowance_today",
                "level": "ok" | "caution" | "over", "basis": "day" | "week_average" | "interdialytic"}
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

### Settings (registered in `app/settings_registry.py`)

`guidance.enabled` (instance, `true`, env `GUIDANCE_ENABLED`), `guidance.pool_per_role` (instance, 200,
20–2000, env `GUIDANCE_POOL_PER_ROLE`), `guidance.beam_width` (instance, 16, 1–64, env
`GUIDANCE_BEAM_WIDTH`), and the person's object `guidance` (scope `user`): `{enabled: true,
carb_tolerance_g: 10 (5–20), hypo_dose_g: 15 (5–30), exclude_categories: [] (≤ 50), show_plan_builder:
true, show_insights: true, ai_enrich: false}`, unknown fields refused. "Not for me" foods are
`food_preferences` rows (≤ 500), exported as `export.json` → `food_preferences`.

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
`period_insights` and `prefilter`.

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
* The service worker leaves `/learn` to the network (offline handbook pages: v0.4, `docs/ROADMAP.md`).

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
