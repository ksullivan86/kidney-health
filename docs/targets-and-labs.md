# Personalised targets, lab results and kidney function

This page explains how the app's **suggested targets** are worked out from a person's profile and lab
results, what each lab result changes (and what it never changes), when the app refuses to suggest
anything, and how the eGFR card works. It is written for the people who run and maintain the app and
for anyone who wants to check the reasoning. The patient handbook explains the same rules in plain
words (`/learn/app/targets-and-warnings/`).

The normative specification is [design note 05](dev/research/05-personalized-targets.md) (§4 and its
fact-check, §10); the API is in [ARCHITECTURE.md](../ARCHITECTURE.md), "M2 API: targets and labs". The
code is `app/targets.py` (rules), `app/target_rules.py` (every number, source and note text),
`app/kidney_function.py` (eGFR), `app/units.py` (lab units) and `app/labs.py` (the lab API).

> **Starting points, not prescriptions.** Every suggestion is labelled "discuss with your care team",
> shows the rule, source and grade behind each number ("Why this number?"), marks the project's own
> choices as expert opinion, and is **never saved** until the person presses **Save profile**. The app
> never suggests insulin or medicine doses, never limits hypo treatments, and the optional AI layer may
> explain these rules but never changes a number. The rules marked *opinion* have **not yet been
> reviewed by a renal dietitian or nephrologist** (checklist C10 of note 05; see "Open clinical
> review" below). Until they have, keep `targets.lab_rules_enabled` off on public demo servers; the
> built-in demo (`?mock=1` and the preview) starts with it off for that reason (its admin can switch it on).

## What the person can enter

Profile → **About you** (all optional; every field can be cleared):

| Field | Values | Used for |
|---|---|---|
| Birth month | `YYYY-MM`, not in the future, within 120 years | age: energy, protein from 65, calcium at stages 1–2, the GLIM low-BMI cut-off, eGFR, the under-18 refusal |
| Sex used in medical formulas | female, male, unspecified ("prefer not to say") | energy, calcium at stages 1–2, eGFR, the fluid note. *Choose the sex your lab uses for your eGFR; with gender-affirming hormones ask your clinician. "Prefer not to say" uses an average and shows ranges.* |
| Activity | inactive, low active, active, very active (not chosen: the server default, `inactive`) | energy |
| Transplant date | `YYYY-MM-DD`, not in the future | transplant rules when dialysis is "none"; the 12-week refusal |
| Frailty or low muscle mass (as told by the care team) | yes/no | nutrition risk |
| Weight 6 months ago | 20–400 kg | weight-loss nutrition risk |
| Pregnant or breastfeeding | yes/no | refusal |
| "I have had high potassium / I take a potassium binder" | yes/no | keeps the potassium ceiling when potassium is normal |
| 24-hour urine volume | 0–5000 mL | dialysis fluid |
| Peritoneal dialysis ultrafiltration | 0–4000 mL/day | PD fluid |
| Calories absorbed from PD fluid | 0–1000 kcal/day | PD energy |

On dialysis the weight means the **dry weight** (after a session). The stage means the **graft's
stage** after a transplant. Only the birth **month** is asked, not the date (data minimisation).

**Lab results** (the Labs view, `POST /api/labs`), stored in the analyte's canonical unit with what
was typed:

| Analyte | Stored in | Also accepted | Plausible (else refused) | Counts for |
|---|---|---|---|---|
| Potassium | mmol/L | mEq/L | 1.5–9.0 | 90 days (setting) |
| Phosphate | mg/dL | mmol/L (÷ 0.3229) | 0.5–20 | 90 days (setting) |
| Albumin (blood) | g/dL | g/L (× 0.1) | 0.5–6.5 | 180 days (setting) |
| Bicarbonate | mmol/L | mEq/L | 5–50 | 180 days (setting) |
| Urine albumin-to-creatinine ratio | mg/g | mg/mmol (÷ 0.113) | 0–50000 | 365 days |
| Creatinine (blood) | mg/dL | µmol/L (÷ 88.4) | 0.1–25 | 365 days |
| Cystatin C | mg/L | – | 0.2–10 | 365 days |
| eGFR reported by the lab | mL/min/1.73 m² | – | 1–200 | 365 days |
| HbA1c | % (NGSP) | mmol/mol (÷ 10.929 + 2.15) | 3–20 | 365 days (note only) |

Factors are KDIGO 2024's, re-derived from molar masses (note 05 §10.1). The app always shows the
conversion before saving ("1.94 mmol/L = 6.0 mg/dL"). A value outside the plausible range is refused
with a message naming the unit, because a wrong unit is the usual cause. Every threshold is judged on
the **shown** value (one decimal; eGFR a whole number), so a note never contradicts the number it
prints. The newest result of each test is used, and only while it is fresh; a date up to one day after
the server's date counts (time zones). Each person's default unit picker follows the setting
`user.units.labs` (`us` or `si`); any unit can still be entered.

## How each target is worked out

All rounding is decimal half-up. Calories are rounded to 10 kcal, protein bounds and fibre to whole
grams, fluid to 50 mL, the per-meal carbohydrate to 5 g.

**Mode.** Hemodialysis or peritoneal dialysis when set; otherwise "transplant" when a transplant date
is saved; otherwise CKD.

**Reference weight** (rules W-1 to W-4, KDOQI 2020 Table 5 formulas on a BMI-based weight; the choice
of weight is left to the care team by KDOQI 1.1.6, so this is the app's default **[opinion]**).
With a height, BMI = weight / height². Above BMI 25: the BMI-25 weight plus a quarter of the excess
(Karkeck). Below BMI 18.5: the weight moved a quarter of the way up to the BMI-18.5 weight (KDOQI
2000). In between, or without a height: the actual weight. It is sex-neutral, continuous at both
edges, and rounded to 0.1 kg. Example: 100 kg at 170 cm → 79.2 kg.

**Nutrition risk** (N-1; a risk flag, not a diagnosis): BMI below 20 (below 22 from age 70; GLIM 2019),
more than 5 % weight lost in 6 months (GLIM 2019), blood albumin below 3.8 g/dL (ISRNM 2008; assays
differ, the note says to ask), or frailty ticked (KDIGO 2024 PP 3.3.1.5).

**Energy.** With age and height: the NASEM 2023 estimated energy requirement (Table S-1, by sex, age,
height, the reference weight and activity; the mean of both equations for "unspecified"), turned into
kcal per kg and **kept inside 25–35 kcal/kg** (KDOQI 2020 3.1.1, 1C) (E-1). NASEM's adult equations are
for ages 19 and over; at 18 the app uses them too, and the 25–35 kcal/kg range bounds the result. Otherwise 30 kcal/kg
(E-2). With nutrition risk, at least 30 kcal/kg (E-3; ESPEN 2022 R1). On peritoneal dialysis the
calories absorbed from the dialysis fluid are subtracted, never below 20 kcal/kg (E-4).

**Protein** (g/kg × reference weight):

| Situation | g/kg | Rule and source |
|---|---|---|
| Dialysis | 1.0–1.2; **1.2–1.3** with nutrition risk | P-3 (KDOQI 2020 3.0.3/3.0.4; ADA 2026 Rec 11.3), P-6 |
| Transplant | 0.8–1.0 | P-7 (CARI 2010) |
| CKD stages 1–2 | 0.8–1.0 | P-1 (RDA; KDIGO 2024 PP 3.3.1.1: avoid > 1.3) |
| CKD stages 3a–5 **with diabetes** | **0.8** ("about X g/day"), never lower | P-2 (ADA 2026 Rec 11.3, A; KDIGO 2022 Rec 3.1.1; KDIGO 2024 Rec 3.3.1.1). KDOQI 2020 3.0.2's 0.6 needs close supervision, so the app never suggests it (fact-check H1; ARCHITECTURE v0.3 item 10) |
| CKD stages 3a–5 without diabetes | 0.6–0.8 | P-2 (KDOQI 2020 3.0.1, under close supervision; KDIGO 2024 Rec 3.3.1.1: 0.8) |
| Age 65+ or nutrition risk, not on dialysis | stages 1–2 (native or graft): 1.0–1.2; native 3a–5: 0.8–1.0; graft 3a–5: unchanged | P-5 (KDIGO 2024 PP 3.3.1.5; ADA 2026 Rec 13.11a; ESPEN 2022 R2; PROT-AGE) |

The general-public advice of 1.2–1.6 g/kg (Dietary Guidelines for Americans 2025–2030) must not be
applied to CKD (KDIGO 2024 PP 3.3.1.1: avoid more than 1.3 g/kg when CKD may progress).

**Carbohydrate and fibre.** Carbohydrate 45 % of calories ÷ 4 (the app's default, **[opinion]**; the
diabetes team sets the real number), per meal a quarter of that (at least 15 g). Fibre at least 14 g per
1000 kcal (ADA 2026 Rec 5.24).

**Sodium** 2000 mg for every adult (KDIGO 2024 Rec 3.3.2.1; KDOQI 2020 6.5.1).

**Potassium** (a review ceiling, never a prescription; every note ends "Only restrict potassium if
your blood potassium is high; your care team sets the number."). Default ladder: 4000 mg (stages 1–3a),
3500 (3b), 3000 (4), 2500 (5 and hemodialysis), 3500 (peritoneal); a transplant uses the graft stage.
With a fresh potassium result (rules K-0 to K-5; direction per KDOQI 2020 6.4.1–6.4.2 and KDIGO 2024 PP
3.11.5.2, numbers **[opinion]**):

| Blood potassium (mmol/L) | Suggestion |
|---|---|
| below 3.5 | no limit |
| 3.5–5.0 | one step higher (4000/4000/4000/4000/3500/3000; HD 3000; PD 4000); the default with "I have had high potassium" |
| 5.1–5.5 | the default, at most 3000 |
| 5.6–5.9 | at most 2500 |
| 6.0 and above | at most 2000, and a **safety alert**: 6.0–6.4 "contact your care team today; repeat within 24 hours; if unwell get urgent care now", 6.5 and above "get urgent medical care now" (KDIGO 2024 Table 28) |

**Phosphorus.** Default 1000 mg (900 at stage 5 without dialysis; KDOQI 2003 800–1000). After a
transplant at graft stage 1–3b, no limit (KDOQI 2020 6.3.3). With a fresh phosphate result: below
2.5 mg/dL no limit; 2.5–4.5 mg/dL 1000 mg (no limit after a transplant at graft stage 1–3b); above 4.5
mg/dL 800 mg (KDOQI 2020 6.3.1; KDIGO 2017 4.1.2, 4.1.8).

**Calcium.** At stages 1–2 (CKD or transplant) with a known age: the IOM 2011 recommended amount to the
upper limit (19–50: 1000–2500 mg; 51–70: women 1200, men 1000, to 2000; 71+: 1200–2000; age 18:
1300–3000; "unspecified" uses the higher amount). Otherwise at most 1000 mg in total including binders
(KDOQI 2020 6.2.1 at stages 3–4, 6.2.2 on dialysis).

**Fluid.** No limit without dialysis; from age 65 at stages 1–3b a reminder to drink at least 1.6 L
(women) or 2.0 L (men) unless the team limits fluid or there is heart failure or swelling (ESPEN 2022
R61; not at stages 4–5, fact-check M1). Hemodialysis: 1000 mL plus the 24-hour urine (1500 mL when the
urine volume is not entered). Peritoneal dialysis: urine plus ultrafiltration (2000 mL when either is
missing).

## What labs change, and what they never change

| Result | Effect |
|---|---|
| Potassium | the potassium ceiling (table above); 6.0+ also raises a safety alert, **always**, even with lab rules off |
| Phosphate | the phosphorus target |
| Albumin below 3.8 g/dL | nutrition risk (protein and calories to the higher end) and a note that low albumin has other causes |
| Bicarbonate below 22 mmol/L | a note: fruit and vegetables lower the acid load at stages 1–4 without dialysis (KDOQI 2020 6.1.1), the team may prescribe bicarbonate (6.1.2); below 18 a second note (KDIGO 2024 PP 3.10.1) |
| Urine albumin-to-creatinine ratio | a note with the A category in the unit it was entered in |
| HbA1c | a note that A1c and CGM do not change these targets (KDIGO 2022 PP 2.1.2) |
| Creatinine, cystatin C, eGFR | the kidney-function card only; **never** the saved stage |

Rules are applied in the order S → W → N → E → P → K → PH → NA → CA → F → C → FB → L and the notes come
out in the same order, ending with "These are starting points only — confirm every target with your
nephrologist and renal dietitian."

## When the app does not suggest targets

`GET /api/profile/suggested-targets` answers **422** with `{"detail": "<message>", "code": "<code>"}` and
no numbers. Targets can still be entered by hand.

| Code | When | Why |
|---|---|---|
| `out_of_scope_pregnancy` | pregnant or breastfeeding | energy, protein, calcium and fluid needs change; specialist care (KDIGO 2024 scope; NASEM 2023) |
| `out_of_scope_under_18` | under 18, counting from the **last** day of the birth month (so nobody who might still be 17 gets adult targets) | children need more protein and energy; different guidelines (KDIGO 2024 PP 3.3.1.4, 3.3.2.2, 1.2.4.3) |
| `out_of_scope_early_transplant` | fewer than 84 days (12 weeks, **[opinion]**) since the transplant | the transplant team sets a recovery diet (CARI 2010; KDOQI "metabolically stable") |

## Kidney function card

`GET /api/labs/kidney-function` shows the eGFR and albuminuria category from the person's results of the
last 365 days. The newest date decides; on that date a **lab-reported eGFR** wins (the lab knows its
region's equation, KDIGO 2024 PP 1.2.4.1), then creatinine with cystatin C taken that day (CKD-EPI 2021
creatinine–cystatin C), then creatinine (CKD-EPI 2021 creatinine), then cystatin C (CKD-EPI 2012). The
equations are race-free (KDIGO 2024 PP 1.2.4.2), need an age of 18 or more and a sex, and assume
standardised assays. With sex "unspecified" both formulas are shown and a stage is suggested only when
they agree. After a transplant the category carries a "T" (G3aT). No estimate is made on dialysis,
during pregnancy or breastfeeding (the equations were not developed for pregnancy, **[opinion]**), or
under 18. The card always says that one result does not change a stage (stages need results over 3
months, KDIGO 2024 PP 1.1.3.2) and **never changes the saved stage**.

Albuminuria (KDIGO 2024 Table 3) uses the unit it was entered in: A1 below 30 mg/g (3 mg/mmol), A2 up to
300 mg/g (30 mg/mmol), A3 above. Converting first would put 3.0 mg/mmol (26.5 mg/g) in A1 instead of A2.

## In the app

**Profile** (`js/views/profile.js`) has four cards:

* **About you**: name, birth month (a month picker), height, weight (labelled *Dry weight (kg, after
  dialysis)* on dialysis), weight 6 months ago, *Sex used in medical formulas* with the help text above,
  *Activity on a usual day* (five radio choices: not chosen, then the four NASEM 2023 Table 7-1 levels
  described in plain words) and three yes/no boxes (frailty or low muscle mass, pregnant or
  breastfeeding, high potassium before or a potassium binder).
* **Kidneys and diabetes**: stage (labelled *Transplant kidney stage* when a transplant date is set),
  dialysis, diabetes, and only the fields that apply: the transplant date without dialysis; dialysis
  days and urine volume on hemodialysis; urine volume, ultrafiltration and calories from dialysis fluid
  on peritoneal dialysis.
* **Blood and urine tests**: the newest result of each test, the kidney-function line, and *Lab results*
  (opens the Labs view).
* **Daily targets**: the editor (protein and calcium as minimum–maximum; the same number in both boxes
  reads "about X"; fiber as "at least", a goal that is never "over"), *Warn at* and *Week starts on*.

**Suggest targets** works from the *saved* profile: when the form differs from it the app asks the
person to save first. The answer fills the editor (not saved) and shows, in order: a very-high-potassium
alert if there is one; what would change compared with the saved targets, each with the first sentence
of the deciding rule's note as the reason; how the numbers were worked out (weight basis, nutrition
risk, age, sex, BMI, kcal/kg, activity and the lab results used); every target with a **Why this
number?** disclosure listing each rule applied — its note, rule id, grade, an **Expert opinion** badge
with what the opinion is, and a link to the source; the lab notes; buttons for the inputs that would make
it more personal (`missing_inputs`); the "starting points only" reminder; handbook links. A refusal
(pregnancy, under 18, first 12 weeks after a transplant) shows its message instead of numbers, and the
saved targets stay. The refusals depend only on the saved profile, so the page recognises them with the
browser copy of the rules before asking the server (which refuses on its own as well).

**Lab results** (`#labs`, `js/views/labs.js`; no tab, opened from Profile): pick the test, type the
result (a decimal comma is accepted), pick the unit (the first offered follows `user.units.labs`, set in
Settings → Preferences) and the date. The converted value is shown while typing ("Will be saved as
1.94 mmol/L = 6.0 mg/dL."), and a value outside the plausible range is explained before anything is
sent. After saving, *What this result changed* compares the suggested targets before and after the result
(for example "Phosphorus: 1,000 mg/day → 800 mg/day") and offers **Review suggested targets**, which runs
the suggestion in Profile; Profile also shows a dismissible *Review suggested targets* notice listing every
change since the last reviewed suggestion. Nothing is ever applied to the saved targets from here. A
potassium of 6.0 mmol/L or more shows a red banner with the KDIGO 2024 Table 28 text (urgent; emergency
from 6.5) right after saving and, on the Labs view and Profile, while it is the newest potassium result
and still counts under `targets.lab_fresh_days.potassium` (90 days unless an admin changed it). The server
decides (`GET /api/labs` returns it as `alerts`), with the same window as *Suggest targets*, so the banner
and the suggestion never disagree. The *Kidney function* card shows the eGFR with its stage (or both formulas when sex is
not set), the albuminuria category, and the server's message. *History* lists every result by test,
newest first, with a filter and deletion (confirmed in the page).

**Today** draws the fiber goal as progress toward "at least X g" (no "over" state) and a protein range
whose minimum equals its maximum as "about X g".

**Demo and preview**: `js/mock/profile.js` and `js/mock/labs.js` answer every route above with the
browser copies of the rules (`js/engine/targets.js`, `js/engine/kidney_function.js`), and the sample
person has a birth month, an activity level and a few months of results (some typed in SI units).

## Settings

| Key | Who sets it | Default | Effect |
|---|---|---|---|
| `targets.lab_rules_enabled` | admin | on | Off: potassium and phosphorus use the defaults, lab notes and albumin-driven risk are left out; the potassium safety alert stays |
| `targets.lab_fresh_days.potassium` / `.phosphate` / `.albumin` / `.bicarbonate` | admin | 90 / 90 / 180 / 180 days (1–365) | how long a result counts |
| `targets.default_activity` | admin | inactive | activity used until a person chooses theirs |
| `user.units.labs` | each person (admin sets the default) | us | the unit offered first in the Labs view |

The note's table lists `user.units.labs` as a personal key; it is registered as `user_default` so the
admin of a server outside the US can make SI the default while each person can still change it.

## Privacy

Birth month, sex, pregnancy and lab results are health data. They are stored only in the server's
database, are never written to the log, appear in the person's own export (`export.json` and
`labs.csv`, with values in the canonical unit plus what was typed), and are deleted with the account.
No admin route reads them.

## For maintainers

* To change a number or a text: edit `app/target_rules.py` (with its source), run
  `python3 tests/data/gen_targets_vectors.py` and `python3 tests/data/gen_kidney_function_vectors.py`,
  update the browser twins `app/static/js/engine/targets.js` and `kidney_function.js` until
  `node tests/js/run_vectors.mjs` passes, then update this page, the handbook and, when the change is
  clinical, note 05.
* `tests/data/personal_target_vectors.json` is note 05 §5.1 verbatim (hand-checked); never regenerate it.
* Tests: `tests/test_targets.py` (spec vectors, properties, every threshold), `tests/test_units.py`,
  `tests/test_kidney_function.py`, `tests/test_targets_api.py` (API, settings, two people, export,
  deletion), `tests/test_targets_vectors.py` (parity files current), `tests/test_migration_m004.py`.
* Frontend: `js/views/profile.js`, `js/views/labs.js` (also `KH.labs`, the helpers Profile uses),
  `css/labs.css`; demo routes in `js/mock/profile.js` and `js/mock/labs.js`. `tests/test_targets_ui.py`
  keeps the forms wired to the server's fields and enums; `python tools/e2e/parity.py --sections 11`
  compares the demo with a real server (profile fields, labs, ~150 suggestions); `tools/e2e/regress.py`
  and `tools/e2e/sandbox.py` walk the screens.
* Schema: step 4 (`app/migrations/m004_targets_labs.py`) adds the profile columns to `user_profiles`
  and the `lab_results` table (`ON DELETE CASCADE` with the account). `activity` is nullable so "not
  chosen" can fall back to `targets.default_activity` and be listed in `missing_inputs`.

## Open clinical review

Before these rules lose their "draft" status a renal dietitian or nephrologist should review (note 05
C10): every rule marked opinion in `app/target_rules.py`; the K-5 alert wording; the 0.6 g/kg lower
bound without diabetes (P-2n, fact-check M6); the one-step potassium relaxation on hemodialysis (2500
→ 3000 mg, fact-check L15). The sources to re-check when they change are listed in note 05 §8 (KDIGO
2026 diabetes guideline, ADA Standards 2027, GLIM and ISRNM primary tables before release). Both items
are tracked in [docs/ROADMAP.md](ROADMAP.md).
