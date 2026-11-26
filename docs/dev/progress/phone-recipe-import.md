Status: complete (2026-11-26)

# phone-recipe-import: a recipe from a web page on the iPhone, with no server

## Plan
1. Python: tests/data/gen_recipe_page_vectors.py → tests/data/recipe_page_vectors.json (ld_json_blocks over HTML cases,
   the page flow, classify_address, the phone's link check).
2. JS twin of ld_json_blocks (plain tokenizer like html.parser; nothing goes into the DOM) in js/engine/recipe_import.js; replayed by
   tests/js/run_vectors.mjs.
3. KidneyHealthCore/RecipePage.swift: link check (https only, ports 80/443, no user/password), address classes (twin of
   app/egress.py classify_address), charset; Linux tests replay the vectors.
4. Services/RecipePage.swift (app): bridge kind `fetchRecipePage`; DNS check, manual redirects (3), 2 MiB, 15 s, no cookies/cache.
5. js/mock/lists.js: device mode with no server (or server unreachable) → read on the phone; screen text says so.
6. pytest pins (tests/test_ios_app.py style), node tests, e2e if practical, docs.

## Done

## Notes
* venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
* Step 1 done: tests/data/gen_recipe_page_vectors.py → recipe_page_vectors.json; `--check` passes on Python 3.12, 3.13, 3.14, 3.15
  (uv venvs in scratchpad prt-venv3.x). Step 2 done: engine ldJsonBlocks/pageRecipe + exact entities/code-point counting;
  `node tests/js/run_vectors.mjs` passes (recipe page 442 checks). lists.js device flow + view words written (not yet tested).
* Step 3 done: KidneyHealthCore/RecipePage.swift + RecipePageTests.swift; `swift test --filter RecipePageTests` passes locally with the
  CI toolchain (6.4.1, downloaded to scratchpad prt-swift; build dir prt-swiftbuild).
* Step 4 done: Services/RecipePageFetcher.swift (bridge kind fetchRecipePage; DNS check with getaddrinfo, metrics remoteAddress
  re-check, manual redirects, 2 MiB, 15 s deadline, ephemeral session, no cookies/cache); FoodServices: case + services.recipePage.
  Type-checked on Linux (swiftc -typecheck, only Darwin-only CF/SOCK_STREAM errors remain, expected).
* Step 5 done: js/mock/lists.js pageReader (server when it offers and has web on, else phone), fallback when server unreachable;
  view words (read_on). tests/js/phone_recipe_page.mjs (38 checks) + tests/test_phone_recipe_import.py pass.
* Committed: 952215a, 9c7d3dc, e5bef46 (run_vectors.mjs: only my hunks staged with update-index; another agent's deviceMap hunks
  are theirs).
* Docs done: ARCHITECTURE.md (Device mode bullet "A recipe page read on the iPhone", Recipe import section), handbook
  app/install.md and app/planning-and-menus.md, CHANGELOG Unreleased, tests/data/README.md section.
* Checks: targeted pytest (test_phone_recipe_import, test_ios_app, test_lists_recipes_ui, test_server_services_phone,
  test_recipe_import) pass; node run_vectors passes; swift test (whole package, 54 tests) passed locally. The full suite was not
  run, as the orchestrator asked (it runs it once for everyone). test_vectors_readme still fails for other agents' files
  (phone_reminder, device_map), not this one.
* Scratch folders (Swift toolchain, builds, venvs) deleted.
* e2e recipe_walk in tools/e2e/device_mode.py: 13/13 PASS (scratch runner prt-run_recipe_e2e.py runs only this walk).
  INCIDENT: a bad one-liner of mine truncated tools/e2e/device_mode.py; I refilled it from HEAD. phone-extras' uncommitted ask_walk
  hunk (mic → words, no mic) was lost; reported to the orchestrator (main) for phone-extras to redo.
