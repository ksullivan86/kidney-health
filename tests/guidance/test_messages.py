"""Explanation strings (note 06 §4.9, F6; note 04 G2/G3/V6): number and portion formatting, and a wording
lint over every template and every message the engine produces in a range of situations."""
from __future__ import annotations

import re

import fixtures as fx
import pytest
from app.guidance import fits, insights, planner, swaps
from app.guidance import messages as M
from app.guidance import topics as T
from app.nutrients import suggest_targets

HIGH_LOW = re.compile(r"\b(high|low|higher|lower)\b", re.I)


def lint(text: str) -> None:
    """No banned word; every qualitative "high" or "low" comes with a number (§6.7); no abbreviations."""
    assert text and text == text.strip(), repr(text)
    assert not M.BANNED_PATTERN.search(text), text
    if HIGH_LOW.search(text):
        assert re.search(r"\d", text), f"qualitative word without a number: {text!r}"
    assert not re.search(r"\b(K|P|Na)\b", text), f"abbreviated nutrient: {text!r}"
    assert "  " not in text and "None" not in text and "nan" not in text.lower().split(), text


@pytest.mark.parametrize("value,text", [
    (0, "0"), (0.04, "0"), (0.05, "0.1"), (8.25, "8.3"), (9.94, "9.9"), (9.96, "10"), (13.5, "14"), (1018.4, "1,018"),
    (None, "?"),
])
def test_grams_one_decimal_below_ten_else_whole(value, text):
    assert M.fmt_g(value) == text


@pytest.mark.parametrize("value,text", [(0, "0"), (462.5, "463"), (2809, "2,809"), (12345.5, "12,346"), (None, "?")])
def test_milligrams_whole_with_separators(value, text):
    assert M.fmt_int(value) == text


@pytest.mark.parametrize("servings,text", [
    (1, "1"), (0.25, "¼"), (0.5, "½"), (0.75, "¾"), (1.5, "1½"), (2.25, "2¼"), (3, "3"), (0.33, "0.33"), (0.666, "0.67"),
])
def test_portions_use_quarter_glyphs(servings, text):
    assert M.fmt_servings(servings) == text


def test_portion_texts():
    assert M.portion_text(1.5, "½ cup (79 g)") == "1½ × ½ cup (79 g)"
    assert M.portion_short(0.75, "1 cup (158 g)") == "¾ × 1 cup"
    assert M.short_serving("4 tablets") == "4 tablets"


def test_note_06_example_strings():
    assert M.fit_text({"carbs_g": 45, "potassium_mg": 55, "phosphorus_mg": 70, "sodium_mg": 0},
                      ["potassium_mg", "phosphorus_mg", "sodium_mg"], True) == (
        "Fits: 45 g carbs · 55 mg potassium · 70 mg phosphorus · 0 mg sodium")
    assert M.reason_text("fills_carbs", meal="dinner", after="45", goal="60") == "Brings dinner to 45 of your 60 g carbs"
    assert M.swap_hypo_text("Glucose tablets, 4", 1, "4 tablets (16 g)", 16, 0) == (
        "For your next low: Glucose tablets, 4 (1 × 4 tablets) gives 16 g carbs with 0 mg potassium")
    assert M.portion_option_text(0.5, 18.5, {"potassium_mg": 462.5}, ["potassium_mg"]) == (
        "Half portion: 19 g carbs and 463 mg potassium. The carbs change, so count the new amount.")
    assert M.plan_why_carbs(58.75, 60, "dinner", 60, 10) == "59 g carbs, close to your 60 g dinner goal"
    assert M.plan_why_carbs(56, 60, "dinner", 60, 4) == "56 g carbs, close to your 60 g dinner goal"  # at the edge
    assert M.plan_why_carbs(17, 30, "snack", 30, 10) == "17 g carbs, 13 g under your 30 g snack goal"
    assert M.plan_why_carbs(45, 30, "snack", 30, 10) == "45 g carbs, 15 g over your 30 g snack goal"
    assert M.plan_why_carbs(28, 60, "lunch", 30, 10) == "28 g carbs, close to the 30 g left of your 60 g lunch goal"
    assert M.plan_why_carbs(4, 60, "lunch", -5, 10) == "4 g carbs: your 60 g lunch goal is already reached"
    assert M.plan_why_room(178.75, 750, "dinner") == "Uses 179 of the 750 mg potassium left for dinner"
    assert M.room_line("dinner", {"potassium_mg": {"room": 750}, "phosphorus_mg": {"room": 167}, "sodium_mg": {"room": 600},
                                  "fluid_ml": None, "carbs_g": {"gap": 60, "goal": 60}}) == (
        "Left for dinner: 750 mg potassium · 167 mg phosphorus · 600 mg sodium · 60 g carbs to reach 60 g")
    assert M.DISCLAIMER == "Suggestions compare foods with the targets your care team set. They are not medical advice."


