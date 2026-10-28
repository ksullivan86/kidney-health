"""The assistant's MCP server, ``POST /mcp`` (``app/mcp``; docs/dev/plans/assistant-step1.md part B; ARCHITECTURE.md
"Assistant MCP server").

Covered: the protocol (initialize and version negotiation, notifications, ping, tools/list, tools/call, the JSON-RPC
errors, 405, Origin, the body limit, no session id), auth (no, invalid or revoked token, the switch, no cookie
session, the exact-path CSRF exemption, another person's token), the tools (get_today equals Today's numbers,
unknown stays unknown, a kidney-only profile has no meal carbohydrate goals, search with and without USDA,
check_meal amounts, household measures, unresolved items and the projection, safety_check wording) and the
per-token rate limit. No network: USDA answers come from an in-process mock.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

import httpx2
import pytest

from app import foods as foods_module
from app import security
from app.auth import api_tokens
from app.mcp import server as mcp_server
from app.mcp import tools as mcp_tools
from app.nutrients import NUTRIENT_KEYS, round_value
from conftest import DAY, TestClient, log_food, make_settings, signed_in_client
from test_api_tokens import make, switch

REMINDER = "Numbers come from the app; fetch them again after any change."
TOOL_NAMES = {"get_today", "search_foods", "check_meal", "safety_check"}
TARGETS = {"potassium_mg": 2000, "phosphorus_mg": 800, "sodium_mg": 2000, "fluid_ml": 1500,
           "protein_g": {"min": 50, "max": 50}, "carbs_g": 200, "carbs_per_meal_g": 45}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def bare(app: Any) -> TestClient:
    """A client with no cookie and no X-Requested-With: what a chat client sends."""
    return TestClient(app, headers={})


def post(app: Any, token: str | None, body: Any = None, *, raw: bytes | None = None, path: str = "/mcp",
         **headers: str) -> Any:
    sent = {"Authorization": f"Bearer {token}"} if token else {}
    sent.update({k.replace("_", "-"): v for k, v in headers.items()})
    if raw is not None:
        return bare(app).post(path, content=raw, headers={**sent, "content-type": "application/json"})
    return bare(app).post(path, json=body, headers=sent)


def rpc(app: Any, token: str | None, method: str, params: Any = None, request_id: Any = 1, **headers: str) -> Any:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return post(app, token, body, **headers)


def call_raw(app: Any, token: str, tool: str, arguments: Any) -> dict[str, Any]:
    r = rpc(app, token, "tools/call", {"name": tool, "arguments": arguments})
    assert r.status_code == 200, r.text
    assert r.json()["jsonrpc"] == "2.0" and r.json()["id"] == 1
    return r.json()["result"]


def call(app: Any, token: str, tool: str, **arguments: Any) -> dict[str, Any]:
    result = call_raw(app, token, tool, arguments)
    assert result["isError"] is False, result
    data = result["structuredContent"]
    assert [c["type"] for c in result["content"]] == ["text"]
    assert json.loads(result["content"][0]["text"]) == data
    assert data["source"] == "kidney-health" and data["reminder"] == REMINDER
    return data


def tool_error(app: Any, token: str, tool: str, arguments: Any) -> str:
    result = call_raw(app, token, tool, arguments)
    assert result["isError"] is True and "structuredContent" not in result, result
    return result["content"][0]["text"]


def token_for(client: TestClient, name: str = "Open WebUI") -> str:
    return make(client, name)["token"]


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    switch(client, True)
    return client


@pytest.fixture
def token(admin: TestClient) -> str:
    return token_for(admin)


def food_id(client: TestClient, query: str) -> int:
    hits = client.get("/api/foods", params={"q": query}).json()["foods"]
    assert hits, query
    return int(hits[0]["id"])


def plan(client: TestClient, query: str, servings: float, meal: str = "lunch", date: str = DAY) -> None:
    body = {"date": date, "meal": meal, "food_id": food_id(client, query), "servings": servings, "status": "planned"}
    assert client.post("/api/log", json=body).status_code == 201


def set_targets(client: TestClient, **profile: Any) -> None:
    r = client.put("/api/profile", json={"targets": TARGETS, **profile})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("asked, answered", [("2025-06-18", "2025-06-18"), ("2025-03-26", "2025-03-26"),
                                             ("2024-11-05", "2025-06-18"), (None, "2025-06-18")])
def test_initialize_negotiates_the_protocol_version(admin, token, asked, answered):
    params = {"capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}}
    if asked:
        params["protocolVersion"] = asked
    r = rpc(admin.app, token, "initialize", params, request_id="init-1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert "mcp-session-id" not in r.headers  # stateless
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["id"] == "init-1" and "error" not in body
    result = body["result"]
    assert result["protocolVersion"] == answered
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "kidney-health" and result["serverInfo"]["version"] == admin.app.version
    assert "safety_check" in result["instructions"] and "never from memory" in result["instructions"]
    assert "doses" in result["instructions"]


def test_notifications_and_client_responses_get_202_without_a_body(admin, token):
    for body in ({"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 3}},
                 {"jsonrpc": "2.0", "method": "notifications/whatever"},
                 {"jsonrpc": "2.0", "id": 7, "result": {}}):
        r = post(admin.app, token, body, mcp_protocol_version="2025-06-18")
        assert r.status_code == 202 and r.content == b"", body


def test_ping_and_a_call_without_initialize(admin, token):
    """Stateless: every request stands alone, so a call needs no initialize first."""
    r = rpc(admin.app, token, "ping", request_id=99)
    assert r.json() == {"jsonrpc": "2.0", "id": 99, "result": {}}
    assert call(admin.app, token, "safety_check", message="hello")["action"] == "none"


def test_tools_list_shape(admin, token):
    r = rpc(admin.app, token, "tools/list", {})
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == TOOL_NAMES and tools[0]["name"] == "safety_check"
    for tool in tools:
        assert tool["title"] and len(tool["description"]) > 40
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert tool["annotations"]["readOnlyHint"] is True and tool["annotations"]["openWorldHint"] is False
        assert "outputSchema" not in tool
    by_name = {t["name"]: t for t in tools}
    items = by_name["check_meal"]["inputSchema"]["properties"]["items"]
    assert items["minItems"] == 1 and items["maxItems"] == 20 and items["items"]["required"] == ["food"]
    assert by_name["search_foods"]["inputSchema"]["properties"]["limit"]["maximum"] == 10
    assert by_name["safety_check"]["inputSchema"]["properties"]["message"]["maxLength"] == 2000
    assert rpc(admin.app, token, "tools/list").json()["result"]["tools"] == tools  # params are optional


def test_json_rpc_errors(admin, token):
    app = admin.app

    def error(r: Any, code: int, status: int, request_id: Any = None) -> None:
        assert r.status_code == status, r.text
        body = r.json()
        assert body["jsonrpc"] == "2.0" and body["id"] == request_id and body["error"]["code"] == code, body

    error(post(app, token, raw=b"{not json"), -32700, 400)
    error(post(app, token, raw=b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"x": NaN}}'), -32700, 400)
    error(post(app, token, raw=b"\xff\xfe"), -32700, 400)
    error(post(app, token, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]), -32600, 400)  # a batch
    error(post(app, token, "ping"), -32600, 400)
    error(post(app, token, {"id": 1, "method": "ping"}), -32600, 400, 1)  # no "jsonrpc": "2.0"
    error(post(app, token, {"jsonrpc": "1.0", "id": 1, "method": "ping"}), -32600, 400, 1)
    error(post(app, token, {"jsonrpc": "2.0", "id": None, "method": "ping"}), -32600, 400)
    error(post(app, token, {"jsonrpc": "2.0", "id": True, "method": "ping"}), -32600, 400)
    error(post(app, token, {"jsonrpc": "2.0", "id": 1, "method": 5}), -32600, 400, 1)
    error(post(app, token, {"jsonrpc": "2.0", "id": 1}), -32600, 400, 1)
    error(rpc(app, token, "resources/list", {}, request_id="r"), -32601, 200, "r")
    error(rpc(app, token, "tools/call", {"name": "delete_everything", "arguments": {}}, request_id=4), -32602, 200, 4)
    error(rpc(app, token, "tools/call", {"arguments": {}}, request_id=5), -32602, 200, 5)
    error(rpc(app, token, "tools/call", ["get_today"], request_id=6), -32602, 200, 6)


def test_bad_arguments_and_failures_are_tool_results_with_is_error(admin, token, monkeypatch, caplog):
    app = admin.app
    assert "date" in tool_error(app, token, "get_today", {"date": "2026-02-30"})
    assert "limit" in tool_error(app, token, "search_foods", {"query": "rice", "limit": 11})
    assert "query" in tool_error(app, token, "search_foods", {"query": "   "})
    assert "items" in tool_error(app, token, "check_meal", {"items": []})
    assert "items.0.amount" in tool_error(app, token, "check_meal", {"items": [{"food": "banana", "amount": -1}]})
    assert "Extra inputs" in tool_error(app, token, "get_today", {"when": "today"})
    assert "message" in tool_error(app, token, "safety_check", {"message": "x" * 2001})
    assert "message" in tool_error(app, token, "safety_check", {})
    assert "arguments must be an object" in tool_error(app, token, "get_today", ["2026-10-05"])
    secret = "potassium 9999 for private person"

    def broken(call: Any, args: Any) -> dict[str, Any]:
        raise RuntimeError(secret)

    monkeypatch.setattr(mcp_tools, "TOOLS_BY_NAME", {**mcp_tools.TOOLS_BY_NAME, "get_today": mcp_tools.Tool(
        "get_today", "t", "d" * 50, {"type": "object"}, mcp_tools.TodayArgs, broken)})
    text = tool_error(app, token, "get_today", {})
    assert "could not answer" in text and secret not in text
    assert "assistant tool get_today failed" in caplog.text


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT", "PATCH"])
def test_other_methods_are_405_and_404_while_switched_off(admin, token, method):
    r = bare(admin.app).request(method, "/mcp", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 405 and r.headers["allow"] == "POST"
    switch(admin, False)
    assert bare(admin.app).request(method, "/mcp").status_code == 404


def test_a_foreign_origin_is_403_on_every_method(admin, token):
    app = admin.app
    for origin in ("https://evil.example", "null", "http://localhost:9999"):
        r = rpc(app, token, "ping", origin=origin)
        assert r.status_code == 403 and r.json() == {"detail": "Cross-site request refused"}, origin
        assert bare(app).get("/mcp", headers={"Origin": origin}).status_code == 403
    assert rpc(app, token, "ping", origin="http://localhost").status_code == 200  # this server's own origin


def test_the_body_limit_applies(admin, token):
    r = post(admin.app, token, raw=b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "x": "' + b"a" * 1_100_000 + b'"}')
    assert r.status_code == 413


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


def test_no_invalid_or_revoked_token_is_401_with_a_bearer_challenge(admin, token):
    app = admin.app
    r = rpc(app, None, "ping")
    assert r.status_code == 401 and r.json() == {"detail": api_tokens.DENIED}
    assert r.headers["www-authenticate"] == 'Bearer realm="kidney-health"'
    for bad in ("kha_" + "A" * 43, "not-a-token", token[:-1]):
        r = rpc(app, bad, "ping")
        assert r.status_code == 401 and r.json() == {"detail": api_tokens.DENIED}
        assert r.headers["www-authenticate"] == 'Bearer realm="kidney-health", error="invalid_token"'
    second = make(admin, "second")
    assert rpc(app, second["token"], "ping").status_code == 200
    assert admin.delete(f"/api/me/tokens/{second['id']}").status_code == 204
    assert rpc(app, second["token"], "ping").status_code == 401
    assert rpc(app, token, "ping").status_code == 200  # the other token is untouched


def test_the_switch_off_makes_mcp_404_and_on_again_restores_it(admin, token):
    switch(admin, False)
    for r in (rpc(admin.app, token, "ping"), rpc(admin.app, None, "ping"), post(admin.app, token, raw=b"junk")):
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    switch(admin, True)
    assert rpc(admin.app, token, "ping").status_code == 200


def test_a_cookie_session_never_opens_mcp(admin, token):
    """The signed-in admin's cookie (and the app's own CSRF header) are not a credential here."""
    r = admin.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
    r = admin.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                   headers={"Authorization": "Bearer kha_" + "B" * 43})
    assert r.status_code == 401
    assert admin.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                      headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_the_csrf_exemption_is_for_the_exact_path_only(admin, token):
    """/mcp needs no X-Requested-With and ignores Sec-Fetch-Site (it never reads a cookie); any other path, even
    /mcp/ or /mcpx, keeps the cookie checks."""
    assert security.BEARER_PATHS == frozenset({"/mcp", "/push/v1/body", "/push/v1/check"})  # the phone shortcuts' routes are the others
    ok = rpc(admin.app, token, "ping", sec_fetch_site="cross-site")
    assert ok.status_code == 200
    for path in ("/mcp/", "/mcpx", "/mcp/tools", "/MCP"):
        r = post(admin.app, token, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, path=path, sec_fetch_site="cross-site")
        assert r.status_code == 403 and r.json() == {"detail": "Cross-site request refused"}, path
    r = bare(admin.app).post("/api/log", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403 and "X-Requested-With" in r.json()["detail"]  # /api is unchanged


def test_another_persons_token_never_sees_this_persons_data(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    sam.put("/api/profile", json={"targets": {"potassium_mg": 1234}})
    secret = sam.post("/api/foods", json={"name": "Sam's secret stew", "serving_desc": "1 bowl (300 g)", "serving_g": 300,
                                          "nutrients": {"potassium_mg": 777, "carbs_g": 30}}).json()
    assert sam.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": secret["id"], "servings": 2}).status_code == 201
    sam_token, admin_token = token_for(sam), token_for(admin)
    app = admin.app

    mine = call(app, sam_token, "get_today", date=DAY)
    assert mine["entries"]["eaten"] == 1 and mine["nutrients"]["potassium_mg"]["eaten"]["value"] == 1554
    assert mine["nutrients"]["potassium_mg"]["target"]["max"] == 1234

    theirs = call(app, admin_token, "get_today", date=DAY)
    assert theirs["entries"] == {"eaten": 0, "planned": 0}
    assert theirs["nutrients"]["potassium_mg"]["eaten"]["value"] == 0 and "target" not in theirs["nutrients"]["potassium_mg"]
    assert all(r["name"] != "Sam's secret stew" for r in call(app, admin_token, "search_foods", query="secret stew")["results"])
    meal = call(app, admin_token, "check_meal", items=[{"food": "stew", "food_id": secret["id"]}])
    assert meal["items"] == [] and meal["unresolved"][0]["reason"] == "unknown_food_id"
    assert "Sam" not in json.dumps(meal)
    assert call(app, sam_token, "check_meal", items=[{"food": "stew", "food_id": secret["id"]}])["items"][0]["matched"]["name"] \
        == "Sam's secret stew"


# --------------------------------------------------------------------------- #
# get_today
# --------------------------------------------------------------------------- #


def _expected_amount(value: Any, missing: int) -> dict[str, Any]:
    return {"value": None if missing and not value else value, "not_listed_by": missing}


def _alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Alerts as the app builds them: the API's response model adds ``"meal": null`` to day-level ones."""
    return [{k: v for k, v in a.items() if v is not None} for a in alerts]


