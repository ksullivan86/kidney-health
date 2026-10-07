"""(b) Swap ideas and low-treatment options (note 06 §4.6; note 04 G7). Pure.

A swap keeps the person's arithmetic: the same carbohydrate (or protein) within a tolerance, and at
least 25 % less of every nutrient that triggered it, without creating a new problem. Three modes:

* ``normal``: the portion is "high" per serving, over the meal's room, or has phosphate additives;
* ``hypo``: the entry treats a low. Only other low treatments are offered, at **at least** the
  person's low-treatment amount (rounded up, never down), ranked by potassium. Nothing here limits,
  delays or shrinks a treatment, and there is never a smaller-portion option;
* ``avoid``: an ``avoid_ckd`` food (star fruit): the flag is the trigger.

:func:`hypo_options` lists the person's low-treatment foods at the dose portion, never filtered by
any budget (§4.6), with the rule-based "Treating a low" card.
"""
from __future__ import annotations

from typing import Any, Sequence

from ..nutrients import round_nutrients, round_value
from . import messages as M
from . import rules as R
from . import topics as T
from .budget import Room, day_totals, meal_room
from .fits import food_core, scaled
from .score import habit_stats, static_term, today_stats
from .state import GuidanceContext
from .vectors import FoodVec, is_high, renal_level

_RENAL_SWAP_SCORE = {"green": 1.5, "yellow": 0.5, "red": -1.5}


def resolve_mode(food: FoodVec, purpose: str | None) -> str:
    """``purpose`` is the entry's purpose or the request's (``hypo`` | ``none``); see ``api.swaps``."""
    if purpose == "hypo":
        return "hypo"
    if food.avoid:
        return "avoid"
    return "normal"


def _amounts(f: FoodVec, q: float) -> dict[str, float | None]:
    return scaled(f, q)


def triggers_for(food: FoodVec, q: float, room: Room, mode: str) -> list[dict[str, Any]]:
    """The nutrients a swap must lower, each with why (``high_per_portion``, ``over_meal_room``,
    ``phosphate_additive``, ``avoid_ckd``, ``potassium_in_treatment``)."""
    a = _amounts(food, q)
    out: list[dict[str, Any]] = []
    if mode == "hypo":
        k = a[R.K]
        if k is not None and k > R.HYPO_SWAP_TRIGGER_MG:
            out.append({"nutrient": R.K, "reasons": ["potassium_in_treatment"], "value": round_value(R.K, k), "room": None})
        return out
    if mode == "avoid":
        return [{"nutrient": "avoid_ckd", "reasons": ["avoid_ckd"], "value": None, "room": None}]
    for key in (R.K, R.P, R.NA, R.FLUID):
        v = a[key]
        reasons: list[str] = []
        if key != R.FLUID and is_high(key, v):
            reasons.append("high_per_portion")
        if key == R.P and food.additive:
            reasons.append("phosphate_additive")
        item = room.nutrients.get(key)
        if item is not None and v is not None and v > item.room + R.NEGLIGIBLE[key]:
            reasons.append("over_meal_room")
        if reasons:
            out.append({"nutrient": key, "reasons": reasons, "value": round_value(key, v),
                        "room": None if item is None else round_value(key, item.room)})
    return out


def match_dimension(food: FoodVec, q: float, mode: str, dose_g: float) -> tuple[str, float]:
    """``(carbs | protein | serving, target amount)`` (§4.6 "Matching dimension")."""
    carbs = (food.carbs or 0.0) * q
    protein = (food.protein or 0.0) * q
    if mode == "hypo":
        return "carbs", max(carbs, float(dose_g))
    if carbs >= R.SWAP_MATCH_CARBS_MIN_G:
        return "carbs", carbs
    if protein >= R.SWAP_MATCH_PROTEIN_MIN_G:
        return "protein", protein
    return "serving", 1.0


