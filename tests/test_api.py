"""API tests against a temporary DATA_DIR and the fixture food database (no network)."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.foods as foods_module
from app.config import Settings
from app.main import create_app
from app.nutrients import NUTRIENT_KEYS

from conftest import DAY, FIXTURE_FOOD_COUNT, find_food, log_food, send_json


# --------------------------------------------------------------------------- #
# Health, startup, import
# --------------------------------------------------------------------------- #


def test_healthz_reports_food_count(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "foods": FIXTURE_FOOD_COUNT}


def test_startup_without_foods_json_still_serves(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", foods_json=tmp_path / "does-not-exist.json")
    with TestClient(create_app(settings)) as c:
        assert c.get("/healthz").json() == {"status": "ok", "foods": 0}
        assert c.app.state.foods_import["status"] == "missing"
    assert (tmp_path / "data" / "kidney.db").exists()


def test_import_is_idempotent_versioned_and_preserves_ids(settings, foods_json):
    with TestClient(create_app(settings)) as c:
        first_ids = {f["name"]: f["id"] for f in c.get("/api/foods", params={"limit": 100}).json()["foods"]}
        assert len(first_ids) == FIXTURE_FOOD_COUNT
        c.app.state.foods_import["status"] == "imported"

    # Same version: skipped, nothing changes.
    with TestClient(create_app(settings)) as c:
        assert c.app.state.foods_import["status"] == "unchanged"
        again = {f["name"]: f["id"] for f in c.get("/api/foods", params={"limit": 100}).json()["foods"]}
        assert again == first_ids
        banana_id = first_ids["Banana, raw"]
        c.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana_id})

    # New version: banana renamed (same fdc_id -> same id), egg white removed (-> hidden, not deleted).
    data = json.loads(foods_json.read_text())
    data["version"] = "test-2"
    foods = [f for f in data["foods"] if f["name"] != "Egg white, raw"]
    for f in foods:
        if f["fdc_id"] == 173944:
            f["name"] = "Banana, raw, medium"
            f["nutrients"]["potassium_mg"] = 400
    data["foods"] = foods
    foods_json.write_text(json.dumps(data))

    with TestClient(create_app(settings)) as c:
        assert c.app.state.foods_import["status"] == "imported"
        assert c.get("/healthz").json()["foods"] == FIXTURE_FOOD_COUNT - 1
        banana = c.get(f"/api/foods/{first_ids['Banana, raw']}").json()
        assert banana["name"] == "Banana, raw, medium" and banana["nutrients"]["potassium_mg"] == 400
        egg = c.get(f"/api/foods/{first_ids['Egg white, raw']}").json()
        assert egg["hidden"] is True
        assert all(f["name"] != "Egg white, raw" for f in c.get("/api/foods", params={"q": "egg"}).json()["foods"])
        # the log entry still resolves to its food
        day = c.get("/api/log", params={"date": DAY}).json()
        assert day["entries"][0]["food_id"] == first_ids["Banana, raw"]


def test_validation_errors_are_400_with_string_detail(client):
    r = client.post("/api/log", json={"date": "2026-13-05", "meal": "brunch", "food_id": 1})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert isinstance(detail, str)
    assert "date" in detail and "meal" in detail
    assert "Value error" not in detail


def test_unknown_api_path_is_404(client):
    assert client.get("/api/nothing-here").status_code == 404


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


def test_profile_defaults_created_on_first_access(client):
    p = client.get("/api/profile").json()
    assert p["id"] == 1
    assert p["name"] == "" and p["weight_kg"] is None and p["height_cm"] is None
    assert p["ckd_stage"] == "3b" and p["dialysis"] == "none" and p["diabetes"] == "type1"
    assert p["warn_fraction"] == 0.8 and p["targets"] == {}
    assert p["updated_at"].endswith("Z")


def test_profile_put_merges_fields_and_targets(client):
    r = client.put("/api/profile", json={"weight_kg": 70, "name": "Sam"})
    assert r.status_code == 200 and r.json()["weight_kg"] == 70 and r.json()["name"] == "Sam"

    r = client.put("/api/profile", json={"ckd_stage": "4", "dialysis": "hemodialysis"})
    p = r.json()
    assert p["weight_kg"] == 70 and p["name"] == "Sam"  # untouched
    assert p["ckd_stage"] == "4" and p["dialysis"] == "hemodialysis"

    r = client.put("/api/profile", json={"targets": {"potassium_mg": 2500, "protein_g": {"min": 42, "max": 56}, "carbs_per_meal_g": 60}})
    assert r.json()["targets"] == {"potassium_mg": 2500, "protein_g": {"min": 42, "max": 56}, "carbs_per_meal_g": 60}

    # key-level merge: only sodium changes, potassium is set to "not tracked" explicitly
    r = client.put("/api/profile", json={"targets": {"sodium_mg": 2000, "potassium_mg": None}})
    assert r.json()["targets"] == {
        "potassium_mg": None, "protein_g": {"min": 42, "max": 56}, "carbs_per_meal_g": 60, "sodium_mg": 2000,
    }
    # weight can be cleared explicitly
    assert client.put("/api/profile", json={"weight_kg": None}).json()["weight_kg"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"ckd_stage": "6"},
        {"dialysis": "sometimes"},
        {"diabetes": "type3"},
        {"warn_fraction": 1.5},
        {"warn_fraction": 0},
        {"weight_kg": -5},
        {"targets": {"nonsense_mg": 5}},
        {"targets": {"protein_g": {"min": 60, "max": 50}}},
        {"targets": {"potassium_mg": -1}},
    ],
)
def test_profile_put_rejects_invalid_values(client, body):
    r = client.put("/api/profile", json=body)
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)


def test_suggested_targets_requires_weight(client):
    r = client.get("/api/profile/suggested-targets")
    assert r.status_code == 400
    assert "weight" in r.json()["detail"]


def test_suggested_targets_from_profile(client):
    client.put("/api/profile", json={"weight_kg": 70, "ckd_stage": "3b", "dialysis": "none"})
    r = client.get("/api/profile/suggested-targets")
    assert r.status_code == 200
    body = r.json()
    assert body["targets"]["protein_g"] == {"min": 42, "max": 56}
    assert body["targets"]["potassium_mg"] == 3500 and body["targets"]["phosphorus_mg"] == 1000
    assert body["targets"]["fluid_ml"] is None and body["targets"]["calories_kcal"] == 2100
    assert isinstance(body["notes"], list) and body["notes"]
    # suggestions are never auto-saved
    assert client.get("/api/profile").json()["targets"] == {}

    client.put("/api/profile", json={"ckd_stage": "5", "dialysis": "hemodialysis"})
    t = client.get("/api/profile/suggested-targets").json()["targets"]
    assert t["protein_g"] == {"min": 70, "max": 84} and t["potassium_mg"] == 2500 and t["fluid_ml"] == 1500


# --------------------------------------------------------------------------- #
# Foods: search
# --------------------------------------------------------------------------- #


def test_search_empty_query_alphabetical_then_recently_logged_first(client):
    names = [f["name"] for f in client.get("/api/foods").json()["foods"]]
    assert names == sorted(names, key=str.lower)
    assert len(names) == FIXTURE_FOOD_COUNT

    log_food(client, "chicken", meal="dinner")
    log_food(client, "water", meal="dinner")
    names = [f["name"] for f in client.get("/api/foods", params={"q": ""}).json()["foods"]]
    assert names[:2] == ["Water, tap", "Chicken breast, roasted"]
    assert names[2:] == sorted(names[2:], key=str.lower)


def test_search_prefix_matches_rank_first_and_every_word_must_match(client):
    names = [f["name"] for f in client.get("/api/foods", params={"q": "apple"}).json()["foods"]]
    assert names == ["Apple, raw, with skin", "Juice, apple"]

    names = [f["name"] for f in client.get("/api/foods", params={"q": "APPLE juice"}).json()["foods"]]
    assert names == ["Juice, apple"]

    names = [f["name"] for f in client.get("/api/foods", params={"q": "raw"}).json()["foods"]]
    assert set(names) == {"Banana, raw", "Apple, raw, with skin", "Egg white, raw"}

    assert client.get("/api/foods", params={"q": "zzzz"}).json()["foods"] == []


def test_search_matches_brand_and_escapes_like_wildcards(client):
    client.post("/api/foods", json={"name": "Protein bar", "brand": "Acme 100% Whey", "serving_desc": "1 bar", "serving_g": 50, "nutrients": {"protein_g": 20}})
    assert [f["name"] for f in client.get("/api/foods", params={"q": "acme"}).json()["foods"]] == ["Protein bar"]
    assert [f["name"] for f in client.get("/api/foods", params={"q": "100%"}).json()["foods"]] == ["Protein bar"]
    # wildcards are escaped: "%" only matches the one brand that literally contains it, "_" matches nothing
    assert [f["name"] for f in client.get("/api/foods", params={"q": "%"}).json()["foods"]] == ["Protein bar"]
    assert client.get("/api/foods", params={"q": "_"}).json()["foods"] == []


def test_search_filters_and_limit(client):
    fruits = client.get("/api/foods", params={"category": "Fruits"}).json()["foods"]
    assert {f["name"] for f in fruits} == {"Banana, raw", "Apple, raw, with skin", "Star fruit (carambola)"}
    assert client.get("/api/foods", params={"source": "custom"}).json()["foods"] == []
    assert len(client.get("/api/foods", params={"limit": 3}).json()["foods"]) == 3
    assert len(client.get("/api/foods", params={"q": "a", "limit": 2}).json()["foods"]) == 2
    assert client.get("/api/foods", params={"limit": 0}).status_code == 400


def test_categories_endpoint_lists_contract_categories(client):
    cats = client.get("/api/foods/categories").json()["categories"]
    assert cats[:12] == list(foods_module.CATEGORIES)
    assert "Diabetes supplies" in cats


# --------------------------------------------------------------------------- #
# Foods: shapes, warnings, CRUD rules
# --------------------------------------------------------------------------- #


def test_food_shape_and_warnings(client):
    banana = find_food(client, "banana")
    assert banana["source"] == "builtin" and banana["fdc_id"] == 173944 and banana["hidden"] is False
    assert set(banana["nutrients"]) == set(NUTRIENT_KEYS)
    assert banana["nutrients"]["potassium_mg"] == 422 and banana["nutrients"]["carbs_g"] == 27.0
    assert banana["kidney_rating"] == "red"
    assert banana["warnings"][0]["message"] == "High potassium: 422 mg per serving"

    cheese = find_food(client, "cheese")
    assert cheese["kidney_rating"] == "red"
    assert any(w["nutrient"] == "phosphorus_mg" and w["flag"] == "phosphate_additive" for w in cheese["warnings"])
    assert any(w["nutrient"] == "sodium_mg" and w["level"] == "medium" for w in cheese["warnings"])

    glucose = find_food(client, "glucose")  # hypo treatment: never warned against for its carbohydrate
    assert glucose["kidney_rating"] == "green"
    assert glucose["warnings"] == []

    star = find_food(client, "star fruit")
    assert star["warnings"][0]["nutrient"] == "avoid_ckd" and star["warnings"][0]["message"] == star["kidney_notes"]

    assert find_food(client, "apple, raw")["kidney_rating"] == "yellow"
    assert find_food(client, "egg white")["kidney_rating"] == "green"
    assert find_food(client, "water")["nutrients"]["fluid_ml"] == 240


def test_get_food_404(client):
    r = client.get("/api/foods/99999")
    assert r.status_code == 404 and "not found" in r.json()["detail"]


def test_create_custom_food(client):
    body = {
        "name": "  Grandma's rice pudding ", "category": "Sweets & Snacks", "serving_desc": "1/2 cup (120 g)",
        "serving_g": 120, "nutrients": {"carbs_g": 32, "potassium_mg": 150, "phosphorus_mg": 95}, "flags": ["Processed"],
        "kidney_notes": "Made with low-phosphorus rice milk.",
    }
    r = client.post("/api/foods", json=body)
    assert r.status_code == 201, r.text
    food = r.json()
    assert food["source"] == "custom" and food["name"] == "Grandma's rice pudding" and food["fdc_id"] is None
    assert food["flags"] == ["processed"]
    assert food["nutrients"]["carbs_g"] == 32 and food["nutrients"]["protein_g"] is None
    assert food["nutrients"]["fluid_ml"] == 0  # not flagged counts_as_fluid
    assert food["kidney_rating"] == "red"  # carbs > 30
    assert client.get(f"/api/foods/{food['id']}").json() == food
    assert [f["id"] for f in client.get("/api/foods", params={"source": "custom"}).json()["foods"]] == [food["id"]]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "serving_desc": "1", "serving_g": 0, "nutrients": {}},
        {"name": "", "serving_desc": "1", "serving_g": 10, "nutrients": {}},
        {"name": "x", "serving_desc": "1", "serving_g": 10, "nutrients": {"potasium_mg": 5}},
        {"name": "x", "serving_desc": "1", "serving_g": 10, "nutrients": {"potassium_mg": -5}},
        {"name": "x", "serving_desc": "1", "serving_g": 10, "nutrients": {"potassium_mg": "lots"}},
        {"name": "x", "serving_desc": "1", "serving_g": 10, "flags": ["Has Spaces"]},
    ],
)
def test_create_food_validation(client, body):
    assert client.post("/api/foods", json=body).status_code == 400


def test_counts_as_fluid_rule(client):
    r = client.post("/api/foods", json={"name": "Herbal tea", "serving_desc": "1 mug", "serving_g": 250, "nutrients": {}, "flags": ["counts_as_fluid"]})
    assert r.json()["nutrients"]["fluid_ml"] == 250  # defaults to the serving weight
    r = client.post("/api/foods", json={"name": "Soup", "serving_desc": "1 bowl", "serving_g": 300, "nutrients": {"fluid_ml": 280}, "flags": ["counts_as_fluid"]})
    assert r.json()["nutrients"]["fluid_ml"] == 280
    r = client.post("/api/foods", json={"name": "Cracker", "serving_desc": "1", "serving_g": 10, "nutrients": {"fluid_ml": 100}})
    assert r.json()["nutrients"]["fluid_ml"] == 0


def test_builtin_foods_cannot_be_edited_or_deleted_but_can_be_copied(client):
    banana = find_food(client, "banana")
    body = {"name": "Banana, small", "serving_desc": "1 small (101 g)", "serving_g": 101, "nutrients": {"potassium_mg": 362}}
    r = client.put(f"/api/foods/{banana['id']}", json=body)
    assert r.status_code == 409 and "copy" in r.json()["detail"].lower()
    assert client.delete(f"/api/foods/{banana['id']}").status_code == 409

    r = client.post(f"/api/foods/{banana['id']}/copy")
    assert r.status_code == 201
    copy = r.json()
    assert copy["id"] != banana["id"] and copy["source"] == "custom" and copy["fdc_id"] == banana["fdc_id"]
    assert copy["nutrients"] == banana["nutrients"] and copy["name"] == banana["name"]

    r = client.put(f"/api/foods/{copy['id']}", json=body)
    assert r.status_code == 200
    edited = r.json()
    assert edited["name"] == "Banana, small" and edited["nutrients"]["potassium_mg"] == 362
    assert edited["nutrients"]["carbs_g"] is None  # PUT replaces the nutrient set
    assert edited["kidney_rating"] == "red"
    assert client.get("/healthz").json()["foods"] == FIXTURE_FOOD_COUNT + 1


def test_put_and_delete_unknown_food_404(client):
    body = {"name": "x", "serving_desc": "1", "serving_g": 10, "nutrients": {}}
    assert client.put("/api/foods/4242", json=body).status_code == 404
    assert client.delete("/api/foods/4242").status_code == 404
    assert client.post("/api/foods/4242/copy").status_code == 404


def test_delete_custom_food_unreferenced_removes_referenced_hides(client):
    a = client.post("/api/foods", json={"name": "Temp A", "serving_desc": "1", "serving_g": 10, "nutrients": {}}).json()
    assert client.delete(f"/api/foods/{a['id']}").status_code == 204
    assert client.get(f"/api/foods/{a['id']}").status_code == 404

    b = client.post("/api/foods", json={"name": "Temp B", "serving_desc": "1", "serving_g": 10, "nutrients": {"carbs_g": 10}}).json()
    entry = client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": b["id"]}).json()
    assert client.delete(f"/api/foods/{b['id']}").status_code == 204
    r = client.get(f"/api/foods/{b['id']}")
    assert r.status_code == 200 and r.json()["hidden"] is True
    assert client.get("/api/foods", params={"q": "temp b"}).json()["foods"] == []
    # the log entry keeps working
    day = client.get("/api/log", params={"date": DAY}).json()
    assert [e["id"] for e in day["entries"]] == [entry["id"]]
    assert day["totals"]["carbs_g"] == 10


# --------------------------------------------------------------------------- #
# Log entries
# --------------------------------------------------------------------------- #


def test_create_entry_snapshots_and_multiplies(client):
    banana = find_food(client, "banana")
    r = client.post("/api/log", json={"date": DAY, "meal": "breakfast", "food_id": banana["id"], "servings": 2, "note": "with oats"})
    assert r.status_code == 201
    e = r.json()
    assert e["date"] == DAY and e["meal"] == "breakfast" and e["food_id"] == banana["id"]
    assert e["food_name"] == "Banana, raw" and e["servings"] == 2 and e["grams"] is None and e["note"] == "with oats"
    assert e["nutrients"]["potassium_mg"] == 844 and e["nutrients"]["carbs_g"] == 53.9
    assert e["kidney_rating"] == "red"
    assert e["warnings"][0]["message"] == "High potassium: 844 mg in this entry"
    assert e["created_at"].endswith("Z") and e["updated_at"].endswith("Z")

    # default servings = 1
    e1 = client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"]}).json()
    assert e1["servings"] == 1 and e1["nutrients"]["potassium_mg"] == 422


def test_create_entry_grams_converts_to_servings(client):
    banana = find_food(client, "banana")
    e = client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": banana["id"], "grams": 59, "servings": 7}).json()
    assert e["servings"] == 0.5 and e["grams"] == 59  # grams win over servings
    assert e["nutrients"]["potassium_mg"] == 211 and e["nutrients"]["calories_kcal"] == 52.5


def test_create_entry_errors(client):
    banana = find_food(client, "banana")
    assert client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": 99999}).status_code == 404
    assert client.post("/api/log", json={"date": DAY, "meal": "brunch", "food_id": banana["id"]}).status_code == 400
    assert client.post("/api/log", json={"date": "05/10/2026", "meal": "lunch", "food_id": banana["id"]}).status_code == 400
    assert client.post("/api/log", json={"date": "2026-02-30", "meal": "lunch", "food_id": banana["id"]}).status_code == 400
    assert client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"], "servings": 0}).status_code == 400
    assert client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"], "grams": -1}).status_code == 400


def test_update_entry_recomputes_snapshot(client):
    e = log_food(client, "banana", meal="breakfast", servings=1)
    r = client.put(f"/api/log/{e['id']}", json={"servings": 3})
    assert r.status_code == 200
    u = r.json()
    assert u["servings"] == 3 and u["nutrients"]["potassium_mg"] == 1266 and u["grams"] is None

    u = client.put(f"/api/log/{e['id']}", json={"grams": 236}).json()
    assert u["servings"] == 2 and u["grams"] == 236 and u["nutrients"]["potassium_mg"] == 844

    u = client.put(f"/api/log/{e['id']}", json={"meal": "dinner", "date": "2026-10-06", "note": "late"}).json()
    assert u["meal"] == "dinner" and u["date"] == "2026-10-06" and u["note"] == "late"
    assert u["servings"] == 2 and u["grams"] == 236  # untouched

    u = client.put(f"/api/log/{e['id']}", json={"note": None, "grams": None}).json()
    assert u["note"] is None and u["grams"] is None and u["servings"] == 2

    assert client.put(f"/api/log/{e['id']}", json={"meal": "elevenses"}).status_code == 400
    assert client.put("/api/log/99999", json={"servings": 1}).status_code == 404
    assert client.get("/api/log", params={"date": DAY}).json()["entries"] == []
    assert len(client.get("/api/log", params={"date": "2026-10-06"}).json()["entries"]) == 1


def test_update_entry_follows_edited_custom_food(client):
    food = client.post("/api/foods", json={"name": "Bar", "serving_desc": "1 bar", "serving_g": 40, "nutrients": {"carbs_g": 20}}).json()
    e = client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": food["id"]}).json()
    client.put(f"/api/foods/{food['id']}", json={"name": "Bar v2", "serving_desc": "1 bar", "serving_g": 40, "nutrients": {"carbs_g": 25}})
    # snapshot is frozen until the entry is edited
    assert client.get("/api/log", params={"date": DAY}).json()["entries"][0]["nutrients"]["carbs_g"] == 20
    u = client.put(f"/api/log/{e['id']}", json={"servings": 1}).json()
    assert u["nutrients"]["carbs_g"] == 25 and u["food_name"] == "Bar v2"


def test_delete_entry(client):
    e = log_food(client, "banana")
    assert client.delete(f"/api/log/{e['id']}").status_code == 204
    assert client.delete(f"/api/log/{e['id']}").status_code == 404
    assert client.get("/api/log", params={"date": DAY}).json()["entries"] == []


# --------------------------------------------------------------------------- #
# Day summary
# --------------------------------------------------------------------------- #


def test_day_summary_totals_meals_status_alerts_and_order(client):
    client.put("/api/profile", json={
        "weight_kg": 70,
        "targets": {"potassium_mg": 1000, "protein_g": {"min": 42, "max": 56}, "sodium_mg": 2000,
                    "carbs_g": 236, "carbs_per_meal_g": 20, "fluid_ml": None},
    })
    # insertion order deliberately differs from meal order
    snack = log_food(client, "glucose", meal="snack")
    dinner = log_food(client, "chicken", meal="dinner", servings=2)
    breakfast1 = log_food(client, "banana", meal="breakfast")
    breakfast2 = log_food(client, "water", meal="breakfast")
    other_day = log_food(client, "banana", meal="lunch", date="2026-10-04")

    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["date"] == DAY
    assert [e["id"] for e in day["entries"]] == [breakfast1["id"], breakfast2["id"], dinner["id"], snack["id"]]
    assert other_day["id"] not in {e["id"] for e in day["entries"]}

    totals = day["totals"]
    assert set(totals) == set(NUTRIENT_KEYS)
    assert totals["potassium_mg"] == 422 + 2 * 218
    assert totals["protein_g"] == round(1.29 + 2 * 26.4, 1)
    assert totals["carbs_g"] == round(26.95 + 16, 1)
    assert totals["fluid_ml"] == 240

    meals = day["meals"]
    assert set(meals) == {"breakfast", "lunch", "dinner", "snack"}
    assert meals["breakfast"]["carbs_g"] == 27.0 and meals["snack"]["carbs_g"] == 16 and meals["lunch"]["carbs_g"] == 0
    assert meals["dinner"]["protein_g"] == 52.8
    assert set(meals["lunch"]) == set(NUTRIENT_KEYS)

    assert day["targets"]["potassium_mg"] == 1000 and day["targets"]["fluid_ml"] is None
    status = day["status"]
    assert set(status) == {"potassium_mg", "protein_g", "sodium_mg", "carbs_g"}  # null fluid and per-meal carbs excluded
    assert status["potassium_mg"] == {"value": 858, "target": 1000, "min": None, "fraction": 0.86, "level": "caution"}
    assert status["protein_g"]["level"] == "caution" and status["protein_g"]["min"] == 42
    assert status["sodium_mg"]["level"] == "ok"

    alerts = day["alerts"]
    kinds = {(a["nutrient"], a["level"], a.get("meal")) for a in alerts}
    assert ("potassium_mg", "caution", None) in kinds
    assert ("protein_g", "caution", None) in kinds
    assert ("carbs_g", "over", "breakfast") in kinds  # 27 g > 20 g per meal
    assert ("carbs_g", "over", "snack") not in kinds
    k_alert = next(a for a in alerts if a["nutrient"] == "potassium_mg")
    assert k_alert["message"] == "Potassium is at 86 % of today's limit (858 / 1000 mg)"

    # push potassium over the limit
    log_food(client, "banana", meal="lunch")
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["status"]["potassium_mg"]["level"] == "over"
    assert day["alerts"][0]["level"] == "over" and day["alerts"][0]["nutrient"] == "potassium_mg"


def test_day_summary_empty_day_and_default_date(client):
    day = client.get("/api/log", params={"date": "2030-01-01"}).json()
    assert day["entries"] == [] and day["alerts"] == [] and day["status"] == {}
    assert all(v == 0 for v in day["totals"].values())
    assert client.get("/api/log").json()["date"] == date.today().isoformat()
    assert client.get("/api/log", params={"date": "yesterday"}).status_code == 400


# --------------------------------------------------------------------------- #
# Range, CSV, quick add
# --------------------------------------------------------------------------- #


def test_range_includes_empty_days(client):
    client.put("/api/profile", json={"targets": {"potassium_mg": 400}})
    log_food(client, "banana", date="2026-10-04")
    log_food(client, "egg white", date="2026-10-06", servings=2)
    r = client.get("/api/log/range", params={"start": "2026-10-04", "end": "2026-10-06"})
    assert r.status_code == 200
    days = r.json()["days"]
    assert [d["date"] for d in days] == ["2026-10-04", "2026-10-05", "2026-10-06"]
    assert days[0]["totals"]["potassium_mg"] == 422 and days[0]["status"]["potassium_mg"]["level"] == "over"
    assert days[1]["totals"]["potassium_mg"] == 0 and days[1]["status"]["potassium_mg"]["level"] == "ok"
    assert days[2]["totals"]["protein_g"] == 7.2
    assert "entries" not in days[0]

    assert client.get("/api/log/range", params={"start": "2026-10-06", "end": "2026-10-04"}).status_code == 400
    assert client.get("/api/log/range", params={"start": "2026-10-04"}).status_code == 400
    assert client.get("/api/log/range", params={"start": "2020-01-01", "end": "2026-10-04"}).status_code == 400
    one = client.get("/api/log/range", params={"start": "2026-10-05", "end": "2026-10-05"}).json()["days"]
    assert len(one) == 1


def test_csv_export(client):
    log_food(client, "banana", meal="breakfast", date="2026-10-04", note="sliced, \"ripe\"")
    log_food(client, "chicken", meal="dinner", date="2026-10-05", servings=1.5)
    log_food(client, "water", meal="snack", date="2026-10-07")

    r = client.get("/api/log/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="kidney-log_all_all.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    header, body = rows[0], rows[1:]
    assert header[:9] == ["id", "date", "meal", "status", "food_id", "food_name", "servings", "grams", "note"]
    assert header[9:21] == list(NUTRIENT_KEYS)
    assert header[21:] == ["created_at", "updated_at"]
    assert len(body) == 3
    assert [row[1] for row in body] == ["2026-10-04", "2026-10-05", "2026-10-07"]
    banana_row = dict(zip(header, body[0]))
    assert banana_row["food_name"] == "Banana, raw" and banana_row["note"] == 'sliced, "ripe"' and banana_row["potassium_mg"] == "422"
    chicken_row = dict(zip(header, body[1]))
    assert chicken_row["servings"] == "1.5" and chicken_row["protein_g"] == "39.6" and chicken_row["grams"] == ""

    r = client.get("/api/log/export.csv", params={"start": "2026-10-05", "end": "2026-10-06"})
    rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) == 2 and rows[1][1] == "2026-10-05"
    assert 'filename="kidney-log_2026-10-05_2026-10-06.csv"' in r.headers["content-disposition"]
    assert client.get("/api/log/export.csv", params={"start": "bad"}).status_code == 400


def test_quick_add_creates_custom_food_and_entry(client):
    body = {
        "date": DAY, "meal": "lunch", "name": "Cafeteria lentil soup", "serving_desc": "1 bowl (300 g)", "serving_g": 300,
        "nutrients": {"calories_kcal": 180, "carbs_g": 28, "protein_g": 10, "potassium_mg": 450, "sodium_mg": 700, "fluid_ml": 250},
        "servings": 1.5, "flags": ["counts_as_fluid"],
    }
    r = client.post("/api/log/quick", json=body)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["food_name"] == "Cafeteria lentil soup" and e["servings"] == 1.5 and e["meal"] == "lunch"
    assert e["nutrients"]["potassium_mg"] == 675 and e["nutrients"]["fluid_ml"] == 375 and e["nutrients"]["carbs_g"] == 42
    assert e["kidney_rating"] == "red"
    food = client.get(f"/api/foods/{e['food_id']}").json()
    assert food["source"] == "custom" and food["flags"] == ["counts_as_fluid"] and food["serving_g"] == 300
    assert client.get("/api/foods", params={"q": "lentil"}).json()["foods"][0]["id"] == e["food_id"]

    # minimal body: defaults for serving and servings
    e2 = client.post("/api/log/quick", json={"date": DAY, "meal": "snack", "name": "Mystery cookie", "nutrients": {"carbs_g": 12}}).json()
    assert e2["servings"] == 1 and e2["nutrients"]["carbs_g"] == 12
    food2 = client.get(f"/api/foods/{e2['food_id']}").json()
    assert food2["serving_desc"] == "1 serving" and food2["serving_g"] == 100

    assert client.post("/api/log/quick", json={"date": DAY, "meal": "snack", "name": "", "nutrients": {}}).status_code == 400
    assert client.post("/api/log/quick", json={"date": DAY, "meal": "snack", "name": "x", "nutrients": {"bogus": 1}}).status_code == 400


# --------------------------------------------------------------------------- #
# Basic auth
# --------------------------------------------------------------------------- #


def test_basic_auth_when_password_set(tmp_path, foods_json):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json, app_password="s3cret")
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/profile")
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == 'Basic realm="kidney-health"'
        assert r.json() == {"detail": "Unauthorized"}
        assert c.get("/api/profile", auth=("anyone", "wrong")).status_code == 401
        assert c.get("/api/profile", headers={"Authorization": "Bearer s3cret"}).status_code == 401
        assert c.get("/api/profile", headers={"Authorization": "Basic not-base64!"}).status_code == 401
        assert c.get("/api/profile", auth=("anyone", "s3cret")).status_code == 200
        assert c.get("/api/profile", auth=("someone-else", "s3cret")).status_code == 200
        assert c.get("/api/foods", params={"q": "banana"}, auth=("u", "s3cret")).status_code == 200
        # static routes are protected too
        assert c.get("/").status_code == 401
        assert c.get("/", auth=("u", "s3cret")).status_code in (200, 404)
        # the health check stays open for liveness probes
        assert c.get("/healthz").status_code == 200


def test_no_auth_when_password_unset(client):
    assert client.get("/api/profile").status_code == 200
    assert "www-authenticate" not in client.get("/api/profile").headers


def test_settings_from_env_treats_empty_password_as_unset(tmp_path):
    from app.config import load_settings
    s = load_settings({"DATA_DIR": str(tmp_path / "d"), "APP_PASSWORD": "", "USDA_API_KEY": "  ", "FOODS_JSON": str(tmp_path / "f.json")})
    assert s.app_password is None and s.usda_api_key is None
    assert s.data_dir == tmp_path / "d" and s.db_path == tmp_path / "d" / "kidney.db"
    assert s.foods_json == tmp_path / "f.json"
    s2 = load_settings({})
    assert s2.data_dir in (Path("./data-local"), Path("/data"))
    assert s2.foods_json.name == "foods.json"


# --------------------------------------------------------------------------- #
# USDA proxy (mocked transport, no network)
# --------------------------------------------------------------------------- #

SR_BANANA = {
    "fdcId": 173944, "description": "Bananas, raw", "dataType": "SR Legacy",
    "foodCategory": {"description": "Fruits and Fruit Juices"},
    "foodNutrients": [
        {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "kcal"}, "amount": 89.0},
        {"nutrient": {"id": 1062, "number": "268", "name": "Energy", "unitName": "kJ"}, "amount": 371.0},
        {"nutrient": {"id": 1003, "number": "203", "name": "Protein"}, "amount": 1.09},
        {"nutrient": {"id": 1004, "number": "204", "name": "Total lipid (fat)"}, "amount": 0.33},
        {"nutrient": {"id": 1258, "number": "606", "name": "Fatty acids, total saturated"}, "amount": 0.112},
        {"nutrient": {"id": 1005, "number": "205", "name": "Carbohydrate, by difference"}, "amount": 22.84},
        {"nutrient": {"id": 1079, "number": "291", "name": "Fiber, total dietary"}, "amount": 2.6},
        {"nutrient": {"id": 2000, "number": "269", "name": "Sugars, total"}, "amount": 12.23},
        {"nutrient": {"id": 1093, "number": "307", "name": "Sodium, Na"}, "amount": 1.0},
        {"nutrient": {"id": 1092, "number": "306", "name": "Potassium, K"}, "amount": 358.0},
        {"nutrient": {"id": 1091, "number": "305", "name": "Phosphorus, P"}, "amount": 22.0},
        {"nutrient": {"id": 1087, "number": "301", "name": "Calcium, Ca"}, "amount": 5.0},
        {"nutrient": {"id": 1051, "number": "255", "name": "Water"}, "amount": 74.91},
    ],
    "foodPortions": [
        {"amount": 1.0, "gramWeight": 118.0, "measureUnit": {"name": "undetermined"}, "modifier": "medium (7\" to 7-7/8\" long)"},
        {"amount": 1.0, "gramWeight": 225.0, "measureUnit": {"name": "undetermined"}, "modifier": "cup, mashed"},
    ],
}

SR_COFFEE = {
    "fdcId": 171890, "description": "Beverages, coffee, brewed", "dataType": "SR Legacy",
    "foodCategory": {"description": "Beverages"},
    "foodNutrients": [
        {"nutrient": {"id": 1008, "number": "208"}, "amount": 1.0},
        {"nutrient": {"id": 1092, "number": "306"}, "amount": 49.0},
        {"nutrient": {"id": 1091, "number": "305"}, "amount": 3.0},
        {"nutrient": {"id": 1051, "number": "255"}, "amount": 99.39},
    ],
    "foodPortions": [{"amount": 1.0, "gramWeight": 237.0, "measureUnit": {"name": "cup"}, "modifier": ""}],
}

BRANDED_CHIPS = {
    "fdcId": 777777, "description": "BANANA CHIPS", "dataType": "Branded", "brandOwner": "Acme Foods",
    "brandedFoodCategory": "Chips, Pretzels & Snacks",
    "servingSize": 28.0, "servingSizeUnit": "g", "householdServingFullText": "1 oz",
    "foodNutrients": [
        {"nutrient": {"id": 1008, "number": "208"}, "amount": 519.0},
        {"nutrient": {"id": 1005, "number": "205"}, "amount": 58.4},
        {"nutrient": {"id": 1093, "number": "307"}, "amount": 6.0},
    ],
}

SEARCH_RESULT = {
    "totalHits": 2,
    "foods": [
        {"fdcId": 173944, "description": "Bananas, raw", "dataType": "SR Legacy", "foodCategory": "Fruits and Fruit Juices"},
        {"fdcId": 777777, "description": "BANANA CHIPS", "dataType": "Branded", "brandOwner": "Acme Foods", "foodCategory": "Chips, Pretzels & Snacks"},
        {"description": "no id -> skipped"},
    ],
}


@pytest.fixture
def usda_client(tmp_path, foods_json, monkeypatch):
    """TestClient with a USDA key whose outbound HTTP goes to an in-process mock."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/fdc/v1/foods/search":
            return httpx.Response(200, json=SEARCH_RESULT)
        if path == "/fdc/v1/food/173944":
            return httpx.Response(200, json=SR_BANANA)
        if path == "/fdc/v1/food/171890":
            return httpx.Response(200, json=SR_COFFEE)
        if path == "/fdc/v1/food/777777":
            return httpx.Response(200, json=BRANDED_CHIPS)
        if path == "/fdc/v1/food/500500":
            return httpx.Response(500, text="upstream exploded")
        if path == "/fdc/v1/food/403403":
            return httpx.Response(403, json={"error": {"code": "API_KEY_INVALID"}})
        if path == "/fdc/v1/food/666666":
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(404, json={"error": "not found"})

    def fake_client() -> httpx.Client:
        return httpx.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(foods_module, "usda_client", fake_client)
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json, usda_api_key="TESTKEY")
    with TestClient(create_app(settings)) as c:
        c.seen_requests = seen  # type: ignore[attr-defined]
        yield c


