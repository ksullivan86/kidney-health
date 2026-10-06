"""The room left for one meal (note 06 §4.4). Pure.

Notation of the spec: ``T_k`` the daily target (max side), ``proj_k`` the day's projected total
(eaten + planned, **including** low treatments and the planner's virtual entries), ``used_k(m)`` the
projected amount already in meal ``m``.

* Open slots ``O(m)``: ``m``; every later main meal with no entries; the snack slot when empty. For
  the snack slot: the snack slot and every main meal with no entries. A slot with planned entries is
  not open (its plan is already in ``proj``); earlier empty main meals count as skipped.
* Allowance ``A_k``: the daily target for potassium, sodium and fluid (on hemodialysis with dialysis
  days also ``(T × D − eaten since the last session) / days left``, whichever is lower); for
  phosphorus, which is judged on the weekly average,
  ``clamp(T × (n + 1) − S, 0.8 T, 1.2 T)`` over the ``n`` logged days of the previous 6.
* Room: ``max(0, min(cap − used, share))`` with ``share = max(0, A − proj) × w(m) / Σ w(O)`` and
  ``cap = 0.30 T`` per main meal, ``0.15 T`` for the snack slot (no cap for fluid).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date as _date, timedelta
from typing import Iterable, Mapping, Sequence

from ..periods import interdialytic_interval
from . import rules as R
from .state import DayEntry, GuidanceContext, HistoryEntry

INF = math.inf


@dataclass(frozen=True, slots=True)
class NutrientRoom:
    key: str
    target: float
    allowance: float
    projected: float
    remaining: float
    share: float
    cap: float  # +inf for fluid
    in_meal: float
    room: float
    level: str  # ok | caution | over (projected vs allowance)
    basis: str  # day | week_average | interdialytic


@dataclass(frozen=True, slots=True)
class CarbRoom:
    goal: float
    in_meal: float  # non-hypo carbohydrate already in the meal (eaten + planned)
    gap: float  # goal - in_meal
    tolerance: float
    hypo_excluded: float


@dataclass(frozen=True, slots=True)
class ProteinRoom:
    aim: float
    aim_min: float
    projected: float
    minimum: float | None
    maximum: float | None


@dataclass(frozen=True)
class Room:
    """Everything the scorers need about one meal of one day."""

    meal: str
    open_meals: tuple[str, ...]
    nutrients: Mapping[str, NutrientRoom]  # K, P, Na, fluid that have a numeric target
    carbs: CarbRoom | None
    protein: ProteinRoom | None
    meal_has: Mapping[str, bool]  # protein, starch, veg_fruit (non-hypo entries of the meal)
    meal_high_k: int  # non-hypo entries of the meal with > 200 mg potassium
    day_high_k: int  # same for the whole day
    usage_weight: Mapping[str, float] = field(default_factory=dict)
    # Potassium, sodium and fluid still left today before the day's own target (not the per-meal
    # room): one suggested food never tips a day that is not over into "over" (§6.7). +inf when the
    # day is already over (nothing new to protect) or the nutrient has no target.
    day_left: Mapping[str, float] = field(default_factory=dict)

    def room_of(self, key: str) -> float:
        item = self.nutrients.get(key)
        return INF if item is None else item.room

    def level_of(self, key: str) -> str:
        item = self.nutrients.get(key)
        return "ok" if item is None else item.level

    @property
    def gap(self) -> float:
        return 0.0 if self.carbs is None else self.carbs.gap

    @property
    def tolerance(self) -> float:
        return 0.0 if self.carbs is None else self.carbs.tolerance


# --------------------------------------------------------------------------- #
# Slots
# --------------------------------------------------------------------------- #


def meals_with_entries(day: Iterable[DayEntry]) -> set[str]:
    return {e.meal for e in day}


def open_slots(meal: str, day: Iterable[DayEntry]) -> list[str]:
    """``O(m)`` (TV-B3): ``open_slots("dinner") == ["dinner", "snack"]`` when breakfast is eaten and
    lunch planned; ``open_slots("snack") == ["snack", "dinner"]``."""
    used = meals_with_entries(day)
    slots = [meal]
    if meal == R.SNACK:
        slots += [m for m in R.MAIN_MEALS if m not in used]
        return slots
    after = R.MAIN_MEALS[R.MAIN_MEALS.index(meal) + 1:]
    slots += [m for m in after if m not in used]
    if R.SNACK not in used:
        slots.append(R.SNACK)
    return slots


# --------------------------------------------------------------------------- #
# Allowances
# --------------------------------------------------------------------------- #


def _days_back(day: str, n: int) -> str:
    return (_date.fromisoformat(day) - timedelta(days=n)).isoformat()


def week_allowance(target: float, history: Iterable[HistoryEntry], day: str) -> tuple[float, int, float]:
    """``(A_P, n, S_P)`` (TV-B1/B2): the phosphorus allowance for ``day`` from the logged days among
    the previous 6 (a day with at least one eaten entry is logged; unlogged days are ignored)."""
    start = _days_back(day, R.WEEK_LOOKBACK_DAYS)
    logged: set[str] = set()
    total = 0.0
    for h in history:
        if start <= h.date < day:
            logged.add(h.date)
            total += h.nutrients.get(R.P) or 0.0
    n = len(logged)
    raw = target * (n + 1) - total
    lo, hi = R.WEEK_CLAMP
    return R.clamp(raw, lo * target, hi * target), n, total


def interdialytic_allowance(target: float, key: str, history: Iterable[HistoryEntry], day: str,
                            dialysis_days: Sequence[int]) -> float | None:
    """``(T × D − eaten since the last session, up to yesterday) / days left`` (TV-B6), or ``None``
    without dialysis days. ``D`` runs from the last session (inclusive) to the next (exclusive)."""
    interval = interdialytic_interval(day, dialysis_days)
    if interval is None:
        return None
    since, nxt = interval["since"], interval["next"]
    d_total = (_date.fromisoformat(nxt) - _date.fromisoformat(since)).days
    days_left = max(1, (_date.fromisoformat(nxt) - _date.fromisoformat(day)).days)
    eaten = sum((h.nutrients.get(key) or 0.0) for h in history if since <= h.date < day)
    return (target * d_total - eaten) / days_left


def level_for(projected: float, allowance: float, warn_fraction: float) -> str:
    if allowance <= 0:
        return "over" if projected > 0 else "caution"
    fraction = projected / allowance
    if fraction > 1.0:
        return "over"
    if fraction >= warn_fraction:
        return "caution"
    return "ok"


def snack_carb_goal(targets: Mapping[str, object], per_meal: float) -> float:
    """``targets.carbs_per_snack_g``, else ``max(15, 5 × round(carbs_per_meal_g / 2 / 5))`` (§4.3)."""
    explicit = R.target_max(targets.get("carbs_per_snack_g"))
    if explicit is not None:
        return explicit
    return max(float(R.SNACK_CARB_MIN_G), 5.0 * R.js_round(per_meal / 2.0 / 5.0))


@dataclass(frozen=True)
class DayTotals:
    """Projected totals of the day and per meal, computed once per request."""

    projected: Mapping[str, float]
    meal_used: Mapping[str, Mapping[str, float]]
    meal_carbs: Mapping[str, float]  # non-hypo
    meal_hypo_carbs: Mapping[str, float]
    meal_groups: Mapping[str, frozenset[str]]  # non-hypo
    meal_high_k: Mapping[str, int]
    day_high_k: int


def day_totals(day: Iterable[DayEntry]) -> DayTotals:
    keys = (R.K, R.P, R.NA, R.FLUID, R.PROTEIN, R.CARBS, R.KCAL)
    projected = {k: 0.0 for k in keys}
    meal_used: dict[str, dict[str, float]] = {m: {k: 0.0 for k in keys} for m in R.SLOT_ORDER}
    carbs = {m: 0.0 for m in R.SLOT_ORDER}
    hypo_carbs = {m: 0.0 for m in R.SLOT_ORDER}
    groups: dict[str, set[str]] = {m: set() for m in R.SLOT_ORDER}
    meal_high = {m: 0 for m in R.SLOT_ORDER}
    day_high = 0
    for e in day:
        used = meal_used.setdefault(e.meal, {k: 0.0 for k in keys})
        for k in keys:
            v = e.nutrients.get(k)
            if v is not None:
                projected[k] += v
                used[k] += v
        c = e.nutrients.get(R.CARBS) or 0.0
        if e.hypo:
            hypo_carbs[e.meal] = hypo_carbs.get(e.meal, 0.0) + c
            continue
        carbs[e.meal] = carbs.get(e.meal, 0.0) + c
        groups.setdefault(e.meal, set()).add(e.group)
        if e.role == "mixed":
            groups[e.meal].add("starch")
        if (e.nutrients.get(R.K) or 0.0) > R.HIGH_K_ENTRY_MG:
            meal_high[e.meal] = meal_high.get(e.meal, 0) + 1
            day_high += 1
    return DayTotals(
        projected=projected, meal_used=meal_used, meal_carbs=carbs, meal_hypo_carbs=hypo_carbs,
        meal_groups={m: frozenset(g) for m, g in groups.items()}, meal_high_k=meal_high, day_high_k=day_high,
    )


def meal_room(ctx: GuidanceContext, meal: str, open_meals: Sequence[str] | None = None,
              totals: DayTotals | None = None) -> Room:
    """The room for ``meal`` on ``ctx.date`` (TV-B4/B5/B7). ``open_meals`` overrides ``O(m)`` (the
    planner passes the requested slots still to fill, ``slots[i:]``)."""
    slots = tuple(open_meals) if open_meals is not None else tuple(open_slots(meal, ctx.day))
    if meal not in slots:
        slots = (meal,) + slots
    totals = totals or day_totals(ctx.day)
    targets = ctx.profile.targets
    warn = ctx.profile.warn_fraction
    weight_sum = sum(R.MEAL_WEIGHT[m] for m in slots)
    share_factor = R.MEAL_WEIGHT[meal] / weight_sum if weight_sum > 0 else 1.0

    hd = ctx.profile.dialysis == "hemodialysis" and bool(ctx.profile.dialysis_days)
    nutrients: dict[str, NutrientRoom] = {}
    weights: dict[str, float] = {}
    day_left: dict[str, float] = {}
    for key in R.ROOM_KEYS:
        target = R.target_max(targets.get(key))
        if target is None:
            continue
        basis = "day"
        if key == R.P:
            allowance, _, _ = week_allowance(target, ctx.history, ctx.date)
            basis = "week_average"
        else:
            allowance = target
            if hd and key in R.INTERDIALYTIC_KEYS:
                inter = interdialytic_allowance(target, key, ctx.history, ctx.date, ctx.profile.dialysis_days)
                if inter is not None and inter < target:
                    allowance, basis = inter, "interdialytic"
        proj = totals.projected.get(key, 0.0)
        remaining = allowance - proj
        share = max(0.0, remaining) * share_factor
        cap = R.MEAL_CAP_FRACTION[meal] * target if key in R.CAP_KEYS else INF
        in_meal = totals.meal_used.get(meal, {}).get(key, 0.0)
        room = max(0.0, min(cap - in_meal, share))
        level = level_for(proj, allowance, warn)
        nutrients[key] = NutrientRoom(key, target, allowance, proj, remaining, share, cap, in_meal, room, level, basis)
        weight = R.USAGE_WEIGHT[key]
        if key == R.P and level != "ok":
            weight = R.USAGE_WEIGHT_P_NOT_OK
        weights[key] = weight
        if key in R.DAY_JUDGED:
            day_left[key] = target - proj if proj <= target else INF

    carbs: CarbRoom | None = None
    per_meal = R.target_max(targets.get("carbs_per_meal_g"))
    if ctx.profile.diabetes != "none" and per_meal is not None:
        goal = per_meal if meal != R.SNACK else snack_carb_goal(targets, per_meal)
        in_meal = totals.meal_carbs.get(meal, 0.0)
        carbs = CarbRoom(goal=goal, in_meal=in_meal, gap=goal - in_meal, tolerance=float(ctx.prefs.carb_tolerance_g),
                         hypo_excluded=totals.meal_hypo_carbs.get(meal, 0.0))

    protein: ProteinRoom | None = None
    pt = targets.get(R.PROTEIN)
    p_max = R.target_max(pt)
    p_min = R.target_min(pt)
    if p_max is not None or p_min is not None:
        proj_protein = totals.projected.get(R.PROTEIN, 0.0)
        mid = (p_min + p_max) / 2.0 if (p_min is not None and p_max is not None) else (p_max if p_max is not None else p_min)
        aim = max(0.0, mid - proj_protein) * share_factor
        aim_min = max(0.0, p_min - proj_protein) * share_factor if p_min is not None else 0.0
        protein = ProteinRoom(aim=aim, aim_min=aim_min, projected=proj_protein, minimum=p_min, maximum=p_max)

    groups = totals.meal_groups.get(meal, frozenset())
    return Room(
        meal=meal,
        open_meals=slots,
        nutrients=nutrients,
        carbs=carbs,
        protein=protein,
        meal_has={"protein": "protein" in groups, "starch": "starch" in groups, "veg_fruit": "veg_fruit" in groups},
        meal_high_k=totals.meal_high_k.get(meal, 0),
        day_high_k=totals.day_high_k,
        usage_weight=weights,
        day_left=day_left,
    )
