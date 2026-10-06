"""(d) End-of-day and period insights in plain language (note 06 §4.8). Pure, rule-only in v0.3.

Each insight: ``{id, severity, nutrient, message, numbers, sources, handbook}``. Only **eaten**
entries count (planned ones are reported as ``planned_excluded``). Severity order ``warning`` >
``attention`` > ``info`` > ``good``, then nutrient priority potassium, phosphorus, sodium, fluid,
protein, carbohydrate; at most ``INSIGHT_MAX`` (6), at most one ``good``, always last. Insights are
never sent to an AI provider in v0.3.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date as _date, timedelta
from typing import Any, Iterable, Mapping, Sequence

from ..nutrients import NUTRIENT_BY_KEY
from ..periods import interdialytic_interval
from . import messages as M
from . import rules as R
from . import topics as T
from .fits import short_names
from .state import DayEntry, GuidanceContext, HistoryEntry, Prefs, Profile
from .vectors import FoodVec
from .swaps import candidate_portion

_WEEKDAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_WEEKDAY_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_LABEL = {R.K: "Potassium", R.P: "Phosphorus", R.NA: "Sodium", R.FLUID: "Fluid", R.PROTEIN: "Protein",
          R.CARBS: "Carbohydrate", R.KCAL: "Calories"}


def insight(id_: str, severity: str, nutrient: str | None, message: str, numbers: Mapping[str, Any] | None = None,
            sources: Sequence[Mapping[str, Any]] = (), handbook: Sequence[str] = ()) -> dict[str, Any]:
    return {"id": id_, "severity": severity, "nutrient": nutrient, "message": message,
            "numbers": dict(numbers or {}), "sources": list(sources), "handbook": T.pages(*handbook)}


def order_insights(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Severity, then nutrient priority; at most ``INSIGHT_MAX``; at most one ``good``, always last."""
    ranked = sorted(
        items,
        key=lambda i: (R.SEVERITY_ORDER[i["severity"]], R.NUTRIENT_PRIORITY.get(i["nutrient"] or "", 9), i["id"]),
    )
    good = [i for i in ranked if i["severity"] == "good"][:1]
    rest = [i for i in ranked if i["severity"] != "good"]
    return (rest[: R.INSIGHT_MAX - len(good)] + good)[: R.INSIGHT_MAX]


# --------------------------------------------------------------------------- #
# Source attribution
# --------------------------------------------------------------------------- #


def sources(entries: Iterable[Any], key: str) -> list[dict[str, Any]]:
    """The foods that gave most of ``key``: share ≥ 10 %, at most 3, share ↓ then name (§4.8)."""
    sums: "OrderedDict[Any, list[Any]]" = OrderedDict()
    total = 0.0
    for e in entries:
        v = e.nutrients.get(key)
        if v is None or v <= 0:
            continue
        ident = e.food_id if e.food_id is not None else e.name
        if ident not in sums:
            sums[ident] = [e.name, 0.0]
        sums[ident][1] += v
        total += v
    if total <= 0:
        return []
    rows = [(name, value, value / total) for name, value in sums.values() if value / total >= R.SOURCE_MIN_SHARE]
    rows.sort(key=lambda r: (-r[2], r[0].casefold()))
    rows = rows[: R.SOURCE_MAX]
    shorts = short_names([r[0] for r in rows])
    return [{"name": M.safe_name(r[0]), "short_name": s, "value": M.whole(r[1]), "share_pct": M.pct(r[2])}
            for r, s in zip(rows, shorts)]


def _named(entries: Iterable[Any]) -> list[str]:
    """Distinct foods in first-appearance order, ``name (n)`` when one appears more than once."""
    order: "OrderedDict[Any, list[Any]]" = OrderedDict()
    for e in entries:
        ident = e.food_id if e.food_id is not None else e.name
        if ident not in order:
            order[ident] = [e.name, 0]
        order[ident][1] += 1
    names = short_names([v[0] for v in order.values()])
    return [f"{n} ({c})" if c > 1 else n for n, (_, c) in zip(names, order.values())]


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _sum(entries: Iterable[Any], key: str) -> float:
    return sum((e.nutrients.get(key) or 0.0) for e in entries)


