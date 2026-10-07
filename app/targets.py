"""Personalised suggested targets (note 05 §4.3–§4.6): pure functions, no I/O.

``suggest(inputs, today)`` turns a profile, the person's fresh lab results and three instance
settings into starting-point targets, the notes that explain them, the rules applied (with source,
grade and whether part of it is the project's own opinion), derived values, the inputs that would
make it more personal, and safety alerts. It raises :class:`OutOfScope` for pregnancy, under-18s
and the first 12 weeks after a transplant: those people get no numbers at all.

All numbers, equations and note texts live in :mod:`app.target_rules`. All rounding is decimal
half-up (``app.nutrients._half_up``). ``today`` is always a parameter so results are deterministic.

Callers: ``app.profile`` (``GET /api/profile/suggested-targets``, via :func:`suggest_from_records`),
``app.nutrients.suggest_targets`` (the v0.2 signature, without the new inputs) and the parity vector
generator ``tests/data/gen_targets_vectors.py``, which pins the browser twin to this module.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping

from . import target_rules as R
from . import units
from .kidney_function import ALBUMINURIA_LABELS, LabRow, age_on, albuminuria_category, is_fresh, newest
from .nutrients import CKD_STAGES, DIABETES_TYPES, DIALYSIS_MODES, _half_up

BIRTH_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_AGE = 120  # note 05 §4.2: birth year within the last 120 years

# Labs that change targets or notes; others (creatinine, cystatin C, eGFR) only feed kidney_function.
TARGET_LABS: tuple[str, ...] = ("potassium", "phosphate", "albumin", "bicarbonate", "uacr", "a1c")
# Defaults of the instance settings (app/settings_registry.py, note 05 §4.9).
DEFAULT_FRESH_DAYS: dict[str, int] = {a: int(units.ANALYTES[a].fresh_days or 0) for a in units.CONFIGURABLE_FRESHNESS}


class OutOfScope(Exception):
    """The person is outside what the rules cover; the API answers 422 with ``code`` and ``message``."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.rule, self.message = R.REFUSALS[code]
        super().__init__(self.message)


@dataclass(frozen=True)
class Lab:
    """One lab result as the rules use it: canonical ``value`` plus what was typed."""

    value: float
    taken_on: str
    entered_value: float | None = None
    entered_unit: str | None = None


@dataclass(frozen=True)
class Inputs:
    """Everything :func:`suggest` reads. Field names follow note 05 §4.2."""

    weight_kg: float
    ckd_stage: str
    dialysis: str = "none"
    diabetes: str = "type1"
    height_cm: float | None = None
    birth_month: str | None = None
    sex: str = "unspecified"
    activity: str | None = None  # None: not chosen, the instance default applies
    transplant_date: str | None = None
    frail_or_sarcopenic: bool = False
    weight_6_months_ago_kg: float | None = None
    pregnant_or_breastfeeding: bool = False
    hyperkalemia_history: bool = False
    urine_output_ml: float | None = None
    pd_uf_ml: float | None = None
    pd_dialysate_kcal: float | None = None
    # Fresh lab results by analyte (already filtered, see :func:`fresh_labs`).
    labs: Mapping[str, Lab] = field(default_factory=dict)
    # Instance settings (note 05 §4.9).
    lab_rules_enabled: bool = True
    default_activity: str = "inactive"
    fresh_days: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_FRESH_DAYS))


@dataclass(frozen=True)
class ReferenceWeight:
    """The weight calories and protein are computed per kg of (note 05 §4.3 "Reference weight")."""

    weight_kg: float  # rounded to 0.1 kg
    basis: str  # actual | actual_no_height | adjusted_above_bmi25 | adjusted_below_bmi18_5
    bmi: float | None  # unrounded
    w25: float | None  # weight at BMI 25 for the height (unrounded)
    w18_5: float | None  # weight at BMI 18.5


@dataclass(frozen=True)
class Suggestion:
    targets: dict[str, Any]
    notes: list[str]
    rules: list[dict[str, Any]]
    derived: dict[str, Any]
    missing_inputs: list[str]
    alerts: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": self.targets,
            "notes": self.notes,
            "rules": self.rules,
            "derived": self.derived,
            "missing_inputs": self.missing_inputs,
            "alerts": self.alerts,
        }


# --------------------------------------------------------------------------- #
# Small pure helpers
# --------------------------------------------------------------------------- #


def _int(value: float) -> int:
    return int(_half_up(float(value), 0))


