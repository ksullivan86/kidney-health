"""Visit prep in the app's pages (ARCHITECTURE.md "Visit prep"): the shell, the view's code, the print rules and the
promises it makes (nothing leaves the device, the questions are never stored). Static checks of what the browser is given;
the flows are run in Chromium by ``tools/e2e/visitprep.py`` and the numbers by ``tests/test_visit_prep_numbers.py``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "visit.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "visitprep.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "visit.css").read_text(encoding="utf-8")
CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
APPOINTMENTS = (ROOT / "handbook" / "docs" / "living" / "appointments.md").read_text(encoding="utf-8")


def strip_comments(js: str) -> str:
    return re.sub(r"^\s*//.*$|(?<![:'\"\\])//[^\n]*", "", re.sub(r"/\*.*?\*/", "", js, flags=re.S), flags=re.M)


VIEW_CODE, ENGINE_CODE = strip_comments(VIEW), strip_comments(ENGINE)
PAGE = INDEX[INDEX.index('<section id="view-visit"'):INDEX.index("<!-- ===================== SETTINGS")]


def scripts() -> list[str]:
    return re.findall(r'<script src="([^"]+)"', INDEX)


def test_the_files_are_in_the_shell_in_dependency_order_and_in_the_service_worker():
    s = scripts()
    assert s.index("js/engine/rules.js") < s.index("js/engine/visitprep.js") < s.index("js/core.js")
    assert s.index("js/views/trends.js") < s.index("js/views/symptoms.js") < s.index("js/views/labs.js") < s.index("js/views/visit.js") < s.index("js/main.js")
    assert s.index("js/learn.js") < s.index("js/views/visit.js")
    assert 'href="css/visit.css"' in INDEX and INDEX.index("css/symptoms.css") < INDEX.index("css/visit.css") < INDEX.index("css/touch.css")
    for path in ("/css/visit.css", "/js/engine/visitprep.js", "/js/views/visit.js"):
        assert f"'{path}'" in SW, path
        assert (STATIC / path.lstrip("/")).is_file()
    assert re.search(r"const VIEWS = \[[^\]]*'visit'", CORE)


def test_no_inline_script_style_or_handler_in_the_page_or_the_view():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)
    assert not re.search(r"\sstyle\s*=", INDEX, re.IGNORECASE)
    assert not re.search(r"\son[a-z]+\s*=", INDEX, re.IGNORECASE)
    assert not re.search(r"javascript:", INDEX, re.IGNORECASE)
    assert not re.search(r"<script|\sstyle\s*=|\son[a-z]+\s*=", PAGE, re.IGNORECASE)
    for code in (VIEW_CODE, ENGINE_CODE):
        assert not re.search(r"\.style\b|setAttribute\(\s*['\"]style|cssText|\bstyle\s*:", code), "no inline style from script"
        assert not re.search(r"\beval\s*\(|new Function|document\.write", code)
    assert "<style" not in PAGE.lower()


def test_text_goes_in_with_textcontent_never_as_html():
    for code in (VIEW_CODE, ENGINE_CODE):
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|createContextualFragment|DOMParser|\.html\(", code)
    assert "textContent" in VIEW_CODE and "h('" in VIEW_CODE  # h() children are text nodes (core.js appendChildren)
    assert "KH.labs.alertBanner" in VIEW_CODE and "KH.symptoms.flagEl" in VIEW_CODE  # the lines other screens already draw


def test_print_is_window_print_called_from_the_js_file():
    assert re.search(r"\$\('#visit-print'\)\.addEventListener\('click'", VIEW_CODE)
    assert VIEW_CODE.count("window.print()") == 1
    assert 'id="visit-print"' in PAGE and "Print / Save as PDF" in PAGE
    assert "onclick" not in PAGE.lower() and "print(" not in PAGE


def test_print_css_hides_the_shell_and_the_controls_and_is_black_on_white():
    print_css = CSS[CSS.index("@media print"):]
    assert "@page" in print_css
    for hidden in (".topbar", ".skip-link", ".preview-banner", ".install-tip", ".toast", "dialog", ".screen-only"):
        assert hidden in print_css, hidden
    assert re.search(r"display:\s*none\s*!important", print_css)
    assert "background: #fff" in print_css and re.search(r"color:\s*#000\s*!important", print_css) and "color-scheme: light" in print_css
    assert "break-inside: avoid" in print_css
    # the pieces that are not for paper carry the marker the print rules hide
    for marker in ('id="visit-periods"', 'id="visit-q-input"', 'id="visit-q-add"'):
        assert marker in PAGE
    head = PAGE[PAGE.index('<div class="visit-head'):PAGE.index("</div>", PAGE.index("visit-controls"))]
    assert "screen-only" in head.split("\n", 1)[0]
    assert re.search(r'class="visit-q-add screen-only"', PAGE)
    # light and dark come from the tokens; no hard-coded colours outside the print block
    screen_css = CSS[:CSS.index("@media print")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", screen_css), "screen colours come from the theme tokens"


def test_the_page_is_reached_from_trends_and_goes_back_to_it():
    trends = INDEX[INDEX.index('<section id="view-trends"'):INDEX.index("<!-- ===================== PROFILE")]
    assert 'id="visit-open"' in trends
    assert "router.show('visit')" in VIEW_CODE and "router.show('trends')" in VIEW_CODE
    assert "router.register('visit'" in VIEW_CODE
    # no new tab: the bottom bar keeps its six tabs
    assert 'id="tab-visit"' not in INDEX and "data-view=\"visit\"" not in INDEX


def test_it_reads_only_the_apps_own_api_and_sends_nothing():
    assert re.findall(r"api\.(\w+)\(", VIEW_CODE) == ["summary", "labs", "symptoms"]  # three reads, in this order
    for forbidden in (r"\bfetch\s*\(", r"XMLHttpRequest", r"sendBeacon", r"WebSocket", r"EventSource", r"KH\.request\(", r"\bapi\.(add|update|delete|post|put|save|import)\w*\(",
                      r"KH\.ai\b", r"/api/ai", r"\bimport\s*\(", r"https?://"):
        assert not re.search(forbidden, VIEW_CODE), forbidden
        assert not re.search(forbidden, ENGINE_CODE), forbidden


def test_the_questions_and_ticks_are_never_stored_anywhere():
    for code in (VIEW_CODE, ENGINE_CODE):
        for store in ("localStorage", "sessionStorage", "indexedDB", "IndexedDB", "document.cookie", "caches", "navigator.storage", "KH.offline", "history.pushState",
                      "history.replaceState", "location.hash", "location.search"):
            assert store not in code, store
    # they live in the page's memory, per person, and are dropped when another person is signed in
    assert "S.questions = []" in VIEW_CODE and "S.owner !== owner" in VIEW_CODE
    # and the page says so, in words, where the person writes them
    assert "not saved on this device, not sent to your server and never seen by the AI" in PAGE


def test_only_the_display_name_a_person_chose_is_printed_never_the_username():
    assert "display_name" in VIEW_CODE
    assert "username" not in VIEW_CODE and "email" not in VIEW_CODE.lower() and "instance" not in VIEW_CODE.lower()


def test_the_checklist_is_the_handbooks_what_to_do_list_word_for_word():
    section = APPOINTMENTS.split("## What to do", 1)[1].split("\n## ", 1)[0]
    handbook = re.findall(r"^- \[ \] (.+)$", section, flags=re.M)
    listed = re.findall(r"^    ((?:'|\")(?:.+)(?:'|\")),?$", ENGINE.split("const CHECKLIST = [", 1)[1].split("];", 1)[0], flags=re.M)
    texts = [ast.literal_eval(item) for item in listed]  # the JS string literals are plain quoted text
    assert handbook and texts == handbook
    assert "/learn/living/appointments/" in ENGINE  # tests/test_learn_links.py checks that the page exists in the built handbook


def test_the_average_text_rules_keep_unknown_values_out_of_zero():
    body = ENGINE_CODE.split("function averageText", 1)[1].split("function averageRows", 1)[0]
    assert "'Not listed'" in body and "≥" in body and "'No entries'" in body


def test_the_handbook_page_points_to_visit_prep():
    assert "Get ready for a visit" in APPOINTMENTS
