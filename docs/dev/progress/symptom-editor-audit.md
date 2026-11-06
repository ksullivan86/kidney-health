Status: complete

Branch audit/symptom-editor-lifecycle, main cea3c94. PR #165 ready for review; do not merge.

Confirmed late symptom success/400/500 replies changed a reopened draft. Five live-handler/real-rule cases:
clean main fails 4 and passes 1; fixed 5 pass. Each opening owns its save and errors. Submitted fields
freeze, Close/Cancel work, reopened drafts stay editable while Save waits for the earlier request, and
stale success refreshes the current day's entries while preserving the draft. Current refusals keep the
submitted values. No symptom/severity rules, clinical numbers, handbook flags or text changed. Architecture,
symptom guide, handbook, changelog and browser-walk documentation updated.

Focused Python/static/new regressions: 65 passed. Complete Chromium walk: 87 passed at phone/desktop plus
demo, including held committed saves, intact newer drafts, once-only server writes, handbook red flags and
layout checks. Ruff, OpenAPI, generated pages, Node parity and strict handbook pass.

Complete CI run 42225683694 for functional commit 550e16a is green: Python 3.12/3.14/3.15, native iOS/Swift,
handbook, lint and image checks. Python 3.12 job 127918452767 reports 7387 passed, 2 skipped and the two
existing handbook citation warnings. Concurrent local full suites exhausted /tmp; isolated CI verifies
the full suite. Completed failed-run artifacts were removed; new tests use /workspace/work/pytest-scratch.
No PR or branch was merged. Logs: /workspace/work/symptom-editor-audit/.
