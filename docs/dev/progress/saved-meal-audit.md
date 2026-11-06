Status: in progress

Branch `audit/saved-meal-editor-lifecycle`, based on main `cea3c94`. Create a PR and leave it unmerged.

Confirmed late search/save/delete replies crossed New/Edit saved-meal openings; Save as meal, Add to a day and Copy day
had the same save-close issue. An old apply also navigated to its submitted day after a newer action. Search
invalidation waited for the debounce rather than the input, and submitted forms remained editable.

Fixed per-opening reply checks, immediate search invalidation, stale detached row actions, and frozen submitted
fields (Close/Cancel still work). Keep one outstanding write per sheet type across reopening; a newer draft can
be edited but cannot submit until that write finishes. After an old apply, refresh the current view without
navigation. A failed current save restores controls and preserves the draft. Server/demo share these views.

Verified 20 Node cases pass, plus existing unknown-nutrient and recipe-serving editor cases.
Real Chromium harness: 44 checks pass at 375 light and 1280 dark. Existing reliability walk: 87 checks pass.
Full pytest is running. Ruff, vectors, generated pages and strict handbook pass. Initial harness seeded apple juice, correctly
excluded by Save as meal as a low treatment; changed fixture to raw apple. This was a harness issue.

Next: finish full pytest, run all Node regression files after final opening guards, and mark the PR ready after checks pass. Logs `/workspace/work/meal-audit/`.
