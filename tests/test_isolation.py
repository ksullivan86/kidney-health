"""Two-user isolation matrix (note 07 §4.10 and §9 N5).

User A (the admin) creates one of everything; user B must get 404 on every id-bearing route, never
see A's rows in lists, summaries, shopping, search, categories or exports, and B's USDA import of the
same ``fdc_id`` links the shared row without exposing (or removing) A's link.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile


import httpx2
import pytest

import app.foods as foods_module

from conftest import DAY, HTTPS_URL, add_user, make_settings, signed_in_client

OTHER_DAY = "2026-10-06"
CUSTOM = {"name": "Grandma's secret stew", "category": "Family recipes", "serving_desc": "1 bowl", "serving_g": 300,
          "nutrients": {"potassium_mg": 900, "sodium_mg": 1200}}
USDA_RECORD = {
    "fdcId": 424242, "description": "Shared USDA oats", "dataType": "SR Legacy",
    "foodCategory": {"description": "Breakfast Cereals"},
    "foodNutrients": [{"nutrient": {"number": "306"}, "amount": 100}],
}


@pytest.fixture
def pair(tmp_path, foods_json, monkeypatch):
    """(A, B, A's things) on one HTTPS app with a mocked USDA upstream and a shared env key."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/fdc/v1/food/424242":
            return httpx2.Response(200, json=USDA_RECORD)
        return httpx2.Response(404, json={})

    monkeypatch.setattr(
        foods_module, "usda_client",
        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)),
    )
    settings = make_settings(tmp_path, foods_json, usda_api_key="SHARED-ENV-KEY-0123456789")
    with signed_in_client(settings, base_url=HTTPS_URL) as a:
        b = add_user(a, "sam")
        banana = a.get("/api/foods", params={"q": "banana"}).json()["foods"][0]
        food = a.post("/api/foods", json=CUSTOM).json()
        entry = a.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"], "note": "A's note"}).json()
        planned = a.post("/api/log", json={"date": DAY, "meal": "dinner", "food_id": banana["id"], "status": "planned"}).json()
        meal = a.post("/api/meals", json={"name": "A's usual", "items": [{"food_id": food["id"], "servings": 1}]}).json()
        usda = a.post("/api/foods/usda/import", json={"fdc_id": 424242}).json()
        assert a.put("/api/profile", json={"name": "Alice", "weight_kg": 61}).status_code == 200
        assert a.patch("/api/me/settings", json={"ui.theme": "dark"}).status_code == 200
        assert a.put("/api/me/keys/usda", json={"api_key": "A-PRIVATE-KEY-abcdefghijklmnop"}).status_code == 200
        things = {"food": food, "entry": entry, "planned": planned, "meal": meal, "usda": usda, "banana": banana}
        yield a, b, things


def test_b_gets_404_on_every_id_bearing_route_of_a(pair):
    a, b, t = pair
    fid, eid, mid = t["food"]["id"], t["entry"]["id"], t["meal"]["id"]
    food_body = {"name": "x", "serving_desc": "1", "serving_g": 1, "nutrients": {}}
    checks = [
        ("GET", f"/api/foods/{fid}", None),
        ("PUT", f"/api/foods/{fid}", food_body),
        ("DELETE", f"/api/foods/{fid}", None),
        ("POST", f"/api/foods/{fid}/copy", None),
        ("PUT", f"/api/log/{eid}", {"servings": 2}),
        ("DELETE", f"/api/log/{eid}", None),
        ("GET", f"/api/meals/{mid}", None),
        ("PUT", f"/api/meals/{mid}", {"name": "mine now", "items": [{"food_id": t["banana"]["id"], "servings": 1}]}),
        ("DELETE", f"/api/meals/{mid}", None),
        ("POST", f"/api/meals/{mid}/apply", {"date": DAY, "meal": "lunch"}),
        # A's custom food used by B
        ("POST", "/api/log", {"date": DAY, "meal": "lunch", "food_id": fid}),
        ("POST", "/api/meals", {"name": "x", "items": [{"food_id": fid, "servings": 1}]}),
        # the shared USDA row is not B's until B imports it
        ("GET", f"/api/foods/{t['usda']['id']}", None),
        ("POST", "/api/log", {"date": DAY, "meal": "lunch", "food_id": t["usda"]["id"]}),
    ]
    for method, url, body in checks:
        r = b.request(method, url, json=body)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
    # and nothing of A's changed
    assert a.get(f"/api/foods/{fid}").json()["name"] == CUSTOM["name"]
    assert a.get(f"/api/meals/{mid}").json()["name"] == "A's usual"
    assert [e["id"] for e in a.get("/api/log", params={"date": DAY}).json()["entries"]] == [eid, t["planned"]["id"]]


