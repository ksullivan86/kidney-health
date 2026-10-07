# fixer-frontend-docs progress

Status: in progress (started 2026-10-07)

Role: v0.3.0 review fixer for app/static, tools/e2e, tests/js, scripts/build_preview.py, handbook/, docs/,
README/CHANGELOG/CONTRIBUTING/AGENTS and the GitHub templates. Ports 8620-8639. Scratch:
`/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/fixer-frontend-docs/`.
Another fixer works on the backend half at the same time: commit only my paths, re-read shared files
before editing them.

## Findings

CONFIRMED (fix with root cause and a test):

| id | finding | status |
|---|---|---|
| C1 | unknown K/P counted as 0 (today.js:147 and every total) | done |
| C2 | handbook light-scheme links/header fail WCAG AA | done |
| C3 | Settings → This device renders twice on first visit | done |
| C4 | DG47 dead citation on 13 handbook pages | done |
| C5 | guidance never shows which targets it used / when saved | done |

LOW (apply or justify):

| id | finding | status |
|---|---|---|
| L1 | research notes still state pre-v0.3 protein rule | pending |
| L2 | handbook SI phosphate table edges | pending |
| L3 | labs.js K alert window hard-coded 90 days | pending |
| L4 | AI activity shows raw provider reply uncaptioned | pending |
| L5 | Settings → AI ideas stale after admin switch | done |
| L6 | ai.* switches under "Other" | done |
| L7 | Trends ignores goal / about targets | done (with C1, d458205) |
| L8 | "about X" protein treated as hard max in plan | pending |
| L9 | GET /api/foods/builtin ETag deferred without spec | pending |
| L10 | guidance AI buttons: no What will be sent? / dropped | pending |
| L11 | carbs_per_snack_g has no UI | pending |
| L12 | iOS install tip after third visit | pending |
| L13 | demo runs with lab rules on (note 05 C10) | done |
| L14 | disabled Units placeholder promising a later version | done |
| L15 | "Prefer live camera" setting missing | pending |
| L16 | PEMAT self-score not recorded | pending |

## Done

