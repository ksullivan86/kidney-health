"""Layout rules found by looking at every screen of the demo (CHANGELOG.md 0.5.0, "Tidier screens"; what is left is in docs/ROADMAP.md).

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
    own_line = rule(phone, ".alert .learn-more, .warning .learn-more, .body-flag .learn-more, .sym-flag .learn-more")
    assert "display: block" in own_line and "width: fit-content" in own_line
    inline = rule(SETTINGS_CSS, "#set-push-recipe .learn-more")  # "How to make the shortcut — the handbook has the steps ..."
    assert "display: inline" in inline and "min-height: 0" in inline
    assert re.search(r"padding: 1[5-9]px 0", inline), "the padding (not the box) keeps the touch target at 44 px"
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


# ------------------------------------------------------------------------------------- the rest of the screens
TODAY_CSS = read("css", "today.css")
GUIDANCE_CSS = read("css", "guidance.css")
PROFILE_CSS = read("css", "profile.css")
TODAY_JS = read("js", "views", "today.js")
BODY_JS = read("js", "views", "body.js")


def test_a_message_that_is_its_own_card_keeps_the_cards_padding() -> None:
    """Trends with no targets showed its words touching the card's border: `.empty-state` (6px 0) came after `.card`."""
    assert "padding: 14px 16px" in rule(TODAY_CSS, ".card.empty-state")
    assert TODAY_CSS.index(".card.empty-state") > TODAY_CSS.index(".empty-state {")


def test_a_link_button_after_a_sentence_takes_its_own_line_at_a_full_44_px() -> None:
    """On a phone the 44 px box of a link button beside words spread their lines apart. Two buttons end a lead-in sentence ("Using the
    targets in your profile ... Check them in Profile", "Your CKD stage ... Choose them in Profile"): on a touch screen each is on its own line."""
    phone = block(TOUCH, "@media (pointer: coarse), (max-width: 719.98px)")
    declarations = rule(phone, ".profile-choose-note .link-btn, .g-targets .link-btn")
    assert "display: flex" in declarations
    assert "link-btn inline" not in TODAY_JS and "link-btn inline" not in read("js", "views", "guidance.js")


def test_two_boxes_side_by_side_line_up_in_settings_too() -> None:
    """Settings → blood pressure goal (top and bottom number) and Admin → Invite someone (Role, Link works for (days))."""
    assert "h('div', { class: 'form-grid align-end' },\n        h('div', { class: 'field' }, h('label', { for: 'set-body-goal-systolic' }" in BODY_JS
    settings = read("js", "views", "settings.js")
    assert "h('div', { class: 'form-grid align-end' },\n          h('div', { class: 'field' }, h('label', { for: roleId }, 'Role')" in settings


def test_a_long_saved_meal_name_in_meals_that_fit_wraps_to_two_lines() -> None:
    declarations = rule(GUIDANCE_CSS, ".g-meal-chips .meal-chip-name")
    assert "white-space: normal" in declarations and "-webkit-line-clamp: 2" in declarations


def test_lab_rows_stack_the_date_above_the_value_on_a_phone() -> None:
    inner = block(LABS_CSS, "@media (max-width: 480px)")
    assert ".lab-row-main" in inner and ".lab-import-list label" in inner and "flex-direction: column" in inner


def test_c_cda_is_not_broken_at_its_hyphen() -> None:
    assert 'Import from a patient portal file (<span class="nobr">C-CDA .xml</span>)' in INDEX
    assert "white-space: nowrap" in rule(BASE, ".nobr")


# ------------------------------------------------------------------------------------------------- keyboard (tools/e2e/a11y.py)
def test_a_control_reached_with_tab_is_not_hidden_under_the_tab_bar() -> None:
    """On a phone, Tab scrolled the next button just far enough to sit under the fixed tab bar at the bottom (WCAG 2.4.11).
    The page keeps room for the bar and for the sticky header when it scrolls a control into view."""
    padding = re.search(r"html \{ (scroll-padding-top:[^}]*)\}", BASE)
    assert padding, "html needs scroll-padding"
    assert "scroll-padding-bottom: calc(var(--tabbar-h)" in padding.group(1) and "scroll-padding-top: calc(64px" in padding.group(1)


def test_the_calendar_button_inside_a_date_field_shows_the_focus_outline() -> None:
    """Tab stops on the calendar button inside a date or time field, where the field does not match :focus."""
    assert "outline: 3px solid var(--focus)" in rule(BASE, "input:focus, input:focus-within, select:focus")


def test_a_hidden_radio_stays_inside_its_group() -> None:
    """The radios behind the meal and "when" choices are absolutely placed; without a positioned group they sat elsewhere on the
    page, and Tab scrolled to them instead of to their labels."""
    assert "position: relative" in rule(BASE, ".meal-seg")
    assert "position: relative" in rule(BODY_CSS, ".body-seg")
