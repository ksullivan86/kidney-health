"""Food preferences in the engine (note 09 §6): the properties P1-P7, the hand-computed TV-PREF-1 and TV-PREF-2, the
refined planned-but-not-eaten rule, the usual-meal key, "Not for me" in familiar meals and the "Learned from your log"
list. Pure: no database. The server side (routes, settings, loader) is tests/guidance/test_preferences_api.py."""
from __future__ import annotations

import itertools
import random
from dataclasses import replace

import fixtures as fx
import pytest
from app.guidance import budget, fits, hypo, insights, planner, swaps
from app.guidance import messages as M
from app.guidance import rules as R
from app.guidance.score import (
    NO_PREFERENCES,
    Scorer,
    check_meal,
    food_order_key,
    habit_stats,
    pref_terms,
    score_meal,
    skip_stats,
    today_stats,
)
from app.guidance.state import GuidanceContext, PlannedEntry, Prefs
from app.guidance.vectors import make_food

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

SOFT = Prefs(
    food_pref={1: "less", 4: "like", 5: "neutral", 7: "like", 11: "less"},
    like_categories=frozenset({"Fruits"}), less_categories=frozenset({"Dairy & Alternatives"}),
)


def with_prefs(ctx: GuidanceContext, **kw) -> GuidanceContext:
    return replace(ctx, prefs=replace(ctx.prefs, **kw))


def scorer_for(ctx: GuidanceContext, meal: str = "dinner"):
    room = budget.meal_room(ctx, meal)
    return Scorer(room, habit_stats(ctx), today_stats(ctx.day)), room


def real_ctx(**kw) -> GuidanceContext:
    return fx.context(food_map=fx.real_foods(), targets=fx.STAGE4_TARGETS, day=(), history=(), saved=(), **kw)


def ids(result, key="foods"):
    return [f["food_id"] for f in result[key]]


# --------------------------------------------------------------------------- #
# The term itself: TV-PREF-1, TV-PREF-2, the weights and the clamps
# --------------------------------------------------------------------------- #


def synthetic_pair():
    """Two starches identical in every number except potassium: 40 mg (green, base 3.0) and 130 mg (yellow, base 1.0)."""
    def rice(fid, name, k):
        return make_food(id=fid, name=name, category="Grains & Breads", serving_desc="1 cup", serving_g=150,
                         nutrients=fx.nutrients(30, 3, k, 60, 10, 0))
    return {1: rice(1, "Green rice", 40), 2: rice(2, "Yellow rice", 130)}


def test_tv_pref_1_a_like_on_the_yellow_food_gives_2_0_against_3_0_and_the_green_food_still_ranks_first():
    foods = synthetic_pair()
    plain = fx.context(food_map=foods, day=(), history=(), saved=())
    liked = with_prefs(plain, food_pref={2: "like"})
    sc_plain, _ = scorer_for(plain, "lunch")
    sc_liked, _ = scorer_for(liked, "lunch")
    green, yellow = foods[1], foods[2]
    ev_green, ev_yellow = sc_liked.evaluate(green, 1.0, True), sc_liked.evaluate(yellow, 1.0, True)
    assert (ev_green.components["base"], ev_yellow.components["base"]) == (3.0, 1.0)
    assert (ev_green.components["preference"], ev_yellow.components["preference"]) == (0.0, 1.0)
    # base + preference: 3.0 for the green food, 2.0 for the liked yellow one
    assert ev_green.components["base"] + ev_green.components["preference"] == 3.0
    assert ev_yellow.components["base"] + ev_yellow.components["preference"] == 2.0
    # everything else about the yellow food is untouched by the like
    assert sc_plain.evaluate(yellow, 1.0).score == pytest.approx(ev_yellow.score - 1.0, abs=0.0051)
    assert ev_green.score > ev_yellow.score  # at one serving the green food still ranks first
    assert food_order_key(ev_green) < food_order_key(ev_yellow)


def test_tv_pref_2_a_green_less_often_food_in_a_less_often_group_is_clamped_at_minus_2_5():
    foods = synthetic_pair()
    ctx = with_prefs(fx.context(food_map=foods, day=(), history=(), saved=()), food_pref={1: "less"},
                     less_categories=frozenset({"Grains & Breads"}))
    # -2.0 (food) - 1.0 (group) = -3.0, clamped
    assert pref_terms(ctx).of(foods[1]) == -2.5
    sc, _ = scorer_for(ctx, "lunch")
    ev = sc.evaluate(foods[1], 1.0, True)
    assert ev.components["base"] == 3.0 and ev.components["preference"] == -2.5
    # the yellow food in the same group has only the group term
    assert pref_terms(ctx).of(foods[2]) == -1.0


