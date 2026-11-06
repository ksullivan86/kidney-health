Status: in progress

Audit on main `cea3c94` (0.22.2). Branch `audit/assistant-write-authorization`. Leave the PR unmerged.

Confirmed: authentication at request entry outlives token revocation during a USDA lookup (food/recipe),
preference preparation, or phone body upload. Existing write transactions did not recheck current access.
The original food-log reproduction returned a successful save after the owner revoked the token.

Added `api_tokens.require_current_write`, called inside the existing write transactions for both food tools,
the taste tool and phone submissions. It checks current owner, token ownership, expiry, revocation, required
scope and family switch. It neither commits nor touches last use. Ask chat keeps its own session authorization.
All request work rolls back on refusal and returns the existing generic family 401.

Verification in progress:

* `tests/test_token_write_lifecycle.py`: 45 cases across log food, recipe, food/group tastes and phone submissions;
  revocation, expiry, scope, switch, required password change, disabled/wrong-kind/deleted owner and deleted token.
  Real routes and USDA mock; no external network. The same 45 cases fail on clean main; the fixed branch passes all 45.
* Focused existing bearer/MCP/phone/Ask tests running. Full pytest started; Node and vectors, generated pages and changed-file Ruff passed. Next: full pytest, JS parity, Ruff, generated pages,
  strict handbook, review the diff, commit/push own paths and create an unmerged PR.

Commands/logs: `/workspace/work/assistant-audit/`; Python `/workspace/kidney-health/.venv/bin/python`.
