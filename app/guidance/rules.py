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
import re
from functools import lru_cache
from typing import Any, Iterable, Mapping

RULES_VERSION = "2026-10-06.1"

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
HYPO_PORTION_MAX = 10.0  # a low treatment may take up to 10 servings: 8 × 4 g glucose tablets reach the 30 g maximum
# A serving of exactly one of these is counted out whole for a low (no "3¾ glucose tablets").
HYPO_WHOLE_UNITS: tuple[str, ...] = ("tablet", "piece", "candy", "candies", "sweet", "lozenge", "gummy", "gummies",
                                     "chew", "pastille", "mint", "jelly bean", "cube", "sachet", "packet")
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


def ceil_to_step(value: float, step: float) -> float:
    """Round up to the next multiple of ``step`` servings (¼, or 1 for a counted item). Float noise is ignored."""
    units = value / step
    nearest = js_round(units)
    if abs(units - nearest) < 1e-9:
        return nearest * step
    return math.ceil(units) * step


_WHOLE_UNIT = re.compile(
    r"^\s*(?:1|one)\s+(?:[a-z-]+\s+)?(?:" + "|".join(re.escape(u) for u in sorted(HYPO_WHOLE_UNITS, key=len, reverse=True))
    + r")s?\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=4096)
def is_whole_unit_serving(serving_desc: str | None) -> bool:
    """``"1 tablet (4 g)"``, ``"1 glucose tablet"``, ``"1 piece"``: one serving is one item you count out,
    so a low-treatment portion is a whole number of them. ``"3 pieces"`` or ``"1 tube"`` keep ¼ steps."""
    return bool(serving_desc) and _WHOLE_UNIT.match(serving_desc) is not None


def hypo_portion_step(serving_desc: str | None) -> float:
    """The step of a low-treatment portion: 1 serving for a counted item, else ¼ (§4.6)."""
    return 1.0 if is_whole_unit_serving(serving_desc) else 0.25


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


# Every tunable number of the engine with the reason it has that value (note 06 §4.3; F1–F10 are the
# note's findings). ``rules_table()`` serves these through ``GET /api/guidance/rules`` and
# ``scripts/guidance_rules_doc.py`` prints them into docs/guidance.md, so the docs cannot drift.
RULE_DOCS: tuple[tuple[str, str], ...] = (
    ("MEAL_WEIGHT", "Share of the day's remaining room per open slot; reproduces AKF's 600 mg per meal at 2,000 mg (F1)"),
    ("MEAL_CAP_FRACTION", "Per-meal cap as a fraction of the day's target: 0.30 per main meal, 0.15 for all snacks (F1; phosphorus by analogy, F2)"),
    ("CAP_KEYS", "Nutrients with a per-meal cap (fluid has a day allowance only)"),
    ("NEGLIGIBLE", "Amounts that never count against a room; carbs: a \"free\" food has ≤ 5 g (UW Food Choice Lists, F4)"),
    ("USAGE_WEIGHT", "How much using up each room costs in a score; potassium acts fastest (diet guide §2)"),
    ("USAGE_WEIGHT_P_NOT_OK", "Phosphorus weight while this week's phosphorus is not ok"),
    ("PORTIONS_MAIN", "Portions tried for protein, mixed, starch and vegetable/fruit foods (servings)"),
    ("PORTIONS_SIDE", "Portions tried for drinks and extras: never two root beers (F10)"),
    ("PORTIONS_BUILD", "Portions tried when ranking plan-day candidates"),
    ("PORTIONS_BUILD_PROTEIN", "Portions tried for plan-day protein candidates"),
    ("WEEK_LOOKBACK_DAYS", "Previous days that balance week-judged phosphorus (§3.3)"),
    ("WEEK_CLAMP", "Phosphorus allowance today, as a fraction of the daily target, never outside this range (§3.3)"),
    ("CARB_TOLERANCE_G", "Grams either side of the meal carb goal that count as on target (Smart 2009/2012, F4); a personal setting"),
    ("CARB_TOLERANCE_RANGE", "Allowed range of the personal carb tolerance (g)"),
    ("SNACK_CARB_GOAL", "Carb goal of the snack slot (NKF: 1–3 carb choices per snack, F4)"),
    ("SNACK_CARB_MIN_G", "Smallest snack carb goal: one carb choice"),
    ("HYPO_DOSE_G", "Carbs that treat a low (rule of 15, ADA 2026 Rec 6.15, F5); a personal setting from the diabetes team"),
    ("HYPO_DOSE_RANGE", "Allowed range of the personal low-treatment amount (g; 5–10 g on automated insulin delivery)"),
    ("HIGH_K_ENTRY_MG", "A \"high-potassium portion\" (the app's per-serving high); AKF/UW: not several in one day"),
    ("PROTEIN_ROLE_MIN_G", "A protein portion has at least this much protein (NKF: 7 g = 1 oz of meat, F3)"),
    ("STARCH_ROLE_MIN_CARBS_G", "A starch has at least one carb choice"),
    ("P_PER_G_PROTEIN", "Phosphorus per gram of protein: good at or below, poor at or above (Noori 2010, F2)"),
    ("K_PER_G_PROTEIN", "Potassium per gram of protein: good at or below, poor at or above (design choice: chicken breast 8, ground chicken 29)"),
    ("PROTEIN_AIM_FLOOR_G", "Smallest protein aim used in a score (avoids dividing by tiny aims)"),
    ("MIN_SHOW_SCORE", "Foods scoring below this are not shown as \"fits\""),
    ("GROUP_LIMITS", "At most this many suggestions per group"),
    ("CATEGORY_LIMIT", "At most this many suggestions per food category"),
    ("DEFAULT_LIMIT", "Suggestions returned by default"),
    ("MAX_LIMIT", "Most suggestions a request may ask for"),
    ("BEAM_WIDTH", "Partial meals kept at each step of the plan builder (admin: GUIDANCE_BEAM_WIDTH; §3.4)"),
    ("BEAM_WIDTH_RANGE", "Allowed range of the beam width"),
    ("PER_ROLE", "Best candidates per role the plan builder combines"),
    ("POOL_PER_ROLE", "Foods per role pre-ranked for the plan builder (admin: GUIDANCE_POOL_PER_ROLE; F8)"),
    ("POOL_PER_ROLE_RANGE", "Allowed range of the pool size"),
    ("FAMILIAR_MARGIN", "A saved, usual or starter meal wins if it scores at least the best built meal minus this"),
    ("SLOT_HABIT_BONUS", "Bonus for a food eaten in this meal slot on enough recent days (F10: no pasta at breakfast)"),
    ("SLOT_HABIT_MIN_DAYS", "Days in the last 14 a food must have been eaten in the slot for the bonus"),
    ("OFTEN_MIN_DAYS", "Days in the last 14 for \"You often have this\""),
    ("HISTORY_DAYS", "Days of history for habit, variety and the phosphorus week"),
    ("USUAL_HISTORY_DAYS", "Days of history mined for usual meals"),
    ("USUAL_MIN_ITEMS", "Fewest foods in a usual meal"),
    ("USUAL_MAX_ITEMS", "Most foods in a usual meal"),
    ("USUAL_MIN_DATES", "A usual meal was eaten on at least this many dates"),
    ("SWAP_MIN_REDUCTION", "A swap lowers every nutrient that triggered it by at least this fraction"),
    ("SWAP_CARB_MATCH", "A swap's carbs stay within max(min_g, fraction × original): the insulin arithmetic stays the same (F4)"),
    ("SWAP_PROTEIN_MATCH", "A swap matched on protein stays within max(min_g, fraction × original)"),
    ("SWAP_MATCH_CARBS_MIN_G", "Swaps match carbs when the original has at least this much"),
    ("SWAP_MATCH_PROTEIN_MIN_G", "Otherwise they match protein when the original has at least this much"),
    ("SWAP_MAX", "Swap ideas returned"),
    ("SWAP_AI_MAX", "Rule swaps handed to the optional AI layer"),
    ("PORTION_RANGE", "Every planned or swapped portion is between these servings"),
    ("PORTION_MIN", "Smallest portion (servings)"),
    ("PORTION_MAX", "Largest portion (servings)"),
    ("PORTION_OPTION_FRACTIONS", "Smaller-portion fallbacks of a swap request (¾, then ½)"),
    ("HYPO_PORTION_MAX", "Largest low-treatment portion (servings): enough single 4 g glucose tablets for the 30 g maximum dose; never fewer carbs than the dose"),
    ("HYPO_WHOLE_UNITS", "A serving of one of these items (\"1 tablet\") is counted out whole for a low, rounded up"),
    ("HYPO_SWAP_TRIGGER_MG", "In low-treatment mode the only trigger is potassium above this"),
    ("HYPO_INSIGHT_K_MG", "A low treatment above this potassium makes the insight name a lower-potassium choice"),
    ("HYPO_BEST_MAX_K_MG", "… when one of the person's low treatments has at most this much"),
    ("INSIGHT_MAX", "Insights returned"),
    ("SOURCE_MIN_SHARE", "A food is named as a source when it gave at least this share"),
    ("SOURCE_MAX", "Sources listed per insight"),
    ("MIN_LOGGED_DAYS", "Logged days needed for period insights"),
    ("PERIOD_DEFAULT_DAYS", "Default insight period (the days ending yesterday)"),
    ("PERIOD_MAX_DAYS", "Longest insight period"),
    ("PERIOD_CHANGE_MIN", "A change against the previous period is reported from this fraction"),
    ("MEAL_SHARE_MIN", "One meal slot giving at least this share of potassium or sodium is reported"),
    ("PERIOD_HYPO_MIN", "Low treatments in a period from which the diabetes team may want to know"),
    ("SAVED_MEAL_SCALES", "Sizes a saved, usual or starter meal is tried at"),
    ("SAVED_MEALS_MAX", "Fitting saved and usual meals returned"),
    ("AI_FOODS_MAX", "Candidate foods handed to the optional AI layer (note 04 R2)"),
    ("AI_FOODS_PER_GROUP_MIN", "… at least this many per group when available"),
    ("AI_MEALS_MAX", "Saved or usual meals handed to the AI layer"),
    ("AI_PLAN_OPTIONS_MAX", "Options per slot the AI layer may pick from"),
    ("AI_QUARTERS_RANGE", "An AI idea's portion in quarter servings (note 04 V3)"),
    ("ENERGY_NOTE_FRACTION", "A plan below this share of the calorie goal gets the energy note (R2: under-eating)"),
    ("ENERGY_LOW_INSIGHT_FRACTION", "A logged day below this share of the calorie goal gets the eating-enough insight"),
    ("ENERGY_DENSE_MIN_KCAL", "An energy-dense, low-mineral food has at least this many kcal per serving"),
    ("ENERGY_DENSE_MAX", "… and at most these minerals and carbs per serving"),
    ("ENERGY_NOTE_FOODS", "Energy-dense foods named in the note"),
    ("PROTEIN_TOPUP_STEP", "Servings added to a built meal's protein item when the day is below its protein minimum"),
    ("PROTEIN_TOPUP_STEPS", "Most top-up steps per meal"),
    ("REPAIR_STEP", "Servings taken off a built item when the plan would make a day-judged nutrient newly over"),
    ("REPAIR_STEPS", "Most repair steps before the slot is marked partial"),
    ("VARIANT_MAX", "Most \"Show another plan\" variants"),
    ("UNKNOWN_PENALTY", "Score cost of each unknown potassium, phosphorus or sodium value (unknown is never 0, note 03)"),
    ("FREE_FOOD_CARBS_G", "A food with at most this many carbs is free once the meal's carbs are done"),
    ("HIGH_GI_PENALTY_MIN_CARBS_G", "High-glycaemic foods cost a point from one carb choice"),
    ("FILLS_CARBS_MIN_G", "\"Brings the meal to … carbs\" needs at least one carb choice"),
    ("LOW_K_REASON_MG", "\"Low in potassium\" at or below this portion amount"),
    ("LOW_P_REASON_MG", "\"Low in phosphorus\" at or below this portion amount"),
    ("MAX_NAME_CHARS", "Food names in sentences are cut to this length (custom names are untrusted text)"),
    ("RENAL_MEDIUM", "Per-portion \"medium\" thresholds of the renal rating (the app's warnings, ARCHITECTURE)"),
    ("RENAL_HIGH", "Per-portion \"high\" thresholds (above this, rounded to whole mg)"),
)

# Names, keys and labels: structure, not numbers to tune (listed so the drift test sees every constant).
STRUCTURAL: frozenset[str] = frozenset({
    "RULES_VERSION", "MAIN_MEALS", "SNACK", "SLOT_ORDER", "K", "P", "NA", "FLUID", "CARBS", "PROTEIN", "KCAL",
    "ROOM_KEYS", "RENAL_KEYS", "DAY_JUDGED", "INTERDIALYTIC_KEYS", "ROLES", "GROUP_OF_ROLE", "GROUPS", "GROUP_LABEL",
    "CARB_FILL_ROLES", "PROTEIN_ROLES", "STARCH_ROLES", "MAIN_PORTION_ROLES", "MAIN_ROLE_STEPS", "STEP_ROLES",
    "SNACK_ROLES", "INGREDIENT_FLAG", "SUPPLIES_CATEGORY", "BEVERAGES", "VEGETABLES", "LEACHING_STEMS", "SEVERITY_ORDER",
    "NUTRIENT_PRIORITY", "RENAL_HIGH_CUT", "RENAL_MEDIUM_CUT", "RULE_DOCS", "STRUCTURAL",
})

_DERIVED = {"SNACK_CARB_GOAL": "targets.carbs_per_snack_g, else max(15, 5 × round(carbs_per_meal_g / 2 / 5))",
            "PORTION_RANGE": [PORTION_MIN, PORTION_MAX]}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (frozenset, set)):
        return sorted(_plain(v) for v in value)
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def rules_table() -> dict[str, Any]:
    """Every number of the engine as plain JSON, in :data:`RULE_DOCS` order (``GET /api/guidance/rules``)."""
    module = globals()
    return {name: _plain(_DERIVED[name] if name in _DERIVED else module[name]) for name, _ in RULE_DOCS}


def rule_notes() -> dict[str, str]:
    """Why each number has its value (the "Basis" column of docs/guidance.md)."""
    return dict(RULE_DOCS)


def rules_hash() -> str:
    """A short hash of :data:`RULES_VERSION` and every number (the AI layer's cache key, note 06 §4.13)."""
    blob = json.dumps({"version": RULES_VERSION, "rules": rules_table()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
