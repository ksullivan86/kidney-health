Status: in progress

# a11y-walk: automated accessibility check and fixes

Task: build `tools/e2e/a11y.py` (keyboard, names, large text, contrast at 375×812 and 1280×800, light and dark,
real server on port 8099), fix what it finds in `app/static`, docs (tools/e2e/README.md, docs/maintainers.md,
CHANGELOG.md Unreleased). Commit locally only, never push.

## Done
- Merged `claude/adoring-sagan-th5swr` into the worktree branch.
- `tools/e2e/a11y.py` written; in README table and `tests/test_e2e_tools.py` HARNESSES (pytest passes, ruff clean).

## Baseline (before any fix), `python3 tools/e2e/a11y.py`: 650 passed, 134 failed
Findings by kind: focus-visible 28, focus-obscured 72, grow 1115, reflow 6, spill 48, clipped 18, target 4, contrast 4.
Names, labels, images, live regions, sheet focus/Escape/close/return: all pass.
1. **grow**: text does not grow at 200 % root size: `body { font-size: 16px }` in base.css (inherited text and form fields stay 16 px).
2. **focus-obscured** (phones): Tab lands on controls under the fixed bottom tab bar (no scroll-padding).
3. **focus-visible**: date/time/month inputs: the calendar button inside the field gets focus but `input:focus` does not match there.
4. **focus-obscured** entry sheet: meal radio `input` is absolutely placed outside `.meal-seg` (no positioned parent), so focus scrolls to the input and its label stays out of view.
5. **target/contrast**: `input[type=url]` (#meal-source) has no base field style (29 px tall; dark UA background); `textarea::placeholder` not styled (dark: 3.9:1).
6. **spill**: `.step-btn` glyph spills its 44 px box at 200 %; meal-chip sub line; profile labels in 2 columns; strip labels; hints with long words.
7. **clipped**: `.meal-seg` labels (Dinner/Snack/Never suggest) cut off at 200 %; meal chip name ellipsis.
8. **reflow**: Today 421 px at 375 (200 %); Profile, Settings, Trends at 320 px.
Open questions in the harness (`OPEN_QUESTIONS`): desktop targets 24–43 px with a mouse; 11 px chart labels.

## In progress
- Fixes, one at a time; re-run the relevant config after each.

## Commands
- `python3 tools/e2e/a11y.py` (report in `<tmp>/kidney-health-e2e/a11y/report.json`); `--only 375-light --parts large`
- pytest: `<venv312>/bin/python -m pytest -q tests/test_e2e_tools.py tests/test_layout_ui.py`
