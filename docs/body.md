# Weight and blood pressure

This page is for the people who run and change the app. It explains the **log of weights and blood pressure readings** (schema step
18): what is stored, the routes, the settings, what the app works out from the numbers, the handbook's words it points to, how the data
leaves (export) and comes in (import), what it never does, and how the browser twin and the checks work. The normative specification is
[design note 10](dev/research/10-weight-and-blood-pressure.md); the contract is [ARCHITECTURE.md](../ARCHITECTURE.md), "Weight and blood
pressure". The code is `app/body.py`, the models in `app/models.py` and `app/migrations/m018_body_measurements.py`.

> **Built in three parts (note 10 §7).** Part A, described here, is the server, the demo's twin, the settings, the export and import and the
> handbook's two lines for a very high reading: **it has no screens yet**. Part B adds the Today card and its sheets, the Trends charts, the
> Settings section, the Profile helpers, the visit prep section and the handbook's "Using the app" page; Part C an import from the iPhone
> Health app's `export.xml`. Until Part B ships, the log is reachable through the API (and the demo's twin of it) and appears in the export.

## What the app does and does not do

A person records a weight (in kilograms; the unit they type and see, pounds by default, is a setting) and a blood pressure reading (top
number, bottom number, optional pulse), each with a date, an optional time and when it was taken (morning, before or after dialysis,
other). The app **records and shows**, works out a few plain numbers, and points to the handbook when a number is past a limit.

* **It never suggests a weight-gain alarm, a blood pressure goal or a dry weight.** Those are the care team's. The person enters the two
  numbers their team gave them in Settings (`body.weight_alarm`, `body.bp_goal`); with none set, readings are shown without a verdict.
  KDIGO's top-number target of 120 is for blood pressure measured the standard way at the clinic, and home readings only complement it
  (note 10 F3), so there is no home goal of the app's own.
* **It says nothing about a cause, a treatment or a medicine.** The warning-sign lines are the handbook's own words with a link; there
  is no advice on taking, skipping or changing a medicine, and nothing about insulin or glucose (CLAUDE.md).
* **It never changes the Profile weight.** That weight moves the protein and calorie targets and, on dialysis, is the dry weight the unit
  sets; a scale reading is not that. (Part B offers to fill a field only when the person taps "Use this".)

## What is stored

Two tables, because the readings validate differently (`weights`, `blood_pressures`; both `ON DELETE CASCADE` from `users`, one unique
index each on `(user_id, source_key)` where the key is not null, so a second import adds nothing). There is **no `CHECK` on a context or
a source** (a later value must not need a table rebuild); a row with a value this version does not know is kept, left out of the lists and
included in the export. `source` is `manual` (typed), `apple_health` or `import`; editing an imported row makes it `manual` and keeps its key, so
importing again does not bring the old value back. Ids are never reused (`AUTOINCREMENT`).

The ranges (a weight of 20 to 400 kg, a top number of 50 to 300, a bottom number of 20 to 200 and below the top number, a pulse of 20 to
250) and the limits (20 weights and 30 readings a day, a note of 200 characters, 1,000 rows in a batch) are **the project's own plausibility
choices**: they keep a typing error out of the log and are not clinical numbers. Everything else a number means traces to a cited source
(note 10 §3, F1 to F7; the new handbook source is `NHLBI-BPS`).

## Routes

All under `/api/body`, every one needs a signed-in person, reads and writes only that person's rows (not yours is a 404) and needs the app
header on writes. The full table is in ARCHITECTURE.md; in short: `GET`/`POST`/`PUT`/`DELETE` on `/weights` and on `/blood-pressure`
(a list needs `start` and `end`, at most 366 days), `POST …/batch` on each (up to 1,000 rows from an import, each with a `source_key`;
**all or nothing**, the first invalid row refuses the request and is named; rows already there are skipped and counted;
60 requests an hour per person), and `GET /summary?date=` (what Today shows).

## What the app works out

* **Units**: `kg = lb × 0.45359237` (exactly), stored to 0.01 kg, shown to one decimal rounded **half up** (154.25 lb shows 154.3).
* **Weight gain against the alarm** (only with an alarm number): *in n days* compares the latest weight with the latest weight of the
  **same kind** (morning with morning) from n to 2n days earlier; *between sessions* (hemodialysis) compares it with the last weight after a
  session in the 7 days before, or the dry weight in Profile (only on hemodialysis), or says to add a weight after a session. It is over
  the alarm only when the gain is **more than** the number. The answer names the two weights compared.
