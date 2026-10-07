"""Note 04 G7: hypoglycaemia is never routed through AI. Pure.

``app/ai/`` runs :func:`prefilter` on every piece of free text a person types (the parse-meal box)
**before** it builds a prompt. When the text may describe a low (``low``, ``hypo``, ``shaky``,
``sweaty``, ``glucose < 70``, a reading under 70 mg/dL or 3.9 mmol/L, …) the AI is not called and
the rule-based "Treating a low" card is shown instead. The classifier errs on the side of showing
the card: a false alarm costs one tap, a missed low could cost far more. Common food descriptors
("low-fat", "low sodium", "low-carb") are not read as a low.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import messages as M
from . import rules as R

# Words and phrases that may describe a low (case-insensitive, after NFKC and apostrophe folding),
# including past tenses and CGM wording ("sugar dropped", "it crashed", "glucose fell", "need sugar fast").
_TERMS = re.compile(
    r"\b(hypo\w*|shak(?:y|ey|ing|es)|sweat(?:y|ing)|trembl\w*|jitter\w*|dizzy|light[- ]?headed|faint\w*|"
    r"blurr\w* vision|pounding heart|racing heart|treat(?:ing)? a low|going low|feel(?:ing)? low|"
    r"i'?m low|i am low|running low|dropp?ed|dropping|crash(?:ed|ing)|tank(?:ed|ing)|plummet\w*|"
    r"low (?:blood )?(?:sugar|glucose|bg|bs)|"
    r"(?:sugar|glucose|bg|bs|cgm|reading)s? (?:is |are |was |went |getting |dropped )?(?:low|down|dropping)|"
    r"(?:sugar|glucose|bg|bs|cgm|reading|level|number)s? (?:has |have |is |was |just )?(?:fell|fallen|falling)|"
    r"need(?:s|ed)? (?:some |a |fast )?(?:sugar|glucose|carbs?)(?![- ]?free))\b",
    re.IGNORECASE,
)
# "low" on its own counts, except as a food descriptor ("low-fat milk", "low sodium soup").
_LOW_WORD = re.compile(
    r"\blow\b(?![-\s]*(?:fat|sodium|salt|sugar|carb\w*|cal\w*|potassium|phosph\w*|fib(?:er|re)|lactose|"
    r"cholesterol|protein|gi|glycemic|glycaemic|in)\b)",
    re.IGNORECASE,
)
# A glucose word, then up to three linking words ("is", "was at", "cgm says", "reading shows", "is now").
_LEAD = (r"(?:glucose|sugar|bg|bs|cgm|reading)\s*"
         r"(?:(?:is|was|of|at|:|says|said|reads|read|shows|showed|showing|now|just|only)\s*){0,3}")
# A number followed by a kitchen or energy unit is an amount, not a reading ("sugar 2 tsp", "rice at 50 g").
_NOT_A_READING = (r"(?![.,]?\d)(?!\s*(?:(?:tsps?|tbsps?|teaspoons?|tablespoons?|spoons?|cubes?|lumps?|packets?|"
                  r"sachets?|cups?|slices?|pieces?|servings?|portions?|bowls?|glass(?:es)?|mugs?|cans?|bottles?|g|grams?|"
                  r"kg|oz|lbs?|ml|kcal|cal(?:orie)?s?|min(?:ute)?s?|hours?|hrs?|am|pm|o'?clock)\b|%))")
_LESS_THAN = re.compile(_LEAD + r"(?:<|under|below|less than)", re.IGNORECASE)
_READING = re.compile(_LEAD + r"(\d{1,3}(?:[.,]\d)?)" + _NOT_A_READING, re.IGNORECASE)
# "I'm at 58", "at 3.2", "down to 61": a bare number in the mg/dL low range (30-69) or a decimal mmol/L
# value; whole numbers under 30 are left out here ("lunch at 1", "at 12") because they read as times.
_BARE = re.compile(r"\b(?:i'?m|i am|at|down to|only)\s+(?:about\s+|around\s+)?(\d{1,2}(?:[.,]\d)?)" + _NOT_A_READING,
                   re.IGNORECASE)
# A number with a glucose unit: "3.4 mmol" (low at or under 3.9), "61 mg/dL" (under 70) and a whole
# "30-69 mg" unless a nutrient is named just before or after it ("60 mg sodium", "sodium 60 mg").
_WITH_UNIT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d)?)\s*(?:(mmol)|(mg\s*/\s*dl)\b|mg\b)", re.IGNORECASE)
_NUTRIENT = (r"(?:sodium|potassium|phosph\w*|calcium|caffeine|salt|iron|magnesium|zinc|vitamin\w*|"
             r"na|k|p|ca|fe|mg|mcg)")
_NUTRIENT_AFTER = re.compile(r"\s*(?:of\s+)?" + _NUTRIENT + r"\b", re.IGNORECASE)
_NUTRIENT_BEFORE = re.compile(r"\b" + _NUTRIENT + r"\W*$", re.IGNORECASE)

MMOL_LOW = 3.9  # level 1 hypoglycaemia (ADA 2026 §6)
MGDL_LOW = 70.0


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    folded = "".join(ch for ch in folded if unicodedata.category(ch) not in ("Cc", "Cf") or ch in "\n\t")
    return folded.replace("’", "'").replace("‘", "'")


def _number(raw: str) -> float:
    return float(raw.replace(",", "."))


def _is_low_reading(raw: str) -> bool:
    """A reading after a glucose word: a decimal or a whole number under 30 is mmol/L (low at or under
    3.9), 30-69 is mg/dL."""
    value = _number(raw)
    if ("." in raw or "," in raw or value < 30) and value <= MMOL_LOW:
        return True  # mmol/L
    return 30 <= value < MGDL_LOW  # mg/dL


def mentions_low(text: str | None) -> bool:
    """Does free text possibly describe a low (or ask how to treat one)?"""
    if not text:
        return False
    folded = _fold(text)
    if _TERMS.search(folded) or _LOW_WORD.search(folded) or _LESS_THAN.search(folded):
        return True
    if any(_is_low_reading(m.group(1)) for m in _READING.finditer(folded)):
        return True
    for match in _BARE.finditer(folded):
        raw = match.group(1)
        value = _number(raw)
        if (("." in raw or "," in raw) and value <= MMOL_LOW) or 30 <= value < MGDL_LOW:
            return True
    for match in _WITH_UNIT.finditer(folded):
        raw = match.group(1)
        value = _number(raw)
        if match.group(2):
            low = value <= MMOL_LOW
        elif match.group(3):
            low = value < MGDL_LOW
        else:
            low = ("." not in raw and "," not in raw and 30 <= value < MGDL_LOW
                   and not _NUTRIENT_AFTER.match(folded, match.end())
                   and not _NUTRIENT_BEFORE.search(folded[max(0, match.start() - 24):match.start()]))
        if low:
            return True
    return False


def prefilter(text: str | None, dose_g: float = R.HYPO_DOSE_G) -> dict[str, Any] | None:
    """The card to show **instead of** calling AI, or ``None`` when the text is not about a low."""
    if not mentions_low(text):
        return None
    return {"status": "treating_a_low", "card": M.treating_a_low_card(dose_g), "ai_called": False}