def candidate_portion(cand: FoodVec, match: str, target: float, mode: str) -> float | None:
    """The candidate's portion that matches ``target`` (¼ servings, 0.25–3), or ``None``.

    For a low (``mode == "hypo"``) the portion is rounded **up** so it gives at least ``target`` grams of
    carbohydrate: to the next ¼ serving, or to whole servings when one serving is one counted item
    ("1 tablet"), and up to :data:`~app.guidance.rules.HYPO_PORTION_MAX` servings."""
    if match == "serving":
        return 1.0
    per = cand.carbs if match == "carbs" else cand.protein
    if per is None or per <= 0:
        return None
    if mode == "hypo":
        step = R.hypo_portion_step(cand.serving_desc)
        q = max(step, R.ceil_to_step(target / per, step))
        if q > R.HYPO_PORTION_MAX or q * per < target - 1e-9:
            return None  # cannot reach the treatment amount: never under-treat
        return q
    q = R.clamp(R.round_to_quarter(target / per), R.PORTION_MIN, R.PORTION_MAX)
    tol_min, tol_frac = R.SWAP_CARB_MATCH if match == "carbs" else R.SWAP_PROTEIN_MATCH
    if abs(q * per - target) > max(tol_min, tol_frac * target):
        return None
    return q


def _fits_room(a: dict[str, float | None], room: Room) -> bool:
    for key, item in room.nutrients.items():
        v = a.get(key)
        if v is not None and v > item.room + R.NEGLIGIBLE[key]:
            return False
    return True


def _eligible_swap(f: FoodVec, original: FoodVec, ctx: GuidanceContext, mode: str) -> bool:
    if f.id == original.id or f.hidden or f.avoid or f.id in ctx.prefs.exclude_food_ids:
        return False
    if (f.category or "") in ctx.prefs.exclude_categories:
        return False
    if mode == "hypo":
        return f.hypo
    if f.ingredient or f.alcohol or f.supplies:
        return False
    if f.hypo and not original.beverage:
        return False
    if mode == "avoid":  # every same-category food is a candidate (§4.6)
        return f.category == original.category
    return (f.category == original.category) or (f.role == original.role)


