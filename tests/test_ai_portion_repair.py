"""AI meal ideas that are only too big are made smaller, not dropped; every other reason still drops them.

The owner's live run (2026-10-29) dropped most AI ideas for ``high_portion_too_large``: a food that is not "high" at its own
portion becomes "high" at 6 quarters, and an AI idea may hold at most one serving of a "high" food (note 04 V5). The app now
lowers such a portion one quarter at a time until the meal check passes (``validate_ai_items``), and each candidate sent to
the AI says the most quarters the app accepts of it (``max_quarters``). Pure: the note 06 §6.1 fixture, no network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "guidance"))

import fixtures as fx  # noqa: E402  (tests/guidance/fixtures.py)

from app.ai import guard as G  # noqa: E402
from app.ai import prompts as P  # noqa: E402
from app.guidance import ai_bridge  # noqa: E402
from app.guidance import rules as R  # noqa: E402
from app.guidance.budget import day_totals, meal_room  # noqa: E402
from app.guidance.score import check_meal  # noqa: E402
from app.guidance.vectors import is_high, make_food  # noqa: E402

LABEL = {"provider_label": "OpenAI", "model": "gpt-6-luna"}
CAULI = 40  # 170 mg potassium a serving: not "high" at 4 quarters (170 mg), "high" at 5 (212.5 mg) and 6 (255 mg)


@pytest.fixture(autouse=True)
def no_status_provider():
    ai_bridge.register_ai_status(None)
    yield
    ai_bridge.register_ai_status(None)


def food_map(**extra):
    fs = fx.foods()
    fs[CAULI] = make_food(id=CAULI, name="Cauliflower, boiled (test)", category="Vegetables", serving_desc="1/2 cup (62 g)",
                          serving_g=62, nutrients=fx.nutrients(3, 1, 170, 20, 15, 0), fdc_id=10040)
    for fid, f in extra.items():
        fs[int(fid[1:])] = f
    return fs


def idea(items, theme="light", codes=("low_potassium",)):
    return {"theme": theme, "items": [{"food_id": f, "quarters": q} for f, q in items], "reason_codes": list(codes),
            "handbook": []}


def judge(ideas, ctx=None, meal="dinner"):
    ctx = ctx or fx.context(food_map=food_map())
    bridge = ai_bridge.candidates_for_ai(ctx, meal, "ideas")
    return G.judge_ideas({"status": "ok", "refusal": "none", "ideas": ideas}, ctx, meal, bridge, **LABEL)


def test_the_fixture_food_is_high_at_six_quarters_and_fine_at_four():
    ctx = fx.context(food_map=food_map())
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    f = ctx.foods[CAULI]
    assert not is_high(R.K, f.k * 1.0) and is_high(R.K, f.k * 1.25) and is_high(R.K, f.k * 1.5)
    assert room.level_of(R.K) == "ok"
    assert check_meal([(f, 1.5)], room, "ai").reason == "high_portion_too_large"  # what dropped the idea before
    assert check_meal([(f, 1.0)], room, "ai").ok


def test_six_quarters_of_a_food_high_at_that_size_is_lowered_and_kept():
    """Before: ``{"status": "dropped_all", "message": FALLBACK_TEXT, "dropped": [{"index": 0, "reason": "high_portion_too_large"}]}``.
    After: the idea is shown with 4 quarters, ``portions_lowered`` says so and the card carries the app's sentence."""
    result = judge([idea([(1, 4), (CAULI, 6)])])
    assert result["status"] == "ok", result
    assert result["dropped"] == [] and result.get("message") is None
    shown = result["ideas"][0]
    servings = {it["food_id"]: it["servings"] for it in shown["items"]}
    assert servings == {1: 1.0, CAULI: 1.0}  # lowered from 1.5 to 1 serving; the rice is untouched
    assert shown["portion_note"] == G.PORTION_LOWERED_TEXT
    assert result["portions_lowered"] == [{"index": 0, "reason": "high_portion_too_large",
                                           "changes": [{"food_id": CAULI, "from_quarters": 6, "to_quarters": 4}]}]
    # the numbers shown come from the rules after the change
    assert shown["totals"]["potassium_mg"] == 55 + 170
    assert shown["after"]["potassium_mg"]["used"] == 225


def test_an_idea_that_fits_is_not_touched():
    result = judge([idea([(1, 4), (CAULI, 4)])])
    assert result["status"] == "ok" and "portion_note" not in result["ideas"][0]
    assert result["portions_lowered"] == []


def test_too_much_potassium_is_lowered_one_quarter_at_a_time():
    """``would_exceed``: baked potato (925 mg a serving) on a dinner with 750 mg of room. Only the potato is lowered, to the
    largest amount that fits."""
    ctx = fx.context(food_map=food_map())
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    checked = ai_bridge.validate_ai_items(ctx, "dinner", [[{"food_id": 2, "quarters": 4}, {"food_id": 1, "quarters": 4}]],
                                         candidate_ids=[1, 2])
    assert checked["dropped"] == [] and checked["note"] is None
    kept = checked["ideas"][0]
    potato = next(it for it in kept["items"] if it["food_id"] == 2)
    assert potato["servings"] < 1.0
    items = [(ctx.foods[it["food_id"]], it["servings"]) for it in kept["items"]]
    assert check_meal(items, room, "ai").ok
    bigger = [(f, q + 0.25 if f.id == 2 else q) for f, q in items]
    assert not check_meal(bigger, room, "ai").ok  # one more quarter would not fit
    assert checked["portions_lowered"][0]["reason"] == "would_exceed:potassium_mg"


