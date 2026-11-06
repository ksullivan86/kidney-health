Status: complete

# Care team planning audit

Base main bf35adb, branch fix/care-plan-confirmation-and-retry. Leave the PR unmerged.

Confirmed and fixed:
- Clear planned days used live date fields after showing its confirmation. It now captures exactly the shown range.
- A failed or unanswered batch reenabled the same generated plan preview. Shared helper batches ignore client_id, so
  retrying could duplicate food already saved. Each preview now sends once and offers Review the plan after a failure.
- Review opens the first generated day's week, so a plan for another week can actually be checked before making a new preview.

No API, schema or clinical rule changed. No automatic rollback or retry removes or duplicates food.
The helper reviews what reached the server, including requests whose success reply was lost.

Validation:
- Full pytest: 7,332 passed, 2 skipped, with the two existing handbook-source warnings.
- The harness registration added during that run was checked separately: test_e2e_tools.py, 43 passed.
- New Node regressions: 8 passed; original functions fail 5 and pass the 3 normal cases.
- Focused Care team pytest: 82 passed.
- New Chromium harness care_plan_actions.py: 18 checks at phone/light and desktop/dark.
  Real Clear removes only the confirmed date, preserving a planned low treatment. Both real batches save,
  the second success reply is dropped, the same preview cannot resend, and Review shows the saved day.
- Existing sharing.py browser walk: 89 passed, including the demo and permissions.
- Node tests, vectors, Ruff, generated handbook check, strict MkDocs build and whitespace checks pass.

The same main base has a pinned-image vulnerability scan blocker, documented in PR #144.
This branch changes no image pins. Do not merge, deploy, enable auto-merge or bump the version.
Combine its CHANGELOG Unreleased entry with the other audit PRs when the owner's other session merges.

Reproduce:
    python -m pytest
    node --test tests/js/care_plan_actions.test.mjs
    python3 tools/e2e/care_plan_actions.py
    python3 tools/e2e/sharing.py

Worktree /workspace/work/care-audit-src; logs /workspace/work/care-audit/.
