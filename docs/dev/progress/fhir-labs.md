Status: complete (2026-10-15; the caller integrates the branch; nothing pushed, no PR opened)

# fhir-labs: lab results from Apple Health clinical records (FHIR R4 JSON, read in the browser)

Base: `f95d586` (lab-photo feature, `KH.views.labs.saveImported`). Branch `worktree-agent-aefbf1b4be4074eee`.
Commit trailers: as the brief gives them.

## Plan (sub-steps)
1. Engine `app/static/js/engine/fhir_labs.js` (`KH.fhirLabs`): LOINC table, `start()` accumulator (`add(file)`, `finish()`), `analyse(files, opts)`.
2. Vectors `tests/data/fhir_labs_vectors.json` (+ generator `tests/js/gen_fhir_labs_vectors.mjs`) and `run_vectors.mjs` section.
3. Page `app/static/js/views/lab_fhir.js` (`KH.labFhir`), card in `index.html`, `sw.js`, CSS, hook in `labs.js` if needed.
4. Python tests: `tests/test_fhir_labs.py` (LOINC table vs `app/units.py`, vectors vs units), `tests/test_fhir_labs_ui.py` + `tests/js/fhir_labs_page.mjs`.
5. Docs: targets-and-labs.md, privacy.md, ARCHITECTURE.md, CHANGELOG.md, ROADMAP.md, handbook `app/targets-and-warnings.md` (labs page).
6. Full suite in 4 shards, vectors, report.

## Decisions (and why)
* LOINC codes were checked against LOINC 2.82 through tx.fhir.org `$lookup` and the NLM Clinical Tables LOINC search on 2026-10-15
  (loinc.org itself answers 403 to this machine). Several remembered codes were wrong (for example 50210-4 is the
  cystatin-C eGFR, 77139-4 is sodium), so nothing is in the table that was not looked up.
* Dates: a date alone is used as written; a time WITH a zone is converted to the calendar day on the device (`tzOffsetMinutes` for
  tests), a time without a zone as written; one day ahead of today is allowed like the server and the CSV import.
* The engine takes files one at a time (`start().add()`), so the page never holds 2,000 file texts; 1,000 newest rows are shown
  (POST /api/labs/import takes 1 to 1,000), the rest counted as "left out".
* Only specimens "Serum or Plasma" and LOINC's own generic "Serum, Plasma or Blood" are read; whole/venous/arterial blood
  (blood-gas) codes, urine potassium/creatinine and 24-hour urine ratios are not tracked tests. eGFR: CKD-EPI (2009/2012 and
  2021, creatinine, creatinine+cystatin C) and the cystatin-C one; race-specific pairs, MDRD and the paediatric formulas are
  not read (the app cannot tell which of a pair applies, and uses CKD-EPI 2021).

## Done (how it was checked)
* Step 1 and 2 (12:05 UTC): `app/static/js/engine/fhir_labs.js` (`KH.fhirLabs`: `start()`/`add()`/`finish()`, `analyse()`), generator
  `tests/js/gen_fhir_labs_vectors.mjs` (hand-written resources AND hand-written expectations; it stops if the module disagrees),
  `tests/data/fhir_labs_vectors.json`, section "fhir labs" in `tests/js/run_vectors.mjs`. `node tests/js/run_vectors.mjs` passes.

* Step 3 and 4 (12:10 UTC): page `app/static/js/views/lab_fhir.js` (`KH.labFhir`), card `#lab-fhir` in `index.html` (next to the CSV card),
  `sw.js` entries, CSS (`labs.css`), harness `tests/js/fhir_labs_page.mjs`, tests `tests/test_fhir_labs.py` (the docs-list test fails
  until the docs step lists the codes) and `tests/test_fhir_labs_ui.py`; neighbouring frontend tests pass.

* Step 5 (docs, 12:25 UTC): `docs/targets-and-labs.md` (section + LOINC table with loinc.org links, which a test keeps in step),
  `docs/privacy.md`, `ARCHITECTURE.md` (new subsection under "M2 API: targets and labs" + module list), `CHANGELOG.md`, `docs/ROADMAP.md`,
  handbook `app/targets-and-warnings.md` ("Import lab results from the iPhone Health app"). `tests/test_fhir_labs*.py`, handbook tests pass.

* Chromium walk (12:25 UTC): no harness existed for the CSV import, so the walk is in `tools/e2e/regress.py` step 2c-ii (nine
  hand-written FHIR files through `set_input_files`); `python tools/e2e/regress.py --no-pytest --no-probes --only 375-light --out <fresh dir>`
  passes (131 checks, the 9 Apple Health ones included); screenshot looked at (375 px, no overflow).

* Step 6: full suite in 4 parallel shards (`timeout 900 python -m pytest -q -x -p no:cacheprovider <files>`), all exit 0;
  `node tests/js/run_vectors.mjs` exit 0.

## Not done / for the owner
* A run on a real iPhone Health export (the sample resources are hand-written): see ROADMAP and `docs/maintainers.md`.
* Whole-blood/venous/arterial, race-specific eGFR and MDRD codes are left out on purpose; more than 1,000 rows are not sent in
  several requests; `export.xml` ClinicalRecord entries are not read (the folder is).

## Reproduce
`node tests/js/run_vectors.mjs`; `python -m pytest -q -p no:cacheprovider tests/test_fhir_labs.py tests/test_fhir_labs_ui.py tests/test_lab_import.py tests/test_lab_photo_ui.py`
