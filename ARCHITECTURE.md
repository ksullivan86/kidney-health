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

Starting points only; the UI labels them "discuss with your care team". These are the
**final, reconciled** numbers: they equal `docs/research/targets_by_stage.json` (the
fact-checked file) and `docs/diet-guide.md` section 7, and `tests/test_nutrients.py`
compares the code with the JSON row by row.

**Per kg means per kg of ideal body weight** (KDOQI 2020 3.0.1, 3.1.x). The profile has no
sex, so `nutrients.dosing_weight(weight_kg, height_cm)` takes the ideal weight sex-neutrally as
the weight at the edge of the healthy BMI band for the person's height: BMI 25 when they are
above it, BMI 18.5 when below, the actual weight in between. Without a height the actual weight
is used. The first note returned always states which weight the numbers assume
("Weight basis: …"), and `GET /api/profile/suggested-targets` passes the stored `height_cm`.

| stage / dialysis | protein g/kg (min–max) | potassium mg | phosphorus mg | sodium mg | fluid mL | kcal/kg | calcium mg |
|---|---|---|---|---|---|---|---|
| 1, 2 (no dialysis) | 0.8–1.0 | 4000 (informational) | 1000 | 2000 | null | 30 | 1000 |
| 3a | 0.6–0.8 | 4000 | 1000 | 2000 | null | 30 | 1000 |
| 3b | 0.6–0.8 | 3500 | 1000 | 2000 | null | 30 | 1000 |
| 4 | 0.6–0.8 | 3000 | 1000 | 2000 | null | 30 | 1000 |
| 5, no dialysis | 0.6–0.8 | 2500 | 900 | 2000 | null | 30 | 1000 |
| hemodialysis | 1.0–1.2 | 2500 | 1000 | 2000 | 1500 (1000 + ~500 urine) | 30 | 1000 |
| peritoneal | 1.0–1.2 | 3500 | 1000 | 2000 | 2000 | 30 | 1000 |

* protein_g: `{"min": round(min_per_kg × kg), "max": round(max_per_kg × kg)}` (KDOQI 2020 3.1.2–3.1.4;
  stages 1–2 use the 0.8 g/kg RDA floor with a 1.0 ceiling, KDIGO 2024: avoid > 1.3). The note for
  non-dialysis stages 3–5 says that below 0.6 g/kg risks wasting and hypoglycaemia, that guidelines
  recommend 0.8 and advise avoiding more than 1.3 g/kg (KDIGO 2024); it cites KDOQI 2020 3.1.3 with
  diabetes and 3.1.1 / KDIGO 2024 3.3.1.1 without.
* potassium_mg: no guideline fixes a number; restriction is ordered only when serum potassium runs
  high, so these are review ceilings. The note returned with the suggestion must say: "Only restrict
  potassium if your blood potassium is high; your care team sets the number."
* phosphorus_mg: KDOQI 2003 800–1000 mg when phosphate runs high; 1000 at stages 1–4 and on either
  dialysis ("adjusted for protein needs"), 900 at stage 5 before dialysis.
* sodium_mg: 2000 (all stages; KDIGO 2024 < 2000, KDOQI < 2300).
* fluid_ml: `null` (no limit) unless dialysis: hemodialysis 1000 + urine output ≈ 1500 default; peritoneal 2000.
* calories_kcal: 30 kcal/kg (KDOQI 25–35). carbs_g: 45 % of calories / 4 = round(cal × 0.45 / 4);
  carbs_per_meal_g: carbs / 4 rounded to 5 g (minimum 15).
* calcium_mg: 1000 (max, including binders).

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
  from the stored profile (400 if weight missing)

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
   Install with `--require-hashes`.
6. **Base image:** Chainguard Python pinned by digest for `deploy/Containerfile`, plus
   `deploy/Containerfile.debian` as the fallback (note 01 §5.1). CI tests on **Python 3.12 and
   the image's Python** (3.14 at the time of writing). The app must stay compatible with 3.11+.
7. **Image tags:** pushes to `main` publish `:edge` and `:sha-<short>`; `v*` tags publish
   `:latest`, `:X.Y.Z`, `:X.Y`. Signing, SBOM and provenance per note 01 §5.4; attestation steps
   that need a public repo are gated on `github.event.repository.private == false`.
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
| 6 | `m006_barcode_ai.py` | ai-barcode (M2) | note 03 R6 (food `gtin`, `source='off'`, `barcode_cache`, attribution fields) and note 04 (AI usage/audit tables with `ON DELETE CASCADE`) |

## Backend file ownership