def _round_step(value: float, step: int) -> int:
    """Half-up to a multiple of ``step`` (10 kcal, 50 mL, 5 g)."""
    return int(_half_up(float(value) / step, 0)) * step


def _calories(value: float) -> int:
    return int(_half_up(float(value), -1))  # nearest 10 kcal, decimal half-up on the shortest repr


def reference_weight(weight_kg: float, height_cm: float | None) -> ReferenceWeight:
    """Sex-neutral reference weight (KDOQI 2020 Table 5 formulas on the BMI-based desirable weight) [OPINION].

    Above BMI 25: the BMI-25 weight plus a quarter of the excess (Karkeck adjusted weight). Below BMI
    18.5: the actual weight moved a quarter of the way to the BMI-18.5 weight (KDOQI 2000). In
    between (exactly 25 and 18.5 included) or without a height: the actual weight. Continuous at
    both edges. Rounded half-up to 0.1 kg.
    """
    w = float(weight_kg)
    if not math.isfinite(w) or w <= 0:
        raise ValueError("weight_kg must be a positive number")
    if height_cm is None:
        return ReferenceWeight(_half_up(w, 1), "actual_no_height", None, None, None)
    h_cm = float(height_cm)
    if not math.isfinite(h_cm) or h_cm <= 0:
        raise ValueError("height_cm must be a positive number")
    h = h_cm / 100.0
    h2 = h * h
    bmi = w / h2
    w25 = R.BMI_HIGH * h2
    w185 = R.BMI_LOW * h2
    if bmi > R.BMI_HIGH + R.BMI_EPS:
        ref, basis = w25 + R.ADJUST_FRACTION * (w - w25), "adjusted_above_bmi25"
    elif bmi < R.BMI_LOW - R.BMI_EPS:
        ref, basis = w + R.ADJUST_FRACTION * (w185 - w), "adjusted_below_bmi18_5"
    else:
        ref, basis = w, "actual"
    return ReferenceWeight(_half_up(ref, 1), basis, bmi, w25, w185)


def eer_kcal(sex: str, activity: str, age: int, height_cm: float, weight_kg: float) -> float:
    """NASEM 2023 estimated energy requirement (Table S-1, adults), kcal/day, unrounded.

    ``sex == "unspecified"`` gives the mean of the female and male equations.
    """
    if activity not in R.ACTIVITIES:
        raise ValueError(f"activity must be one of {', '.join(R.ACTIVITIES)}")
    if sex == "unspecified":
        return (eer_kcal("female", activity, age, height_cm, weight_kg) + eer_kcal("male", activity, age, height_cm, weight_kg)) / 2
    if sex not in ("female", "male"):
        raise ValueError(f"sex must be one of {', '.join(R.SEXES)}")
    intercept, a, h, w = R.EER_COEFFICIENTS[sex][activity]
    return intercept + a * age + h * float(height_cm) + w * float(weight_kg)


def mode_of(dialysis: str, transplant_date: str | None) -> str:
    """``hemodialysis`` | ``peritoneal`` | ``transplant`` (no dialysis, a transplant date) | ``ckd``."""
    if dialysis in ("hemodialysis", "peritoneal"):
        return dialysis
    return "transplant" if transplant_date else "ckd"


def lab_display(analyte: str, lab: Lab | None) -> float | None:
    """The value the rules compare: canonical, rounded half-up to the analyte's shown decimals."""
    return None if lab is None else units.display_value(analyte, lab.value)


def fresh_labs(rows: Iterable[Mapping[str, Any] | LabRow], today: date, fresh_days: Mapping[str, int] | None = None) -> dict[str, Lab]:
    """The newest result of each target lab, kept only when it is fresh (note 05 §4.2 windows).

    ``fresh_days`` overrides the potassium/phosphate/albumin/bicarbonate windows (settings
    ``targets.lab_fresh_days.*``); UACR and A1c use their fixed 365 days.
    """
    windows = {**DEFAULT_FRESH_DAYS, **(fresh_days or {})}
    parsed = [r if isinstance(r, LabRow) else LabRow.from_mapping(r) for r in rows]
    out: dict[str, Lab] = {}
    for analyte in TARGET_LABS:
        latest = newest(r for r in parsed if r.analyte == analyte)
        if latest is None:
            continue
        if is_fresh(latest.taken_on, today, units.fresh_days(analyte, windows)):
            out[analyte] = Lab(latest.value, latest.taken_on, latest.entered_value, latest.entered_unit)
    return out


