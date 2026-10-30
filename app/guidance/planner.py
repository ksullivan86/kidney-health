"""(c) "Plan the rest of my day" (note 06 §4.7). Pure; computes only, writes nothing.

Slots are filled in order breakfast, lunch, dinner, snack. For each slot the room is computed with
the requested slots still to fill (``slots[i:]``) and with the items already placed in earlier slots
added to the day as virtual planned entries (so variety and the budgets see them). Options per slot,
all checked by the same :func:`~app.guidance.score.check_meal`:

1. saved meals with a matching ``meal_hint`` (scale 1, ¾, ½);
2. usual meals mined from the last 60 days;
3. starter combos (``data/combos.json``) whose foods all exist;
4. a meal built by beam search (protein → starch → vegetable or fruit; one item for the snack slot).

The best familiar option (1–3) wins when it scores at least the best built option minus
``FAMILIAR_MARGIN``. Then a whole-day check repairs a new "over" for potassium, sodium or fluid,
a protein top-up lifts a day below its protein minimum, and an energy note guards against a plan
that is too low in calories (R2: restriction-only ranking drives under-eating).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as _date, timedelta
from typing import Any, Iterable, Mapping, Sequence

from ..nutrients import NUTRIENT_KEYS, build_projected_alerts, daily_status, round_nutrients
from . import messages as M
from . import rules as R
from .budget import Room, day_totals, meal_room
from .fits import eligible_foods, familiar_excluded, familiar_option, food_core, resolve_items, room_json, \
    saved_meals_for, totals_json, unknown_json, usual_meals_for
from .score import (
    Counter,
    Evaluation,
    HabitStats,
    MealItem,
    PrefTerms,
    Scorer,
    TodayStats,
    check_meal,
    food_order_key,
    habit_stats,
    meal_totals,
    score_meal,
    static_term,
    today_stats,
)
from .state import DayEntry, GuidanceContext, HistoryEntry, virtual_entry
from .vectors import FoodVec

_LEVEL_RANK = {"green": 0, "yellow": 1, "red": 2}


# --------------------------------------------------------------------------- #
# Candidate pools
# --------------------------------------------------------------------------- #


def build_pools(ctx: GuidanceContext, habit: HabitStats, today: TodayStats, pool_size: int) -> dict[str, list[FoodVec]]:
    """Eligible foods per role, pre-ranked statically (renal level at one serving, then the static term
    ↓, then potassium per serving ↑, name, id) and cut to ``pool_size`` (``GUIDANCE_POOL_PER_ROLE``)."""
    pools: dict[str, list[FoodVec]] = {role: [] for role in R.ROLES}
    for f in eligible_foods(ctx):
        pools[f.role].append(f)
    for role, foods in pools.items():
        # The preference term joins the static term, so a liked food is not cut from a long list (note 09 §4.5).
        foods.sort(key=lambda f: (_LEVEL_RANK[f.level1], -(static_term(f, habit, today) + habit.pref.of(f)),
                                  f.k if f.k is not None else float("inf"), f.name_fold, f.id))
        del foods[pool_size:]
    return pools


def step_candidates(scorer: Scorer, pool: Iterable[FoodVec], protein_step: bool) -> list[Evaluation]:
    """The ``PER_ROLE`` best foods of a pool by their best single-food score (portions 1, ½ and, for
    protein, 1½)."""
    best: list[Evaluation] = []
    portions = R.PORTIONS_BUILD_PROTEIN if protein_step else R.PORTIONS_BUILD
    for f in pool:
        ev, _ = scorer.best_portion(f, portions)
        if ev is not None:
            best.append(ev)
    best.sort(key=food_order_key)
    return best[: R.PER_ROLE]


# --------------------------------------------------------------------------- #
# Beam search
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Built:
    items: tuple[MealItem, ...]
    score: float
    k_total: float

    @property
    def key(self) -> tuple[tuple[int, float], ...]:
        return tuple((f.id, q) for f, q in self.items)


def _carbs(items: Sequence[MealItem]) -> float:
    return sum((f.carbs or 0.0) * q for f, q in items)


def _k(items: Sequence[MealItem]) -> float:
    return sum((f.k or 0.0) * q for f, q in items)


def _portions(ev: Evaluation, items: Sequence[MealItem], room: Room) -> list[float]:
    """Its best single-food portion, ½, 1, and the carbohydrate-targeted portion when more than the
    tolerance is still missing (§4.7)."""
    out = [ev.servings, 0.5, 1.0]
    f = ev.food
    if room.carbs is not None and f.carbs and f.carbs > 0:
        missing = room.carbs.gap - _carbs(items)
        if missing > room.carbs.tolerance:
            out.append(R.clamp(R.round_to_quarter(missing / f.carbs), R.PORTION_MIN, R.PORTION_MAX))
    seen: list[float] = []
    for q in out:
        if q not in seen:
            seen.append(q)
    return seen


def _rank(states: Iterable[Built]) -> list[Built]:
    return sorted(states, key=lambda b: (-b.score, b.k_total, b.key))


def beam_build(room: Room, scorer: Scorer, today: TodayStats, dialysis: bool, steps: Sequence[list[Evaluation]],
               beam_width: int, counter: Counter, *, snack: bool = False, relaxed: bool = False) -> list[Built]:
    """Beam search over the role steps; each step may be skipped. ``relaxed`` skips the meal check
    (used only to find the closest meal when nothing fits)."""
    pref = scorer.habit.pref
    empty = Built((), score_meal((), room, today, dialysis, counter=counter, pref=pref), 0.0)
    beam = [empty]
    for index, candidates in enumerate(steps):
        children: dict[tuple, Built] = {}
        for state in beam:
            has_mixed = any(f.role == "mixed" for f, _ in state.items)
            if not snack and index == 1 and has_mixed:
                continue  # a mixed dish fills the starch step
            ids = {f.id for f, _ in state.items}
            for ev in candidates:
                if ev.food.id in ids:
                    continue
                for q in _portions(ev, state.items, room):
                    items = state.items + ((ev.food, q),)
                    key = tuple((f.id, qq) for f, qq in items)
                    if key in children:
                        continue
                    totals = meal_totals(items)
                    if not relaxed and not check_meal(items, room, "built", totals).ok:
                        continue
                    children[key] = Built(items, score_meal(items, room, today, dialysis, counter=counter, totals=totals,
                                                            pref=pref), totals[0][R.K])
        beam = _rank(list(beam) + list(children.values()))[:beam_width]
    finals = [fine_tune(b, room, today, dialysis, counter, relaxed, pref) for b in beam if b.items]
    unique: dict[tuple, Built] = {}
    for b in finals:
        unique.setdefault(b.key, b)
    return _rank(unique.values())


def fine_tune(b: Built, room: Room, today: TodayStats, dialysis: bool, counter: Counter, relaxed: bool,
              pref: PrefTerms | None = None) -> Built:
    """Move the starch portion over ¼–3 servings to bring carbohydrate closest to the meal's goal."""
    if room.carbs is None:
        return b
    idx = next((i for i, (f, _) in enumerate(b.items) if f.role == "starch" and f.carbs), None)
    if idx is None:
        return b
    f, q0 = b.items[idx]
    others = _carbs(b.items) - (f.carbs or 0.0) * q0
    best_q, best_d = q0, abs(others + (f.carbs or 0.0) * q0 - room.carbs.gap)
    q = R.PORTION_MIN
    while q <= R.PORTION_MAX + 1e-9:
        d = abs(others + (f.carbs or 0.0) * q - room.carbs.gap)
        if d < best_d - 1e-9 or (abs(d - best_d) <= 1e-9 and q < best_q):
            items = b.items[:idx] + ((f, q),) + b.items[idx + 1:]
            if relaxed or check_meal(items, room, "built").ok:
                best_q, best_d = q, d
        q += 0.25
    if best_q == q0:
        return b
    items = b.items[:idx] + ((f, best_q),) + b.items[idx + 1:]
    return Built(items, score_meal(items, room, today, dialysis, counter=counter, pref=pref), _k(items))


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #


@dataclass
class SlotPlan:
    meal: str
    room: Room
    status: str
    source: str | None = None
    name: str | None = None
    template_id: int | None = None
    scale: float = 1.0
    score: float | None = None
    items: list[MealItem] | None = None
    reason: str | None = None
    closest: dict[str, Any] | None = None
    today: TodayStats | None = None  # the day as it was when this slot was planned (for re-scoring)
    modified: bool = False  # changed by the whole-day repair or the protein top-up
    repeated: bool = False  # several days (note 23 §4): the same foods as this meal on a day before, as nothing else fits

    @property
    def built(self) -> bool:
        return self.source == "built"


def default_slots(ctx: GuidanceContext) -> list[str]:
    used = {e.meal for e in ctx.day}
    return [m for m in R.SLOT_ORDER if m not in used]


def _day_with(ctx: GuidanceContext, plans: Sequence[SlotPlan]) -> tuple[DayEntry, ...]:
    extra = tuple(virtual_entry(f, p.meal, q) for p in plans if p.items for f, q in p.items)
    return ctx.day + extra


def _day_totals12(day: Iterable[DayEntry]) -> dict[str, float]:
    totals = {k: 0.0 for k in NUTRIENT_KEYS}
    for e in day:
        for k in NUTRIENT_KEYS:
            v = e.nutrients.get(k)
            if v is not None:
                totals[k] += v
    return totals