def test_b_never_sees_a_rows_in_lists_summaries_and_search(pair):
    a, b, t = pair
    day = b.get("/api/log", params={"date": DAY}).json()
    assert day["entries"] == [] and day["counts"] == {"eaten": 0, "planned": 0} and day["totals"]["potassium_mg"] == 0
    rng = b.get("/api/log/range", params={"start": DAY, "end": DAY}).json()["days"][0]
    assert rng["counts"] == {"eaten": 0, "planned": 0}
    summary = b.get("/api/log/summary", params={"start": DAY, "end": DAY}).json()
    assert summary["logged_days"] == 0
    assert b.get("/api/plan/shopping", params={"start": DAY, "end": DAY}).json() == {"items": []}
    assert b.get("/api/meals").json() == {"meals": []}
    names = {f["name"] for f in b.get("/api/foods", params={"limit": 200}).json()["foods"]}
    assert CUSTOM["name"] not in names and "Shared USDA oats" not in names
    assert b.get("/api/foods", params={"q": "secret stew"}).json()["foods"] == []
    assert "Family recipes" not in b.get("/api/foods/categories").json()["categories"]
    assert "Family recipes" in a.get("/api/foods/categories").json()["categories"]
    profile = b.get("/api/profile").json()
    assert profile["name"] == "" and profile["weight_kg"] is None and profile["id"] != 1
    assert b.get("/api/me/settings").json()["settings"]["ui.theme"]["value"] == "system"
    keys = b.get("/api/me/keys").json()["providers"][0]
    assert keys["own"] == {"set": False} and keys["effective"] == "shared"


def test_b_actions_never_touch_a_rows(pair):
    a, b, t = pair
    assert b.post("/api/log/mark-eaten", json={"date": DAY}).json() == {"updated": 0}
    assert a.get("/api/log", params={"date": DAY}).json()["counts"] == {"eaten": 1, "planned": 1}
    assert b.post("/api/log/copy-day", json={"from_date": DAY, "to_date": OTHER_DAY}).status_code == 400
    assert b.post("/api/meals/from-log", json={"date": DAY, "meal": "lunch", "name": "steal"}).status_code == 400
    assert b.get("/api/log", params={"date": OTHER_DAY}).json()["entries"] == []


def test_recently_logged_order_uses_only_the_callers_log(pair):
    """§9 N5 (1): B's empty-query list must not reveal what A ate recently."""
    a, b, t = pair
    for _ in range(3):
        a.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": t["banana"]["id"]})
    a_first = a.get("/api/foods", params={"limit": 3}).json()["foods"][0]["name"]
    assert a_first == t["banana"]["name"]
    b_list = [f["name"] for f in b.get("/api/foods", params={"limit": 50}).json()["foods"]]
    assert b_list == sorted(b_list, key=str.casefold)  # nothing logged by B: plain alphabetical


def test_shared_usda_row_links_without_exposing_and_unlink_is_per_person(pair):
    """§9 N5 (2): importing reuses the shared row; DELETE removes only the caller's link."""
    a, b, t = pair
    shared_id = t["usda"]["id"]
    imported = b.post("/api/foods/usda/import", json={"fdc_id": 424242})
    assert imported.status_code == 200 and imported.json()["id"] == shared_id
    assert b.get(f"/api/foods/{shared_id}").status_code == 200
    assert b.post("/api/log", json={"date": DAY, "meal": "breakfast", "food_id": shared_id}).status_code == 201
    # read-only for both: edit means copy
    body = {"name": "Mine", "serving_desc": "1", "serving_g": 40, "nutrients": {}}
    assert b.put(f"/api/foods/{shared_id}", json=body).status_code == 409
    assert b.delete(f"/api/foods/{shared_id}").status_code == 204
    assert b.get(f"/api/foods/{shared_id}").status_code == 404
    assert b.delete(f"/api/foods/{shared_id}").status_code == 404
    assert a.get(f"/api/foods/{shared_id}").status_code == 200  # A keeps theirs
    assert any(f["id"] == shared_id for f in a.get("/api/foods", params={"q": "oats"}).json()["foods"])
    # B's entry (a snapshot) survives B's unlink
    assert len(b.get("/api/log", params={"date": DAY}).json()["entries"]) == 1


