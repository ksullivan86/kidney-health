"""Note 06 §6.5 plan vectors TV-P1 … TV-P7, the protein top-up, the whole-day repair, the energy note
and the §6.7 "beam versus exhaustive oracle" property."""
from __future__ import annotations

import json
import random

import fixtures as fx
import pytest
from app.guidance import planner
from app.guidance import rules as R
from app.guidance.budget import meal_room
from app.guidance.score import Counter, Scorer, check_meal, habit_stats, score_meal, today_stats
from app.guidance.state import Prefs, SavedMeal
from app.nutrients import suggest_targets


@pytest.fixture(scope="module")
def real_foods():
    return fx.real_foods()


def items(meal: dict) -> list[tuple[int, float]]:
    return [(i["food_id"], i["servings"]) for i in meal["items"]]


def test_tv_p1_fixture_plans_dinner_and_snack():
    r = planner.plan_day(fx.context())
    dinner, snack = r["meals"]
    assert (dinner["meal"], snack["meal"]) == ("dinner", "snack")  # breakfast eaten, lunch planned
    assert dinner["source"] == "built" and items(dinner) == [(4, 1.0), (1, 1.0), (7, 1.25)]
    assert dinner["score"] == 10.71
    # 8.2 g protein: the fixture table gives blueberries 0.5 g (the note's "8.1 g" used 0.4 g).
    assert dinner["totals"] == {"carbs_g": 58.8, "protein_g": 8.2, "potassium_mg": 179, "phosphorus_mg": 88, "sodium_mg": 55}
    assert dinner["why"] == ["59 g carbs, close to your 60 g dinner goal", "Uses 179 of the 750 mg potassium left for dinner"]
    assert items(snack) == [(1, 0.75)] and snack["score"] == 6.49
    assert snack["totals"]["carbs_g"] == 33.8 and snack["totals"]["potassium_mg"] == 41
    assert r["day_after"]["new_alerts"] == [] and r["energy_note"] is None
    assert r["apply"] == {"endpoint": "/api/log/batch", "entries": [
        {"date": fx.DATE, "meal": "dinner", "food_id": 4, "servings": 1.0, "status": "planned", "purpose": "none"},
        {"date": fx.DATE, "meal": "dinner", "food_id": 1, "servings": 1.0, "status": "planned", "purpose": "none"},
        {"date": fx.DATE, "meal": "dinner", "food_id": 7, "servings": 1.25, "status": "planned", "purpose": "none"},
        {"date": fx.DATE, "meal": "snack", "food_id": 1, "servings": 0.75, "status": "planned", "purpose": "none"},
    ]}


def test_tv_p2_hemodialysis_keeps_the_familiar_dinner_and_reaches_the_protein_minimum():
    targets = {**fx.TARGETS, "protein_g": {"min": 70, "max": 84}, "fluid_ml": 1500}
    r = planner.plan_day(fx.context(targets=targets, dialysis="hemodialysis", day=(), history=()))
    by_meal = {m["meal"]: m for m in r["meals"]}
    assert items(by_meal["breakfast"]) == [(3, 0.5), (1, 1.25), (5, 0.5)]
    assert items(by_meal["lunch"]) == [(3, 0.5), (1, 1.25), (7, 0.5)]
    dinner = by_meal["dinner"]
    assert (dinner["source"], dinner["name"], dinner["scale"], dinner["score"]) == ("saved", "Usual dinner", 1.0, 3.94)
    assert dinner["apply_saved"] == {"endpoint": "/api/meals/1/apply",
                                     "body": {"date": fx.DATE, "meal": "dinner", "status": "planned", "scale": 1.0}}
    assert items(by_meal["snack"]) == [(1, 0.75)]
    assert r["day_after"]["projected_totals"]["protein_g"] == 72.8
    assert r["day_after"]["new_alerts"] == []