def test_usda_endpoints_503_without_key(client):
    r = client.get("/api/foods/usda/search", params={"q": "banana"})
    assert r.status_code == 503 and r.json() == {"detail": "USDA_API_KEY not configured"}
    r = client.post("/api/foods/usda/import", json={"fdc_id": 173944})
    assert r.status_code == 503


def test_usda_search_maps_results_and_sends_key_in_header(usda_client):
    r = usda_client.get("/api/foods/usda/search", params={"q": "banana"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "foods": [
            {"fdc_id": 173944, "description": "Bananas, raw", "data_type": "SR Legacy", "brand": None, "category": "Fruits and Fruit Juices"},
            {"fdc_id": 777777, "description": "BANANA CHIPS", "data_type": "Branded", "brand": "Acme Foods", "category": "Chips, Pretzels & Snacks"},
        ]
    }
    req = usda_client.seen_requests[-1]
    assert req.url.path == "/fdc/v1/foods/search"
    assert req.url.params["query"] == "banana"
    assert req.headers["x-api-key"] == "TESTKEY"
    assert "TESTKEY" not in str(req.url)
    assert usda_client.get("/api/foods/usda/search", params={"q": "  "}).status_code == 400


def test_usda_import_sr_legacy_with_household_portion(usda_client):
    r = usda_client.post("/api/foods/usda/import", json={"fdc_id": 173944})
    assert r.status_code == 200, r.text
    food = r.json()
    assert food["source"] == "usda" and food["fdc_id"] == 173944 and food["name"] == "Bananas, raw"
    assert food["category"] == "Fruits" and food["brand"] is None
    assert food["serving_g"] == 118 and food["serving_desc"] == '1 medium (7" to 7-7/8" long) (118 g)'
    n = food["nutrients"]
    assert n["calories_kcal"] == 105.0  # 89 kcal/100 g * 1.18, kJ entry ignored
    assert n["potassium_mg"] == 422 and n["phosphorus_mg"] == 26 and n["sodium_mg"] == 1
    assert n["protein_g"] == 1.3 and n["carbs_g"] == 27.0 and n["fiber_g"] == 3.1 and n["sugar_g"] == 14.4
    assert n["sat_fat_g"] == 0.1 and n["calcium_mg"] == 6
    assert n["fluid_ml"] == 0 and food["flags"] == [] and food["kidney_notes"] is None
    assert food["kidney_rating"] == "red"
    # importing again upserts the same row
    again = usda_client.post("/api/foods/usda/import", json={"fdc_id": 173944}).json()
    assert again["id"] == food["id"]
    assert len([f for f in usda_client.get("/api/foods", params={"source": "usda"}).json()["foods"]]) == 1
    # usda foods are editable (only builtin is locked)
    body = {"name": "Banana (USDA)", "serving_desc": "1 medium", "serving_g": 118, "nutrients": {"potassium_mg": 422}}
    assert usda_client.put(f"/api/foods/{food['id']}", json=body).status_code == 200


def test_usda_import_beverage_counts_as_fluid(usda_client):
    food = usda_client.post("/api/foods/usda/import", json={"fdc_id": 171890}).json()
    assert food["category"] == "Beverages" and food["flags"] == ["counts_as_fluid"]
    assert food["serving_desc"] == "1 cup (237 g)" and food["serving_g"] == 237
    assert food["nutrients"]["fluid_ml"] == 236  # 99.39 g water per 100 g * 2.37
    assert food["nutrients"]["potassium_mg"] == 116


def test_usda_import_branded_without_minerals_marks_unknown(usda_client):
    food = usda_client.post("/api/foods/usda/import", json={"fdc_id": 777777}).json()
    assert food["brand"] == "Acme Foods" and food["category"] == "Chips, Pretzels & Snacks"
    assert food["serving_g"] == 28 and food["serving_desc"] == "1 oz (28 g)"
    assert food["nutrients"]["calories_kcal"] == 145.3 and food["nutrients"]["carbs_g"] == 16.4
    assert food["nutrients"]["potassium_mg"] is None and food["nutrients"]["phosphorus_mg"] is None
    assert "potassium or phosphorus" in food["kidney_notes"]


def test_usda_upstream_errors(usda_client):
    assert usda_client.post("/api/foods/usda/import", json={"fdc_id": 500500}).status_code == 502
    assert usda_client.post("/api/foods/usda/import", json={"fdc_id": 666666}).status_code == 502
    assert usda_client.post("/api/foods/usda/import", json={"fdc_id": 403403}).status_code == 503
    assert usda_client.post("/api/foods/usda/import", json={"fdc_id": 123}).status_code == 404
    assert usda_client.post("/api/foods/usda/import", json={"fdc_id": 0}).status_code == 400
    assert usda_client.get("/healthz").json()["foods"] == FIXTURE_FOOD_COUNT  # nothing half-imported


# --------------------------------------------------------------------------- #
# Fixes after review: numeric bounds, non-finite values, oversized ids and queries
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "extra",
    [
        {"servings": 1e308},
        {"servings": float("inf")},
        {"servings": 1001},
        {"grams": 1e308},
        {"grams": float("inf")},
        {"grams": 100001},
    ],
)
def test_huge_or_infinite_amounts_are_rejected_with_400(client, extra):
    banana = find_food(client, "banana")
    r = send_json(client, "POST", "/api/log", {"date": DAY, "meal": "lunch", "food_id": banana["id"], **extra})
    assert r.status_code == 400, r.text
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]
    e = log_food(client, "banana")
    assert send_json(client, "PUT", f"/api/log/{e['id']}", extra).status_code == 400
    # the day is still readable afterwards
    assert client.get("/api/log", params={"date": DAY}).status_code == 200


