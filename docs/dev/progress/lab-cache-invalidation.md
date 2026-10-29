Status: complete

Base: main bf7436b. Refreshed all branch tips; Claude's latest fetched branch 10289d8 does not change
labs.js/profile.js. Separate from prior sharing and AI fix branches. No PR/deployment.

Reproduced: load + invalidate (on a save/profile change) + load returns the same pre-change promise.
Only one list request is made; old results can overwrite the history, kidney-function text and Profile summary.
Five of seven Node cases fail on unchanged main; deduplication and retry of a genuine current error already pass.

Fix: invalidate increments the cache generation and drops the in-flight handle. Stale success or failure
redirects readers to the newest read, rather than returning pre-change data or repopulating the cache.
Only its own promise can clear the in-flight handle. Lab results and Profile summary also guard refresh order.
No server, target formulas, alert thresholds or unit conversion changes.

Validation: `python -m pytest tests/test_lab_cache.py tests/test_targets_ui.py tests/test_lab_photo_ui.py
tests/test_fhir_labs_ui.py tests/test_ccda_labs_ui.py tests/test_e2e_tools.py tests/test_handbook_content.py`:
720 passed, one existing unused-sources warning. Seven new Node cases pass, five reproduced failures before the fix.
Chromium reliability walk including delayed lab reads: 13 passed, zero failed
(/tmp/kidney-lab-cache-20261029/report.json). Synthetic cache checks write no lab to the server.
Ruff, parity, both module syntax checks, demo build and git diff --check passed.
Full suite was already run on the health-loading branch; not repeated for this focused cache fix.
