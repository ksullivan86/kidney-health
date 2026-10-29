Status: complete

Base: main 867b09b (#118). Refreshed all remote branches; Claude's branch 55b9c29 has picked up the
last four fixes but does not change core.js. Separate cache problem, no PR/deployment.

Reproduced: core's loadProfile/loadMeals assign old replies after completed writes. Concurrent uncached
reads duplicate requests; older forced reads can overwrite newer results. Save-as-meal/import set meals
to null without invalidating an already pending read (including null-to-null cases).

Fix: per-cache request records deduplicate normal reads, follow newer forced refreshes, and preserve
external completed-save references. Explicit invalidation for meals and import clears the pending handle
too. Stale replies/failures converge on the current result; genuine latest failures still propagate and allow retry.
Public async helper signatures and server/API behavior are unchanged; cache invalidators are client-only helpers.
Validation: 18 Node cases pass (the baseline fails 16); 659 focused pytest checks pass with the existing
unused-handbook-sources warning. Chromium reliability: 16 passed, including both controlled stale-cache
checks. Chromium import walk: 109 passed. Node parity vectors, Ruff, JavaScript syntax, demo build and
git diff --check pass. Browser artifacts: /tmp/kidney-shared-cache-20261029 and
/tmp/kidney-shared-cache-import-20261029. No server data is written by the synthetic cache checks.

Ready on fix/shared-state-cache-order for Claude to review/cherry-pick. No PR or deployment.
