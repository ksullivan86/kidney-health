"""Personalised suggested targets (``app/targets.py`` + ``app/target_rules.py``; note 05 §4.3–§4.5, §5, §7 C2).

The §5.1 vectors live in ``tests/data/personal_target_vectors.json``, copied verbatim from the note.
The property tests below are the ones checklist C2 asks for (continuity, kcal range, potassium note,
rule order, the H1 diabetes floor, M1, M2, M5) plus every threshold edge of the rule catalogue.
"""
from __future__ import annotations

import itertools
import json
import random
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app import nutrients
from app import target_rules as R
from app import targets as T

ROOT = Path(__file__).resolve().parents[1]
SPEC_VECTORS = json.loads((ROOT / "tests" / "data" / "personal_target_vectors.json").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(SPEC_VECTORS["today"])
LAB_UNITS = {"potassium": "mmol/L", "phosphate": "mg/dL", "albumin": "g/dL", "bicarbonate": "mmol/L", "uacr": "mg/g", "a1c": "%"}
STAGES = ("1", "2", "3a", "3b", "4", "5")


def labs_of(values: dict[str, float], taken_on: str = "2026-10-05") -> list[dict[str, Any]]:
    return [{"id": i + 1, "analyte": a, "value": v, "entered_value": v, "entered_unit": LAB_UNITS[a], "taken_on": taken_on}
            for i, (a, v) in enumerate(values.items())]


def run(profile: dict[str, Any], labs: dict[str, float] | None = None, today: date = TODAY, **settings: Any) -> dict[str, Any]:
    return T.suggest_from_records({"weight_kg": 70, "ckd_stage": "3b", **profile}, labs_of(labs or {}), today, **settings)


def rule_ids(result: dict[str, Any]) -> list[str]:
    return [r["id"] for r in result["rules"]]


def k_rule_of(result: dict[str, Any]) -> str:
    return next(i for i in rule_ids(result) if i.startswith("K-"))


def note(result: dict[str, Any], prefix: str) -> str:
    found = [n for n in result["notes"] if n.startswith(prefix)]
    assert len(found) == 1, (prefix, result["notes"])
    return found[0]


# --------------------------------------------------------------------------- #
# §5.1 vectors
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vector", SPEC_VECTORS["vectors"], ids=[v["id"] for v in SPEC_VECTORS["vectors"]])
def test_spec_vectors(vector):
    inputs = dict(vector["input"])
    labs = {a: inputs.pop(a) for a in list(inputs) if a in LAB_UNITS}
    expect = vector["expect"]
    if "error" in expect:
        with pytest.raises(T.OutOfScope) as info:
            T.suggest_from_records(inputs, labs_of(labs), TODAY)
        assert info.value.code == expect["error"]
        assert info.value.message == R.REFUSALS[expect["error"]][1]
        return
    result = T.suggest_from_records(inputs, labs_of(labs), TODAY)
    assert result["targets"] == expect["targets"]
    assert result["derived"]["reference_weight_kg"] == expect["reference_weight_kg"]
    assert result["derived"]["weight_basis"] == expect["weight_basis"]
    assert result["derived"]["age"] == expect["age"]
    assert result["derived"]["nutrition_risk"] == expect["nutrition_risk"]
    assert rule_ids(result) == expect["rules"]
    assert [{"level": a["level"], "code": a["code"]} for a in result["alerts"]] == expect.get("alerts", [])


def test_spec_intermediate_energy_values():
    """Note 05 §5.1 "Intermediate values": EER kcal and kcal/kg for the vectors that have them."""
    table = {"TV02": (2282, 32.6), "TV03": (1880, 30.3), "TV04": (2089, 27.9), "TV05": (1731, 33.0), "TV06": (2429, 29.6),
             "TV07": (1841, 30.7), "TV08": (2596, 32.7), "TV12": (1691, 29.2), "TV13": (2202, 32.4), "TV14": (2497, 35.0),
             "TV15": (2298, 29.6), "TV16": (1921, 27.4), "TV17": (2304, 31.1), "TV18": (2056, 27.6), "TV20": (1811, 30.0),
             "TV21": (2076, 29.7), "TV22": (1782, 29.7)}
    by_id = {v["id"]: v for v in SPEC_VECTORS["vectors"]}
    for vid, (eer, used) in table.items():
        inputs = dict(by_id[vid]["input"])
        labs = {a: inputs.pop(a) for a in list(inputs) if a in LAB_UNITS}
        derived = T.suggest_from_records(inputs, labs_of(labs), TODAY)["derived"]
        assert derived["eer_kcal"] == eer, vid
        assert derived["kcal_per_kg"] == used, vid
    tv14 = T.eer_kcal("male", "active", 50, 168, 70), T.eer_kcal("female", "active", 50, 168, 70)
    assert (round(tv14[0]), round(tv14[1])) == (2672, 2322)


def test_reference_weight_checks():
    """Note 05 §5.1 "Reference-weight checks" and §3.1 (100 kg at 170 cm -> 79.2)."""
    assert T.reference_weight(95, 165).weight_kg == 74.8
    assert T.reference_weight(52, 170).weight_kg == 52.4
    assert T.reference_weight(82, 181).weight_kg == 81.9
    assert T.reference_weight(100, 170) == T.ReferenceWeight(79.2, "adjusted_above_bmi25", 100 / 1.7**2, 25 * 1.7**2, 18.5 * 1.7**2)
    assert T.reference_weight(72.25, 170).basis == "actual"  # exactly BMI 25
    assert T.reference_weight(53.465, 170).basis == "actual"  # exactly BMI 18.5
    assert T.reference_weight(70, None) == T.ReferenceWeight(70.0, "actual_no_height", None, None, None)
    for bad in ((0, 170), (-1, None), (float("nan"), 170), (70, 0), (70, float("inf"))):
        with pytest.raises(ValueError):
            T.reference_weight(*bad)


# --------------------------------------------------------------------------- #
# Properties (checklist C2)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("height", [150, 158.5, 165, 170, 181, 195])
def test_reference_weight_is_continuous_at_bmi_18_5_and_25(height):
    h2 = (height / 100) ** 2
    for edge in (18.5, 25.0):
        w = edge * h2
        for step in (0.01, -0.01):
            a, b = T.reference_weight(w, height).weight_kg, T.reference_weight(w + step, height).weight_kg
            assert abs(a - b) < 0.1 + 1e-9, (height, edge, step, a, b)


def random_profiles(n: int, seed: int = 20261005):
    rng = random.Random(seed)
    for _ in range(n):
        dialysis = rng.choice(("none", "none", "hemodialysis", "peritoneal"))
        profile: dict[str, Any] = {
            "weight_kg": round(rng.uniform(35, 160), 1),
            "ckd_stage": rng.choice(STAGES) if dialysis == "none" else "5",
            "dialysis": dialysis,
            "diabetes": rng.choice(("none", "type1", "type2")),
            "height_cm": rng.choice((None, round(rng.uniform(145, 200), 1))),
            "birth_month": rng.choice((None, f"{rng.randint(1920, 2007)}-{rng.randint(1, 12):02d}")),
            "sex": rng.choice(R.SEXES),
            "activity": rng.choice((None, *R.ACTIVITIES)),
            "frail_or_sarcopenic": rng.random() < 0.2,
            "hyperkalemia_history": rng.random() < 0.3,
        }
        if dialysis == "none" and rng.random() < 0.25:
            profile["transplant_date"] = f"{rng.randint(2005, 2026)}-{rng.randint(1, 12):02d}-01"
        if dialysis != "none" and rng.random() < 0.6:
            profile["urine_output_ml"] = rng.choice((0, rng.randint(0, 2500)))
        if dialysis == "peritoneal" and rng.random() < 0.6:
            profile["pd_uf_ml"] = rng.randint(0, 2000)
            profile["pd_dialysate_kcal"] = rng.choice((None, rng.randint(0, 1000)))
        if rng.random() < 0.3:
            profile["weight_6_months_ago_kg"] = round(profile["weight_kg"] * rng.uniform(0.9, 1.15), 1)
        labs = {}
        for analyte, lo, hi in (("potassium", 2.8, 7.0), ("phosphate", 1.5, 8.0), ("albumin", 2.5, 4.8), ("bicarbonate", 14, 30),
                                ("uacr", 0, 2000), ("a1c", 5, 11)):
            if rng.random() < 0.5:
                labs[analyte] = round(rng.uniform(lo, hi), 2)
        yield profile, labs


def all_results(n: int = 1500):
    for profile, labs in random_profiles(n):
        try:
            yield profile, labs, T.suggest_from_records(profile, labs_of(labs), TODAY)
        except T.OutOfScope:
            continue


def test_properties_over_a_fixed_random_sample():
    order = {prefix: i for i, prefix in enumerate(R.RULE_ORDER)}
    seen_rules: set[str] = set()
    count = 0
    for profile, labs, result in all_results():
        count += 1
        ids = rule_ids(result)
        seen_rules.update(ids)
        derived, targets = result["derived"], result["targets"]
        ref = derived["reference_weight_kg"]
        # kcal/kg stays inside KDOQI's 25–35 before the PD subtraction
        assert 25 <= derived["kcal_per_kg"] <= 35, (profile, derived)
        # every potassium note carries the contract sentence, and there is exactly one
        potassium_notes = [n for n in result["notes"] if n.startswith("Potassium")]
        assert len(potassium_notes) == 1 and potassium_notes[0].endswith(R.POTASSIUM_NOTE)
        # rules come out in the order S → W → N → E → P → K → PH → NA → CA → F → C → FB → L
        prefixes = [order[i.split("-")[0]] for i in ids]
        assert prefixes == sorted(prefixes), ids
        # one note per rule, then the closing note
        assert len(result["notes"]) == len(ids) + 1 and result["notes"][-1] == R.NOTES["END"]
        # H1: with diabetes and no dialysis at G3a–G5, protein never goes below 0.8 g/kg
        if profile["diabetes"] != "none" and derived["mode"] in ("ckd", "transplant"):
            assert targets["protein_g"]["min"] >= int(nutrients._half_up(0.8 * ref, 0)), (profile, targets)
        # M1: the "drink at least" note never appears at stage 4–5 or on dialysis
        if "F-0o" in ids:
            assert profile["ckd_stage"] in ("1", "2", "3a", "3b") and derived["mode"] in ("ckd", "transplant")
        # M2: P-5 never raises a transplant at graft G3a–G5
        if derived["mode"] == "transplant" and profile["ckd_stage"] not in ("1", "2"):
            assert "P-5" not in ids and targets["protein_g"] == {"min": int(nutrients._half_up(0.8 * ref, 0)),
                                                                 "max": int(nutrients._half_up(1.0 * ref, 0))}
        # dialysis never restricts protein below 1.0 g/kg
        if derived["mode"] in ("hemodialysis", "peritoneal"):
            assert targets["protein_g"]["min"] >= int(nutrients._half_up(1.0 * ref, 0))
        # no fluid limit without dialysis; no potassium limit when potassium is low
        if derived["mode"] in ("ckd", "transplant"):
            assert targets["fluid_ml"] is None
        if "K-1" in ids:
            assert targets["potassium_mg"] is None
        # every rule returned is in the catalogue, with its source
        for rule in result["rules"]:
            assert rule["source"] and rule["grade"] and rule["url"].startswith("https://") and isinstance(rule["opinion"], bool)
        assert targets["carbs_per_meal_g"] >= 15 and targets["carbs_per_meal_g"] % 5 == 0
        assert targets["calories_kcal"] % 10 == 0
    assert count > 1000
    # the sample exercises nearly the whole catalogue (refusals and two rare lab notes are tested below)
    assert len(seen_rules) >= 45, sorted(seen_rules)


def test_m5_any_birth_month_whose_18th_birthday_could_still_be_ahead_is_refused():
    for today in (date(2026, 10, 1), date(2026, 10, 5), date(2026, 10, 31), date(2026, 2, 28), date(2026, 12, 31)):
        same_month_18_years_ago = f"{today.year - 18}-{today.month:02d}"
        last_day_of_that_month_birthday_ahead = today.day < 28 or today.month == 2
        if last_day_of_that_month_birthday_ahead or today.day < 31:
            with pytest.raises(T.OutOfScope) as info:
                run({"birth_month": same_month_18_years_ago}, today=today)
            assert info.value.code == "out_of_scope_under_18"
        previous = date(today.year - 18, today.month, 1).replace(day=1)
        month_before = f"{previous.year - (previous.month == 1)}-{(previous.month - 2) % 12 + 1:02d}"
        assert run({"birth_month": month_before}, today=today)["derived"]["age"] == 18


def test_m5_end_of_month_birthday():
    """Born 2008-10 at the latest on the 31st: 18 for certain only from 2026-10-31."""
    with pytest.raises(T.OutOfScope):
        run({"birth_month": "2008-10"}, today=date(2026, 10, 30))
    assert run({"birth_month": "2008-10"}, today=date(2026, 10, 31))["derived"]["age"] == 18


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def test_refusals_come_first_and_in_order():
    with pytest.raises(T.OutOfScope) as info:
        run({"pregnant_or_breastfeeding": True, "birth_month": "2010-01", "transplant_date": "2026-10-01"})
    assert info.value.code == "out_of_scope_pregnancy" and info.value.rule == "S-1"
    with pytest.raises(T.OutOfScope) as info:
        run({"birth_month": "2010-01", "transplant_date": "2026-10-01"})
    assert info.value.code == "out_of_scope_under_18" and info.value.rule == "S-2"
    with pytest.raises(T.OutOfScope) as info:
        run({"transplant_date": "2026-10-01"})
    assert info.value.code == "out_of_scope_early_transplant" and info.value.rule == "S-3"
    assert "you can still enter them by hand" in R.REFUSALS["out_of_scope_pregnancy"][1]


def test_early_transplant_cut_off_is_84_days():
    with pytest.raises(T.OutOfScope):
        run({"transplant_date": "2026-07-14"})  # 83 days
    assert run({"transplant_date": "2026-07-13"})["derived"]["mode"] == "transplant"  # 84 days
    with pytest.raises(T.OutOfScope):
        run({"transplant_date": "2026-12-01"})  # a date ahead counts as "less than 12 weeks"
    # back on dialysis after a transplant: the dialysis rules apply, no refusal
    assert run({"ckd_stage": "5", "dialysis": "hemodialysis", "transplant_date": "2026-10-01"})["derived"]["mode"] == "hemodialysis"


# --------------------------------------------------------------------------- #
# Energy
# --------------------------------------------------------------------------- #


def test_energy_clamps_and_says_so():
    high = run({"weight_kg": 70, "height_cm": 168, "birth_month": "1976-10", "activity": "active"})  # TV14 without albumin
    assert high["derived"]["eer_kcal_per_kg"] == 35.7 and high["derived"]["kcal_per_kg"] == 35.0
    assert note(high, "Calories").endswith(
        "(KDOQI 2020 3.1.1). The estimate was 35.7 kcal/kg, so it was set to 35 kcal/kg. Sex is not set, so the average of "
        "the female and male equations is used."
    )
    low = run({"weight_kg": 110, "height_cm": 160, "birth_month": "1940-01", "sex": "female"})
    assert low["derived"]["kcal_per_kg"] == 25.0 and "so it was set to 25 kcal/kg" in note(low, "Calories")


def test_energy_activity_default_comes_from_the_setting_and_a_choice_wins():
    base = {"height_cm": 175, "birth_month": "1971-03", "sex": "male"}
    assert run(base)["derived"]["activity"] == "inactive" and "activity" in run(base)["missing_inputs"]
    active_default = run(base, default_activity="low_active")
    assert active_default["derived"]["activity"] == "low_active" and active_default["derived"]["eer_kcal"] > run(base)["derived"]["eer_kcal"]
    chosen = run({**base, "activity": "inactive"}, default_activity="very_active")
    assert chosen["derived"]["activity"] == "inactive" and "activity" not in chosen["missing_inputs"]
    assert '("low active")' in note(active_default, "Calories")


def test_energy_fallback_without_age_or_height():
    result = run({"birth_month": "1971-03", "sex": "male"})  # no height
    assert rule_ids(result)[1] == "E-2" and result["derived"]["eer_kcal"] is None
    assert note(result, "Calories") == (
        "Calories: 30 kcal/kg × 70 kg = 2100 kcal/day, the middle of the guideline range of 25–35 kcal/kg (KDOQI 2020 3.1.1). "
        "Add your birth month, sex, height and activity for a personal estimate."
    )


def test_nutrition_risk_floor_is_30_kcal_per_kg():
    result = run({"weight_kg": 70, "height_cm": 170, "birth_month": "1961-05", "sex": "female", "frail_or_sarcopenic": True})
    assert "E-3" in rule_ids(result) and result["derived"]["kcal_per_kg"] == 30.0
    assert result["targets"]["calories_kcal"] == 2100
    assert "Calories: 1920 kcal/day" in note(result, "Calories:")  # the estimate, before E-3 raised it


def test_pd_dialysate_subtraction_floor_and_insulin_sentence():
    pd = {"weight_kg": 60, "ckd_stage": "5", "dialysis": "peritoneal", "height_cm": 158, "birth_month": "1976-05", "sex": "female"}
    normal = run({**pd, "pd_dialysate_kcal": 350})
    assert normal["targets"]["calories_kcal"] == 1490
    assert note(normal, "Peritoneal") == (
        "Peritoneal dialysis: 350 kcal/day absorbed from dialysis fluid was subtracted, so food calories are 1490 of 1840 kcal. "
        "That glucose also needs insulin; your diabetes team plans for it."
    )
    floored = run({**pd, "pd_dialysate_kcal": 1000})
    assert floored["targets"]["calories_kcal"] == 1200  # 20 kcal/kg × 60 kg
    assert "kept at 20 kcal/kg × 60 kg, so they are 1200 of 1840 kcal" in note(floored, "Peritoneal")
    no_diabetes = run({**pd, "diabetes": "none", "pd_dialysate_kcal": 350})
    assert "insulin" not in note(no_diabetes, "Peritoneal")
    unknown = run(pd)
    assert "E-4" not in rule_ids(unknown) and "absorbs from the dialysis fluid" in note(unknown, "Calories")
    assert run({**pd, "pd_dialysate_kcal": 0})["targets"]["calories_kcal"] == 1840  # 0 subtracts nothing


# --------------------------------------------------------------------------- #
# Protein
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "profile, expected, ids",
    [
        ({"ckd_stage": "2", "diabetes": "none"}, {"min": 56, "max": 70}, ["P-1"]),
        ({"ckd_stage": "3a"}, {"min": 56, "max": 56}, ["P-2"]),
        ({"ckd_stage": "3a", "diabetes": "type2"}, {"min": 56, "max": 56}, ["P-2"]),
        ({"ckd_stage": "5", "diabetes": "none"}, {"min": 42, "max": 56}, ["P-2"]),
        ({"ckd_stage": "5", "dialysis": "hemodialysis"}, {"min": 70, "max": 84}, ["P-3"]),
        ({"ckd_stage": "5", "dialysis": "hemodialysis", "frail_or_sarcopenic": True}, {"min": 84, "max": 91}, ["P-3", "P-6"]),
        ({"ckd_stage": "5", "dialysis": "peritoneal", "birth_month": "1950-01"}, {"min": 70, "max": 84}, ["P-3"]),  # older only
        ({"ckd_stage": "3b", "birth_month": "1950-01"}, {"min": 56, "max": 70}, ["P-2", "P-5"]),
        ({"ckd_stage": "1", "birth_month": "1950-01"}, {"min": 70, "max": 84}, ["P-1", "P-5"]),
        ({"ckd_stage": "2", "transplant_date": "2020-01-01"}, {"min": 56, "max": 70}, ["P-7"]),
        ({"ckd_stage": "2", "transplant_date": "2020-01-01", "frail_or_sarcopenic": True}, {"min": 70, "max": 84}, ["P-7", "P-5"]),
        ({"ckd_stage": "3a", "transplant_date": "2020-01-01", "birth_month": "1950-01"}, {"min": 56, "max": 70}, ["P-7"]),
    ],
)
def test_protein_rules(profile, expected, ids):
    result = run(profile)
    assert result["targets"]["protein_g"] == expected
    assert [i for i in rule_ids(result) if i.startswith("P-")] == ids