def test_nan_input_yields_400_with_detail_not_500(client):
    banana = find_food(client, "banana")
    r = send_json(client, "POST", "/api/log", {"date": DAY, "meal": "lunch", "food_id": banana["id"], "servings": float("nan")})
    assert r.status_code == 400, r.text
    body = r.json()
    assert "servings" in body["detail"] and isinstance(body["errors"], list)
    r = send_json(client, "PUT", "/api/profile", {"weight_kg": float("nan")})
    assert r.status_code == 400 and "weight_kg" in r.json()["detail"]
    r = send_json(client, "PUT", "/api/profile", {"warn_fraction": float("inf")})
    assert r.status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "serving_desc": "1", "serving_g": 1e-320, "nutrients": {}},
        {"name": "x", "serving_desc": "1", "serving_g": 0.05, "nutrients": {}},
        {"name": "x", "serving_desc": "1", "serving_g": float("inf"), "nutrients": {}},
        {"name": "x", "serving_desc": "1", "serving_g": 1e6, "nutrients": {}},
        {"name": "x", "serving_desc": "1", "serving_g": 10, "nutrients": {"potassium_mg": float("inf")}},
        {"name": "x", "serving_desc": "1", "serving_g": 10, "nutrients": {"potassium_mg": 1e999}},
        {"name": "x", "serving_desc": "1", "serving_g": 10, "nutrients": {"potassium_mg": 1e7}},
    ],
)
def test_food_serving_and_nutrient_bounds(client, body):
    r = send_json(client, "POST", "/api/foods", body)
    assert r.status_code == 400, r.text
    assert isinstance(r.json()["detail"], str)
    r = send_json(client, "POST", "/api/log/quick", {"date": DAY, "meal": "lunch", **body})
    assert r.status_code == 400, r.text


