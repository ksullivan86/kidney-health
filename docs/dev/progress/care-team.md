Status: in progress

# Care team (design note 25)

Branch: worktree-agent-a0c4dba93435a1585, fast-forwarded to next-8 (897538c, has the AI naming change) before starting.

## Done
- Design note `docs/dev/research/25-care-team.md` (decisions: saved meals not in this version; helper may change/remove any
  planned entry except a low treatment; Care helper adds food log; invite answers the same whether the name exists).

## Next
1. m027 + server (`app/sharing.py`, `app/log.py` added_by, `app/models.py` Entry.added_by) + `tests/test_care_team.py`.
2. OpenAPI regen, vectors.
3. UI: Settings → Care team section (`js/views/sharing.js`), Profile link, Today "Added by", Plan "Planning for" (`js/views/careplan.js`).
4. Mock twin (sample Care team), Node UI tests.
5. e2e `tools/e2e/sharing.py` extended.
6. Docs (accounts.md, handbook caregivers + app pages, ARCHITECTURE.md, CHANGELOG).
7. Full pytest.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -q -p no:cacheprovider --basetemp=<scratch>/bt tests/test_care_team.py tests/test_sharing*.py
