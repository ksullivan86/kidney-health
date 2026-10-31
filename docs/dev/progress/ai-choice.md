# ai-choice: chosen people pick the server's local or cloud AI (0.21)

Status: in progress

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

## Next
* CHANGELOG Unreleased; docs/test-the-full-app.md tester step; docs/privacy.md line.
* e2e Chromium walk if a harness covers Settings → AI features / admin users.
* ruff, node --check, full suite at the end.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -p no:cacheprovider --basetemp=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/aichoice/bt tests/test_ai_route_choice.py
$PY tests/data/gen_settings_vectors.py --check; node tests/js/run_vectors.mjs; $PY scripts/gen_openapi.py --check
$PY scripts/build_handbook.py --check; cd handbook && .../hbvenv/bin/mkdocs build --strict -d <scratch>
Git: commit only own paths (no -A/-a); split git commands into plain ones (the worktree guard refuses compound ones).
