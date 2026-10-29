# Progress: ROADMAP item 1, the other screens that save (Plan, Labs, Profile, weight and blood pressure)

Status: in progress (merge, tests, proof and docs done; final test runs going)

Branch: worktree-agent-a4cedbd9f24537640. It started at main's d1ba260, so reliability-2 (499af10) was merged first (3094f21).
Then `claude/adoring-sagan-th5swr` (head of PR #119) was merged (8f6f265).

## Done

New walks in `tools/e2e/reliability.py`: Plan saved-meal editor, Plan "Add to a day" sheet, Labs add a result, Labs slow list then
Today and back (old answer = stale list, then = 500), weight and blood pressure sheets, weight card slow day (late answer = the
real day-before answer, then = 500), Profile save targets. A failed save checks: sheet open, values kept, error on top (toast checked
with elementFromPoint), button enabled; the next try is counted (exactly one POST/PUT) and checked on the server.

Bugs found and fixed:

1. **Toast hidden under an open sheet** (`core.js toast`, `setupDialog`): sheets open with showModal (top layer, page inert), so
   every error toast during a sheet was under the sheet and not read out. Fix: the toast moves into the open modal dialog
   (`toastHost`), and back to body on the dialog's close.
2. **Labs drew an old answer** (`labs.js load/invalidate`). This branch had its own fix; at the merge it was dropped for PR #119's
   (e5d7d74: generation counter in load, plus request counters in labs refresh and profile's lab summary).
3. **Weight card showed the other day's weights while a day loads** (`body.js loadToday`): "Loading…" until the day is drawn
   (`S.drawnDate`).

### The labs overlap (merge decision)

Kept PR #119's `labs.js` and `profile.js`. Kept both walks: "Lab cache" (PR #119) stubs `KH.api` in the page and holds a read
across `invalidate()`, checking the list, the redirected promise and the kidney-function text. "Labs, slow list" (this branch)
uses the real server and real navigation (Profile → Labs, Today, back), and checks both a late old list and a late error. Neither
covers the other: Lab cache has no error case and no navigation; Labs slow does not check the kidney-function card. Both fail on
the old labs.js (3 + 2 checks).

### Tests

* `tests/js/reliability_ui.test.mjs` (10 tests), run by `tests/test_reliability_ui.py::test_the_toast_and_the_weight_card_in_node`.
  It runs core.js's real toast section and `setupDialog` (sliced out by markers; the rest of core.js needs a full page) and the
  whole `views/body.js` with the engine files, on a fake page.
* The old static labs test was removed (it matched this branch's dropped code); `tests/test_lab_cache.py` covers it.

### Proof (old = 499af10's core.js, body.js, labs.js)

* `timeout 900 python3 tools/e2e/reliability.py`: new 56 passed, 0 failed. Old: 44 passed, 12 failed (toast on top: 5; Lab cache:
  3; Labs slow: 2; weight card while loading: 2).
* `node --test tests/js/reliability_ui.test.mjs`: new 10/10. Old core.js + body.js: 7 pass, 3 fail (toast in a sheet, toast in
  the top sheet, weight card while the day before loads). The pytest wrapper fails on the old files too.
* A Playwright "CancelledError" traceback prints at the end of the walk: routes held by the slow walks whose request the page
  had cancelled. Noise only; the result line and exit code are right.

### Docs

tools/e2e/README.md row, reliability.py docstring, docs/ROADMAP.md item 1, CHANGELOG Unreleased (two bullets),
ARCHITECTURE (weight card bullet and a new "A failed save on a sheet" section), handbook weight-and-blood-pressure.md (two lines).

## Next

* Final pytest on the touched and doc-reading test files; full pytest in the background if time allows.

## Reproduce

    timeout 900 python3 tools/e2e/reliability.py
    node --test tests/js/reliability_ui.test.mjs
    /root/.local/bin/ruff check tools/e2e/reliability.py tests/test_reliability_ui.py
    # old code: git show 499af10:app/static/js/core.js > app/static/js/core.js (same for views/body.js, views/labs.js), run, restore
