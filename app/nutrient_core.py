"""The nutrient registry, display rounding and number formatting that both :mod:`app.nutrients` and
:mod:`app.rules_kidney` stand on.

Pure and domain-neutral: the twelve nutrients with their units and roles, the meal names, the app's half-up
rounding, ``_fmt`` and the normalising of a target to ``(min, max)``. They live here only so that
``rules_kidney`` (the kidney and type 1 diabetes rule pack, design note 14 section 2.2) and ``nutrients``
(which re-exports the rule pack so that every caller keeps ``from .nutrients import ...``) can both import
them without an import cycle. Callers import these names from :mod:`app.nutrients`, as before.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Mapping

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

MEALS: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")

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


def _fmt(key: str, value: float | int | None) -> str:
    """Human formatting for messages: ``2125``, ``40``, ``40.5``."""
    if value is None:
        return "?"
    rounded = round_value(key, value)
    if rounded is None:  # NaN or infinity from an old database row: shown as unknown
        return "?"
    if isinstance(rounded, int):
        return str(rounded)
    return f"{rounded:g}"


def target_bounds(target: Any) -> tuple[float | None, float | None]:
    """Normalise a target (number | {min,max} | None) to ``(min, max)``."""
    if target is None:
        return (None, None)
    if isinstance(target, Mapping):
        lo = target.get("min")
        hi = target.get("max")
        return (None if lo is None else float(lo), None if hi is None else float(hi))
    return (None, float(target))
