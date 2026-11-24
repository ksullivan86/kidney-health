"""The change feed (design note 39 §8, plan step 5; ``app/sync_feed.py``): ``GET`` and ``POST /push/v1/changes`` and
``POST /push/v1/match``.

Covered: only a token with ``app:sync`` (old app tokens, cookies, the switch), the feed's shape (export rows with ``client_id``, the
version, the foods an entry uses), the latest state only, paging with the cursor, deletes as tombstones, tombstones purged after 180
days and ``410`` for an older cursor, every writer recorded (the web app, the import, step 4's sync), the per-row writes with note 02's
rule (done, conflict, gone, refused; the same edit on both sides is no conflict; one conflict does not stop the others; a low treatment
is like any entry), match with step 4's receipts, isolation between people, limits, and account deletion."""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app import row_versions as RV
from app import sync_feed
from conftest import DAY, TestClient, add_user, find_food
from test_api_tokens import db
from test_app_gateway import make_sync, switches
from test_push import bare

FEED = "/push/v1/changes"
MATCH = "/push/v1/match"


def cid() -> str:
    return str(uuid.uuid4())


def get(app: Any, token: str, **params: Any) -> Any:
    return bare(app).get(FEED, params=params, headers={"Authorization": f"Bearer {token}"})


def everything(app: Any, token: str, after: str = "0", limit: int = 500) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    foods: dict[str, Any] = {}
    while True:
        r = get(app, token, after=after, limit=limit)
        assert r.status_code == 200, r.text
        page = r.json()
        changes += page["changes"]
        for f in page["foods"]:
            foods[json.dumps(f["ref"], sort_keys=True)] = f["food"]
        after = page["next"]
        if not page["more"]:
            return changes, after, foods


def post(app: Any, token: str, path: str, body: Any) -> Any:
    return bare(app).post(path, content=json.dumps(body), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})


def send(app: Any, token: str, *changes: dict[str, Any]) -> list[dict[str, Any]]:
    r = post(app, token, FEED, {"changes": list(changes)})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()["results"]


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    switches(client)
    return client


@pytest.fixture
def token(admin: TestClient) -> str:
    return make_sync(admin)["token"]


def _log(client: TestClient, query: str = "banana", **extra: Any) -> dict[str, Any]:
    food = find_food(client, query)
    r = client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"], **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


# --------------------------------------------------------------------------- who may read it


