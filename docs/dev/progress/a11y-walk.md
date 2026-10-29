Status: complete

# a11y-walk: automated accessibility check and fixes

Task: build `tools/e2e/a11y.py` (keyboard, names, large text, contrast at 375×812 and 1280×800, light and dark,
real server on port 8099), fix what it finds in `app/static`, docs (tools/e2e/README.md, docs/maintainers.md,
CHANGELOG.md Unreleased). Commit locally only, never push.

## Done
- Merged `claude/adoring-sagan-th5swr` into the worktree branch.
- a935357 `tools/e2e/a11y.py`; README row; `tests/test_e2e_tools.py` HARNESSES.
- 2326187 keyboard fixes; 52b8ab1 large text and contrast fixes (details below). Static tests in tests/test_layout_ui.py,
  each shown to fail on the CSS before the fix (scratch script loading the module with `git show HEAD:<css>`).
- Docs: tools/e2e/README.md, docs/maintainers.md step 2 (run a11y.py first) and step 3 list, CHANGELOG Unreleased,
  ARCHITECTURE.md (text size and keyboard bullet), handbook settings-and-keys.md ("Bigger text").

## Results
- Before (a935357, all configs): 650 passed, 134 failed. Findings: focus-visible 28, focus-obscured 72, grow 1115,
  reflow 6, spill 48, clipped 18, target 4, contrast 4 (later harness checks would have found more spill).
  Names, labels, images, live regions, sheet focus/Escape/close/return all passed.
- After (all parts, all configs): 784 passed, 0 failed, 259 open (3 questions).
- No regressions at normal size: `regress.py --no-pytest --only 375-light` 142/0, `--only 1280-dark --no-probes` 141/0;
  `sandbox.py --only top-phone-light-none,top-desktop-dark-none --no-sweep`: same Trends harness errors as on the old code
  (sandbox's own selector `#charts .chart-card svg` is stale; not from these changes), and the old meal-source tap-target
  issue is gone.

## Fixes
1. Focus under the phone tab bar: `html { scroll-padding-top/bottom }`.
2. Calendar button in date/time fields: `input:focus-within` outline.
3. Meal / "when" radios placed outside their group: `.meal-seg`, `.body-seg` position relative.
4. Text did not grow: `body { font-size: 1rem; overflow-wrap: break-word }`; rem max-widths for the meal chip and date field.
5. `input[type=url]` without field style; `textarea::placeholder` colour (dark: 3.9:1).
6. Large-text layout: `.btn` wraps; `min-width: min(100%, max-content)`; auto-fit grids (`.meal-seg`, `.form-grid`,
   `.strip-grid`, `.plan-grid`); wrapping rows (`.sheet-foot`, `.inline-row`, `.meal-head`, `.entry-planned`, `.period-name`,
   `.strip-label`); `.stat-value` wraps; `.status-msg` flex-shrink 0 (Scan message squashed to 0 px).

## Open questions (OPEN_QUESTIONS in the harness)
- Mouse targets 24–43 px at 200 % (44 px is the rule only on touch/phone widths).
- 11 px chart labels in SVG do not grow.
- Bottom tab bar words at 320 px + 200 %.
- Not checked by the harness, seen by eye: field borders (`--border` #d7dbe2 on white, 1.4:1) are below the 3:1 for
  non-text contrast (WCAG 1.4.11); changing them is a design decision.

## Next
- None. Full `python -m pytest` passed (exit 0, no failures) on dca1ea3.

## Commands
- `python3 tools/e2e/a11y.py` (report in `<tmp>/kidney-health-e2e/a11y/report.json`); `--only 375-light --parts large`; `--shots`
- pytest: `<venv312>/bin/python -m pytest -q tests/test_e2e_tools.py tests/test_layout_ui.py`
- The disk filled up once during the work (other sessions too): keep `--shots` off and delete old work directories.