def test_get_today_has_exactly_todays_numbers(admin, token):
    set_targets(admin)
    log_food(admin, "Banana", meal="breakfast", servings=3)
    log_food(admin, "Cheese", meal="lunch")
    log_food(admin, "Chicken", meal="dinner", servings=3)  # protein above the "about" target
    plan(admin, "Juice, apple", 1, meal="snack")
    today = admin.get("/api/log", params={"date": DAY}).json()
    got = call(admin.app, token, "get_today", date=DAY)

    assert got["date"] == DAY and got["is_today"] is False
    assert got["entries"] == today["counts"] == {"eaten": 3, "planned": 1}
    assert got["targets_set"] is True
    assert _alerts(got["alerts"]) == _alerts(today["alerts"]) and got["alerts"]
    assert _alerts(got["alerts_if_planned_food_is_eaten"]) == _alerts(today["projected_alerts"])
    assert got["pattern_alerts"] == today["pattern_alerts"]
    for key in NUTRIENT_KEYS:
        view = got["nutrients"][key]
        assert view["eaten"] == _expected_amount(today["totals"][key], today["unknown"].get(key, 0)), key
        assert view["planned"] == _expected_amount(today["planned_totals"][key], today["planned_unknown"].get(key, 0))
        assert view["eaten_and_planned"] == _expected_amount(today["projected_totals"][key], today["projected_unknown"].get(key, 0))
        status = today["status"].get(key)
        assert ("target" in view) is (status is not None), key
        if status is None:
            continue
        assert view["target"]["max"] == status["target"] and view["target"]["min"] == status.get("min")
        judged = view["eaten_vs_target"]
        assert judged["level"] == status["level"] and judged["percent"] == round(status["fraction"] * 100)
        if status["fraction"] > 1:
            assert judged["over_by"] == round_value(key, status["value"] - status["target"]) and judged["left"] is None
        else:
            assert judged["left"] == round_value(key, status["target"] - status["value"]) and judged["over_by"] is None
        assert view["eaten_and_planned_vs_target"]["level"] == today["projected_status"][key]["level"]

    protein = got["nutrients"]["protein_g"]
    assert protein["target"] == {"max": 50, "min": 50, "about": True, "kind": "target"}
    assert protein["eaten_vs_target"]["over_by"] > 0
    assert got["nutrients"]["potassium_mg"]["target"] == {"max": 2000, "min": None, "about": False, "kind": "limit"}
    assert got["nutrients"]["potassium_mg"]["eaten_vs_target"]["left"] == 2000 - 1970  # 3 × 422 + 50 + 3 × 218
    assert "dialysis" not in got

    carbs = got["meal_carbohydrate"]  # a type 1 profile (the default before a type is chosen)
    assert carbs["goals_set"] is True and carbs["tolerance_g"] == today["carb_tolerance_g"] == 10
    assert carbs["meals"]["breakfast"]["goal_g"] == 45 and carbs["meals"]["breakfast"]["eaten_g"] == today["meals"]["breakfast"]["carbs_g"]
    assert carbs["meals"]["breakfast"]["over"] is True and carbs["meals"]["breakfast"]["left_g"] == 0  # 81 g > 45 + 10
    assert carbs["meals"]["lunch"]["left_g"] == round_value("carbs_g", 45 - today["meals"]["lunch"]["carbs_g"])
    assert carbs["meals"]["snack"]["planned_g"] == today["planned_meals"]["snack"]["carbs_g"]


