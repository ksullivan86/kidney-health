Status: complete

Branch `audit/care-change-accounting`, based on main `cea3c94` (0.22.2). Create an unmerged PR.

Confirmed: after two concurrent helper requests both save their entries, the first request can overwrite
the second request's helper_changes snapshot. On the first changes of the day it can also duplicate the
care.plan_changed or care.food_logged activity entry. Six deterministic route-level cases hold the first
snapshot while another request runs: planned/planned, eaten/eaten and mixed, checking counts and notes
separately. Clean main: 5 fail, 1 passes (mixed kinds already have separate notes).

Fix: `note_change` obtains a write lock before reading its count and commits the count and daily audit note
together. Failed accounting rolls back its transaction. The food-writing APIs, permissions, low-treatment
rules, response shapes and clinical numbers are unchanged. The demo processes its count updates synchronously.

Verified: 139 focused tests; full pytest 7,392 passed, 2 skipped, 2 existing handbook citation warnings.
Ruff, parity vectors, OpenAPI, generated pages and strict handbook pass. All changes are committed.
PR https://github.com/ksullivan86/kidney-health/pull/157 is ready for review and remains unmerged. Logs:
`/workspace/work/care-count-audit/`.
