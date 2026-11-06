Status: in progress

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

Architecture, device guide, handbook and changelog describe the cancellation behavior. Ruff passes.
Full pytest is running (session 5820), started after the 24 lifecycle cases passed; the four extra mode cases
were added afterward and are checked separately. OpenAPI/parity/generated pages and strict handbook running.
Next: inspect mode/full/check logs, commit and push own files, create draft PR, finalize after verification.
Logs: `/workspace/work/device-callback-audit/`. Other PRs remain unmerged. Ask #159 is ready after 7400 tests
and 144 browser checks passed; do not merge it.
