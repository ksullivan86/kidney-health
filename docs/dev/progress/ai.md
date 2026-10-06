Status: in progress

# ai (M2): optional AI + photo routes

Spec: docs/dev/research/04-optional-ai.md R1, R3–R9, R11, R13 (with the contract's corrections), §6 checklist,
§9 security review (overrides earlier text); note 03 R8, R9, §9 (B1, B10) for the photo routes; note 06 §4.13
(the guidance AI hook); contract items 2 (one registry + credential resolver) and 13 (Hermes).
Owned files: app/ai/**, app/migrations/m006_ai.py, app/vision.py, app/imagecheck.py, AI settings keys,
docs/ai.md, docs/barcode-and-photos.md "Photos" section, deploy/compose.ai-ollama.yaml, scripts/ai_eval.py,
tests/test_ai_*.py, tests/test_vision_api.py, tests/test_imagecheck.py, tests/test_migration_m006.py,
tests/ai_golden/**, tests/fixtures/ai/**. Ports 8330–8339.
Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/ai/

## Plan (sub-steps)
1. m006 schema + migration test (commit first: the barcode builder waits for it to add m007)
2. Settings keys (registry) + env (config.py `AiEnv`), presets, netpolicy (pure), transport (pinned async httpx2)
3. client.py (body per preset, parse, JSON extraction, retries/repair, limiter + per-user lock, probe incl. Hermes gate)
4. prompts.py, schemas.py, guard.py (V1–V9; A2 no free text: reason_codes/theme enums; A3 escaping)
5. features.py (next_meal via app.guidance.ai_bridge, parse_meal, read_label, identify_food, G7/G8 prefilters)
6. config.py (provider store, env provider sync, resolution user→shared→none, quota, consent, audit, purge)
7. routes: /api/ai/*, /api/me/ai, /api/admin/ai-providers; app/imagecheck.py; app/vision.py (/api/vision/label, /plate)
8. export/delete, main.py registration, A7 none-mode 403, guidance ai block (register_ai_status)
9. Tests: netpolicy, client, guard, golden (≥40), routes, imagecheck, vision; scripts/ai_eval.py
10. Docs: docs/ai.md, ARCHITECTURE "M2 API: AI and photos" + ownership row, network allowlist, compose overlay,
    barcode-and-photos photos section, ROADMAP, handbook pages if needed

## Done (and how verified)
* Step 1: app/migrations/m006_ai.py (ai_providers, ai_consents, ai_usage, ai_audit; cascades) +
  tests/test_migration_m006.py (populated v5 upgrade, idempotent, constraints, cascade). `pytest tests/test_migration_m006.py`.

## Decisions
* Consents are rows (`ai_consents`, FK to provider and user) rather than a list inside the `ai` settings
  object: they must only be written by the consent route (which shows the exact payload), must not be
  clobbered by a generic settings PATCH, and must disappear when a provider's host changes.
* The env provider (`AI_PROVIDER`…) is a `locked=1` row synced at start-up; its key stays in the env only.
