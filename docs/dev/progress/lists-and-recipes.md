Status: in progress (2026-10-31)

# Lists and recipes (0.19): list sync to Grocy/KitchenOwl/Mealie, recipe import

Design: docs/dev/research/30-list-sync-and-recipe-import.md. Branch: this worktree's branch, from next-8 (0.18.0). Schema step 32.
Do NOT bump the version or write a CHANGELOG release heading (the integrator does).

## Done
1. Merged next-8 (ff). Read CLAUDE.md, notes 16/22/27/28, devices code, egress, meals, settings registry.
2. List-app APIs verified from each project's source (curl of raw files on GitHub, 2026-10-31), recorded in note 30 §1.
3. Design note 30 written.

## Next
- Server: settings keys, config LIST_SYNC_ALLOWED_HOSTS, m032, app/list_sync/, app/recipe_import/, main.py wiring, audit actions,
  ENCRYPTED_COLUMNS. Tests with fakes.
- JS twin engine/recipe_import.js + vectors; mock routes; UI (Settings section, Plan send sheet, import sheet).
- Docs, handbook, OpenAPI, Chromium walk, full suite.

## Commands
    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad
    $S/venv312/bin/python -m pytest -p no:cacheprovider --basetemp=$S/pt-lr <files>
