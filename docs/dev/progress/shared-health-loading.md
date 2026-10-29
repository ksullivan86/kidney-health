Status: in progress

Base: main bf7436b (#117, Other choices now merged). Refreshed all branch tips before starting.
This branch changes only symptom and body Trends loading, not the food-chart or dry-weight fixes
on the previous branches. Claude's last fetched feature branch did not change these modules.

Reproduced with real views/engines: seven of nine Node regressions fail on unchanged main.
Both cards retain the previous person's data while loading. The body chart also retains its redraw
cache, so resize can restore old readings under the new heading. Handled errors currently leave stale content.

Fix clears before reads and resets the body redraw cache. Failures show Retry for the same person/period.
Request guards discard late results and errors; unshared areas retain their explicit unavailable wording.
No server, clinical arithmetic, or data-write behavior changes.

Focused validation: `python -m pytest tests/test_shared_health_loading.py tests/test_sharing_ui.py
tests/test_body_ui.py tests/test_symptoms_ui.py tests/test_handbook_content.py`: 647 passed, existing
unused-sources warning. Nine new Node cases pass (seven reproduced failures before the fix).
Parity vectors, Ruff, both module syntax checks, demo build and git diff --check passed.
Full suite started as `timeout 1200 .venv/bin/python -m pytest > /tmp/kidney-full-health-loading.log 2>&1`
and is still running; session 21863. Keep this checkout on the branch until it completes so results
refer to this code. Pending next review: shared day rendering in sharing.js lacks a request guard.
User stopping target: October 29, 2026, about 10 a.m. America/Los_Angeles (17:00 UTC).
Push this tested checkpoint without a PR; no deployment or environment publication.
