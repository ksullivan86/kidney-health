"""``POST /api/guidance/plan-days`` and ``POST /api/log/clear-planned`` (design note 23): shapes, the 14-day cap, validation,
``no_targets`` and ``disabled``, that planning writes nothing, that "Add to plan" goes through the batch as planned food that is
never counted as eaten, that clearing never touches eaten food or a planned low treatment, and that another person's entries
are 404 and never seen."""
from __future__ import annotations

from typing import Any

import pytest
from app.guidance import rules as R
from conftest import add_user
from test_api_guidance import DAY, entries, food_id, log, real, set_targets  # noqa: F401  (the ``real`` fixture)

DAYS = ["2026-10-05", "2026-10-06", "2026-10-07"]


def plan_days(client, **body: Any) -> dict[str, Any]:
    r = client.post("/api/guidance/plan-days", json={"start": DAY, **body})
    assert r.status_code == 200, r.text
    return r.json()


def add_plan(client, plan: dict[str, Any]) -> list[int]:
    """What the screen does: the entries in requests of at most 40, each with the batch's answer ids."""
    ids: list[int] = []
    rows = plan["apply"]["entries"]
    for i in range(0, len(rows), 40):
        r = client.post("/api/log/batch", json={"entries": rows[i:i + 40]})
        assert r.status_code == 201, r.text
        ids += [x["id"] for x in r.json()["results"]]
    return ids


def test_plan_days_answers_with_the_contract_shape_and_writes_nothing(real):  # noqa: F811
    set_targets(real)
    log(real, "Bread, white", "breakfast", 2)
    before = [entries(real, d) for d in DAYS]
    plan = plan_days(real, days=3)
    assert [entries(real, d) for d in DAYS] == before  # computing writes nothing
    assert plan["status"] == "ok" and plan["rules_version"] == R.RULES_VERSION
    assert (plan["start"], plan["end"], plan["variant"]) == (DAY, "2026-10-07", 0)
    assert [d["date"] for d in plan["days"]] == DAYS
    assert [m["meal"] for m in plan["days"][0]["meals"]] == ["lunch", "dinner"]  # breakfast is logged; no snack unless asked
    assert [m["meal"] for m in plan["days"][1]["meals"]] == ["breakfast", "lunch", "dinner"]
    assert plan["limits"] == {"days_max": 60, "ai_days_max": 31}
    assert plan["choices"] == {"repeat_meals": [], "snack": False, "skip_first_day": []}
    for d in plan["days"]:
        assert d["dialysis_day"] is False and isinstance(d["day_after"]["projected_unknown"], dict)
        assert all(isinstance(m["repeated"], bool) for m in d["meals"])
    assert plan["apply"]["endpoint"] == "/api/log/batch"
    assert all(e["status"] == "planned" and e["purpose"] == "none" for e in plan["apply"]["entries"])
    assert {e["date"] for e in plan["apply"]["entries"]} == set(DAYS)
    assert plan["shopping"]["items"] and plan["targets"]["values"]["potassium_mg"] == 2500
    # With the snack, the first day is what "Plan a day…" gives for it.
    with_snack = plan_days(real, days=3, snack=True)
    one = real.post("/api/guidance/plan-day", json={"date": DAY}).json()
    assert [m["items"] for m in with_snack["days"][0]["meals"]] == [m["items"] for m in one["meals"]]


def test_added_days_are_planned_food_never_eaten_and_clear_takes_them_off(real):  # noqa: F811
    set_targets(real)
    eaten = log(real, "Bread, white", "breakfast", 2)
    low = log(real, "Apple juice", "snack", 1, day="2026-10-06", status="planned")  # a planned low treatment
    assert low["purpose"] == "hypo"
    plan = plan_days(real, days=3)
    ids = add_plan(real, plan)
    assert len(ids) == len(plan["apply"]["entries"])
    for d in DAYS:
        day = real.get("/api/log", params={"date": d}).json()
        planned = [e for e in day["entries"] if e["status"] == "planned" and e["purpose"] != "hypo"]
        assert planned and all(e["purpose"] is None for e in planned)
        eaten_now = [e for e in day["entries"] if e["status"] == "eaten"]
        assert day["counts"]["eaten"] == len(eaten_now)  # planning made nothing eaten
        if d != DAY:
            assert day["totals"]["potassium_mg"] == 0  # the eaten totals do not count the plan
    # Undo: exactly what was added.
    r = real.post("/api/log/clear-planned", json={"start": DAYS[0], "end": DAYS[-1], "ids": ids})
    assert r.status_code == 200 and r.json() == {"deleted": len(ids)}
    left = [e["id"] for d in DAYS for e in entries(real, d)]
    assert sorted(left) == sorted([eaten["id"], low["id"]])
    # Clear planned days: every planned food of the days, never the eaten food or the planned low treatment.
    add_plan(real, plan)
    log(real, "Rice, white, long-grain, cooked", "dinner", day="2026-10-07", status="planned")
    r = real.post("/api/log/clear-planned", json={"start": DAYS[0], "end": DAYS[-1]})
    assert r.status_code == 200 and r.json()["deleted"] == len(plan["apply"]["entries"]) + 1
    assert sorted(e["id"] for d in DAYS for e in entries(real, d)) == sorted([eaten["id"], low["id"]])


