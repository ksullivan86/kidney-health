"""(a) "What fits now" (note 06 §4.5): foods and saved or usual meals that fit the next meal. Pure.

Hard filters, then a score, then a grouped selection; reasons and texts are built only for the
returned foods. Everything returned is JSON-ready and deterministic (every sort ends in the food id).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from ..nutrients import food_warnings, round_nutrients, round_value
from . import messages as M
from . import rules as R
from . import topics as T
from .budget import INF, DayTotals, Room, day_totals, meal_room
from .score import (
    Counter,
    Evaluation,
    HabitStats,
    MealItem,
    Scorer,
    TodayStats,
    check_meal,
    food_order_key,
    habit_stats,
    meal_totals,
    score_meal,
    today_stats,
)
from .state import GuidanceContext
from .vectors import FoodVec, protein_quality, renal_level


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #


def ineligible_reason(f: FoodVec, ctx: GuidanceContext) -> str | None:
    """Why ``f`` is never a meal suggestion (§4.3), or ``None`` when it may be one: ``hidden``,
    ``avoid_ckd``, ``hypo_treatment`` (low treatments are not food suggestions), ``ingredient``,
    ``diabetes_supplies``, ``not_for_me`` or ``excluded_category`` (the person's choices)."""
    if f.hidden:
        return "hidden"
    if f.avoid:
        return "avoid_ckd"
    if f.hypo:
        return "hypo_treatment"
    if f.ingredient:
        return "ingredient"
    if f.supplies:
        return "diabetes_supplies"
    if f.id in ctx.prefs.exclude_food_ids:
        return "not_for_me"
    if (f.category or "") in ctx.prefs.exclude_categories:
        return "excluded_category"
    return None


def eligible_for_meals(f: FoodVec, ctx: GuidanceContext) -> bool:
    """§4.3: not hidden, not ``avoid_ckd``, not a low treatment, not an ingredient, not a diabetes
    supply, and not something the person marked "Not for me" or a category they never want."""
    return not (
        f.hidden or f.avoid or f.hypo or f.ingredient or f.supplies
        or f.id in ctx.prefs.exclude_food_ids or (f.category or "") in ctx.prefs.exclude_categories
    )


def eligible_foods(ctx: GuidanceContext) -> list[FoodVec]:
    return [f for f in ctx.foods.values() if eligible_for_meals(f, ctx)]


# --------------------------------------------------------------------------- #
# JSON helpers shared with swaps and the planner
# --------------------------------------------------------------------------- #


def scaled(f: FoodVec, q: float) -> dict[str, float | None]:
    return {k: (None if v is None else v * q) for k, v in f.nutrients.items()}


def grams_of(f: FoodVec, q: float) -> float:
    return round_value("carbs_g", f.serving_g * q) or 0.0  # 1 decimal, the app's half-up rounding


def food_core(f: FoodVec, q: float) -> dict[str, Any]:
    """Name, portion and numbers of one food at one portion (what every guidance list shows)."""
    values = scaled(f, q)
    warnings = food_warnings(values, f.flags, f.kidney_notes, scope="in this portion")
    return {
        "food_id": f.id,
        "name": f.name,
        "group": f.group,
        "role": f.role,
        "servings": q,
        "serving_desc": f.serving_desc,
        "grams": grams_of(f, q),
        "portion_text": M.portion_text(q, f.serving_desc),
        "nutrients": round_nutrients(values),
        "warnings": warnings,
        "renal_rating": renal_level(values[R.K], values[R.P], values[R.NA], f.additive),
    }


def tracked_keys(room: Room) -> list[str]:
    return [k for k in (R.K, R.P, R.NA, R.FLUID) if k in room.nutrients]


def room_json(room: Room) -> dict[str, Any]:
    """The ``room`` object of §4.10 (mg and mL whole, grams to 1 decimal, untracked → ``null``)."""
    out: dict[str, Any] = {}
    for key in (R.K, R.P, R.NA, R.FLUID):
        item = room.nutrients.get(key)
        if item is None:
            out[key] = None
            continue
        out[key] = {
            "room": round_value(key, item.room),
            "cap": None if item.cap == INF else round_value(key, item.cap),
            "share": round_value(key, item.share),
            "in_meal": round_value(key, item.in_meal),
            "remaining_today": round_value(key, item.remaining),
            "allowance_today": round_value(key, item.allowance),
            "level": item.level,
            "basis": item.basis,
        }
    if room.carbs is not None:
        c = room.carbs
        out[R.CARBS] = {
            "goal": round_value(R.CARBS, c.goal), "in_meal": round_value(R.CARBS, c.in_meal),
            "gap": round_value(R.CARBS, c.gap), "tolerance": round_value(R.CARBS, c.tolerance),
            "hypo_excluded_g": round_value(R.CARBS, c.hypo_excluded),
        }
    else:
        out[R.CARBS] = None
    if room.protein is not None:
        out[R.PROTEIN] = {"aim": round_value(R.PROTEIN, room.protein.aim),
                          "aim_min": round_value(R.PROTEIN, room.protein.aim_min)}
    else:
        out[R.PROTEIN] = None
    return out


def totals_json(totals: Mapping[str, float], room: Room | None = None) -> dict[str, Any]:
    keys = [R.CARBS, R.PROTEIN, R.K, R.P, R.NA]
    if room is not None and R.FLUID in room.nutrients:
        keys.append(R.FLUID)
    return {k: round_value(k, totals.get(k, 0.0)) for k in keys}


# --------------------------------------------------------------------------- #
# Reasons
# --------------------------------------------------------------------------- #

_REASON_TOPIC = {
    "fills_carbs": "carb-counting", "low_potassium": "potassium", "low_phosphorus": "phosphorus",
    "protein_quality": "protein", "free_food": "carb-counting", "half_portion": "portions",
}
_GROUP_TOPIC = {"protein": "protein", "starch": "carb-counting", "veg_fruit": "potassium", "extra": "portions"}


def reasons_for(ev: Evaluation, scorer: Scorer, room: Room, standard: Evaluation | None, habit: HabitStats) -> tuple[list[dict[str, str]], list[str]]:
    """≤ 2 positive reasons + ≤ 1 caution, in the priority order of §4.5; and their handbook slugs."""
    f, q = ev.food, ev.servings
    meal = room.meal
    amounts = scaled(f, q)
    candidates: list[tuple[str, str, str | None]] = []
    group = f.group
    missing = (
        (f.role in R.PROTEIN_ROLES and not room.meal_has["protein"])
        or (f.role in R.STARCH_ROLES and not room.meal_has["starch"])
        or (f.role == "veg_fruit" and not room.meal_has["veg_fruit"])
    )
    if missing:
        g = "protein" if f.role in R.PROTEIN_ROLES else group
        candidates.append(("adds_missing_group", M.reason_text("adds_missing_group", group=R.GROUP_LABEL[g], meal=meal),
                           _GROUP_TOPIC.get(g)))
    ac = amounts.get(R.CARBS)
    if (room.carbs is not None and ac is not None and room.gap > room.tolerance and f.role in R.CARB_FILL_ROLES
            and ac >= R.FILLS_CARBS_MIN_G):
        after = room.carbs.in_meal + ac
        candidates.append(("fills_carbs", M.reason_text("fills_carbs", meal=meal, after=M.fmt_g(after),
                                                       goal=M.fmt_g(room.carbs.goal)), _REASON_TOPIC["fills_carbs"]))
    ak, ap = amounts.get(R.K), amounts.get(R.P)
    if ak is not None and ak <= R.LOW_K_REASON_MG:
        candidates.append(("low_potassium", M.reason_text("low_potassium", k=M.fmt_int(ak)), _REASON_TOPIC["low_potassium"]))
    if ap is not None and ap <= R.LOW_P_REASON_MG:
        candidates.append(("low_phosphorus", M.reason_text("low_phosphorus", p=M.fmt_int(ap)), _REASON_TOPIC["low_phosphorus"]))
    apr = amounts.get(R.PROTEIN)
    quality = protein_quality(apr, ak, ap)
    if f.role in R.PROTEIN_ROLES and quality["p_grade"] == "good":
        candidates.append(("protein_quality", M.reason_text("protein_quality", protein=M.fmt_g(apr),
                                                           ratio=M.fmt_int(quality["p_per_g"])),
                           _REASON_TOPIC["protein_quality"]))
    if habit.days_14.get(f.id, 0) >= R.OFTEN_MIN_DAYS:
        candidates.append(("you_eat_often", M.reason_text("you_eat_often"), None))
    if room.carbs is not None and ac is not None and room.gap <= room.tolerance and ac <= R.FREE_FOOD_CARBS_G:
        candidates.append(("free_food", M.reason_text("free_food", carbs=M.fmt_g(ac)), _REASON_TOPIC["free_food"]))
    if q == 0.5 and standard is not None and standard.score is None and standard.why_not:
        key = standard.why_not.split(":", 1)[1] if ":" in standard.why_not else R.CARBS
        word = M.NUTRIENT_WORD.get(key, "carbs")
        candidates.append(("half_portion", M.reason_text("half_portion", nutrient=word, meal=meal),
                           _REASON_TOPIC["half_portion"]))
    positive = candidates[:2]
    reasons = [{"code": c, "text": t} for c, t, _ in positive]
    slugs = [s for _, _, s in positive if s]
    if ev.unknown:
        key = ev.unknown[0]
        reasons.append({"code": f"unknown:{key}",
                        "text": M.reason_text("unknown", Nutrient=M.capitalise(M.NUTRIENT_WORD[key]))})
        slugs.append("label-reading")
    seen: list[str] = []
    for s in slugs:
        if s not in seen:
            seen.append(s)
    return reasons, seen


# --------------------------------------------------------------------------- #
# Tips
# --------------------------------------------------------------------------- #


def day_tips(ctx: GuidanceContext, room: Room) -> list[dict[str, Any]]:
    """At most two tips from ``topics.TIPS`` whose condition holds for the day (§4.5)."""
    out: list[dict[str, Any]] = []
    dialysis = ctx.profile.dialysis != "none"
    for tip in T.TIPS:
        values: dict[str, Any] | None = None
        if tip.when == "potassium_not_ok":
            item = room.nutrients.get(R.K)
            if item is not None and item.level != "ok":
                values = {"pct": M.pct(item.projected / item.allowance) if item.allowance > 0 else 100}
        elif tip.when == "phosphorus_week_not_ok":
            item = room.nutrients.get(R.P)
            if item is not None and item.level != "ok":
                values = {"pct": M.pct(item.projected / item.allowance) if item.allowance > 0 else 100}
        elif tip.when == "sodium_caution":
            item = room.nutrients.get(R.NA)
            if item is not None and item.level != "ok":
                values = {"pct": M.pct(item.projected / item.allowance) if item.allowance > 0 else 100}
        elif tip.when == "fluid_caution_dialysis":
            item = room.nutrients.get(R.FLUID)
            if dialysis and item is not None and item.level != "ok":
                values = {"pct": M.pct(item.projected / item.allowance) if item.allowance > 0 else 100}
        elif tip.when == "dialysis_protein_low":
            p = room.protein
            if dialysis and p is not None and p.minimum is not None and p.projected < p.minimum:
                values = {"value": M.fmt_g(p.projected), "min": M.fmt_g(p.minimum)}
        elif tip.when == "meal_carbs_done":
            c = room.carbs
            if c is not None and c.in_meal > 0 and c.gap <= c.tolerance:
                values = {"Meal": M.capitalise(room.meal), "carbs": M.fmt_g(c.in_meal), "goal": M.fmt_g(c.goal)}
        if values is not None:
            out.append(T.tip_json(tip, **values))
        if len(out) >= 2:
            break
    return out


# --------------------------------------------------------------------------- #
# Saved and usual meals
# --------------------------------------------------------------------------- #


def resolve_items(ctx: GuidanceContext, items: Iterable[tuple[int, float]]) -> list[MealItem] | None:
    """``[(FoodVec, servings)]`` or ``None`` when a food is gone (the meal cannot be checked)."""
    out: list[MealItem] = []
    for food_id, servings in items:
        f = ctx.foods.get(food_id)
        if f is None:
            return None
        out.append((f, float(servings)))
    return out


def best_scale(items: Sequence[MealItem], room: Room, kind: str) -> tuple[float | None, str | None]:
    """The first of 1, ¾, ½ that passes :func:`check_meal`; and the reason the full size failed."""
    first_reason: str | None = None
    for scale in R.SAVED_MEAL_SCALES:
        scaled_items = [(f, q * scale) for f, q in items]
        check = check_meal(scaled_items, room, kind)
        if check.ok:
            return scale, first_reason
        if first_reason is None:
            first_reason = check.reason
    return None, first_reason


def familiar_option(ctx: GuidanceContext, room: Room, today: TodayStats, items: Sequence[MealItem], *, kind: str,
                    name: str, template_id: int | None, counter: Counter | None = None,
                    detail: bool = True) -> dict[str, Any] | None:
    """A saved, usual or starter meal at its best scale, scored; ``None`` when no scale fits.

    ``detail=False`` (the planner, which compares many options and shows its own items) leaves out the
    display fields (``items``, ``totals``, ``note``); ``_items`` and ``_k`` (shown potassium) are always set.
    """
    if any(f.avoid for f, _ in items):
        return None
    scale, reason = best_scale(items, room, kind)
    if scale is None:
        return None
    scaled_items = [(f, q * scale) for f, q in items]
    score = score_meal(scaled_items, room, today, ctx.profile.dialysis != "none", scale, counter)
    totals, _ = meal_totals(scaled_items)
    option: dict[str, Any] = {
        "template_id": template_id,
        "name": name,
        "source": kind,
        "scale": scale,
        "score": score,
        "_items": scaled_items,
        "_k": round_value(R.K, totals[R.K]) or 0,
    }
    if not detail:
        return option
    limiting = None
    if reason and reason.startswith("would_exceed:"):
        key = reason.split(":", 1)[1]
        item = room.nutrients.get(key)
        if item is not None:
            limiting = (key, item.room, item.basis)
    goal = room.carbs.goal if room.carbs is not None else None
    option.update({
        "items": [{"food_id": f.id, "name": f.name, "servings": R.round_to(q, 3)} for f, q in scaled_items],
        "totals": totals_json(totals, room),
        "note": M.saved_meal_note(scale, totals[R.CARBS], room.gap, goal, room.meal, limiting),
    })
    return option


def saved_meals_for(ctx: GuidanceContext, meal: str) -> list[tuple[int, str, list[MealItem]]]:
    out: list[tuple[int, str, list[MealItem]]] = []
    for m in ctx.saved_meals:
        if m.meal_hint == meal or (m.meal_hint is None and meal in R.MAIN_MEALS):
            items = resolve_items(ctx, m.items)
            if items:
                out.append((m.id, m.name, items))
    return out


def usual_meals_for(ctx: GuidanceContext, meal: str) -> list[tuple[str, list[MealItem]]]:
    """Usual meals (§4.7 option 2): sets of 2–6 ``(food, servings to ¼)`` eaten together in this slot
    on at least 2 different dates of the last 60 days. Low treatments are not part of a meal."""
    by_day: dict[str, dict[int, float]] = {}
    for h in ctx.history60:
        if h.meal != meal or h.hypo:
            continue
        foods = by_day.setdefault(h.date, {})
        foods[h.food_id] = foods.get(h.food_id, 0.0) + h.servings
    counts: dict[tuple[tuple[int, float], ...], int] = {}
    for foods in by_day.values():
        key = tuple(sorted((fid, R.round_to_quarter(s)) for fid, s in foods.items()))
        if R.USUAL_MIN_ITEMS <= len(key) <= R.USUAL_MAX_ITEMS and all(q > 0 for _, q in key):
            counts[key] = counts.get(key, 0) + 1
    out: list[tuple[str, list[MealItem]]] = []
    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < R.USUAL_MIN_DATES:
            continue
        items = resolve_items(ctx, key)
        if not items or any(f.hidden for f, _ in items):
            continue
        items.sort(key=lambda it: (R.ROLES.index(it[0].role), it[0].name_fold, it[0].id))  # protein, starch, veg…
        names = short_names([f.name for f, _ in items])
        out.append((M.usual_meal_name(meal, names), items))
    return out


def short_names(names: Sequence[str]) -> list[str]:
    """``short_name`` of §4.8 for a list: the text before the first comma, lower-cased, unless two
    entries share that head, then their full names lower-cased (TV-I4)."""
    heads = [M.safe_name(n).split(",", 1)[0].strip().casefold() for n in names]
    out: list[str] = []
    for name, head in zip(names, heads):
        out.append(M.safe_name(name).casefold() if heads.count(head) > 1 else head)
    return out


def fitting_saved_meals(ctx: GuidanceContext, meal: str, room: Room, today: TodayStats,
                        counter: Counter | None = None, limit: int = R.SAVED_MEALS_MAX) -> list[dict[str, Any]]:
    """Saved meals (``meal_hint`` = ``meal``, or none for a main meal) and usual meals that fit."""
    options: list[dict[str, Any]] = []
    for template_id, name, items in saved_meals_for(ctx, meal):
        opt = familiar_option(ctx, room, today, items, kind="saved", name=name, template_id=template_id, counter=counter)
        if opt is not None:
            options.append(opt)
    for name, items in usual_meals_for(ctx, meal):
        opt = familiar_option(ctx, room, today, items, kind="usual", name=name, template_id=None, counter=counter)
        if opt is not None:
            options.append(opt)
    options.sort(key=lambda o: (-o["score"], o["name"].casefold(), o["template_id"] or 0))
    return options[:limit]


def public(option: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in option.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- #
# What fits now
# --------------------------------------------------------------------------- #


def rank_foods(ctx: GuidanceContext, room: Room, scorer: Scorer, foods: Iterable[FoodVec],
               explain: bool = False) -> tuple[list[tuple[Evaluation, Evaluation]], dict[int, str]]:
    """Every eligible food at its best portion, sorted (§4.5 "Ordering"); and ``why_not`` per food
    that no portion passed (the reason at one serving)."""
    ranked: list[tuple[Evaluation, Evaluation]] = []
    why_not: dict[int, str] = {}
    for f in foods:
        best, standard = scorer.best_portion(f, R.portions_for(f.role), explain)
        if best is None:
            why_not[f.id] = standard.why_not or "no_portion"
            continue
        ranked.append((best, standard))
    ranked.sort(key=lambda pair: food_order_key(pair[0]))
    return ranked, why_not


def select(ranked: Sequence[tuple[Evaluation, Evaluation]], limit: int) -> list[tuple[Evaluation, Evaluation]]:
    """Walk the sorted list: stop at the first score below ``MIN_SHOW_SCORE``; respect the group and
    category limits; stop at ``limit``."""
    chosen: list[tuple[Evaluation, Evaluation]] = []
    per_group: dict[str, int] = {}
    per_category: dict[str, int] = {}
    for best, standard in ranked:
        if (best.score or 0.0) < R.MIN_SHOW_SCORE:
            break
        f = best.food
        if per_group.get(f.group, 0) >= R.GROUP_LIMITS.get(f.group, 0):
            continue
        cat = f.category or ""
        if per_category.get(cat, 0) >= R.CATEGORY_LIMIT:
            continue
        chosen.append((best, standard))
        per_group[f.group] = per_group.get(f.group, 0) + 1
        per_category[cat] = per_category.get(cat, 0) + 1
        if len(chosen) >= limit:
            break
    return chosen


def what_fits(ctx: GuidanceContext, meal: str, limit: int = R.DEFAULT_LIMIT, explain: bool = False,
              counter: Counter | None = None) -> dict[str, Any]:
    """The "What fits now" result for ``meal`` on ``ctx.date`` (the body of ``GET /api/guidance/next-meal``)."""
    counter = counter if counter is not None else Counter()
    totals: DayTotals = day_totals(ctx.day)
    room = meal_room(ctx, meal, totals=totals)
    habit = habit_stats(ctx)
    today = today_stats(ctx.day)
    scorer = Scorer(room, habit, today, counter)
    ranked, why_not = rank_foods(ctx, room, scorer, eligible_foods(ctx), explain)
    chosen = select(ranked, max(1, min(int(limit), R.MAX_LIMIT)))
    tracked = tracked_keys(room)
    carbs_first = room.carbs is not None
    foods: list[dict[str, Any]] = []
    for best, standard in chosen:
        item = food_core(best.food, best.servings)
        reasons, slugs = reasons_for(best, scorer, room, standard, habit)
        item.update({
            "score": best.score,
            "fit_text": M.fit_text(scaled(best.food, best.servings), tracked, carbs_first),
            "reasons": reasons,
            "handbook": T.pages(*slugs),
        })
        if explain:
            item["explain"] = {"components": best.components or {}}
        foods.append(item)
    saved = [public(o) for o in fitting_saved_meals(ctx, meal, room, today, counter)]
    result: dict[str, Any] = {
        "status": "ok",
        "rules_version": R.RULES_VERSION,
        "date": ctx.date,
        "meal": meal,
        "open_meals": list(room.open_meals),
        "room": room_json(room),
        "room_text": M.room_line(meal, {k: room_json(room)[k] for k in (R.K, R.P, R.NA, R.FLUID, R.CARBS)}),
        "meal_has": dict(room.meal_has),
        "foods": foods,
        "saved_meals": saved,
        "tips": day_tips(ctx, room),
        "notes": [M.DISCLAIMER],
    }
    if explain:
        not_eligible = {f.id: ineligible_reason(f, ctx) for f in ctx.foods.values()}
        result["explain"] = {
            "why_not": {str(fid): code for fid, code in sorted(why_not.items())},
            "not_eligible": {str(fid): code for fid, code in sorted(not_eligible.items()) if code is not None},
            "evaluations": counter.foods,
            "meal_evaluations": counter.meals,
            "eligible": len(ranked) + len(why_not),
        }
    return result