def validate_inputs(inputs: Inputs, today: date) -> None:
    """Raise ``ValueError`` with a clear message for anything the rules cannot use."""
    w = inputs.weight_kg
    if w is None or isinstance(w, bool) or not math.isfinite(float(w)) or float(w) <= 0:
        raise ValueError("weight_kg must be a positive number")
    if inputs.height_cm is not None and (not math.isfinite(float(inputs.height_cm)) or float(inputs.height_cm) <= 0):
        raise ValueError("height_cm must be a positive number")
    if inputs.ckd_stage not in CKD_STAGES:
        raise ValueError(f"ckd_stage must be one of {', '.join(CKD_STAGES)}")
    if inputs.dialysis not in DIALYSIS_MODES:
        raise ValueError(f"dialysis must be one of {', '.join(DIALYSIS_MODES)}")
    if inputs.diabetes not in DIABETES_TYPES:
        raise ValueError(f"diabetes must be one of {', '.join(DIABETES_TYPES)}")
    if inputs.sex not in R.SEXES:
        raise ValueError(f"sex must be one of {', '.join(R.SEXES)}")
    for name, value in (("activity", inputs.activity), ("default_activity", inputs.default_activity)):
        if value is not None and value not in R.ACTIVITIES:
            raise ValueError(f"{name} must be one of {', '.join(R.ACTIVITIES)}")
    if inputs.birth_month is not None:
        if not BIRTH_MONTH_RE.match(inputs.birth_month):
            raise ValueError("birth_month must be formatted YYYY-MM")
        if inputs.birth_month > today.isoformat()[:7]:
            raise ValueError("birth_month must not be in the future")
        if (age_on(inputs.birth_month, today) or 0) > MAX_AGE:
            raise ValueError(f"birth_month must be within the last {MAX_AGE} years")
    if inputs.transplant_date is not None:
        if not DATE_RE.match(inputs.transplant_date):
            raise ValueError("transplant_date must be formatted YYYY-MM-DD")
        date.fromisoformat(inputs.transplant_date)  # ValueError for 2026-02-30
    for name in ("weight_6_months_ago_kg", "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal"):
        value = getattr(inputs, name)
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError(f"{name} must be a non-negative number")


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #


class _Builder:
    """Collects rules (in application order) and their notes."""

    def __init__(self) -> None:
        self.rules: list[dict[str, Any]] = []
        self.notes: list[str] = []

    def apply(self, rule_id: str, note: str | None = None, *, catalogue_id: str | None = None) -> None:
        entry = R.RULES[catalogue_id or rule_id]
        self.rules.append({"id": rule_id, **entry})
        if note:
            self.notes.append(note)


def _stage_label(mode: str, stage: str) -> str:
    if mode == "hemodialysis":
        return "hemodialysis"
    if mode == "peritoneal":
        return "peritoneal dialysis"
    if mode == "transplant":
        return f"a kidney transplant at stage {stage}"
    return f"stage {stage}"


