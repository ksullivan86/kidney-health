Status: complete (2026-10-31)

# Lists and recipes (0.19): list sync to Grocy/KitchenOwl/Mealie, recipe import

Design: docs/dev/research/30-list-sync-and-recipe-import.md. Branch: this worktree's branch (worktree-agent-aaa6eae790965487c),
from next-8 (0.18.0). Schema step 32. Do NOT bump the version or write a CHANGELOG release heading (the integrator does): the
CHANGELOG has an "Unreleased" list, ARCHITECTURE a "v0.19 work" note. docs/deployment.md has no "From v0.18 to v0.19" upgrade
section yet (it names the tag): the integrator adds it (schema step 32 adds one table; nothing new is switched on).

## Done (and how it was checked)
1. Merged next-8 (ff). Read CLAUDE.md, notes 16/22/27/28, devices code, egress, meals, settings registry.
2. List-app APIs verified from each project's source (raw files on GitHub, 2026-10-31), recorded in note 30 §1.
3. Design note 30; pointers added in notes 16 (§13 web import) and 22 (status).
4. Server: settings `lists.sync_enabled` / `recipes.import_enabled` (+ engine/settings.js twin, settings vectors, Server settings
   group "Shopping list app and recipe import"), config `LIST_SYNC_ALLOWED_HOSTS` (validated), m032 `list_sync`,
   `app/list_sync/` (apps.py: address check, allowlist, ListTransport, Grocy/KitchenOwl/Mealie; api.py), `app/recipe_import/`
   (parse.py pure, fetch.py, api.py), main.py wiring (`app.state.list_sync_net`, `app.state.recipe_fetcher`), audit actions
   (person-visible), ENCRYPTED_COLUMNS, brand user agents, `meals.shopping_items()`, rate limits `list_send`, `list_test`,
   `recipe_page`. Tests: tests/test_list_sync.py (38), tests/test_recipe_import.py (84), tests/test_migration_m032.py (2),
   isolation matrix (`list_sync`), egress client list, test_brand, test_migration_m031 (later steps allowed).
5. JS: engine/recipe_import.js twin + tests/data/lists_recipes_vectors.json (gen_lists_recipes_vectors.py --check in
   tests/test_lists_recipes_ui.py; run_vectors.mjs section "lists and recipes", 144 checks); mock/lists.js (sample Grocy +
   sample recipe page); views/list_sync.js (Settings section, Plan send sheet); views/recipe_import.js (import sheet);
   index.html, sw.js, plan.css; activity labels in settings.js. tests/test_lists_recipes_ui.py + tests/js/lists_recipes_demo.mjs.
6. OpenAPI regenerated (`scripts/gen_openapi.py --check` current).
7. Docs: ARCHITECTURE (v0.19 work note, step 32 row, shopping list pointer, outbound list, two new sections), docs/list-sync.md,
   docs/recipe-import.md, network-allowlist, deployment table, privacy, guidance link, README index, test-the-full-app (tester
   step under 6 and server-owner note), ROADMAP (both items built; Privacy tiers next for 0.20), CHANGELOG Unreleased,
   deploy env templates (.env.example, compose, quadlet, k8s), tests/data/README.md. Handbook: planning-and-menus (Import a
   recipe, Send it to your own list app, troubleshooting), settings-and-keys (row), self-hosting/configuration (3 rows),
   self-hosting/network-allowlist (2 rows); sources NOTE30 and SCHEMA-NUTRITION (schema.org NutritionInformation has no
   potassium or phosphorus property, checked 2026-10-31). build_handbook.py run, --check current, mkdocs --strict OK.
   No removed headings (git diff checked).
8. Chromium walk tools/e2e/lists_recipes.py (+ lists_recipes_app.py): 42 passed, 0 failed.

9. Full suite (7203 collected): 1 failure, `tests/test_recipes_ui.py` pinned the old handbook words "never opens" (the link is
   now opened on import); the test now pins the new sentence. 2 skipped. After the fix: the changed files and the doc tests
   (824 passed), ruff clean, vectors, settings vectors, OpenAPI and handbook checks current.

## Left for the owner or the integrator
- Version bump, CHANGELOG release heading, and a "From v0.18 to v0.19" section in docs/deployment.md (one new table, nothing on).
- A try against real Grocy, KitchenOwl and Mealie servers (tests use fakes built from each project's source).

## Commands
    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad
    $S/lr_pt.sh -q tests/test_list_sync.py tests/test_recipe_import.py tests/test_lists_recipes_ui.py tests/test_migration_m032.py
    $S/venv312/bin/python tests/data/gen_lists_recipes_vectors.py --check; $S/venv312/bin/python tests/data/gen_settings_vectors.py --check
    $S/venv312/bin/python scripts/gen_openapi.py --check; $S/venv312/bin/python scripts/build_handbook.py --check
    node tests/js/run_vectors.mjs; /root/.local/bin/ruff check app tests scripts tools
    python3 tools/e2e/lists_recipes.py --out $S/lr-e2e
    (cd handbook && $S/hbvenv/bin/mkdocs build --strict -d $S/lr-hb-site)
