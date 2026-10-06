"""Scores and the single meal gate (note 06 §4.5 "Score", §4.7 "Meal check" and "Meal score"). Pure.

* :class:`Scorer` scores one food at one portion for one meal (what fits now, the planner's
  candidates). The hot path uses plain floats only (§4.12); reasons and texts are built later for
  the few foods that are returned.
* :func:`check_meal` is the one gate every meal passes: plan-day options, saved and usual meals,
  starter combos and AI ideas (note 04 V5 via :mod:`app.guidance.ai_bridge`).
* :func:`score_meal` ranks whole meals.

Every score is rounded to 2 decimals (``rules.round_score``) before it is compared.
"""
from __future__ import annotations

from collections import defaultdict
from math import floor as _floor
from dataclasses import dataclass, field
from datetime import date as _date, timedelta
from typing import Iterable, Mapping, Sequence

from . import rules as R
from .budget import INF, Room
from .state import GuidanceContext
from .vectors import FoodVec, is_high, protein_quality, renal_level

MealItem = tuple[FoodVec, float]

_NEG_CARBS = R.NEGLIGIBLE[R.CARBS]
_K_HIGH, _P_HIGH, _NA_HIGH = R.RENAL_HIGH_CUT[R.K], R.RENAL_HIGH_CUT[R.P], R.RENAL_HIGH_CUT[R.NA]
_P_GOOD, _P_POOR = R.P_PER_G_PROTEIN
_K_GOOD, _K_POOR = R.K_PER_G_PROTEIN


# --------------------------------------------------------------------------- #
# Habit and variety (the static term)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HabitStats:
    """Per-person history facts used by ``static(f)`` (computed once per request)."""

    days_14: Mapping[int, int]  # distinct days each food was eaten in the last 14
    prev2: Mapping[int, int]  # how many of the previous 2 days each food was eaten
    slot_days: Mapping[tuple[int, str], int]  # distinct days per (food, meal slot) in the last 14
    saved_ids: frozenset[int]


@dataclass(frozen=True)
class TodayStats:
    """What the day already holds (eaten, planned and the planner's virtual items)."""

    food_ids: frozenset[int]
    families: Mapping[str, frozenset[int]]


def habit_stats(ctx: GuidanceContext) -> HabitStats:
    """Low treatments (``purpose = 'hypo'``) are not meals and do not count as habits."""
    start14 = (_date.fromisoformat(ctx.date) - timedelta(days=R.HISTORY_DAYS)).isoformat()
    start2 = (_date.fromisoformat(ctx.date) - timedelta(days=2)).isoformat()
    days: dict[int, set[str]] = defaultdict(set)
    prev2: dict[int, set[str]] = defaultdict(set)
    slots: dict[tuple[int, str], set[str]] = defaultdict(set)
    for h in ctx.history:
        if h.hypo or not (start14 <= h.date < ctx.date):
            continue
        days[h.food_id].add(h.date)
        slots[(h.food_id, h.meal)].add(h.date)
        if h.date >= start2:
            prev2[h.food_id].add(h.date)
    saved = frozenset(fid for m in ctx.saved_meals for fid, _ in m.items)
    return HabitStats(
        days_14={k: len(v) for k, v in days.items()},
        prev2={k: len(v) for k, v in prev2.items()},
        slot_days={k: len(v) for k, v in slots.items()},
        saved_ids=saved,
    )


def today_stats(day: Iterable) -> TodayStats:
    ids: set[int] = set()
    fams: dict[str, set[int]] = defaultdict(set)
    for e in day:
        ids.add(e.food_id)
        if e.family:
            fams[e.family].add(e.food_id)
    return TodayStats(food_ids=frozenset(ids), families={k: frozenset(v) for k, v in fams.items()})


