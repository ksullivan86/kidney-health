Status: in progress

Branch `audit/oidc-password-change-guard`, main `cea3c94`. Keep PR unmerged.

Confirmed: OIDC Settings link/reauth callbacks call identify after the exchange, correctly checking the session
and active owner, but omit current_user's must_change_password check. A forced password change during a
pending flow still adds another way to sign in or refreshes recent confirmation. Six route cases cover
link/reauth x before callback/during exchange/no flag. Unchanged main fails 4 and passes 2. Added the missing
flag check to the existing callback identity refusal (expired), without changing public shapes. Updated
architecture, account guide, handbook and changelog. No external network: existing real signature/checked-
transport fake provider. Focused OIDC suite: 116 passed. Ruff passes. Full pytest, vectors and strict handbook running; generated
pages/OpenAPI checked. Next: finish full tests/checks, finalize unmerged PR.
Logs: `/workspace/work/oidc-password-audit/`.
