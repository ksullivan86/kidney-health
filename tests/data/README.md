<!-- tests/test_vectors_readme.py reads this file. Keep one "## <name>_vectors.json" heading per vector file, and under it a line
"Top-level keys:" followed by a tight list that starts each item with the key in backticks. -->

# Test vectors

The `*_vectors.json` files in this folder pair inputs with the answers the server gives. Each one was made by running the server's own
code on a set of inputs and writing down what came out. They are plain JSON, so any language can read them.

They exist for two reasons.

* The demo and the preview run in a browser with JavaScript copies of some server logic. We call them twins. A twin must give the same
  answer as the server, and the vectors are how that is checked.
* Another client can check its own copy of the same rules the same way, without reading the Python. The planned iOS app is the first.

Two commands check the vectors. Both run without a network.

```bash
python -m pytest                  # each generated file is what the server gives now
node tests/js/run_vectors.mjs     # the browser twins give the answers in the files; exits 0 when every vector matches
```

## When server logic changes

1. Change the server and its twin.
2. Regenerate the file with the command in the table below, and read the diff. It should show only what you meant to change.
3. Run both commands above. Fix the twin until they pass.

Never edit a generated file by hand. If a replay fails, fix the twin or the server, not the vectors or the runner.
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-parity-rule-demo-mode) has the same rule from the contributor's side.

Run the commands from the repository root.

| File | Command |
|---|---|
| `apple_health_vectors.json` | `node tests/js/gen_apple_health_vectors.mjs` |
| `barcode_vectors.json` | `python3 tests/data/gen_barcode_vectors.py` |
| `body_vectors.json` | `python3 tests/data/gen_body_vectors.py` |
| `ccda_labs_vectors.json` | `node tests/js/gen_ccda_labs_vectors.mjs` |
| `entry_version_vectors.json` | `python3 tests/data/gen_entry_version_vectors.py` |
| `fhir_labs_vectors.json` | `node tests/js/gen_fhir_labs_vectors.mjs` |
| `guidance_vectors.json` | `python3 tests/data/gen_guidance_vectors.py` |
| `import_vectors.json` | `python3 tests/data/gen_import_vectors.py` |
| `kidney_function_vectors.json` | `python3 tests/data/gen_kidney_function_vectors.py` |
| `lab_import_vectors.json` | `node tests/js/gen_lab_import_vectors.mjs` |
| `menu_link_vectors.json` | none: written by hand |
| `meta_vectors.json` | `python3 tests/data/gen_meta_vectors.py` |
| `personal_target_vectors.json` | none: copied from a design note |
| `rules_vectors.json` | `python3 tests/data/gen_rules_vectors.py` |
| `settings_vectors.json` | `python3 tests/data/gen_settings_vectors.py` |
| `symptoms_vectors.json` | `python3 tests/data/gen_symptoms_vectors.py` |
| `targets_vectors.json` | `python3 tests/data/gen_targets_vectors.py` |

What to know about the commands:

* Every generator writes the file in place. The Python ones and `tests/js/gen_apple_health_vectors.mjs` also take `--check`, which
  writes nothing and exits 1 when the file is out of date. That is what pytest runs.
* `tests/js/gen_ccda_labs_vectors.mjs`, `tests/js/gen_fhir_labs_vectors.mjs` and `tests/js/gen_lab_import_vectors.mjs` have no `--check`.
  The files hold hand-written expectations, so read `git diff` after running them.
* The generators for body, entry version, import, meta and symptoms start the app on a temporary database. They need the app's
  dependencies and no network.
* `personal_target_vectors.json` is not regenerated. Change `docs/dev/research/05-personalized-targets.md` first.

## How the shapes are written

In the sections below, a shape such as `{name: string, expected: object}` lists the fields of one case. `field?` is a field that
is not in every case, `a | b` means one of the two, `[x]` is a list of `x`, and `null` is JSON null. Most files have an `about` key. It is free text
saying where the file comes from, and no replay reads it.

## apple_health_vectors.json

Weights and blood pressure readings read from the Health app's `export.xml`, the file the iPhone makes under "Export All Health Data".

* Server: none for the file itself, because it is read on the device and the server only sees the rows the person keeps. The row rules (ranges,
  contexts, the watch rule) are the server's in `app/body.py`. The phone-shortcut route builds the same key texts in `app/push.py`, and
  `tests/test_push.py` checks them against these vectors.
* Browser twin: `app/static/js/engine/apple_health.js`.
* Made by `tests/js/gen_apple_health_vectors.mjs`, from hand-written `export.xml` pieces and hand-written answers. The script stops if the
  reader disagrees. Only each `source_key` is computed, from the hand-written `key_input` text.

Top-level keys:

* `about`: where the file comes from.
* `limits`: constants the reader must hold. The longest start tag it reads, the upload batch size, the pounds-to-kilograms factor, the plausible ranges and the three HealthKit type names.
* `chunk_sizes`: the sizes the text of each case is cut into, and `"whole"` for no cut.
* `cases`: the main cases, below.
* `default_since`: `{today: string, since: string}`, the start of the default review period for a given day.
* `default_since_errors`: values for `today` that must be refused.
* `filter_since`: `{name: string, since: string | null, expected: [string]}`, which days of a fixed list a start date keeps.
* `filter_since_errors`: start dates that must be refused.
* `batches`: `{count: int, size: int, sizes: [int]}`, how a list of `count` rows is split into upload batches.
* `batch_errors`: batch sizes that must be refused.
* `watch`: `[sourceName, bool]` pairs, whether a source name counts as a watch.
* `upload`: `{row, expected}`, a row before and after the source name is removed for the upload.
* `sha256`: `{name: string, text?: string, repeat?: {text, count}, digest: string}`, SHA-256 examples. A digest of 32 characters is the first 32 of the SHA-256, as in a `source_key`.