def test_a_hemodialysis_week_marks_the_dialysis_days(real):  # noqa: F811
    set_targets(real, dialysis="hemodialysis", dialysis_days=[0, 2, 4])
    plan = plan_days(real, days=7)  # Monday 5 October to Sunday 11 October
    assert [d["dialysis_day"] for d in plan["days"]] == [True, False, True, False, True, False, False]


def test_the_range_is_capped_by_the_server_settings(real):  # noqa: F811
    set_targets(real)
    big = plan_days(real, days=60, meals=["breakfast"])  # the default cap (note 23 §12.1)
    assert len(big["days"]) == 60 and big["end"] == "2026-12-03"
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 61})
    assert r.status_code == 400 and "at most 60 days" in r.text
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 91})
    assert r.status_code == 400 and "days" in r.text  # above the ceiling: refused by the request model
    assert real.post("/api/log/clear-planned", json={"start": "2026-10-01", "end": "2026-11-29"}).status_code == 200
    r = real.post("/api/log/clear-planned", json={"start": "2026-10-01", "end": "2026-11-30"})
    assert r.status_code == 400 and "at most 60 days" in r.text
    # An admin lowers the caps: the plan and the clear follow, and the AI cap never goes above the plain one.
    r = real.patch("/api/admin/settings", json={"guidance.plan_days_max": 20, "guidance.plan_days_ai_max": 31})
    assert r.status_code == 200, r.text
    assert plan_days(real, days=20, meals=["dinner"])["limits"] == {"days_max": 20, "ai_days_max": 20}
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 21})
    assert r.status_code == 400 and "at most 20 days" in r.text
    r = real.post("/api/log/clear-planned", json={"start": "2026-10-01", "end": "2026-10-21"})
    assert r.status_code == 400 and "at most 20 days" in r.text
    r = real.patch("/api/admin/settings", json={"guidance.plan_days_max": 90, "guidance.plan_days_ai_max": 10})
    assert r.status_code == 200, r.text
    assert plan_days(real, days=1)["limits"] == {"days_max": 90, "ai_days_max": 10}
    for bad in (0, 91):
        assert real.patch("/api/admin/settings", json={"guidance.plan_days_max": bad}).status_code == 400


def test_the_caps_are_environment_variables():
    from app.settings_registry import get
    from app.settings_store import SettingsStore

    for key, env, default in (("guidance.plan_days_max", "PLAN_DAYS_MAX", 60),
                              ("guidance.plan_days_ai_max", "PLAN_DAYS_AI_MAX", 31)):
        d = get(key)
        assert (d.env, d.default, d.scope) == (env, default, "instance")
        assert SettingsStore(env={env: "45"}).env_value(d) == (True, 45)
        assert SettingsStore(env={env: ""}).env_value(d)[0] is False  # an empty value means unset
    assert R.PLAN_DAYS_MAX == get("guidance.plan_days_max").default
    assert R.PLAN_DAYS_AI_MAX == get("guidance.plan_days_ai_max").default