def test_protein_notes():
    d = note(run({}), "Protein")
    assert d.startswith("Protein: about 56 g/day (0.8 g/kg × 70 kg) for CKD stages 3–5 with diabetes")
    assert "not recommended" in d and "KDOQI 2020 3.0.2: 0.6–0.8" in d
    n = note(run({"diabetes": "none"}), "Protein")
    assert n.startswith("Protein: 42–56 g/day (0.6–0.8 g/kg × 70 kg) for CKD stages 3–5.") and "PP 3.3.1.3" in n
    older = run({"birth_month": "1950-01", "frail_or_sarcopenic": True})
    assert note(older, "Protein raised").startswith("Protein raised to 0.8–1.0 g/kg (56–70 g/day) because you are 65 or older and at nutrition risk:")
    graft = note(run({"ckd_stage": "4", "transplant_date": "2018-05-01", "birth_month": "1955-03"}), "Protein")
    assert graft.endswith("It is not raised further for age because your transplant's function is at stage 4; ask your team.")
    hd = note(run({"ckd_stage": "5", "dialysis": "hemodialysis", "frail_or_sarcopenic": True}), "Protein raised")
    assert hd.startswith("Protein raised to 1.2–1.3 g/kg (84–91 g/day) because of the nutrition risk above")
    assert "on hemodialysis (KDOQI 2020 3.0.3/3.0.4)" in note(run({"ckd_stage": "5", "dialysis": "hemodialysis"}), "Protein")