def suggest(inputs: Inputs, today: date) -> Suggestion:
    """Apply note 05 §4.3/§4.4 to ``inputs`` on ``today``; raises :class:`OutOfScope` or ``ValueError``."""
    validate_inputs(inputs, today)
    mode = mode_of(inputs.dialysis, inputs.transplant_date)
    stage = inputs.ckd_stage
    on_dialysis = mode in ("hemodialysis", "peritoneal")
    ladder_key = mode if on_dialysis else stage
    has_diabetes = inputs.diabetes != "none"
    age = age_on(inputs.birth_month, today)

    # S: refusals, before any number.
    if inputs.pregnant_or_breastfeeding:
        raise OutOfScope("out_of_scope_pregnancy")
    if inputs.birth_month is not None and (age_on(inputs.birth_month, today, last_day=True) or 0) < R.ADULT_AGE:
        raise OutOfScope("out_of_scope_under_18")
    if mode == "transplant":
        assert inputs.transplant_date is not None
        if (today - date.fromisoformat(inputs.transplant_date)).days < R.EARLY_TRANSPLANT_DAYS:
            raise OutOfScope("out_of_scope_early_transplant")

    b = _Builder()
    labs_on = inputs.lab_rules_enabled
    lab = {a: (inputs.labs.get(a) if labs_on else None) for a in TARGET_LABS}
    shown = {a: lab_display(a, lab[a]) for a in TARGET_LABS}
    windows = {**DEFAULT_FRESH_DAYS, **dict(inputs.fresh_days)}

    # W: reference weight.
    actual = float(inputs.weight_kg)
    rw = reference_weight(actual, inputs.height_cm)
    ref = rw.weight_kg
    bmi_shown = None if rw.bmi is None else _half_up(rw.bmi, 1)
    h = None if inputs.height_cm is None else float(inputs.height_cm)
    if rw.basis == "actual_no_height":
        w_id, w_note = "W-2", R.NOTES["W-2"].format(w=actual)
    elif rw.basis == "actual":
        w_id, w_note = "W-1", R.NOTES["W-1"].format(w=actual, bmi=bmi_shown, h=h)
    elif rw.basis == "adjusted_above_bmi25":
        w_id, w_note = "W-3", R.NOTES["W-3"].format(bmi=bmi_shown, ref=ref, h=h, w25=_half_up(rw.w25 or 0.0, 1))
    else:
        w_id, w_note = "W-4", R.NOTES["W-4"].format(bmi=bmi_shown, ref=ref, w185=_half_up(rw.w18_5 or 0.0, 1))
    if on_dialysis:
        w_note += R.NOTES["W-D"]
    b.apply(w_id, w_note)

    # N: nutrition risk (a flag, not a diagnosis).
    risk: list[str] = []
    reasons: list[str] = []
    if bmi_shown is not None:
        threshold = R.LOW_BMI["from_70"] if age is not None and age >= R.GLIM_OLDER_AGE else R.LOW_BMI["under_70"]
        if bmi_shown < threshold:
            risk.append("low_bmi")
            key = "N-1.low_bmi.older" if threshold == R.LOW_BMI["from_70"] else "N-1.low_bmi"
            reasons.append(R.NOTES[key].format(bmi=bmi_shown, thr=threshold))
    if inputs.weight_6_months_ago_kg is not None and float(inputs.weight_6_months_ago_kg) > 0:
        before = float(inputs.weight_6_months_ago_kg)
        pct = _half_up((before - actual) / before * 100.0, 1)
        if pct > R.WEIGHT_LOSS_PCT:
            risk.append("weight_loss")
            reasons.append(R.NOTES["N-1.weight_loss"].format(pct=pct))
    if shown["albumin"] is not None and shown["albumin"] < R.LOW_ALBUMIN_G_DL:
        risk.append("low_albumin")
        reasons.append(R.NOTES["N-1.low_albumin"].format(alb=shown["albumin"]))
    if inputs.frail_or_sarcopenic:
        risk.append("frailty")
        reasons.append(R.NOTES["N-1.frailty"])
    if risk:
        b.apply("N-1", R.NOTES["N-1"].format(reasons="; ".join(reasons)))

    # E: energy.
    activity = inputs.activity or inputs.default_activity
    eer: float | None = None
    eer_per_kg: float | None = None
    if age is not None and h is not None:
        eer = eer_kcal(inputs.sex, activity, age, h, ref)
        eer_per_kg = eer / ref
        kpk = min(max(eer_per_kg, R.KCAL_PER_KG_MIN), R.KCAL_PER_KG_MAX)
        raised = bool(risk) and kpk < R.KCAL_PER_KG_RISK_FLOOR  # E-3 follows: this is only the estimate
        note = R.NOTES["E-1.estimate" if raised else "E-1"].format(
            kcal=_calories(kpk * ref), ref=ref, activity_label=R.ACTIVITY_LABELS[activity], kpk=_half_up(kpk, 1)
        )
        if kpk != eer_per_kg:
            note += R.NOTES["E-1.clamped"].format(raw=_half_up(eer_per_kg, 1), edge=f"{kpk:g}")
        if inputs.sex == "unspecified":
            note += R.NOTES["E-1.unspecified"]
        e_id = "E-1"
    else:
        kpk = R.KCAL_PER_KG_DEFAULT
        e_id, note = "E-2", R.NOTES["E-2"].format(ref=ref, kcal=_calories(kpk * ref))
    if mode == "peritoneal" and inputs.pd_dialysate_kcal is None:
        note += R.NOTES["E-PD.missing"]
    b.apply(e_id, note)
    if risk and kpk < R.KCAL_PER_KG_RISK_FLOOR:
        kpk = R.KCAL_PER_KG_RISK_FLOOR
        b.apply("E-3", R.NOTES["E-3"].format(kcal=_calories(kpk * ref), ref=ref))
    total = kpk * ref
    food = total
    pdk = inputs.pd_dialysate_kcal
    if mode == "peritoneal" and pdk:
        floor = R.PD_FOOD_FLOOR_KCAL_PER_KG * ref
        food = max(total - float(pdk), floor)
        key = "E-4" if total - float(pdk) >= floor else "E-4.floor"
        note = R.NOTES[key].format(pdk=_int(float(pdk)), kcal=_calories(food), total=_calories(total), ref=ref)
        if has_diabetes:
            note += R.NOTES["E-4.insulin"]
        b.apply("E-4", note)
    calories = _calories(food)

    # P: protein (g/kg × reference weight, each bound rounded half-up).
    older = age is not None and age >= R.OLDER_AGE
    early = stage in R.EARLY_STAGES

    def grams(per_kg: tuple[float, float]) -> dict[str, int]:
        return {"min": _int(per_kg[0] * ref), "max": _int(per_kg[1] * ref)}

    if on_dialysis:
        per_kg = R.PROTEIN_G_PER_KG["dialysis"]
        g = grams(per_kg)
        b.apply("P-3", R.NOTES["P-3"].format(min=g["min"], max=g["max"], ref=ref, mode_label=_stage_label(mode, stage)))
    elif mode == "transplant":
        per_kg = R.PROTEIN_G_PER_KG["transplant"]
        g = grams(per_kg)
        note = R.NOTES["P-7"].format(min=g["min"], max=g["max"], ref=ref)
        if (older or risk) and not early:
            note += R.NOTES["P-7.graft"].format(stage=stage)
        b.apply("P-7", note)
    elif early:
        per_kg = R.PROTEIN_G_PER_KG["early"]
        g = grams(per_kg)
        b.apply("P-1", R.NOTES["P-1"].format(min=g["min"], max=g["max"], ref=ref))
    elif has_diabetes:
        per_kg = R.PROTEIN_G_PER_KG["late_diabetes"]
        g = grams(per_kg)
        b.apply("P-2", R.NOTES["P-2d"].format(max=g["max"], ref=ref), catalogue_id="P-2d")
    else:
        per_kg = R.PROTEIN_G_PER_KG["late_no_diabetes"]
        g = grams(per_kg)
        b.apply("P-2", R.NOTES["P-2n"].format(min=g["min"], max=g["max"], ref=ref), catalogue_id="P-2n")
    if on_dialysis:
        if risk:
            per_kg = R.PROTEIN_G_PER_KG["dialysis_risk"]
            g = grams(per_kg)
            b.apply("P-6", R.NOTES["P-6"].format(min=g["min"], max=g["max"]))
    elif (older or risk) and (early or mode == "ckd"):
        per_kg = R.PROTEIN_G_PER_KG["older_early" if early else "older_late"]
        g = grams(per_kg)
        why = R.NOTES["P-5a.both" if older and risk else ("P-5a.older" if older else "P-5a.risk")]
        b.apply("P-5", R.NOTES["P-5a"].format(lo=f"{per_kg[0]:.1f}", hi=f"{per_kg[1]:.1f}", min=g["min"], max=g["max"], why=why))
    protein = g

    # K: potassium (ladder L, relaxed R, caps; labs judged on the shown value).
    ladder = R.POTASSIUM_LADDER[ladder_key]
    stage_label = _stage_label(mode, stage)
    k = shown["potassium"]
    k_lab = lab["potassium"]
    alerts: list[dict[str, Any]] = []
    potassium: int | None
    if k is None or k_lab is None:
        potassium = ladder
        if labs_on:
            note = R.NOTES["K-0"].format(k_mg=ladder, stage_label=stage_label, days=windows["potassium"], potassium_note=R.POTASSIUM_NOTE)
        else:
            note = R.NOTES["K-0.labs_off"].format(k_mg=ladder, stage_label=stage_label, potassium_note=R.POTASSIUM_NOTE)
        b.apply("K-0", note)
    elif k < R.POTASSIUM_LOW:
        potassium = None
        b.apply("K-1", R.NOTES["K-1"].format(k=k, date=units.display_date(k_lab.taken_on), potassium_note=R.POTASSIUM_NOTE))
    elif k <= R.POTASSIUM_NORMAL_MAX:
        if inputs.hyperkalemia_history:
            potassium = ladder
            b.apply("K-2h", R.NOTES["K-2h"].format(k=k, date=units.display_date(k_lab.taken_on), k_mg=potassium, potassium_note=R.POTASSIUM_NOTE))
        else:
            potassium = R.POTASSIUM_RELAXED[ladder_key]
            if potassium == ladder:  # stages 1–3a: the relaxed step is the ladder, so nothing was relaxed
                b.apply("K-2", R.NOTES["K-2.top"].format(k=k, date=units.display_date(k_lab.taken_on), k_mg=potassium, stage_label=stage_label,
                                                         potassium_note=R.POTASSIUM_NOTE))
            else:
                b.apply("K-2", R.NOTES["K-2"].format(k=k, date=units.display_date(k_lab.taken_on), k_mg=potassium, potassium_note=R.POTASSIUM_NOTE))
    elif k <= R.POTASSIUM_HIGH_MAX:
        potassium = min(ladder, R.POTASSIUM_CAPS["K-3"])
        b.apply("K-3", R.NOTES["K-3"].format(k=k, date=units.display_date(k_lab.taken_on), k_mg=potassium, potassium_note=R.POTASSIUM_NOTE))
    elif k < R.POTASSIUM_VERY_HIGH:
        potassium = min(ladder, R.POTASSIUM_CAPS["K-4"])
        b.apply("K-4", R.NOTES["K-4"].format(k=k, date=units.display_date(k_lab.taken_on), k_mg=potassium, potassium_note=R.POTASSIUM_NOTE))
    else:
        potassium = min(ladder, R.POTASSIUM_CAPS["K-5"])
        level = potassium_alert_level(k)
        urgency = R.NOTES[f"K-5.{level}"]
        b.apply("K-5", R.NOTES["K-5"].format(k=k, date=units.display_date(k_lab.taken_on), urgency=urgency, k_mg=potassium, potassium_note=R.POTASSIUM_NOTE))
    # The safety alert does not depend on targets.lab_rules_enabled (note 05 §4.9).
    alert = potassium_alert(inputs.labs.get("potassium"))
    if alert is not None:
        alerts.append(alert)

    # PH: phosphorus.
    p = shown["phosphate"]
    p_lab = lab["phosphate"]
    graft_early = mode == "transplant" and stage in R.STAGES_TO_3B
    phosphorus: int | None
    if p is None or p_lab is None:
        if graft_early:
            phosphorus = None
            b.apply("PH-T", R.NOTES["PH-T"])
        else:
            phosphorus = R.PHOSPHORUS_DEFAULT[ladder_key]
            if labs_on:
                b.apply("PH-0", R.NOTES["PH-0"].format(p_mg=phosphorus, days=windows["phosphate"]))
            else:
                b.apply("PH-0", R.NOTES["PH-0.labs_off"].format(p_mg=phosphorus))
    elif p < R.PHOSPHATE_LOW:
        phosphorus = None
        b.apply("PH-1", R.NOTES["PH-1"].format(p=p, date=units.display_date(p_lab.taken_on)))
    elif p <= R.PHOSPHATE_HIGH:
        if graft_early:
            phosphorus = None
            b.apply("PH-2", R.NOTES["PH-2.none"].format(p=p, date=units.display_date(p_lab.taken_on)))
        else:
            phosphorus = R.PHOSPHORUS_NORMAL_MG
            b.apply("PH-2", R.NOTES["PH-2"].format(p=p, date=units.display_date(p_lab.taken_on), p_mg_or_none=f"{phosphorus} mg/day"))
    else:
        phosphorus = R.PHOSPHORUS_HIGH_MG
        b.apply("PH-3", R.NOTES["PH-3"].format(p=p, date=units.display_date(p_lab.taken_on)))

    # NA: sodium.
    b.apply("NA-1", R.NOTES["NA-1"])

    # CA: calcium.
    calcium: int | dict[str, int]
    if not on_dialysis and early:
        if age is None:
            calcium = R.CALCIUM_MG
            b.apply("CA-0", R.NOTES["CA-0"])
        else:
            rda, ul = calcium_dri(age, inputs.sex)
            calcium = {"min": rda, "max": ul}
            b.apply("CA-3", R.NOTES["CA-3"].format(rda=rda, ul=ul))
    elif not on_dialysis and stage != "5":
        calcium = R.CALCIUM_MG
        b.apply("CA-1", R.NOTES["CA-1"])
    else:
        calcium = R.CALCIUM_MG
        b.apply("CA-2", R.NOTES["CA-2"])

    # F: fluid.
    fluid: int | None
    if mode == "hemodialysis":
        if inputs.urine_output_ml is not None:
            u = float(inputs.urine_output_ml)
            fluid = _round_step(R.FLUID_HD_BASE_ML + u, R.FLUID_STEP_ML)
            b.apply("F-2", R.NOTES["F-2"].format(u=_int(u), fluid=fluid))
        else:
            fluid = R.FLUID_HD_DEFAULT_ML
            b.apply("F-1", R.NOTES["F-1"])
    elif mode == "peritoneal":
        if inputs.urine_output_ml is not None and inputs.pd_uf_ml is not None:
            u, uf = float(inputs.urine_output_ml), float(inputs.pd_uf_ml)
            fluid = _round_step(u + uf, R.FLUID_STEP_ML)
            b.apply("F-4", R.NOTES["F-4"].format(u=_int(u), uf=_int(uf), fluid=fluid))
        else:
            fluid = R.FLUID_PD_DEFAULT_ML
            b.apply("F-3", R.NOTES["F-3"])
    else:
        fluid = None
        if older and stage in R.STAGES_TO_3B:
            b.apply("F-0o", R.NOTES["F-0o"].format(floor=R.FLUID_FLOOR_TEXT[inputs.sex]))
        else:
            b.apply("F-0", R.NOTES["F-0"])

    # C: carbohydrate (v0.2 notes), FB: fibre — both from the food calories.
    carbs = _int(calories * R.CARB_FRACTION / 4.0)
    per_meal = max(R.CARBS_PER_MEAL_MIN_G, _round_step(carbs / 4.0, R.CARBS_PER_MEAL_STEP_G))
    if has_diabetes:
        b.apply("C-1", R.NOTES["C-1.diabetes"].format(carbs=carbs, per_meal=per_meal))
    else:
        b.apply("C-1", R.NOTES["C-1"].format(carbs=carbs))
    fiber = _int(R.FIBER_G_PER_1000_KCAL * calories / 1000.0)
    b.apply("FB-1", R.NOTES["FB-1"].format(fib=fiber))

    # L: lab notes (only when lab rules are on; the labs dict is empty otherwise).
    if shown["albumin"] is not None and shown["albumin"] < R.LOW_ALBUMIN_G_DL:
        b.apply("L-ALB", R.NOTES["L-ALB"])
    bic = shown["bicarbonate"]
    if bic is not None and bic < R.BICARBONATE_LOW:
        fv = ""
        if not on_dialysis and stage in R.STAGES_1_TO_4:
            k_caveat = R.NOTES["L-BIC22.k_caveat"] if k is not None and k > R.POTASSIUM_NORMAL_MAX else ""
            fv = R.NOTES["L-BIC22.fv"].format(k_caveat=k_caveat)
        b.apply("L-BIC22", R.NOTES["L-BIC22"].format(b=bic, fv=fv))
        if bic < R.BICARBONATE_VERY_LOW:
            b.apply("L-BIC18", R.NOTES["L-BIC18"].format(b=bic))
    uacr = lab["uacr"]
    if uacr is not None:
        entered_value = uacr.entered_value if uacr.entered_value is not None else uacr.value
        entered_unit = uacr.entered_unit or units.analyte_def("uacr").canonical_unit
        cat = albuminuria_category(entered_value, entered_unit)
        note = R.NOTES["L-UACR"].format(
            uacr=_half_up(entered_value, 1), unit=units.canonical_unit_name("uacr", entered_unit), cat=cat, cat_label=ALBUMINURIA_LABELS[cat]
        )
        if cat == "A3" and shown["albumin"] is not None and shown["albumin"] < R.LOW_ALBUMIN_G_DL:
            note += R.NOTES["L-UACR.a3_low_albumin"]
        b.apply(f"L-UACR-{cat}", note)
    if lab["a1c"] is not None:
        b.apply("L-A1C", R.NOTES["L-A1C"])
    b.notes.append(R.NOTES["END"])

    targets: dict[str, Any] = {
        "calories_kcal": calories,
        "protein_g": protein,
        "carbs_g": carbs,
        "carbs_per_meal_g": per_meal,
        "fiber_g": {"min": fiber},
        "sodium_mg": R.SODIUM_MG,
        "potassium_mg": potassium,
        "phosphorus_mg": phosphorus,
        "calcium_mg": calcium,
        "fluid_ml": fluid,
    }
    labs_used = {
        a: None if lab[a] is None else {"value": shown[a], "unit": units.analyte_def(a).canonical_unit, "taken_on": lab[a].taken_on}
        for a in TARGET_LABS
    }
    derived = {
        "mode": mode,
        "age": age,
        "sex": inputs.sex,
        "activity": activity,
        "bmi": bmi_shown,
        "reference_weight_kg": ref,
        "weight_basis": rw.basis,
        "eer_kcal": None if eer is None else _int(eer),
        "eer_kcal_per_kg": None if eer_per_kg is None else _half_up(eer_per_kg, 1),
        "kcal_per_kg": _half_up(kpk, 1),
        "nutrition_risk": risk,
        "labs_used": labs_used,
        "lab_rules_enabled": labs_on,
    }
    return Suggestion(targets, b.notes, b.rules, derived, missing_inputs(inputs, mode), alerts)


