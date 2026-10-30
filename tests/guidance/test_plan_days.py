"""Several days at once (design note 23): ``planner.plan_days``.

Day 1 is exactly ``plan_day`` of that date; later days see the earlier ones (the dialysis interval, the phosphorus week, the
repeat rule and the food rotation); nothing planned is ever a low treatment or counted as eaten; a food a person marked
"Not for me" is never planned on any day."""
from __future__ import annotations

import fixtures as fx
import pytest
from app.guidance import planner
from app.guidance import rules as R
from app.guidance.budget import meal_room
from app.guidance.score import score_meal, today_stats
from app.guidance.state import Prefs


@pytest.fixture(scope="module")
def real_foods():
    return fx.real_foods()


def items(meal: dict) -> list[tuple[int, float]]:
    return [(i["food_id"], i["servings"]) for i in meal["items"]]


def food_set(meal: dict) -> frozenset[int]:
    return frozenset(i["food_id"] for i in meal["items"])


def real_ctx(real_foods, **kw):
    return fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=(), **kw)


def test_the_first_day_is_the_one_day_plan(real_foods):
    ctx = fx.context()
    one = planner.plan_day(ctx)
    many = planner.plan_days(ctx, [ctx.day, (), ()])
    first = many["days"][0]
    assert first["date"] == fx.DATE and many["start"] == fx.DATE and many["end"] == "2026-10-07"
    assert [{k: v for k, v in m.items() if k != "repeated"} for m in first["meals"]] == one["meals"]
    assert first["day_after"]["projected_totals"] == one["day_after"]["projected_totals"]
    assert many["apply"]["entries"][: len(one["apply"]["entries"])] == one["apply"]["entries"]
    real = real_ctx(real_foods)
    assert [m["items"] for m in planner.plan_days(real, [()])["days"][0]["meals"]] == \
        [m["items"] for m in planner.plan_day(real)["meals"]]


def test_a_week_never_plans_the_same_meal_twice_in_a_row(real_foods):
    r = planner.plan_days(real_ctx(real_foods), [()] * 7)
    assert len(r["days"]) == 7 and r["end"] == "2026-10-11"
    for i, day in enumerate(r["days"]):
        assert [m["meal"] for m in day["meals"]] == list(R.SLOT_ORDER)
        for m in day["meals"]:
            assert m["status"] != "no_fit" and not m["repeated"]
            for before in r["days"][max(0, i - R.PLAN_REPEAT_DAYS):i]:
                same = next(b for b in before["meals"] if b["meal"] == m["meal"])
                assert food_set(m) != food_set(same), (day["date"], m["meal"])
        assert day["day_after"]["new_alerts"] == []
    # Foods rotate: no dinner food is on every day.
    dinners = [food_set(next(m for m in d["meals"] if m["meal"] == "dinner")) for d in r["days"]]
    assert not frozenset.intersection(*dinners)


def test_a_meal_may_repeat_only_when_nothing_else_fits():
    only_rice = Prefs(exclude_food_ids=frozenset({2, 3, 4, 5, 6, 7, 8, 11, 13, 14}))
    r = planner.plan_days(fx.context(day=(), history=(), prefs=only_rice, saved=()), [()] * 3, ["dinner"])
    dinners = [d["meals"][0] for d in r["days"]]
    assert [items(m) for m in dinners] == [[(1, 1.25)]] * 3
    assert [m["repeated"] for m in dinners] == [False, True, True]


def test_a_saved_meal_comes_back_after_two_days():
    r = planner.plan_days(fx.context(day=(), history=()), [()] * 4, ["dinner"])
    dinners = [d["meals"][0] for d in r["days"]]
    assert dinners[0]["source"] == "saved" and dinners[0]["name"] == "Usual dinner"
    assert all(m["source"] == "built" for m in dinners[1:3])
    assert dinners[3]["source"] == "saved" and not any(m["repeated"] for m in dinners)


def test_a_food_on_a_day_before_costs_the_meal_score():
    fs = fx.foods()
    ctx = fx.context(day=(), history=())
    room = meal_room(ctx, "dinner")
    meal = [(fs[3], 1.0), (fs[1], 1.0)]
    base = today_stats(())
    plain = score_meal(meal, room, base, False)
    from dataclasses import replace
    assert score_meal(meal, room, replace(base, recent={3: 2}), False) == R.round_score(plain - 2 * R.PLAN_RECENT_FOOD_PENALTY)


