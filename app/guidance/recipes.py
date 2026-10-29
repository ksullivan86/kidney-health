"""Recipes that fit (note 16 §9): check one serving of a recipe against a meal's room or what is left today, and if it does not
fit, lower amounts, swap a food or suggest a smaller serving, listing every change.

Pure: no database, no clock, no randomness; every sort ends in the food id. A recipe is its items as pot amounts (servings of each
food in the whole recipe) and ``servings_made``. One serving's **share** of a food is its pot amount ÷ ``servings_made`` × the serving
fraction. The order, in one line: lower amounts, then swap, then a smaller serving, and stop at the first that fits.

* Lowering never touches a protein food (it would cut protein silently) or a low-treatment food, and never goes below
  :data:`~app.guidance.rules.RECIPE_FLOOR` of the recipe's own amount.
* A swap never takes out or brings in a low-treatment food. It keeps the swap engine's rules: same category or role, no
  ingredient, alcohol or supply, nothing "Not for me", 25 % less of the nutrient that is over, carbohydrate or protein kept close.
* ``check_meal`` kind ``recipe`` is the one gate (:func:`app.guidance.score.check_meal`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Sequence

from . import messages as M
from . import rules as R
from .budget import INF, Room, meal_room, open_slots
from .fits import tracked_keys
from .score import MealItem, check_meal, habit_stats, is_high, meal_totals
from .state import GuidanceContext
from .swaps import _eligible_swap
from .vectors import FoodVec
from ..nutrients import round_value

SHOWN_KEYS: tuple[str, ...] = (R.K, R.P, R.NA, R.FLUID, R.CARBS, R.PROTEIN, R.KCAL)
_LOWERABLE = ("would_exceed", "high_warning", "too_many_carbs", "high_portion_too_large", "portion_out_of_range")


@dataclass(frozen=True)
class Target:
    kind: str  # "meal" | "day"
    meal: str | None = None


@dataclass
class Item:
    food: FoodVec
    amount: float  # pot amount, in servings of the food
    original: float
    swapped_from: FoodVec | None = None
    because: str | None = None  # why it was lowered: a nutrient key, or "portion"

    @property
    def floor(self) -> float:
        return max(R.PORTION_MIN, R.ceil_to_step(R.RECIPE_FLOOR * self.original, R.REPAIR_STEP))


# --------------------------------------------------------------------------- #
# Targets and rooms
# --------------------------------------------------------------------------- #


def next_open_meal(ctx: GuidanceContext) -> str:
    """The first main meal of the day with nothing logged, else the snack slot."""
    used = {e.meal for e in ctx.day}
    for meal in R.MAIN_MEALS:
        if meal not in used:
            return meal
    return R.SNACK


def day_room(ctx: GuidanceContext) -> Room:
    """One serving against what is left today (note 16 §9.1): for each tracked nutrient ``max(0, allowance − projected)``, with no
    per-meal cap, no fair share and no carbohydrate check (the carbohydrate goal belongs to a meal)."""
    base = meal_room(ctx, R.MAIN_MEALS[-1], open_meals=[R.MAIN_MEALS[-1]])
    nutrients = {key: replace(item, share=max(0.0, item.remaining), cap=INF, in_meal=0.0, room=max(0.0, item.remaining))
                 for key, item in base.nutrients.items()}
    return replace(base, meal="day", open_meals=(), nutrients=nutrients, carbs=None)


def room_for(ctx: GuidanceContext, target: Target) -> Room:
    if target.kind == "day":
        return day_room(ctx)
    meal = target.meal or next_open_meal(ctx)
    return meal_room(ctx, meal, open_meals=open_slots(meal, ctx.day))


# --------------------------------------------------------------------------- #
# Shares, checks and figures
# --------------------------------------------------------------------------- #


def shares(items: Sequence[Item], n: float, fraction: float = 1.0) -> list[MealItem]:
    return [(i.food, i.amount / n * fraction) for i in items]


def check(items: Sequence[Item], n: float, room: Room, fraction: float = 1.0):
    return check_meal(shares(items, n, fraction), room, kind="recipe")


def _value(f: FoodVec, key: str) -> float | None:
    return {R.K: f.k, R.P: f.p, R.NA: f.na, R.FLUID: f.fluid, R.CARBS: f.carbs, R.PROTEIN: f.protein, R.KCAL: f.kcal}[key]


def figures(items: Sequence[Item], n: float, room: Room, fraction: float = 1.0) -> dict[str, Any]:
    """One serving's figures: ``per_serving`` (a nutrient no food lists is ``None``), ``unknown`` (how many foods do not list it)
    and ``checks`` against the room."""
    part = shares(items, n, fraction)
    totals, _ = meal_totals(part)
    unknown: dict[str, int] = {}
    for f, _q in part:
        for key in SHOWN_KEYS:
            if _value(f, key) is None:
                unknown[key] = unknown.get(key, 0) + 1
    per = {key: (None if part and unknown.get(key, 0) >= len(part) else round_value(key, totals[key])) for key in SHOWN_KEYS}
    checks = []
    for key in tracked_keys(room):
        item = room.nutrients[key]
        limit = min(item.room + R.NEGLIGIBLE[key], room.day_left.get(key, INF))
        used = totals[key]
        checks.append({"nutrient": key, "used": round_value(key, used), "room": round_value(key, item.room),
                       "ok": used <= limit + 1e-9})
    if room.carbs is not None:
        allowed = max(room.carbs.gap, 0.0) + room.carbs.tolerance
        carbs = totals[R.CARBS]
        checks.append({"nutrient": R.CARBS, "used": round_value(R.CARBS, carbs), "room": round_value(R.CARBS, allowed),
                       "ok": carbs <= 5.0 or carbs <= allowed + 1e-9})
    return {"per_serving": per, "unknown": dict(sorted(unknown.items())), "checks": checks}


# --------------------------------------------------------------------------- #
# The moves
# --------------------------------------------------------------------------- #


def _reason_key(reason: str | None) -> str | None:
    if reason is None or ":" not in reason:
        return R.CARBS if reason == "too_many_carbs" else None
    return reason.split(":", 1)[1]


def _high_share(f: FoodVec, q: float) -> bool:
    return any((v is not None and is_high(key, v * q)) or (key == R.P and f.additive)
               for key, v in ((R.K, f.k), (R.P, f.p), (R.NA, f.na)))


def _contributors(items: Sequence[Item], n: float, reason: str) -> list[int]:
    """Indices of the items behind ``reason``, largest share first (then by food id)."""
    key = _reason_key(reason)
    rows: list[tuple[float, int, int]] = []
    for idx, it in enumerate(items):
        q = it.amount / n
        if reason == "avoid_ckd":
            if it.food.avoid:
                rows.append((0.0, it.food.id, idx))
        elif reason.startswith("unknown:"):
            if _value(it.food, key) is None:  # type: ignore[arg-type]
                rows.append((0.0, it.food.id, idx))
        elif reason in ("high_portion_too_large", "portion_out_of_range"):
            if (reason == "portion_out_of_range" and q > R.PORTION_MAX) or (reason == "high_portion_too_large" and q > 1.0 and _high_share(it.food, q)):
                rows.append((-q, it.food.id, idx))
        elif key is not None:
            v = _value(it.food, key)
            if v is not None and v * q > 0:
                rows.append((-(v * q), it.food.id, idx))
    rows.sort()
    return [idx for _, _, idx in rows]


def _swap_because(reason: str) -> str:
    if reason == "avoid_ckd" or reason.startswith("unknown:"):
        return reason.split(":", 1)[0]
    return _reason_key(reason) or "portion"


def _step_down(q: float) -> float:
    return (math.ceil(4 * q - 1e-9) - 1) / 4


def recipe_swap(ctx: GuidanceContext, item: Item, n: float, reason: str, room: Room) -> tuple[FoodVec, float] | None:
    """The best swap for one ingredient (note 16 §9.4): the swap engine's eligibility, never a low treatment, 25 % less of the
    nutrient behind ``reason`` in one serving, carbohydrate or protein matched on the pot amount, no new problem."""
    food, pot = item.food, item.amount
    key = _reason_key(reason)
    mode = "avoid" if food.avoid else "normal"
    if reason == "too_many_carbs":
        return None  # the swap engine keeps carbohydrate the same, so a swap cannot fix this
    carbs, protein = (food.carbs or 0.0) * pot, (food.protein or 0.0) * pot
    if carbs >= R.SWAP_MATCH_CARBS_MIN_G * n:
        match, target = "carbs", carbs
    elif protein >= R.SWAP_MATCH_PROTEIN_MIN_G * n:
        match, target = "protein", protein
    else:
        match, target = "serving", pot
    orig_share = {k: (None if _value(food, k) is None else _value(food, k) * pot / n) for k in R.RENAL_KEYS}  # type: ignore[operator]
    pref = habit_stats(ctx).pref
    best: tuple[tuple, FoodVec, float] | None = None
    for cand in ctx.foods.values():
        if cand.hypo or not _eligible_swap(cand, food, ctx, mode):
            continue
        if match == "serving":
            q = pot
        else:
            per = cand.carbs if match == "carbs" else cand.protein
            if per is None or per <= 0:
                continue
            q = R.clamp(R.round_to_quarter(target / per), R.PORTION_MIN, R.RECIPE_POT_MAX_SERVINGS)
            tol_min, tol_frac = R.SWAP_CARB_MATCH if match == "carbs" else R.SWAP_PROTEIN_MATCH
            if abs(q * per - target) > max(tol_min, tol_frac * target):
                continue
        share = q / n
        if share > R.PORTION_MAX + 1e-9:
            continue
        new = {k: (None if _value(cand, k) is None else _value(cand, k) * share) for k in R.RENAL_KEYS}  # type: ignore[operator]
        if reason.startswith("unknown:") and _value(cand, key) is None:  # type: ignore[arg-type]
            continue
        if key in R.RENAL_KEYS and not reason.startswith("unknown:"):
            o, v = orig_share[key], new[key]
            if o is None or v is None or o <= 0 or v > (1.0 - R.SWAP_MIN_REDUCTION) * o + 1e-9:
                continue
            if key == R.P and cand.additive:
                continue
        problem = False
        for k in R.RENAL_KEYS:
            if new[k] is None and room.level_of(k) != "ok":
                problem = True
            if is_high(k, new[k]) and not is_high(k, orig_share[k]):
                problem = True
        if problem:
            continue
        score = R.round_score((1.0 if cand.category == food.category else 0.0) + pref.of(cand) - (1.0 if cand.processed else 0.0))
        rank = (-score, new.get(key) if key in new and new.get(key) is not None else 0.0, cand.name_fold, cand.id)
        if best is None or rank < best[0]:
            best = (rank, cand, q)
    return None if best is None else (best[1], best[2])


# --------------------------------------------------------------------------- #
# fit_recipe
# --------------------------------------------------------------------------- #


def fit_recipe(ctx: GuidanceContext, recipe: Sequence[tuple[FoodVec, float]], servings_made: float | None,
               target: Target) -> dict[str, Any]:
    """The answer of ``POST /api/guidance/fit-recipe`` (note 16 §7), without ``rules_version`` and ``target``."""
    room = room_for(ctx, target)
    n = float(servings_made or 1.0)
    items = [Item(food=f, amount=float(q), original=float(q)) for f, q in recipe]
    before = figures(items, n, room)
    if check(items, n, room).ok:
        return _result("fits", before, items, n, 1.0, [], room, target)
    changes: list[dict[str, Any]] = []
    lowered: list[tuple[int, float]] = []  # (index, amount before the step), in order

    # 1. Lower amounts, one ingredient at a time, largest contributor first.
    steps = 0
    while steps < R.RECIPE_MAX_LOWER_STEPS:
        result = check(items, n, room)
        if result.ok or result.reason is None or not result.reason.startswith(_LOWERABLE):
            break
        pick = next((i for i in _contributors(items, n, result.reason)
                     if items[i].food.role != "protein" and not items[i].food.hypo and items[i].amount > items[i].floor + 1e-9), None)
        if pick is None:
            break
        reason = result.reason
        items[pick].because = items[pick].because or _reason_key(reason) or "portion"
        while items[pick].amount > items[pick].floor + 1e-9 and steps < R.RECIPE_MAX_LOWER_STEPS:
            lowered.append((pick, items[pick].amount))
            items[pick].amount = max(items[pick].floor, _step_down(items[pick].amount))
            steps += 1
            if check(items, n, room).reason != reason:
                break

    # 2. Swap, at most RECIPE_MAX_SWAPS times.
    swaps = 0
    while swaps < R.RECIPE_MAX_SWAPS:
        result = check(items, n, room)
        if result.ok or result.reason is None:
            break
        pick = next((i for i in _contributors(items, n, result.reason)
                     if not items[i].food.hypo and items[i].swapped_from is None), None)
        if pick is None:
            break
        found = recipe_swap(ctx, items[pick], n, result.reason, room)
        if found is None:
            break
        old = items[pick]
        items[pick] = Item(food=found[0], amount=found[1], original=found[1], swapped_from=old.food)
        lowered = [(i, q) for i, q in lowered if i != pick]  # the swapped food's lowering cannot be given back
        changes.append({"code": "swapped", "food_id": found[0].id, "from_food_id": old.food.id, "from": old.amount, "to": found[1],
                        "because": _swap_because(result.reason),
                        "_from_food": old.food, "_to_food": found[0]})
        swaps += 1

    # 3. A smaller serving.
    fraction = 1.0
    if not check(items, n, room).ok:
        for g in R.RECIPE_SERVING_FRACTIONS:
            if check(items, n, room, g).ok:
                fraction = g
                break

    if check(items, n, room, fraction).ok:
        # Give back lowering that turned out not to be needed, last first, one quarter at a time.
        while lowered:
            idx, previous = lowered[-1]
            keep = items[idx].amount
            items[idx].amount = previous
            if not check(items, n, room, fraction).ok:
                items[idx].amount = keep
                break
            lowered.pop()
        status = "fits_smaller_serving" if fraction < 1.0 else "fits_after_changes"
        return _result(status, before, items, n, fraction, changes, room, target)
    return _result("does_not_fit", before, items, n, R.RECIPE_SERVING_FRACTIONS[-1], changes, room, target)


def _partial(fig: dict[str, Any], key: str) -> bool:
    """Some food of the serving does not list ``key``, so its figure counts only the others ("at least")."""
    return fig["unknown"].get(key, 0) > 0


def _result(status: str, before: dict[str, Any], items: Sequence[Item], n: float, fraction: float,
            swaps: list[dict[str, Any]], room: Room, target: Target) -> dict[str, Any]:
    after = figures(items, n, room, fraction)
    full = figures(items, n, room) if fraction != 1.0 else after  # a full serving after the changes, for the change lines
    label = M.recipe_target_label(target.kind, room.meal)
    changes: list[dict[str, Any]] = []
    for it in items:
        if it.swapped_from is None and abs(it.amount - it.original) > 1e-9:
            key = it.because or R.K
            changes.append({"code": "lowered", "food_id": it.food.id, "from": it.original, "to": it.amount, "because": key,
                            "text": M.recipe_lowered_text(it.food.name, it.food.serving_desc, it.original, it.amount, key, label,
                                                          before["per_serving"].get(key), full["per_serving"].get(key),
                                                          _partial(before, key), _partial(full, key))})
    for s in swaps:
        key = s["because"]
        changes.append({k: v for k, v in s.items() if not k.startswith("_")} | {
            "text": M.recipe_swapped_text(s["_from_food"].name, s["_to_food"].name, s["_to_food"].serving_desc, s["to"], key, label,
                                          before["per_serving"], full["per_serving"], before["unknown"], full["unknown"])})
    if status == "fits_smaller_serving":
        key = next((c["nutrient"] for c in full["checks"] if not c["ok"]), R.K)
        changes.append({"code": "smaller_serving", "fraction": fraction, "because": key,
                        "text": M.recipe_smaller_text(fraction, key, label, full["per_serving"].get(key), after["per_serving"].get(key),
                                                      next((c["room"] for c in full["checks"] if c["nutrient"] == key), None),
                                                      _partial(full, key))})
    fitted = {
        "items": [{"food_id": it.food.id, "name": it.food.name, "servings": it.amount, "serving_desc": it.food.serving_desc,
                   "portion_text": M.portion_text(it.amount, it.food.serving_desc)} for it in items],
        "serving_fraction": fraction,
        "log_scale": R.round_to(fraction / n, 4),
    }
    out: dict[str, Any] = {
        "status": status,
        "servings_made": n,
        "before": before,
        "after": after if status != "does_not_fit" else None,
        "fitted": fitted if status != "does_not_fit" else None,
        "closest": ({**fitted, "after": after} if status == "does_not_fit" else None),
        "changes": changes,
        "still_over": [c["nutrient"] for c in after["checks"] if not c["ok"]] if status == "does_not_fit" else [],
        "notes": list(M.RECIPE_NOTES) + [M.DISCLAIMER],
    }
    if status == "does_not_fit":
        over = next((c for c in after["checks"] if not c["ok"]), None)
        partial = over is not None and _partial(after, str(over["nutrient"]))
        out["changes"].append({"code": "does_not_fit", "text": M.recipe_no_fit_text(label, over, partial)})
    return out