def _familiar_options(ctx: GuidanceContext, slot: str, room: Room, today: TodayStats, counter: Counter,
                      use_saved: bool, use_usual: bool, use_starters: bool, pref: PrefTerms) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    ok_meals = ctx.prefs.repeat_ok_meal_ids
    if use_saved:
        for template_id, name, items in saved_meals_for(ctx, slot):
            # A saved meal marked "OK to repeat" (note 23 §12.2) is scored without the plan's food rotation.
            seen = replace(today, recent={}) if template_id in ok_meals and today.recent else today
            opt = familiar_option(ctx, room, seen, items, kind="saved", name=name, template_id=template_id, counter=counter,
                                  detail=False, pref=pref)
            if opt is not None:
                options.append(opt)
    if use_usual:
        for name, items in usual_meals_for(ctx, slot):
            opt = familiar_option(ctx, room, today, items, kind="usual", name=name, template_id=None, counter=counter,
                                  detail=False, pref=pref)
            if opt is not None:
                options.append(opt)
    if use_starters:
        for combo in ctx.combos:
            if combo.meal != slot:
                continue
            items = resolve_items(ctx, combo.items)
            if not items or any(f.hidden for f, _ in items) or familiar_excluded(ctx, items):
                continue  # a starter meal with a "Not for me" food or a "Never suggest" group is not offered (note 09 §4.6)
            opt = familiar_option(ctx, room, today, items, kind="starter", name=combo.name, template_id=None,
                                  counter=counter, detail=False, pref=pref)
            if opt is not None:
                options.append(opt)
    options.sort(key=lambda o: (-o["score"], o["_k"], o["name"].casefold()))
    return options


def _option_from_familiar(slot: str, room: Room, opt: Mapping[str, Any]) -> SlotPlan:
    return SlotPlan(slot, room, "ok", source=opt["source"], name=opt["name"], template_id=opt["template_id"],
                    scale=opt["scale"], score=opt["score"], items=list(opt["_items"]))


def food_set(items: Iterable[MealItem]) -> frozenset[int]:
    """The foods of a meal, whatever the amounts: "the same meal" for the repeat rule (note 23 §4)."""
    return frozenset(f.id for f, _ in items)


def plan_slot(ctx: GuidanceContext, slot: str, open_meals: Sequence[str], habit: HabitStats,
              pools: Mapping[str, list[FoodVec]], counter: Counter, *, use_saved: bool, use_usual: bool,
              use_starters: bool, variant: int, forced: int | None = None,
              avoid: frozenset[frozenset[int]] = frozenset(), recent: Mapping[int, int] | None = None,
              ) -> tuple[SlotPlan, list[SlotPlan]]:
    """``(chosen plan, up to AI_PLAN_OPTIONS_MAX options)`` for one slot; the rule's choice is option 0.

    ``forced`` picks another option by index (the AI layer's ``plan`` mode, note 06 §4.13); an index
    out of range keeps the rule's choice. ``avoid`` and ``recent`` serve several days at once (note 23 §4):
    meals whose food set is in ``avoid`` are left out unless nothing else fits, and ``recent`` joins the
    day's :class:`TodayStats` so the meal score sees the foods of the days before.
    """
    totals = day_totals(ctx.day)
    room = meal_room(ctx, slot, open_meals=open_meals, totals=totals)
    today = today_stats(ctx.day)
    if recent:
        today = replace(today, recent=recent)
    scorer = Scorer(room, habit, today, counter)
    dialysis = ctx.profile.dialysis != "none"
    snack = slot == R.SNACK
    if snack:
        candidates: list[Evaluation] = []
        for role in R.SNACK_ROLES:
            candidates += step_candidates(scorer, pools.get(role, []), protein_step=False)
        candidates.sort(key=food_order_key)
        steps = [candidates]
    else:
        steps = [
            step_candidates(scorer, list(pools.get("protein", [])) + list(pools.get("mixed", [])), protein_step=True),
            step_candidates(scorer, pools.get("starch", []), protein_step=False),
            step_candidates(scorer, pools.get("veg_fruit", []), protein_step=False),
        ]
    width = max(R.BEAM_WIDTH_RANGE[0], min(int(ctx.tunables.beam_width), R.BEAM_WIDTH_RANGE[1]))
    built = beam_build(room, scorer, today, dialysis, steps, width, counter, snack=snack)
    pref = habit.pref
    familiar = _familiar_options(ctx, slot, room, today, counter, use_saved, use_usual, use_starters, pref)
    repeated = False
    if avoid and (familiar or built):
        ok_meals = ctx.prefs.repeat_ok_meal_ids  # a saved meal marked "OK to repeat" may come back (note 23 §12.2)
        fresh_familiar = [o for o in familiar if food_set(o["_items"]) not in avoid
                          or (o["source"] == "saved" and o["template_id"] in ok_meals)]
        fresh_built = [b for b in built if food_set(b.items) not in avoid]
        if fresh_familiar or fresh_built:
            familiar, built = fresh_familiar, fresh_built
        else:
            repeated = True  # nothing else fits: the meal of a day before may come back

    # "Show me another plan": variant n skips the first n built options.
    built_choices = built[min(variant, len(built) - 1):] if built else []
    best_built = built_choices[0] if built_choices else None
    best_familiar = familiar[0] if familiar else None
    chosen: SlotPlan | None = None
    if best_familiar is not None and (best_built is None or best_familiar["score"] >= best_built.score - R.FAMILIAR_MARGIN):
        chosen = _option_from_familiar(slot, room, best_familiar)
    elif best_built is not None:
        chosen = SlotPlan(slot, room, "ok", source="built", score=best_built.score, items=list(best_built.items))
    if chosen is not None:
        others = [_option_from_familiar(slot, room, o) for o in familiar]
        others += [SlotPlan(slot, room, "ok", source="built", score=b.score, items=list(b.items)) for b in built_choices]
        others.sort(key=lambda o: (-(o.score or 0.0), 0 if o.source != "built" else 1, _k(o.items or [])))
        options = [chosen]
        seen = {tuple((f.id, q) for f, q in chosen.items or [])}
        for o in others:
            key = tuple((f.id, q) for f, q in o.items or [])
            if key not in seen:
                seen.add(key)
                options.append(o)
            if len(options) >= R.AI_PLAN_OPTIONS_MAX:
                break
        if forced is not None and 0 <= forced < len(options):
            chosen = options[forced]
        chosen.repeated = repeated
        return chosen, options
    # Nothing fits: the closest built meal (no room check) at its best scale.
    relaxed = beam_build(room, scorer, today, dialysis, steps, width, counter, snack=snack, relaxed=True)
    if not relaxed:
        # No single food passed the hard filters: show the statically best food of each role instead,
        # so the person still sees what is closest and why it does not fit.
        roles = R.SNACK_ROLES if snack else R.MAIN_ROLE_STEPS
        fallback: list[MealItem] = []
        for role in roles:
            pool = list(pools.get(role, [])) + (list(pools.get("mixed", [])) if role == "protein" else [])
            if pool:
                fallback.append((pool[0], 1.0))
                if snack:
                    break
        if fallback:
            relaxed = [Built(tuple(fallback), score_meal(fallback, room, today, dialysis, counter=counter, pref=pref),
                             _k(fallback))]
    closest = None
    reason = None
    if relaxed:
        meal_items = list(relaxed[0].items)
        for scale in R.SAVED_MEAL_SCALES:
            scaled_items = [(f, q * scale) for f, q in meal_items]
            check = check_meal(scaled_items, room, "built")
            if check.ok:
                plan = SlotPlan(slot, room, "ok", source="built",
                                score=score_meal(scaled_items, room, today, dialysis, counter=counter, pref=pref),
                                items=scaled_items)
                return plan, [plan]
            if reason is None:
                reason = check.reason
        scale = R.SAVED_MEAL_SCALES[-1]
        scaled_items = [(f, q * scale) for f, q in meal_items]
        totals_c, unknown_c = meal_totals(scaled_items)
        closest = {"scale": scale, "items": [food_core(f, q) for f, q in scaled_items],
                   "totals": totals_json(totals_c, room), "unknown": unknown_json(unknown_c, room), "reason": check_meal(scaled_items, room, "built").reason}
    return SlotPlan(slot, room, "no_fit", reason=reason or "no_candidates", closest=closest), []