def test_the_earlier_days_count_in_the_dialysis_interval():
    fs = fx.foods()
    targets = {**fx.TARGETS, "fluid_ml": 1500}
    monday = (fx.entry(fs[2], "lunch", 3, entry_id=5),)  # 3 baked potatoes: 2,775 mg potassium, over the 2,500 mg limit
    hd = dict(targets=targets, dialysis="hemodialysis", dialysis_days=(0, 2, 4))
    r = planner.plan_days(fx.context(day=monday, history=(), date="2026-10-05", **hd), [monday, ()], ["dinner"])
    assert [d["dialysis_day"] for d in r["days"]] == [True, False]
    tuesday = r["days"][1]["meals"][0]["room"]["potassium_mg"]
    assert tuesday["basis"] == "interdialytic" and tuesday["allowance_today"] < 2500
    # Planned on its own, Tuesday does not know about Monday's plan or log in the future.
    alone = planner.plan_day(fx.context(day=(), history=(), date="2026-10-06", **hd), ["dinner"])
    assert alone["meals"][0]["room"]["potassium_mg"]["basis"] == "day"


def test_the_earlier_days_count_in_the_phosphorus_week():
    fs = fx.foods()
    heavy = (fx.entry(fs[14], "lunch", 4, entry_id=7),)  # 1,200 mg phosphorus at lunch, over the 1,000 mg target
    ctx = fx.context(day=heavy, history=())
    r = planner.plan_days(ctx, [heavy, ()], ["dinner"])
    room = r["days"][1]["meals"][0]["room"]["phosphorus_mg"]
    alone = planner.plan_day(fx.context(day=(), history=(), date="2026-10-06"), ["dinner"])["meals"][0]["room"]["phosphorus_mg"]
    assert room["basis"] == "week_average" and room["allowance_today"] < alone["allowance_today"]


def test_nothing_planned_is_a_low_treatment_or_eaten_and_not_for_me_stays_out(real_foods):
    egg = fx.by_name(real_foods, "Egg white")
    rice = fx.by_name(real_foods, "Rice, white, long-grain, cooked")
    ctx = real_ctx(real_foods, prefs=Prefs(exclude_food_ids=frozenset({egg.id, rice.id})))
    r = planner.plan_days(ctx, [()] * 5)
    entries = r["apply"]["entries"]
    assert entries and all(e["status"] == "planned" and e["purpose"] == "none" for e in entries)
    for e in entries:
        f = real_foods[e["food_id"]]
        assert not (f.hypo or f.avoid or f.alcohol or f.ingredient), f.name
        assert e["food_id"] not in (egg.id, rice.id)
    assert {e["date"] for e in entries} == {d["date"] for d in r["days"]}


def test_a_low_treatment_already_logged_stays_and_its_meal_is_not_planned_over():
    fs = fx.foods()
    low = (fx.entry(fs[10], "snack", purpose="hypo", entry_id=9),)
    r = planner.plan_days(fx.context(day=low, history=()), [low, low])
    for d in r["days"]:
        assert "snack" not in [m["meal"] for m in d["meals"]]  # the slot already holds food
    assert all(e["food_id"] != 10 for e in r["apply"]["entries"])


def test_a_day_with_every_meal_logged_adds_nothing():
    fs = fx.foods()
    full = tuple(fx.entry(fs[1], m, entry_id=20 + i) for i, m in enumerate(R.SLOT_ORDER))
    r = planner.plan_days(fx.context(day=(), history=()), [(), full], ["dinner", "lunch"])
    assert [m["meal"] for m in r["days"][0]["meals"]] == ["lunch", "dinner"]
    assert [m["meal"] for m in r["days"][1]["meals"]] == ["lunch", "dinner"]  # ticked meals are planned anyway
    r = planner.plan_days(fx.context(day=(), history=()), [(), full])
    assert r["days"][1]["meals"] == [] and all(e["date"] == fx.DATE for e in r["apply"]["entries"])


