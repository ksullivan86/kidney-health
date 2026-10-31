Status: in progress (2026-10-31)

# Lists and recipes (0.19): list sync to Grocy/KitchenOwl/Mealie, recipe import

Design: docs/dev/research/30-list-sync-and-recipe-import.md. Branch: this worktree's branch, from next-8 (0.18.0). Schema step 32.
Do NOT bump the version or write a CHANGELOG release heading (the integrator does).

## Done
1. Merged next-8 (ff). Read CLAUDE.md, notes 16/22/27/28, devices code, egress, meals, settings registry.
2. List-app APIs verified from each project's source (curl of raw files on GitHub, 2026-10-31), recorded in note 30 §1.
3. Design note 30 written.

4. Server: settings lists.sync_enabled / recipes.import_enabled (+ engine/settings.js twin, settings vectors, Server settings group),
   config LIST_SYNC_ALLOWED_HOSTS (validated), m032 list_sync, app/list_sync/ (apps.py: transport + 3 clients; api.py),
   app/recipe_import/ (parse.py pure, fetch.py, api.py), main.py wiring, audit actions (user visible), ENCRYPTED_COLUMNS,
   brand user agents, meals.shopping_items(). Verified: tests/test_list_sync.py (38), test_recipe_import.py (84),
   test_migration_m032.py, isolation matrix, egress client list, OpenAPI regenerated (--check).
5. JS: engine/recipe_import.js twin + tests/data/lists_recipes_vectors.json (gen_lists_recipes_vectors.py, run_vectors.mjs
   section "lists and recipes"); mock/lists.js (sample Grocy + sample recipe page); views/list_sync.js (Settings section, Plan
   send sheet); views/recipe_import.js (import sheet); index.html markup, sw.js, plan.css. tests/test_lists_recipes_ui.py +
   tests/js/lists_recipes_demo.mjs.

## Next
- Deploy env files, docs (ARCHITECTURE, list-sync.md, recipes, network-allowlist, test-the-full-app, ROADMAP, CHANGELOG),
  handbook pages; Chromium walk tools/e2e/lists_recipes.py; full suite.

## Commands
    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad
    $S/venv312/bin/python -m pytest -p no:cacheprovider --basetemp=$S/pt-lr <files>
