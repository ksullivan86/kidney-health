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

# Words and phrases that may describe a low (case-insensitive, after NFKC and apostrophe folding).
_TERMS = re.compile(
    r"\b(hypo\w*|shak(?:y|ey|ing|es)|sweat(?:y|ing)|trembl\w*|jitter\w*|dizzy|light[- ]?headed|faint\w*|"
    r"blurr\w* vision|pounding heart|racing heart|treat(?:ing)? a low|going low|feel(?:ing)? low|"
    r"i'?m low|i am low|running low|dropping|crashing|low (?:blood )?(?:sugar|glucose|bg|bs)|"
    r"(?:sugar|glucose|bg|bs|cgm|reading)s? (?:is |are |was |went |getting |dropped )?(?:low|down|dropping))\b",
    re.IGNORECASE,
)
# "low" on its own counts, except as a food descriptor ("low-fat milk", "low sodium soup").
_LOW_WORD = re.compile(
    r"\blow\b(?![-\s]*(?:fat|sodium|salt|sugar|carb\w*|cal\w*|potassium|phosph\w*|fib(?:er|re)|lactose|"
    r"cholesterol|protein|gi|glycemic|glycaemic|in)\b)",
    re.IGNORECASE,
)
_LESS_THAN = re.compile(r"(?:glucose|sugar|bg|bs|cgm|reading)\s*(?:is|was|of|at|:)?\s*(?:<|under|below|less than)",
                        re.IGNORECASE)
_READING = re.compile(r"(?:glucose|sugar|bg|bs|cgm|reading)\s*(?:is|was|of|at|:)?\s*(\d{1,3}(?:[.,]\d)?)",
                      re.IGNORECASE)

MMOL_LOW = 3.9  # level 1 hypoglycaemia (ADA 2026 §6)
MGDL_LOW = 70.0


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    folded = "".join(ch for ch in folded if unicodedata.category(ch) not in ("Cc", "Cf") or ch in "\n\t")
    return folded.replace("’", "'").replace("‘", "'")


def mentions_low(text: str | None) -> bool:
    """Does free text possibly describe a low (or ask how to treat one)?"""
    if not text:
        return False
    folded = _fold(text)
    if _TERMS.search(folded) or _LOW_WORD.search(folded) or _LESS_THAN.search(folded):
        return True
    for match in _READING.finditer(folded):
        value = float(match.group(1).replace(",", "."))
        if ("." in match.group(1) or "," in match.group(1) or value < 30) and value <= MMOL_LOW:
            return True  # mmol/L
        if 30 <= value < MGDL_LOW:
            return True  # mg/dL
    return False


def prefilter(text: str | None, dose_g: float = R.HYPO_DOSE_G) -> dict[str, Any] | None:
    """The card to show **instead of** calling AI, or ``None`` when the text is not about a low."""
    if not mentions_low(text):
        return None
    return {"status": "treating_a_low", "card": M.treating_a_low_card(dose_g), "ai_called": False}
