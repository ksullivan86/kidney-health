"""Two-person isolation for the v0.3 data (note 07 §4.10, §9 N5; ARCHITECTURE "M2 API" sections).

``tests/test_isolation.py`` is the M1 matrix (log, foods, meals, profile, keys, sessions, exports). This
module adds the tables of schema steps 4–7 and keeps the matrix complete: every table of the final
schema that holds a person's rows must be listed in :data:`MATRIX` with the tests that prove another
person never sees or changes those rows, so a new per-person table cannot ship without one.

Person A (the admin) creates one of every v0.3 thing: a lab result, a "Not for me" food, personal
guidance settings, an entry with an offline ``client_id``, AI activity (consent, a call, usage) and an
own AI provider with a key. Person B must get 404 on A's ids, see none of A's rows in lists, settings,
suggestions or the export, be able to reuse A's ``client_id`` for B's own entry, and deleting B's
account must leave every one of A's rows in place.
"""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from typing import Any, Iterator

import pytest

import test_ai_routes as ai_tests
import test_auth_coverage
import test_export_delete
import test_isolation
from ai_support import FakeProvider, attach, chat
from conftest import DAY, HTTPS_URL, TestClient, add_user, find_food, sign_in
from app.config import AiEnv
from app.main import create_app

CLIENT_ID = "6f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6c"
OWN_KEY = "sk-own-isolation-0123456789abcdefXYZ9"
GUIDANCE_A = {"enabled": True, "carb_tolerance_g": 15, "hypo_dose_g": 20, "exclude_categories": ["Sweets & Snacks"],
              "show_plan_builder": True, "show_insights": False, "ai_enrich": False}

# Every table with a person's rows (a ``user_id`` or ``owner_user_id`` column) and the tests that prove a
# second person can neither see nor change them. Tables without a person (``barcode_cache`` holds product
# data only, never who scanned) are in SHARED_OR_SYSTEM with the reason.
MATRIX: dict[str, tuple[str, ...]] = {
    "log_entries": ("test_isolation.test_b_gets_404_on_every_id_bearing_route_of_a",
                    "test_isolation.test_b_never_sees_a_rows_in_lists_summaries_and_search",
                    "test_isolation_v03.test_client_ids_are_per_person"),
    "foods": ("test_isolation.test_deleting_a_custom_food_only_counts_the_owners_references",
              "test_isolation.test_barcode_lookup_never_matches_another_persons_custom_food"),
    "user_food_links": ("test_isolation.test_shared_usda_row_links_without_exposing_and_unlink_is_per_person",),
    "meal_templates": ("test_isolation.test_b_gets_404_on_every_id_bearing_route_of_a",),
    "user_profiles": ("test_isolation.test_b_never_sees_a_rows_in_lists_summaries_and_search",),
    "user_settings": ("test_isolation_v03.test_guidance_preferences_are_per_person",),
    "sessions": ("test_isolation.test_sessions_are_per_person",),
    "secrets": ("test_isolation_v03.test_ai_activity_and_own_provider_are_per_person",),
    "usage_daily": ("test_isolation_v03.test_ai_activity_and_own_provider_are_per_person",),
    "auth_tokens": ("test_auth_coverage.test_admin_routes_are_403_for_people_who_are_not_admins",
                    "test_export_delete.test_delete_account_needs_confirmation_and_password_and_cascades"),
    "lab_results": ("test_isolation_v03.test_lab_results_are_per_person",),
    "food_preferences": ("test_isolation_v03.test_guidance_preferences_are_per_person",),
    "ai_providers": ("test_isolation_v03.test_ai_activity_and_own_provider_are_per_person",),
    "ai_consents": ("test_isolation_v03.test_ai_activity_and_own_provider_are_per_person",),
    "ai_usage": ("test_isolation_v03.test_ai_activity_and_own_provider_are_per_person",),
    "ai_audit": ("test_isolation_v03.test_ai_activity_and_own_provider_are_per_person",),
}
SHARED_OR_SYSTEM = {
    "users": "the accounts themselves (admins only, tests/test_auth_coverage.py)",
    "audit_log": "security events: a person reads only their own (GET /api/me/activity), admins all",
    "barcode_cache": "product data only, never who scanned (note 03 §9 B7)",
    "instance_settings": "server settings (admins only)",
    "login_failures": "HMAC of a name, no person",
    "profile": "the frozen v0.2 row, never read after schema step 3",
    "meta": "schema version and counters",
    "sqlite_sequence": "SQLite internal",
}
MODULES = {"test_isolation": test_isolation, "test_export_delete": test_export_delete,
           "test_auth_coverage": test_auth_coverage}