A case: `{name: string, xml: string | [string | {repeat: {text: string, count: int}}], chunks?: [string], options?: {today: string}, expected: {weights: [row], readings: [row], summary: object}}`.
A `repeat` piece stands for `text` written `count` times, so a long file need not be stored. A weight row is
`{date, time, kg, context, key_input, sourceName, source_key}`. A reading row has `systolic` and `diastolic` in place of `kg`.
`summary` is `{found, kept, skipped: {unknownUnit, halfPair, outOfRange, badEntity, tagTooLong, duplicate, unreadable}, firstDate, lastDate, sourceNames}`.

What a replayer must get right:

* The reader takes decoded text and must give the same rows wherever the text is cut. Replay each case at every size in `chunk_sizes`, and at the case's own `chunks` when it has them.
* `date` and `time` are the `startDate` as written. `2026-10-19 07:15:00 -0400` gives `2026-10-19` and `07:15`. Nothing is converted to UTC.
* `source_key` is the first 32 hex characters of the SHA-256 of the UTF-8 text `key_input`. For a weight that text is
  `type|startDate|value|sourceName`, with the value as written (pounds stay pounds). For a reading it is `BloodPressure|startDate|systolic/diastolic|sourceName`.
  The web import and a native client must build the same text, so that importing the same reading twice adds nothing.
* `kg` is the value in kilograms, or pounds times `kg_per_lb`, rounded half up to 0.01 (see "Rounding" below). A reading is two records
  with the same `startDate` and source. Half a pair is skipped and counted.
* `context` comes from the time of day. The edges are in `context_cases` of `body_vectors.json`, which the runner also replays against this reader.
* Rows come out sorted by date, time and source. Types other than weight and blood pressure are ignored without being read.
* `summary.skipped` counts what was left out and why. Those counts are part of the answer.
* A HealthKit client has no XML, so the chunk and entity cases do not apply to it. The row, key, rounding, range, pairing, context and watch cases do.

## barcode_vectors.json

Barcode numbers, the cleaning of text from outside, the scan for phosphate and potassium additives, and the barcode lookup the demo answers.

* Server: `app/gtin.py`, `app/textclean.py`, `app/additives.py`, `app/off.py` and the route in `app/barcode.py`.
* Browser twin: `app/static/js/engine/gtin.js`, `app/static/js/engine/textclean.js`, `app/static/js/engine/additives.js`,
  `app/static/js/engine/off.js` and the demo route `app/static/js/mock/barcode.js`.
* Made by `tests/data/gen_barcode_vectors.py`. It is seeded, has no clock, and runs on recorded Open Food Facts and USDA answers, so it needs no network.

Top-level keys:

* `about`: where the file comes from.
* `check_digit_cases`: `{body: string, digit: int}`.
* `gtin_cases`: `{code: string, format: string, normalize?: string, classify?: string, off_code?: string, usda_candidates?: [string], error?: {reason: string, message: string}}`.
  A case has either the four answers or an `error`. `format` is one of `unknown`, `upc_a`, `upc_e`, `ean_8` and `ean_13`.
* `textclean_cases`: `{value: string, max_len: int, keep_newlines: bool, result: string | null}`.
* `additive_cases`: `{tags: [string] | null, text: string | int | null, name: string | float | null, result: {flags, findings, kidney_notes, additives, notes}}`.
* `quality_cases`: `{codes: [string], items: [{code: string, message: string}]}`, Open Food Facts data-quality tags and the notes they give.
* `demo_products`: `{fixture: string, code: string, format: string, row: object, result: object}`. `row` is the stored product. `result` is the server's whole answer to `POST /api/foods/barcode`, with the food id removed.

What a replayer must get right:

* `max_len` counts Unicode code points. It is not UTF-16 units and not what a person sees as one character.
* Some `textclean_cases` values hold lone UTF-16 surrogates, written `\ud800` in the JSON. Python and JavaScript strings can hold them. A Swift `String` cannot, so a JSON decoder there
  will fail or replace them. Decide how your client reads these before you trust the cases.
* The text is cleaned before the additive scan: NFKC, invisible characters removed, spaces folded. This is a safety step. A zero-width
  character inside "phosphate" must not hide an additive, so a client must not skip the cleaning or run the scan on raw text.
* The scan compares case-folded text the way Python's `casefold` does. `ß` and the Greek final sigma are in the cases.
* `additive_cases` also pass `null` and values that are not text. The expected answer is still a full `result`.
* `flags`, `kidney_notes` and `notes` in a `result` are shown to people word for word.
* A `gtin_cases` answer is compared as a whole: the 14-digit form, the class, the Open Food Facts code and the USDA candidates in their order.

## body_vectors.json

Weight and blood pressure: units, the weight-gain alarm, 7-day averages against a goal, the six-month change, red-flag readings, the API shape of a row, and every body route.

