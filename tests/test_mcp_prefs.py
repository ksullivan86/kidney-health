"""``set_food_preference`` over MCP for a token with ``assistant:prefs`` (note 09 §4.8b; ``app/mcp/preference_tool.py``).

The in-app Ask chat proposes a taste as a card (``tests/test_ai_chat_preference.py``). An assistant connected with a token has
no card, so the tool is opt-in (a second tick when the token is made), narrow (one food or one food group, nothing else is read
or returned) and limited (30 changes a day per token). Covered: the scope and what it implies; the tick of ``POST
/api/me/tokens``; who sees the tool; the tool for a food and for a food group, every preference; the refusals (a food the person
may not use, another person's food, both or neither of ``food_id`` and ``category``, a food that treats a low); ``request_key``;
the audit row and the activity list; the daily cap; the short answer; what the Settings list shows; and that nothing about
treating a low changes (``@pytest.mark.safety``).
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Iterator

import pytest

from app.auth import api_tokens
from app.mcp import preference_tool as PT
from app.mcp import server as mcp_server
from app.mcp import tools as mcp_tools
from conftest import DAY, HTTPS_URL, TestClient, make_settings, sign_in
from test_api_tokens import audit_rows, bearer, db, make, switch
from test_mcp import call_raw, food_id, rpc, set_targets

ROOT = Path(__file__).resolve().parents[1]
TOOL = "set_food_preference"
READ_TOOLS = {"get_today", "search_foods", "check_meal", "safety_check"}
KEY = "taste-key-0001"
_keys = iter(range(10_000))


def fresh_key() -> str:
    return f"taste-key-{next(_keys):05d}"


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
    return make(admin, "saver", can_log=True)["token"]


@pytest.fixture
def taster(admin: TestClient) -> str:
    return make(admin, "Hermes", can_prefs=True)["token"]


@pytest.fixture
def real(tmp_path) -> Iterator[TestClient]:
    """The admin over HTTPS on the real built-in food list (395 foods), assistant access on."""
    from app.main import create_app

    with TestClient(create_app(make_settings(tmp_path, ROOT / "data" / "foods.json")), base_url=HTTPS_URL) as c:
        sign_in(c)
        switch(c, True)
        yield c


def taste(app: Any, token: str, **arguments: Any) -> dict[str, Any]:
    """A successful call: the structured answer."""
    arguments.setdefault("request_key", fresh_key())
    result = call_raw(app, token, TOOL, arguments)
    assert result["isError"] is False, result
    data = result["structuredContent"]
    assert json.loads(result["content"][0]["text"]) == data
    return data


def refused(app: Any, token: str, **arguments: Any) -> str:
    """A refused call: its short message, with nothing written by the caller to check."""
    arguments.setdefault("request_key", fresh_key())
    result = call_raw(app, token, TOOL, arguments)
    assert result["isError"] is True and "structuredContent" not in result, result
    return result["content"][0]["text"]


def preferences(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/guidance/preferences")
    assert r.status_code == 200, r.text
    return r.json()


def rows(client: TestClient) -> dict[str, tuple[str, str]]:
    """{food name: (preference, source)} as the Settings list shows them."""
    return {f["name"]: (f["preference"], f["source"]) for f in preferences(client)["foods"]}


def groups(client: TestClient) -> dict[str, list[str]]:
    return preferences(client)["groups"]


def sets(client: TestClient) -> list[dict[str, Any]]:
    return audit_rows(client, "assistant.preference_set")


def key_rows(client: TestClient) -> int:
    conn = db(client)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM assistant_request_keys WHERE tool = ?", (TOOL,)).fetchone()[0])
    finally:
        conn.close()


def untouched(client: TestClient) -> None:
    """Nothing was written: no preference, no group choice, no audit row, no remembered key."""
    assert preferences(client)["foods"] == [] and groups(client) == {"like": [], "less": [], "never": []}
    assert sets(client) == [] and key_rows(client) == 0


def person_puts(client: TestClient, fid: int, preference: str) -> None:
    r = client.put(f"/api/guidance/preferences/{fid}", json={"preference": preference})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# The scope
# --------------------------------------------------------------------------- #


def test_prefs_implies_read_and_nothing_else_and_log_does_not_imply_prefs():
    p = api_tokens.parse_scopes
    assert api_tokens.PREFS == "assistant:prefs" and api_tokens.SCOPES == ("assistant:read", "assistant:log", "assistant:prefs")
    assert p("assistant:prefs") == ("assistant:read", "assistant:prefs")  # read, and nothing more
    assert p("assistant:log") == ("assistant:read", "assistant:log")  # log does not give prefs
    assert p("assistant:read") == ("assistant:read",)
    assert p("assistant:prefs assistant:log") == ("assistant:read", "assistant:log", "assistant:prefs")
    assert p("assistant:prefs prefs assistant:preferences assistant:admin") == ("assistant:read", "assistant:prefs")
    # the families stay strict: a device token never holds it, and a row that mixes them grants nothing
    assert p("body:write") == ("body:write",) and p("body:write assistant:prefs") == () and p("assistant:prefs body:write") == ()
    assert api_tokens.family_of_scope("assistant:prefs") == "assistant"
    assert api_tokens.family_of_scopes("assistant:prefs") == "assistant"
    assert api_tokens.scopes_for(False) == ("assistant:read",)
    assert api_tokens.scopes_for(True) == ("assistant:read", "assistant:log")
    assert api_tokens.scopes_for(False, True) == ("assistant:read", "assistant:prefs")
    assert api_tokens.scopes_for(True, True) == ("assistant:read", "assistant:log", "assistant:prefs")
    with pytest.raises(ValueError):
        api_tokens.create(None, 1, "x", 30, ("body:write", "assistant:prefs"))  # type: ignore[arg-type]


def test_the_tick_makes_the_scope_and_is_off_by_default(admin):
    plain = make(admin, "plain")
    assert plain["scopes"] == ["assistant:read"]
    only_log = make(admin, "log", can_log=True, can_prefs=False)
    assert only_log["scopes"] == ["assistant:read", "assistant:log"]
    only_prefs = make(admin, "prefs", can_prefs=True)
    assert only_prefs["scopes"] == ["assistant:read", "assistant:prefs"]  # the tick does not give log
    both = make(admin, "both", can_log=True, can_prefs=True)
    assert both["scopes"] == ["assistant:read", "assistant:log", "assistant:prefs"]
    listed = {t["name"]: t["scopes"] for t in admin.get("/api/me/tokens").json()["tokens"]}
    assert listed["prefs"] == ["assistant:read", "assistant:prefs"] and listed["plain"] == ["assistant:read"]
    created = {r["details"]["scopes"][-1] for r in audit_rows(admin, "api_token.created")}
    assert "assistant:prefs" in created  # the activity log says what a token may do
    for body in ({"can_prefs": "yes please"}, {"can_prefs": None}, {"can_prefs": 1.5}, {"scopes": ["assistant:prefs"]},
                 {"scope": "assistant:prefs"}):
        assert admin.post("/api/me/tokens", json={"name": "x", **body}).status_code == 400, body
    assert admin.post("/api/me/tokens", json={"name": "x", "family": "device", "can_prefs": True}).status_code == 400


def test_a_token_that_can_log_or_only_read_never_gets_prefs_and_still_works(admin):
    """Tokens made before this scope existed name only read, or read and log, in their row: they keep exactly that."""
    old = make(admin, "old saver", can_log=True)
    reader = make(admin, "old reader")
    conn = db(admin)
    try:
        stored = {r["name"]: r["scopes"] for r in conn.execute("SELECT name, scopes FROM api_tokens")}
    finally:
        conn.close()
    assert stored == {"old saver": "assistant:read assistant:log", "old reader": "assistant:read"}
    names = {t["name"]: t["scopes"] for t in admin.get("/api/me/tokens").json()["tokens"]}
    assert names == {"old saver": ["assistant:read", "assistant:log"], "old reader": ["assistant:read"]}
    for token in (old["token"], reader["token"]):
        assert TOOL not in {t["name"] for t in rpc(admin.app, token, "tools/list").json()["result"]["tools"]}
        assert bearer(admin.app, token).status_code == 200


# --------------------------------------------------------------------------- #
# Who sees the tool
# --------------------------------------------------------------------------- #


def listed(app: Any, token: str) -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in rpc(app, token, "tools/list").json()["result"]["tools"]}


def test_the_tool_is_listed_and_callable_only_with_the_scope(admin, reader, saver, taster):
    app = admin.app
    foods_id = food_id(admin, "banana")
    for name, token in (("read", reader), ("read+save", saver)):
        assert TOOL not in listed(app, token), name
        r = rpc(app, token, "tools/call", {"name": TOOL, "arguments": {"food_id": foods_id, "preference": "like", "request_key": KEY}})
        assert r.json()["error"]["code"] == -32602 and "Unknown tool: set_food_preference" in r.json()["error"]["message"], name
        assert TOOL not in rpc(app, token, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]["instructions"]
    untouched(admin)
    tools = listed(app, taster)
    assert set(tools) == READ_TOOLS | {TOOL}  # read, and the taste tool: not the saving tools
    assert "log_food" not in tools and "save_recipe" not in tools
    tool = tools[TOOL]
    assert tool["annotations"] == {"title": tool["title"], "readOnlyHint": False, "destructiveHint": True,
                                   "idempotentHint": True, "openWorldHint": False}
    schema = tool["inputSchema"]
    assert schema["additionalProperties"] is False and schema["required"] == ["preference", "request_key"]
    assert set(schema["properties"]) == {"food_id", "category", "preference", "request_key"}
    assert schema["properties"]["preference"]["enum"] == ["like", "less", "not_for_me", "clear"]  # never "neutral"
    assert len(tool["description"]) > 200
    # a token with both ticks has all of it
    both = make(admin, "both", can_log=True, can_prefs=True)["token"]
    assert set(listed(app, both)) == READ_TOOLS | {TOOL, "log_food", "save_recipe"}


def test_a_token_with_the_scope_cannot_save_food_and_the_instructions_tell_the_model_what_it_may_do(admin, reader, saver, taster):
    app = admin.app

    def instructions(token: str) -> str:
        return rpc(app, token, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]["instructions"]

    assert TOOL not in instructions(reader) and TOOL not in instructions(saver)
    text = instructions(taster)
    assert "set_food_preference" in text and "never infer a taste" in text and "allergy" in text and "request_key" in text
    assert "log_food" not in text  # the tick for tastes gives no saving
    result = call_raw(app, taster, "log_food", {"items": [{"food": "banana"}], "meal": "lunch"})
    assert result["isError"] is True and result["content"][0]["text"] == mcp_tools.READ_ONLY


def test_the_tool_is_not_in_the_read_and_save_registry_and_ask_cannot_reach_it(admin, taster):
    assert TOOL not in mcp_tools.TOOLS_BY_NAME and PT.TOOL in mcp_server.all_tools() and mcp_server.tool_named(TOOL) is PT.TOOL
    assert PT.TOOL.needs == "assistant:prefs" and PT.TOOL.writes is True
    assert {t.needs for t in mcp_tools.TOOLS if t.writes} == {"assistant:log"} and {t.needs for t in mcp_tools.TOOLS if not t.writes} == {"assistant:read"}
    from app.ai import chat_save

    assert TOOL == chat_save.PREF.TOOL_NAME  # Ask's tool has the same name and its own path (always a card)
    from app.mcp.tools import Asker, Call

    with pytest.raises(mcp_tools.ToolError):
        PT.set_food_preference(Call(None, None, None, Asker()), PT.PreferenceCall(food_id=1, preference="like", request_key=KEY))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# A food
# --------------------------------------------------------------------------- #


def test_each_preference_for_a_food_is_saved_as_from_the_assistant(admin, taster):
    app = admin.app
    banana = food_id(admin, "banana")
    for preference, shown in (("like", "more like this"), ("less", "less often"), ("not_for_me", "not for me")):
        got = taste(app, taster, food_id=banana, preference=preference)
        assert set(got) == {"saved", "target", "preference", "note"} and got["saved"] is True
        assert got["target"] == {"kind": "food", "name": "Banana, raw"} and got["preference"] == preference
        assert shown in got["note"] and "Settings → Meal guidance → Your food preferences" in got["note"]
        assert rows(admin) == {"Banana, raw": (preference, "assistant")}
        [row] = preferences(admin)["foods"]
        assert row["food_id"] == banana and row["category"] == "Fruits"
    cleared = taste(app, taster, food_id=banana, preference="clear")
    assert cleared["preference"] == "clear" and "Cleared" in cleared["note"] and rows(admin) == {}
    assert [(r["details"]["old"], r["details"]["new"]) for r in sets(admin)] == [
        ("none", "like"), ("like", "less"), ("less", "not_for_me"), ("not_for_me", "none")]


def test_the_person_sees_the_row_as_from_the_assistant_and_removes_or_changes_it_as_usual(admin, taster):
    banana = food_id(admin, "banana")
    taste(admin.app, taster, food_id=banana, preference="less")
    [row] = preferences(admin)["foods"]
    assert row["source"] == "assistant" and row["preference"] == "less" and row["updated_at"] >= row["created_at"]
    # the page changes it like any other row; the person's own change is the person's
    person_puts(admin, banana, "like")
    assert rows(admin) == {"Banana, raw": ("like", "person")}
    taste(admin.app, taster, food_id=banana, preference="not_for_me")
    assert rows(admin)["Banana, raw"] == ("not_for_me", "assistant")
    assert admin.delete(f"/api/guidance/preferences/{banana}").status_code == 204  # "Suggest again" / "Remove"
    assert rows(admin) == {}
    # the export carries the word, and the import accepts it (tests/data/import_vectors.json has a row from the assistant)
    taste(admin.app, taster, food_id=banana, preference="like")
    with zipfile.ZipFile(io.BytesIO(admin.get("/api/me/export.zip").content)) as z:
        exported = json.loads(z.read("export.json"))["food_preferences"]
    assert [(r["name"], r["preference"], r["source"]) for r in exported] == [("Banana, raw", "like", "assistant")]


def test_asks_undo_puts_back_a_row_the_assistant_set_with_the_source_it_had(admin, taster):
    """Ask's Remember replaces the row (source ask); its Undo writes the previous state back through the same PUT, with the previous
    source, and that source can be "assistant". A bad word is still refused."""
    banana = food_id(admin, "banana")
    taste(admin.app, taster, food_id=banana, preference="less")
    put = lambda body: admin.put(f"/api/guidance/preferences/{banana}", json=body)  # noqa: E731
    assert put({"preference": "like", "source": "ask"}).status_code == 200  # Remember
    assert rows(admin) == {"Banana, raw": ("like", "ask")}
    back = put({"preference": "less", "source": "assistant"})  # Undo
    assert back.status_code == 200 and back.json()["source"] == "assistant"
    assert rows(admin) == {"Banana, raw": ("less", "assistant")}
    assert put({"preference": "less", "source": "robot"}).status_code == 400


def test_a_change_to_the_same_value_changes_nothing_and_leaves_the_persons_own_row_alone(admin, taster):
    banana = food_id(admin, "banana")
    person_puts(admin, banana, "like")
    before = preferences(admin)["foods"]
    got = taste(admin.app, taster, food_id=banana, preference="like")
    assert got["saved"] is True and got["preference"] == "like"  # the same answer: it says what is set, not what was there
    assert preferences(admin)["foods"] == before and rows(admin) == {"Banana, raw": ("like", "person")}  # still the person's
    assert sets(admin) == []  # nothing changed, nothing to audit
    assert key_rows(admin) == 1  # but the key is remembered, so a repeat is a no-op too
    nothing = taste(admin.app, taster, food_id=food_id(admin, "apple"), preference="clear")
    assert nothing["preference"] == "clear" and sets(admin) == [] and rows(admin) == {"Banana, raw": ("like", "person")}


def test_clear_leaves_a_learning_switch_alone(admin, taster):
    """A ``neutral`` row is "stop learning about this food", not a taste: ``clear`` does not delete it, as in Ask."""
    banana = food_id(admin, "banana")
    person_puts(admin, banana, "neutral")
    taste(admin.app, taster, food_id=banana, preference="clear")
    assert rows(admin) == {"Banana, raw": ("neutral", "person")} and sets(admin) == []
    taste(admin.app, taster, food_id=banana, preference="like")  # an actual taste replaces it
    assert rows(admin) == {"Banana, raw": ("like", "assistant")}
    assert sets(admin)[0]["details"]["old"] == "neutral"


# --------------------------------------------------------------------------- #
# A food group
# --------------------------------------------------------------------------- #


def test_each_preference_for_a_food_group_moves_only_that_group(admin, taster):
    app = admin.app
    assert admin.patch("/api/me/settings", json={"guidance": {"carb_tolerance_g": 12, "like_categories": ["Vegetables"],
                                                              "less_categories": ["Dairy & Alternatives"]}}).status_code == 200
    got = taste(app, taster, category="Fruits", preference="like")
    assert got["target"] == {"kind": "group", "name": "Fruits"} and "Settings → Meal guidance → Your food preferences → Kinds of food" in got["note"]
    assert groups(admin) == {"like": ["Vegetables", "Fruits"], "less": ["Dairy & Alternatives"], "never": []}
    taste(app, taster, category="Fruits", preference="less")  # moves between lists, never in two
    assert groups(admin) == {"like": ["Vegetables"], "less": ["Dairy & Alternatives", "Fruits"], "never": []}
    never = taste(app, taster, category="Fruits", preference="not_for_me")
    assert "never suggest" in never["note"]
    assert groups(admin) == {"like": ["Vegetables"], "less": ["Dairy & Alternatives"], "never": ["Fruits"]}
    taste(app, taster, category="Fruits", preference="clear")
    assert groups(admin) == {"like": ["Vegetables"], "less": ["Dairy & Alternatives"], "never": []}
    settings = admin.get("/api/me/settings").json()["settings"]["guidance"]["value"]
    assert settings["carb_tolerance_g"] == 12  # nothing else in the setting changed
    assert [(r["details"]["old"], r["details"]["new"]) for r in sets(admin)] == [
        ("none", "like"), ("like", "less"), ("less", "not_for_me"), ("not_for_me", "none")]
    assert all(r["details"]["kind"] == "group" and r["details"]["name"] == "Fruits" and "food_id" not in r["details"] for r in sets(admin))
    assert preferences(admin)["foods"] == []  # a group has no row of its own


def test_a_group_is_found_by_its_name_in_any_case_and_an_unknown_one_lists_some(admin, taster):
    assert taste(admin.app, taster, category="  fruits ", preference="like")["target"]["name"] == "Fruits"
    assert groups(admin)["like"] == ["Fruits"]
    text = refused(admin.app, taster, category="Fruit salad", preference="like")
    assert text.startswith("category must be one of the person's food groups: ") and "Fruits" in text
    assert groups(admin)["like"] == ["Fruits"]


def test_a_full_group_list_is_told_to_the_person(admin, taster):
    names = [f"Group {n}" for n in range(50)]
    r = admin.patch("/api/me/settings", json={"guidance": {"like_categories": names}})
    assert r.status_code == 200, r.text
    text = refused(admin.app, taster, category="Fruits", preference="like")
    assert "full (50)" in text and "Tell them to remove one in Settings" in text
    assert sets(admin) == [] and key_rows(admin) == 0


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def test_exactly_one_of_food_id_and_category(admin, taster):
    app, banana = admin.app, food_id(admin, "banana")
    assert "exactly one of food_id and category" in refused(app, taster, preference="like")
    assert "exactly one of food_id and category" in refused(app, taster, food_id=banana, category="Fruits", preference="like")
    untouched(admin)


@pytest.mark.parametrize("arguments, mention", [
    ({"food_id": 1, "preference": "love"}, "preference"),
    ({"food_id": 1, "preference": "neutral"}, "preference"),  # "stop learning" is the person's switch
    ({"food_id": 1}, "preference"),
    ({"food_id": 0, "preference": "like"}, "food_id"),
    ({"food_id": "1", "preference": "like"}, "food_id"),
    ({"food_id": True, "preference": "like"}, "food_id"),
    ({"food_id": 2 ** 63, "preference": "like"}, "food_id"),
    ({"category": "", "preference": "like"}, "category"),
    ({"category": "x" * 101, "preference": "like"}, "category"),
    ({"category": "Fruits", "preference": "like", "source": "person"}, "Extra inputs"),  # the source is not the model's to name
    ({"category": "Fruits", "preference": "like", "colour": "red"}, "Extra inputs"),
    ({"category": "Fruits", "preference": "like", "request_key": "short"}, "request_key"),
    ({"category": "Fruits", "preference": "like", "request_key": "has spaces in it!"}, "request_key"),
    ({"category": "Fruits", "preference": "like", "request_key": "k" * 65}, "request_key"),
])
def test_wrong_arguments_are_a_short_error_and_write_nothing(admin, taster, arguments, mention):
    arguments = {"request_key": KEY, **arguments}
    text = refused(admin.app, taster, **arguments)
    assert text.startswith("Invalid arguments: ") and mention in text
    untouched(admin)


def test_the_request_key_is_required(admin, taster):
    result = call_raw(admin.app, taster, TOOL, {"category": "Fruits", "preference": "like"})
    assert result["isError"] is True and "request_key" in result["content"][0]["text"]
    untouched(admin)


def test_a_food_the_person_may_not_use_is_refused_like_ask(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    token = make(admin, "Hermes", can_prefs=True)["token"]
    theirs = sam.post("/api/foods", json={"name": "Sam secret stew", "serving_desc": "1 bowl (300 g)", "serving_g": 300,
                                          "nutrients": {"carbs_g": 30}}).json()
    for fid in (theirs["id"], 999_999):
        text = refused(admin.app, token, food_id=fid, preference="not_for_me")
        assert text == (f"food_id {fid} is not one of the person's foods. Use search_foods and give the id of a result with "
                        "in_app true, or use a category.")
        assert "Sam" not in text and "secret" not in text
    untouched(admin)
    assert preferences(sam)["foods"] == [] and sets(sam) == []
    # Ask refuses it with the very same words: the tool calls Ask's own check (tests/test_ai_chat_preference.py pins the text)
    from app.ai import chat_preference as PREF

    assert PT.PREF is PREF


def test_another_persons_token_changes_only_its_own_person(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    mine, theirs = make(admin, "mine", can_prefs=True)["token"], make(sam, "theirs", can_prefs=True)["token"]
    banana = food_id(admin, "banana")
    taste(sam.app, theirs, food_id=food_id(sam, "banana"), preference="not_for_me", request_key=KEY)
    assert rows(sam) == {"Banana, raw": ("not_for_me", "assistant")} and rows(admin) == {}  # the builtin food is shared, the row is not
    taste(admin.app, mine, food_id=banana, preference="like", request_key=KEY)  # the same key text, another person
    assert rows(admin) == {"Banana, raw": ("like", "assistant")} and rows(sam) == {"Banana, raw": ("not_for_me", "assistant")}
    assert sorted(r["actor_user_id"] for r in sets(admin)) == [1, 2]  # one row each, in each person's own activity
    assert [e["action"] for e in sam.get("/api/me/activity").json()["events"] if e["action"].startswith("assistant.")] == ["assistant.preference_set"]
    assert groups(sam) == {"like": [], "less": [], "never": []}


def test_a_full_preference_list_is_told_to_the_person(admin, taster, monkeypatch):
    from app.guidance import context as guidance_context

    monkeypatch.setattr(guidance_context, "MAX_FOOD_PREFERENCES", 1)
    person_puts(admin, food_id(admin, "banana"), "like")
    text = refused(admin.app, taster, food_id=food_id(admin, "apple"), preference="like")
    assert "full (1 foods)" in text and "Tell them to remove one in Settings" in text
    assert rows(admin) == {"Banana, raw": ("like", "person")} and sets(admin) == []
    taste(admin.app, taster, food_id=food_id(admin, "banana"), preference="less")  # changing a row needs no room


def test_a_failure_inside_the_save_writes_nothing_and_says_nothing_of_the_cause(admin, taster, monkeypatch):
    from app.guidance import api as guidance_api

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(guidance_api, "apply_preference", broken)
    text = refused(admin.app, taster, food_id=food_id(admin, "banana"), preference="like")
    assert "nothing was saved" in text and "disk" not in text
    untouched(admin)


# --------------------------------------------------------------------------- #
# request_key
# --------------------------------------------------------------------------- #


def test_a_repeat_with_the_same_key_is_a_no_op_that_answers_the_first_time(admin, taster):
    app, banana = admin.app, food_id(admin, "banana")
    first = taste(app, taster, food_id=banana, preference="less", request_key=KEY)
    assert first["saved"] is True and "duplicate" not in first
    person_puts(admin, banana, "like")  # the person changes their mind in the app
    again = taste(app, taster, food_id=banana, preference="less", request_key=KEY)
    assert again["duplicate"] is True and again["saved"] is True and again["target"] == first["target"]
    assert again["preference"] == "less" and "already did this" in again["note"] and "nothing was changed again" in again["note"]
    assert rows(admin) == {"Banana, raw": ("like", "person")}  # the repeat did not undo the person
    assert len(sets(admin)) == 1 and key_rows(admin) == 1
    # a repeat is answered whatever its other arguments are: the key is the identity of the change
    other = taste(app, taster, category="Fruits", preference="not_for_me", request_key=KEY)
    assert other["duplicate"] is True and other["target"] == first["target"] and groups(admin)["never"] == []
    # a new key is a new change
    new = taste(app, taster, food_id=banana, preference="less", request_key="taste-key-new1")
    assert "duplicate" not in new and rows(admin) == {"Banana, raw": ("less", "assistant")} and len(sets(admin)) == 2


def test_a_key_is_independent_for_another_token_and_the_other_tool_refuses_it(admin, taster):
    app, banana = admin.app, food_id(admin, "banana")
    second = make(admin, "second", can_prefs=True)["token"]
    taste(app, taster, food_id=banana, preference="less", request_key=KEY)
    assert "duplicate" not in taste(app, second, food_id=banana, preference="not_for_me", request_key=KEY)  # its own key
    assert rows(admin) == {"Banana, raw": ("not_for_me", "assistant")} and key_rows(admin) == 2
    both = make(admin, "both", can_log=True, can_prefs=True)["token"]
    logged = call_raw(app, both, "log_food", {"items": [{"food": "banana"}], "meal": "lunch", "request_key": "shared-key-01"})
    assert logged["isError"] is False
    text = refused(app, both, food_id=banana, preference="like", request_key="shared-key-01")
    assert "already used by log_food" in text and rows(admin) == {"Banana, raw": ("not_for_me", "assistant")}


def test_the_key_is_kept_as_a_hash_for_24_hours_only(admin, taster, fake_clock):
    taste(admin.app, taster, category="Fruits", preference="like", request_key=KEY)
    conn = db(admin)
    try:
        dump = json.dumps([tuple(r) for r in conn.execute("SELECT * FROM assistant_request_keys")])
        dump += json.dumps([tuple(r) for r in conn.execute("SELECT * FROM audit_log")])
    finally:
        conn.close()
    assert KEY not in dump
    assert taste(admin.app, taster, category="Fruits", preference="less", request_key=KEY)["duplicate"] is True
    fake_clock.advance(hours=24, seconds=5)
    again = taste(admin.app, taster, category="Fruits", preference="less", request_key=KEY)  # the key expired: a new change
    assert "duplicate" not in again and groups(admin) == {"like": [], "less": ["Fruits"], "never": []}
    assert key_rows(admin) == 1  # the old key was deleted by the new one


# --------------------------------------------------------------------------- #
# The audit row and the activity list
# --------------------------------------------------------------------------- #


def test_every_change_is_audited_with_old_new_and_the_token_name_never_the_token(admin):
    made = make(admin, "Kitchen tablet", can_prefs=True)
    token = made["token"]
    banana = food_id(admin, "banana")
    taste(admin.app, token, food_id=banana, preference="not_for_me")
    taste(admin.app, token, category="Dairy & Alternatives", preference="less")
    food, group = sets(admin)
    assert (food["actor_user_id"], food["target_type"], food["target_id"]) == (1, "api_token", str(made["id"]))
    assert food["details"] == {"via": "Kitchen tablet", "kind": "food", "name": "Banana, raw", "old": "none", "new": "not_for_me",
                               "food_id": banana}
    assert group["details"] == {"via": "Kitchen tablet", "kind": "group", "name": "Dairy & Alternatives", "old": "none", "new": "less"}
    conn = db(admin)
    try:
        dump = json.dumps([tuple(r) for r in conn.execute("SELECT * FROM audit_log")])
    finally:
        conn.close()
    assert token not in dump and made["prefix"] not in dump
    events = [e for e in admin.get("/api/me/activity").json()["events"] if e["action"] == "assistant.preference_set"]
    assert len(events) == 2 and {e["details"]["via"] for e in events} == {"Kitchen tablet"}  # the person sees them
    from app import audit

    assert "assistant.preference_set" in audit.ACTIONS and "assistant.preference_set" in audit.USER_VISIBLE_ACTIONS


def test_refused_and_repeated_calls_leave_no_activity(admin, taster, reader):
    refused(admin.app, taster, category="Nope", preference="like")
    refused(admin.app, taster, preference="like")
    unknown = rpc(admin.app, reader, "tools/call", {"name": TOOL, "arguments": {"category": "Fruits", "preference": "like", "request_key": KEY}})
    assert unknown.json()["error"]["code"] == -32602  # not allowed for this token: unknown tool
    taste(admin.app, taster, category="Fruits", preference="like", request_key=KEY)
    taste(admin.app, taster, category="Fruits", preference="like", request_key=KEY)
    assert len(sets(admin)) == 1


# --------------------------------------------------------------------------- #
# The limits
# --------------------------------------------------------------------------- #


def toggle(app: Any, token: str, banana: int, n: int) -> dict[str, Any]:
    return taste(app, token, food_id=banana, preference=("like", "less")[n % 2], request_key=f"toggle-key-{n:04d}")


def test_thirty_changes_a_day_per_token_then_the_limits_own_429(admin, taster, fake_clock):
    app, banana = admin.app, food_id(admin, "banana")
    from app.auth.ratelimit import LIMITS

    assert PT.DAILY_MAX == 30 and (LIMITS[PT.DAILY_LIMIT].max_requests, LIMITS[PT.DAILY_LIMIT].window_s) == (30, 24 * 3600)
    for n in range(30):
        toggle(app, taster, banana, n)
        fake_clock.advance(seconds=3)  # under 60 requests a minute
    assert len(sets(admin)) == 30
    r = rpc(app, taster, "tools/call", {"name": TOOL, "arguments": {"food_id": banana, "preference": "not_for_me", "request_key": "toggle-key-9999"}})
    assert r.status_code == 429 and 1 <= int(r.headers["retry-after"]) <= 24 * 3600
    assert r.json() == {"detail": "Too many changes from this assistant today. Try again later.", "retry_after": int(r.headers["retry-after"])}
    assert len(sets(admin)) == 30 and rows(admin)["Banana, raw"][1] == "assistant" and rows(admin)["Banana, raw"][0] == "less"
    # a retry of a change that was made is not a new change; a refused call is not one either
    assert toggle(app, taster, banana, 3)["duplicate"] is True
    assert refused(app, taster, category="Nope", preference="like").startswith("category must be")
    # the cap belongs to the token: another token of the same person, and the read tools, are not stopped
    other = make(admin, "other", can_prefs=True)["token"]
    assert taste(app, other, category="Fruits", preference="like")["saved"] is True
    assert rpc(app, taster, "tools/call", {"name": "safety_check", "arguments": {"message": "hello"}}).status_code == 200
    # a day later it works again
    fake_clock.advance(hours=24)
    assert taste(app, taster, food_id=banana, preference="not_for_me")["saved"] is True


def test_bulk_shaping_across_many_foods_is_stopped_by_the_same_cap(real):
    c = real
    token = make(c, "bulk", can_prefs=True)["token"]
    ids: list[int] = []
    for query in ("chicken", "beef", "rice", "bread", "cheese", "milk", "apple", "bean", "fish", "soup"):
        ids += [f["id"] for f in c.get("/api/foods", params={"q": query, "limit": 50}).json()["foods"] if f["id"] not in ids]
    ids = ids[:35]
    assert len(ids) == 35
    done = 0
    for fid in ids:
        r = rpc(c.app, token, "tools/call", {"name": TOOL, "arguments": {"food_id": fid, "preference": "not_for_me", "request_key": fresh_key()}})
        if r.status_code == 429:
            break
        assert r.status_code == 200 and r.json()["result"]["isError"] is False, r.text
        done += 1
    assert done == 30 and len(preferences(c)["foods"]) == 30


def test_the_per_token_request_limit_still_applies_to_the_tool(admin, taster):
    for _ in range(60):
        assert rpc(admin.app, taster, "ping").status_code == 200
    r = rpc(admin.app, taster, "tools/call", {"name": TOOL, "arguments": {"category": "Fruits", "preference": "like", "request_key": KEY}})
    assert r.status_code == 429 and r.json()["detail"] == "Too many assistant requests with this token. Try again in a minute."
    assert sets(admin) == []


# --------------------------------------------------------------------------- #
# The answer is short and reads nothing else
# --------------------------------------------------------------------------- #


def test_the_answer_names_only_what_was_set_and_how_to_undo_it(admin, taster):
    app = admin.app
    person_puts(admin, food_id(admin, "apple"), "not_for_me")
    person_puts(admin, food_id(admin, "chicken"), "like")
    assert admin.patch("/api/me/settings", json={"guidance": {"less_categories": ["Dairy & Alternatives"]}}).status_code == 200
    got = taste(app, taster, food_id=food_id(admin, "banana"), preference="like")
    text = json.dumps(got)
    for other in ("Apple", "Chicken", "Dairy", "not_for_me"):
        assert other not in text, other
    assert len(text) < 500 and got["note"].endswith("Tell the person what you set.")
    assert "change or undo it in the app" in got["note"]
    group = taste(app, taster, category="Vegetables", preference="like")
    assert "Apple" not in json.dumps(group) and "Dairy" not in json.dumps(group) and len(json.dumps(group)) < 500
    # the refusals do not list the person's foods either (only food groups, as Ask's message does)
    text = refused(app, taster, food_id=999_999, preference="like")
    assert "Apple" not in text and "Chicken" not in text


def test_the_tool_text_and_the_instructions_speak_of_no_doses_and_never_against_a_low():
    import re

    dosing = re.compile(r"\b(insulin|bolus|basal|doses?|dosing|correction|ratios?|binders?|medicines?|medications?)\b", re.I)
    texts = [PT.TOOL.description, json.dumps(PT.TOOL.input_schema), mcp_server.PREFS_INSTRUCTIONS, PT.PHRASE["like"],
             *PT.PHRASE.values(), *PT.GROUP_PHRASE.values()]
    for text in texts:
        assert not dosing.search(text), text
    for text in (PT.TOOL.description, mcp_server.PREFS_INSTRUCTIONS):
        assert not re.search(r"\b(wait|hold off|too much sugar|avoid|should not)\b", text, re.I), text
        assert "treating a low" in text  # it says outright that a taste has no part in it
        assert "log_food" not in text


# --------------------------------------------------------------------------- #
# Treating a low is never touched
# --------------------------------------------------------------------------- #


def low_state(client: TestClient, token: str) -> dict[str, Any]:
    """Everything a person reads about treating a low: the options and the card, the day's insight that names a better low
    treatment, and the assistant's own safety_check answer for a message about a low."""
    options = client.get("/api/guidance/hypo-options")
    assert options.status_code == 200, options.text
    day = client.get("/api/guidance/insights/day", params={"date": DAY})
    assert day.status_code == 200, day.text
    check = call_raw(client.app, token, "safety_check", {"message": "I feel shaky and low"})
    assert check["isError"] is False
    return {"options": options.json(), "day": day.json(), "safety_check": check["structuredContent"]}


