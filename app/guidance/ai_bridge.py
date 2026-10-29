"""The contract between the rules engine and the optional AI layer (note 06 §4.13; note 04 R2, R7). Pure.

The AI never sees the database and never decides what fits. ``app/ai/`` (note 04) builds its prompt
context **only** from :func:`candidates_for_ai` and checks every idea **only** with
:func:`validate_ai_items` (one meal) or :func:`validate_ai_plan` (the ``plan`` mode's picks, which
re-runs the whole-day check of §4.7). Low treatments are never candidates and hypo options and
insights are never sent to AI (note 04 G7).

The one stateful piece is the availability hook: the AI layer registers a provider with
:func:`register_ai_status` so ``GET /api/guidance/next-meal`` can say whether "AI order" / "AI
ideas" are on offer (``{"available": bool, "provider_label": str | None}``, note 04 R2). Without
the AI layer the answer is always ``{"available": false, "provider_label": null}``.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Callable, Iterable, Mapping, Sequence

from .. import brand
from . import messages as M
from . import rules as R
from . import topics as T
from .budget import day_totals, meal_room
from .fits import (
    eligible_foods,
    fitting_saved_meals,
    food_core,
    public,
    rank_foods,
    reasons_for,
    room_json,
    scaled,
    totals_json,
    unknown_json,
)
from .planner import plan_day
from .score import Counter, Scorer, check_meal, habit_stats, meal_totals, pref_terms, score_meal, today_stats
from .state import GuidanceContext
from .vectors import FoodVec, is_high, renal_level
from .swaps import find_swaps

log = logging.getLogger(f"{brand.LOGGER_NAME}.guidance")

MODES = ("rerank", "ideas", "swap", "plan")
UNTRUSTED_SOURCES = frozenset({"custom", "off"})  # names typed by a person or a wiki (note 04 §9.2)
AiStatus = dict[str, Any]
AiStatusProvider = Callable[[sqlite3.Connection, int], AiStatus]

_status_provider: AiStatusProvider | None = None


def register_ai_status(provider: AiStatusProvider | None) -> None:
    """Called by ``app/ai/`` at start-up; ``None`` unregisters (tests)."""
    global _status_provider
    _status_provider = provider


def ai_status(conn: sqlite3.Connection, user_id: int) -> AiStatus:
    """``{"available", "provider_label"}`` for the ``ai`` block of next-meal. Never raises: a failing
    provider is logged and reported as unavailable, so guidance always answers (note 04 R1)."""
    unavailable: AiStatus = {"available": False, "provider_label": None}
    if _status_provider is None:
        return unavailable
    try:
        status = _status_provider(conn, user_id)
    except Exception:  # noqa: BLE001 - the rule result must never depend on the AI layer
        log.exception("AI status provider failed; guidance continues without AI")
        return unavailable
    return {"available": bool(status.get("available")), "provider_label": status.get("provider_label")}


def _per_portion(f: FoodVec, q: float) -> dict[str, Any]:
    a = scaled(f, q)
    out = {}
    for key, name in ((R.CARBS, "carbs"), (R.K, "potassium"), (R.P, "phosphorus"), (R.NA, "sodium"),
                      (R.FLUID, "fluid"), (R.PROTEIN, "protein")):
        out[name] = None if a[key] is None else (M.whole(a[key]) if key in (R.K, R.P, R.NA, R.FLUID)
                                                 else R.round_to(a[key], 1))
    return out


def candidates_for_ai(ctx: GuidanceContext, meal: str, mode: str, *, food: FoodVec | None = None,
                      servings: float | None = None, purpose: str | None = None,
                      exclude: frozenset[int] = frozenset()) -> dict[str, Any]:
    """The rule result for ``meal``, trimmed for a prompt (§4.13).

    * ``foods``: up to 40 of the what-fits ranking without the display limit (at least 6 per group
      when available), each ``{ref, food_id, name, untrusted, group, portion, per_portion,
      renal_rating, fit_text, reasons, liked, often, max_quarters}`` (``max_quarters``: the most of
      that food alone the meal check accepts here, :func:`max_quarters`);
    * ``meals``: up to 5 fitting saved or usual meals;
    * ``room``, ``levels``, ``handbook`` (allowed slugs);
    * ``swap`` mode: ``swaps`` (≤ 15 rule swaps that passed) for ``food`` × ``servings``;
    * ``plan`` mode: ``plan`` (≤ 5 options per slot).
    Low-treatment foods are never in the list (note 04 G7). ``exclude`` leaves out foods of ideas already shown ("Other ideas").
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    counter = Counter()
    totals = day_totals(ctx.day)
    room = meal_room(ctx, meal, totals=totals)
    habit = habit_stats(ctx)
    today = today_stats(ctx.day)
    scorer = Scorer(room, habit, today, counter)
    ranked, _ = rank_foods(ctx, room, scorer, [f for f in eligible_foods(ctx) if f.id not in exclude])
    ranked = [pair for pair in ranked if (pair[0].score or 0.0) >= R.MIN_SHOW_SCORE]
    picked: list = []
    per_group: dict[str, int] = {}
    for best, std in ranked:  # first the best few of every group …
        if per_group.get(best.food.group, 0) < R.AI_FOODS_PER_GROUP_MIN:
            picked.append((best, std))
            per_group[best.food.group] = per_group.get(best.food.group, 0) + 1
    for pair in ranked:  # … then the rest in rule order
        if len(picked) >= R.AI_FOODS_MAX:
            break
        if pair not in picked:
            picked.append(pair)
    picked = sorted(picked[: R.AI_FOODS_MAX], key=lambda pair: ranked.index(pair))
    tracked = [k for k in (R.K, R.P, R.NA, R.FLUID) if k in room.nutrients]
    foods = []
    for i, (best, std) in enumerate(picked, start=1):
        f, q = best.food, best.servings
        reasons, _ = reasons_for(best, scorer, room, std, habit)
        codes = [r["code"] for r in reasons]
        a = scaled(f, q)
        foods.append({
            "ref": f"f{i}", "food_id": f.id, "name": M.safe_name(f.name), "untrusted": f.source in UNTRUSTED_SOURCES,
            "group": f.group, "portion": q, "per_portion": _per_portion(f, q),
            "renal_rating": renal_level(a[R.K], a[R.P], a[R.NA], f.additive),
            "fit_text": M.fit_text(a, tracked, room.carbs is not None),
            # "You said you like this" is a taste the person stated, not one of the app's reasons: it stays out of
            # ``reasons`` and travels as its own bit, which the AI layer shows the model and checks its "you_like"
            # claim against. The bit is the person's Like itself, not whether the card had room to show the reason (a
            # card shows at most two, so a food with two kidney reasons would otherwise read as not liked). The
            # ``often`` bit is the same for "You often have this": the habit itself (the rule of the reason, so off for
            # a neutral food and when learning from the log is off), not whether the card showed it.
            "reasons": [c for c in codes if c != "you_like"],
            "liked": f.id in habit.pref.liked,
            "often": habit.days_14.get(f.id, 0) >= R.OFTEN_MIN_DAYS,
            "max_quarters": max_quarters(f, room),
        })
    meals = [public(o) for o in fitting_saved_meals(ctx, meal, room, today, counter, limit=R.AI_MEALS_MAX)]
    for i, m in enumerate(meals, start=1):
        m["ref"] = f"m{i}"
        m["name"] = M.safe_name(m["name"])
    result: dict[str, Any] = {
        "rules_version": R.RULES_VERSION,
        "rules_hash": R.rules_hash(),
        "date": ctx.date,
        "meal": meal,
        "mode": mode,
        "room": room_json(room),
        "levels": {k: v.level for k, v in room.nutrients.items()},
        "foods": foods,
        "meals": meals,
        "handbook": sorted(T.TOPIC_PAGES),
    }
    if mode == "swap":
        if food is None or servings is None:
            raise ValueError("swap mode needs the food and its servings")
        swaps = find_swaps(ctx, meal, food, servings, purpose, limit=R.SWAP_AI_MAX)
        if swaps["mode"] == "hypo":
            raise ValueError("low treatments are never sent to AI (note 04 G7)")
        result["swaps"] = [{"ref": f"s{i}", **{k: s[k] for k in ("food_id", "name", "servings", "renal_rating", "text")}}
                           for i, s in enumerate(swaps["swaps"], start=1)]
        result["triggers"] = swaps["triggers"]
    if mode == "plan":
        plan = plan_day(ctx, with_options=True)
        result["plan"] = {slot: [{"index": i, "source": o["source"], "name": o["name"], "score": o["score"],
                                  "items": [{"food_id": it["food_id"], "name": M.safe_name(it["name"]),
                                             "servings": it["servings"]} for it in o["items"]],
                                  "totals": o["totals"]} for i, o in enumerate(opts)]
                          for slot, opts in plan.get("options", {}).items()}
    return result


