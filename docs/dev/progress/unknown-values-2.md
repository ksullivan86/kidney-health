# Progress: unknown values in swaps and the fit sheet (ROADMAP item 2, second part)

Status: in progress

Branch `worktree-agent-aec7bcc7cd9e8f4d1` (local only, never pushed). Continues the WIP commits cbf83f0 and a66660f.

## Done
* Merged `claude/adoring-sagan-th5swr` (PR 119 head); conflicts in ARCHITECTURE.md, docs/accounts.md, handbook
  settings-and-keys.md and tools/e2e/reliability.py were only additions from that branch, taken as they are (f62c30c).

## Next
* Old-vs-new test runs; docs (ARCHITECTURE, docs/guidance.md, handbook, CHANGELOG, ROADMAP); full pytest.
* Checked the WIP code: swaps (null deltas, "not listed" texts), the fit sheet (rows "≥"/"not listed", grey row, carbs line)
  and the recipe change lines ("at least"). All WIP tests pass.
* Added: `fit_text` (What fits now) says "carbs not listed" instead of "0 g carbs" (server + twin; not reachable today
  because What fits leaves out a food with unknown carbs when carbs are counted, so a vector case shows that instead).
* Added: low treatment rows on the guidance sheet show "potassium not listed" (keyNumbers keeps a key that is in `unknown`;
  lowOption passes `notListedIn(o.nutrients)`). Before, the missing value was silently left out.
* Fixed: the fit sheet note said "do not list k, p" (chip letters); now "potassium and phosphorus".
* Tests: twin-vs-server text check in tests/test_unknown_swaps_fit_ui.py (node), low-option and note checks there,
  `fit_text` in tests/guidance/test_messages.py, API test in tests/guidance/test_api_guidance.py
  (`test_low_treatments_and_the_fit_sheet_say_which_values_a_food_does_not_list`). OpenAPI unchanged (`--check` ok;
  `SwapIdea.deltas` already allowed null).

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY tests/data/gen_guidance_vectors.py --check; node tests/js/run_vectors.mjs
$PY -m pytest -q tests/test_unknown_swaps_fit_ui.py tests/guidance/ tests/test_unknown_totals_ui.py tests/test_guidance_ui.py
