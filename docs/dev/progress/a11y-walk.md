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

## Fixes done (commits)
- 2326187 keyboard: scroll-padding (tab bar/header), `input:focus-within`, `.meal-seg`/`.body-seg` position relative.
  Keyboard part re-run on 375-light and 1280-dark: 164 passed, 0 failed. Static tests in tests/test_layout_ui.py fail on the old CSS.
- 52b8ab1 large text + contrast: body 1rem + break-word, url field style, textarea placeholder, `.btn` wraps,
  `min(100%, max-content)`, auto-fit grids (`.meal-seg`, `.form-grid`, `.strip-grid`, `.plan-grid`), wrap rows (sheet foot,
  inline-row, meal-head, entry-planned, period-name, strip-label), `.status-msg` flex-shrink 0, rem max-widths (meal chip,
  date input). Large part re-run on all configs: 280 passed, 0 failed. Harness got: text-grows check, words out of their
  control / off the window, field text cut, 0.15em vertical glyph tolerance, `--shots` (screenshots off by default: the disk
  filled up once).
- Open questions (in OPEN_QUESTIONS): mouse targets 24–43 px; 11 px chart labels; tab bar words at 320 px + 200 %.

## In progress
- Full run of all parts; then docs (README row done; maintainers.md, CHANGELOG).

## Commands
- `python3 tools/e2e/a11y.py` (report in `<tmp>/kidney-health-e2e/a11y/report.json`); `--only 375-light --parts large`
- pytest: `<venv312>/bin/python -m pytest -q tests/test_e2e_tools.py tests/test_layout_ui.py`