def static_term(f: FoodVec, habit: HabitStats, today: TodayStats) -> float:
    """``static(f)`` of §4.5: additives, processing, habit, saved meals, today and recent variety."""
    s = 0.0
    if f.additive:
        s -= 2.0
    if f.processed:
        s -= 0.5
    s += min(1.5, 0.5 * habit.days_14.get(f.id, 0))
    if f.id in habit.saved_ids:
        s += 0.5
    if f.id in today.food_ids:
        s -= 1.5
    s -= 0.5 * habit.prev2.get(f.id, 0)
    fam = today.families.get(f.family)
    if fam and any(other != f.id for other in fam):
        s -= 0.75
    return s


# --------------------------------------------------------------------------- #
# One food at one portion
# --------------------------------------------------------------------------- #


@dataclass
class Evaluation:
    """A scored (food, portion), or the first hard filter it failed (``why_not``)."""

    food: FoodVec
    servings: float
    score: float | None
    why_not: str | None
    unknown: tuple[str, ...] = ()
    components: dict[str, float] | None = None


@dataclass
class Counter:
    """Evaluation counts (§4.12: hardware-independent performance assertions)."""

    foods: int = 0
    meals: int = 0


class Scorer:
    """Scores foods for one meal against its :class:`~app.guidance.budget.Room`."""

    def __init__(self, room: Room, habit: HabitStats, today: TodayStats, counter: Counter | None = None):
        self.room = room
        self.habit = habit
        self.today = today
        self.counter = counter if counter is not None else Counter()
        self.meal = room.meal
        n = room.nutrients
        self.tracked = tuple(k for k in R.ROOM_KEYS if k in n)
        # A portion fails ``would_exceed`` above the meal's room + negligible, or above what is left of the
        # day's own target for potassium, sodium and fluid (never tips the day into "over", §6.7).
        self.lim = {k: min((n[k].room + R.NEGLIGIBLE[k]) if k in n else INF, room.day_left.get(k, INF))
                    for k in R.ROOM_KEYS}
        self.lim_k, self.lim_p, self.lim_na, self.lim_fl = (self.lim[k] for k in (R.K, R.P, R.NA, R.FLUID))
        # Usage-term denominators and weights; ``None`` / 0 for a nutrient without a numeric target.
        self.denom = {k: max(n[k].room, R.NEGLIGIBLE[k]) for k in n}
        self.weight = dict(room.usage_weight)
        self.dk, self.dp, self.dna, self.dfl = (self.denom.get(k) for k in (R.K, R.P, R.NA, R.FLUID))
        self.wk, self.wp, self.wna, self.wfl = (self.weight.get(k, 0.0) for k in (R.K, R.P, R.NA, R.FLUID))
        self.not_ok = {k: (k in n and n[k].level != "ok") for k in R.ROOM_KEYS}
        self.k_not_ok, self.p_not_ok, self.na_not_ok = self.not_ok[R.K], self.not_ok[R.P], self.not_ok[R.NA]
        self.carb_on = room.carbs is not None
        self.gap = room.gap
        self.tol = room.tolerance
        self.has = room.meal_has
        self.has_protein = bool(room.meal_has["protein"])
        self.has_starch = bool(room.meal_has["starch"])
        self.has_veg = bool(room.meal_has["veg_fruit"])
        self.aim = (max(room.protein.aim, R.PROTEIN_AIM_FLOOR_G) if room.protein is not None else None)
        self.meal_high_k = room.meal_high_k
        self.day_high_k = room.day_high_k
        self._static: dict[int, float] = {}

    def static(self, f: FoodVec) -> float:
        s = self._static.get(f.id)
        if s is None:
            s = static_term(f, self.habit, self.today)
            self._static[f.id] = s
        return s

    def slot_habit(self, f: FoodVec) -> bool:
        return self.habit.slot_days.get((f.id, self.meal), 0) >= R.SLOT_HABIT_MIN_DAYS

    def evaluate(self, f: FoodVec, q: float, explain: bool = False) -> Evaluation:
        """Score ``f`` at ``q`` servings, or return the first hard filter it fails (§4.5).

        Hard filters in order: ``would_exceed:<k>`` (over the room + negligible), ``unknown:<k>``
        (unknown while the day's level is not ok), ``too_many_carbs``, ``high_warning:<k>`` (a "high"
        portion of a nutrient that is not ok today). This is the hot path (§4.12): plain floats only.
        """
        self.counter.foods += 1
        fk, fp, fna, ffl = f.k, f.p, f.na, f.fluid
        ak = None if fk is None else fk * q
        ap = None if fp is None else fp * q
        ana = None if fna is None else fna * q
        afl = None if ffl is None else ffl * q
        # 1. would_exceed
        if ak is not None and ak > self.lim_k:
            return Evaluation(f, q, None, "would_exceed:potassium_mg")
        if ap is not None and ap > self.lim_p:
            return Evaluation(f, q, None, "would_exceed:phosphorus_mg")
        if ana is not None and ana > self.lim_na:
            return Evaluation(f, q, None, "would_exceed:sodium_mg")
        if afl is not None and afl > self.lim_fl:
            return Evaluation(f, q, None, "would_exceed:fluid_ml")
        # 2. unknown values: blocked while the day's level is not ok, else a penalty
        unknown: tuple[str, ...] = ()
        if ak is None or ap is None or ana is None:
            missing = []
            for key, v in ((R.K, ak), (R.P, ap), (R.NA, ana)):
                if v is None:
                    if self.not_ok[key]:
                        return Evaluation(f, q, None, f"unknown:{key}")
                    missing.append(key)
            unknown = tuple(missing)
        # 3. carbohydrate
        fc = f.carbs
        ac = None if fc is None else fc * q
        gap = self.gap
        if self.carb_on:
            if ac is None:
                return Evaluation(f, q, None, "unknown:carbs_g")
            if ac > _NEG_CARBS and ac > (gap if gap > 0.0 else 0.0) + self.tol:
                return Evaluation(f, q, None, "too_many_carbs")
        # 4. a "high" portion of a nutrient that is not ok today
        if self.k_not_ok and ak is not None and ak >= _K_HIGH:
            return Evaluation(f, q, None, "high_warning:potassium_mg")
        if self.p_not_ok and (f.additive or (ap is not None and ap >= _P_HIGH)):
            return Evaluation(f, q, None, "high_warning:phosphorus_mg")
        if self.na_not_ok and ana is not None and ana >= _NA_HIGH:
            return Evaluation(f, q, None, "high_warning:sodium_mg")

        role = f.role
        fpr = f.protein
        apr = None if fpr is None else fpr * q
        protein_role = role in R.PROTEIN_ROLES
        # base
        if protein_role and apr is not None and apr >= R.PROTEIN_ROLE_MIN_G:
            base = 1.0
            if ap is not None:
                ratio = ap / apr
                if ratio <= _P_GOOD:
                    base += 1.0
                elif ratio >= _P_POOR:
                    base -= 1.5
            if ak is not None:
                ratio = ak / apr
                if ratio <= _K_GOOD:
                    base += 0.5
                elif ratio >= _K_POOR:
                    base -= 1.0
            if ana is not None and ana >= _NA_HIGH:
                base -= 3.0
            if f.additive:
                base -= 3.0
        else:
            level = renal_level(ak, ap, ana, f.additive)
            base = 3.0 if level == "green" else 1.0 if level == "yellow" else -3.0
        static = self.static(f)
        unknown_pen = R.UNKNOWN_PENALTY * len(unknown)
        portion = 0.5 * abs(q - 1.0)
        usage = 0.0
        if ak is not None and self.dk is not None:
            x = ak / self.dk
            usage += self.wk * x * x
        if ap is not None and self.dp is not None:
            x = ap / self.dp
            usage += self.wp * x * x
        if ana is not None and self.dna is not None:
            x = ana / self.dna
            usage += self.wna * x * x
        if afl is not None and self.dfl is not None:
            x = afl / self.dfl
            usage += self.wfl * x * x
        carbs_term = free = gi = 0.0
        if self.carb_on and ac is not None:
            if gap > self.tol and role in R.CARB_FILL_ROLES:
                carbs_term = 2.0 * (ac if ac < gap else gap) / gap
            if gap <= self.tol and ac <= R.FREE_FOOD_CARBS_G:
                free = 1.0
        if f.high_gi and ac is not None and ac >= R.HIGH_GI_PENALTY_MIN_CARBS_G:
            gi = -1.0
        missing_group = 0.0
        if protein_role and not self.has_protein:
            missing_group += 1.5
        if role in R.STARCH_ROLES and not self.has_starch and (not self.carb_on or gap > 15.0):
            missing_group += 1.5
        if role == "veg_fruit" and not self.has_veg:
            missing_group += 1.0
        protein_term = 0.0
        if protein_role and self.aim is not None and apr is not None:
            a_ = self.aim
            protein_term = 1.5 * (apr if apr < a_ else a_) / a_
            if apr > a_:
                d = (apr - a_) / a_
                protein_term -= min(2.0, d * d)
        habit = R.SLOT_HABIT_BONUS if self.slot_habit(f) else 0.0
        high_k = 0.0
        if ak is not None and ak > R.HIGH_K_ENTRY_MG:
            if self.meal_high_k > 0:
                high_k -= 2.0
            if self.day_high_k >= 2:
                high_k -= 1.0
        s = (base + static - unknown_pen - portion - usage + carbs_term + free + gi + missing_group + protein_term
             + habit + high_k)
        comp = None
        if explain:
            comp = {k: R.round_to(v, 4) for k, v in {
                "base": base, "static": static, "unknown": -unknown_pen, "portion": -portion, "usage": -usage,
                "carbs": carbs_term, "free_food": free, "high_gi": gi, "missing_group": missing_group,
                "protein": protein_term, "slot_habit": habit, "high_potassium": high_k,
            }.items()}
        # R.round_score inlined (hot path): JavaScript Math.round of s × 100, exact at .5 (§4.12).
        x = s * 100.0
        fl = _floor(x)
        return Evaluation(f, q, (fl + 1.0 if x - fl >= 0.5 else fl) / 100.0, None, unknown, comp)

    def best_portion(self, f: FoodVec, portions: Sequence[float], explain: bool = False) -> tuple[Evaluation | None, Evaluation]:
        """``(best scored evaluation or None, the evaluation at one serving)``; ties → lower K, P, Na.

        Every hard filter is monotone in the portion (amounts scale with it; unknown values and additives
        do not depend on it), so once a portion fails, larger ones are not evaluated: they would fail too.
        """
        best: Evaluation | None = None
        best_key: tuple[float, float, float, float] | None = None
        standard: Evaluation | None = None
        failed_at = float("inf")
        for q in portions:
            if q > failed_at:
                continue
            ev = self.evaluate(f, q, explain)
            if q == 1.0:
                standard = ev
            if ev.score is None:
                failed_at = q
                continue
            key = _portion_key(ev)
            if best_key is None or key < best_key:
                best, best_key = ev, key
        if standard is None:
            standard = self.evaluate(f, 1.0, explain)
        return best, standard


