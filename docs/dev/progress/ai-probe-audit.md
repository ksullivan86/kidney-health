Status: complete

Branch audit/ai-probe-settings-lifecycle, main cea3c94. PR #164 ready for review; do not merge.

Confirmed: manual AI probes saved results to an edited provider without checking its tested settings.
Daily probes compared address/main model only, missing changed keys and vision models. Shared-provider
deletion during a manual test caused a server error. Sixteen real-route/background cases: clean main
10 failed, 6 passed; fixed 16 passed. The positive daily/manual interleave allows a changed test receipt
when settings stay unchanged. Concurrent manual probes for one person are correctly gated with 429.

Compare the provider row except probe receipts under BEGIN IMMEDIATE before saving the result. A stale
manual result returns 409 asking to test again; a daily result is discarded. No network call holds that
lock. The final admin view also uses the existing not-found guard. Current-provider request usage still
counts normally. No id allocation changes: provider ids already use AUTOINCREMENT. Architecture, guide,
handbook and changelog updated. No clinical rules, response payload fields, schema or dependencies changed.

Focused AI route/routing/cloud suite: 188 passed; extra positive receipt case checked separately. Ruff,
OpenAPI, generated handbook, Node parity and strict handbook pass. Complete CI run 42225013275 for
functional commit aa1bdf7 is green, including Python 3.12/3.14/3.15, native iOS/Swift and image checks.
Python 3.12 job 127916189465 reports 7402 passed, 2 skipped and the two existing handbook citation warnings.
Concurrent local full suites exhausted /tmp; isolated CI verifies the full suite. Completed failed-run
artifacts were removed; new checks use /workspace/work/pytest-scratch. No PR or branch was merged.
Logs: /workspace/work/ai-probe-audit/.
