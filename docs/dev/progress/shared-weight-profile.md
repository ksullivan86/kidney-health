Status: complete

Based on current main d1ba260 (2026-10-29). Fetched all remote branches, including Claude's active
claude/adoring-sagan-th5swr at fa32278. That branch's unmerged work is Other foods / Other ideas /
Other recipes; body_trends.js is identical to main. No changes to that work.

Reproduced: if the shared profile request fails, last.profile falls back to the signed-in viewer's
profile. A caregiver on hemodialysis can see their own dry-weight line on the owner's weight chart.
Fix retains null for unavailable shared profiles, while own Trends retain their existing fallback.
Tests execute the real chart and engines, checking lines, legend, accessible text and redraw.
The regression fails on unchanged main; owner-profile success and own-profile tests already pass.

Validation: `python -m pytest tests/test_shared_weight_profile.py tests/test_sharing_ui.py tests/test_body_ui.py
tests/test_body_ui_numbers.py tests/test_handbook_content.py`: 725 passed, one existing unused-sources warning.
The new Node runner has three tests: failed shared profile (also redraw), successful owner profile,
and the signed-in person's own chart. All execute the real chart and engines.
`node tests/js/run_vectors.mjs`, `.venv/bin/ruff check .`, demo build and `git diff --check` passed.
Full Python suite and a real-browser walk were not run for this focused fallback fix.
Branch fix/shared-trends-reliability, no PR or publication.