* Server: `app/body.py` and the weight and blood pressure models in `app/models.py`.
* Browser twin: `app/static/js/engine/body.js` and the demo routes `app/static/js/mock/body.js`.
* Made by `tests/data/gen_body_vectors.py`.

Top-level keys:

* `constants`: the tables a twin must hold. `kg_per_lb`, `weight_contexts`, `blood_pressure_contexts`, `sources`, `units`, `limits` (every range and maximum), `flag_systolic`, `flag_diastolic`, `href`, `link_text` and `red_flags`.
* `unit_cases`: `[{name: string, cases: [object]}]`, three groups: pounds to stored kilograms and back, kilograms rounded to two decimals, and the number and text shown for a stored weight.
* `alarm_cases`: `{name, weights, alarm: {amount_kg, over, days}, dry_weight_kg: number | null, unit: string, expected: object | null}`. `over` is `days` or `between_sessions`.
* `week_cases`: `{name, readings, day, goal, expected}`, the 7-day averages against the person's goal.
* `six_month_cases`: `{name, weights, expected: object | null}`.
* `flag_cases`: `{systolic: int, diastolic: int, flag: object | null}`.
* `row_cases`: `{kind: "weight" | "reading", row: object, api: object}`, a stored row and the shape the API gives it.
* `summary_cases`: `{name, weights, readings, day, units, alarm, goal, dry_weight_kg, expected}`, the answer of `GET /api/body/summary`.
* `context_cases`: `{kind: string, time: string | null, minutes: int | null, context: string}`, the context a clock time gets.
* `watch_cases`: `{name: string | null, watch: bool}`, whether a source name counts as a watch.
* `script`: one request script (see "Request scripts" below). A step with `quiet: true` is set-up: compare only whether it worked.

What a replayer must get right:

* Kilograms are stored rounded half up to 0.01. A weight shown in either unit is rounded half up to one decimal. Pounds are converted with the exact `kg_per_lb`, and the result is then rounded.
* The alarm and the goal are numbers the person's care team gave them. The app never suggests either. With none set, the summary has no verdict.
* A flagged reading and a weight over the alarm carry handbook text and a link to Get help now (`red_flags`, `flag`). Show that text and keep the `prominent` setting. Do not shorten or soften it.
* `context_cases` and `watch_cases` are also replayed against the Apple Health reader, so a reading gets the same context by every way in. `minutes: null` is a reading with no time, and the server gives it the context `other`. The Apple Health reader always has a time, so the runner skips those cases for it.

## ccda_labs_vectors.json

Lab results read from a C-CDA health summary, the XML file a patient portal gives.

* Server: none, because the XML never reaches the server. `tests/test_ccda_labs.py` checks every converted value against `app/units.py` and that every importable row is accepted by `POST /api/labs/import`.
* Browser twin: `app/static/js/engine/ccda_labs.js`. It reuses the test table, units and date rule of `app/static/js/engine/fhir_labs.js`.
* Made by `tests/js/gen_ccda_labs_vectors.mjs`, from hand-written documents and hand-written answers. The script stops if the reader disagrees.

Top-level keys:

* `about`: where the file comes from.
* `limits`: `max_files`, `max_file_bytes`, `max_elements`, `max_depth`, `max_records`, `max_collect`, `max_results` and `max_problems`.
* `oids`: the identifiers of the C-CDA templates the reader looks for.
* `cases`: `{name: string, files: files, options: {tzOffsetMinutes: int, today?: string, existing?: [{analyte, taken_on, value}]}, expected: {problem, counts, results, problems, summary}}`. `existing` lists results the person already has, which are marked and not counted again.

`files` is a list of `{name: string, text: string}`. An item may instead be `{name, repeat: {prefix, item, separator, count, suffix, dates_from?}}`, a recipe for a long text:
`prefix`, then `item` written `count` times with `separator` between, then `suffix`. A `{date}` in `item` becomes the nth day counting from `dates_from`. For a pick of many files,
`files` is one object instead, `{repeat_file: {name, text, count, dates_from?}}`. It stands for `count` files, where `{n}` in `name` becomes the index and `{date}` in `text` the nth day.

What a replayer must get right:

* The runner parses the XML with `tests/js/mini_xml.mjs`, which stands in for the browser's `DOMParser`. Another client needs its own parser. A file with a DOCTYPE or an entity declaration is refused before it is parsed.
* The reader never reads a clock. `today` is given, and a date more than a day after it is refused (a day of slack for time zones).
* A date with a time and a zone becomes the day in the device's own zone, so the cases pass `tzOffsetMinutes` (minutes east of UTC) to make the answer the same on every machine. A date with no time is used as written.
* Result rows come out newest first, with `value`, `unit`, `text` and `display`. `problems` and `summary` are sentences shown to people.

## entry_version_vectors.json

The version of a logged entry, the `If-Match` rule, and the `PUT` and `DELETE` routes that use them to stop one device overwriting another's edit.

* Server: `app/log.py` (`entry_version`, `version_matches` and the routes of `/api/log/{id}`).
* Browser twin: the demo route `app/static/js/mock/log.js`.
* Made by `tests/data/gen_entry_version_vectors.py`.

Top-level keys:

* `fields`: the entry fields the version is made of, in order. The 12 nutrient values follow them in registry order.
* `cases`: `{name: string, entry: object, version: string}`.
* `match_cases`: `{name: string, header: string | null, version: string, expected: bool}`, whether an `If-Match` header allows a change.
* `script`: one request script. A step may have `if_match`, the `If-Match` header to send.

What a replayer must get right:

* `version` is 16 hex digits: FNV-1a (64 bit) over a canonical text. A missing value is `~`. A number is `n<number>;`, written without a point when it is whole, so `1` and `1.0` give one version.
  Text is `s<length in UTF-8 bytes>:<text>`. `app/log.py` has the exact rule. The cases include accents and emoji, so count bytes, not characters.
* A version is a change token and is compared exactly.
* In `script`, `{{version:N}}` in `if_match` is the `version` of step N's answer, and `{{version:N.I}}` is the version of entry I in that answer's `entries`. Take them from your own answers, not from the file.
* The entries in the file hold only the fields that are the same on both sides: `id`, `date`, `meal`, `food_name`, `servings`, `grams`, `note`, `status`, `purpose`, `kidney_rating`, `version` and `nutrients`. A `412` answer carries the entry as it now is, in `current`.

## fhir_labs_vectors.json

Lab results read from FHIR JSON files, the clinical records the iPhone Health app exports.

* Server: none, because the files are read on the device. `tests/test_fhir_labs.py` checks every code and unit against `app/units.py`.
* Browser twin: `app/static/js/engine/fhir_labs.js`.
* Made by `tests/js/gen_fhir_labs_vectors.mjs`, from hand-written resources and hand-written answers. All names and values are invented.

Top-level keys:

* `about`: where the file comes from.
* `limits`: `max_files`, `max_file_bytes`, `max_depth`, `max_nodes`, `max_bundle_entries`, `max_records`, `max_collect`, `max_results` and `max_problems`.
* `loinc`: `[{code, analyte, name, ucum, unit, url}]`, the table of LOINC codes the reader accepts and the app unit each one maps to.
* `unit_aliases`: an object from a lower-case unit spelling to the app's unit.
* `cases`: `{name: string, files: files, options: {tzOffsetMinutes: int, today?: string, existing?: [{analyte, taken_on, value}]}, expected: {problem, counts, results, problems, summary}}`. `files` is written as in `ccda_labs_vectors.json`.

What a replayer must get right:

* The `loinc` table and `unit_aliases` are exact. A record with two codes for different tests, or a unit that could mean two things, is refused and counted.
* Dates and `tzOffsetMinutes` work as in `ccda_labs_vectors.json`.
* Only a final observation with a tracked code and a single number becomes a row. Every other record is counted in `counts`, and those counts are part of the answer.
* Rows come out newest first. `problems` and `summary` are sentences shown to people.

## guidance_vectors.json

Meal guidance: room left in a meal, what fits now, swaps, the Treating a low options and card, day planning, day and period insights, what the app has learned, and the check that sends a message about a low away from the AI.

* Server: the pure engine in `app/guidance/` (`budget.py`, `fits.py`, `swaps.py`, `planner.py`, `insights.py`, `hypo.py`, `rules.py` and the rest).
* Browser twin: the nine files in `app/static/js/engine/guidance/`, loaded after `rules.js` in the order `GUIDANCE_PARTS` gives in `tests/js/run_vectors.mjs`.
* Made by `tests/data/gen_guidance_vectors.py`, from the fixture in `tests/guidance/fixtures.py` and real foods from `data/foods.json`. It has no clock and no randomness.

Top-level keys:

* `format`: the layout version of this file.
* `rules_version`: the version of the guidance rules.
* `rules_hash`: a hash of the rules. Both change whenever a rule or its text changes, so compare them with your own copy first.
* `about`: where the file comes from.
* `foods`: the food rows the cases use. Ids below 101 are the fixture foods, and ids from 101 are real foods. A row is `{id, name, category, serving_desc, serving_g, nutrients, flags, source, fdc_id, kidney_notes, hidden, role}`. A `null` nutrient is unknown.
* `cases`: `{id: string, input: object, call: object, output: object | null}`.

`input` is everything a request loads for one person: `date`, `food_set` (`fixture`, `real` or `all`, which foods the case may use), `profile`, `prefs`, `tunables`, `day`,
`history`, `history60`, `planned30`, `saved_meals` and `combos`. Entries carry their nutrients already multiplied by `servings`. `call.fn` names the function and the
other fields of `call` are its arguments: `meal_room`, `what_fits`, `find_swaps`, `hypo_options`, `plan_day`, `day_insights`, `period_insights`, `learned` or `prefilter`. `output` is the JSON the API sends for that function, before the API adds `ai` and `targets`.
The replayer in `tests/js/run_vectors.mjs` (`guidanceVectors`) and the docstring of `tests/data/gen_guidance_vectors.py` are the specification.

What a replayer must get right:

* **Treating a low is never blocked, delayed or sent to an AI.** The `hypo_options` and `prefilter` cases pin this. The prefilter cases say which typed texts get the Treating a low card instead of an AI call, and which do not (`output: null`).
  The classifier is built to show the card when in doubt. A client must replay all of them, show the card text unchanged, and give a low treatment no carbohydrate warning and no limit. Do not drop or soften any of these cases.
  The options still carry their potassium, phosphorus and sodium warnings, so a person can pick the lowest-potassium one.