def _repair(ctx: GuidanceContext, plans: list[SlotPlan], before: Mapping[str, Any]) -> None:
    """Whole-day check (§4.7): a new ``over`` for potassium, sodium or fluid → take ¼ serving off the
    built item contributing most (removing it at zero), at most ``REPAIR_STEPS`` times; then mark the
    slot ``partial``."""
    targets, warn = ctx.profile.targets, ctx.profile.warn_fraction
    for _ in range(R.REPAIR_STEPS + 1):
        status = daily_status(_day_totals12(_day_with(ctx, plans)), targets, warn)
        new_over = [k for k in R.DAY_JUDGED if status.get(k, {}).get("level") == "over"
                    and before.get(k, {}).get("level") != "over"]
        if not new_over:
            return
        key = new_over[0]
        best: tuple[float, int, int] | None = None
        for pi, plan in enumerate(plans):
            if not plan.built or not plan.items:
                continue
            for ii, (f, q) in enumerate(plan.items):
                v = f.nutrients.get(key)
                amount = (v or 0.0) * q
                if amount > 0 and (best is None or amount > best[0]):
                    best = (amount, pi, ii)
        if best is None or _ == R.REPAIR_STEPS:
            for plan in plans:
                if plan.items and any((f.nutrients.get(key) or 0.0) > 0 for f, _q in plan.items):
                    plan.status = "partial"
                    plan.reason = f"day_over:{key}"
            return
        _, pi, ii = best
        plan = plans[pi]
        f, q = plan.items[ii]
        q2 = q - R.REPAIR_STEP
        if q2 < R.PORTION_MIN - 1e-9:
            del plan.items[ii]
        else:
            plan.items[ii] = (f, q2)
        plan.reason = f"reduced:{key}"
        plan.modified = True


