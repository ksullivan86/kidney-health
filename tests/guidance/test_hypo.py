"""Note 04 G7 Layer-0 duty: free text that may describe a low shows the rule-based "Treating a low" card
instead of any AI call (``app.guidance.hypo.prefilter``), and low treatments are never ranked down,
limited or warned against anywhere in guidance."""
from __future__ import annotations

import fixtures as fx
import pytest
from app.guidance import fits, hypo, insights, planner, swaps
from app.guidance import rules as R
from app.guidance.budget import meal_room


@pytest.mark.parametrize("text", [
    "I'm low", "feeling low", "going low, what do I eat", "hypo!", "had a hypo at 3am", "feeling shaky and sweaty",
    "trembling", "dizzy and lightheaded", "my sugar is low", "low blood sugar", "bg 62", "glucose is 3.4",
    "sugar 2,9", "reading below 70", "glucose < 70", "CGM says dropping", "how do I treat a low?", "Hypoglycaemia",
    "LOW", "i am low", "BG: 54", "sugar is dropping", "I’m low",  # typographic apostrophe
    "jitter​s and sweating",  # a zero-width space is removed before matching
])
def test_text_that_may_describe_a_low_shows_the_card_and_no_ai(text):
    result = hypo.prefilter(text)
    assert result is not None, text
    assert result["status"] == "treating_a_low" and result["ai_called"] is False
    assert result["card"]["title"] == "Treating a low"
    assert result["card"]["url"] == "/learn/t1d/treating-a-low/"


@pytest.mark.parametrize("text", [
    "2 eggs, toast with butter, tea", "low-fat milk", "low sodium soup", "a low carb wrap", "low-potassium bread",
    "chicken and rice", "bg 120", "glucose 7.2", "sugar 5", "", None, "lowest price bread", "slow cooker stew",
])
def test_ordinary_meal_text_is_left_to_the_ai(text):
    assert hypo.prefilter(text) is None


def test_the_card_uses_the_persons_amount():
    card = hypo.prefilter("I'm low", dose_g=20)["card"]
    assert "take 20 g of fast carbs now" in card["lines"][0]


def test_low_treatments_are_never_meal_suggestions_never_planned_and_never_shrunk():
    ctx = fx.context()
    fit_ids = {f["food_id"] for f in fits.what_fits(ctx, "snack", limit=20)["foods"]}
    assert not fit_ids & {10, 12}
    plan = planner.plan_day(ctx)
    assert not {i["food_id"] for m in plan["meals"] for i in m["items"]} & {10, 12}
    r = swaps.find_swaps(ctx, "snack", ctx.foods[12], 1.0, "hypo")  # apple juice used for a low
    assert r["mode"] == "hypo" and r["portion_option"] is None
    for s in r["swaps"]:
        assert s["nutrients"]["carbs_g"] >= R.HYPO_DOSE_G
    options = swaps.hypo_options(ctx)
    assert [o["food_id"] for o in options["options"]] == [10, 12]  # never filtered by a budget


def test_low_treatment_entries_do_not_count_toward_meal_carbs_or_carb_insights():
    fs = fx.foods()
    day = (fx.entry(fs[1], "snack", 0.75), fx.entry(fs[10], "snack", 3.0, purpose="hypo"))
    ctx = fx.context(day=day, history=())
    room = meal_room(ctx, "snack")
    assert room.carbs.in_meal == pytest.approx(33.75) and room.carbs.hypo_excluded == 48
    ids = [i["id"] for i in insights.day_insights(ctx)["insights"]]
    assert "day.carbs.meal_off" not in ids and "day.hypo.logged" in ids


def test_a_hypo_food_eaten_as_food_is_judged_as_food():
    ctx = fx.context()
    r = swaps.find_swaps(ctx, "dinner", ctx.foods[12], 1.0, "none")
    assert r["mode"] == "normal" and r["reason"] == "no_warning"