def test_only_a_token_with_app_sync_reads_or_writes(admin, token):
    old = admin.post("/api/me/tokens", json={"name": "old", "family": "device", "kind": "app"}).json()["token"]
    for path, method in ((FEED, "GET"), (FEED, "POST"), (MATCH, "POST")):
        body = {"ids": {"entry": []}} if path == MATCH else {"changes": [{"kind": "lab", "id": cid(), "op": "delete", "base": "0" * 16}]}
        assert bare(admin.app).request(method, path, json=body, headers={"Authorization": f"Bearer {old}"}).status_code == 401
        assert admin.request(method, path, json=body).status_code == 401  # a cookie is never read
        r = bare(admin.app).request(method, path, json=body, headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"})
        assert r.status_code == 403
    switches(admin, app_sync=False)
    assert get(admin.app, token).status_code == 401


def test_other_methods_are_405(admin, token):
    for method in ("PUT", "PATCH", "DELETE"):
        assert bare(admin.app).request(method, FEED).status_code == 405
    assert bare(admin.app).get(MATCH).status_code == 405


# --------------------------------------------------------------------------- the feed


def test_the_feed_has_every_row_in_the_export_shape_with_its_version(admin, token):
    entry = _log(admin)
    own = admin.post("/api/foods", json={"name": "Pudding", "serving_desc": "1 bowl", "serving_g": 150, "nutrients": {"potassium_mg": 180}}).json()
    mine = _log(admin, "pudding")
    lab = admin.post("/api/labs", json={"analyte": "potassium", "value": 5.1, "unit": "mmol/L", "taken_on": DAY}).json()
    admin.post("/api/symptoms", json={"date": DAY, "symptom": "itching", "severity": 2})
    admin.post("/api/body/weights", json={"date": DAY, "time": "07:15", "kg": 70.2, "context": "morning"})
    admin.post("/api/body/blood-pressure", json={"date": DAY, "time": "07:20", "systolic": 122, "diastolic": 78, "context": "morning"})
    apple = find_food(admin, "apple")
    admin.post("/api/meals", json={"name": "Usual", "items": [{"food_id": apple["id"], "servings": 1}]})
    changes, nxt, foods = everything(admin.app, token)
    assert sorted(c["kind"] for c in changes) == ["entry", "entry", "food", "lab", "meal", "reading", "symptom", "weight"]
    for c in changes:
        assert c["op"] == "put" and c["id"] == c["row"]["client_id"] and len(c["id"]) == 36
        assert c["version"] == RV.row_version(c["kind"], c["row"])
    by_kind = {c["kind"]: c for c in changes}
    assert by_kind["lab"]["row"]["id"] == lab["id"] and by_kind["lab"]["row"]["unit"] == "mmol/L"
    entries = {c["row"]["id"]: c for c in changes if c["kind"] == "entry"}
    assert entries[entry["id"]]["version"] == entry["version"]  # the entry's version is note 02's, as the API shows it
    assert entries[entry["id"]]["row"]["food"] == {"builtin": {"fdc_id": 173944, "name": "Banana, raw"}}
    assert entries[mine["id"]]["row"]["food"] == {"client_id": by_kind["food"]["id"]}
    assert json.dumps({"client_id": by_kind["food"]["id"]}, sort_keys=True) in foods and own["name"] == "Pudding"
    assert by_kind["meal"]["row"]["items"][0]["food"]["builtin"]["name"] == apple["name"]
    # nothing new: the same cursor
    page = get(admin.app, token, after=nxt).json()
    assert page == {"changes": [], "foods": [], "next": nxt, "more": False}


def test_only_the_latest_state_of_a_row_and_deletes_as_tombstones(admin, token):
    entry = _log(admin)
    _, start, _ = everything(admin.app, token)
    for servings in (2, 3):
        assert admin.put(f"/api/log/{entry['id']}", json={"servings": servings}).status_code == 200
    changes, nxt, _ = everything(admin.app, token, start)
    assert len(changes) == 1 and changes[0]["row"]["servings"] == 3
    assert admin.delete(f"/api/log/{entry['id']}").status_code == 204
    changes, _, _ = everything(admin.app, token, nxt)
    assert changes == [{"kind": "entry", "id": entry["client_id"], "op": "delete", "version": None}]
    all_changes, _, _ = everything(admin.app, token)  # from the start: the tombstone, not the row
    assert [c["op"] for c in all_changes if c["id"] == entry["client_id"]] == ["delete"]


def test_paging_follows_the_cursor(admin, token):
    for _ in range(5):
        _log(admin)
    first = get(admin.app, token, limit=2).json()
    assert len(first["changes"]) == 2 and first["more"] is True
    changes, _, _ = everything(admin.app, token, limit=2)
    assert len(changes) == 5 and len({c["id"] for c in changes}) == 5
    for bad in ("x", "-1", "1.5"):
        assert get(admin.app, token, after=bad).status_code == 400
    assert get(admin.app, token, limit=0).status_code == 400 and get(admin.app, token, limit=501).status_code == 400


def test_tombstones_older_than_180_days_are_purged_and_an_older_cursor_is_410(admin, token):
    gone = _log(admin)
    _, before, _ = everything(admin.app, token)
    admin.delete(f"/api/log/{gone['id']}")
    kept = _log(admin)
    conn = db(admin)
    try:
        conn.execute("UPDATE sync_changes SET at = '2026-01-01T00:00:00.000000Z' WHERE deleted = 1")
        conn.commit()
        assert sync_feed.purge_tombstones(conn) == 1
        assert conn.execute("SELECT COUNT(*) FROM sync_changes WHERE deleted = 1").fetchone()[0] == 0
    finally:
        conn.close()
    r = get(admin.app, token, after=before)
    assert r.status_code == 410 and r.json()["resync"] is True and r.headers["cache-control"] == "no-store"
    changes, _, _ = everything(admin.app, token)  # from the start it works, and the row that is still here is there
    assert kept["client_id"] in {c["id"] for c in changes} and gone["client_id"] not in {c["id"] for c in changes}


def test_every_writer_is_recorded(admin, token):
    """The import, the Care team's or the assistant's writes and step 4's sync all go through the triggers."""
    _, start, _ = everything(admin.app, token)
    phone = cid()
    r = bare(admin.app).post("/push/v1/sync", json={"labs": [{"client_id": phone, "analyte": "potassium", "value": 5, "unit": "mmol/L",
                                                              "taken_on": DAY}]}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["added"]["labs"] == 1
    changes, _, _ = everything(admin.app, token, start)
    assert [(c["kind"], c["id"]) for c in changes] == [("lab", phone)]  # the phone's ID is the server's now


# --------------------------------------------------------------------------- writes


def test_an_edit_on_the_version_it_was_made_on_is_done(admin, token):
    entry = _log(admin)
    [r] = send(admin.app, token, {"kind": "entry", "id": entry["client_id"], "op": "edit", "base": entry["version"], "fields": {"servings": 2}})
    stored = admin.get("/api/log", params={"date": DAY}).json()["entries"][0]
    assert r == {"kind": "entry", "id": entry["client_id"], "status": "done", "version": stored["version"]}
    assert stored["servings"] == 2


def test_a_stale_base_is_a_conflict_and_nothing_changes(admin, token):
    entry = _log(admin)
    assert admin.put(f"/api/log/{entry['id']}", json={"note": "changed on the web"}).status_code == 200
    stored = admin.get("/api/log", params={"date": DAY}).json()["entries"][0]
    [r] = send(admin.app, token, {"kind": "entry", "id": entry["client_id"], "op": "edit", "base": entry["version"], "fields": {"servings": 4}})
    assert r["status"] == "conflict" and r["version"] == stored["version"] and r["row"]["note"] == "changed on the web"
    assert admin.get("/api/log", params={"date": DAY}).json()["entries"][0]["servings"] == 1
    [r] = send(admin.app, token, {"kind": "entry", "id": entry["client_id"], "op": "delete", "base": entry["version"]})
    assert r["status"] == "conflict"  # a delete of a row changed elsewhere is a conflict too
    # "Use mine": sent again on the version now, it is done
    [r] = send(admin.app, token, {"kind": "entry", "id": entry["client_id"], "op": "edit", "base": stored["version"], "fields": {"servings": 4}})
    assert r["status"] == "done"


def test_the_same_edit_on_both_sides_is_no_conflict(admin, token):
    entry = _log(admin)
    assert admin.put(f"/api/log/{entry['id']}", json={"servings": 2}).status_code == 200
    now = admin.get("/api/log", params={"date": DAY}).json()["entries"][0]["version"]
    [r] = send(admin.app, token, {"kind": "entry", "id": entry["client_id"], "op": "edit", "base": entry["version"], "fields": {"servings": 2},
                                  "version": now})
    assert r["status"] == "done" and r["version"] == now


def test_gone_refused_and_one_answer_never_stops_the_others(admin, token):
    entry = _log(admin)
    lab = admin.post("/api/labs", json={"analyte": "potassium", "value": 5.1, "unit": "mmol/L", "taken_on": DAY}).json()
    changes, _, _ = everything(admin.app, token)
    lab_change = next(c for c in changes if c["kind"] == "lab")
    results = send(admin.app, token,
                   {"kind": "symptom", "id": cid(), "op": "delete", "base": "0" * 16},  # never here
                   {"kind": "lab", "id": lab_change["id"], "op": "edit", "base": lab_change["version"], "fields": {"note": "x"}},
                   {"kind": "entry", "id": entry["client_id"], "op": "edit", "base": entry["version"], "fields": {"servings": -1}},
                   {"kind": "lab", "id": lab_change["id"], "op": "delete", "base": lab_change["version"]})
    assert [r["status"] for r in results] == ["gone", "refused", "refused", "done"]
    assert results[1]["detail"] == "Lab results can only be added or deleted."
    assert admin.get("/api/labs").json()["labs"] == [] and lab["id"]


@pytest.mark.parametrize("kind,make,fields", [
    ("symptom", lambda c: c.post("/api/symptoms", json={"date": DAY, "symptom": "itching", "severity": 2}), {"date": DAY, "symptom": "itching", "severity": 3}),
    ("weight", lambda c: c.post("/api/body/weights", json={"date": DAY, "time": "07:15", "kg": 70.2, "context": "morning"}),
     {"date": DAY, "time": "07:15", "kg": 70.4, "context": "morning"}),
    ("reading", lambda c: c.post("/api/body/blood-pressure", json={"date": DAY, "systolic": 122, "diastolic": 78, "context": "morning"}),
     {"date": DAY, "systolic": 124, "diastolic": 78, "context": "morning"}),
    ("food", lambda c: c.post("/api/foods", json={"name": "Pudding", "serving_desc": "1 bowl", "serving_g": 150, "nutrients": {}}),
     {"name": "Rice pudding", "serving_desc": "1 bowl", "serving_g": 150, "nutrients": {}}),
])
def test_every_kind_is_edited_and_deleted_the_same_way(admin, token, kind, make, fields):
    assert make(admin).status_code == 201
    changes, _, _ = everything(admin.app, token)
    c = next(x for x in changes if x["kind"] == kind)
    [r] = send(admin.app, token, {"kind": kind, "id": c["id"], "op": "edit", "base": "0" * 16, "fields": fields})
    assert r["status"] == "conflict" and r["version"] == c["version"]
    [r] = send(admin.app, token, {"kind": kind, "id": c["id"], "op": "edit", "base": c["version"], "fields": fields})
    assert r["status"] == "done" and r["version"] != c["version"]
    [r2] = send(admin.app, token, {"kind": kind, "id": c["id"], "op": "delete", "base": r["version"]})
    assert r2 == {"kind": kind, "id": c["id"], "status": "done", "version": None}


def test_a_low_treatment_is_synced_like_any_entry(admin, token):
    entry = _log(admin, purpose="hypo")
    changes, _, _ = everything(admin.app, token)
    row = next(c for c in changes if c["kind"] == "entry")["row"]
    assert row["purpose"] == "hypo"
    [r] = send(admin.app, token, {"kind": "entry", "id": entry["client_id"], "op": "edit", "base": entry["version"], "fields": {"servings": 2}})
    assert r["status"] == "done"


def test_the_body_is_checked(admin, token):
    for body in ({"changes": []}, {"changes": [{"kind": "medicine", "id": cid(), "op": "delete", "base": "0" * 16}]},
                 {"changes": [{"kind": "lab", "id": "short", "op": "delete", "base": "0" * 16}]},
                 {"changes": [{"kind": "lab", "id": cid(), "op": "edit", "base": "0" * 16}]},
                 {"changes": [{"kind": "lab", "id": cid(), "op": "delete", "base": "XYZ"}]}, {"other": 1}):
        assert post(admin.app, token, FEED, body).status_code == 400, body
    r = bare(admin.app).post(FEED, content=b"{}", headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
    assert r.status_code == 415


# --------------------------------------------------------------------------- match


def test_match_names_this_servers_id_for_each_of_the_phones(admin, token):
    entry = _log(admin)
    added, found = cid(), cid()
    body = {"labs": [{"client_id": added, "analyte": "potassium", "value": 5, "unit": "mmol/L", "taken_on": DAY}],
            "symptoms": [{"client_id": found, "date": DAY, "symptom": "itching", "severity": 2, "created_at": "2026-10-05T08:00:00Z"}]}
    conn = db(admin)
    try:  # a symptom already here with the same content: the phone's is found, not added
        conn.execute("INSERT INTO symptoms (user_id, date, symptom, label, severity, note, created_at) "
                     "VALUES (1, ?, 'itching', '', 2, '', '2026-10-05T08:00:00.000000Z')", (DAY,))
        conn.commit()
        server_symptom = conn.execute("SELECT client_id FROM symptoms").fetchone()[0]
    finally:
        conn.close()
    r = bare(admin.app).post("/push/v1/sync", json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["already_there"]["symptoms"] == 1
    unknown = cid()
    r = post(admin.app, token, MATCH, {"ids": {"lab": [added], "symptom": [found], "entry": [entry["client_id"], unknown], "meal": []}})
    assert r.status_code == 200, r.text
    assert r.json() == {"known": {"lab": {added: added}, "symptom": {found: server_symptom}, "entry": {entry["client_id"]: entry["client_id"]},
                                  "meal": {}},
                        "unknown": {"lab": [], "symptom": [], "entry": [unknown], "meal": []}}
    assert post(admin.app, token, MATCH, {"ids": {"lab": ["nope"]}}).status_code == 400
    assert post(admin.app, token, MATCH, {"ids": {"lab": [cid() for _ in range(2001)]}}).status_code == 400


# --------------------------------------------------------------------------- people


def test_another_persons_rows_never_reach_the_feed_or_the_writes(https_client):
    admin = https_client
    switches(admin)
    sam = add_user(admin)
    entry = _log(admin)
    sams = make_sync(sam)["token"]
    changes, _, _ = everything(admin.app, sams)
    assert changes == []
    [r] = send(admin.app, sams, {"kind": "entry", "id": entry["client_id"], "op": "delete", "base": entry["version"]})
    assert r["status"] == "gone"
    r = post(admin.app, sams, MATCH, {"ids": {"entry": [entry["client_id"]]}})
    assert r.json()["unknown"]["entry"] == [entry["client_id"]]
    assert len(admin.get("/api/log", params={"date": DAY}).json()["entries"]) == 1


def test_the_rate_limits(admin, token, monkeypatch):
    from app.auth import ratelimit

    monkeypatch.setitem(ratelimit.LIMITS, sync_feed.FEED_LIMIT, ratelimit.Limit(sync_feed.FEED_LIMIT, 2, 3600.0, "Too many"))
    assert get(admin.app, token).status_code == 200 and get(admin.app, token).status_code == 200
    assert get(admin.app, token).status_code == 429
    assert (ratelimit.LIMITS[sync_feed.WRITE_LIMIT].max_requests, ratelimit.LIMITS[sync_feed.WRITE_LIMIT].window_s) == (120, 3600.0)


def test_the_registered_feed_limit_is_120_an_hour():
    from app.auth import ratelimit

    assert (ratelimit.LIMITS[sync_feed.FEED_LIMIT].max_requests, ratelimit.LIMITS[sync_feed.FEED_LIMIT].window_s) == (120, 3600.0)