* Every number in `output` is already rounded by the engine. Scores use JavaScript `Math.round` semantics to two decimals, milligrams are whole numbers, and grams have one decimal, half up.
  Floats are written in their shortest round-trip form.
* `day_left` in a `meal_room` answer is `null` where the limit is unlimited. Python's infinity has no JSON form.
* The text in `output` (cards, notes, tips, `explain` blocks) is shown to people and is compared word for word.
* The runner compares guidance answers keeping the sign of zero, because Python writes `-0.0` when a small negative number rounds to zero. No case has one today.

## import_vectors.json

The import of an `export.json` file ("Keep my data in this browser"): every refusal in its words, the dry run, adding to an account that has data, and what the account holds afterwards.

* Server: `app/data_import.py`, behind `POST /api/me/import`.
* Browser twin: the demo route `app/static/js/mock/import.js`.
* Made by `tests/data/gen_import_vectors.py`. It builds its own files, so the cases test the rules and not one side's idea of an export.

Top-level keys:

* `constants`: `rule` (the duplicate rule, a text shown to people), `not_imported`, `imported_settings`, `skipped_sections` and `max_depth`.
* `base`: a complete export file. Most steps are small edits of a copy of it.
* `script`: one request script. A step has `edits` or `body`, and its `answer` is `{status: int, body: object}`.

An edit is `{op: "set", path: [string | int], value}`, `{op: "delete", path}` or `{op: "replace", value}`. A path mixes object keys and list positions. `replace` swaps the whole file for `value`.
Apply the edits in order to a deep copy of `base`, and send the result as the request body.

What a replayer must get right:

* Answers to `GET` steps are compared without `id`, `food_id`, `created_at`, `updated_at`, `version`, `linked_at` and `client_id`, which differ between servers.
* The `detail` of a refusal is the sentence a person sees. It is compared word for word.
* What a browser cannot hold is left out of the file: a float written `2.0` against the integer `2`, numbers past 2^53 and `Infinity`. `run_vectors.mjs` checks `Infinity` and the depth limit by hand.

## kidney_function_vectors.json

Lab units and conversions, the three eGFR equations, the G and A categories, ages, and the kidney function card.

* Server: `app/units.py` and `app/kidney_function.py`.
* Browser twin: `app/static/js/engine/kidney_function.js`.
* Made by `tests/data/gen_kidney_function_vectors.py`.

Top-level keys:

* `about`: where the file comes from, and the one tolerance rule.
* `unit_table`: `{key, label, canonical_unit, units: {unit: {mul, div, add}}, plausible: [number], fresh_days: int, decimals: int, si_unit: string}`, one row per test.
* `unit_systems`: the two unit systems, `us` and `si`.
* `conversion_cases`: `{analyte: string, value: number | "Infinity", unit: string, expect: object}`. `expect` is the stored values and the echo shown before saving, or `{error: string}`.
* `egfr_cases`: `{equation: "cr" | "cys" | "cr_cys", creatinine?: number, cystatin_c?: number, age: int, sex: string, expect: {unrounded: number, rounded: int, category: string} | {error: string}}`.
* `category_cases`: `{egfr: number, category: string}`.
* `albuminuria_cases`: `{value: number, unit: string, category: string}`.
* `age_cases`: `{birth_month: string, today: string, last_day: bool, age: int}`.
* `assess_cases`: `{name: string, today: string, profile: object, labs: [object], expect: object}`, the whole card of `GET /api/labs/kidney-function`.
* `today`: the day the generator used as "today" for the cards. Each case that needs a day also carries its own.

What a replayer must get right:

* Everything is compared exactly except `egfr_cases[].expect.unrounded`, which is compared within 1e-9 relative. The rounded integer and the category are exact.
* A stored value is `value * mul / div + add`, and a step that is the identity is skipped. Do the steps in this order. The comparison is exact, so another order can change the last digits.
* JSON has no infinity, so `"Infinity"` as a `value` stands for it.
* `error` strings, the card's `message` and the echo are shown to people and compared word for word.
* Ages come from `birth_month` as `YYYY-MM`. `last_day` counts from the last day of that month instead of the first.

## lab_import_vectors.json

Lab results read from a CSV file ("Import from a spreadsheet").

* Server: none, because the file is read on the device. `tests/test_lab_import.py` checks every conversion against `app/units.py` and that the request body is accepted by `POST /api/labs/import`.
* Browser twin: `app/static/js/engine/lab_import.js`.
* Made by `tests/js/gen_lab_import_vectors.mjs`. It writes down what the reader does, so review the diff by hand after a change.

Top-level keys:

* `about`: where the file comes from.
* `limits`: `max_chars`, `max_rows` and `max_results`.
* `cases`: `{name: string, text: string, options: {today: string, dateOrder?: string, units?: {column: unit}, existing?: [{analyte, taken_on, value}]}, expected: object}`. `expected` is
  `{problem, delimiter, rows, dateColumn, slashDates, dateOrder, dateOrderDetected, columns, ignored, results}`. `text` is the whole file. `columns` says how each column was read and `ignored` lists the headers that are not lab tests.
* `request_cases`: `{name: string, results: [object], expected: {results: [{analyte, value, unit, taken_on}]}}`, the body of `POST /api/labs/import` for the rows the person kept.