# --------------------------------------------------------------------------- #
# End of day
# --------------------------------------------------------------------------- #


def best_hypo_food(foods: Mapping[int, FoodVec], prefs: Prefs) -> tuple[FoodVec, float, float] | None:
    """The person's low treatment with the least potassium at the treatment amount: ``(food, servings, K)``."""
    best: tuple[tuple, FoodVec, float, float] | None = None
    for f in foods.values():
        if not f.hypo or f.hidden or f.avoid or f.id in prefs.exclude_food_ids or f.k is None:
            continue
        q = candidate_portion(f, "carbs", float(prefs.hypo_dose_g), "hypo")
        if q is None:
            continue
        k = f.k * q
        key = (k, (f.p or 0.0) * q, f.name_fold, f.id)
        if best is None or key < best[0]:
            best = (key, f, q, k)
    return None if best is None else (best[1], best[2], best[3])


def _carb_meals(entries: Sequence[DayEntry], goal: float, tol: float) -> tuple[list[tuple[str, float]], list[tuple[str, float]], int]:
    above: list[tuple[str, float]] = []
    below: list[tuple[str, float]] = []
    logged = 0
    for meal in R.MAIN_MEALS:
        rows = [e for e in entries if e.meal == meal and not e.hypo]
        if not rows:
            continue
        logged += 1
        c = _sum(rows, R.CARBS)
        if c > goal + tol:
            above.append((meal, c))
        elif c < goal - tol:
            below.append((meal, c))
    return above, below, logged


def _meal_list(rows: Sequence[tuple[str, float]]) -> str:
    """``Lunch had 72 g and dinner 87 g of carbs`` (first meal capitalised)."""
    head = f"{M.capitalise(rows[0][0])} had {M.fmt_g(rows[0][1])} g"
    rest = [f"{m} {M.fmt_g(c)} g" for m, c in rows[1:]]
    return M.join_and([head, *rest]) + " of carbs"


