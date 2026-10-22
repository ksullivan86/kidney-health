# visual-qa: a look at every screen (Status: in progress)

Task: build the demo, drive it with Playwright, look at every screen at 375x812 and 1280x800 in light and dark, fix the small
layout bugs, report the rest. Screenshots stay outside the repository.

## How to reproduce

* Build: `python scripts/build_preview.py --pages <tmpdir>`, serve it (`python -m http.server` in that folder, or the helpers in
  `tools/e2e/readme_shots.py`), drive it with Playwright (`executable_path=khserver.chromium_executable()`, `--no-sandbox`).
* My scratch scripts and screenshots are in the session scratchpad (`.../scratchpad/vq/*.py`, `.../scratchpad/vqshots*/`). They are
  not in the repository. The audit script flags sideways scroll, text over text, controls over controls, clipped text and SVG text
  that overlaps.
* The checks that stay: `tests/test_layout_ui.py` (source checks) and probes 7 and 8 in `tools/e2e/sandbox.py` (header at 19
  widths, Plan badges).

## Found and fixed

* Header, phone: the app name beside the Preview pill showed as "K..." (375-390 px) or nothing. Now whole or hidden (still read
  aloud); the logo and pill keep their room. `base.css`.
* Header, 720-880 px: with the Preview pill, the admin shield and the Ask tab the six tab words and four icons ran past the window
  (the page scrolled sideways). Only the open tab keeps its word there. `base.css`.
* Header, 960 px and wider: the Preview pill sat under the Today tab (same cause). Fixed by the same rules.
* Header: the offline badge in its long form pushed the gear off the page below 1000 px. `device.css`.
* Plan week, desktop: the TODAY badge stuck out of its day card. `plan.css`.
* Warnings and flags on a phone: the 44 px handbook link spread the lines of the text above it apart; now it has its own line.
  Its arrow no longer jumps to the right edge when the link wraps (inline-block, no-break space before the arrow). `touch.css`,
  `base.css`.
* Blood pressure sheet: the top and bottom number boxes sat at different heights; "How to measure" spread its sentence. `body.css`,
  `index.html`.
* Copy a day: the Include select showed "Eaten and planne"; Lab results: the note box showed "e.g. before dialys". Both take the
  whole row on a phone. `base.css`, `index.html`.
* Lab results: the two handbook links were joined by a dot that was left at a line end; now a wrapping row. `labs.js`, `labs.css`.
* Settings: Export / Keep my data buttons, and Sign out everywhere else, touched the element above them. `settings.css`.

## Left, with reasons

* What fits now, "Meals that fit" chips: a long chip name is cut with an ellipsis ("Your usual dinner: egg white, bread, bel...").
  The chip is a button; the full name is not shown anywhere else on the phone. Not changed: needs a design choice.
* Admin: an input that shows a long value (the Open Food Facts contact URL) cuts it inside the box. Normal for an input.
* Disabled primary buttons in dark mode (Use this plan, Keep my data in this browser) are dim by design.

## Next

Sheets and dialogs after the fixes (a second look), the README screenshots are unchanged, CHANGELOG, final checks.