def test_more_than_twelve_quarters_is_brought_down_to_what_fits():
    ctx = fx.context(food_map=food_map())
    checked = ai_bridge.validate_ai_items(ctx, "dinner", [[{"food_id": 7, "quarters": 16}]], candidate_ids=[7])
    assert checked["ideas"] and checked["ideas"][0]["items"][0]["servings"] <= R.AI_QUARTERS_RANGE[1] / 4
    assert checked["portions_lowered"][0]["reason"] == "quarters_out_of_range"


def test_nothing_is_lowered_below_one_quarter_and_a_meal_that_cannot_fit_is_still_dropped():
    ctx = fx.context(food_map=food_map(), targets={**fx.TARGETS, "carbs_per_meal_g": 10})
    checked = ai_bridge.validate_ai_items(ctx, "dinner", [[{"food_id": 1, "quarters": 4}, {"food_id": 6, "quarters": 4},
                                                          {"food_id": 11, "quarters": 4}]], candidate_ids=[1, 6, 11])
    # one quarter of each still has 21 g carbohydrate against a 10 g goal: dropped, with the first reason
    assert checked["ideas"] == [] and checked["dropped"] == [{"index": 0, "reason": "too_many_carbs"}]
    assert checked["portions_lowered"] == []


@pytest.mark.safety
def test_avoid_ckd_and_low_treatments_are_never_repaired():
    ctx = fx.context(food_map=food_map())
    # star fruit (avoid_ckd) and glucose tablets (a low treatment) next to a portion that is too big
    checked = ai_bridge.validate_ai_items(ctx, "dinner", [[{"food_id": 9, "quarters": 4}, {"food_id": CAULI, "quarters": 6}],
                                                          [{"food_id": 10, "quarters": 4}, {"food_id": 2, "quarters": 4}]],
                                         candidate_ids=[2, 9, 10, CAULI])
    assert checked["ideas"] == [] and checked["portions_lowered"] == []
    assert [d["reason"] for d in checked["dropped"]] == ["avoid_ckd", "would_exceed:potassium_mg"]


@pytest.mark.safety
def test_a_high_food_on_a_day_that_is_not_ok_is_never_repaired():
    """Potassium is at caution today (most of it eaten), so a "high" potassium portion is refused whatever its size; an idea
    that also holds too much of something else is dropped too, not made smaller."""
    ctx = fx.context(food_map=food_map(), day=[fx.entry(fx.food(fx.FOOD_ROWS[12]), "breakfast", 1.0,
                                                        override={"potassium_mg": 2000.0})])
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    assert room.level_of(R.K) != "ok"
    checked = ai_bridge.validate_ai_items(ctx, "dinner", [[{"food_id": 3, "quarters": 4}], [{"food_id": 3, "quarters": 4},
                                                          {"food_id": 1, "quarters": 12}]], candidate_ids=[1, 3])
    assert checked["ideas"] == [] and checked["portions_lowered"] == []
    assert checked["dropped"][0] == {"index": 0, "reason": "high_warning:potassium_mg"}
    assert checked["dropped"][1]["index"] == 1


def test_max_quarters_is_sent_with_every_candidate_and_respects_the_room():
    ctx = fx.context(food_map=food_map())
    bridge = ai_bridge.candidates_for_ai(ctx, "dinner", "ideas")
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    lo, hi = R.AI_QUARTERS_RANGE
    for item in bridge["foods"]:
        f, top = ctx.foods[item["food_id"]], item["max_quarters"]
        assert lo <= top <= hi
        assert check_meal([(f, top / 4)], room, "ai").ok
        if top < hi:
            assert not check_meal([(f, (top + 1) / 4)], room, "ai").ok
    by_id = {item["food_id"]: item["max_quarters"] for item in bridge["foods"]}
    assert by_id[CAULI] == 4  # "high" above one serving
    data = P.next_meal_context(bridge, ctx, mode="ideas", meal="dinner", meals_left=["dinner", "snack"], person={})
    sent = {c["id"]: c["max_quarters"] for c in data["candidates"]}
    assert sent == by_id
    # a smaller room gives a smaller limit: after a potassium-heavy lunch only part of a serving fits
    ctx2 = fx.context(food_map=food_map(), day=[fx.entry(fx.food(fx.FOOD_ROWS[12]), "breakfast", 1.0,
                                                         override={"potassium_mg": 2250.0})])
    bridge2 = ai_bridge.candidates_for_ai(ctx2, "dinner", "ideas")
    room2 = meal_room(ctx2, "dinner", totals=day_totals(ctx2.day))
    for item in bridge2["foods"]:
        f, top = ctx2.foods[item["food_id"]], item["max_quarters"]
        assert top == 0 or check_meal([(f, top / 4)], room2, "ai").ok
        assert top == hi or not check_meal([(f, (top + 1) / 4)], room2, "ai").ok
        assert top <= by_id.get(item["food_id"], hi)


def test_the_prompt_tells_the_ai_the_limit():
    assert '"max_quarters"' in P.SYSTEM_PROMPT
