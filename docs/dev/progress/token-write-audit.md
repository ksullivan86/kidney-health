Status: complete

Audit on main `cea3c94` (0.22.2). Branch `audit/assistant-write-authorization`. Leave the PR unmerged.

Confirmed: authentication at request entry outlives token revocation during a USDA lookup (food/recipe),
preference preparation, or phone body upload. Existing write transactions did not recheck current access.
The original food-log reproduction returned a successful save after the owner revoked the token.

Added `api_tokens.require_current_write`, called inside the existing write transactions for both food tools,
the taste tool and phone submissions. It checks current owner, token ownership, expiry, revocation, required
scope and family switch. It neither commits nor touches last use. Ask chat keeps its own session authorization.
All request work rolls back on refusal and returns the existing generic family 401.

Verified:

* Full pytest: 7,431 passed, 2 skipped; 2 existing handbook citation warnings.
* All 45 new lifecycle cases fail on clean main and pass with the fix. Existing token/MCP/phone/Ask save tests pass.
* Node regression files and parity vectors, Ruff, OpenAPI snapshot, generated pages and strict handbook pass.
* PR https://github.com/ksullivan86/kidney-health/pull/153 remains unmerged. No schema or clinical-number changes.

The recovery link flow claims a single-use token before password/session changes; the backend export importer
uses one write transaction and invalidates settings caches on dry-run/failure rollback. No additional finding
was confirmed in those paths during this pass. Import UI and native phone findings have separate PRs.

Commands/logs: `/workspace/work/assistant-audit/`; Python `/workspace/kidney-health/.venv/bin/python`.