def test_sub_gram_serving_cannot_create_an_infinite_entry(client):
    """0.1 g is the smallest serving; grams / serving_g then stays finite (1e6 servings at most)."""
    food = client.post("/api/foods", json={"name": "Sweetener", "serving_desc": "1 packet", "serving_g": 0.1, "nutrients": {"carbs_g": 0.9}}).json()
    assert food["serving_g"] == 0.1
    e = client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": food["id"], "grams": 100000}).json()
    assert e["servings"] == 1000000 and e["nutrients"]["carbs_g"] == 900000
    assert client.get("/api/log", params={"date": DAY}).status_code == 200


@pytest.mark.parametrize(
    "targets",
    [{"sodium_mg": float("nan")}, {"calcium_mg": float("inf")}, {"calcium_mg": 1e999}, {"protein_g": {"min": 10, "max": float("inf")}}, {"potassium_mg": 1e7}],
)
def test_profile_targets_must_be_finite_and_bounded(client, targets):
    r = send_json(client, "PUT", "/api/profile", {"targets": targets})
    assert r.status_code == 400, r.text
    assert client.get("/api/profile").json()["targets"] == {}


def test_a_stored_non_finite_snapshot_does_not_take_the_day_range_or_summary_down(client, settings):
    """Defensive path for rows written before the bounds existed (reproduced the 500s in review)."""
    import sqlite3

    client.put("/api/profile", json={"targets": {"potassium_mg": 2500, "protein_g": {"min": 42, "max": 56}, "sodium_mg": 2000}})
    e = log_food(client, "banana")
    conn = sqlite3.connect(settings.db_path)
    conn.execute("UPDATE log_entries SET potassium_mg = ?, servings = ?, protein_g = ? WHERE id = ?", (float("inf"), 1e308, float("nan"), e["id"]))
    conn.commit()
    conn.close()
    day = client.get("/api/log", params={"date": DAY})
    assert day.status_code == 200, day.text
    body = day.json()
    assert body["entries"][0]["nutrients"]["potassium_mg"] is None
    assert body["status"]["potassium_mg"]["level"] == "over" and body["status"]["potassium_mg"]["fraction"] is None
    assert all(a["nutrient"] != "potassium_mg" for a in body["alerts"])
    rng = client.get("/api/log/range", params={"start": DAY, "end": DAY})
    assert rng.status_code == 200, rng.text
    summary = client.get("/api/log/summary", params={"start": DAY, "end": DAY})
    assert summary.status_code == 200, summary.text
    assert summary.json()["nutrients"]["potassium_mg"]["total"] == 0  # the broken value is ignored, not fatal
    assert client.get("/api/log/export.csv", params={"start": DAY, "end": DAY}).status_code == 200