def day_insights(ctx: GuidanceContext) -> dict[str, Any]:
    """``GET /api/guidance/insights/day`` (TV-I1, TV-I5)."""
    eaten = [e for e in ctx.day if e.status == "eaten"]
    planned = sum(1 for e in ctx.day if e.status != "eaten")
    out: list[dict[str, Any]] = []
    targets = ctx.profile.targets
    warn = ctx.profile.warn_fraction
    dialysis = ctx.profile.dialysis != "none"
    if eaten:
        k_level = "ok"
        # Day-judged limits.
        for key in (R.K, R.NA, R.FLUID):
            t = R.target_max(targets.get(key))
            if t is None:
                continue
            v = _sum(eaten, key)
            fraction = v / t
            unit = NUTRIENT_BY_KEY[key].unit
            topic = T.NUTRIENT_TOPIC[key]
            if fraction > 1.0:
                src = sources(eaten, key)
                msg = (f"{_LABEL[key]} was {M.fmt_amount(key, v)} {unit} today, {M.pct(fraction)} % of your "
                       f"{M.fmt_amount(key, t)} {unit} limit.")
                if len(src) >= 2:
                    msg += (f" Most came from {src[0]['short_name']} ({src[0]['share_pct']} %) and "
                            f"{src[1]['short_name']} ({src[1]['share_pct']} %).")
                elif len(src) == 1:
                    msg += f" Most came from {src[0]['short_name']} ({src[0]['share_pct']} %)."
                out.append(insight(f"day.{key}.over", "warning", key, msg,
                                   {"value": M.whole(v), "target": M.whole(t), "percent": M.pct(fraction)}, src, [topic]))
                if key == R.K:
                    k_level = "over"
            elif fraction >= warn:
                msg = (f"{_LABEL[key]} reached {M.pct(fraction)} % of your limit ({M.fmt_amount(key, v)} of "
                       f"{M.fmt_amount(key, t)} {unit}).")
                out.append(insight(f"day.{key}.caution", "attention", key, msg,
                                   {"value": M.whole(v), "target": M.whole(t), "percent": M.pct(fraction)}, (), [topic]))
                if key == R.K:
                    k_level = "caution"
        # Phosphorus: one high day is information (weekly average).
        tp = R.target_max(targets.get(R.P))
        if tp is not None and _sum(eaten, R.P) > tp:
            v = _sum(eaten, R.P)
            out.append(insight(
                "day.phosphorus_mg.over", "info", R.P,
                f"Phosphorus was {M.fmt_int(v)} mg today, above your {M.fmt_int(tp)} mg target. It is judged on the "
                "weekly average, so lighter days around it balance it out.",
                {"value": M.whole(v), "target": M.whole(tp)}, sources(eaten, R.P), ["phosphorus"]))
        # Carbohydrate per meal (low treatments are not part of a meal).
        per_meal = R.target_max(targets.get("carbs_per_meal_g"))
        if ctx.profile.diabetes != "none" and per_meal is not None:
            tol = float(ctx.prefs.carb_tolerance_g)
            above, below, logged = _carb_meals(eaten, per_meal, tol)
            sentences = []
            if above:
                sentences.append(f"{_meal_list(above)}, more than {M.fmt_g(tol)} g above your usual {M.fmt_g(per_meal)} g.")
            if below:
                sentences.append(f"{_meal_list(below)}, more than {M.fmt_g(tol)} g below your usual {M.fmt_g(per_meal)} g.")
            if sentences:
                out.append(insight("day.carbs.meal_off", "info", R.CARBS, " ".join(sentences),
                                   {"goal": M.whole(per_meal), "tolerance": M.whole(tol),
                                    "above": {m: R.round_to(c, 1) for m, c in above},
                                    "below": {m: R.round_to(c, 1) for m, c in below}}, (), ["carb-counting"]))
            elif logged >= 2:
                out.append(insight("day.carbs.consistent", "good", R.CARBS,
                                   f"All {logged} meals were within {M.fmt_g(tol)} g of your {M.fmt_g(per_meal)} g carb goal.",
                                   {"meals": logged, "goal": M.whole(per_meal), "tolerance": M.whole(tol)}))
        # Low treatments: counted honestly, never warned against.
        hypo = [e for e in eaten if e.hypo]
        if hypo:
            c, k = _sum(hypo, R.CARBS), _sum(hypo, R.K)
            msg = (f"You logged {_plural(len(hypo), 'low-glucose treatment')} ({M.fmt_g(c)} g carbs, {M.fmt_int(k)} mg "
                   "potassium). They are not counted in the meal carb check.")
            numbers: dict[str, Any] = {"count": len(hypo), "carbs_g": R.round_to(c, 1), "potassium_mg": M.whole(k)}
            if any((e.nutrients.get(R.K) or 0.0) > R.HYPO_INSIGHT_K_MG for e in hypo):
                best = best_hypo_food(ctx.foods, ctx.prefs)
                if best is not None and best[2] <= R.HYPO_BEST_MAX_K_MG:
                    msg += f" {M.safe_name(best[0].name)} would treat the same low with {M.fmt_int(best[2])} mg potassium."
                    numbers["better_food_id"] = best[0].id
            out.append(insight("day.hypo.logged", "info", R.CARBS, msg, numbers, (), ["treating-a-low"]))
        # Several high-potassium portions (AKF/UW: not several high-K foods in one day).
        high = [e for e in eaten if not e.hypo and (e.nutrients.get(R.K) or 0.0) > R.HIGH_K_ENTRY_MG]
        if len(high) >= 2:
            sev = "attention" if k_level in ("caution", "over") else "info"
            out.append(insight("day.high_k.count", sev, R.K,
                               f"You had {len(high)} high-potassium portions today: {M.join_and(_named(high))}.",
                               {"count": len(high)}, (), ["potassium"]))
        # Phosphate additives.
        additive = [e for e in eaten if "phosphate_additive" in e.flags]
        if additive:
            names = _named(additive)
            n = len(names)
            out.append(insight("day.additives", "info", R.P,
                               f"{_plural(n, 'food')} today had phosphate additives: {M.join_and([x.split(' (')[0] for x in names])}. "
                               "Additive phosphorus is almost fully absorbed.", {"count": n}, (), ["phosphate-additives"]))
        # Protein.
        pt = targets.get(R.PROTEIN)
        p_min, p_max = R.target_min(pt), R.target_max(pt)
        protein = _sum(eaten, R.PROTEIN)
        if dialysis and p_min is not None and protein < p_min:
            out.append(insight("day.protein.low", "attention", R.PROTEIN,
                               f"Protein was {M.fmt_g(protein)} g, below your {M.fmt_g(p_min)} g minimum. On dialysis your "
                               "body needs more protein, not less.",
                               {"value": R.round_to(protein, 1), "min": M.whole(p_min)}, (), ["protein"]))
        if not dialysis and p_max is not None and protein > p_max:
            out.append(insight("day.protein.high", "info", R.PROTEIN,
                               f"Protein was {M.fmt_g(protein)} g, above your {M.fmt_g(p_max)} g maximum. Protein is judged "
                               "on the weekly average.", {"value": R.round_to(protein, 1), "max": M.whole(p_max)}, (), ["protein"]))
        # Unknown values.
        missing_keys = [k for k in (R.K, R.P, R.NA) if any(e.nutrients.get(k) is None for e in eaten)]
        if missing_keys:
            foods_missing = {e.food_id for e in eaten if any(e.nutrients.get(k) is None for k in missing_keys)}
            words = M.join_and([M.NUTRIENT_WORD[k] for k in missing_keys]).replace(" and ", " or ")
            n = len(foods_missing)
            out.append(insight("day.unknown", "info", missing_keys[0],
                               f"{_plural(n, 'food')} had no {words} value, so today's total may be low.",
                               {"count": n, "nutrients": missing_keys}, (), ["label-reading"]))
        # Between dialysis sessions.
        inter = _interdialytic(ctx, eaten)
        if inter is not None:
            out.append(inter)
        # Eating enough.
        kcal_goal = R.target_max(targets.get(R.KCAL))
        meals_logged = len({e.meal for e in eaten if not e.hypo})
        if kcal_goal is not None and meals_logged >= 3 and all(e.nutrients.get(R.KCAL) is not None for e in eaten):
            kcal = _sum(eaten, R.KCAL)
            if kcal < R.ENERGY_LOW_INSIGHT_FRACTION * kcal_goal:
                out.append(insight("day.energy.low", "info", R.KCAL,
                                   f"Calories were {M.fmt_int(kcal)} kcal, {M.pct(kcal / kcal_goal)} % of your "
                                   f"{M.fmt_int(kcal_goal)} kcal goal. Eating too little can cause muscle loss; fats such as "
                                   "olive oil add calories without potassium or phosphorus.",
                                   {"value": M.whole(kcal), "goal": M.whole(kcal_goal)}, (), ["eating-enough"]))
        # All good.
        if not any(i["severity"] in ("warning", "attention") for i in out):
            within = []
            for key in (R.K, R.P, R.NA, R.FLUID):
                t = R.target_max(targets.get(key))
                if t is not None and _sum(eaten, key) <= t:
                    within.append(M.NUTRIENT_WORD[key])
            if within:
                verb = "all stayed" if len(within) > 1 else "stayed"
                plural = "targets" if len(within) > 1 else "target"
                out.append(insight("day.all_good", "good", None,
                                   f"{M.capitalise(M.join_and(within))} {verb} within your {plural} today."))
    return {
        "status": "ok",
        "rules_version": R.RULES_VERSION,
        "date": ctx.date,
        "insights": order_insights(out),
        "planned_excluded": planned,
        "notes": [M.DISCLAIMER],
    }


