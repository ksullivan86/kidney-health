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
| L1 | research notes still state pre-v0.3 protein rule | done |
| L2 | handbook SI phosphate table edges | done |
| L3 | labs.js K alert window hard-coded 90 days | done |
| L4 | AI activity shows raw provider reply uncaptioned | done |
| L5 | Settings → AI ideas stale after admin switch | done |
| L6 | ai.* switches under "Other" | done |
| L7 | Trends ignores goal / about targets | done (with C1, d458205) |
| L8 | "about X" protein treated as hard max in plan | partly done: wording; tolerance = clinical decision (REVIEW.md) |
| L9 | GET /api/foods/builtin ETag deferred without spec | pending |
| L10 | guidance AI buttons: no What will be sent? / dropped | done |
| L11 | carbs_per_snack_g has no UI | done |
| L12 | iOS install tip after third visit | pending |
| L13 | demo runs with lab rules on (note 05 C10) | done |
| L14 | disabled Units placeholder promising a later version | done |
| L15 | "Prefer live camera" setting missing | pending |
| L16 | PEMAT self-score not recorded | pending |

## Done

* **L11** (snack carbohydrate goal): Profile field `tg-carbs_per_snack_g` (data-target, hint) next to the per-meal
  one; a suggestion fills only the targets it gives (`fillTargets(…, { onlyGiven: true })`), so it never blanks
  the snack goal; Today's snack line and the entry sheet's impact use it; the server's meal carbohydrate alerts
  use it for the snack ("over the snack goal": app/nutrients.py `_carb_goals`, app/log.py; twin rules.js
  `mealCarbAlerts(…, snackTarget)`, mock/log.js). The plan sheet already showed it in the C5 targets line and the
  room text. Tests: test_nutrients.py (snack goal alone, with per-meal, projected), test_unknown_values_twin.py
  (PROFILE carries carbs_per_snack_g 15: the snack alert compared Python vs JS), test_targets_ui.py (static);
  parity.py section 9 "snack carb goal" variant; journey.py: saved, survives a suggestion, Today "of 20 g"
  (133/133). Docs: handbook app/guidance.md (+DG7), first-setup.md, docs/guidance.md, ARCHITECTURE Today.
  Parity full run also caught two of my own regressions, fixed: section 3 compared suggestions while the demo
  ships lab rules off (L13) → `lab_rules_at_default` runs before section 3; the demo's plan-day status model
  lacked `unknown` (C1) → mock/guidance.js `statusModel`. Full parity 6527/6527.

* **L8** (about-protein "Over limit"): reproduced on the server engine: `suggest_targets(70, "4")` → protein
  56–56, plan-day ends at 56.7 g via the ½-serving protein top-up with a new "101 % of today's maximum" alert.
  With min = max and ½-serving steps the planner cannot land exactly, so the only real fix is a tolerance for
  "about" targets, which is a clinical number no cited guideline gives (CLAUDE.md: every number cited). Done:
  "about" targets never read "limit": `KH.ui.ABOUT_LEVEL_TEXT` ("Near target" / "Above target") on Today's
  bar, the plan sheet's "The day with this plan" and the Plan week chips; level and colour stay the server's.
  Recorded as an open clinical decision in handbook/REVIEW.md ("Food targets"); handbook targets-and-warnings
  says it. Test: test_targets_ui.py `test_an_about_target_is_never_called_a_limit`.

* **L10** (guidance AI buttons): guidance.js `aiSentButton(body)` (dry run → `KH.ai.showSent`) beside "AI order"
  and "Ask AI to pick"; the plan's "What will be sent?" is a link above the plan (`#g-plan-ai-sent`; the foot
  keeps three buttons at 375 px); `aiDropped` shows `KH.ai.droppedNotes` (factored out of ai.js `answerHead`,
  same wording) after each answer. CSS `.g-ai-buttons`, `.g-ai-plan-note`. Tests: test_guidance_ui.py static
  check; device.py ai: the fake answers rerank with a ref the rules never offered; "What will be sent?" shows
  the rerank request to 127.0.0.1:<port>, and "1 AI pick was left out … a food the rules had not offered":
  24/24. Docs: handbook app/guidance.md, ARCHITECTURE Optional AI bullet.

