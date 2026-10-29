Status: in progress

Three small loading fixes. Worktree branch `worktree-agent-a3f2ee7639205c3ed`, merged from `claude/adoring-sagan-th5swr`
(289c2b3). Local commits only, no push.

1. Sharing list (`js/views/sharing.js`, `load()`): DONE. A WeakMap per block keeps a load counter and the link just made;
   only the newest load draws; the link stays until the list no longer has it as unused; only the load that made it focuses it.
   Test `tests/js/sharing_list_loading.test.mjs` (pytest `tests/test_sharing_list_loading.py`), 7 cases: 4 failed on the old
   code (overlap answered newest first, link lost on a later load, link lost on a failed load, older failure replaced the list),
   all 7 pass now. Existing sharing, visit prep, settings and handbook tests pass. Docs: ARCHITECTURE Sharing → Screens,
   handbook settings-and-keys.md step 2, docs/accounts.md step 2, CHANGELOG.
2. Signed-in devices (`js/views/settings.js`, `loadDevices`): request counter. Not started.
3. Add tab search (`js/views/add.js`, `runSearch`): a failed search shows in place of old results, with Retry. Not started.

Python: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
