"""Handbook menu day -> planned entries in the app ("Add this day to my plan", ROADMAP v0.4; note 08 §4.10).

The handbook build writes a plain link under every generated menu day, ``#plan-menu?items=b173905x1,...``, naming
only built-in foods (``fdc_id``) and servings. The app reads it in the browser (``js/engine/menu_link.js``), looks every
food up in its own built-in list, shows a confirmation sheet and, only on "Add to plan", posts the ticked foods through
``POST /api/log/batch`` with a ``client_id`` each (``js/views/menuplan.js``). Runs offline. Needs Node (the reader is
JavaScript, like the other parity checks in CLAUDE.md). What a person sees and presses is checked in Chromium by
``tools/e2e/menuplan.py`` (run by hand); these tests keep the contract from drifting:

* every generated menu day has its link, it names exactly that day's foods and servings, and every food resolves to a
  built-in food of the shipped ``data/foods.json`` (served by the real app's ``GET /api/foods/builtin``);
* a tampered link is refused or its foods skipped with a reason (custom or another person's food id never resolves);
* the batch the reader builds creates planned entries, a second post of the same body adds nothing, and the server
  holds what the link said;
* the MkDocs hook points the link at the app, at the demo, or drops it; the page holds no script;
* the sheet is in the shell, loads in order, writes only from its submit handler, keeps the list in memory only and
  puts text into the page as text.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import make_settings, signed_in_client

ROOT = Path(__file__).resolve().parents[1]
MENUS_DIR = ROOT / "handbook" / "docs" / "eat" / "menus"
MENUS_YML = ROOT / "handbook" / "data" / "menus.yml"
FOODS_JSON = ROOT / "data" / "foods.json"
RUNNER = ROOT / "tests" / "js" / "menu_link_runner.mjs"
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
VIEW_JS = (STATIC / "js" / "views" / "menuplan.js").read_text(encoding="utf-8")
ENGINE_JS = (STATIC / "js" / "engine" / "menu_link.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
AUTH_JS = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
LINK_RE = re.compile(r'<a class="kh-plan-link" href="@KH_APP@(#plan-menu\?items=[^"]*)">([^<]*)</a>')
LETTER = {"breakfast": "b", "lunch": "l", "dinner": "d", "snack": "s"}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def menus() -> list[dict]:
    return yaml.safe_load(MENUS_YML.read_text(encoding="utf-8"))["menus"]


def expected_tokens(day: dict) -> list[str]:
    """What the link must say for a day of menus.yml, worked out here from the data and not by the build script."""
    out = []
    for meal in day["meals"]:
        for item in meal["items"]:
            servings = f"{float(item['servings']):.4f}".rstrip("0").rstrip(".")
            out.append(f"{LETTER[meal['meal']]}{int(item['fdc_id'])}x{servings}")
    return out


def generated_links() -> list[tuple[str, str]]:
    """(menu id, link hash) for every day link in the generated pages, in page order."""
    found = []
    for spec in menus():
        text = (MENUS_DIR / f"{spec['id']}.md").read_text(encoding="utf-8")
        found += [(spec["id"], m.group(1)) for m in LINK_RE.finditer(text)]
    return found


def node_run(payload: dict) -> list[dict]:
    assert shutil.which("node"), "Node.js 22 is needed to run the menu link reader (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ----------------------------------------------------------------------------- the handbook build

def test_every_generated_menu_day_has_one_link_naming_its_foods():
    links = generated_links()
    assert len(links) == 7 * len(menus()) == 42
    position = 0
    for spec in menus():
        for day in spec["days"]:
            menu_id, link = links[position]
            position += 1
            assert menu_id == spec["id"]
            tokens = link.split("items=", 1)[1].split(",")
            assert tokens == expected_tokens(day), f"{spec['id']} {day['name']}: the link does not say what the day says"
            assert 1 <= len(tokens) <= 40


def test_each_link_sits_under_its_own_day_and_is_plain_html():
    for spec in menus():
        text = (MENUS_DIR / f"{spec['id']}.md").read_text(encoding="utf-8")
        for day in spec["days"]:
            heading = day["name"] + (f": {day['label']}" if day.get("label") else "")
            section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
            assert len(LINK_RE.findall(section)) == 1, f"{spec['id']} {day['name']}"
            assert section.rstrip().splitlines()[-1].startswith('<p class="kh-plan-day">')
        for paragraph in re.findall(r'<p class="kh-plan-day">.*?</p>', text):
            lowered = paragraph.lower()
            for banned in ("<script", "onclick", "onerror", "style=", "javascript:", "<iframe", "<img", "<form"):
                assert banned not in lowered, banned
            assert "Add this day to my plan" in paragraph and "Nothing is saved until you confirm" in paragraph
        for href in re.findall(r'href="([^"]*)"', "".join(re.findall(r'<p class="kh-plan-day">.*?</p>', text))):
            assert re.fullmatch(r"@KH_APP@#plan-menu\?items=[bldsx0-9.,]+", href), href


def test_the_build_refuses_a_day_the_link_cannot_carry():
    bh = load_module("build_handbook", ROOT / "scripts" / "build_handbook.py")
    foods = bh.load_foods()
    spec = menus()[0]
    rows = bh.load_target_rows()
    person = yaml.safe_load(MENUS_YML.read_text(encoding="utf-8"))["reference_person"]

    def problems_with(change) -> list[str]:
        copy = json.loads(json.dumps(spec))
        change(copy["days"][0])
        result = bh.evaluate_menu(copy, foods, rows, person)
        return result.days[0].problems

    first = spec["days"][0]["meals"][0]["items"][0]
    twice = problems_with(lambda d: d["meals"][0]["items"].append(dict(first)))
    assert any("listed twice" in p for p in twice)
    odd = problems_with(lambda d: d["meals"][0]["items"][0].update(servings=0.66667))
    assert any("cannot go in the 'Add this day to my plan' link" in p for p in odd)
    huge = problems_with(lambda d: d["meals"][0]["items"][0].update(servings=1001))
    assert any("cannot go in the 'Add this day to my plan' link" in p for p in huge)
    many = problems_with(lambda d: d["meals"][0]["items"].extend({"fdc_id": 1000 + n, "servings": 1} for n in range(40)))
    assert any("takes at most 40" in p for p in many) or any("not in data/foods.json" in p for p in many)


def test_the_servings_text_is_the_shortest_exact_form():
    bh = load_module("build_handbook", ROOT / "scripts" / "build_handbook.py")
    assert [bh.menu_link_servings(s) for s in (1, 0.5, 2, 0.6667, 0.3333, 1.25, 1.2, 0.25, 10, 100)] == \
        ["1", "0.5", "2", "0.6667", "0.3333", "1.25", "1.2", "0.25", "10", "100"]


# ----------------------------------------------------------------------------- the MkDocs hook

def hook():
    return load_module("menu_links_hook", ROOT / "handbook" / "tools" / "menu_links.py")


PAGE = ('<h2>Day 1</h2><p class="kh-plan-day"><a class="kh-plan-link" href="@KH_APP@#plan-menu?items=b1x1,l2x0.5">'
        'Add this day to my plan</a> <span class="kh-plan-hint">Opens the app.</span></p>\n<h2>Day 2</h2>')


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url


def test_hook_points_the_link_at_the_app_when_there_is_one():
    out = hook().on_page_content(PAGE, page=_Page("eat/menus/g3/"), config={"extra": {"app_link": "/", "demo_link": ""}})
    assert 'href="/#plan-menu?items=b1x1,l2x0.5">Add this day to my plan</a>' in out and "@KH_APP@" not in out


def test_hook_points_the_link_at_the_demo_on_pages_with_a_relative_path():
    for url, up in (("eat/menus/g3/", "../../../"), ("eat/menus/g3.html", "../../"), ("index.html", ""), ("", "")):
        out = hook().on_page_content(PAGE, page=_Page(url), config={"extra": {"app_link": "", "demo_link": "demo/"}})
        assert f'href="{up}demo/#plan-menu?items=b1x1,l2x0.5">Try this day in the app’s demo</a>' in out, url
        assert "@KH_APP@" not in out and "Add this day to my plan" not in out


def test_hook_drops_the_paragraph_when_there_is_no_app_and_no_demo():
    out = hook().on_page_content(PAGE, page=_Page("eat/menus/g3/"), config={"extra": {"app_link": "", "demo_link": ""}})
    assert out == "<h2>Day 1</h2><h2>Day 2</h2>"
    assert hook().on_page_content("<p>no link</p>", page=_Page("x/"), config={"extra": {}}) == "<p>no link</p>"
    other = '<p class="kh-plan-day">kept: no token</p>'
    assert hook().on_page_content(other + PAGE, page=_Page("x/"), config={"extra": {}}).startswith(other)


def test_mkdocs_loads_the_hook_for_both_builds():
    text = (ROOT / "handbook" / "mkdocs.yml").read_text(encoding="utf-8")
    assert re.search(r"^hooks:\n  - tools/menu_links\.py$", text, re.M)
    assert (ROOT / "handbook" / "tools" / "menu_links.py").is_file()
    assert "INHERIT: mkdocs.yml" in (ROOT / "handbook" / "mkdocs.pages.yml").read_text(encoding="utf-8")  # the Pages build keeps the hook


def test_check_links_does_not_read_an_app_route_as_a_page_anchor():
    text = (ROOT / "handbook" / "tools" / "check_links.py").read_text(encoding="utf-8")
    assert '"?" in u.fragment' in text


# ----------------------------------------------------------------------------- the reader over the real food list

@pytest.fixture
def real_foods_client(tmp_path):
    """The app started on the shipped data/foods.json (the other tests use a nine-food fixture)."""
    with signed_in_client(make_settings(tmp_path, FOODS_JSON)) as c:
        yield c


def test_every_link_resolves_to_builtin_foods_of_the_shipped_list(real_foods_client):
    foods = real_foods_client.get("/api/foods/builtin").json()["foods"]
    assert len(foods) == len(json.loads(FOODS_JSON.read_text(encoding="utf-8"))["foods"])  # the whole shipped list
    links = generated_links()
    answers = node_run({"hashes": [h for _, h in links], "foods": foods, "date": "2026-10-20"})
    assert len(answers) == 42
    for (menu_id, link), answer in zip(links, answers):
        label = f"{menu_id}: {link[:40]}"
        assert answer["parsed"]["ok"] and answer["parsed"]["skipped"] == [], label
        assert answer["resolved"]["skipped"] == [], label  # every food is a built-in food the app knows
        rows = answer["resolved"]["rows"]
        assert len(rows) == len(link.split("items=", 1)[1].split(",")), label
        assert {r["source"] for r in rows} == {"builtin"}, label
        # the rows are the link's entries (meals regrouped, the order inside a meal kept)
        order = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}
        tokens = [(t[0], int(t[1:].split("x")[0]), float(t[1:].split("x")[1])) for t in link.split("items=", 1)[1].split(",")]
        wanted = sorted(((dict(zip("bldsx", ("breakfast", "lunch", "dinner", "snack", "")))[m], f, s) for m, f, s in tokens),
                        key=lambda t: order[t[0]])
        assert [(r["meal"], r["fdc_id"], r["servings"]) for r in rows] == wanted, label
        assert len(answer["batch"]) == len(rows) and {e["date"] for e in answer["batch"]} == {"2026-10-20"}
        assert {e["status"] for e in answer["batch"]} == {"planned"}
        assert len({e["client_id"] for e in answer["batch"]}) == len(rows)


def test_a_menu_day_becomes_planned_entries_once_and_a_second_post_adds_nothing(real_foods_client):
    client = real_foods_client
    foods = client.get("/api/foods/builtin").json()["foods"]
    menu_id, link = generated_links()[0]
    [answer] = node_run({"hashes": [link], "foods": foods, "date": "2026-10-20"})
    body = {"entries": answer["batch"]}
    assert client.get("/api/log", params={"date": "2026-10-20"}).json()["entries"] == []  # reading the link writes nothing
    first = client.post("/api/log/batch", json=body)
    assert first.status_code == 201, first.text
    saved = client.get("/api/log", params={"date": "2026-10-20"}).json()["entries"]
    assert len(saved) == len(body["entries"]) and {e["status"] for e in saved} == {"planned"}
    by_id = {f["id"]: f for f in foods}
    assert sorted((e["meal"], by_id[e["food_id"]]["fdc_id"], round(e["servings"], 3)) for e in saved) == \
        sorted((r["meal"], r["fdc_id"], round(r["servings"], 3)) for r in answer["resolved"]["rows"])
    projected = client.get("/api/log", params={"date": "2026-10-20"}).json()
    assert projected["projected_totals"]["potassium_mg"] > 0  # the app's own projection of what was planned
    again = client.post("/api/log/batch", json=body)  # a second press, or a retry after a lost answer
    assert again.status_code == 200 and {r["result"] for r in again.json()["results"]} == {"existing"}
    assert len(client.get("/api/log", params={"date": "2026-10-20"}).json()["entries"]) == len(saved)


def test_a_tampered_link_never_reaches_a_custom_or_another_persons_food(real_foods_client):
    client = real_foods_client
    mine = client.post("/api/foods", json={"name": "My own stew", "serving_desc": "1 bowl", "serving_g": 300,
                                           "nutrients": {"potassium_mg": 900}}).json()
    foods = client.get("/api/foods/builtin").json()["foods"]
    assert mine["id"] not in {f["id"] for f in foods} and "My own stew" not in json.dumps(foods)  # the resolver's list never holds it
    builtin_id = foods[0]["id"]
    tampered = [
        f"#plan-menu?items=b{mine['id']}x1,l{builtin_id}x1",  # the app's own row ids are not food numbers
        "#plan-menu?items=b999999999x1,d0x1,s1x1",
        "#plan-menu?items=z173944x1,b173944x1,b173944x2",
    ]
    answers = node_run({"hashes": tampered, "foods": foods, "date": "2026-10-20"})
    for answer in answers:
        assert answer["parsed"]["ok"]
        listed = json.dumps(answer)
        assert "My own stew" not in listed
        for row in answer["resolved"]["rows"]:
            assert row["source"] == "builtin"
    first, second, third = answers
    assert any("not one of the app's built-in foods" in s["reason"] for s in first["resolved"]["skipped"])
    assert {s["text"] for s in second["resolved"]["skipped"]} == {"food 999999999", "food 1"} and second["parsed"]["skipped"][0]["text"] == "d0x1"
    assert [i["servings"] for i in third["parsed"]["items"]] == [1] and len(third["parsed"]["skipped"]) == 2


# ----------------------------------------------------------------------------- the sheet in the app

def scripts() -> list[str]:
    return re.findall(r'<script src="([^"]+)"', INDEX)


def test_the_sheet_and_the_files_are_in_the_shell():
    s = scripts()
    assert s.index("js/engine/menu_link.js") < s.index("js/views/menuplan.js") < s.index("js/main.js")
    assert s.index("js/views/menuplan.js") > s.index("js/core.js") and s.index("js/views/menuplan.js") > s.index("js/views/plan.js")
    assert "'/js/engine/menu_link.js'" in SW and "'/js/views/menuplan.js'" in SW
    start = INDEX.index('<dialog id="sheet-menuplan"')
    sheet = INDEX[start:INDEX.index("</dialog>", start)]
    for element in ('id="menuplan-form"', 'id="menuplan-date"', 'id="menuplan-groups"', 'id="menuplan-skipped"', 'id="menuplan-save"',
                    'id="menuplan-close"', 'id="menuplan-error" role="alert"', 'aria-live="polite"', 'data-close'):
        assert element in sheet, element
    assert re.search(r'<button class="btn primary" type="submit" id="menuplan-save">Add to plan</button>', sheet)
    lowered = sheet.lower()
    assert "<script" not in lowered and " style=" not in lowered and " onclick=" not in lowered
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)  # the page as a whole: only script files


def test_the_view_writes_only_from_its_submit_handler():
    submit = VIEW_JS.index("sheets.onSubmit($('#menuplan-form')")
    assert VIEW_JS.count("'POST'") == 1 and VIEW_JS.index("'POST'") > submit
    assert VIEW_JS.count("/api/log/batch") >= 1 and VIEW_JS.index("/api/log/batch", VIEW_JS.index("'POST'")) > submit
    before = VIEW_JS[:submit]
    for write in ("'POST'", "'PUT'", "'PATCH'", "'DELETE'", "addEntry", "applyMeal", "copyDay", "markEaten", "quick("):
        assert write not in before, write
    # the reads: the built-in list, the day's totals, the range for the default date; nothing else leaves the page
    assert VIEW_JS.count("KH.request('GET'") == 1 and "'/api/foods/builtin'" in VIEW_JS
    assert "KH.api.day(" in VIEW_JS and "KH.api.range(" in VIEW_JS
    for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "import(", "importScripts"):
        assert banned not in VIEW_JS and banned not in ENGINE_JS, banned
    # the posted entries are the ticked rows, planned, with the ids made when the sheet opened
    assert "M.batchEntries(on, date, uid)" in VIEW_JS and "on = ticked()" in VIEW_JS
    assert "client_id: uid()" in VIEW_JS and "if (S.busy) return;" in VIEW_JS
    assert "status: 'planned'" in ENGINE_JS


def test_the_link_is_kept_in_memory_only_and_opens_after_sign_in():
    for banned in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert banned not in VIEW_JS and banned not in ENGINE_JS, banned
    assert "let pending = null;" in VIEW_JS and "history.replaceState(null, '', location.pathname + location.search)" in VIEW_JS
    assert "KH.menuPlan.openPending()" in MAIN_JS and MAIN_JS.index("router.show(") < MAIN_JS.index("KH.menuPlan.openPending()")
    assert "KH.menuPlan.openPending()" in AUTH_JS  # also after signing in again on a page that was already open
    assert VIEW_JS.index("takeLink(); // a link the page was opened with") > VIEW_JS.index("function takeLink()")


def test_text_goes_into_the_page_as_text_only():
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on",
                   "setAttribute('style'", "style:", "createContextualFragment", "DOMParser"):
        assert banned not in VIEW_JS and banned not in ENGINE_JS, banned
    assert "textContent" in VIEW_JS and "h('li', {}, h('b', {}, s.text), `: ${s.reason}`)" in VIEW_JS
    assert "h('span', { class: 'mp-name' }, ratingIcon(r.food.kidney_rating, { decorative: true }), r.food.name)" in VIEW_JS


def test_a_food_that_treats_a_low_gets_no_wording_of_its_own():
    # the view never names a low, a hypo or a treatment in what it says; the one use of the flag leaves such a food out
    # of a meal's carbohydrate line, as the app does for every entry (nutrients.meal_carb_alerts)
    code = re.sub(r"/\*.*?\*/", "", VIEW_JS, flags=re.S)
    assert len(re.findall(r"hypo", code)) == 1 and "!(r.food.flags || []).includes('hypo_treatment')" in code
    assert not re.search(r"\b(avoid|dangerous|do not eat|too much sugar|treat(?:ing)? a low)\b", code, re.I)


def test_the_planning_doc_pages_say_where_the_link_appears():
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "#plan-menu?items=" in architecture and "Menu days in the app" in architecture
    page = (ROOT / "handbook" / "docs" / "app" / "planning-and-menus.md").read_text(encoding="utf-8")
    assert "Add this day to my plan" in page
