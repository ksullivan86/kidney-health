Status: complete

Validated main 84330f306f93180d9d21bad716e59093939a6a22 (#119), 2026-10-29. No source changes.
Used an isolated detached worktree so concurrent branch edits did not affect the run.

Command: /workspace/kidney-health/.venv/bin/python -m pytest -o faulthandler_timeout=120
Result: 6533 passed, 2 skipped, 1 existing unused-handbook-sources warning, 883.75 seconds.
Full log: /tmp/kidney-current-main-full-suite.log.

The historical schema-v3 Git object was fetched earlier and retained under a local fixture ref;
the upgrade-starting-points test passed without changing or skipping its assertion. API tests ran
with local asyncio socket support outside the restricted network sandbox. No network-dependent
test was added and no environment, app or PR was published.

This confirms the tests pass at that exact main revision. New fixes are checked separately on
their own branches; this run does not claim to cover unmerged branches, physical devices or live AI.
