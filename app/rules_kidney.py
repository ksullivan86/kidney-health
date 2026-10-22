"""The kidney and type 1 diabetes rule pack of the nutrient core (design note 14, section 2.2).

What :mod:`app.nutrients` used to hold next to the generic pieces and now lives here, code unchanged: the
chronic kidney disease, dialysis and diabetes choices and the food flags, the per-serving thresholds and the
warnings built on them (``food_warnings``, ``kidney_rating``), the per-meal carbohydrate alerts and the
carbohydrate tolerance, and the v0.2 ``suggest_targets`` entry point over :mod:`app.targets`. Every
clinical number is cited where it is defined (ARCHITECTURE.md, ``docs/research/``, the handbook sources).

The nutrient registry, rounding and number formatting come from :mod:`app.nutrient_core`; the daily status and
alert builders, which know nothing of a condition, stay in :mod:`app.nutrients`. Callers keep importing every
name from :mod:`app.nutrients`, which re-exports this module. The safety rules in CLAUDE.md travel with this
pack: a ``hypo_treatment`` food gets no carbohydrate warning, and carbohydrate eaten to treat a low is left
out of every meal-carb alert.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .nutrient_core import MEALS, NUTRIENT_BY_KEY, _fmt, round_value, target_bounds

# Returned with every potassium suggestion (contract requirement); the note texts live in
# app/target_rules.py, a data-only module (no import cycle).
from .target_rules import POTASSIUM_NOTE  # noqa: F401  (re-exported: nutrients.POTASSIUM_NOTE)

CKD_STAGES: tuple[str, ...] = ("1", "2", "3a", "3b", "4", "5")
DIALYSIS_MODES: tuple[str, ...] = ("none", "hemodialysis", "peritoneal")
DIABETES_TYPES: tuple[str, ...] = ("none", "type1", "type2")

FLAGS: tuple[str, ...] = (
    "phosphate_additive",
    "potassium_additive",  # v0.3 (note 03 R5, ARCHITECTURE v0.3 item 9): a bulk potassium salt in the ingredients
    "high_gi",
    "counts_as_fluid",
    "avoid_ckd",
    "hypo_treatment",
    "low_potassium_fruit",
    "processed",
    "ingredient",  # only ever added to other food (flour, salt, oil): meal guidance never suggests it alone
    "alcohol",  # v0.3: an alcoholic drink; meal guidance never suggests it (delayed lows with insulin: ADA 2026 §5, 5.18–5.19)
)

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

# ARCHITECTURE.md v0.3 item 9: shown when a food lists a potassium additive but no potassium value.
# Products listing one measured 750-1,100 mg potassium per 100 g (Parpia 2018) and additive potassium
# is about 90 % absorbed (KDIGO 2024 Figure 33); docs/research/fact-check.md section 5. Medium, not high,
# until a renal dietitian reviews it (handbook review list).
POTASSIUM_ADDITIVE_MESSAGE = "Contains a potassium additive; potassium not listed"


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
    if flag == "potassium_additive":
        return POTASSIUM_ADDITIVE_MESSAGE
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

    ``potassium_additive`` (v0.3 item 9): when the potassium value is unknown (``None``) the food
    gets a ``medium`` potassium warning, "Contains a potassium additive; potassium not listed", with
    ``value`` ``None``; when potassium is listed the normal thresholds apply unchanged.
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
        elif key == "potassium_mg" and "potassium_additive" in flag_set and round_value(key, value) is None:
            level, flag = "medium", "potassium_additive"
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


def _carb_goals(carbs_per_meal_target: Any, snack_target: Any) -> dict[str, float]:
    """The carbohydrate goal of each meal: the per-meal goal, and for the snack ``carbs_per_snack_g`` when set
    (note 06 §4.11: a person's snack goal from their diabetes team; v0.3.0 review L11)."""
    _, per_meal = target_bounds(carbs_per_meal_target)
    _, snack = target_bounds(snack_target)
    goals = {meal: float(per_meal) for meal in MEALS if per_meal}
    if snack:
        goals["snack"] = float(snack)
    return goals


def _goal_word(meal: str, snack_target: Any) -> str:
    return "snack goal" if meal == "snack" and target_bounds(snack_target)[1] else "per-meal goal"


def carb_tolerance(tolerance_g: Any) -> float:
    """The person's carbohydrate tolerance in grams (``guidance.carb_tolerance_g``, 5–20, default 10: Smart et al.
    2009/2012, note 06 F4); anything unusable is 0, the goal itself."""
    try:
        value = float(tolerance_g or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def _meal_carb_alert_items(
    meals: Mapping[str, Mapping[str, float | None]],
    carbs_per_meal_target: Any,
    snack_target: Any,
    tolerance_g: Any,
    hypo_carbs: Mapping[str, float] | None,
) -> list[tuple[str, float, float, float, float, str]]:
    """``(meal, counted carbs, goal, tolerance, low-treatment carbs left out, goal word)`` for each meal whose
    carbohydrate is more than the tolerance above its goal. Carbohydrate eaten to treat a low is left out: treating
    a low is never warned against (note 06 §4.11)."""
    goals = _carb_goals(carbs_per_meal_target, snack_target)
    tol = carb_tolerance(tolerance_g)
    out = []
    for meal in MEALS:
        hi = goals.get(meal)
        if not hi:
            continue
        hypo = float((hypo_carbs or {}).get(meal) or 0.0)
        carbs = float((meals.get(meal) or {}).get("carbs_g") or 0.0) - hypo
        if carbs > hi + tol:
            out.append((meal, carbs, hi, tol, hypo, _goal_word(meal, snack_target)))
    return out


def _over_words(tol: float, word: str) -> str:
    return f"more than {_fmt('carbs_g', tol)} g over the {word}" if tol > 0 else f"over the {word}"


def _hypo_words(hypo: float) -> str:
    return f"not counting {_fmt('carbs_g', hypo)} g used to treat a low" if hypo > 0 else ""


def meal_carb_alerts(
    meals: Mapping[str, Mapping[str, float | None]],
    carbs_per_meal_target: Any,
    snack_target: Any = None,
    *,
    tolerance_g: Any = 0,
    hypo_carbs: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """``over`` alerts for meals whose carbohydrate is more than ``tolerance_g`` above the per-meal goal (the snack:
    its own goal when set); ``hypo_carbs`` (per meal) are left out."""
    alerts: list[dict[str, Any]] = []
    for meal, carbs, hi, tol, hypo, word in _meal_carb_alert_items(meals, carbs_per_meal_target, snack_target,
                                                                     tolerance_g, hypo_carbs):
        note = _hypo_words(hypo)
        alerts.append(
            {
                "level": "over",
                "nutrient": "carbs_g",
                "meal": meal,
                "message": (
                    f"{meal.capitalize()} carbohydrate is {_over_words(tol, word)}: "
                    f"{_fmt('carbs_g', carbs)} / {_fmt('carbs_g', hi)} g" + (f" ({note})" if note else "")
                ),
            }
        )
    return alerts


def projected_meal_carb_alerts(
    meals: Mapping[str, Mapping[str, float | None]],
    carbs_per_meal_target: Any,
    snack_target: Any = None,
    *,
    tolerance_g: Any = 0,
    hypo_carbs: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """``over`` alerts for meals whose *projected* carbohydrate is more than ``tolerance_g`` above the per-meal goal
    (the snack: its own goal when set); ``hypo_carbs`` (per meal, eaten and planned) are left out."""
    alerts: list[dict[str, Any]] = []
    for meal, carbs, hi, tol, hypo, word in _meal_carb_alert_items(meals, carbs_per_meal_target, snack_target,
                                                                     tolerance_g, hypo_carbs):
        parts = [_over_words(tol, word), _hypo_words(hypo)]
        alerts.append(
            {
                "level": "over",
                "nutrient": "carbs_g",
                "meal": meal,
                "message": (
                    f"If you eat what's planned, {meal} carbohydrate reaches "
                    f"{_fmt('carbs_g', carbs)} / {_fmt('carbs_g', hi)} g ({'; '.join(p for p in parts if p)})"
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
