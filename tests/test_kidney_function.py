"""eGFR, G and A categories and the kidney-function card (``app/kidney_function.py``; note 05 §4.3, §5.2)."""
from __future__ import annotations

from datetime import date

import pytest

from app import kidney_function as kf
from app import units

TODAY = date(2026, 10, 5)


@pytest.mark.parametrize(
    "vector, compute, unrounded, rounded, category",
    [
        ("E1", lambda: kf.egfr_cr(1.2, 50, "female"), 55.147, 55, "G3a"),
        ("E2", lambda: kf.egfr_cr(1.2, 50, "male"), 73.674, 74, "G2"),
        ("E3", lambda: kf.egfr_cr(2.0, 70, "male"), 35.243, 35, "G3b"),
        ("E4", lambda: kf.egfr_cr(units.to_canonical("creatinine", 106, "µmol/L"), 65, "female"), 50.280, 50, "G3a"),
        ("E5", lambda: kf.egfr_cr(0.6, 30, "female"), 123.758, 124, "G1"),  # below kappa: the alpha branch
        ("E6", lambda: kf.egfr_cr_cys(1.5, 1.6, 60, "male"), 47.165, 47, "G3a"),
        ("E7", lambda: kf.egfr_cys(1.2, 40, "female"), 61.630, 62, "G2"),
        ("E8", lambda: kf.egfr_cr(1.1, 60, "female"), 57.525, 58, "G3a"),
        ("E9", lambda: kf.egfr_cr(1.1, 60, "male"), 76.851, 77, "G2"),
        ("E10", lambda: kf.egfr_cr(4.8, 75, "female"), 8.944, 9, "G5"),
    ],
)
def test_egfr_vectors(vector, compute, unrounded, rounded, category):
    value = compute()
    assert value == pytest.approx(unrounded, abs=0.01), vector
    assert kf.round_egfr(value) == rounded
    assert kf.gfr_category(value) == category


def test_fact_check_sanity_value():
    """Note 05 §10.1: a 50-year-old man with creatinine 1.0 mg/dL gives 91.7."""
    assert kf.egfr_cr(1.0, 50, "male") == pytest.approx(91.7, abs=0.05)


def test_equation_branches_on_both_sides_of_kappa_and_0_8():
    # creatinine exactly at kappa: both min and max terms are 1
    assert kf.egfr_cr(0.9, 40, "male") == pytest.approx(142 * 0.9938**40)
    assert kf.egfr_cr(0.7, 40, "female") == pytest.approx(142 * 0.9938**40 * 1.012)
    assert kf.egfr_cys(0.8, 40, "male") == pytest.approx(133 * 0.996**40)
    assert kf.egfr_cr_cys(0.9, 0.8, 40, "male") == pytest.approx(135 * 0.9961**40)
    # lower levels give a higher eGFR, on every branch
    for f in (lambda x: kf.egfr_cr(x, 50, "female"), lambda x: kf.egfr_cys(x, 50, "male"), lambda x: kf.egfr_cr_cys(x, x, 50, "female")):
        assert f(0.5) > f(0.8) > f(1.2) > f(3.0)


@pytest.mark.parametrize(
    "egfr, category",
    [(120, "G1"), (90, "G1"), (89.5, "G1"), (89.49, "G2"), (60, "G2"), (59.5, "G2"), (59.49, "G3a"), (45, "G3a"),
     (44.6, "G3a"), (44.4, "G3b"), (30, "G3b"), (29.4, "G4"), (15, "G4"), (14.5, "G4"), (14.49, "G5"), (0.4, "G5")],
)
def test_g_category_is_judged_on_the_integer_shown(egfr, category):
    assert kf.gfr_category(egfr) == category


@pytest.mark.parametrize(
    "value, unit, category",
    [
        (29.9, "mg/g", "A1"), (29.96, "mg/g", "A2"), (30, "mg/g", "A2"), (300.0, "mg/g", "A2"),
        (300.04, "mg/g", "A2"), (300.05, "mg/g", "A3"), (0, "mg/g", "A1"),  # U7
        (25, "mg/mmol", "A2"),  # U4
        (3.0, "mg/mmol", "A2"),  # U5: 26.5 mg/g would be A1, but the entered unit decides
        (2.94, "mg/mmol", "A1"), (2.95, "mg/mmol", "A2"), (30.04, "mg/mmol", "A2"), (30.05, "mg/mmol", "A3"),
    ],
)
def test_albuminuria_category_in_the_entered_unit(value, unit, category):
    assert kf.albuminuria_category(value, unit) == category


