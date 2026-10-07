"""Kidney function from lab results: eGFR, G and A categories, and the stage *suggestion*.

Pure functions, no I/O (note 05 §4.3 "eGFR", §4.5 G-1, §5.2). ``today`` is always a parameter.

Equations (race-free; age in completed years, adults only; creatinine in mg/dL, IDMS-traceable;
cystatin C in mg/L, standardised):

* CKD-EPI 2021 creatinine (Inker, NEJM 2021)::

      142 · min(Scr/κ,1)^α · max(Scr/κ,1)^−1.200 · 0.9938^age · (1.012 if female)
      κ: female 0.7, male 0.9      α: female −0.241, male −0.302

* CKD-EPI 2021 creatinine–cystatin C::

      135 · min(Scr/κ,1)^α · max(Scr/κ,1)^−0.544 · min(Scys/0.8,1)^−0.323
          · max(Scys/0.8,1)^−0.778 · 0.9961^age · (0.963 if female)
      κ as above      α: female −0.219, male −0.144

* CKD-EPI 2012 cystatin C::

      133 · min(Scys/0.8,1)^−0.499 · max(Scys/0.8,1)^−1.328 · 0.996^age · (0.932 if female)

Which result is used (§4.3): among the creatinine, cystatin C and lab-reported eGFR results of the
last 365 days, the **newest date** decides; on that date a lab-reported eGFR wins (the lab knows its
region's equation, KDIGO 2024 PP 1.2.4.1), then creatinine with cystatin C taken that day, then
creatinine, then cystatin C. With sex "unspecified" both formulas are computed and a category is
suggested only when both give the same one. Nothing is computed on dialysis, in pregnancy or for
anyone under 18, and the saved ``ckd_stage`` is **never** changed (KDIGO 2024 PP 1.1.3.2: one result
does not make a stage).

Albuminuria (KDIGO 2024 Table 3) is categorised **in the unit it was entered in**, on the displayed
value (one decimal): < 3 / 3–30 / > 30 mg/mmol, < 30 / 30–300 / > 300 mg/g. Converting first would
put 3.0 mg/mmol (= 26.5 mg/g) in A1 instead of A2 (§5.2 U5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Literal, Mapping

from . import units
from .nutrients import _half_up

Sex = Literal["female", "male"]
SEXES: tuple[str, ...] = ("female", "male", "unspecified")

# Analytes this module reads and how long a result counts (days; units.ANALYTES holds the windows).
KIDNEY_ANALYTES: tuple[str, ...] = ("egfr", "creatinine", "cystatin_c")

METHOD_LABELS: dict[str, str] = {
    "lab": "reported by your lab",
    "ckd_epi_2021_cr_cys": "CKD-EPI 2021, creatinine and cystatin C",
    "ckd_epi_2021_cr": "CKD-EPI 2021, creatinine",
    "ckd_epi_2012_cys": "CKD-EPI 2012, cystatin C",
}
# Preference on the newest date (note 05 §4.3 "Order of preference").
METHOD_ORDER: tuple[str, ...] = ("lab", "ckd_epi_2021_cr_cys", "ckd_epi_2021_cr", "ckd_epi_2012_cys")

# G categories (KDIGO 2024), judged on the eGFR rounded to an integer: lower bound -> category.
G_CATEGORIES: tuple[tuple[int, str], ...] = ((90, "G1"), (60, "G2"), (45, "G3a"), (30, "G3b"), (15, "G4"), (0, "G5"))
STAGE_FOR_CATEGORY: dict[str, str] = {"G1": "1", "G2": "2", "G3a": "3a", "G3b": "3b", "G4": "4", "G5": "5"}

# A categories (KDIGO 2024 Table 3): per unit, (A1 below, A3 above); A2 in between, both edges included.
ALBUMINURIA_LIMITS: dict[str, tuple[float, float]] = {"mg/g": (30.0, 300.0), "mg/mmol": (3.0, 30.0)}
ALBUMINURIA_LABELS: dict[str, str] = {
    "A1": "normal to mildly increased",
    "A2": "moderately increased",
    "A3": "severely increased",
}

# Messages of GET /api/labs/kidney-function. G-1 is note 05 §4.5 word for word; the others say why
# no stage is suggested (project wording, same tone).
G1_TEXT = (
    "Your eGFR on {date} is {e} mL/min/1.73 m² ({method}), which is stage {G}{T}{range_note}. Your profile says "
    "stage {stage}. One result does not change a stage — kidney disease stages need results over 3 months "
    "(KDIGO 2024). Talk to your nephrologist before changing it."
)
RANGE_NOTE = " (female formula {ef}, male formula {em})"
SEX_SPLIT_TEXT = (
    "Your eGFR on {date} is {lo}–{hi} mL/min/1.73 m² ({method}): the female formula gives {ef} (stage {Gf}{T}) and "
    "the male formula {em} (stage {Gm}{T}). Because they point to different stages, the app does not suggest one. "
    "Choose the sex your lab uses for your eGFR in your profile, or ask your nephrologist. Your profile says stage {stage}."
)
NO_RESULT_TEXT = (
    "No creatinine, cystatin C or eGFR result from the last {days} days is saved. Add one from your latest blood test "
    "to see which stage it suggests."
)
DIALYSIS_TEXT = (
    "Kidney function is not estimated on dialysis: eGFR equations do not apply once dialysis has started. "
    "Your profile stage stays as it is."
)
PREGNANCY_TEXT = (
    "Kidney function is not estimated during pregnancy or breastfeeding: the eGFR equations were not developed for "
    "pregnancy. Ask your kidney team."
)
UNDER_18_TEXT = (
    "Kidney function is not estimated for people under 18: children need different eGFR equations (KDIGO 2024). "
    "Ask your child's kidney team."
)
NEEDS_AGE_TEXT = (
    "Add your birth month to estimate kidney function from your {analyte} result: the equations use age. "
    "Or add the eGFR your lab reported."
)


class KidneyFunctionError(ValueError):
    """An input the equations cannot use (non-positive level, age under 18, unknown sex)."""


def _check(age: int, sex: str, **levels: float) -> None:
    if sex not in ("female", "male"):
        raise KidneyFunctionError("sex must be 'female' or 'male' (compute both for 'unspecified')")
    if not isinstance(age, int) or isinstance(age, bool) or age < 18 or age > 130:
        raise KidneyFunctionError("the equations are for adults: age must be a whole number of years from 18")
    for name, value in levels.items():
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise KidneyFunctionError(f"{name} must be a positive number")


def egfr_cr(creatinine_mg_dl: float, age: int, sex: str) -> float:
    """CKD-EPI 2021 creatinine equation (mL/min/1.73 m², unrounded)."""
    _check(age, sex, creatinine=creatinine_mg_dl)
    female = sex == "female"
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    ratio = float(creatinine_mg_dl) / kappa
    value = 142.0 * min(ratio, 1.0) ** alpha * max(ratio, 1.0) ** -1.200 * 0.9938**age
    return value * 1.012 if female else value


def egfr_cr_cys(creatinine_mg_dl: float, cystatin_mg_l: float, age: int, sex: str) -> float:
    """CKD-EPI 2021 creatinine–cystatin C equation (mL/min/1.73 m², unrounded)."""
    _check(age, sex, creatinine=creatinine_mg_dl, cystatin_c=cystatin_mg_l)
    female = sex == "female"
    kappa = 0.7 if female else 0.9
    alpha = -0.219 if female else -0.144
    ratio = float(creatinine_mg_dl) / kappa
    cys = float(cystatin_mg_l) / 0.8
    value = (
        135.0
        * min(ratio, 1.0) ** alpha
        * max(ratio, 1.0) ** -0.544
        * min(cys, 1.0) ** -0.323
        * max(cys, 1.0) ** -0.778
        * 0.9961**age
    )
    return value * 0.963 if female else value


def egfr_cys(cystatin_mg_l: float, age: int, sex: str) -> float:
    """CKD-EPI 2012 cystatin C equation (mL/min/1.73 m², unrounded)."""
    _check(age, sex, cystatin_c=cystatin_mg_l)
    cys = float(cystatin_mg_l) / 0.8
    value = 133.0 * min(cys, 1.0) ** -0.499 * max(cys, 1.0) ** -1.328 * 0.996**age
    return value * 0.932 if sex == "female" else value


def round_egfr(value: float) -> int:
    """eGFR as reported: an integer, rounded half-up."""
    return int(_half_up(float(value), 0))


def gfr_category(egfr: float) -> str:
    """``"G1"`` … ``"G5"`` for an eGFR, judged on the integer it is shown as (59.5 -> 60 -> G2)."""
    shown = round_egfr(egfr)
    for lower, category in G_CATEGORIES:
        if shown >= lower:
            return category
    return "G5"


def albuminuria_category(value: float, unit: str) -> str:
    """``"A1"``/``"A2"``/``"A3"`` for a urine albumin-to-creatinine ratio **in the unit it was entered in**.

    Judged on the displayed value (one decimal, half-up): in mg/g 29.96 shows as 30.0 (A2) and
    300.05 as 300.1 (A3). Raises :class:`app.units.UnitError` for a unit other than mg/g or mg/mmol.
    """
    name = units.canonical_unit_name("uacr", unit)
    low, high = ALBUMINURIA_LIMITS[name]
    shown = _half_up(float(value), 1)
    if not math.isfinite(shown) or shown < 0:
        raise units.UnitError("uacr must be a non-negative number")
    if shown < low:
        return "A1"
    if shown > high:
        return "A3"
    return "A2"


# --------------------------------------------------------------------------- #
# Assessment (GET /api/labs/kidney-function)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LabRow:
    """One stored result as the assessment needs it (canonical ``value``)."""

    id: int
    analyte: str
    value: float
    taken_on: str
    entered_value: float
    entered_unit: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "LabRow":
        return cls(
            id=int(row.get("id") or 0),
            analyte=str(row["analyte"]),
            value=float(row["value"]),
            taken_on=str(row["taken_on"]),
            entered_value=float(row["entered_value"] if row.get("entered_value") is not None else row["value"]),
            entered_unit=str(row.get("entered_unit") or units.analyte_def(str(row["analyte"])).canonical_unit),
        )


def is_fresh(taken_on: str, today: date, days: int | None) -> bool:
    """A result counts when it is at most ``days`` days old (a date after ``today`` counts as fresh)."""
    if days is None:
        return False
    return (today - date.fromisoformat(taken_on)).days <= int(days)


def newest(rows: Iterable[LabRow]) -> LabRow | None:
    """The newest result: latest ``taken_on``, then the latest entered (highest id)."""
    best: LabRow | None = None
    for row in rows:
        if best is None or (row.taken_on, row.id) > (best.taken_on, best.id):
            best = row
    return best


def age_on(birth_month: str | None, today: date, *, last_day: bool = False) -> int | None:
    """Completed years from the first (or, with ``last_day``, the last) day of ``birth_month`` to ``today``."""
    if not birth_month:
        return None
    year, month = (int(part) for part in birth_month.split("-"))
    if last_day:
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        born = date.fromordinal(next_month.toordinal() - 1)
    else:
        born = date(year, month, 1)
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _compute(method: str, cr: LabRow | None, cys: LabRow | None, age: int, sex: str) -> float:
    if method == "ckd_epi_2021_cr_cys":
        assert cr is not None and cys is not None
        return egfr_cr_cys(cr.value, cys.value, age, sex)
    if method == "ckd_epi_2021_cr":
        assert cr is not None
        return egfr_cr(cr.value, age, sex)
    assert cys is not None
    return egfr_cys(cys.value, age, sex)


def assess(
    *,
    labs: Iterable[Mapping[str, Any] | LabRow],
    today: date,
    ckd_stage: str,
    dialysis: str = "none",
    transplant: bool = False,
    birth_month: str | None = None,
    sex: str = "unspecified",
    pregnant_or_breastfeeding: bool = False,
) -> dict[str, Any]:
    """The kidney-function card: ``{egfr, albuminuria, profile_stage, mode, message}``.

    ``egfr`` is ``None`` or ``{value, method, method_label, category, suggested_stage,
    matches_profile, female, male, taken_on}``: ``value`` is the eGFR shown (``None`` when sex is
    unspecified and a formula was used: then ``female`` and ``male`` hold both values),
    ``category`` carries a ``T`` for a transplant (``"G3aT"``) and is ``None`` when the two
    formulas disagree. ``albuminuria`` is ``None`` or ``{value_mg_g, category, label,
    entered_value, entered_unit, taken_on}``. Nothing here changes the saved stage.
    """
    if sex not in SEXES:
        raise KidneyFunctionError(f"sex must be one of {', '.join(SEXES)}")
    rows = [r if isinstance(r, LabRow) else LabRow.from_mapping(r) for r in labs]
    mode = dialysis if dialysis in ("hemodialysis", "peritoneal") else ("transplant" if transplant else "ckd")
    suffix = "T" if mode == "transplant" else ""
    out: dict[str, Any] = {"egfr": None, "albuminuria": None, "profile_stage": ckd_stage, "mode": mode, "message": ""}

    uacr = newest(r for r in rows if r.analyte == "uacr" and is_fresh(r.taken_on, today, units.fresh_days("uacr")))
    if uacr is not None:
        category = albuminuria_category(uacr.entered_value, uacr.entered_unit)
        out["albuminuria"] = {
            "value_mg_g": units.display_value("uacr", uacr.value),
            "category": category,
            "label": ALBUMINURIA_LABELS[category],
            "entered_value": uacr.entered_value,
            "entered_unit": uacr.entered_unit,
            "taken_on": uacr.taken_on,
        }

    window = units.fresh_days("creatinine")
    if mode in ("hemodialysis", "peritoneal"):
        out["message"] = DIALYSIS_TEXT
        return out
    if pregnant_or_breastfeeding:
        out["message"] = PREGNANCY_TEXT
        return out
    if birth_month and (age_on(birth_month, today, last_day=True) or 0) < 18:
        out["message"] = UNDER_18_TEXT
        return out
    age = age_on(birth_month, today)

    fresh = [r for r in rows if r.analyte in KIDNEY_ANALYTES and is_fresh(r.taken_on, today, units.fresh_days(r.analyte))]
    if not fresh:
        out["message"] = NO_RESULT_TEXT.format(days=window)
        return out

    # Newest date first, then the preferred method available on that date. Formulas need an age.
    by_date: dict[str, dict[str, LabRow]] = {}
    for row in fresh:
        slot = by_date.setdefault(row.taken_on, {})
        current = slot.get(row.analyte)
        if current is None or row.id > current.id:
            slot[row.analyte] = row
    chosen: tuple[str, str, dict[str, LabRow]] | None = None
    needs_age: str | None = None
    for day in sorted(by_date, reverse=True):
        slot = by_date[day]
        available = []
        if "egfr" in slot:
            available.append("lab")
        if age is not None:
            if "creatinine" in slot and "cystatin_c" in slot:
                available.append("ckd_epi_2021_cr_cys")
            if "creatinine" in slot:
                available.append("ckd_epi_2021_cr")
            if "cystatin_c" in slot:
                available.append("ckd_epi_2012_cys")
        elif needs_age is None and ("creatinine" in slot or "cystatin_c" in slot):
            needs_age = "creatinine" if "creatinine" in slot else "cystatin C"
        if available:
            method = min(available, key=METHOD_ORDER.index)
            chosen = (day, method, slot)
            break
    if chosen is None:
        out["message"] = NEEDS_AGE_TEXT.format(analyte=needs_age or "creatinine")
        return out

    day, method, slot = chosen
    label = METHOD_LABELS[method]
    result: dict[str, Any] = {
        "value": None,
        "method": method,
        "method_label": label,
        "category": None,
        "suggested_stage": None,
        "matches_profile": None,
        "female": None,
        "male": None,
        "taken_on": day,
    }
    out["egfr"] = result
    if method == "lab":
        value = round_egfr(slot["egfr"].value)
        result["value"] = value
        category = gfr_category(value)
    elif sex in ("female", "male"):
        value = round_egfr(_compute(method, slot.get("creatinine"), slot.get("cystatin_c"), age or 0, sex))
        result["value"] = value
        category = gfr_category(value)
    else:
        ef = round_egfr(_compute(method, slot.get("creatinine"), slot.get("cystatin_c"), age or 0, "female"))
        em = round_egfr(_compute(method, slot.get("creatinine"), slot.get("cystatin_c"), age or 0, "male"))
        result["female"], result["male"] = ef, em
        gf, gm = gfr_category(ef), gfr_category(em)
        if gf != gm:
            out["message"] = SEX_SPLIT_TEXT.format(
                date=units.display_date(day), lo=min(ef, em), hi=max(ef, em), method=label, ef=ef, em=em, Gf=gf, Gm=gm, T=suffix, stage=ckd_stage
            )
            return out
        category = gf

    stage = STAGE_FOR_CATEGORY[category]
    result["category"] = category + suffix
    result["suggested_stage"] = stage
    result["matches_profile"] = stage == ckd_stage
    if result["value"] is not None:
        shown, range_note = str(result["value"]), ""
    else:
        lo, hi = sorted((result["female"], result["male"]))
        shown = str(lo) if lo == hi else f"{lo}–{hi}"
        range_note = RANGE_NOTE.format(ef=result["female"], em=result["male"])
    out["message"] = G1_TEXT.format(date=units.display_date(day), e=shown, method=label, G=category, T=suffix, range_note=range_note, stage=ckd_stage)
    return out
