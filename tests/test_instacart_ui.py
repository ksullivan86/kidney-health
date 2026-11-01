"""Plan → Shopping list → Open in Instacart (design note 33; ``js/views/instacart.js``) and the demo's twin (``js/mock/lists.js``)
run in Node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "instacart.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "lists.js").read_text(encoding="utf-8")
PLAN = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_the_script_is_loaded_after_plan_and_kept_offline() -> None:
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/plan.js") < scripts.index("js/views/instacart.js") < scripts.index("js/main.js")
    assert "'/js/views/instacart.js'," in SW


def test_plan_has_the_button_and_the_sheet() -> None:
    assert '<button class="btn secondary" type="button" id="shopping-instacart" hidden>Open in Instacart</button>' in INDEX
    assert INDEX.count('id="sheet-instacart"') == 1
    assert "KH.instacart.planButton($('#shopping-instacart'), items.length > 0)" in PLAN
    assert "KH.instacart.open({ start: state.shopping.start, end: state.shopping.end, checks: loadChecks(state.shopping.start)" in PLAN
    assert "['Instacart', ['lists.instacart_enabled']]," in SETTINGS
    assert "'instacart.sent': 'Shopping list sent to Instacart'," in SETTINGS


def test_the_sheet_says_what_is_sent_and_whose_terms_apply() -> None:
    assert "Nothing else about you is sent. Untick what you already have." in VIEW
    assert "Instacart is another company. Its own terms and privacy policy apply when you use its page." in VIEW
    assert "checked: checks && checks.has(it.food_id) ? null : true" in VIEW  # ticked on this phone: starts unticked
    assert "btn.hidden = !(res && res.enabled)" in VIEW  # hidden while the server has it off


def test_the_link_opens_in_a_new_tab_without_a_referrer_and_only_https() -> None:
    assert "if (MOCK || !/^https:\\/\\//i.test(url || ''))" in VIEW
    assert "target: '_blank', rel: 'noopener noreferrer', referrerpolicy: 'no-referrer'" in VIEW
    assert "window.open(url, '_blank', 'noopener,noreferrer')" in VIEW


def test_no_html_and_no_call_to_instacart_from_the_browser() -> None:
    for text in (VIEW, MOCK):
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "fetch(" not in text
        assert "XMLHttpRequest" not in text and "location.assign" not in text and "instacart.com" not in text
    assert set(re.findall(r"'(/api/[^']+)'", VIEW)) == {"/api/instacart", "/api/instacart/preview", "/api/instacart/send"}


def test_the_error_words_match_the_server() -> None:
    from app.instacart import ERROR_TEXT

    for code, text in ERROR_TEXT.items():
        assert f"{code}: '{text}'," in VIEW.replace("\\'", "'"), code


def test_no_insulin_or_low_warnings() -> None:
    low = VIEW.lower()
    assert "insulin" not in low and "dose" not in low and "hypo" not in low


@node
def test_the_demo_answers_with_a_placeholder_that_stays_in_the_page() -> None:
    got = json.loads(subprocess.run(["node", str(ROOT / "tests" / "js" / "instacart_demo.mjs")], capture_output=True, text=True,
                                    check=True, timeout=120).stdout)
    assert got["get"] == {"enabled": True, "max_items": 200}
    assert got["preview"]["title"] == "Shopping list" and got["preview"]["items"] == got["listPreview"]["items"]
    rice = next(i for i in got["preview"]["items"] if i["name"].startswith("Rice, white"))
    assert rice["text"] == "Rice, white, long-grain, cooked: 3 servings of 1 cup (158 g)"
    assert got["send"] == {"url": "#instacart-demo", "items": 1, "error": None, "message": None}
    assert got["none"]["status"] == 400 and "None of those foods" in got["none"]["detail"]
    assert got["tooMany"]["status"] == 400