def _merge(items: Iterable[Mapping[str, Any]]) -> tuple[list[tuple[int, int]] | None, str | None]:
    merged: dict[int, int] = {}
    order: list[int] = []
    for raw in items:
        try:
            food_id = int(raw["food_id"])
            quarters = int(raw["quarters"])
        except (KeyError, TypeError, ValueError):
            return None, "malformed_item"
        if isinstance(raw.get("quarters"), bool) or isinstance(raw.get("food_id"), bool):
            return None, "malformed_item"
        if food_id not in merged:
            order.append(food_id)
            merged[food_id] = 0
        merged[food_id] += quarters
    return [(fid, merged[fid]) for fid in order], None


#: The meal check's reasons that only mean "a portion is too big": lowering a portion lowers every nutrient, so it can fix
#: these and cannot make anything else fail. ``quarters_out_of_range`` above the top is brought down to it first.
LOWERABLE = ("high_portion_too_large", "would_exceed:", "too_many_carbs", "quarters_out_of_range")
_AMOUNT = {R.K: "k", R.P: "p", R.NA: "na", R.FLUID: "fluid", R.CARBS: "carbs"}


def _not_for_lowering(f: FoodVec, q: float, room: Any) -> bool:
    """Would ``f`` at ``q`` servings fail :func:`check_meal` (kind ``ai``) for a reason a smaller portion must not fix?

    The same tests as the meal check, at the portion the AI proposed: an ``avoid_ckd`` food, a low treatment, an ingredient,
    an alcoholic drink, an unknown value while that nutrient is not ok today (or unknown carbohydrate with a carb goal), or
    a "high" portion of a nutrient that is not ok today. An idea with any of these is dropped as before, never repaired."""
    if f.avoid or f.hypo or f.ingredient or f.alcohol:
        return True
    if room.carbs is not None and f.carbs is None:
        return True
    for key, v in ((R.K, f.k), (R.P, f.p), (R.NA, f.na)):
        if room.level_of(key) == "ok":
            continue
        if v is None or is_high(key, v * q) or (key == R.P and f.additive):
            return True
    return False


