"""Constants, roles and eligibility of the guidance engine (note 06 §4.3). Pure, no I/O.

Every number the engine uses lives in this module, is listed by :func:`rules_table` (returned by
``GET /api/guidance/rules`` and printed in ``docs/guidance.md``) and is versioned by
:data:`RULES_VERSION`. Changing any of them means regenerating the golden vectors
(``python3 tests/data/gen_guidance_vectors.py``) in the same change, and bumping the version.

Evidence level (note 06 §2): the per-meal caps are dietitian rules of thumb (AKF Kidney Kitchen:
600–700 mg potassium per meal and 100–200 mg per snack; Satellite Healthcare: < 600 mg sodium per
meal), expressed as a fraction of the person's own daily target so they scale with what the care
team set (F1). No guideline gives a per-meal number, so the caps only shape suggestions; they never
create a warning or an alert. The carbohydrate tolerance (±10 g) comes from Smart et al. 2009/2012
(F4), the hypo dose from the rule of 15 (ADA 2026 Rec 6.15, F5), the protein-quality ratios from
Noori et al. 2010 (F2). Weights (``USAGE_WEIGHT`` …) are design choices tuned on the reference
prototype; they are not clinical numbers.

Rounding helpers here are the ones the demo-mode JavaScript twin mirrors (``Math.round``
semantics), so both sides produce byte-identical vectors.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable, Mapping

RULES_VERSION = "2026-10-05.1"

MAIN_MEALS: tuple[str, ...] = ("breakfast", "lunch", "dinner")
SNACK = "snack"
SLOT_ORDER: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")

K, P, NA, FLUID, CARBS, PROTEIN, KCAL = (
    "potassium_mg", "phosphorus_mg", "sodium_mg", "fluid_ml", "carbs_g", "protein_g", "calories_kcal",
)

# F1: 0.30 of the day's target per main meal reproduces AKF's 600 mg at a 2,000 mg target; the snack
# slot (every snack of the day together) gets 0.15. The same numbers weight the fair share.
MEAL_WEIGHT: dict[str, float] = {"breakfast": 0.30, "lunch": 0.30, "dinner": 0.30, "snack": 0.15}
MEAL_CAP_FRACTION: dict[str, float] = {"breakfast": 0.30, "lunch": 0.30, "dinner": 0.30, "snack": 0.15}

# Nutrients budgeted per meal (fluid has a day allowance but no per-meal cap).
ROOM_KEYS: tuple[str, ...] = (K, P, NA, FLUID)
CAP_KEYS: tuple[str, ...] = (K, P, NA)
RENAL_KEYS: tuple[str, ...] = (K, P, NA)
DAY_JUDGED: tuple[str, ...] = (K, NA, FLUID)
INTERDIALYTIC_KEYS: tuple[str, ...] = (K, NA, FLUID)

# Amounts that do not count against a room: below the app's "medium" thresholds; F4's "free food".
NEGLIGIBLE: dict[str, float] = {K: 50.0, NA: 50.0, P: 30.0, FLUID: 30.0, CARBS: 5.0}
# Potassium acts fastest (diet guide §2); phosphorus weighs one more when this week's level is not ok.
USAGE_WEIGHT: dict[str, float] = {K: 3.0, NA: 2.0, P: 2.0, FLUID: 2.0}
USAGE_WEIGHT_P_NOT_OK = 3.0

PORTIONS_MAIN: tuple[float, ...] = (1.0, 0.5, 1.5, 2.0)  # protein, mixed, starch, veg/fruit
PORTIONS_SIDE: tuple[float, ...] = (1.0, 0.5)  # drinks, extras (F10: never two root beers)
PORTIONS_BUILD: tuple[float, ...] = (1.0, 0.5)  # plan-day candidate ranking (+1.5 for protein)
PORTIONS_BUILD_PROTEIN: tuple[float, ...] = (1.0, 0.5, 1.5)

WEEK_LOOKBACK_DAYS = 6
WEEK_CLAMP: tuple[float, float] = (0.8, 1.2)

CARB_TOLERANCE_G = 10  # F4: ±10 g per meal (Smart 2009/2012); a personal setting 5–20 g
CARB_TOLERANCE_RANGE: tuple[int, int] = (5, 20)
SNACK_CARB_MIN_G = 15  # one carbohydrate choice (NKF 1–3 per snack)
HYPO_DOSE_G = 15  # F5: rule of 15 (ADA 2026 Rec 6.15); a personal setting 5–30 g
HYPO_DOSE_RANGE: tuple[int, int] = (5, 30)
HIGH_K_ENTRY_MG = 200.0  # the app's per-serving "high" potassium
PROTEIN_ROLE_MIN_G = 7.0  # NKF: 7 g protein = 1 oz meat (F3)
STARCH_ROLE_MIN_CARBS_G = 15.0  # one carbohydrate choice
P_PER_G_PROTEIN: tuple[float, float] = (10.0, 16.0)  # good <=, poor >= (Noori 2010, F2)
K_PER_G_PROTEIN: tuple[float, float] = (10.0, 20.0)  # design choice: chicken breast 8, ground chicken 29
PROTEIN_AIM_FLOOR_G = 5.0
MIN_SHOW_SCORE = 0.0
GROUP_LIMITS: dict[str, int] = {"protein": 3, "starch": 3, "veg_fruit": 3, "extra": 2}
CATEGORY_LIMIT = 2
DEFAULT_LIMIT = 11
MAX_LIMIT = 20
BEAM_WIDTH = 16
BEAM_WIDTH_RANGE: tuple[int, int] = (1, 64)
PER_ROLE = 6
POOL_PER_ROLE = 200
POOL_PER_ROLE_RANGE: tuple[int, int] = (20, 2000)
FAMILIAR_MARGIN = 3.0
SLOT_HABIT_BONUS = 1.0
SLOT_HABIT_MIN_DAYS = 2
OFTEN_MIN_DAYS = 2
HISTORY_DAYS = 14
USUAL_HISTORY_DAYS = 60
USUAL_MIN_ITEMS, USUAL_MAX_ITEMS, USUAL_MIN_DATES = 2, 6, 2
SWAP_MIN_REDUCTION = 0.25
SWAP_CARB_MATCH: tuple[float, float] = (5.0, 0.10)  # ± max(5 g, 10 %)
SWAP_PROTEIN_MATCH: tuple[float, float] = (3.0, 0.15)  # ± max(3 g, 15 %)
SWAP_MATCH_CARBS_MIN_G = 10.0
SWAP_MATCH_PROTEIN_MIN_G = 3.0
SWAP_MAX = 5
SWAP_AI_MAX = 15
PORTION_MIN, PORTION_MAX = 0.25, 3.0
PORTION_OPTION_FRACTIONS: tuple[float, ...] = (0.75, 0.5)
HYPO_SWAP_TRIGGER_MG = 0.0  # in hypo mode the only trigger is potassium above this
HYPO_INSIGHT_K_MG = 50.0  # day.hypo.logged suggests a better treatment above this
HYPO_BEST_MAX_K_MG = 20.0  # … when a hypo food at or below this exists
INSIGHT_MAX = 6
SOURCE_MIN_SHARE = 0.10
SOURCE_MAX = 3
MIN_LOGGED_DAYS = 3
PERIOD_DEFAULT_DAYS = 7
PERIOD_MAX_DAYS = 92
PERIOD_CHANGE_MIN = 0.15
MEAL_SHARE_MIN = 0.45
PERIOD_HYPO_MIN = 3
SAVED_MEAL_SCALES: tuple[float, ...] = (1.0, 0.75, 0.5)
SAVED_MEALS_MAX = 3
AI_FOODS_MAX = 40
AI_FOODS_PER_GROUP_MIN = 6
AI_MEALS_MAX = 5
AI_PLAN_OPTIONS_MAX = 5
AI_QUARTERS_RANGE: tuple[int, int] = (1, 12)
ENERGY_NOTE_FRACTION = 0.8
ENERGY_LOW_INSIGHT_FRACTION = 0.7
ENERGY_DENSE_MIN_KCAL = 50.0
ENERGY_DENSE_MAX = {K: 50.0, P: 30.0, NA: 50.0, CARBS: 5.0}
ENERGY_NOTE_FOODS = 3
PROTEIN_TOPUP_STEP = 0.5
PROTEIN_TOPUP_STEPS = 2
REPAIR_STEP = 0.25
REPAIR_STEPS = 6
VARIANT_MAX = 4
UNKNOWN_PENALTY = 1.5
FREE_FOOD_CARBS_G = 5.0
HIGH_GI_PENALTY_MIN_CARBS_G = 15.0
FILLS_CARBS_MIN_G = 15.0  # the "fills_carbs" reason needs at least one carbohydrate choice
LOW_K_REASON_MG = 100.0
LOW_P_REASON_MG = 50.0
MAX_NAME_CHARS = 60  # untrusted (custom) names are truncated in insight text

# Renal thresholds: the app's per-serving warnings (ARCHITECTURE "Per-serving thresholds").
RENAL_MEDIUM: dict[str, float] = {K: 101.0, P: 101.0, NA: 141.0}
RENAL_HIGH: dict[str, float] = {K: 200.0, P: 150.0, NA: 400.0}

ROLES: tuple[str, ...] = ("protein", "mixed", "starch", "veg_fruit", "drink", "extra")
GROUP_OF_ROLE: dict[str, str] = {
    "protein": "protein", "mixed": "protein", "starch": "starch", "veg_fruit": "veg_fruit",
    "drink": "extra", "extra": "extra",
}
GROUPS: tuple[str, ...] = ("protein", "starch", "veg_fruit", "extra")
GROUP_LABEL: dict[str, str] = {
    "protein": "protein", "starch": "starch", "veg_fruit": "vegetable or fruit", "extra": "extra",
}
CARB_FILL_ROLES = frozenset({"starch", "mixed", "veg_fruit"})
PROTEIN_ROLES = frozenset({"protein", "mixed"})
STARCH_ROLES = frozenset({"starch", "mixed"})
MAIN_PORTION_ROLES = frozenset({"protein", "mixed", "starch", "veg_fruit"})

# Role sequence of a built meal (§4.7): mains protein → starch → veg/fruit; the snack slot one item.
MAIN_ROLE_STEPS: tuple[str, ...] = ("protein", "starch", "veg_fruit")
STEP_ROLES: dict[str, frozenset[str]] = {
    "protein": frozenset({"protein", "mixed"}),
    "starch": frozenset({"starch"}),
    "veg_fruit": frozenset({"veg_fruit"}),
}
SNACK_ROLES: tuple[str, ...] = ("veg_fruit", "starch", "extra", "drink")

INGREDIENT_FLAG = "ingredient"
SUPPLIES_CATEGORY = "Diabetes supplies"
BEVERAGES = "Beverages"
VEGETABLES = "Vegetables"
# Name stems of the vegetables whose potassium leaching helps (diet guide §5, NKF).
LEACHING_STEMS: tuple[str, ...] = ("potato", "sweet potato", "yam", "carrot", "beet", "squash")

# Severity and nutrient order of insights (§4.8).
SEVERITY_ORDER: dict[str, int] = {"warning": 0, "attention": 1, "info": 2, "good": 3}
NUTRIENT_PRIORITY: dict[str, int] = {K: 0, P: 1, NA: 2, FLUID: 3, PROTEIN: 4, CARBS: 5}


# --------------------------------------------------------------------------- #
# Rounding (the JavaScript twin uses exactly these operations)
# --------------------------------------------------------------------------- #


def js_round(value: float) -> float:
    """Round half toward +infinity, exactly like JavaScript's ``Math.round``."""
    floor = math.floor(value)
    return floor + 1.0 if value - floor >= 0.5 else float(floor)


