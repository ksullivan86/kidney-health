Status: in progress

# instacart (release 0.22): open the Plan's shopping list at Instacart

Branch: `worktree-agent-afb89a633be1a633e` (merged `next-8` fast-forward at 8730b34). The integrator merges, bumps the version
and writes the release heading. Do not push to `claude/adoring-sagan-th5swr` or `next-8`.

## Done
- Read CLAUDE.md, ARCHITECTURE (egress, list sync, shopping list), note 22 §4, 0.14-plan (owner approved: only the food list).
- Fetched the Instacart docs (2026-11-01, reachable): create shopping list page, shopping list concept, units of measurement,
  API keys, approval process. Facts are in design note 33 §1.

## In progress / next
1. Design note `docs/dev/research/33-instacart.md`.
2. Config (`INSTACART_API_KEY_FILE`, `INSTACART_BASE_URL`), setting `lists.instacart_enabled` (`INSTACART_ENABLED`).
3. `app/instacart.py`: client through `egress.CheckedTransport`, routes `/api/instacart` (+ `/preview`, `/send`).
4. Tests `tests/test_instacart.py`; egress list in `tests/test_egress.py`.
5. Frontend: Plan → Shopping list → Open in Instacart (sheet), demo mock.
6. OpenAPI, settings vectors, docs, handbook, CHANGELOG Unreleased.

## Commands
- Tests: `$PY -m pytest -p no:cacheprovider --basetemp=$SCR/bt tests/test_instacart.py` with
  `PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`,
  `SCR=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/instacart`.