def test_the_owners_choices_reach_the_plan_and_are_remembered_per_person(real):  # noqa: F811
    admin = real
    sam = add_user(admin)
    for c in (admin, sam):
        set_targets(c)
    # Each person's remembered choices are their own (the guidance settings object, on the server).
    r = admin.patch("/api/me/settings", json={"guidance": {"plan_repeat_meals": ["breakfast"], "plan_snack": True}})
    assert r.status_code == 200, r.text
    mine = plan_days(admin, days=4)
    assert mine["choices"] == {"repeat_meals": ["breakfast"], "snack": True, "skip_first_day": []}
    assert all("snack" in [m["meal"] for m in d["meals"]] for d in mine["days"])
    breakfasts = [tuple((i["food_id"], i["servings"]) for i in d["meals"][0]["items"]) for d in mine["days"][1:]]
    assert len(set(breakfasts)) == 1  # breakfast may repeat: the same on the days that are planned whole
    theirs = sam.post("/api/guidance/plan-days", json={"start": DAY, "days": 4}).json()
    assert theirs["choices"] == {"repeat_meals": [], "snack": False, "skip_first_day": []}
    assert sam.get("/api/me/settings").json()["settings"]["guidance"]["value"]["plan_repeat_meals"] == []
    # The request wins over the remembered choice, and the first day's past meals are left out.
    asked = plan_days(admin, days=2, repeat_meals=[], snack=False, skip_first_day=["lunch", "dinner"])
    assert asked["choices"] == {"repeat_meals": [], "snack": False, "skip_first_day": ["lunch", "dinner"]}
    assert [m["meal"] for m in asked["days"][0]["meals"]] == ["breakfast"]
    assert [m["meal"] for m in asked["days"][1]["meals"]] == ["breakfast", "lunch", "dinner"]


def test_ok_to_repeat_is_the_persons_own_and_another_persons_meal_or_food_is_404(real):  # noqa: F811
    admin = real
    sam = add_user(admin)
    for c in (admin, sam):
        set_targets(c)
    rice = food_id(admin, "Rice, white, long-grain, cooked")
    dinner = [food_id(admin, "Chicken breast, roasted, skinless"), rice, food_id(admin, "Green beans, boiled")]
    meal = admin.post("/api/meals", json={"name": "Admin's dinner", "meal_hint": "dinner",
                                          "items": [{"food_id": f, "servings": 1} for f in dinner]})
    assert meal.status_code == 201, meal.text
    meal_id = meal.json()["id"]
    soup = admin.post("/api/foods", json={"name": "Admin's own soup", "serving_desc": "1 cup", "serving_g": 240,
                                          "nutrients": {"carbs_g": 10, "potassium_mg": 100}})
    assert soup.status_code == 201, soup.text
    soup_id = soup.json()["id"]
    r = admin.put(f"/api/guidance/repeat-ok/meals/{meal_id}")
    assert r.status_code == 200 and r.json()["meals"] == [{"meal_id": meal_id, "name": "Admin's dinner"}]
    r = admin.put(f"/api/guidance/repeat-ok/foods/{soup_id}")
    assert r.status_code == 200 and r.json()["foods"] == [{"food_id": soup_id, "name": "Admin's own soup"}]
    again = admin.put(f"/api/guidance/repeat-ok/foods/{soup_id}").json()  # the same mark twice is one mark
    assert again["foods"] == [{"food_id": soup_id, "name": "Admin's own soup"}]
    # Sam can mark neither: 404, and Sam's list stays empty.
    assert sam.put(f"/api/guidance/repeat-ok/meals/{meal_id}").status_code == 404
    assert sam.put(f"/api/guidance/repeat-ok/foods/{soup_id}").status_code == 404
    assert sam.delete(f"/api/guidance/repeat-ok/meals/{meal_id}").status_code == 404
    listed = sam.get("/api/guidance/repeat-ok")
    assert listed.json()["meals"] == [] and "Admin" not in listed.text
    # A builtin food is everyone's to use.
    marked = sam.put(f"/api/guidance/repeat-ok/foods/{rice}").json()
    assert marked["foods"] == [{"food_id": rice, "name": "Rice, white, long-grain, cooked"}]
    assert admin.get("/api/guidance/repeat-ok").json()["foods"] == [{"food_id": soup_id, "name": "Admin's own soup"}]
    # An id typed into the settings object by hand that is not the person's is never listed nor used.
    r = sam.patch("/api/me/settings", json={"guidance": {"repeat_ok_meals": [meal_id], "repeat_ok_foods": [rice, soup_id]}})
    assert r.status_code == 200
    listed = sam.get("/api/guidance/repeat-ok").json()
    assert listed["meals"] == [] and [f["food_id"] for f in listed["foods"]] == [rice]
    # The marked saved meal comes back on every dinner of the admin's plan; Sam's plan never sees it.
    plan = plan_days(admin, days=3, meals=["dinner"])
    assert all(d["meals"][0]["source"] == "saved" and d["meals"][0]["template_id"] == meal_id for d in plan["days"])
    theirs = sam.post("/api/guidance/plan-days", json={"start": DAY, "days": 3, "meals": ["dinner"]})
    assert "Admin's dinner" not in theirs.text
    # Taking the mark off: the saved meal waits two days again.
    assert admin.delete(f"/api/guidance/repeat-ok/meals/{meal_id}").json()["meals"] == []
    plan = plan_days(admin, days=3, meals=["dinner"])
    assert [d["meals"][0]["template_id"] for d in plan["days"]] == [meal_id, None, None]
    assert admin.delete(f"/api/guidance/repeat-ok/meals/{meal_id}").status_code == 200  # nothing to take off is fine
    for bad in ("/api/guidance/repeat-ok/drinks/1", "/api/guidance/repeat-ok/foods/0", "/api/guidance/repeat-ok/foods/x"):
        assert admin.put(bad).status_code in (400, 404)


