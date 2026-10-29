"""The weight and blood pressure screens in the app's pages (ARCHITECTURE.md "Weight and blood pressure", note 10 Part B): the shell, the
Today card and its two sheets, the Trends charts, the Settings section, the Profile lines, the visit prep section and the files that draw
them. Static checks of what the browser is given; the flows are run in Chromium by ``tools/e2e/body.py``, the numbers by
``tests/test_body_ui_numbers.py`` and the demo's answers by ``tests/data/body_vectors.json``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import body
from app.guidance import topics

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def read(*parts: str) -> str:
    return (STATIC.joinpath(*parts)).read_text(encoding="utf-8")


INDEX = read("index.html")
SW = read("sw.js")
VIEW = read("js", "views", "body.js")
TRENDS_VIEW = read("js", "views", "body_trends.js")
ENGINE = read("js", "engine", "body_ui.js")
CSS = read("css", "body.css")
VISIT_CSS = read("css", "visit.css")
TODAY = read("js", "views", "today.js")
TRENDS = read("js", "views", "trends.js")
PROFILE = read("js", "views", "profile.js")
SETTINGS = read("js", "views", "settings.js")
VISIT = read("js", "views", "visit.js")
VISITPREP = read("js", "engine", "visitprep.js")
CORE = read("js", "core.js")
CODE = {"view": VIEW, "trends": TRENDS_VIEW, "engine": ENGINE}
PAGE = ROOT / "handbook" / "docs" / "app" / "weight-and-blood-pressure.md"


def strip_comments(js: str) -> str:
    return re.sub(r"^\s*//.*$|(?<![:'\"\\])//[^\n]*", "", re.sub(r"/\*.*?\*/", "", js, flags=re.S), flags=re.M)


VIEW_CODE, TRENDS_CODE, ENGINE_CODE = strip_comments(VIEW), strip_comments(TRENDS_VIEW), strip_comments(ENGINE)


def section(start: str, end: str) -> str:
    begin = INDEX.index(start)
    return INDEX[begin:INDEX.index(end, begin)]


def scripts() -> list[str]:
    return re.findall(r'<script src="([^"]+)"', INDEX)


TODAY_CARD = section('<section class="card body-card" id="body-today"', "</section>")
TRENDS_CARD = section('<section class="card body-card" id="body-trends"', "</section>")
WEIGHT_SHEET = section('<dialog id="sheet-weight"', "</dialog>")
BP_SHEET = section('<dialog id="sheet-bp"', "</dialog>")
SETTINGS_SECTION = section('<section class="card settings-section" id="set-body"', "</section>")


# --------------------------------------------------------------------------- the shell
def test_the_files_are_in_the_shell_in_dependency_order_and_in_the_service_worker():
    s = scripts()
    assert s.index("js/engine/rules.js") < s.index("js/engine/body.js") < s.index("js/engine/visitprep.js") < s.index("js/engine/body_ui.js") < s.index("js/core.js")
    assert s.index("js/views/trends.js") < s.index("js/views/symptoms.js") < s.index("js/views/body.js") < s.index("js/views/body_trends.js") < s.index("js/main.js")
    assert s.index("js/learn.js") < s.index("js/views/body.js") and s.index("js/views/body_trends.js") < s.index("js/views/visit.js")
    assert 'href="css/body.css"' in INDEX and INDEX.index("css/symptoms.css") < INDEX.index("css/body.css") < INDEX.index("css/touch.css")
    for path in ("/css/body.css", "/js/engine/body_ui.js", "/js/views/body.js", "/js/views/body_trends.js"):
        assert f"'{path}'" in SW, path
        assert (STATIC / path.lstrip("/")).is_file()


def test_no_inline_script_style_or_handler_in_the_new_markup():
    for markup in (TODAY_CARD, TRENDS_CARD, WEIGHT_SHEET, BP_SHEET, SETTINGS_SECTION):
        assert not re.search(r"<script|\sstyle\s*=|\son[a-z]+\s*=|javascript:", markup, re.IGNORECASE)
    assert not re.search(r"\sstyle\s*=", INDEX, re.IGNORECASE) and not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)


# --------------------------------------------------------------------------- Today
def test_the_today_card_sits_under_symptoms_with_two_add_buttons_and_a_polite_status_line():
    assert '<h2 id="body-today-h" class="card-title">Weight and blood pressure</h2>' in TODAY_CARD
    assert re.search(r'<button class="btn secondary" type="button" id="body-add-weight">.*?Add weight\s*</button>', TODAY_CARD, re.S)
    assert re.search(r'<button class="btn secondary" type="button" id="body-add-bp">.*?Add blood pressure\s*</button>', TODAY_CARD, re.S)
    assert 'id="body-live" role="status"' in TODAY_CARD and 'id="body-today-body"' in TODAY_CARD
    assert INDEX.index('id="symptoms-today"') < INDEX.index('id="body-today"') < INDEX.index('id="guidance-today"')


def test_trends_has_the_section_between_the_symptoms_and_the_charts():
    assert INDEX.index('id="symptoms-trends"') < INDEX.index('id="body-trends"') < INDEX.index('id="charts"')
    assert 'aria-labelledby="body-trends-h"' in TRENDS_CARD and 'id="body-trends-body"' in TRENDS_CARD
    # the Apple Health button lives in a slot that stays hidden until another module (KH.bodyImport) puts one there
    assert 'id="body-trends-actions" hidden' in TRENDS_CARD


def test_today_trends_and_the_api_wrappers_are_wired():
    assert "KH.body.today(state.date)" in TODAY and "KH.bodyTrends.show(start, end, src)" in TRENDS
    assert "KH.body.today(day.date)" not in TODAY  # food rendering must not restart the independent body read
    for wrapper in ("bodyWeights: (start, end) => request('GET', '/api/body/weights?'", "addWeight: (b) => request('POST', '/api/body/weights', b)",
                    "updateWeight: (id, b) => request('PUT', `/api/body/weights/${id}`, b)", "deleteWeight: (id) => request('DELETE', `/api/body/weights/${id}`)",
                    "bloodPressures: (start, end) => request('GET', '/api/body/blood-pressure?'", "addBloodPressure: (b) => request('POST', '/api/body/blood-pressure', b)",
                    "updateBloodPressure: (id, b) => request('PUT', `/api/body/blood-pressure/${id}`, b)",
                    "deleteBloodPressure: (id) => request('DELETE', `/api/body/blood-pressure/${id}`)", "bodySummary: (date) => request('GET', '/api/body/summary?'"):
        assert wrapper in CORE, wrapper


def test_the_weight_sheet_asks_the_weight_when_it_was_taken_the_date_and_a_note():
    assert 'class="sheet"' in WEIGHT_SHEET and 'aria-labelledby="sheet-weight-title"' in WEIGHT_SHEET and 'method="dialog"' in WEIGHT_SHEET
    for element in ('id="weight-value"', 'inputmode="decimal"', 'id="weight-echo" aria-live="polite"', 'id="weight-context"', 'role="radiogroup"', 'id="weight-date"',
                    'id="weight-time"', 'id="weight-note"', 'maxlength="200"', 'id="weight-error" role="alert"', 'data-close', 'type="submit" id="weight-save"'):
        assert element in WEIGHT_SHEET, element
    assert "When was it taken?" in WEIGHT_SHEET
    for label in re.findall(r'<label for="([^"]+)"', WEIGHT_SHEET):
        assert f'id="{label}"' in WEIGHT_SHEET, label
    # the choices are made by the page (the dialysis ones only on dialysis), none of them ticked: the person chooses
    assert "checked" not in WEIGHT_SHEET and "weight-morning" not in WEIGHT_SHEET


def test_the_blood_pressure_sheet_has_the_top_number_then_the_bottom_number_with_plain_names():
    for element in ('id="bp-systolic"', 'id="bp-diastolic"', 'id="bp-pulse"', 'id="bp-echo" aria-live="polite"', 'id="bp-flag" aria-live="polite"', 'id="bp-hint"',
                    'id="bp-context"', 'id="bp-date"', 'id="bp-time"', 'id="bp-note"', 'id="bp-error" role="alert"', 'type="submit" id="bp-save"'):
        assert element in BP_SHEET, element
    assert BP_SHEET.index("Top number (systolic)") < BP_SHEET.index("Bottom number (diastolic)") < BP_SHEET.index("Pulse (optional")
    assert BP_SHEET.index('id="bp-systolic"') < BP_SHEET.index('id="bp-diastolic"') < BP_SHEET.index('id="bp-pulse"')
    for label in re.findall(r'<label for="([^"]+)"', BP_SHEET):
        assert f'id="{label}"' in BP_SHEET, label
    assert "checked" not in BP_SHEET


def test_the_sheets_show_the_one_hint_the_echo_and_the_other_unit():
    assert "const BP_HINT = 'Rest about 5 minutes first, sit with your feet flat, and put the cuff on your upper arm.';" in ENGINE
    assert "U.BP_HINT" in VIEW_CODE and "learnLink('weight_and_blood_pressure', 'How to measure', '#how-to-measure')" in VIEW_CODE
    assert "U.echoWeight(res.kg, S.units)" in VIEW_CODE and "U.echoReading(bTop.value, bBottom.value, bPulse.value)" in VIEW_CODE
    # a very high reading shows the handbook's words before Save, from the twin of the server's rule
    assert "R.bpFlag(res.systolic, res.diastolic)" in VIEW_CODE and "bFlag.append(flagBlock(flag" in VIEW_CODE
    # both sheets listen while the person types
    assert VIEW_CODE.count("addEventListener('input'") >= 2


def test_a_save_writes_only_from_the_submit_handler_and_needs_the_choices_first():
    for form, writes in (("sheets.onSubmit(wForm", ("api.addWeight(", "api.updateWeight(")), ("sheets.onSubmit(bForm", ("api.addBloodPressure(", "api.updateBloodPressure("))):
        submit = VIEW.index(form)
        for write in writes:
            assert VIEW.index(write) > submit, write
    assert "api.deleteWeight(w.id)" in VIEW and "api.deleteBloodPressure(r.id)" in VIEW
    assert "KH.confirm.inline(actions" in VIEW and "confirm(" not in VIEW_CODE.replace("KH.confirm.inline(", "")  # a delete asks in the page
    for message in ("Choose when it was taken.", "Choose the date."):
        assert message in VIEW, message
    assert VIEW.count("if (S.busy) return;") == 2  # a second press does not save twice
    assert "addWeightBtn.disabled = future" in VIEW and "addBpBtn.disabled = future" in VIEW and "date > todayStr()" in VIEW
    # a save without a connection says so and keeps what was typed
    assert "const NEEDS_CONNECTION = 'Weights and blood pressure readings need a connection to your server, and there is none right now.';" in VIEW
    assert "err && err.offline" in VIEW and "`${NEEDS_CONNECTION} Nothing was saved.`" in VIEW
    assert "weightDlg.close()" in VIEW and VIEW.index("weightDlg.close()") > VIEW.index("api.addWeight(")  # closed only after the server said yes


def test_an_edit_that_leaves_the_weight_as_shown_keeps_the_stored_weight():
    assert "W.editing && wValue.value.trim() === W.initialText ? W.editing.kg : res.kg" in VIEW_CODE


# --------------------------------------------------------------------------- the handbook's words
def test_the_view_never_writes_the_handbooks_words_it_draws_what_the_server_sends():
    for banned in ("911", "180/120", "Call your care team", "Call 911", "rest for 5 minutes", "sudden severe"):
        assert banned not in VIEW_CODE and banned not in TRENDS_CODE and banned not in ENGINE_CODE, banned
    assert "h('p', {}, flag.text, link ? [' ', link] : null)" in VIEW_CODE
    assert "KH.learn.href(flag.href)" in VIEW_CODE and "rel: 'noopener'" in VIEW_CODE and "target: '_blank'" in VIEW_CODE
    assert "alarm.flag" in VIEW_CODE and "flagged[0].flag" in VIEW_CODE


def test_a_flagged_reading_is_the_first_block_of_the_card_and_prominent():
    body_of_render = VIEW_CODE[VIEW_CODE.index("function renderToday"):VIEW_CODE.index("async function loadToday")]
    assert body_of_render.index("flagBlock(flagged[0].flag, label)") < body_of_render.index("alarmLine(") < body_of_render.index("goalLine(") < body_of_render.index("weightItem")
    assert "flag.prominent ? ' prominent' : ''" in VIEW_CODE
    assert ".body-flag.prominent" in CSS and "var(--over-tint)" in CSS and "border-left-width: 6px" in CSS
    # the 911 line is the server's first line: the page has no wording of its own to reorder
    flag = body.flag_of("blood_pressure")
    assert flag["text"].index("Call 911 now") < flag["text"].index("Call your care team today") and flag["prominent"] is True


def test_the_alarm_line_names_the_two_weights_the_server_compared():
    code = strip_comments(VIEW[VIEW.index("function alarmLine"):VIEW.index("// The goal's line")])
    assert "alarm.message" in code and "U.alarmSentence(alarm, S.units)" in code and "U.gainText(alarm.gain_kg, S.units)" in code
    assert "Over your alarm. " in code and "Not over your alarm. " in code and "R.formatWeight(latest.kg, S.units)" in code


# --------------------------------------------------------------------------- code rules
@pytest.mark.parametrize("name", sorted(CODE))
def test_text_goes_into_the_page_as_text_only_and_nothing_is_stored_or_sent_from_here(name):
    code = strip_comments(CODE[name])
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on", "setAttribute('style'",
                   "style:", ".style", "cssText", "createContextualFragment", "DOMParser", "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource",
                   "importScripts", "localStorage", "sessionStorage", "indexedDB", "document.cookie", "KH.ai", "/api/ai"):
        assert banned not in code, f"{name}: {banned}"


def test_the_views_draw_with_h_and_s_and_never_with_markup_strings():
    for code in (VIEW_CODE, TRENDS_CODE):
        assert "textContent" in code or "h('" in code
        assert not re.search(r"`<[a-z]", code) and not re.search(r"'<[a-z]", code)
    assert "s('svg'" in TRENDS_CODE and "s('path'" in TRENDS_CODE and "s('line'" in TRENDS_CODE  # the charts are built with the DOM
    assert "h('span', { class: 'body-val' }, R.formatWeight(w.kg, S.units))" in VIEW_CODE and "h('p', { class: 'body-note' }, w.note)" in VIEW_CODE


def test_the_app_names_no_cause_treatment_or_dose_in_what_it_draws_or_says():
    forbidden = re.compile(r"\b(because|causes|caused|due to|dose[sd]?|dosing|insulin|medicine|medication|treat\w*|glucagon|units of|take )\b", re.I)
    for name, code in (("view", VIEW_CODE), ("trends", TRENDS_CODE), ("engine", ENGINE_CODE)):
        assert not forbidden.search(code), (name, forbidden.search(code))
    assert not forbidden.search(CSS)
    for markup in (TODAY_CARD, TRENDS_CARD, WEIGHT_SHEET, BP_SHEET, SETTINGS_SECTION):
        assert not forbidden.search(re.sub(r"<[^>]+>", " ", markup))


def test_every_colour_in_the_stylesheet_is_a_token_and_nothing_is_wider_than_a_phone():
    # light and dark come from base.css; the two chart series are the one place with hex values, as tokens, in both themes
    without_tokens = re.sub(r"--body-(?:top|bottom): #[0-9a-fA-F]{6};", "", CSS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", without_tokens)
    assert CSS.count("--body-top:") == 3 and CSS.count("--body-bottom:") == 3  # light, the OS dark and the dark choice
    assert "url(" not in CSS and "@import" not in CSS
    for width in re.findall(r"(?<![-\w])(?:min-)?width:\s*(\d+)px", CSS):
        assert int(width) <= 375, width
    assert "overflow-wrap: anywhere" in CSS and "var(--over-tint)" in CSS


# --------------------------------------------------------------------------- Trends
def test_the_trends_charts_are_plain_svg_each_with_a_table_under_it():
    assert TRENDS_CODE.count("role: 'img'") == 2 and TRENDS_CODE.count("The table under the chart lists every") == 2
    assert TRENDS_CODE.count("class: 'inline-details'") == 1 and "tableOf('Show as table'" in TRENDS_CODE  # one builder, used by both
    block = TRENDS_CODE[TRENDS_CODE.index("function weightBlock"):TRENDS_CODE.index("function render()")]
    assert block.index("weightChart(") < block.index("weightTable(") and block.index("bpChart(") < block.index("bpTable(")
    # weight: one line, a dashed line for the dry weight only on hemodialysis, a diamond for a weight after dialysis
    assert "profile.dialysis === 'hemodialysis'" in TRENDS_CODE and "diamond(" in TRENDS_CODE and "'ref dry'" in TRENDS_CODE
    # blood pressure: two lines, goal lines dashed and named, a circle and a square per reading
    for needle in ("'series top'", "'series bottom'", "'goal-top'", "'goal-bottom'", "`ref ${cls}`", "circle(", "rect("):
        assert needle in TRENDS_CODE, needle
    assert ".body-chart-svg .ref { fill: none; stroke-width: 1.5; stroke-dasharray: 6 4; }" in CSS
    # the reference lines are named in the legend with their numbers, not by text on the line, which sat on the readings
    assert "class: 'direct'" not in TRENDS_CODE and "text.direct" not in CSS
    assert "`Top goal: under ${goal.systolic} (dashed)`" in TRENDS_CODE and "`Bottom goal: under ${goal.diastolic} (dashed)`" in TRENDS_CODE
    assert "`Dry weight in Profile (${R.formatWeight(dryKg, unit)})`" in TRENDS_CODE
    assert "weekAverages(weights, end)" in TRENDS_CODE and "U.weekSentences(summary.bp.week, summary.bp.goal)" in TRENDS_CODE  # the 7-day averages


def test_the_chart_colours_are_checked_and_the_words_carry_the_meaning():
    assert "#2a78d6" in CSS and "#eb6834" in CSS and "#3987e5" in CSS and "#d95926" in CSS  # the dataviz palette's first two slots, light and dark
    assert "legendItem(" in TRENDS_CODE and "'Top number'" in TRENDS_CODE and "'Bottom number'" in TRENDS_CODE and "'After dialysis'" in TRENDS_CODE
    assert "Yes, see Today" in TRENDS_CODE  # a flagged reading is a word in the table, not only a heavier mark


def test_the_apple_health_button_exists_only_when_another_module_provides_the_import():
    # Trends: the button passes itself to the sheet (so focus comes back to it)
    assert "KH.bodyImport && typeof KH.bodyImport.open === 'function'" in TRENDS_CODE and "slot.hidden = !there" in TRENDS_CODE
    assert "'Import from Apple Health'" in TRENDS_CODE and "KH.bodyImport.open(btn)" in TRENDS_CODE
    # Settings → Your data
    block = SETTINGS[SETTINGS.index("function bodyImportBlock"):SETTINGS.index("// Import from a file (POST /api/me/import")]
    assert "KH.bodyImport && typeof KH.bodyImport.open === 'function'" in block and "wrap.hidden = true" in block
    assert "'Import from Apple Health'" in block and "KH.bodyImport.open(b)" in block and "wrap.append(bodyImportBlock());" in SETTINGS
    # the reader and the sheet are another module's (js/views/body_import.js): these two files never define KH.bodyImport or read the export
    for code in (VIEW_CODE, TRENDS_CODE):
        assert "KH.bodyImport =" not in code and "apple_health" not in code.lower()
    assert 'id="sheet-body-import"' not in INDEX or "body_import.js" in INDEX


# --------------------------------------------------------------------------- Settings
def test_settings_has_a_personal_section_with_the_unit_the_alarm_and_the_goal():
    assert 'data-title="Weight and blood pressure"' in SETTINGS_SECTION and 'id="set-body-body"' in SETTINGS_SECTION
    assert INDEX.index('id="set-prefs"') < INDEX.index('id="set-body"') < INDEX.index('id="set-guidance"')
    assert "KH.body.renderSettings()" in SETTINGS
    code = strip_comments(VIEW[VIEW.index("async function renderSettings"):VIEW.index("// ---- Profile")])
    for text in ("Unit for weight", "My weight-gain alarm (from my care team)", "Call my team if my weight goes up by more than", "My blood pressure goal from my team: under",
                 "between sessions", "in a number of days", "The number your care team gave you. The app does not suggest one.",
                 "The numbers your care team gave you", "The app does not suggest a goal"):
        assert text in code, text
    assert "'user.units.weight'" in code and "'body.weight_alarm'" in code and "'body.bp_goal'" in code
    # between sessions is offered only on hemodialysis (or when the saved choice already is that, so it is never lost)
    assert "hd || alarm.over === 'between_sessions' ? h('option', { value: 'between_sessions' }" in code
    assert "state.profile.dialysis === 'hemodialysis'" in code
    # kilograms in the registry whatever the person types, through the engine
    assert "U.alarmFromInput(aAmount.value, unit)" in code and "U.goalFromInput(gTop.value, gBottom.value)" in code
    # the link to the handbook page, through the table the server sends (no handbook, no link)
    assert "learnLink('weight_and_blood_pressure'" in code
    assert topics.APP_LINKS["pages"]["weight_and_blood_pressure"] == {"path": "app/weight-and-blood-pressure/", "title": "Weight and blood pressure"}
    assert PAGE.is_file()


def test_the_settings_never_suggest_a_number_and_default_to_none():
    code = strip_comments(VIEW[VIEW.index("async function renderSettings"):VIEW.index("// ---- Profile")])
    assert "placeholder: 'e.g. 130'" in code and "placeholder: 'e.g. 80'" in code  # an example is not a default: the boxes start empty from the server's null
    assert "alarm.amount_kg == null ? ''" in code and "goal.systolic == null ? ''" in code and "goal.diastolic == null ? ''" in code
    assert "Leave the amount empty for no alarm" in code and "Leave both empty for no goal" in code


# --------------------------------------------------------------------------- Profile
def test_profile_offers_the_logs_weights_and_never_applies_them():
    assert 'id="pf-weight-log"' in INDEX and 'id="pf-weight-6mo-log"' in INDEX
    assert INDEX.index('id="pf-weight"') < INDEX.index('id="pf-weight-log"') < INDEX.index('id="pf-weight-6mo"') < INDEX.index('id="pf-weight-6mo-log"')
    assert re.search(r'<p class="body-use" id="pf-weight-log" hidden></p>', INDEX) and re.search(r'<p class="body-use" id="pf-weight-6mo-log" hidden></p>', INDEX)
    code = strip_comments(PROFILE)
    block = strip_comments(PROFILE[PROFILE.index("let bodyHints = null;"):PROFILE.index("// The v0.3 fields as the form shows them")])
    # not on dialysis only for the latest weight; the six-month one has no such rule
    assert "$('#pf-dialysis').value === 'none' ? bodyHints.latest : null" in block and "bodyHints ? bodyHints.sixMonth : null" in block
    assert "syncConditionalFields" in code and "showBodyHints();" in code[code.index("function syncConditionalFields"):code.index("$('#pf-dialysis').addEventListener")]
    # "Use this" fills the box and says Save profile saves it: no request, no change of state.profile
    assert "input.value = String(kg);" in block and "Press Save profile to keep it." in block and "'Use this'" in block
    assert "api." not in block and "state.profile" not in block and "saveProfile" not in block
    assert "KH.body.profileHints()" in block and "loadBodyHints();" in code
    helper = VIEW_CODE[VIEW_CODE.index("async function profileHints"):VIEW_CODE.index("KH.body = {")]
    assert re.findall(r"api\.(\w+)\(", helper) == ["bodySummary", "bodyWeights"]  # two reads and nothing else
    assert "R.sixMonthChange(" in helper and "U.SIX_MONTH_LOOKBACK_DAYS" in helper


# --------------------------------------------------------------------------- visit prep
def test_visit_prep_has_the_section_between_the_symptoms_and_the_questions_and_prints_it():
    page = INDEX[INDEX.index('<section id="view-visit"'):INDEX.index("<!-- ===================== SETTINGS")]
    assert page.index('id="visit-sym-body"') < page.index('id="visit-body-body"') < page.index('id="visit-q-h"')
    assert 'aria-labelledby="visit-body-h"' in page and "Weight and blood pressure I recorded" in page
    assert "renderBody(bodyErr ? null" in VISIT and "V.bodyPage(" in VISIT and "KH.body.flagBlock(bp.flag)" in VISIT
    assert "loadError('The weights and blood pressure', err)" in VISIT  # a read that failed says so: a printed page never silently leaves it out
    assert "#view-visit .body-flag" in VISIT_CSS
    for fn in ("sessionGains", "readingsWindow", "bodyPage"):
        assert f"function {fn}(" in VISITPREP
    assert "KH.bodyRules" in VISITPREP and "sixMonthChange(upTo)" in VISITPREP
    # no write and nothing outside the app's own API: the reads are the six the visit prep test lists
    assert re.findall(r"\breads\.(\w+)\(", VISIT) == ["summary", "labs", "symptoms", "bodySummary", "bodyWeights", "bloodPressures", "profile"]


def test_visit_prep_lists_the_gains_between_sessions_only_on_hemodialysis_and_says_what_the_alarm_is():
    assert "dialysis === 'hemodialysis'" in strip_comments(VISITPREP) and "page.sessions" in VISIT
    code = VISIT[VISIT.index("function renderBody"):VISIT.index("// ---- my questions")]
    for text in ("Gains between the last sessions", "No weight-gain alarm is set.", "so the gains below are not compared with it", "over your alarm",
                 "your dry weight in Profile", "Readings with a top number of", "in this period: "):
        assert text in code, text
    assert "R.FLAG_SYSTOLIC" in code and "R.FLAG_DIASTOLIC" in code  # the thresholds are the twin's constants, not numbers typed here


def test_the_handbook_page_is_in_the_nav_and_linked_from_where_a_person_looks_for_it():
    nav = (ROOT / "handbook" / "mkdocs.yml").read_text(encoding="utf-8")
    assert "app/weight-and-blood-pressure.md" in nav
    assert "weight-and-blood-pressure.md" in (ROOT / "handbook" / "docs" / "app" / "index.md").read_text(encoding="utf-8")
    assert "weight-and-blood-pressure.md" in (ROOT / "handbook" / "docs" / "app" / "first-setup.md").read_text(encoding="utf-8")
    assert "The app has no field for your weight-gain limit" not in (ROOT / "handbook" / "docs" / "app" / "first-setup.md").read_text(encoding="utf-8")
    assert "[enter them in the app](../app/weight-and-blood-pressure.md)" in (ROOT / "handbook" / "docs" / "stages" / "hemodialysis-in-centre.md").read_text(encoding="utf-8")