def test_nutrition_risk_thresholds():
    # GLIM low BMI: below 20 under 70 years, below 22 from 70 (shown BMI, one decimal)
    assert run({"weight_kg": 57.7, "height_cm": 170, "birth_month": "1957-01"})["derived"]["nutrition_risk"] == []  # 19.97 shown 20.0
    assert run({"weight_kg": 57.6, "height_cm": 170, "birth_month": "1957-01"})["derived"]["nutrition_risk"] == ["low_bmi"]  # 19.9
    assert run({"weight_kg": 60.0, "height_cm": 170, "birth_month": "1957-01"})["derived"]["nutrition_risk"] == []  # 20.8, age 69
    assert run({"weight_kg": 60.0, "height_cm": 170, "birth_month": "1956-01"})["derived"]["nutrition_risk"] == ["low_bmi"]  # age 70
    # GLIM weight loss: more than 5 % (shown to one decimal)
    assert run({"weight_kg": 95, "weight_6_months_ago_kg": 100})["derived"]["nutrition_risk"] == []
    assert run({"weight_kg": 94.9, "weight_6_months_ago_kg": 100})["derived"]["nutrition_risk"] == ["weight_loss"]
    assert run({"weight_kg": 100, "weight_6_months_ago_kg": 90})["derived"]["nutrition_risk"] == []  # a gain
    # ISRNM albumin below 3.8 g/dL; frailty checkbox; reasons in this order
    result = run({"weight_kg": 50, "height_cm": 170, "weight_6_months_ago_kg": 60, "frail_or_sarcopenic": True}, {"albumin": 3.3})
    assert result["derived"]["nutrition_risk"] == ["low_bmi", "weight_loss", "low_albumin", "frailty"]
    assert note(result, "Nutrition risk") == (
        "Nutrition risk: BMI 17.3 is below 20; you have lost 16.7 % of your weight in 6 months; blood albumin 3.3 g/dL is "
        "below 3.8; frailty or low muscle mass is marked in your profile. The app moves protein and calories to the higher "
        "end. Ask your renal dietitian for a nutrition assessment and whether oral nutrition supplements would help "
        "(KDOQI 2020 4.1.1)."
    )
    assert run({}, {"albumin": 3.8})["derived"]["nutrition_risk"] == []
    assert run({}, {"albumin": 3.75})["derived"]["nutrition_risk"] == []  # shown 3.8