def test_deleting_a_custom_food_only_counts_the_owners_references(pair):
    a, b, t = pair
    mine = b.post("/api/foods", json={**CUSTOM, "name": "B's soup"}).json()
    assert b.delete(f"/api/foods/{mine['id']}").status_code == 204
    assert b.get(f"/api/foods/{mine['id']}").status_code == 404  # unreferenced: really deleted
    # A's referenced custom food is hidden, not deleted, and only for A to see
    assert a.delete(f"/api/foods/{t['food']['id']}").status_code == 204
    assert a.get(f"/api/foods/{t['food']['id']}").json()["hidden"] is True


def test_sessions_are_per_person(pair):
    """§9 N5 (4): a session selector of someone else answers 404."""
    a, b, t = pair
    a_sessions = a.get("/api/me/sessions").json()["sessions"]
    assert len(a_sessions) == 1 and a_sessions[0]["current"] is True
    assert b.delete(f"/api/me/sessions/{a_sessions[0]['id']}").status_code == 404
    assert a.get("/api/me").status_code == 200
    b_sessions = b.get("/api/me/sessions").json()["sessions"]
    assert [s["id"] for s in b_sessions] != [s["id"] for s in a_sessions]


def test_exports_hold_only_the_callers_data(pair):
    a, b, t = pair
    text = b.get("/api/log/export.csv").text
    assert list(csv.reader(io.StringIO(text)))[1:] == []
    r = b.get("/api/me/export.zip")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        data = json.loads(z.read("export.json"))
        blob = b"".join(z.read(n) for n in z.namelist())
    assert data["user"]["username"] == "sam"
    assert data["log_entries"] == [] and data["custom_foods"] == [] and data["meal_templates"] == []
    assert b"secret stew" not in blob and b"Alice" not in blob and b"A's note" not in blob
    assert b"A-PRIVATE-KEY" not in blob and b"SHARED-ENV-KEY" not in blob
    # A's export has A's data
    with zipfile.ZipFile(io.BytesIO(a.get("/api/me/export.zip").content)) as z:
        mine = json.loads(z.read("export.json"))
    assert [e["note"] for e in mine["log_entries"]] == ["A's note", None]
    assert [f["name"] for f in mine["custom_foods"]] == [CUSTOM["name"]]
    assert [f["name"] for f in mine["linked_foods"]] == ["Shared USDA oats"]


def test_admins_cannot_read_other_peoples_data(pair):
    a, b, t = pair
    b.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": t["banana"]["id"], "note": "B private"})
    users = a.get("/api/admin/users").json()["users"]
    assert {u["username"] for u in users} == {"admin", "sam"}
    blob = json.dumps(users) + json.dumps(a.get("/api/admin/usage").json()) + json.dumps(a.get("/api/admin/audit").json())
    assert "B private" not in blob and "potassium" not in blob
    # there is no admin route that takes another person's id for data
    assert all(not p.startswith(("/api/admin/log", "/api/admin/foods", "/api/admin/profile"))
               for p in a.app.openapi()["paths"])


def test_server_ignores_a_user_id_in_bodies(pair):
    """§9 N5 (6): the owner always comes from the session, never from the request body."""
    a, b, t = pair
    r = b.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": t["banana"]["id"], "user_id": 1})
    assert r.status_code in (201, 400)
    assert len(a.get("/api/log", params={"date": DAY}).json()["entries"]) == 2
    r = b.post("/api/foods", json={**CUSTOM, "name": "planted", "owner_user_id": 1})
    assert r.status_code in (201, 400)
    assert a.get("/api/foods", params={"q": "planted"}).json()["foods"] == []


def test_custom_food_without_owner_is_refused_by_the_database(pair):
    """§9 N5 (7): a trigger refuses a custom food without an owner, whatever code path inserts it."""
    import sqlite3

    a, b, t = pair
    conn = sqlite3.connect(a.app.state.settings.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="owner_user_id"):
        conn.execute(
            "INSERT INTO foods (name, source, serving_desc, serving_g, created_at, updated_at) VALUES ('x', 'custom', '1', 1, 'n', 'n')"
        )
    with pytest.raises(sqlite3.IntegrityError, match="user_id is required"):
        conn.execute("UPDATE log_entries SET user_id = NULL")
    conn.close()
