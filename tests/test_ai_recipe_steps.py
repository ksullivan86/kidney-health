"""The checks on an AI recipe's cooking steps (note 16 §8.7): the table as a pass/fail list, with the evasions the app has met
elsewhere (zero-width characters, bidi controls, Cyrillic look-alikes, other cases, written fractions)."""
from __future__ import annotations

import pytest

from app.ai.recipe_steps import MAX_STEPS, check_step, check_steps

NAMES = ["Chicken breast, roasted", "Rice, white, long-grain, cooked", "Beans, kidney, canned", "Soy sauce, low sodium"]

PASSES = [
    "Chop the onion and the carrot small.",
    "Serve with the rice.",
    "Simmer for 20 minutes.",
    "Let it cool for 5 minutes.",
    "Bake at 180 C (350 F) for 25 minutes.",
    "Crack 2 eggs into a bowl.",
    "Soak the dried beans overnight.",  # beans are in the list
    "Season with pepper.",
    "Fry the egg.",
    "Stir in the soy sauce at the end.",  # a food of the list has "soy sauce" in its name
]

FAILS = [
    ("x" * 240, "too_long"),
    ("…", "empty"),
    ("", "empty"),
    ("See https://example.com/recipe", "link"),
    ("Mail chef@example.com for more", "link"),
    ("Use the `pan`", "markup"),
    ("Stir <b>well</b>", "markup"),
    ("Have your insulin ready", "dose:insulin"),
    ("Take your binder with this", "blocklist:binder"),
    ("Take sevelamer with this", "dose:medicine_name"),
    ("Have your ins​ulin ready", "dose:insulin"),  # a zero-width space inside the word
    ("Check the dоse first", "dose:dose"),  # a Cyrillic "о"
    ("Check the DOSE first", "dose:dose"),
    ("If you feel shaky, treat the low first.", "low"),
    ("Add 200 g of flour", "quantity"),
    ("Stir in 30 mg of something", "quantity"),
    ("Add 2 cups of broth", "amount"),
    ("Add ½ tsp pepper", "amount"),
    ("Add 1/2 tsp pepper", "amount"),
    ("Add a pinch of pepper", "amount"),
    ("Boil twice to remove potassium", "nutrient_word"),
    ("This lowers the sodium by half", "nutrient_word"),
    ("Double-boiling makes it kidney-friendly", "claim"),
    ("A healthy way to finish", "claim"),
    ("This is gluten-free.", "diet_claim"),
    ("Stir in a salt substitute", "unlisted_food"),
    ("Add a stock cube", "unlisted_food"),
    ("Season with salt.", "unlisted_food"),
    ("Top with cheese.", "unlisted_food"),
]


@pytest.mark.parametrize("step", PASSES)
def test_a_safe_step_passes(step):
    text, reason = check_step(step, NAMES)
    assert reason is None and text == step


@pytest.mark.safety
@pytest.mark.parametrize("step, reason", FAILS)
def test_an_unsafe_step_is_removed_with_its_reason(step, reason):
    text, why = check_step(step, NAMES)
    assert text is None
    assert why == reason or (why or "").startswith(reason.split(":")[0]), (step, why)


@pytest.mark.safety
def test_a_bidi_control_is_removed_before_the_checks():
    text, why = check_step("Have your ‮insulin‬ ready", NAMES)
    assert text is None and why.startswith("dose:")


def test_unsafe_steps_are_counted_and_the_rest_kept_in_order():
    kept, dropped = check_steps(["Chop it.", "Take your sevelamer.", "Serve."], NAMES)
    assert kept == ["Chop it.", "Serve."] and dropped == [{"index": 1, "reason": "dose:medicine_name"}]


def test_at_most_eight_steps_are_kept():
    kept, dropped = check_steps([f"Stir for {i} minutes." for i in range(1, 11)], NAMES)
    assert len(kept) == MAX_STEPS and [d["reason"] for d in dropped] == ["too_many_steps"] * 2


def test_a_step_that_is_not_text_is_removed():
    assert check_steps([None, 3, {"a": 1}], NAMES)[0] == []
