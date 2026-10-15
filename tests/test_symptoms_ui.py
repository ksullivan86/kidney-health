"""The symptoms log in the app's pages (ARCHITECTURE.md "Symptoms log"): the shell, the Today card, the sheet, the Trends list
and the files that draw them. Static checks of what the browser is given; the flows are run in Chromium by
``tools/e2e/symptoms.py`` and the numbers and texts of the demo by ``tests/data/symptoms_vectors.json``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import symptoms as S

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "symptoms.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "symptoms.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "symptoms.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "symptoms.css").read_text(encoding="utf-8")
TODAY = (STATIC / "js" / "views" / "today.js").read_text(encoding="utf-8")
TRENDS = (STATIC / "js" / "views" / "trends.js").read_text(encoding="utf-8")
CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
CODE = {"view": VIEW, "engine": ENGINE, "mock": MOCK}


def strip_comments(js: str) -> str:
    return re.sub(r"^\s*//.*$|(?<![:'\"\\])//[^\n]*", "", re.sub(r"/\*.*?\*/", "", js, flags=re.S), flags=re.M)


def section(start: str, end: str) -> str:
    begin = INDEX.index(start)
    return INDEX[begin:INDEX.index(end, begin)]


def scripts() -> list[str]:
    return re.findall(r'<script src="([^"]+)"', INDEX)


def test_the_files_are_in_the_shell_in_dependency_order_and_in_the_service_worker():
    s = scripts()
    assert s.index("js/engine/symptoms.js") < s.index("js/core.js") < s.index("js/mock/core.js") < s.index("js/mock/symptoms.js") < s.index("js/mock/seed.js")
    assert s.index("js/views/trends.js") < s.index("js/views/symptoms.js") < s.index("js/main.js") and s.index("js/views/symptoms.js") > s.index("js/learn.js")
    assert 'href="css/symptoms.css"' in INDEX and INDEX.index("css/labs.css") < INDEX.index("css/symptoms.css") < INDEX.index("css/touch.css")
    for path in ("/css/symptoms.css", "/js/engine/symptoms.js", "/js/mock/symptoms.js", "/js/views/symptoms.js"):
        assert f"'{path}'" in SW, path
        assert (STATIC / path.lstrip("/")).is_file()


def test_no_inline_script_style_or_handler_anywhere_in_the_page():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)  # the page as a whole: only script files
    assert not re.search(r"\sstyle\s*=", INDEX, re.IGNORECASE)
    assert not re.search(r"\son[a-z]+\s*=", INDEX, re.IGNORECASE)
    assert not re.search(r"javascript:", INDEX, re.IGNORECASE)
    for markup in (section('<section class="card symptoms-card" id="symptoms-today"', "</section>"),
                   section('<section class="card symptoms-card" id="symptoms-trends"', "</section>"),
                   section('<dialog id="sheet-symptom"', "</dialog>")):
        assert not re.search(r"<script|\sstyle\s*=|\son[a-z]+\s*=", markup, re.IGNORECASE)


def test_the_today_card_has_an_add_button_and_a_polite_status_line():
    card = section('<section class="card symptoms-card" id="symptoms-today"', "</section>")
    assert '<h2 id="symptoms-today-h" class="card-title">Symptoms</h2>' in card
    assert re.search(r'<button class="btn secondary" type="button" id="symptoms-add">.*?Add\s*</button>', card, re.S)
    assert 'id="symptoms-live" role="status"' in card and 'id="symptoms-today-body"' in card
    assert INDEX.index('id="status-bars"') < INDEX.index('id="symptoms-today"') < INDEX.index('id="guidance-today"')  # a compact row below the day's status


def test_the_sheet_is_a_bottom_sheet_with_symptom_severity_date_and_note():
    sheet = section('<dialog id="sheet-symptom"', "</dialog>")
    assert 'class="sheet"' in sheet and 'aria-labelledby="sheet-symptom-title"' in sheet and 'method="dialog"' in sheet
    for element in ('id="symptom-kind"', 'id="symptom-label"', 'maxlength="60"', 'id="symptom-severity"', 'id="symptom-date"', 'id="symptom-note"',
                    'maxlength="300"', 'id="symptom-error" role="alert"', 'id="symptom-flag" aria-live="polite"', 'data-close', 'type="submit" id="symptom-save"'):
        assert element in sheet, element
    # no severity is pre-chosen: the person chooses it
    radios = re.findall(r'<input type="radio" name="symptom-severity" id="symptom-sev-(\d)" value="(\d)"([^>]*)>', sheet)
    assert [(a, b) for a, b, _ in radios] == [("1", "1"), ("2", "2"), ("3", "3")] and not any("checked" in rest for *_, rest in radios)
    assert [label for label in re.findall(r'<label for="symptom-sev-\d">([^<]*)</label>', sheet)] == ["Mild", "Moderate", "Severe"]
    for label in re.findall(r'<label for="([^"]+)"', sheet):
        assert f'id="{label}"' in sheet, label
    assert "does not say what a symptom means" in sheet


def test_the_trends_card_is_between_the_period_summary_and_the_charts():
    assert INDEX.index('id="period-summary"') < INDEX.index('id="symptoms-trends"') < INDEX.index('id="charts"')
    card = section('<section class="card symptoms-card" id="symptoms-trends"', "</section>")
    assert 'aria-labelledby="symptoms-trends-h"' in card and 'id="symptoms-trends-body"' in card


def test_today_and_trends_ask_for_their_symptoms_and_the_api_wrappers_exist():
    assert "KH.symptoms.today(day.date)" in TODAY and "KH.symptoms.trends(start, end)" in TRENDS
    for wrapper in ("symptoms: (start, end) => request('GET', '/api/symptoms?' + qs({ start, end }))", "addSymptom: (b) => request('POST', '/api/symptoms', b)",
                    "updateSymptom: (id, b) => request('PUT', `/api/symptoms/${id}`, b)", "deleteSymptom: (id) => request('DELETE', `/api/symptoms/${id}`)"):
        assert wrapper in CORE, wrapper


@pytest.mark.parametrize("name", sorted(CODE))
def test_text_goes_into_the_page_as_text_only(name):
    code = strip_comments(CODE[name])
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on", "setAttribute('style'",
                   "style:", "createContextualFragment", "DOMParser", "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "importScripts",
                   "localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert banned not in code, f"{name}: {banned}"


def test_the_view_draws_with_h_and_never_with_markup_strings():
    code = strip_comments(VIEW)
    assert "h('p', { class: 'sym-note' }, s.note)" in code and "h('span', { class: 'sym-name' }, s.name)" in code
    assert "textContent" in code
    assert not re.search(r"`<[a-z]", code) and not re.search(r"'<[a-z]", code)


def test_the_app_names_no_cause_treatment_or_dose_in_what_it_draws_or_says():
    forbidden = re.compile(r"\b(because|causes|caused|due to|dose[sd]?|dosing|insulin|medicine|medication|treat\w*|glucagon|units of|take )\b", re.I)
    for name in CODE:
        assert not forbidden.search(strip_comments(CODE[name])), name
    assert not forbidden.search(CSS)
    sheet = section('<dialog id="sheet-symptom"', "</dialog>")
    assert not forbidden.search(re.sub(r"<[^>]+>", " ", sheet))


def test_the_red_flag_decision_lives_in_one_place_and_the_view_asks_for_it():
    # the view knows no symptom by name: it draws what the server (or the demo's twin) sends in red_flag
    for key in ("breathlessness", "swelling", "'emergency'", "'today'"):
        assert key not in strip_comments(VIEW), key
    assert "R.redFlag(kind.value, severity())" in VIEW and "s.red_flag ? flagEl(s.red_flag)" in VIEW and "g.red_flag ? flagEl(g.red_flag)" in VIEW
    # the link goes through the handbook helper (no handbook, no link) and opens in a new tab so a sheet in use is not lost
    assert "KH.learn.href(rf.href)" in VIEW and "rel: 'noopener'" in VIEW and "target: '_blank'" in VIEW
    # the twin holds the same two symptoms as the server
    twin = set(re.findall(r"^    (\w+): \{\s*$", ENGINE[ENGINE.index("const RED_FLAGS"):ENGINE.index("function redFlag")], re.M))
    assert twin == set(S.RED_FLAGS)
    assert "const HREF = '/learn/get-help-now/';" in ENGINE


def test_a_severe_red_flag_is_shown_first_and_prominently():
    code = strip_comments(VIEW)
    assert "red_flag && s.red_flag.prominent ? 0 : 1" in code and "red_flag && g.red_flag.prominent ? 0 : 1" in code
    assert "rf.prominent ? ' prominent' : ''" in code and "h('b', {}, 'Severe. ')" in code
    assert ".sym-flag.prominent" in CSS


def test_a_save_writes_only_from_the_submit_handler_and_needs_a_choice_first():
    submit = VIEW.index("sheets.onSubmit(form")
    for write in ("api.addSymptom(", "api.updateSymptom("):
        assert VIEW.index(write) > submit, write
    assert "api.deleteSymptom(s.id)" in VIEW and VIEW.index("api.deleteSymptom(s.id)") < submit  # inside the confirm handler of the list
    assert "KH.confirm.inline(actions" in VIEW  # a delete asks in the page, never with window.confirm
    assert "confirm(" not in strip_comments(VIEW).replace("KH.confirm.inline(", "")
    for message in ("Choose which symptom it is.", "Name the symptom, for example dry mouth.", "Choose how bad it is: mild, moderate or severe."):
        assert message in VIEW, message
    assert "if (S.busy) return;" in VIEW  # a second press does not save twice
    assert "addBtn.disabled = future" in VIEW and "date > todayStr()" in VIEW  # days after today cannot be added to


def test_every_colour_in_the_stylesheet_is_a_token_and_nothing_is_wider_than_a_phone():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", CSS)  # light and dark both come from base.css
    assert "url(" not in CSS and "@import" not in CSS
    for width in re.findall(r"(?<![-\w])(?:min-)?width:\s*(\d+)px", CSS):
        assert int(width) <= 375, width
    assert "var(--over-tint)" in CSS and "var(--caution-tint)" in CSS and "overflow-wrap: anywhere" in CSS
    assert ".sev-seg { grid-template-columns: repeat(3, 1fr); }" in CSS


def test_the_trends_marks_are_decoration_and_the_words_carry_the_meaning():
    code = strip_comments(VIEW)
    assert "h('div', { class: 'sym-strip', 'aria-hidden': 'true' }, marks)" in code
    assert "'data-sev': byDate.get(day) || null" in code
    assert "sevWord(d.severity)" in code and "class: 'sym-dates'" in code  # the dates are written out with their severity
    assert 'data-sev="3"' in CSS and "i[data-sev=" in CSS and "height: 24px" in CSS  # a mark's height repeats the severity


def test_the_mock_registers_the_same_routes_as_the_server():
    for route in ("route('GET', '/api/symptoms'", "route('POST', '/api/symptoms'", "route('PUT', '/api/symptoms/{id}'", "route('DELETE', '/api/symptoms/{id}'"):
        assert route in MOCK, route
    assert "this._currentUser()" in MOCK and "r.user_id === userId" in MOCK  # every route reads only the signed-in person's rows
    assert "fail(404, 'Symptom not found')" in MOCK