def _amount(v: float | None, q: float) -> float:
    return 0.0 if v is None else v * q


def _portion_key(ev: Evaluation) -> tuple[float, float, float, float]:
    f, q = ev.food, ev.servings
    return (-(ev.score or 0.0), _amount(f.k, q), _amount(f.p, q), _amount(f.na, q))


def food_order_key(ev: Evaluation) -> tuple:
    """Across foods: score ↓, potassium ↑, phosphorus ↑, sodium ↑, case-folded name ↑, id ↑ (§4.5)."""
    f, q = ev.food, ev.servings
    return (-(ev.score or 0.0), _amount(f.k, q), _amount(f.p, q), _amount(f.na, q), f.name_fold, f.id)


# --------------------------------------------------------------------------- #
# Whole meals
# --------------------------------------------------------------------------- #

TOTAL_KEYS = (R.K, R.P, R.NA, R.FLUID, R.CARBS, R.PROTEIN, R.KCAL)


def meal_totals(items: Iterable[MealItem]) -> tuple[dict[str, float], frozenset[str]]:
    """``(totals, keys with an unknown value)``; unknown values count as 0 in the totals.

    Reads the vector's float attributes (not the nutrient mapping): it runs for every meal the
    planner and the familiar-meal check consider (§4.12)."""
    k = p = na = fl = c = pr = kcal = 0.0
    unknown: set[str] = set()
    for f, q in items:
        if f.k is None:
            unknown.add(R.K)
        else:
            k += f.k * q
        if f.p is None:
            unknown.add(R.P)
        else:
            p += f.p * q
        if f.na is None:
            unknown.add(R.NA)
        else:
            na += f.na * q
        if f.fluid is None:
            unknown.add(R.FLUID)
        else:
            fl += f.fluid * q
        if f.carbs is None:
            unknown.add(R.CARBS)
        else:
            c += f.carbs * q
        if f.protein is None:
            unknown.add(R.PROTEIN)
        else:
            pr += f.protein * q
        if f.kcal is None:
            unknown.add(R.KCAL)
        else:
            kcal += f.kcal * q
    totals = {R.K: k, R.P: p, R.NA: na, R.FLUID: fl, R.CARBS: c, R.PROTEIN: pr, R.KCAL: kcal}
    return totals, frozenset(unknown)


