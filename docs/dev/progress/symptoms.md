Status: complete

# Symptoms log (ROADMAP "Symptoms log (medium)")

Role: `symptoms`. Worktree branch `worktree-agent-a89a43915d2fb3607`, fast-forwarded to `claude/adoring-sagan-th5swr`
(`e8706fa`, schema steps 1-14; the worktree was created at `3e887f5`, one step short). Schema step 15 is
`app/migrations/m015_symptoms.py`. Do not touch `app/ai/`.

## State

- [x] 1 migration step 15, `app/symptoms.py` (routes, red-flag table), `Symptom*` models, tests
      (`tests/test_symptoms.py`, `tests/test_migration_m015.py`)
- [x] 2 export (`symptoms` in export.json, `symptoms.csv`) and import (`ImportSymptom`) with tests; the existing
      import/export tests were widened for the new key (`symptoms: 0`)
- [x] 3 JS twin (`js/engine/symptoms.js`, `js/mock/symptoms.js`), parity vectors (`tests/data/symptoms_vectors.json`,
      generator `tests/data/gen_symptoms_vectors.py`), `tests/js/demo_loader.mjs` (shared by `demo_api.mjs` and
      `run_vectors.mjs`), `tests/test_symptoms_vectors.py`
- [x] 4 UI: Today card + sheet, Trends list, `css/symptoms.css`, `index.html`, `sw.js`, `tests/test_symptoms_ui.py`,
      `tools/e2e/symptoms.py` (64 checks pass in Chromium: 375 px light, 1280 px dark, the demo)
- [x] 5 isolation matrix entry, auth coverage, delete-account cascade
- [x] 6 docs: ARCHITECTURE ("Symptoms log" section, migrations row, routes, export/import), handbook
      (`reports-for-your-team.md`, `privacy.md`, `index.md`), `docs/privacy.md`, README, CHANGELOG, ROADMAP
- [x] 7 full pytest run once in the foreground: exit 0 (`python -m pytest -q -x -p no:cacheprovider`)

## Decisions and why

- Red flags are exactly what `handbook/docs/get-help-now.md` sorts as "Call 911 now" (breathlessness) and "Call your
  care team today" (new swelling of the legs, ankles or face). Itch, tiredness, poor appetite, nausea and cramps are in
  "Mention at your next visit": no link and no line. `tests/test_symptoms.py` checks each quoted phrase against the page.
- The red-flag line is the handbook's own words in quotes plus its group heading; the app adds no cause, treatment or dose
  (a regex test over the lines, the view, the twin and the sheet).
- No CHECK on the symptom key in the table (a later key must not need a rebuild); the app validates the key.
- `PUT /api/symptoms/{id}` replaces the editable fields (same body as create). `label` only for `other`.
- A day holds at most 30 symptoms per person (storage bound); the import skips and lists the excess.
- The export format version stays 1 (an optional list, like `builtin_foods`); `symptoms.csv` is new in the archive.
- An account that has symptoms counts as "has data" for the import (409 without `merge=1`), so the `existing` and
  `counts`/`already_there` answers gained a `symptoms` key.
- No severity is pre-chosen in the sheet (the person chooses it); days after today cannot be added to.
- The demo has no sample symptoms (its ids start at 1 so the vectors can replay on it).

## Reproduce

```
python -m pytest -q -p no:cacheprovider tests/test_symptoms.py tests/test_symptoms_ui.py tests/test_symptoms_vectors.py tests/test_migration_m015.py
node tests/js/run_vectors.mjs
python tools/e2e/symptoms.py --port 8078 --out "$TMPDIR/kh-symptoms"
python tests/data/gen_symptoms_vectors.py        # after a change to app/symptoms.py or SymptomCreate
```
