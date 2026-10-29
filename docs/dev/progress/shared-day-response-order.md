Status: complete

Base: main bf7436b. Fetched all remote branches; Claude's active branch 10289d8 has integrated
the earlier three sharing/Trends fixes and other reliability work. sharing.js and visit.js are
unchanged there, so this fixes a separate failure path. No PR, deployment or environment publication.

Reproduced: an earlier date/person's response overwrites a newer shared day, and old errors replace
newly loaded food. Visit also waits for every summary read before replacing the previous shared day.
Before changes: five of six Node tests fail; Chromium sharing walk plus delayed replies reports
39 passed, one expected failure at /tmp/kidney-shared-day-race-before-20261029/report.json.

Fix: per-box WeakMap tokens discard old success and error replies, with independent boxes preserved.
Retry repeats that box's person/date. Visit starts the shared day before waiting for summary reads.
Validation: `python -m pytest tests/test_shared_day_loading.py tests/test_sharing_ui.py
tests/test_visit_prep_ui.py tests/test_handbook_content.py`: 614 passed, one existing unused-sources warning.
Six Node cases pass, including independent boxes and starting the day while summary reads are pending.
Chromium sharing walk plus delayed response race: 40 passed, zero failed
(/tmp/kidney-shared-day-race-after-20261029/report.json). The same race failed before the fix.
Ruff, parity, both module syntax checks, demo build and git diff --check passed.
The full suite was already run on the preceding branch; it was not repeated for this focused fix.