def test_get_today_defaults_to_the_servers_today(admin, token):
    from app.log import today_local

    log_food(admin, "Banana", date=today_local())
    got = call(admin.app, token, "get_today")
    assert got["date"] == today_local() and got["is_today"] is True and got["entries"]["eaten"] == 1
    assert got["targets_set"] is False and "Profile" in got["note"]


@pytest.mark.safety
def test_low_treatment_carbs_never_count_toward_the_meal(admin, token):
    set_targets(admin)
    log_food(admin, "Glucose tablets", meal="lunch", servings=2)  # "Used to treat a low" by default
    carbs = call(admin.app, token, "get_today", date=DAY)["meal_carbohydrate"]["meals"]["lunch"]
    assert carbs["eaten_g"] == 32 and carbs["treating_a_low_g"] == 32 and carbs["left_g"] == 45 and carbs["over"] is False


def test_unknown_potassium_stays_null_with_a_count(admin, token):
    set_targets(admin)
    soup = admin.post("/api/foods", json={"name": "Mystery soup", "serving_desc": "1 cup (240 g)", "serving_g": 240,
                                          "nutrients": {"carbs_g": 20, "sodium_mg": 600}}).json()
    assert admin.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": soup["id"]}).status_code == 201
    got = call(admin.app, token, "get_today", date=DAY)
    potassium = got["nutrients"]["potassium_mg"]
    assert potassium["eaten"] == {"value": None, "not_listed_by": 1}  # never 0
    assert potassium["eaten_vs_target"]["left"] is None  # the total may be higher: nothing is "left"
    assert got["nutrients"]["sodium_mg"]["eaten"] == {"value": 600, "not_listed_by": 0}
    log_food(admin, "Banana", meal="lunch")
    potassium = call(admin.app, token, "get_today", date=DAY)["nutrients"]["potassium_mg"]
    assert potassium["eaten"] == {"value": 422, "not_listed_by": 1}  # at least 422

    found = call(admin.app, token, "search_foods", query="mystery soup")["results"][0]
    assert found["nutrients_per_serving"]["potassium_mg"] is None and found["nutrients_per_serving"]["phosphorus_mg"] is None
    meal = call(admin.app, token, "check_meal", items=[{"food": "mystery soup", "amount": 2}], date=DAY)
    assert meal["items"][0]["nutrients"]["potassium_mg"] is None
    assert meal["totals"]["potassium_mg"] == {"value": None, "not_listed_by": 1}
    assert meal["day_with_these_items"]["potassium_mg"]["total"] == {"value": 422, "not_listed_by": 2}
    assert meal["day_with_these_items"]["potassium_mg"]["left"] is None


