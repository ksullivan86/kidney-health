Status: in progress

Branch audit/food-entry-editor-lifecycle, main cea3c94. Keep PR unmerged.

Confirmed: reopening reset the entry write guard while an earlier save/delete still waited. Late replies
could close another draft, navigate away, show its old errors/conflicts or overwrite serving metadata.
Quick add's late saves/field errors also affected a reopened draft. Final23 live-handler cases: clean main
17 failed/6 passed; fixed23 passed. Initial20 cases were16 failed/4 passed; added offline/date positives.
No fixture failures are counted as product evidence.

Fix: opening generations, one outstanding entry write across reopen, control disabled-state snapshots
that preserve unavailable offline grams, and deferred serving metadata during that opening's write.
Quick add owns its save/error replies separately (its fields are not frozen by this change). Current
conflicts still open review; stale ones don't navigate. Version/base arguments, untouched quantities and
low-treatment purpose stay unchanged. Entry edits intentionally recompute nutrients from current food
(app/log.py); no nutrition/snapshot policy change was made. Core already dismisses confirmations on Close.

Verification:23 Node cases,62 focused Python/static/offline checks and78 real Chromium checks pass.
Browser tests at375 light/1280 dark hold committed adds/edits/deletes, food deletion and Quick add; check
new drafts, once-only writes, competing metadata for the same entry object, CSP and layout. First browser
run found a duplicate test name across viewports; made fixture names distinct and the complete rerun passed.
Architecture, guide, handbook and changelog updated. Registered the browser harness in tests/test_e2e_tools.py
and tools/e2e/README.md. Full pytest session2669 is running with TMPDIR=/workspace/work/pytest-scratch.
Next: finish Ruff/OpenAPI/parity/generated/strict handbook and existing reliability browser checks;
checkpoint/push a draft PR, then finish full-suite/CI validation and mark ready without merging.
Logs: /workspace/work/food-entry-audit/. No user data or main branch was changed.