# --------------------------------------------------------------------------- #
# Potassium and phosphorus
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "k, rule, mg",
    [(3.4, "K-1", None), (3.44, "K-1", None), (3.45, "K-2", 4000), (3.5, "K-2", 4000), (5.0, "K-2", 4000), (5.04, "K-2", 4000),
     (5.05, "K-3", 3000), (5.5, "K-3", 3000), (5.54, "K-3", 3000), (5.55, "K-4", 2500), (5.9, "K-4", 2500),
     (5.95, "K-5", 2000), (6.0, "K-5", 2000), (6.44, "K-5", 2000), (6.5, "K-5", 2000), (8.0, "K-5", 2000)],
)
def test_potassium_thresholds_on_the_shown_value(k, rule, mg):
    result = run({}, {"potassium": k})  # G3b: ladder 3500, relaxed 4000
    assert rule in rule_ids(result) and result["targets"]["potassium_mg"] == mg
    alerts = result["alerts"]
    if rule == "K-5":
        assert [a["level"] for a in alerts] == ["emergency" if k >= 6.45 else "urgent"]
    else:
        assert alerts == []


def test_potassium_caps_never_raise_the_ladder_and_dialysis_relaxes_one_step():
    assert run({"ckd_stage": "5"}, {"potassium": 5.3})["targets"]["potassium_mg"] == 2500  # min(L=2500, 3000)
    assert run({"ckd_stage": "5", "dialysis": "hemodialysis"}, {"potassium": 4.5})["targets"]["potassium_mg"] == 3000
    assert run({"ckd_stage": "5", "dialysis": "peritoneal"}, {"potassium": 4.5})["targets"]["potassium_mg"] == 4000
    assert run({"ckd_stage": "4", "transplant_date": "2018-01-01"}, {"potassium": 4.5})["targets"]["potassium_mg"] == 3500
    history = run({"ckd_stage": "4", "hyperkalemia_history": True}, {"potassium": 4.5})
    assert k_rule_of(history) == "K-2h" and history["targets"]["potassium_mg"] == 3000


