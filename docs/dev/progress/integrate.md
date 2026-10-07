Status: in progress

# integrate (M2 + M3, v0.3.0): one coherent, working app

Role prompt: integrate the whole v0.3.0 build (ARCHITECTURE.md "Milestones": M2 features + M3 integration).
Ports 8380–8389. Scratch: `$S` = /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/integrate/
WIP commits end with " [skip ci]"; commit only my paths (never -A). A docs-release agent owns README, CHANGELOG,
contributor docs, handbook app pages and docs/ROADMAP.md at the same time: leave those to it.

## Plan
0. Handoffs from the progress notes (first work items): alcohol offered by What fits now (safety), NO_TARGETS copy,
   score.py pow vs x*x, handbook DG47 dead link, anything else "not done".
1. Static checks: pytest (system python + venv312), node vectors, node --check, handbook checks, hadolint,
   actionlint, zizmor, SHA-pin check, kubeconform; TODO/FIXME/XXX/NotImplementedError/skip/xfail grep.
2. Real server + Chromium (375x812, 1280x800, light/dark): setup → profile → labs → targets → day with barcode,
   label photo, what-fits, swap, plan-the-rest → offline sync once → Trends insights → Learn links → second user
   isolation → export zip → deletion; upgrade a populated v0.2 and a populated v3 (M1) database.
3. Security cross-checks: auth coverage, isolation matrix, egress only via checked transports, write-only
   secrets, AI and OFF off by default with nothing sent.
4. tools/e2e parity/sandbox/regress cover the new features; README there.
5. Deploy: optional egress (AI, OFF, USDA) in NetworkPolicy/compose/Quadlet comments + docs/deployment.md;
   .env.example.
6. ARCHITECTURE.md matches the build.
7. Preview rebuild + sandbox walk.

## Done (and how verified)

* Baseline (HEAD 855ef2a): `python -m pytest` (3.11) exit 0; CI-like Python 3.12 venv with only
  requirements-dev.lock (`$S/venv312ci`): exit 0 with 2 skips (no PyYAML → tests/test_handbook_content.py and
  test_deploy.py::test_every_yaml_file_parses skipped in CI's test job). node vectors all pass; node --check on 49
  static JS files ok; handbook: build_handbook --check, strict mkdocs build into `$S/learn`, check_links (119 pages,
  0 broken); pin check, actionlint, hadolint (3 Containerfiles), kustomize+kubeconform strict (12 resources),
  shellcheck, yaml_parse (31 files), zizmor 1.30.1 --offline: all clean.
* Step 0 (handoffs):
  - SAFETY: new flag `alcohol` (nutrients.FLAGS, rules.js FLAGS, curated beers/wines/spirits, foods.json
    2026-10-07.1 rebuilt from the SR Legacy zip: only those 5 flags changed). Guidance never suggests it: fits
    eligibility (`alcohol` reason), check_meal strict (built/AI), swaps, planner energy note, usual meals drop the
    drink; JS twin identical; RULES_VERSION 2026-10-07.1 (hash 8514c677136c30ea); vectors regenerated with alcohol
    cases (48 JS checks pass). OFF `en:alcoholic-beverages` and USDA ethanol ≥ 0.4 g/100 g (nutrient 221/1018) or
    "Alcoholic beverage, …" set the flag. ADA 2026 §5 recs 5.18–5.19 verified on PMC12690188. Tests:
    tests/guidance/test_alcohol.py (9), OFF + USDA mapping tests. Docs: ARCHITECTURE (Flags, OFF, USDA),
    docs/guidance.md, docs/barcode-and-photos.md.
  - NO_TARGETS copy says Profile (py + js twin + test + docs); the UI button now reads "Open Profile".
  - score.py `max(0, dev) ** 2` → product (libm pow 1-ulp risk); twin comment updated.
  - Skips removed: PyYAML added to requirements-dev.in and requirements-dev.lock (pip-tools 7.6.1 / pip 26.2.1 on
    Python 3.14, only pyyaml 6.0.3 added); the defensive skips in test_food_db, test_handbook_content (incl. the stale
    "topics.py not written yet"), test_nutrients, test_rules_vectors (node now required, clear message),
    test_security, test_deploy are gone. `git grep` finds no skip/xfail in tests/ or tools/.
* Step 3 (part): tests/test_isolation_v03.py: schema-driven matrix (every table with user_id/owner_user_id must be
  listed with the tests that prove isolation) + labs, Not for me, guidance settings, client_id, AI consent/audit/
  usage/own provider, export and deletion between two people. tests/test_auth_coverage.py: V03_ROUTES (all 38 v0.3
  routes must exist and answer 401 anonymously).
* Full `python -m pytest` after these changes: exit 0.

## In progress

## Cross-owner fixes (file, why, test)

## Decisions

## Not verified here

## Commands