@pytest.mark.safety
def test_tastes_never_change_what_treating_a_low_shows(real):
    c = real
    token = make(c, "Hermes", can_prefs=True)["token"]
    app = c.app
    # a low treated that day, so the day's insights speak of low treatments
    set_targets(c)
    juice = c.get("/api/foods", params={"q": "Apple juice"}).json()["foods"][0]
    assert c.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": juice["id"], "servings": 2,
                                    "status": "eaten", "purpose": "hypo"}).status_code == 201
    base = low_state(c, token)
    assert "day.hypo.logged" in {i["id"] for i in base["day"]["insights"]}
    hypo_ids = [o["food_id"] for o in base["options"]["options"]]
    assert len(hypo_ids) >= 5 and juice["id"] in hypo_ids
    assert base["options"]["card"] and base["safety_check"]["action"] == "treat_low_first"
    # liking, wanting less of and forgetting a food that treats a low are allowed (soft: never read there) and change nothing
    for preference in ("like", "less", "clear"):
        got = taste(app, token, food_id=juice["id"], preference=preference)
        assert got["saved"] is True
        assert low_state(c, token) == base, preference
    assert taste(app, token, food_id=hypo_ids[1], preference="less")["saved"] is True
    # food groups: soft choices on the groups that hold low treatments change nothing either
    for category in ("Beverages", "Sweets & Snacks", "Diabetes supplies"):
        for preference in ("like", "less", "clear"):
            assert taste(app, token, category=category, preference=preference)["saved"] is True
            assert low_state(c, token) == base, (category, preference)
    # "Not for me" / "Never suggest" would take the food or group out of the options (the person's own choice does, note 09 §8 Q1):
    # the assistant cannot make it, for a low treatment or a group that holds one, and nothing is written
    written = (preferences(c), len(sets(c)), key_rows(c))
    for fid in hypo_ids:
        text = refused(app, token, food_id=fid, preference="not_for_me")
        assert "can treat a low" in text and "only the person can mark it Not for me" in text and text.endswith("Nothing was changed.")
    for category in ("Beverages", "Sweets & Snacks", "Diabetes supplies"):
        text = refused(app, token, category=category, preference="not_for_me")
        assert "foods that can treat a low" in text and "only the person can set it to Never suggest" in text
    assert (preferences(c), len(sets(c)), key_rows(c)) == written
    assert low_state(c, token) == base  # the options, the card, the insight and the assistant's own answer: unchanged
    assert all(o["food_id"] in {x["food_id"] for x in c.get("/api/guidance/hypo-options").json()["options"]} for o in base["options"]["options"])


