Status: in progress

Branch `audit/ask-trust-write-lifecycle`, based on main `cea3c94`. Create an unmerged PR.

Confirmed: trusted Ask saves used the request-entry trust snapshot after the person/admin ended it during a
model reply or USDA lookup. A retry of an already completed trusted save after switching to ask mode offered
a new confirmation that could duplicate it. A trust change after the first of two saves also needs truthful
confirmation text: the first save remains complete.

14 route-level regressions: 13 fail on clean main, 1 passes (an ask request does not gain trust mid-flight).
All 14 pass with the fix. Mocks change settings through a second TestClient portal during the provider reply,
or while the USDA lookup waits; no external network. The second portal avoids calling a blocking client from
the provider mock's own event loop.

Fix: recheck stored trust/admin switch before saving and through Asker.authorize_write under write_once's
write lock. Permission loss rolls back and returns the ordinary confirmation card, permanently downgrading
this request. Completed request keys report their earlier result even in ask mode. Partial chat completion
keeps its earlier saved cards and uses text that says they completed. Public shapes, clinical rules and
consent flows are unchanged.

Full pytest running. Earlier focused run: 193 passed and 2 test-script failures (replays need a final model
answer, as existing replay tests do); scripts corrected and all 14 lifecycle cases pass. Next: rerun focused
chat/MCP suite, Ruff/OpenAPI/Node vectors, generated pages/strict handbook, check compatibility with PR #153,
checkpoint/push own files and create PR. Logs: `/workspace/work/ask-audit/`.