def _interdialytic(ctx: GuidanceContext, eaten: Sequence[DayEntry]) -> dict[str, Any] | None:
    if ctx.profile.dialysis != "hemodialysis" or not ctx.profile.dialysis_days:
        return None
    interval = interdialytic_interval(ctx.date, ctx.profile.dialysis_days)
    if interval is None:
        return None
    since, days = interval["since"], int(interval["days"])
    parts: list[str] = []
    worst = "ok"
    numbers: dict[str, Any] = {"since": since, "days": days}
    first_key: str | None = None
    for key in (R.K, R.FLUID):
        t = R.target_max(ctx.profile.targets.get(key))
        if t is None:
            continue
        total = _sum([h for h in ctx.history if since <= h.date < ctx.date], key) + _sum(eaten, key)
        limit = t * days
        fraction = total / limit
        level = "over" if fraction > 1.0 else "caution" if fraction >= ctx.profile.warn_fraction else "ok"
        if level == "ok":
            continue
        worst = "over" if level == "over" or worst == "over" else "caution"
        unit = NUTRIENT_BY_KEY[key].unit
        parts.append(f"{M.NUTRIENT_WORD[key]} adds up to {M.fmt_amount(key, total)} {unit} of "
                     f"{M.fmt_amount(key, limit)} {unit}")
        numbers[key] = {"total": M.whole(total), "limit": M.whole(limit)}
        first_key = first_key or key
    if not parts:
        return None
    weekday = _WEEKDAY[_date.fromisoformat(since).weekday()]
    sev = "warning" if worst == "over" else "attention"
    msg = f"Since dialysis on {weekday}, {M.join_and(parts)} for {_plural(days, 'day')}."
    return insight("day.interdialytic", sev, first_key, msg, numbers, (), ["dialysis-days"])