def test_potassium_notes_and_alert_texts():
    urgent = run({"ckd_stage": "4"}, {"potassium": 6.3})
    assert note(urgent, "Potassium") == (
        "Potassium: 6.3 mmol/L on 2026-10-05 is dangerously high. Contact your care team today: this result should be repeated "
        "within 24 hours, and if you feel unwell (weakness, palpitations or an irregular pulse) get urgent medical care now "
        "(KDIGO 2024 Table 28). The ceiling is set to 2000 mg/day until your team gives you a number. " + R.POTASSIUM_NOTE
    )
    assert urgent["alerts"] == [{
        "level": "urgent", "code": "potassium_very_high", "analyte": "potassium", "value": 6.3, "taken_on": "2026-10-05",
        "message": "Potassium 6.3 mmol/L on 2026-10-05 is dangerously high. Contact your care team today: this result should be "
                   "repeated within 24 hours, and if you feel unwell (weakness, palpitations or an irregular pulse) get urgent "
                   "medical care now (KDIGO 2024 Table 28).",
    }]
    emergency = run({}, {"potassium": 6.6})["alerts"][0]
    assert emergency["level"] == "emergency" and emergency["message"].endswith(
        "Get urgent medical care now, especially with weakness, palpitations or an irregular pulse (KDIGO 2024 Table 28).")
    assert note(run({}), "Potassium") == (
        "Potassium: 3500 mg/day is a review ceiling for stage 3b, not a prescription; no blood potassium from the last 90 days "
        "is saved. " + R.POTASSIUM_NOTE
    )
    assert "review ceiling for hemodialysis" in note(run({"ckd_stage": "5", "dialysis": "hemodialysis"}), "Potassium")
    assert "for a kidney transplant at stage 2" in note(run({"ckd_stage": "2", "transplant_date": "2019-01-01"}), "Potassium")


@pytest.mark.parametrize(
    "p, rule, mg",
    [(2.4, "PH-1", None), (2.45, "PH-2", 1000), (2.5, "PH-2", 1000), (4.5, "PH-2", 1000), (4.54, "PH-2", 1000),
     (4.55, "PH-3", 800), (9.0, "PH-3", 800)],
)
def test_phosphate_thresholds(p, rule, mg):
    result = run({"ckd_stage": "5"}, {"phosphate": p})
    assert rule in rule_ids(result) and result["targets"]["phosphorus_mg"] == mg


