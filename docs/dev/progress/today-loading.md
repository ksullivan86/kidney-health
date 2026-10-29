Status: complete

Fix Today retaining the previous day's food beneath a newly selected date when loading fails.
The load clears food entries, totals and alerts, invalidates the cached day, and offers Retry on failure.
The request sequence guard protects success and failure paths. Treatment-of-low controls stay available.
Docs updated in ARCHITECTURE.md, docs/install-on-your-phone.md and handbook/docs/app/logging.md.

Validation: `python -m pytest tests/test_today_loading.py tests/test_recipes_ui.py tests/test_body_ui.py
tests/test_handbook_content.py` passed (626 tests; existing unused-sources warning).
The new runner exercises the full Today module: loading/failure cleanup, Retry recovery, late success,
late failure, and an old response arriving while the new date is still loading (four Node subtests).
`node tests/js/run_vectors.mjs`, `node --check app/static/js/views/today.js`,
`python scripts/build_preview.py --pages build/demo` and `git diff --check` passed.
The full Python suite and real-device/browser checks were not run for this focused frontend fix.
No environment draft changes or publication.
