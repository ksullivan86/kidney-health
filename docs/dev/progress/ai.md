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

* Steps 2–7 (first pass, smoke-tested end to end with a fake OpenAI transport; route tests next):
  registry block "Note 04" in app/settings_registry.py (ai.* + `ai` object, NO_SIGNIN_ENV_ONLY for §9 A7),
  `AiEnv` + `load_ai_env` in app/config.py, app/ai/{presets,netpolicy,transport,client,schemas,prompts,guard,
  features,config,routes}.py, app/imagecheck.py, app/vision.py, main.py registration + startup hook, admin_api
  A7 refusal for ai.* settings in none mode, export.json ai_usage/ai_consents/ai_provider.
  Verified: `pytest tests/test_ai_netpolicy.py` (122 cases), smoke script
  `$SCRATCH/v030/ai/smoke.py` (dry run, 409 consent, call, audit, /api/me/ai, admin list).

* Resumed 2026-10-06 (second attempt, after a usage-limit cut-off at 100caec): committed the route tests
  (`tests/test_ai_routes.py`, e05eb92); `js/engine/settings.js` twin lists the ai.* and food.* keys
  (030521f; node tests/js/run_vectors.mjs: settings 444 checks pass); daily background re-test of shared
  providers + re-test after an env key change (key fingerprint in probe_json) + R12 CA-store self-check
  (eddb33b). Verified: `pytest tests/test_ai_*.py tests/test_imagecheck.py tests/test_migration_m006.py`.

* Also done (2026-10-06, second attempt): tests/test_vision_api.py (21), tests/test_ai_prompts.py (payload snapshot
  `tests/fixtures/ai/next_meal_payload.json`, PROMPT_VERSION fingerprint pin `prompt_version.json`; version now
  2026-10-06.2 after candidates use full nutrient keys), failure-path tests in test_ai_routes.py, scripts/ai_eval.py
  + tests/test_ai_eval_script.py + docs/dev/ai-eval/README.md, ARCHITECTURE "M2 API: AI and photos" + ownership
  rows, docs/ai.md, docs/barcode-and-photos.md "Photos", docs/privacy.md, docs/network-allowlist.md, ROADMAP.
  Branch coverage (scratch coverage install): guard.py 100 %, AI package 92 % overall.
  Label draft: `flags` empty (saving scans the confirmed ingredient text), `needs` lists name/serving_g when missing.

## Next (in order)
1. Frontend (decided: build it; M1 reserved `#set-ai-slot` for M2, R13 lists `app/static/ai.js`, nobody else owns AI UI):
   new files `app/static/js/ai.js` (KH.ai), `app/static/css/ai.css`, `app/static/js/mock/ai.js` (demo: "available
   in the installed app"); index.html: link/script tags, `#ai-add-slot` in the Add view, AI sheets; settings.js:
   one-line hook in renderAi. Then Chromium checks (375/1280, light/dark), test_frontend_shell, preview build.
2. Handbook pages app/ai.md + self-hosting/configuration.md AI section: drop "coming in v0.3", plate gives names
   + rough weight (note 03 R9), link docs/ai.md; build the handbook strict.
3. Final: full `python -m pytest`, node vectors, progress note "Status: complete".

## Decisions
* Consents are rows (`ai_consents`, FK to provider and user) rather than a list inside the `ai` settings
  object: they must only be written by the consent route (which shows the exact payload), must not be
  clobbered by a generic settings PATCH, and must disappear when a provider's host changes.
* The env provider (`AI_PROVIDER`…) is a `locked=1` row synced at start-up; its key stays in the env only.
* `/api/ai/*` and `/api/vision/*` are always mounted but answer 404 (as unregistered) while `ai.enabled` is off,
  checked per request after `current_user` (anonymous → 401 like every /api route; test_auth_coverage needs it),
  so an admin can switch AI on in Settings without a restart.
* Routes are `/api/vision/label` and `/api/vision/plate` (task), not note 04's `/api/ai/read-label|identify-food`.
* No separate AI_VISION_ENABLED switch: vision is on exactly when the provider has a vision model (task).
* A2: meal features have no model free text; `theme` + `reason_codes` enums, claims re-checked against the
  recomputed numbers (false ones removed and counted), sentences from server templates (guard.REASON_TEXT).
* Upstream failure: next-meal/parse-meal answer 200 `{"status":"error","reason",...,"fallback"}` (Layer 0
  degrade, R1); vision routes answer 502 (no rule result to fall back to).
* At most one extra request per call (one retry for 429/5xx/connect, or one repair turn), R6 "at most one".
* Daily re-test (R4 step 5) runs as a FastAPI background task after a person's call to a shared provider whose
  test is missing or ≥ 24 h old (at most one attempt per provider per hour; own connection; a server slot under a
  pseudo-person; nobody's quota). No timer thread: AI egress still happens only because someone used AI.
* The env provider's key is never stored; `probe_json.key_fp` (HMAC under SECRET_KEY) tells start-up that the
  key changed, which clears the stored test.
* Frontend (app/static/**: AI cards, consent sheet, settings slot, label/plate UI, mock twins) is the
  frontend owner's; handoff below. settings.js lacks the ai.* keys (as it lacks guidance/food.* keys already).
