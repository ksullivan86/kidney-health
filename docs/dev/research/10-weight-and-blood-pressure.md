# 10 · Weight and blood pressure (a log, the numbers your team gave you, Apple Health)

| | |
|---|---|
| Status | Decided 2026-10-22 (§8), to be built in three parts (§7). |
| Date researched | 2026-10-22, against `main` at `f3d2049` |
| Scope | A weight log and a blood pressure log: what a person records, the "alarm" and "goal" numbers their care team gave them, what the app works out from the readings and what it shows, the handbook's words for a warning sign, storage, API, settings, export/import/delete, the demo's twin, an import from the iPhone Health app's `export.xml`, and tests. |
| Out of scope | Glucose, insulin and every medicine (no dosing, ever: CLAUDE.md); a blood pressure goal or a dry weight chosen by the app; advice on taking, skipping or changing a blood pressure medicine; cuffless devices (watches, rings) as a source the app trusts; live push from an iPhone Shortcut (ROADMAP: needs narrow write tokens); scale or cuff vendor APIs (Withings, Omron); sending these readings to an AI provider or the assistant (§4.9); an offline queue for them (§4.10). |
| Builds on | The symptoms log (ARCHITECTURE "Symptoms log": the pattern of a Today card, a sheet, a Trends section and handbook pointers checked against the page), visit prep (`js/engine/visitprep.js`), the lab imports from Apple Health and C-CDA (read on the device, nothing uploaded but the rows the person keeps), note 05 (profile weight, the GLIM weight-loss rule), note 07 (settings registry, export, delete). |
| Re-verify | The Apple Health `export.xml` layout (§4.8) against a real export from an iPhone before calling the import done (the owner; the samples are hand-written, as for the clinical-records import). The 2025 AHA/ACC guideline's home-monitoring wording against its full text when the handbook page is written. |

---

## 1. Context

### 1.1 The ask

The owner's idea list (ROADMAP "Ideas from the owner", 2026-10-07): "Weight (and later blood pressure) from an Apple Health
export", after comparing similar projects that import Apple Health blood pressure; and (2026-10-15) "setting diet macros or
other inputs tracking and warning levels". The owner asked on 2026-10-22 to build what is next on the roadmap.

### 1.2 What exists today

| What | Where | Today |
|---|---|---|
| Profile weight | `profile.weight_kg` (Profile, "Weight (kg)"; on dialysis "your dry (target) weight after a session") | One number, used for protein and calorie targets (note 05). Changing it changes targets. |
| Weight 6 months ago | `profile.weight_6_months_ago_kg` | Feeds the GLIM rule N-1 (`target_rules.WEIGHT_LOSS_PCT = 5.0`: more than 5 % in 6 months). The person has to remember it. |
| Fluid | targets, the interdialytic allowance (note 05, `periods.py`) | Fluid is counted from food and drinks; nothing records weight. |
| The handbook on weighing | `stages/hemodialysis-in-centre.md`: "Weigh yourself every morning and before each session. Write it down." and "enter [your weight-gain limit] in the app"; `app/first-setup.md`: "The app has no field for your weight-gain limit"; `stages/peritoneal-dialysis.md`: "Weigh yourself daily" | The app tells people to weigh and has nowhere to put it. |
| The handbook's warning sign | `get-help-now.md`, "Call your care team today": "**weight gain above the alarm number** your team gave you" (Cabrera 2015, KDIGO 2024 Table 41) | Words the app can quote, as the symptoms log does. |
| Blood pressure in the handbook | `ckd/diabetes-and-your-kidneys.md`, `t1d/kidney-protecting-medicines.md`: KDIGO 2024 rec. 3.4.1 (top number under 120 measured the standard way at the clinic) and ADA 2026 rec. 11.5 (under 130/80); "Know your blood pressure goal, and check at home if your team asks you to." | No thresholds for a home reading and no warning sign for a very high reading. |
| Apple Health | `js/views/lab_fhir.js`, `js/engine/fhir_labs.js` | Reads the `clinical-records/` FHIR files in the browser. Nothing reads `export.xml`. |

---

## 2. Goals and non-goals

Goals:

1. Record a weight (with when it was taken: morning, before or after dialysis, other) and a blood pressure reading (top and
   bottom number, optional pulse) in a few taps, see them on Today and as a trend on Trends, and take them to a visit.
