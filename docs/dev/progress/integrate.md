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
* Step 3 (security cross-checks):
  - Egress: grep found the HIBP breach check (app/auth/policy.py) using a plain httpx2.Client (default transport,
    trust_env, redirects) → now `egress.CheckedTransport()`, no redirects, trust_env off (test_passwords asserts it).
    New static guard tests/test_egress.py::test_every_outbound_client_in_the_app_uses_a_checked_transport (every
    httpx2 client passes transport=; only egress.py and the loopback healthcheck use urllib).
  - AI off by default sends nothing: tests/test_ai_routes.py::test_a_configured_provider_is_never_contacted_while_ai_is_off
    (env provider configured, ai.enabled default: no DNS lookup at start-up or on any AI/photo/guidance route).
    OFF off by default: already tests/test_barcode_api.py::test_off_by_default_nothing_leaves_the_server.
  - Secrets: tests/test_secrets_v03.py (own and shared AI keys never in any answer, export, audit, log or the DB in
    clear; last4 only for keys ≥ 20 characters).

* Step 2 finding (fixed): with Open Food Facts on, no personal agreement yet and a usable USDA key, a product only
  Open Food Facts knows answered 404 "No product with this barcode in Open Food Facts or USDA" (Open Food Facts was
  never asked, and the consent panel never appeared). app/barcode.py now answers 503 off_consent_required in that
  case (the UI's consent panel), and a 404 names only the databases that answered "not found". Tests in
  tests/test_barcode_api.py; ARCHITECTURE + docs/barcode-and-photos.md updated.

* Step 2 (real server + Chromium): new harness tools/e2e/journey.py (fake AI + fake Open Food Facts + USDA replayed by
  tools/e2e/replay_app.py, built handbook): setup → AI on → profile → labs change targets with reasons → barcode (USDA,
  then Open Food Facts after the agreement panel) → label photo (AI) → What fits now → Not for me → swap → Plan the rest →
  offline ×2 synced exactly once → Trends insights → Learn links → second person isolation (incl. the first person's
  waiting offline entry never sent as theirs) → export zip → account deletion (all rows gone) → screens at 375/1280
  light/dark. Result: 122/122 PASS, zero console errors / CSP / failed requests. `python3 tools/e2e/journey.py --site
  $S/learn --port 8380 --ai-port 8381 --off-port 8382 --out $S/journey`.
  - Found + fixed on the way: Learn links (`.learn-more`) were 20 px tall: now ≥ 24 px everywhere (WCAG 2.2 2.5.8) and
    44 px on touch/narrow screens (css/base.css, css/touch.css).
* Upgrades: new harness tools/e2e/upgrade.py (git archive of 8b8d4ec = v0.2 and 9ef9151 = M1 schema v3, filled through
  their own API, upgraded on a copy): 71/71 PASS (entries/totals/profile/meals/custom foods/CSV identical, new columns
  empty, step 4–7 tables, integrity + FK checks, labs/suggestion/guidance/batch/export on old data; APP_PASSWORD import +
  pre-v3 backup 0600; two people and a still-readable USDA key for v3).
* Observations for owners (not changed): after "Use this plan" Today shows a red "Projected over" when the planned
  dinner has 60.6 g carbs for a 60 g goal, while the plan says "close to your goal" (guidance tolerance ±10 g vs the
  strict per-meal alert); the curated "Egg white, raw" is planned as a dinner protein (USDA raw values; a display name
  like "Egg white (cooked)" or a note would read better: food-db owner).
* Step 4 (harnesses, commit 6d60952): parity.py section 14 (AI off: /api/me/ai shape and 10 AI/vision routes
  compared by status + detail): 14/14; sandbox.py walks What fits now, a recorded barcode (3017624010701 with the
  agreement), Plan the rest, Treating a low: 2 walks 0 issues; regress.py step 10b (What fits dinner, a typed barcode
  of the person's own food answering `source: local` with the additive warning, Treating a low): 375-light 122/0.
  tools/e2e/README.md lists journey.py, upgrade.py, replay_app.py with ports and how to read results.
* Step 5 (deploy): compose.yaml passes the v0.3 keys through as `${NAME:-}` (an empty value = unset, so nothing is
  locked unless deploy/.env sets it; proven by tests/test_compose_env.py, 5 tests, plus a TestClient run where
  /api/admin/settings reported every key `source: default`), AI key only as a commented file secret; .env.example
  explains each key; Quadlet and k8s deployment.yaml have commented examples (Quadlet AI example uses a LAN
  address, not host.containers.internal on 127.0.0.1, which docs/deployment.md says stays unreachable);
  secret.example.yaml lists ai_api_key; every profile names the egress hosts and points to
  docs/network-allowlist.md (networkpolicy.yaml and the Cilium example already did). docs/deployment.md: the stale
  "AI_* … once they ship" row replaced by PASSWORD_BREACH_CHECK, OFF_*, GUIDANCE_*, AI_* and the instance-setting
  rows, plus an "Outbound connections" paragraph. Checks: `docker compose config --quiet` for compose.yaml and with
  the Ollama overlay (dummy secrets created and removed), yaml parse, kustomize + kubeconform strict as CI (12 valid),
  pytest tests/test_deploy.py tests/test_compose_env.py green.
* Step 6 (ARCHITECTURE sync): every one of the 216 /api operations (openapi + route-tree walk from
  tests/test_auth_coverage.py) is named in ARCHITECTURE.md and no documented /api path is missing from the app
  (`$S/routes_vs_arch.py`); every registry key and env lock is documented (M1 keys were missing: added under
  "/api/admin"). Fixed stale text: layout (app.js/style.css gone, config/db lines, tools/e2e harness list incl.
  journey/upgrade/replay_app/device/learn/guidance_perf), "Non-goals" points to accounts, Stack names js/ and
  css/, "`usda` (and later `off`)", HIBP check through CheckedTransport, egress section lists every client and the
  test that enforces it. Tests that read ARCHITECTURE.md (17 files) pass.

## In progress

## Cross-owner fixes (file, why, test)

## Decisions

## Not verified here

## Commands