def test_oversized_ids_are_404_or_400_not_500(client):
    huge = 99999999999999999999  # > 2**63 - 1: sqlite3 cannot bind it
    assert client.get(f"/api/foods/{huge}").status_code == 404
    assert client.put(f"/api/foods/{huge}", json={"name": "x", "serving_desc": "1", "serving_g": 10}).status_code == 404
    assert client.post(f"/api/foods/{huge}/copy").status_code == 404
    assert client.delete(f"/api/foods/{huge}").status_code == 404
    assert client.put(f"/api/log/{huge}", json={"meal": "lunch"}).status_code == 404
    assert client.delete(f"/api/log/{huge}").status_code == 404
    r = client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": 10**30})
    assert r.status_code == 400 and "food_id" in r.json()["detail"]
    assert client.post("/api/foods/usda/import", json={"fdc_id": 10**30}).status_code in (400, 503)


def test_search_query_is_bounded(client):
    long_query = " ".join(["a"] * 1000)
    r = client.get("/api/foods", params={"q": long_query})
    assert r.status_code == 400 and isinstance(r.json()["detail"], str)
    many_short_words = " ".join(["a"] * 50)  # under 200 characters: served, extra words ignored
    r = client.get("/api/foods", params={"q": many_short_words})
    assert r.status_code == 200
    assert client.get("/api/foods", params={"q": "ban", "category": "x" * 101}).status_code == 400


