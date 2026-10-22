# Progress: ruff-import-walk

Status: in progress (delete this file in the last commit)

Worktree: /home/user/kidney-health/.claude/worktrees/agent-a43ad033855fd5de3, branch
worktree-agent-a43ad033855fd5de3, started from f3d2049 (origin/main). Local commits only; never push.

## Decisions
* ruff 0.17.0 (PyPI upload 2026-10-09; 0.17.1 is 2026-10-15T15:22Z, under 7 full days on 2026-10-22 02:24Z, so not used).
  sha256 of ruff-x86_64-unknown-linux-gnu.tar.gz = c94fc1dc...c91d3 (from the release's .sha256, tarball hashed to match).
* ruff 0.17 changed its default rule set (about 400 rules, 1052 findings today; 0.15.20 had 61 rules and was clean).
  So pyproject pins `select = ["E4", "E7", "E9", "F"]` (the old default) to keep today's tree clean.

## Done
* Part 1 (ruff in CI): ci.yml (RUFF_VERSION/RUFF_SHA256, fetch step, `ruff check --no-cache --output-format=github .`), pyproject [tool.ruff.lint], tests/test_deploy.py new test, CONTRIBUTING, docs/security.md, docs/network-allowlist.md. Verified: actionlint 1.7.12 (pinned download) and zizmor 1.30.1 --offline clean; ruff 0.17.0 and 0.15.20 pass; CI download step simulated locally with the pinned sha.

## Next
1. ruff in CI (ci.yml lint job, pyproject, test_deploy test, CONTRIBUTING).
2. Import walk harness step; docs (maintainers.md, tools/e2e/README.md, ROADMAP).
3. CHANGELOG Unreleased (For contributors only).
4. Checks, then delete this note.
