"""Unit tests for the pure rules in app/nutrients.py."""
from __future__ import annotations

import re

import pytest

from app import nutrients as n


# --------------------------------------------------------------------------- #
# Registry and rounding
# --------------------------------------------------------------------------- #


def test_registry_has_the_twelve_contract_keys_in_order():
    assert n.NUTRIENT_KEYS == (
        "calories_kcal", "protein_g", "fat_g", "sat_fat_g", "carbs_g", "fiber_g", "sugar_g",
        "sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg", "fluid_ml",
    )
    assert n.NUTRIENT_BY_KEY["potassium_mg"].unit == "mg"
    assert n.NUTRIENT_BY_KEY["potassium_mg"].role == "limit"
    assert n.NUTRIENT_BY_KEY["protein_g"].role == "range"
    assert n.NUTRIENT_BY_KEY["carbs_g"].label == "Carbohydrate"
    assert n.NUTRIENT_BY_KEY["fluid_ml"].unit == "mL"
    assert n.TARGET_KEYS[-2:] == ("carbs_per_meal_g", "carbs_per_snack_g")


def test_round_value_integers_for_mg_and_ml_one_decimal_otherwise():
    assert n.round_value("potassium_mg", 421.6) == 422
    assert isinstance(n.round_value("potassium_mg", 421.6), int)
    assert n.round_value("fluid_ml", 235.5) == 236
    assert n.round_value("protein_g", 26.44) == 26.4
    assert n.round_value("calories_kcal", 105.04) == 105.0
    assert n.round_value("potassium_mg", None) is None


def test_round_nutrients_fills_missing_keys_with_none():
    out = n.round_nutrients({"potassium_mg": 10.4})
    assert set(out) == set(n.NUTRIENT_KEYS)
    assert out["potassium_mg"] == 10
    assert out["protein_g"] is None


def test_scale_and_add_totals():
    scaled = n.scale_nutrients({"potassium_mg": 100, "protein_g": None}, 2.5)
    assert scaled["potassium_mg"] == 250
    assert scaled["protein_g"] is None
    totals = n.empty_totals()
    n.add_totals(totals, scaled)
    n.add_totals(totals, {"potassium_mg": 50, "protein_g": 3})
    assert totals["potassium_mg"] == 300
    assert totals["protein_g"] == 3


# --------------------------------------------------------------------------- #
# Per-serving thresholds
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key, value, level",
    [
        ("potassium_mg", 100, None), ("potassium_mg", 100.4, None), ("potassium_mg", 100.6, "medium"),
        ("potassium_mg", 101, "medium"), ("potassium_mg", 200, "medium"), ("potassium_mg", 201, "high"),
        ("phosphorus_mg", 100, None), ("phosphorus_mg", 101, "medium"), ("phosphorus_mg", 150, "medium"), ("phosphorus_mg", 151, "high"),
        ("sodium_mg", 140, None), ("sodium_mg", 141, "medium"), ("sodium_mg", 400, "medium"), ("sodium_mg", 401, "high"),
        ("carbs_g", 14.9, None), ("carbs_g", 15, "medium"), ("carbs_g", 30, "medium"), ("carbs_g", 30.1, "high"),
        ("protein_g", 14.9, None), ("protein_g", 15, "medium"), ("protein_g", 25, "medium"), ("protein_g", 25.1, "high"),
        ("calories_kcal", 900, None),  # no threshold
        ("potassium_mg", None, None),
    ],
)
def test_threshold_level_boundaries(key, value, level):
    assert n.threshold_level(key, value) == level


def _by_nutrient(warnings):
    return {w["nutrient"]: w for w in warnings}


def test_food_warnings_banana_matches_contract_example():
    warnings = n.food_warnings({"potassium_mg": 422, "carbs_g": 26.95, "phosphorus_mg": 26, "sodium_mg": 1})
    by = _by_nutrient(warnings)
    assert by["potassium_mg"]["level"] == "high"
    assert by["potassium_mg"]["value"] == 422
    assert by["potassium_mg"]["message"] == "High potassium: 422 mg per serving"
    assert by["carbs_g"]["level"] == "medium"
    assert "phosphorus_mg" not in by and "sodium_mg" not in by
    # high warnings are listed before medium ones
    assert [w["level"] for w in warnings] == ["high", "medium"]
    assert n.kidney_rating(warnings) == "red"