def test_albuminuria_refuses_other_units():
    with pytest.raises(units.UnitError):
        kf.albuminuria_category(30, "mg/L")


@pytest.mark.parametrize(
    "call",
    [
        lambda: kf.egfr_cr(1.0, 17, "male"),
        lambda: kf.egfr_cr(1.0, 40, "unspecified"),
        lambda: kf.egfr_cr(0, 40, "male"),
        lambda: kf.egfr_cys(float("nan"), 40, "male"),
        lambda: kf.egfr_cr_cys(1.0, -1, 40, "female"),
        lambda: kf.egfr_cr(1.0, 40.5, "male"),
    ],
)
def test_equations_refuse_inputs_they_were_not_built_for(call):
    with pytest.raises(kf.KidneyFunctionError):
        call()


def test_age_counts_completed_years_from_the_first_or_last_day_of_the_month():
    assert kf.age_on("1971-03", TODAY) == 55
    assert kf.age_on("1976-10", TODAY) == 50  # 1976-10-01 -> 50 on 2026-10-05
    assert kf.age_on("2008-10", TODAY) == 18
    assert kf.age_on("2008-10", TODAY, last_day=True) == 17  # 2008-10-31: still 17 (note 05 M5)
    assert kf.age_on("2008-09", TODAY, last_day=True) == 18
    assert kf.age_on("2000-02", date(2026, 2, 28), last_day=True) == 25  # 29 Feb 2000 -> not yet 26
    assert kf.age_on("2008-12", date(2026, 12, 31), last_day=True) == 18
    assert kf.age_on(None, TODAY) is None


# --------------------------------------------------------------------------- #
# The card (GET /api/labs/kidney-function)
# --------------------------------------------------------------------------- #


def lab(i: int, analyte: str, value: float, taken_on: str = "2026-10-01", unit: str | None = None, entered: float | None = None):
    return {"id": i, "analyte": analyte, "value": value, "taken_on": taken_on,
            "entered_value": value if entered is None else entered, "entered_unit": unit or units.analyte_def(analyte).canonical_unit}


def card(labs, **profile):
    defaults = {"ckd_stage": "3b", "birth_month": "1976-10", "sex": "female"}
    return kf.assess(labs=labs, today=TODAY, **{**defaults, **profile})


def test_no_results():
    out = card([])
    assert out["egfr"] is None and out["albuminuria"] is None
    assert out["message"].startswith("No creatinine, cystatin C or eGFR result from the last 365 days")


def test_creatinine_gives_a_g1_suggestion_text_and_never_changes_the_stage():
    out = card([lab(1, "creatinine", 1.2)])
    egfr = out["egfr"]
    assert egfr["value"] == 55 and egfr["method"] == "ckd_epi_2021_cr" and egfr["category"] == "G3a"
    assert egfr["suggested_stage"] == "3a" and egfr["matches_profile"] is False and egfr["taken_on"] == "2026-10-01"
    assert out["profile_stage"] == "3b"
    assert out["message"] == (
        "Your eGFR on 2026-10-01 is 55 mL/min/1.73 m² (CKD-EPI 2021, creatinine), which is stage G3a. Your profile says "
        "stage 3b. One result does not change a stage — kidney disease stages need results over 3 months (KDIGO 2024). "
        "Talk to your nephrologist before changing it."
    )


def test_lab_reported_egfr_wins_on_the_same_day_but_a_newer_creatinine_wins_over_an_older_lab_egfr():
    same_day = card([lab(1, "creatinine", 1.2), lab(2, "egfr", 41)])
    assert same_day["egfr"]["method"] == "lab" and same_day["egfr"]["value"] == 41 and same_day["egfr"]["category"] == "G3b"
    assert "(reported by your lab)" in same_day["message"]
    newer = card([lab(1, "egfr", 41, "2026-06-01"), lab(2, "creatinine", 1.2, "2026-09-01")])
    assert newer["egfr"]["method"] == "ckd_epi_2021_cr" and newer["egfr"]["taken_on"] == "2026-09-01"


