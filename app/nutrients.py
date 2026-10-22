"""Nutrient registry and the pure rules of the app.

Everything in this module is a pure function: no I/O, no database, no FastAPI.
It is the single source of truth for nutrient keys, per-serving warning
thresholds, daily status levels and the suggested-target starting points
described in ARCHITECTURE.md. The suggested-target rules themselves live in
:mod:`app.targets` (v0.3); :func:`suggest_targets` keeps the v0.2 signature on top of them.

The module is the generic nutrient core plus a stable import surface. The kidney and type 1 diabetes
rules (thresholds, ``food_warnings``, ``kidney_rating``, the per-meal carbohydrate alerts,
``suggest_targets``, the CKD, dialysis and diabetes choices and the food flags) live in
:mod:`app.rules_kidney`, and the registry, rounding and number formatting they share with this module in
:mod:`app.nutrient_core` (design note 14, section 2.2). Both are re-exported below, so every
``from .nutrients import X`` and ``nutrients.X`` keeps working.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

# The registry and display rounding (app/nutrient_core.py), and the kidney/T1D rule pack (app/rules_kidney.py),
# re-exported under their old names: callers and tests keep importing everything from here.
from .nutrient_core import (  # noqa: F401  (re-exported)
    MEALS,
    NUTRIENT_BY_KEY,
    NUTRIENT_KEYS,
    NUTRIENTS,
    Nutrient,
    _INTEGER_UNITS,
    _fmt,
    _half_up,
    round_value,
    target_bounds,
)
from .rules_kidney import (  # noqa: F401  (re-exported)
    CKD_STAGES,
    DIABETES_TYPES,
    DIALYSIS_MODES,
    FLAGS,
    HIGH_GI_MIN_CARBS_G,
    POTASSIUM_ADDITIVE_MESSAGE,
    POTASSIUM_NOTE,
    THRESHOLDS,
    WARNING_ORDER,
    Threshold,
    _carb_choices,
    _carb_goals,
    _goal_word,
    _hypo_words,
    _LEVEL_WORD,
    _meal_carb_alert_items,
    _over_words,
    _warning_message,
    carb_tolerance,
    dosing_weight,
    food_warnings,
    kidney_rating,
    meal_carb_alerts,
    projected_meal_carb_alerts,
    suggest_targets,
    threshold_level,
)

# Profile targets may also carry a per-meal carbohydrate goal (type 1 carb counting) and, optionally,
# a goal for the snack slot (meal guidance; default max(15, carbs_per_meal_g / 2 rounded to 5 g)).
TARGET_KEYS: tuple[str, ...] = NUTRIENT_KEYS + ("carbs_per_meal_g", "carbs_per_snack_g")

FOOD_SOURCES: tuple[str, ...] = ("builtin", "usda", "custom", "off")  # off: Open Food Facts (v0.3, note 03)


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


def count_unknown(acc: dict[str, int], values: Mapping[str, float | None]) -> dict[str, int]:
    """Count, in ``acc`` (in place), the nutrients ``values`` does not know: ``{key: entries}``.

    :func:`add_totals` skips an unknown value, so a total alone cannot tell "none" from "not listed"
    (most scanned foods have no potassium or phosphorus value). Only keys with a count are present."""
    for key in NUTRIENT_KEYS:
        if values.get(key) is None:
            acc[key] = acc.get(key, 0) + 1
    return acc


def merge_unknown(*counts: Mapping[str, int]) -> dict[str, int]:
    """The sum of several :func:`count_unknown` results (e.g. eaten + planned = projected)."""
    out: dict[str, int] = {}
    for count in counts:
        for key, n in count.items():
            out[key] = out.get(key, 0) + int(n)
    return out


def mark_unknown(status: dict[str, dict[str, Any]], unknown: Mapping[str, int]) -> dict[str, dict[str, Any]]:
    """Set ``"unknown": n`` on every :func:`daily_status` item: how many entries' values its total
    misses (0 when all are known). The level is kept (it is judged on what is known), but with
    ``n > 0`` the total is incomplete: the true value may be higher, so the app must never show it
    as a plain, complete figure."""
    for key, item in status.items():
        item["unknown"] = int(unknown.get(key, 0))
    return status


def scale_nutrients(values: Mapping[str, float | None], factor: float) -> dict[str, float | None]:
    """Multiply every known nutrient by ``factor``; unknown (``None``) stays ``None``."""
    return {
        key: (None if values.get(key) is None else float(values[key]) * factor)
        for key in NUTRIENT_KEYS
    }


# --------------------------------------------------------------------------- #
# Daily status against targets
# --------------------------------------------------------------------------- #


def status_level(fraction: float | None, warn_fraction: float, over_at: float = 1.0) -> str:
    """``over`` above ``over_at`` (1.0, or more for an "about" target with a tolerance), ``caution`` from
    ``warn_fraction``, else ``ok``."""
    if fraction is None or math.isnan(fraction):
        return "ok"
    if fraction > over_at:  # includes +inf
        return "over"
    if fraction >= warn_fraction:
        return "caution"
    return "ok"


# The person's tolerance above an "about" target (v0.3.1): 0 (the default, the number itself) to 10 %, from
# their care team. No guideline gives a value, so the app sets none (handbook/REVIEW.md, "Food targets").
ABOUT_TOLERANCE_MAX_PCT = 10


def about_tolerance(pct: Any) -> float:
    """The tolerance in percent, clamped to 0..``ABOUT_TOLERANCE_MAX_PCT``; anything unusable is 0."""
    try:
        value = float(pct or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), float(ABOUT_TOLERANCE_MAX_PCT))


def _is_limit(key: str) -> bool:
    nutrient = NUTRIENT_BY_KEY.get(key)
    return nutrient is not None and nutrient.role == "limit"


def is_about(key: str, lo: float | None, hi: float | None) -> bool:
    """A range whose minimum equals its maximum once rounded (protein "about 56 g", note 05 §4.8), as the UI
    shows it. A limit (potassium, sodium, phosphorus, fluid) is never an "about" target, even entered so."""
    if lo is None or hi is None or not (math.isfinite(lo) and math.isfinite(hi)) or hi <= 0 or _is_limit(key):
        return False
    return round_value(key, lo) == round_value(key, hi)


def over_at(key: str, lo: float | None, hi: float | None, about_tolerance_pct: Any = 0) -> float:
    """The fraction of the maximum above which a total is ``over``: 1 + the tolerance for an "about" target,
    else 1.0."""
    return 1.0 + about_tolerance(about_tolerance_pct) / 100.0 if is_about(key, lo, hi) else 1.0


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
    about_tolerance_pct: Any = 0,
) -> dict[str, dict[str, Any]]:
    """Per-nutrient ``{"value","target","fraction","level"}`` (+ ``"min"`` for ranges).

    Only nutrient keys that have a non-null target are included; the per-meal
    carbohydrate goal is not a nutrient and is handled by :func:`meal_carb_alerts`.
    An "about" target (minimum = maximum) is ``over`` only above the person's ``about_tolerance_pct``.
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
        level = status_level(fraction, warn_fraction, over_at(key, lo, hi, about_tolerance_pct))
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


