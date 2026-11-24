"""Saved meals and recipes both ways (design note 39, plan step 8; ``app/app_sync.py``, ``app/sync_feed.py``).

Covered: a phone that syncs both ways sends a new saved meal in ``POST /push/v1/sync`` (``meals``), each item naming its food as an
entry does; a second send adds nothing; a meal whose food the server does not have is skipped; an edit of a saved meal through
``POST /push/v1/changes`` names its foods the same way, keeps note 02's rule (a stale base is a conflict and nothing changes) and
answers ``refused`` for a food the server does not have yet; a food made on the server and read from the feed is found by its
``client_id`` (for entries too); nothing reaches another person."""
from __future__ import annotations

import uuid
from typing import Any

from app import row_versions as RV
from conftest import DAY, add_user, find_food
from test_app_gateway import make_sync, switches
from test_app_sync import ok
from test_push import bare
from test_sync_feed import everything, send

import pytest


def cid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def admin(client):
    switches(client)
    return client


@pytest.fixture
def token(admin) -> str:
    return make_sync(admin)["token"]


def builtin_ref(food: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"name": food["name"]}
    if food.get("fdc_id") is not None:
        out["fdc_id"] = food["fdc_id"]
    return {"builtin": out}


def meal_body(admin, client_id: str, **extra: Any) -> dict[str, Any]:
    apple = find_food(admin, "apple")
    return {"client_id": client_id, "name": "Usual breakfast", "meal_hint": "breakfast",
            "items": [{"food": builtin_ref(apple), "servings": 1.5}], **extra}


def test_a_new_saved_meal_is_added_once_and_comes_back_in_the_feed(admin, token):
    m = cid()
    out = ok(admin.app, token, {"meals": [meal_body(admin, m, servings_made=2, steps=["Slice", "Serve"])]})
    assert out["added"]["meals"] == 1 and out["already_there"]["meals"] == 0
    again = ok(admin.app, token, {"meals": [meal_body(admin, m)]})
    assert again["added"]["meals"] == 0 and again["already_there"]["meals"] == 1
    [meal] = admin.get("/api/meals").json()["meals"]
    assert meal["name"] == "Usual breakfast" and meal["servings_made"] == 2 and meal["steps"] == ["Slice", "Serve"]
    assert meal["items"][0]["servings"] == 1.5
    changes, _, _ = everything(admin.app, token)
    [c] = [x for x in changes if x["kind"] == "meal"]
    assert c["id"] == m and c["version"] == RV.row_version("meal", c["row"])
    assert c["row"]["items"][0]["food"]["builtin"]["name"] == meal["items"][0]["food_name"]


def test_a_meal_with_an_own_food_sent_in_the_same_request_or_made_on_the_server(admin, token):
    food = cid()
    pudding = {"client_id": food, "name": "Rice pudding", "serving_desc": "1 bowl", "serving_g": 150, "nutrients": {"potassium_mg": 180}}
    out = ok(admin.app, token, {"foods": [pudding], "meals": [{"client_id": cid(), "name": "Pudding night",
                                                               "items": [{"food": {"client_id": food}, "servings": 1}]}]})
    assert out["added"]["meals"] == 1
    # A food made in the web app: the phone reads it from the feed and names it by its client_id.
    admin.post("/api/foods", json={"name": "Custard", "serving_desc": "1 cup", "serving_g": 120, "nutrients": {}})
    changes, _, _ = everything(admin.app, token)
    custard = next(c for c in changes if c["kind"] == "food" and c["row"]["name"] == "Custard")
    out = ok(admin.app, token, {"meals": [{"client_id": cid(), "name": "Custard", "items": [{"food": {"client_id": custard["id"]}, "servings": 2}]}],
                                "entries": [{"client_id": cid(), "date": DAY, "meal": "snack", "food": {"client_id": custard["id"]}}]})
    assert out["added"]["meals"] == 1 and out["added"]["entries"] == 1 and out["skipped"]["food_not_found"] == 0