def test_creatinine_and_cystatin_on_the_same_day_use_the_combined_equation():
    out = card([lab(1, "creatinine", 1.5), lab(2, "cystatin_c", 1.6)], birth_month="1966-01", sex="male")
    assert out["egfr"]["method"] == "ckd_epi_2021_cr_cys" and out["egfr"]["value"] == 47  # E6 (age 60)
    apart = card([lab(1, "creatinine", 1.5, "2026-09-01"), lab(2, "cystatin_c", 1.2, "2026-09-20")], birth_month="1986-01")
    assert apart["egfr"]["method"] == "ckd_epi_2012_cys" and apart["egfr"]["value"] == 62  # E7 (age 40): the newer one


def test_the_newest_entry_of_a_day_is_used():
    out = card([lab(1, "creatinine", 2.0), lab(5, "creatinine", 1.2), lab(3, "creatinine", 4.0)])
    assert out["egfr"]["value"] == 55


def test_unspecified_sex_reports_both_formulas_and_suggests_only_when_they_agree():
    split = card([lab(1, "creatinine", 1.1)], birth_month="1966-04", sex="unspecified")  # E8/E9
    egfr = split["egfr"]
    assert egfr["value"] is None and egfr["female"] == 58 and egfr["male"] == 77
    assert egfr["category"] is None and egfr["suggested_stage"] is None
    assert split["message"].startswith("Your eGFR on 2026-10-01 is 58–77 mL/min/1.73 m² (CKD-EPI 2021, creatinine): the female")
    assert "does not suggest one" in split["message"]
    agree = card([lab(1, "creatinine", 3.0)], birth_month="1966-04", sex="unspecified")
    assert agree["egfr"]["category"] == "G4" and agree["egfr"]["female"] < agree["egfr"]["male"]
    lo, hi = agree["egfr"]["female"], agree["egfr"]["male"]
    assert f"is {lo}–{hi} mL/min/1.73 m²" in agree["message"] and f"(female formula {lo}, male formula {hi})" in agree["message"]
    # a lab-reported eGFR needs no sex
    assert card([lab(1, "egfr", 58)], sex="unspecified")["egfr"]["value"] == 58


def test_transplant_categories_carry_a_t():
    out = card([lab(1, "creatinine", 1.2)], transplant=True)
    assert out["egfr"]["category"] == "G3aT" and out["mode"] == "transplant"
    assert "which is stage G3aT." in out["message"]


@pytest.mark.parametrize(
    "profile, text",
    [
        ({"dialysis": "hemodialysis", "ckd_stage": "5"}, "not estimated on dialysis"),
        ({"dialysis": "peritoneal", "ckd_stage": "5"}, "not estimated on dialysis"),
        ({"pregnant_or_breastfeeding": True}, "not estimated during pregnancy"),
        ({"birth_month": "2008-10"}, "not estimated for people under 18"),
    ],
)
def test_no_estimate_on_dialysis_in_pregnancy_or_under_18(profile, text):
    out = card([lab(1, "creatinine", 1.2), lab(2, "egfr", 50)], **profile)
    assert out["egfr"] is None and text in out["message"]


def test_a_missing_age_asks_for_the_birth_month_or_falls_back_to_a_lab_egfr():
    out = card([lab(1, "creatinine", 1.2)], birth_month=None)
    assert out["egfr"] is None and out["message"].startswith("Add your birth month to estimate kidney function from your creatinine")
    older_lab = card([lab(1, "egfr", 52, "2026-08-01"), lab(2, "creatinine", 1.2, "2026-10-01")], birth_month=None)
    assert older_lab["egfr"]["method"] == "lab" and older_lab["egfr"]["value"] == 52


def test_results_older_than_365_days_are_ignored():
    assert card([lab(1, "creatinine", 1.2, "2025-10-05")])["egfr"]["value"] == 55  # exactly 365 days
    assert card([lab(1, "creatinine", 1.2, "2025-10-04")])["egfr"] is None


def test_albuminuria_uses_the_entered_unit():
    out = card([lab(1, "uacr", 3.0 / 0.113, unit="mg/mmol", entered=3.0)])
    assert out["albuminuria"] == {"value_mg_g": 26.5, "category": "A2", "label": "moderately increased",
                                  "entered_value": 3.0, "entered_unit": "mg/mmol", "taken_on": "2026-10-01"}
    # also shown on dialysis (it is not an eGFR)
    assert card([lab(1, "uacr", 450)], dialysis="hemodialysis")["albuminuria"]["category"] == "A3"


def test_assess_refuses_an_unknown_sex():
    with pytest.raises(kf.KidneyFunctionError):
        card([], sex="other")
