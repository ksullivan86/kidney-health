"""Nutrient registry and the pure rules of the app.

Everything in this module is a pure function: no I/O, no database, no FastAPI.
It is the single source of truth for nutrient keys, per-serving warning
thresholds, daily status levels and the suggested-target starting points
described in ARCHITECTURE.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Nutrient:
    key: str
    label: str
    unit: str
    role: str  # goal | range | info | track | limit


NUTRIENTS: tuple[Nutrient, ...] = (
    Nutrient("calories_kcal", "Calories", "kcal", "goal"),
    Nutrient("protein_g", "Protein", "g", "range"),
    Nutrient("fat_g", "Fat", "g", "info"),
    Nutrient("sat_fat_g", "Saturated fat", "g", "info"),
    Nutrient("carbs_g", "Carbohydrate", "g", "track"),
    Nutrient("fiber_g", "Fiber", "g", "info"),
    Nutrient("sugar_g", "Sugars", "g", "info"),
    Nutrient("sodium_mg", "Sodium", "mg", "limit"),
    Nutrient("potassium_mg", "Potassium", "mg", "limit"),
    Nutrient("phosphorus_mg", "Phosphorus", "mg", "limit"),
    Nutrient("calcium_mg", "Calcium", "mg", "info"),
    Nutrient("fluid_ml", "Fluid", "mL", "limit"),
)
NUTRIENT_KEYS: tuple[str, ...] = tuple(n.key for n in NUTRIENTS)
NUTRIENT_BY_KEY: dict[str, Nutrient] = {n.key: n for n in NUTRIENTS}

# Profile targets may also carry a per-meal carbohydrate goal (type 1 carb counting).
TARGET_KEYS: tuple[str, ...] = NUTRIENT_KEYS + ("carbs_per_meal_g",)

MEALS: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")
CKD_STAGES: tuple[str, ...] = ("1", "2", "3a", "3b", "4", "5")
DIALYSIS_MODES: tuple[str, ...] = ("none", "hemodialysis", "peritoneal")
DIABETES_TYPES: tuple[str, ...] = ("none", "type1", "type2")
FOOD_SOURCES: tuple[str, ...] = ("builtin", "usda", "custom")

FLAGS: tuple[str, ...] = (
    "phosphate_additive",
    "high_gi",
    "counts_as_fluid",
    "avoid_ckd",
    "hypo_treatment",
    "low_potassium_fruit",
    "processed",
)

_INTEGER_UNITS = {"mg", "mL"}


def _half_up(value: float, places: int) -> float:
    """Decimal half-up rounding on the number's shortest repr, so 26.95 -> 27.0 (not 26.9)."""
    try:
        quantum = Decimal(1).scaleb(-places)
        return float(Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):  # inf / nan
        return float(value)


def round_value(key: str, value: float | None) -> float | int | None:
    """Round for presentation: mg and mL to integers, everything else to 1 decimal."""
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    nutrient = NUTRIENT_BY_KEY.get(key)
    if nutrient is not None and nutrient.unit in _INTEGER_UNITS:
        return int(_half_up(value, 0))
    return _half_up(value, 1)


def round_nutrients(values: Mapping[str, float | None]) -> dict[str, float | int | None]:
    """All 12 keys, rounded; missing keys become ``None``."""
    return {key: round_value(key, values.get(key)) for key in NUTRIENT_KEYS}


def empty_totals() -> dict[str, float]:
    return {key: 0.0 for key in NUTRIENT_KEYS}


def add_totals(acc: dict[str, float], values: Mapping[str, float | None]) -> dict[str, float]:
    """Accumulate ``values`` into ``acc`` in place (``None`` counts as 0)."""
    for key in NUTRIENT_KEYS:
        v = values.get(key)
        if v is not None:
            acc[key] = acc.get(key, 0.0) + float(v)
    return acc


