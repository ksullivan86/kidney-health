"""v0.3 log changes (note 06 §4.10–§4.11, note 02 R5): ``purpose``, ``client_id`` on ``POST /api/log``,
``/quick`` and ``PUT``, ``POST /api/log/batch`` (atomic, idempotent per person, per-item results) and
the saved meal's ``meal_hint``."""
from __future__ import annotations

import csv
import io
import json
import uuid

from conftest import DAY, find_food, log_food, send_json


def cid() -> str:
    return str(uuid.uuid4())


def entry_body(client, query: str, **extra):
    food = find_food(client, query)
    return {"date": DAY, "meal": "lunch", "food_id": food["id"], "servings": 1, **extra}


def count_entries(client, day: str = DAY) -> int:
    return len(client.get("/api/log", params={"date": day}).json()["entries"])


# --------------------------------------------------------------------------- #
# purpose
# --------------------------------------------------------------------------- #


def test_low_treatment_foods_default_to_purpose_hypo(client):
    tablets = log_food(client, "glucose tablets", meal="snack")
    assert tablets["purpose"] == "hypo"
    unticked = log_food(client, "glucose tablets", meal="snack", purpose="none")
    assert unticked["purpose"] is None
    apple_juice_at_breakfast = log_food(client, "juice, apple", meal="breakfast", purpose="none")
    assert apple_juice_at_breakfast["purpose"] is None
    banana_for_a_low = log_food(client, "banana", meal="snack", purpose="hypo")  # any food can treat a low
    assert banana_for_a_low["purpose"] == "hypo"
    assert log_food(client, "banana")["purpose"] is None


def test_purpose_is_validated_and_editable(client):
    body = entry_body(client, "banana", purpose="sometimes")
    assert client.post("/api/log", json=body).status_code == 400
    entry = log_food(client, "glucose tablets", meal="snack")
    r = client.put(f"/api/log/{entry['id']}", json={"purpose": "none"})
    assert r.status_code == 200 and r.json()["purpose"] is None
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 2})  # left out: unchanged
    assert r.json()["purpose"] is None
    r = client.put(f"/api/log/{entry['id']}", json={"purpose": "hypo"})
    assert r.json()["purpose"] == "hypo"
    assert client.put(f"/api/log/{entry['id']}", json={"purpose": "maybe"}).status_code == 400


def test_quick_add_purpose_follows_its_flags(client):
    body = {"date": DAY, "meal": "snack", "name": "Jelly beans", "nutrients": {"carbs_g": 15},
            "flags": ["hypo_treatment"]}
    r = client.post("/api/log/quick", json=body)
    assert r.status_code == 201 and r.json()["purpose"] == "hypo"
    r = client.post("/api/log/quick", json={**body, "name": "Toast", "flags": []})
    assert r.json()["purpose"] is None


def test_csv_and_export_carry_the_purpose(client):
    log_food(client, "glucose tablets", meal="snack")
    rows = list(csv.reader(io.StringIO(client.get("/api/log/export.csv").text)))
    record = dict(zip(rows[0], rows[1]))
    assert record["purpose"] == "hypo"


def test_copy_day_keeps_the_purpose(client):
    log_food(client, "glucose tablets", meal="snack")
    r = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": "2026-10-06"})
    assert r.status_code == 201 and r.json()["entries"][0]["purpose"] == "hypo"


# --------------------------------------------------------------------------- #
# client_id (offline outbox replay)
# --------------------------------------------------------------------------- #


def test_repeat_of_a_client_id_answers_200_with_the_same_entry(client):
    body = entry_body(client, "banana", client_id=cid().upper())
    first = client.post("/api/log", json=body)
    assert first.status_code == 201
    assert first.json()["client_id"] == body["client_id"].lower()
    again = client.post("/api/log", json=body)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert count_entries(client) == 1


