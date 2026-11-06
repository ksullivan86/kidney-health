Status: complete

Branch `audit/oidc-password-change-guard`, main `cea3c94`. Keep PR unmerged.

Confirmed: OIDC Settings link/reauth callbacks call identify after the exchange, correctly checking the session
and active owner, but omit current_user's must_change_password check. A forced password change during a
pending flow still adds another way to sign in or refreshes recent confirmation. Six route cases cover
link/reauth x before callback/during exchange/no flag. Unchanged main fails 4 and passes 2. Added the missing
flag check to the existing callback identity refusal (expired), without changing public shapes. Updated
architecture, account guide, handbook and changelog. No external network: existing real signature/checked-
transport fake provider. Focused OIDC suite: 116 passed. Ruff, OpenAPI, generated pages, Node parity and strict
handbook pass. Full CI run 42221270024 for functional commit 48bc1d7 is green, including Python 3.12/3.14/3.15,
native iOS/Swift and image checks. Python 3.12 job127903629181 reports7392 passed,2skipped and the two existing
handbook citation warnings. The separate local full run may still be finishing and is redundant.
PR #161 is ready for review. No branch or PR was merged.
Logs: `/workspace/work/oidc-password-audit/`.
