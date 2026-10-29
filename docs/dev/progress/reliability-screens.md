# Progress: ROADMAP item 1, the other screens that save (Plan, Labs, Profile, weight and blood pressure)

Status: in progress (all work done and committed; the last full pytest run is going)

Branch: worktree-agent-a4cedbd9f24537640 (local only, never pushed). It started at main's d1ba260, so reliability-2 (499af10)
was merged first (3094f21). Then `claude/adoring-sagan-th5swr` (head of PR #119) was merged (8f6f265), and two commits from
the owner's other assistant were cherry-picked: 444d204 → 1d657e5 (weight card while a day loads) and e925af5 → 52d8fc2
(Profile suggested targets while loading).

## Done

New walks in `tools/e2e/reliability.py`: Plan saved-meal editor, Plan "Add to a day" sheet, Labs add a result, Labs slow list then
Today and back (old answer = stale list, then = 500), weight and blood pressure sheets, weight card slow day (late answer = the
real day-before answer, then = 500), Profile save targets. A failed save checks: sheet open, values kept, error on top (toast checked
with elementFromPoint), button enabled; the next try is counted (exactly one POST/PUT) and checked on the server.

Bugs found and fixed:

1. **Toast hidden under an open sheet** (`core.js toast`, `setupDialog`), this branch's fix: sheets open with showModal (top
   layer, page inert), so every error toast during a sheet was under the sheet and not read out. The toast moves into the open
   modal dialog (`toastHost`), and back to body on the dialog's close.
2. **Labs drew an old answer** (`labs.js load/invalidate`): PR #119's fix (e5d7d74) kept; this branch's own was dropped.
3. **Weight card showed the other day's weights while a day loads** (`body.js loadToday`): the other assistant's fix (1d657e5)
   kept; this branch's `S.drawnDate` version was dropped (0c5ec30).

### Overlap decisions

* **Labs.** Kept PR #119's `labs.js` and `profile.js`. Kept both walks: "Lab cache" (PR #119) stubs `KH.api` in the page and
  holds a read across `invalidate()`, checking the list, the redirected promise and the kidney-function text. "Labs, slow list"
  (this branch) uses the real server and real navigation (Profile → Labs, Today, back), and checks a late old list and a late
  error. Neither covers the other. Both fail on the old labs.js (3 + 2 checks).
* **Weight card.** Theirs is more correct: it also clears `S.summary` (old alarm and goal lines), and a handled failure (a 401)
  now shows Try again. In this branch's version a handled failure left "Loading…" on the card for good. Their
  `tests/js/body_day_loading.test.mjs`: old body.js 2 pass / 5 fail; this branch's body.js 3 / 4; theirs 7 / 0. This
  branch's Node weight-card tests were removed (their tests cover the same; one of mine asserted no "Loading" on a same-day
  reload, which their design does on purpose). The reliability.py weight walks pass with theirs.
* **Profile suggestions.** A different bug from anything here (late suggested targets replacing entries), so no fix of mine to
  drop. Their `tests/js/profile_suggestion_context.test.mjs`: old profile.js 2 / 6, theirs 8 / 0. Their
  `tools/e2e/profile_reliability.py` (8 checks) and this branch's Profile walk both check a failed save and retry; both kept.

### Tests

* `tests/js/reliability_ui.test.mjs` (5 toast tests), run by `tests/test_reliability_ui.py::test_a_toast_is_shown_inside_an_open_sheet`.
  It runs core.js's real toast section and `setupDialog`, sliced out by markers (the rest of core.js needs a full page).
* The old static labs test was removed; `tests/test_lab_cache.py` covers it.

### Proof (old = 499af10's core.js, body.js, labs.js)

* `timeout 900 python3 tools/e2e/reliability.py` (about 30 s): now 56 passed, 0 failed. Old: 44 passed, 12 failed (toast on top: 5;
  Lab cache: 3; Labs slow: 2; weight card while loading: 2).
* `node --test tests/js/reliability_ui.test.mjs` with old core.js: the two "toast inside the sheet" tests fail.
* After the cherry-picks: all 67 Node `*.test.mjs` pass; reliability.py 56/0; profile_reliability.py 8/0; body.py 366/0.
* Full pytest before the cherry-picks (commit 387b59f + README timing): exit 0.
* A Playwright "CancelledError" traceback prints at the end of reliability.py: routes held by the slow walks whose request the
  page had cancelled. Noise only; the result line and exit code are right.

### Docs

tools/e2e/README.md row, reliability.py docstring, docs/ROADMAP.md item 1, CHANGELOG Unreleased (error over sheets, weight
card, suggested targets), ARCHITECTURE "A failed save on a sheet" section, handbook weight-and-blood-pressure.md (a failed save).

## Next

* Full pytest on the final tree (running; output in the scratchpad's full_pytest2.txt).

## Reproduce

    timeout 900 python3 tools/e2e/reliability.py
    node --test tests/js/reliability_ui.test.mjs tests/js/body_day_loading.test.mjs tests/js/profile_suggestion_context.test.mjs
    /root/.local/bin/ruff check tools/e2e/reliability.py tests/test_reliability_ui.py
    # old code: git show 499af10:app/static/js/core.js > app/static/js/core.js (same for views/body.js, views/labs.js), run, restore