def _protein_topup(ctx: GuidanceContext, plans: list[SlotPlan], before: Mapping[str, Any]) -> list[str]:
    """Day protein below its minimum → ½ serving more of the protein item of the latest built main
    meal while its meal check passes (2 steps), then the previous built meal (§4.7)."""
    minimum = R.target_min(ctx.profile.targets.get(R.PROTEIN))
    if minimum is None:
        return []
    grown: list[str] = []
    targets, warn = ctx.profile.targets, ctx.profile.warn_fraction
    for plan in reversed(plans):
        if plan.meal == R.SNACK or not plan.built or not plan.items:
            continue
        for _ in range(R.PROTEIN_TOPUP_STEPS):
            protein = _day_totals12(_day_with(ctx, plans))[R.PROTEIN]
            if protein >= minimum:
                return grown
            idx = next((i for i, (f, _q) in enumerate(plan.items) if f.role in R.PROTEIN_ROLES), None)
            if idx is None:
                break
            f, q = plan.items[idx]
            items = list(plan.items)
            items[idx] = (f, q + R.PROTEIN_TOPUP_STEP)
            if not check_meal(items, plan.room, "built").ok:
                break
            old = plan.items
            plan.items = items
            status = daily_status(_day_totals12(_day_with(ctx, plans)), targets, warn)
            if any(status.get(k, {}).get("level") == "over" and before.get(k, {}).get("level") != "over"
                   for k in R.DAY_JUDGED):
                plan.items = old
                break
            plan.modified = True
            grown.append(plan.meal)
    return grown


def _energy_note(ctx: GuidanceContext, plans: Sequence[SlotPlan]) -> dict[str, Any] | None:
    goal = R.target_max(ctx.profile.targets.get(R.KCAL))
    if goal is None:
        return None
    day = _day_with(ctx, plans)
    if any(e.nutrients.get(R.KCAL) is None for e in day):
        return None  # computed only when every entry and planned item carries calories
    kcal = sum(e.nutrients.get(R.KCAL) or 0.0 for e in day)
    if kcal >= R.ENERGY_NOTE_FRACTION * goal:
        return None
    foods = [
        f for f in ctx.foods.values()
        if not (f.hidden or f.avoid or f.hypo or f.alcohol or f.supplies or f.id in ctx.prefs.exclude_food_ids)
        and f.kcal is not None and f.kcal >= R.ENERGY_DENSE_MIN_KCAL
        and all(v is not None and v <= R.ENERGY_DENSE_MAX[k] for k, v in
                ((R.K, f.k), (R.P, f.p), (R.NA, f.na), (R.CARBS, f.carbs)))
    ]
    foods.sort(key=lambda f: (-(f.kcal or 0.0), f.name_fold, f.id))
    return {
        "kcal": round_nutrients({R.KCAL: kcal})[R.KCAL],
        "goal": round_nutrients({R.KCAL: goal})[R.KCAL],
        "text": M.energy_note_text(kcal, goal),
        "foods": [food_core(f, 1.0) for f in foods[: R.ENERGY_NOTE_FOODS]],
        "handbook": "eating-enough",
    }


def _why(plan: SlotPlan) -> list[str]:
    if not plan.items:
        return []
    totals, _ = meal_totals(plan.items)
    out: list[str] = []
    if plan.room.carbs is not None:
        carb = plan.room.carbs
        out.append(M.plan_why_carbs(totals[R.CARBS], carb.goal, plan.meal, carb.gap, carb.tolerance))
    for key in (R.K, R.P, R.NA, R.FLUID):
        item = plan.room.nutrients.get(key)
        if item is not None:
            out.append(M.plan_why_room(totals[key], item.room, plan.meal, key))
            break
    return out


def plan_json(ctx: GuidanceContext, plan: SlotPlan) -> dict[str, Any]:
    out: dict[str, Any] = {
        "meal": plan.meal,
        "status": plan.status,
        "source": plan.source,
        "name": plan.name,
        "template_id": plan.template_id,
        "scale": plan.scale,
        "score": plan.score,
        "items": [food_core(f, q) for f, q in (plan.items or [])],
        "totals": totals_json(meal_totals(plan.items or [])[0], plan.room) if plan.items else None,
        "unknown": unknown_json(meal_totals(plan.items)[1], plan.room) if plan.items else [],
        "why": _why(plan),
        "room": room_json(plan.room),
        "reason": plan.reason,
    }
    if plan.status == "no_fit":
        key = (plan.reason or "").split(":", 1)[1] if (plan.reason or "").startswith("would_exceed:") else R.K
        item = plan.room.nutrients.get(key)
        room_left = item.room if item is not None else 0.0
        out["message"] = M.no_fit_text(plan.meal, key if item is not None else R.K, room_left)
        out["closest"] = plan.closest
    elif plan.status == "partial" and plan.reason and ":" in plan.reason:
        out["message"] = M.partial_text(plan.meal, plan.reason.split(":", 1)[1])
    return out