def scale_nutrients(values: Mapping[str, float | None], factor: float) -> dict[str, float | None]:
    """Multiply every known nutrient by ``factor``; unknown (``None``) stays ``None``."""
    return {
        key: (None if values.get(key) is None else float(values[key]) * factor)
        for key in NUTRIENT_KEYS
    }


def _fmt(key: str, value: float | int | None) -> str:
    """Human formatting for messages: ``2125``, ``40``, ``40.5``."""
    if value is None:
        return "?"
    rounded = round_value(key, value)
    if isinstance(rounded, int):
        return str(rounded)
    return f"{rounded:g}"


# --------------------------------------------------------------------------- #
# Per-serving thresholds
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Threshold:
    """``medium`` when ``medium_min <= value <= high_min``; ``high`` when ``value > high_min``.

    Evaluated on the *displayed* (rounded) value so the level always matches the
    number the person sees: 100.6 mg potassium shows as 101 mg and is "medium".
    """

    medium_min: float
    high_min: float


THRESHOLDS: dict[str, Threshold] = {
    "potassium_mg": Threshold(101, 200),
    "phosphorus_mg": Threshold(101, 150),
    "sodium_mg": Threshold(141, 400),
    "carbs_g": Threshold(15, 30),
    "protein_g": Threshold(15, 25),
}

# Order in which warnings are reported (renal priorities first).
WARNING_ORDER: tuple[str, ...] = ("potassium_mg", "phosphorus_mg", "sodium_mg", "protein_g", "carbs_g")

# ``high_gi`` upgrades carbohydrate to ``high`` only from one carb choice (15 g) upwards; below
# that the flag is reported as a ``medium`` note (per-portion glycaemic load, not just index).
HIGH_GI_MIN_CARBS_G = 15.0

_LEVEL_WORD = {"high": "High", "medium": "Moderate"}


def threshold_level(key: str, value: float | None) -> str | None:
    """``"high"``, ``"medium"`` or ``None`` for one nutrient amount."""
    th = THRESHOLDS.get(key)
    if th is None or value is None:
        return None
    shown = round_value(key, value)
    if shown is None:
        return None
    if shown > th.high_min:
        return "high"
    if shown >= th.medium_min:
        return "medium"
    return None


def _carb_choices(grams: float) -> str:
    choices = max(1, int(round(grams / 15.0)))
    return f"{choices} carb choice" + ("" if choices == 1 else "s")


def _warning_message(key: str, level: str, value: float | None, flag: str | None, scope: str) -> str:
    label = NUTRIENT_BY_KEY[key].label.lower()
    unit = NUTRIENT_BY_KEY[key].unit
    amount = f"{_fmt(key, value)} {unit}" if value is not None else None

    if flag == "phosphate_additive":
        base = "Contains phosphate additives (almost fully absorbed)"
        return f"{base}: {amount} phosphorus {scope}" if amount else base
    if flag == "high_gi":
        return f"High glycaemic index: {amount} fast-acting carbohydrate {scope}"
    if key == "carbs_g":
        if level == "high":
            return f"High carbohydrate: {amount} {scope} ({_carb_choices(value or 0)})"
        return f"{_carb_choices(value or 0)}: {amount} carbohydrate {scope}"
    if key == "protein_g" and level == "high":
        return f"Large protein portion: {amount} {scope}"
    return f"{_LEVEL_WORD[level]} {label}: {amount} {scope}"


