Status: complete

Branch `audit/device-callback-lifecycle`, main `cea3c94`. Create an unmerged PR.

Confirmed: late Withings/Whoop OAuth callbacks could restore a disconnected connection, overwrite a newer
completed sign-in, or save credentials after logout, session expiry/idleness, owner disablement or a forced
password change, or the server switch turning off during exchange. Deleting the owner caused a foreign-key
error. User ids already use AUTOINCREMENT and are not reused; no id-allocation change is needed.

24 real route/provider lifecycle cases: clean main fails 20 and passes 4; the fix passes all 24. With the
existing connected-device/Whoop tests, 82 pass. Includes Disconnect before and during exchange, replacement,
switch off, disabled/deleted owner, logout, password change, expired/idle session, unchanged flow and unrelated
sync receipts. Four additional positive tests for proxy/no-login modes pass; lifecycle plus auth-mode tests: 41 passed.

Fix: capture a digest of the connection identity/credentials/status at flow start. Refuse changed connections
before exchanging the code and recheck under BEGIN IMMEDIATE afterward, with fresh user/session and switch
reads. Store credentials and audit together. No write lock over provider calls; session lookup under the lock
is read-only (session validation would commit). Ignore sync timestamps/receipts when checking connection
identity. Keep current single-use state/session binding and existing cancellation redirect. Do not revoke
discarded credentials at the provider, since a provider-wide revoke could end the newer valid connection.

Architecture, device guide, handbook and changelog describe the cancellation behavior. Ruff, OpenAPI,
parity, generated pages and strict handbook pass. CI run 42220785538 for functional commit c812c4f is green,
including Python 3.12/3.14/3.15, native iOS/Swift, handbook, lint and image checks. Python 3.12 job
127901998103 reports 7414 passed, 2 skipped and the two existing handbook citation warnings. This includes
all 28 new lifecycle/auth-mode cases. The separate local full run is redundant and may still be finishing.
PR #160 is ready for review. No branch or PR was merged. Logs: `/workspace/work/device-callback-audit/`.
