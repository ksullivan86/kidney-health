Status: complete

Branch audit/usda-import-concurrency, main cea3c94. PR #166 ready for review; keep unmerged.

Confirmed: simultaneous imports could create different shared food ids for the same USDA record. Six
real-route/transaction cases cover same/different people and an API import overlapping an assistant-style
write, plus rollback of shared food/link and earlier caller work. Corrected HTTPS baseline: four concurrent
cases fail on different returned ids, two rollback cases pass; fixed six pass. Earlier plain-HTTP setup
failures were not product evidence and were explicitly corrected before the valid reproduction.

The shared-row helper reserves BEGIN IMMEDIATE before looking up the FDC id only when the caller has no
transaction. Existing write transactions retain ownership; no caller work is committed by the helper.
Upstream requests and mapping stay outside the new lock. No schema, matching/mapping values, clinical
rules or API fields changed. Architecture, food/barcode guide, handbook and changelog updated.

Broader API/isolation/MCP/Ask suite: 200 passed. Separate transactional MCP-write suite: 77 passed. Ruff,
OpenAPI, generated pages, Node parity and strict handbook pass. Full local pytest: 7392 passed, 2 skipped,
with the two existing handbook citation warnings, in 1875.71s. This clean run used workspace scratch files.
Complete CI run 42279711531 at functional commit 768e86c also passes, including its Python matrix, native
iOS/Swift, handbook and image checks. No branch or PR was merged.
Logs: /workspace/work/usda-import-audit/, especially baseline-final.log and lifecycle-verified.log.