def test_untrusted_names_are_trimmed_and_never_empty():
    assert M.safe_name("  Soup   with\nspaces ") == "Soup with spaces"
    assert len(M.safe_name("x" * 100)) == 60 and M.safe_name("x" * 100).endswith("…")
    assert M.safe_name("") == "this food"


def test_every_fixed_template_passes_the_wording_lint():
    for tip in T.ALL_TIPS:
        lint(tip.text.format(pct=85, value="40", min="70", Meal="Dinner", carbs="62", goal="60", dose="15"))
    for line in M.treating_a_low_card(15)["lines"]:
        assert not M.BANNED_PATTERN.search(line), line
    for text in (M.DISCLAIMER, M.AI_FALLBACK, M.NO_TARGETS, M.DISABLED, M.NEEDS_CONNECTION):
        lint(text)
    for code in ("adds_missing_group", "you_eat_often", "half_portion", "unknown"):
        lint(M.reason_text(code, group="protein", meal="dinner", nutrient="potassium", Nutrient="Potassium"))


def test_the_low_card_follows_the_persons_amount_and_never_mentions_insulin():
    card = M.treating_a_low_card(20)
    assert "take 20 g of fast carbs now" in card["lines"][0]
    assert "take another 20 g" in card["lines"][1]
    text = " ".join(card["lines"]).lower()
    assert "insulin" not in text and "dose" not in text and "potassium never delays" in text


def collect(result, out: list[str]) -> None:
    """Every user-facing string in an engine result (``text``, ``message``, ``note`` … fields)."""
    if isinstance(result, dict):
        for key, value in result.items():
            if key in ("text", "message", "note", "room_text", "fit_text") and isinstance(value, str):
                out.append(value)
            elif key in ("why", "notes", "lines") and isinstance(value, list):
                out.extend(v for v in value if isinstance(v, str))
            else:
                collect(value, out)
    elif isinstance(result, list):
        for item in result:
            collect(item, out)


def test_every_generated_message_passes_the_wording_lint():
    texts: list[str] = []
    foods = fx.real_foods()
    contexts = [
        fx.context(),
        fx.context(food_map=foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=()),
        fx.context(food_map=foods, targets=fx.HD_TARGETS, dialysis="hemodialysis", dialysis_days=(0, 2, 4), day=(),
                   history=(), saved=()),
        fx.context(food_map=foods, targets=suggest_targets(70, "3b")["targets"], diabetes="none", day=(), history=(),
                   saved=()),
    ]
    for ctx in contexts:
        for meal in ("breakfast", "lunch", "dinner", "snack"):
            collect(fits.what_fits(ctx, meal), texts)
        collect(planner.plan_day(ctx), texts)
        collect(insights.day_insights(ctx), texts)
        collect(swaps.hypo_options(ctx), texts)
        for f in list(ctx.foods.values())[::9]:
            collect(swaps.find_swaps(ctx, "dinner", f, 1.0), texts)
            collect(swaps.find_swaps(ctx, "snack", f, 1.0, "hypo"), texts)
    collect(insights.day_insights(fx.context(day=(fx.entry(fx.foods()[2], "dinner", 3.0),
                                                     fx.entry(fx.foods()[10], "snack", purpose="hypo")))), texts)
    card_lines = set(M.treating_a_low_card(15)["lines"])
    assert len(texts) > 500
    for text in texts:
        if text in card_lines:
            assert not M.BANNED_PATTERN.search(text)
            continue
        lint(text)