def _status_word(key: str, item: Mapping[str, Any]) -> str:
    """How an alert names the number: "target" for an "about" target (minimum = maximum, as the UI words it),
    else by the nutrient's role."""
    if not _is_limit(key) and item.get("min") is not None and item.get("target") is not None and item["min"] == item["target"]:
        return "target"
    return _ROLE_WORD.get(NUTRIENT_BY_KEY[key].role, "goal")


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
        word = _status_word(key, item)
        if level == "caution":
            message = f"{nutrient.label} is at {pct} % of today's {word} ({value} / {target} {nutrient.unit})"
        else:
            message = f"{nutrient.label} is over today's {word}: {value} / {target} {nutrient.unit} ({pct} %)"
        alerts.append({"level": level, "nutrient": key, "message": message})
    alerts.sort(key=lambda a: 0 if a["level"] == "over" else 1)
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
        word = _status_word(key, item)
        message = (
            f"If you eat what's planned, {nutrient.label.lower()} reaches {pct} % of today's {word} "
            f"({_fmt(key, item.get('value'))} / {_fmt(key, item.get('target'))} {nutrient.unit})"
        )
        alerts.append({"level": level, "nutrient": key, "message": message})
    alerts.sort(key=lambda a: 0 if a["level"] == "over" else 1)
    return alerts
