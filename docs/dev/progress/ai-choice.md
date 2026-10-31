# ai-choice: chosen people pick the server's local or cloud AI (0.21)

Status: in progress

Branch: worktree-agent-a267dd5ea2389b2d3 (fast-forwarded to next-8 at 1936769). Design: docs/dev/research/32-choose-local-or-cloud-ai.md.

## Done
* Read CLAUDE.md, ARCHITECTURE routing sections, docs/ai.md, note 31, app/ai/routing.py, config.resolve, admin users API/screen, mock.
* Design note 32 written (decisions listed there).

## Next
1. m033 (users.can_choose_ai) + test.
2. Settings: ai.person_route_choice (env AI_PERSON_ROUTE_CHOICE_ENABLED), ai.route_choice (user object); JS twin; vectors.
3. app/ai/route_choice.py; routing step 5; routes (GET /api/me/ai route_choice, PUT /api/me/ai/route-choice); PATCH /api/me/settings guard.
4. Admin users: can_choose_ai in view + PATCH + audit; settings.js tick box; mock auth.js.
5. ai.js Settings choice UI; mock ai.js route_choice:null.
6. Tests, OpenAPI, docs, handbook, CHANGELOG, e2e.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -p no:cacheprovider --basetemp=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/aichoice/bt <files>
