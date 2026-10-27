"""The assistant's tools that save (``log_food``, ``save_recipe``; assistant step 1, part C;
``docs/dev/plans/assistant-step1.md``; ARCHITECTURE.md "Assistant MCP server").

They need a token made with "Can also save food and recipes" (scope ``assistant:log``). Everything goes
through the app's own code: the entries through ``POST /api/log``'s function, the recipe through the saved-meals
code, a USDA food through the import route's code. Nothing here uses the network: FoodData Central is a mock.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any

import httpx2
import pytest

from app import egress
from app import foods as foods_module
from app import log as log_module
from conftest import DAY, USER_PASSWORD, TestClient, make_settings, signed_in_client
from test_api_tokens import audit_rows, db, make, switch
from test_mcp import TARGETS, call, call_raw, rpc, set_targets, tool_error

WRITE_TOOLS = {"log_food", "save_recipe"}
READ_TOOLS = {"get_today", "search_foods", "check_meal", "safety_check"}
READ_ONLY = "This token can only read. The person can make a token that can also save in Settings → Assistant access."
NOTE = "Numbers come from the app; fetch them again after any change."


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    switch(client, True)
    return client


@pytest.fixture
def reader(admin: TestClient) -> str:
    return make(admin, "reader")["token"]


@pytest.fixture
def saver(admin: TestClient) -> str:
    return make(admin, "Open WebUI", can_log=True)["token"]


def entries(client: TestClient, date: str = DAY) -> list[dict[str, Any]]:
    r = client.get("/api/log", params={"date": date})
    assert r.status_code == 200, r.text
    return r.json()["entries"]


def saved_meals(client: TestClient) -> list[dict[str, Any]]:
    return client.get("/api/meals").json()["meals"]


def my_foods(client: TestClient, query: str) -> list[dict[str, Any]]:
    return client.get("/api/foods", params={"q": query}).json()["foods"]


def count(client: TestClient, table: str) -> int:
    conn = db(client)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def nothing_saved(client: TestClient, date: str = DAY) -> None:
    assert entries(client, date) == [] and saved_meals(client) == []
    assert audit_rows(client, "assistant.food_logged") == [] and audit_rows(client, "assistant.recipe_saved") == []


def block_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any outbound request from the server (through the SSRF-checked transport) fails the test."""
    def no_http(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the server must not fetch anything here")

    monkeypatch.setattr(egress.CheckedTransport, "handle_request", no_http)
    monkeypatch.setattr(foods_module, "usda_client", no_http)


def soup(client: TestClient, name: str = "Mystery soup") -> dict[str, Any]:
    """A food with no potassium or phosphorus value: unknown, not zero."""
    r = client.post("/api/foods", json={"name": name, "serving_desc": "1 cup (240 g)", "serving_g": 240,
                                        "nutrients": {"carbs_g": 20, "sodium_mg": 600}})
    assert r.status_code == 201, r.text
    return r.json()


def log_food(app: Any, token: str, items: list[dict[str, Any]], meal: str = "lunch", date: str = DAY,
             **extra: Any) -> dict[str, Any]:
    return call(app, token, "log_food", items=items, meal=meal, date=date, **extra)


# --------------------------------------------------------------------------- #
# Scopes
# --------------------------------------------------------------------------- #


def test_tools_list_shows_the_saving_tools_only_to_a_token_that_can_save(admin, reader, saver):
    def listed(token: str) -> dict[str, dict[str, Any]]:
        return {t["name"]: t for t in rpc(admin.app, token, "tools/list").json()["result"]["tools"]}

    assert set(listed(reader)) == READ_TOOLS
    tools = listed(saver)
    assert set(tools) == READ_TOOLS | WRITE_TOOLS
    for name in WRITE_TOOLS:
        assert tools[name]["annotations"] == {"title": tools[name]["title"], "readOnlyHint": False,
                                              "destructiveHint": False, "idempotentHint": False,
                                              "openWorldHint": False}
        assert tools[name]["inputSchema"]["additionalProperties"] is False and len(tools[name]["description"]) > 80
    for name in READ_TOOLS:
        assert tools[name]["annotations"]["readOnlyHint"] is True
    assert tools["log_food"]["inputSchema"]["required"] == ["items", "meal"]
    assert tools["save_recipe"]["inputSchema"]["required"] == ["name", "ingredients", "servings"]
    item = tools["log_food"]["inputSchema"]["properties"]["items"]["items"]
    assert {"food", "amount", "unit", "food_id", "fdc_id"} <= set(item["properties"])


def test_initialize_tells_a_saving_token_to_confirm_first(admin, reader, saver):
    def instructions(token: str) -> str:
        return rpc(admin.app, token, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]["instructions"]

    assert "log_food" not in instructions(reader) and "Read-only" in instructions(reader)
    text = instructions(saver)
    assert "ask the person to confirm" in text and "say what was saved" in text and "never comes before" in text


def test_a_read_only_token_cannot_save_and_nothing_is_saved(admin, reader):
    app = admin.app
    good = {"items": [{"food": "banana"}], "meal": "lunch", "date": DAY}
    assert tool_error(app, reader, "log_food", good) == READ_ONLY
    assert tool_error(app, reader, "log_food", {}) == READ_ONLY  # the scope is checked before the arguments
    recipe = {"name": "Pudding", "ingredients": [{"food": "banana"}], "servings": 2}
    assert tool_error(app, reader, "save_recipe", recipe) == READ_ONLY
    assert call_raw(app, reader, "get_today", {})["isError"] is False  # reading still works
    nothing_saved(admin)
    # a tool that does not exist is still a protocol error, not a hint that it exists
    assert rpc(app, reader, "tools/call", {"name": "delete_log", "arguments": {}}).json()["error"]["code"] == -32602


# --------------------------------------------------------------------------- #
# log_food
# --------------------------------------------------------------------------- #


def test_log_food_saves_eaten_entries_exactly_as_the_log_api_would(admin, saver):
    got = log_food(admin.app, saver, [{"food": "banana", "amount": 2}, {"food": "apple juice", "amount": 1, "unit": "cup"}])
    assert got["saved"] is True and got["status"] == "eaten" and got["date"] == DAY and got["meal"] == "lunch"
    banana, juice = got["entries"]
    stored = {e["id"]: e for e in entries(admin)}
    assert set(stored) == {banana["entry_id"], juice["entry_id"]}
    for saved in got["entries"]:
        api = stored[saved["entry_id"]]
        for key in ("date", "meal", "status", "food_id", "food_name", "servings", "grams", "nutrients", "purpose"):
            assert saved[key] == api[key], key
        assert "warnings" not in saved and "kidney_rating" not in saved  # never a warning on a saved entry
    assert (banana["food_name"], banana["servings"], banana["nutrients"]["potassium_mg"]) == ("Banana, raw", 2, 844)
    assert (juice["food_name"], juice["servings"], juice["nutrients"]["potassium_mg"]) == ("Juice, apple", 2, 250)
    assert got["totals"]["potassium_mg"] == {"value": 1094, "not_listed_by": 0}
    assert got["added_to_foods"] == [] and got["source"] == "kidney-health" and got["reminder"] == NOTE
    # the day's figures after saving are get_today's, not a copy
    today = call(admin.app, saver, "get_today", date=DAY)
    assert {k: v for k, v in today.items() if k not in ("source", "reminder")} == got["day"]
    assert got["day"]["entries"] == {"eaten": 2, "planned": 0}
    assert got["day"]["nutrients"]["potassium_mg"]["eaten"] == {"value": 1094, "not_listed_by": 0}


def test_log_food_saves_planned_entries_that_count_as_planned(admin, saver):
    got = log_food(admin.app, saver, [{"food": "banana"}], meal="dinner", status="planned")
    assert got["status"] == "planned" and got["entries"][0]["status"] == "planned"
    assert [e["status"] for e in entries(admin)] == ["planned"]
    assert got["day"]["entries"] == {"eaten": 0, "planned": 1}
    potassium = got["day"]["nutrients"]["potassium_mg"]
    assert potassium["eaten"]["value"] in (0, 0.0, None) and potassium["planned"] == {"value": 422, "not_listed_by": 0}


def test_log_food_amounts_in_grams_are_kept_as_grams_like_the_log_api(admin, saver):
    got = log_food(admin.app, saver, [{"food": "banana", "amount": 100, "unit": "g"}])
    via_api = admin.post("/api/log", json={"date": "2026-10-06", "meal": "lunch", "grams": 100,
                                           "food_id": got["entries"][0]["food_id"]}).json()
    saved = got["entries"][0]
    assert saved["grams"] == 100.0 and saved["servings"] == via_api["servings"] and saved["nutrients"] == via_api["nutrients"]


def test_log_food_unknown_potassium_and_phosphorus_stay_null(admin, saver):
    set_targets(admin)
    mystery = soup(admin)
    got = log_food(admin.app, saver, [{"food": "mystery soup", "amount": 2}])
    [saved] = got["entries"]
    assert saved["food_id"] == mystery["id"] and saved["nutrients"]["carbs_g"] == 40
    assert saved["nutrients"]["potassium_mg"] is None and saved["nutrients"]["phosphorus_mg"] is None
    assert entries(admin)[0]["nutrients"]["potassium_mg"] is None  # null in the log too, never 0
    assert got["totals"]["potassium_mg"] == {"value": None, "not_listed_by": 1}
    assert got["day"]["nutrients"]["potassium_mg"]["eaten"] == {"value": None, "not_listed_by": 1}
    assert got["day"]["nutrients"]["potassium_mg"]["eaten_vs_target"]["left"] is None


def test_log_food_defaults_to_todays_date_and_refuses_what_the_log_api_refuses(admin, saver):
    today = log_module.today_local()
    got = call(admin.app, saver, "log_food", items=[{"food": "banana"}], meal="breakfast")
    assert got["date"] == today and entries(admin, today)[0]["id"] == got["entries"][0]["entry_id"]
    for bad in ("2026-02-30", "10/05/2026", "yesterday"):
        assert "date" in tool_error(admin.app, saver, "log_food", {"items": [{"food": "banana"}], "meal": "lunch", "date": bad})
        assert admin.post("/api/log", json={"date": bad, "meal": "lunch", "servings": 1,
                                            "food_id": got["entries"][0]["food_id"]}).status_code == 400
    # a day ahead is fine for a plan, as it is for the log API
    ahead = log_food(admin.app, saver, [{"food": "banana"}], date="2027-01-01", status="planned")
    assert ahead["date"] == "2027-01-01" and len(entries(admin, "2027-01-01")) == 1


def test_log_food_bad_arguments_are_tool_errors_and_save_nothing(admin, saver):
    app = admin.app
    for arguments in (
        {"items": [{"food": "banana"}]},  # no meal
        {"items": [{"food": "banana"}], "meal": "brunch"},
        {"items": [], "meal": "lunch"},
        {"items": [{"food": "banana"}], "meal": "lunch", "status": "maybe"},
        {"items": [{"food": "banana"}], "meal": "lunch", "purpose": "insulin"},
        {"items": [{"food": "banana", "amount": 0}], "meal": "lunch"},
        {"items": [{"food": "banana"}] * 21, "meal": "lunch"},
        {"items": [{"food": "banana", "unexpected": 1}], "meal": "lunch"},
        {"items": [{"food": "banana", "fdc_id": 0}], "meal": "lunch"},
    ):
        assert tool_error(app, saver, "log_food", arguments).startswith("Invalid arguments"), arguments
    nothing_saved(admin)


def test_log_food_saves_nothing_when_any_item_is_unresolved(admin, saver):
    for name in ("Rice, brown, cooked", "Rice, white, cooked"):
        admin.post("/api/foods", json={"name": name, "serving_desc": "1 cup (158 g)", "serving_g": 158,
                                       "nutrients": {"carbs_g": 44, "potassium_mg": 55}})
    got = call(admin.app, saver, "log_food", date=DAY, meal="lunch", items=[
        {"food": "banana"},
        {"food": "zzzz qqqq"},
        {"food": "rice"},
        {"food": "banana", "amount": 2, "unit": "tbsp"},
        {"food": "banana", "food_id": 999999},
    ])
    assert got["saved"] is False and "entries" not in got and "day" not in got
    assert [(u["food"], u["reason"]) for u in got["unresolved"]] == [
        ("zzzz qqqq", "no_match"), ("rice", "several_matches"), ("banana", "unknown_unit"), ("banana", "unknown_food_id")]
    assert all(u["question"].endswith(("?", ".")) for u in got["unresolved"])
    assert any("Nothing was saved" in n for n in got["notes"])
    nothing_saved(admin)
    # an ambiguous name is never guessed: the alternatives come back, and picking one saves
    rice = next(u for u in got["unresolved"] if u["reason"] == "several_matches")
    assert {a["name"] for a in rice["alternatives"]} == {"Rice, brown, cooked", "Rice, white, cooked"}
    picked = rice["alternatives"][0]["food_id"]
    done = log_food(admin.app, saver, [{"food": "banana"}, {"food": "rice", "food_id": picked}])
    assert done["saved"] is True and len(entries(admin)) == 2


def test_log_food_for_a_low_is_saved_at_once_and_never_warned_about_or_blocked(admin, saver):
    set_targets(admin)
    # glucose tablets are a treatment for a low by their flag: purpose is left out and still "hypo"
    got = log_food(admin.app, saver, [{"food": "glucose tablets", "amount": 2}])
    [tablets] = got["entries"]
    assert tablets["purpose"] == "hypo" and tablets["counted_as_treating_a_low"] is True
    # the person says a banana is for a low
    banana = log_food(admin.app, saver, [{"food": "banana"}], purpose="hypo")["entries"][0]
    assert banana["purpose"] == "hypo" and banana["counted_as_treating_a_low"] is True
    # ... and that the apple juice (a "treating a low" food) was a drink with lunch
    juice = log_food(admin.app, saver, [{"food": "apple juice"}], purpose="none")["entries"][0]
    assert juice["purpose"] is None and juice["counted_as_treating_a_low"] is False
    by_id = {e["id"]: e for e in entries(admin)}
    assert [by_id[e["entry_id"]]["purpose"] for e in (tablets, banana, juice)] == ["hypo", "hypo", None]
    # the day counts it the way Today does: in the totals, never toward the meal's carbohydrate goal
    day = call(admin.app, saver, "get_today", date=DAY)
    lunch = day["meal_carbohydrate"]["meals"]["lunch"]
    low_g = round(2 * 16 + 26.95, 1)
    assert lunch["treating_a_low_g"] == low_g and lunch["eaten_g"] == round(low_g + 14, 1)
    assert lunch["left_g"] == TARGETS["carbs_per_meal_g"] - 14 and lunch["over"] is False
    assert day["nutrients"]["carbs_g"]["eaten"]["value"] == round(low_g + 14, 1)
    # a large amount of a quick carbohydrate is saved like any other: nothing is blocked or warned
    big = log_food(admin.app, saver, [{"food": "glucose tablets", "amount": 10}])
    assert big["saved"] is True and big["entries"][0]["purpose"] == "hypo"
    assert not json.dumps(big).lower().count("warning") and "warnings" not in big["entries"][0]
    assert call(admin.app, saver, "get_today", date=DAY)["meal_carbohydrate"]["meals"]["lunch"]["left_g"] == 31


def test_another_persons_food_id_is_not_found_and_never_leaked(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    token = make(admin, "mine", can_log=True)["token"]
    theirs = sam.post("/api/foods", json={"name": "Sam secret stew", "serving_desc": "1 bowl (300 g)", "serving_g": 300,
                                          "nutrients": {"carbs_g": 30}}).json()
    got = call(admin.app, token, "log_food", date=DAY, meal="lunch", items=[{"food": "stew", "food_id": theirs["id"]}])
    assert got["saved"] is False and got["unresolved"][0]["reason"] == "unknown_food_id"
    assert "Sam" not in json.dumps(got) and "secret" not in json.dumps(got)
    by_name = call(admin.app, token, "log_food", date=DAY, meal="lunch", items=[{"food": "Sam secret stew"}])
    assert by_name["saved"] is False and by_name["unresolved"][0]["reason"] == "no_match"
    recipe = call(admin.app, token, "save_recipe", name="Stew", servings=2, ingredients=[{"food": "x", "food_id": theirs["id"]}])
    assert recipe["saved"] is False and recipe["unresolved"][0]["reason"] == "unknown_food_id"
    assert entries(admin) == [] and entries(sam) == [] and saved_meals(admin) == [] and saved_meals(sam) == []


def test_a_failure_part_way_saves_nothing(admin, saver, monkeypatch):
    real = log_module.insert_logged
    calls = {"n": 0}

    def flaky(conn: sqlite3.Connection, user_id: int, body: Any, where: str = "") -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk on fire")
        return real(conn, user_id, body, where)

    monkeypatch.setattr(log_module, "insert_logged", flaky)
    text = tool_error(admin.app, saver, "log_food", {"items": [{"food": "banana"}, {"food": "apple juice"}],
                                                      "meal": "lunch", "date": DAY})
    assert "nothing was saved" in text and "disk" not in text  # no detail from inside
    assert calls["n"] == 2
    nothing_saved(admin)
    monkeypatch.setattr(log_module, "insert_logged", real)
    assert log_food(admin.app, saver, [{"food": "banana"}, {"food": "apple juice"}])["saved"] is True
    assert len(entries(admin)) == 2


def test_a_failure_after_saving_still_reports_the_save(admin, saver, monkeypatch):
    """The entries are committed; if only the day's figures fail, the answer must not look like a failed save."""
    import app.mcp.tools as tools

    def broken(call: Any, args: Any) -> dict[str, Any]:
        raise RuntimeError("figures broke")

    monkeypatch.setattr(tools, "get_today", broken)
    got = log_food(admin.app, saver, [{"food": "banana"}])
    assert got["saved"] is True and got["day"] is None and any("get_today" in n for n in got["notes"])
    assert len(entries(admin)) == 1


# --------------------------------------------------------------------------- #
# USDA foods named by fdc_id
# --------------------------------------------------------------------------- #

NECTAR = {
    "fdcId": 2000001, "description": "MANGO NECTAR", "dataType": "Branded", "brandOwner": "Acme Drinks",
    "brandedFoodCategory": "Fruit & Vegetable Juice, Nectars & Fruit Drinks", "servingSize": 240,
    "servingSizeUnit": "ml", "householdServingFullText": "1 cup",
    "foodNutrients": [{"nutrientNumber": "208", "value": 50}, {"nutrientNumber": "205", "value": 12.5},
                      {"nutrientNumber": "307", "value": 10}],
}
CHIPS = {
    "fdcId": 777777, "description": "BANANA CHIPS", "dataType": "Branded", "brandOwner": "Acme Foods",
    "servingSize": 28, "servingSizeUnit": "g",
    "foodNutrients": [{"nutrientNumber": "208", "value": 519}, {"nutrientNumber": "205", "value": 58},
                      {"nutrientNumber": "306", "value": 536}],
}
USDA_RECORDS = {2000001: NECTAR, 777777: CHIPS}


@pytest.fixture
def usda_admin(tmp_path, foods_json, monkeypatch):
    seen: list[httpx2.Request] = []
    failing: dict[int, int] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        prefix = "/fdc/v1/food/"
        if request.url.path.startswith(prefix):
            fdc_id = int(request.url.path[len(prefix):])
            if fdc_id in failing:
                return httpx2.Response(failing[fdc_id], json={"error": "no"})
            if fdc_id in USDA_RECORDS:
                return httpx2.Response(200, json=USDA_RECORDS[fdc_id])
        return httpx2.Response(404, json={"error": "not found"})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    with signed_in_client(make_settings(tmp_path, foods_json, usda_api_key="TESTKEY")) as c:
        switch(c, True)
        c.seen_requests = seen  # type: ignore[attr-defined]
        c.failing = failing  # type: ignore[attr-defined]
        yield c


def lookups(client: Any, fdc_id: int) -> int:
    return sum(1 for r in client.seen_requests if r.url.path == f"/fdc/v1/food/{fdc_id}")


def test_check_meal_reads_a_usda_food_by_fdc_id_and_saves_nothing(usda_admin):
    token = make(usda_admin, "reader")["token"]
    got = call(usda_admin.app, token, "check_meal", date=DAY, meal="lunch",
               items=[{"food": "mango nectar", "fdc_id": 2000001, "amount": 2}])
    [item] = got["items"]
    assert item["matched"] == {"food_id": None, "name": "MANGO NECTAR", "brand": "Acme Drinks", "source": "usda",
                               "in_app": False, "fdc_id": 2000001}
    assert item["how_matched"] == "fdc_id" and item["amount"]["servings"] == 2 and "not in the person's food list" in item["note"]
    assert item["nutrients"]["carbs_g"] == 60 and item["nutrients"]["potassium_mg"] is None
    assert got["totals"]["carbs_g"] == {"value": 60, "not_listed_by": 0}
    assert got["totals"]["potassium_mg"] == {"value": None, "not_listed_by": 1}
    assert got["day_with_these_items"]["carbs_g"]["total"]["value"] == 60
    # read-only: not in the person's foods, no link, no entry; the key never travelled in the URL
    assert my_foods(usda_admin, "mango") == [] and count(usda_admin, "user_food_links") == 0
    assert count(usda_admin, "log_entries") == 0 and not [f for f in my_foods(usda_admin, "nectar")]
    assert lookups(usda_admin, 2000001) == 1 and all("TESTKEY" not in str(r.url) for r in usda_admin.seen_requests)
    assert "TESTKEY" not in json.dumps(got)


def test_log_food_adds_a_usda_food_to_the_list_first_then_logs_it_by_its_new_id(usda_admin):
    token = make(usda_admin, "Open WebUI", can_log=True)["token"]
    assert my_foods(usda_admin, "mango") == []
    got = log_food(usda_admin.app, token, [{"food": "mango nectar", "fdc_id": 2000001, "amount": 2}, {"food": "banana"}])
    [added] = got["added_to_foods"]
    assert added["fdc_id"] == 2000001 and added["name"] == "MANGO NECTAR" and isinstance(added["food_id"], int)
    nectar = got["entries"][0]
    assert nectar["food_id"] == added["food_id"] and nectar["food_name"] == "MANGO NECTAR"
    assert nectar["servings"] == 2 and nectar["nutrients"]["carbs_g"] == 60 and nectar["nutrients"]["potassium_mg"] is None
    # the person's list has it now, as an import through the app would leave it
    [food] = my_foods(usda_admin, "mango")
    assert food["id"] == added["food_id"] and food["source"] == "usda" and food["fdc_id"] == 2000001
    via_api = usda_admin.get(f"/api/foods/{added['food_id']}").json()
    assert via_api["nutrients"]["carbs_g"] == 30 and via_api["serving_desc"] == "1 cup (240 mL)"
    assert {e["food_id"] for e in entries(usda_admin)} == {added["food_id"], got["entries"][1]["food_id"]}
    assert lookups(usda_admin, 2000001) == 1 and count(usda_admin, "user_food_links") == 1
    # the next time it is in the list: no new lookup, nothing added again
    again = log_food(usda_admin.app, token, [{"food": "mango nectar", "fdc_id": 2000001}])
    assert again["added_to_foods"] == [] and again["entries"][0]["food_id"] == added["food_id"]
    assert lookups(usda_admin, 2000001) == 1 and count(usda_admin, "user_food_links") == 1
    # and search_foods now shows it as one of the person's own
    found = call(usda_admin.app, token, "search_foods", query="mango")["results"][0]
    assert found["in_app"] is True and found["id"] == added["food_id"]
    [row] = audit_rows(usda_admin, "assistant.food_logged")[:1]
    assert row["details"]["foods_added"] == 1


def test_a_usda_food_named_twice_is_fetched_and_added_once(usda_admin):
    token = make(usda_admin, "x", can_log=True)["token"]
    got = log_food(usda_admin.app, token, [{"food": "nectar", "fdc_id": 2000001}, {"food": "nectar", "fdc_id": 2000001, "amount": 3}])
    assert len(got["added_to_foods"]) == 1 and lookups(usda_admin, 2000001) == 1
    assert got["entries"][0]["food_id"] == got["entries"][1]["food_id"]
    assert len(my_foods(usda_admin, "mango")) == 1


def test_nothing_is_added_to_the_list_when_another_item_is_unresolved(usda_admin):
    token = make(usda_admin, "x", can_log=True)["token"]
    got = call(usda_admin.app, token, "log_food", date=DAY, meal="lunch",
               items=[{"food": "nectar", "fdc_id": 2000001}, {"food": "zzzz qqqq"}])
    assert got["saved"] is False and [u["reason"] for u in got["unresolved"]] == ["no_match"]
    assert my_foods(usda_admin, "mango") == [] and count(usda_admin, "user_food_links") == 0
    assert entries(usda_admin) == []


def test_a_failed_usda_lookup_is_an_unresolved_item_and_saves_nothing(usda_admin):
    token = make(usda_admin, "x", can_log=True)["token"]
    usda_admin.failing[777777] = 500
    got = call(usda_admin.app, token, "log_food", date=DAY, meal="lunch", items=[
        {"food": "nectar", "fdc_id": 2000001}, {"food": "chips", "fdc_id": 777777}, {"food": "ghost", "fdc_id": 31337}])
    assert got["saved"] is False
    assert [(u["food"], u["reason"]) for u in got["unresolved"]] == [("chips", "usda_unavailable"), ("ghost", "unknown_fdc_id")]
    assert "TESTKEY" not in json.dumps(got)
    assert entries(usda_admin) == [] and my_foods(usda_admin, "mango") == [] and count(usda_admin, "user_food_links") == 0


def test_a_usda_food_without_a_key_says_so(admin, saver):
    got = call(admin.app, saver, "log_food", date=DAY, meal="lunch", items=[{"food": "nectar", "fdc_id": 2000001}])
    [unresolved] = got["unresolved"]
    assert got["saved"] is False and unresolved["reason"] == "usda_unavailable"
    assert foods_module.USDA_UNAVAILABLE["not_configured"] in unresolved["question"]


def test_an_fdc_id_also_finds_a_builtin_food_that_carries_it(usda_admin):
    token = make(usda_admin, "x", can_log=True)["token"]
    got = log_food(usda_admin.app, token, [{"food": "banana", "fdc_id": 173944}])  # the fixture's built-in banana
    assert got["entries"][0]["food_name"] == "Banana, raw" and got["added_to_foods"] == []
    assert usda_admin.seen_requests == []  # no lookup: the person has this food already


def test_food_id_wins_over_fdc_id(usda_admin):
    token = make(usda_admin, "x", can_log=True)["token"]
    banana = my_foods(usda_admin, "banana")[0]["id"]
    got = log_food(usda_admin.app, token, [{"food": "x", "food_id": banana, "fdc_id": 2000001}])
    assert got["entries"][0]["food_id"] == banana and usda_admin.seen_requests == []


# --------------------------------------------------------------------------- #
# save_recipe
# --------------------------------------------------------------------------- #

RECIPE = {"name": "Banana pudding", "servings": 4, "source_url": "https://example.com/recipes/banana-pudding?id=7",
          "ingredients": [{"food": "banana", "amount": 3}, {"food": "apple juice", "amount": 1, "unit": "cup"}]}


def test_save_recipe_creates_a_saved_meal_the_meals_api_shows_to_that_person_only(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    token = make(admin, "Open WebUI", can_log=True)["token"]
    got = call(admin.app, token, "save_recipe", **RECIPE)
    assert got["saved"] is True and got["servings_made"] == 4 and got["source_url"] == RECIPE["source_url"]
    meal = got["meal"]
    assert meal["name"] == "Banana pudding"
    assert meal["note"] is None and meal["servings_made"] == 4  # schema step 21: no more "Makes 4 servings." note
    assert meal["source_url"] == "https://example.com/recipes/banana-pudding?id=7"
    api = admin.get(f"/api/meals/{meal['id']}").json()
    assert api["name"] == meal["name"] and api["note"] == meal["note"] and api["meal_hint"] is None
    assert (api["servings_made"], api["source_url"]) == (meal["servings_made"], meal["source_url"])
    assert api["per_serving"]["potassium_mg"] == round((3 * 422 + 2 * 125) / 4)
    assert [(i["food_name"], i["servings"]) for i in api["items"]] == [("Banana, raw", 3), ("Juice, apple", 2)]  # the whole recipe
    assert [i["food_id"] for i in meal["items"]] == [i["food_id"] for i in api["items"]]
    assert meal["items"][0]["nutrients"] == api["items"][0]["nutrients"]
    assert got["totals_whole_recipe"]["potassium_mg"] == {"value": 3 * 422 + 2 * 125, "not_listed_by": 0}
    assert got["totals_per_serving"]["potassium_mg"] == {"value": round((3 * 422 + 2 * 125) / 4), "not_listed_by": 0}
    assert got["totals_whole_recipe"]["potassium_mg"]["value"] == api["totals"]["potassium_mg"]
    assert [m["id"] for m in saved_meals(admin)] == [meal["id"]]
    assert saved_meals(sam) == [] and sam.get(f"/api/meals/{meal['id']}").status_code == 404  # only theirs
    assert entries(admin) == []  # a recipe is not eaten


def test_save_recipe_one_serving_without_a_link_and_unknown_values_stay_unknown(admin, saver):
    soup(admin)
    got = call(admin.app, saver, "save_recipe", name="Plain soup", servings=1, ingredients=[{"food": "mystery soup"}, {"food": "banana"}])
    assert got["meal"]["servings_made"] == 1 and got["meal"]["source_url"] is None and got["source_url"] is None
    assert got["totals_whole_recipe"]["potassium_mg"] == {"value": 422, "not_listed_by": 1}  # at least
    assert got["totals_per_serving"]["phosphorus_mg"] == {"value": 26, "not_listed_by": 1}
    half = call(admin.app, saver, "save_recipe", name="Half", servings=2.5, ingredients=[{"food": "mystery soup"}])
    assert half["meal"]["servings_made"] == 2.5 and half["meal"]["note"] is None
    assert half["totals_whole_recipe"]["potassium_mg"] == {"value": None, "not_listed_by": 1}
    assert half["totals_per_serving"]["potassium_mg"] == {"value": None, "not_listed_by": 1}  # never 0


def test_save_recipe_with_an_unresolved_ingredient_saves_nothing(admin, saver):
    got = call(admin.app, saver, "save_recipe", name="Stew", servings=2, ingredients=[{"food": "banana"}, {"food": "zzzz qqqq"}])
    assert got["saved"] is False and got["unresolved"][0]["reason"] == "no_match" and "meal" not in got
    assert saved_meals(admin) == [] and audit_rows(admin, "assistant.recipe_saved") == []


def test_save_recipe_with_a_usda_ingredient_adds_the_food(usda_admin):
    token = make(usda_admin, "x", can_log=True)["token"]
    got = call(usda_admin.app, token, "save_recipe", name="Mango mix", servings=2,
               ingredients=[{"food": "nectar", "fdc_id": 2000001, "amount": 2}, {"food": "banana"}])
    [added] = got["added_to_foods"]
    assert added["fdc_id"] == 2000001 and [i["food_id"] for i in got["meal"]["items"]][0] == added["food_id"]
    assert my_foods(usda_admin, "mango")[0]["id"] == added["food_id"]
    assert got["totals_whole_recipe"]["carbs_g"] == {"value": 87, "not_listed_by": 0}  # 60 + 26.95, whole grams


@pytest.mark.parametrize("url", ["ftp://example.com/a", "javascript:alert(1)", "file:///etc/passwd", "example.com/recipe",
                                 "https://user:secret@example.com/r", "https://exa mple.com/r", "https://example.com/r\nX: y",
                                 "https://", "http:///nohost", "https://example.com:0/r", "https://example.com:99999/r",
                                 "https://example.com/" + "a" * 900])
def test_save_recipe_refuses_a_source_that_is_not_a_plain_web_link(admin, saver, monkeypatch, url):
    block_outbound(monkeypatch)
    text = tool_error(admin.app, saver, "save_recipe", {**RECIPE, "source_url": url})
    assert "source_url" in text and "secret" not in text
    assert saved_meals(admin) == []


def test_save_recipe_name_and_size_rules(admin, saver, monkeypatch):
    block_outbound(monkeypatch)
    for bad in ({"name": ""}, {"name": "x" * 61}, {"servings": 0}, {"servings": -1}, {"servings": 101}, {"ingredients": []},
                {"ingredients": [{"food": "banana"}] * 31}, {"source_url": ""}, {"extra": 1}):
        assert tool_error(admin.app, saver, "save_recipe", {**RECIPE, **bad}).startswith("Invalid arguments"), bad
    assert saved_meals(admin) == []
    ok = call(admin.app, saver, "save_recipe", **{**RECIPE, "name": "  " + "x" * 58 + "  ", "source_url": "http://example.org/" + "a" * 880})
    assert ok["meal"]["name"] == "x" * 58 and len(ok["meal"]["source_url"]) == 899
    assert admin.get(f"/api/meals/{ok['meal']['id']}").status_code == 200
    # the stored meal can be edited again in the app, and a PUT without the recipe fields keeps them
    put = admin.put(f"/api/meals/{ok['meal']['id']}", json={"name": "Renamed", "note": ok["meal"]["note"],
                                                           "items": [{"food_id": i["food_id"], "servings": i["servings"]} for i in ok["meal"]["items"]]})
    assert put.status_code == 200, put.text
    assert (put.json()["servings_made"], put.json()["source_url"]) == (RECIPE["servings"], ok["meal"]["source_url"])


# --------------------------------------------------------------------------- #
# Activity log
# --------------------------------------------------------------------------- #


def test_every_save_is_in_the_activity_log_with_the_token_name_and_never_the_token(admin):
    made = make(admin, "Kitchen tablet", can_log=True)
    token = made["token"]
    log_food(admin.app, token, [{"food": "banana"}, {"food": "apple juice"}], meal="dinner", status="planned")
    call(admin.app, token, "save_recipe", **RECIPE)
    [logged] = audit_rows(admin, "assistant.food_logged")
    assert (logged["target_type"], logged["target_id"]) == ("api_token", str(made["id"]))
    assert logged["details"] == {"via": "Kitchen tablet", "entries": 2, "status": "planned", "meal": "dinner",
                                 "date": DAY, "foods_added": 0}
    [recipe] = audit_rows(admin, "assistant.recipe_saved")
    assert recipe["details"] == {"via": "Kitchen tablet", "name": "Banana pudding", "ingredients": 2, "servings": 4.0, "foods_added": 0}
    assert recipe["target_type"] == "meal"
    conn = db(admin)
    try:
        dump = json.dumps([tuple(r) for r in conn.execute("SELECT * FROM audit_log")])
    finally:
        conn.close()
    assert token not in dump and made["prefix"] not in dump  # never the token, nor its start
    events = admin.get("/api/me/activity").json()["events"]
    mine = [e for e in events if e["action"].startswith("assistant.")]
    assert {e["action"] for e in mine} == {"assistant.food_logged", "assistant.recipe_saved"}  # the person sees them
    assert all(e["details"]["via"] == "Kitchen tablet" for e in mine)


def test_saves_that_did_not_happen_leave_no_activity(admin, saver, reader):
    call(admin.app, saver, "log_food", date=DAY, meal="lunch", items=[{"food": "zzzz"}])
    tool_error(admin.app, saver, "log_food", {"items": []})
    tool_error(admin.app, reader, "log_food", {"items": [{"food": "banana"}], "meal": "lunch"})
    nothing_saved(admin)


# --------------------------------------------------------------------------- #
# A token that has ended, the switch, the limit
# --------------------------------------------------------------------------- #


def test_a_revoked_token_or_the_switch_off_cannot_save(admin):
    made = make(admin, "Open WebUI", can_log=True)
    token = made["token"]
    body = {"name": "log_food", "arguments": {"items": [{"food": "banana"}], "meal": "lunch", "date": DAY}}
    assert rpc(admin.app, token, "tools/call", body).json()["result"]["isError"] is False
    assert len(entries(admin)) == 1
    switch(admin, False)
    off = rpc(admin.app, token, "tools/call", body)
    assert off.status_code == 404
    switch(admin, True)
    assert admin.delete(f"/api/me/tokens/{made['id']}").status_code == 204
    gone = rpc(admin.app, token, "tools/call", body)
    assert gone.status_code == 401 and "Bearer" in gone.headers["www-authenticate"]
    assert rpc(admin.app, token, "tools/call", {**body, "name": "save_recipe"}).status_code == 401
    assert len(entries(admin)) == 1 and saved_meals(admin) == []


def test_an_expired_or_unknown_token_cannot_save(admin):
    body = {"name": "log_food", "arguments": {"items": [{"food": "banana"}], "meal": "lunch", "date": DAY}}
    assert rpc(admin.app, "kha_" + "A" * 43, "tools/call", body).status_code == 401
    assert rpc(admin.app, None, "tools/call", body).status_code == 401
    assert entries(admin) == []


def test_saving_counts_toward_the_sixty_requests_a_minute(admin, saver, fake_clock):
    item = [{"food": "water"}]
    for _ in range(60):
        r = rpc(admin.app, saver, "tools/call", {"name": "log_food", "arguments": {"items": item, "meal": "snack", "date": DAY}})
        assert r.status_code == 200 and r.json()["result"]["isError"] is False
    blocked = rpc(admin.app, saver, "tools/call", {"name": "log_food", "arguments": {"items": item, "meal": "snack", "date": DAY}})
    assert blocked.status_code == 429 and 1 <= int(blocked.headers["retry-after"]) <= 60
    assert len(entries(admin)) == 60  # the 61st saved nothing
    fake_clock.advance(seconds=61)
    assert rpc(admin.app, saver, "tools/call", {"name": "log_food", "arguments": {"items": item, "meal": "snack", "date": DAY}}).status_code == 200
    assert len(entries(admin)) == 61


# --------------------------------------------------------------------------- #
# Wording
# --------------------------------------------------------------------------- #


@pytest.mark.safety
def test_the_saving_tools_speak_of_no_doses_or_medicines():
    from app.mcp import server as mcp_server
    from app.mcp import tools as mcp_tools

    dosing = re.compile(r"\b(insulin|bolus|basal|doses?|dosing|correction|ratios?|binders?|medicines?|medications?)\b", re.I)
    for tool in (mcp_tools.TOOLS_BY_NAME[n] for n in WRITE_TOOLS):
        assert not dosing.search(tool.description) and not dosing.search(json.dumps(tool.input_schema)), tool.name
    assert not dosing.search(mcp_server.WRITE_INSTRUCTIONS) and not dosing.search(mcp_tools.READ_ONLY)
    for text in (mcp_tools.TOOLS_BY_NAME["log_food"].description, mcp_server.WRITE_INSTRUCTIONS):
        assert not re.search(r"\b(wait|hold off|too much sugar|avoid|should not)\b", text, re.I), text  # never against a low


# --------------------------------------------------------------------------- #
# Retries: request_key (schema step 11; app/mcp/request_keys.py)
# --------------------------------------------------------------------------- #

KEY = "retry-key-0001"


def key_rows(client: TestClient) -> list[dict[str, Any]]:
    conn = db(client)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM assistant_request_keys ORDER BY created_at, key_hash")]
    finally:
        conn.close()


def two_logged(app: Any, token: str, key: str | None = KEY, **extra: Any) -> dict[str, Any]:
    items = [{"food": "banana", "amount": 2}, {"food": "apple juice", "amount": 1, "unit": "cup"}]
    return log_food(app, token, items, **({"request_key": key} if key else {}), **extra)


def test_the_saving_tools_list_request_key_and_tell_the_model_when_to_reuse_it(admin, saver):
    tools = {t["name"]: t for t in rpc(admin.app, saver, "tools/list").json()["result"]["tools"]}
    for name in WRITE_TOOLS:
        key = tools[name]["inputSchema"]["properties"]["request_key"]
        assert (key["type"], key["minLength"], key["maxLength"], key["pattern"]) == ("string", 8, 64, r"^[A-Za-z0-9_-]+$")
        assert "request_key" not in tools[name]["inputSchema"]["required"]  # optional
        assert "new request_key with each save" in tools[name]["description"]
        assert "only to retry that same save" in tools[name]["description"]
    text = rpc(admin.app, saver, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]["instructions"]
    assert "request_key" in text and "only to retry" in text


def test_log_food_repeat_with_the_same_key_saves_nothing_and_answers_with_the_first_save(admin, saver):
    first = two_logged(admin.app, saver)
    assert first["saved"] is True and "duplicate" not in first and len(first["entries"]) == 2
    before = entries(admin)
    assert len(before) == 2 and audit_rows(admin, "assistant.food_logged")[0]["details"]["entries"] == 2
    for _ in range(2):  # and again: still the first save
        again = two_logged(admin.app, saver)
        assert again["saved"] is True and again["duplicate"] is True
        assert [e["entry_id"] for e in again["entries"]] == [e["entry_id"] for e in first["entries"]]
        for key in ("date", "meal", "status", "entries", "added_to_foods", "totals", "day"):
            assert again[key] == first[key], key
        assert any("already saved" in n and "nothing was saved again" in n for n in again["notes"])
        assert entries(admin) == before  # nothing new: the eaten count is unchanged
        assert again["day"]["entries"] == {"eaten": 2, "planned": 0}
    assert len(audit_rows(admin, "assistant.food_logged")) == 1  # only the first call saved


def test_a_repeat_with_other_items_but_the_same_key_is_still_the_first_save_and_says_how_to_save_a_new_one(admin, saver):
    first = two_logged(admin.app, saver)
    other = log_food(admin.app, saver, [{"food": "banana", "amount": 5}], meal="dinner", request_key=KEY)
    assert other["duplicate"] is True and [e["entry_id"] for e in other["entries"]] == [e["entry_id"] for e in first["entries"]]
    assert other["meal"] == "lunch" and len(entries(admin)) == 2
    assert any("different save" in n and "new request_key" in n for n in other["notes"])
    new = log_food(admin.app, saver, [{"food": "banana", "amount": 5}], meal="dinner", request_key="retry-key-0002")
    assert new["saved"] is True and "duplicate" not in new and len(entries(admin)) == 3


def test_without_a_key_every_call_saves_again_as_before(admin, saver):
    one, two = two_logged(admin.app, saver, key=None), two_logged(admin.app, saver, key=None)
    assert "duplicate" not in one and "duplicate" not in two and len(entries(admin)) == 4
    assert key_rows(admin) == []


def test_the_key_is_stored_hashed_with_the_token_id_and_never_in_the_clear(admin):
    from app.mcp import request_keys

    made = make(admin, "Kitchen tablet", can_log=True)
    first = two_logged(admin.app, made["token"])
    [row] = key_rows(admin)
    assert row["key_hash"] == request_keys.key_hash(made["id"], KEY) and re.fullmatch(r"[0-9a-f]{64}", row["key_hash"])
    assert row["key_hash"] != hashlib.sha256(KEY.encode()).hexdigest()  # the token id is part of it
    assert (row["user_id"], row["token_id"], row["tool"]) == (1, made["id"], "log_food")
    assert json.loads(row["saved_json"])["entry_ids"] == [e["entry_id"] for e in first["entries"]]
    conn = db(admin)
    try:
        dump = json.dumps([tuple(r) for table in ("assistant_request_keys", "audit_log")
                           for r in conn.execute(f"SELECT * FROM {table}")])
    finally:
        conn.close()
    assert KEY not in dump  # not in the table, not in the activity log


def test_a_repeat_reads_the_entries_from_the_database_again(admin, saver):
    first = two_logged(admin.app, saver)
    banana, juice = (e["entry_id"] for e in first["entries"])
    assert admin.put(f"/api/log/{banana}", json={"servings": 3}).status_code == 200  # edited since
    edited = two_logged(admin.app, saver)
    assert edited["duplicate"] is True and edited["entries"][0]["servings"] == 3
    assert edited["entries"][0]["nutrients"]["potassium_mg"] == 3 * 422
    assert edited["day"]["nutrients"]["potassium_mg"]["eaten"]["value"] == 3 * 422 + 2 * 125
    assert admin.delete(f"/api/log/{juice}").status_code == 204  # one deleted since: say so, never save it again
    partly = two_logged(admin.app, saver)
    assert partly["saved"] is True and partly["duplicate"] is True and [e["entry_id"] for e in partly["entries"]] == [banana]
    assert any("1 of the 2 entries" in n and "not in the log" in n for n in partly["notes"])
    assert admin.delete(f"/api/log/{banana}").status_code == 204  # all deleted since
    gone = two_logged(admin.app, saver)
    assert gone["saved"] is False and gone["duplicate"] is True and gone["entries"] == []
    assert "day" not in gone and any("none of them is in the log" in n and "new request_key" in n for n in gone["notes"])
    assert entries(admin) == [] and len(audit_rows(admin, "assistant.food_logged")) == 1  # nothing was saved again
    fresh = two_logged(admin.app, saver, key="retry-key-0002")  # a new key saves
    assert fresh["saved"] is True and len(entries(admin)) == 2


def test_a_key_is_stored_only_when_the_save_succeeded(admin, saver, monkeypatch):
    unresolved = log_food(admin.app, saver, [{"food": "zzzz qqqq"}], request_key=KEY)
    assert unresolved["saved"] is False and "duplicate" not in unresolved and key_rows(admin) == []
    assert tool_error(admin.app, saver, "log_food", {"items": [], "meal": "lunch", "request_key": KEY}).startswith("Invalid")
    assert key_rows(admin) == []
    real = log_module.insert_logged
    calls = {"n": 0}

    def flaky(conn: sqlite3.Connection, user_id: int, body: Any, where: str = "") -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk on fire")
        return real(conn, user_id, body, where)

    monkeypatch.setattr(log_module, "insert_logged", flaky)
    assert "nothing was saved" in tool_error(admin.app, saver, "log_food", {
        "items": [{"food": "banana"}, {"food": "apple juice"}], "meal": "lunch", "date": DAY, "request_key": KEY})
    nothing_saved(admin)
    assert key_rows(admin) == []  # the key was rolled back with the save
    monkeypatch.setattr(log_module, "insert_logged", real)
    done = two_logged(admin.app, saver)  # the retry with the same key is a real save, not a duplicate
    assert done["saved"] is True and "duplicate" not in done and len(entries(admin)) == 2 and len(key_rows(admin)) == 1


def test_a_key_expires_after_24_hours_and_old_keys_are_deleted(admin, saver, fake_clock):
    two_logged(admin.app, saver)
    [old] = key_rows(admin)
    fake_clock.advance(hours=23, minutes=59)
    assert two_logged(admin.app, saver)["duplicate"] is True and len(entries(admin)) == 2
    fake_clock.advance(minutes=2)  # now more than 24 hours since the first save
    again = two_logged(admin.app, saver)
    assert again["saved"] is True and "duplicate" not in again and len(entries(admin)) == 4
    [new] = key_rows(admin)  # the expired row was replaced, not left behind
    assert new["key_hash"] == old["key_hash"] and new["created_at"] > old["created_at"]
    assert two_logged(admin.app, saver)["duplicate"] is True  # and the new one counts from now
    # a daily clean-up removes keys nobody asked for again
    from app.mcp import request_keys

    fake_clock.advance(hours=25)
    conn = db(admin)
    try:
        assert request_keys.purge_old(conn) == 1
        assert conn.execute("SELECT COUNT(*) FROM assistant_request_keys").fetchone()[0] == 0
    finally:
        conn.close()


def test_a_key_is_independent_for_another_token_and_for_another_person(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    mine = make(admin, "mine", can_log=True)["token"]
    other_token = make(admin, "second", can_log=True)["token"]
    theirs = make(sam, "theirs", can_log=True)["token"]
    first = two_logged(admin.app, mine)
    assert two_logged(admin.app, mine)["duplicate"] is True
    second = two_logged(admin.app, other_token)  # the same person's other token: its own key
    assert second["saved"] is True and "duplicate" not in second and len(entries(admin)) == 4
    for_sam = two_logged(sam.app, theirs)  # another person, the same key text
    assert for_sam["saved"] is True and "duplicate" not in for_sam and len(entries(sam)) == 2
    assert {e["entry_id"] for e in for_sam["entries"]}.isdisjoint(e["entry_id"] for e in first["entries"])
    assert two_logged(sam.app, theirs)["duplicate"] is True and len(entries(sam)) == 2
    assert two_logged(admin.app, other_token)["entries"] == second["entries"]
    assert sorted((r["user_id"], r["tool"]) for r in key_rows(admin)) == [(1, "log_food"), (1, "log_food"), (2, "log_food")]
    # the answer to a retry only ever lists the caller's own rows, even if the stored ids point at someone else's
    conn = db(admin)
    try:
        conn.execute("UPDATE assistant_request_keys SET saved_json = ? WHERE user_id = 2",
                     (json.dumps({"entry_ids": [e["entry_id"] for e in first["entries"]]}),))
        conn.commit()
    finally:
        conn.close()
    stolen = two_logged(sam.app, theirs)
    assert stolen["saved"] is False and stolen["duplicate"] is True and stolen["entries"] == []
    assert "Banana" not in json.dumps(stolen)


def test_a_retry_that_raced_the_first_save_is_answered_as_a_duplicate_and_adds_nothing(admin, saver, monkeypatch):
    from app.mcp import request_keys
    from app.mcp import tools as mcp_tools

    first = two_logged(admin.app, saver)
    real, calls = request_keys.find, {"n": 0}

    def late(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*args, **kwargs)  # the first look (before the lock) sees nothing

    monkeypatch.setattr(mcp_tools.request_keys, "find", late)
    raced = two_logged(admin.app, saver)
    assert calls["n"] == 2 and raced["duplicate"] is True
    assert [e["entry_id"] for e in raced["entries"]] == [e["entry_id"] for e in first["entries"]]
    assert len(entries(admin)) == 2 and len(audit_rows(admin, "assistant.food_logged")) == 1 and len(key_rows(admin)) == 1


def test_the_same_key_on_the_other_saving_tool_is_refused_and_saves_nothing(admin, saver):
    two_logged(admin.app, saver)
    text = tool_error(admin.app, saver, "save_recipe", {**RECIPE, "request_key": KEY})
    assert "already used by log_food" in text and "new request_key" in text
    assert saved_meals(admin) == [] and audit_rows(admin, "assistant.recipe_saved") == []
    ok = call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": "retry-key-0002"})
    assert ok["saved"] is True and len(saved_meals(admin)) == 1
    assert "already used by save_recipe" in tool_error(admin.app, saver, "log_food", {
        "items": [{"food": "banana"}], "meal": "lunch", "date": DAY, "request_key": "retry-key-0002"})
    assert len(entries(admin)) == 2


@pytest.mark.parametrize("bad", ["short", "x" * 7, "x" * 65, "has space inside", "slash/slash/slash", "dot.dot.dot.dot",
                                 "ключ-ключ-ключ", "key\nkey\nkey\n", "        ", "", 12345678, True, ["retry-key-0001"]])
def test_a_bad_request_key_is_an_error_and_saves_nothing(admin, saver, bad):
    assert tool_error(admin.app, saver, "log_food", {"items": [{"food": "banana"}], "meal": "lunch", "date": DAY,
                                                      "request_key": bad}).startswith("Invalid arguments")
    assert tool_error(admin.app, saver, "save_recipe", {**RECIPE, "request_key": bad}).startswith("Invalid arguments")
    nothing_saved(admin)
    assert key_rows(admin) == []


@pytest.mark.parametrize("good", ["abcdefgh", "A" * 64, "a-b_C-1_2-3_", "8f14e45f-ceea-467f-a8d1-5e6a7b9c0d12"])
def test_request_keys_of_8_to_64_url_safe_characters_are_accepted(admin, saver, good):
    got = log_food(admin.app, saver, [{"food": "banana"}], request_key=good)
    assert got["saved"] is True
    assert log_food(admin.app, saver, [{"food": "banana"}], request_key=good)["duplicate"] is True
    assert len(entries(admin)) == 1


def test_save_recipe_repeat_with_the_same_key_answers_with_the_first_meal_and_saves_nothing(admin, saver):
    first = call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": KEY})
    assert first["saved"] is True and "duplicate" not in first and len(saved_meals(admin)) == 1
    for _ in range(2):
        again = call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": KEY})
        assert again["saved"] is True and again["duplicate"] is True and again["meal"] == first["meal"]
        for key in ("servings_made", "source_url", "totals_whole_recipe", "totals_per_serving", "added_to_foods"):
            assert again[key] == first[key], key
        assert any("already saved this recipe" in n and "nothing was saved again" in n for n in again["notes"])
        assert [m["id"] for m in saved_meals(admin)] == [first["meal"]["id"]]
    assert len(audit_rows(admin, "assistant.recipe_saved")) == 1
    [row] = key_rows(admin)
    assert (row["tool"], json.loads(row["saved_json"])["meal_id"]) == ("save_recipe", first["meal"]["id"])
    other = call(admin.app, saver, "save_recipe", **{**RECIPE, "name": "Other pudding", "request_key": "retry-key-0002"})
    assert other["saved"] is True and "duplicate" not in other and len(saved_meals(admin)) == 2


def test_save_recipe_repeat_reads_the_meal_from_the_database_again(admin, saver):
    first = call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": KEY})
    meal = first["meal"]
    put = admin.put(f"/api/meals/{meal['id']}", json={"name": "Renamed pudding", "note": meal["note"], "items": [
        {"food_id": i["food_id"], "servings": i["servings"]} for i in meal["items"][:1]]})  # edited since: one ingredient
    assert put.status_code == 200, put.text
    edited = call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": KEY})
    assert edited["duplicate"] is True and edited["meal"]["name"] == "Renamed pudding" and len(edited["meal"]["items"]) == 1
    assert edited["totals_whole_recipe"]["potassium_mg"] == {"value": 3 * 422, "not_listed_by": 0}
    assert edited["totals_per_serving"]["potassium_mg"] == {"value": 317, "not_listed_by": 0}  # 1266 / 4 = 316.5, rounded half up
    assert admin.delete(f"/api/meals/{meal['id']}").status_code == 204  # deleted since: say so, never save it again
    gone = call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": KEY})
    assert gone["saved"] is False and gone["duplicate"] is True and "meal" not in gone
    assert any("not in the app now" in n and "new request_key" in n for n in gone["notes"])
    assert saved_meals(admin) == [] and len(audit_rows(admin, "assistant.recipe_saved")) == 1
    assert call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": "retry-key-0002"})["saved"] is True


def test_save_recipe_key_is_stored_only_when_the_save_succeeded(admin, saver):
    bad = call(admin.app, saver, "save_recipe", name="Stew", servings=2, request_key=KEY,
               ingredients=[{"food": "banana"}, {"food": "zzzz qqqq"}])
    assert bad["saved"] is False and key_rows(admin) == [] and saved_meals(admin) == []
    done = call(admin.app, saver, "save_recipe", **{**RECIPE, "request_key": KEY})
    assert done["saved"] is True and "duplicate" not in done and len(key_rows(admin)) == 1


def test_a_deleted_account_takes_its_keys_with_it(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    token = make(sam, "theirs", can_log=True)
    two_logged(admin.app, token["token"])
    assert len(key_rows(admin)) == 1
    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    assert key_rows(admin) == []
