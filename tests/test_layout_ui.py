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


# ------------------------------------------------------------------------------------------------- large text (tools/e2e/a11y.py)
ADD_CSS = read("css", "add.css")
SHEETS_CSS = read("css", "sheets.css")
TRENDS_CSS = read("css", "trends.css")
AI_CSS = read("css", "ai.css")


def test_text_grows_with_the_size_the_person_chose() -> None:
    """The page's text was 16 px whatever the browser's text size: a size in px ignores it. 1rem is 16 px by default."""
    body = rule(BASE, "body")
    assert "font-size: 1rem" in body and "font-size: 16px" not in body
    assert "overflow-wrap: break-word" in body  # a word longer than its line breaks instead of running out of its box
    assert not re.search(r"font-size:\s*\d+(\.\d+)?px", BASE + TODAY_CSS + ADD_CSS + SHEETS_CSS + PLAN + SETTINGS_CSS), \
        "text sizes in px do not grow (the 11 px chart labels are an open question in tools/e2e/a11y.py)"
    assert "max-width: 16.25rem" in ADD_CSS and "max-width: 260px" not in ADD_CSS  # a saved-meal shortcut grows with its words
    assert ".date-input { max-width: 11.875rem;" in TODAY_CSS


def test_every_text_field_has_the_field_style_and_a_readable_placeholder() -> None:
    """The web address field of a saved meal had no field style: 29 px tall, and a grey box in the dark theme. A textarea's
    placeholder had the browser's grey, 3.9:1 on the dark surface."""
    assert 'input[type="date"], input[type="url"], select, textarea {' in BASE
    assert "input::placeholder, textarea::placeholder { color: var(--text-3);" in BASE


def test_long_button_labels_wrap_instead_of_running_off_the_screen() -> None:
    assert "white-space: nowrap" not in rule(BASE, ".btn")
    assert "text-align: center" in rule(BASE, ".btn")
    for css, selector in ((ADD_CSS, ".add-actions .btn"), (AI_CSS, ".ai-add .btn"), (GUIDANCE_CSS, ".guidance-actions .btn")):
        assert "min-width: min(100%, max-content)" in rule(css, selector), selector
    assert "flex-wrap: wrap" in rule(SHEETS_CSS, ".sheet-foot")
    assert "flex-wrap: wrap" in rule(SETTINGS_CSS, ".inline-row")


def test_rows_and_grids_make_room_for_large_text() -> None:
    """At 200 % text: the meal choices lost "Dinner" and "Snack", Profile's labels ran out of their column, the daily totals and the
    Trends summary made the page scroll sideways, and the week on Plan spilled its numbers out of each day."""
    assert "repeat(auto-fit, minmax(min(100%, 4.25rem), 1fr))" in rule(BASE, ".meal-seg")
    assert "repeat(auto-fit, minmax(min(100%, max(10rem, calc(50% - 6px))), 1fr))" in rule(BASE, ".form-grid")
    assert "white-space: nowrap" not in rule(TODAY_CSS, ".stat-value")
    assert "flex-wrap: wrap" in rule(TODAY_CSS, ".strip-label") and "auto-fit" in rule(TODAY_CSS, ".strip-grid")
    assert "flex-wrap: wrap" in rule(TODAY_CSS, ".entry-planned")
    assert "flex-wrap: wrap" in rule(TRENDS_CSS, ".period-name")
    assert "repeat(auto-fit, minmax(min(100%, 5.5rem), 1fr))" in block(PLAN, "@media (min-width: 720px) { .plan-grid")


def test_a_message_in_a_sheet_keeps_its_height() -> None:
    """In the Scan sheet with large text, "No camera was found" was squashed to 0 px and printed over the buttons."""
    assert "flex-shrink: 0" in rule(SHEETS_CSS, ".status-msg")


# ------------------------------------------------------------------------------------------------- control edges
AUTH_CSS = read("css", "auth.css")
THEMES = {  # the light tokens, and the two places the dark tokens are set (the device's choice, the person's choice)
    "light": block(BASE, ":root {"),
    "dark (device)": block(block(BASE, "@media (prefers-color-scheme: dark)"), ':root:not([data-theme="light"])'),
    "dark (chosen)": block(BASE, ':root[data-theme="dark"] {'),
}
# The rules that draw the edge of a field, a select, or the box of a hidden radio or checkbox.
CONTROL_EDGES = (
    (BASE, 'input[type="text"], input[type="number"], input[type="search"], input[type="date"], input[type="url"], select, textarea'),
    (AUTH_CSS, 'input[type="password"]'),
    (BODY_CSS, 'input[type="time"]'),
    (PROFILE_CSS, 'input[type="month"]'),
    (BASE, ".segmented"),  # the edge of a row of choices (meal, eaten or planned, Trends' range)
    (BODY_CSS, ".body-seg label"),  # when a weight was taken
    (PROFILE_CSS, ".wd-check > span"),  # dialysis weekdays
)


def token(theme: str, name: str) -> str:
    """A colour token as the theme sets it; a dark theme that does not set it keeps the light value."""
    for css in (THEMES[theme], THEMES["light"]):
        match = re.search(rf"(?<![\w-]){re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", css)
        if match:
            return match.group(1)
    raise AssertionError(f"no {name} in the {theme} tokens")


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two #rrggbb colours."""
    def lum(hex_colour: str) -> float:
        c = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def test_the_edge_of_every_field_and_choice_box_stands_out_3_to_1() -> None:
    """Fields had the card line as their edge: #d7dbe2 on white is 1.4:1, #353d47 on the dark card 1.5:1. WCAG 1.4.11 asks 3:1
    against the colours next to the control: the page, a card or a sheet, and the grey panels. tools/e2e/a11y.py measures the
    same in the browser, and the browser's own checkboxes and radios too (4.3:1 or more in both themes)."""
    low = []
    for css, selector in CONTROL_EDGES:
        match = re.search(r"border: 1px solid var\((--[\w-]+)\)", rule(css, selector))
        assert match, f"{selector} has no 1 px edge"
        for theme in THEMES:
            edge = token(theme, match.group(1))
            for behind in ("--bg", "--surface", "--surface-2"):
                ratio = contrast(edge, token(theme, behind))
                if ratio < 3:
                    low.append(f"{selector} ({theme}): {match.group(1)} {edge} on {behind} {token(theme, behind)} is {ratio:.2f}:1")
    assert not low, "\n".join(low)


def test_cards_and_dividers_keep_their_light_line() -> None:
    """Only the controls got the stronger edge: cards, lists and the lines between choices stay as light as before."""
    assert "border: 1px solid var(--border)" in rule(BASE, ".card")
    assert "border-left: 1px solid var(--border)" in rule(BASE, ".meal-seg label + input + label")
    assert "border-left: 1px solid var(--border)" in rule(BASE, ".segmented .seg + .seg")
    for theme in THEMES:
        assert contrast(token(theme, "--border"), token(theme, "--surface")) < 2, theme
