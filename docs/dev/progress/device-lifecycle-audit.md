Status: complete

# Broader audit: device connection lifecycle

PR: https://github.com/ksullivan86/kidney-health/pull/145
Base main `bf35adb`; branch `fix/device-sync-connection-lifecycle`.
PR #144 remains separate. Recipe-import findings are in PR #146.
The user's other session reviews and merges. No PR was merged or auto-merge enabled.

## Confirmed and fixed

- Disconnect during fetch could import data afterward and then fail response validation.
- Reconnect during fetch could import the previous account's data and move the new cursor.
- An old refresh or authentication failure could overwrite or clear new credentials.
- Disabling the account, marking it as a test account or turning devices off did not stop a pending import.
- Readings/activity/ledger committed before the sync cursor; a later failure left a partial batch.

Each network operation uses a snapshot, then checks it against the current connection and
permissions before writing. Refresh and error writes are guarded in a write transaction.
One fetched batch's readings, activity, ledger and cursor commit together. Provider calls
hold no write transaction. Disconnect while waiting is a plain 404; replacement or permission
changes answer `connection_changed`. No response field type, clinical rule or schema changed.

## Validation

- Full pytest: **7,357 passed, 2 skipped**, with only the two existing handbook-source warnings.
- New lifecycle tests: **26 passed**. The final fixtures use Withings weights and Whoop activity,
  and inject failure at the cursor write after those imports. On clean main: **24 failed, 2 passed**.
- The final provider-specific fixture refinement was rerun separately: all 26 pass.
- Existing Withings/Whoop integration tests, Node tests and parity vectors pass.
- Ruff, OpenAPI snapshot, generated handbook check, strict MkDocs build and whitespace checks pass.
- CodeQL, lint, handbook, JS parity and iOS CI checks passed on the functional commit.
- Published source trees are checked against the local tree.

## Handoff

The main base's pinned container image fails Grype on Python CVE-2026-115557 (Critical)
and libexpat CVE-2026-115506/CVE-2026-113351 (High). See PR #144's CI handoff and scan link.
Existing image update PR #142 is not green either: its earlier tests failed because the
Containerfile's split-stage comment is stale when builder and handbook digests match.
Do not assume that PR fixes the current scan; it needs review and a fresh image build/scan.
No image pins were changed here. Do not merge, deploy or bump the version in this session.

Commands:

    .venv/bin/python -m pytest
    .venv/bin/python -m pytest tests/test_device_sync_lifecycle.py tests/test_connected_devices.py tests/test_whoop.py
    node --test tests/js/*.test.mjs
    node tests/js/run_vectors.mjs

Logs: `/workspace/work/device-audit/`. TestClient needs the shell command's network
permission in this environment for its local event loop; the tests use fakes for providers.
