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


def test_plan_days_answers_with_the_contract_shape_and_writes_nothing(real):
    set_targets(real)
    log(real, "Bread, white", "breakfast", 2)
    before = [entries(real, d) for d in DAYS]
    plan = plan_days(real, days=3)
    assert [entries(real, d) for d in DAYS] == before  # computing writes nothing
    assert plan["status"] == "ok" and plan["rules_version"] == R.RULES_VERSION
    assert (plan["start"], plan["end"], plan["variant"]) == (DAY, "2026-10-07", 0)
    assert [d["date"] for d in plan["days"]] == DAYS
    assert [m["meal"] for m in plan["days"][0]["meals"]] == ["lunch", "dinner", "snack"]  # breakfast is logged
    assert [m["meal"] for m in plan["days"][1]["meals"]] == ["breakfast", "lunch", "dinner", "snack"]
    for d in plan["days"]:
        assert d["dialysis_day"] is False and isinstance(d["day_after"]["projected_unknown"], dict)
        assert all(isinstance(m["repeated"], bool) for m in d["meals"])
    assert plan["apply"]["endpoint"] == "/api/log/batch"
    assert all(e["status"] == "planned" and e["purpose"] == "none" for e in plan["apply"]["entries"])
    assert {e["date"] for e in plan["apply"]["entries"]} == set(DAYS)
    assert plan["shopping"]["items"] and plan["targets"]["values"]["potassium_mg"] == 2500
    # The first day is what "Plan a day…" gives for it.
    one = real.post("/api/guidance/plan-day", json={"date": DAY}).json()
    assert [m["items"] for m in plan["days"][0]["meals"]] == [m["items"] for m in one["meals"]]


def test_added_days_are_planned_food_never_eaten_and_clear_takes_them_off(real):
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


def test_a_hemodialysis_week_marks_the_dialysis_days(real):
    set_targets(real, dialysis="hemodialysis", dialysis_days=[0, 2, 4])
    plan = plan_days(real, days=7)  # Monday 5 October to Sunday 11 October
    assert [d["dialysis_day"] for d in plan["days"]] == [True, False, True, False, True, False, False]


def test_the_range_is_capped_at_14_days(real):
    set_targets(real)
    assert len(plan_days(real, days=R.PLAN_DAYS_MAX)["days"]) == 14
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 15})
    assert r.status_code == 400 and "days" in r.text
    r = real.post("/api/log/clear-planned", json={"start": "2026-10-01", "end": "2026-10-15"})
    assert r.status_code == 400 and "at most 14 days" in r.text


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
])
def test_plan_days_validation(real, body):
    set_targets(real)
    assert real.post("/api/guidance/plan-days", json=body).status_code == 400


@pytest.mark.parametrize("body", [
    {"start": DAY},
    {"start": DAY, "end": "2026-10-04"},
    {"start": DAY, "end": DAY, "ids": []},
    {"start": DAY, "end": DAY, "ids": [0]},
    {"start": DAY, "end": DAY, "surprise": 1},
])
def test_clear_planned_validation(real, body):
    assert real.post("/api/log/clear-planned", json=body).status_code == 400


def test_without_targets_or_with_the_plan_builder_off(real):
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 2}).json()
    assert r["status"] == "no_targets"
    set_targets(real)
    assert real.patch("/api/me/settings", json={"guidance": {"show_plan_builder": False}}).status_code == 200
    r = real.post("/api/guidance/plan-days", json={"start": DAY, "days": 2}).json()
    assert r["status"] == "disabled"


def test_another_persons_food_and_entries_are_never_seen_and_are_404(real):
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