def round_to(value: float, places: int) -> float:
    """``Math.round(value * 10**places) / 10**places`` (scores use 2 places)."""
    factor = 10.0 ** places
    return js_round(value * factor) / factor


def round_score(value: float) -> float:
    """Scores are rounded to 2 decimals before any comparison (§4.12 determinism)."""
    return round_to(value, 2)


def round_to_quarter(value: float) -> float:
    return js_round(value * 4.0) / 4.0


def ceil_to_quarter(value: float) -> float:
    """Round up to the next ¼ serving (a low is never under-treated). Float noise is ignored."""
    quarters = value * 4.0
    nearest = js_round(quarters)
    if abs(quarters - nearest) < 1e-9:
        return nearest / 4.0
    return math.ceil(quarters) / 4.0


def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


# --------------------------------------------------------------------------- #
# Names, roles, eligibility
# --------------------------------------------------------------------------- #


def family_of(name: str | None) -> str:
    """First word of the name, case-folded, letters and digits only ("Rice, white" → "rice")."""
    word: list[str] = []
    for ch in (name or "").strip().casefold():
        if ch.isalnum():
            word.append(ch)
        elif word:
            break
    return "".join(word)


def role_of(category: str | None, carbs: float | None, protein: float | None, override: str | None = None) -> str:
    """The guidance role of a food (§4.3) from one serving's carbohydrate and protein.

    ``override`` is the curated ``role`` of a builtin food in ``data/foods.json`` (coleslaw is a
    vegetable side, not an "extra"); an unknown override value is ignored.
    """
    if override in ROLES:
        return str(override)
    cat = category or ""
    c = carbs or 0.0
    pr = protein or 0.0
    if cat in ("Meat, Poultry & Eggs", "Fish & Seafood"):
        return "protein"
    if cat == "Prepared & Fast Food" and pr >= PROTEIN_ROLE_MIN_G and c >= STARCH_ROLE_MIN_CARBS_G:
        return "mixed"
    if cat in ("Dairy & Alternatives", "Legumes, Nuts & Seeds", "Prepared & Fast Food") and pr >= PROTEIN_ROLE_MIN_G:
        return "protein"
    if cat == "Grains & Breads":
        return "starch"
    if cat in (VEGETABLES, "Legumes, Nuts & Seeds", "Prepared & Fast Food") and c >= STARCH_ROLE_MIN_CARBS_G:
        return "starch"
    if cat in (VEGETABLES, "Fruits"):
        return "veg_fruit"
    if cat == BEVERAGES:
        return "drink"
    return "extra"


