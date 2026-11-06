Status: complete

Branch audit/food-entry-editor-lifecycle, main cea3c94. PR #167 ready for review; keep unmerged.

Confirmed: reopening reset the entry write guard while an earlier save/delete waited. Late replies could
close another draft, navigate away, show old errors/conflicts or overwrite serving metadata. Quick add's
late saves/field errors also affected reopened drafts. Final 23 live-handler cases: clean main 17 failed,
6 passed; fixed 23 passed. No fixture failures are counted as product evidence.

Fix: opening generations, one outstanding entry write across reopen, disabled-state snapshots that
preserve unavailable offline grams, and deferred serving metadata during that opening's write. Quick add
owns its save/error replies separately; its fields are not frozen by this change. Current conflicts still
open review; stale ones do not navigate. Version/base arguments, untouched quantities and low-treatment
purpose remain unchanged. Entry edits intentionally recompute nutrients from current food; that policy
was not changed. Core still dismisses confirmations on Close. Docs/handbook/changelog updated.

Verification: 23 Node cases, all 30 direct Node regression files, 62 focused Python/static/offline checks,
and 78 new real Chromium checks pass. Browser coverage holds committed adds/edits/deletes, food deletion
and Quick add; checks new drafts, single writes, same-object metadata, CSP and layout at phone/desktop.
The existing reliability walk passes all 87 checks with exit 0 (Playwright emits teardown cancellation
diagnostics). Ruff, OpenAPI, generated pages, parity and strict handbook pass.

Full local pytest: 7388 passed, 2 skipped, 2 existing handbook citation warnings in 1716.15s. Scratch data
uses /workspace/work/pytest-scratch. Complete CI run 42283407355 for functional commit 368581e is green,
including Python matrix, native iOS/Swift, handbook and image checks. No branch or PR was merged.
Logs: /workspace/work/food-entry-audit/. Durable cross-session index: docs/dev/audit-handoff.md in PR #168.
