"""``/api/guidance`` (note 06 §4.10, §7 "API tests"): shapes, ``no_targets``, ``disabled``, validation
400s, ``?explain=true``, "Not for me", isolation between two people, targets shared with the Today
screen, and that computing a plan writes nothing while "Use this plan" goes through the batch."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
from app.guidance import context as C
from app.guidance import rules as R
from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in

ROOT = Path(__file__).resolve().parents[2]
REAL_FOODS = ROOT / "data" / "foods.json"
DAY = "2026-10-05"

TARGETS = {
    "potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": {"min": 42, "max": 56},
    "carbs_g": 236, "carbs_per_meal_g": 60, "fluid_ml": None, "calories_kcal": 2100, "calcium_mg": 1000,
}


@pytest.fixture
def real(tmp_path) -> Iterator[TestClient]:
    """The admin, signed in over HTTPS, on a database with the real builtin food list (395 foods)."""
    settings = make_settings(tmp_path, REAL_FOODS)
    from app.main import create_app

    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        yield c


def set_targets(client: TestClient, targets: dict[str, Any] = TARGETS, **profile: Any) -> None:
    body = {"targets": targets, "diabetes": "type1", "dialysis": "none", **profile}
    r = client.put("/api/profile", json=body)
    assert r.status_code == 200, r.text


def food_id(client: TestClient, name: str) -> int:
    foods = client.get("/api/foods", params={"q": name, "limit": 50}).json()["foods"]
    for f in foods:
        if f["name"] == name:
            return f["id"]
    raise AssertionError(f"{name!r} not found")


def log(client: TestClient, name: str, meal: str, servings: float = 1, day: str = DAY, **extra: Any) -> dict[str, Any]:
    r = client.post("/api/log", json={"date": day, "meal": meal, "food_id": food_id(client, name), "servings": servings, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def entries(client: TestClient, day: str = DAY) -> list[dict[str, Any]]:
    return client.get("/api/log", params={"date": day}).json()["entries"]


# --------------------------------------------------------------------------- #
# What fits now
# --------------------------------------------------------------------------- #


def test_next_meal_without_targets_says_so(real):
    real.put("/api/profile", json={"targets": {k: None for k in TARGETS}})
    r = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "dinner"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "no_targets", "rules_version": R.RULES_VERSION,
                    "message": "Set your targets in Settings first; guidance compares foods with the targets your care team gave you."}


def test_next_meal_answers_with_the_contract_shape(real):
    set_targets(real)
    log(real, "Bread, white", "breakfast", 2)
    log(real, "Egg, scrambled", "breakfast")
    r = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "dinner"})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["status"] == "ok" and body["rules_version"] == R.RULES_VERSION
    assert body["open_meals"] == ["dinner", "snack"]
    assert body["room"]["potassium_mg"]["cap"] == 750 and body["room"]["fluid_ml"] is None
    assert body["room_text"].startswith("Left for dinner: ")
    assert body["ai"] == {"available": False, "provider_label": None}
    assert body["notes"] == ["Suggestions compare foods with the targets your care team set. They are not medical advice."]
    foods = body["foods"]
    assert 1 <= len(foods) <= R.DEFAULT_LIMIT
    for f in foods:
        assert f["score"] >= R.MIN_SHOW_SCORE and f["fit_text"].startswith("Fits: ")
        assert "explain" not in f or f["explain"] is None
        for page in f["handbook"]:
            assert page["url"].startswith("/learn/")
    # Never a low treatment, an ingredient or an avoid_ckd food (§6.7).
    names = {f["name"] for f in foods}
    assert not names & {"Glucose tablet (4 g carb)", "Flour, all-purpose", "Olive oil", "Star fruit (carambola)"}
    # The same targets the Today screen shows, and when the profile was saved (R10).
    today = real.get("/api/log", params={"date": DAY}).json()
    assert body["targets"]["values"]["potassium_mg"] == today["targets"]["potassium_mg"] == 2500
    assert body["targets"]["profile_updated_at"]


def test_guidance_follows_a_target_change_at_once(real):
    set_targets(real)
    room = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "lunch"}).json()["room"]
    assert room["potassium_mg"]["cap"] == 750
    real.put("/api/profile", json={"targets": {"potassium_mg": 2000}})
    room = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "lunch"}).json()["room"]
    assert room["potassium_mg"]["cap"] == 600  # 0.30 × the new target (AKF's 600 mg at 2,000 mg)


def test_explain_adds_components_and_reasons_for_leaving_foods_out(real):
    set_targets(real)
    body = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "lunch", "explain": "true"}).json()
    components = body["foods"][0]["explain"]["components"]
    assert {"base", "static", "usage", "carbs", "missing_group", "protein"} <= set(components)
    gt = food_id(real, "Glucose tablet (4 g carb)")
    assert body["explain"]["not_eligible"][str(gt)] == "hypo_treatment"
    assert body["explain"]["evaluations"] <= 4 * body["explain"]["eligible"]


@pytest.mark.parametrize("params", [
    {"date": DAY},  # meal is required
    {"date": DAY, "meal": "brunch"},
    {"date": "2026-02-30", "meal": "lunch"},
    {"date": "05/10/2026", "meal": "lunch"},
    {"date": DAY, "meal": "lunch", "limit": 0},
    {"date": DAY, "meal": "lunch", "limit": 21},
])
def test_next_meal_validation(real, params):
    set_targets(real)
    r = real.get("/api/guidance/next-meal", params=params)
    assert r.status_code == 400, r.text
    assert isinstance(r.json()["detail"], str)


# --------------------------------------------------------------------------- #
# Swaps and low treatments
# --------------------------------------------------------------------------- #


def test_swaps_for_a_food_before_saving_and_for_a_saved_entry(real):
    set_targets(real)
    potato = food_id(real, "Potato, baked, with skin")
    r = real.get("/api/guidance/swaps", params={"date": DAY, "meal": "dinner", "food_id": potato, "servings": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "normal" and body["match"] == "carbs"
    assert body["triggers"][0]["nutrient"] == "potassium_mg"
    assert body["swaps"] and all(s["nutrients"]["potassium_mg"] <= 0.75 * body["food"]["nutrients"]["potassium_mg"]
                                 for s in body["swaps"])
    entry = log(real, "Potato, baked, with skin", "dinner")
    by_entry = real.get("/api/guidance/swaps", params={"entry_id": entry["id"], "explain": "true"}).json()
    assert by_entry["entry_id"] == entry["id"] and by_entry["meal"] == "dinner"
    # The entry itself is not counted against the room it is being compared with.
    assert by_entry["triggers"] == body["triggers"]
    assert set(by_entry["explain"]["rejected"]) == {"not_eligible", "no_matching_portion", "not_lower",
                                                    "phosphate_additive", "new_problem"}
    serving_g = real.get(f"/api/foods/{potato}").json()["serving_g"]
    grams = real.get("/api/guidance/swaps", params={"date": DAY, "meal": "dinner", "food_id": potato, "grams": 101}).json()
    assert grams["food"]["servings"] == pytest.approx(101 / serving_g)


def test_swaps_for_a_low_treatment_never_shrink_it(real):
    set_targets(real)
    oj = food_id(real, "Orange juice")
    body = real.get("/api/guidance/swaps", params={"date": DAY, "meal": "snack", "food_id": oj, "purpose": "hypo"}).json()
    assert body["mode"] == "hypo" and body["portion_option"] is None
    assert body["card"]["title"] == "Treating a low" and body["card"]["url"] == "/learn/t1d/treating-a-low/"
    for s in body["swaps"]:
        assert s["nutrients"]["carbs_g"] >= 15  # at least the person's low-treatment amount
        assert s["text"].startswith("For your next low: ")
    entry = log(real, "Glucose tablet (4 g carb)", "snack", 4)  # purpose defaults to "hypo"
    hypo_entry = real.get("/api/guidance/swaps", params={"entry_id": entry["id"]}).json()
    assert hypo_entry["mode"] == "hypo"


@pytest.mark.parametrize("params", [
    {"date": DAY, "meal": "dinner"},  # neither food nor entry
    {"date": DAY, "meal": "dinner", "food_id": 1, "entry_id": 1},
    {"date": DAY, "food_id": 1},  # meal needed with food_id
    {"date": DAY, "meal": "dinner", "food_id": 1, "servings": 0},
    {"date": DAY, "meal": "dinner", "food_id": 1, "servings": "inf"},
    {"date": DAY, "meal": "dinner", "food_id": 1, "purpose": "maybe"},
    {"date": DAY, "meal": "dinner", "food_id": 0},
])
def test_swaps_validation(real, params):
    set_targets(real)
    assert real.get("/api/guidance/swaps", params=params).status_code == 400


def test_swaps_404_for_unknown_food_or_entry(real):
    set_targets(real)
    assert real.get("/api/guidance/swaps", params={"date": DAY, "meal": "dinner", "food_id": 999999}).status_code == 404
    assert real.get("/api/guidance/swaps", params={"entry_id": 999999}).status_code == 404


def test_hypo_options_are_always_available_and_lowest_potassium_first(real):
    real.put("/api/profile", json={"targets": {k: None for k in TARGETS}})  # no targets needed
    real.patch("/api/admin/settings", json={"guidance.enabled": False})
    r = real.get("/api/guidance/hypo-options")
    assert r.status_code == 200
    body = r.json()
    assert body["dose_g"] == 15 and body["card"]["title"] == "Treating a low"
    ks = [o["nutrients"]["potassium_mg"] for o in body["options"]]
    assert ks == sorted(ks) and body["options"][0]["name"].startswith("Glucose")
    assert all(o["nutrients"]["carbs_g"] >= 15 for o in body["options"])
    real.patch("/api/me/settings", json={"guidance": {"hypo_dose_g": 20}})
    assert all(o["nutrients"]["carbs_g"] >= 20 for o in real.get("/api/guidance/hypo-options").json()["options"])


# --------------------------------------------------------------------------- #
# Plan the day
# --------------------------------------------------------------------------- #


def test_plan_day_writes_nothing_and_its_apply_block_logs_through_the_batch(real):
    set_targets(real)
    log(real, "Bread, white", "breakfast", 2)
    before = entries(real)
    r = real.post("/api/guidance/plan-day", json={"date": DAY, "explain": True})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert entries(real) == before  # computing a plan writes nothing
    assert [m["meal"] for m in plan["meals"]] == ["lunch", "dinner", "snack"]
    assert plan["explain"]["evaluations"] <= 8000 and plan["explain"]["meal_evaluations"] <= 1500
    assert plan["apply"]["endpoint"] == "/api/log/batch"
    assert all(e["purpose"] == "none" and e["status"] == "planned" for e in plan["apply"]["entries"])
    applied = real.post("/api/log/batch", json={"entries": plan["apply"]["entries"]})
    assert applied.status_code == 201, applied.text
    planned = [e for e in entries(real) if e["status"] == "planned"]
    assert len(planned) == len(plan["apply"]["entries"])
    assert all(e["purpose"] is None for e in planned)


def test_plan_day_is_deterministic_and_variant_changes_it(real):
    set_targets(real)
    first = real.post("/api/guidance/plan-day", json={"date": DAY, "meals": ["dinner"]}).json()
    again = real.post("/api/guidance/plan-day", json={"date": DAY, "meals": ["dinner"]}).json()
    assert first == again
    other = real.post("/api/guidance/plan-day", json={"date": DAY, "meals": ["dinner"], "variant": 1}).json()
    assert other["variant"] == 1
    assert [i["food_id"] for i in other["meals"][0]["items"]] != [i["food_id"] for i in first["meals"][0]["items"]]


@pytest.mark.parametrize("body", [
    {},
    {"date": "2026-13-01"},
    {"date": DAY, "variant": 5},
    {"date": DAY, "variant": -1},
    {"date": DAY, "meals": []},
    {"date": DAY, "meals": ["dinner", "dinner"]},
    {"date": DAY, "meals": ["supper"]},
    {"date": DAY, "surprise": True},
])
def test_plan_day_validation(real, body):
    set_targets(real)
    assert real.post("/api/guidance/plan-day", json=body).status_code == 400


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #


def test_day_insights_count_eaten_entries_only(real):
    set_targets(real)
    log(real, "Orange juice", "breakfast", 4)  # 4 × ½ cup: 2 cups
    log(real, "Potato, baked, with skin", "dinner", 2)
    log(real, "Banana, raw", "lunch", status="planned")
    body = real.get("/api/guidance/insights/day", params={"date": DAY}).json()
    assert body["status"] == "ok" and body["planned_excluded"] == 1
    ids = [i["id"] for i in body["insights"]]
    assert "day.potassium_mg.over" in ids or "day.potassium_mg.caution" in ids
    assert len(ids) <= R.INSIGHT_MAX


def test_period_insights_need_three_logged_days_and_bound_the_range(real):
    set_targets(real)
    log(real, "Bread, white", "breakfast", day="2026-10-01")
    body = real.get("/api/guidance/insights/period", params={"start": "2026-09-28", "end": "2026-10-04"}).json()
    assert body["logged_days"] == 1
    assert [i["message"] for i in body["insights"]] == ["Log at least 3 days to see weekly insights."]
    assert body["previous"] == {"start": "2026-09-21", "end": "2026-09-27"}
    assert real.get("/api/guidance/insights/period", params={"start": "2026-01-01", "end": "2026-10-04"}).status_code == 400
    assert real.get("/api/guidance/insights/period", params={"start": "2026-10-04", "end": "2026-10-01"}).status_code == 400
    assert real.get("/api/guidance/insights/period", params={"start": "2026-10-x"}).status_code == 400


# --------------------------------------------------------------------------- #
# Switches and settings
# --------------------------------------------------------------------------- #


def test_admin_and_person_can_switch_guidance_off(real):
    set_targets(real)
    q = {"date": DAY, "meal": "lunch"}
    assert real.patch("/api/admin/settings", json={"guidance.enabled": False}).status_code == 200
    body = real.get("/api/guidance/next-meal", params=q).json()
    assert body["status"] == "disabled" and body["message"] == "Meal guidance is switched off on this server."
    assert real.patch("/api/admin/settings", json={"guidance.enabled": None}).status_code == 200
    assert real.get("/api/guidance/next-meal", params=q).json()["status"] == "ok"
    assert real.patch("/api/me/settings", json={"guidance": {"enabled": False}}).status_code == 200
    assert real.get("/api/guidance/next-meal", params=q).json()["status"] == "disabled"
    real.patch("/api/me/settings", json={"guidance": {"show_plan_builder": False, "show_insights": False}})
    assert real.get("/api/guidance/next-meal", params=q).json()["status"] == "ok"
    assert real.post("/api/guidance/plan-day", json={"date": DAY}).json()["status"] == "disabled"
    assert real.get("/api/guidance/insights/day", params={"date": DAY}).json()["status"] == "disabled"
    assert real.get("/api/guidance/rules").status_code == 200  # the rules table is never switched off


def test_guidance_settings_are_validated_and_used(real):
    set_targets(real)
    for bad in ({"carb_tolerance_g": 4}, {"carb_tolerance_g": 21}, {"hypo_dose_g": 31}, {"colour": "red"},
                {"exclude_categories": ["x" * 101]}):
        assert real.patch("/api/me/settings", json={"guidance": bad}).status_code == 400, bad
    assert real.patch("/api/me/settings", json={"guidance": {"carb_tolerance_g": 15,
                                                             "exclude_categories": ["Grains & Breads"]}}).status_code == 200
    body = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "lunch"}).json()
    assert body["room"]["carbs_g"]["tolerance"] == 15
    assert all(f["group"] != "starch" or "Grains" not in f["name"] for f in body["foods"])
    starch_categories = {real.get(f"/api/foods/{f['food_id']}").json()["category"] for f in body["foods"]}
    assert "Grains & Breads" not in starch_categories


def test_rules_table_lists_every_number_and_the_handbook_pages(real):
    body = real.get("/api/guidance/rules").json()
    assert body["rules_version"] == R.RULES_VERSION and len(body["rules_hash"]) == 16
    assert body["rules"]["MEAL_CAP_FRACTION"]["dinner"] == 0.30 and body["rules"]["HYPO_DOSE_G"] == 15
    assert body["topic_pages"]["treating-a-low"]["url"] == "/learn/t1d/treating-a-low/"


# --------------------------------------------------------------------------- #
# "Not for me"
# --------------------------------------------------------------------------- #


def test_not_for_me_hides_a_food_from_suggestions_until_removed(real, monkeypatch):
    set_targets(real)
    q = {"date": DAY, "meal": "lunch", "limit": 20}
    first = real.get("/api/guidance/next-meal", params=q).json()["foods"][0]
    r = real.put(f"/api/guidance/not-for-me/{first['food_id']}")
    assert r.status_code == 200 and [f["food_id"] for f in r.json()["foods"]] == [first["food_id"]]
    assert real.put(f"/api/guidance/not-for-me/{first['food_id']}").status_code == 200  # idempotent
    ids = [f["food_id"] for f in real.get("/api/guidance/next-meal", params=q).json()["foods"]]
    assert first["food_id"] not in ids
    assert real.get("/api/guidance/not-for-me").json()["limit"] == 500
    assert real.delete(f"/api/guidance/not-for-me/{first['food_id']}").status_code == 204
    assert real.delete(f"/api/guidance/not-for-me/{first['food_id']}").status_code == 404
    assert real.put("/api/guidance/not-for-me/999999").status_code == 404
    assert real.put(f"/api/guidance/not-for-me/{2**70}").status_code in (404, 400)
    monkeypatch.setattr(C, "MAX_NOT_FOR_ME", 1)
    assert real.put(f"/api/guidance/not-for-me/{food_id(real, 'Banana, raw')}").status_code == 200
    full = real.put(f"/api/guidance/not-for-me/{food_id(real, 'Apple, raw, with skin')}")
    assert full.status_code == 409 and "full" in full.json()["detail"]


# --------------------------------------------------------------------------- #
# Two people
# --------------------------------------------------------------------------- #


def test_two_people_never_see_each_others_foods_meals_or_history(real):
    admin = real
    sam = add_user(admin)
    for c in (admin, sam):
        set_targets(c)
    # The admin's private food, saved meal, history and "Not for me" list.
    soup = admin.post("/api/log/quick", json={"date": DAY, "meal": "lunch", "name": "Admin's secret soup",
                                              "nutrients": {"carbs_g": 20, "protein_g": 10, "potassium_mg": 50,
                                                            "phosphorus_mg": 40, "sodium_mg": 60}}).json()
    rice = food_id(admin, "Rice, white, long-grain, cooked")
    admin.post("/api/meals", json={"name": "Admin dinner", "meal_hint": "dinner",
                                   "items": [{"food_id": soup["food_id"], "servings": 1}, {"food_id": rice, "servings": 1}]})
    for d in ("2026-10-01", "2026-10-02", "2026-10-03"):
        admin.post("/api/log", json={"date": d, "meal": "dinner", "food_id": soup["food_id"]})
    admin.put(f"/api/guidance/not-for-me/{rice}")

    # The admin sees their own food in guidance …
    admin_fits = admin.get("/api/guidance/next-meal", params={"date": DAY, "meal": "dinner", "explain": "true"}).json()
    assert "Admin dinner" in {m["name"] for m in admin_fits["saved_meals"]}
    assert admin_fits["explain"]["not_eligible"][str(rice)] == "not_for_me"
    # … Sam never does, in any guidance answer.
    texts = []
    texts.append(sam.get("/api/guidance/next-meal", params={"date": DAY, "meal": "dinner", "limit": 20}).text)
    texts.append(sam.post("/api/guidance/plan-day", json={"date": DAY}).text)
    texts.append(sam.get("/api/guidance/insights/day", params={"date": "2026-10-02"}).text)
    texts.append(sam.get("/api/guidance/insights/period", params={"start": "2026-09-28", "end": "2026-10-04"}).text)
    texts.append(sam.get("/api/guidance/hypo-options").text)
    texts.append(sam.get("/api/guidance/not-for-me").text)
    for t in texts:
        assert "secret soup" not in t and "Admin dinner" not in t
    assert sam.get("/api/guidance/not-for-me").json()["foods"] == []
    # Not yours = 404, like not found.
    assert sam.get("/api/guidance/swaps", params={"date": DAY, "meal": "dinner", "food_id": soup["food_id"]}).status_code == 404
    assert sam.get("/api/guidance/swaps", params={"entry_id": soup["id"]}).status_code == 404
    assert sam.put(f"/api/guidance/not-for-me/{soup['food_id']}").status_code == 404
    assert sam.delete(f"/api/guidance/not-for-me/{rice}").status_code == 404
    # The admin's "Not for me" is the admin's alone.
    sam_fits = sam.get("/api/guidance/next-meal", params={"date": DAY, "meal": "dinner", "explain": "true"}).json()
    assert str(rice) not in sam_fits["explain"]["not_eligible"]
    assert str(soup["food_id"]) not in sam_fits["explain"]["not_eligible"]  # not even known to Sam's request


def test_a_new_custom_food_is_a_candidate_at_once(real):
    set_targets(real)
    body = {"name": "Zucchini fritter (home)", "category": "Vegetables", "serving_desc": "1 fritter", "serving_g": 60,
            "nutrients": {"carbs_g": 6, "protein_g": 2, "potassium_mg": 60, "phosphorus_mg": 30, "sodium_mg": 40,
                          "calories_kcal": 70}}
    before = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "lunch", "explain": "true"}).json()
    created = real.post("/api/foods", json=body)
    assert created.status_code == 201, created.text
    after = real.get("/api/guidance/next-meal", params={"date": DAY, "meal": "lunch", "explain": "true"}).json()
    assert after["explain"]["eligible"] == before["explain"]["eligible"] + 1  # the vector cache saw the new revision


def test_export_carries_the_guidance_data(real):
    import io
    import json as _json
    import zipfile

    set_targets(real)
    rice = food_id(real, "Rice, white, long-grain, cooked")
    real.put(f"/api/guidance/not-for-me/{rice}")
    log(real, "Glucose tablet (4 g carb)", "snack", 4)
    real.post("/api/meals", json={"name": "Rice bowl", "meal_hint": "lunch", "items": [{"food_id": rice, "servings": 1}]})
    archive = zipfile.ZipFile(io.BytesIO(real.get("/api/me/export.zip").content))
    data = _json.loads(archive.read("export.json"))
    assert [(p["food_id"], p["preference"]) for p in data["food_preferences"]] == [(rice, "not_for_me")]
    assert data["log_entries"][0]["purpose"] == "hypo"
    assert data["meal_templates"][0]["meal_hint"] == "lunch"
    assert "guidance" not in data["settings"] or isinstance(data["settings"]["guidance"], dict)
    assert b"purpose" in archive.read("log.csv").splitlines()[0]
