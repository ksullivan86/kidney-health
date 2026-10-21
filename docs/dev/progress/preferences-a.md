Status: complete

# Learn my food preferences, part A (server and engine)

Role: `preferences-a`. Worktree branch `worktree-agent-ace517398703420cb`, started at `2fd1cee`.
Spec: `docs/dev/research/09-food-preferences.md` (§4.1-§4.6, §4.9-§4.12, §6, §8). Parts B (screens) and C (AI, Ask) are
NOT built here. Never push, never open a PR; the integrator does.

## Plan / state

- [x] 1 schema step 17 (`m017_food_preference_source.py`), `tests/test_migration_m017.py` (5 tests pass), ARCHITECTURE migration row
- [x] 2 `GuidancePreferences` fields + model validator (`Value error, ...`), `engine/settings.js` (`check` hook), settings vectors regenerated with guidance cases
- [x] 3 engine (Python): `state.py` (Prefs, PlannedEntry, planned30/eaten30), `rules.py` (PREF_*, SKIP_*, LEARNED_MAX, `usual_meal_key`,
      RULES_VERSION 2026-10-21.1), `score.py` (PrefTerms, skip_stats, pref_terms, HabitStats gating, Scorer.pref, score_meal pref),
      `fits.py` (you_like, familiar_excluded, usual_meal_entries + key, learned), `swaps.py` (swap term, hypo floor), `planner.py`,
      `messages.py`, `ai_bridge.py` (you_like kept out of `reasons`, `liked` bit)
- [x] 4 context loader (`context.py`: food_preferences, load_planned, eaten30, `explicit_preferences`)
- [x] 5a routes + models (`/preferences` GET/PUT/DELETE, `/learned`, aliases rewritten on the same helper)
- [x] 5b Python tests: `tests/guidance/test_preferences.py` (engine P1-P7, TV-PREF-1/2, skipped-food rule, hypo floor, familiar meals),
      `tests/guidance/test_preferences_api.py` (routes, limits, aliases, validation), isolation matrix in `tests/test_isolation_v03.py`
- [x] 6 export / import / zip README / import vectors (`app/account.py`, `app/data_import.py`, `gen_import_vectors.py`, `mock/import.js`)
- [x] 7 JS twin (`rules.js`, `messages.js`, `score.js`, `fits.js`, `swaps.js`, `planner.js`, `hypo.js` entry `learned`), `run_vectors.mjs`,
      `gen_guidance_vectors.py` (+43 PREF cases, 107 cases total); Python and JS agree on every case. P1 verified by
      a scratch diff of old vs new vector outputs (equal except rules_version and the explain `preference` component).
- [x] 8 demo (`mock/guidance.js`, `mock/export.js`, `mock/import.js`); a scratch replay of 72 requests gave the same answers on
      the server and in the demo; `tools/e2e/parity.py` section 12g2 added (needs Chromium, not run here)
- [x] 9 docs: ARCHITECTURE, `docs/guidance.md` (+ `scripts/guidance_rules_doc.py`), `docs/privacy.md`, `docs/demo.md`, handbook
      guidance and privacy pages, CHANGELOG Unreleased, note 09 (§4.4 refined rule, §7 built notes, §8 Q1/Q4/Q5)
- [x] perf: `tests/guidance/test_perf_guidance.py` passes; `scripts/bench_guidance.py --runs 3` (see below)
- [x] 10 final runs: full `python -m pytest -q` 4,724 tests passed, 0 failed, 0 skipped (exit 0, no network); `node tests/js/run_vectors.mjs`
      all suites pass (guidance 109 checks over 107 cases, settings 615, import 254); the three generators and
      `scripts/guidance_rules_doc.py` `--check` are up to date; `ruff check .` clean; `node --check` on all 13 changed JS files

## Decisions and why

- Planned-but-not-eaten uses the owner's refined rule, not the note's first draft: a food is skipped on a date when an entry is
  still `planned` on a past date of `[today-30, today-1]` and that date+meal has at least one `eaten` non-hypo entry of another
  food; learned `-0.5` when skipped on at least 2 dates and eaten (any meal, not hypo) on fewer than half the dates it was planned.
  No person-level condition. Pure engine (`score.skip_stats`, JS `skipStats`) from `ctx.planned30` plus eaten rows (`eaten30` only
  when `history60` is not loaded).
- Invalid values and bodies return 400 like the whole settings API (the note says 422); a group in two lists is 400 too.
- Not-for-me limit is checked before the total limit; messages `the "Not for me" list is full (500 foods); remove one first` and
  `your food preferences are full (1000 foods); remove one first`.
- `you_like` is the last reason (spec order) and the card shows at most two, so it shows mainly when no kidney reason competes.
- AI bridge: `you_like` leaves the candidates' `reasons` and travels as a `liked` bit; `app/ai/**` is untouched and does not read it.
- Low-treatment options, card and swaps never read a like, a "less often" or a learned signal. `hypo_options` shows the whole list
  with the note `shown_despite_exclusions` when exclusions would empty it. `best_hypo_food` is unchanged (it has no exclusion floor).
- Notes in guidance answers stay plain strings (the code is the key into `messages.NOTE_TEXTS`), so `views/guidance.js` is unchanged.
- `GET /preferences` and `GET /learned` are not gated by `guidance.enabled` (they are the person's own data).
- The planner's pool pre-rank includes the preference term (not in the note) so a liked food can reach the plan.
- Hypo-mode swaps use `habit_stats(soft=False)`: no taste term in a low.
- `explicit_preferences(conn, user_id, store=None)` is the helper part C reads.
- Demo mock keeps a lazy `_foodPrefs` Map and migrates a legacy `_notForMe`; its validation messages equal the server's.
- `views/settings.js` only changed the import-report labels ("food preference(s)"); the settings form keeps the new fields on save.

## Performance (2,000 foods, x86, Python 3.11)

- `python -m pytest tests/guidance/test_perf_guidance.py -q`: 6 passed.
- `python3 scripts/bench_guidance.py --runs 3`: at 395 foods engine-only next-meal 8.1 ms, swaps 1.1 ms, plan-day 21.2 ms,
  insights/day 0.06 ms (p50); at 1,975 foods request p50/p95: next-meal 35.4/44.1, swaps 9.3/9.9, plan-day 47.9/52.3,
  insights/day 3.2/3.7, hypo-options 4.2/4.2 ms; engine-only next-meal 36.8, plan-day 51.2 (this 3-run sample is noisy).
- Same machine, base commit `2fd1cee` against this branch, 25 runs, engine-only p50 (two repeats each): next-meal 25.0/23.5 base,
  22.0/22.8 now; plan-day 30.7/31.2 base, 29.1/31.8 now. No measurable change for a person without preferences. The x86 CI
  budgets (25/5/40 ms) are already marginal at 2,000 foods on this machine before the change (p95 flips between ok and OVER).
- A person with 300 food preferences, 150 "Not for me" foods, 5 food-group choices and 80 planned entries (scratch run, 25 runs,
  p50 ms): next-meal 22.7 vs 20.5 without, swaps 3.15 vs 2.67, plan-day 33.5 vs 31.6.

## Commands that reproduce the checks

- `python3 -m pytest tests/guidance -q -p no:cacheprovider` (about 1 minute)
- `python -m pytest -q` (full, about 10+ minutes)
- `node tests/js/run_vectors.mjs`
- `python3 tests/data/gen_guidance_vectors.py --check`, `gen_settings_vectors.py --check`, `gen_import_vectors.py --check`
- `python3 scripts/guidance_rules_doc.py --check`
- `ruff check .`
- `python3 scripts/bench_guidance.py --runs 3`