def test_a_kidney_only_profile_has_no_meal_carbohydrate_goals(admin, token):
    set_targets(admin, diabetes="none")
    log_food(admin, "Banana", meal="breakfast", servings=3)
    got = call(admin.app, token, "get_today", date=DAY)
    assert "meal_carbohydrate" not in got
    assert not [a for a in got["alerts"] if a.get("meal")]
    meal = call(admin.app, token, "check_meal", items=[{"food": "banana", "amount": 3}], date=DAY, meal="lunch")
    assert "meal_carbohydrate" not in meal and not [n for n in meal["notes"] if "which meal" in n]
    set_targets(admin, diabetes="type1")
    assert "meal_carbohydrate" in call(admin.app, token, "get_today", date=DAY)


def test_hemodialysis_days_and_the_totals_since_the_last_session(admin, token):
    # 2026-10-05 is a Monday; sessions on Monday, Wednesday and Friday.
    set_targets(admin, dialysis="hemodialysis", dialysis_days=[0, 2, 4])
    log_food(admin, "Banana", meal="lunch", date="2026-10-05")
    log_food(admin, "Banana", meal="lunch", date="2026-10-06")
    info = call(admin.app, token, "get_today", date="2026-10-06")["dialysis"]
    assert info["type"] == "hemodialysis" and info["dialysis_days"] == ["Monday", "Wednesday", "Friday"]
    assert info["is_dialysis_day"] is False
    since = info["since_last_dialysis"]
    summary = admin.get("/api/log/summary", params={"start": "2026-09-30", "end": "2026-10-06"}).json()["interdialytic"]
    assert since == summary and since["since"] == "2026-10-05" and since["nutrients"]["potassium_mg"]["total"] == 844
    assert call(admin.app, token, "get_today", date="2026-10-05")["dialysis"]["is_dialysis_day"] is True