def _tables_with_people(conn: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
        out[name] = [c for c in cols if c in ("user_id", "owner_user_id")]
    return out


def test_every_per_person_table_is_in_the_matrix(tmp_path, foods_json):
    from conftest import make_settings
    with TestClient(create_app(make_settings(tmp_path, foods_json))) as c:
        conn = sqlite3.connect(c.app.state.settings.db_path)
        try:
            tables = _tables_with_people(conn)
        finally:
            conn.close()
    personal = {t for t, cols in tables.items() if cols}
    assert personal == set(MATRIX), f"add these tables to MATRIX with an isolation test: {sorted(personal - set(MATRIX))}"
    assert set(tables) == set(MATRIX) | set(SHARED_OR_SYSTEM), sorted(set(tables) ^ (set(MATRIX) | set(SHARED_OR_SYSTEM)))
    here = globals()
    for table, tests in MATRIX.items():
        for ref in tests:
            module, name = ref.split(".")
            source = here if module == "test_isolation_v03" else vars(MODULES[module])
            assert callable(source.get(name)), f"{table}: {ref} does not exist"


# --------------------------------------------------------------------------- the v0.3 pair


@pytest.fixture
def pair(tmp_path, foods_json) -> Iterator[tuple[TestClient, TestClient, dict[str, Any]]]:
    settings = ai_tests.ai_settings(tmp_path, foods_json)
    assert isinstance(settings.ai, AiEnv)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as a:
        sign_in(a)
        ai_tests.enable(a)
        b = add_user(a, "sam")
        banana = find_food(a, "banana")
        lab = a.post("/api/labs", json={"analyte": "potassium", "value": 5.2, "unit": "mmol/L", "taken_on": DAY,
                                       "note": "A's lab"})
        assert lab.status_code == 201, lab.text
        assert a.put(f"/api/guidance/not-for-me/{banana['id']}").status_code == 200
        assert a.patch("/api/me/settings", json={"guidance": GUIDANCE_A}).status_code == 200
        entry = a.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"], "client_id": CLIENT_ID})
        assert entry.status_code == 201, entry.text
        pid = ai_tests.ready(a)
        with attach(a.app, FakeProvider([chat(ai_tests.IDEAS)])):
            assert a.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}).status_code == 200
        own = a.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY})
        assert own.status_code == 200, own.text
        things = {"banana": banana, "lab": lab.json(), "entry": entry.json(), "provider_id": pid, "own": own.json()["own"]}
        yield a, b, things


def test_lab_results_are_per_person(pair):
    a, b, t = pair
    assert b.get("/api/labs").json()["labs"] == []
    assert b.get("/api/labs", params={"analyte": "potassium"}).json()["labs"] == []
    assert b.delete(f"/api/labs/{t['lab']['id']}").status_code == 404
    assert [lab["id"] for lab in a.get("/api/labs").json()["labs"]] == [t["lab"]["id"]]  # B's delete changed nothing
    assert b.get("/api/profile/suggested-targets").status_code == 400  # B has no weight; A's lab is not B's
    b.put("/api/profile", json={"weight_kg": 70})
    suggestion = b.get("/api/profile/suggested-targets").json()
    assert suggestion["derived"]["labs_used"]["potassium"] is None and suggestion["alerts"] == []


def test_guidance_preferences_are_per_person(pair):
    a, b, t = pair
    banana = t["banana"]["id"]
    assert [f["food_id"] for f in a.get("/api/guidance/not-for-me").json()["foods"]] == [banana]
    assert b.get("/api/guidance/not-for-me").json()["foods"] == []
    assert b.delete(f"/api/guidance/not-for-me/{banana}").status_code == 404
    assert [f["food_id"] for f in a.get("/api/guidance/not-for-me").json()["foods"]] == [banana]
    a_setting = a.get("/api/me/settings").json()["settings"]["guidance"]
    b_setting = b.get("/api/me/settings").json()["settings"]["guidance"]
    assert a_setting["value"] == GUIDANCE_A and a_setting["source"] == "user"
    assert b_setting["source"] != "user" and b_setting["value"]["exclude_categories"] == []
    b.put("/api/profile", json={"targets": ai_tests.TARGETS})
    r = b.get("/api/guidance/next-meal", params={"meal": "lunch", "date": DAY, "explain": "true"}).json()
    assert r["status"] == "ok"
    assert r["explain"]["not_eligible"].get(str(banana)) != "not_for_me"  # A's "Not for me" is not B's