def test_a_meal_whose_food_is_not_here_is_skipped(admin, token):
    out = ok(admin.app, token, {"meals": [{"client_id": cid(), "name": "Mystery", "items": [{"food": {"client_id": cid()}, "servings": 1}]}]})
    assert out["added"]["meals"] == 0 and out["skipped"]["food_not_found"] == 1
    assert admin.get("/api/meals").json()["meals"] == []


def test_the_meal_is_checked_like_the_route(admin, token):
    r = bare(admin.app).post("/push/v1/sync", json={"meals": [{**meal_body(admin, cid()), "name": ""}]},
                             headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400 and r.json()["detail"].startswith("meals.0.name")
    r = bare(admin.app).post("/push/v1/sync", json={"meals": [{**meal_body(admin, cid()), "items": [{"food_id": 1, "servings": 1}]}]},
                             headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


def test_an_edit_names_foods_like_the_phone_and_keeps_note_02s_rule(admin, token):
    apple = find_food(admin, "apple")
    banana = find_food(admin, "banana")
    made = admin.post("/api/meals", json={"name": "Snack", "items": [{"food_id": apple["id"], "servings": 1}], "steps": ["Wash"]}).json()
    changes, _, _ = everything(admin.app, token)
    c = next(x for x in changes if x["kind"] == "meal")
    fields = {"name": "Fruit snack", "items": [{"food": builtin_ref(apple), "servings": 1}, {"food": builtin_ref(banana), "servings": 0.5}]}
    [r] = send(admin.app, token, {"kind": "meal", "id": c["id"], "op": "edit", "base": "0" * 16, "fields": fields})
    assert r["status"] == "conflict" and r["version"] == c["version"]
    assert admin.get(f"/api/meals/{made['id']}").json()["name"] == "Snack"
    [r] = send(admin.app, token, {"kind": "meal", "id": c["id"], "op": "edit", "base": c["version"], "fields": fields})
    assert r["status"] == "done"
    now = admin.get(f"/api/meals/{made['id']}").json()
    assert now["name"] == "Fruit snack" and [i["food_name"] for i in now["items"]] == [apple["name"], banana["name"]]
    assert now["steps"] == ["Wash"]  # left out: kept, as on the route
    changes, _, _ = everything(admin.app, token)
    assert next(x for x in changes if x["kind"] == "meal")["version"] == r["version"]
    [r2] = send(admin.app, token, {"kind": "meal", "id": c["id"], "op": "edit", "base": r["version"],
                                   "fields": {"name": "X", "items": [{"food": {"client_id": cid()}, "servings": 1}]}})
    assert r2["status"] == "refused" and "not on your server yet" in r2["detail"]
    [r3] = send(admin.app, token, {"kind": "meal", "id": c["id"], "op": "edit", "base": r["version"],
                                   "fields": {"name": "X", "items": [{"food_id": apple["id"], "servings": 1}]}})
    assert r3["status"] == "refused"  # the server's ids mean nothing on the phone: refused, never used
    [r4] = send(admin.app, token, {"kind": "meal", "id": c["id"], "op": "delete", "base": r["version"]})
    assert r4["status"] == "done" and admin.get("/api/meals").json()["meals"] == []


def test_another_persons_meals_never_reach_the_feed_or_the_writes(https_client):
    switches(https_client)
    mine = make_sync(https_client)["token"]
    apple = find_food(https_client, "apple")
    sam = add_user(https_client)
    other = https_client.post("/api/meals", json={"name": "Admin's", "items": [{"food_id": apple["id"], "servings": 1}]})
    assert other.status_code == 201
    changes, _, _ = everything(https_client.app, mine)
    c = next(x for x in changes if x["kind"] == "meal")
    bobs = make_sync(sam, name="Sam's iPhone")["token"]
    bob_changes, _, _ = everything(https_client.app, bobs)
    assert [x for x in bob_changes if x["kind"] == "meal"] == []
    [r] = send(https_client.app, bobs, {"kind": "meal", "id": c["id"], "op": "delete", "base": c["version"]})
    assert r["status"] == "gone"
    out = ok(https_client.app, bobs, {"meals": [{"client_id": c["id"], "name": "Bob's", "items": [{"food": builtin_ref(apple), "servings": 1}]}]})
    assert out["added"]["meals"] == 1  # the same ID is free for another person: their own row
