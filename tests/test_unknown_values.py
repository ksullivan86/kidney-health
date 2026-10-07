"""An unknown nutrient value is never a silent 0 (review C8; note 03 R7 and F1; note 06 R4).

Most scanned foods have no potassium or phosphorus value. A total adds only what is known, so every
total, meal sum, status item, range day and period figure comes with how many entries it misses;
the app shows "+ n not listed" instead of a complete-looking number. No network: fixture foods."""
from __future__ import annotations

from typing import Any

from app import nutrients as N
from app.periods import interdialytic_block, summarize_period
from conftest import log_food

DAY = "2026-10-05"


def custom_food(client: Any, name: str, **nutrients: float | None) -> dict[str, Any]:
    body = {"name": name, "serving_desc": "1 serving (100 g)", "serving_g": 100, "nutrients": nutrients}
    r = client.post("/api/foods", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def log_id(client: Any, food: dict[str, Any], meal: str, servings: float = 1, date: str = DAY, **extra: Any) -> dict[str, Any]:
    r = client.post("/api/log", json={"date": date, "meal": meal, "food_id": food["id"], "servings": servings, **extra})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- pure helpers


def test_count_unknown_counts_only_missing_values_and_merges():
    known = {key: 1.0 for key in N.NUTRIENT_KEYS}
    acc: dict[str, int] = {}
    N.count_unknown(acc, {**known, "potassium_mg": None, "phosphorus_mg": 10, "sodium_mg": 0})
    N.count_unknown(acc, {**known, "potassium_mg": None, "phosphorus_mg": None, "sodium_mg": 5})
    assert acc == {"potassium_mg": 2, "phosphorus_mg": 1}  # 0 is a known value, not an unknown one
    N.count_unknown(acc, {"calories_kcal": 5})  # a missing key is unknown too
    assert acc["potassium_mg"] == 3 and acc["fluid_ml"] == 1 and "calories_kcal" not in acc
    assert N.merge_unknown({"potassium_mg": 2}, {"potassium_mg": 1, "fluid_ml": 2}, {}) == {"potassium_mg": 3, "fluid_ml": 2}
    status = N.mark_unknown(N.daily_status({"potassium_mg": 1033.0, "sodium_mg": 300.0},
                                           {"potassium_mg": 2500, "sodium_mg": 2000}), {"potassium_mg": 2})
    assert status["potassium_mg"]["unknown"] == 2 and status["potassium_mg"]["level"] == "ok"  # level kept
    assert status["sodium_mg"]["unknown"] == 0


def test_period_and_interdialytic_figures_say_how_many_entries_they_miss():
    totals = {"2026-10-01": {"potassium_mg": 1000.0}, "2026-10-02": {"potassium_mg": 0.0}, "2026-09-25": {"potassium_mg": 900.0}}
    unknown = {"2026-10-01": {"potassium_mg": 2}, "2026-10-02": {"potassium_mg": 1, "phosphorus_mg": 1},
               "2026-09-25": {"potassium_mg": 5}}  # previous period: not counted
    s = summarize_period("2026-09-29", "2026-10-05", totals, {"potassium_mg": 2500, "phosphorus_mg": 1000}, day_unknown=unknown)
    assert (s["nutrients"]["potassium_mg"]["unknown_entries"], s["nutrients"]["potassium_mg"]["unknown_days"]) == (3, 2)
    assert (s["nutrients"]["phosphorus_mg"]["unknown_entries"], s["nutrients"]["phosphorus_mg"]["unknown_days"]) == (1, 1)
    plain = summarize_period("2026-09-29", "2026-10-05", totals, {"potassium_mg": 2500})
    assert plain["nutrients"]["potassium_mg"]["unknown_entries"] == 0  # no counts given: nothing claimed
    interval = {"since": "2026-10-01", "end": "2026-10-02", "days": 2, "next": "2026-10-03"}
    block = interdialytic_block(interval, totals, {"potassium_mg": 2000}, day_unknown=unknown)
    assert block["nutrients"]["potassium_mg"]["unknown_entries"] == 3


# --------------------------------------------------------------------------- the API


def test_day_summary_counts_entries_without_a_value_per_day_meal_and_status(client):
    client.put("/api/profile", json={"targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000}})
    # Lunch: a quick-add drink with a potassium additive but no potassium value, and a scanned soda
    # that lists neither; dinner: a food with potassium but no phosphorus. Breakfast: all known.
    salt_sub = custom_food(client, "Electrolyte drink", sodium_mg=100, potassium_mg=None, phosphorus_mg=None)
    soda = custom_food(client, "Diet cola", sodium_mg=40)
    mac = custom_food(client, "Mac and cheese, prepared", potassium_mg=370, sodium_mg=710, phosphorus_mg=None)
    log_food(client, "banana", meal="breakfast")
    log_id(client, salt_sub, "lunch", servings=2)
    log_id(client, soda, "lunch")
    log_id(client, mac, "dinner")
    log_id(client, soda, "snack", status="planned")

    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["totals"]["potassium_mg"] == 422 + 370  # banana + mac: only what is known
    assert day["unknown"]["potassium_mg"] == 2 and day["unknown"]["phosphorus_mg"] == 3
    assert "sodium_mg" not in day["unknown"]  # every sodium value is known
    assert day["meals"]["lunch"]["potassium_mg"] == 0  # a 0 total ...
    lunch = day["meal_unknown"]["lunch"]
    assert lunch["potassium_mg"] == 2 and lunch["phosphorus_mg"] == 2 and "sodium_mg" not in lunch and "fluid_ml" not in lunch
    assert day["meal_unknown"]["breakfast"] == {}  # ... is "not listed" only where the count says so
    assert day["meal_unknown"]["dinner"]["phosphorus_mg"] == 1 and "potassium_mg" not in day["meal_unknown"]["dinner"]
    assert day["status"]["potassium_mg"]["unknown"] == 2 and day["status"]["phosphorus_mg"]["unknown"] == 3
    assert day["status"]["sodium_mg"]["unknown"] == 0
    assert day["status"]["phosphorus_mg"]["level"] == "ok"  # judged on what is known; the count marks it incomplete
    # Planned entries are counted apart, and in the projection.
    assert day["planned_unknown"]["potassium_mg"] == 1 and day["planned_meal_unknown"]["snack"]["potassium_mg"] == 1
    assert day["projected_unknown"]["potassium_mg"] == 3 and day["projected_status"]["potassium_mg"]["unknown"] == 3

    days = client.get("/api/log/range", params={"start": DAY, "end": DAY}).json()["days"]
    assert days[0]["unknown"] == day["unknown"] and days[0]["projected_unknown"] == day["projected_unknown"]
    assert days[0]["status"]["potassium_mg"]["unknown"] == 2

    s = client.get("/api/log/summary", params={"start": "2026-09-29", "end": DAY}).json()
    k = s["nutrients"]["potassium_mg"]
    assert (k["unknown_entries"], k["unknown_days"]) == (2, 1)  # the planned soda is not eaten
    assert s["nutrients"]["sodium_mg"]["unknown_entries"] == 0


def test_a_day_with_every_value_known_reports_no_unknowns(client):
    client.put("/api/profile", json={"targets": {"potassium_mg": 2500}})
    log_food(client, "banana")
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["unknown"] == {} and day["projected_unknown"] == {} and day["planned_unknown"] == {}
    assert all(v == {} for v in day["meal_unknown"].values()) and day["status"]["potassium_mg"]["unknown"] == 0
    empty = client.get("/api/log", params={"date": "2026-10-04"}).json()
    assert empty["unknown"] == {} and set(empty["meal_unknown"]) == {"breakfast", "lunch", "dinner", "snack"}


def test_the_interdialytic_block_counts_unknown_entries(client):
    client.put("/api/profile", json={"dialysis": "hemodialysis", "dialysis_days": [0, 2, 4],
                                     "targets": {"potassium_mg": 2000, "sodium_mg": 2000, "fluid_ml": 1500}})
    soda = custom_food(client, "Diet cola", sodium_mg=40)
    log_id(client, soda, "lunch", date="2026-10-03")
    log_id(client, soda, "lunch", date="2026-10-04")
    s = client.get("/api/log/summary", params={"start": "2026-09-28", "end": "2026-10-04"}).json()
    iv = s["interdialytic"]["nutrients"]
    assert iv["potassium_mg"]["unknown_entries"] == 2 and iv["sodium_mg"]["unknown_entries"] == 0
