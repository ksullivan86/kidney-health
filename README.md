# Kidney Health food log

A small, self-hosted food log for **one person living with chronic kidney disease (CKD)
and type 1 diabetes**. You log what you eat; the app totals the nutrients a renal diet
restricts (potassium, phosphorus, sodium, protein, fluid) and the one a type 1 diabetic
counts (carbohydrate per meal), compares them with targets set together with your care
team, and warns when a single food or the day's running total needs careful consideration.
It also lets you plan meals ahead, see weekly averages and, on hemodialysis, the totals
since your last session.

It runs as one container with one SQLite file, serves a phone-friendly web page that
works offline on a LAN, and makes no external requests unless you enable USDA lookups.

**Who it is for:** the person doing the logging and, through the CSV export, their renal
dietitian. It is **not** a medical device and gives no medical advice; every target in it
should come from a nephrologist or renal dietitian (see [Disclaimer](#disclaimer)).

## Features

* **Food logging** by servings or grams, per meal (breakfast, lunch, dinner, snack), with a
  395-food builtin database built from USDA SR Legacy plus your own custom foods and a
  "quick add" from a nutrition label. Entries keep a nutrient snapshot, so later edits to a
  food never rewrite history.
* **Per-serving warnings** (`medium` / `high`) for potassium, phosphorus, sodium, carbohydrate
  and protein, plus flags for phosphate additives, high glycaemic index, star fruit
  (`avoid_ckd`) and hypo treatments. Each food and entry gets a green / yellow / red rating;
  the warnings are shown *before* you save.
* **Daily targets and status bars** per nutrient (`ok` / `caution` / `over`, with an adjustable
  warning threshold), a prominent carbohydrate total per meal, and a one-click **"Suggest
  targets"** that fills guideline-based starting points from your weight, CKD stage and
  dialysis mode, labelled "discuss with your care team".
* **Meal planning**: log a food as *planned* for any day, see the projected total
  (eaten + planned) as a lighter extension of each status bar, "If you eat what's planned…"
  alerts, one-tap "Eaten", "Mark all eaten", a 7-day **Plan** grid with per-day chips, and
  **Copy day** to reuse a day's menu.
* **Saved meals**: save a logged meal as a template ("Usual breakfast"), build templates in an
  editor, and add them to any day as planned or eaten, scaled.
* **Weekly / period summaries**: averages per logged day versus target, days over, the highest
  day and the change against the previous period; potassium, sodium, fluid and carbohydrate
  are judged day by day, phosphorus and protein on the weekly average, exactly as the diet
  guide explains. A compact "Last 7 days" strip sits on the Today page.
* **Interdialytic totals**: with hemodialysis days set in the profile, potassium, sodium and
  fluid are also totalled since the last session against *per-day target × days*, so the long
  weekend gap is visible.
* **Shopping list** aggregated from everything planned in the visible week.
* **USDA FoodData Central lookup** (optional, needs a free API key) to import any food.
* **CSV export** of every entry in a date range for your dietitian.
* **Offline-capable UI**: plain HTML/JS/CSS served by the app, no build step, no CDN, light and
  dark themes, keyboard and screen-reader friendly.
* **Optional password** (HTTP Basic) for exposure beyond the LAN; `/healthz` stays open for probes.

## Quick start

### Run locally with uvicorn

Python 3.11 or newer.

```bash
git clone https://github.com/ksullivan86/kidney-health.git
cd kidney-health
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest                                  # 192 tests, no network needed
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>, fill in **Profile** (weight, stage, dialysis), press **Suggest
targets**, review them with your care team, save, and start logging. The database lands in
`./data-local/kidney.db`.

### Podman

```bash
podman volume create kidney-data
podman run -d --name kidney-health -p 8000:8000 -v kidney-data:/data \
  --restart always --security-opt no-new-privileges --cap-drop ALL \
  ghcr.io/ksullivan86/kidney-health:latest
```

`deploy/compose.yaml` does the same for `podman-compose` / `docker compose`, and
`deploy/quadlet/` holds a systemd Quadlet unit with auto-update. Build the image yourself
with `podman build -f deploy/Containerfile -t kidney-health .`.

### Kubernetes (Talos or any other distribution)

```bash
kubectl apply -k deploy/k8s/
```

The kustomization creates a namespace, a `ReadWriteOnce` PVC, a `Recreate` Deployment
running as uid 10001 with probes on `/healthz`, a Service and an example Ingress /
HTTPRoute. SQLite means **exactly one replica**.

Everything above, plus backups and restore of `kidney.db`, reverse-proxy and Authelia
setups, ARM builds, upgrades and troubleshooting, is in **[docs/deployment.md](docs/deployment.md)**.
The outbound domains the project needs (for development, image pulls and the optional USDA
lookups) are listed in [docs/network-allowlist.md](docs/network-allowlist.md).

## Configuration

All settings are environment variables; empty means unset.

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/data` inside the container, `./data-local` outside | Directory holding `kidney.db` (and its `-wal` / `-shm` files while running). Created on start. Mount a volume here. |
| `USDA_API_KEY` | unset | Enables **Search USDA** in the Add view and `GET /api/foods/usda/search` / `POST /api/foods/usda/import`. Free key from <https://api.data.gov>. Without it those endpoints answer `503` and the UI explains why. |
| `APP_PASSWORD` | unset | When set, every page and API call except `GET /healthz` requires HTTP Basic auth (any username, this password, constant-time compare). |
| `FOODS_JSON` | `<repo>/data/foods.json` (`/app/data/foods.json` in the image) | Path of the builtin food database that is upserted on start. Normally leave alone. |

The server listens on port 8000 (plain HTTP; put TLS on a reverse proxy). On start it
creates or migrates the schema in place (a v0.1 database upgrades automatically) and imports
the builtin foods when the file's `version` changed.

## How targets and warnings work

* **Suggested targets** come from `app/nutrients.py::suggest_targets()`, which encodes the
  fact-checked table in `docs/research/targets_by_stage.json`: protein 0.6–0.8 g/kg at CKD
  stages 3–5 with diabetes (0.8–1.0 at stages 1–2, 1.0–1.2 on dialysis), potassium review
  ceilings of 4000 → 3500 → 3000 → 2500 mg from stage 3a to stage 5 / hemodialysis (3500 on
  peritoneal dialysis), phosphorus 1000 mg (900 at stage 5 before dialysis), sodium 2000 mg,
  calcium 1000 mg, 30 kcal/kg with 45 % of calories as carbohydrate split per meal, and a fluid
  limit only on dialysis (1500 mL hemodialysis, 2000 mL peritoneal). Per kg means per kg of
  **ideal** body weight: with a saved height the app uses the weight at BMI 25 (or 18.5) when
  you are above (or below) the healthy range, your actual weight otherwise, and the first note
  says which weight it used. Every suggestion carries the note *"Only restrict potassium if your
  blood potassium is high; your care team sets the number."* Nothing is saved until you press
  **Save profile**.
* **Per-serving warnings** use renal-dietitian conventions: potassium 101–200 mg medium,
  > 200 mg high; phosphorus 101–150 mg medium, > 150 mg high, or **any** food flagged
  `phosphate_additive`; sodium 141–400 mg medium, > 400 mg high; carbohydrate 15–30 g
  medium ("1–2 carb choices"), > 30 g high, with `high_gi` upgrading to high from one carb choice
  (≥ 15 g) upwards and shown as a medium note below that; protein 15–25 g medium, > 25 g high.
  Foods flagged `avoid_ckd` (star fruit, potassium-chloride salt substitutes) are always high.
  Foods flagged `hypo_treatment` (glucose tablets, apple juice …) get **no carbohydrate
  warning**: treating a low is never warned against; their potassium warning stays so the
  lowest-potassium rescue can be chosen.
* **Daily status**: `ok` below 80 % of a target (the profile's `warn_fraction`), `caution`
  between 80 and 100 %, `over` above. Potassium, sodium, fluid and carbohydrate are judged
  **day by day**; phosphorus, protein, calories and calcium on the **weekly average**.

The reasoning and the sources behind every number, the eat / limit / avoid food lists, carb
counting with renal swaps, treating a low on a kidney diet and label reading are in
**[docs/diet-guide.md](docs/diet-guide.md)** (research notes in `docs/research/`).

## Regenerating the food database

`data/foods.json` is generated and committed. To add or change foods, edit the curated
list in `scripts/curated_foods.py` (look up `fdc_id`s in USDA SR Legacy's `food.csv`;
never guess them) and run

```bash
python3 scripts/build_food_db.py            # add --version 2026-10-05.2 when regenerating on the same day
```

The script downloads the USDA SR Legacy CSV zip once into `scripts/.cache/`, scales the 12
tracked nutrients to each curated household serving, derives `fluid_ml` for foods flagged
`counts_as_fluid`, validates categories and flags, runs sanity checks (banana potassium, milk
phosphorus …) and writes the JSON. Commit both the script change and the regenerated file;
the backend re-imports builtin foods on the next start because the `version` changed, keeping
row ids so existing log entries stay attached.

## Project layout

```
ARCHITECTURE.md           the contract: API shapes, data model, rules, UI behaviour
app/
  main.py                 FastAPI app factory, Basic auth, static mount, startup import
  config.py               settings from the environment
  db.py                   SQLite schema + ordered in-place migrations
  models.py               Pydantic request/response models
  nutrients.py            pure rules: registry, thresholds, daily status, suggested targets
  periods.py              pure period maths: averages, previous period, interdialytic interval
  foods.py                food search/CRUD, builtin import, USDA proxy
  log.py                  entries, day/range/period summaries, mark-eaten, copy-day, CSV
  meals.py                saved meals and the shopping list
  profile.py              profile and targets
  static/                 index.html, app.js, style.css (the whole UI, no build step)
data/foods.json           builtin food database (generated)
scripts/                  build_food_db.py and curated_foods.py
tests/                    pytest suite (API, rules, periods, planning, migrations)
docs/diet-guide.md        the renal + type 1 diet guide the rules are based on
docs/research/            research notes, fact check, targets_by_stage.json
docs/deployment.md        Podman, Quadlet, Kubernetes, backups, auth, troubleshooting
docs/network-allowlist.md outbound domains per environment
deploy/                   Containerfile, compose.yaml, quadlet/, k8s/
.github/workflows/ci.yml  pytest, image build and push to ghcr.io
```

The HTTP API is documented in `ARCHITECTURE.md` and browsable at `/docs` while the server runs.

## Roadmap

* Glucose and insulin log next to the food log (CGM readings, doses, hypo treatments as
  events), so the carb counts and lows can be reviewed together.
* Barcode lookup via Open Food Facts for packaged foods, with the phosphate-additive flag set
  from the ingredient list.
* Multi-user accounts (today the app is strictly one person per database).

## Disclaimer

This software is a logging aid, not medical advice and not a medical device. Nutrient
targets, limits and warnings must come from your nephrologist and renal dietitian, insulin
decisions from your diabetes care team; the suggested targets are published guideline
starting points that your care team should overwrite. The food database is reference data
(USDA SR Legacy and manual entries): check labels and portions. Never delay or under-treat
low blood glucose because of a potassium or phosphorus number.

## License

This project is licensed under the **PolyForm Noncommercial License 1.0.0**: you may use,
copy, modify and share it for personal and other noncommercial purposes, free of charge.
**Any commercial use requires the written permission of the author.** The full text is in
[LICENSE](LICENSE). The food data comes from USDA FoodData Central (public domain).