def test_phosphorus_after_a_transplant():
    early_graft = {"ckd_stage": "3b", "transplant_date": "2019-01-01"}
    assert run(early_graft)["targets"]["phosphorus_mg"] is None and "PH-T" in rule_ids(run(early_graft))
    normal = run(early_graft, {"phosphate": 3.5})
    assert normal["targets"]["phosphorus_mg"] is None and "no phosphorus limit is set after a kidney transplant" in note(normal, "Phosphorus")
    assert run(early_graft, {"phosphate": 5.0})["targets"]["phosphorus_mg"] == 800
    late_graft = run({"ckd_stage": "5", "transplant_date": "2019-01-01"})
    assert late_graft["targets"]["phosphorus_mg"] == 900 and "PH-0" in rule_ids(late_graft)


def test_lab_freshness_windows_and_settings():
    def k_rule(taken_on: str, **settings: Any) -> str:
        result = T.suggest_from_records({"weight_kg": 70, "ckd_stage": "3b"}, labs_of({"potassium": 4.5}, taken_on), TODAY, **settings)
        return [i for i in rule_ids(result) if i.startswith("K-")][0]

    assert k_rule("2026-07-07") == "K-2"  # 90 days
    assert k_rule("2026-07-06") == "K-0"  # 91 days
    assert k_rule("2026-10-06") == "K-2"  # tomorrow (a time-zone ahead) still counts
    assert k_rule("2026-09-01", fresh_days={"potassium": 30}) == "K-0"
    result = T.suggest_from_records({"weight_kg": 70, "ckd_stage": "3b"}, labs_of({"potassium": 4.5}, "2026-09-01"), TODAY,
                                    fresh_days={"potassium": 30})
    assert "from the last 30 days" in note(result, "Potassium")
    # the newest result counts, not the highest
    rows = labs_of({"potassium": 6.2}, "2026-09-01") + [{"id": 9, "analyte": "potassium", "value": 4.4, "taken_on": "2026-10-01",
                                                          "entered_value": 4.4, "entered_unit": "mmol/L"}]
    assert k_rule_of(T.suggest_from_records({"weight_kg": 70, "ckd_stage": "3b"}, rows, TODAY)) == "K-2"


def test_lab_rules_switched_off_fall_back_but_keep_the_potassium_alert():
    """Note 05 §4.9 / C6: K-*/PH-* use K-0/PH-0, lab notes and lab-driven risk go, the safety alert stays."""
    labs = {"potassium": 6.6, "phosphate": 6.0, "albumin": 3.0, "bicarbonate": 16, "uacr": 500, "a1c": 8}
    result = run({"ckd_stage": "4"}, labs, lab_rules_enabled=False)
    ids = rule_ids(result)
    assert "K-0" in ids and "PH-0" in ids and not [i for i in ids if i.startswith("L-")]
    assert result["targets"]["potassium_mg"] == 3000 and result["targets"]["phosphorus_mg"] == 1000
    assert result["derived"]["nutrition_risk"] == [] and result["derived"]["lab_rules_enabled"] is False
    assert all(v is None for v in result["derived"]["labs_used"].values())
    assert "this server does not change it for blood test results" in note(result, "Potassium")
    assert "this server does not change it for blood test results" in note(result, "Phosphorus")
    assert [a["level"] for a in result["alerts"]] == ["emergency"]


# --------------------------------------------------------------------------- #
# Calcium, fluid, carbohydrate, fibre
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "birth_month, sex, expected",
    [("2008-01", "male", {"min": 1300, "max": 3000}), ("1990-01", "female", {"min": 1000, "max": 2500}),
     ("1970-01", "female", {"min": 1200, "max": 2000}), ("1970-01", "male", {"min": 1000, "max": 2000}),
     ("1970-01", "unspecified", {"min": 1200, "max": 2000}), ("1950-01", "male", {"min": 1200, "max": 2000})],
)
def test_calcium_reference_values_at_g1_g2(birth_month, sex, expected):
    result = run({"ckd_stage": "1", "birth_month": birth_month, "sex": sex})
    assert result["targets"]["calcium_mg"] == expected and "CA-3" in rule_ids(result)


@pytest.mark.parametrize(
    "profile, rule",
    [({"ckd_stage": "2"}, "CA-0"), ({"ckd_stage": "3a"}, "CA-1"), ({"ckd_stage": "4"}, "CA-1"), ({"ckd_stage": "5"}, "CA-2"),
     ({"ckd_stage": "5", "dialysis": "peritoneal"}, "CA-2"), ({"ckd_stage": "5", "transplant_date": "2019-01-01"}, "CA-2"),
     ({"ckd_stage": "2", "transplant_date": "2019-01-01", "birth_month": "1980-01"}, "CA-3")],
)
def test_calcium_rules(profile, rule):
    assert rule in rule_ids(run(profile))


def test_calcium_dri_table_covers_every_adult_age():
    for age in range(18, 131):
        rda, ul = T.calcium_dri(age, "female")
        assert 1000 <= rda <= 1300 and rda < ul
    assert T.calcium_dri(18, "male") == (1300, 3000)  # IOM 14–18 years (only age 18 gets here)
    with pytest.raises(ValueError):
        T.calcium_dri(13, "male")