def _to_lower(items: Sequence[tuple[FoodVec, int]], reason: str) -> int | None:
    """The item to take one quarter off for ``reason``: the biggest contributor (most quarters for a "high" food over one
    serving), then the most quarters, then the lowest food id. Never a low treatment, never below the smallest portion."""
    lo = R.AI_QUARTERS_RANGE[0]
    rows: list[tuple[float, int, int, int]] = []
    for idx, (f, qt) in enumerate(items):
        if f.hypo or qt <= lo:
            continue
        q = qt / 4.0
        if reason == "high_portion_too_large":
            high = f.additive or any(v is not None and is_high(key, v * q) for key, v in ((R.K, f.k), (R.P, f.p), (R.NA, f.na)))
            if q > 1.0 + 1e-9 and high:
                rows.append((-q, -qt, f.id, idx))
        elif reason == "portion_out_of_range":
            if q > R.PORTION_MAX + 1e-9:
                rows.append((-q, -qt, f.id, idx))
        else:
            key = R.CARBS if reason == "too_many_carbs" else reason.split(":", 1)[1]
            v = getattr(f, _AMOUNT[key]) if key in _AMOUNT else None
            if v is not None and v * q > 0:
                rows.append((-(v * q), -qt, f.id, idx))
    return min(rows)[3] if rows else None


