Status: complete

# ai-choice: chosen people pick the server's local or cloud AI (0.21)

Branch: worktree-agent-a267dd5ea2389b2d3 (fast-forwarded to next-8 at 1936769). Design: docs/dev/research/32-choose-local-or-cloud-ai.md.

## Done (and how verified)
* Design note 32 (decisions listed there: switch AI_PERSON_ROUTE_CHOICE_ENABLED off by default; users.can_choose_ai via m033;
  setting ai.route_choice (default|local|cloud per photos/meal_ideas/describe/chat/recipes; no labs); choices kept and ignored
  when tick/switch goes; own provider wins; chosen = one AI, no fallback; chosen role gone -> chosen_role_missing, never moved).
* m033 + tests/test_migration_m033.py (pass).
* Registry: ai.person_route_choice, ai.route_choice (+ JS twin, vectors with ROUTE_CHOICE_VALUES). gen --check ok, node vectors ok.
* app/ai/route_choice.py; routing._resolve_feature step after own provider; Resolved.chosen; route_view "chosen"; "You chose this.".
* Routes: GET /api/me/ai route_choice; PUT /api/me/ai/route-choice; PATCH /api/me/settings refuses ai.route_choice (403).
* Admin: can_choose_ai in user view + PATCH + audit user.updated; audit action ai.route_choice_changed (person-visible).
* UI: settings.js tick box + hint + GROUPS + activity labels; ai.js routeChoicePart; ai_routing.js hint; mocks (auth, ai, settings).
* tests/test_ai_route_choice.py: 16 pass. Batch of related suites (routing, cloud routing, fallback, privacy filter, ai routes,
  settings, auth coverage, isolation, openapi, audit, ui, compose env, deploy) pass.
* OpenAPI regenerated. Docs: ARCHITECTURE (v0.21 note, migration row, new section), docs/ai.md, env template/compose/quadlet,
  handbook (ai, settings-and-keys, configuration, users-and-keys, NOTE32 source); build_handbook --check ok; mkdocs strict ok.
* CHANGELOG "Unreleased" section, docs/privacy.md, docs/test-the-full-app.md tester step.
* Chromium walk tools/e2e/route_choice.py (new, listed in tools/e2e/README.md): 34 passed, 0 failed (375 light, 1280 dark).
* ruff clean; node --check on changed JS; vectors, settings --check, OpenAPI --check, build_handbook --check all pass.

* Full suite after the last code change: 7,279 collected, 7,277 passed, 2 skipped, 0 failed (exit 0, no network). Two warnings,
  both from before this work (settings-and-keys.md lists NOTE28 without citing it; 6 unused sources.yml ids).

## Left for the integrator
* Version bump and the CHANGELOG release heading (the "Unreleased" list has the 0.21 section above the 0.20 one).

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -p no:cacheprovider --basetemp=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/aichoice/bt tests/test_ai_route_choice.py
$PY tests/data/gen_settings_vectors.py --check; node tests/js/run_vectors.mjs; $PY scripts/gen_openapi.py --check
$PY scripts/build_handbook.py --check; cd handbook && .../hbvenv/bin/mkdocs build --strict -d <scratch>
Git: commit only own paths (no -A/-a); split git commands into plain ones (the worktree guard refuses compound ones).
