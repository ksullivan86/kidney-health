# visual-qa: a look at every screen (Status: complete)

Task: build the demo, drive it with Playwright, look at every screen at 375x812 and 1280x800 in light and dark, fix the small
layout bugs, report the rest. Screenshots stay outside the repository (the four README ones are the exception: see below).

## How to reproduce

* Build: `python scripts/build_preview.py --pages <tmpdir>`, serve it (`python -m http.server` in that folder, or the helpers in
  `tools/e2e/readme_shots.py`), drive it with Playwright (`executable_path=khserver.chromium_executable()`, `--no-sandbox`).
* My scratch scripts and screenshots are in the session scratchpad (`.../scratchpad/vq/*.py`, `.../scratchpad/final/`). They are
  not in the repository. The audit script flags sideways scroll, text over text, controls over controls, clipped text and SVG text
  that overlaps; it reports false positives where a sheet body scrolls under its header and footer.
* The checks that stay: `tests/test_layout_ui.py` (source checks) and probes 7 and 8 in `tools/e2e/sandbox.py` (the header at 19
  widths with every optional part on and off, the Plan week's badges). Run against the build before the fixes, the two probes
  report the cut name, the overlaps and the sideways scroll; against the fixed build they report nothing.

## Found and fixed

* Header, phone: the app name beside the Preview pill showed as "K..." (375-390 px) or nothing. Now whole or hidden (still read
  aloud); the logo and pill keep their room. `base.css`.
* Header, 720-880 px: with the Preview pill, the admin shield and the Ask tab the six tab words and four icons ran past the window
  (the page scrolled sideways). Only the open tab keeps its word there. `base.css`.
* Header, 960 px and wider: the name was cut to "K..." next to the pill; the pill sat under the Today tab around 820 px. Same rules.
* Header: the offline badge in its long form pushed the gear off the page below 1000 px. `device.css`.
* Plan week, desktop: the TODAY badge stuck out of its day card. `plan.css`.
* Warnings and flags on a phone: the 44 px handbook link spread the lines of the text above it apart; now it has its own line.
  Its arrow no longer jumps to the right edge when the link wraps (inline-block, no-break space before the arrow). `touch.css`,
  `base.css`.
* Blood pressure sheet, Settings goal, Admin invite: two boxes side by side sat at different heights when one label wrapped.
  "How to measure" spread its sentence. `base.css` (`align-end`), `body.css`, `index.html`, `body.js`, `settings.js`.
* Copy a day ("Eaten and planne") and Lab results ("e.g. before dialys"): the box takes the whole row on a phone. `span-2-narrow`.
* Lab results: the two handbook links were joined by a dot that was left at a line end; now a wrapping row. `labs.js`, `labs.css`.
* Lab results import review: the date was beside a short value and above a long one; on a phone it is always above. `labs.css`.
* "Import from a patient portal file (C-CDA .xml)": broke at the hyphen on a phone. A no-break span. `index.html`.
* Settings: Export / Keep my data buttons and Sign out everywhere else touched the element above them. `settings.css`.
* Trends with no targets: the message card had no padding (`.empty-state` came after `.card`). `today.css`.
* Today with an empty log ("Choose them in Profile") and What fits now ("Check them in Profile"): a 44 px link button beside the words
  spread their lines apart; on a phone it now has its own line, still 44 px. `touch.css`. (A try with inline links was refused by
  the sandbox's 44 px tap check, so it was dropped.) "How to make the shortcut" in Settings is an inline link whose padding keeps
  44 px. `settings.css`.
* What fits now, "Meals that fit": a long chip name was cut at one line; two lines now. `guidance.css`.

## Left, with reasons

* Header, phone, admin or Preview: the app name is hidden (logo only, and the pill in the demo). With the four icons and the pill
  there is no room for a 128 px name. A decision for a person: a smaller pill, or moving the Learn link into Settings, would free it.
* Profile, Daily targets (and About you): in two-column rows, boxes sit at different heights when one label wraps. The rows have
  hints under the box, so `align-items: end` does not fit; a CSS subgrid worked in a try but crowded two hint paragraphs together
  (screenshot in the scratchpad). Left as it is.
* Today with an empty log: "...enter them in Settings." ends with a 44 px link button, so the full stop sits a little apart and
  the lines are a little loose. Cosmetic; changing the sentence is not a layout fix.
* `tools/e2e/import_walk.py` fails four checks (the preview text now ends "..., 0 weights, 0 blood pressure readings"). It fails the
  same four on the commit before this work: a stale expectation from the weight and blood pressure part A.
* Admin: an input that shows a long value (the Open Food Facts contact address) cuts it inside the box. Normal for an input.
* Disabled primary buttons in dark mode (Use this plan, Keep my data in this browser) are dim by design.
* A malformed C-CDA file makes Chromium draw an error document whose inline styles the CSP refuses: two console errors that
  `tools/e2e/regress.py` already expects.

## Checks (all on the final tree)

* `python -m pytest -q`: 5,652 passed, none failed or skipped.
* `node tests/js/run_vectors.mjs`: 12,928 checks passed. Parity vectors unchanged.
* `ruff check .` and `python scripts/build_handbook.py --check`: clean.
* `tools/e2e/sandbox.py`: 17 walks, 2 sweeps and the probes, 0 issues (before the work: 0, because nothing looked at the header).
* `body.py` 360 pass; `symptoms.py` 67; `ask.py` 144; `device.py` 187; `push.py` 97; `visitprep.py` 114; `regress.py` 565, all
  with no failure. `import_walk.py`: 105 pass, 4 fail, the same four as on the commit before this work.
* README screenshots: taken again with `tools/e2e/readme_shots.py` (they showed the cut name and the spread lines).