* **Blood pressure week**: the mean top and bottom number of the readings in the last 7 days (the day and the 6 before), each rounded half
  up, and whether a mean is **at or above** the goal number ("under 130/80": 130 is not under). With fewer than 3 readings the means are
  shown and nothing is said against the goal.
* **Six-month change**: the latest weight against the weight closest to 182 days before it (within 30 days): kg and percent. Visit prep
  (Part B) shows it; the GLIM weight-loss rule reads it only if the person copies it into Profile.

## The handbook's words

| When | The app shows | From the handbook page |
|---|---|---|
| a weight is over the person's alarm | "The handbook lists “weight gain above the alarm number your team gave you” under “Call your care team today”." (not prominent: the person set the number) | Get help now → Call your care team today → Fluid |
| a reading has a top number of 180 or more, or a bottom number of 120 or more | both lines of the page quoted, the 911 one first: under Call 911 now (with a sudden severe headache, trouble breathing, chest, belly or back pain, numbness or weakness, a sudden change in vision or trouble talking; no second reading needed), then, without those signs, rest 5 minutes and measure again, under Call your care team today (still that high after resting 5 minutes). Prominent. | Get help now → the new "Blood pressure" group and the bullet after the stroke signs |

The lines come from NHLBI, "High Blood Pressure – Symptoms" (last updated 2024-04-25), and the 911 line also from MedlinePlus, "Measuring Blood Pressure" (last updated 2024-08-26), which sends a reading over 180/120 with those signs to 911 without a second reading. The page also says the provider "may recommend starting
a medicine or changing your dose"; the handbook leaves that out on purpose. Reading "180/120" as *either* number is the project's cautious choice
(NHLBI does not say) and is an open question in `handbook/REVIEW.md` ("Emergency tiers and red flags", S8) for the clinician review.
`tests/test_body.py` reads the page and fails when a quoted phrase is no longer under its heading, so the app never quotes words the page no
longer has. Changing these lines needs the same clinical review as the page itself.

## Settings

