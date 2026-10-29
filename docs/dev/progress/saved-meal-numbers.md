Status: complete

Plan's saved-meal cards use per_serving for plain meals and recipes, preserving null values.
Missing values say "not listed", partial values show ≥ with the missing-food count, and known zero stays zero.
Accessible labels say "at least" and explain missing nutrients. No server/API, ratings or recipe fitting changes.
The earlier Today fix and other sessions' work stay intact. The user subsequently requested both fixes
be committed and pushed to a branch without a PR. Environment publication remains with the other session.

Validation: tests/test_saved_meal_numbers.py runs the real Plan module with plain, one-serving,
multi-serving, complete and partial-zero saved meals via tests/js/saved_meal_numbers.test.mjs (five Node subtests).
`python -m pytest tests/test_saved_meal_numbers.py tests/test_today_loading.py tests/test_recipes_ui.py
tests/test_handbook_content.py`: 599 passed, one existing unused-sources warning.
`python -m pytest tests/test_recipes_api.py tests/test_planning.py tests/test_unknown_values.py
tests/test_unknown_values_twin.py`: 65 passed (local socket permission required).
JavaScript parity vectors, Plan syntax check, demo build and git diff --check passed.
Full Python suite and real-browser/device checks were not run for this focused display fix.