@dataclass(frozen=True)
class MealCheck:
    ok: bool
    reason: str | None = None


def check_meal(items: Sequence[MealItem], room: Room, kind: str = "built",
               totals: tuple[dict[str, float], frozenset[str]] | None = None) -> MealCheck:
    """The single gate (§4.7): ``kind`` is ``built``, ``ai``, ``saved``, ``usual`` or ``starter``.

    Totals of potassium, phosphorus, sodium and fluid within room + negligible; unknown values only
    while the day's level is ok; carbohydrate at most ``tolerance`` above the meal's gap (negligible
    carbohydrate always passes, as in the food filter); no
    ``avoid_ckd`` food; every portion ¼–3 servings. Built meals and AI ideas additionally never hold
    a low-treatment food, an ingredient, or a "high" portion of a nutrient that is not ok today, and
    AI ideas never hold more than 1 serving of a food with a "high" warning (note 04 V5).
    """
    if not items:
        return MealCheck(False, "empty")
    totals, unknown = totals if totals is not None else meal_totals(items)
    for key in (R.K, R.P, R.NA, R.FLUID):
        item = room.nutrients.get(key)
        if item is None:
            continue
        if totals[key] > item.room + R.NEGLIGIBLE[key]:
            return MealCheck(False, f"would_exceed:{key}")
    for key in (R.K, R.P, R.NA):
        if key in unknown and room.level_of(key) != "ok":
            return MealCheck(False, f"unknown:{key}")
    if room.carbs is not None:
        if R.CARBS in unknown:
            return MealCheck(False, "unknown:carbs_g")
        # The food filter's rule for the whole meal: at most the gap (never below 0) plus the tolerance,
        # and a meal with negligible carbohydrate (≤ 5 g) always passes, even when the meal is already at
        # its goal (so a free food can follow a full meal; §4.5 "too_many_carbs").
        carbs = totals[R.CARBS]
        if carbs > _NEG_CARBS and carbs > max(room.carbs.gap, 0.0) + room.carbs.tolerance:
            return MealCheck(False, "too_many_carbs")
    strict = kind in ("built", "ai")
    for f, q in items:
        if f.avoid:
            return MealCheck(False, "avoid_ckd")
        if q < R.PORTION_MIN - 1e-9 or q > R.PORTION_MAX + 1e-9:
            return MealCheck(False, "portion_out_of_range")
        if strict:
            if f.hypo:
                return MealCheck(False, "hypo_treatment")
            if f.ingredient:
                return MealCheck(False, "ingredient")
            high_any = False
            for key, v in ((R.K, f.k), (R.P, f.p), (R.NA, f.na)):
                high = (v is not None and is_high(key, v * q)) or (key == R.P and f.additive)
                high_any = high_any or high
                if high and room.level_of(key) != "ok":
                    return MealCheck(False, f"high_warning:{key}")
            if kind == "ai" and high_any and q > 1.0 + 1e-9:
                return MealCheck(False, "high_portion_too_large")
    return MealCheck(True)


