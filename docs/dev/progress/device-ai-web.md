Status: in progress

# device-ai-web: the iPhone's own AI in device mode, web side (design note 38 §5.6, step 5)

Branch: `worktree-agent-a4d90a7fe2dfd0a87` (fast-forwarded to `9f7825a`, which holds `js/mock/device.js` and its `lookup`).
Do not push, no pull request. Commit only the paths below.

## Plan

1. Engine twins (Python is the reference):
   * `app/static/js/engine/aijudge.js` (`KH.aiJudge`): a Python-regex translator (`pyRe`), `features.prefilter` (red flag,
     medicine question with `chat.dose_reason` and `lab_words`; the low check is the existing `KH.guidanceEngine.prefilter`),
     `guard.name_policy`, `features.serving_quantity` and `servings_for`, the parse-meal judge, `prompts.clean` and the data
     payload, `features.lab_text_lines`, and the page-only answer checks for the model's answer.
   * `app/static/js/engine/lab_report.js` (`KH.labReport`): `app/ai/lab_report.py` (dates, judge, numbers_in, judge_text).
   * Vectors: `tests/data/gen_ai_device_vectors.py` writes `tests/data/ai_device_vectors.json`; `tests/js/run_vectors.mjs`
     replays them; `tests/test_ai_device_vectors.py` checks freshness, regex sources and `ai-prompts.json`.
2. `scripts/build_preview.py --device` writes `ai-prompts.json`; the device build also packs pdf.js (lab PDFs).
3. `js/mock/ai.js` device branch; `js/views/ai.js` lets device mode reach the in-page routes and shows a small settings part.
4. Tests in `tests/js/device_mode.mjs`; docs.

## ai-prompts.json (the Swift side reads it)

    { "system": "<TASK_SYSTEM_PROMPT>",
      "tasks": { "parse_meal": { "template": "..." }, "read_lab_report_text": { "template": "..." } } }

Each template is `prompts.user_message(task, data, mode="json_schema", schema)` with the data block's JSON replaced by `{text}`:
`<TASK line>\n<data>\n{text}\n</data>`. The page sends, as `text`, the exact escaped JSON the server puts in the data block
(`{"text":"..."}` or `{"lines":[...]}`), so substitution gives the server's message byte for byte. Mode `json_schema` (no
schema line) because guided generation enforces the shape.

## Done

(nothing yet)