def calcium_dri(age: int, sex: str) -> tuple[int, int]:
    """``(RDA, UL)`` mg/day from IOM 2011 for an adult's age and sex (``unspecified``: the higher RDA)."""
    for row in R.CALCIUM_DRI:
        if row["min_age"] <= age <= row["max_age"]:
            rda = max(row["female"], row["male"]) if sex == "unspecified" else row[sex]
            return rda, row["ul"]
    raise ValueError(f"no calcium reference value for age {age}")


def potassium_alert_level(k_shown: float) -> str:
    """``"emergency"`` from 6.5 mmol/L, ``"urgent"`` from 6.0 (KDIGO 2024 Table 28), on the shown value."""
    return "emergency" if k_shown >= R.POTASSIUM_EMERGENCY else "urgent"


def potassium_alert(potassium: Lab | None) -> dict[str, Any] | None:
    """The safety alert for a potassium of 6.0 mmol/L or more (shown value), else ``None``."""
    if potassium is None:
        return None
    k = units.display_value("potassium", potassium.value)
    if k < R.POTASSIUM_VERY_HIGH:
        return None
    level = potassium_alert_level(k)
    return {
        "level": level,
        "code": R.ALERT_CODE_POTASSIUM,
        "analyte": "potassium",
        "value": k,
        "taken_on": potassium.taken_on,
        "message": R.NOTES["K-5.alert"].format(k=k, date=units.display_date(potassium.taken_on), urgency=R.NOTES[f"K-5.{level}"]),
    }