def test_update_entry_keeps_grams_and_servings_consistent_after_the_food_is_reportioned(client):
    food = client.post("/api/foods", json={"name": "Yoghurt", "serving_desc": "1 pot", "serving_g": 100, "nutrients": {"potassium_mg": 100}}).json()
    e = client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": food["id"], "grams": 50}).json()
    assert e["servings"] == 0.5 and e["nutrients"]["potassium_mg"] == 50
    client.put(f"/api/foods/{food['id']}", json={"name": "Yoghurt", "serving_desc": "1 big pot", "serving_g": 200, "nutrients": {"potassium_mg": 100}})
    # editing an unrelated field (as the one-tap "Eaten" PUT does) re-derives servings from the stored weight
    u = client.put(f"/api/log/{e['id']}", json={"meal": "dinner"}).json()
    assert u["grams"] == 50 and u["servings"] == 0.25 and u["nutrients"]["potassium_mg"] == 25
    # an explicit servings edit still wins and drops the weight
    u = client.put(f"/api/log/{e['id']}", json={"servings": 2}).json()
    assert u["grams"] is None and u["servings"] == 2 and u["nutrients"]["potassium_mg"] == 200


def test_suggested_targets_use_the_saved_height_for_ideal_body_weight(client):
    client.put("/api/profile", json={"weight_kg": 100, "height_cm": 170, "ckd_stage": "4", "dialysis": "none"})
    body = client.get("/api/profile/suggested-targets").json()
    assert body["targets"]["calories_kcal"] == 2169 and body["targets"]["protein_g"] == {"min": 43, "max": 58}
    assert any("ideal body weight" in note and "72.3 kg" in note for note in body["notes"])
    client.put("/api/profile", json={"height_cm": None})
    body = client.get("/api/profile/suggested-targets").json()
    assert body["targets"]["calories_kcal"] == 3000 and body["targets"]["protein_g"] == {"min": 60, "max": 80}
    assert any("without a saved height" in note for note in body["notes"])
    # the 400 for a missing weight is plain language (no field names)
    client.put("/api/profile", json={"weight_kg": None})
    detail = client.get("/api/profile/suggested-targets").json()["detail"]
    assert "weight" in detail and "weight_kg" not in detail