def lower_to_fit(items: Sequence[tuple[FoodVec, int]], room: Any, reason: str) -> list[tuple[FoodVec, int]] | None:
    """An AI idea (``[(food, quarters)]``) that failed :func:`check_meal` with ``reason``, made smaller until it passes, or
    ``None`` when it cannot be repaired.

    Only a portion that is too big is repaired (:data:`LOWERABLE`); an idea that also fails for any other reason at the
    proposed amounts (:func:`_not_for_lowering`) is not. More than 12 quarters is first brought down to 12. Then one quarter
    at a time comes off the item behind the current reason (:func:`_to_lower`), never below one quarter, never off a low
    treatment, and nothing is ever raised. The full meal check decides at the end."""
    lo, hi = R.AI_QUARTERS_RANGE
    if not reason.startswith(LOWERABLE) or any(qt < lo for _, qt in items):
        return None
    if any(_not_for_lowering(f, qt / 4.0, room) for f, qt in items):
        return None
    work = [(f, min(qt, hi)) for f, qt in items]
    for _ in range(sum(qt for _, qt in work)):  # each step takes one quarter off, so this always ends
        check = check_meal([(f, qt / 4.0) for f, qt in work], room, "ai")
        if check.ok:
            return work
        if check.reason is None or not check.reason.startswith((*LOWERABLE, "portion_out_of_range")):
            return None
        pick = _to_lower(work, check.reason)
        if pick is None:
            return None
        f, qt = work[pick]
        work[pick] = (f, qt - 1)
    return work if check_meal([(f, qt / 4.0) for f, qt in work], room, "ai").ok else None


def max_quarters(f: FoodVec, room: Any) -> int:
    """The most quarters of ``f`` (within ``AI_QUARTERS_RANGE``) that pass :func:`check_meal` (kind ``ai``) alone in this
    meal's room, or 0 when not even one quarter does. Every part of the check grows with the portion, so the first amount
    that passes from the top is the answer. Sent to the AI with each candidate, so it is told the limit, not only warned."""
    lo, hi = R.AI_QUARTERS_RANGE
    for qt in range(hi, lo - 1, -1):
        if check_meal([(f, qt / 4.0)], room, "ai").ok:
            return qt
    return 0