def group_of(role: str) -> str:
    return GROUP_OF_ROLE.get(role, "extra")


def portions_for(role: str) -> tuple[float, ...]:
    """Portions tried by "what fits now": main roles 1, ½, 1½, 2; drinks and extras 1, ½ (§4.3)."""
    return PORTIONS_MAIN if role in MAIN_PORTION_ROLES else PORTIONS_SIDE


# js_round(v) > H  ⇔  v ≥ H + 0.5 and js_round(v) ≥ M  ⇔  v ≥ M − 0.5 for integer thresholds (the
# fractional part of a double near H is exact), so the hot path compares against these cuts.
RENAL_HIGH_CUT: dict[str, float] = {k: v + 0.5 for k, v in RENAL_HIGH.items()}
RENAL_MEDIUM_CUT: dict[str, float] = {k: v - 0.5 for k, v in RENAL_MEDIUM.items()}


def text_has_any(text: str, stems: Iterable[str]) -> bool:
    folded = (text or "").casefold()
    return any(stem in folded for stem in stems)


def target_max(target: Any) -> float | None:
    """The max side of a target (number or ``{min, max}``); ``None`` when untracked, not finite or ≤ 0."""
    if target is None or isinstance(target, bool):
        return None
    hi = target.get("max") if isinstance(target, Mapping) else target
    try:
        value = float(hi) if hi is not None else None
    except (TypeError, ValueError):
        return None
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value


