"""AI recipes whose only problem is a share that is too big are fitted, not dropped; every other reason still drops them.

A share is one serving's amount of a food: its pot amount ÷ the servings the recipe makes. The meal check accepts at most 3
servings of a food in one serving. Before, ``judge_recipes`` dropped a bigger share (``share_too_large``) before the fit ran,
although the fit can lower it (``portion_out_of_range``). The live run of 2026-10-29 dropped 1 recipe of 118 that way. Now the
recipe goes through ``fit_recipe``, and the card carries ``portion_note`` and ``portions_lowered`` like a meal idea the app made
smaller. Pure: the note 06 §6.1 fixture, no network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "guidance"))

import fixtures as fx  # noqa: E402  (tests/guidance/fixtures.py)

from app.ai import guard as G  # noqa: E402
from app.ai import recipes as AR  # noqa: E402
from app.guidance import rules as R  # noqa: E402
from app.guidance.recipes import Target  # noqa: E402
from app.guidance.state import Prefs  # noqa: E402
from app.guidance.vectors import make_food  # noqa: E402

DINNER = Target("meal", "dinner")
RICE, POTATO, CHICKEN, EGG, BEANS, STAR, GLUCOSE, APPLE_JUICE, BLUEBERRIES = 1, 2, 3, 4, 5, 9, 10, 12, 7
WINE, SALT, MYSTERY = 60, 61, 62


def food_map():
    fs = fx.foods()
    fs[WINE] = make_food(id=WINE, name="Wine, red (test)", category="Beverages", serving_desc="5 fl oz (147 g)", serving_g=147,
                         nutrients=fx.nutrients(4, 0, 190, 34, 6, 147), flags=(R.ALCOHOL_FLAG,), fdc_id=10060)
    fs[SALT] = make_food(id=SALT, name="Salt, table (test)", category="Spices & Herbs", serving_desc="1/4 tsp (1.5 g)",
                         serving_g=1.5, nutrients=fx.nutrients(0, 0, 0, 0, 580, 0), fdc_id=10061)
    fs[MYSTERY] = make_food(id=MYSTERY, name="Mystery stew (test)", category="Test only", serving_desc="1 cup (240 g)",
                            serving_g=240, nutrients=fx.nutrients(10, 5, None, 40, 50, 100), fdc_id=10062)
    return fs


def context(**extra):
    return fx.context(food_map=food_map(), **extra)


def bridge_for(ctx, everything=False):
    """The rule candidates; ``everything`` adds every food, so a check after "is it a candidate?" is the one that drops."""
    bridge = AR.recipe_candidates(ctx, DINNER)
    if everything:
        sent = {int(f["food_id"]) for f in bridge["foods"]}
        bridge = {**bridge, "foods": bridge["foods"] + [{"food_id": fid, "often": False, "liked": False}
                                                         for fid in ctx.foods if fid not in sent]}
    return bridge


def judge(items, *, ctx=None, makes=1.0, everything=False, answer=None, **raw_extra):
    ctx = ctx or context()
    raw = {"dish": "bowl", "theme": "light", "ingredients": [{"food_id": f, "quarters": q} for f, q in items], "steps": [],
           "reason_codes": [], **raw_extra}
    return AR.judge_recipes(answer or {"status": "ok", "refusal": "none", "recipes": [raw]}, ctx, DINNER,
                            bridge_for(ctx, everything), mode="suggest", makes=makes, steps=False, provider_label="OpenAI",
                            model="gpt-6-luna")


def shares(card):
    n = card["body"]["servings_made"]
    return {i["food_id"]: i["servings"] / n for i in card["body"]["items"]}


# --------------------------------------------------------------------------- the repair


def test_a_share_of_three_and_a_half_servings_is_lowered_to_three_and_kept():
    """Before: ``{"status": "dropped_all", "message": DROPPED_ALL_TEXT, "dropped": [{"index": 0, "reason": "share_too_large"}]}``.
    After: the blueberries go down to 3 servings, the card says so and the answer lists the change."""
    out = judge([(BLUEBERRIES, 14), (RICE, 2)])
    assert out["status"] == "ok" and out["dropped"] == [], out
    [card] = out["recipes"]
    assert shares(card) == {BLUEBERRIES: 3.0, RICE: 0.5}
    assert card["portion_note"] == AR.PORTION_LOWERED_TEXT == "The app made a portion smaller so the recipe fits your targets."
    assert card["portions_lowered"] == [{"food_id": BLUEBERRIES, "from_servings": 3.5, "to_servings": 3.0}]
    assert out["portions_lowered"] == [{"index": 0, "reason": "share_too_large", "changes": card["portions_lowered"]}]
    [line] = [c for c in card["fit"]["changes"] if c["code"] == "lowered"]
    assert line["text"].endswith("so one serving holds a smaller portion of it.")
    assert card["per_serving"]["potassium_mg"] == 193  # 3 × 55 + ½ × 55 mg: the app's numbers, after the change


def test_a_pot_for_two_counts_the_share_of_one_serving():
    out = judge([(BLUEBERRIES, 28), (RICE, 4)], makes=2)  # 7 servings in the pot, 3.5 in each serving
    assert out["status"] == "ok", out
    [card] = out["recipes"]
    assert max(shares(card).values()) <= 3.0 + 1e-9 and card["portions_lowered"][0]["from_servings"] == 3.5


def test_a_protein_food_is_never_lowered_so_the_fit_swaps_it_and_says_why():
    out = judge([(EGG, 14), (RICE, 2)])
    assert out["status"] == "ok", out
    [card] = out["recipes"]
    assert EGG not in shares(card) and max(shares(card).values()) <= 3.0 + 1e-9
    assert card["portions_lowered"] == [{"food_id": EGG, "from_servings": 3.5, "to_servings": 0.0}]
    [swap] = [c for c in card["fit"]["changes"] if c["code"] == "swapped"]
    assert swap["from_food_id"] == EGG and swap["because"] == "portion"
    assert swap["text"].endswith("because one serving held more of Egg white, cooked than the app allows.")
    assert "does not list a value" not in swap["text"]  # the old text blamed a missing value


def test_with_no_swap_the_fit_offers_a_smaller_serving():
    ctx = context(prefs=Prefs(exclude_food_ids=frozenset({CHICKEN})))  # the only swap for egg white is Not for me
    out = judge([(EGG, 14), (RICE, 2)], ctx=ctx)
    assert out["status"] == "ok", out
    [card] = out["recipes"]
    assert card["fitted"]["serving_fraction"] < 1.0 and card["body"]["servings_made"] > 1
    assert max(shares(card).values()) <= 3.0 + 1e-9
    assert card["portions_lowered"][0]["to_servings"] == round(shares(card)[EGG], 2) <= 3.0
    assert any(c["code"] == "smaller_serving" for c in card["fit"]["changes"])


def test_two_shares_that_are_too_big_get_the_plural_note():
    out = judge([(BLUEBERRIES, 14), (BEANS, 14)])
    assert out["status"] == "ok", out
    [card] = out["recipes"]
    assert card["portion_note"] == AR.PORTIONS_LOWERED_TEXT
    assert [c["food_id"] for c in card["portions_lowered"]] == [BLUEBERRIES, BEANS]
    assert max(shares(card).values()) <= 3.0 + 1e-9


def test_a_recipe_that_fits_has_no_note():
    out = judge([(BLUEBERRIES, 4), (RICE, 2)])
    [card] = out["recipes"]
    assert card["portion_note"] is None and card["portions_lowered"] == [] and out["portions_lowered"] == []


# --------------------------------------------------------------------------- every other reason still drops


@pytest.mark.safety
@pytest.mark.parametrize("items, everything, reason", [
    ([(STAR, 14), (RICE, 2)], False, "not_a_candidate"),  # avoid_ckd is never a candidate
    ([(BLUEBERRIES, 14), (STAR, 2)], True, "not_a_candidate"),  # avoid_ckd, even if it were offered
    ([(APPLE_JUICE, 14), (RICE, 2)], True, "not_a_candidate"),  # a low treatment is kept for treating lows
    ([(GLUCOSE, 14), (RICE, 2)], True, "not_a_candidate"),  # a diabetes supply
    ([(BLUEBERRIES, 14), (WINE, 4)], True, "not_a_candidate"),  # alcohol
    ([(BLUEBERRIES, 14), (SALT, 1)], True, "excluded_category"),  # table salt: the AI never adds it
    ([(BLUEBERRIES, 14), (999_999, 2)], False, "not_a_candidate"),
    ([(BLUEBERRIES, 161), (RICE, 2)], False, "quarters_out_of_range"),
    ([(BLUEBERRIES, 14)], False, "too_few_items"),
    ([(BEANS, 160), (RICE, 2)], False, "share_too_large"),  # 40 servings: too much for the fit to bring under 3
    ([(CHICKEN, 14), (RICE, 2)], False, "would_exceed:phosphorus_mg"),  # the day's phosphorus is used up: no size fits
])
def test_a_too_big_share_does_not_hide_another_reason(items, everything, reason):
    out = judge(items, everything=everything)
    assert out["status"] == "dropped_all" and out["recipes"] == [], out
    assert out["dropped"] == [{"index": 0, "reason": reason}] and out["portions_lowered"] == []
    assert out["message"] == AR.DROPPED_ALL_TEXT


@pytest.mark.safety
@pytest.mark.parametrize("prefs, reason", [
    (Prefs(exclude_food_ids=frozenset({BLUEBERRIES})), "not_for_me"),
    (Prefs(exclude_categories=frozenset({"Fruits"})), "excluded_category"),
])
def test_a_too_big_share_of_a_food_the_person_does_not_want_is_dropped(prefs, reason):
    out = judge([(BLUEBERRIES, 14), (RICE, 2)], ctx=context(prefs=prefs), everything=True)
    assert out["status"] == "dropped_all" and out["dropped"] == [{"index": 0, "reason": reason}], out


@pytest.mark.safety
def test_a_too_big_share_of_a_food_with_an_unknown_value_is_dropped_on_a_day_that_value_matters():
    ctx = context(day=(fx.entry(fx.foods()[13], "breakfast", entry_id=1), fx.entry(fx.foods()[14], "lunch", entry_id=2),
                       fx.entry(fx.foods()[POTATO], "lunch", entry_id=3)))  # 2,225 mg potassium: not OK any more
    out = judge([(MYSTERY, 14), (RICE, 2)], ctx=ctx, everything=True)  # the stew lists no potassium
    assert out["status"] == "dropped_all" and out["recipes"] == [] and out["portions_lowered"] == [], out
    assert out["dropped"][0]["reason"] != "share_too_large"  # a smaller serving fixes the size, not the missing value


@pytest.mark.safety
def test_a_refusal_and_an_unexpected_field_still_drop():
    refused = judge([], answer={"status": "refused", "refusal": "outside_scope", "recipes": []})
    assert refused["status"] == "refused" and refused["message"] == G.REFUSED_TEXT and refused["portions_lowered"] == []
    out = judge([(BLUEBERRIES, 14), (RICE, 2)], title="Kidney-safe miracle bowl")
    assert out["status"] == "dropped_all" and out["dropped"] == [{"index": 0, "reason": "unexpected_field"}]