def test_food_warnings_scope_text_for_entries():
    warnings = n.food_warnings({"potassium_mg": 844}, scope="in this entry")
    assert warnings[0]["message"] == "High potassium: 844 mg in this entry"


def test_food_warnings_empty_or_unknown_values():
    assert n.food_warnings({}) == []
    assert n.food_warnings({"potassium_mg": None, "carbs_g": None}) == []
    assert n.kidney_rating([]) == "green"


def test_phosphate_additive_flag_forces_high_phosphorus_even_when_low():
    warnings = n.food_warnings({"phosphorus_mg": 40}, flags=["phosphate_additive"])
    by = _by_nutrient(warnings)
    assert by["phosphorus_mg"]["level"] == "high"
    assert by["phosphorus_mg"]["flag"] == "phosphate_additive"
    assert "phosphate additives" in by["phosphorus_mg"]["message"]
    assert n.kidney_rating(warnings) == "red"
    # also when the phosphorus value is unknown
    unknown = n.food_warnings({}, flags=["phosphate_additive"])
    assert unknown[0]["nutrient"] == "phosphorus_mg" and unknown[0]["level"] == "high" and unknown[0]["value"] is None


def test_high_gi_flag_forces_high_carbs():
    warnings = n.food_warnings({"carbs_g": 16}, flags=["high_gi"])
    by = _by_nutrient(warnings)
    assert by["carbs_g"]["level"] == "high"
    assert by["carbs_g"]["flag"] == "high_gi"
    assert "glycaemic" in by["carbs_g"]["message"]
    # no carbs -> nothing to warn about even if flagged
    assert n.food_warnings({"carbs_g": 0}, flags=["high_gi"]) == []


def test_hypo_treatment_suppresses_carbohydrate_warnings_only():
    """Guide section 7: hypo treatments are never warned against for their (fast) carbohydrate."""
    assert n.food_warnings({"carbs_g": 16}, flags=["hypo_treatment", "high_gi"]) == []
    assert n.food_warnings({"carbs_g": 38}, flags=["hypo_treatment"]) == []
    # mineral warnings stay so the lowest-potassium option can still be chosen
    juice = n.food_warnings({"carbs_g": 14, "potassium_mg": 125}, flags=["hypo_treatment", "high_gi", "counts_as_fluid"])
    assert [w["nutrient"] for w in juice] == ["potassium_mg"]
    assert juice[0]["level"] == "medium"
    assert n.kidney_rating(juice) == "yellow"


def test_avoid_ckd_flag_yields_high_warning_with_kidney_notes():
    notes = "AVOID: star fruit is toxic in kidney failure."
    warnings = n.food_warnings({"potassium_mg": 121}, flags=["avoid_ckd"], kidney_notes=notes)
    assert warnings[0] == {"nutrient": "avoid_ckd", "level": "high", "value": None, "flag": "avoid_ckd", "message": notes}
    assert warnings[1]["nutrient"] == "potassium_mg" and warnings[1]["level"] == "medium"
    assert n.kidney_rating(warnings) == "red"
    # fallback text when there are no notes
    assert n.food_warnings({}, flags=["avoid_ckd"])[0]["message"].startswith("Not recommended")


def test_other_flags_do_not_create_warnings():
    assert n.food_warnings({"potassium_mg": 50}, flags=["low_potassium_fruit", "processed", "counts_as_fluid"]) == []


def test_protein_and_carb_messages():
    by = _by_nutrient(n.food_warnings({"protein_g": 26.4, "carbs_g": 45}))
    assert by["protein_g"]["message"] == "Large protein portion: 26.4 g per serving"
    assert by["carbs_g"]["message"] == "High carbohydrate: 45 g per serving (3 carb choices)"
    by = _by_nutrient(n.food_warnings({"protein_g": 20, "carbs_g": 15, "sodium_mg": 300}))
    assert by["protein_g"]["message"] == "Moderate protein: 20 g per serving"
    assert by["carbs_g"]["message"] == "1 carb choice: 15 g carbohydrate per serving"
    assert by["sodium_mg"]["message"] == "Moderate sodium: 300 mg per serving"


@pytest.mark.parametrize(
    "warnings, rating",
    [
        ([], "green"),
        ([{"level": "medium"}], "yellow"),
        ([{"level": "medium"}, {"level": "high"}], "red"),
        ([{"level": "high"}], "red"),
    ],
)
def test_kidney_rating(warnings, rating):
    assert n.kidney_rating(warnings) == rating


# --------------------------------------------------------------------------- #
# Daily status and alerts
# --------------------------------------------------------------------------- #