def _h(d: float) -> float:
    """Carbohydrate consistency: quadratic up to 2 tolerances, then linear (no plateau, F10)."""
    return d * d if d <= 2.0 else 4.0 + 4.0 * (d - 2.0)


def is_poor(f: FoodVec, q: float) -> bool:
    """A "poor" item: a protein portion with P/protein ≥ 16, K/protein ≥ 20 or sodium > 400 mg; any
    other item with a red renal level."""
    apr = None if f.protein is None else f.protein * q
    ak = None if f.k is None else f.k * q
    ap = None if f.p is None else f.p * q
    ana = None if f.na is None else f.na * q
    if f.role in R.PROTEIN_ROLES and apr is not None and apr >= R.PROTEIN_ROLE_MIN_G:
        quality = protein_quality(apr, ak, ap)
        if quality["p_grade"] == "poor" or quality["k_grade"] == "poor":
            return True
        return is_high(R.NA, ana)
    return renal_level(ak, ap, ana, f.additive) == "red"


def score_meal(items: Sequence[MealItem], room: Room, today: TodayStats, dialysis: bool, scale: float = 1.0,
               counter: Counter | None = None, totals: tuple[dict[str, float], frozenset[str]] | None = None) -> float:
    """The meal score of §4.7, rounded to 2 decimals (TV-F7, TV-P1). ``totals`` may pass the
    :func:`meal_totals` the caller already computed for :func:`check_meal`."""
    if counter is not None:
        counter.meals += 1
    totals, _ = totals if totals is not None else meal_totals(items)
    s = 10.0
    for key, item in room.nutrients.items():
        x = totals[key] / max(item.room, R.NEGLIGIBLE[key])
        s -= room.usage_weight[key] * x * x
    if room.carbs is not None and room.carbs.tolerance > 0:
        s -= 2.0 * _h(abs(totals[R.CARBS] - room.carbs.gap) / room.carbs.tolerance)
    if room.protein is not None:
        a = max(room.protein.aim, R.PROTEIN_AIM_FLOOR_G)
        total_p = totals[R.PROTEIN]
        dev = (total_p - a) / a
        if dialysis:
            s -= 6.0 * max(0.0, -dev) + 0.5 * min(2.0, max(0.0, dev) ** 2)
        else:
            a_min = max(room.protein.aim_min, R.PROTEIN_AIM_FLOOR_G)
            s -= 4.0 * max(0.0, (a_min - total_p) / a_min) + 1.5 * min(2.0, dev * dev)
    has_protein = has_veg = False
    for f, q in items:
        if is_poor(f, q):
            s -= 2.0
        if f.additive:
            s -= 1.0
        if f.id in today.food_ids:
            s -= 1.0
        fam = today.families.get(f.family)
        if fam and any(other != f.id for other in fam):
            s -= 0.75
        if f.role in R.PROTEIN_ROLES:
            has_protein = True
        if f.role == "veg_fruit":
            has_veg = True
    if has_protein:
        s += 1.0
    if has_veg:
        s += 0.5
    s -= 1.0 - scale
    return R.round_score(s)
