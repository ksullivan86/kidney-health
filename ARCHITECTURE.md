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
* Tests: `pytest` with `httpx` (FastAPI `TestClient`).

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
app/log.py                  log entries, day summary, range summary, CSV export
app/profile.py              profile + targets
app/static/index.html
app/static/app.js
app/static/style.css
data/foods.json             builtin food database (generated, committed)
scripts/build_food_db.py    downloads USDA SR Legacy CSV zip and writes data/foods.json
scripts/curated_foods.py    the curated list (fdc_id, display name, serving, category, flags)
tests/test_nutrients.py
tests/test_api.py
deploy/Containerfile
deploy/compose.yaml
deploy/quadlet/kidney-health.container
deploy/k8s/*.yaml (+ kustomization.yaml)
.github/workflows/ci.yml    pytest + build image + push to ghcr.io on main
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
| carbs_g         | 15–30 g ("1–2 carb choices") | > 30 g, or flagged `high_gi` | type 1 carb counting |
| protein_g       | 15–25 g          | > 25 g                     | large protein portion for restricted intake |

Flags (strings, set in curated data or by the user on custom foods):
`phosphate_additive`, `high_gi`, `counts_as_fluid`, `avoid_ckd` (e.g. star fruit),
`hypo_treatment` (fast carbs that are also low potassium, e.g. glucose tablets),
`low_potassium_fruit`, `processed`.

`avoid_ckd` always yields a `high` warning with the food's `kidney_notes` text.

`kidney_rating` is computed, never stored: `"red"` if any high warning,
`"yellow"` if any medium, else `"green"`.

### Daily status

For each nutrient with a target: `fraction = total / target`.
`level = "ok"` if fraction < `warn_fraction` (profile, default 0.8), `"caution"`
if `warn_fraction ≤ fraction ≤ 1.0`, `"over"` if > 1.0. For `protein_g` with a
`min`, also `"low"` if end-of-day and below min is **not** computed server-side —
just report `fraction` against max and include `min` so the UI can show the range.

### Suggested targets (`nutrients.suggest_targets(weight_kg, ckd_stage, dialysis)`)

Starting points only; the UI labels them "discuss with your care team".
Values must agree with `docs/diet-guide.md` after the reconcile step.

* protein_g: non-dialysis CKD 3–5 with diabetes 0.6–0.8 g/kg (use 0.8 for max, 0.6 for min);
  hemodialysis / peritoneal 1.0–1.2 g/kg (min 1.0, max 1.2).
* potassium_mg: stage 3: 3000; stage 4–5 non-dialysis: 2500; hemodialysis: 2300; peritoneal: 3000.
* phosphorus_mg: 800–1000 → use 900 for stage 3b+, 1000 for stage 3a.
* sodium_mg: 2000 (all stages; KDOQI < 2300, many programs use 2000).
* fluid_ml: `null` (no limit) unless dialysis: hemodialysis 1000 + urine output ≈ 1500 default; peritoneal 2000.
* carbs_g: 45 % of calories / 4 → default calories 30 kcal/kg (KDOQI 25–35) → carbs = round(cal*0.45/4).
* calories_kcal: 30 kcal/kg.
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
  -- snapshot of nutrients for this entry (already multiplied by servings)
  calories_kcal REAL, protein_g REAL, fat_g REAL, sat_fat_g REAL, carbs_g REAL, fiber_g REAL, sugar_g REAL,
  sodium_mg REAL, potassium_mg REAL, phosphorus_mg REAL, calcium_mg REAL, fluid_ml REAL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_date ON log_entries(date);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- e.g. foods_json_version
```

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
  word must match; exact-prefix matches rank first.
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
* `PUT /api/log/{id}` body any of `meal`, `servings`, `grams`, `note`, `date` → Entry (recomputes snapshot from the food)
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
If `APP_PASSWORD` is set, every route (including static) requires HTTP Basic auth
with any username and that password. Otherwise no auth (LAN use behind a reverse proxy).

## Frontend behaviour (app/static)

Mobile-first single page, four views switched client-side (no router library):

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
   (fills the form from `/api/profile/suggested-targets`, never auto-saves), warn_fraction.
   Footer disclaimer: targets come from the person's nephrologist / renal dietitian.

Colors: green `#2e7d32`, yellow `#f9a825`, red `#c62828`, neutral grays; must pass
contrast on both light and dark (`prefers-color-scheme`). Fonts: system stack.
All strings in English. `fetch()` only to same-origin `/api/...`.

## Conventions

* Timestamps ISO-8601 UTC with `Z`. Dates `YYYY-MM-DD` as provided by the client.
* Round nutrient numbers to 1 decimal in responses (mg values to integers).
* `python -m pytest` must pass with no network.
* `uvicorn app.main:app --host 0.0.0.0 --port 8000` runs the server; `DATA_DIR` default
  `./data-local` when running outside a container (gitignored), `/data` in the image.