| Milestone / owner | Files |
|---|---|
| M1 backend-core | `app/config.py`, `app/db.py`, `app/migrations/**` (steps 1–3), `app/security.py`, `app/auth/**`, `app/settings_registry.py`, `app/settings_store.py`, `app/crypto.py`, `app/credentials.py`, `app/audit.py`, `app/account.py` (export/delete), `app/admin.py` (CLI), `app/healthcheck.py`, `app/pwa.py` (note 02 R6: `/sw.js`, manifest/icon headers), `app/main.py`, `app/models.py`, user scoping edits in `app/foods.py`, `app/log.py`, `app/meals.py`, `app/profile.py`, `app/periods.py`; `requirements*.in/.lock`, `pyproject.toml`, `scripts/lock.sh`; `tests/**` except frontend-owned tests |
| M1 deploy | `deploy/**`, `.github/**`, `.hadolint.yaml`, `.dockerignore`, `scripts/verify-image.sh`, `SECURITY.md`, `docs/security.md`, `docs/https.md`, `docs/deployment.md`, `docs/network-allowlist.md` |
| M1 frontend | `app/static/**`, `scripts/build_preview.py`, `scripts/build_icons.py`, `requirements-tools.txt`, `tests/test_preview_build.py`, `tests/js/**`, `docs/install-on-your-phone.md` |
| Handbook (parallel) | `handbook/**`, `scripts/build_handbook.py`, `tests/test_handbook_content.py` |
| M2 targets | `app/targets.py`, `app/target_rules.py`, `app/kidney_function.py`, `app/units.py`, `app/labs.py`, `app/migrations/m004_*`, `suggest_targets` wrapper in `app/nutrients.py`, profile fields in `app/profile.py`, `docs/research/targets_by_stage.json`, `docs/diet-guide.md`, its tests |
| M2 guidance | `app/guidance/**`, `data/combos.json`, `app/migrations/m005_*`, `POST /api/log/batch` + `purpose`/`client_id` handling in `app/log.py`, `scripts/bench_guidance.py`, `docs/guidance.md`, `tests/guidance/**` |
| M2 ai-barcode | `app/ai/**`, `app/gtin.py`, `app/additives.py`, `app/off.py`, `app/barcode.py`, `app/vision.py`, `app/imagecheck.py`, `app/migrations/m006_*`, barcode/source fields in `app/foods.py`, flag + warning rule in `app/nutrients.py`, `docs/ai.md`, `docs/barcode-and-photos.md`, their tests and fixtures |
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
  js/engine/targets.js, js/engine/kidney_function.js        (M2 targets)
  js/engine/guidance.js (or js/engine/guidance/*.js)        (M2 guidance)
  js/mock/core.js       MockApi with a route table: KH.mock.route(method, pattern, handler)
  js/mock/<feature>.js  feature twins register their routes (M1: auth/settings; M2: labs, guidance, barcode fixtures)
  js/views/today.js, add.js, plan.js, trends.js, profile.js, settings.js, auth.js   (M1)
  js/views/labs.js, guidance.js                                                    (M2)
  js/pwa.js (M1), js/offline.js, js/scan.js (M2)
  js/main.js            boot
```

`scripts/build_preview.py` inlines the `<link rel="stylesheet">` and `<script src>` tags of
`index.html` in document order. **Parity rule:** every JS twin of server logic (`js/engine/*`,
`js/mock/*`) is checked against the server by shared vector files in `tests/data/*.json`, run by
pytest on the Python side and by `node tests/js/run_vectors.mjs` on the JS side (CI runs both).
In demo/preview mode the user is a signed-in demo admin; AI, Open Food Facts and USDA calls
answer "available in the installed app" except for a few recorded barcode fixtures.

## Milestones

* **M1 foundation:** accounts, settings, secrets, security middleware, migrations framework,
  scoping, admin CLI, healthcheck, PWA shell, frontend restructure + sign-in/setup/settings UI,
  rootless/hardened deploy assets, CI/release pipeline. Handbook writing runs in parallel.
* **M2 features:** personalised targets + labs + eGFR; guidance engine; AI; barcode/photo;
  offline outbox; their UI and mock twins.
* **M3 integration:** `/learn` mount and handbook build in the image, contributor docs, e2e
  harnesses in `tools/e2e/`, full review, preview rebuild, PR.

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
  `POST /api/auth/{login,setup,register,reset}`. Anonymous → `401 {"detail": "Sign in required"}`
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
  `Retry-After`), per client IP (`LOGIN_IP_MAX_FAILURES` in 10 min → 10-min block; skipped for
  `TRUSTED_PROXIES` and rootless gateway addresses), 60 sign-ins per minute instance-wide (queued up
  to 5 s, then `503`), 2 password hashes at a time (`503` + `Retry-After: 1`), 100 consecutive
  failures lock the account (an admin reset link or the CLI unlocks it). Unknown, disabled and
  locked accounts get the same answer after the same single hash. Other limits (`app/auth/ratelimit.py`):
  open registration 3/hour per IP, key tests 10/hour, exports 10/hour.
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
| `POST /api/auth/login` | public | `{username, password}` → `{user: Me, notice}` + cookies; 401 `{"detail": "Username or password is incorrect"}`, 429, 400 HTTPS required. 404 in proxy/none mode |
| `POST /api/auth/logout` | user | → `{ok: true, redirect?}` (proxy: `PROXY_LOGOUT_URL`); deletes the session, expires both cookie names, `Clear-Site-Data: "cache", "storage"` |
| `POST /api/auth/register` | public + invite token (or open mode) | `{token?, username, display_name?, password}` → 201 `{user: Me}`, signed in. 403 closed/no invite, 400 bad token, 409 username taken |
| `POST /api/auth/reset` | public + reset token | `{token, password}` → `{user: Me}`; signs out every other session, clears `locked`, activates a new account |
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
| `DELETE /api/me` | user + password | `{password, confirm: "DELETE"}` → 204, cookies cleared, `Clear-Site-Data`; 409 for the last active admin. Deletes the account and everything it owns (cascade) |
| `POST /api/me/password` | user (local) | `{current_password, new_password}` → `{user: Me}`; signs out other devices, renews this session |
| `GET /api/me/sessions` | user | → `{sessions: [{id, created_at, last_seen_at, expires_at, user_agent, ip_prefix, current}]}` |
| `DELETE /api/me/sessions/{id}` | user | → 204 (404 if not one of yours) |
| `POST /api/me/sessions/revoke-others` | user *(re-auth)* | → `{revoked: n}` |
| `GET /api/me/settings` · `PATCH /api/me/settings` | user | → `{settings: {key: {value, source ("env"\|"user"\|"instance"\|"default"), editable}}}`; PATCH `{key: value \| null}` (null = back to inherited); 400 invalid/unknown, 403 not a personal key, 409 locked by env |
| `GET /api/me/keys` | user | → `{providers: [KeyItem]}` |
| `PUT /api/me/keys/{provider}` | user *(re-auth)* | `{api_key, test?}` → KeyItem (+ `test: "ok"\|"rejected"\|"unreachable"`); 8–512 printable ASCII, no spaces; 403 when personal keys are off |
| `DELETE /api/me/keys/{provider}` | user *(re-auth)* | → 204 |
| `GET /api/me/usage` | user | → `{days: 30, usage: [{provider, scope, today, last_30_days}], by_day: [...]}` |
| `GET /api/me/activity?before=&limit=` | user | → `{events: [AuditEvent]}` (own sign-in, session, password, key and export events) |
| `GET /api/me/export.zip` | user *(re-auth)* | → `application/zip` (`Content-Disposition: attachment; filename="kidney-health-<username>-<date>.zip"`, `Cache-Control: no-store`) with `export.json`, `log.csv`, `foods.csv`, `meals.csv`, `labs.csv`, `README.txt`; no passwords, sessions or keys |

```json
KeyItem = {"provider": "usda", "label": "USDA FoodData Central",
           "own": {"set": true, "last4": "9xQz", "updated_at": "…"},          // or {"set": false}; {"set": true, "status": "unreadable"} after a lost SECRET_KEY
           "shared": {"available": true, "remaining_today": 187, "daily_limit": 200},
           "user_keys_allowed": true, "effective": "own" | "shared" | "none"}
export.json = {"format": "kidney-health-export", "version": 1, "exported_at", "app_version",
               "user": {username, display_name, created_at}, "profile", "settings", "log_entries",
               "custom_foods", "linked_foods", "meal_templates", "lab_results", "ai_audit", "activity"}
```

`last4` is shown only for keys of 20 characters or more. Keys are never returned, logged or
audited; they are sealed with Fernet under keys derived from `SECRET_KEY` (`app/crypto.py`).

### `/api/admin` (admins; every write *(re-auth)*)

| Method and path | Body → response |
|---|---|
| `GET /api/admin/users` | → `{users: [{id, username, display_name, role, status, auth_source, can_use_shared, must_change_password, has_password, created_at, last_login_at}]}` |
| `POST /api/admin/users` | `{username, display_name?, role}` → 201 `{user, setup_url, expires_at}`: a `pending_setup` account and a one-time link (`/#/reset/…`, `registration.invite_ttl_days`) where the person sets a password. Proxy mode: pre-creates the proxy identity (`setup_url: null`) |
| `PATCH /api/admin/users/{id}` | any of `{role, status ("active"\|"disabled"), can_use_shared, must_change_password (true), display_name}` → `{user}`. 409 when it would leave no active admin, for disabling yourself, or enabling a locked/new account (use a reset link). A role change or disabling signs the person out |
| `DELETE /api/admin/users/{id}` | `{confirm_username}` → 204 (cascade); 409 for yourself or the last admin |
| `POST /api/admin/users/{id}/reset-link` | → `{url, expires_at}` (24 h, single use; also unlocks) |
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
USERNAME [--stdin]` (prints a 24-hour link, or sets the password from stdin and unlocks),
`list-users [--json]`, `setup-code`, `revoke-sessions USERNAME|--all`, `purge-pre-v3-backup`,
`vacuum`, plus the platform's `backup`, `check`, `restore-check`, `rotate-secret-key`, `reencrypt`,
`settings`.

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