# --------------------------------------------------------------------------- #
# search_foods
# --------------------------------------------------------------------------- #


def test_search_foods_shows_the_apps_foods_per_serving(admin, token):
    got = call(admin.app, token, "search_foods", query="apple")
    assert 1 <= len(got["results"]) <= 5 and got["query"] == "apple"
    api = {f["id"]: f for f in admin.get("/api/foods", params={"q": "apple", "limit": 5}).json()["foods"]}
    for result in got["results"]:
        food = api[result["id"]]
        assert result["in_app"] is True and result["source"] == "builtin" and result["fdc_id"] == food["fdc_id"]
        assert result["name"] == food["name"] and result["nutrients_per_serving"] == food["nutrients"]
        assert result["serving"] == {"description": food["serving_desc"], "grams": food["serving_g"]}
        assert result["warnings_per_serving"] == food["warnings"] and result["kidney_rating"] == food["kidney_rating"]
    juice = next(r for r in got["results"] if r["name"] == "Juice, apple")
    assert juice["units"] == ["serving", "g", "cup"]
    assert len(call(admin.app, token, "search_foods", query="a", limit=2)["results"]) == 2
    assert got["usda"] == {"searched": False, "detail": foods_module.USDA_UNAVAILABLE["not_configured"]}
    nothing = call(admin.app, token, "search_foods", query="zzzz qqqq")
    assert nothing["results"] == [] and "fewer" in nothing["note"]


USDA_SEARCH = {
    "mango": {"totalHits": 2, "foods": [
        {"fdcId": 2000001, "description": "MANGO NECTAR", "dataType": "Branded", "brandOwner": "Acme Drinks",
         "brandedFoodCategory": "Fruit & Vegetable Juice, Nectars & Fruit Drinks", "servingSize": 240,
         "servingSizeUnit": "ml", "householdServingFullText": "1 cup",
         "foodNutrients": [{"nutrientId": 1008, "nutrientNumber": "208", "unitName": "KCAL", "value": 50},
                           {"nutrientId": 1005, "nutrientNumber": "205", "unitName": "G", "value": 12.5},
                           {"nutrientId": 1093, "nutrientNumber": "307", "unitName": "MG", "value": 10}]},
        {"description": "no id: skipped"},
    ]},
    "banana": {"totalHits": 2, "foods": [
        {"fdcId": 173944, "description": "Bananas, raw", "dataType": "SR Legacy", "foodCategory": "Fruits and Fruit Juices",
         "foodNutrients": [{"nutrientNumber": "208", "value": 89}, {"nutrientNumber": "306", "value": 358},
                           {"nutrientNumber": "305", "value": 22}, {"nutrientNumber": "205", "value": 22.84}]},
        {"fdcId": 777777, "description": "BANANA CHIPS", "dataType": "Branded", "brandOwner": "Acme Foods",
         "servingSize": 28, "servingSizeUnit": "g",
         "foodNutrients": [{"nutrientNumber": "208", "value": 519}, {"nutrientNumber": "306", "value": 536}]},
    ]},
}


