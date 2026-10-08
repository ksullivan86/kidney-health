"""v0.3.1 item 4 (docs/dev/plans/v0.3.1.md): "running high" warnings that join the last few days with the plan.

* Potassium, sodium, fluid: the day's total with the plan is over the limit, and so were at least 2 of the 3 days
  before it. On hemodialysis with dialysis days set, the interdialytic interval instead.
* Phosphorus, protein: the average of the logged days of the last 7, with the plan, is over the target.
* Only from today on, only for a day with something planned, only for a nutrient the plan adds; low treatments are
  never named as something to cut; unknown values count as nothing (a known total over the limit stays over).
* The demo's twin (``js/mock/log.js``) answers the same.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app import log as log_module
from app.log import day_pattern_alerts, pattern_inputs
from app.nutrients import NUTRIENT_KEYS
from app.periods import pattern_alerts

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "demo_log_twin.mjs"
TODAY = "2026-10-08"  # a Thursday
LIMITS = {"potassium_mg": 2500, "sodium_mg": 2000, "fluid_ml": 1500, "phosphorus_mg": 1000, "protein_g": {"min": 56, "max": 56}}


def _values(**days: dict[str, float]) -> dict[str, dict[str, float]]:
    return {day.replace("d", "2026-10-0"): values for day, values in days.items()}


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("high_days", "expected"), [(0, None), (1, None), (2, "2 of the last 3 days"), (3, "each of the last 3 days")])
def test_high_days_before_a_planned_day_over(high_days, expected):
    before = ["2026-10-05", "2026-10-06", "2026-10-07"]
    values = {d: {"potassium_mg": 2600 if i < high_days else 2400} for i, d in enumerate(before)}
    values[TODAY] = {"potassium_mg": 2750}
    alerts = pattern_alerts(TODAY, values, {"potassium_mg": 900}, [("Banana", {"potassium_mg": 422})], LIMITS)
    if expected is None:
        assert alerts == []
        return
    assert alerts == [{
        "level": "over", "nutrient": "potassium_mg", "kind": "recent_days",
        "message": f"Potassium was over your limit on {expected}, and with what's planned it goes over again: 2750 / 2500 mg. "
                   "The planned food adding the most: Banana (422 mg)."}]


def test_no_warning_when_the_planned_day_stays_under_or_the_plan_adds_none_of_it():
    values = {"2026-10-06": {"sodium_mg": 2500}, "2026-10-07": {"sodium_mg": 2600}, TODAY: {"sodium_mg": 1900}}
    assert pattern_alerts(TODAY, values, {"sodium_mg": 300}, [], LIMITS) == []  # 1900 < 2000
    values[TODAY] = {"sodium_mg": 2100}
    assert pattern_alerts(TODAY, values, {"sodium_mg": 0}, [], LIMITS) == []  # the plan adds no sodium
    assert pattern_alerts(TODAY, values, {"sodium_mg": 0.5}, [], LIMITS)[0]["kind"] == "recent_days"
    # exactly at the limit is not over
    values = {"2026-10-06": {"fluid_ml": 1500}, "2026-10-07": {"fluid_ml": 1600}, TODAY: {"fluid_ml": 1600}}
    assert pattern_alerts(TODAY, values, {"fluid_ml": 250}, [], LIMITS) == []
    # no limit set: nothing to compare with
    assert pattern_alerts(TODAY, {TODAY: {"potassium_mg": 9000}}, {"potassium_mg": 9000}, [], {}) == []


def test_sources_add_up_per_food_and_name_the_two_largest():
    values = {"2026-10-06": {"potassium_mg": 2600}, "2026-10-07": {"potassium_mg": 2600}, TODAY: {"potassium_mg": 3000}}
    sources = [("Banana", {"potassium_mg": 422}), ("Potato", {"potassium_mg": 610}), ("Banana", {"potassium_mg": 422}),
               ("Rice", {"potassium_mg": 35}), ("Mystery bar", {"potassium_mg": None})]
    message = pattern_alerts(TODAY, values, {"potassium_mg": 1500}, sources, LIMITS)[0]["message"]
    assert message.endswith("The planned foods adding the most: Banana (844 mg) and Potato (610 mg).")


def test_hemodialysis_uses_the_interval_since_the_last_session():
    # dialysis Monday, Wednesday, Friday; Sunday 2026-10-11 closes the long weekend gap that started Friday the 9th
    hd = {"dialysis": "hemodialysis", "dialysis_days": [0, 2, 4]}
    values = {"2026-10-09": {"potassium_mg": 2700}, "2026-10-10": {"potassium_mg": 2600}, "2026-10-11": {"potassium_mg": 2400}}
    alerts = pattern_alerts("2026-10-11", values, {"potassium_mg": 800}, [], LIMITS, **hd)
    assert alerts == [{"level": "over", "nutrient": "potassium_mg", "kind": "interdialytic", "message":
                       "Since your last dialysis day (Friday), potassium adds up to 7700 / 7500 mg with what's planned "
                       "(3 days at 2500 mg)."}]
    # under the interval's limit: nothing, even though two single days were over
    values["2026-10-11"] = {"potassium_mg": 2100}
    assert pattern_alerts("2026-10-11", values, {"potassium_mg": 800}, [], LIMITS, **hd) == []
    # a dialysis day itself is left to the day's own alert
    assert pattern_alerts("2026-10-09", {"2026-10-09": {"potassium_mg": 9000}}, {"potassium_mg": 9000}, [], LIMITS, **hd) == []
    # hemodialysis without dialysis days set: the 3-day rule
    values = {"2026-10-06": {"potassium_mg": 2600}, "2026-10-07": {"potassium_mg": 2600}, TODAY: {"potassium_mg": 2600}}
    alerts = pattern_alerts(TODAY, values, {"potassium_mg": 100}, [], LIMITS, dialysis="hemodialysis", dialysis_days=[])
    assert [a["kind"] for a in alerts] == ["recent_days"]


def test_weekly_average_with_the_plan():
    values = {"2026-10-02": {"phosphorus_mg": 1100}, "2026-10-05": {"phosphorus_mg": 1000}, TODAY: {"phosphorus_mg": 1300}}
    alerts = pattern_alerts(TODAY, values, {"phosphorus_mg": 500}, [("Cheese", {"phosphorus_mg": 500})], LIMITS)
    assert alerts == [{"level": "caution", "nutrient": "phosphorus_mg", "kind": "weekly_average", "message":
                       "With what's planned, phosphorus averages 1133 mg a day over the 3 days you logged this past week, "
                       "above your 1000 mg target. It is judged on the weekly average, so lighter days around it balance it "
                       "out. The planned food adding the most: Cheese (500 mg)."}]
    # fewer than 3 logged days in the window, or a day 7 or more days back: no average to speak of
    assert pattern_alerts(TODAY, {"2026-10-01": {"phosphorus_mg": 3000}, "2026-10-07": {"phosphorus_mg": 1500},
                                  TODAY: {"phosphorus_mg": 1500}}, {"phosphorus_mg": 500}, [], LIMITS) == []
    # an "about" protein target uses the person's tolerance (Profile, v0.3.1)
    values = {"2026-10-06": {"protein_g": 58}, "2026-10-07": {"protein_g": 58}, TODAY: {"protein_g": 58}}
    assert [a["nutrient"] for a in pattern_alerts(TODAY, values, {"protein_g": 20}, [], LIMITS)] == ["protein_g"]
    assert pattern_alerts(TODAY, values, {"protein_g": 20}, [], LIMITS, about_tolerance_pct=5) == []


def test_unknown_values_count_as_nothing():
    values = {"2026-10-06": {"potassium_mg": None}, "2026-10-07": {"potassium_mg": 2600}, TODAY: {"potassium_mg": 2700}}
    assert pattern_alerts(TODAY, values, {"potassium_mg": 200}, [], LIMITS) == []  # only one known high day
    values["2026-10-06"] = {"potassium_mg": float("nan")}
    assert pattern_alerts(TODAY, values, {"potassium_mg": 200}, [], LIMITS) == []


# --------------------------------------------------------------------------- #
# Its inputs: what each day stands for
# --------------------------------------------------------------------------- #


def _row(date: str, status: str, name: str, *, purpose: str | None = None, **nutrients: float) -> dict[str, Any]:
    return {"date": date, "meal": "lunch", "status": status, "purpose": purpose, "food_name": name,
            **{k: nutrients.get(k, 0) for k in NUTRIENT_KEYS}}


PROFILE = {"targets": LIMITS, "dialysis": "none", "dialysis_days": [], "about_tolerance_pct": 0}
ROWS = [
    _row("2026-10-06", "eaten", "Stew", potassium_mg=2600, phosphorus_mg=700),
    _row("2026-10-06", "planned", "Forgotten plan", potassium_mg=900),  # a past plan never eaten: not counted
    _row("2026-10-07", "eaten", "Potato soup", potassium_mg=2700, sodium_mg=1500),
    _row(TODAY, "eaten", "Breakfast", potassium_mg=1200),
    _row(TODAY, "planned", "Banana", potassium_mg=422),
    _row(TODAY, "planned", "Juice", purpose="hypo", potassium_mg=1000, carbs_g=15),  # counted, never named
    _row(TODAY, "planned", "Chicken", potassium_mg=300, phosphorus_mg=250),
    _row("2026-10-09", "planned", "Soup", potassium_mg=2600),
    _row("2026-10-10", "planned", "Soup", potassium_mg=2600),
]


def test_pattern_inputs_take_eaten_before_today_and_the_plan_from_today_on():
    values, planned, sources = pattern_inputs(ROWS, TODAY)
    assert values["2026-10-06"]["potassium_mg"] == 2600 and values[TODAY]["potassium_mg"] == 1200 + 422 + 1000 + 300
    assert planned[TODAY]["potassium_mg"] == 1722 and "2026-10-05" not in values
    assert [name for name, _ in sources[TODAY]] == ["Banana", "Chicken"]
    alerts = day_pattern_alerts(TODAY, (values, planned, sources), PROFILE, TODAY)
    assert [a["kind"] for a in alerts] == ["recent_days"]
    assert alerts[0]["message"].endswith("2922 / 2500 mg. The planned foods adding the most: Banana (422 mg) and Chicken (300 mg).")
    # a future day reads the planned days before it; a past day never warns
    assert [a["nutrient"] for a in day_pattern_alerts("2026-10-11", (values, planned, sources), PROFILE, TODAY)] == []
    assert day_pattern_alerts("2026-10-07", (values, planned, sources), PROFILE, TODAY) == []


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #


def _quick(client, date: str, status: str, potassium: float, name: str = "Food") -> None:
    r = client.post("/api/log/quick", json={"date": date, "meal": "dinner", "name": name, "status": status,
                                            "nutrients": {"potassium_mg": potassium, "carbs_g": 0}})
    assert r.status_code == 201, r.text


def test_today_and_the_week_carry_the_warning(client, monkeypatch):
    monkeypatch.setattr(log_module, "today_local", lambda: TODAY)
    client.put("/api/profile", json={"targets": {"potassium_mg": 2500}})
    _quick(client, "2026-10-06", "eaten", 2600, "Stew")
    _quick(client, "2026-10-07", "eaten", 2700, "Potato soup")
    _quick(client, TODAY, "eaten", 2000, "Breakfast")
    day = client.get("/api/log", params={"date": TODAY}).json()
    assert day["pattern_alerts"] == []  # nothing planned yet
    _quick(client, TODAY, "planned", 700, "Baked potato")
    day = client.get("/api/log", params={"date": TODAY}).json()
    assert [(a["kind"], a["level"], a["nutrient"]) for a in day["pattern_alerts"]] == [("recent_days", "over", "potassium_mg")]
    assert "Baked potato (700 mg)" in day["pattern_alerts"][0]["message"]
    # the week view carries it on the same day only
    week = client.get("/api/log/range", params={"start": "2026-10-05", "end": "2026-10-11"}).json()["days"]
    assert {d["date"]: len(d["pattern_alerts"]) for d in week} == {
        "2026-10-05": 0, "2026-10-06": 0, "2026-10-07": 0, TODAY: 1, "2026-10-09": 0, "2026-10-10": 0, "2026-10-11": 0}
    # a past day never warns, even with a forgotten plan
    _quick(client, "2026-10-07", "planned", 900, "Leftovers")
    assert client.get("/api/log", params={"date": "2026-10-07"}).json()["pattern_alerts"] == []


# --------------------------------------------------------------------------- #
# The demo's twin answers the same
# --------------------------------------------------------------------------- #


def _js(payload: dict[str, Any]) -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the demo's twin (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _js_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"date": r["date"], "meal": r["meal"], "status": r["status"], "purpose": r["purpose"], "food_name": r["food_name"],
             "nutrients": {k: r[k] for k in NUTRIENT_KEYS}} for r in rows]


HD_PROFILE = {**PROFILE, "dialysis": "hemodialysis", "dialysis_days": [0, 2, 4]}
LOW_P_PROFILE = {**PROFILE, "targets": {**LIMITS, "phosphorus_mg": 800}}
SCENARIOS = [(TODAY, PROFILE), ("2026-10-09", PROFILE), ("2026-10-10", PROFILE), ("2026-10-11", PROFILE), ("2026-10-07", PROFILE),
             (TODAY, HD_PROFILE), ("2026-10-10", HD_PROFILE), ("2026-10-11", HD_PROFILE),
             (TODAY, {**PROFILE, "about_tolerance_pct": 5}), (TODAY, LOW_P_PROFILE)]
TWIN_ROWS = ROWS + [_row("2026-10-05", "eaten", "Fish", phosphorus_mg=1400, protein_g=70),
                    _row("2026-10-07", "eaten", "Cheese", phosphorus_mg=900, protein_g=60),
                    _row(TODAY, "planned", "Yogurt", phosphorus_mg=600, protein_g=20)]


def test_the_demo_twin_matches_the_server():
    kinds = set()
    for day, profile in SCENARIOS:
        py = day_pattern_alerts(day, pattern_inputs(TWIN_ROWS, TODAY), profile, TODAY)
        js = _js({"pattern": {"day": day, "today": TODAY, "profile": profile, "rows": _js_rows(TWIN_ROWS)}})["pattern"]
        assert js == json.loads(json.dumps(py)), (day, profile)
        kinds.update(a["kind"] for a in py)
    assert kinds == {"recent_days", "interdialytic", "weekly_average"}  # every kind compared at least once
