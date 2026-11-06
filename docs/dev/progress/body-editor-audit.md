Status: in progress

Branch `audit/body-editor-lifecycle`, main `cea3c94`. Keep PR unmerged.

Confirmed: old weight/BP saves closed newer drafts or wrote their old validation errors into them. Submitted
fields stayed editable; refreshed page units could reinterpret the open weight's displayed pounds as kg.
Ten real-view/real-parser Node regressions: clean main fails 7, passes 3; all 10 pass with the fix. A note-only
edit still preserves the stored hundredth. Deferred API calls cover add/edit, duplicate prevention, failures,
Close/reopen and displayed-unit capture. Pytest invokes them through test_body_editor_lifecycle.py.

Fix: each sheet tracks opening generation and one outstanding write. Fields freeze during a submitted save,
Close/Cancel stay usable, a new draft is editable while Save waits, stale replies cannot close it or show old
errors. Successful old writes refresh the current day's actual data. Weight units are captured per opening,
including echo and parsing. Flagged reading focus cannot move behind a new measurement sheet. No clinical
numbers, ranges, warning text, routes, schema or dependencies changed. Docs/handbook/changelog updated.

Focused original suite: 123 passed, 2 static checks referred to retired S.units/S.busy. Updated the echo
reference; duplicate behavior is covered by the live handler regression instead of source-string counting.
Affected static/new tests now 29 passed. Full suite was started before that test maintenance; inspect its
results and rerun affected failures as needed. No all-green full result claimed yet.

Browser body.py extended with held committed writes/refusals and a real settings refresh. First run passed
93 checks then found a harness cleanup typo (Api uses json/call, not request); fixed and full walk rerunning.
Focused new browser walk: all 36 checks pass at 375 light / 1280 dark, including real unit refresh and once-only
commits. It ignores only the deliberately injected 422 console responses at their exact API paths. Full
browser rerun started before this harness-only adjustment; rerun it after completion if needed. Ruff,
parity/OpenAPI/generated checks pass; strict handbook running.
Full body.py browser walk now passes all 414 checks, including the held cases in three real-account
contexts, all original demo/dialysis flows, CSP and layout checks. Strict handbook passes. PR #162 is
draft/unmerged while full pytest runs. Next: finish full-suite validation, update PR and mark ready.
Logs: `/workspace/work/body-editor-audit/`.
