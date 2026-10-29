Status: complete

# control-borders: field and toggle borders at 3:1, and the sandbox Trends error

Task (from the a11y walk, `docs/dev/progress/a11y-walk.md`): field borders were `--border` #d7dbe2, 1.4:1 on white.
WCAG 1.4.11 asks 3:1. Raise them in light and dark, only for form controls; add a browser check to
`tools/e2e/a11y.py` and a static test; check the handbook search field. Second: find why `tools/e2e/sandbox.py`
reports "Cannot read properties of null" on Trends. Commit locally only, never push.

## Done
- Started on 8a532ea (fast-forwarded to origin/claude/adoring-sagan-th5swr).
- Field and choice edges: new token `--control-border` (light #7d8590, dark #76808c) in the three token blocks of
  `base.css`; used by the text-field rule (base.css), `input[type=password]` (auth.css), `input[type=time]` (body.css),
  `input[type=month]` (profile.css), `.segmented` (group edge), `.body-seg label`, `.wd-check > span`.
- `tools/e2e/a11y.py`: `CONTROLS_JS` + `Walk.native_edges` (kind `control-contrast`, part of `contrast`). Old CSS:
  152 passed, 40 failed (all control-contrast). New CSS: 192 passed, 0 failed.
- Native checkboxes and radios (measured on pixels): light 4.54:1 (checkbox #767676) and 4.35:1 (radio #797979) on white;
  dark 4.49:1 and 4.37:1 on #1b1f24. No change needed.
- Static tests: `tests/test_layout_ui.py::test_the_edge_of_every_field_and_choice_box_stands_out_3_to_1` (failed on the old
  CSS with every rule listed, 1.22 to 1.68:1), `test_cards_and_dividers_keep_their_light_line`;
  `tests/test_e2e_tools.py::test_a11y_reads_the_pixels_of_a_browser_picture` (the PNG reader, all five row filters).
- Handbook search field (built with `<scratchpad>/hbvenv/bin/mkdocs build -d <scratchpad>/borders-agent/hb-site`, measured
  with `<scratchpad>/borders-agent/hb_probe2.py`): in the header 1.47:1 fill on teal, no edge; open dark 2.43:1; phone
  open: same colour as the results. Fix in `handbook/docs/stylesheets/extra.css`: outline white 70 % (4.1:1 on teal) from
  60em, a bottom line `--md-default-fg-color--light` below 60em (4.42:1 light, 4.06:1 dark on the results bar).
  Test `tests/test_handbook_content.py::test_the_search_field_has_an_edge_that_stands_out_3_to_1` (failed before).
- Sandbox: cause is the harness. Pressing 7 d sets the title at once and empties #charts ("Loading food trends…"); the
  wait predicate read `document.querySelector('#charts .chart-card svg').querySelectorAll` on null and threw. The
  page error's stack is Playwright's `UtilityScript.evaluate` predicate, not app code (probe
  `<scratchpad>/borders-agent/sb_probe2.py`). Fix: `?.` in the wait. Before: 4 and 6 issues; after: 0 and 0.

- Docs: CHANGELOG Unreleased (two lines for people, one for maintainers), ARCHITECTURE.md ("Field edges" bullet next to
  "Text size and keyboard"), tools/e2e/README.md a11y row.
- Checks on the final tree: full `a11y.py` 828 passed, 0 failed, 259 open (was 784/0 before the new check);
  `regress.py --no-pytest --only 375-light` 142 passed, 0 failed; `node --test tests/js/*.test.mjs` 166 passed;
  `run_vectors.mjs` passed; pytest on every `tests/test_*ui*.py`, layout, frontend shell, handbook, learn, e2e tools and
  preview build files: 1404 passed. Full pytest not run (asked not to).

## Next
- None.

## Decisions
- `--border` stays for cards, lists and dividers (also the lines between choices inside a row). Buttons
  (`.btn.secondary`, chips, steppers, the "More like this" toggles) keep `--border`: their words identify them.
- Targets: 3:1 on `--bg`, `--surface` and `--surface-2` in both themes (fields sit on the page, cards, sheets and grey panels).

## Commands
- Contrast of a colour: `python3 <scratchpad>/borders-agent/cr.py "#light1,#light2" "#dark1"`
- `python3 tools/e2e/a11y.py --port 8191 --parts contrast --out <scratchpad>/borders-agent/a11y-new`
- `python3 tools/e2e/sandbox.py --only top-phone-light-none,top-desktop-dark-none --no-sweep --no-probes --workers 2 --port 8187 --out <scratchpad>/borders-agent/sb-after` (delete `shots/` after)
- `<venv312>/bin/python -m pytest -q tests/test_layout_ui.py tests/test_e2e_tools.py tests/test_handbook_content.py --basetemp=<scratchpad>/borders-agent/pt`