def find_swaps(ctx: GuidanceContext, meal: str, food: FoodVec, servings: float, purpose: str | None = None,
               limit: int = R.SWAP_MAX, explain: bool = False) -> dict[str, Any]:
    """Swap ideas for ``food`` × ``servings`` in ``meal`` (``ctx.day`` must not contain the entry itself).

    ``explain`` adds ``explain.rejected``: how many foods each rule turned away (``not_eligible``,
    ``no_matching_portion``, ``not_lower``, ``phosphate_additive``, ``new_problem``) and how many passed.
    """
    mode = resolve_mode(food, purpose)
    totals = day_totals(ctx.day)
    room = meal_room(ctx, meal, totals=totals)
    orig = _amounts(food, servings)
    triggers = triggers_for(food, servings, room, mode)
    base: dict[str, Any] = {
        "status": "ok",
        "rules_version": R.RULES_VERSION,
        "date": ctx.date,
        "meal": meal,
        "mode": mode,
        "food": {"food_id": food.id, "name": food.name, "servings": servings, "serving_desc": food.serving_desc,
                 "nutrients": round_nutrients(orig)},
        "triggers": triggers,
        "match": None,
        "swaps": [],
        "portion_option": None,
        "tips": [],
        "widened": False,
        "notes": [M.DISCLAIMER],
    }
    dose = float(ctx.prefs.hypo_dose_g)
    if mode == "hypo":
        base["card"] = M.treating_a_low_card(dose)
        base["tips"].append(T.tip_json(T.HYPO_TIP, dose=M.fmt_g(dose)))
    if not triggers:
        base["reason"] = "no_warning"
        return base
    match, target = match_dimension(food, servings, mode, dose)
    base["match"] = match
    trigger_keys = [t["nutrient"] for t in triggers if t["nutrient"] in R.ROOM_KEYS]
    p_trigger = R.P in trigger_keys
    orig_high = {k: is_high(k, orig[k]) or (k == R.P and food.additive) for k in R.RENAL_KEYS}
    habit = habit_stats(ctx)
    today = today_stats(ctx.day)
    weights = dict(R.USAGE_WEIGHT)
    weights.update(room.usage_weight)
    found: list[tuple[tuple, tuple]] = []
    rejected = {"not_eligible": 0, "no_matching_portion": 0, "not_lower": 0, "phosphate_additive": 0, "new_problem": 0}
    for cand in ctx.foods.values():
        if not _eligible_swap(cand, food, ctx, mode):
            rejected["not_eligible"] += 1
            continue
        q = candidate_portion(cand, match, target, mode)
        if q is None:
            rejected["no_matching_portion"] += 1
            continue
        new = _amounts(cand, q)
        ok = True
        reduction = 0.0
        for key in trigger_keys:
            o, n = orig[key], new[key]
            if n is None or o is None or o <= 0 or n > (1.0 - R.SWAP_MIN_REDUCTION) * o + 1e-9:
                ok = False
                break
            reduction += weights.get(key, 1.0) * (o - n) / o
        if not ok:
            rejected["not_lower"] += 1
            continue
        if p_trigger and cand.additive:
            rejected["phosphate_additive"] += 1
            continue
        if mode != "hypo":
            # A swap must not create a new problem: a nutrient over the room where the original was lower,
            # an unknown value while that nutrient is not ok today, or a new "high" portion.
            for key, item in room.nutrients.items():
                n, o = new.get(key), orig.get(key)
                if n is not None and n > item.room + R.NEGLIGIBLE[key] and (o is None or n > o):
                    ok = False
                    break
            if ok:
                for key in R.RENAL_KEYS:
                    if new[key] is None and room.level_of(key) != "ok":
                        ok = False
                        break
                    high = is_high(key, new[key]) or (key == R.P and cand.additive)
                    if high and not orig_high[key]:
                        ok = False
                        break
            if not ok:
                rejected["new_problem"] += 1
                continue
        level = renal_level(new[R.K], new[R.P], new[R.NA], cand.additive)
        same_category = cand.category == food.category
        same_family = bool(cand.family) and cand.family == food.family
        fits = _fits_room(new, room)
        carb_diff = abs((new[R.CARBS] or 0.0) - (orig[R.CARBS] or 0.0))
        score = (reduction + _RENAL_SWAP_SCORE[level] + (1.0 if same_category else 0.0)
                 + (1.0 if same_family else 0.0) + (1.0 if fits else 0.0)
                 + min(1.0, max(0.0, static_term(cand, habit, today))) - (1.0 if cand.processed else 0.0)
                 - 0.1 * carb_diff)
        score = R.round_score(score)
        k_amount = new[R.K] if new[R.K] is not None else float("inf")
        if mode == "hypo":
            p_amount = new[R.P] if new[R.P] is not None else float("inf")
            fl = (new[R.FLUID] or 0.0) if R.FLUID in room.nutrients else 0.0
            key_ = (k_amount, p_amount, fl, cand.name_fold, cand.id)
        else:
            key_ = (-score, k_amount, cand.name_fold, cand.id)
        found.append((key_, (cand, q, new, same_category, fits, score)))
    found.sort(key=lambda pair: pair[0])
    # Warnings and texts only for the swaps that are returned (§4.12: never in the hot loop).
    swaps: list[dict[str, Any]] = []
    for _, (cand, q, new, same_category, fits, score) in found[:limit]:
        item = food_core(cand, q)
        deltas = {k: round_value(k, (new[k] or 0.0) - (orig[k] or 0.0)) for k in (R.CARBS, R.K, R.P, R.NA)}
        if mode == "hypo":
            text = M.swap_hypo_text(cand.name, q, cand.serving_desc, new[R.CARBS] or 0.0, new[R.K])
        elif mode == "avoid":
            text = M.swap_avoid_text(cand.name, q, cand.serving_desc, new, food.name)
        else:
            text = M.swap_text(match, cand.name, q, cand.serving_desc, new, orig,
                               {k: (new[k] or 0.0) - (orig[k] or 0.0) for k in trigger_keys}, trigger_keys)
        item.update({"same_category": same_category, "fits_meal": fits, "score": score, "deltas": deltas, "text": text})
        swaps.append(item)
    base["swaps"] = swaps
    base["widened"] = any(not s["same_category"] for s in swaps)
    if mode == "normal":
        base["portion_option"] = portion_option(food, servings, room, triggers)
        if p_trigger and food.additive:
            base["tips"].append(T.tip_json(T.ADDITIVES_TIP))
        if (R.K in trigger_keys and food.category == R.VEGETABLES
                and R.text_has_any(food.name, R.LEACHING_STEMS)):
            base["tips"].insert(0, T.tip_json(T.LEACHING_TIP))
    if not swaps:
        base["reason"] = "no_swap_found"
    if explain:
        base["explain"] = {"rejected": rejected, "passed": len(found)}
    return base


