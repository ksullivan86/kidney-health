"""Nutrient registry and the pure rules of the app.

Everything in this module is a pure function: no I/O, no database, no FastAPI.
It is the single source of truth for nutrient keys, per-serving warning
thresholds, daily status levels and the suggested-target starting points
described in ARCHITECTURE.md. The suggested-target rules themselves live in
:mod:`app.targets` (v0.3); :func:`suggest_targets` keeps the v0.2 signature on top of them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

# Returned with every potassium suggestion (contract requirement); the note texts live in
# app/target_rules.py, a data-only module (no import cycle).
from .target_rules import POTASSIUM_NOTE  # noqa: F401  (re-exported: nutrients.POTASSIUM_NOTE)

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
# Suggested targets (v0.2 signature; the rules live in app/targets.py since v0.3)
# --------------------------------------------------------------------------- #

def dosing_weight(weight_kg: float, height_cm: float | None) -> tuple[float, str]:
    """``(reference weight in kg, basis)`` for per-kg targets; see :func:`app.targets.reference_weight`.

    ``basis`` is ``"actual"`` (healthy BMI band), ``"actual_no_height"``, ``"adjusted_above_bmi25"``
    or ``"adjusted_below_bmi18_5"``; the weight is rounded half-up to 0.1 kg (note 05 §4.3).
    """
    from .targets import reference_weight

    ref = reference_weight(weight_kg, height_cm)
    return ref.weight_kg, ref.basis


def suggest_targets(
    weight_kg: float,
    ckd_stage: str,
    dialysis: str = "none",
    diabetes: str = "type1",
    height_cm: float | None = None,
) -> dict[str, Any]:
    """``{"targets": {...}, "notes": [...]}``: starting points for the care team to adjust.

    The v0.2 entry point, kept for existing callers: it builds :class:`app.targets.Inputs` from
    these arguments alone (no age, sex, activity, labs or transplant) and applies the personalised
    rules of note 05 §4.3 (``app.targets.suggest``). Raises ``ValueError`` for an input the rules
    cannot use. ``GET /api/profile/suggested-targets`` uses :func:`app.targets.suggest_from_records`
    with the whole profile and the person's lab results instead.
    """
    from datetime import date

    from .targets import Inputs, suggest

    inputs = Inputs(weight_kg=weight_kg, ckd_stage=ckd_stage, dialysis=dialysis, diabetes=diabetes, height_cm=height_cm)
    # Without a birth month, transplant date or labs the date does not change the result.
    result = suggest(inputs, date.today())
    return {"targets": result.targets, "notes": result.notes}