def test_the_shopping_list_sums_the_days():
    r = planner.plan_days(fx.context(day=(), history=()), [()] * 3, ["dinner"])
    by_food: dict[int, list[float]] = {}
    for e in r["apply"]["entries"]:
        by_food.setdefault(e["food_id"], []).append(e["servings"])
    shop = {i["food_id"]: i for i in r["shopping"]["items"]}
    assert set(shop) == set(by_food)
    for fid, servings in by_food.items():
        assert shop[fid]["servings"] == R.round_to(sum(servings), 3) and shop[fid]["days"] == len(servings)
    rice = shop[1]
    assert rice["food_name"] == "Rice, white, cooked" and rice["grams"] == R.round_to(rice["servings"] * 158, 1)
    names = [i["food_name"].casefold() for i in r["shopping"]["items"]]
    assert names == sorted(names)


def test_a_value_a_food_does_not_list_is_counted_for_the_day():
    fs = fx.foods()
    unknown = fx.food((15, "Soup (test)", "Soups", "1 cup", 240, 10, 3, None, 40, 300, 200, ()))
    food_map = {**fs, 15: unknown}
    day = (fx.entry(unknown, "lunch", entry_id=3),)
    r = planner.plan_days(fx.context(day=day, history=(), food_map=food_map), [day, ()], ["dinner"])
    assert r["days"][0]["day_after"]["projected_unknown"]["potassium_mg"] == 1
    assert "potassium_mg" not in r["days"][1]["day_after"]["projected_unknown"]


def test_variant_and_days_are_bounded():
    r = planner.plan_days(fx.context(day=(), history=()), [()], ["dinner"], variant=9)
    assert r["variant"] == R.VARIANT_MAX
    assert R.PLAN_DAYS_MAX == 60 and R.PLAN_DAYS_AI_MAX == 31 and R.PLAN_DAYS_CEILING == 90 and R.PLAN_REPEAT_DAYS == 2


# --------------------------------------------------------------------------- #
# The owner's answers (note 23 §12)
# --------------------------------------------------------------------------- #


def meal_of(day: dict, meal: str) -> dict:
    return next(m for m in day["meals"] if m["meal"] == meal)


def test_a_meal_that_may_repeat_is_the_same_every_day(real_foods):
    ctx = real_ctx(real_foods)
    rotating = planner.plan_days(ctx, [()] * 5, ["breakfast"])
    assert len({food_set(d["meals"][0]) for d in rotating["days"]}) > 1  # without the choice, breakfast rotates
    same = planner.plan_days(ctx, [()] * 5, ["breakfast"], repeat_meals=["breakfast"])
    breakfasts = [d["meals"][0] for d in same["days"]]
    assert len({tuple(items(m)) for m in breakfasts}) == 1 and not any(m["repeated"] for m in breakfasts)
    # Only the ticked meal may repeat: lunch comes back the next day (the rule would forbid it), dinner never does.
    mixed = planner.plan_days(ctx, [()] * 4, repeat_meals=["lunch"])
    lunches = [food_set(meal_of(d, "lunch")) for d in mixed["days"]]
    dinners = [food_set(meal_of(d, "dinner")) for d in mixed["days"]]
    assert any(lunches[i] == lunches[i - 1] for i in range(1, 4))
    assert all(dinners[i] not in dinners[max(0, i - 2):i] for i in range(1, 4))
    # The first day is still "Plan a day…".
    assert [m["items"] for m in same["days"][0]["meals"]] == [m["items"] for m in planner.plan_day(ctx, ["breakfast"])["meals"]]


def test_a_saved_meal_marked_ok_to_repeat_comes_back_every_day():
    ok = Prefs(repeat_ok_meal_ids=frozenset({fx.SAVED_MEAL.id}))
    r = planner.plan_days(fx.context(day=(), history=(), prefs=ok), [()] * 4, ["dinner"])
    dinners = [d["meals"][0] for d in r["days"]]
    assert all(m["source"] == "saved" and m["name"] == "Usual dinner" for m in dinners)
    assert not any(m["repeated"] for m in dinners)
    assert len({m["score"] for m in dinners}) == 1  # no rotation cost: the same score every day