def missing_inputs(inputs: Inputs, mode: str) -> list[str]:
    """Profile fields that would make the suggestion more personal (drives "Add your …" prompts)."""
    missing = {
        "height_cm": inputs.height_cm is None,
        "birth_month": inputs.birth_month is None,
        "sex": inputs.sex == "unspecified",
        "activity": inputs.activity is None,
        "urine_output_ml": mode in ("hemodialysis", "peritoneal") and inputs.urine_output_ml is None,
        "pd_uf_ml": mode == "peritoneal" and inputs.pd_uf_ml is None,
        "pd_dialysate_kcal": mode == "peritoneal" and inputs.pd_dialysate_kcal is None,
    }
    return [name for name in R.MISSING_INPUT_ORDER if missing[name]]


# --------------------------------------------------------------------------- #
# From stored records (app.profile and the parity vectors use this one entry point)
# --------------------------------------------------------------------------- #

PROFILE_FIELDS: tuple[str, ...] = (
    "weight_kg", "ckd_stage", "dialysis", "diabetes", "height_cm", "birth_month", "sex", "activity", "transplant_date",
    "frail_or_sarcopenic", "weight_6_months_ago_kg", "pregnant_or_breastfeeding", "hyperkalemia_history",
    "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal",
)
_BOOL_FIELDS = ("frail_or_sarcopenic", "pregnant_or_breastfeeding", "hyperkalemia_history")