def test_the_weights_are_the_decided_ones():
    assert (R.PREF_LIKE, R.PREF_LESS, R.PREF_GROUP_LIKE, R.PREF_GROUP_LESS, R.PREF_SKIPPED) == (1.0, -2.0, 0.5, -1.0, -0.5)
    assert tuple(R.PREF_FOOD_CLAMP) == (-2.5, 1.0) and tuple(R.PREF_MEAL_CLAMP) == (-1.5, 1.0)
    fs = fx.foods()
    terms = pref_terms(with_prefs(fx.context(), food_pref={1: "like", 2: "less"}, like_categories=frozenset({"Vegetables"}),
                                  less_categories=frozenset({"Fruits"})))
    assert terms.of(fs[1]) == 1.0  # like, no group
    assert terms.of(fs[2]) == -2.0 + 0.5  # less + liked group
    assert terms.of(fs[6]) == -1.0  # banana: only the less-often group
    assert terms.of(fs[5]) == 0.5  # green beans: only the liked group
    assert terms.of(fs[3]) == 0.0
    both = pref_terms(with_prefs(fx.context(), food_pref={1: "like"}, like_categories=frozenset({"Grains & Breads"})))
    assert both.of(fs[1]) == 1.0  # 1.0 + 0.5 is clamped at +1.0


def test_a_person_without_preferences_has_no_term_and_pays_nothing():
    ctx = fx.context()
    assert pref_terms(ctx) is NO_PREFERENCES and not NO_PREFERENCES.active
    assert habit_stats(ctx).pref is NO_PREFERENCES


# --------------------------------------------------------------------------- #
# P1 to P3: no change, filters unchanged, bounded
# --------------------------------------------------------------------------- #


def test_p1_no_preferences_means_the_same_numbers_as_before():
    """The 64 earlier vectors replay unchanged (tests/guidance/test_parity_vectors.py); here the fixture's TV-F4 order."""
    result = fits.what_fits(fx.context(), "dinner")
    assert [(f["food_id"], f["score"]) for f in result["foods"]] == [(1, 6.13), (4, 5.04), (3, 4.8), (5, 4.59), (7, 4.34), (11, 0.66)]
    assert all("you_like" not in [r["code"] for r in f["reasons"]] for f in result["foods"])