def food_warnings(
    nutrients: Mapping[str, float | None],
    flags: Iterable[str] | None = None,
    kidney_notes: str | None = None,
    *,
    scope: str = "per serving",
) -> list[dict[str, Any]]:
    """Warnings for one food (per serving) or one log entry (``scope="in this entry"``).

    Each warning is ``{"nutrient", "level", "value", "message"}`` plus ``"flag"``
    when a food flag caused or upgraded it. ``avoid_ckd`` yields a ``high`` warning
    carrying the food's ``kidney_notes``; its ``nutrient`` is ``"avoid_ckd"``.

    ``hypo_treatment`` foods (glucose tablets, apple juice ...) get **no carbohydrate
    warning**: fast carbohydrate is the point of treating a low, and the diet guide says
    hypo treatments are never warned against. Their potassium, phosphorus and sodium
    warnings stay, so the person can still pick the lowest-potassium option.
    """
    flag_set = set(flags or ())
    hypo = "hypo_treatment" in flag_set
    warnings: list[dict[str, Any]] = []

    if "avoid_ckd" in flag_set:
        warnings.append(
            {
                "nutrient": "avoid_ckd",
                "level": "high",
                "value": None,
                "flag": "avoid_ckd",
                "message": (kidney_notes or "").strip() or "Not recommended for people with kidney disease",
            }
        )

    for key in WARNING_ORDER:
        if key == "carbs_g" and hypo:
            continue
        raw = nutrients.get(key)
        value = None if raw is None else float(raw)
        level = threshold_level(key, value)
        flag = None
        if key == "phosphorus_mg" and "phosphate_additive" in flag_set:
            level, flag = "high", "phosphate_additive"
        elif key == "carbs_g" and "high_gi" in flag_set and (value or 0) > 0:
            # Glycaemic index only matters once there is a carb choice to spike on: a condiment's
            # 4 g of fast sugar is a note, not the same red as a sugary drink (glycaemic load).
            shown = round_value(key, value) or 0
            level, flag = ("high" if shown >= HIGH_GI_MIN_CARBS_G else "medium"), "high_gi"
        if level is None:
            continue
        warnings.append(
            {
                "nutrient": key,
                "level": level,
                "value": round_value(key, value),
                "flag": flag,
                "message": _warning_message(key, level, value, flag, scope),
            }
        )

    # High warnings first; stable sort keeps avoid_ckd at the very top.
    warnings.sort(key=lambda w: 0 if w["level"] == "high" else 1)
    return warnings


def kidney_rating(warnings: Iterable[Mapping[str, Any]]) -> str:
    """``"red"`` if any high warning, ``"yellow"`` if any medium, else ``"green"``."""
    rating = "green"
    for w in warnings:
        if w.get("level") == "high":
            return "red"
        if w.get("level") == "medium":
            rating = "yellow"
    return rating


# --------------------------------------------------------------------------- #
# Daily status against targets
# --------------------------------------------------------------------------- #


def target_bounds(target: Any) -> tuple[float | None, float | None]:
    """Normalise a target (number | {min,max} | None) to ``(min, max)``."""
    if target is None:
        return (None, None)
    if isinstance(target, Mapping):
        lo = target.get("min")
        hi = target.get("max")
        return (None if lo is None else float(lo), None if hi is None else float(hi))
    return (None, float(target))


def status_level(fraction: float | None, warn_fraction: float) -> str:
    if fraction is None or math.isnan(fraction):
        return "ok"
    if fraction > 1.0:  # includes +inf
        return "over"
    if fraction >= warn_fraction:
        return "caution"
    return "ok"


def _finite_fraction(item: Mapping[str, Any]) -> float | None:
    """The status item's fraction as a finite float, or ``None`` when absent or not finite."""
    fraction = item.get("fraction")
    if fraction is None:
        return None
    try:
        value = float(fraction)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def daily_status(
    totals: Mapping[str, float | None],
    targets: Mapping[str, Any],
    warn_fraction: float = 0.8,
) -> dict[str, dict[str, Any]]:
    """Per-nutrient ``{"value","target","fraction","level"}`` (+ ``"min"`` for ranges).

    Only nutrient keys that have a non-null target are included; the per-meal
    carbohydrate goal is not a nutrient and is handled by :func:`meal_carb_alerts`.
    """
    status: dict[str, dict[str, Any]] = {}
    for key in NUTRIENT_KEYS:
        if key not in targets:
            continue
        lo, hi = target_bounds(targets[key])
        # A non-finite bound (from an old database row) cannot be judged against: treat as unset.
        if lo is not None and not math.isfinite(lo):
            lo = None
        if hi is not None and not math.isfinite(hi):
            hi = None
        if lo is None and hi is None:
            continue
        value = float(totals.get(key) or 0.0)
        fraction = (value / hi) if hi else None
        # The level is judged on the raw fraction (inf is "over"); the reported fraction must be
        # finite because JSON cannot carry it and the alert builders turn it into a percentage.
        level = status_level(fraction, warn_fraction)
        if fraction is not None and not math.isfinite(fraction):
            fraction = None
        item: dict[str, Any] = {
            "value": round_value(key, value),
            "target": round_value(key, hi) if hi else None,
            "fraction": None if fraction is None else round(fraction, 2),
            "level": level,
        }
        if lo is not None:
            item["min"] = round_value(key, lo)
        status[key] = item
    return status


