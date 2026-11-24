"""``POST /push/v1/sync`` (design note 38 §5.5, step 4; ``app/app_sync.py``): the iPhone app sends the rows it made on the phone
with an **app** token (a device token with the scope ``app:add``), and reads nothing.

Covered: the token kind (scopes, the list item, refusals), which tokens work where, the instance switch, every list (own foods,
built-in, USDA and Open Food Facts foods, entries, labs, symptoms, weights, readings), the checks of the normal create routes and
their words, all or nothing, client IDs (no duplicates, even after a delete), skipped rows, the size, row, rate and day limits,
ownership and isolation, the audit row, the export and the account deletion, and "Delete what it sent" for every kind. The
schema step is in ``tests/test_migration_m037.py``.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

import pytest

from app import app_sync
from app.auth import api_tokens
from app.foods import WEIGHT_UNKNOWN_DETAIL, Provenance, insert_food
from app.models import validate_gtin
from conftest import DAY, USER_PASSWORD, TestClient, find_food
from test_api_tokens import audit_rows, db, make, switch
from test_push import bare, make_device, push, push_switch

SYNC = "/push/v1/sync"
GENERIC = {"detail": api_tokens.DEVICE_DENIED}
NOTHING = {"foods": 0, "entries": 0, "labs": 0, "symptoms": 0, "weights": 0, "readings": 0}


def cid() -> str:
    return str(uuid.uuid4())


def make_app(client: TestClient, name: str = "My iPhone", **extra: Any) -> dict[str, Any]:
    r = client.post("/api/me/tokens", json={"name": name, "family": "device", "kind": "app", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def sync(app: Any, token: str | None, body: Any = None, *, raw: bytes | None = None, content_type: str | None = "application/json",
         headers: dict[str, str] | None = None) -> Any:
    h = dict(headers or {})
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if content_type is not None:
        h["Content-Type"] = content_type
    content = raw if raw is not None else json.dumps(body).encode("utf-8")
    return bare(app).post(SYNC, content=content, headers=h)


def ok(app: Any, token: str, body: Any) -> dict[str, Any]:
    r = sync(app, token, body)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    out = r.json()
    assert set(out) == {"added", "already_there", "skipped"}  # counts only
    return out


def counts(**added: int) -> dict[str, int]:
    return {**NOTHING, "meals": 0, **added}


def own_food(client_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"client_id": client_id or cid(), "name": "Grandma's rice pudding", "serving_desc": "1 bowl", "serving_g": 150,
            "nutrients": {"calories_kcal": 210, "potassium_mg": 180, "phosphorus_mg": 120}, **extra}


def entry(food: dict[str, Any], client_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"client_id": client_id or cid(), "date": DAY, "meal": "lunch", "food": food, **extra}


def lab(client_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"client_id": client_id or cid(), "analyte": "potassium", "value": 5.1, "unit": "mmol/L", "taken_on": DAY, **extra}


def symptom(client_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"client_id": client_id or cid(), "date": DAY, "symptom": "itching", "severity": 2, **extra}


def weight(client_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"client_id": client_id or cid(), "date": DAY, "time": "07:15", "kg": 70.2, "context": "morning", **extra}


def reading(client_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"client_id": client_id or cid(), "date": DAY, "time": "07:20", "systolic": 122, "diastolic": 78, "context": "morning", **extra}


def log_rows(client: TestClient) -> list[dict[str, Any]]:
    r = client.get("/api/log", params={"date": DAY})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["entries"] if isinstance(body, dict) else body


def shared_food(client: TestClient, source: str, **kw: Any) -> int:
    conn = db(client)
    try:
        food_id = insert_food(conn, source=source, name=kw.get("name", "Shared oat drink"), serving_desc="1 cup", serving_g=kw.get("serving_g", 240),
                              nutrients={"calories_kcal": 120, "potassium_mg": 150}, fdc_id=kw.get("fdc_id"),
                              provenance=Provenance(gtin=validate_gtin(kw.get("gtin"))))
        conn.commit()
    finally:
        conn.close()
    return food_id


def receipts(client: TestClient) -> list[dict[str, Any]]:
    conn = db(client)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM app_sync_rows ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    push_switch(client, True)
    return client


@pytest.fixture
def app_token(admin: TestClient) -> str:
    return make_app(admin)["token"]


# --------------------------------------------------------------------------- the token


def test_an_app_token_is_a_device_token_with_app_add_and_a_shortcut_token_is_unchanged(admin):
    made = make_app(admin, "Kidney Health on my iPhone")
    assert made["token"].startswith("khd_") and made["scopes"] == ["body:write", "app:add"] and made["kind"] == "app"
    assert made["sent"] == NOTHING
    assert made["pair_url"] is None or made["pair_url"].startswith("kidneyhealth://pair?")
    shortcut = make_device(admin)
    assert shortcut["scopes"] == ["body:write"] and shortcut["kind"] == "shortcut"
    assert shortcut["sent"] == {"weights": 0, "readings": 0}
    listed = {t["id"]: t for t in admin.get("/api/me/tokens", params={"family": "device"}).json()["tokens"]}
    assert listed[made["id"]]["kind"] == "app" and listed[made["id"]]["sent"] == NOTHING
    assert listed[shortcut["id"]]["kind"] == "shortcut" and listed[shortcut["id"]]["sent"] == {"weights": 0, "readings": 0}
    assert admin.get("/api/me/tokens").json()["tokens"] == []  # not an assistant token
    created = audit_rows(admin, "api_token.created")
    assert created[-2]["details"]["kind"] == "app" and "kind" not in created[-1]["details"]


def test_the_kind_is_only_for_a_phone_token_and_only_shortcut_or_app(admin):
    switch(admin, True)
    r = admin.post("/api/me/tokens", json={"name": "x", "kind": "app"})
    assert r.status_code == 400 and r.json()["field"] == "kind"
    r = admin.post("/api/me/tokens", json={"name": "x", "family": "device", "kind": "admin"})
    assert r.status_code == 400
    r = admin.post("/api/me/tokens", json={"name": "x", "family": "device", "kind": "app", "can_log": True})
    assert r.status_code == 400 and r.json()["field"] == "can_log"
    r = admin.post("/api/me/tokens", json={"name": "x", "family": "device", "scopes": ["app:add"]})
    assert r.status_code == 400  # scopes are never named
    assert make(admin)["scopes"] == ["assistant:read"]


def test_scopes_imply_only_what_they_say():
    assert api_tokens.parse_scopes("app:add") == ("body:write", "app:add")
    assert api_tokens.parse_scopes("body:write") == ("body:write",)
    assert api_tokens.parse_scopes("app:add assistant:read") == ()  # two families grant nothing
    assert api_tokens.family_of_scopes("app:add") == api_tokens.DEVICE
    assert api_tokens.kind_of_scopes("body:write app:add") == "app" and api_tokens.kind_of_scopes("body:write") == "shortcut"
    assert api_tokens.kind_of_scopes("assistant:read") is None


def test_where_each_token_works(admin, app_token):
    shortcut = make_device(admin)["token"]
    switch(admin, True)
    assistant = make(admin, can_log=True)["token"]
    body = {"weights": [weight()]}
    assert sync(admin.app, shortcut, body).status_code == 401 and sync(admin.app, shortcut, body).json() == GENERIC
    assert sync(admin.app, assistant, body).status_code == 401
    assert sync(admin.app, None, body).status_code == 401
    assert bare(admin.app).get(SYNC, headers={"Authorization": f"Bearer {shortcut}"}).status_code == 401
    check = bare(admin.app).get(SYNC, headers={"Authorization": f"Bearer {app_token}"})
    assert check.status_code == 200 and check.json() == {"ok": True}
    # An app token also sends Health readings to /push/v1/body and passes its check, like a shortcut token.
    r = push(admin.app, app_token, {"weights": [{"at": "2026-10-05T07:15:00-04:00", "value": 154.3, "unit": "lb", "source": "Health"}]})
    assert r.status_code == 200, r.text
    assert bare(admin.app).get("/push/v1/check", headers={"Authorization": f"Bearer {app_token}"}).status_code == 200
    mcp = bare(admin.app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": f"Bearer {app_token}"})
    assert mcp.status_code == 401
    # Every /api route ignores the header: the token reads nothing.
    for path in ("/api/log?date=" + DAY, "/api/labs", "/api/symptoms?start=" + DAY, "/api/body/weights", "/api/me/tokens?family=device", "/api/foods"):
        assert bare(admin.app).get(path, headers={"Authorization": f"Bearer {app_token}"}).status_code == 401, path


def test_a_cookie_is_never_enough_and_a_foreign_origin_is_403(admin, app_token):
    r = admin.post(SYNC, json={"weights": [weight()]})  # the signed-in browser session, with the app header
    assert r.status_code in (401, 403)
    r = sync(admin.app, app_token, {"weights": [weight()]}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert bare(admin.app).put(SYNC, headers={"Authorization": f"Bearer {app_token}"}).status_code == 405


def test_the_switch_turns_it_off_and_on(admin, app_token):
    push_switch(admin, False)
    assert sync(admin.app, app_token, {"weights": [weight()]}).json() == GENERIC
    assert bare(admin.app).get(SYNC, headers={"Authorization": f"Bearer {app_token}"}).status_code == 401
    push_switch(admin, True)
    assert ok(admin.app, app_token, {"weights": [weight()]})["added"] == counts(weights=1)


# --------------------------------------------------------------------------- the rows


def test_every_kind_is_added_once_as_the_owners_and_counted(admin, app_token):
    banana = find_food(admin, "banana")
    food = own_food()
    body = {
        "foods": [food],
        "entries": [entry({"client_id": food["client_id"]}, servings=2, note="after dialysis"),
                    entry({"builtin": {"fdc_id": banana["fdc_id"], "name": "Banana"}}, meal="breakfast", grams=59),
                    entry({"builtin": {"name": "Glucose tablets", "fdc_id": 1003}}, meal="snack")],
        "labs": [lab()],
        "symptoms": [symptom(), symptom(symptom="other", label="Restless legs", severity=1, note="at night")],
        "weights": [weight()],
        "readings": [reading(pulse=64)],
    }
    out = ok(admin.app, app_token, body)
    assert out == {"added": counts(foods=1, entries=3, labs=1, symptoms=2, weights=1, readings=1), "already_there": counts(),
                   "skipped": {"food_not_found": 0, "day_full": 0}}
    rows = {e["food_name"]: e for e in log_rows(admin)}
    assert rows["Grandma's rice pudding"]["servings"] == 2 and rows["Grandma's rice pudding"]["note"] == "after dialysis"
    assert rows["Grandma's rice pudding"]["nutrients"]["potassium_mg"] == 360  # recomputed from the food, never sent
    assert rows["Banana, raw"]["grams"] == 59 and rows["Banana, raw"]["meal"] == "breakfast"
    assert rows["Glucose tablets"]["purpose"] == "hypo"  # a low treatment keeps its automatic mark
    labs = admin.get("/api/labs").json()["labs"]
    assert [(x["analyte"], x["value"]) for x in labs] == [("potassium", 5.1)]
    assert len(admin.get("/api/symptoms", params={"start": DAY, "end": DAY}).json()["symptoms"]) == 2
    w = admin.get("/api/body/weights", params={"start": DAY, "end": DAY}).json()["weights"]
    assert w[0]["kg"] == 70.2 and w[0]["source"] == "shortcut" and w[0]["via"] == "My iPhone"
    bp = admin.get("/api/body/blood-pressure", params={"start": DAY, "end": DAY}).json()["readings"]
    assert bp[0]["pulse"] == 64 and bp[0]["via"] == "My iPhone"
    foods = admin.get("/api/foods", params={"q": "pudding"}).json()
    mine = foods["foods"] if isinstance(foods, dict) else foods
    assert [f["source"] for f in mine] == ["custom"]
    assert len(receipts(admin)) == 9 and all(r["added"] == 1 for r in receipts(admin))

    again = ok(admin.app, app_token, body)  # the same request again: nothing new
    assert again["added"] == counts()
    assert again["already_there"] == counts(foods=1, entries=3, labs=1, symptoms=2, weights=1, readings=1)
    assert len(log_rows(admin)) == 3 and len(receipts(admin)) == 9


def test_a_row_deleted_here_is_not_sent_back(admin, app_token):
    e = entry({"builtin": {"fdc_id": 173944, "name": "Banana, raw"}})
    ok(admin.app, app_token, {"entries": [e], "labs": [lab()]})
    entry_id = log_rows(admin)[0]["id"]
    assert admin.delete(f"/api/log/{entry_id}").status_code == 204
    out = ok(admin.app, app_token, {"entries": [e]})
    assert out["already_there"]["entries"] == 1 and out["added"] == counts() and log_rows(admin) == []


def test_a_food_is_found_again_by_its_client_id_in_a_later_request(admin, app_token):
    food = own_food()
    ok(admin.app, app_token, {"foods": [food]})
    out = ok(admin.app, app_token, {"entries": [entry({"client_id": food["client_id"]})]})
    assert out["added"] == counts(entries=1)
    assert log_rows(admin)[0]["food_name"] == food["name"]
    # A new app token of the same person finds it too (a replaced phone keeps its foods).
    second = make_app(admin, "New iPhone")["token"]
    assert ok(admin.app, second, {"entries": [entry({"client_id": food["client_id"]})]})["added"] == counts(entries=1)
    # The same food sent again changes nothing.
    assert ok(admin.app, second, {"foods": [food]})["already_there"] == counts(foods=1)


def test_an_identical_food_the_person_already_has_is_reused(admin, app_token):
    food = own_food()
    made = admin.post("/api/foods", json={k: v for k, v in food.items() if k != "client_id"})
    assert made.status_code == 201
    out = ok(admin.app, app_token, {"foods": [food], "entries": [entry({"client_id": food["client_id"]})]})
    assert out["already_there"]["foods"] == 1 and out["added"] == counts(entries=1)
    assert log_rows(admin)[0]["food_id"] == made.json()["id"]
    assert [r["added"] for r in receipts(admin) if r["kind"] == "food"] == [0]


def test_a_food_deleted_here_is_made_again_when_an_entry_needs_it(admin, app_token):
    food = own_food()
    ok(admin.app, app_token, {"foods": [food]})
    food_id = receipts(admin)[0]["row_id"]
    assert admin.delete(f"/api/foods/{food_id}").status_code == 204
    out = ok(admin.app, app_token, {"foods": [food], "entries": [entry({"client_id": food["client_id"]})]})
    assert out["added"] == counts(foods=1, entries=1)
    assert log_rows(admin)[0]["food_id"] != food_id
    assert len([r for r in receipts(admin) if r["kind"] == "food"]) == 1


def test_usda_and_open_food_facts_foods_link_the_shared_row_or_are_kept_as_your_own(admin, app_token):
    shared_usda = shared_food(admin, "usda", fdc_id=2_000_001, name="Oat drink, unsweetened")
    shared_off = shared_food(admin, "off", gtin="5000112637922", name="Fizzy drink")
    usda_here = own_food(source="usda", fdc_id=2_000_001, name="Oat drink, unsweetened", serving_g=240)
    usda_missing = own_food(source="usda", fdc_id=2_000_002, name="Rice drink", source_license="CC0-1.0",
                            source_url="https://fdc.nal.usda.gov/")
    off_here = own_food(source="off", gtin="5000112637922", name="Fizzy drink", serving_g=240)
    off_missing = own_food(source="off", gtin="4006381333931", name="Crackers")
    body = {"foods": [usda_here, usda_missing, off_here, off_missing],
            "entries": [entry({"client_id": f["client_id"]}) for f in (usda_here, usda_missing, off_here, off_missing)]}
    out = ok(admin.app, app_token, body)
    assert out["added"] == counts(foods=4, entries=4)
    by_name = {e["food_name"]: e["food_id"] for e in log_rows(admin)}
    assert by_name["Oat drink, unsweetened"] == shared_usda and by_name["Fizzy drink"] == shared_off
    conn = db(admin)
    try:
        kept = {r["name"]: dict(r) for r in conn.execute("SELECT name, source, fdc_id, gtin, owner_user_id, source_license FROM foods "
                                                         "WHERE name IN ('Rice drink', 'Crackers')")}
        links = {r[0] for r in conn.execute("SELECT food_id FROM user_food_links WHERE user_id = 1")}
        shared_count = conn.execute("SELECT COUNT(*) FROM foods WHERE owner_user_id IS NULL AND source IN ('usda', 'off')").fetchone()[0]
    finally:
        conn.close()
    assert kept["Rice drink"]["source"] == "custom" and kept["Rice drink"]["fdc_id"] == 2_000_002
    assert kept["Rice drink"]["source_license"] == "CC0-1.0" and kept["Crackers"]["gtin"] == "04006381333931"
    assert {shared_usda, shared_off} <= links and shared_count == 2  # a shared row is never made from the phone
    # A receipt for a linked shared food never lets "Delete what it sent" touch the shared row.
    assert {r["row_id"]: r["added"] for r in receipts(admin) if r["kind"] == "food"}[shared_usda] == 0


def test_an_entry_may_name_a_shared_food_directly_by_fdc_id_or_barcode(admin, app_token):
    usda = shared_food(admin, "usda", fdc_id=2_000_003, name="Lentils, boiled", serving_g=198)
    off = shared_food(admin, "off", gtin="5000112637922", name="Fizzy drink")
    out = ok(admin.app, app_token, {"entries": [
        entry({"usda": {"fdc_id": 2_000_003, "name": "Wrong name"}}),  # neither the name nor a weight agrees: not the same food
        entry({"usda": {"fdc_id": 2_000_003, "name": "Something else", "serving_g": 198}}),  # the serving weight agrees
        entry({"usda": {"fdc_id": 2_000_003, "name": "lentils, boiled"}}),
        entry({"off": {"gtin": "5000112637922", "name": "Fizzy drink"}}),
        entry({"usda": {"fdc_id": 9_999_999, "name": "Not here"}}),
        entry({"off": {"gtin": "4006381333931", "name": "Not here"}}),
    ]})
    assert out["added"] == counts(entries=3) and out["skipped"] == {"food_not_found": 3, "day_full": 0}
    assert sorted(e["food_id"] for e in log_rows(admin)) == sorted([usda, usda, off])
    assert receipts(admin) and all(r["kind"] == "entry" for r in receipts(admin)) and len(receipts(admin)) == 3
    # Once the food is in the person's list, its fdc_id alone finds it (as the assistant's log_food does).
    assert ok(admin.app, app_token, {"entries": [entry({"usda": {"fdc_id": 2_000_003, "name": "Lentils"}})]})["added"] == counts(entries=1)


def test_a_usda_id_of_a_built_in_food_is_the_built_in_food_and_needs_no_link(admin, app_token):
    banana = find_food(admin, "banana")
    as_food = own_food(source="usda", fdc_id=banana["fdc_id"], name="Bananas, raw", serving_g=118)
    out = ok(admin.app, app_token, {"foods": [as_food], "entries": [entry({"client_id": as_food["client_id"]}),
                                                                    entry({"usda": {"fdc_id": banana["fdc_id"], "name": "Banana"}})]})
    assert out["added"] == counts(entries=2) and out["already_there"] == counts(foods=1)
    assert [e["food_id"] for e in log_rows(admin)] == [banana["id"], banana["id"]]
    conn = db(admin)
    try:
        assert conn.execute("SELECT COUNT(*) FROM user_food_links").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM foods WHERE owner_user_id IS NOT NULL").fetchone()[0] == 0
    finally:
        conn.close()


def test_food_that_cannot_be_found_is_skipped_and_tried_again_next_time(admin, app_token):
    lost = entry({"client_id": cid()})
    unknown_builtin = entry({"builtin": {"fdc_id": 424242, "name": "Not in this list"}})
    by_name = entry({"builtin": {"name": "No such food"}})
    out = ok(admin.app, app_token, {"entries": [lost, unknown_builtin, by_name], "labs": [lab()]})
    assert out["added"] == counts(labs=1) and out["skipped"] == {"food_not_found": 3, "day_full": 0}
    assert [r["kind"] for r in receipts(admin)] == ["lab"]  # no receipt: sending again tries again
    food = own_food(lost["food"]["client_id"])
    out = ok(admin.app, app_token, {"foods": [food], "entries": [lost]})
    assert out["added"] == counts(foods=1, entries=1)


def test_a_full_day_is_skipped_not_refused(admin, app_token):
    for _ in range(30):
        assert admin.post("/api/symptoms", json={"date": DAY, "symptom": "nausea", "severity": 1}).status_code == 201
    for i in range(20):
        assert admin.post("/api/body/weights", json={"date": DAY, "time": f"0{i % 10}:{i:02d}", "kg": 70, "context": "other"}).status_code == 201
    out = ok(admin.app, app_token, {"symptoms": [symptom()], "weights": [weight()], "readings": [reading()]})
    assert out["added"] == counts(readings=1) and out["skipped"] == {"food_not_found": 0, "day_full": 2}


def test_the_same_reading_from_health_is_not_added_twice(admin, app_token):
    key = "a" * 32
    conn = db(admin)
    try:
        conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at) "
                     "VALUES (1, ?, '06:00', 71.5, 'morning', '', 'apple_health', ?, '2026-10-05T10:00:00.000000Z', '2026-10-05T10:00:00.000000Z')",
                     (DAY, key))
        conn.commit()
    finally:
        conn.close()
    out = ok(admin.app, app_token, {"weights": [weight(source_key=key, time="06:00", kg=71.5),
                                                weight(time="06:00", kg=71.5)],  # the same moment and kilograms
                                    "readings": [reading(), reading(time="07:20")]})
    assert out["added"] == counts(readings=1) and out["already_there"] == counts(weights=2, readings=1)


def test_created_at_finds_a_row_that_came_by_file(admin, app_token):
    banana = find_food(admin, "banana")
    stamp = "2026-10-05T12:30:00.123456Z"
    first = entry({"builtin": {"fdc_id": banana["fdc_id"], "name": "Banana, raw"}}, created_at=stamp)
    ok(admin.app, app_token, {"entries": [first], "labs": [lab(created_at=stamp)], "symptoms": [symptom(created_at=stamp)]})
    # The same rows under new client IDs (an export imported here, then the phone sends them): found by their content and time.
    copy = {**first, "client_id": cid()}
    out = ok(admin.app, app_token, {"entries": [copy], "labs": [lab(created_at=stamp)], "symptoms": [symptom(created_at=stamp)]})
    assert out["added"] == counts() and out["already_there"] == counts(entries=1, labs=1, symptoms=1)
    assert log_rows(admin)[0]["created_at"] == stamp


# --------------------------------------------------------------------------- the checks


@pytest.mark.parametrize("body, where", [
    ({"entries": [entry({"builtin": {"name": "Banana, raw"}}, date="2026-13-01")]}, "entries.0.date"),
    ({"entries": [entry({"builtin": {"name": "Banana, raw"}}, servings=0)]}, "entries.0.servings"),
    ({"entries": [entry({"builtin": {"name": "Banana, raw"}}, meal="brunch")]}, "entries.0.meal"),
    ({"entries": [entry({"builtin": {"name": "Banana, raw"}}, food_id=3)]}, "entries.0.food_id"),
    ({"entries": [entry({"builtin": {"name": "Banana, raw"}, "client_id": cid()})]}, "entries.0.food"),
    ({"entries": [entry({})]}, "entries.0.food"),
    ({"entries": [entry({"builtin": {"name": "Banana, raw"}}, client_id="not-a-uuid")]}, "entries.0.client_id"),
    ({"entries": [entry({"builtin": {"name": "Banana, raw"}}, created_at="yesterday")]}, "entries.0.created_at"),
    ({"foods": [own_food(serving_g=0)]}, "foods.0.serving_g"),
    ({"foods": [own_food(nutrients={"potassium_mg": -1})]}, "foods.0.nutrients"),
    ({"foods": [own_food(source="usda")]}, "foods.0"),
    ({"foods": [own_food(source="off")]}, "foods.0"),
    ({"foods": [own_food(source="builtin")]}, "foods.0.source"),
    ({"foods": [own_food(source_url="https://evil.example/")]}, "foods.0.source_url"),
    ({"labs": [lab(unit="furlongs")]}, "labs.0"),
    ({"labs": [lab(taken_on="2999-01-01")]}, "labs.0.taken_on"),
    ({"symptoms": [symptom(label="not other")]}, "symptoms.0"),
    ({"symptoms": [symptom(severity=4)]}, "symptoms.0.severity"),
    ({"weights": [weight(kg=5)]}, "weights.0.kg"),
    ({"weights": [weight(time="25:00")]}, "weights.0.time"),
    ({"readings": [reading(systolic=70, diastolic=80)]}, "readings.0"),
    ({"readings": [reading(glucose=5.5)]}, "readings.0.glucose"),
    ({"insulin": [{"units": 4}]}, "insulin"),
])
def test_every_row_is_checked_like_its_create_route_and_nothing_is_stored(admin, app_token, body, where):
    if "labs" not in body:
        body = {**body, "labs": [lab()]}  # a good row next to the bad one: it is not stored either
    r = sync(admin.app, app_token, body)
    assert r.status_code == 400, r.text
    assert r.json()["field"] == where and r.json()["detail"].startswith(where)
    assert receipts(admin) == [] and admin.get("/api/labs").json()["labs"] == []


def test_the_words_are_the_create_routes_words(admin, app_token):
    r = admin.post("/api/labs", json={"analyte": "potassium", "value": 5.1, "unit": "furlongs", "taken_on": DAY})
    assert r.status_code == 400
    assert sync(admin.app, app_token, {"labs": [lab(unit="furlongs")]}).json()["detail"] == "labs.0: " + r.json()["detail"]
    r = admin.post("/api/body/weights", json={"date": DAY, "kg": 5, "context": "morning"})
    assert r.status_code == 400 and r.json()["detail"].startswith("kg: ")
    assert sync(admin.app, app_token, {"weights": [weight(kg=5)]}).json()["detail"] == "weights.0." + r.json()["detail"]
    r = admin.post("/api/symptoms", json={"date": DAY, "symptom": "itching", "severity": 1, "label": "x"})
    assert sync(admin.app, app_token, {"symptoms": [symptom(severity=1, label="x")]}).json()["detail"] == "symptoms.0: " + r.json()["detail"]


def test_grams_for_a_food_with_an_unknown_weight_is_the_log_routes_400(admin, app_token):
    conn = db(admin)
    try:
        insert_food(conn, source="off", name="Macaroni and cheese", serving_desc="1 cup", serving_g=70.9,
                    nutrients={"carbs_g": 47}, provenance=Provenance(gtin="05000112637922", quality=("prepared_values",)))
        conn.commit()
    finally:
        conn.close()
    ref = {"off": {"gtin": "5000112637922", "name": "Macaroni and cheese"}}
    r = sync(admin.app, app_token, {"labs": [lab()], "entries": [entry(ref), entry(ref, grams=198)]})
    assert r.status_code == 400 and r.json()["field"] == "entries.1.grams"
    assert r.json()["detail"] == "entries.1." + WEIGHT_UNKNOWN_DETAIL
    assert receipts(admin) == [] and log_rows(admin) == [] and admin.get("/api/labs").json()["labs"] == []


def test_the_request_shape(admin, app_token):
    app = admin.app
    assert sync(app, app_token, raw=b"not json").json()["detail"] == "The body is not valid JSON."
    assert sync(app, app_token, raw=b'{"weights": [{"kg": NaN}]}').status_code == 400
    assert sync(app, app_token, []).status_code == 400
    assert sync(app, app_token, {}).json()["detail"] == "Send at least one row."
    assert sync(app, app_token, {"weights": [weight()]}, content_type="text/plain").status_code == 415
    same = cid()
    r = sync(app, app_token, {"labs": [lab(same), lab(same)]})
    assert r.status_code == 400 and r.json()["field"] == "labs.1.client_id"
    # The same client ID in two different lists is fine: each kind has its own.
    assert ok(app, app_token, {"labs": [lab(same)], "symptoms": [symptom(same)]})["added"] == counts(labs=1, symptoms=1)
    too_many = {"labs": [lab() for _ in range(app_sync.MAX_ROWS + 1)]}
    r = sync(app, app_token, too_many)
    assert r.status_code == 400 and "at most 200" in r.json()["detail"]
    big = {"foods": [own_food(ingredients_text="x" * 3900) for _ in range(70)]}
    assert sync(app, app_token, big).status_code == 413


def test_sixty_requests_an_hour_for_each_token(admin, app_token):
    other = make_app(admin, "Second")["token"]
    for _ in range(60):
        assert bare(admin.app).get(SYNC, headers={"Authorization": f"Bearer {app_token}"}).status_code == 200
    r = sync(admin.app, app_token, {"labs": [lab()]})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert ok(admin.app, other, {"labs": [lab()]})["added"] == counts(labs=1)


def test_a_days_cap_for_each_token_rolls_the_request_back(admin, app_token, monkeypatch):
    monkeypatch.setattr(app_sync, "MAX_PER_DAY", 3)
    assert ok(admin.app, app_token, {"labs": [lab(), lab()]})["added"] == counts(labs=2)
    r = sync(admin.app, app_token, {"labs": [lab(), lab()]})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 3600
    assert len(admin.get("/api/labs").json()["labs"]) == 2 and len(receipts(admin)) == 2
    # Rows the server already has count for nothing.
    first = receipts(admin)[0]["client_id"]
    assert ok(admin.app, app_token, {"labs": [lab(first)]})["already_there"] == counts(labs=1)


def test_access_that_ends_while_sending_stores_nothing(admin, app_token, monkeypatch):
    real = app_sync.read_body

    def revoke_then_read(raw):
        conn = db(admin)
        conn.execute("UPDATE api_tokens SET revoked_at = '2026-01-01T00:00:00.000000Z'")
        conn.commit()
        conn.close()
        return real(raw)

    monkeypatch.setattr(app_sync, "read_body", revoke_then_read)
    r = sync(admin.app, app_token, {"labs": [lab()], "weights": [weight()]})
    assert r.status_code == 401 and r.json() == GENERIC
    assert receipts(admin) == [] and admin.get("/api/labs").json()["labs"] == []


def test_the_answer_and_the_log_line_hold_no_values(admin, app_token, caplog):
    caplog.set_level("INFO")
    out = ok(admin.app, app_token, {"foods": [own_food()], "labs": [lab(note="secret note 98765")]})
    text = json.dumps(out) + caplog.text
    assert "98765" not in text and "pudding" not in text and "5.1" not in text


def test_the_activity_list_says_what_the_app_added(admin, app_token):
    ok(admin.app, app_token, {"labs": [lab()], "weights": [weight()]})
    ok(admin.app, app_token, {"labs": [lab(receipts(admin)[0]["client_id"])]})  # nothing new: no row
    rows = audit_rows(admin, "app.rows_added")
    assert len(rows) == 1 and rows[0]["target_type"] == "api_token"
    assert rows[0]["details"] == {"via": "My iPhone", **counts(labs=1, weights=1)}
    actions = [e["action"] for e in admin.get("/api/me/activity").json()["events"]]
    assert "app.rows_added" in actions


# --------------------------------------------------------------------------- isolation, export, deletion


def test_another_persons_rows_and_client_ids_never_mix(two_clients):
    a, b = two_clients
    push_switch(a, True)
    ta, tb = make_app(a)["token"], make_app(b, "Sam's phone")["token"]
    food = own_food()
    shared_id = cid()
    ok(a.app, ta, {"foods": [food], "entries": [entry({"client_id": food["client_id"]})], "labs": [lab(shared_id)]})
    # B's phone using A's food client ID finds nothing of A's; the same lab client ID is B's own.
    out = ok(b.app, tb, {"entries": [entry({"client_id": food["client_id"]})], "labs": [lab(shared_id)]})
    assert out["added"] == counts(labs=1) and out["skipped"]["food_not_found"] == 1
    assert len(a.get("/api/labs").json()["labs"]) == 1 and len(b.get("/api/labs").json()["labs"]) == 1
    assert log_rows(b) == [] and len(log_rows(a)) == 1
    # B's own food with A's food's client ID is B's.
    out = ok(b.app, tb, {"foods": [own_food(food["client_id"], name="Sam's soup")], "entries": [entry({"client_id": food["client_id"]})]})
    assert out["added"] == counts(foods=1, entries=1) and log_rows(b)[0]["food_name"] == "Sam's soup"
    assert log_rows(a)[0]["food_name"] == food["name"]
    # Tokens and "Delete what it sent" are per person: another person's token id is 404.
    a_id = a.get("/api/me/tokens", params={"family": "device"}).json()["tokens"][0]["id"]
    assert b.delete(f"/api/me/tokens/{a_id}/body-rows").status_code == 404
    assert len(log_rows(a)) == 1
    conn = db(a)
    try:
        owners = {(r["user_id"], r["api_token_id"]) for r in conn.execute("SELECT user_id, api_token_id FROM app_sync_rows")}
    finally:
        conn.close()
    ids = {t["id"] for t in b.get("/api/me/tokens", params={"family": "device"}).json()["tokens"]}
    assert all((uid == 1) == (tid == a_id) for uid, tid in owners) and any(tid in ids for _, tid in owners)


def test_deleting_the_account_deletes_its_receipts_and_only_its_own(two_clients):
    a, b = two_clients
    push_switch(a, True)
    ok(a.app, make_app(a)["token"], {"labs": [lab()]})
    ok(b.app, make_app(b)["token"], {"labs": [lab()], "weights": [weight()]})
    sam = b.get("/api/me").json()["id"]
    r = b.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"})
    assert r.status_code in (200, 204), r.text
    assert [r["user_id"] for r in receipts(a)] == [1] and sam != 1


def test_the_export_holds_the_rows_but_not_the_receipts_and_imports_elsewhere(admin, app_token, tmp_path, foods_json):
    food = own_food()
    ok(admin.app, app_token, {"foods": [food], "entries": [entry({"client_id": food["client_id"]})], "labs": [lab()],
                              "weights": [weight()]})
    data = admin.get("/api/me/export.json")
    if data.status_code != 200:
        import io
        import zipfile
        zipped = admin.get("/api/me/export.zip")
        assert zipped.status_code == 200, zipped.text
        doc = json.loads(zipfile.ZipFile(io.BytesIO(zipped.content)).read("export.json"))
    else:
        doc = data.json()
    assert "app_sync_rows" not in doc and "receipts" not in json.dumps(sorted(doc))
    assert [e["food_name"] for e in doc["log_entries"]] == [food["name"]]
    assert doc["weights"][0]["source"] == "shortcut" and "api_token_id" not in doc["weights"][0]
    from conftest import make_settings
    from app.main import create_app
    with TestClient(create_app(make_settings(tmp_path / "other", foods_json))) as other:
        from conftest import sign_in
        sign_in(other)
        r = other.post("/api/me/import", content=json.dumps(doc), headers={"Content-Type": "application/json"})
        assert r.status_code == 200, r.text
        assert r.json()["counts"]["log_entries"] == 1 and r.json()["counts"]["lab_results"] == 1


# --------------------------------------------------------------------------- "Delete what it sent"


def test_delete_what_it_sent_removes_every_kind_the_token_added_and_nothing_else(admin, app_token):
    banana = find_food(admin, "banana")
    used = own_food(name="Soup I also log by hand")
    unused = own_food(name="Pudding only the phone used")
    key = "b" * 32
    conn = db(admin)
    try:  # a weight from the Health app that the phone sends too: found already here, so never the token's to delete
        conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at) "
                     "VALUES (1, ?, '06:00', 71.5, 'morning', '', 'apple_health', ?, '2026-10-05T10:00:00.000000Z', "
                     "'2026-10-05T10:00:00.000000Z')", (DAY, key))
        conn.commit()
    finally:
        conn.close()
    sent_symptom = symptom()
    ok(admin.app, app_token, {
        "foods": [used, unused],
        "entries": [entry({"client_id": used["client_id"]}), entry({"client_id": unused["client_id"]}),
                    entry({"builtin": {"fdc_id": banana["fdc_id"], "name": "Banana, raw"}})],
        "labs": [lab()], "symptoms": [sent_symptom], "weights": [weight(), weight(time="06:00", kg=71.5, source_key=key)],
        "readings": [reading()],
    })
    soup_id = next(r["row_id"] for r in receipts(admin) if r["kind"] == "food" and r["added"] == 1)
    mine = admin.post("/api/log", json={"date": DAY, "meal": "dinner", "food_id": soup_id})  # the person's own entry with it
    assert mine.status_code == 201
    typed = admin.post("/api/labs", json={"analyte": "phosphate", "value": 1.4, "unit": "mmol/L", "taken_on": DAY})
    assert typed.status_code == 201
    token = next(t for t in admin.get("/api/me/tokens", params={"family": "device"}).json()["tokens"] if t["kind"] == "app")
    assert token["sent"] == {"entries": 3, "foods": 2, "labs": 1, "symptoms": 1, "weights": 1, "readings": 1}

    r = admin.delete(f"/api/me/tokens/{token['id']}/body-rows")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": {"weights": 1, "readings": 1, "entries": 3, "labs": 1, "symptoms": 1, "foods": 1}}
    assert [e["id"] for e in log_rows(admin)] == [mine.json()["id"]]  # the person's own entry, with its food
    assert [x["analyte"] for x in admin.get("/api/labs").json()["labs"]] == ["phosphate"]
    assert admin.get("/api/symptoms", params={"start": DAY, "end": DAY}).json()["symptoms"] == []
    assert [w["source"] for w in admin.get("/api/body/weights", params={"start": DAY, "end": DAY}).json()["weights"]] == ["apple_health"]
    assert admin.get(f"/api/foods/{soup_id}").status_code == 200
    token = next(t for t in admin.get("/api/me/tokens", params={"family": "device"}).json()["tokens"] if t["kind"] == "app")
    assert token["sent"] == {"entries": 0, "foods": 1, "labs": 0, "symptoms": 0, "weights": 0, "readings": 0}
    deleted = audit_rows(admin, "body.token_rows_deleted")[-1]["details"]
    assert deleted == {"weights": 1, "readings": 1, "entries": 3, "labs": 1, "symptoms": 1, "foods": 1}
    # The phone sending the same rows again adds nothing back.
    assert ok(admin.app, app_token, {"symptoms": [sent_symptom]})["added"] == counts()


def test_delete_what_it_sent_works_after_revoking_and_a_shortcut_tokens_answer_is_unchanged(admin, app_token):
    ok(admin.app, app_token, {"labs": [lab()]})
    token_id = next(t["id"] for t in admin.get("/api/me/tokens", params={"family": "device"}).json()["tokens"])
    assert admin.delete(f"/api/me/tokens/{token_id}").status_code == 204
    r = admin.delete(f"/api/me/tokens/{token_id}/body-rows")
    assert r.status_code == 200 and r.json()["deleted"]["labs"] == 1
    shortcut = make_device(admin)
    r = admin.delete(f"/api/me/tokens/{shortcut['id']}/body-rows")
    assert r.json() == {"deleted": {"weights": 0, "readings": 0}}


def test_a_purged_token_keeps_the_receipts_so_a_late_resend_adds_nothing(admin, app_token):
    l1 = lab()
    ok(admin.app, app_token, {"labs": [l1]})
    conn = db(admin)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM api_tokens")
        conn.commit()
        row = conn.execute("SELECT api_token_id, added FROM app_sync_rows").fetchone()
    finally:
        conn.close()
    assert row["api_token_id"] is None and row["added"] == 1
    other = make_app(admin, "New")["token"]
    assert ok(admin.app, other, {"labs": [l1]})["already_there"] == counts(labs=1)


def test_a_receipt_needs_its_person():
    from app import db as app_db
    conn = app_db.connect(":memory:")
    app_db.migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO app_sync_rows (user_id, kind, client_id, row_id, added, created_at) VALUES (999, 'entry', ?, 1, 1, 'x')",
                     (cid(),))
    conn.close()
