# Progress: ROADMAP item 1, the other screens that save (Plan, Labs, Profile, weight and blood pressure)

Status: in progress (walks and fixes done; static tests and docs next)

Branch: worktree-agent-a4cedbd9f24537640. It started at main's d1ba260, so reliability-2 (499af10) was merged first (3094f21):
the task's starting point (slow day, failed entry save walks) lives there. The merge result is exactly reliability-2's tree.

## Done (verified with `timeout 900 python3 tools/e2e/reliability.py`: 53 passed with the fixes, 44 passed and 9 failed without)

New walks in `tools/e2e/reliability.py`: Plan saved-meal editor, Plan "Add to a day" sheet, Labs add a result, Labs slow list then
Today and back (old answer = stale list, then = 500), weight and blood pressure sheets, weight card slow day (late answer = the
real day-before answer, then = 500), Profile save targets. A failed save checks: sheet open, values kept, error on top (toast checked
with elementFromPoint), button enabled; the next try is counted (exactly one POST/PUT) and checked on the server.

Bugs found and fixed:

1. **Toast hidden under an open sheet** (`core.js toast`, `setupDialog`): sheets open with showModal (top layer, page inert), so
   every error toast during a sheet was under the sheet and not read out. Entry sheet, saved meal editor, Add to a day, weight, BP.
   Fix: the toast moves into the open modal dialog (`toastHost`), and back to body on the dialog's close.
2. **Labs drew an old answer** (`labs.js load/invalidate`): invalidate() kept `cache.loading`, so a new visit (or a save) reused
   the old in-flight request and drew its results or its error. Fix: a generation counter; an answer from before invalidate()
   is replaced by a new load for whoever waits on it.
3. **Weight card showed the other day's weights while a day loads** (`body.js loadToday`): "Loading…" until the day is drawn
   (`S.drawnDate`).

Behaved (walk kept as a guard): Profile save; Plan editor and Add to a day kept values, retry once; Labs save kept values; the
weight card ignored late answers (S.req).

## Next

* Static tests in `tests/test_reliability_ui.py` for the three fixes.
* Docs: tools/e2e/README.md row, reliability.py docstring, ROADMAP item 1, CHANGELOG Unreleased, ARCHITECTURE if it describes these.

## Reproduce

    timeout 900 python3 tools/e2e/reliability.py
    /root/.local/bin/ruff check tools/e2e/reliability.py