* **Handoff from fixer-backend-ops (C7 UI, task #151)**: a product with only prepared values is logged in
  servings. `KH.off.weightKnown` (engine/off.js; twin of `foods.weight_known`, same codes and refusal text);
  the demo's POST/batch/PUT/copy-day/swaps refuse or drop grams like the server; the entry sheet hides Grams
  and says why under the servings. Verified: `tests/test_demo_servings_only.py` (4 tests, through the new general
  Node runner `tests/js/demo_api.mjs`, which replays requests against `MockApi`), `tools/e2e/device.py --only demo`
  13/13 (Kraft 0021000658831: no grams field, logged `[[1, None]]`), barcode vectors 2034. Docs:
  `docs/barcode-and-photos.md` "How the numbers are read" (the mapping rules the backend changed), handbook
  app/barcode-and-photo.md, ARCHITECTURE barcode Frontend bullet. Left uncommitted: the egg/C11 edits in
  mock/foods.js, parity.py, menus and vectors are fixer-backend-ops' work in progress.

* **L7** (Trends goal/about targets): done with C1 in d458205 (`targetKind` goal/about/range/limit; the goal
  line on the chart; fibre/protein minimums are goals, "about" is not a limit).

* **C3** (settings.js `renderDevice`, offline.js `renderDevice`): each render builds into a detached fragment;
  only the newest (ticket) replaces `#set-device-body` after its last await; the outbox list's `draw()` builds
  its parts and `replaceChildren`s (ticket too), and `renderDevice(container)` now returns a stop function
  that Settings calls when a newer render replaces the list. Verified: `tools/e2e/device.py --only firstvisit`
  (new section: three fresh profiles at `/#settings` with the service worker allowed) fails 6/9 on HEAD's code
  (copy via `git archive`) with exactly the review's symptoms and passes 9/9 after; `outbox` and `demo`
  sections still pass (36/36). Static guard: `tests/test_device_ui.py::test_settings_device_section_is_drawn_once_when_renders_overlap`.

* **C2** (`handbook/docs/stylesheets/extra.css`): teal primary → teal 800 `#00695c` (white on it and it on
  white 6.61:1; the header in both schemes and light links), light accent `#004d40` (hover/focus 9.8:1),
  inactive tabs 85 % opacity (5.2:1) with the current tab underlined, the phone drawer's section title at full
  foreground colour (was 4.4:1 light / 4.1:1 dark). The probe found more than the review: tabs 2.59:1 and the
  drawer title. `tools/e2e/learn.py` now measures every visible text run (colour alpha, opacity, stacked
  backgrounds; waits for transitions to end) on 5 pages in both schemes: 60/60 pass on a build with
  `HANDBOOK_APP_LINK=/` (the image's flags). Before the CSS the same probe found 6 failing groups per page.

* **C4** DG47 removed from `handbook/sources.yml`; the 600 mg per-meal line now cites `SAT-labels` (new:
  Satellite Healthcare food-label guide, sodium "less than 600 mg per meal and less than 200 mg for a snack")
  and `AKF-meal` (potassium "600-700mg ... per meal"), both fetched and quoted 2026-10-07, both `dg: [47]`.
  Edited `data/recipes.yml` (generator input), `eat/recipes/index.md`, the RECIPE_LIMITS comment; regenerated
  with `python scripts/build_handbook.py --write` (`--check` clean). REVIEW.md eat/ finding 36. Tests:
  `test_retired_sources_stay_retired` (no page, data file or link include may cite DG47) and
  `test_recipe_review_lines_cite_the_sources_that_state_them`. Strict build OK; `handbook/tools/check_links.py`
  0 broken of 14,636; `tests/test_learn_links.py` against the built site passes.

* **C5** `js/views/guidance.js` `targetsUsed()`: under What fits now's room line and in the plan sheet, "Using
  the targets in your profile, saved <date, time>: potassium … · carbs per meal … . Check them in Profile"
  from the answer's own `targets` block (`values`, `profile_updated_at`); {min,max} with min = max → "about X".
  Tests: `tests/test_guidance_ui.py::test_answers_show_which_targets_they_used_and_when_saved` (keys ⊆ the
  server's TARGET_KEYS_SHOWN, demo twin mirrors them), `tools/e2e/journey.py` step 4 (both places, the
  profile's potassium value, the Profile link): 125/125. Docs: docs/guidance.md, handbook app/guidance.md,
  ARCHITECTURE guidance Frontend bullets (only my hunks staged with `git apply --cached`).

* **L5/L6** settings.js: GROUPS gains "Optional AI" (ai.enabled first); an `ai.*` save calls `KH.ai.forget()`,
  `KH.ai.renderSettings()`, `KH.ai.renderAddSlot()`; ai.js `renderSettings` builds its parts and only the newest
  render replaces the slot. Tests: `test_every_server_setting_has_a_named_group` (every admin-editable registry
  key grouped), `test_an_ai_switch_change_refreshes_the_ai_panel_and_buttons`; journey step 1 no longer reloads
  after switching AI on and checks the panel updated in place.
* **L13** `js/mock/settings.js` starts with instance value `targets.lab_rules_enabled: false` (the registry key
  has no env var, so not an env lock; the demo admin may switch it on); Labs' review note says so in the demo.
  parity.py section 11 compares the shipped values (server on, demo off) then resets both to the default:
  691/691. Test: `tests/test_targets_ui.py::test_the_demo_ships_with_lab_rules_off` (runs the mock in Node).
* **L14** removed the disabled Units select (no spec defers lb/oz); contract line now "units for lab results";
  `test_the_ui_promises_no_unbuilt_feature`.

* **C1 (UI + demo twin)** server shape by fixer-backend-ops (1216f15). Twin: `KH.rules.countUnknown/mergeUnknown/
  markUnknown`; `js/mock/log.js` day figures, range, summary (`_eatenDayUnknown`, `unknown_entries/days`,
  interdialytic). UI helpers in core.js (`unknownOf`, `notListed`, `foodsNotListing`, `atLeast(Words)`, level
  `unknown` = "Not complete", grey icon). Today (bars, goal bar, meal head carbs, meal lines, entry rows,
  all totals, 7-day strip, since-dialysis), Plan chips, Trends (days, table, averages, period card, dashed
  bar edge), entry impact. Tests: `tests/test_unknown_values_twin.py` (Python day_figures / summarize_period /
  interdialytic vs the twin through Node, `tests/js/demo_log_twin.mjs`), parity.py section 5 adds an eaten
  no-K/P quick add, journey step 4 checks Today/Trends after the Nutella scan (130/130). Handbook logging.md,
  targets-and-warnings.md; contract paragraph under "Foods and log changes".

* **C1 (guidance room text)** smallest change outside my area, in `app/guidance/` (budget.py DayTotals.unknown +
  meal_carbs_unknown, NutrientRoom/CarbRoom.unknown; fits.room_json "unknown"; messages.room_line "at most …"
  + "Some foods logged today do not list X, so there may be less room"; guidance/models.py) and the twin
  (budget.js, fits.js, messages.js). Two new vector cases in tests/data/gen_guidance_vectors.py (54 checks);
  tests/guidance/test_fits.py pinned shapes gain `unknown: 0` + `test_room_with_values_not_listed_is_an_upper_bound`.
  Docs: docs/guidance.md, handbook app/guidance.md, contract NutrientRoom/carbs shape.

## Coordination

* The backend fixer (`fixer-backend-ops`) owns the server half of C1 (their C8: unknown K/P counted as 0 in
  `app/log.py`; their C6: insights). I build the UI on the shape they add to DaySummary / range / summary and
  update the mock twin (`js/mock/log.js`) to match. If their shape is not there when I reach C1, I add the
  smallest server change myself and say so here.
* Their contract text (uncommitted in ARCHITECTURE.md "Foods and log changes" when I looked): DaySummary gains
  `unknown`, `planned_unknown`, `projected_unknown`, `meal_unknown`, `planned_meal_unknown` ({nutrient: n});
  status items `unknown: n`; range days the three maps; PeriodSummary nutrients `unknown_entries`,
  `unknown_days`; interdialytic `unknown_entries`; UI "+ n not listed"; the demo twin returns the same.

* (2026-10-07, for fixer-backend-ops) C1's guidance room text ("Left for dinner: 1,050 mg potassium" built on
  totals that skip unknowns) is not in your handoff list, so I will take it: `unknown` per room key on
  `budget.DayTotals` / `NutrientRoom` and a room_text suffix, in `app/guidance/budget.py` + `messages.py` + the twin +
  regenerated guidance vectors. Your C6 (insights) may add unknown counts to `budget.day_totals` too: if you do it
  first, say so under your Handoffs and I will build on yours instead of adding a second count.

## Next steps

Work order: C3, C2, C4, C5, C1 (largest), then the LOW list, then final checks.

## Commands

* `python -m pytest -q` ; `node tests/js/run_vectors.mjs`
* handbook: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/venv/bin/mkdocs build --strict -f handbook/mkdocs.yml -d <scratch>/site`