def test_tv_p3_real_food_list_stage_4(real_foods):
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    r = planner.plan_day(ctx)
    meals = {m["meal"]: m for m in r["meals"]}
    for m in ("breakfast", "lunch", "dinner"):
        assert abs(meals[m]["totals"]["carbs_g"] - 60) <= 10, m
    protein = r["day_after"]["projected_totals"]["protein_g"]
    assert 42 <= protein <= 56
    for m in r["meals"]:
        for i in m["items"]:
            f = real_foods[i["food_id"]]
            assert not (f.ingredient or f.hypo or f.avoid), f.name
    assert r["day_after"]["new_alerts"] == []
    # The plan is low in calories, so the energy note names fats and starch, never more meat (R2).
    note = r["energy_note"]
    assert note is not None and "not with more meat" in note["text"] and note["handbook"] == "eating-enough"
    for f in note["foods"]:
        assert f["nutrients"]["potassium_mg"] <= 50 and f["nutrients"]["calories_kcal"] >= 50


def test_current_stage_4_suggestion_reaches_its_protein_floor(real_foods):
    """v0.3 decision 10 raised the floor to 0.8 g/kg (56 g at 70 kg); the top-up step gets there."""
    targets = suggest_targets(70, "4")["targets"]
    r = planner.plan_day(fx.context(food_map=real_foods, targets=targets, day=(), history=(), saved=()))
    assert r["day_after"]["projected_totals"]["protein_g"] >= targets["protein_g"]["min"]


def test_tv_p4_hemodialysis_on_the_real_food_list(real_foods):
    targets = fx.HD_TARGETS
    r = planner.plan_day(fx.context(food_map=real_foods, targets=targets, dialysis="hemodialysis", day=(), history=(),
                                    saved=()))
    assert r["day_after"]["projected_totals"]["protein_g"] >= 70
    assert r["day_after"]["new_alerts"] == []
    status = r["day_after"]["projected_status"]
    for key in ("potassium_mg", "sodium_mg", "fluid_ml"):
        assert status[key]["level"] != "over"


def test_tv_p4_forced_protein_top_up_grows_a_protein_item_by_half_servings(real_foods, monkeypatch):
    targets = {**fx.HD_TARGETS, "protein_g": {"min": 90, "max": 104}}
    seen: dict[str, list] = {}
    original = planner._protein_topup

    def spy(ctx, plans, before):
        seen["before"] = [list(p.items or []) for p in plans]
        grown = original(ctx, plans, before)
        seen["after"] = [list(p.items or []) for p in plans]
        return grown

    monkeypatch.setattr(planner, "_protein_topup", spy)
    r = planner.plan_day(fx.context(food_map=real_foods, targets=targets, dialysis="hemodialysis", day=(), history=(),
                                    saved=()))
    assert r["protein_topup"], "the minimum of 90 g needs the top-up"
    changed = [(b, a) for b, a in zip(seen["before"], seen["after"]) if b != a]
    assert changed
    for before, after in changed:
        diffs = [(f.role, qa - qb) for (f, qb), (_, qa) in zip(before, after) if qa != qb]
        assert len(diffs) == 1 and diffs[0][0] in R.PROTEIN_ROLES
        assert diffs[0][1] in (0.5, 1.0)  # ½ serving per step, at most 2 steps
    meal = next(m for m in r["meals"] if m["meal"] == r["protein_topup"][0])
    assert meal["score"] is not None  # re-scored after growing


def test_tv_p5_a_saved_dinner_is_never_planned_as_the_snack():
    saved = (SavedMeal(id=1, name="Usual dinner", meal_hint="dinner", items=((4, 1.0), (1, 0.5))),)
    ctx = fx.context(day=(fx.entry(fx.foods()[13], "breakfast"), fx.entry(fx.foods()[14], "lunch"),
                          fx.entry(fx.foods()[4], "dinner")), saved=saved)
    r = planner.plan_day(ctx)
    assert [m["meal"] for m in r["meals"]] == ["snack"]
    assert r["meals"][0]["source"] != "saved"


def test_tv_p6_variant_changes_the_built_dinner_and_output_is_byte_identical(real_foods):
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    a = json.dumps(planner.plan_day(ctx, ["dinner"]), sort_keys=True)
    b = json.dumps(planner.plan_day(ctx, ["dinner"]), sort_keys=True)
    assert a == b
    v1 = planner.plan_day(ctx, ["dinner"], variant=1)
    assert items(v1["meals"][0]) != items(json.loads(a)["meals"][0])
    assert v1["variant"] == 1
    assert planner.plan_day(ctx, ["dinner"], variant=99)["variant"] == R.VARIANT_MAX


