# Progress: reading a lab PDF's own text layer (lab-pdf-text)

Status: in progress

Branch `lab-pdf-text` from origin/main (fed556c). No schema step. Do not touch Web Push (step 35, app/reminders*).

## Plan
1. Design note docs/dev/research/36-lab-pdf-text.md
2. Server: feature `read_lab_report_text`, route `POST /api/ai/read-lab-report-text` (JSON `{text, page?}`), routed as `labs`
   (local only, consent purpose `labs`), verbatim value check, size limits, audit keeps a fingerprint only.
3. Browser: `js/engine/pdf_text.js` (KH.pdfText: line builder, has-text test, identity-line strip) + Node tests;
   `pdf_pages.js` gets `text(n)`; lab_photo.js offers "Read the text" for pages with text (default), pictures for the rest.
4. Demo twin (mock route with a fixed example, says nothing was sent).
5. Golden cases + ai_eval text section; tests; Chromium walk tools/e2e/lab_pdf_text.py.
6. Docs: ARCHITECTURE, docs/ai.md, handbook labs page, CHANGELOG, ROADMAP.

## Done
* Note 36 written.
* Server: `app/ai/lab_report.py` (`numbers_in`, `judge_text`, TEXT_* sentences; `judge(date_notes=)`), `app/ai/features.py`
  (`lab_text_lines`, `prepare_read_lab_report_text`, `Prepared.hidden_text` → audit keeps `<data>[not kept]</data>` + `lab_text`
  {page, lines, characters, text_sha256}), `app/ai/prompts.py` (TASK_LINES["lab_report_text"], PROMPT_VERSION 2026-11-12.1,
  pinned in tests/fixtures/ai/prompt_version.json), `app/vision.py` (route `POST /api/ai/read-lab-report-text`, body
  `{text<=20000, page 1..50}`, 413 `too_long_for_ai` when over AI_CONTEXT_TOKENS), `app/ai/routes.py` (`features.lab_report_text`).
* tests/test_lab_text.py (37 pass), snapshot tests/fixtures/ai/lab_report_text_request.txt; test_lab_photo writers list updated.
  Verified: `scratchpad/pt.sh tests/test_lab_text.py tests/test_lab_photo.py tests/test_ai_prompts.py`.

## Decisions
* Reuses routing feature `labs` and consent purpose `labs` (same switch, same local-only rule); no new route setting, no schema step.
* One page per request (like pictures); 10-page limit is the browser's (MAX_TICKED), server caps page number 1..50.
* Verbatim check is on numbers as written (with decimal-comma and thousands readings), and a date not in the text is cleared.
* Validation errors in this app are 400 (not 422).
