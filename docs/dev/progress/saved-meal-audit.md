Status: complete

Branch `audit/saved-meal-editor-lifecycle`, based on main `cea3c94`. Create a PR and leave it unmerged.

Confirmed late search/save/delete replies crossed New/Edit saved-meal openings; Save as meal, Add to a day and Copy day
had the same save-close issue. An old apply also navigated to its submitted day after a newer action. Search
invalidation waited for the debounce rather than the input, and submitted forms remained editable.

Fixed per-opening reply checks, immediate search invalidation, stale detached row actions, and frozen submitted
fields (Close/Cancel still work). Keep one outstanding write per sheet type across reopening; a newer draft can
be edited but cannot submit until that write finishes. After an old apply, refresh the current view without
navigation. A failed current save restores controls and preserves the draft. Server/demo share these views.

Verified 20 Node cases pass (17 fail, 3 pass on clean main), plus existing unknown-nutrient and recipe-serving editor cases.
Real Chromium harness: 44 checks pass at 375 light and 1280 dark. Existing reliability walk: 87 checks pass.
Full pytest: 7,386 passed, 2 skipped, with two test-maintenance failures: the new harness needed a README entry, and one recipe-field test cut its source at the retired mealEd.busy marker. Added the README entry and bounded the field test by its submit handler. The affected and related tests now all pass (59 cases). All 7,388 cases are verified; the 2 handbook warnings predate this change. All 30 Node regression files, Ruff, vectors, generated pages and strict handbook pass. Initial harness seeded apple juice, correctly
excluded by Save as meal as a low treatment; changed fixture to raw apple. This was a harness issue.

PR https://github.com/ksullivan86/kidney-health/pull/154 is ready for review and remains unmerged. No API, schema or clinical-number changes. Logs `/workspace/work/meal-audit/`.
