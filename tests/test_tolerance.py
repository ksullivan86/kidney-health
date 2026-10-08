"""v0.3.1 item 2 (docs/dev/plans/v0.3.1.md): adjustable tolerance.

* Today's per-meal carbohydrate alert fires only more than the person's carbohydrate tolerance
  (``guidance.carb_tolerance_g``, 5–20 g, default 10: Smart et al. 2009/2012, note 06 F4) above the meal's goal,
  the same number meal guidance uses. Carbohydrate eaten to treat a low is left out of the meal's goal (it still
  counts in every total): treating a low is never warned against.
* An "about" target (minimum = maximum, such as protein "about 56 g") is "over" only above the person's
  ``about_tolerance_pct`` (Profile, schema step 9, 0–10 %, default 0 = the number itself). Alerts call it a
  "target". Limits and real ranges are unchanged.
* The demo's twin (``js/mock/log.js`` over ``js/engine/rules.js``) answers the same.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app import db, migrations
from app import nutrients as n
from app.log import day_figures
from app.migrations import m009_about_tolerance as m009
from app.models import Alert, NutrientStatus
from app.nutrients import NUTRIENT_KEYS
from app.periods import summarize_period
from conftest import insert_users

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "demo_log_twin.mjs"
DAY = "2026-10-06"
NOW = "2026-10-05T08:00:00.000000Z"


# --------------------------------------------------------------------------- #
# Per-meal carbohydrate: tolerance and low treatments
# --------------------------------------------------------------------------- #


def test_the_per_meal_alert_waits_for_the_tolerance():
    meals = {"breakfast": {"carbs_g": 70}, "lunch": {"carbs_g": 70.1}, "dinner": {"carbs_g": 60.6}, "snack": {}}
    alerts = n.meal_carb_alerts(meals, 60, tolerance_g=10)
    assert [a["meal"] for a in alerts] == ["lunch"]  # 70 g is exactly 10 g over: still on target
    assert alerts[0] == {"level": "over", "nutrient": "carbs_g", "meal": "lunch",
                         "message": "Lunch carbohydrate is more than 10 g over the per-meal goal: 70.1 / 60 g"}
    # the plan's "close to your goal" dinner (60.6 g for 60 g) no longer shows "Projected over" (REVIEW.md A4)
    projected = n.projected_meal_carb_alerts(meals, 60, tolerance_g=10)
    assert [a["message"] for a in projected] == [
        "If you eat what's planned, lunch carbohydrate reaches 70.1 / 60 g (more than 10 g over the per-meal goal)"]
    # without a tolerance (direct callers, old behaviour) the goal itself is the line
    assert [a["meal"] for a in n.meal_carb_alerts(meals, 60)] == ["breakfast", "lunch", "dinner"]
    # a smaller tolerance from the diabetes team
    assert [a["meal"] for a in n.meal_carb_alerts(meals, 60, tolerance_g=5)] == ["breakfast", "lunch"]


@pytest.mark.parametrize("bad", [None, "x", float("nan"), float("inf"), -5, 0])
def test_an_unusable_tolerance_is_the_goal_itself(bad):
    assert n.carb_tolerance(bad) == 0.0
    assert [a["meal"] for a in n.meal_carb_alerts({"dinner": {"carbs_g": 61}}, 60, tolerance_g=bad)] == ["dinner"]


def test_carbohydrate_that_treated_a_low_is_left_out_of_the_meal():
    meals = {"breakfast": {}, "lunch": {}, "dinner": {}, "snack": {"carbs_g": 45}}
    # 15 g glucose for a low + 30 g of other snacks, against a 15 g snack goal and a 10 g tolerance
    alerts = n.meal_carb_alerts(meals, 60, 15, tolerance_g=10, hypo_carbs={"snack": 15})
    assert [a["message"] for a in alerts] == [
        "Snack carbohydrate is more than 10 g over the snack goal: 30 / 15 g (not counting 15 g used to treat a low)"]
    projected = n.projected_meal_carb_alerts(meals, 60, 15, tolerance_g=10, hypo_carbs={"snack": 15})
    assert [a["message"] for a in projected] == [
        "If you eat what's planned, snack carbohydrate reaches 30 / 15 g "
        "(more than 10 g over the snack goal; not counting 15 g used to treat a low)"]
    # a meal that is only a low treatment is never "over", whatever its size and whatever the tolerance
    only_low = {"snack": {"carbs_g": 40}}
    assert n.meal_carb_alerts(only_low, 60, 15, hypo_carbs={"snack": 40}) == []
    assert n.projected_meal_carb_alerts(only_low, 60, 15, hypo_carbs={"snack": 40}) == []


# --------------------------------------------------------------------------- #
# "About" targets
# --------------------------------------------------------------------------- #

ABOUT = {"protein_g": {"min": 56, "max": 56}, "potassium_mg": 2500, "sodium_mg": {"min": 1500, "max": 2000}}


def test_about_target_is_over_only_above_the_tolerance():
    totals = {"protein_g": 58, "potassium_mg": 2510, "sodium_mg": 2010}  # 103.6 %, 100.4 %, 100.5 %
    assert {k: v["level"] for k, v in n.daily_status(totals, ABOUT, 0.8).items()} == {
        "protein_g": "over", "potassium_mg": "over", "sodium_mg": "over"}
    with_tol = n.daily_status(totals, ABOUT, 0.8, 5)
    # only the "about" target moves; a limit and a real range keep their line
    assert {k: v["level"] for k, v in with_tol.items()} == {"protein_g": "caution", "potassium_mg": "over", "sodium_mg": "over"}
    assert with_tol["protein_g"]["fraction"] == 1.04  # the number is still reported as it is
    assert n.daily_status({"protein_g": 59}, ABOUT, 0.8, 5)["protein_g"]["level"] == "over"  # 105.4 %
    assert n.daily_status({"protein_g": 58.8}, ABOUT, 0.8, 5)["protein_g"]["level"] == "caution"  # exactly 105 %


def test_a_limit_never_gets_the_tolerance_even_entered_as_min_equals_max():
    targets = {"potassium_mg": {"min": 2500, "max": 2500}, "sodium_mg": {"min": 2000, "max": 2000}}
    status = n.daily_status({"potassium_mg": 2550, "sodium_mg": 2050}, targets, 0.8, 10)
    assert {k: v["level"] for k, v in status.items()} == {"potassium_mg": "over", "sodium_mg": "over"}
    assert not n.is_about("potassium_mg", 2500, 2500) and n.over_at("fluid_ml", 1500, 1500, 10) == 1.0
    assert [a["message"] for a in n.build_alerts(status)] == [
        "Sodium is over today's limit: 2050 / 2000 mg (102 %)", "Potassium is over today's limit: 2550 / 2500 mg (102 %)"]


def test_alerts_call_an_about_target_a_target():
    status = n.daily_status({"protein_g": 58, "sodium_mg": 2100}, ABOUT, 0.8, 5)
    alerts = {a["nutrient"]: a for a in n.build_alerts(status)}
    assert alerts["protein_g"]["message"] == "Protein is at 104 % of today's target (58 / 56 g)"
    assert alerts["sodium_mg"]["message"] == "Sodium is over today's limit: 2100 / 2000 mg (105 %)"  # by its role
    over = n.build_alerts(n.daily_status({"protein_g": 60}, ABOUT, 0.8, 5))
    assert over[0]["message"] == "Protein is over today's target: 60 / 56 g (107 %)"
    projected = n.build_projected_alerts(n.daily_status({"protein_g": 60}, ABOUT, 0.8))
    assert projected[0]["message"] == "If you eat what's planned, protein reaches 107 % of today's target (60 / 56 g)"


@pytest.mark.parametrize(("pct", "expected"), [(0, 0.0), (5, 5.0), (10, 10.0), (11, 10.0), (-1, 0.0), (None, 0.0),
                                               ("x", 0.0), (float("nan"), 0.0), (float("inf"), 0.0)])
def test_about_tolerance_is_clamped(pct, expected):
    assert n.about_tolerance(pct) == expected


def test_about_is_judged_on_the_rounded_bounds_like_the_ui():
    assert n.is_about("protein_g", 55.96, 56.04)  # both show as 56.0
    assert not n.is_about("protein_g", 50, 56)
    assert not n.is_about("protein_g", None, 56)
    assert not n.is_about("protein_g", 56, float("inf"))
    assert n.over_at("protein_g", 56, 56, 5) == 1.05 and n.over_at("protein_g", 50, 56, 5) == 1.0


def test_period_summary_uses_the_tolerance_for_about_targets():
    days = {"2026-10-01": {"protein_g": 58, "potassium_mg": 2600}, "2026-10-02": {"protein_g": 60, "potassium_mg": 2400}}
    plain = summarize_period("2026-10-01", "2026-10-02", days, ABOUT, 0.8)
    assert plain["nutrients"]["protein_g"]["days_over"] == 2 and plain["nutrients"]["protein_g"]["level"] == "over"
    tol = summarize_period("2026-10-01", "2026-10-02", days, ABOUT, 0.8, about_tolerance_pct=5)
    assert tol["nutrients"]["protein_g"]["days_over"] == 1  # 58 g is within 5 %, 60 g is not
    assert tol["nutrients"]["protein_g"]["level"] == "caution"  # average 59 g = 105.36 %, reported as 1.05
    assert tol["nutrients"]["potassium_mg"] == plain["nutrients"]["potassium_mg"]  # a limit is unchanged


# --------------------------------------------------------------------------- #
# Schema step 9 and the profile field
# --------------------------------------------------------------------------- #


def test_step_9_adds_the_column_with_default_zero_and_is_idempotent(tmp_path):
    steps = migrations.steps()
    assert [s.version for s in steps][:9] == list(range(1, 10))
    assert steps[8].name == "m009_about_tolerance" and steps[8].atomic and steps[8].schema == ""
    conn = db.connect(tmp_path / "kidney.db")
    assert db.migrate(conn, steps[:8]) == list(range(1, 9))
    insert_users(conn, [(1, "admin")])
    conn.execute("INSERT INTO user_profiles (user_id, updated_at, updated_by) VALUES (1, ?, 1)", (NOW,))
    conn.commit()
    assert "about_tolerance_pct" not in db.table_columns(conn, "user_profiles")
    assert db.migrate(conn, steps[:9]) == [9]
    assert conn.execute("SELECT about_tolerance_pct FROM user_profiles WHERE user_id = 1").fetchone()[0] == 0
    m009.migrate(conn)  # a re-run changes nothing
    conn.commit()
    assert conn.execute("SELECT about_tolerance_pct FROM user_profiles WHERE user_id = 1").fetchone()[0] == 0
    conn.close()


def test_profile_tolerance_round_trip_and_limits(client):
    assert client.get("/api/profile").json()["about_tolerance_pct"] == 0
    assert client.put("/api/profile", json={"about_tolerance_pct": 5}).json()["about_tolerance_pct"] == 5
    assert client.put("/api/profile", json={"weight_kg": 70}).json()["about_tolerance_pct"] == 5  # left out: kept
    for bad in (11, -1, 2.5, "lots"):
        assert client.put("/api/profile", json={"about_tolerance_pct": bad}).status_code == 400, bad
    assert client.put("/api/profile", json={"about_tolerance_pct": None}).json()["about_tolerance_pct"] == 0  # null: reset


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #


def _quick(client, meal: str, carbs: float, *, purpose: str | None = None, name: str = "Food", status: str = "eaten",
           protein: float = 0) -> dict[str, Any]:
    body: dict[str, Any] = {"date": DAY, "meal": meal, "name": name, "status": status,
                            "nutrients": {"carbs_g": carbs, "protein_g": protein}}
    if purpose:
        body["purpose"] = purpose
    r = client.post("/api/log/quick", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_today_uses_the_tolerance_from_the_guidance_settings(client):
    client.put("/api/profile", json={"targets": {"carbs_per_meal_g": 60, "carbs_per_snack_g": 15}})
    _quick(client, "breakfast", 68)
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["carb_tolerance_g"] == 10  # the registry default
    assert [a for a in day["alerts"] if a["nutrient"] == "carbs_g"] == []
    assert client.patch("/api/me/settings", json={"guidance": {"carb_tolerance_g": 5}}).status_code == 200
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["carb_tolerance_g"] == 5
    assert [a["message"] for a in day["alerts"] if a["nutrient"] == "carbs_g"] == [
        "Breakfast carbohydrate is more than 5 g over the per-meal goal: 68 / 60 g"]


def test_a_low_treatment_never_makes_a_meal_over(client):
    client.put("/api/profile", json={"targets": {"carbs_per_meal_g": 60, "carbs_per_snack_g": 15}})
    _quick(client, "snack", 20, purpose="hypo", name="Glucose tablets")
    _quick(client, "snack", 20, purpose="hypo", name="Juice")  # a second treatment for the same low
    _quick(client, "snack", 10, name="Crackers")
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["meals"]["snack"]["carbs_g"] == 50  # the total still counts what was eaten
    assert [a for a in day["alerts"] if a["nutrient"] == "carbs_g"] == []
    _quick(client, "snack", 20, name="Biscuit", status="planned")
    day = client.get("/api/log", params={"date": DAY}).json()
    assert [a["message"] for a in day["projected_alerts"] if a["nutrient"] == "carbs_g"] == [
        "If you eat what's planned, snack carbohydrate reaches 30 / 15 g "
        "(more than 10 g over the snack goal; not counting 40 g used to treat a low)"]


def test_about_target_tolerance_reaches_today_and_the_summary(client):
    client.put("/api/profile", json={"targets": {"protein_g": {"min": 56, "max": 56}}})
    _quick(client, "lunch", 0, protein=58)
    assert client.get("/api/log", params={"date": DAY}).json()["status"]["protein_g"]["level"] == "over"
    client.put("/api/profile", json={"about_tolerance_pct": 5})
    day = client.get("/api/log", params={"date": DAY}).json()
    assert day["status"]["protein_g"]["level"] == "caution"
    assert [a["message"] for a in day["alerts"]] == ["Protein is at 104 % of today's target (58 / 56 g)"]
    summary = client.get("/api/log/summary", params={"start": DAY, "end": DAY}).json()
    assert summary["nutrients"]["protein_g"]["days_over"] == 0 and summary["nutrients"]["protein_g"]["level"] == "caution"


# --------------------------------------------------------------------------- #
# The demo's twin answers the same
# --------------------------------------------------------------------------- #

PROFILE = {"targets": {"potassium_mg": 2500, "sodium_mg": 2000, "protein_g": {"min": 56, "max": 56},
                       "carbs_per_meal_g": 60, "carbs_per_snack_g": 15},
           "warn_fraction": 0.8, "about_tolerance_pct": 5, "dialysis": "none", "dialysis_days": []}


def _nutrients(**values: float) -> dict[str, float | None]:
    return {key: values.get(key, 0) for key in NUTRIENT_KEYS}


ROWS = [
    {"status": "eaten", "meal": "breakfast", "purpose": None, **_nutrients(carbs_g=68.4, protein_g=20)},
    {"status": "eaten", "meal": "lunch", "purpose": None, **_nutrients(carbs_g=71.25, protein_g=38.5)},
    {"status": "eaten", "meal": "snack", "purpose": "hypo", **_nutrients(carbs_g=15)},
    {"status": "eaten", "meal": "snack", "purpose": None, **_nutrients(carbs_g=26.3)},
    {"status": "planned", "meal": "dinner", "purpose": None, **_nutrients(carbs_g=70.2, protein_g=2)},
    {"status": "planned", "meal": "snack", "purpose": "hypo", **_nutrients(carbs_g=16)},
]


def _js(payload: dict[str, Any]) -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the demo's twin (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _as_served(figures: dict[str, Any]) -> dict[str, Any]:
    """The day figures as the API serves them: each status item and alert through its response model."""
    out = json.loads(json.dumps(figures))
    for key in ("status", "projected_status"):
        out[key] = {k: NutrientStatus(**v).model_dump(mode="json") for k, v in out[key].items()}
    for key in ("alerts", "projected_alerts"):
        out[key] = [Alert(**a).model_dump(mode="json") for a in out[key]]
    return out


@pytest.mark.parametrize("tolerance", [0, 5, 10, 20])
def test_the_demo_twin_matches_the_server(tolerance):
    py = day_figures(ROWS, PROFILE, tolerance)
    js = _js({"profile": PROFILE, "carb_tolerance_g": tolerance,
              "rows": [{"status": r["status"], "meal": r["meal"], "purpose": r["purpose"], "nutrients": {k: r[k] for k in NUTRIENT_KEYS}}
                       for r in ROWS]})["day"]
    assert _as_served(py) == js
    if tolerance == 10:
        assert [a["meal"] for a in js["alerts"] if a["nutrient"] == "carbs_g"] == ["lunch", "snack"]
        assert js["status"]["protein_g"]["level"] == "caution"  # 58.5 g against about 56 g, within 5 %


def test_the_demo_twin_summary_matches_the_server():
    entries = [
        {"id": 1, "date": "2026-10-01", "meal": "lunch", "status": "eaten", "nutrients": _nutrients(protein_g=58),
         "created_at": "2026-10-01T00:00:01Z"},
        {"id": 2, "date": "2026-10-02", "meal": "lunch", "status": "eaten", "nutrients": _nutrients(protein_g=60),
         "created_at": "2026-10-02T00:00:01Z"},
    ]
    js = _js({"profile": PROFILE, "entries": entries, "summary": ["2026-10-01", "2026-10-02"]})["summary"]
    days = {"2026-10-01": _nutrients(protein_g=58), "2026-10-02": _nutrients(protein_g=60)}
    py = summarize_period(date(2026, 10, 1), date(2026, 10, 2), days, PROFILE["targets"], 0.8,
                          about_tolerance_pct=PROFILE["about_tolerance_pct"])
    assert js["nutrients"] == json.loads(json.dumps(py["nutrients"]))
    assert js["nutrients"]["protein_g"]["days_over"] == 1
