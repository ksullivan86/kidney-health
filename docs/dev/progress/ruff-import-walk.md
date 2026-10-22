# Progress: ruff-import-walk

Status: in progress (delete this file in the last commit)

Worktree: /home/user/kidney-health/.claude/worktrees/agent-a43ad033855fd5de3, branch
worktree-agent-a43ad033855fd5de3, started from f3d2049 (origin/main). Local commits only; never push.

## Decisions
* ruff 0.17.0 (PyPI upload 2026-10-09; 0.17.1 is 2026-10-15T15:22Z, under 7 full days on 2026-10-22 02:24Z, so not used).
  sha256 of ruff-x86_64-unknown-linux-gnu.tar.gz = c94fc1dc...c91d3 (from the release's .sha256, tarball hashed to match).
* ruff 0.17 changed its default rule set (about 400 rules, 1052 findings today; 0.15.20 had 61 rules and was clean).
  So pyproject pins `select = ["E4", "E7", "E9", "F"]` (the old default) to keep today's tree clean.
* New harness tools/e2e/import_walk.py (journey.py needs a built handbook and three fakes; regress.py makes a server per
  config with one person). Port 8086.
* FINDING (not fixed, report it): after Cancel on the password sheet the file box still holds the file, and choosing the
  same file again fires no change event (Chromium), so nothing happens; no Retry. Way out: leave Settings and open it again
  (the block is drawn fresh). The harness takes that way out (reopen_settings) and does not assert the quirk.

## Done
* Part 1 (ruff in CI): commit 142cbb3. Verified: actionlint 1.7.12 (pinned download) and zizmor 1.30.1 --offline clean;
  ruff 0.17.0 and 0.15.20 pass; CI download step simulated with the pinned sha.
* Part 2 (harness): tools/e2e/import_walk.py passes (101 checks, ~16 s), twice in a row; negative control (merge dedupe removed
  in app/data_import.py, restored) made it fail. Docs: tools/e2e/README.md, tests/test_e2e_tools.py, CONTRIBUTING.md,
  docs/maintainers.md, docs/ROADMAP.md (two items removed), CHANGELOG.md (Unreleased, For contributors).

## Next
* Final checks: python -m pytest -q, node tests/js/run_vectors.mjs, ruff check ., harness twice; commit; delete this note.

## Commands
* PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/import_walk.py --out <dir>
* ruff check .   (rules: pyproject.toml [tool.ruff.lint])