What a replayer must get right:

* The unit comes from the column header, or from `options.units` (the unit the person chose for a column) when the header gives none. `needsUnit` marks a column that still has no unit.
* A date written with slashes is ambiguous. It follows `dateOrder`, which is detected when a day is above 12. `dateOrderDetected` and `slashDates` say what happened.
* A value such as `<0.5` is never guessed. It is listed as not imported, with a reason.
* `display` shows the converted value as the server will store it. The conversions follow `kidney_function_vectors.json`.
* `problem` and each row's `problem` are sentences shown to people.

## menu_link_vectors.json

The "Add this day to my plan" links in the handbook: reading a link, matching its foods, building the log request, and writing a link.

* Server: none for reading. The links are written by `scripts/build_handbook.py` (`menu_plan_items`), and `tests/test_menu_plan.py` runs the reader over every link it makes.
* Browser twin: `app/static/js/engine/menu_link.js`.
* Written by hand and reviewed by hand. No generator.

Top-level keys:

* `about`: where the file comes from.
* `limits`: `max_items`, `max_link_chars` and `max_servings`.
* `meals`: the one-letter meal codes in a link and their names.
* `parse_cases`: `{name: string, hash?: string, hash_repeat?: {prefix, item, count, start, same?}, expected?: object, expected_ok?: bool, expected_count?: int}`.
* `resolve_cases`: `{name: string, foods: [object] | null, items: [object], expected: {rows, skipped}}`.
* `batch_cases`: `{name: string, rows: [object], date: string, expected: [object]}`.
* `encode_cases`: `{items: [object], expected: string}`.

A link looks like `#plan-menu?items=b173905x1,l170187x0.5`: a meal letter, a food number, `x`, and the servings. A `hash_repeat` stands for `prefix`, then `item` written `count` times
joined by commas, with `{n}` replaced by `start + i` (or left as it is when `same` is true). A case with `expected_ok` checks only that the link is accepted and has `expected_count` items.

What a replayer must get right:

* A `resolve_cases` lookup matches a food number to the first built-in food that is not hidden. Rows come back in meal order, and in link order inside a meal. An item with no match goes to `skipped` as `{text, reason}`, and the reason is shown to people. The expected rows carry the matched food's `id` as `food_id`.
* `batch_cases` build planned entries, one `client_id` each. The runner hands out `id-1`, `id-2` and so on. A row that brings its own `client_id` keeps it.
* The limits in `limits` are exact.

## meta_vectors.json

The answer of `GET /api/meta` on a server with nothing optional switched on.

* Server: `app/meta.py`, over `app/nutrient_core.py` and `app/api_version.py`.
* Browser twin: the demo route `app/static/js/mock/meta.js`.
* Made by `tests/data/gen_meta_vectors.py`, from a fresh server with every switch at its default.

Top-level keys:

* `about`: where the file comes from.
* `api_version`: the integer API version.
* `capability_keys`: the keys of `capabilities`, in the server's order.
* `capabilities`: `{key: bool}`. They are all `false`, because nothing optional is on.
* `nutrients`: `[{key, label, unit, role}]`, the nutrient registry in the server's order.
* `meals`: the meal names in order.

What a replayer must get right:

* Order is part of the answer for `capability_keys`, `nutrients` and `meals`.
* `app_version` is not in the file, because it changes with every release.
* A client can compare its own nutrient list with `nutrients`. A nutrient added on one side only fails the check.

## personal_target_vectors.json

The test vectors of design note 05 section 5.1: a person's details in, daily targets out.

* Server: `app/targets.py`, checked by `tests/test_targets.py`.
* Browser twin: none of its own. `tests/data/gen_targets_vectors.py` reads this file and turns its vectors into the cases TV01 to TV23 of `targets_vectors.json`, which the twin replays.
* Copied word for word from `docs/dev/research/05-personalized-targets.md`, with hand-checked answers. Not generated.

Top-level keys:

* `about`: where the file comes from.
* `today`: the day all the vectors treat as today.
* `vectors`: `{id: string, input: object, expect: object}`. `input` holds profile fields and, for some, lab values (`potassium`, `phosphate`, `albumin`, `bicarbonate`, `uacr`). `expect` has
  `targets`, `reference_weight_kg`, `weight_basis`, `age`, `nutrition_risk` and `rules`, or `error`, and sometimes `alerts`.

What a replayer must get right:

* In this file `rules` uses the note's rule ids (`P-2`). In `targets_vectors.json` the same rule is `P-2d` or `P-2n`.
* The values are the note's. If a vector is wrong, change the note first and then this file.

## rules_vectors.json

The food rules: warnings, the red, yellow or green rating, and the rounding of nutrient values, for every built-in food and for the edges of every threshold.

* Server: `app/rules_kidney.py` (`food_warnings`, `kidney_rating`), `app/nutrient_core.py` (`round_value`, `NUTRIENT_KEYS`) and `app/nutrients.py` (`round_nutrients`).
* Browser twin: `app/static/js/engine/rules.js`.
* Made by `tests/data/gen_rules_vectors.py`.

Top-level keys:

* `about`: where the file comes from.
* `foods_version`: the version of `data/foods.json` the foods came from. It changes with the food list.
* `servings`: the three amounts each food is tried at.
* `nutrient_keys`: the nutrient keys in the order of every `rounded` list.
* `foods`: `{i: int, fdc_id: int, name: string, nutrients: {key: number | null}, flags: [string], kidney_notes: string | null}`, every built-in food. `kidney_notes` is kept only when the food has the `avoid_ckd` flag.
* `food_cases`: `{food: int, servings: number, scope: string, warnings: [warning], kidney_rating: string, rounded: [number | null]}`. `food` is the `i` of a row in `foods`.
* `boundary_cases`: `{nutrients: object, flags: [string], kidney_notes: string | null, scope: string, warnings: [warning], kidney_rating: string}`, edge values around every threshold, every flag that changes a rule, unknown values and a seeded random sample.
* `round_cases`: `{key: string, value: number, expected: number}`.

A warning is `{nutrient: string, level: string, value: number | null, flag: string | null, message: string}`.

What a replayer must get right:

* For a `food_cases` row, multiply each nutrient by `servings` as a floating-point number (an unknown stays `null`) and do not round before the rules run. Then call the rules with `scope`, and round with `round_value` to get `rounded`.
* `scope` is `per serving`, `in this entry` or `in this meal`. It changes the wording of `message`.
* Rounding is half up on the decimal text, and everything here is compared exactly. See "Rounding" below.
* **A food that treats a low gets no carbohydrate warning.** The cases with the `hypo_treatment` flag expect none, at every amount. Its potassium, phosphorus and sodium warnings stay, so a person can still pick the lowest-potassium option. Do not drop or soften these cases.
* `message` is shown to people and is compared word for word.

## settings_vectors.json

The settings registry, how a value is checked, and which level wins when the environment, the admin and the person all set one.

* Server: `app/settings_registry.py` and `app/settings_store.py`.
* Browser twin: `app/static/js/engine/settings.js`.
* Made by `tests/data/gen_settings_vectors.py`.

Top-level keys:

* `about`: where the file comes from.
* `registry`: one row per setting: `{key, scope, default, env, label, help, type, min?, max?, options?, minLength?, maxLength?, pattern?}`. `scope` is `instance`, `user` or `user_default`.
  `type` is `bool`, `int`, `choice`, `object` or `str`. `env` is the environment variable that locks the setting, or `null`.
* `validation_cases`: `{key: string, input: any, value?: any, error?: string}`. A case has `value` when the input is accepted and `error` when it is refused.
* `precedence_cases`: `{name: string, env: object, instance: object, user: object, user_view: object, admin_view: object}`, a set of stored values and what each view shows for them.

What a replayer must get right:

* The registry keys come in the same order as the server's.
* `error` is the wording of the server's validator. A client that does not use that validator only needs to refuse the same inputs.
* In `precedence_cases`, `env` holds raw environment variable values as text, such as `"false"` and `"  Locked name "`. A blank value is not a lock, and a stored value that is not valid falls through to the next level.
* Each view entry has a `source`: `default`, `env`, `instance` or `user`.
* `label` and `help` are shown to people.

## symptoms_vectors.json

The symptoms log: the list of symptoms, severities, the handbook red flags, the API shape of a row, the Trends grouping, and every symptoms route.

* Server: `app/symptoms.py` and the `SymptomCreate` model in `app/models.py`.
* Browser twin: `app/static/js/engine/symptoms.js` and the demo routes `app/static/js/mock/symptoms.js`.
* Made by `tests/data/gen_symptoms_vectors.py`. Its `summarise_cases` are written by hand in the script, because only the browser draws Trends.

Top-level keys:

* `symptoms`: `[[key, name]]`, the fixed list.
* `severity_labels`: `{"1": string, "2": string, "3": string}`.
* `limits`: `max_label`, `max_note` and `max_per_day`.
* `href`: the path of the Get help now page.
* `link_text`: the words of the link to it.
* `red_flags`: `{symptom: {level: string, text: string}}`, the handbook's words for symptoms that call for action.
* `row_cases`: `{row: object, symptom: object}`, a stored row and the shape the API gives it.
* `script`: one request script.
* `summarise_cases`: `{name: string, symptoms: [object], groups: [object]}`, the Trends grouping: highest severity per day, most days first, then by name.

What a replayer must get right:

* A symptom with a red flag carries its handbook text and a link to Get help now. Show it. Do not drop, shorten or soften it. A flag can be `prominent`, and that is kept too.
* The request script rules below apply: `{{today:N}}`, `<ts>` and the order of steps. The "not in the future" rule is checked against today's date.
* A symptom of another person is invisible and a 404. The runner checks that after the script.
* `name`, `severity_label` and every refusal's `detail` are shown to people.

## targets_vectors.json

Daily targets for a person from their profile and lab results, with every note word for word, the refusals, the alerts, and the two formulas under them.

* Server: `app/targets.py`, with the data in `app/target_rules.py`.
* Browser twin: `app/static/js/engine/targets.js`. It needs `rules.js` and `kidney_function.js` loaded first.
* Made by `tests/data/gen_targets_vectors.py`. The cases TV01 to TV23 come from `personal_target_vectors.json`.

Top-level keys:

* `about`: where the file comes from, and the one tolerance rule.
* `tables`: named tables the twin must hold word for word: the rule catalogue, notes, refusals and the number tables.
* `reference_weight_cases`: `{weight_kg: number, height_cm: number | null, expect: {weight_kg, basis}}`.
* `eer_cases`: `{sex: string, activity: string, age: int, height_cm: number, weight_kg: number, kcal: number}`, the energy equation.
* `cases`: `{id: string, today: string, profile: object, labs: [object], settings: object, expect: object}`. `expect` is `{targets, notes, rules, derived, missing_inputs, alerts}`, or `{error: {code, message}}` for a refusal, or `{invalid: string}` for input the rules cannot use.
* `wrapper_cases`: `{args: [weight_kg, stage, dialysis, diabetes, height_cm], expect: object}`, the older `suggest_targets` call.

A lab row looks like a stored row: `{id, analyte, value, entered_value, entered_unit, taken_on}`, with `value` in the canonical unit.

What a replayer must get right:

* `notes` and every message are compared byte for byte. They cite their sources and contain typographic characters.
* `eer_cases[].kcal` is compared within 1e-9 relative. Everything else is exact.
* A case's `settings` holds the three settings the rules read: `default_activity`, `fresh_days` and `lab_rules_enabled`.
* `rules` lists catalogue keys. The API sends `{id, ...}` with the id `P-2` for the keys `P-2d` and `P-2n`.
* `alerts` are urgent and emergency messages about a lab result. A client must show them.
* The three refusals (pregnancy, under 18, an early transplant) mean the app gives no suggestion and the person enters targets by hand. A client must not suggest numbers in those cases.
* `today` is always given. Never read a clock.

## Replaying in another language

The recipe is the same for every file.

1. Load the file as JSON. Read numbers as doubles.
2. For each case, call your function with the case's input and compare the result with the expected answer. The section for each file names which fields those are.
3. Collect every mismatch and fail if there is one. `tests/js/run_vectors.mjs` is the reference replayer, and it is written to be read. Each `...Vectors` function in it shows what to pass for its file.

Comparison rules that hold across files:

* **Deep equality.** The same keys with the same values. Object key order does not matter. List order does. A key set to `null` and a missing key are different answers.
* **Numbers are compared by value.** Python writes `3.0` where JavaScript has `3`. A decoder that keeps integers and floats apart must not call these different. The only tolerances are
  `egfr_cases[].expect.unrounded` in the kidney function file and `eer_cases[].kcal` in the targets file: within 1e-9 relative, meaning `|got - want| <= 1e-9 * max(1, |want|)`. Everything else is exact.
* **Text is compared code point by code point.** Do not normalise it. In Swift, `==` on strings treats some different spellings of one letter as equal, so compare `unicodeScalars` or the UTF-8 bytes.
* **Rounding** is half up on the number's shortest decimal text, not on its binary value. `26.95` rounds to `27.0`, not `26.9`. This is the server's `_half_up` in `app/nutrient_core.py`, and
  the twins use `KH.rules.halfUp`. A plain `round` on a double gets some of these wrong. The vectors are full of these edge values on purpose.
* **Dates and time zones.** The cases do not depend on the real date. `today` comes with the case, or as `{{today:N}}` in a request script. A date from the Health app is the wall-clock date as written. A date in a lab record with a time and a zone is moved to the device's zone, and the cases pass `tzOffsetMinutes` so that the answer does not depend on the machine.
* **Versions and hashes** change when rules change: `rules_version` and `rules_hash` in the guidance file, `foods_version` in the rules file, `api_version` in the meta file, and the entry `version`. A client that keeps its own copy of one needs a test that fails when the copy is old.
* **Text shown to people** (warnings, notes, refusals, red flags, cards) comes from the server's code and the handbook, and the clinical numbers in it cite their sources. A client shows it word for word and does not reword it.

### Request scripts

The body, symptoms, entry version and import files each hold a `script`: a list of steps run in order against a fresh account, so later steps depend on earlier ones (ids start at 1).
A step is `{name: string, method: string, path: string, body?: any, answer: object}`.

* Send the request and compare with `answer`. An answer is `{ok: true, body}` or `{ok: false, status: int, detail: string}`, with extra fields where the server sends them. The import file uses `{status, body}`.
* `{{today:N}}` in a path or a body is the date N days from today. N is negative for earlier days. Turn a date in the answer back into its marker before comparing, so the vectors hold for any day.
* A `created_at` or `updated_at` in the answer is written `<ts>`. Compare only that the field is there.
* Details that belong to one file are in its section above.

### Safety

Some vectors carry the app's health-data rules. Treating a low is never blocked, delayed or sent to an AI, and gets no carbohydrate warning (`guidance_vectors.json`, `rules_vectors.json`).
Red flags and alerts are shown (`body_vectors.json`, `symptoms_vectors.json`, `targets_vectors.json`). An additive cannot hide behind an invisible character (`barcode_vectors.json`).
A client must not drop, shorten or soften these cases to make a replay pass. If one fails, the client is wrong.

### For an iOS client

The first two files to replay are `body_vectors.json` and `apple_health_vectors.json` (design note 14, change 6 in `docs/dev/research/14-reuse-map.md`).
They pin the kilogram rounding, the ranges, the contexts, the pairing of the two blood pressure numbers and the `source_key`. The `source_key` must match the one the web import builds, or the same reading will be added twice.
A Swift test target that replays them is planned with the iOS design note. None exists yet.