_ROLE_WORD = {"limit": "limit", "range": "maximum", "info": "maximum", "goal": "goal", "track": "goal"}


def build_alerts(status: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Alerts for every nutrient whose level is ``caution`` or ``over`` (over first)."""
    alerts: list[dict[str, Any]] = []
    for key, item in status.items():
        level = item.get("level")
        fraction = _finite_fraction(item)
        if level not in ("caution", "over") or fraction is None:
            continue
        nutrient = NUTRIENT_BY_KEY[key]
        pct = int(round(fraction * 100))
        value = _fmt(key, item.get("value"))
        target = _fmt(key, item.get("target"))
        word = _ROLE_WORD.get(nutrient.role, "goal")
        if level == "caution":
            message = f"{nutrient.label} is at {pct} % of today's {word} ({value} / {target} {nutrient.unit})"
        else:
            message = f"{nutrient.label} is over today's {word}: {value} / {target} {nutrient.unit} ({pct} %)"
        alerts.append({"level": level, "nutrient": key, "message": message})
    alerts.sort(key=lambda a: 0 if a["level"] == "over" else 1)
    return alerts


def meal_carb_alerts(
    meals: Mapping[str, Mapping[str, float | None]],
    carbs_per_meal_target: Any,
) -> list[dict[str, Any]]:
    """``over`` alerts for meals whose carbohydrate exceeds the per-meal goal."""
    _, hi = target_bounds(carbs_per_meal_target)
    if not hi:
        return []
    alerts: list[dict[str, Any]] = []
    for meal in MEALS:
        carbs = float((meals.get(meal) or {}).get("carbs_g") or 0.0)
        if carbs > hi:
            alerts.append(
                {
                    "level": "over",
                    "nutrient": "carbs_g",
                    "meal": meal,
                    "message": (
                        f"{meal.capitalize()} carbohydrate is over the per-meal goal: "
                        f"{_fmt('carbs_g', carbs)} / {_fmt('carbs_g', hi)} g"
                    ),
                }
            )
    return alerts


def build_projected_alerts(status: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Alerts on *projected* (eaten + planned) totals, phrased as a forecast (over first).

    Same selection rule as :func:`build_alerts`; the wording follows the contract example
    "If you eat what's planned, potassium reaches 104 % of today's limit (2600 / 2500 mg)".
    """
    alerts: list[dict[str, Any]] = []
    for key, item in status.items():
        level = item.get("level")
        fraction = _finite_fraction(item)
        if level not in ("caution", "over") or fraction is None:
            continue
        nutrient = NUTRIENT_BY_KEY[key]
        pct = int(round(fraction * 100))
        word = _ROLE_WORD.get(nutrient.role, "goal")
        message = (
            f"If you eat what's planned, {nutrient.label.lower()} reaches {pct} % of today's {word} "
            f"({_fmt(key, item.get('value'))} / {_fmt(key, item.get('target'))} {nutrient.unit})"
        )
        alerts.append({"level": level, "nutrient": key, "message": message})
    alerts.sort(key=lambda a: 0 if a["level"] == "over" else 1)
    return alerts


def projected_meal_carb_alerts(
    meals: Mapping[str, Mapping[str, float | None]],
    carbs_per_meal_target: Any,
) -> list[dict[str, Any]]:
    """``over`` alerts for meals whose *projected* carbohydrate exceeds the per-meal goal."""
    _, hi = target_bounds(carbs_per_meal_target)
    if not hi:
        return []
    alerts: list[dict[str, Any]] = []
    for meal in MEALS:
        carbs = float((meals.get(meal) or {}).get("carbs_g") or 0.0)
        if carbs > hi:
            alerts.append(
                {
                    "level": "over",
                    "nutrient": "carbs_g",
                    "meal": meal,
                    "message": (
                        f"If you eat what's planned, {meal} carbohydrate reaches "
                        f"{_fmt('carbs_g', carbs)} / {_fmt('carbs_g', hi)} g (over the per-meal goal)"
                    ),
                }
            )
    return alerts


# --------------------------------------------------------------------------- #
# Suggested targets
# --------------------------------------------------------------------------- #

# Starting points from ARCHITECTURE.md "Suggested targets", reconciled with
# docs/research/targets_by_stage.json and docs/diet-guide.md section 7. Kept as data.
CALORIES_PER_KG = 30.0  # KDOQI 25–35 kcal/kg
CARB_FRACTION_OF_CALORIES = 0.45
PROTEIN_G_PER_KG = {
    # (dialysis) -> (min, max); non-dialysis also depends on stage, see below.
    "hemodialysis": (1.0, 1.2),
    "peritoneal": (1.0, 1.2),
    "none_ckd3plus": (0.6, 0.8),  # CKD 3–5 with diabetes
    "none_ckd1_2": (0.8, 1.0),  # not in the contract: RDA 0.8, avoid > 1.3 g/kg (KDIGO)
}
# Starting points (ARCHITECTURE.md "Suggested targets"): no guideline fixes a number;
# restriction is only ordered when serum potassium runs high. These are the review
# ceilings of docs/research/targets_by_stage.json (the fact-checked file wins).
POTASSIUM_MG = {
    "hemodialysis": 2500,
    "peritoneal": 3500,
    "1": 4000,  # informational: stages 1–2 are usually unrestricted
    "2": 4000,
    "3a": 4000,
    "3b": 3500,
    "4": 3000,
    "5": 2500,
}
# Returned verbatim with every potassium suggestion (contract requirement).
POTASSIUM_NOTE = "Only restrict potassium if your blood potassium is high; your care team sets the number."
# 800–1000 mg when phosphate runs high (KDOQI 2003): 1000 for stages 1–4 and on dialysis
# ("adjusted for protein needs"), 900 for stage 5 without dialysis. Reconciled with
# docs/research/targets_by_stage.json (tests compare the two).
PHOSPHORUS_MG = {"1": 1000, "2": 1000, "3a": 1000, "3b": 1000, "4": 1000, "5": 900}
PHOSPHORUS_MG_DIALYSIS = {"hemodialysis": 1000, "peritoneal": 1000}
SODIUM_MG = 2000
CALCIUM_MG = 1000
FLUID_ML = {"none": None, "hemodialysis": 1500, "peritoneal": 2000}

# Every per-kg guideline figure (KDOQI 2020 3.0.1 energy, 3.1.x protein) is per kg of *ideal*
# body weight. Without the person's sex the Hamwi/Devine formulas cannot be used, so the ideal
# weight is taken sex-neutrally as the weight at the edge of the healthy BMI band for the
# person's height: BMI 25 when they are above it, BMI 18.5 when below, their actual weight
# in between. Without a height the actual weight is the only option, and the notes say so.
IBW_BMI_MIN = 18.5
IBW_BMI_MAX = 25.0


def dosing_weight(weight_kg: float, height_cm: float | None) -> tuple[float, str]:
    """``(weight used for per-kg targets, basis)``.

    ``basis`` is ``"actual"`` (within the healthy BMI band, or no height), ``"ideal_bmi_25"`` or
    ``"ideal_bmi_18.5"``. The returned weight is rounded to 0.1 kg.
    """
    w = float(weight_kg)
    if height_cm is None or not math.isfinite(float(height_cm)) or float(height_cm) <= 0:
        return w, "actual"
    h_m = float(height_cm) / 100.0
    bmi = w / (h_m * h_m)
    eps = 1e-9  # exactly BMI 25.0 / 18.5 counts as inside the band despite float noise
    if bmi > IBW_BMI_MAX + eps:
        return _half_up(IBW_BMI_MAX * h_m * h_m, 1), "ideal_bmi_25"
    if bmi < IBW_BMI_MIN - eps:
        return _half_up(IBW_BMI_MIN * h_m * h_m, 1), "ideal_bmi_18.5"
    return w, "actual"


def suggest_targets(
    weight_kg: float,
    ckd_stage: str,
    dialysis: str = "none",
    diabetes: str = "type1",
    height_cm: float | None = None,
) -> dict[str, Any]:
    """Return ``{"targets": {...}, "notes": [...]}`` starting points for the care team to adjust.

    Calories, protein and therefore carbohydrate are per kg of **ideal** body weight
    (see :func:`dosing_weight`); with no ``height_cm`` the actual weight is used and the notes say so.
    """
    if weight_kg is None or not math.isfinite(float(weight_kg)) or float(weight_kg) <= 0:
        raise ValueError("weight_kg must be a positive number")
    if height_cm is not None and (not math.isfinite(float(height_cm)) or float(height_cm) <= 0):
        raise ValueError("height_cm must be a positive number")
    if ckd_stage not in CKD_STAGES:
        raise ValueError(f"ckd_stage must be one of {', '.join(CKD_STAGES)}")
    if dialysis not in DIALYSIS_MODES:
        raise ValueError(f"dialysis must be one of {', '.join(DIALYSIS_MODES)}")
    if diabetes not in DIABETES_TYPES:
        raise ValueError(f"diabetes must be one of {', '.join(DIABETES_TYPES)}")

    actual = float(weight_kg)
    w, basis = dosing_weight(actual, height_cm)
    on_dialysis = dialysis != "none"
    notes: list[str] = []

    if basis == "actual" and height_cm is None:
        notes.append(
            f"Weight basis: guidelines give calories and protein per kg of ideal body weight; without a saved "
            f"height the actual weight ({actual:g} kg) is used. Add your height if you are over- or under-weight."
        )
    elif basis == "actual":
        notes.append(
            f"Weight basis: {actual:g} kg is within the healthy BMI range for {float(height_cm):g} cm, "
            "so it is used as the ideal body weight."
        )
    else:
        edge = "25" if basis == "ideal_bmi_25" else "18.5"
        notes.append(
            f"Weight basis: calories and protein are per kg of ideal body weight; for {float(height_cm):g} cm "
            f"that is taken as {w:g} kg (BMI {edge}), not the actual {actual:g} kg (KDOQI 2020)."
        )

    calories = int(round(CALORIES_PER_KG * w))
    notes.append(
        f"Calories: {CALORIES_PER_KG:g} kcal/kg × {w:g} kg ideal body weight = {calories} kcal "
        "(KDOQI 2020 3.0.1 range 25–35 kcal/kg)."
    )

    if on_dialysis:
        p_min, p_max = PROTEIN_G_PER_KG[dialysis]
        notes.append(
            f"Protein: {p_min}–{p_max} g/kg ideal body weight for {dialysis} (KDOQI 2020 3.1.2/3.1.4); "
            "losses during dialysis mean more protein is needed, not less."
        )
    elif ckd_stage in ("1", "2"):
        p_min, p_max = PROTEIN_G_PER_KG["none_ckd1_2"]
        notes.append(
            f"Protein: {p_min}–{p_max} g/kg ideal body weight for CKD stage {ckd_stage}; guidelines only ask to avoid "
            "high intakes (> 1.3 g/kg) this early."
        )
    else:
        p_min, p_max = PROTEIN_G_PER_KG["none_ckd3plus"]
        source = (
            "non-dialysis CKD 3–5 with diabetes (KDOQI 2020 3.1.3)"
            if diabetes != "none"
            else "non-dialysis CKD 3–5 (KDOQI 2020 3.1.1 gives 0.55–0.6; KDIGO 2024 3.3.1.1 gives 0.8)"
        )
        notes.append(
            f"Protein: {p_min}–{p_max} g/kg ideal body weight for {source}; "
            "below 0.6 risks wasting and hypoglycaemia; guidelines recommend 0.8 and advise avoiding "
            "more than 1.3 g/kg (KDIGO 2024)."
        )
    protein = {"min": int(round(p_min * w)), "max": int(round(p_max * w))}

    if on_dialysis:
        potassium = POTASSIUM_MG[dialysis]
        notes.append(f"Potassium: {potassium} mg/day is a common {dialysis} starting point. {POTASSIUM_NOTE}")
    else:
        potassium = POTASSIUM_MG[ckd_stage]
        if ckd_stage in ("1", "2"):
            notes.append(
                f"Potassium: {potassium} mg/day is informational only; stages 1–2 usually need no restriction. "
                f"{POTASSIUM_NOTE}"
            )
        else:
            notes.append(
                f"Potassium: {potassium} mg/day is the starting point for stage {ckd_stage}; medicines "
                f"(ACE inhibitors, ARBs, potassium binders) change it. {POTASSIUM_NOTE}"
            )

    phosphorus = PHOSPHORUS_MG_DIALYSIS[dialysis] if on_dialysis else PHOSPHORUS_MG[ckd_stage]
    notes.append(
        f"Phosphorus: {phosphorus} mg/day (guideline range 800–1000 mg); avoiding phosphate additives "
        "matters more than the total because additive phosphorus is almost fully absorbed."
    )

    notes.append(f"Sodium: {SODIUM_MG} mg/day (KDIGO < 2000 mg, KDOQI < 2300 mg).")

    fluid = FLUID_ML[dialysis]
    if dialysis == "hemodialysis":
        notes.append(
            "Fluid: 1000 mL plus your 24-hour urine volume; 1500 mL assumes about 500 mL of urine. "
            "Ask your dialysis unit for your personal allowance."
        )
    elif dialysis == "peritoneal":
        notes.append(
            "Fluid: about 2000 mL/day on peritoneal dialysis, individualised to residual kidney function. "
            "Also subtract the glucose absorbed from dialysate (often 400+ kcal/day) from the calorie goal."
        )
    else:
        notes.append("Fluid: no routine limit without dialysis (left untracked) unless your care team sets one.")

    carbs = int(round(calories * CARB_FRACTION_OF_CALORIES / 4.0))
    carbs_per_meal = max(15, int(round(carbs / 4.0 / 5.0)) * 5)
    if diabetes == "none":
        notes.append(f"Carbohydrate: 45 % of calories ÷ 4 kcal/g = {carbs} g/day.")
    else:
        notes.append(
            f"Carbohydrate: 45 % of calories ÷ 4 kcal/g = {carbs} g/day, about {carbs_per_meal} g per meal "
            "for carb counting; your insulin-to-carb ratio decides the real per-meal number."
        )

    notes.append(f"Calcium: {CALCIUM_MG} mg/day total including calcium-based phosphate binders.")
    notes.append("These are starting points only — confirm every target with your nephrologist and renal dietitian.")

    targets: dict[str, Any] = {
        "calories_kcal": calories,
        "protein_g": protein,
        "carbs_g": carbs,
        "carbs_per_meal_g": carbs_per_meal,
        "sodium_mg": SODIUM_MG,
        "potassium_mg": potassium,
        "phosphorus_mg": phosphorus,
        "calcium_mg": CALCIUM_MG,
        "fluid_ml": fluid,
    }
    return {"targets": targets, "notes": notes}
