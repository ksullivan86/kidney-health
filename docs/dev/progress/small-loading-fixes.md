Status: in progress

Three small loading fixes. Worktree branch `worktree-agent-a3f2ee7639205c3ed`, merged from `claude/adoring-sagan-th5swr`
(289c2b3). Local commits only, no push.

1. Sharing list (`js/views/sharing.js`, `load()`): DONE. A WeakMap per block keeps a load counter and the link just made;
   only the newest load draws; the link stays until the list no longer has it as unused; only the load that made it focuses it.
   Test `tests/js/sharing_list_loading.test.mjs` (pytest `tests/test_sharing_list_loading.py`), 7 cases: 4 failed on the old
   code (overlap answered newest first, link lost on a later load, link lost on a failed load, older failure replaced the list),
   all 7 pass now. Existing sharing, visit prep, settings and handbook tests pass. Docs: ARCHITECTURE Sharing → Screens,
   handbook settings-and-keys.md step 2, docs/accounts.md step 2, CHANGELOG.
2. Signed-in devices (`js/views/settings.js`, `loadDevices`): DONE. `devicesRequest` counter; only the newest load draws,
   success or failure. Test `tests/js/devices_loading.test.mjs` (cuts loadDevices out of settings.js between the end of
   passwordForm and the data block; pytest `tests/test_devices_loading.py`), 5 cases: 3 failed on the old code (revoked phone
   came back, newest-first overlap, older failure replaced the list), all pass now. All tests that read settings.js pass
   (232). Docs: ARCHITECTURE Settings view, CHANGELOG. Handbook unchanged: nothing new on screen.
3. Add tab search (`js/views/add.js`, `runSearch`): DONE. The counter was already there; the newest failed search now calls
   `renderSearchFailed`: the new heading, no count, "Could not search: <why>." and Retry (runs runSearch again), in place of
   the old results. The toast is gone (said once, in place). Test `tests/js/food_search_failed.test.mjs` (pytest
   `tests/test_food_search_failed.py`), 3 cases: 2 failed on the old code (old results stayed, no Retry), all pass now.
   Tests that read add.js, USDA and scan late replies pass. Docs: ARCHITECTURE Add food, handbook logging.md "If something
   goes wrong", CHANGELOG.
4. E2E: DONE. tools/e2e/late_replies.py has three new steps (Search, Devices, Sharing; the server runs with
   SHARING_ENABLED=true; Ana gets two more sessions and a share with bob before the browser opens). On the old view files
   (from 289c2b3) all three fail; with the fixes 8 of 8 pass. A failed step now prints its traceback. tools/e2e/README.md
   updated. Run: `python3 tools/e2e/late_replies.py --out <empty dir>`.
5. Next: full `python -m pytest`; node tests/js/run_vectors.mjs passed.

Python: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
