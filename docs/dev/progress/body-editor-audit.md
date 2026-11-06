Status: complete

Branch `audit/body-editor-lifecycle`, main `cea3c94`. PR #162 ready for review; never merge it.

Confirmed: old weight/BP saves closed newer drafts or wrote their old validation errors into them. Submitted
fields stayed editable; refreshed page units could reinterpret the open weight's displayed pounds as kg.
Each sheet now tracks its opening and one outstanding write. Submitted fields freeze; Close/Cancel work;
new drafts stay editable while Save waits. Stale replies leave the draft intact. Successful writes refresh
the current day's data. Weight echoes/parsing use the unit captured at opening. A note-only edit preserves
the stored hundredth. Flag focus cannot move behind a new measurement sheet. No clinical rules or text,
ranges, routes, schema or dependencies changed. Architecture, guide, handbook and changelog updated.

Ten live-view/parser Node cases: clean main7fail3pass, fixed10pass. Initial focused suite123pass2fail: two
static assertions referred to retired S.units/S.busy. Updated the echo reference; live duplicate-write
coverage replaces source-string counting. The affected static/new tests then passed29/29. All30 direct
Node regression files, vectors, Ruff, OpenAPI, generated pages and strict handbook pass.

Full browser body.py:414passed,0failed across real accounts at phone/desktop, dialysis and demo. New cases
hold committed saves and refusals, preserve new drafts and confirm once-only writes. A real settings API
change while a pounds draft is open still saves69.99kg for154.3lb. Initial harness cleanup/expected422
console handling were corrected; final report is browser-verified/report.json. Focused browser36pass.

Complete CI run42223205700 at8df0599 is green: Python3.12/3.14/3.15, native iOS/Swift, handbook, lint and
image checks. Python3.12 job127910323286 reports7387passed,2skipped and2existing handbook citation warnings.
Concurrent local full suites later exhausted /tmp; isolated CI is the full-suite verification. New local
checks use /workspace/work/pytest-scratch. No PR or branch was merged. Logs: /workspace/work/body-editor-audit/.