@pytest.mark.parametrize(
    "profile, fluid, rule",
    [
        ({"dialysis": "hemodialysis"}, 1500, "F-1"),
        ({"dialysis": "hemodialysis", "urine_output_ml": 0}, 1000, "F-2"),
        ({"dialysis": "hemodialysis", "urine_output_ml": 324}, 1300, "F-2"),
        ({"dialysis": "hemodialysis", "urine_output_ml": 325}, 1350, "F-2"),
        ({"dialysis": "peritoneal", "urine_output_ml": 800}, 2000, "F-3"),
        ({"dialysis": "peritoneal", "urine_output_ml": 800, "pd_uf_ml": 913}, 1700, "F-4"),
        ({"ckd_stage": "3b", "birth_month": "1950-01", "sex": "male"}, None, "F-0o"),
        ({"ckd_stage": "4", "birth_month": "1950-01"}, None, "F-0"),
        ({"ckd_stage": "3b", "birth_month": "1970-01"}, None, "F-0"),
    ],
)
def test_fluid(profile, fluid, rule):
    profile = {"ckd_stage": "5", **profile} if "dialysis" in profile else profile
    result = run(profile)
    assert result["targets"]["fluid_ml"] == fluid and rule in rule_ids(result)


def test_fluid_notes():
    assert note(run({"ckd_stage": "5", "dialysis": "hemodialysis", "urine_output_ml": 300}), "Fluid") == (
        "Fluid: 1000 mL + your 300 mL of urine = 1300 mL/day, the usual hemodialysis allowance; your unit may set a different number."
    )
    assert "aim for at least 2.0 L of drinks a day" in note(run({"birth_month": "1950-01", "sex": "male"}), "Fluid")
    assert "at least 1.6 L (women) or 2.0 L (men)" in note(run({"birth_month": "1950-01"}), "Fluid")


def test_carbohydrate_uses_half_up_rounding():
    """2280 × 0.45 / 4 = 256.5 -> 257 (v0.2's round() gave 256); per meal 64.25 -> 65."""
    result = run({"height_cm": 175, "birth_month": "1971-03", "sex": "male"})
    assert result["targets"]["calories_kcal"] == 2280 and result["targets"]["carbs_g"] == 257
    assert result["targets"]["carbs_per_meal_g"] == 65 and result["targets"]["fiber_g"] == {"min": 32}
    assert note(result, "Carbohydrate").endswith("your insulin-to-carb ratio decides the real per-meal number.")
    assert note(run({"diabetes": "none"}), "Carbohydrate") == "Carbohydrate: 45 % of calories ÷ 4 kcal/g = 236 g/day."
    tiny = run({"weight_kg": 25})
    assert tiny["targets"]["carbs_per_meal_g"] == 20 and run({"weight_kg": 15})["targets"]["carbs_per_meal_g"] == 15


# --------------------------------------------------------------------------- #
# Lab notes
# --------------------------------------------------------------------------- #


def test_bicarbonate_notes():
    assert not [i for i in rule_ids(run({}, {"bicarbonate": 22.0})) if i.startswith("L-")]
    assert not [i for i in rule_ids(run({}, {"bicarbonate": 21.95})) if i.startswith("L-")]  # shown 22.0
    g3 = run({"ckd_stage": "3a"}, {"bicarbonate": 21.0})
    assert note(g3, "Bicarbonate") == (
        "Bicarbonate 21.0 mmol/L is below 22: acid builds up as kidneys fail. More fruit and vegetables lower the acid load "
        "(KDOQI 2020 6.1.1). Your team may prescribe bicarbonate (KDOQI 2020 6.1.2)."
    )
    high_k = run({"ckd_stage": "3a"}, {"bicarbonate": 21.0, "potassium": 5.2})
    assert "(KDOQI 2020 6.1.1) (your potassium is high, so ask your team first). " in note(high_k, "Bicarbonate")
    g5 = note(run({"ckd_stage": "5"}, {"bicarbonate": 20.5}), "Bicarbonate")  # TV22: no fruit-and-vegetable sentence
    assert g5 == "Bicarbonate 20.5 mmol/L is below 22: acid builds up as kidneys fail. Your team may prescribe bicarbonate (KDOQI 2020 6.1.2)."
    hd = run({"ckd_stage": "5", "dialysis": "hemodialysis"}, {"bicarbonate": 17.0})
    assert [i for i in rule_ids(hd) if i.startswith("L-")] == ["L-BIC22", "L-BIC18"]
    assert hd["notes"][-2] == (
        "Bicarbonate 17.0 mmol/L is below 18. KDIGO 2024 says treatment should be considered at this level (practice point 3.10.1); "
        "tell your care team."
    )


def test_uacr_notes_use_the_entered_unit():
    rows = [{"id": 1, "analyte": "uacr", "value": 3.0 / 0.113, "entered_value": 3.0, "entered_unit": "mg/mmol", "taken_on": "2026-10-01"}]
    result = T.suggest_from_records({"weight_kg": 70, "ckd_stage": "3b"}, rows, TODAY)
    assert rule_ids(result)[-1] == "L-UACR-A2"
    assert result["notes"][-2] == (
        "Urine albumin 3.0 mg/mmol (as entered) is category A2 (moderately increased). It does not change food targets but is a "
        "reason to keep sodium low (KDOQI 2020 6.5.2)."
    )
    a3 = run({}, {"uacr": 450, "albumin": 3.2})
    assert a3["notes"][-2].endswith("With low blood albumin this can mean protein is lost in urine; your team may set protein differently.")
    assert rule_ids(run({}, {"uacr": 12}))[-1] == "L-UACR-A1"


def test_a1c_note_only_for_a_recent_result():
    assert rule_ids(run({}, {"a1c": 7.4}))[-1] == "L-A1C"
    stale = T.suggest_from_records({"weight_kg": 70, "ckd_stage": "3b"}, labs_of({"a1c": 7.4}, "2025-09-01"), TODAY)
    assert "L-A1C" not in rule_ids(stale)


# --------------------------------------------------------------------------- #
# Shape, inputs and the v0.2 wrapper
# --------------------------------------------------------------------------- #