def test_daily_status_levels_ok_caution_over():
    targets = {"potassium_mg": 2500, "sodium_mg": 2000, "phosphorus_mg": 900}
    status = n.daily_status({"potassium_mg": 1800, "sodium_mg": 1700, "phosphorus_mg": 950}, targets, 0.8)
    assert status["potassium_mg"] == {"value": 1800, "target": 2500, "fraction": 0.72, "level": "ok"}
    assert status["sodium_mg"]["level"] == "caution" and status["sodium_mg"]["fraction"] == 0.85
    assert status["phosphorus_mg"]["level"] == "over" and status["phosphorus_mg"]["fraction"] == 1.06


def test_daily_status_boundaries_and_warn_fraction():
    targets = {"potassium_mg": 1000}
    assert n.daily_status({"potassium_mg": 799.9}, targets, 0.8)["potassium_mg"]["level"] == "ok"
    assert n.daily_status({"potassium_mg": 800}, targets, 0.8)["potassium_mg"]["level"] == "caution"
    assert n.daily_status({"potassium_mg": 1000}, targets, 0.8)["potassium_mg"]["level"] == "caution"
    assert n.daily_status({"potassium_mg": 1000.1}, targets, 0.8)["potassium_mg"]["level"] == "over"
    assert n.daily_status({"potassium_mg": 600}, targets, 0.5)["potassium_mg"]["level"] == "caution"


def test_daily_status_range_target_reports_min_and_uses_max():
    status = n.daily_status({"protein_g": 40}, {"protein_g": {"min": 42, "max": 56}}, 0.8)
    assert status["protein_g"] == {"value": 40.0, "target": 56.0, "min": 42.0, "fraction": 0.71, "level": "ok"}
    # min-only range: no fraction, still reported so the UI can show the floor
    status = n.daily_status({"fiber_g": 10}, {"fiber_g": {"min": 25}}, 0.8)
    assert status["fiber_g"]["fraction"] is None and status["fiber_g"]["level"] == "ok" and status["fiber_g"]["min"] == 25


def test_daily_status_skips_null_targets_missing_totals_and_non_nutrient_keys():
    status = n.daily_status({}, {"fluid_ml": None, "potassium_mg": 2500, "carbs_per_meal_g": 60}, 0.8)
    assert set(status) == {"potassium_mg"}
    assert status["potassium_mg"]["value"] == 0 and status["potassium_mg"]["level"] == "ok"


def test_build_alerts_messages_and_order():
    status = n.daily_status(
        {"potassium_mg": 2125, "sodium_mg": 2500, "carbs_g": 100, "protein_g": 50},
        {"potassium_mg": 2500, "sodium_mg": 2000, "carbs_g": 236, "protein_g": {"min": 42, "max": 56}},
        0.8,
    )
    alerts = n.build_alerts(status)
    assert [a["nutrient"] for a in alerts] == ["sodium_mg", "protein_g", "potassium_mg"]  # over first, then registry order
    by = {a["nutrient"]: a for a in alerts}
    assert by["potassium_mg"] == {
        "level": "caution", "nutrient": "potassium_mg",
        "message": "Potassium is at 85 % of today's limit (2125 / 2500 mg)",
    }
    assert by["sodium_mg"]["level"] == "over"
    assert by["sodium_mg"]["message"] == "Sodium is over today's limit: 2500 / 2000 mg (125 %)"
    assert by["protein_g"]["message"] == "Protein is at 89 % of today's maximum (50 / 56 g)"
    assert n.build_alerts(n.daily_status({"potassium_mg": 100}, {"potassium_mg": 2500}, 0.8)) == []


def test_meal_carb_alerts_only_when_over():
    meals = {"breakfast": {"carbs_g": 70}, "lunch": {"carbs_g": 55}, "dinner": {"carbs_g": 0}, "snack": {}}
    alerts = n.meal_carb_alerts(meals, 60)
    assert len(alerts) == 1
    assert alerts[0]["meal"] == "breakfast" and alerts[0]["level"] == "over" and alerts[0]["nutrient"] == "carbs_g"
    assert alerts[0]["message"] == "Breakfast carbohydrate is over the per-meal goal: 70 / 60 g"
    assert n.meal_carb_alerts(meals, None) == []
    assert n.meal_carb_alerts(meals, {"max": 80}) == []