def test_tv_p7_no_potassium_room_left(real_foods):
    potato = fx.by_name(real_foods, "Potato, baked, with skin")
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(fx.entry(potato, "breakfast", 3.5),),
                     history=(), saved=())
    meal = planner.plan_day(ctx, ["dinner"])["meals"][0]
    assert meal["room"]["potassium_mg"]["level"] == "over" and meal["room"]["potassium_mg"]["room"] == 0
    assert meal["status"] == "ok"
    for i in meal["items"]:
        assert i["nutrients"]["potassium_mg"] <= R.NEGLIGIBLE[R.K]


def test_tv_p7_nothing_fits_gives_no_fit_with_the_closest_meal():
    fs = fx.foods()
    block = fs[13]
    ctx = fx.context(day=(fx.entry(block, "breakfast", 5.0),), history=(), saved=(),
                     prefs=Prefs(exclude_food_ids=frozenset({4, 5, 7})))  # without the lightest foods nothing fits
    meal = planner.plan_day(ctx, ["dinner"])["meals"][0]
    assert meal["status"] == "no_fit" and meal["items"] == [] and meal["totals"] is None
    assert meal["message"].startswith("Nothing in your foods fits dinner within today's potassium room (0 mg left).")
    assert meal["closest"] is not None and meal["closest"]["reason"].startswith(("would_exceed:", "high_warning:"))


def test_plan_writes_nothing_and_never_places_low_treatments_or_ingredients(real_foods):
    ctx = fx.context(food_map=real_foods, targets=fx.HD_TARGETS, dialysis="hemodialysis", day=(), history=(), saved=())
    before = ctx.day
    r = planner.plan_day(ctx)
    assert ctx.day == before
    for m in r["meals"]:
        for i in m["items"]:
            f = real_foods[i["food_id"]]
            assert not (f.hypo or f.ingredient or f.avoid or f.supplies)


def _near_limit_day(potassium: float) -> tuple:
    """Breakfast already holds ``potassium`` mg of the 2,500 mg limit. Each open slot may use its share plus
    the 50 mg "negligible" allowance, so three slots together can tip the day over: the repair must act."""
    return (fx.entry(fx.foods()[13], "breakfast", override={"potassium_mg": potassium}),)


def test_whole_day_repair_cuts_back_built_items_until_the_day_fits():
    r = planner.plan_day(fx.context(day=_near_limit_day(2400.0), history=(), saved=()))
    assert [m["status"] for m in r["meals"]] == ["ok", "ok", "ok"]
    assert [m["reason"] for m in r["meals"]][:2] == ["reduced:potassium_mg", "reduced:potassium_mg"]
    assert r["day_after"]["projected_status"]["potassium_mg"]["level"] != "over"
    assert r["day_after"]["new_alerts"] == []
    for m in r["meals"]:  # the scores follow the cut-back items
        rebuilt = [(fx.foods()[i["food_id"]], i["servings"]) for i in m["items"]]
        assert m["totals"]["potassium_mg"] == round(sum(f.k * q for f, q in rebuilt))


def test_whole_day_repair_gives_up_after_six_steps_and_says_so():
    r = planner.plan_day(fx.context(day=_near_limit_day(2460.0), history=(), saved=()))
    assert {m["status"] for m in r["meals"]} == {"partial"}
    for m in r["meals"]:
        assert m["reason"] == "day_over:potassium_mg"
        assert m["message"] == (f"This {m['meal']} plan was cut back, but today's potassium would still go over your "
                                "limit; choose a smaller portion or a different food.")
    assert [a["nutrient"] for a in r["day_after"]["new_alerts"]] == ["potassium_mg"]


