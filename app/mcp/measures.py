"""Amounts for the assistant's ``check_meal``: servings, grams, or a household measure the food itself lists.

A food knows one serving, described as ``"<quantity> <measure>[, <more>] (<grams> g)"`` (``data/foods.json``,
foods a person adds, USDA portions): ``"1 cup (158 g)"``, ``"1/2 cup, 4 fl oz (124 g)"``, ``"3 oz (85 g)"``,
``"1 medium (118 g)"``. :func:`food_measures` reads the measures from that text, so "2 cups" of a food served as
"1/2 cup" is 4 servings. Nothing else is converted: no measure the food does not list (no cups to tablespoons,
no millilitres to grams), so a measure the food does not know is a question for the person, never a guess.

Also :func:`split_amount`, which takes a quantity and a measure off the food words a chat model sends
(``"white rice 1 cup"``, ``"2 slices of toast"``), and :func:`singular` for the search. Pure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from ..guidance.messages import short_serving

_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
# "1", "10", "1.5", "1/2", "1-1/4", "1 1/4", "½", "1½"
QUANTITY = r"(?:\d+(?:[.,]\d+)?(?:(?:\s*-\s*|\s+)\d+/\d+|/\d+)?[½¼¾⅓⅔⅛]?|[½¼¾⅓⅔⅛])"
_QUANTITY_RE = re.compile(rf"^\s*({QUANTITY})\s*(.*?)\s*$")

# Spellings of the same measure → one name. Anything else is compared by its key (:func:`normalize_unit`).
_SYNONYMS: dict[str, str] = {
    "tablespoon": "tbsp", "tbs": "tbsp", "tbl": "tbsp", "tbsp": "tbsp",
    "teaspoon": "tsp", "tsp": "tsp",
    "ounce": "oz", "oz": "oz",
    "fluid ounce": "fl oz", "fl oz": "fl oz", "fl. oz": "fl oz", "fl.oz": "fl oz", "floz": "fl oz",
    "gram": "g", "gr": "g", "g": "g",
    "serving": "serving", "portion": "serving", "serve": "serving",
}
# Measures read from the part of a serving description after the first comma ("1 can, 12 fl oz"): only
# weights and volumes, so "1 tortilla, 8 in" or "1 piece, 1/8 of 18 oz cake" add nothing.
_SECONDARY = frozenset({"oz", "fl oz", "cup", "tbsp", "tsp"})
# A serving measured by size ("1 medium (118 g)") is one whole food: "1 banana" is then one serving.
SIZE_WORDS = frozenset({"small", "medium", "large", "extra large", "whole", "jumbo"})
# Measures a chat model may write in front of or after the food words ("2 slices of toast", "rice 200 g").
_TEXT_UNITS = (
    r"g|grams?|gr|oz|ounces?|fl\.?\s?oz|fluid ounces?|cups?|tbsps?|tbs|tablespoons?|tsps?|teaspoons?|slices?|"
    r"pieces?|servings?|portions?|cans?|bowls?|glass(?:es)?|bottles?|containers?|small|medium|large|whole"
)
_WORD_NUMBERS = {"a": 1.0, "an": 1.0, "one": 1.0, "two": 2.0, "three": 3.0}
# The quantity must be followed by a space or a measure ("2% milk" is a food, not 2 × "% milk").
_LEADING = re.compile(rf"^\s*({QUANTITY}|an?|one|two|three)(?:\s*({_TEXT_UNITS})\b\.?)?\s+(?:of\s+)?(.+?)\s*$",
                      re.IGNORECASE)
_TRAILING = re.compile(rf"^\s*(.+?)[\s,]+({QUANTITY})(?:\s*({_TEXT_UNITS})\b\.?)?\s*$", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")


def parse_quantity(text: str) -> float | None:
    """``"1-1/4"`` → 1.25, ``"1/2"`` → 0.5, ``"1.5"`` → 1.5, ``"½"`` → 0.5, ``"two"`` → 2; ``None`` when it is
    not a quantity."""
    raw = (text or "").strip().replace(",", ".")
    if not raw:
        return None
    if raw.lower() in _WORD_NUMBERS:
        return _WORD_NUMBERS[raw.lower()]
    glyph = 0.0
    if raw[-1] in _FRACTIONS:
        glyph, raw = _FRACTIONS[raw[-1]], raw[:-1].strip()
        if not raw:
            return glyph
    whole, _, fraction = re.sub(r"\s*-\s*", " ", raw).partition(" ")
    try:
        if "/" in whole and not fraction:
            top, bottom = whole.split("/", 1)
            value = float(top) / float(bottom)
        else:
            value = float(whole)
            if fraction:
                top, bottom = fraction.split("/", 1)
                value += float(top) / float(bottom)
    except (ValueError, ZeroDivisionError):
        return None
    value += glyph
    return value if value > 0 else None


def singular(word: str) -> str:
    """A plural word without its plural ending, for a substring search: ``"bananas"`` → ``"banana"``,
    ``"tomatoes"`` → ``"tomato"``, ``"boxes"`` → ``"box"``, ``"cookies"`` → ``"cookie"`` (and ``"cherries"`` →
    ``"cherrie"``, still inside "Cherries"). Short words and words in -ss, -us, -is stay as they are."""
    w = word.lower()
    if w.endswith(("oes", "xes", "zes", "ches", "shes", "sses")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def word_key(word: str) -> str:
    """The same key for a word's singular and plural, for comparing measures and names: English "-ies" plurals
    are irregular ("cookies" → cookie, "cherries" → cherry), so both forms end in "y" here and a final "e" goes
    ("slices" and "slice" → "slic"). A key, never shown."""
    w = singular(word)
    if w.endswith("ie"):
        return w[:-2] + "y"
    if len(w) > 3 and w.endswith("e"):
        return w[:-1]
    return w


def normalize_unit(text: str | None) -> str:
    """One key per measure: lower case, single spaces, a trailing dot dropped, synonyms joined, the last word's
    plural ending gone (``"Tablespoons"`` → ``"tbsp"``, ``"large cookies"`` and ``"large cookie"`` → the same
    key); ``""`` for nothing."""
    unit = " ".join((text or "").lower().replace(" ", " ").split()).rstrip(".")
    if not unit:
        return ""
    if unit in _SYNONYMS:
        return _SYNONYMS[unit]
    words = unit.split(" ")
    words[-1] = singular(words[-1])
    if " ".join(words) in _SYNONYMS:
        return _SYNONYMS[" ".join(words)]
    words[-1] = word_key(words[-1])
    return " ".join(words)


@dataclass(frozen=True)
class Measure:
    servings: float  # servings in one of this measure
    label: str  # as the food writes it ("cup", "fl oz", "large cookie")


def food_measures(serving_desc: str | None) -> dict[str, Measure]:
    """``{measure: Measure}`` from a serving description: ``"1/2 cup, 4 fl oz (124 g)"`` → cup = 2 servings,
    fl oz = 0.25 servings; ``"3 oz (85 g)"`` → oz = 1/3 serving. Empty when it names no measure."""
    measures: dict[str, Measure] = {}
    parts = [p.strip() for p in short_serving(serving_desc or "").split(",")]
    for index, part in enumerate(parts):
        match = _QUANTITY_RE.match(part)
        if match is None:
            continue
        quantity = parse_quantity(match.group(1))
        unit = normalize_unit(match.group(2))
        if quantity is None or not unit or not re.fullmatch(r"[a-z][a-z .-]*", unit):
            continue
        if index > 0 and unit not in _SECONDARY:
            continue
        if unit in ("g", "serving"):
            continue  # grams and servings are handled for every food already
        label = " ".join(match.group(2).split()).rstrip(".")
        measures.setdefault(unit, Measure(1.0 / quantity, label))
    return measures


def servings_per_unit(unit: str, measures: Mapping[str, Measure], food_name: str) -> float | None:
    """How many servings one ``unit`` is, from the food's own measures; ``None`` when the food does not list it.

    Matches the measure itself (``"cups"`` → ``"cup"``), its last word (``"cookie"`` for ``"large cookie"``),
    and, when the serving is measured by size (``"1 medium"``), a word of the food's own name
    (``"banana"`` for ``"Banana, raw"``: one whole banana)."""
    wanted = normalize_unit(unit)
    if not wanted:
        return None
    if wanted in measures:
        return measures[wanted].servings
    # "cookie" for "large cookie"; but an ounce of weight is not a fluid ounce, so "oz" never means "fl oz".
    ends = [m.servings for name, m in measures.items() if name.split(" ")[-1] == wanted and name != "fl oz"]
    if len(ends) == 1:
        return ends[0]
    name_words = {normalize_unit(w) for w in _WORD_RE.findall((food_name or "").lower())}
    if wanted in name_words:
        sized = [m.servings for name, m in measures.items() if name in _SIZE_KEYS]
        if len(sized) == 1:
            return sized[0]
    return None


def split_amount(text: str) -> tuple[str, float | None, str | None]:
    """``(food words, amount, measure)`` from what a chat model sent as the food: ``"white rice 1 cup"`` →
    ``("white rice", 1.0, "cup")``, ``"2 slices of toast"`` → ``("toast", 2.0, "slices")``, ``"2 eggs"`` →
    ``("eggs", 2.0, None)``; text without a quantity comes back unchanged with ``None, None``."""
    words = " ".join((text or "").split())
    match = _LEADING.match(words)
    if match is not None and match.group(3) and not re.fullmatch(QUANTITY, match.group(3)):
        return match.group(3), parse_quantity(match.group(1)), match.group(2)
    match = _TRAILING.match(words)
    if match is not None and match.group(1):
        return match.group(1), parse_quantity(match.group(2)), match.group(3)
    return words, None, None


def search_words(text: str) -> list[str]:
    """The words of a food phrase worth searching for: lower case, without "a", "an", "the", "some", "of", "my"."""
    return [w for w in _WORD_RE.findall((text or "").lower()) if w not in _FILLER]


_FILLER = frozenset({"a", "an", "the", "some", "of", "my"})
_SIZE_KEYS = frozenset(normalize_unit(w) for w in SIZE_WORDS)