@pytest.fixture
def usda_admin(tmp_path, foods_json, monkeypatch):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/fdc/v1/foods/search":
            return httpx2.Response(200, json=USDA_SEARCH.get(request.url.params["query"], {"foods": []}))
        return httpx2.Response(404, json={"error": "not found"})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    with signed_in_client(make_settings(tmp_path, foods_json, usda_api_key="TESTKEY")) as c:
        switch(c, True)
        c.seen_requests = seen  # type: ignore[attr-defined]
        yield c


def test_search_foods_adds_usda_results_mapped_by_the_app_and_saves_nothing(usda_admin):
    token = token_for(usda_admin)
    got = call(usda_admin.app, token, "search_foods", query="mango")
    assert got["usda"] == {"searched": True, "found": 1}
    request = usda_admin.seen_requests[-1]
    assert request.headers["x-api-key"] == "TESTKEY" and "TESTKEY" not in str(request.url)
    [nectar] = got["results"]
    assert nectar["id"] is None and nectar["fdc_id"] == 2000001 and nectar["source"] == "usda" and nectar["in_app"] is False
    assert nectar["serving"] == {"description": "1 cup (240 mL)", "grams": 240.0} and nectar["units"] == ["serving", "g", "cup"]  # usable by its fdc_id
    per = nectar["nutrients_per_serving"]
    assert per["calories_kcal"] == 120 and per["carbs_g"] == 30.0 and per["sodium_mg"] == 24
    assert per["potassium_mg"] is None and per["phosphorus_mg"] is None  # not reported: unknown, never 0
    assert "unknown, not zero" in nectar["notes"] and "fdc_id" in got["note"] and "add the food to the person" in got["note"]

    both = call(usda_admin.app, token, "search_foods", query="banana", limit=3)
    assert [(r["source"], r["fdc_id"]) for r in both["results"]] == [("builtin", 173944), ("usda", 777777)]
    conn = sqlite3.connect(usda_admin.app.state.settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'usda'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM user_food_links").fetchone()[0] == 0
    finally:
        conn.close()
    assert call(usda_admin.app, token, "search_foods", query="banana", limit=1)["usda"]["searched"] is False


# --------------------------------------------------------------------------- #
# check_meal
# --------------------------------------------------------------------------- #


def test_check_meal_amounts_in_servings_grams_and_household_measures(admin, token):
    banana = admin.get("/api/foods", params={"q": "banana"}).json()["foods"][0]
    juice = admin.get("/api/foods", params={"q": "juice, apple"}).json()["foods"][0]
    got = call(admin.app, token, "check_meal", date=DAY, meal="snack", items=[
        {"food": "banana"},
        {"food": "banana", "amount": 59, "unit": "g"},
        {"food": "apple juice", "amount": 1, "unit": "cups"},  # served as "1/2 cup (124 g)": 2 servings
        {"food": "chicken", "amount": 6, "unit": "oz"},  # "3 oz (85 g)": 2 servings
        {"food": "apple juice 1 cup"},  # amount and measure in the words
        {"food": "2 bananas"},
    ])
    assert got["saved"] is False and got["unresolved"] == []
    amounts = [(i["matched"]["name"], i["amount"]["servings"], i["amount"]["grams"]) for i in got["items"]]
    assert amounts == [("Banana, raw", 1.0, 118.0), ("Banana, raw", 0.5, 59.0), ("Juice, apple", 2.0, 248.0),
                       ("Chicken breast, roasted", 2.0, 170.0), ("Juice, apple", 2.0, 248.0), ("Banana, raw", 2.0, 236.0)]
    assert [i["amount"]["as_asked"] for i in got["items"]][:4] == ["1 serving", "59 g", "1 cups", "6 oz"]
    assert got["items"][0]["nutrients"] == banana["nutrients"]
    assert got["items"][2]["nutrients"]["potassium_mg"] == 2 * juice["nutrients"]["potassium_mg"]
    assert got["items"][1]["nutrients"]["potassium_mg"] == 211
    assert [i["how_matched"] for i in got["items"]] == ["name", "name", "name", "only_match", "name", "name"]
    assert got["items"][0]["warnings"][0]["message"] == "High potassium: 422 mg in this amount"
    assert got["totals"]["potassium_mg"] == {"value": round_value("potassium_mg", 422 * 3.5 + 125 * 4 + 218 * 2), "not_listed_by": 0}
    assert admin.get("/api/log", params={"date": DAY}).json()["entries"] == []  # nothing saved


def test_check_meal_projects_the_day_as_the_log_would_with_planned_entries(admin, token):
    set_targets(admin)
    log_food(admin, "Cheese", meal="breakfast")
    got = call(admin.app, token, "check_meal", date=DAY, meal="lunch",
               items=[{"food": "banana", "amount": 2}, {"food": "juice, apple", "amount": 1}])
    plan(admin, "Banana", 2)
    plan(admin, "Juice, apple", 1)
    today = admin.get("/api/log", params={"date": DAY}).json()
    for key in NUTRIENT_KEYS:
        view = got["day_with_these_items"][key]
        assert view["total"] == _expected_amount(today["projected_totals"][key], today["projected_unknown"].get(key, 0))
        if key in today["projected_status"]:
            assert view["level"] == today["projected_status"][key]["level"], key
    assert _alerts(got["alerts"]) == _alerts(today["projected_alerts"])
    assert got["pattern_alerts"] == today["pattern_alerts"]
    lunch = got["meal_carbohydrate"]
    assert lunch["meal"] == "lunch" and lunch["goal_g"] == 45
    # A banana is stored as 27.0 g of carbohydrate a serving (data/foods.json precision), the juice treats a low.
    assert lunch["these_items_g"] == 68.0 and lunch["treating_a_low_g"] == 14 and lunch["meal_with_these_items_g"] == 54.0
    assert lunch["over"] is False and lunch["left_g"] == 0  # 54 g is within the 10 g tolerance above 45 g
    juice = got["items"][1]
    assert juice["counted_as_treating_a_low"] is True and not [w for w in juice["warnings"] if w["nutrient"] == "carbs_g"]


def test_check_meal_unresolved_items_come_with_a_question(admin, token):
    for name in ("Rice, brown, cooked", "Rice, white, cooked"):
        admin.post("/api/foods", json={"name": name, "serving_desc": "1 cup (158 g)", "serving_g": 158,
                                       "nutrients": {"carbs_g": 44, "potassium_mg": 55}})
    got = call(admin.app, token, "check_meal", items=[
        {"food": "zzzz qqqq"},
        {"food": "rice", "amount": 1, "unit": "cup"},
        {"food": "banana", "amount": 2, "unit": "tbsp"},
        {"food": "banana", "food_id": 999999},
        {"food": "white rice 1 cup"},
    ])
    reasons = [(u["food"], u["reason"]) for u in got["unresolved"]]
    assert reasons == [("zzzz qqqq", "no_match"), ("rice", "several_matches"), ("banana", "unknown_unit"),
                       ("banana", "unknown_food_id")]
    for item in got["unresolved"]:
        assert item["question"].endswith(("?", ".")) and len(item["question"]) > 20
    rice = got["unresolved"][1]
    assert {a["name"] for a in rice["alternatives"]} == {"Rice, brown, cooked", "Rice, white, cooked"}
    assert all(isinstance(a["food_id"], int) for a in rice["alternatives"])
    assert got["unresolved"][2]["units"] == ["serving", "g", "medium"]
    [white] = got["items"]  # "white rice 1 cup": one food has both words
    assert white["matched"]["name"] == "Rice, white, cooked" and white["amount"]["servings"] == 1.0
    assert got["totals"]["carbs_g"] == {"value": 44.0, "not_listed_by": 0}
    assert any("unresolved" in n for n in got["notes"])
    picked = call(admin.app, token, "check_meal", items=[{"food": "rice", "food_id": rice["alternatives"][0]["food_id"]}])
    assert picked["unresolved"] == [] and picked["items"][0]["how_matched"] == "food_id"

    only_unresolved = call(admin.app, token, "check_meal", items=[{"food": "zzzz"}])
    assert only_unresolved["items"] == [] and only_unresolved["totals"] is None and "day_with_these_items" not in only_unresolved


def test_check_meal_reads_list_style_names_the_natural_way_round_and_never_guesses_the_order(admin, token):
    """"Chocolate, milk" (the food lists' style) is milk chocolate: "chocolate milk" must be asked about, not matched."""
    admin.post("/api/foods", json={"name": "Chocolate, milk", "serving_desc": "1 bar (44 g)", "serving_g": 44,
                                   "nutrients": {"carbs_g": 26, "potassium_mg": 169}})
    asked = call(admin.app, token, "check_meal", items=[{"food": "chocolate milk"}])
    assert asked["items"] == [] and asked["unresolved"][0]["reason"] == "several_matches"
    assert [a["name"] for a in asked["unresolved"][0]["alternatives"]] == ["Chocolate, milk"]
    named = call(admin.app, token, "check_meal", items=[{"food": "milk chocolate"}, {"food": "egg white"},
                                                        {"food": "roasted chicken"}, {"food": "Chocolate, milk"}])
    assert [(i["matched"]["name"], i["how_matched"]) for i in named["items"]] == [
        ("Chocolate, milk", "name"), ("Egg white, raw", "name"), ("Chicken breast, roasted", "only_match"),
        ("Chocolate, milk", "name")]  # the exact name, as search_foods shows it
    near = call(admin.app, token, "check_meal", items=[{"food": "grilled chicken"}])  # found only without "grilled"
    assert near["items"] == [] and near["unresolved"][0]["reason"] == "several_matches"
    assert [a["name"] for a in near["unresolved"][0]["alternatives"]] == ["Chicken breast, roasted"]


def test_check_meal_asks_which_meal_for_the_carbohydrate_goal(admin, token):
    set_targets(admin)
    got = call(admin.app, token, "check_meal", items=[{"food": "banana", "amount": 3}], date=DAY)
    assert "meal_carbohydrate" not in got and any("which meal" in n for n in got["notes"])
    lunch = call(admin.app, token, "check_meal", items=[{"food": "banana", "amount": 3}], date=DAY, meal="lunch")
    assert lunch["meal_carbohydrate"]["over"] is True and lunch["meal_carbohydrate"]["meal_with_these_items_g"] == 81.0
    assert any(a.get("meal") == "lunch" for a in lunch["alerts"])


# --------------------------------------------------------------------------- #
# safety_check
# --------------------------------------------------------------------------- #


@pytest.mark.safety
def test_safety_check_low_wording_returns_the_treating_a_low_card_with_the_persons_grams(admin, token):
    assert admin.patch("/api/me/settings", json={"guidance": {"hypo_dose_g": 20}}).status_code == 200
    for message in ("I feel shaky and low", "my sugar is 3.2", "bg 62 mg/dL", "I think I'm going low"):
        got = call(admin.app, token, "safety_check", message=message)
        assert got["action"] == "treat_low_first" and got["matched"] == {"low": True, "emergency": False}, message
        [card] = got["cards"]
        assert card["title"] == "Treating a low" and "take 20 g of fast carbs now" in card["lines"][0]
        assert card["url"] == "/learn/t1d/treating-a-low/" and card["full_url"] == "http://localhost/learn/t1d/treating-a-low/"
        assert "Treating a low card" in got["say_first"] and "link" not in got


@pytest.mark.safety
def test_safety_check_emergency_wording_points_to_get_help_now(admin, token):
    got = call(admin.app, token, "safety_check", message="I have chest pain and can't breathe")
    assert got["action"] == "get_help_now" and got["matched"] == {"low": False, "emergency": True}
    assert got["link"] == "/learn/get-help-now/" and got["full_link"] == "http://localhost/learn/get-help-now/"
    assert [c["title"] for c in got["cards"]] == ["Get help now"] and "emergency number" in got["say_first"]
    both = call(admin.app, token, "safety_check", message="I'm shaky and confused")
    assert both["action"] == "get_help_now" and both["matched"] == {"low": True, "emergency": True}
    assert [c["title"] for c in both["cards"]] == ["Get help now", "Treating a low"]
    assert "treat the low first" in both["say_first"] and "never delay" in both["say_first"]


@pytest.mark.safety
@pytest.mark.parametrize("message", ["What can I eat for lunch?", "low-fat yogurt with berries", "low sodium soup",
                                     "", "2 tsp sugar in my tea"])
def test_safety_check_neutral_wording_is_none(admin, token, message):
    got = call(admin.app, token, "safety_check", message=message)
    assert got["action"] == "none" and got["cards"] == [] and got["matched"] == {"low": False, "emergency": False}


@pytest.mark.safety
def test_no_tool_text_speaks_of_doses_or_insulin():
    """The only mention is the instruction never to give them."""
    dosing = re.compile(r"\b(insulin|bolus|basal|doses?|dosing|correction|ratios?|binders?|medicines?|medications?)\b", re.I)
    prohibition = "Never give insulin or medicine doses and never interpret lab results"
    assert prohibition in mcp_server.INSTRUCTIONS
    texts = [mcp_server.INSTRUCTIONS.replace(prohibition, ""), *mcp_tools.SAY_FIRST.values(), mcp_tools.LOW_TOO,
             mcp_tools.REMINDER, *(t.description for t in mcp_tools.TOOLS),
             *(json.dumps(t.input_schema) for t in mcp_tools.TOOLS)]
    for text in texts:
        assert not dosing.search(text), text


# --------------------------------------------------------------------------- #
# Rate limit
# --------------------------------------------------------------------------- #


def test_sixty_requests_a_minute_per_token(admin, token, fake_clock):
    for _ in range(60):
        assert rpc(admin.app, token, "ping").status_code == 200
    r = rpc(admin.app, token, "ping")
    assert r.status_code == 429 and 1 <= int(r.headers["retry-after"]) <= 60
    other = token_for(admin, "phone")
    assert rpc(admin.app, other, "ping").status_code == 200  # per token
    fake_clock.advance(seconds=61)
    assert rpc(admin.app, token, "ping").status_code == 200


def test_a_second_person_on_the_same_server_has_their_own_limit(two_clients):
    admin, sam = two_clients
    switch(admin, True)
    admin_token = token_for(admin)
    for _ in range(60):
        rpc(admin.app, admin_token, "ping")
    assert rpc(admin.app, admin_token, "ping").status_code == 429
    assert rpc(admin.app, token_for(sam), "ping").status_code == 200
