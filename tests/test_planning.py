"""API tests for the v0.2 features: planned entries, mark-eaten, copy-day, projections, the
period summary, saved meals, the shopping list and the new profile fields (no network)."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest

from app.nutrients import NUTRIENT_KEYS
from app.periods import NOTE_CARBS, NOTE_DAILY, NOTE_INTERDIALYTIC, NOTE_NO_DIALYSIS_DAYS, NOTE_WEEKLY

from conftest import DAY, find_food, log_food, send_json

TOMORROW = "2026-10-06"
NEXT_DAY = "2026-10-07"


# --------------------------------------------------------------------------- #
# Profile: dialysis days and week start
# --------------------------------------------------------------------------- #


def test_profile_defaults_include_dialysis_days_and_week_start(client):
    p = client.get("/api/profile").json()
    assert p["dialysis_days"] == [] and p["week_start"] == "monday"


def test_profile_dialysis_days_are_normalised_and_week_start_saved(client):
    r = client.put("/api/profile", json={"dialysis_days": [4, 0, 2, 0], "week_start": "sunday"})
    assert r.status_code == 200, r.text
    assert r.json()["dialysis_days"] == [0, 2, 4] and r.json()["week_start"] == "sunday"
    # stored for any dialysis mode (only the hemodialysis summary uses it); other fields untouched
    p = client.put("/api/profile", json={"name": "Sam"}).json()
    assert p["dialysis_days"] == [0, 2, 4] and p["week_start"] == "sunday" and p["dialysis"] == "none"
    assert client.put("/api/profile", json={"dialysis_days": []}).json()["dialysis_days"] == []
    client.put("/api/profile", json={"dialysis_days": [6]})
    assert client.put("/api/profile", json={"dialysis_days": None}).json()["dialysis_days"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"dialysis_days": [7]},
        {"dialysis_days": [-1]},
        {"dialysis_days": ["mon"]},
        {"dialysis_days": [True]},
        {"dialysis_days": "0,2,4"},
        {"week_start": "tuesday"},
    ],
)
def test_profile_rejects_invalid_dialysis_days_and_week_start(client, body):
    r = client.put("/api/profile", json=body)
    assert r.status_code == 400 and isinstance(r.json()["detail"], str)


# --------------------------------------------------------------------------- #
# Entry status
# --------------------------------------------------------------------------- #


def test_entry_status_defaults_to_eaten_and_can_be_planned(client):
    eaten = log_food(client, "banana")
    assert eaten["status"] == "eaten"
    planned = log_food(client, "banana", meal="lunch", date=TOMORROW, status="planned")
    assert planned["status"] == "planned" and planned["nutrients"]["potassium_mg"] == 422
    quick = client.post(
        "/api/log/quick",
        json={"date": TOMORROW, "meal": "snack", "name": "Planned cookie", "nutrients": {"carbs_g": 12}, "status": "planned"},
    )
    assert quick.status_code == 201 and quick.json()["status"] == "planned"
    banana = find_food(client, "banana")
    assert client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"], "status": "maybe"}).status_code == 400


def test_put_status_marks_a_single_entry_eaten_and_keeps_the_snapshot(client):
    e = log_food(client, "banana", servings=2, status="planned")
    u = client.put(f"/api/log/{e['id']}", json={"status": "eaten"})
    assert u.status_code == 200
    assert u.json()["status"] == "eaten" and u.json()["servings"] == 2 and u.json()["nutrients"]["potassium_mg"] == 844
    # other edits leave the status alone
    u = client.put(f"/api/log/{e['id']}", json={"servings": 1}).json()
    assert u["status"] == "eaten" and u["nutrients"]["potassium_mg"] == 422
    assert client.put(f"/api/log/{e['id']}", json={"status": "planned"}).json()["status"] == "planned"
    assert client.put(f"/api/log/{e['id']}", json={"status": "skipped"}).status_code == 400


def test_day_summary_separates_eaten_planned_and_projected(client):
    client.put("/api/profile", json={"targets": {"potassium_mg": 1000, "carbs_per_meal_g": 20}})
    # v0.3.1: per-meal alerts wait for the person's carbohydrate tolerance (default 10 g; tests/test_tolerance.py)
    assert client.patch("/api/me/settings", json={"guidance": {"carb_tolerance_g": 5}}).status_code == 200
    water_planned = log_food(client, "water", meal="breakfast", status="planned")
    banana_eaten = log_food(client, "banana", meal="breakfast")
    banana_planned = log_food(client, "banana", meal="lunch", status="planned")
    chicken_planned = log_food(client, "chicken", meal="dinner", status="planned")
    glucose_eaten = log_food(client, "glucose", meal="snack")

    day = client.get("/api/log", params={"date": DAY}).json()
    # meal order, then eaten before planned, then created_at
    assert [e["id"] for e in day["entries"]] == [
        banana_eaten["id"], water_planned["id"], banana_planned["id"], chicken_planned["id"], glucose_eaten["id"],
    ]
    assert day["counts"] == {"eaten": 2, "planned": 3}

    assert day["totals"]["potassium_mg"] == 422 and day["totals"]["fluid_ml"] == 0
    assert day["planned_totals"]["potassium_mg"] == 422 + 218 and day["planned_totals"]["fluid_ml"] == 240
    assert day["projected_totals"]["potassium_mg"] == 1062 and day["projected_totals"]["fluid_ml"] == 240
    assert set(day["planned_totals"]) == set(day["projected_totals"]) == set(NUTRIENT_KEYS)

    assert day["status"]["potassium_mg"]["level"] == "ok" and day["status"]["potassium_mg"]["value"] == 422
    assert day["projected_status"]["potassium_mg"] == {"value": 1062, "target": 1000, "min": None, "fraction": 1.06, "level": "over",
                                                       "unknown": 0}

    assert day["meals"]["breakfast"]["carbs_g"] == 27.0 and day["meals"]["lunch"]["carbs_g"] == 0
    assert day["planned_meals"]["breakfast"]["fluid_ml"] == 240 and day["planned_meals"]["lunch"]["carbs_g"] == 27.0
    assert day["planned_meals"]["dinner"]["protein_g"] == 26.4 and set(day["planned_meals"]) == {"breakfast", "lunch", "dinner", "snack"}

    # eaten alerts: only the breakfast carb goal is exceeded (27 g > 20 g + 5 g tolerance)
    assert {(a["nutrient"], a["level"], a.get("meal")) for a in day["alerts"]} == {("carbs_g", "over", "breakfast")}
    projected = {(a["nutrient"], a["level"], a.get("meal")): a["message"] for a in day["projected_alerts"]}
    assert ("potassium_mg", "over", None) in projected
    assert projected[("potassium_mg", "over", None)] == "If you eat what's planned, potassium reaches 106 % of today's limit (1062 / 1000 mg)"
    assert ("carbs_g", "over", "lunch") in projected and ("carbs_g", "over", "breakfast") in projected
    assert day["projected_alerts"][0]["level"] == "over"


def test_projected_alerts_are_empty_when_nothing_is_planned(client):
    client.put("/api/profile", json={"targets": {"potassium_mg": 400}})
    log_food(client, "banana")
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["alerts"] and day["alerts"][0]["level"] == "over"
    assert day["projected_alerts"] == []
    assert day["projected_totals"] == day["totals"] and day["projected_status"] == day["status"]
    assert day["counts"] == {"eaten": 1, "planned": 0}
    empty = client.get("/api/log", params={"date": "2030-01-01"}).json()
    assert empty["counts"] == {"eaten": 0, "planned": 0} and empty["projected_alerts"] == [] and empty["planned_meals"]["snack"]["carbs_g"] == 0


def test_range_reports_planned_and_projected_per_day(client):
    client.put("/api/profile", json={"targets": {"potassium_mg": 400}})
    log_food(client, "banana", date="2026-10-04")
    log_food(client, "banana", date=DAY, status="planned")
    days = client.get("/api/log/range", params={"start": "2026-10-04", "end": TOMORROW}).json()["days"]
    assert [d["counts"] for d in days] == [{"eaten": 1, "planned": 0}, {"eaten": 0, "planned": 1}, {"eaten": 0, "planned": 0}]
    assert days[0]["status"]["potassium_mg"]["level"] == "over" and days[0]["projected_status"]["potassium_mg"]["level"] == "over"
    assert days[1]["totals"]["potassium_mg"] == 0 and days[1]["status"]["potassium_mg"]["level"] == "ok"
    assert days[1]["planned_totals"]["potassium_mg"] == 422 and days[1]["projected_totals"]["potassium_mg"] == 422
    assert days[1]["projected_status"]["potassium_mg"]["level"] == "over"
    assert set(days[2]) == {"date", "totals", "planned_totals", "projected_totals", "status", "projected_status", "counts",
                            "unknown", "planned_unknown", "projected_unknown"}


def test_mark_eaten_for_a_meal_then_the_whole_day(client):
    log_food(client, "banana", meal="breakfast", status="planned")
    log_food(client, "water", meal="breakfast", status="planned")
    log_food(client, "chicken", meal="dinner", status="planned")
    log_food(client, "glucose", meal="snack")
    other = log_food(client, "apple", meal="lunch", date=TOMORROW, status="planned")

    r = client.post("/api/log/mark-eaten", json={"date": DAY, "meal": "breakfast"})
    assert r.status_code == 200 and r.json() == {"updated": 2}
    assert client.get("/api/log", params={"date": DAY}).json()["counts"] == {"eaten": 3, "planned": 1}

    assert client.post("/api/log/mark-eaten", json={"date": DAY}).json() == {"updated": 1}
    assert client.post("/api/log/mark-eaten", json={"date": DAY}).json() == {"updated": 0}
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["counts"] == {"eaten": 4, "planned": 0} and all(e["status"] == "eaten" for e in day["entries"])
    # the other day is untouched
    assert client.get("/api/log", params={"date": TOMORROW}).json()["entries"][0]["id"] == other["id"]
    assert client.get("/api/log", params={"date": TOMORROW}).json()["counts"] == {"eaten": 0, "planned": 1}

    assert client.post("/api/log/mark-eaten", json={"date": DAY, "meal": "brunch"}).status_code == 400
    assert client.post("/api/log/mark-eaten", json={"meal": "lunch"}).status_code == 400
    assert client.post("/api/log/mark-eaten", json={"date": "2026-13-01"}).status_code == 400


def test_copy_day_defaults_to_planned_and_recomputes_snapshots(client):
    log_food(client, "banana", meal="breakfast", note="ripe")
    chicken = find_food(client, "chicken")
    client.post("/api/log", json={"date": DAY, "meal": "dinner", "food_id": chicken["id"], "grams": 170, "status": "planned"})
    bar = client.post("/api/foods", json={"name": "Bar", "serving_desc": "1 bar", "serving_g": 40, "nutrients": {"carbs_g": 20}}).json()
    client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": bar["id"]})

    r = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": TOMORROW})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] == 3 and len(body["entries"]) == 3
    assert all(e["status"] == "planned" and e["date"] == TOMORROW for e in body["entries"])
    assert [e["meal"] for e in body["entries"]] == ["breakfast", "dinner", "snack"]
    assert body["entries"][0]["note"] == "ripe"
    assert body["entries"][1]["grams"] == 170 and body["entries"][1]["servings"] == 2 and body["entries"][1]["nutrients"]["protein_g"] == 52.8
    # the source day is untouched
    src = client.get("/api/log", params={"date": DAY}).json()
    assert src["counts"] == {"eaten": 2, "planned": 1}
    assert client.get("/api/log", params={"date": TOMORROW}).json()["counts"] == {"eaten": 0, "planned": 3}

    # snapshots come from the *current* food, not from the source entry
    client.put(f"/api/foods/{bar['id']}", json={"name": "Bar v2", "serving_desc": "1 bar", "serving_g": 40, "nutrients": {"carbs_g": 25}})
    copied = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": NEXT_DAY, "status": "eaten"}).json()
    snack = next(e for e in copied["entries"] if e["meal"] == "snack")
    assert snack["nutrients"]["carbs_g"] == 25 and snack["food_name"] == "Bar v2" and snack["status"] == "eaten"
    assert next(e for e in src["entries"] if e["meal"] == "snack")["nutrients"]["carbs_g"] == 20


def test_copy_day_filters_by_meal_and_status(client):
    log_food(client, "banana", meal="breakfast")
    log_food(client, "water", meal="breakfast", status="planned")
    log_food(client, "chicken", meal="dinner", status="planned")

    r = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": TOMORROW, "include": "eaten", "status": "eaten"})
    assert r.json()["created"] == 1 and r.json()["entries"][0]["food_name"] == "Banana, raw" and r.json()["entries"][0]["status"] == "eaten"

    r = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": NEXT_DAY, "include": "planned"})
    assert r.json()["created"] == 2 and {e["food_name"] for e in r.json()["entries"]} == {"Water, tap", "Chicken breast, roasted"}

    r = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": "2026-10-08", "meals": ["breakfast", "breakfast"]})
    assert r.json()["created"] == 2 and all(e["meal"] == "breakfast" for e in r.json()["entries"])

    r = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": "2026-10-09", "meals": ["lunch"]})
    assert r.status_code == 400 and "no entries" in r.json()["detail"]


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({"from_date": DAY, "to_date": DAY}, "differ"),
        ({"from_date": DAY, "to_date": TOMORROW, "meals": []}, "meals"),
        ({"from_date": "2030-01-01", "to_date": TOMORROW}, "no entries"),
        ({"from_date": DAY, "to_date": TOMORROW, "include": "bogus"}, "include"),
        ({"from_date": DAY, "to_date": TOMORROW, "status": "maybe"}, "status"),
        ({"from_date": DAY}, "to_date"),
        ({"from_date": "05/10/2026", "to_date": TOMORROW}, "from_date"),
    ],
)
def test_copy_day_errors(client, body, fragment):
    log_food(client, "banana")
    r = client.post("/api/log/copy-day", json=body)
    assert r.status_code == 400, r.text
    assert fragment in r.json()["detail"]


def test_csv_export_includes_status(client):
    log_food(client, "banana", meal="breakfast")
    log_food(client, "water", meal="lunch", status="planned")
    rows = list(csv.reader(io.StringIO(client.get("/api/log/export.csv").text)))
    header = rows[0]
    assert header.index("status") == 3
    by_name = {dict(zip(header, r))["food_name"]: dict(zip(header, r)) for r in rows[1:]}
    assert by_name["Banana, raw"]["status"] == "eaten" and by_name["Water, tap"]["status"] == "planned"


# --------------------------------------------------------------------------- #
# Period summary
# --------------------------------------------------------------------------- #


def test_summary_defaults_to_the_seven_days_ending_today(client):
    s = client.get("/api/log/summary").json()
    today = date.today()
    assert s["end"] == today.isoformat() and s["start"] == (today - timedelta(days=6)).isoformat()
    assert s["days"] == 7 and s["logged_days"] == 0
    assert s["nutrients"] == {}  # no targets yet
    assert s["interdialytic"] is None
    assert s["notes"] == [NOTE_DAILY, NOTE_WEEKLY, NOTE_CARBS]


def test_summary_aggregates_eaten_entries_only_with_previous_period(client):
    client.put("/api/profile", json={"targets": {"potassium_mg": 800, "protein_g": {"min": 42, "max": 56}, "fluid_ml": None}})
    log_food(client, "banana", date="2026-10-01")
    log_food(client, "banana", date="2026-10-03", servings=2)
    log_food(client, "egg white", date="2026-10-05", servings=2)
    log_food(client, "banana", date="2026-10-06", status="planned")  # planned: ignored
    log_food(client, "banana", date="2026-09-28")  # previous period
    log_food(client, "banana", date="2026-09-30", servings=3)  # previous period

    r = client.get("/api/log/summary", params={"start": "2026-10-01", "end": "2026-10-07"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["start"], s["end"], s["days"], s["logged_days"]) == ("2026-10-01", "2026-10-07", 7, 3)
    assert set(s["nutrients"]) == {"potassium_mg", "protein_g"}

    k = s["nutrients"]["potassium_mg"]
    assert k["role"] == "limit" and k["target"] == 800 and k["assessment"] == "daily"
    assert k["total"] == 422 + 844 + 108 and k["average"] == 458
    assert k["fraction"] == pytest.approx(0.57, abs=0.01) and k["level"] == "ok"
    assert k["days_over"] == 1 and k["max_day"] == {"date": "2026-10-03", "value": 844}
    assert k["previous_average"] == 844 and k["change_pct"] == pytest.approx(-45.7, abs=0.05)

    pr = s["nutrients"]["protein_g"]
    assert pr["role"] == "range" and pr["target"] == 56.0 and pr["assessment"] == "weekly_average"
    assert pr["total"] == 11.1 and pr["average"] == 3.7 and pr["days_over"] == 0
    assert pr["max_day"] == {"date": "2026-10-05", "value": 7.2}
    # protein per banana is stored as shown (1.3 g, the fixture says 1.29): 3.7 vs 2.6 g/day
    assert pr["previous_average"] == 2.6 and pr["change_pct"] == pytest.approx(42.3, abs=0.05)
    assert s["interdialytic"] is None and len(s["notes"]) == 3


def test_summary_range_handling_and_errors(client):
    s = client.get("/api/log/summary", params={"start": "2026-10-01"}).json()
    assert (s["start"], s["end"], s["days"]) == ("2026-10-01", "2026-10-07", 7)
    s = client.get("/api/log/summary", params={"end": "2026-10-07"}).json()
    assert (s["start"], s["end"]) == ("2026-10-01", "2026-10-07")
    s = client.get("/api/log/summary", params={"start": "2026-10-01", "end": "2026-10-01"}).json()
    assert s["days"] == 1
    s = client.get("/api/log/summary", params={"start": "2025-10-07", "end": "2026-10-07"}).json()
    assert s["days"] == 366
    assert client.get("/api/log/summary", params={"start": "2025-10-06", "end": "2026-10-07"}).status_code == 400
    assert client.get("/api/log/summary", params={"start": "2026-10-07", "end": "2026-10-01"}).status_code == 400
    assert client.get("/api/log/summary", params={"start": "last week"}).status_code == 400
    assert client.get("/api/log/summary", params={"end": "2026-02-30"}).status_code == 400


def test_summary_interdialytic_block_for_hemodialysis(client):
    client.put(
        "/api/profile",
        json={"dialysis": "hemodialysis", "dialysis_days": [0, 2, 4], "targets": {"potassium_mg": 2000, "sodium_mg": 2000, "fluid_ml": 1500}},
    )
    log_food(client, "water", date="2026-10-01")  # in the period, before the interval
    log_food(client, "water", date="2026-10-02")
    log_food(client, "water", date="2026-10-03", servings=2)
    log_food(client, "water", date="2026-10-04")
    log_food(client, "banana", date="2026-10-04")
    log_food(client, "water", date="2026-10-04", servings=5, status="planned")  # ignored

    s = client.get("/api/log/summary", params={"start": "2026-09-28", "end": "2026-10-04"}).json()  # ends on a Sunday
    iv = s["interdialytic"]
    assert (iv["since"], iv["days"], iv["next"]) == ("2026-10-02", 3, "2026-10-05")
    assert set(iv["nutrients"]) == {"potassium_mg", "sodium_mg", "fluid_ml"}
    assert iv["nutrients"]["fluid_ml"] == {"total": 960, "limit": 4500, "fraction": 0.21, "level": "ok", "unknown_entries": 0}
    assert iv["nutrients"]["potassium_mg"]["total"] == 422 and iv["nutrients"]["potassium_mg"]["limit"] == 6000
    assert iv["nutrients"]["sodium_mg"]["total"] == 7 + 14 + 7 + 1 and iv["nutrients"]["sodium_mg"]["limit"] == 6000
    assert NOTE_INTERDIALYTIC in s["notes"] and NOTE_NO_DIALYSIS_DAYS not in s["notes"]
    # the period figures still cover the whole range (4 logged days, fluid 1200 in total)
    assert s["logged_days"] == 4 and s["nutrients"]["fluid_ml"]["total"] == 1200

    # ending on a dialysis day: intake that day counts toward the next session
    s = client.get("/api/log/summary", params={"start": "2026-09-29", "end": "2026-10-05"}).json()
    assert (s["interdialytic"]["since"], s["interdialytic"]["days"], s["interdialytic"]["next"]) == ("2026-10-05", 1, "2026-10-07")
    assert s["interdialytic"]["nutrients"]["fluid_ml"] == {"total": 0, "limit": 1500, "fraction": 0.0, "level": "ok", "unknown_entries": 0}

    # a nutrient without a target drops out of the block
    client.put("/api/profile", json={"targets": {"fluid_ml": None}})
    s = client.get("/api/log/summary", params={"start": "2026-09-28", "end": "2026-10-04"}).json()
    assert set(s["interdialytic"]["nutrients"]) == {"potassium_mg", "sodium_mg"}


def test_summary_interdialytic_is_null_without_days_or_outside_hemodialysis(client):
    client.put("/api/profile", json={"dialysis": "hemodialysis", "targets": {"potassium_mg": 2000}})
    s = client.get("/api/log/summary").json()
    assert s["interdialytic"] is None and s["notes"][-1] == NOTE_NO_DIALYSIS_DAYS
    client.put("/api/profile", json={"dialysis": "peritoneal", "dialysis_days": [1, 3, 5]})
    s = client.get("/api/log/summary").json()
    assert s["interdialytic"] is None and NOTE_NO_DIALYSIS_DAYS not in s["notes"] and NOTE_INTERDIALYTIC not in s["notes"]
    assert client.get("/api/profile").json()["dialysis_days"] == [1, 3, 5]


# --------------------------------------------------------------------------- #
# Saved meals
# --------------------------------------------------------------------------- #


def test_meal_crud_shape_and_alphabetical_list(client):
    egg = find_food(client, "egg white")
    chicken = find_food(client, "chicken")
    r = client.post("/api/meals", json={"name": "Zed meal", "note": "", "items": [{"food_id": egg["id"], "servings": 2}, {"food_id": chicken["id"], "servings": 1}]})
    assert r.status_code == 201, r.text
    meal = r.json()
    assert meal["name"] == "Zed meal" and meal["note"] is None and meal["kidney_rating"] == "red"
    assert meal["created_at"].endswith("Z") and meal["updated_at"].endswith("Z")
    item = meal["items"][0]
    assert item == {
        "food_id": egg["id"], "food_name": "Egg white, raw", "servings": 2, "serving_desc": "1 large (33 g)",
        "nutrients": item["nutrients"], "kidney_rating": "yellow", "hidden": False,
    }
    assert item["nutrients"]["protein_g"] == 7.2 and item["nutrients"]["potassium_mg"] == 108
    assert meal["items"][1]["kidney_rating"] == "red" and meal["items"][1]["nutrients"]["protein_g"] == 26.4
    assert meal["totals"]["protein_g"] == 33.6 and meal["totals"]["potassium_mg"] == 108 + 218
    assert set(meal["totals"]) == set(NUTRIENT_KEYS)

    apple = find_food(client, "apple, raw")
    client.post("/api/meals", json={"name": "alpha", "items": [{"food_id": apple["id"], "servings": 1}]})
    client.post("/api/meals", json={"name": "Beta", "note": "with tea", "items": [{"food_id": find_food(client, "water")["id"], "servings": 1}]})
    names = [m["name"] for m in client.get("/api/meals").json()["meals"]]
    assert names == ["alpha", "Beta", "Zed meal"]

    assert client.get(f"/api/meals/{meal['id']}").json() == meal

    r = client.put(f"/api/meals/{meal['id']}", json={"name": "Zed v2", "note": "lighter", "items": [{"food_id": apple["id"], "servings": 1.5}]})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["id"] == meal["id"] and updated["name"] == "Zed v2" and updated["note"] == "lighter"
    assert len(updated["items"]) == 1 and updated["items"][0]["servings"] == 1.5
    assert updated["totals"]["potassium_mg"] == 293 and updated["kidney_rating"] == "red"  # 195 × 1.5 = 292.5 → 293 mg, > 200 is high
    assert updated["created_at"] == meal["created_at"] and updated["updated_at"] >= meal["updated_at"]

    assert client.delete(f"/api/meals/{meal['id']}").status_code == 204
    assert client.get(f"/api/meals/{meal['id']}").status_code == 404
    assert client.delete(f"/api/meals/{meal['id']}").status_code == 404
    assert [m["name"] for m in client.get("/api/meals").json()["meals"]] == ["alpha", "Beta"]


def test_meal_validation(client):
    apple = find_food(client, "apple, raw")
    good = [{"food_id": apple["id"], "servings": 1}]
    assert client.post("/api/meals", json={"name": "Empty", "items": []}).status_code == 400
    assert client.post("/api/meals", json={"name": "", "items": good}).status_code == 400
    assert client.post("/api/meals", json={"name": "Zero", "items": [{"food_id": apple["id"], "servings": 0}]}).status_code == 400
    assert client.post("/api/meals", json={"name": "Missing", "items": [{"servings": 1}]}).status_code == 400
    r = client.post("/api/meals", json={"name": "Ghost", "items": [{"food_id": 99999, "servings": 1}]})
    assert r.status_code == 404 and "99999" in r.json()["detail"]
    assert client.get("/api/meals").json()["meals"] == []  # nothing half-created
    assert client.get("/api/meals/4242").status_code == 404
    assert client.put("/api/meals/4242", json={"name": "x", "items": good}).status_code == 404
    assert client.delete("/api/meals/4242").status_code == 404
    assert client.post("/api/meals/4242/apply", json={"date": DAY, "meal": "lunch"}).status_code == 404


def test_meal_from_log_uses_both_statuses_of_that_meal(client):
    log_food(client, "egg white", meal="breakfast", servings=3)
    log_food(client, "water", meal="breakfast", status="planned")
    log_food(client, "banana", meal="lunch")
    r = client.post("/api/meals/from-log", json={"date": DAY, "meal": "breakfast", "name": "Usual breakfast", "note": "weekdays"})
    assert r.status_code == 201, r.text
    meal = r.json()
    assert meal["name"] == "Usual breakfast" and meal["note"] == "weekdays"
    assert [(i["food_name"], i["servings"]) for i in meal["items"]] == [("Egg white, raw", 3), ("Water, tap", 1)]
    assert meal["totals"]["fluid_ml"] == 240 and meal["totals"]["protein_g"] == 10.8
    r = client.post("/api/meals/from-log", json={"date": DAY, "meal": "dinner", "name": "Nothing"})
    assert r.status_code == 400 and "dinner" in r.json()["detail"]
    assert client.post("/api/meals/from-log", json={"date": DAY, "meal": "breakfast", "name": ""}).status_code == 400


def test_meal_apply_creates_entries_with_status_and_scale(client):
    egg = find_food(client, "egg white")
    banana = find_food(client, "banana")
    meal = client.post("/api/meals", json={"name": "Snack box", "items": [{"food_id": egg["id"], "servings": 2}, {"food_id": banana["id"], "servings": 0.5}]}).json()

    r = client.post(f"/api/meals/{meal['id']}/apply", json={"date": TOMORROW, "meal": "snack"})
    assert r.status_code == 201, r.text
    entries = r.json()["entries"]
    assert len(entries) == 2 and all(e["status"] == "planned" and e["date"] == TOMORROW and e["meal"] == "snack" for e in entries)
    assert [(e["food_name"], e["servings"]) for e in entries] == [("Egg white, raw", 2), ("Banana, raw", 0.5)]
    assert entries[1]["nutrients"]["potassium_mg"] == 211 and entries[1]["grams"] is None
    assert client.get("/api/log", params={"date": TOMORROW}).json()["counts"] == {"eaten": 0, "planned": 2}

    r = client.post(f"/api/meals/{meal['id']}/apply", json={"date": DAY, "meal": "lunch", "status": "eaten", "scale": 2})
    entries = r.json()["entries"]
    assert all(e["status"] == "eaten" for e in entries)
    assert [e["servings"] for e in entries] == [4, 1] and entries[1]["nutrients"]["potassium_mg"] == 422
    assert client.get("/api/log", params={"date": DAY}).json()["totals"]["protein_g"] == round(4 * 3.6 + 1.29, 1)

    assert client.post(f"/api/meals/{meal['id']}/apply", json={"date": DAY, "meal": "lunch", "scale": 0}).status_code == 400
    assert client.post(f"/api/meals/{meal['id']}/apply", json={"date": DAY, "meal": "tea"}).status_code == 400
    assert client.post(f"/api/meals/{meal['id']}/apply", json={"meal": "lunch"}).status_code == 400


def test_meal_keeps_hidden_food_and_apply_still_works(client):
    sauce = client.post("/api/foods", json={"name": "Secret sauce", "serving_desc": "1 tbsp (15 g)", "serving_g": 15, "nutrients": {"sodium_mg": 500}}).json()
    meal = client.post("/api/meals", json={"name": "Saucy", "items": [{"food_id": sauce["id"], "servings": 2}]}).json()
    assert meal["items"][0]["hidden"] is False and meal["totals"]["sodium_mg"] == 1000

    # deleting a food that only a saved meal references hides it instead of removing it
    assert client.delete(f"/api/foods/{sauce['id']}").status_code == 204
    assert client.get(f"/api/foods/{sauce['id']}").json()["hidden"] is True
    assert client.get("/api/foods", params={"q": "secret"}).json()["foods"] == []

    meal = client.get(f"/api/meals/{meal['id']}").json()
    assert meal["items"][0] == {**meal["items"][0], "food_name": "Secret sauce", "hidden": True, "kidney_rating": "red"}
    assert meal["totals"]["sodium_mg"] == 1000 and meal["kidney_rating"] == "red"
    r = client.post(f"/api/meals/{meal['id']}/apply", json={"date": DAY, "meal": "dinner", "status": "eaten"})
    assert r.status_code == 201
    assert r.json()["entries"][0]["food_id"] == sauce["id"] and r.json()["entries"][0]["nutrients"]["sodium_mg"] == 1000
    assert client.get("/api/log", params={"date": DAY}).json()["totals"]["sodium_mg"] == 1000


def test_delete_unreferenced_custom_food_still_removes_it(client):
    tmp = client.post("/api/foods", json={"name": "Temp", "serving_desc": "1", "serving_g": 10, "nutrients": {}}).json()
    assert client.delete(f"/api/foods/{tmp['id']}").status_code == 204
    assert client.get(f"/api/foods/{tmp['id']}").status_code == 404


# --------------------------------------------------------------------------- #
# Shopping list
# --------------------------------------------------------------------------- #


def test_shopping_list_aggregates_planned_entries_by_food(client):
    log_food(client, "banana", date=DAY, status="planned")
    log_food(client, "banana", date=TOMORROW, servings=2, meal="dinner", status="planned")
    log_food(client, "water", date=TOMORROW, status="planned")
    log_food(client, "banana", date=DAY)  # eaten: not on the list
    log_food(client, "apple", date="2026-10-08", status="planned")  # outside the range

    r = client.get("/api/plan/shopping", params={"start": DAY, "end": NEXT_DAY})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    banana = find_food(client, "banana")
    assert items == [
        {"food_id": banana["id"], "food_name": "Banana, raw", "serving_desc": "1 medium (118 g)", "servings": 3, "grams": 354.0, "days": 2},
        {"food_id": find_food(client, "water")["id"], "food_name": "Water, tap", "serving_desc": "1 cup (240 g)", "servings": 1, "grams": 240.0, "days": 1},
    ]
    assert client.get("/api/plan/shopping", params={"start": "2030-01-01", "end": "2030-01-07"}).json() == {"items": []}
    assert client.get("/api/plan/shopping", params={"start": DAY}).status_code == 400
    assert client.get("/api/plan/shopping", params={"start": NEXT_DAY, "end": DAY}).status_code == 400
    assert client.get("/api/plan/shopping", params={"start": "2020-01-01", "end": NEXT_DAY}).status_code == 400


def test_shopping_list_is_emptied_by_marking_eaten(client):
    log_food(client, "banana", date=DAY, status="planned")
    assert len(client.get("/api/plan/shopping", params={"start": DAY, "end": DAY}).json()["items"]) == 1
    client.post("/api/log/mark-eaten", json={"date": DAY})
    assert client.get("/api/plan/shopping", params={"start": DAY, "end": DAY}).json()["items"] == []


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def test_new_endpoints_are_registered(client):
    # /openapi.json is not served unless ENABLE_API_DOCS=true (note 01 §5.5); read the schema directly.
    paths = client.app.openapi()["paths"]
    for path in (
        "/api/log/summary", "/api/log/mark-eaten", "/api/log/copy-day",
        "/api/meals", "/api/meals/from-log", "/api/meals/{meal_id}", "/api/meals/{meal_id}/apply",
        "/api/plan/shopping",
    ):
        assert path in paths, path
    from app.main import APP_VERSION

    assert client.app.version == APP_VERSION
    assert client.get("/healthz").status_code == 200


# --------------------------------------------------------------------------- #
# Fixes after review: numeric bounds on saved meals
# --------------------------------------------------------------------------- #


def test_meal_items_and_apply_scale_are_bounded_and_finite(client):
    apple = find_food(client, "apple, raw")
    for servings in (1e308, float("inf"), float("nan"), 1001):
        r = send_json(client, "POST", "/api/meals", {"name": "Big", "items": [{"food_id": apple["id"], "servings": servings}]})
        assert r.status_code == 400, r.text
    assert client.post("/api/meals", json={"name": "Ghost", "items": [{"food_id": 10**20, "servings": 1}]}).status_code == 400
    meal = client.post("/api/meals", json={"name": "Snack", "items": [{"food_id": apple["id"], "servings": 1}]}).json()
    for scale in (1e308, float("inf"), 101):
        assert send_json(client, "POST", f"/api/meals/{meal['id']}/apply", {"date": DAY, "meal": "snack", "scale": scale}).status_code == 400
    assert client.get("/api/meals/99999999999999999999").status_code == 404
    assert client.post("/api/meals/99999999999999999999/apply", json={"date": DAY, "meal": "snack"}).status_code == 404
    assert client.get("/api/log", params={"date": DAY}).json()["entries"] == []
