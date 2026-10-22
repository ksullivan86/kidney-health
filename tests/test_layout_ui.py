"""Layout rules found by looking at every screen of the demo (docs/dev/progress/visual-qa.md).

Each test pins one fix in the stylesheets or the page, so the bug does not come back. They are source checks; the measuring is
done in a browser: ``tools/e2e/sandbox.py`` (probes 7 and 8) checks the header at 19 widths and the Plan week's badges, and its walk
checks overflow, contrast and tap targets on every screen.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def read(*parts: str) -> str:
    return STATIC.joinpath(*parts).read_text(encoding="utf-8")


BASE = read("css", "base.css")
TOUCH = read("css", "touch.css")
DEVICE = read("css", "device.css")
PLAN = read("css", "plan.css")
SETTINGS_CSS = read("css", "settings.css")
BODY_CSS = read("css", "body.css")
LABS_CSS = read("css", "labs.css")
LABS_JS = read("js", "views", "labs.js")
INDEX = read("index.html")


def block(css: str, opener: str) -> str:
    """The text between the braces of the first rule (or at-rule) that starts with ``opener``, nested braces included."""
    start = css.index(opener)
    depth, i = 0, css.index("{", start)
    begin = i + 1
    while True:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[begin:i]
        i += 1


def rule(css: str, selector: str) -> str:
    """The declarations of the rule whose selector list is exactly ``selector``."""
    match = re.search(rf"(?:^|[\n}}])\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match, f"no rule for {selector}"
    return match.group(1)


# ------------------------------------------------------------------------------------------------- the header
def test_the_app_name_is_whole_or_hidden_never_cut_to_a_letter() -> None:
    """At 375 to 390 px the name beside the Preview pill showed as "K…". The brand is a size container: below a width the name leaves
    the screen but stays in the page for screen readers (clipped, not display: none)."""
    assert "container: brand / inline-size" in rule(BASE, ".brand")
    for opener in ("@container brand (max-width: 191.98px)", "@container brand (max-width: 279.98px)"):
        inner = block(BASE, opener)
        assert ".brand-name" in inner and "clip: rect(0 0 0 0)" in inner and "position: absolute" in inner
        assert "display: none" not in inner, "the name must stay readable by a screen reader"
    # with the Preview pill the name needs more room than without it
    assert ".brand:has(#brand-pill:not([hidden])) .brand-name" in block(BASE, "@container brand (max-width: 279.98px)")
    # the logo and the pill always keep their room
    assert "min-width: 28px" in rule(BASE, ".brand") and "min-width: 112px" in rule(BASE, ".brand:has(#brand-pill:not([hidden]))")


def test_the_header_makes_room_for_six_tabs_and_four_icons_without_scrolling_sideways() -> None:
    """Between 720 and 880 px the six tab words and the four icons did not fit: the page scrolled sideways. Only the open tab keeps its
    word there; the others are icons that a screen reader still names."""
    narrow = block(BASE, "@media (min-width: 720px) and (max-width: 879.98px)")
    assert '.tab:not([aria-selected="true"]) > span' in narrow and "clip: rect(0 0 0 0)" in narrow
    assert "display: none" not in narrow
    assert "max-width: 959.98px" not in BASE, "the old rule that hid the app name up to 960 px is gone"
    # the offline badge is its short form until the header has room for the long one
    assert ".sync-badge-long { display: none; }" in block(DEVICE, "@media (max-width: 999.98px)")


def test_the_plan_days_badge_wraps_inside_its_day() -> None:
    assert "flex-wrap: wrap" in rule(PLAN, ".plan-day-head")


# ------------------------------------------------------------------------------------------ handbook links
def test_a_handbook_link_stays_at_the_end_of_its_words_and_beside_its_arrow() -> None:
    """On a touch screen the link is 44 px tall. As a flex box its arrow was pushed to the right edge when the words wrapped; and
    inline in a warning it spread the lines of the text above it apart."""
    phone = block(TOUCH, "@media (pointer: coarse), (max-width: 719.98px)")
    declarations = rule(phone, ".learn-more")
    assert "display: inline-block" in declarations and "min-height: var(--tap)" in declarations
    assert "inline-flex" not in declarations
    own_line = rule(phone, ".alert .learn-more, .body-flag .learn-more, .sym-flag .learn-more")
    assert "display: block" in own_line and "width: fit-content" in own_line
    # the arrow is joined to the last word by a no-break space
    assert r'content: "\00a0\2197"' in BASE and r'content: " \2197"' not in BASE


def test_the_how_to_measure_link_sits_in_its_sentence() -> None:
    declarations = rule(BODY_CSS, ".body-bp-hint a.learn-more")
    assert "display: inline" in declarations and "min-height: 0" in declarations


def test_the_two_lab_links_are_a_flex_row_not_words_joined_by_a_dot() -> None:
    assert "' · '" not in LABS_JS.split("const links = [learnLink('egfr'")[1].split("\n")[1]
    assert "class: 'learn-links'" in LABS_JS
    declarations = rule(LABS_CSS, ".learn-links")
    assert "display: flex" in declarations and "flex-wrap: wrap" in declarations


# ------------------------------------------------------------------------------------------- forms and sheets
def test_the_two_blood_pressure_boxes_line_up_when_one_label_wraps() -> None:
    assert "align-items: end" in rule(BASE, ".form-grid.align-end")
    sheet = INDEX[INDEX.index('<dialog id="sheet-bp"'):INDEX.index("</dialog>", INDEX.index('<dialog id="sheet-bp"'))]
    assert '<div class="form-grid align-end">' in sheet and sheet.index("bp-systolic") < sheet.index("bp-diastolic") < sheet.index("span-2")


def test_a_field_that_would_be_cut_in_half_a_row_takes_the_whole_row_on_a_phone() -> None:
    assert "grid-column: 1 / -1" in rule(block(BASE, "@media (max-width: 480px) { .form-grid .span-2-narrow"), ".form-grid .span-2-narrow")
    for field in ("lab-note", "copy-include"):  # "e.g. before dialys", "Eaten and planne"
        assert re.search(rf'<div class="field span-2-narrow">\s*<label for="{field}">', INDEX), field


# ---------------------------------------------------------------------------------------------------- settings
def test_settings_blocks_that_stack_buttons_leave_a_gap() -> None:
    declarations = rule(SETTINGS_CSS, ".data-block, #set-devices")
    assert "display: flex" in declarations and "flex-direction: column" in declarations and re.search(r"gap: \d+px", declarations)