def portion_option(food: FoodVec, servings: float, room: Room, triggers: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """A smaller portion of the same food (§4.6 fallback): ¾ when it removes every trigger (within
    the meal's room and no longer "high"); otherwise ½ when it fits the room (it halves the amount
    even if a "high" portion stays "high"). A phosphate-additive trigger cannot be cleared by a
    smaller portion, so such foods get none."""
    if any("phosphate_additive" in t["reasons"] for t in triggers):
        return None
    keys = [t["nutrient"] for t in triggers if t["nutrient"] in R.ROOM_KEYS]
    for fraction in R.PORTION_OPTION_FRACTIONS:
        q = servings * fraction
        a = _amounts(food, q)
        if not _fits_room(a, room):
            continue
        clears = all(not (k != R.FLUID and is_high(k, a[k])) for k in keys)
        if fraction == 0.75 and not clears:
            continue
        return {
            "servings": q,
            "fraction": fraction,
            "fits_meal": True,
            "nutrients": round_nutrients(a),
            "text": M.portion_option_text(fraction, a[R.CARBS] or 0.0, a, [k for k in keys if k != R.FLUID] or [R.K]),
        }
    return None


def hypo_options(ctx: GuidanceContext) -> dict[str, Any]:
    """The person's low-treatment foods at the amount that treats a low (``hypo_dose_g`` rounded up
    to ¼ serving, or to whole items such as tablets), lowest potassium first. Never filtered by a budget or a target (§4.6)."""
    dose = float(ctx.prefs.hypo_dose_g)
    fluid_tracked = R.target_max(ctx.profile.targets.get(R.FLUID)) is not None
    rows: list[tuple[tuple, dict[str, Any]]] = []
    for f in ctx.foods.values():
        if not f.hypo or f.hidden or f.avoid or f.id in ctx.prefs.exclude_food_ids:
            continue
        if (f.category or "") in ctx.prefs.exclude_categories:
            continue
        q = candidate_portion(f, "carbs", dose, "hypo")
        if q is None:
            continue
        a = _amounts(f, q)
        item = food_core(f, q)
        item["text"] = M.swap_hypo_text(f.name, q, f.serving_desc, a[R.CARBS] or 0.0, a[R.K])
        k = a[R.K] if a[R.K] is not None else float("inf")
        p = a[R.P] if a[R.P] is not None else float("inf")
        fl = (a[R.FLUID] or 0.0) if fluid_tracked else 0.0
        rows.append(((k, p, fl, f.name_fold, f.id), item))
    rows.sort(key=lambda pair: pair[0])
    return {
        "status": "ok",
        "rules_version": R.RULES_VERSION,
        "dose_g": round_value(R.CARBS, dose),
        "options": [item for _, item in rows],
        "card": M.treating_a_low_card(dose),
        "notes": [M.DISCLAIMER],
    }