| Key | Scope | Values | Default |
|---|---|---|---|
| `user.units.weight` | `user_default` | `kg`, `lb` | `lb` (the app's US defaults) |
| `body.weight_alarm` | `user` | `{amount_kg: 0.2 to 10 or null, over: "between_sessions" or "days", days: 1 to 7}` | `{null, "days", 1}` (no alarm) |
| `body.bp_goal` | `user` | `{systolic: 80 to 200 or null, diastolic: 40 to 130 or null}`, top above bottom | both null (no goal) |

They are in the export's `settings`, carried over by an import with "Also replace my profile, targets and settings", and mirrored in the
browser by `js/engine/settings.js` (checked by `tests/data/settings_vectors.json`). The unit's default for everyone is in Server administration → Server
settings → Default for everyone.

## Export, import, deletion and privacy

* `export.json` gains `weights` and `blood_pressures` (oldest first, `source_key` kept); the archive gains `weights.csv` and `blood_pressure.csv`
  (formula-escaped) with lines in `README.txt`. The export version stays 1: a file written before this has neither list and still imports.
* The import checks every row like the API, never uses the id in the file, treats an account that has weights or readings as having data
  (409 without "Add to my existing data"), then leaves out a row that came from an import and has a key the person already has, or one they typed
  that is identical to one already there, and skips (and lists) a 21st weight or 31st reading of a day. There is no "replace my data" mode.
* Deleted with the account. **Never logged** (not in the server log, not in the activity list). **Never sent to an AI provider, the Ask chat or an
  assistant**: the code that builds those requests does not read the tables, and a test greps for it. See [Privacy](privacy.md).
* The log needs the connection in this version: no offline queue (like symptoms).

## Import from the iPhone Health app

Part C. A person on an iPhone can bring past weights and blood pressure readings in from the Health app's export. It is **browser only**: no route,
setting or schema step of its own, and no new network host. The steps for a person are in the handbook ("Using the app", *Weights and blood
pressure from the Health app*); this is how it works. The contract is ARCHITECTURE.md, "Weight and blood pressure → Import from the iPhone Health
app"; the specification is note 10 §4.8.

* **Opening it.** `KH.bodyImport.open()` (`js/views/body_import.js`) opens the sheet `#sheet-body-import`. The buttons that call it are in Trends
  (Weight and blood pressure → Import from Apple Health) and Settings → Your data (Part B); the sheet itself has no button of its own.
* **Reading.** The person picks `apple_health_export/export.xml` (after unzipping `export.zip` in the Files app). The reader `KH.appleHealth.scan`
  (`js/engine/apple_health.js`; its header comment is its full specification) streams the file as text, finds the `<Record ` start tags of the
  three types it keeps and reads their attributes by hand. **There is no XML parser**: the file can be hundreds of megabytes and starts with an
  internal DTD, so nothing is parsed or expanded. It keeps weights in kg or lb and blood pressure (a systolic and a diastolic record with the same
  `startDate` and `sourceName`, in mmHg); **nothing else in the file is read** (no heart rate, steps, glucose or insulin). The sheet shows a progress line
  and a Cancel that aborts the scan. Nothing is sent while the file is read or reviewed.
* **Review.** What was found and kept, what was left out and why (in words), the dates in the file, the sources, a period (**the last 3 months by
  default**, or everything) with the counts of each, and, listed apart and **unticked**, readings from a source with "Watch" in its name: note 10 F4
  says cuffless devices (watches, rings) are not recommended for checking blood pressure, so the person has to choose them. (Only readings are held
  back that way; a weight from a source named "… Watch" is imported like any other.) Source names come from the file and are drawn as text only.
* **Sending.** Import sends the rows of the period in batches of 1,000, weights first, **without the source name** and with `source: "apple_health"`
  (what `WeightBatchRow` and `BloodPressureBatchRow` accept besides `import`), each with its `source_key`, so importing the same file again adds nothing
  ("c were already here"). The result reads "Added a weights and b readings; c were already here", and Today and Trends are loaded again.
* **A day with more than the app keeps.** One person holds at most 20 weights and 30 readings a day, and a batch with a row that would overfill a day is
  refused **whole**. So the sheet keeps the **first rows of such a day in time order**, as many as the day can still take (the limits minus what the
  person already has that day, read through the list routes for the days of the file), and says "n more on m days were left out (the app keeps at most
  20 weights and 30 readings a day)". Rows a former import of the same file stored count as "already here" and take no room; one the person edited since
  counts as typed by hand. If the rows already there cannot be read, only the limit is used.
* **If the server refuses anyway** (another device added rows meanwhile, the hourly limit of 60 batch requests, a version difference, a gateway error),
  the import **stops**: the sheet shows the server's own words (with the day of the row it names) and how many weights and readings were already added,
  and pressing Import again carries on without repeating them. Nothing is dropped silently. Closing the sheet during an import stops it after the request
  in flight and says so in a message.
* **Checks.** `tests/test_body_import_ui.py` (with `tests/js/body_import_page.mjs`, which runs the view against a fake backend that keeps the server's batch
  rules), the reader's `tests/test_apple_health.py` and vectors, and the browser harness `python tools/e2e/body_import.py` (a real server and the demo; a
  generated `export.xml`; the server's rows read back through the API). The sample records are hand-written: before calling the import done, try a real
  export from an iPhone ([maintainers](maintainers.md), release checklist).

## The demo and the checks

The Pages demo runs `js/mock/body.js` over `js/engine/body.js` in the page: the same routes, the same errors in the same order, the same `flag`,
`summary` and batch answers; its sample data is two weeks of weights and readings with a sample alarm and goal, today's weight over the
alarm and **no reading at 180/120** (so the demo never shows the emergency block unasked). The demo has no rate limit on the batch routes.
The import sheet works against it too (`tools/e2e/body_import.py` runs it in the demo as well).

Checks, all without a network: `python -m pytest` (`tests/test_body.py`, `test_body_vectors.py`, `test_migration_m018.py`, and the
isolation, auth coverage, export and import tests), `node tests/js/run_vectors.mjs` (`tests/data/body_vectors.json`, generated from the
server by `tests/data/gen_body_vectors.py`; regenerate it with `python tests/data/gen_body_vectors.py` after a change to `app/body.py` or
the body models, then make the browser twin agree), and the browser harness `python tools/e2e/parity.py` (section 16 runs the same
request script on the live server and the demo).
