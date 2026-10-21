Status: complete

# Learn my food preferences, part B (the screens)

Role: `preferences-b`. Worktree branch `worktree-agent-afc173fa1cb6c0e4b`. Spec: `docs/dev/research/09-food-preferences.md`
(§4.1, §4.3, §4.4, §4.10 wording, §8; §7 "Part B"). Part A (server, engine, routes, demo routes) is described in
`docs/dev/progress/preferences-a.md`. Never push, never open a PR, never touch another branch.

## Start-up facts

- The worktree was created at `2fd1cee` WITHOUT part A (the brief said it had it). Part A is the commit `3fa3ae0` on
  `claude/adoring-sagan-th5swr`; this branch was fast-forwarded to it with `git merge --ff-only 3fa3ae0` (only this branch moved).
- Part C (AI, Ask) runs in parallel and owns `app/ai/**`, `views/ask.js`, prompts, `docs/ai.md`, `docs/assistant.md`; it will not touch
  `views/ai.js` or `views/guidance.js`.

## Plan / state

- [x] 1 `views/guidance.js`: preference API calls (`/preferences`, `/learned`), the "⋯" menu `rowMenu` (More like this / Less often / Not for me, each a toggle with aria-pressed, clear by pressing again; state read from GET /preferences when the menu opens, or passed in by Settings)
- [x] 2 menu on swap rows (normal mode only, never for a low) and plan-sheet items (plan meals and the energy note, not the "closest" list); Not for me in a swap list/plan reloads it
- [x] 3 Settings → Meal guidance → "Your food preferences" (`prefsSection`): three lists with Remove / Suggest again + the "⋯" menu per row, learned list (Keep / Stop using this / Save as a meal / Not this meal), "Not learning about" (Learn again), hidden usual meals (Show them again), per-kind None / Like / Less often / Never suggest radios (replace the old "Never suggest" checkboxes), Learn-from-my-log switch, §4.10 wording
- [x] 4 AI text moved: `KH.ai.preferencesField()` in `views/ai.js`; one line + link in Settings → AI ideas; `KH.guidance.openPreferences()`
- [x] 5 `plan.js`: `openMealEditor(t, trigger, draft)` so "Save as a meal" opens a new saved meal with the usual meal's foods (parsed from the learned item's key)
- [x] 6 CSS (`guidance.css`); first look at 375 light and 1280 dark in the demo build: fine (see scratch shots)
- [x] 7 tests: `tests/test_guidance_ui.py` (static pins), `tools/e2e/journey.py` (Not for me uses the preference route), new harness `tools/e2e/prefs.py` (README row, HARNESSES in `tests/test_e2e_tools.py`)
- [x] 8 `python3 tools/e2e/prefs.py` (all parts, real server with AI_ENABLED + the Pages demo): 198 PASS, 0 FAIL at 375x812 light and 1280x800 dark
- [x] 8b `tools/e2e/parity.py --sections 0,12`: 731/731 (12g2 food preferences 58/58); `tools/e2e/journey.py --site <built handbook>`: 134 PASS, 0 FAIL (its "Not for me" step now expects the preference route)
- [x] 8c `tools/e2e/sandbox.py --workers 4` (the demo inside the artifact host): 17 walks, 3 sweeps, 0 issues; final `prefs.py` run: 204 PASS, 0 FAIL; screenshots in
      `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/prefs-b-shots/` (44 files: menu, swap, plan, low, offline, settings lists/kinds/learned/neutral/save-meal/learn-off/AI text; 375x812 light, 1280x800 dark, real server and demo)
- [x] 9 docs: `docs/guidance.md`, `handbook/docs/app/guidance.md`, `handbook/docs/app/ai.md` (where the AI text is), ARCHITECTURE "Frontend", CHANGELOG (new bullet + part A's bullet no longer says the screens are missing), note 09 §7 + status, ROADMAP line;
      handbook: `build_handbook.py --check`, `mkdocs build --strict` (own venv from `handbook/requirements.lock`), `check_links.py`, `tests/test_handbook_content.py`, `tests/test_learn_links.py` all green
- [x] 10 final runs: `python -m pytest -q` 4,736 passed, 0 failed, no network; `node tests/js/run_vectors.mjs` all suites pass; `ruff check .` clean; `node --check` on guidance.js, ai.js, plan.js;
      handbook: `scripts/build_handbook.py --check`, `mkdocs build --strict`, `check_links.py` (0 broken), `tests/test_handbook_content.py`, `tests/test_learn_links.py` green

## Decisions and why

- Keep on a food the app *lowered* (`effect: less`, planned but not eaten) stores `less`, not `like`: turning a skipped food into a like would
  say the opposite of the item. A kept food shows "Kept: …" and no buttons (Stop using this would replace its like with `neutral`).
- One component, `rowMenu`, for every "⋯" (suggestion, swap, plan item, Settings row): three toggles with `aria-pressed` and a CSS check mark;
  the state is read from `GET /preferences` when the menu opens (no route for one food), Settings passes it in. A like or a "less often"
  does not reload the list; only Not for me does (the food leaves it). Radios for the kinds of food (not a select: arrow keys on a closed
  select would save every value passed).
- No menu on Treating a low rows or the swaps "for your next low" (note 09 §4.9). The sentence of §4.10 is shown once (Settings); the menu does
  not use the word allergy.
- Settings stay online-only: writes go through the plain API client, which the outbox never queues; offline the person gets the outbox's own
  refusal ("Your server cannot be reached, so this change was not saved…"), and the lists say "Guidance needs a connection to your server.".
- "Save as a meal": the usual meal's foods are rebuilt from the learned item's `key` and `GET /api/foods/{id}`, then the existing saved-meal editor
  opens as a NEW meal (`openMealEditor(null, trigger, draft)`); nothing is saved until Save meal.
- AI text: `KH.ai.preferencesField()` (ai.js) builds the field (same `PATCH /api/me/ai`, same 200 characters); Settings → AI ideas keeps one line
  with a link (`KH.guidance.openPreferences()`); absent in the demo and when AI is off.

## Commands that reproduce the checks

- `python3 -m pytest tests/test_guidance_ui.py tests/test_settings_ui.py tests/test_kidney_only.py -q -p no:cacheprovider`
- `node tests/js/run_vectors.mjs`
- `ruff check .`
- `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 tools/e2e/prefs.py` (once written)

## Notes for part C and the integrator

- Preferences Ask writes with `source = "ask"` show in the Settings lists as "added in Ask". After a card writes one, `KH.guidance.forgetAnswers()`
  is enough for the next What fits now load to be fresh; the "⋯" menu always reads the server when it opens; Settings re-reads on every visit.
- Part C owns `docs/ai.md` and `docs/assistant.md`; they still say the AI text is in Settings → AI ideas only where they mention it at all
  (`docs/ai.md` line "Your food preferences text" is a what-is-sent table and needs no change); the handbook's AI page says where the field is now.
- `tools/e2e/journey.py` expects the preference route for "Not for me" (changed); `tools/e2e/prefs.py` is new (port 8085).
- The worktree started without part A (see "Start-up facts").
