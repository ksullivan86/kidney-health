"""Kidney-only profile (docs/ROADMAP.md, "Kidney-only profile: diabetes as an option, not an assumption"), part 1.

With ``diabetes`` "none" a meal has no carbohydrate goal: no per-meal carbohydrate alert (eaten or planned) on the
server or in the demo, no carbohydrate line in Today's meal headers, and the two diabetes settings of Meal guidance
(carbohydrate tolerance, carbs taken for a low) are explained instead of shown. The day's carbohydrate is judged like
any nutrient. Before a diabetes type is chosen the app keeps using type 1, so the meal goals stay.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.log import day_figures, has_meal_carb_goals
from app.models import Alert, NutrientStatus
from app.nutrients import NUTRIENT_KEYS
from conftest import log_food

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
RUNNER = ROOT / "tests" / "js" / "demo_log_twin.mjs"
TARGETS = {"potassium_mg": 2500, "sodium_mg": 2000, "carbs_g": 200, "carbs_per_meal_g": 60, "carbs_per_snack_g": 15}


def profile(diabetes: str) -> dict[str, Any]:
    return {"targets": TARGETS, "warn_fraction": 0.8, "about_tolerance_pct": 0, "dialysis": "none", "dialysis_days": [],
            "diabetes": diabetes}


def _nutrients(**values: float) -> dict[str, float]:
    return {key: values.get(key, 0) for key in NUTRIENT_KEYS}


ROWS = [
    {"status": "eaten", "meal": "breakfast", "purpose": None, **_nutrients(carbs_g=95)},
    {"status": "eaten", "meal": "lunch", "purpose": None, **_nutrients(carbs_g=120)},
    {"status": "planned", "meal": "dinner", "purpose": None, **_nutrients(carbs_g=90)},
    {"status": "planned", "meal": "snack", "purpose": None, **_nutrients(carbs_g=40)},
]


def meal_alerts(alerts: list[dict[str, Any]]) -> list[str]:
    return [a["meal"] for a in alerts if a.get("meal")]


def test_meals_have_carbohydrate_goals_only_with_diabetes():
    assert has_meal_carb_goals(profile("type1")) and has_meal_carb_goals(profile("type2"))
    assert has_meal_carb_goals({"targets": TARGETS})  # no type yet: the app uses type 1
    assert not has_meal_carb_goals(profile("none"))


def test_a_kidney_only_day_has_no_per_meal_carbohydrate_alert():
    with_t1 = day_figures(ROWS, profile("type1"), 10)
    assert meal_alerts(with_t1["alerts"]) == ["breakfast", "lunch"]
    assert meal_alerts(with_t1["projected_alerts"]) == ["breakfast", "lunch", "dinner", "snack"]
    kidney = day_figures(ROWS, profile("none"), 10)
    assert meal_alerts(kidney["alerts"]) == [] and meal_alerts(kidney["projected_alerts"]) == []
    # the day's carbohydrate is still judged like any nutrient: 215 g eaten of a 200 g goal
    assert kidney["status"]["carbs_g"] == with_t1["status"]["carbs_g"]
    assert [a["nutrient"] for a in kidney["alerts"]] == [a["nutrient"] for a in with_t1["alerts"] if not a.get("meal")]
    assert kidney["meals"] == with_t1["meals"]  # the meal totals themselves do not change


def test_the_api_follows_the_profile(client):
    client.put("/api/profile", json={"targets": {"carbs_per_meal_g": 15}})
    day = "2026-10-05"
    log_food(client, "banana", meal="lunch", servings=3, date=day)  # about 80 g of carbohydrate
    log_food(client, "banana", meal="dinner", servings=3, date=day, status="planned")
    before = client.get("/api/log", params={"date": day}).json()
    assert meal_alerts(before["projected_alerts"]) == ["lunch", "dinner"]
    assert meal_alerts(before["alerts"]) == ["lunch"]  # not chosen yet: type 1 for now
    assert client.put("/api/profile", json={"diabetes": "none"}).status_code == 200
    after = client.get("/api/log", params={"date": day}).json()
    assert meal_alerts(after["alerts"]) == [] and meal_alerts(after["projected_alerts"]) == []
    assert client.get("/api/profile").json()["diabetes"] == "none"


def _js(payload: dict[str, Any]) -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the demo's twin (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _as_served(figures: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(figures))
    for key in ("status", "projected_status"):
        out[key] = {k: NutrientStatus(**v).model_dump(mode="json") for k, v in out[key].items()}
    for key in ("alerts", "projected_alerts"):
        out[key] = [Alert(**a).model_dump(mode="json") for a in out[key]]
    return out


@pytest.mark.parametrize("diabetes", ["none", "type1"])
def test_the_demo_twin_matches_the_server(diabetes):
    rows = [{"status": r["status"], "meal": r["meal"], "purpose": r["purpose"], "nutrients": {k: r[k] for k in NUTRIENT_KEYS}}
            for r in ROWS]
    js = _js({"profile": profile(diabetes), "carb_tolerance_g": 10, "rows": rows})["day"]
    assert _as_served(day_figures(ROWS, profile(diabetes), 10)) == js


def test_today_and_meal_guidance_follow_the_profile():
    today = (STATIC / "js" / "views" / "today.js").read_text(encoding="utf-8")
    assert "const mealCarbs = !(state.profile && state.profile.diabetes === 'none');" in today
    assert "h('div', { class: 'meal-head-right' }, mealCarbs ? carbsEl : null)" in today
    assert "if (mealCarbs && plannedEntries.length)" in today
    guidance = (STATIC / "js" / "views" / "guidance.js").read_text(encoding="utf-8")
    assert "const kidneyOnly = !!(state.profile && state.profile.diabetes === 'none');" in guidance
    settings = guidance[guidance.index("const kidneyOnly"):]
    shown = settings[settings.index("...(kidneyOnly"):]
    assert shown.index("set-g-kidney-only") < shown.index("number('carb_tolerance_g'") < shown.index("number('hypo_dose_g'")


def test_profile_hides_the_meal_carbohydrate_targets_but_keeps_them():
    profile_js = (STATIC / "js" / "views" / "profile.js").read_text(encoding="utf-8")
    sync = profile_js[profile_js.index("function syncConditionalFields()"):profile_js.index("$('#pf-dialysis').addEventListener")]
    assert "const kidneyOnly = $('#pf-diabetes').value === 'none';" in sync
    assert "for (const id of ['#tg-carbs_per_meal_g', '#tg-carbs_per_snack_g']) $(id).closest('.field').hidden = kidneyOnly;" in sync
    assert "$('#pf-diabetes').addEventListener('change', syncConditionalFields);" in profile_js
    # hidden, not removed: the form still collects every input[data-target], so a saved value is sent back unchanged
    assert "for (const inp of $$('input[data-target]')) targets[inp.dataset.target] = numOrNull(inp.value);" in profile_js
    # the suggestion review names no carbohydrate per meal without diabetes
    suggestion = profile_js[profile_js.index("function renderSuggestion("):]
    assert "const mealCarbs = !(state.profile && state.profile.diabetes === 'none');" in suggestion
    assert "key === 'carbs_g' && mealCarbs ? ['carbs_g', 'carbs_per_meal_g'] : [key]" in suggestion


def test_saving_a_kidney_only_profile_keeps_the_per_meal_targets(client):
    client.put("/api/profile", json={"targets": {"carbs_per_meal_g": 45, "carbs_per_snack_g": 15}})
    saved = client.put("/api/profile", json={"diabetes": "none", "targets": {"carbs_per_meal_g": 45, "carbs_per_snack_g": 15}})
    assert saved.status_code == 200
    targets = client.get("/api/profile").json()["targets"]
    assert targets["carbs_per_meal_g"] == 45 and targets["carbs_per_snack_g"] == 15