@pytest.mark.parametrize("body", [
    {},
    {"start": "2026-13-01"},
    {"start": DAY, "days": 0},
    {"start": DAY, "days": 2.5},
    {"start": DAY, "variant": 5},
    {"start": DAY, "meals": []},
    {"start": DAY, "meals": ["dinner", "dinner"]},
    {"start": DAY, "meals": ["supper"]},
    {"start": DAY, "date": DAY},
    {"start": DAY, "repeat_meals": ["brunch"]},
    {"start": DAY, "repeat_meals": ["lunch", "lunch"]},
    {"start": DAY, "snack": "maybe"},
    {"start": DAY, "skip_first_day": ["dinner", "dinner"]},
    {"start": DAY, "skip_first_day": "dinner"},
])
def test_plan_days_validation(real, body):  # noqa: F811
    set_targets(real)
    assert real.post("/api/guidance/plan-days", json=body).status_code == 400


@pytest.mark.parametrize("body", [
    {"start": DAY},
    {"start": DAY, "end": "2026-10-04"},
    {"start": DAY, "end": DAY, "ids": []},
    {"start": DAY, "end": DAY, "ids": [0]},
    {"start": DAY, "end": DAY, "surprise": 1},
])
def test_clear_planned_validation(real, body):  # noqa: F811
    assert real.post("/api/log/clear-planned", json=body).status_code == 400


def test_without_targets_or_with_the_plan_builder_off(real):  # noqa: F811
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 2}).json()
    assert r["status"] == "no_targets"
    set_targets(real)
    assert real.patch("/api/me/settings", json={"guidance": {"show_plan_builder": False}}).status_code == 200
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 2}).json()
    assert r["status"] == "disabled"


def test_another_persons_food_and_entries_are_never_seen_and_are_404(real):  # noqa: F811
    admin = real
    sam = add_user(admin)
    for c in (admin, sam):
        set_targets(c)
    soup = admin.post("/api/log/quick", json={"date": "2026-10-06", "meal": "lunch", "name": "Admin's secret soup",
                                              "nutrients": {"carbs_g": 20, "protein_g": 10, "potassium_mg": 2400,
                                                            "phosphorus_mg": 40, "sodium_mg": 60}}).json()
    rice = food_id(admin, "Rice, white, long-grain, cooked")
    admin.post("/api/log", json={"date": "2026-10-07", "meal": "dinner", "food_id": rice, "status": "planned"})
    sam_plan = sam.post("/api/guidance/plan-days", json={"start": DAY, "days": 3})
    assert sam_plan.status_code == 200 and "secret soup" not in sam_plan.text
    # The admin's lunch on the 6th fills that meal for the admin only.
    assert "lunch" in [m["meal"] for m in sam_plan.json()["days"][1]["meals"]]
    assert "lunch" not in [m["meal"] for m in plan_days(admin, days=3)["days"][1]["meals"]]
    # Sam cannot clear the admin's entries: 404, and nothing is deleted.
    r = sam.post("/api/log/clear-planned", json={"start": DAYS[0], "end": DAYS[-1], "ids": [soup["id"]]})
    assert r.status_code == 404
    r = sam.post("/api/log/clear-planned", json={"start": DAYS[0], "end": DAYS[-1]})
    assert r.status_code == 200 and r.json() == {"deleted": 0}
    assert [e["food_name"] for e in entries(admin, "2026-10-07")] == ["Rice, white, long-grain, cooked"]
    assert len(entries(admin, "2026-10-06")) == 1