@pytest.mark.safety
def test_a_food_group_without_a_low_treatment_can_still_be_set_to_never_suggest(real):
    """The refusal is exact: it covers a food that treats a low and a group that holds one, nothing wider."""
    c = real
    token = make(c, "Hermes", can_prefs=True)["token"]
    base = c.get("/api/guidance/hypo-options").json()
    salmon = c.get("/api/foods", params={"q": "Salmon"}).json()["foods"][0]
    assert taste(c.app, token, food_id=salmon["id"], preference="not_for_me")["saved"] is True
    assert taste(c.app, token, category="Fish & Seafood", preference="not_for_me")["saved"] is True
    assert groups(c)["never"] == ["Fish & Seafood"] and rows(c)[salmon["name"]] == ("not_for_me", "assistant")
    assert c.get("/api/guidance/hypo-options").json() == base  # none of them is a low treatment


@pytest.mark.safety
def test_the_persons_own_not_for_me_still_works_as_before_and_keeps_the_floor(real):
    """The person's own choice is not changed by this feature: the same route, the same effect on the options, the floor."""
    c = real
    base = c.get("/api/guidance/hypo-options").json()
    ids = [o["food_id"] for o in base["options"]]
    person_puts(c, ids[0], "not_for_me")
    one = c.get("/api/guidance/hypo-options").json()
    assert [o["food_id"] for o in one["options"]] == ids[1:]
    for fid in ids[1:]:
        person_puts(c, fid, "not_for_me")
    floor = c.get("/api/guidance/hypo-options").json()
    assert [o["food_id"] for o in floor["options"]] == ids and floor["notes"][-1] == "Shown although you marked them Not for me."
    assert floor["card"] == base["card"]


@pytest.mark.safety
def test_the_tool_and_its_wiring_touch_none_of_the_low_treatment_code():
    """The module reads no hypo code: its only mention of a low treatment is the food flag it refuses to hide."""
    import ast

    tree = ast.parse((ROOT / "app" / "mcp" / "preference_tool.py").read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            used.update([node.module or "", *(a.name for a in node.names)])
        elif isinstance(node, ast.Import):
            used.update(a.name for a in node.names)
    for name in ("hypo_options", "best_hypo_food", "prefilter", "treating_a_low_card", "swaps", "insights", "hypo", "messages"):
        assert name not in used, name
    assert "HYPO_FLAG" in used  # the food flag it reads, to refuse hiding a low treatment, and nothing else of the kind