def plan_day(ctx: GuidanceContext, meals: Sequence[str] | None = None, *, use_saved_meals: bool = True,
             use_usual: bool = True, use_starters: bool = True, variant: int = 0,
             counter: Counter | None = None, forced: Mapping[str, int] | None = None,
             with_options: bool = False) -> dict[str, Any]:
    """Plan the requested slots (default: every slot with no entries) of ``ctx.date``.

    ``forced`` (slot → option index) and ``with_options`` serve the AI layer's ``plan`` mode
    (:mod:`app.guidance.ai_bridge`): the whole-day check and repair always run on the chosen options.
    """
    return _plan_day(ctx, meals, use_saved_meals=use_saved_meals, use_usual=use_usual, use_starters=use_starters,
                     variant=variant, counter=counter, forced=forced, with_options=with_options)[0]


def _plan_day(ctx: GuidanceContext, meals: Sequence[str] | None = None, *, use_saved_meals: bool = True,
              use_usual: bool = True, use_starters: bool = True, variant: int = 0,
              counter: Counter | None = None, forced: Mapping[str, int] | None = None,
              with_options: bool = False, habit: HabitStats | None = None,
              avoid: Mapping[str, frozenset[frozenset[int]]] | None = None,
              recent: Mapping[int, int] | None = None, slots: Sequence[str] | None = None,
              free: frozenset[str] = frozenset(), habit_free: HabitStats | None = None) -> tuple[dict[str, Any], list[SlotPlan]]:
    """:func:`plan_day` and its slot plans. ``habit``, ``avoid`` (slot → food sets), ``recent``, ``slots`` (the meals to
    plan, already decided), ``free`` (meals that may repeat: no avoid, no rotation, ``habit_free``) come from
    :func:`plan_days`; left out, the day is planned on its own."""
    counter = counter if counter is not None else Counter()
    if slots is None:
        slots = [m for m in R.SLOT_ORDER if m in set(meals)] if meals else default_slots(ctx)
    slots = list(slots)
    variant = max(0, min(int(variant), R.VARIANT_MAX))
    targets, warn = ctx.profile.targets, ctx.profile.warn_fraction
    before = daily_status(_day_totals12(ctx.day), targets, warn)
    habit = habit if habit is not None else habit_stats(ctx)
    pool_size = max(R.POOL_PER_ROLE_RANGE[0], min(int(ctx.tunables.pool_per_role), R.POOL_PER_ROLE_RANGE[1]))
    pools = build_pools(ctx, habit, today_stats(ctx.day), pool_size)
    plans: list[SlotPlan] = []
    slot_options: dict[str, list[SlotPlan]] = {}
    for i, slot in enumerate(slots):
        ctx_i = ctx.with_day(_day_with(ctx, plans))
        own = slot in free  # a meal that may repeat skips the 2-day rule and the plan's food rotation (note 23 §12.2)
        slot_recent = None if own else recent
        plan, options = plan_slot(ctx_i, slot, slots[i:], (habit_free or habit) if own else habit, pools, counter,
                                  use_saved=use_saved_meals, use_usual=use_usual, use_starters=use_starters, variant=variant,
                                  forced=(forced or {}).get(slot),
                                  avoid=frozenset() if own else (avoid or {}).get(slot, frozenset()), recent=slot_recent)
        plan.today = today_stats(ctx_i.day)
        if slot_recent:
            plan.today = replace(plan.today, recent=slot_recent)
        plans.append(plan)
        slot_options[slot] = options
    _repair(ctx, plans, before)
    grown = _protein_topup(ctx, plans, before)
    dialysis = ctx.profile.dialysis != "none"
    for plan in plans:  # re-score what the repair or the top-up changed, so the score matches the items
        if plan.modified and plan.items and plan.today is not None:
            plan.score = score_meal(plan.items, plan.room, plan.today, dialysis, counter=counter, pref=habit.pref)
    projected = _day_totals12(_day_with(ctx, plans))
    after = daily_status(projected, targets, warn)
    # New "over" alerts only: a plan that brings the day near (not over) a goal is what was asked for.
    was_over = {a["nutrient"] for a in build_projected_alerts(before) if a["level"] == "over"}
    new_alerts = [a for a in build_projected_alerts(after) if a["level"] == "over" and a["nutrient"] not in was_over]
    # A planned meal is never a low treatment, even when a saved meal holds apple juice: "none" stops
    # POST /api/log/batch from defaulting a hypo_treatment food to purpose "hypo".
    entries = [
        {"date": ctx.date, "meal": p.meal, "food_id": f.id, "servings": R.round_to(q, 3), "status": "planned",
         "purpose": "none"}
        for p in plans if p.items for f, q in p.items
    ]
    meals_json = []
    for p in plans:
        item = plan_json(ctx, p)
        if p.source == "saved" and p.template_id is not None:
            item["apply_saved"] = {"endpoint": f"/api/meals/{p.template_id}/apply",
                                   "body": {"date": ctx.date, "meal": p.meal, "status": "planned", "scale": p.scale}}
        meals_json.append(item)
    result: dict[str, Any] = {
        "status": "ok",
        "rules_version": R.RULES_VERSION,
        "date": ctx.date,
        "variant": variant,
        "meals": meals_json,
        "protein_topup": grown,
        "day_after": {"projected_totals": round_nutrients(projected), "projected_status": after, "new_alerts": new_alerts},
        "energy_note": _energy_note(ctx, plans),
        "apply": {"endpoint": "/api/log/batch", "entries": entries},
        "notes": [M.DISCLAIMER],
    }
    if with_options:
        result["options"] = {slot: [plan_json(ctx, o) for o in opts] for slot, opts in slot_options.items()}
    return result, plans


