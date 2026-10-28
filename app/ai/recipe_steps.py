"""The cooking steps of an AI recipe (note 16 §8.7, G18). Pure.

Steps are the one free text an AI recipe may carry, and only while the admin switch ``ai.recipe_steps`` is on (off by default).
Each step passes the checks below in order. A step that fails is removed and counted with its reason code; the rest stay, and the
first :data:`MAX_STEPS` survivors are kept. The lists lean to dropping: a false positive costs one step, which the person can see
was removed, while a false negative would show unchecked advice.

1. Clean: NFKC, control and format characters out, white space collapsed, at most :data:`MAX_STEP_CHARS` characters, some letters.
2. No link, e-mail address, markup or code characters.
3. No insulin or medicine talk (:func:`app.ai.chat.dose_reason`) and nothing on the names blocklist (:func:`app.ai.guard.blocked`),
   after folding look-alike letters and invisible characters.
4. No mention of a low at all.
5. No number with a nutrient or energy unit, and no amount by spoon, cup, weight or pinch: amounts belong to the ingredient list.
   Times, temperatures and counts are fine.
6. No nutrient word and no claim that cooking changes a nutrient or makes food healthy.
7. No allergen or diet claim the app cannot check.
8. Nothing added that the ingredient list does not show: never a salt substitute, and none of :data:`UNLISTED_ITEMS` unless a food
   of the list has that word in its name.

What the checks cannot do: tell whether a time or a temperature is right. Every card with steps says so (:data:`STEPS_LABEL`).
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from ..textclean import clean_text
from . import chat, guard

MAX_STEPS = 8
MAX_STEP_CHARS = 200
STEPS_LABEL = ("Steps written by AI. The app checked them for medicine talk and nutrient claims, not for cooking times or food "
               "safety. Check them before you cook.")
STEPS_REMOVED_TEXT = "Steps removed because the app changed the foods."

_I = re.IGNORECASE
_LETTER = re.compile(r"[A-Za-z]")
_MARKUP = re.compile(r"[<>{}\[\]\\`|]")
_AMOUNT = re.compile(
    r"(?:\b(?:\d+(?:[.,]\d+)?(?:\s*[/⁄]\s*\d+)?|a|an|one|two|three|four|five|six|half(?:\s+a)?|a\s+half|quarter(?:\s+of)?(?:\s+a)?)"
    r"|(?<![\w])[½¼¾⅓⅔⅛])\s*-?\s*(?:heaped\s+|level\s+|rounded\s+|small\s+|large\s+)?"
    r"(?:cups?|c\.|tbsps?|tbs|tablespoons?|tsps?|teaspoons?|spoons?(?:ful)?s?|oz|ounces?|lbs?|pounds?|pints?|quarts?|gallons?|"
    r"pinch(?:es)?|dash(?:es)?|handfuls?|sticks?|knobs?|splash(?:es)?|drizzles?|glugs?|grams?|kilos?|kg|litres?|liters?|ml)\b", _I)
_NUTRIENT_WORD = re.compile(
    r"\b(?:potassium|phosph\w*|sodium|minerals?|electrolytes?|nutrients?|nutrition\w*|vitamins?|calories?|kcal|carbs?|"
    r"carbohydrates?|protein|proteins|fib(?:re|er)s?|glyc(?:a)?emic|sugars?|fats?|cholesterol)\b", _I)
_CLAIM = re.compile(
    r"\b(?:leach\w*|detox\w*|flush\w*|purif\w*|cleans(?:e|es|ing)|kidney[- ]friendly|renal[- ]friendly|kidney[- ]safe|"
    r"good for (?:your |the )?kidneys?|healthy|healthier|healthiest|harmful|toxic|toxins?|safe for|safer)\b", _I)
_DIET_CLAIM = re.compile(
    r"\b(?:allerg\w*|gluten[- ]free|dairy[- ]free|nut[- ]free|lactose[- ]free|egg[- ]free|vegan|vegetarian|plant[- ]based|halal|"
    r"kosher|keto|paleo)\b", _I)
_SALT_SUBSTITUTE = re.compile(
    r"\b(?:salt substitutes?|salt replacers?|salt alternatives?|potassium (?:salt|chloride)|lo-?salt|nu-?salt|no-?salt|lite salt|"
    r"light salt|low[- ]sodium salt|reduced[- ]sodium salt)\b", _I)
# Heavy items a step must not add when the ingredient list does not show them (their sodium, potassium or phosphorus would not be
# counted). Each is allowed only when a food of the list has the same word in its name. Grown from the golden set.
UNLISTED_ITEMS: tuple[str, ...] = (
    "salt", "soy sauce", "tamari", "fish sauce", "oyster sauce", "worcestershire", "stock", "stock cube", "stock cubes", "bouillon",
    "broth", "seasoning", "seasoning mix", "seasoned salt", "msg", "baking powder", "baking soda", "bicarbonate", "miso", "ketchup",
    "mustard", "gravy", "cheese", "parmesan", "bacon", "ham", "olives", "pickles", "capers", "anchovies", "chocolate", "cocoa",
    "nuts", "beans", "lentils", "tomato paste", "tomato puree", "dried fruit", "raisins", "banana", "avocado", "milk", "yogurt",
    "yoghurt", "cream",
)
_UNLISTED = [(item, re.compile(rf"\b{re.escape(item)}\b", _I)) for item in UNLISTED_ITEMS]


def _names_text(names: Iterable[str]) -> str:
    return " | ".join(guard.fold(n or "").casefold() for n in names)


def check_step(text: object, ingredient_names: Sequence[str]) -> tuple[str | None, str | None]:
    """``(the step as shown, None)`` or ``(None, reason)``. ``ingredient_names`` are the names of the recipe's foods, from the
    food rows (never the model)."""
    if not isinstance(text, str):
        return None, "empty"
    cleaned = clean_text(text, max_len=10_000) or ""
    if not cleaned or not _LETTER.search(guard.fold(cleaned)):
        return None, "empty"
    if len(cleaned) > MAX_STEP_CHARS:
        return None, "too_long"
    folded = chat._matchable(cleaned)
    if chat._LINK.search(folded) or chat._EMAIL_ADDRESS.search(folded):
        return None, "link"
    if _MARKUP.search(folded):
        return None, "markup"
    dose = chat.dose_reason(cleaned)
    if dose is not None:
        return None, f"dose:{dose}"
    term = guard.blocked(cleaned)
    if term is not None:
        return None, f"blocklist:{term}"
    if chat._LOW_CONTEXT.search(folded) or re.search(r"\b(?:hypo\w*|shaky|low blood|blood sugar|blood glucose)\b", folded, _I):
        return None, "low"
    if chat.quantities(folded):
        return None, "quantity"
    if _AMOUNT.search(folded):
        return None, "amount"
    if _NUTRIENT_WORD.search(folded):
        return None, "nutrient_word"
    if _CLAIM.search(folded):
        return None, "claim"
    if _DIET_CLAIM.search(folded):
        return None, "diet_claim"
    if _SALT_SUBSTITUTE.search(folded):
        return None, "unlisted_food"
    names = _names_text(ingredient_names)
    for item, pattern in _UNLISTED:
        if pattern.search(folded) and not pattern.search(names):
            return None, "unlisted_food"
    return folded.strip(), None


def check_steps(steps: Iterable[object], ingredient_names: Sequence[str]) -> tuple[list[str], list[dict[str, object]]]:
    """The steps that pass, at most :data:`MAX_STEPS`, and ``[{index, reason}]`` for each one removed."""
    kept: list[str] = []
    dropped: list[dict[str, object]] = []
    for index, raw in enumerate(steps):
        text, reason = check_step(raw, ingredient_names)
        if text is None:
            dropped.append({"index": index, "reason": reason})
        elif len(kept) >= MAX_STEPS:
            dropped.append({"index": index, "reason": "too_many_steps"})
        else:
            kept.append(text)
    return kept, dropped
