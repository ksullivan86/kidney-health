"""A recipe from a web page or pasted ingredients (design note 30 §3; app/recipe_import/). A fake web site
(tests/lists_support.py) answers behind the app's real SSRF-checked transport; nothing touches the network.

Covered: the switch (GET always answers; a page is 404 while off; pasting works either way); sign-in; reading JSON-LD (plain,
``@graph``, arrays, ``mainEntity``, ``@type`` lists, broken blocks, none at all, scripts never run); the name, yield, steps (sections,
long steps split, more than 20 cut) and ingredient lines; the ingredient parser on a table of real-looking lines; search words;
amounts (weight, volume, count, never a guess); the draft (matches from the person's own foods, none for an unknown food, never 0);
the address rules (only http and https, ports 80 and 443, no password, private and metadata addresses refused, redirects re-checked
and at most 3); the size, time and type limits; the hourly limit; the page is never stored; a saved recipe keeps its link; foods
that do not list a nutrient stay unknown in the saved recipe; another person's foods are never matched.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.recipe_import import parse as P
from app.recipe_import.fetch import RecipeFetcher
from conftest import HTTPS_URL, TestClient, add_user, make_settings, signed_in_client
from lists_support import HOME, FakeSite, attach_site, page_html, recipe_jsonld

URL = "https://recipes.example.com/lemon-chicken"


@pytest.fixture
def web(tmp_path: Path, foods_json: Path):
    s = make_settings(tmp_path, foods_json)
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        assert admin.patch("/api/admin/settings", json={"recipes.import_enabled": True}).status_code == 200
        yield admin


def fetch_page(client: TestClient, url: str = URL) -> Any:
    return client.post("/api/recipe-import/page", json={"url": url})


# --------------------------------------------------------------------------- #
# Switch and sign-in
# --------------------------------------------------------------------------- #


def test_info_always_answers_and_pages_are_off_by_default(client: TestClient) -> None:
    r = client.get("/api/recipe-import")
    assert r.status_code == 200 and r.json()["web"] is False and r.json()["max_lines"] == 60 and "estimates" in r.json()["estimate"]
    assert fetch_page(client).status_code == 404
    r = client.post("/api/recipe-import/text", json={"text": "1 banana"})
    assert r.status_code == 200 and r.json()["lines"][0]["matches"]


def test_anonymous_is_401(anon_client: TestClient) -> None:
    assert anon_client.get("/api/recipe-import").status_code == 401
    assert anon_client.post("/api/recipe-import/text", json={"text": "1 banana"}).status_code == 401
    assert anon_client.post("/api/recipe-import/page", json={"url": URL}).status_code == 401


def test_on_says_pages_can_be_read(web: TestClient) -> None:
    assert web.get("/api/recipe-import").json()["web"] is True


# --------------------------------------------------------------------------- #
# Reading the page (pure)
# --------------------------------------------------------------------------- #


def test_jsonld_plain_graph_array_and_main_entity() -> None:
    recipe = recipe_jsonld()
    assert P.find_recipe(P.ld_json_blocks(page_html(recipe))[0])["name"] == recipe["name"]
    graph = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {"@type": ["Recipe", "NewsArticle"], "name": "G"}]}
    assert P.find_recipe(graph)["name"] == "G"
    assert P.find_recipe([{"@type": "Organization"}, {"@type": "Recipe", "name": "A"}])["name"] == "A"
    assert P.find_recipe({"@type": "WebPage", "mainEntity": {"@type": "http://schema.org/Recipe", "name": "M"}})["name"] == "M"
    assert P.find_recipe({"@type": "WebPage", "about": {"@type": "Recipe"}}) is None
    assert P.find_recipe({"@type": "Article"}) is None and P.find_recipe("Recipe") is None


def test_broken_blocks_are_skipped_and_scripts_never_run() -> None:
    page = page_html("{not json", {"@type": "Organization"}, recipe_jsonld(name="Second block"))
    blocks = P.ld_json_blocks(page)
    assert len(blocks) == 2  # the broken one is skipped; the plain <script> is not read at all
    found = next(r for r in (P.find_recipe(b) for b in blocks) if r)
    assert found["name"] == "Second block"
    assert P.ld_json_blocks("<html><script type='text/javascript'>{\"@type\": \"Recipe\"}</script></html>") == []
    assert P.ld_json_blocks('<script type="application/ld+json; charset=utf-8">{"a": 1}</script>') == [{"a": 1}]


def test_name_yield_steps_and_lines() -> None:
    out = P.recipe_from_jsonld(recipe_jsonld())
    assert out["name"] == "Lemon chicken & rice" and out["servings_made"] == 4
    assert out["steps"] == ["Rinse the rice.", "Simmer for 20 minutes."] and out["steps_cut"] is False
    assert out["lines"][0] == "1 lb chicken breast" and len(out["lines"]) == 6 and out["lines_cut"] is False


@pytest.mark.parametrize("value, want", [
    (4, 4), ("6 servings", 6), (["2", "2 bowls"], 2), ("Makes 8", 8), ("4-6", 4), ("1.5", 1.5), ("0", None), (500, None),
    ("a big pot", None), (None, None), (True, None), ({"value": 4}, None),
])
def test_yield(value: Any, want: Any) -> None:
    assert P.yield_of(value) == want


def test_steps_long_ones_split_and_more_than_20_cut() -> None:
    long = " ".join(f"Sentence number {i} is here." for i in range(60))
    steps, cut = P.steps_of(long)
    assert all(len(s) <= 500 for s in steps) and " ".join(steps) == long and not cut
    steps, cut = P.steps_of([f"Step {i}" for i in range(25)])
    assert len(steps) == 20 and cut
    steps, _ = P.steps_of("x" * 1200)
    assert [len(s) for s in steps] == [500, 500, 200]
    steps, _ = P.steps_of("Mix.\nBake.\n\n")
    assert steps == ["Mix.", "Bake."]


def test_more_than_60_lines_are_cut() -> None:
    lines, cut = P.ingredient_lines([f"{i} g flour" for i in range(70)])
    assert len(lines) == 60 and cut


# --------------------------------------------------------------------------- #
# Ingredient lines, search words, amounts (pure; the same table is in tests/data/lists_recipes_vectors.json)
# --------------------------------------------------------------------------- #

LINES = [
    ("2 cups white rice, rinsed", 2, "cup", "white rice", "rinsed"),
    ("1 1/2 lb boneless chicken breast", 1.5, "lb", "boneless chicken breast", None),
    ("½ cup low-sodium chicken broth", 0.5, "cup", "low-sodium chicken broth", None),
    ("1½ cups whole milk", 1.5, "cup", "whole milk", None),
    ("1 (14.5 oz) can diced tomatoes", 14.5, "oz", "diced tomatoes", None),
    ("2 15-ounce cans black beans, drained", 30, "oz", "black beans", "drained"),
    ("3 cloves garlic, minced", 3, "clove", "garlic", "minced"),
    ("Salt and pepper, to taste", None, None, "Salt and pepper", "to taste"),
    ("2-3 carrots, peeled", 2, None, "carrots", "peeled"),
    ("1 tablespoon olive oil", 1, "tbsp", "olive oil", None),
    ("200 g pasta", 200, "g", "pasta", None),
    ("1,5 kg potatoes", 1.5, "kg", "potatoes", None),
    ("a pinch of salt", 1, "pinch", "salt", None),
    ("a few sprigs thyme", None, None, "a few sprigs thyme", None),
    ("One onion, diced", 1, None, "onion", "diced"),
    ("2 large eggs", 2, None, "large eggs", None),
    ("1 cup (240 ml) milk", 1, "cup", "milk", None),
    ("350 g/12 oz flour", 350, "g", "flour", None),
    ("▢ 1 c. sugar", 1, "cup", "sugar", None),
    ("8 fl oz apple juice", 8, "fl_oz", "apple juice", None),
]


@pytest.mark.parametrize("line, amount, unit, food, note", LINES)
def test_parse_line(line: str, amount: Any, unit: Any, food: str, note: Any) -> None:
    got = P.parse_line(line)
    assert (got["amount"], got["unit"], got["food_text"], got["note"]) == (amount, unit, food, note)


@pytest.mark.parametrize("food, terms", [
    ("boneless skinless chicken breasts", ["chicken breast", "breast", "chicken"]),
    ("diced tomatoes", ["tomato"]),
    ("butter or margarine", ["butter"]),
    ("fresh berries (any kind)", ["berr"]),
    ("Salt and pepper to taste", ["salt pepper", "pepper", "salt"]),
    ("", []),
    ("chopped", []),
])
def test_search_terms(food: str, terms: list[str]) -> None:
    assert P.search_terms(food) == terms


@pytest.mark.parametrize("amount, unit, desc, grams, want", [
    (2, "cup", "1/2 cup (79 g)", 79, 4),
    (1.5, "lb", "3 oz (85 g)", 85, 8),
    (200, "g", "1 cup (140 g)", 140, 1.43),
    (2, None, "1 large (50 g)", 50, 2),
    (3, "clove", "1 clove (3 g)", 3, 3),
    (1, "tbsp", "1 tsp (5 g)", 5, 3),
    (8, "fl_oz", "1 cup, 8 fl oz (248 g)", 248, 1),
    (2, None, "3 oz (85 g)", 85, None),  # "2 chicken breasts": the serving is a weight
    (1, "cup", "3 oz (85 g)", 85, None),  # a volume, a weight serving: no density, no guess
    (1, "pinch", "1 tsp (6 g)", 6, None),
    (None, "cup", "1 cup", 240, None),
    (2, "slice", "1 medium (118 g)", 118, None),
    (0.001, "g", "1 cup (240 g)", 240, None),
])
def test_recipe_servings(amount: Any, unit: Any, desc: str, grams: float, want: Any) -> None:
    assert P.recipe_servings(amount, unit, desc, grams) == want


# --------------------------------------------------------------------------- #
# The draft
# --------------------------------------------------------------------------- #


def test_pasted_text_gives_lines_with_matches_and_unknowns(client: TestClient) -> None:
    text = "For the chicken:\n1 lb chicken breast\n2 cups water\n3 large egg whites\n1/2 cup apple juice\n1 tsp dried thyme\n\n"
    r = client.post("/api/recipe-import/text", json={"text": text, "name": "Chicken", "servings": 4})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "Chicken" and d["servings_made"] == 4 and d["source_url"] is None and d["steps"] == []
    assert "Check each food" in d["notice"] and "estimates" in d["estimate"]
    lines = {line["text"]: line for line in d["lines"]}
    assert list(lines) == ["1 lb chicken breast", "2 cups water", "3 large egg whites", "1/2 cup apple juice", "1 tsp dried thyme"]
    chicken = lines["1 lb chicken breast"]["matches"][0]
    assert chicken["food"]["name"] == "Chicken breast, roasted" and chicken["servings"] == 5.34
    assert lines["2 cups water"]["matches"][0]["servings"] == 2
    assert lines["3 large egg whites"]["matches"][0]["servings"] == 3
    juice = lines["1/2 cup apple juice"]["matches"][0]
    assert juice["food"]["name"] == "Juice, apple" and juice["servings"] == 1 and "hypo_treatment" in juice["food"]["flags"]
    assert lines["1 tsp dried thyme"]["matches"] == []  # no such food: unknown, never 0
    assert set(chicken["food"]) == {"id", "name", "brand", "category", "source", "serving_desc", "serving_g", "nutrients", "flags",
                                    "warnings", "kidney_rating", "hidden"}


def test_pasted_text_limits(client: TestClient) -> None:
    assert client.post("/api/recipe-import/text", json={"text": "For the sauce:\n\n"}).status_code == 422
    assert client.post("/api/recipe-import/text", json={"text": "x" * 20001}).status_code == 400
    assert client.post("/api/recipe-import/text", json={"text": "1 banana", "servings": 0}).status_code == 400
    many = "\n".join(f"{i} g banana" for i in range(1, 70))
    d = client.post("/api/recipe-import/text", json={"text": many}).json()
    assert len(d["lines"]) == 60 and d["lines_cut"] is True


def test_another_persons_own_food_is_never_matched(https_client: TestClient) -> None:
    sam = add_user(https_client)
    r = sam.post("/api/foods", json={"name": "Zucchini bread, Sam's", "serving_desc": "1 slice", "serving_g": 60,
                                     "nutrients": {"potassium_mg": 100}})
    assert r.status_code == 201, r.text
    assert sam.post("/api/recipe-import/text", json={"text": "1 slice zucchini bread"}).json()["lines"][0]["matches"]
    assert https_client.post("/api/recipe-import/text", json={"text": "1 slice zucchini bread"}).json()["lines"][0]["matches"] == []


def test_a_page_becomes_a_draft_and_is_never_stored(web: TestClient) -> None:
    site = attach_site(web.app, FakeSite())
    site.add("/lemon-chicken", page_html({"@graph": [{"@type": "WebSite"}, recipe_jsonld()]}, extra="<p>MARKER-PAGE-TEXT</p>"))
    r = fetch_page(web)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "Lemon chicken & rice" and d["servings_made"] == 4 and d["source_url"] == URL
    assert d["steps"] == ["Rinse the rice.", "Simmer for 20 minutes."]
    assert [line["text"] for line in d["lines"]][:2] == ["1 lb chicken breast", "2 cups water"]
    call = site.calls[0]
    assert call["host"] == "recipes.example.com" and call["path"] == "/lemon-chicken"
    assert "cookie" not in call["headers"] and "authorization" not in call["headers"]
    assert call["headers"]["user-agent"] == "kidney-health (recipe import)"
    assert b"MARKER-PAGE-TEXT" not in Path(web.app.state.settings.db_path).read_bytes()


def test_a_page_without_a_recipe_says_so(web: TestClient) -> None:
    site = attach_site(web.app, FakeSite())
    site.add("/lemon-chicken", page_html({"@type": "Article", "name": "News"}))
    r = fetch_page(web)
    assert r.status_code == 422 and r.json()["code"] == "no_recipe" and "Paste the ingredients" in r.json()["detail"]
    site.add("/lemon-chicken", page_html(recipe_jsonld(recipeIngredient=[])))
    assert fetch_page(web).json()["code"] == "no_lines"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://recipes.example.com/x", "https://kim:pw@recipes.example.com/x",
                                 "https://recipes.example.com:8080/x", "recipes.example.com/x", "https://recipes.example.com/a b"])
def test_links_that_are_not_opened(web: TestClient, url: str) -> None:
    site = attach_site(web.app, FakeSite())
    r = fetch_page(web, url)
    assert r.status_code == 400 and r.json()["code"] == "bad_link" and site.calls == []


@pytest.mark.parametrize("address", [HOME, "127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "fd00::1"])
def test_private_and_metadata_addresses_are_refused(web: TestClient, address: str) -> None:
    site = attach_site(web.app, FakeSite(), address=address)
    site.add("/lemon-chicken", page_html(recipe_jsonld()))
    r = fetch_page(web)
    assert r.status_code == 422 and r.json()["code"] == "blocked" and site.calls == []


def test_redirects_are_checked_again_and_limited(web: TestClient) -> None:
    site = attach_site(web.app, FakeSite(), address=lambda host: HOME if host == "home.lan" else "93.184.216.34")
    site.add("/lemon-chicken", "", status=301, headers={"Location": "https://www.recipes.example.com/r/1"})
    site.add("/r/1", "", status=302, headers={"Location": "/r/2"})
    site.add("/r/2", page_html(recipe_jsonld()))
    d = fetch_page(web).json()
    assert d["name"] == "Lemon chicken & rice" and d["source_url"] == URL  # the link the person gave is kept
    assert [c["host"] for c in site.calls] == ["recipes.example.com", "www.recipes.example.com", "www.recipes.example.com"]
    site.add("/r/2", "", status=302, headers={"Location": "https://home.lan/r/3"})  # to a home address: refused
    site.calls.clear()
    r = fetch_page(web)
    assert r.json()["code"] == "blocked" and all(c["host"] != "home.lan" for c in site.calls)
    site.add("/r/2", "", status=302, headers={"Location": "file:///etc/passwd"})
    assert fetch_page(web).json()["code"] == "bad_link"
    site.add("/r/2", "", status=302, headers={"Location": "/r/3"})
    site.add("/r/3", "", status=302, headers={"Location": "/r/4"})
    site.add("/r/4", page_html(recipe_jsonld()))
    assert fetch_page(web).json()["code"] == "too_many_redirects"


def test_size_type_status_and_time_limits(web: TestClient) -> None:
    site = attach_site(web.app, FakeSite())
    web.app.state.recipe_fetcher.max_bytes = 2000
    site.add("/lemon-chicken", page_html(recipe_jsonld(), extra="x" * 5000))
    assert fetch_page(web).json()["code"] == "too_large"
    web.app.state.recipe_fetcher.max_bytes = 2 * 1024 * 1024
    site.add("/lemon-chicken", "{}", headers={"Content-Type": "application/json"})
    assert fetch_page(web).json()["code"] == "not_html"
    site.add("/lemon-chicken", "<p>gone</p>", status=410)
    assert fetch_page(web).json()["code"] == "http_error"
    site.add("/lemon-chicken", page_html(recipe_jsonld()))
    ticks = iter([0.0, 100.0, 100.0, 100.0])
    web.app.state.recipe_fetcher.clock = lambda: next(ticks, 100.0)
    assert fetch_page(web).json()["code"] == "timeout"


def test_the_charset_of_the_page_is_used(web: TestClient) -> None:
    site = attach_site(web.app, FakeSite())
    html = page_html(recipe_jsonld(name="Crème brûlée")).encode("latin-1")
    site.pages["/lemon-chicken"] = (200, {"Content-Type": "text/html; charset=ISO-8859-1"}, html)
    assert fetch_page(web).json()["name"] == "Crème brûlée"


def test_pages_are_limited_per_hour(web: TestClient) -> None:
    site = attach_site(web.app, FakeSite())
    site.add("/lemon-chicken", page_html(recipe_jsonld()))
    for _ in range(20):
        assert fetch_page(web).status_code == 200
    r = fetch_page(web)
    assert r.status_code == 429 and "paste the ingredients" in r.json()["detail"]


def test_the_fetcher_never_follows_redirects_itself() -> None:
    fetcher = RecipeFetcher()
    with fetcher._client() as client:
        assert client.follow_redirects is False


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #


def test_a_saved_recipe_keeps_its_link_and_unknowns_stay_unknown(web: TestClient) -> None:
    r = web.post("/api/foods", json={"name": "Thyme, dried, my label", "serving_desc": "1 tsp", "serving_g": 1,
                                     "nutrients": {"sodium_mg": 1}})
    assert r.status_code == 201, r.text
    thyme = r.json()["id"]
    site = attach_site(web.app, FakeSite())
    site.add("/lemon-chicken", page_html(recipe_jsonld()))
    d = fetch_page(web).json()
    chicken = d["lines"][0]["matches"][0]
    body = {"name": d["name"], "servings_made": d["servings_made"], "steps": d["steps"], "source_url": d["source_url"],
            "note": "Not counted: Salt to taste", "items": [{"food_id": chicken["food"]["id"], "servings": chicken["servings"]},
                                                          {"food_id": thyme, "servings": 1}]}
    saved = web.post("/api/meals", json=body)
    assert saved.status_code == 201, saved.text
    meal = saved.json()
    assert meal["source_url"] == URL and meal["servings_made"] == 4 and meal["steps"] == d["steps"]
    assert meal["unknown"]["potassium_mg"] == 1  # the thyme does not list potassium: "at least", not a full number
    assert meal["per_serving"]["potassium_mg"] == pytest.approx(round(218 * 5.34 / 4))
    only_thyme = web.post("/api/meals", json={**body, "items": [{"food_id": thyme, "servings": 1}]}).json()
    assert only_thyme["per_serving"]["potassium_mg"] is None  # not listed by any food: unknown, never 0


def test_jsonld_with_entities_and_tags_in_lines() -> None:
    out = P.recipe_from_jsonld({"@type": "Recipe", "name": "<b>Soup</b> &#38; bread",
                                "recipeIngredient": "2 cups &frac12;-strength broth"})
    assert out["name"] == "Soup & bread" and out["lines"] == ["2 cups ½-strength broth"]
    assert json.loads(json.dumps(out))  # plain JSON


def test_the_whole_fetch_has_one_deadline_headers_included(web: TestClient) -> None:
    """A site that answers a byte at a time cannot hold the request: the fetch stops at the deadline, however the time is
    spent (security review of 0.19)."""
    import threading
    import time

    import httpx2

    release = threading.Event()

    def slow(request: httpx2.Request) -> httpx2.Response:
        release.wait(10)
        return httpx2.Response(200, headers={"Content-Type": "text/html"}, content=b"<p>late</p>")

    attach_site(web.app, FakeSite())
    fetcher = web.app.state.recipe_fetcher
    fetcher.direct = httpx2.MockTransport(slow)
    fetcher.deadline_s = 0.3
    started = time.monotonic()
    assert fetch_page(web).json()["code"] == "timeout"
    assert time.monotonic() - started < 3
    release.set()


def test_a_charset_that_is_not_a_text_encoding_is_read_as_utf8(web: TestClient) -> None:
    site = attach_site(web.app, FakeSite())
    for charset in ("zlib", "base64", "hex", "rot13"):
        html = page_html(recipe_jsonld(name="Lemon chicken")).replace("<head>", f'<head><meta charset="{charset}">')
        site.pages["/lemon-chicken"] = (200, {"Content-Type": f"text/html; charset={charset}"}, html.encode("utf-8"))
        r = fetch_page(web)
        assert r.status_code == 200 and r.json()["name"] == "Lemon chicken", charset


def test_tag_stripping_stays_fast_on_text_full_of_angle_brackets() -> None:
    import time

    started = time.monotonic()
    for _ in range(300):  # a page's worth of values, each at the 4,000-character cap and full of "<"
        P.text_of("<" * 3996 + "rice")
    assert time.monotonic() - started < 1.0  # the old pattern took about 4 seconds here
    assert P.text_of("1 <b>cup</b> rice") == "1 cup rice"


@pytest.mark.parametrize("line", ["(" * 300, "(" + " " * 299, "A" * 299 + "1", "2" + " " * 298 + "x", "(" * 150 + "1 cup)" * 20])
def test_hostile_ingredient_lines_stay_fast(line: str) -> None:
    """Lines CodeQL flagged as possibly slow for a regex (code scanning 31-36): each parses at once."""
    import time

    started = time.monotonic()
    for _ in range(50):
        P.parse_line(line)
        P.search_terms(line)
    assert time.monotonic() - started < 1.0