def validate_ai_items(ctx: GuidanceContext, meal: str, ideas: Sequence[Sequence[Mapping[str, Any]]],
                      candidate_ids: Iterable[int] | None = None) -> dict[str, Any]:
    """Check AI ideas (``[[{food_id, quarters}, …], …]``) exactly like built meals (§4.13; note 04 V3–V5).

    ``food_id`` must be in the candidate set (default: the ``candidates_for_ai`` foods and saved-meal
    foods of this meal); duplicates are merged; ``1 ≤ quarters ≤ 12`` per item; ≤ 5 items per idea,
    ≤ 3 ideas; then :func:`check_meal` (kind ``ai``) and :func:`score_meal` on the current room.
    Numbers, warnings and texts always come from the rules. An idea that fails only because a portion
    is too big is made smaller (:func:`lower_to_fit`) and kept; ``portions_lowered`` lists those
    (``{index, reason, changes: [{food_id, from_quarters, to_quarters}]}``) and the idea carries its
    ``changes`` too. Other failing ideas are dropped with a reason code (``not_a_candidate``,
    ``quarters_out_of_range``, ``would_exceed:<k>``, ``too_many_carbs``, ``avoid_ckd``, …).
    """
    if candidate_ids is None:
        ctx_c = candidates_for_ai(ctx, meal, "ideas")
        allowed = {f["food_id"] for f in ctx_c["foods"]}
        for m in ctx_c["meals"]:
            allowed |= {it["food_id"] for it in m["items"]}
    else:
        allowed = set(candidate_ids)
    totals = day_totals(ctx.day)
    room = meal_room(ctx, meal, totals=totals)
    today = today_stats(ctx.day)
    pref = pref_terms(ctx)
    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    lowered: list[dict[str, Any]] = []
    lo, hi = R.AI_QUARTERS_RANGE
    for index, idea in enumerate(ideas):
        if index >= 3:
            dropped.append({"index": index, "reason": "too_many_ideas"})
            continue
        merged, error = _merge(idea)
        if error or merged is None:
            dropped.append({"index": index, "reason": error or "malformed_item"})
            continue
        if not merged:
            dropped.append({"index": index, "reason": "empty"})
            continue
        if len(merged) > 5:
            dropped.append({"index": index, "reason": "too_many_items"})
            continue
        reasons = []  # every grounding problem, in item order; only "more than 12 quarters" can be repaired
        for food_id, quarters in merged:
            if food_id not in allowed or food_id not in ctx.foods:
                reasons.append("not_a_candidate")
            elif not lo <= quarters <= hi:
                reasons.append("quarters_out_of_range" if quarters > hi else "quarters_too_small")
        if reasons:
            first = "quarters_out_of_range" if reasons[0] == "quarters_too_small" else reasons[0]
            if set(reasons) != {"quarters_out_of_range"}:
                dropped.append({"index": index, "reason": first})
                continue
        proposed = [(ctx.foods[food_id], quarters) for food_id, quarters in merged]
        if reasons:
            reason: str | None = "quarters_out_of_range"
        else:
            check = check_meal([(f, qt / 4.0) for f, qt in proposed], room, "ai")
            reason = None if check.ok else check.reason
        changes: list[dict[str, int]] = []
        if reason is not None:
            fixed = lower_to_fit(proposed, room, reason)
            if fixed is None:
                dropped.append({"index": index, "reason": reason})
                continue
            changes = [{"food_id": f.id, "from_quarters": was, "to_quarters": now}
                       for (f, was), (_, now) in zip(proposed, fixed) if now != was]
            lowered.append({"index": index, "reason": reason, "changes": changes})
            proposed = fixed
        items = [(f, qt / 4.0) for f, qt in proposed]
        meal_t, meal_u = meal_totals(items)
        out = {
            "index": index,
            "items": [food_core(f, q) for f, q in items],
            "totals": totals_json(meal_t, room),
            "unknown": unknown_json(meal_u, room),
            "score": score_meal(items, room, today, ctx.profile.dialysis != "none", pref=pref),
            "checked": True,
        }
        if changes:
            out["portions_lowered"] = changes
        accepted.append(out)
    note = M.AI_FALLBACK if not accepted else None
    return {"ideas": accepted, "dropped": dropped, "portions_lowered": lowered, "note": note}


def validate_ai_plan(ctx: GuidanceContext, picks: Mapping[str, int], **options: Any) -> dict[str, Any]:
    """The ``plan`` mode: one option index per slot (from ``candidates_for_ai(..., "plan")``); the
    plan is rebuilt with those picks and the whole-day check, repair and protein top-up run again."""
    clean = {slot: int(i) for slot, i in picks.items() if slot in R.SLOT_ORDER and isinstance(i, int)
             and not isinstance(i, bool) and 0 <= i < R.AI_PLAN_OPTIONS_MAX}
    return plan_day(ctx, forced=clean, **options)