def inputs_from_records(
    profile: Mapping[str, Any],
    labs: Iterable[Mapping[str, Any]],
    today: date,
    *,
    lab_rules_enabled: bool = True,
    default_activity: str = "inactive",
    fresh_days: Mapping[str, int] | None = None,
) -> Inputs:
    """:class:`Inputs` from a profile (the API's Profile shape) and stored lab rows (any order)."""
    values: dict[str, Any] = {}
    for name in PROFILE_FIELDS:
        if name in profile and profile[name] is not None:
            values[name] = bool(profile[name]) if name in _BOOL_FIELDS else profile[name]
    windows = {**DEFAULT_FRESH_DAYS, **dict(fresh_days or {})}
    return Inputs(
        **values,
        labs=fresh_labs(labs, today, windows),
        lab_rules_enabled=bool(lab_rules_enabled),
        default_activity=default_activity,
        fresh_days=windows,
    )


def suggest_from_records(
    profile: Mapping[str, Any],
    labs: Iterable[Mapping[str, Any]],
    today: date,
    *,
    lab_rules_enabled: bool = True,
    default_activity: str = "inactive",
    fresh_days: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """:func:`suggest` on stored records, as a plain dict (raises :class:`OutOfScope` / ``ValueError``)."""
    inputs = inputs_from_records(
        profile, labs, today, lab_rules_enabled=lab_rules_enabled, default_activity=default_activity, fresh_days=fresh_days
    )
    return suggest(inputs, today).to_dict()