def test_client_id_must_be_a_uuid(client):
    for bad in ("x" * 36, "1234", "", "0f8fad5b-d9cb-469f-a165-70867728950e0"):
        r = client.post("/api/log", json=entry_body(client, "banana", client_id=bad))
        assert r.status_code == 400, bad
        assert "client_id" in r.json()["detail"]
    assert count_entries(client) == 0


def test_two_people_may_use_the_same_client_id(two_clients):
    admin, sam = two_clients
    shared = cid()
    a = admin.post("/api/log", json=entry_body(admin, "banana", client_id=shared))
    b = sam.post("/api/log", json=entry_body(sam, "apple", client_id=shared))
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    assert sam.post("/api/log", json=entry_body(sam, "apple", client_id=shared)).status_code == 200
    assert count_entries(sam) == 1 and count_entries(admin) == 1


def test_quick_add_repeat_creates_no_second_food(client):
    body = {"date": DAY, "meal": "lunch", "name": "Grandma's soup", "nutrients": {"sodium_mg": 300},
            "client_id": cid()}
    first = client.post("/api/log/quick", json=body)
    again = client.post("/api/log/quick", json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    custom = client.get("/api/foods", params={"q": "grandma"}).json()["foods"]
    assert len(custom) == 1


# --------------------------------------------------------------------------- #
# POST /api/log/batch
# --------------------------------------------------------------------------- #


def test_batch_adds_entries_in_order_with_per_item_results(client):
    ids = [cid(), cid()]
    body = {"entries": [entry_body(client, "egg white", meal="dinner", status="planned", client_id=ids[0]),
                        entry_body(client, "apple", meal="dinner", status="planned", servings=0.5, client_id=ids[1]),
                        entry_body(client, "glucose tablets", meal="snack")]}
    r = client.post("/api/log/batch", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert [e["food_name"] for e in data["entries"]] == ["Egg white, raw", "Apple, raw, with skin", "Glucose tablets"]
    assert [e["status"] for e in data["entries"]] == ["planned", "planned", "eaten"]
    assert data["entries"][1]["servings"] == 0.5
    assert data["entries"][2]["purpose"] == "hypo"  # same default as POST /api/log
    assert [x["result"] for x in data["results"]] == ["created"] * 3
    assert [x["index"] for x in data["results"]] == [0, 1, 2]
    assert [x["id"] for x in data["results"]] == [e["id"] for e in data["entries"]]

    # Replay (the response was lost): nothing is added twice; items without client_id are new.
    replay = {"entries": body["entries"][:2]}
    r = client.post("/api/log/batch", json=replay)
    assert r.status_code == 200
    assert [x["result"] for x in r.json()["results"]] == ["existing", "existing"]
    assert [e["id"] for e in r.json()["entries"]] == [e["id"] for e in data["entries"][:2]]
    mixed = {"entries": [body["entries"][0], entry_body(client, "water", meal="dinner", client_id=cid())]}
    r = client.post("/api/log/batch", json=mixed)
    assert r.status_code == 201
    assert [x["result"] for x in r.json()["results"]] == ["existing", "created"]
    assert count_entries(client) == 4


def test_batch_is_all_or_nothing(client):
    good = entry_body(client, "banana", client_id=cid())
    missing = {**entry_body(client, "apple"), "food_id": 999_999}
    r = client.post("/api/log/batch", json={"entries": [good, missing]})
    assert r.status_code == 404
    assert r.json()["detail"] == "entries[1]: food 999999 not found"
    assert count_entries(client) == 0
    # The same batch, fixed, goes through: the failed attempt left nothing behind.
    r = client.post("/api/log/batch", json={"entries": [good, entry_body(client, "apple")]})
    assert r.status_code == 201 and [x["result"] for x in r.json()["results"]] == ["created", "created"]


def test_batch_items_are_validated_like_single_entries(client):
    good = entry_body(client, "banana")
    cases = [
        {"entries": []},
        {"entries": [good] * 41},
        {"entries": [good, {**good, "servings": 0}]},
        {"entries": [good, {**good, "meal": "brunch"}]},
        {"entries": [good, {**good, "date": "2026-02-30"}]},
        {"entries": [good, {**good, "purpose": "later"}]},
        {"entries": [good], "extra": True},
        {"items": [good]},
    ]
    for body in cases:
        r = client.post("/api/log/batch", json=body)
        assert r.status_code == 400, (body if len(str(body)) < 200 else "41 items", r.text)
    r = send_json(client, "POST", "/api/log/batch", {"entries": [{**good, "servings": float("inf")}]})
    assert r.status_code == 400
    same = cid()
    r = client.post("/api/log/batch", json={"entries": [{**good, "client_id": same}, {**good, "client_id": same}]})
    assert r.status_code == 400 and "entries[1].client_id repeats entries[0].client_id" in r.json()["detail"]
    assert count_entries(client) == 0
    r = client.post("/api/log/batch", json={"entries": [good] * 40})
    assert r.status_code == 201 and len(r.json()["entries"]) == 40


def test_batch_never_reaches_another_persons_food(two_clients):
    admin, sam = two_clients
    custom = admin.post("/api/log/quick", json={"date": DAY, "meal": "lunch", "name": "Admin's stew"}).json()
    r = sam.post("/api/log/batch", json={"entries": [{"date": DAY, "meal": "lunch", "food_id": custom["food_id"]}]})
    assert r.status_code == 404 and count_entries(sam) == 0


def test_batch_needs_a_signed_in_person(anon_client):
    r = anon_client.post("/api/log/batch", json={"entries": [{"date": DAY, "meal": "lunch", "food_id": 1}]})
    assert r.status_code == 401


def test_batch_body_over_the_server_limit_is_refused(client):
    body = {"entries": [entry_body(client, "banana", note="x" * 500)] * 40}
    padded = "{\"entries\": " + json.dumps(body["entries"]) + " " * 1_100_000 + "}"
    r = client.post("/api/log/batch", content=padded, headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert count_entries(client) == 0


# --------------------------------------------------------------------------- #
# Saved meals: meal_hint
# --------------------------------------------------------------------------- #


def test_from_log_sets_the_meal_hint_and_leaves_low_treatments_out(client):
    log_food(client, "chicken", meal="dinner")
    log_food(client, "apple", meal="dinner")
    log_food(client, "glucose tablets", meal="dinner")  # a low treated at dinner is not part of the meal
    r = client.post("/api/meals/from-log", json={"date": DAY, "meal": "dinner", "name": "Usual dinner"})
    assert r.status_code == 201
    meal = r.json()
    assert meal["meal_hint"] == "dinner"
    assert [i["food_name"] for i in meal["items"]] == ["Chicken breast, roasted", "Apple, raw, with skin"]
    only_low = client.post("/api/meals/from-log", json={"date": DAY, "meal": "snack", "name": "x"})
    assert only_low.status_code == 400


def test_meal_hint_is_optional_validated_and_kept_by_older_clients(client):
    food = find_food(client, "egg white")
    body = {"name": "Eggs", "items": [{"food_id": food["id"], "servings": 2}]}
    assert client.post("/api/meals", json={**body, "meal_hint": "elevenses"}).status_code == 400
    meal = client.post("/api/meals", json={**body, "meal_hint": "breakfast"}).json()
    assert meal["meal_hint"] == "breakfast"
    kept = client.put(f"/api/meals/{meal['id']}", json={**body, "name": "Eggs (2)"}).json()
    assert kept["meal_hint"] == "breakfast" and kept["name"] == "Eggs (2)"
    cleared = client.put(f"/api/meals/{meal['id']}", json={**body, "meal_hint": None}).json()
    assert cleared["meal_hint"] is None
    assert client.post("/api/meals", json=body).json()["meal_hint"] is None
