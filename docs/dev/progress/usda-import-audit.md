Status: in progress

Branch `audit/usda-import-concurrency`, main `cea3c94`. Keep PR unmerged.

USDA's shared-row helper SELECTs an existing record then inserts if absent without reserving a write lock.
Unlike builtin and OFF keys there is no unique USDA FDC index. Confirmed duplicate food copies with held
real route inserts, across same/different people and API versus an existing assistant-style transaction.
Also require rollback of the shared food/link and earlier caller work: a helper fix must never commit a
caller's surrounding transaction. Six cases use the existing mock USDA fixture, no network.
After correcting the multi-account fixture to use HTTPS, clean main fails all4 concurrent cases on
different returned food ids and passes2 rollback cases. All6 pass with the fix: reserve BEGIN IMMEDIATE
only when there is no active transaction, before looking up the FDC id; never commit caller work. Initial
plain-HTTP failures were harness setup errors, not product evidence. Docs/handbook/changelog updated.
Broader API/isolation/MCP/Ask suite: 200 passed. Separate transactional MCP-write suite: 77 passed.
Ruff, OpenAPI, generated handbook and Node parity pass; strict handbook passes. Full pytest is running (session59179); next create a draft PR, finish
full-suite verification, then mark ready without merging. New tests use TMPDIR under /workspace/work/
pytest-scratch because concurrent earlier full runs exhausted the separate /tmp disk. Next: finish checks,
checkpoint/push and draft PR; complete validation and mark ready unmerged. Logs: `/workspace/work/usda-import-audit/`.
