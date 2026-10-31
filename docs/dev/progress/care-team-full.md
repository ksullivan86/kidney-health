Status: in progress

# Full Care team (design note 29, release 0.18 work)

Branch: worktree-agent-a39dd5dde408ee2a1, fast-forwarded to next-8 (4c139f2, 0.17.0) before starting.

## Done
- Design note `docs/dev/research/29-full-care-team.md` with the Decisions section.

## Next
1. Migration m031 (switches on shares and care_invites, care_suggestions) + tests.
2. Server: switches/roles in app/sharing.py, Caregiver logging, saved meals routes, suggestions (app/care_suggestions.py),
   audit actions, export key `care_suggestions`, import skips it.
3. Tests, OpenAPI, vectors (import skipped sections).
4. UI: sharing.js switches, careplan.js (eaten, saved meals, suggest), Plan "Suggestions for you", activity labels.
5. Demo twin js/mock/care.js; Node tests; e2e tools/e2e/sharing.py.
6. Docs: ARCHITECTURE, docs/accounts.md, handbook, test-the-full-app, CHANGELOG Unreleased.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -q -p no:cacheprovider --basetemp=<scratch>/bt tests/test_care_team*.py tests/test_sharing*.py
