Status: complete

# List app configuration lifecycle audit

Base main bf35adb, branch fix/list-sync-configuration-lifecycle. Leave the PR unmerged.

Confirmed and fixed:
- A late Test could overwrite a new list selection or record the old connection's error on it.
- Test/Send could fail response validation after Remove instead of explaining the intervening change.
- A completed send to a previous connection marked the new destination as sent.
- Reconfiguring a list, address or key retained an unrelated last-send receipt even without a race.

Test/Send capture their connection for the network operation and check it under a write transaction before
applying the result. Changes give 409 with reason connection_changed. An already issued send may finish at the
old destination; its confirmed count is returned with the conflict and audited when the owner still exists.
The new connection never gets that receipt. The error asks the person to check the previous list before retrying.
Changing destination or credentials clears receipts on the server and demo. No schema or clinical rule changed.

Validation:
- Full pytest: 7,350 passed, 2 skipped, with the two existing handbook-source warnings.
- New lifecycle tests: 18 API cases pass. Clean main fails 17, passing only the normal path.
- Demo receipt checks: 4 Node cases pass, run by the additional pytest wrapper.
- Focused existing list/API/UI/OpenAPI tests: 91 passed before the last four failure-path cases were added;
  all 19 lifecycle/demo pytest cases pass together afterward and in the full suite.
- Existing lists_recipes.py Chromium walk: 42 passed, including real transport fakes and the demo.
- All Node tests, parity vectors and list/recipe generator check pass.
- Ruff, OpenAPI regeneration, generated handbook check, strict MkDocs build and whitespace checks pass.

The same main base has a pinned-image vulnerability scan blocker, documented in PR #144.
No image pins changed here. Do not merge, deploy, enable auto-merge or bump the version.
Combine its CHANGELOG Unreleased entry with the other audit PRs when the owner's other session merges.

Reproduce:
    python -m pytest
    python -m pytest tests/test_list_sync_lifecycle.py tests/test_list_sync_receipts_demo.py
    node --test tests/js/list_sync_receipts.test.mjs
    python3 tools/e2e/lists_recipes.py

Worktree /workspace/work/list-audit-src; logs /workspace/work/list-audit/.
