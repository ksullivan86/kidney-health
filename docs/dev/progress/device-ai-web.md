Status: complete

# device-ai-web: the iPhone's own AI in device mode, web side (design note 38 §5.6, step 5)

Branch: `worktree-agent-a4d90a7fe2dfd0a87` (fast-forwarded to `9f7825a`, which holds `js/mock/device.js` and its `lookup`).
Do not push, no pull request. Commit only the paths below.

## What was built

* `app/static/js/engine/aijudge.js` (`KH.aiJudge`): `pyRe` (a Python regex as a JS one: Unicode `\w \b \d \s`, `.`, `$`),
  `features.prefilter` (red flag, medicine question with `chat.dose_reason` and `lab_words`; the low check is
  `KH.guidanceEngine.prefilter`), `guard.name_policy`, `features.serving_quantity` / `servings_for` (round half to even), the
  parse-meal judge, `prompts.clean`, the data block's escaped JSON (`dataPayload`), `features.lab_text_lines`, and page-only answer
  checks (`checkParseMeal`, `checkLabReport`). `PROMPT_VERSION` is a copy, checked by pytest.
* `app/static/js/engine/lab_report.js` (`KH.labReport`): `app/ai/lab_report.py` whole (dates, judge, numbers_in, judge_text).
* Both are in `index.html` (after aiguard.js) and `sw.js`.
* Vectors: `tests/data/gen_ai_device_vectors.py` → `tests/data/ai_device_vectors.json` (62 prefilter, 62 name policy,
  27 serving quantity, 306 servings, 11 payload, 7 parse-meal, 40 date, 27 number, 7 lab judge, 13 lab text cases; 869 checks).
  Replayed by `node tests/js/run_vectors.mjs` ("ai device"). `tests/test_ai_device_vectors.py`: freshness, the twins' regex sources
  equal the server's, PROMPT_VERSION, coverage, `ai-prompts.json`. README section in `tests/data/README.md`.
* `scripts/build_preview.py --device` writes `ai-prompts.json` and packs `vendor/pdfjs-dist-6.4.299/` (lab PDFs on the phone).
* `app/static/js/mock/ai.js`: device branch (GET/PATCH `/api/me/ai`, GET `/api/ai/status`, POST `/api/ai/parse-meal`,
  POST `/api/ai/read-lab-report-text`). Outside device mode unchanged (fixed lab example stays).
* `app/static/js/views/ai.js`: `status()` reaches the in-page API in device mode; Settings → AI features shows one switch
  (`devicePart`); the dry run view says it stays on the iPhone. `views/lab_photo.js`: the opt-in sentence in device mode.
* Tests: `tests/js/device_mode.mjs` sections 9 and 10; `tools/e2e/device_mode.py` `ai_walk` (Chromium, 32 PASS).
* Docs: ARCHITECTURE "Device mode", CHANGELOG Unreleased, note 38 §5.6, handbook `app/install.md`.

## ai-prompts.json (the Swift side reads it)

    { "system": "<TASK_SYSTEM_PROMPT>",
      "tasks": { "parse_meal": { "template": "..." }, "read_lab_report_text": { "template": "..." } } }

Each template is `prompts.user_message(task, data, mode="json_schema", schema)` with the data block's JSON replaced by `{text}`:
`<TASK line>\n<data>\n{text}\n</data>`. The page sends, as `text`, the exact escaped JSON the server puts in the data block
(`{"text":"..."}` or `{"lines":[...]}`), so substitution gives the server's message byte for byte. Mode `json_schema` (no
schema line) because guided generation enforces the shape. A lab payload over 8,000 characters is 413 `too_long_for_ai` before asking.

## Decisions

* `{text}` stands for the whole data JSON, not only the text value, so one rule fits both tasks (lab text is a list of lines).
* A malformed item is left out (`malformed_item`); a malformed lab row is counted in `dropped.malformed` with a note (page only;
  the server fails the whole answer). A top level that does not fit is `schema`.
* Consent is given with `skip_preview` (nothing leaves the phone); `opt_in` stays the person's choice, kept as `api._aiPrefs`.
* The prefilter runs before asking whether the model is available, so a low's card shows even then.

## Commands

    node tests/js/run_vectors.mjs
    node tests/js/device_mode.mjs
    python -m pytest -p no:cacheprovider -o addopts="" tests/test_ai_device_vectors.py tests/test_device_mode.py ...
    cd tools/e2e && python device_mode.py --out <empty dir>
    /root/.local/bin/ruff check .

## Verified (2026-11-21)

* `node tests/js/run_vectors.mjs`: all groups pass, "ai device vectors: 869 checks passed".
* `node tests/js/device_mode.mjs`: 86 checks passed.
* pytest of every file that mentions mock/ai.js, views/ai.js, aiguard, lab_report, build_preview or device, plus the vector tests:
  2690 passed; the 3 failures (source-reading tests in test_ai_ui, test_lab_photo_ui, test_ask_ui) were updated and pass now.
* `tools/e2e/device_mode.py`: 32 PASS (Chromium, 375 light and 1280 dark).
* `ruff check .`: clean.
* `tests/test_vectors_readme.py` was failing before this work (no usda section, barcode `off_map_cases` missing); fixed in the README.
