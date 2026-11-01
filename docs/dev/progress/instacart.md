Status: complete

# instacart (release 0.22): open the Plan's shopping list at Instacart

Branch: `worktree-agent-afb89a633be1a633e` (merged `next-8` fast-forward at 8730b34). The integrator merges, bumps the version
and writes the release heading. Do not push to `claude/adoring-sagan-th5swr` or `next-8`.

## Done
- Read CLAUDE.md, ARCHITECTURE (egress, list sync, shopping list), note 22 §4, 0.14-plan (owner approved: only the food list).
- Fetched the Instacart docs (2026-11-01, reachable): create shopping list page, shopping list concept, units of measurement,
  API keys, approval process. Facts are in design note 33 §1.
- Design note `docs/dev/research/33-instacart.md` (decisions in §2, owner-changeable ones in §4).
- Server (a529189): `app/config.py` `InstacartEnv` (`INSTACART_API_KEY_FILE` only, `INSTACART_BASE_URL` https host only,
  warning for a non-Instacart host), setting `lists.instacart_enabled` (`INSTACART_ENABLED`) in the registry and the JS twin,
  settings vectors; `app/instacart.py`; audit `instacart.sent`; `brand.USER_AGENT_INSTACART`; egress list; OpenAPI.
- Frontend (91d6e3d): `#shopping-instacart`, `#sheet-instacart`, `js/views/instacart.js`, plan.js, sw.js, demo routes in
  `js/mock/lists.js`, `tests/js/instacart_demo.mjs`, `tests/test_instacart_ui.py`.
- Docs (f9f37a1, 2bfc339): `docs/instacart.md`, README index, deployment, privacy, security, network allowlist (docs, handbook,
  cilium example), deploy templates (compose, .env.example, quadlet, k8s deployment + secret example), test-the-full-app,
  ROADMAP, CHANGELOG "## Unreleased", handbook planning page + configuration + sources (NOTE33, INSTACART-IDP), ARCHITECTURE.
- Chromium (cc52094): `tools/e2e/instacart.py` + `instacart_app.py`: 25 passed, 0 failed.
- Checks: ruff clean; openapi, settings vectors, lists vectors, handbook `--check` clean; `node tests/js/run_vectors.mjs` 19
  suites pass; handbook strict build passes.

## Next
Nothing. Full suite after the last code change: 7,331 passed, 2 skipped, exit 0.

## Left for the integrator
- The release heading for 0.22 in CHANGELOG, the "Upgrading" lines in `docs/deployment.md` and `handbook/.../upgrades.md`
  ("nothing new is switched on": Instacart stays off until `INSTACART_ENABLED` and the key), version bump.

## Decisions (see note 33 §2)
- Title "Shopping list" and User-Agent "shopping-list": the brand name would hint at a health condition.
- Grams as the only measurement; no measurement without weight. `expires_in` 7. No linkback, instructions, image.
- Audit on every send that may have reached Instacart (not `blocked`), details `{items}` only.
- Test accounts may use it. Own Plan only (no Care team button).
- Demo preview reuses list-sync `listItem` (no control-character cleaning: demo food names are clean).

## Commands
- `PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
- `SCR=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/instacart`
- `$PY -m pytest -p no:cacheprovider --basetemp=$SCR/bt tests/test_instacart.py tests/test_instacart_ui.py`
- `$PY tests/data/gen_settings_vectors.py --check`, `$PY scripts/gen_openapi.py --check`, `node tests/js/run_vectors.mjs`
- `python3 tools/e2e/instacart.py --out $SCR/e2e`