def test_a_snack_goal_replaces_the_per_meal_goal_for_the_snack():
    """carbs_per_snack_g (note 06 §4.11) is the snack's own goal on Today and in its alerts (v0.3.0 review L11)."""
    meals = {"breakfast": {"carbs_g": 70}, "lunch": {"carbs_g": 55}, "dinner": {}, "snack": {"carbs_g": 25}}
    assert [a["meal"] for a in n.meal_carb_alerts(meals, 60)] == ["breakfast"]  # 25 g is under the per-meal 60
    alerts = n.meal_carb_alerts(meals, 60, 20)
    assert [a["meal"] for a in alerts] == ["breakfast", "snack"]
    assert alerts[1]["message"] == "Snack carbohydrate is over the snack goal: 25 / 20 g"
    assert [a["meal"] for a in n.meal_carb_alerts(meals, None, 20)] == ["snack"]  # a snack goal alone
    assert [a["meal"] for a in n.meal_carb_alerts(meals, 60, 30)] == ["breakfast"]
    projected = n.projected_meal_carb_alerts(meals, None, {"max": 15})
    assert [a["message"] for a in projected] == ["If you eat what's planned, snack carbohydrate reaches 25 / 15 g (over the snack goal)"]


# --------------------------------------------------------------------------- #
# Suggested targets
# --------------------------------------------------------------------------- #


def test_suggest_targets_non_dialysis_stage_3b_70kg():
    """Note 05 §5.3: with diabetes at G3a–G5 protein is 0.8 g/kg (never below; fact-check H1) and fibre is new."""
    result = n.suggest_targets(70, "3b", "none", "type1")
    targets = result["targets"]
    assert targets == {
        "calories_kcal": 2100,
        "protein_g": {"min": 56, "max": 56},
        "carbs_g": 236,
        "carbs_per_meal_g": 60,
        "fiber_g": {"min": 29},
        "sodium_mg": 2000,
        "potassium_mg": 3500,
        "phosphorus_mg": 1000,
        "calcium_mg": 1000,
        "fluid_ml": None,
    }
    assert result["notes"] and any("care team" in note for note in result["notes"])


@pytest.mark.parametrize(
    "stage, potassium, phosphorus",
    [("1", 4000, 1000), ("2", 4000, 1000), ("3a", 4000, 1000), ("3b", 3500, 1000), ("4", 3000, 1000), ("5", 2500, 900)],
)
def test_suggest_targets_provisional_potassium_and_phosphorus_by_stage(stage, potassium, phosphorus):
    targets = n.suggest_targets(70, stage, "none")["targets"]
    assert targets["potassium_mg"] == potassium
    assert targets["phosphorus_mg"] == phosphorus


def test_suggest_targets_stage_4_protein_range():
    assert n.suggest_targets(70, "4", "none")["targets"]["protein_g"] == {"min": 56, "max": 56}  # default type1: 0.8 g/kg
    assert n.suggest_targets(70, "4", "none", "none")["targets"]["protein_g"] == {"min": 42, "max": 56}  # 0.6–0.8 g/kg


@pytest.mark.parametrize("stage, dialysis", [("3b", "none"), ("1", "none"), ("5", "hemodialysis"), ("5", "peritoneal")])
def test_suggest_targets_always_carries_the_required_potassium_note(stage, dialysis):
    notes = n.suggest_targets(70, stage, dialysis)["notes"]
    potassium_notes = [note for note in notes if note.startswith("Potassium")]
    assert len(potassium_notes) == 1
    assert n.POTASSIUM_NOTE in potassium_notes[0]
    assert n.POTASSIUM_NOTE == "Only restrict potassium if your blood potassium is high; your care team sets the number."


def test_suggest_targets_hemodialysis():
    targets = n.suggest_targets(70, "5", "hemodialysis")["targets"]
    assert targets["protein_g"] == {"min": 70, "max": 84}
    assert targets["potassium_mg"] == 2500
    assert targets["phosphorus_mg"] == 1000
    assert targets["fluid_ml"] == 1500
    assert targets["sodium_mg"] == 2000


def test_suggest_targets_peritoneal():
    result = n.suggest_targets(80, "5", "peritoneal")
    targets = result["targets"]
    assert targets["protein_g"] == {"min": 80, "max": 96}
    assert targets["potassium_mg"] == 3500
    assert targets["phosphorus_mg"] == 1000
    assert targets["fluid_ml"] == 2000
    assert targets["calories_kcal"] == 2400
    assert targets["carbs_g"] == 270
    # without the absorbed dialysate calories the note asks for them (E-4 subtracts them once known)
    assert any("absorbs from the dialysis fluid" in note for note in result["notes"] if note.startswith("Calories"))