# --------------------------------------------------------------------------- #
# Period
# --------------------------------------------------------------------------- #


def _by_day(entries: Iterable[HistoryEntry]) -> dict[str, list[HistoryEntry]]:
    out: dict[str, list[HistoryEntry]] = {}
    for e in entries:
        out.setdefault(e.date, []).append(e)
    return out


def period_insights(profile: Profile, prefs: Prefs, start: str, end: str, entries: Sequence[HistoryEntry],
                    previous: Sequence[HistoryEntry] = ()) -> dict[str, Any]:
    """``GET /api/guidance/insights/period`` over the eaten ``entries`` of ``start``…``end`` (TV-I2, TV-I3)."""
    start_d, end_d = _date.fromisoformat(start), _date.fromisoformat(end)
    span = (end_d - start_d).days + 1
    days = _by_day(e for e in entries if start <= e.date <= end)
    logged = sorted(days)
    n = len(logged)
    base = {"status": "ok", "rules_version": R.RULES_VERSION, "start": start, "end": end, "days": span,
            "logged_days": n, "notes": [M.DISCLAIMER]}
    if n < R.MIN_LOGGED_DAYS:
        base["insights"] = [insight("period.too_few_days", "info", None, "Log at least 3 days to see weekly insights.",
                                    {"logged_days": n, "needed": R.MIN_LOGGED_DAYS})]
        return base
    targets = profile.targets
    dialysis = profile.dialysis != "none"
    week_word = "this week" if span == 7 else f"in these {span} days"
    all_entries = [e for d in logged for e in days[d]]
    out: list[dict[str, Any]] = []
    if n < span:
        out.append(insight("period.coverage", "info", None,
                           f"You logged {n} of {span} days; averages use logged days only.",
                           {"logged_days": n, "days": span}))
    day_totals = {d: {k: _sum(days[d], k) for k in (R.K, R.P, R.NA, R.FLUID, R.PROTEIN, R.KCAL, R.CARBS)} for d in logged}

    def average(key: str) -> float:
        return sum(day_totals[d][key] for d in logged) / n

    # Week-judged averages above target: phosphorus, protein (max), calories.
    for key in (R.P, R.PROTEIN, R.KCAL):
        t = R.target_max(targets.get(key))
        if t is None:
            continue
        avg = average(key)
        if avg <= t:
            continue
        above = sum(1 for d in logged if day_totals[d][key] > t)
        src = sources(all_entries, key)
        unit = NUTRIENT_BY_KEY[key].unit
        msg = (f"{_LABEL[key]} averaged {M.fmt_amount(key, avg)} {unit} a day on the {n} days you logged, above your "
               f"{M.fmt_amount(key, t)} {unit} target. It was above target on {above} of {n} days")
        if len(src) >= 2:
            msg += f"; the main sources were {src[0]['short_name']} and {src[1]['short_name']}."
        elif len(src) == 1:
            msg += f"; the main source was {src[0]['short_name']}."
        else:
            msg += "."
        out.append(insight(f"period.{key}.average_over", "attention", key, msg,
                           {"average": M.whole(avg), "target": M.whole(t), "days_above": above, "logged_days": n},
                           src, [T.NUTRIENT_TOPIC[key]]))
    pmin = R.target_min(targets.get(R.PROTEIN))
    if dialysis and pmin is not None and average(R.PROTEIN) < pmin:
        avg = average(R.PROTEIN)
        out.append(insight("period.protein.average_low", "attention", R.PROTEIN,
                           f"Protein averaged {M.fmt_g(avg)} g a day, below your {M.fmt_g(pmin)} g minimum.",
                           {"average": R.round_to(avg, 1), "min": M.whole(pmin)}, (), ["protein"]))
    # Day-judged limits over on 2 or more days.
    stayed: list[str] = []
    for key in (R.K, R.NA, R.FLUID):
        t = R.target_max(targets.get(key))
        if t is None:
            continue
        over_days = [d for d in logged if day_totals[d][key] > t]
        if not over_days:
            stayed.append(M.NUTRIENT_WORD[key])
        if len(over_days) < 2:
            continue
        sev = "warning" if 2 * len(over_days) >= n else "attention"
        wd = [_date.fromisoformat(d).weekday() for d in over_days]
        src = sources([e for d in over_days for e in days[d]], key)
        msg = (f"{_LABEL[key]} was over your limit on {len(over_days)} of {n} days "
               f"({', '.join(_WEEKDAY_SHORT[w] for w in wd)}).")
        if len(src) >= 2:
            msg += f" The main sources were {src[0]['short_name']} and {src[1]['short_name']}."
        elif len(src) == 1:
            msg += f" The main source was {src[0]['short_name']}."
        if all(w >= 5 for w in wd):
            msg += " Mostly at the weekend."
        out.append(insight(f"period.{key}.days_over", sev, key, msg,
                           {"days_over": len(over_days), "logged_days": n, "dates": over_days}, src, [T.NUTRIENT_TOPIC[key]]))
    # One meal slot with most of the potassium or sodium.
    for key in (R.K, R.NA):
        if R.target_max(targets.get(key)) is None:
            continue
        total = sum(day_totals[d][key] for d in logged)
        if total <= 0:
            continue
        for meal in R.SLOT_ORDER:
            share = _sum([e for e in all_entries if e.meal == meal], key) / total
            if share >= R.MEAL_SHARE_MIN:
                out.append(insight(f"period.meal_share.{key}", "info", key,
                                   f"{M.capitalise(meal)} gave {M.pct(share)} % of your {M.NUTRIENT_WORD[key]} {week_word}.",
                                   {"meal": meal, "share_pct": M.pct(share)}, (), [T.NUTRIENT_TOPIC[key]]))
                break
    # Carbohydrate consistency per main meal.
    per_meal = R.target_max(targets.get("carbs_per_meal_g"))
    if profile.diabetes != "none" and per_meal is not None:
        tol = float(prefs.carb_tolerance_g)
        stats = []
        for meal in R.MAIN_MEALS:
            values = []
            for d in logged:
                rows = [e for e in days[d] if e.meal == meal and not e.hypo]
                if rows:
                    values.append(_sum(rows, R.CARBS))
            if values:
                within = sum(1 for v in values if abs(v - per_meal) <= tol)
                stats.append((meal, within, len(values), min(values), max(values)))
        if stats:
            best = max(stats, key=lambda s: (s[1] / s[2], s[2], -R.MAIN_MEALS.index(s[0])))
            worst = min(stats, key=lambda s: (s[1] / s[2], -s[2], R.MAIN_MEALS.index(s[0])))
            msg = (f"{M.capitalise(best[0])} carbs were within {M.fmt_g(tol)} g of your {M.fmt_g(per_meal)} g goal on "
                   f"{best[1]} of {best[2]} days.")
            if worst[0] != best[0] and worst[1] < worst[2]:
                msg += f" {M.capitalise(worst[0])} varied more ({M.fmt_g(worst[3])}–{M.fmt_g(worst[4])} g)."
            all_within = all(s[1] == s[2] for s in stats)
            out.append(insight("period.carbs.consistency", "good" if all_within else "info", R.CARBS, msg,
                               {m: {"within": w, "days": c, "min": R.round_to(lo, 1), "max": R.round_to(hi, 1)}
                                for m, w, c, lo, hi in stats}, (), ["carb-counting"]))
    # Low treatments.
    hypo = [e for e in all_entries if e.hypo]
    if len(hypo) >= R.PERIOD_HYPO_MIN:
        out.append(insight("period.hypo.count", "info", R.CARBS,
                           f"You logged {len(hypo)} low-glucose treatments {week_word}. Your diabetes team may want to know.",
                           {"count": len(hypo)}, (), ["treating-a-low"]))
    # Phosphate additives.
    additive_days = [d for d in logged if any("phosphate_additive" in e.flags for e in days[d])]
    if len(additive_days) >= 2:
        counts: "OrderedDict[Any, list[Any]]" = OrderedDict()
        for d in logged:
            for e in days[d]:
                if "phosphate_additive" in e.flags:
                    ident = e.food_id
                    counts.setdefault(ident, [e.name, 0])[1] += 1
        rows = sorted(counts.values(), key=lambda r: (-r[1], r[0].casefold()))[:3]
        shorts = short_names([r[0] for r in rows])
        listed = ", ".join(f"{s} ({_plural(c, 'time')})" for s, (_, c) in zip(shorts, rows))
        out.append(insight("period.additives", "info", R.P,
                           f"Phosphate-additive foods were eaten on {len(additive_days)} of {n} days: {listed}.",
                           {"days": len(additive_days), "logged_days": n}, (), ["phosphate-additives"]))
    # Change against the previous period.
    prev_days = _by_day(previous)
    if len(prev_days) >= R.MIN_LOGGED_DAYS:
        for key in (R.K, R.P):
            if R.target_max(targets.get(key)) is None:
                continue
            prev_avg = sum(_sum(v, key) for v in prev_days.values()) / len(prev_days)
            if prev_avg <= 0:
                continue
            change = (average(key) - prev_avg) / prev_avg
            if abs(change) >= R.PERIOD_CHANGE_MIN:
                word = "less" if change < 0 else "more"
                before = "the week before" if span == 7 else "the period before"
                out.append(insight(f"period.change.{key}", "good" if change < 0 else "info", key,
                                   f"{_LABEL[key]} averaged {M.pct(abs(change))} % {word} than {before}.",
                                   {"change_pct": M.pct(change), "previous_average": M.whole(prev_avg)}, (),
                                   [T.NUTRIENT_TOPIC[key]]))
    if not any(i["severity"] in ("warning", "attention") for i in out) and stayed:
        verb = "stayed"
        out.append(insight("period.all_good", "good", None,
                           f"{M.capitalise(M.join_and(stayed))} {verb} within your limit on all {n} days you logged.",
                           {"logged_days": n}))
    base["insights"] = order_insights(out)
    return base


def period_bounds(start: str | None, end: str | None, today: str) -> tuple[str, str, str, str]:
    """``(start, end, previous_start, previous_end)``: default the 7 days ending yesterday."""
    if end is None and start is None:
        end_d = _date.fromisoformat(today) - timedelta(days=1)
        start_d = end_d - timedelta(days=R.PERIOD_DEFAULT_DAYS - 1)
    else:
        start_d = _date.fromisoformat(start) if start else _date.fromisoformat(end) - timedelta(days=R.PERIOD_DEFAULT_DAYS - 1)  # type: ignore[arg-type]
        end_d = _date.fromisoformat(end) if end else start_d + timedelta(days=R.PERIOD_DEFAULT_DAYS - 1)
    span = (end_d - start_d).days + 1
    prev_end = start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return start_d.isoformat(), end_d.isoformat(), prev_start.isoformat(), prev_end.isoformat()
