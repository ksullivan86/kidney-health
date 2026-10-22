Status: in progress (change 5 committed; change 7 written, final full pytest run under way)

# reuse-groundwork

Two behaviour-neutral changes from design note 14 §4 (decided in §6): **5** (kidney/T1D rules out of
`app/nutrients.py`) and **7** (name the safety set, `pytest -m safety`). Base: `7372537` (origin/main +
note 14), merged fast-forward.

## Change 5: rules_kidney.py (done)

* `app/nutrient_core.py` (new): `Nutrient`, `NUTRIENTS`, `NUTRIENT_KEYS`, `NUTRIENT_BY_KEY`, `MEALS`,
  `_INTEGER_UNITS`, `_half_up`, `round_value`, `_fmt`, `target_bounds`. Only what both other modules need.
* `app/rules_kidney.py` (new): `CKD_STAGES`, `DIALYSIS_MODES`, `DIABETES_TYPES`, `FLAGS`, `Threshold`,
  `THRESHOLDS`, `WARNING_ORDER`, `HIGH_GI_MIN_CARBS_G`, `_LEVEL_WORD`, `POTASSIUM_ADDITIVE_MESSAGE`,
  `POTASSIUM_NOTE` (re-export of the `target_rules` constant), `threshold_level`, `_carb_choices`,
  `_warning_message`, `food_warnings`, `kidney_rating`, `_carb_goals`, `_goal_word`, `carb_tolerance`,
  `_meal_carb_alert_items`, `_over_words`, `_hypo_words`, `meal_carb_alerts`, `projected_meal_carb_alerts`,
  `dosing_weight`, `suggest_targets`.
* `app/nutrients.py` keeps the generic part (totals, unknown counting, scaling, `status_level`,
  tolerance/`is_about`/`over_at`, `daily_status`, `build_alerts`, `build_projected_alerts`, `TARGET_KEYS`,
  `FOOD_SOURCES`) and re-exports every moved name from both new modules at the top.
* Why a third module: `rules_kidney` needs the registry/rounding from `nutrients`, and `nutrients` must
  re-export `rules_kidney`; with the rules importing from `nutrients` that is a cycle (importing
  `app.rules_kidney` first fails). The shared helpers (about 70 lines) went into `nutrient_core`
  instead of moving the whole generic core.
* Decisions: `FLAGS` moved (6 of its 10 values are kidney/T1D and `food_warnings` reads them; note 14 §1.1
  lists it as K). `TARGET_KEYS` (the two carb goal keys) stays: it is a key list used by profile
  validation, not a rule. `MEALS` and `FOOD_SOURCES` stay (generic).
* Wording-only updates to pointers that named where a moved name lives: ARCHITECTURE.md, README.md,
  CONTRIBUTING.md parity table, `docs/barcode-and-photos.md`, `docs/research/fact-check.md`,
  `handbook/README.md`, `handbook/REVIEW.md` (the pointers to THRESHOLDS, `food_warnings`, M2 targets),
  the handbook Pages workflow `paths:` (added `app/rules_kidney.py`), comments in the JS twins
  (`engine/rules.js`, `engine/targets.js`, `core.js`, `views/today.js`, `mock/core.js`), docstrings in
  `app/guidance/{topics,vectors}.py`, `app/{additives,units,targets}.py`, `app/mcp/tools.py`,
  `tools/e2e/parity.py`, `scripts/build_handbook.py`, test docstrings. Left alone on purpose: dated design
  notes and plans under `docs/dev/` (records of what was decided then), `app/migrations/m007_barcode.py`
  (released step; its `FOOD_SOURCES` pointer is still right), the `about` string inside
  `tests/data/rules_vectors.json` (vectors must not change), and the two historical lines of
  `handbook/REVIEW.md` that describe the v0.2 comparison.
* No monkeypatch of any `nutrients.*` name exists in `tests/`, `tools/` or `scripts/` (grep for
  `setattr`/`patch` with those names found none), so no test needed re-pointing.

Verified (from the repo root): AST check that every top-level definition of the old `nutrients.py` is
identical in exactly one of the three modules (56 definitions, 0 differences) and every old name still
resolves on `app.nutrients` (only stdlib helpers such as `Decimal` no longer do; nothing uses them);
each of `app.rules_kidney`, `app.nutrient_core`, `app.nutrients`, `app.targets` imports first on its own;
`ruff check .`; every `python tests/data/gen_*.py --check` exits 0 (vectors unchanged);
`node tests/js/run_vectors.mjs` passes.

## Change 7: pytest -m safety (written)

* `pyproject.toml`: `safety` marker registered under `[tool.pytest.ini_options] markers`.
* Module-level `pytestmark = pytest.mark.safety`: `tests/guidance/test_hypo.py`,
  `tests/guidance/test_food_safety.py`, `tests/test_ai_guard_twin.py`.
* Single tests marked in 30 more files (the list is in `tests/test_safety_set.py` `SAFETY_FILES`); the AI
  golden runner marks `safety-*`, `prefilter-*` and four named cases through `pytest.param(..., marks=...)`.
* `tests/test_safety_set.py`: collection-only subprocess (`--strict-markers`), asserts the set is not
  empty, every listed file keeps a marked test, and the golden runner still marks its `safety-` and
  `prefilter-` cases.
* `CONTRIBUTING.md` "Tests": the command and one paragraph. `CLAUDE.md` untouched (as asked).
* A mixed test's mark is a judgment call; the criterion was: its name or docstring states one of the
  rules (no dosing, a low is never blocked or warned against, quoted handbook text, AI guard and
  prefilter, health data never sent to AI).

## Commands

    python -m pytest -q
    python -m pytest -m safety
    node tests/js/run_vectors.mjs
    python tests/data/gen_rules_vectors.py --check    # and the other gen_*.py
    ruff check .
