Status: complete (2026-10-15; the caller integrates the branch; nothing pushed, no PR opened)

# lab-photo: read lab results from a photo of a report

Branch `worktree-agent-a90911b820067f713`, base `5eb2867`. Local AI only (privacy tier 1 routing, role `local`),
own consent purpose `labs`, migration step 16, `POST /api/ai/read-lab-report`, review table with every row unticked.

## Decisions
* Merged with `origin/main` (84ab48c: symptoms log = the real step 15, profile-worded prompts `.3`, visit prep) on 2026-10-15.
  The temporary local stand-in for step 15 used while testing is gone; `tests/test_migration_m016.py` builds its "before"
  database from the real steps 1..15.
* The photo route takes the raw `image/jpeg` body like `/api/vision/label` (the brief said multipart; the existing pattern is
  raw JPEG, no spooling to disk, same image checks and `MAX_IMAGE_BYTES` rules).
* The route lives in `app/vision.py` (`lab_router`, prefix `/api/ai`), reusing `read_photo`, `photo_headers`, `ai_slot`.
* Routing: `labs` joins `routing.FEATURES` with `LOCAL_ONLY = ("labs",)`: registry type `Literal["local","off"]`, the
  resolver ignores a person's own provider and `any`, `plan()` refuses cloud/any (400 `local_only`), `PUT /api/admin/ai-routing`
  takes `labs: "local"|"off"` (400 otherwise), the overview adds `allowed` per feature, `initialise` writes `local` for it.
* The model's `analyte` may be `other` (or any short string): the wire schema hints the app's codes + `other`; the code drops and
  counts anything else (`unknown_analyte`). A failing schema (wrong type, extra field, a boolean value) shows nothing (one
  repair, then 502).
* Dates: only unambiguous printed dates are read (ISO, month names, d/m or m/d when a part > 12 or both equal); otherwise
  `taken_on` is null with `date_problem` + `date_note` (the app's words) and the person types the date. A future date is cleared
  the same way (it is not a dropped row). `printed_date` is shown only if it is digits, month names and `/ . , : -`.
* Audit row: `Prepared.keep_response=False` so the AI activity row has no copy of the answer (health data); the request copy has
  the photo as sha256/size/dimensions only.
* `PROMPT_VERSION` 2026-10-15.4 (main's text unchanged, plus `TASK_LINES["lab_report"]`) pinned in
  `tests/fixtures/ai/prompt_version.json`; the per-profile prompt snapshots are unchanged (a task line is not part of them).
  After any later prompt change re-pin with `KH_UPDATE_SNAPSHOTS=1 pytest tests/test_ai_prompts.py` (delete the stale pin first).
* `tests/test_ai_prompts.py::test_fields_that_are_never_sent` is flaky on its own (the dry run holds a random hex
  `safety_identifier`; the test fails when it happens to contain "168"): seen once in a shard, passes on re-run; not touched.

## Done (how it was checked)
* Backend: m016, registry key `ai.route.labs` (+ JS twin, `settings_vectors.json` regenerated), routing, schema, prompt line,
  `app/ai/lab_report.py` (judge), `prepare_read_lab_report`, `POST /api/ai/read-lab-report`, status (`features.lab_report`,
  `routes.labs`, `consent.labs`), consent purpose `labs` with the server's `notice` lines. `tests/test_lab_photo.py` (~50 tests),
  `tests/test_migration_m016.py`, golden cases `tests/ai_golden/lab-report-*.json` (14), auth coverage, isolation matrix.
* Front end: `js/views/lab_photo.js`, shared `saveImported` in `labs.js`, hooks in `ai.js`, admin table in `ai_routing.js`,
  card in `index.html`, `sw.js`, CSS, deploy pass-through of `AI_ROUTE_LABS`. `tests/test_lab_photo_ui.py` runs
  `tests/js/lab_photo_page.mjs` (rows start unticked etc.) and `tests/js/routing_page.mjs` (labs row).
* Docs: ai.md, privacy.md, ARCHITECTURE.md, CHANGELOG, ROADMAP, handbook (ai.md, targets-and-warnings.md, configuration.md),
  deployment.md, targets-and-labs.md, barcode-and-photos.md.
* Verification: full suite in 4 shards (`-x`), all exit 0 at the final commit; `node tests/js/run_vectors.mjs`;
  `python tests/data/gen_settings_vectors.py --check`.

## Not done / for the owner
* A live run on a real local vision model (units and dates a model misreads); `scripts/ai_eval.py` skips the local-only cases.
* Uploading the PDF itself (only the photo/screenshot version is built).

## Reproduce
`python -m pytest -q -p no:cacheprovider tests/test_lab_photo.py tests/test_lab_photo_ui.py tests/test_migration_m016.py tests/test_ai_golden.py`
`node tests/js/run_vectors.mjs`  `node tests/js/lab_photo_page.mjs`