2. Let the person enter the **numbers their team gave them** — a weight-gain alarm and a blood pressure goal — and show
   plainly when a reading is past them, with the handbook's own words for what to do. The app never invents either number.
3. Point to the handbook when a blood pressure reading is very high (§3, F5), the way the symptoms log points to Get help
   now: words copied from the page, a link, nothing about a cause or a medicine.
4. Fill the GLIM input (weight 6 months ago) and offer the latest weight for Profile **only when the person taps it**.
5. Bring in past weights and readings from the iPhone Health app's `export.xml`, read on the device.

Non-goals (and why):

* **No goal or alarm by default.** KDIGO's top-number target of 120 is for blood pressure measured "the standard way" at the
  clinic, and home readings only complement it (F3); the right home goal and weight-gain alarm are the team's (the handbook
  already says "your team's limit"). An empty goal shows readings without a verdict.
* **No medicine advice** of any kind (CLAUDE.md), not even "talk to your team about your pills": the handbook's line names the
  action ("call your care team today"), not a treatment.
* **Profile weight never changes by itself.** It moves targets, and on dialysis it is the *dry* weight the unit sets, which a
  scale reading is not.

---

## 3. Facts used (each number in the app or the handbook traces to one of these)

| | Fact | Source | Used for |
|---|---|---|---|
| F1 | Weight loss of more than 5 % within 6 months is a GLIM phenotypic criterion for malnutrition. | GLIM 2019 (Cederholm et al., Clin Nutr 2019;38:1–9, doi 10.1016/j.clnu.2018.08.002), already `target_rules.URL_GLIM_2019` | The 6-month change shown in visit prep and the "weight 6 months ago" helper (§4.6). No new alert. |
| F2 | On hemodialysis, gains between sessions above 3.5 % of body weight are linked to death. | Cabrera 2015 (handbook source DG28a) | Handbook text only (an example of what a team's limit may be). Not an app default. |
| F3 | KDIGO 2021 blood pressure in CKD: rec. 1.1 standardized office measurement in preference to routine office measurement; rec. 1.2 home or ambulatory readings *complement* standardized office readings; rec. 3.1.1 a systolic target under 120 when tolerated, **using standardized office measurement**. | KDIGO 2021 Clinical Practice Guideline for the Management of Blood Pressure in CKD, Kidney Int 2021;99(3S):S1–S87 | Why the app has no home goal of its own (§2). |
| F4 | Home monitoring with a validated upper-arm (oscillometric) cuff is recommended; cuffless devices (watches, rings) are not recommended for clinical blood pressure assessment; severe hypertension is above 180/120. | 2025 AHA/ACC/AANP/… Guideline for the Prevention, Detection, Evaluation and Management of High Blood Pressure in Adults, Hypertension 2025;82(10):e212–e316, doi 10.1161/HYP.0000000000000249 (re-verify the wording against the full text) | The handbook page's "how to measure" and "which device" lines. |
| F5 | "If your blood pressure is 180/120 but you don't have symptoms, wait 5 minutes and check your blood pressure again. If it is still high, call your healthcare provider…" ("who may recommend starting a medicine or changing your dose": not repeated in the handbook). If the second measurement is also high and there is a sudden severe headache, difficulty breathing, sudden severe pain in the abdomen, chest or back, numbness or weakness, a sudden change in vision or problems talking: call 911; "Do not wait to see if your pressure comes down on its own." | NHLBI, "High Blood Pressure – Symptoms", last updated 2024-04-25 (https://www.nhlbi.nih.gov/health/high-blood-pressure/symptoms) | The new Get help now lines (§4.5) and the app's pointer for a reading at or above 180 or 120. |
| F6 | How to measure at home: rest about five minutes in a chair, sit up straight, legs uncrossed and feet flat, an upper-arm cuff that fits snugly, the same time of day each time. | MedlinePlus, "Measuring Blood Pressure", last updated 2024-08-26 (https://medlineplus.gov/lab-tests/measuring-blood-pressure/) | The handbook page and the sheet's one-line hint. |
| F7 | 1 lb = 0.45359237 kg exactly. | The international pound (1959); NIST SP 811 Appendix B | Unit conversion (§4.4). |

The plausibility ranges in §4.1 (what a form accepts) are the project's own choice, not clinical numbers, and are labelled
so in the code.

---

## 4. Design

### 4.1 Storage (schema step 18, `m018_body_measurements.py`)

Two tables, because the two readings validate differently; both `ON DELETE CASCADE` from `users`.

```sql
CREATE TABLE weights (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,                 -- YYYY-MM-DD, the person's day
  time TEXT,                          -- HH:MM on the person's clock, optional
  kg REAL NOT NULL,                   -- stored in kg, two decimals
  context TEXT NOT NULL,              -- morning | before_dialysis | after_dialysis | other
  note TEXT,                          -- at most 200 characters
  source TEXT NOT NULL DEFAULT 'manual',   -- manual | apple_health | import
  source_key TEXT,                    -- the import's de-duplication key (§4.8), NULL for manual rows
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX weights_user_date ON weights(user_id, date);
CREATE UNIQUE INDEX weights_user_source_key ON weights(user_id, source_key) WHERE source_key IS NOT NULL;

CREATE TABLE blood_pressures (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  time TEXT,
  systolic INTEGER NOT NULL,          -- mmHg, the top number
  diastolic INTEGER NOT NULL,         -- mmHg, the bottom number
  pulse INTEGER,                      -- beats a minute, optional
  context TEXT NOT NULL,              -- morning | evening | before_dialysis | after_dialysis | other
  note TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  source_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
-- the same two indexes
```

Validation (Pydantic models in `app/models.py`, the same rules in the twin): `kg` 20–400 (the profile's
`weight_6_months_ago_kg` range); `systolic` 50–300, `diastolic` 20–200, `systolic > diastolic`, `pulse` 20–250 (project's
own plausibility ranges); dates as the symptoms log checks them (no date in the future, none before 1900); `time`
`HH:MM` 00:00–23:59; at most 20 weights and 30 readings on one day (a 21st is a 400, like the 31st symptom). No `CHECK`
constraints in SQL beyond `NOT NULL` (the project keeps enums in the models so a later value needs no table rebuild).

### 4.2 API (`app/body.py`, router prefix `/api/body`; every route `current_user`, scoped by `user.id`, not yours → 404)

* `GET /api/body/weights?start=&end=` and `GET /api/body/blood-pressure?start=&end=` (both required, at most 366 days, the
  symptoms' `parse_range`) → `{weights: [...]}` / `{readings: [...]}`, oldest first, then by time (no time last), then id.
  Each blood pressure row carries `flag` (§4.5) or `null`.
* `POST` to each → 201, the stored row; `PUT /…/{id}` → 200 (replaces the editable fields; `source` becomes `manual` once a
  person edits an imported row, `source_key` stays so a second import does not bring the old value back); `DELETE` → 204.
* `POST /api/body/weights/batch` and `POST /api/body/blood-pressure/batch` `{rows: [...]}` for the import (§4.8): at most
  1,000 rows a request, each with a `source_key`; the whole request is checked first and refused on the first invalid row
  (the lab import's rule); rows whose `source_key` the person already has are skipped and counted → `{added, skipped}`.
* `GET /api/body/summary?date=` → what Today and the Settings preview show: `{weight: {latest, previous, gain, alarm},
  bp: {latest, week: {count, systolic, diastolic, above_goal}, goal, flagged_today}, units}` (§4.4), computed by
  `app/body.py` from the rows; the twin computes the same from the mock's rows.

### 4.3 Settings (registry, `scope="user"`, in the export, mirrored by `js/engine/settings.js` and its vectors)

* `user.units.weight`: `kg` or `lb`, `scope="user_default"` like `user.units.labs`, default `lb` (the app's US defaults: 911,
  mg/dL). Only display and entry change; storage is kg.
* `body.weight_alarm`: `{amount_kg: number | null (0.2–10), over: "between_sessions" | "days", days: 1–7}`; default
  `{amount_kg: null, over: "days", days: 1}`. `between_sessions` is offered only on hemodialysis. Shown as "Call my team if my
  weight goes up by more than [ ] [kg/lb] [between sessions | in [n] days]" with "Use the number your team gave you".
* `body.bp_goal`: `{systolic: 80–200 | null, diastolic: 40–130 | null}`; default both `null`. Shown as "My blood pressure
  goal from my team: under [ ] / [ ]".

### 4.4 What the app works out (pure functions in `app/body.py`, twin `js/engine/body.js`, vectors `tests/data/body_vectors.json` from `gen_body_vectors.py`)

* **Units.** `kg = lb × 0.45359237` (F7), stored rounded to 0.01 kg; shown in the person's unit to one decimal
  (`round half away from zero`, the project's `round_half_up` helpers, so 154.25 lb shows 154.3 on both sides).
* **Weight gain against the alarm** (only when `amount_kg` is set):
  * `between_sessions` (hemodialysis): reference = the latest `after_dialysis` weight dated in the 7 days before the latest
    weight (inclusive of the same day if earlier in time); without one, the profile's dry weight, labelled "your dry weight in
    Profile"; without either, "Add a weight after a session to compare". Gain = latest − reference.
  * `days`: reference = the latest weight **with the same context** dated on or before `latest.date − days`, looking back at most
    `2 × days` days; without one, "Not enough weights to compare yet". Gain = latest − reference.
  * `over_alarm = gain > amount_kg` (strictly more, as the setting's words say). The result names the two readings compared, so
    the person can see why.
* **Blood pressure week.** Readings dated `date − 6` … `date`: count, mean systolic and mean diastolic (each rounded half up to
  an integer), and `above_goal` = a goal number is set and that mean is **at or above** it ("under 130/80" means 130 is not
  under). Fewer than 3 readings → the means are shown with "only n readings" and no `above_goal` verdict.
* **Six-month change** (visit prep and the Profile helper): the latest weight against the weight dated closest to 182 days
  before it, within ±30 days; kg and % (one decimal). No alert: visit prep shows it, and the GLIM rule (F1) reads it only if
  the person copies it into Profile.

### 4.5 The handbook's words for a warning sign (as `app/symptoms.py` `RED_FLAGS` does)

* **Weight over the alarm**: the line quotes the existing Get help now phrase — "The handbook lists “weight gain above the alarm
  number your team gave you” under “Call your care team today”." — with the link. Not prominent (the person set the number).
* **Blood pressure at or above 180 top or 120 bottom** (a single reading; F5's "180/120"): Part A added two lines to
  `get-help-now.md`, cited to NHLBI (F5, source id `NHLBI-BPS`, page read 2026-10-22): under **Call your care team today**
  (a new group "Blood pressure"): "**A blood pressure of 180/120 or higher** that is still that high when you check again after
  resting 5 minutes"; under **Call 911 now**: "**A blood pressure of 180/120 or higher with** a sudden severe headache, trouble
  breathing, sudden severe pain in the chest, belly or back, numbness or weakness, a sudden change in vision or problems
  talking. Call even if you have not measured again, and do not wait to see if it comes down on its own" (MedlinePlus
  `MEDLINE-BPM`: over 180/120 with those signs, call 911; and NHLBI's "Do not wait"; NHLBI's own "if the second measurement is
  also high and if you have any of these symptoms" could be read as waiting with emergency signs, so the handbook takes the safer
  reading, decided 2026-10-22 at review). The page's clause that the provider "may recommend starting a medicine or
  changing your dose" is **not** repeated (no medicine advice). The wallet card (`includes/help-card.md`) carries both in a few
  words. The reading's `flag` quotes the 911 line **first**, then says that without those signs a person rests 5 minutes and
  measures again, quoting the care-team line; it links to the page and is **prominent**. A second reading within 15 minutes that is still that high changes nothing in the app's words (the page
  already says what to do). Reading "180/120" as a top number of 180 or more **or** a bottom number of 120 or more is the
  project's cautious choice (NHLBI does not say), and is an open item for the clinician review (`handbook/REVIEW.md`,
  "Emergency tiers and red flags").
* `tests/test_body.py` checks every quoted phrase against the page, under the group it is quoted for (like
  `tests/test_symptoms.py`), so the app never quotes words the page no longer has. `handbook/REVIEW.md` has the new lines under
  "Emergency tiers and red flags" for the clinician review (done in Part A).
* Low blood pressure has no number in the app: the handbook already lists dizziness on standing (a symptom, `stages/g3a.md`);
  a reading below the plausibility range is refused as a typing error.

### 4.6 Screens (Part B)

* **Today**: a card "Weight and blood pressure" under Symptoms: the day's weights and readings (Edit, Delete), **Add weight**
  and **Add blood pressure** (sheets; nothing saved until Save), the alarm line or the goal line when set, and the flag block
  for a very high reading first. The weight sheet asks when it was taken (morning / before dialysis / after dialysis / other;
  the dialysis ones only on dialysis), defaults the unit to the setting and echoes the other unit ("154.3 lb = 70.0 kg"). The
  blood pressure sheet has the top and bottom number in that order with their plain names ("top number (systolic)"), pulse
  optional, and one line from F6 ("Rest 5 minutes, sit with feet flat, cuff on your upper arm").
* **Trends**: a section with a weight chart (one line; on dialysis a dashed line for the profile's dry weight; markers for
  after-dialysis weights) and a blood pressure chart (top and bottom numbers as two lines, the goal as dashed lines when set),
  both plain SVG built with the DOM (no chart library, no inline style), each with a table under it so nothing depends on
  seeing the chart or on colour; the 7-day averages.
* **Settings → Weight and blood pressure** (personal settings page): the unit, the alarm and the goal, each saying "from your
  care team"; a link to the handbook page.
* **Profile**: under Weight, when the log has one: "Latest in your log: 70.2 kg on Oct 20 — Use this" (not shown on dialysis,
  where Profile holds the dry weight); under Weight 6 months ago: "In your log: 74.0 kg on Apr 21 — Use this" (the six-month
  rule of §4.4). Using either fills the field; Save still saves.
* **Visit prep**: latest weight, the six-month change, on hemodialysis the gains between the last sessions (up to 6, with the
  alarm if set); blood pressure 7-day and 30-day averages, the number of readings, how many were at or above the goal, and any
  flagged reading with its date.
* **Handbook**: a "Using the app" page `app/weight-and-blood-pressure.md` (what to record, how to measure (F6), which device
  (F4), the alarm and goal are the team's (F3), what the app shows and does not); `app/first-setup.md` loses "The app has no
  field for your weight-gain limit"; `stages/hemodialysis-in-centre.md`'s "enter them in the app" links to the new page; Get
  help now gained the two lines of §4.5 in Part A. Every new handbook sentence with a number cites F2–F6.

### 4.7 The demo (GitHub Pages) and parity

`js/mock/body.js` serves the same routes from the browser store with the same validation and the same `flag`, `summary` and
batch results (`js/engine/body.js`); `seed.js` adds two weeks of sample weights and readings (one over the sample alarm, none
at 180/120, so the demo never shows the emergency block unasked). `node tests/js/run_vectors.mjs` runs `body_vectors.json`
(conversions and rounding, the gain cases of §4.4 including missing references, the week means and the goal boundary, the
six-month match, the flag boundaries (179/119 → none; 180/80 → flagged; 140/120 → flagged), validation errors in order).

### 4.8 Import from the iPhone Health app (Part C)

* **Where**: Trends → Weight and blood pressure → **Import from Apple Health**, and Settings → Your data next to the other
  imports. The person exports from the Health app (profile picture → Export All Health Data), taps `export.zip` in the Files
  app to unzip it, and picks `apple_health_export/export.xml`. (Reading the zip directly was the ROADMAP's "Import from a file
  takes the export .zip" item; it is built, and this import uses the same reader: note 11. The sheet now takes `export.zip` itself.)
* **Reading**: the file can be hundreds of megabytes and starts with an internal DTD, so it is **not** given to an XML parser
  (no `DOMParser`, no `kh-xml` policy, no entity expansion): `js/engine/apple_health.js` streams it as text
  (`file.stream().pipeThrough(new TextDecoderStream())`), finds each `<Record ` start tag of the three types below with a
  bounded buffer (a tag longer than 8 KiB is skipped and counted), reads its attributes in one linear pass (a hand-written
  scanner, not a regular expression: one that may start a name anywhere is quadratic on a hostile 8 KiB tag), decodes
  only the five XML entities and numeric character references (anything else: the record is skipped and counted), and keeps:
  * `HKQuantityTypeIdentifierBodyMass` with `unit` `kg` or `lb` → a weight (context `other`, or `morning` when the time is
    04:00–10:59);
  * `HKQuantityTypeIdentifierBloodPressureSystolic` and `…Diastolic` with `unit` `mmHg`, paired by identical `startDate`
    and `sourceName` (inside a `HKCorrelationTypeIdentifierBloodPressure` correlation or not; a lone half is skipped and
    counted) → a reading (context by time: morning 04:00–10:59, evening 17:00–23:59, else other).
* `date` and `time` come from `startDate` (`YYYY-MM-DD HH:MM:SS ±HHMM`) **as written** (the person's clock when measured).
  `source_key` = the first 32 hex characters of SHA-256 over `type|startDate|value|sourceName` (blood pressure: both values),
  so importing the same export twice adds nothing.
* **Details settled when the reader was built** (its header comment has them in full; `tests/data/apple_health_vectors.json`
  pins each): a start tag ends at the first `>` outside quotes, and a `<` inside it ends it early (skipped and counted as
  unreadable); `type` and `unit` are compared as written (`KG` is an unknown unit) and only `value`, `startDate` and `sourceName`
  are decoded, so an entity in any other attribute is never looked at; a missing `value`, `startDate` or `sourceName`, a value
  that is not a plain number, or a `startDate` that is not a real day (before 1900, or, when the page passes today's date, more
  than one day ahead, the server's own rule, because a batch with one bad row is refused whole) is **unreadable**, a reason of its
  own in the summary. A systolic or diastolic with no partner, or two different values from one source at one instant (pairing
  them would be a guess), is a half pair; a top number not above the bottom one counts as out of range; readings are whole mmHg
  (a fraction rounds half up). The same record twice (type, `startDate`, value and `sourceName` equal, as inside a correlation
  and again loose) is one, the repeat counted as a duplicate. The `source_key` texts are exactly
  `HKQuantityTypeIdentifierBodyMass|<startDate>|<value>|<sourceName>` and `BloodPressure|<startDate>|<systolic>/<diastolic>|<sourceName>`,
  `startDate` and values as written (a weight in pounds stays in pounds) and `sourceName` decoded. Rows carry `sourceName` for
  the sheet only (`forUpload` drops it) and come out sorted by date, time and source. SHA-256 is `crypto.subtle`, or a small
  plain-JavaScript SHA-256 where the page has none (a self-hosted app on a plain-HTTP address). `scan` takes an `AbortSignal` and
  calls back about every 10 MB for the progress line.
* **Review before saving**: the headline counts what was found, the date range, what was skipped and why (unknown unit,
  half a pair, out of range, already there); the person picks a period (the last 3 months by default, "everything" possible)
  and presses Import; rows go up in batches of 1,000. Readings from a source whose `sourceName` contains "Watch" are listed
  separately and unticked by default, with F4's line that cuffless devices are not recommended for checking blood pressure;
  the person decides.
* Nothing else in the file is read or kept (no heart rate, no steps, no glucose, no insulin: CLAUDE.md), and nothing is
  uploaded but the rows the person imports.

### 4.9 Privacy and security

* Health data: never in logs (the activity log records "added a weight" with no value), only in the person's own export;
  deleted with the account (`ON DELETE CASCADE`).
* **Not sent to an AI provider or the assistant** in this version: `app/ai/`, `app/mcp/` and `app/guidance/` do not read the two
  tables (a test checks, as for symptoms). A later version can add them to Ask's `get_today` behind the existing consent; that
  is a ROADMAP line, not part of this note.
* Every route: `current_user`, scoped by `user.id`, not yours → 404, `tests/test_auth_coverage.py` lists them; the batch
  routes keep the default body-size limit and allow 60 requests an hour per person (60,000 rows; the project's own limit,
  room for years of daily weights).
* No inline script or style; all text through `textContent`; the import runs in the page, with no new network host.

### 4.10 Offline

Like symptoms, weights and readings need the connection in this version (a save offline says so; the Today card shows the
last loaded rows from the snapshot only if they were loaded). The offline outbox (note 02 R5) is for the food log; adding
these to it is a ROADMAP line.

### 4.11 Export and import (`app/account.py`, `app/data_import.py`, the demo's `export.js`/`import.js`)

`export.json` gains `weights` and `blood_pressures` (oldest first, without `user_id`; `source_key` kept); the archive gains
`weights.csv` and `blood_pressure.csv` with a header and the README's lines. **Import from a file** accepts both lists with the
same validation (and the per-day limits), "Add to my existing data" skips rows whose `source_key` exists and adds manual rows
as new; replacing removes the person's rows first. The export version stays 1 (older files have neither list).

### 4.12 Decisions made while building Part A (where the code's pattern or a detail the note left open decided)

Each follows the symptoms log (the established pattern) unless it says otherwise; the code and `ARCHITECTURE.md` "Weight and blood pressure" are the
contract.

* **Storage.** `id` is `INTEGER PRIMARY KEY AUTOINCREMENT` (ids are never reused, as in every other table) rather than the note's plain `INTEGER PRIMARY
  KEY`; no `CHECK` beyond `NOT NULL`, as §4.1 says (the symptoms table has some, these have none on purpose). A note is stored as `''` (never `NULL`); `time`
  and `source_key` are `NULL` when there is none. The unique index is partial (`WHERE source_key IS NOT NULL`), as §4.1 says.
* **API.** A blank `time` means no time. `kg` is kilograms only (Part B converts what the person types and shows). `source_key` is internal: it is in the
  export, not in `WeightOut` / `BloodPressureOut`. The batch routes answer **200** `{added, skipped}` (nothing is "created" as one resource; `POST /api/log/batch`'s
  201 is for entries) and refuse the whole request on the first row that is not valid or would overfill a day, naming it `rows.N.field: …` with **all** of that
  row's problems (`rows.N: …` for the top-below-bottom rule). A batch row's `source` is `apple_health` or `import` (default `import`), never `manual`. The one
  `body_batch` limit (60 an hour per person) covers both routes. `PUT` sets `updated_at` and makes the row `manual`; there is no activity row for weights or
  readings, as for symptoms (§4.9's "added a weight with no value" is not recorded: nothing about them is).
* **Summary** (`GET /api/body/summary?date=`; `date` required): the note's `{weight: {latest, previous, gain, alarm}, bp: {latest, week, goal, flagged_today},
  units}` is `{date, units, weight: {latest, previous, gain: {kg, since} | null, alarm | null}, bp: {latest, week: {count, systolic, diastolic, above_goal,
  above: {systolic, diastolic}, few}, goal, flagged_today}}`. `alarm` is the §4.4 check (`status`, `reference_kind`, `reference`, `reference_kg`, `gain_kg`,
  `over_alarm`, `message`, `flag`); `flagged_today` is the latest flagged reading dated that day; `above_goal` is true when either number's mean is at or
  above its goal number (`above` says which). The "dry weight in Profile" is used **only while the profile says hemodialysis**.
* **Settings.** The goal also refuses a top number that is not above the bottom one (as a reading does). `user.units.weight` is in the admin's "Default for
  everyone" group like `user.units.labs`. All three are carried over by an import with `replace_profile` (so the care team's numbers move with the person),
  and the "not selected" line names them.
* **Flags.** Both are `{level, text, href, link_text, prominent}` like a symptom's `red_flag`; the blood pressure flag's `level` is `emergency` (it points to both
  groups). The weight flag is `today`, not prominent. The 911 line on the page needs no second reading when a sign is there (MedlinePlus; see §4.5), the
  flag's text puts it first, and the wallet card carries both lines.
* **Import and export** (§4.11). There is **no "replace my data" mode** in the code (an account that has data is a 409 unless `merge=1`, for every kind), so
  that part of §4.11 is not built; a row with a `source_key` is left out when the person has that key, a typed row when an identical one is there, a day over
  its limit is skipped and listed (like symptoms), and the lists are capped at 20,000 rows each. `weights` and `blood_pressures` follow `symptoms` in
  `export.json`.
* **The demo.** `index.html` lists the two new scripts and `sw.js` precaches them (needed for the twin to load; no screen). The sample data are two weeks with a
  sample alarm (1 kg in a day; on hemodialysis 2 kg between sessions) and goal (130/80), today's weight over the alarm and no reading at 180/120.
* **Not in Part A:** every screen, the Profile helpers, the visit prep section, the handbook page "Using the app", the Apple Health import. The import
  summary lines in Settings (`IMPORT_KINDS` in `js/views/settings.js`) and the "Data imported" activity line do not name weights and readings yet (Part B).

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| A real `export.xml` differs from the hand-written samples (attribute order, units such as `g`, nested correlations). | The scanner reads attributes in any order; unknown units are skipped and counted in the headline; the owner runs a real export before the import is called done (the header's Re-verify line). |
| People read a home reading against KDIGO's 120 and worry. | No app goal; the handbook page explains F3 in one sentence; the goal field says "from your care team". |
| The 180/120 block frightens someone after a mis-typed number. | The sheet echoes the reading before Save ("Top 180, bottom 95"); the block says to rest and measure again first (F5). |
| Weight-gain alarms with mixed contexts (morning vs evening) give noise. | `days` compares the same context; `between_sessions` uses after-dialysis weights; both name the two weights compared. |
| A large import freezes the phone. | Streamed reading, bounded buffers, only three record types kept, a progress line every 10 MB, batches of 1,000. |

---

## 6. Tests (per part; `python -m pytest` with no network, `node tests/js/run_vectors.mjs`)

* **A**: migration m018 on a populated step-17 database (`tests/test_migration_m018.py`); validation boundaries (every range
  end, `systolic > diastolic`, future dates, per-day limits, unknown fields); CRUD and batch with two users (not yours → 404,
  batch de-duplication, all-or-nothing); summary cases; `flag` phrases checked against `get-help-now.md` (Part A asserts the
  existing weight phrase and the two blood pressure lines it added); export/import round trip; settings
  validation and the settings vectors; the AI, MCP and guidance packages never read the tables; body vectors in Python and JS;
  the mock matches the server on the vectors' requests.
* **B**: the UI tests in the style of `tests/test_symptoms_ui.py` (no `innerHTML`, sheet fields, Profile helpers, Settings
  fields), the handbook checks (strict build, links, `tests/test_handbook_content.py`, every number cited), and a browser
  harness `tools/e2e/body.py` (add, edit, delete, alarm line, 180/120 block, charts with their tables, Profile "Use this",
  visit prep, 375 px and desktop, light and dark, the demo).
* **C**: `apple_health_vectors.json` (hand-written `export.xml` fragments: kg and lb, a correlation and loose pairs, a lone
  half, entities, an over-long tag, a DTD at the top, duplicates), the scanner run on a 200 MB generated file under a memory
  bound in Node, the review sheet in the harness.

---

## 7. Parts and build order

| Part | Contents | Rough size |
|---|---|---|
| A | m018, `app/body.py` (routes, summary, flags, validation), models, settings keys, export/import, auth coverage, `js/engine/body.js`, `js/mock/body.js`, seed data, `core.js` API helpers, vectors and generator, tests, the two Get help now lines (with `NHLBI-BPS`, the wallet card and REVIEW.md), ARCHITECTURE (schema table, "Weight and blood pressure" section, module map), docs page `docs/body.md`, CHANGELOG | 1.5–2M |
| B | Today card and sheets, Trends charts, Settings section, Profile helpers, visit prep section, CSS, the handbook page (`app/weight-and-blood-pressure.md`), `tools/e2e/body.py`, UI tests, docs and CHANGELOG | 1.5–2M |
| C | `js/engine/apple_health.js`, the import sheet, vectors, the large-file test, harness steps, docs and CHANGELOG | 1–1.5M |

A first (B and C need its routes and twin); B and C can be built in parallel after A merges (they touch different views;
both add to `index.html` and `core.js`, merged by hand).

---

## 8. Decisions (2026-10-22)

The owner asked to build what is next on the roadmap; these are the calls this note makes, each open to the owner's change.

| | Question | Decision |
|---|---|---|
| Q1 | Default weight unit | `lb`, per person and per server default (like `user.units.labs`); storage in kg. |
| Q2 | Does the app suggest a home blood pressure goal? | No. Only the team's number (F3). |
| Q3 | Which very high reading gets the handbook pointer? | A top number at or above 180 or a bottom number at or above 120 (NHLBI's "180/120", F5), with the page's two new lines; prominent. |
| Q4 | Weight alarms | The team's number only, "between sessions" (hemodialysis) or "in n days", compared as §4.4 says. |
| Q5 | AI and assistant | Not sent in this version (§4.9); a ROADMAP line for later, behind consent. |
| Q6 | Offline | Needs the connection, as symptoms do (§4.10). |
| Q7 | Profile weight | Never changed by the log; "Use this" fills the field when tapped, and not on dialysis (dry weight). |
| Q8 | Apple Health | `export.xml` streamed as text in the browser, three record types, no XML parser, nothing uploaded but the rows kept; watch-sourced readings unticked by default. |
