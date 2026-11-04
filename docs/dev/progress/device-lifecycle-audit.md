Status: in progress

# Broader audit: device connection lifecycle

Base main `bf35adb`; separate branch `fix/device-sync-connection-lifecycle`.
PR #144 remains open and unmerged. The user asked whether the shopping pass was all;
continue beyond it, with confirmed fixes in separate unmerged PRs.

Surveyed recipe import, connected devices, Care team suggestions and list sync.
Recipe import has unguarded draft loads/saves and global search state; follow up separately.
Priority here: sync uses a connection snapshot across provider calls. Disconnect, reconnect
or disabling the account during those calls can leave the old sync writing afterward.
Refresh/error paths also update rows by id without checking that tokens are still current.
The two import helpers each commit separately.

Confirmed on a clean main worktree: 24 failures and 2 passing normal-sync cases in
`tests/test_device_sync_lifecycle.py`. Both providers are covered. The fixes pass those
26 cases and preserve the existing Withings/Whoop integration tests. Updated the UI error
word check to compare with the server's codes, including `connection_changed`.

Done: guards before network work and inside each refresh/error/import transaction;
atomic readings/activity/ledger/cursor commit; explicit 404 for a connection disconnected
during a request (rather than response-validation 500). No response field type changed.
Docs and OpenAPI updated. Ruff, vectors and Node tests pass; handbook build running.

Plan: deterministic provider hooks reproduce the intervening user/admin change. Guard
refresh, error and import writes against the current connection and user; commit each
fetched result atomically. No network lock while waiting for a provider. Check cancellation
response and UI, docs and OpenAPI. Do not merge, deploy or bump the version.