def test_usual_meals_and_starter_combos_are_familiar_options(real_foods):
    from app.guidance.context import read_combos, resolve_combos

    combos = resolve_combos(real_foods, read_combos())
    assert {c.meal for c in combos} == {"breakfast", "lunch", "dinner", "snack"}
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=(), combos=combos)
    r = planner.plan_day(ctx, with_options=True)
    sources = {o["source"] for opts in r["options"].values() for o in opts}
    assert "starter" in sources
    for slot, opts in r["options"].items():
        assert opts[0]["meal"] == slot


def test_pool_and_beam_tunables_are_clamped(real_foods):
    from dataclasses import replace

    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    small = replace(ctx, tunables=replace(ctx.tunables, pool_per_role=1, beam_width=0))
    counter = Counter()
    r = planner.plan_day(small, ["dinner"], counter=counter)
    assert r["meals"][0]["status"] in ("ok", "no_fit")
    assert counter.foods <= R.POOL_PER_ROLE_RANGE[0] * 3 * 3 + 50


# --------------------------------------------------------------------------- #
# §6.7: beam versus an exhaustive search over the same candidates and portions
# --------------------------------------------------------------------------- #


def _exhaustive(room, steps, today, dialysis, counter):
    best = None

    def rec(i, chosen):
        nonlocal best
        if i == len(steps):
            if not chosen:
                return
            built = planner.Built(tuple(chosen), score_meal(chosen, room, today, dialysis, counter=counter), planner._k(chosen))
            built = planner.fine_tune(built, room, today, dialysis, counter, False)
            if best is None or (built.score, -built.k_total) > (best.score, -best.k_total):
                best = built
            return
        rec(i + 1, chosen)  # every role may be skipped
        if i == 1 and any(f.role == "mixed" for f, _ in chosen):
            return  # a mixed dish fills the starch step
        ids = {f.id for f, _ in chosen}
        for ev in steps[i]:
            if ev.food.id in ids:
                continue
            for q in planner._portions(ev, chosen, room):
                nxt = chosen + [(ev.food, q)]
                if check_meal(nxt, room, "built").ok:  # totals only grow: a failing prefix never recovers
                    rec(i + 1, nxt)

    rec(0, [])
    return best


def test_beam_is_within_half_a_point_of_exhaustive_search(real_foods):
    eligible = [f for f in real_foods.values() if not (f.hidden or f.avoid or f.hypo or f.ingredient or f.supplies)]
    cases = [("3b", "none"), ("4", "none"), ("5", "none"), ("5", "hemodialysis")]
    gaps = []
    for seed in range(40):
        rnd = random.Random(seed)
        stage, dialysis_mode = cases[seed % 4]
        targets = suggest_targets(70, stage, dialysis_mode)["targets"]
        breakfast = tuple(fx.entry(f, "breakfast", rnd.choice([0.5, 1.0, 1.5]))
                          for f in rnd.sample(eligible, rnd.randint(0, 3)))
        ctx = fx.context(food_map=real_foods, targets=targets, dialysis=dialysis_mode, day=breakfast, history=(), saved=())
        habit, today = habit_stats(ctx), today_stats(ctx.day)
        pools = planner.build_pools(ctx, habit, today, R.POOL_PER_ROLE)
        dialysis = dialysis_mode != "none"
        for slot, open_meals in (("lunch", ["lunch", "dinner", "snack"]), ("dinner", ["dinner", "snack"])):
            room = meal_room(ctx, slot, open_meals=open_meals)
            counter = Counter()
            scorer = Scorer(room, habit, today, counter)
            steps = [planner.step_candidates(scorer, list(pools["protein"]) + list(pools["mixed"]), True),
                     planner.step_candidates(scorer, pools["starch"], False),
                     planner.step_candidates(scorer, pools["veg_fruit"], False)]
            beam = planner.beam_build(room, scorer, today, dialysis, steps, R.BEAM_WIDTH, counter)
            oracle = _exhaustive(room, steps, today, dialysis, counter)
            assert (oracle is None) == (not beam), (seed, slot)
            if oracle is not None:
                gaps.append(oracle.score - beam[0].score)
    assert len(gaps) == 80
    assert max(gaps) <= 0.5, max(gaps)
    assert sorted(gaps)[len(gaps) // 2] <= 0.05  # median essentially 0
