Status: complete

Based on current main d1ba260. Refreshed all remote branch tips, including Claude's active branch
fa32278. Its pending Other choices feature does not change trends.js; no edits to that work.
The previous shared-weight-profile fix is on its separate branch, not included here.

Reproduced against unchanged main: opening another person's Trends leaves old food charts/summary
under the new person's name during loading or a failed request; the cached summary is also retained
when the next person has not shared food. New tests fail on those paths, while existing request
guards already handle late success/failure after a newer request completes.

Fix clears chart/summary state and content before loading, hides old tooltips, and offers Retry on failure.
Latest-request guards cover error and success. Scope: food charts and period summary; child body/symptom
modules keep their independent loading/error handling.

Validation: `python -m pytest tests/test_trends_loading.py tests/test_sharing_ui.py tests/test_body_ui.py
tests/test_handbook_content.py`: 630 passed, one existing unused-sources warning.
tests/test_trends_loading.py runs the complete Trends module (five Node cases): immediate cleanup and Retry,
late success/failure after source switching, another person still loading, and food not shared.
Three cases fail on unchanged main; all pass with the fix. JavaScript parity vectors, Ruff,
Trends syntax, demo build and git diff --check passed. Full Python suite and real-browser checks not run.
Local branch fix/trends-loading-state. No PR or deployment.