def test_client_ids_are_per_person(pair):
    a, b, t = pair
    first = b.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": t["banana"]["id"], "client_id": CLIENT_ID})
    assert first.status_code == 201 and first.json()["id"] != t["entry"]["id"]
    again = b.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": t["banana"]["id"], "client_id": CLIENT_ID})
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]  # B's own repeat, not A's row
    batch = b.post("/api/log/batch", json={"entries": [{"date": DAY, "meal": "snack", "food_id": t["banana"]["id"],
                                                        "client_id": CLIENT_ID}]})
    assert batch.status_code == 200 and batch.json()["results"][0]["result"] == "existing"
    assert batch.json()["results"][0]["id"] == first.json()["id"]
    a_rows = [e for e in a.get("/api/log", params={"date": DAY}).json()["entries"] if e["client_id"] == CLIENT_ID]
    assert [e["id"] for e in a_rows] == [t["entry"]["id"]]


def test_ai_activity_and_own_provider_are_per_person(pair):
    a, b, t = pair
    assert len(a.get("/api/ai/audit").json()["events"]) == 1
    assert b.get("/api/ai/audit").json()["events"] == []
    me = b.get("/api/me/ai").json()
    assert me["own"] is None and not me["consents"]
    assert b.delete(f"/api/ai/consent/{t['provider_id']}").status_code == 404
    assert b.delete(f"/api/ai/consent/{t['own']['id']}").status_code == 404
    # AI usage (ai_usage) counts per person: A's call uses A's shared allowance, not B's.
    a_ai, b_ai = a.get("/api/me/ai").json(), b.get("/api/me/ai").json()
    assert a_ai["daily_limit"] == b_ai["daily_limit"] == 30
    assert (a_ai["remaining_today"], b_ai["remaining_today"]) == (29, 30)
    rows = a.get("/api/admin/ai-usage").json()["usage"]
    assert {r["username"] for r in rows} == {"admin"} and sum(r["requests"] for r in rows) == 1
    # A's own provider and its key are A's only: invisible to B, never shown to anyone.
    text = json.dumps(b.get("/api/me/ai").json()) + json.dumps(a.get("/api/me/ai").json())
    assert OWN_KEY not in text and OWN_KEY[-8:] not in text
    assert b.delete("/api/me/ai/provider").status_code in (204, 404)
    assert a.get("/api/me/ai").json()["own"]["id"] == t["own"]["id"]
    # Naming A's own provider as a "shared" choice never makes it B's: only shared rows resolve.
    assert b.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{t['own']['id']}"}).status_code == 200
    status = b.get("/api/ai/status").json()
    assert status["available"] is False and status["provider"] is None and status["reason"] == "not_configured"


def test_exports_hold_only_the_callers_v03_data(pair):
    a, b, t = pair
    for client, mine in ((a, True), (b, False)):
        r = client.get("/api/me/export.zip")
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            doc = json.loads(z.read("export.json"))
            labs_csv = z.read("labs.csv").decode("utf-8")
        assert bool(doc["lab_results"]) is mine and ("A's lab" in labs_csv) is mine
        assert bool(doc["food_preferences"]) is mine
        assert bool(doc["ai_audit"]) is mine and bool(doc["ai_consents"]) is mine and bool(doc["ai_usage"]) is mine
        assert (doc["ai_provider"] is not None) is mine
        assert any(e.get("client_id") == CLIENT_ID for e in doc["log_entries"]) is mine
        assert OWN_KEY not in json.dumps(doc)


def test_deleting_one_person_leaves_the_others_v03_rows(pair):
    a, b, t = pair
    b.post("/api/labs", json={"analyte": "phosphate", "value": 1.2, "unit": "mmol/L", "taken_on": DAY})
    b.put(f"/api/guidance/not-for-me/{t['banana']['id']}")
    conn = sqlite3.connect(a.app.state.settings.db_path)
    try:
        counts = lambda uid: {table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,)).fetchone()[0]  # noqa: E731
                              for table in ("lab_results", "food_preferences", "ai_audit", "ai_usage", "ai_consents", "log_entries")}
        b_id = b.get("/api/me").json()["id"]
        before = counts(1)
        assert counts(b_id)["lab_results"] == 1 and counts(b_id)["food_preferences"] == 1
        from conftest import USER_PASSWORD
        assert b.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
        assert counts(b_id) == dict.fromkeys(before, 0)
        assert counts(1) == before and all(before[k] >= 1 for k in before)
        assert conn.execute("SELECT COUNT(*) FROM ai_providers WHERE owner_user_id = 1").fetchone()[0] == 1
    finally:
        conn.close()