# --------------------------------------------------------------------------- #
# Several days at once (note 23)
# --------------------------------------------------------------------------- #


def add_days(day: str, n: int) -> str:
    return (_date.fromisoformat(day) + timedelta(days=n)).isoformat()


def is_dialysis_day(ctx: GuidanceContext, day: str) -> bool:
    """A hemodialysis day of the profile (``dialysis_days``: 0 = Monday … 6 = Sunday), as the Plan week marks it."""
    return ctx.profile.dialysis == "hemodialysis" and _date.fromisoformat(day).weekday() in set(ctx.profile.dialysis_days)


def _history_rows(day: str, entries: Iterable[DayEntry]) -> list[HistoryEntry]:
    return [HistoryEntry(date=day, meal=e.meal, food_id=e.food_id, name=e.name, servings=e.servings,
                         nutrients=e.nutrients, purpose=e.purpose, flags=e.flags) for e in entries]


def unknown_counts(day: Iterable[DayEntry]) -> dict[str, int]:
    """Entries (and planned items) of a day without a value, per nutrient: the day's total is then "at least"."""
    out: dict[str, int] = {}
    for e in day:
        for k in NUTRIENT_KEYS:
            if e.nutrients.get(k) is None:
                out[k] = out.get(k, 0) + 1
    return {k: out[k] for k in NUTRIENT_KEYS if k in out}


