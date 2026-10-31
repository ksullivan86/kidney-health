"""The screens of design note 30: Settings → Shopping list app (``js/views/list_sync.js``), Plan → Shopping list → Send, Plan →
Import a recipe (``js/views/recipe_import.js``), and the demo's twin (``js/mock/lists.js``) run in Node.
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
LISTS = (STATIC / "js" / "views" / "list_sync.js").read_text(encoding="utf-8")
IMPORT = (STATIC / "js" / "views" / "recipe_import.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "lists.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "recipe_import.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
PLAN = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_the_scripts_are_loaded_in_order_and_kept_offline() -> None:
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/engine/recipe_import.js") < scripts.index("js/mock/lists.js") < scripts.index("js/mock/seed.js")
    assert scripts.index("js/views/plan.js") < scripts.index("js/views/list_sync.js") < scripts.index("js/views/recipe_import.js")
    assert scripts.index("js/views/recipe_import.js") < scripts.index("js/main.js")
    for path in ("/js/engine/recipe_import.js", "/js/mock/lists.js", "/js/views/list_sync.js", "/js/views/recipe_import.js"):
        assert f"'{path}'," in SW


def test_settings_section_hidden_until_the_server_answers() -> None:
    sec = '<section class="card settings-section" id="set-lists" data-title="Shopping list app" aria-labelledby="set-lists-h" hidden>'
    assert INDEX.index('id="set-connected"') < INDEX.index(sec) < INDEX.index('id="set-guidance"')
    assert "const show = await KH.listSync.render($('#set-lists-body'));" in SETTINGS
    assert "['Shopping list app and recipe import', ['lists.sync_enabled', 'recipes.import_enabled']]," in SETTINGS
    assert "if (!res.enabled) { clear(body); return false; }" in LISTS


def test_the_key_box_is_write_only_and_the_words_say_what_is_sent() -> None:
    assert "type: 'password'" in LISTS and "autocomplete: 'off'" in LISTS
    assert "'Saved. Type a new one to change it.'" in LISTS and "It is kept locked on this server and never shown again." in LISTS
    assert "Only the foods\\' names and amounts are sent, ' + 'nothing else about you." in LISTS.replace("\n    ", " ")
    assert "Nothing else about you is sent." in LISTS and "Untick what you already have." in LISTS
    assert "checked: checks && checks.has(it.food_id) ? null : true" in LISTS  # ticked on this phone: starts unticked


def test_plan_has_the_send_and_import_buttons() -> None:
    assert '<button class="btn secondary" type="button" id="shopping-send" hidden>Send to list app</button>' in INDEX
    assert '<button class="btn secondary" type="button" id="btn-import-recipe">Import a recipe</button>' in INDEX
    assert "KH.listSync.planButton($('#shopping-send'), items.length > 0)" in PLAN
    assert "KH.recipeImportView.open({ trigger: e.currentTarget, onSaved: afterAiSave })" in PLAN
    for sheet in ('id="sheet-list-send"', 'id="sheet-recipe-import"'):
        assert INDEX.count(sheet) == 1


def test_every_line_must_be_checked_and_the_estimate_is_always_shown() -> None:
    assert "const allChecked = st.rows.every((r) => r.checked);" in IMPORT
    assert "goButton(ready ? 'Save recipe' : `Check every line" in IMPORT
    assert "h('p', { class: 'hint ri-estimate', id: 'ri-estimate' }, draft.estimate)" in IMPORT
    assert "'Leave this out'" in IMPORT and "'Search for another food…'" in IMPORT
    assert "The app cannot tell the amount from this line: enter it." in IMPORT
    assert "Not counted: ${left.map((r) => r.line.text).join('; ')}" in IMPORT
    # Unknown never 0: a food that does not list a nutrient counts as missing, and none listing it is "not listed".
    assert "if (v == null) missing[n.key] += 1; else totals[n.key]" in IMPORT
    assert "none ? 'not listed' : atLeast(" in IMPORT


def test_no_insulin_or_low_warnings_in_the_new_screens() -> None:
    for text in (LISTS, IMPORT, MOCK, ENGINE):
        low = text.lower()
        assert "insulin" not in low and "dose" not in low
    assert "flags.add('hypo_treatment')" in IMPORT  # a recipe of low treatments only: no carbohydrate warning, as for any low treatment


def test_no_html_no_network_from_the_browser() -> None:
    for text in (LISTS, IMPORT, MOCK, ENGINE):
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "fetch(" not in text
        assert "XMLHttpRequest" not in text and "location.assign" not in text
    assert set(re.findall(r"'(/api/[^']+)'", LISTS)) == {"/api/list-sync", "/api/list-sync/test", "/api/list-sync/preview",
                                                          "/api/list-sync/send"}
    assert set(re.findall(r"'(/api/[^']+)'", IMPORT)) == {"/api/recipe-import", "/api/recipe-import/page", "/api/recipe-import/text"}


@node
def test_the_demo_answers_with_a_fake_list_app_and_a_sample_page() -> None:
    got = json.loads(subprocess.run(["node", str(ROOT / "tests" / "js" / "lists_recipes_demo.mjs")], capture_output=True, text=True,
                                    check=True, timeout=120).stdout)
    assert got["get"]["enabled"] is True and got["get"]["connection"]["app"] == "grocy" and got["get"]["connection"]["key_set"] is True
    assert "key" not in got["get"]["connection"]
    assert got["test"]["ok"] is True and got["test"]["lists"] == [{"id": "1", "name": "Groceries"}]
    rice = next(i for i in got["preview"]["items"] if i["name"].startswith("Rice, white"))
    assert rice["text"] == "Rice, white, long-grain, cooked: 3 servings of 1 cup (158 g)"  # 1 planned in the sample + 2 here
    assert got["send"]["sent"] == 1 and got["sent"] == [{"list": "1", "text": rice["text"]}]
    assert got["noKey"]["status"] == 400 and "Enter the key again" in got["noKey"]["detail"]
    assert got["badUrl"]["status"] == 400 and got["keep"]["base_url"] == "http://grocy.example" and got["keep"]["list_id"] == "1"
    assert got["remove"]["status"] == 200 and got["afterRemove"] is None
    assert got["info"]["web"] is True and "estimates" in got["info"]["estimate"]
    page = got["page"]
    assert page["name"] == "Lemon garlic chicken with rice" and page["servings_made"] == 4 and len(page["steps"]) == 4
    assert page["source_url"] == "https://recipes.example.com/anything"
    lines = {line["text"]: line for line in page["lines"]}
    assert lines["1 tsp dried thyme"]["matches"] == []
    assert lines["2 cups cooked white rice"]["matches"][0]["servings"] == 2
    assert got["badLink"]["status"] == 400 and got["badLink"]["extra"] == {"code": "bad_link"}
    assert [line["text"] for line in got["text"]["lines"]] == ["2 cups cooked white rice", "1 tsp dried thyme"]
    assert got["saved"]["source_url"] == page["source_url"] and got["saved"]["note"] == "Not counted: 1 tsp dried thyme"