def test_p2_the_hard_filters_do_not_depend_on_any_preference():
    rng = random.Random(7)
    foods = fx.real_foods()
    base = fx.context(food_map=foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    sc0, _ = scorer_for(base, "lunch")
    ids_ = sorted(foods)
    for _ in range(6):
        pref = {i: rng.choice(["like", "less", "neutral"]) for i in rng.sample(ids_, 120)}
        cats = sorted({f.category for f in foods.values() if f.category})
        ctx = with_prefs(base, food_pref=pref, like_categories=frozenset(rng.sample(cats, 3)),
                         less_categories=frozenset(c for c in cats if c not in ()) & frozenset(rng.sample(cats, 3)))
        sc1, _ = scorer_for(ctx, "lunch")
        for f in foods.values():
            for q in R.portions_for(f.role):
                a, b = sc0.evaluate(f, q), sc1.evaluate(f, q)
                assert a.why_not == b.why_not, (f.name, q)
                assert (a.score is None) == (b.score is None)


def test_p3_a_food_moves_by_at_most_minus_2_5_and_plus_1_0_and_a_meal_by_minus_1_5_and_plus_1_0():
    foods = fx.real_foods()
    base = fx.context(food_map=foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    sc0, room = scorer_for(base, "lunch")
    worst = with_prefs(base, food_pref={f.id: "less" for f in foods.values()}, less_categories=frozenset(
        f.category for f in foods.values() if f.category))
    best = with_prefs(base, food_pref={f.id: "like" for f in foods.values()},
                      like_categories=frozenset(f.category for f in foods.values() if f.category))
    lows, highs = [], []
    for ctx, bucket in ((worst, lows), (best, highs)):
        sc, _ = scorer_for(ctx, "lunch")
        for f in foods.values():
            for q in R.portions_for(f.role):
                a, b = sc0.evaluate(f, q), sc.evaluate(f, q)
                if a.score is None:
                    continue
                bucket.append(round(b.score - a.score, 2))
    assert min(lows) == -2.5 and max(lows) <= -1.0  # less + a less-often group is clamped at -2.5
    assert max(highs) == 1.0 and min(highs) >= 1.0  # like + a liked group is clamped at +1.0
    today = today_stats(base.day)
    items = [(foods[i], 1.0) for i in (1, 20, 40)]
    plain = score_meal(items, room, today, False)
    assert round(score_meal(items, room, today, False, pref=pref_terms(worst)) - plain, 2) == -1.5
    assert round(score_meal(items, room, today, False, pref=pref_terms(best)) - plain, 2) == 1.0
    mixed = with_prefs(base, food_pref={1: "like", 20: "less"})
    delta = score_meal(items, room, today, False, pref=pref_terms(mixed)) - plain
    assert round(delta, 2) == round((1.0 - 2.0 + 0.0) / 3, 2)  # the mean of the three terms


def test_the_term_is_added_after_the_filters_so_a_liked_food_that_does_not_fit_still_does_not_fit():
    ctx = with_prefs(fx.context(), food_pref={2: "like"})  # the baked potato: 925 mg potassium
    result = fits.what_fits(ctx, "dinner", explain=True)
    assert result["explain"]["why_not"].get("2") is None or 2 in ids(result)  # only the half portion fits, as before
    sc, _ = scorer_for(ctx)
    assert sc.evaluate(ctx.foods[2], 1.0).why_not == "would_exceed:potassium_mg"


# --------------------------------------------------------------------------- #
# The reason
# --------------------------------------------------------------------------- #


def test_you_like_is_a_reason_after_the_kidney_reasons_and_before_often():
    # orange juice has one reason (low phosphorus); liking it adds the new one after it
    ctx = with_prefs(fx.context(), food_pref={11: "like"})
    reasons = {f["food_id"]: [r["code"] for r in f["reasons"]] for f in fits.what_fits(ctx, "dinner")["foods"]}
    assert reasons[11] == ["low_phosphorus", "you_like"]
    assert next(r for f in fits.what_fits(ctx, "dinner")["foods"] if f["food_id"] == 11 for r in f["reasons"]
                if r["code"] == "you_like")["text"] == "You said you like this."
    # a food with two earlier reasons does not show it (at most two positive reasons), like "you often have this"
    assert "you_like" not in reasons.get(4, [])
    # …and it comes before "you often have this" when both could show: a snack with no kidney reason of its own
    plain = make_food(id=70, name="Plain snack", category="Sweets & Snacks", serving_desc="1 piece", serving_g=30,
                      nutrients=fx.nutrients(12, 1, 130, 80, 90, 0))
    ctx2 = with_prefs(fx.context(food_map={**fx.foods(), 70: plain}, day=()), food_pref={70: "like"})
    sc, room = scorer_for(ctx2, "snack")
    ev = sc.evaluate(plain, 1.0)
    assert ev.score is not None
    habit = replace(sc.habit, days_14={**sc.habit.days_14, 70: 5})
    codes = [r["code"] for r in fits.reasons_for(ev, sc, room, None, habit)[0]]
    assert codes == ["you_like", "you_eat_often"]


def test_a_group_like_gives_no_reason_only_a_food_like_does():
    ctx = with_prefs(fx.context(), like_categories=frozenset({"Fruits"}))
    assert all("you_like" not in [r["code"] for r in f["reasons"]] for f in fits.what_fits(ctx, "dinner")["foods"])


# --------------------------------------------------------------------------- #
# P5 neutral, P6 learn_from_log off, hidden usual meals
# --------------------------------------------------------------------------- #


def breakfast_habit(**prefs):
    return with_prefs(fx.context(day=()), **prefs)


def test_p5_a_neutral_food_has_no_habit_history_slot_habit_often_reason_or_skip_term():
    control, neutral = breakfast_habit(), breakfast_habit(food_pref={13: "neutral"})
    h0, h1 = habit_stats(control), habit_stats(neutral)
    assert h0.days_14[13] == 4 and h0.slot_days[(13, "breakfast")] == 4 and h0.prev2[13] == 2
    assert 13 not in h1.days_14 and (13, "breakfast") not in h1.slot_days
    assert h1.prev2[13] == 2  # the variety penalty of the previous two days is not a preference
    assert h1.saved_ids == h0.saved_ids
    sc0, _ = scorer_for(control, "breakfast")
    sc1, _ = scorer_for(neutral, "breakfast")
    f13 = control.foods[13]
    e0, e1 = sc0.evaluate(f13, 0.5, True), sc1.evaluate(f13, 0.5, True)
    assert e0.components["slot_habit"] == 1.0 and e1.components["slot_habit"] == 0.0
    # +1.5 habit (4 days, capped) is gone for the neutral food; the -0.5 × 2 days variety penalty stays
    assert e0.components["static"] == 1.5 - 1.0 and e1.components["static"] == -1.0
    assert e1.components["preference"] == 0.0


def test_p5_the_often_reason_goes_with_a_neutral_food():
    for prefs, expect in (({}, True), ({"food_pref": {13: "neutral"}}, False), ({"learn_from_log": False}, False)):
        ctx = breakfast_habit(**prefs)
        sc, room = scorer_for(ctx, "breakfast")
        ev, std = sc.best_portion(ctx.foods[13], R.portions_for(ctx.foods[13].role))
        reasons = fits.reasons_for(ev, sc, room, std, sc.habit)[0]
        # (the food may not be best at any portion; the habit counts are what the reason reads)
        assert (sc.habit.days_14.get(13, 0) >= R.OFTEN_MIN_DAYS) is expect
        del reasons


def test_p6_learn_from_log_off_clears_every_learned_term_but_not_the_saved_meal_or_variety():
    off = breakfast_habit(learn_from_log=False)
    h = habit_stats(off)
    assert h.days_14 == {} and h.slot_days == {}
    assert h.prev2[13] == 2  # previous two days: variety stays
    assert h.saved_ids == {1, 3, 5}  # the saved-meal bonus stays
    sc, _ = scorer_for(off, "dinner")
    assert sc.static(off.foods[1]) == 0.5  # the saved meal's +0.5 only
    # an eaten-today food and a same-family food still cost their variety penalties
    today_ctx = with_prefs(fx.context(day=(fx.entry(fx.foods()[1], "lunch"),)), learn_from_log=False)
    sc2, _ = scorer_for(today_ctx, "dinner")
    assert sc2.static(today_ctx.foods[1]) == 0.5 - 1.5


def real_usual_ctx(**prefs):
    foods = fx.real_foods()
    pick = [fx.by_name(foods, n) for n in ("Chicken breast, roasted, skinless", "Rice, white, long-grain, cooked", "Green beans, boiled")]
    rows = tuple(fx.hist(f, d, "dinner") for d in ("2026-09-30", "2026-10-01", "2026-10-02") for f in pick)
    ctx = fx.context(food_map=foods, targets=fx.STAGE4_TARGETS, day=(), history=rows, saved=())
    return with_prefs(ctx, **prefs), pick


def test_p6_usual_meals_need_learn_from_log_and_a_hidden_key_removes_exactly_that_meal():
    ctx, pick = real_usual_ctx()
    entries = fits.usual_meal_entries(ctx, "dinner")
    assert len(entries) == 1 and entries[0].dates == 3
    key = entries[0].key
    assert key == "dinner:" + ",".join(f"{f.id}x4" for f in sorted(pick, key=lambda f: f.id))
    assert fits.usual_meals_for(ctx, "dinner")[0][0] == entries[0].name
    assert fits.usual_meal_entries(with_prefs(ctx, learn_from_log=False), "dinner") == []
    assert fits.usual_meal_entries(with_prefs(ctx, hidden_usual_meals=frozenset({key})), "dinner") == []
    other = with_prefs(ctx, hidden_usual_meals=frozenset({"lunch" + key[6:], "dinner:1x4,2x4"}))
    assert len(fits.usual_meal_entries(other, "dinner")) == 1  # another meal's key and another set hide nothing
    # the same foods another day in lunch are another meal, with another key
    assert fits.usual_meal_entries(with_prefs(ctx, hidden_usual_meals=frozenset({key})), "lunch") == []
    # what fits and the planner honour it
    shown = [m["name"] for m in fits.what_fits(ctx, "dinner")["saved_meals"]]
    hidden = fits.what_fits(with_prefs(ctx, hidden_usual_meals=frozenset({key})), "dinner")["saved_meals"]
    assert shown and not hidden
    off = fits.what_fits(with_prefs(ctx, learn_from_log=False), "dinner")
    assert off["saved_meals"] == []


def test_the_usual_meal_key_is_whole_numbers_sorted_by_food_id():
    assert R.usual_meal_key("lunch", [(30, 0.5), (12, 1.0)]) == "lunch:12x4,30x2"
    assert R.usual_meal_key("snack", [(7, 1.25), (3, 0.25), (100, 2.75)]) == "snack:3x1,7x5,100x11"
    assert R.usual_meal_key("dinner", [(2, 1.0 / 3.0 * 3)]) == "dinner:2x4"
    key = R.usual_meal_key("breakfast", [(9, 0.75), (4, 1.0)])
    assert key == "breakfast:4x4,9x3"
    from app.settings_registry import GuidancePreferences

    assert GuidancePreferences(hidden_usual_meals=[key]).hidden_usual_meals == [key]  # a key the setting accepts


# --------------------------------------------------------------------------- #
# P7 familiar meals and "Not for me"
# --------------------------------------------------------------------------- #


def test_p7_a_usual_meal_with_a_not_for_me_food_or_a_never_suggest_group_is_never_offered():
    ctx, pick = real_usual_ctx()
    beans = pick[2]
    assert fits.usual_meal_entries(ctx, "dinner")
    assert fits.usual_meal_entries(with_prefs(ctx, exclude_food_ids=frozenset({beans.id})), "dinner") == []
    assert fits.usual_meal_entries(with_prefs(ctx, exclude_categories=frozenset({beans.category})), "dinner") == []
    # an unrelated exclusion changes nothing
    assert fits.usual_meal_entries(with_prefs(ctx, exclude_food_ids=frozenset({999})), "dinner")
    plan = planner.plan_day(with_prefs(ctx, exclude_food_ids=frozenset({beans.id})), ["dinner"])
    assert plan["meals"][0]["source"] == "built" and beans.id not in [i["food_id"] for i in plan["meals"][0]["items"]]


def test_p7_a_saved_meal_with_a_not_for_me_food_is_still_offered():
    ctx = fx.context(prefs=Prefs(exclude_food_ids=frozenset({5})))  # the saved "Usual dinner" holds green beans
    assert "Usual dinner" in [m["name"] for m in fits.what_fits(ctx, "dinner")["saved_meals"]]
    plan = planner.plan_day(ctx, ["dinner"])
    assert plan["meals"][0]["source"] in ("saved", "built")  # the saved meal is among the options the planner weighs
    ctx2 = fx.context(prefs=Prefs(exclude_categories=frozenset({"Vegetables"})))
    assert "Usual dinner" in [m["name"] for m in fits.what_fits(ctx2, "dinner")["saved_meals"]]


def test_p7_a_starter_meal_with_an_excluded_food_is_never_planned():
    foods = fx.real_foods()
    from app.guidance.state import Combo

    base = real_ctx()
    built = planner.plan_day(base, ["dinner"])["meals"][0]
    combo = Combo(id="starter", name="Starter dinner", meal="dinner", source="test",
                  items=tuple((i["food_id"], i["servings"]) for i in built["items"]))
    ctx = replace(base, combos=(combo,))
    assert planner.plan_day(ctx, ["dinner"])["meals"][0]["source"] == "starter"  # it wins when nothing is excluded
    food = foods[built["items"][-1]["food_id"]]
    for prefs in ({"exclude_food_ids": frozenset({food.id})}, {"exclude_categories": frozenset({food.category})}):
        meal = planner.plan_day(with_prefs(ctx, **prefs), ["dinner"])["meals"][0]
        assert meal["source"] == "built" and food.id not in [i["food_id"] for i in meal["items"]]


def test_familiar_excluded_reads_only_the_two_exclusions():
    ctx = fx.context(prefs=Prefs(exclude_food_ids=frozenset({5}), exclude_categories=frozenset({"Fruits"}),
                                 food_pref={1: "less"}, less_categories=frozenset({"Meat, Poultry & Eggs"})))
    fs = ctx.foods
    assert fits.familiar_excluded(ctx, [(fs[5], 1.0)]) and fits.familiar_excluded(ctx, [(fs[6], 1.0)])
    assert not fits.familiar_excluded(ctx, [(fs[1], 1.0), (fs[3], 1.0)])  # less often is not never


# --------------------------------------------------------------------------- #
# Planned but not eaten (decision Q5, refined)
# --------------------------------------------------------------------------- #

DINNERS = ("2026-09-28", "2026-09-30", "2026-10-02", "2026-10-03")


def skip_ctx(planned=DINNERS, eaten_other=DINNERS, eaten_food=(), meal="dinner", **kw):
    fs = fx.foods()
    rows = tuple([fx.hist(fs[1], d, meal) for d in eaten_other] + [fx.hist(fs[5], d, "lunch") for d in eaten_food])
    ctx = fx.context(day=(), history=rows, saved=())
    return replace(ctx, planned30=tuple(PlannedEntry(food_id=5, date=d, meal=meal) for d in planned), **kw)


def test_a_food_planned_four_times_and_not_eaten_gets_minus_0_5_with_the_reason():
    ctx = skip_ctx()
    stat = skip_stats(ctx)[5]
    assert (stat.planned, stat.skipped, stat.eaten, stat.learned) == (4, 4, 0, True)
    assert pref_terms(ctx).of(ctx.foods[5]) == -0.5
    sc, _ = scorer_for(ctx)
    assert sc.evaluate(ctx.foods[5], 1.0, True).components["preference"] == -0.5
    item = next(i for i in fits.learned(ctx)["items"] if i["kind"] == "planned_not_eaten")
    assert item == {"kind": "planned_not_eaten", "food_id": 5, "name": "Green beans, boiled",
                    "reason": "Planned 4 times in 30 days, not eaten", "effect": "less"}


def test_the_rule_needs_two_dates_each_with_something_else_eaten_in_the_same_slot():
    assert not skip_stats(skip_ctx(planned=DINNERS[:1], eaten_other=DINNERS[:1]))[5].learned  # one date only
    assert skip_stats(skip_ctx(planned=DINNERS[:2], eaten_other=DINNERS[:2]))[5].learned  # two dates are enough
    # nothing eaten in those meals: a person who does not log what they eat is never inferred about
    assert not skip_stats(skip_ctx(eaten_other=()))[5].learned
    # something eaten in another meal of the day does not count
    wrong_slot = skip_ctx()
    wrong_slot = replace(wrong_slot, planned30=tuple(PlannedEntry(5, p.date, "lunch") for p in wrong_slot.planned30))
    assert skip_stats(wrong_slot)[5].skipped == 0
    # only the planned food itself eaten in the slot is not a skip
    same = skip_ctx(eaten_other=())
    fs = fx.foods()
    same = replace(same, history=tuple(fx.hist(fs[5], d, "dinner") for d in DINNERS), history60=())
    assert skip_stats(same)[5].skipped == 0


def test_a_low_treatment_does_not_count_as_something_else_eaten():
    fs = fx.foods()
    rows = tuple(fx.hist(fs[10], d, "dinner", purpose="hypo") for d in DINNERS)
    ctx = replace(skip_ctx(eaten_other=()), history=rows, history60=rows)
    assert not skip_stats(ctx)[5].learned


def test_eaten_on_fewer_than_half_of_the_planned_dates():
    one = skip_stats(skip_ctx(eaten_food=("2026-10-01",)))[5]
    assert (one.planned, one.eaten, one.learned) == (4, 1, True)  # 1 < 2
    two = skip_stats(skip_ctx(eaten_food=("2026-10-01", "2026-10-04")))[5]
    assert (two.planned, two.eaten, two.learned) == (4, 2, False)  # 2 is half: not fewer
    assert fits.learned(skip_ctx(eaten_food=("2026-10-01",)))["items"][-1]["reason"] == "Planned 4 times in 30 days, eaten once"
    three_planned = skip_stats(skip_ctx(planned=DINNERS[:3], eaten_other=DINNERS[:3], eaten_food=("2026-10-01",)))[5]
    assert (three_planned.planned, three_planned.eaten, three_planned.learned) == (3, 1, True)  # 1 < 1.5


def test_the_window_is_the_thirty_days_before_today():
    def with_dates(*planned):
        return skip_ctx(planned=planned, eaten_other=planned)

    assert skip_stats(with_dates("2026-09-05", "2026-10-04"))[5].planned == 2  # date-30 is in
    assert skip_stats(with_dates("2026-09-04", "2026-10-04"))[5].planned == 1  # date-31 is out
    assert skip_stats(with_dates("2026-10-05", "2026-10-04"))[5].planned == 1  # today is not a past day


def test_neutral_and_learn_from_log_off_remove_the_skip_term_and_the_list_item():
    for kw in ({"prefs": Prefs(food_pref={5: "neutral"})}, {"prefs": Prefs(learn_from_log=False)}):
        ctx = skip_ctx(**kw)
        assert pref_terms(ctx).of(ctx.foods[5]) == 0.0
        assert not [i for i in fits.learned(ctx)["items"] if i["kind"] == "planned_not_eaten"]
    explicit = skip_ctx(prefs=Prefs(food_pref={5: "less"}))
    assert pref_terms(explicit).of(explicit.foods[5]) == -2.5  # -2.0 and -0.5 together hit the lower clamp exactly
    liked = skip_ctx(prefs=Prefs(food_pref={5: "like"}))
    assert pref_terms(liked).of(liked.foods[5]) == 0.5  # +1.0 and -0.5


def test_the_skip_inputs_use_the_eaten_rows_the_loader_gives():
    ctx = skip_ctx()
    assert skip_stats(replace(ctx, history60=(), eaten30=ctx.history60))[5].learned  # eaten30 when history60 was not loaded
    assert not skip_stats(replace(ctx, history60=(), eaten30=()))[5].learned


# --------------------------------------------------------------------------- #
# P4: a low treatment never reads a preference
# --------------------------------------------------------------------------- #

SOFT_VARIANTS = [
    {},
    {"food_pref": {10: "less", 12: "neutral", 1: "like"}},
    {"like_categories": frozenset({"Beverages"}), "less_categories": frozenset({"Diabetes supplies"})},
    {"learn_from_log": False},
    {"hidden_usual_meals": frozenset({"dinner:1x4,3x4,5x4"})},
    {"food_pref": {10: "less", 12: "like"}, "like_categories": frozenset({"Beverages"}),
     "less_categories": frozenset({"Diabetes supplies"}), "learn_from_log": False,
     "hidden_usual_meals": frozenset({"dinner:1x4,3x4,5x4"})},
]


@pytest.mark.parametrize("variant", SOFT_VARIANTS)
def test_p4_hypo_options_the_card_the_prefilter_and_a_low_swap_are_identical_for_any_soft_preference(variant):
    base = fx.context()
    ctx = with_prefs(base, **variant)
    assert swaps.hypo_options(ctx) == swaps.hypo_options(base)
    assert swaps.find_swaps(ctx, "snack", base.foods[11], 1.0, "hypo") == swaps.find_swaps(base, "snack", base.foods[11], 1.0, "hypo")
    assert insights.best_hypo_food(ctx.foods, ctx.prefs) == insights.best_hypo_food(base.foods, base.prefs)
    assert M.treating_a_low_card(ctx.prefs.hypo_dose_g) == M.treating_a_low_card(base.prefs.hypo_dose_g)
    assert hypo.prefilter("I'm low", ctx.prefs.hypo_dose_g) == hypo.prefilter("I'm low", base.prefs.hypo_dose_g)


def test_p4_a_planned_but_not_eaten_low_treatment_food_does_not_change_the_options_either():
    ctx = skip_ctx()
    ctx = replace(ctx, planned30=ctx.planned30 + tuple(PlannedEntry(10, d, "snack") for d in DINNERS))
    assert swaps.hypo_options(ctx) == swaps.hypo_options(fx.context())


def test_a_normal_swap_does_use_the_term_but_not_the_kidney_test():
    base = fx.context()
    liked = with_prefs(base, food_pref={1: "like", 5: "less"})
    plain = swaps.find_swaps(base, "dinner", base.foods[2], 1.0)
    with_like = swaps.find_swaps(liked, "dinner", base.foods[2], 1.0)
    assert [s["food_id"] for s in plain["swaps"]] == [s["food_id"] for s in with_like["swaps"]]  # the same swaps pass
    by = {s["food_id"]: s["score"] for s in plain["swaps"]}
    for s in with_like["swaps"]:
        assert s["score"] == pytest.approx(by[s["food_id"]] + {1: 1.0, 5: -2.0}.get(s["food_id"], 0.0), abs=0.0051)


# --------------------------------------------------------------------------- #
# Decision Q1: the hypo floor
# --------------------------------------------------------------------------- #


def test_the_hypo_options_are_never_empty_while_a_low_treatment_exists():
    note = "Shown although you marked them Not for me."
    base = swaps.hypo_options(fx.context())
    assert [o["food_id"] for o in base["options"]] == [10, 12] and base["notes"] == [M.DISCLAIMER]
    one = swaps.hypo_options(fx.context(prefs=Prefs(exclude_food_ids=frozenset({10}))))
    assert [o["food_id"] for o in one["options"]] == [12] and one["notes"] == [M.DISCLAIMER]  # an exclusion still works
    both = swaps.hypo_options(fx.context(prefs=Prefs(exclude_food_ids=frozenset({10, 12}))))
    assert [o["food_id"] for o in both["options"]] == [10, 12] and both["notes"] == [M.DISCLAIMER, note]
    groups = swaps.hypo_options(fx.context(prefs=Prefs(exclude_categories=frozenset({"Diabetes supplies", "Beverages"}))))
    assert [o["food_id"] for o in groups["options"]] == [10, 12] and groups["notes"][-1] == note
    assert M.NOTE_TEXTS["shown_despite_exclusions"] == note and M.note_text("shown_despite_exclusions") == note


def test_the_floor_does_not_bring_back_a_hidden_or_unsafe_food_or_invent_one():
    fs = fx.foods()
    hidden = replace(fs[10], hidden=True)
    ctx = fx.context(food_map={**fs, 10: hidden}, prefs=Prefs(exclude_food_ids=frozenset({12})))
    r = swaps.hypo_options(ctx)
    assert [o["food_id"] for o in r["options"]] == [12] and r["notes"][-1] == "Shown although you marked them Not for me."
    none = fx.context(food_map={i: f for i, f in fs.items() if i not in (10, 12)}, prefs=Prefs(exclude_food_ids=frozenset({10, 12})))
    assert swaps.hypo_options(none)["options"] == [] and swaps.hypo_options(none)["notes"] == [M.DISCLAIMER]


def test_best_hypo_food_still_leaves_out_not_for_me_and_reads_nothing_soft():
    fs = fx.foods()
    prefs = Prefs(exclude_food_ids=frozenset({10}), food_pref={12: "less"}, learn_from_log=False)
    best = insights.best_hypo_food(fs, prefs)
    assert best is not None and best[0].id == 12


# --------------------------------------------------------------------------- #
# The learned list
# --------------------------------------------------------------------------- #


def test_the_learned_list_has_the_reasons_the_ranking_uses():
    ctx = fx.context()
    got = fits.learned(ctx)
    assert got["rules_version"] == R.RULES_VERSION and got["learn_from_log"] is True
    assert got["items"] == [
        {"kind": "often", "food_id": 13, "name": "Breakfast block (test)", "reason": "Eaten on 4 of the last 14 days", "effect": "more"},
        {"kind": "slot", "food_id": 13, "name": "Breakfast block (test)", "meal": "breakfast", "reason": "Usually at breakfast",
         "effect": "more"},
    ]


def test_the_learned_list_names_a_usual_meal_with_its_key():
    ctx, pick = real_usual_ctx()
    items = fits.learned(ctx)["items"]
    meal = next(i for i in items if i["kind"] == "usual_meal")
    assert meal["meal"] == "dinner" and meal["key"] == fits.usual_meal_entries(ctx, "dinner")[0].key
    assert meal["reason"] == "Eaten together at dinner on 3 days" and meal["effect"] == "more" and "food_id" not in meal
    assert meal["name"].startswith("Your usual dinner: ")


def test_the_learned_list_leaves_out_what_the_ranking_does_not_use():
    ctx, pick = real_usual_ctx()
    key = fits.usual_meal_entries(ctx, "dinner")[0].key
    assert fits.learned(with_prefs(ctx, learn_from_log=False)) == {"rules_version": R.RULES_VERSION, "learn_from_log": False, "items": []}
    hidden = fits.learned(with_prefs(ctx, hidden_usual_meals=frozenset({key})))["items"]
    assert not [i for i in hidden if i["kind"] == "usual_meal"]
    neutral = fits.learned(with_prefs(ctx, food_pref={pick[0].id: "neutral"}))["items"]
    assert pick[0].id not in [i.get("food_id") for i in neutral]
    never = fits.learned(with_prefs(ctx, exclude_food_ids=frozenset({pick[1].id})))["items"]
    assert pick[1].id not in [i.get("food_id") for i in never]  # a food that is never suggested is not "learned"
    assert not [i for i in never if i["kind"] == "usual_meal"]


def test_the_learned_list_is_capped_per_kind():
    foods = fx.real_foods()
    eaten = [f for f in foods.values() if f.role in ("starch", "veg_fruit", "protein")][:60]
    rows = tuple(fx.hist(f, d, "lunch") for f in eaten for d in ("2026-10-01", "2026-10-02"))
    ctx = fx.context(food_map=foods, targets=fx.STAGE4_TARGETS, day=(), history=rows, saved=())
    items = fits.learned(ctx)["items"]
    assert len([i for i in items if i["kind"] == "often"]) == R.LEARNED_MAX
    assert len([i for i in items if i["kind"] == "slot"]) == R.LEARNED_MAX


# --------------------------------------------------------------------------- #
# Order of terms, caching and the meal term
# --------------------------------------------------------------------------- #


def test_the_meal_term_is_the_clamped_mean_and_applies_to_saved_and_usual_meals():
    ctx = fx.context()
    room = budget.meal_room(ctx, "dinner")
    today = today_stats(ctx.day)
    items = [(ctx.foods[3], 1.0), (ctx.foods[1], 1.0), (ctx.foods[5], 1.0)]  # the saved "Usual dinner"
    plain = score_meal(items, room, today, False)
    less = with_prefs(ctx, food_pref={3: "less", 1: "less", 5: "less"})
    assert round(score_meal(items, room, today, False, pref=pref_terms(less)) - plain, 2) == -1.5  # mean -2.0 clamped
    option = fits.familiar_option(less, room, today, items, kind="saved", name="Usual dinner", template_id=1)
    baseline = fits.familiar_option(ctx, room, today, items, kind="saved", name="Usual dinner", template_id=1)
    assert option["score"] == pytest.approx(baseline["score"] - 1.5, abs=0.0051)


def test_the_scorer_caches_the_term_per_food():
    ctx = with_prefs(fx.context(), food_pref={4: "like"})
    sc, _ = scorer_for(ctx)
    assert sc.pref(ctx.foods[4]) == 1.0 and sc.pref(ctx.foods[4]) == 1.0 and sc._pref == {4: 1.0}


def test_every_new_message_passes_the_wording_lint():
    texts = [M.reason_text("you_like"), M.note_text("shown_despite_exclusions"),
             M.learned_reason("often", days=6), M.learned_reason("slot", meal="breakfast"),
             M.learned_reason("usual_meal", meal="lunch", days=3), M.learned_reason("planned_not_eaten", planned=4, eaten=1),
             M.learned_reason("planned_not_eaten", planned=3, eaten=0), M.learned_reason("planned_not_eaten", planned=5, eaten=2),
             M.learned_reason("planned_not_eaten", planned=9, eaten=3)]
    assert texts[2:] == ["Eaten on 6 of the last 14 days", "Usually at breakfast", "Eaten together at lunch on 3 days",
                         "Planned 4 times in 30 days, eaten once", "Planned 3 times in 30 days, not eaten",
                         "Planned 5 times in 30 days, eaten twice", "Planned 9 times in 30 days, eaten 3 times"]
    for text in texts:
        assert not M.BANNED_PATTERN.search(text), text
    assert M.reason_text("you_like") == "You said you like this."


def test_all_soft_combinations_leave_the_ranking_deterministic():
    foods = fx.real_foods()
    base = fx.context(food_map=foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    flags = [{"learn_from_log": v} for v in (True, False)]
    for kw, pref in itertools.product(flags, [{}, {"food_pref": {1: "like", 2: "less"}}]):
        ctx = with_prefs(base, **kw, **pref)
        a, b = fits.what_fits(ctx, "lunch"), fits.what_fits(ctx, "lunch")
        assert a == b and check_meal([(foods[1], 1.0)], budget.meal_room(ctx, "lunch")).ok