def shopping_items(ctx: GuidanceContext, entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What a plan adds, by food: servings summed, grams, on how many days (``GET /api/plan/shopping``'s shape), by name."""
    servings: dict[int, float] = {}
    dates: dict[int, set[str]] = {}
    for e in entries:
        fid = int(e["food_id"])
        servings[fid] = servings.get(fid, 0.0) + float(e["servings"])
        dates.setdefault(fid, set()).add(e["date"])
    foods = sorted((ctx.foods[fid] for fid in servings), key=lambda f: (f.name_fold, f.id))
    return [{"food_id": f.id, "food_name": f.name, "serving_desc": f.serving_desc, "servings": R.round_to(servings[f.id], 3),
             "grams": R.round_to(servings[f.id] * f.serving_g, 1), "days": len(dates[f.id])} for f in foods]


def day_slots(ctx: GuidanceContext, meals: Sequence[str] | None, *, snack: bool | None = None,
              skip: Iterable[str] = ()) -> list[str]:
    """The meals to plan on one day of several (note 23 §12.5, §12.6): ``meals`` (each planned even when it has food) or every
    meal with nothing logged. ``snack`` False leaves the snack out unless ``meals`` names it; True adds it to ``meals``; None
    (one day, as "Plan a day…") changes nothing. The meals in ``skip`` are not planned (the first day's past meals). A logged
    low treatment is never touched."""
    if meals:
        wanted = set(meals) | ({R.SNACK} if snack else set())
        slots = [m for m in R.SLOT_ORDER if m in wanted]
    else:
        slots = [m for m in default_slots(ctx) if snack is not False or m != R.SNACK]
    skipped = set(skip)
    return [m for m in slots if m not in skipped]


def plan_days(ctx: GuidanceContext, days: Sequence[Sequence[DayEntry]], meals: Sequence[str] | None = None, *,
              use_saved_meals: bool = True, use_usual: bool = True, use_starters: bool = True, variant: int = 0,
              counter: Counter | None = None, repeat_meals: Iterable[str] = (), snack: bool | None = None,
              skip_first_day: Iterable[str] = ()) -> dict[str, Any]:
    """Plan ``len(days)`` days from ``ctx.date`` (note 23); ``days[i]`` holds the logged entries of ``ctx.date + i``.

    Each day is :func:`plan_day` of that date with its own logged food. The days are planned in order and see each other:

    * the earlier days of the plan (what is logged on them and what the plan adds) join the history the room reads, so the
      phosphorus week and the dialysis interval count them (as Running high counts plans);
    * the habit term is the first day's (a planned food is never counted as eaten); only its "the 2 days before" part also
      counts the earlier plan days;
    * a meal with the same foods as the same meal on one of the ``PLAN_REPEAT_DAYS`` days before is left out unless
      nothing else fits, and each food on those days costs ``PLAN_RECENT_FOOD_PENALTY`` per day in the meal score.

    The owner's choices (note 23 §12): a meal in ``repeat_meals`` skips both rules for that meal, and the plan's days do not
    count in its "2 days before"; a food marked "OK to repeat" (``prefs.repeat_ok_food_ids``) never counts in the rotation,
    and a meal made only of such foods may come back; a saved meal marked "OK to repeat" (``prefs.repeat_ok_meal_ids``) may
    come back and is scored without the rotation. ``snack`` and ``skip_first_day`` choose the meals (:func:`day_slots`).

    With the defaults (``snack`` None, nothing skipped), the first day is exactly :func:`plan_day` of ``ctx.date``.
    Computes only."""
    counter = counter if counter is not None else Counter()
    variant = max(0, min(int(variant), R.VARIANT_MAX))
    start = ctx.date
    free = frozenset(m for m in repeat_meals if m in R.SLOT_ORDER)
    ok_foods = ctx.prefs.repeat_ok_food_ids
    skip0 = frozenset(skip_first_day)
    habit0 = habit_stats(ctx)
    carried: list[HistoryEntry] = []
    foods_on: list[frozenset[int]] = []  # per day so far: its foods (logged and planned), low treatments and OK foods left out
    slot_sets: list[dict[str, frozenset[int]]] = []  # per day so far: meal slot → its foods
    out_days: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for i, logged in enumerate(days):
        day = add_days(start, i)
        window = range(max(0, i - R.PLAN_REPEAT_DAYS), i)
        recent: dict[int, int] = {}
        for j in window:
            for fid in sorted(foods_on[j]):
                recent[fid] = recent.get(fid, 0) + 1
        habit = habit_free = habit0
        if i:
            # "The 2 days before" of the habit term: the eaten days before the plan that are still in it, then the plan's days.
            since = add_days(day, -R.PLAN_REPEAT_DAYS)
            eaten: dict[int, set[str]] = {}
            for h in ctx.history:
                if not h.hypo and since <= h.date < start:
                    eaten.setdefault(h.food_id, set()).add(h.date)
            prev_eaten = {fid: len(dates) for fid, dates in eaten.items()}
            prev2 = dict(prev_eaten)
            for fid, n in recent.items():
                prev2[fid] = prev2.get(fid, 0) + n
            habit = replace(habit0, prev2=prev2)
            habit_free = replace(habit0, prev2=prev_eaten)  # a meal that may repeat: only what was really eaten
        avoid: dict[str, frozenset[frozenset[int]]] = {}
        for slot in R.SLOT_ORDER:
            # A meal made only of foods marked "OK to repeat" may come back (note 23 §12.2).
            sets = frozenset(slot_sets[j][slot] for j in window
                             if slot in slot_sets[j] and not slot_sets[j][slot] <= ok_foods)
            if sets:
                avoid[slot] = sets
        ctx_i = GuidanceContext(
            date=day, profile=ctx.profile, prefs=ctx.prefs, foods=ctx.foods, day=tuple(logged),
            history=ctx.history + tuple(carried), history60=ctx.history60, planned30=ctx.planned30, eaten30=ctx.eaten30,
            saved_meals=ctx.saved_meals, combos=ctx.combos, tunables=ctx.tunables,
        )
        slots = day_slots(ctx_i, meals, snack=snack, skip=skip0 if i == 0 else ())
        result, plans = _plan_day(ctx_i, meals, use_saved_meals=use_saved_meals, use_usual=use_usual,
                                  use_starters=use_starters, variant=variant, counter=counter, habit=habit, avoid=avoid,
                                  recent=recent, slots=slots, free=free, habit_free=habit_free)
        with_plan = _day_with(ctx_i, plans)
        carried.extend(_history_rows(day, with_plan))
        foods_on.append(frozenset(e.food_id for e in with_plan if not e.hypo and e.food_id not in ok_foods))
        sets_now: dict[str, set[int]] = {}
        for e in with_plan:
            if not e.hypo:
                sets_now.setdefault(e.meal, set()).add(e.food_id)
        slot_sets.append({slot: frozenset(ids) for slot, ids in sets_now.items()})
        for item, plan in zip(result["meals"], plans):
            item["repeated"] = plan.repeated
        day_after = {**result["day_after"], "projected_unknown": unknown_counts(with_plan)}
        out_days.append({"date": day, "dialysis_day": is_dialysis_day(ctx, day), "meals": result["meals"],
                         "protein_topup": result["protein_topup"], "day_after": day_after,
                         "energy_note": result["energy_note"]})
        entries.extend(result["apply"]["entries"])
    return {
        "status": "ok",
        "rules_version": R.RULES_VERSION,
        "start": start,
        "end": add_days(start, len(days) - 1),
        "variant": variant,
        "days": out_days,
        "apply": {"endpoint": "/api/log/batch", "entries": entries},
        "shopping": {"items": shopping_items(ctx, entries)},
        "notes": [M.DISCLAIMER],
    }