def test_derived_and_missing_inputs():
    result = run({"ckd_stage": "5", "dialysis": "peritoneal"}, {"potassium": 4.0})
    assert result["missing_inputs"] == ["height_cm", "birth_month", "sex", "activity", "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal"]
    assert result["derived"]["labs_used"]["potassium"] == {"value": 4.0, "unit": "mmol/L", "taken_on": "2026-10-05"}
    full = run({"height_cm": 175, "birth_month": "1971-03", "sex": "male", "activity": "active"})
    assert full["missing_inputs"] == []
    assert set(full["derived"]) == {"mode", "age", "sex", "activity", "bmi", "reference_weight_kg", "weight_basis", "eer_kcal",
                                    "eer_kcal_per_kg", "kcal_per_kg", "nutrition_risk", "labs_used", "lab_rules_enabled"}
    hd = run({"ckd_stage": "5", "dialysis": "hemodialysis", "urine_output_ml": 0})
    assert "urine_output_ml" not in hd["missing_inputs"] and "pd_uf_ml" not in hd["missing_inputs"]


def test_rule_entries_carry_source_grade_and_opinion():
    result = run({"height_cm": 175, "birth_month": "1971-03", "sex": "male"})
    e1 = result["rules"][1]
    assert e1 == {"id": "E-1", "source": "NASEM 2023 DRI Energy Table S-1; KDOQI 2020 3.1.1", "grade": "DRI; 1C (range)",
                  "opinion": True, "opinion_note": "combining the energy equation with the kidney range", "url": R.URL_NASEM_2023_ENERGY}
    p2 = result["rules"][2]
    assert p2["id"] == "P-2" and p2["grade"] == "A / 2C / 2C" and p2["opinion"] is False
    assert run({"diabetes": "none"})["rules"][2]["grade"] == "1A (supervised) / 2C / PP"


def test_the_catalogue_covers_every_rule_of_section_4_4():
    ids = {"S-1", "S-2", "S-3", "W-1", "W-2", "W-3", "W-4", "N-1", "E-1", "E-2", "E-3", "E-4", "P-1", "P-2d", "P-2n", "P-3", "P-5",
           "P-6", "P-7", "K-0", "K-1", "K-2", "K-2h", "K-3", "K-4", "K-5", "PH-0", "PH-T", "PH-1", "PH-2", "PH-3", "NA-1", "CA-0",
           "CA-1", "CA-2", "CA-3", "F-0", "F-0o", "F-1", "F-2", "F-3", "F-4", "C-1", "FB-1", "L-ALB", "L-BIC22", "L-BIC18",
           "L-UACR-A1", "L-UACR-A2", "L-UACR-A3", "L-A1C", "G-1"}
    assert set(R.RULES) == ids
    for rule_id, rule in R.RULES.items():
        assert rule["opinion"] == (rule["opinion_note"] is not None), rule_id
        assert rule["url"].startswith("https://"), rule_id
    for code, (rule, message) in R.REFUSALS.items():
        assert rule in R.RULES and message.endswith("by hand.") and code.startswith("out_of_scope_")


def test_every_note_template_formats_without_leftover_placeholders():
    for profile, labs in itertools.islice(random_profiles(400, seed=7), 400):
        try:
            result = T.suggest_from_records(profile, labs_of(labs), TODAY)
        except T.OutOfScope:
            continue
        for text in result["notes"]:
            assert "{" not in text and "}" not in text and "  " not in text and not text.startswith(" "), text


@pytest.mark.parametrize(
    "profile, message",
    [
        ({"weight_kg": 0}, "weight_kg must be a positive number"),
        ({"weight_kg": float("nan")}, "weight_kg must be a positive number"),
        ({"height_cm": -1}, "height_cm must be a positive number"),
        ({"ckd_stage": "6"}, "ckd_stage must be one of"),
        ({"dialysis": "sometimes"}, "dialysis must be one of"),
        ({"diabetes": "lada"}, "diabetes must be one of"),
        ({"sex": "x"}, "sex must be one of"),
        ({"activity": "athlete"}, "activity must be one of"),
        ({"birth_month": "1970-13"}, "birth_month must be formatted YYYY-MM"),
        ({"birth_month": "2026-11"}, "birth_month must not be in the future"),
        ({"birth_month": "1900-01"}, "birth_month must be within the last 120 years"),
        ({"transplant_date": "2026-02-30"}, "day is out of range"),
        ({"transplant_date": "01/02/2020"}, "transplant_date must be formatted YYYY-MM-DD"),
        ({"urine_output_ml": -5, "dialysis": "hemodialysis", "ckd_stage": "5"}, "urine_output_ml must be a non-negative number"),
    ],
)
def test_invalid_inputs_raise_clear_errors(profile, message):
    with pytest.raises(ValueError, match=None) as info:
        run(profile)
    assert message in str(info.value)


def test_today_is_injected_and_results_are_deterministic():
    profile = {"height_cm": 175, "birth_month": "1971-10", "sex": "male"}
    assert run(profile, today=date(2026, 9, 30))["derived"]["age"] == 54
    assert run(profile, today=date(2026, 10, 1))["derived"]["age"] == 55
    assert run(profile) == run(profile)


def test_v0_2_wrapper_keeps_its_signature_and_shape():
    """Existing callers (the guidance vectors use suggest_targets(70, "4") and (70, "5", "hemodialysis"))."""
    four = nutrients.suggest_targets(70, "4")
    assert set(four) == {"targets", "notes"}
    assert four == {k: v for k, v in run({"ckd_stage": "4"}).items() if k in ("targets", "notes")}
    hd = nutrients.suggest_targets(70, "5", "hemodialysis")
    assert hd["targets"]["protein_g"] == {"min": 70, "max": 84} and hd["targets"]["fluid_ml"] == 1500
    assert nutrients.suggest_targets(70, "3b", "none", "type1", height_cm=170)["targets"]["calories_kcal"] == 2100
    with pytest.raises(ValueError):
        nutrients.suggest_targets(70, "3b", "none", "type1", height_cm=0)