def test_suggest_targets_early_stage_is_more_liberal():
    targets = n.suggest_targets(70, "2", "none")["targets"]
    assert targets["protein_g"] == {"min": 56, "max": 70}
    assert targets["potassium_mg"] >= 3000
    assert targets["phosphorus_mg"] == 1000


def test_suggest_targets_match_research_json():
    """The code must agree with docs/research/targets_by_stage.json (the fact-checked file) row by row."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "docs" / "research" / "targets_by_stage.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) == 8
    weight = 70.0
    for row in rows:
        targets = n.suggest_targets(weight, row["stage"], row["dialysis"])["targets"]
        label = f"stage {row['stage']} / {row['dialysis']}"
        assert targets["potassium_mg"] == row["potassium_mg"], label
        assert targets["phosphorus_mg"] == row["phosphorus_mg"], label
        assert targets["sodium_mg"] == row["sodium_mg"], label
        assert targets["calcium_mg"] == row["calcium_mg"], label
        assert targets["fluid_ml"] == row["fluid_ml"], label
        assert targets["calories_kcal"] == round(row["calories_kcal_per_kg"] * weight / 10) * 10, label
        assert targets["protein_g"] == {
            "min": round(row["protein_g_per_kg_min"] * weight),
            "max": round(row["protein_g_per_kg_max"] * weight),
        }, label
        # the notes cite the published KDOQI 2020 numbering, never the 2019 draft's (note 05 F1, C1)
        assert not re.search(r"KDOQI 2020 3\.1\.[2-4]|KDOQI 2020 3\.0\.1 range|ideal body weight", row["note"]), label


def test_suggest_targets_rejects_bad_input():
    with pytest.raises(ValueError):
        n.suggest_targets(0, "3b", "none")
    with pytest.raises(ValueError):
        n.suggest_targets(70, "6", "none")
    with pytest.raises(ValueError):
        n.suggest_targets(70, "3b", "sometimes")


# --------------------------------------------------------------------------- #
# Fixes after review: glycaemic-index gate, ideal body weight, non-finite values
# --------------------------------------------------------------------------- #


def test_high_gi_below_one_carb_choice_is_only_a_medium_note():
    """Ketchup (4.7 g) or one slice of white bread (14.3 g) must not rate red for glycaemic index alone."""
    ketchup = n.food_warnings({"carbs_g": 4.7, "sodium_mg": 150}, flags=["high_gi"])
    by = _by_nutrient(ketchup)
    assert by["carbs_g"]["level"] == "medium" and by["carbs_g"]["flag"] == "high_gi"
    assert by["carbs_g"]["message"] == "High glycaemic index: 4.7 g fast-acting carbohydrate per serving"
    assert n.kidney_rating(ketchup) == "yellow"
    bread = _by_nutrient(n.food_warnings({"carbs_g": 14.3}, flags=["high_gi"]))
    assert bread["carbs_g"]["level"] == "medium"
    # from one carb choice (15 g, judged on the displayed value) the flag upgrades to high
    assert _by_nutrient(n.food_warnings({"carbs_g": 14.96}, flags=["high_gi"]))["carbs_g"]["level"] == "high"
    assert _by_nutrient(n.food_warnings({"carbs_g": 15}, flags=["high_gi"]))["carbs_g"]["level"] == "high"
    assert _by_nutrient(n.food_warnings({"carbs_g": 38}, flags=["high_gi"]))["carbs_g"]["level"] == "high"
    assert n.HIGH_GI_MIN_CARBS_G == 15


@pytest.mark.parametrize(
    "weight, height, expected",
    [
        (70, None, (70.0, "actual_no_height")),
        (70, 170, (70.0, "actual")),  # BMI 24.2: inside the healthy band
        (100, 170, (79.2, "adjusted_above_bmi25")),  # 72.25 + 0.25 x 27.75 = 79.1875 -> 79.2 (note 05 §5.3)
        (45, 170, (47.1, "adjusted_below_bmi18_5")),  # 45 + 0.25 x (53.465 - 45) = 47.116 -> 47.1
        (72.25, 170, (72.3, "actual")),  # exactly BMI 25 is still "actual"; the weight is rounded to 0.1 kg
    ],
)
def test_dosing_weight_is_the_reference_weight(weight, height, expected):
    assert n.dosing_weight(weight, height) == expected


def test_suggest_targets_use_the_reference_weight_when_height_is_known():
    """Note 05 §4.3 and §5.3: per kg of a reference weight (KDOQI leaves the choice to the team, 1.1.6)."""
    heavy = n.suggest_targets(100, "4", "none", "type1", height_cm=170)
    assert heavy["targets"]["calories_kcal"] == 2380  # 30 x 79.2 = 2376 -> nearest 10
    assert heavy["targets"]["protein_g"] == {"min": 63, "max": 63}  # 0.8 x 79.2
    assert heavy["targets"]["carbs_g"] == 268  # 2380 x 0.45 / 4 = 267.75
    basis = [note for note in heavy["notes"] if note.startswith("Weight basis")]
    assert len(basis) == 1 and "79.2 kg" in basis[0] and "BMI 34.6" in basis[0] and "adjusted weight" in basis[0]
    assert "ideal body weight" not in " ".join(heavy["notes"])
    assert any("79.2 kg" in note for note in heavy["notes"] if note.startswith("Calories"))
    # the same person without a saved height falls back to the actual weight and says so
    plain = n.suggest_targets(100, "4", "none", "type1")
    assert plain["targets"]["calories_kcal"] == 3000 and plain["targets"]["protein_g"] == {"min": 80, "max": 80}
    assert any("without a saved height" in note for note in plain["notes"])
    # underweight: moved a quarter of the way up to BMI 18.5; BMI 15.6 is a nutrition risk, so protein rises (P-5)
    light = n.suggest_targets(45, "3b", "none", height_cm=170)
    assert light["targets"]["calories_kcal"] == 1410 and light["targets"]["protein_g"] == {"min": 38, "max": 47}
    assert any(note.startswith("Nutrition risk: BMI 15.6 is below 20") for note in light["notes"])
    # a normal-weight person gets the contract numbers unchanged
    assert n.suggest_targets(70, "3b", "none", height_cm=170)["targets"] == n.suggest_targets(70, "3b", "none")["targets"]
    with pytest.raises(ValueError):
        n.suggest_targets(70, "3b", "none", height_cm=0)


def test_protein_note_states_the_guideline_thresholds_and_the_right_source():
    """Published KDOQI 2020 numbering (note 05 F1, C1): protein 3.0.1–3.0.4, energy 3.1.1."""
    diabetic = [note for note in n.suggest_targets(70, "3b", "none", "type1")["notes"] if note.startswith("Protein")][0]
    assert "KDOQI 2020 3.0.2" in diabetic and "ADA 2026 Rec 11.3" in diabetic and "not recommended" in diabetic
    assert "with diabetes" in diabetic and "more than 1.3 g/kg (KDIGO 2024)" in diabetic
    assert "speeds progression" not in diabetic and "3.1.3" not in diabetic
    non_diabetic = [note for note in n.suggest_targets(70, "3b", "none", "none")["notes"] if note.startswith("Protein")][0]
    assert "with diabetes" not in non_diabetic and "3.0.1" in non_diabetic and "KDIGO 2024 Rec 3.3.1.1" in non_diabetic
    calories = [note for note in n.suggest_targets(70, "3b")["notes"] if note.startswith("Calories")][0]
    assert "KDOQI 2020 3.1.1" in calories and "3.0.1" not in calories
    assert n.suggest_targets(70, "3b", "none", "none")["targets"]["protein_g"] == {"min": 42, "max": 56}


def test_non_finite_totals_and_targets_do_not_break_status_or_alerts():
    inf = float("inf")
    status = n.daily_status({"potassium_mg": inf, "sodium_mg": 500}, {"potassium_mg": 2500, "sodium_mg": inf, "protein_g": {"min": inf, "max": 56}}, 0.8)
    assert status["potassium_mg"]["value"] is None and status["potassium_mg"]["fraction"] is None
    assert status["potassium_mg"]["level"] == "over"
    assert "sodium_mg" not in status  # an infinite ceiling cannot be judged against: not tracked
    assert "min" not in status["protein_g"] and status["protein_g"]["target"] == 56
    assert n.build_alerts(status) == [] and n.build_projected_alerts(status) == []
    nan_status = {"potassium_mg": {"value": None, "target": 2500, "fraction": float("nan"), "level": "over"}}
    assert n.build_alerts(nan_status) == []
    assert n.status_level(float("nan"), 0.8) == "ok" and n.status_level(inf, 0.8) == "over"