* **L4** (raw AI answer in AI activity): new `js/engine/aiguard.js` (KH.aiguard: `fold`, `blocked`,
  `maskForDisplay`; pattern and look-alike table verbatim from app/ai/guard.py), loaded after textclean.js
  (index.html, sw.js SHELL_URLS). ai.js `activityRow`: heading "What came back (before the app's checks)", a
  caption (unchecked, used only what passed, words read [hidden], not advice, export keeps the full text), the
  masked copy. No server change (app/ai/routes.py is fixer-backend-ops' in-progress file; the stored row and
  export stay intact as the finding asks). Tests: tests/test_ai_guard_twin.py via tests/js/aiguard_twin.mjs
  (pattern/table equal; same `blocked` answers on the guard's 84 terms, obfuscations and food names; the
  review's example masked, readable, nothing left the guard would stop; static ai.js check). device.py ai: the
  fake now prefixes "Sure! Take 6 units of insulin before this meal." to next-meal answers (the review's
  repro): cards stay clean, activity shows "Sure! Take 6 [hidden] of [hidden] …" with the caption: 22/22.
  Docs: docs/ai.md, handbook app/ai.md, ARCHITECTURE (file layout, Settings AI bullet).

* **L3** (potassium banner window): the server decides. `GET /api/labs` now returns `alerts` (app/labs.py
  `current_alerts`: newest potassium, `fresh_labs` with `profile.target_settings` windows, `potassium_alert`;
  whatever the filters); `LabList.alerts` in app/models.py. Outside my area, minimal: those two backend files
  (+ tests/test_targets_api.py). Twin `_labAlerts` in js/mock/labs.js; views/labs.js `currentAlert(data)` reads
  `data.alerts` (ALERT_DAYS constant gone), profile.js the same. Tests: test_targets_api.py (4 windows × 3
  filter sets equal to the suggestion's alerts; newest only; two people), tests/test_demo_labs_alert.py (demo
  through demo_api.mjs under the same 4 windows; static check), parity.py 11c compares GET /api/labs after
  each admin settings change: section 11 695/695. Docs: docs/targets-and-labs.md, ARCHITECTURE (route table,
  Lab results bullet).

* **L1** (research notes): `docs/research/ckd-diet.md`, `food-lists.md`, `t1d-and-ckd.md` and `fact-check.md`
  carry a dated "Superseded in part by design note 05" banner; the protein rows say 0.8 g/kg with diabetes
  (KDOQI 3.0.2's 0.6 only under close supervision), the KDOQI numbers are the published ones (3.0.1–3.0.4
  protein, 3.1.1 energy), "ideal body weight"/IBW became body weight / reference weight. While there, the two
  safety errors handbook/REVIEW.md listed for food-lists.md are fixed (a 20-oz soda is labelled as one serving;
  juice or regular soda treats a low when it is all there is). handbook/REVIEW.md open items struck through
  with what was done. Test: `tests/test_research_notes.py` (banner present; old wording absent outside the
  banner; the patterns catch the review's quoted rows; REVIEW item closed).

* **L2** (handbook SI phosphate table): International tab now 0.79 or below / 0.80–1.46 / 1.47 or above, with
  a sentence on converting then rounding to one decimal. Test computes the edges from `app.units` and
  `app.target_rules` (`tests/test_handbook_content.py::test_si_phosphate_table_gives_the_edges_the_app_uses`).

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

* 2026-10-07: `tests/test_food_db.py::test_ingredients_are_flagged_so_meal_guidance_never_suggests_them_alone` fails
  since 058894c (raw whole egg became an ingredient); fixer-backend-ops' file, left to them.

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