def target_min(target: Any) -> float | None:
    """The ``min`` side of a ``{min, max}`` target; ``None`` otherwise."""
    if not isinstance(target, Mapping):
        return None
    lo = target.get("min")
    try:
        value = float(lo) if lo is not None and not isinstance(lo, bool) else None
    except (TypeError, ValueError):
        return None
    if value is None or not math.isfinite(value) or value < 0:
        return None
    return value


def rules_table() -> dict[str, Any]:
    """Every number of the engine as plain JSON (``GET /api/guidance/rules``, ``docs/guidance.md``)."""
    return {
        "MEAL_WEIGHT": dict(MEAL_WEIGHT),
        "MEAL_CAP_FRACTION": dict(MEAL_CAP_FRACTION),
        "CAP_KEYS": list(CAP_KEYS),
        "NEGLIGIBLE": dict(NEGLIGIBLE),
        "USAGE_WEIGHT": dict(USAGE_WEIGHT),
        "USAGE_WEIGHT_P_NOT_OK": USAGE_WEIGHT_P_NOT_OK,
        "PORTIONS_MAIN": list(PORTIONS_MAIN),
        "PORTIONS_SIDE": list(PORTIONS_SIDE),
        "WEEK_LOOKBACK_DAYS": WEEK_LOOKBACK_DAYS,
        "WEEK_CLAMP": list(WEEK_CLAMP),
        "CARB_TOLERANCE_G": CARB_TOLERANCE_G,
        "CARB_TOLERANCE_RANGE": list(CARB_TOLERANCE_RANGE),
        "SNACK_CARB_GOAL": "targets.carbs_per_snack_g, else max(15, 5 × round(carbs_per_meal_g / 2 / 5))",
        "HYPO_DOSE_G": HYPO_DOSE_G,
        "HYPO_DOSE_RANGE": list(HYPO_DOSE_RANGE),
        "HIGH_K_ENTRY_MG": HIGH_K_ENTRY_MG,
        "PROTEIN_ROLE_MIN_G": PROTEIN_ROLE_MIN_G,
        "STARCH_ROLE_MIN_CARBS_G": STARCH_ROLE_MIN_CARBS_G,
        "P_PER_G_PROTEIN": {"good_max": P_PER_G_PROTEIN[0], "poor_min": P_PER_G_PROTEIN[1]},
        "K_PER_G_PROTEIN": {"good_max": K_PER_G_PROTEIN[0], "poor_min": K_PER_G_PROTEIN[1]},
        "PROTEIN_AIM_FLOOR_G": PROTEIN_AIM_FLOOR_G,
        "MIN_SHOW_SCORE": MIN_SHOW_SCORE,
        "GROUP_LIMITS": dict(GROUP_LIMITS),
        "CATEGORY_LIMIT": CATEGORY_LIMIT,
        "DEFAULT_LIMIT": DEFAULT_LIMIT,
        "MAX_LIMIT": MAX_LIMIT,
        "BEAM_WIDTH": BEAM_WIDTH,
        "PER_ROLE": PER_ROLE,
        "POOL_PER_ROLE": POOL_PER_ROLE,
        "FAMILIAR_MARGIN": FAMILIAR_MARGIN,
        "SLOT_HABIT_BONUS": SLOT_HABIT_BONUS,
        "SLOT_HABIT_MIN_DAYS": SLOT_HABIT_MIN_DAYS,
        "HISTORY_DAYS": HISTORY_DAYS,
        "USUAL_HISTORY_DAYS": USUAL_HISTORY_DAYS,
        "SWAP_MIN_REDUCTION": SWAP_MIN_REDUCTION,
        "SWAP_CARB_MATCH": {"min_g": SWAP_CARB_MATCH[0], "fraction": SWAP_CARB_MATCH[1]},
        "SWAP_PROTEIN_MATCH": {"min_g": SWAP_PROTEIN_MATCH[0], "fraction": SWAP_PROTEIN_MATCH[1]},
        "SWAP_MAX": SWAP_MAX,
        "PORTION_RANGE": [PORTION_MIN, PORTION_MAX],
        "PORTION_OPTION_FRACTIONS": list(PORTION_OPTION_FRACTIONS),
        "INSIGHT_MAX": INSIGHT_MAX,
        "SOURCE_MIN_SHARE": SOURCE_MIN_SHARE,
        "MIN_LOGGED_DAYS": MIN_LOGGED_DAYS,
        "PERIOD_MAX_DAYS": PERIOD_MAX_DAYS,
        "SAVED_MEAL_SCALES": list(SAVED_MEAL_SCALES),
        "ENERGY_NOTE_FRACTION": ENERGY_NOTE_FRACTION,
        "ENERGY_LOW_INSIGHT_FRACTION": ENERGY_LOW_INSIGHT_FRACTION,
        "RENAL_MEDIUM": dict(RENAL_MEDIUM),
        "RENAL_HIGH": dict(RENAL_HIGH),
    }


def rules_hash() -> str:
    """A short hash of :data:`RULES_VERSION` and every number (the AI layer's cache key, note 06 §4.13)."""
    blob = json.dumps({"version": RULES_VERSION, "rules": rules_table()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