def test_a_meal_made_only_of_ok_to_repeat_foods_may_come_back():
    only_rice = frozenset({2, 3, 4, 5, 6, 7, 8, 11, 13, 14})
    plain = planner.plan_days(fx.context(day=(), history=(), prefs=Prefs(exclude_food_ids=only_rice), saved=()), [()] * 3,
                              ["dinner"])
    assert [m["repeated"] for d in plain["days"] for m in d["meals"]] == [False, True, True]
    ok = Prefs(exclude_food_ids=only_rice, repeat_ok_food_ids=frozenset({1}))
    r = planner.plan_days(fx.context(day=(), history=(), prefs=ok, saved=()), [()] * 3, ["dinner"])
    assert [items(d["meals"][0]) for d in r["days"]] == [[(1, 1.25)]] * 3
    assert not any(m["repeated"] for d in r["days"] for m in d["meals"])  # not "nothing else fits": it is allowed


def test_an_ok_to_repeat_food_does_not_rotate(real_foods):
    pasta = fx.by_name(real_foods, "Pasta, cooked")
    plain = planner.plan_days(real_ctx(real_foods), [()] * 6, ["lunch", "dinner"])
    marked = planner.plan_days(real_ctx(real_foods, prefs=Prefs(repeat_ok_food_ids=frozenset({pasta.id}))), [()] * 6,
                               ["lunch", "dinner"])

    def days_with_pasta(r: dict) -> int:
        return sum(1 for d in r["days"] if any(i["food_id"] == pasta.id for m in d["meals"] for i in m["items"]))

    assert days_with_pasta(plain) < 6 and days_with_pasta(marked) == 6


def test_the_snack_is_planned_only_when_asked():
    ctx = fx.context(day=(), history=())
    off = planner.plan_days(ctx, [()] * 2, snack=False)
    assert all("snack" not in [m["meal"] for m in d["meals"]] for d in off["days"])
    on = planner.plan_days(ctx, [()] * 2, snack=True)
    assert all([m["meal"] for m in d["meals"]] == list(R.SLOT_ORDER) for d in on["days"])
    ticked = planner.plan_days(ctx, [()] * 2, ["dinner"], snack=True)
    assert all([m["meal"] for m in d["meals"]] == ["dinner", "snack"] for d in ticked["days"])
    named = planner.plan_days(ctx, [()] * 2, ["snack"], snack=False)  # a meal list that names the snack plans it
    assert all([m["meal"] for m in d["meals"]] == ["snack"] for d in named["days"])


def test_the_first_days_past_meals_are_skipped_and_a_low_treatment_stays():
    fs = fx.foods()
    low = (fx.entry(fs[10], "breakfast", purpose="hypo", entry_id=9),)
    ctx = fx.context(day=low, history=())
    r = planner.plan_days(ctx, [low, (), ()], skip_first_day=["lunch", "dinner"], snack=False)
    assert r["days"][0]["meals"] == []  # breakfast holds the low treatment; lunch and dinner are past
    assert [m["meal"] for m in r["days"][1]["meals"]] == ["breakfast", "lunch", "dinner"]  # later days are whole
    assert all(e["food_id"] != 10 and e["purpose"] == "none" for e in r["apply"]["entries"])
    assert all(e["date"] != fx.DATE for e in r["apply"]["entries"])
    # Skipping is only for the first day, and only for the meals named.
    some = planner.plan_days(fx.context(day=(), history=()), [(), ()], skip_first_day=["breakfast"])
    assert [m["meal"] for m in some["days"][0]["meals"]] == ["lunch", "dinner", "snack"]
    assert [m["meal"] for m in some["days"][1]["meals"]] == list(R.SLOT_ORDER)


def test_sixty_days_plan_in_a_sensible_time(real_foods):
    import time

    ctx = real_ctx(real_foods)
    start = time.perf_counter()
    r = planner.plan_days(ctx, [()] * R.PLAN_DAYS_MAX, snack=True)
    took = time.perf_counter() - start
    assert len(r["days"]) == 60 and r["end"] == "2026-12-03"
    assert took < 20.0, took  # about 2 s on a laptop; generous for a busy CI runner
    # The shopping list stays short: it sums by food, so 60 days list far fewer lines than foods planned.
    assert len(r["shopping"]["items"]) < len(r["apply"]["entries"]) / 10
    assert all(1 <= i["days"] <= 60 for i in r["shopping"]["items"])
