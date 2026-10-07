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

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..nutrients import NUTRIENT_KEYS, build_projected_alerts, daily_status, round_nutrients
from . import messages as M
from . import rules as R
from .budget import Room, day_totals, meal_room
from .fits import eligible_foods, familiar_option, food_core, public, resolve_items, room_json, saved_meals_for, \
    totals_json, usual_meals_for
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
    static_term,
    today_stats,
)
from .state import DayEntry, GuidanceContext, virtual_entry
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
        foods.sort(key=lambda f: (_LEVEL_RANK[f.level1], -static_term(f, habit, today),
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
    empty = Built((), score_meal((), room, today, dialysis, counter=counter), 0.0)
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
                    children[key] = Built(items, score_meal(items, room, today, dialysis, counter=counter, totals=totals),
                                          totals[0][R.K])
        beam = _rank(list(beam) + list(children.values()))[:beam_width]
    finals = [fine_tune(b, room, today, dialysis, counter, relaxed) for b in beam if b.items]
    unique: dict[tuple, Built] = {}
    for b in finals:
        unique.setdefault(b.key, b)
    return _rank(unique.values())


def fine_tune(b: Built, room: Room, today: TodayStats, dialysis: bool, counter: Counter, relaxed: bool) -> Built:
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
    return Built(items, score_meal(items, room, today, dialysis, counter=counter), _k(items))


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
                      use_saved: bool, use_usual: bool, use_starters: bool) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if use_saved:
        for template_id, name, items in saved_meals_for(ctx, slot):
            opt = familiar_option(ctx, room, today, items, kind="saved", name=name, template_id=template_id, counter=counter,
                                  detail=False)
            if opt is not None:
                options.append(opt)
    if use_usual:
        for name, items in usual_meals_for(ctx, slot):
            opt = familiar_option(ctx, room, today, items, kind="usual", name=name, template_id=None, counter=counter,
                                  detail=False)
            if opt is not None:
                options.append(opt)
    if use_starters:
        for combo in ctx.combos:
            if combo.meal != slot:
                continue
            items = resolve_items(ctx, combo.items)
            if not items or any(f.hidden for f, _ in items):
                continue
            opt = familiar_option(ctx, room, today, items, kind="starter", name=combo.name, template_id=None,
                                  counter=counter, detail=False)
            if opt is not None:
                options.append(opt)
    options.sort(key=lambda o: (-o["score"], o["_k"], o["name"].casefold()))
    return options


def _option_from_familiar(slot: str, room: Room, opt: Mapping[str, Any]) -> SlotPlan:
    return SlotPlan(slot, room, "ok", source=opt["source"], name=opt["name"], template_id=opt["template_id"],
                    scale=opt["scale"], score=opt["score"], items=list(opt["_items"]))


def plan_slot(ctx: GuidanceContext, slot: str, open_meals: Sequence[str], habit: HabitStats,
              pools: Mapping[str, list[FoodVec]], counter: Counter, *, use_saved: bool, use_usual: bool,
              use_starters: bool, variant: int, forced: int | None = None) -> tuple[SlotPlan, list[SlotPlan]]:
    """``(chosen plan, up to AI_PLAN_OPTIONS_MAX options)`` for one slot; the rule's choice is option 0.

    ``forced`` picks another option by index (the AI layer's ``plan`` mode, note 06 §4.13); an index
    out of range keeps the rule's choice.
    """
    totals = day_totals(ctx.day)
    room = meal_room(ctx, slot, open_meals=open_meals, totals=totals)
    today = today_stats(ctx.day)
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
    familiar = _familiar_options(ctx, slot, room, today, counter, use_saved, use_usual, use_starters)

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
            relaxed = [Built(tuple(fallback), score_meal(fallback, room, today, dialysis, counter=counter), _k(fallback))]
    closest = None
    reason = None
    if relaxed:
        meal_items = list(relaxed[0].items)
        for scale in R.SAVED_MEAL_SCALES:
            scaled_items = [(f, q * scale) for f, q in meal_items]
            check = check_meal(scaled_items, room, "built")
            if check.ok:
                plan = SlotPlan(slot, room, "ok", source="built",
                                score=score_meal(scaled_items, room, today, dialysis, counter=counter), items=scaled_items)
                return plan, [plan]
            if reason is None:
                reason = check.reason
        scale = R.SAVED_MEAL_SCALES[-1]
        scaled_items = [(f, q * scale) for f, q in meal_items]
        totals_c, _ = meal_totals(scaled_items)
        closest = {"scale": scale, "items": [food_core(f, q) for f, q in scaled_items],
                   "totals": totals_json(totals_c, room), "reason": check_meal(scaled_items, room, "built").reason}
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
    counter = counter if counter is not None else Counter()
    slots = [m for m in R.SLOT_ORDER if m in set(meals)] if meals else default_slots(ctx)
    variant = max(0, min(int(variant), R.VARIANT_MAX))
    targets, warn = ctx.profile.targets, ctx.profile.warn_fraction
    before = daily_status(_day_totals12(ctx.day), targets, warn)
    habit = habit_stats(ctx)
    pool_size = max(R.POOL_PER_ROLE_RANGE[0], min(int(ctx.tunables.pool_per_role), R.POOL_PER_ROLE_RANGE[1]))
    pools = build_pools(ctx, habit, today_stats(ctx.day), pool_size)
    plans: list[SlotPlan] = []
    slot_options: dict[str, list[SlotPlan]] = {}
    for i, slot in enumerate(slots):
        ctx_i = ctx.with_day(_day_with(ctx, plans))
        plan, options = plan_slot(ctx_i, slot, slots[i:], habit, pools, counter, use_saved=use_saved_meals,
                                  use_usual=use_usual, use_starters=use_starters, variant=variant,
                                  forced=(forced or {}).get(slot))
        plan.today = today_stats(ctx_i.day)
        plans.append(plan)
        slot_options[slot] = options
    _repair(ctx, plans, before)
    grown = _protein_topup(ctx, plans, before)
    dialysis = ctx.profile.dialysis != "none"
    for plan in plans:  # re-score what the repair or the top-up changed, so the score matches the items
        if plan.modified and plan.items and plan.today is not None:
            plan.score = score_meal(plan.items, plan.room, plan.today, dialysis, counter=counter)
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
    return result
