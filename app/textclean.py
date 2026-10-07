"""Clean text that comes from outside the app before it is stored, scanned or shown (note 03 §9 B3).

Open Food Facts is a wiki: anyone can edit a product's name, brand or ingredient list. FoodData
Central and an AI label reader return text we did not write either. Two things can go wrong with
such text, and this module removes both:

* **Invisible characters defeat the additive scan.** A zero-width space or a soft hyphen inside
  "phos​phate" or "potassium­chloride" (both Unicode category ``Cf``) keeps the
  ingredient regexes of :mod:`app.additives` from matching, so ``phosphate_additive`` or
  ``potassium_additive`` would silently be missing: a safety false negative.
* **Bidi controls** (U+202A–U+202E, U+2066–U+2069) make a stored name display differently from what
  it is, and control characters (``Cc``) can break CSV files, logs and terminals.

:func:`clean_text` applies the review's recipe in one place, so the database, the additive scan,
the UI and any AI prompt all see the same string: NFKC, remove every ``Cf`` and ``Cc`` character
(except LF where line breaks are kept) and lone surrogates, collapse whitespace, cap the length.
Pure functions, no I/O.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# Categories removed outright: format (zero-width, soft hyphen, bidi, BOM), control, lone surrogates.
_REMOVED_CATEGORIES = frozenset({"Cf", "Cc", "Cs"})
# Characters that end a line (kept as "\n" when line breaks are kept, else a space).
_LINE_BREAKS = frozenset({"\n", "\r", " ", " ", "\x0b", "\x0c", "\x85"})
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{2,}")


def _strip_invisible(text: str, keep_newlines: bool) -> str:
    out: list[str] = []
    for ch in text:
        if ch in _LINE_BREAKS:
            out.append("\n" if keep_newlines else " ")
        elif ch == "\t":
            out.append(" ")
        elif unicodedata.category(ch) in _REMOVED_CATEGORIES:
            continue
        else:
            out.append(ch)
    return "".join(out)


def clean_text(value: Any, *, max_len: int, keep_newlines: bool = False) -> str | None:
    """``value`` as safe display text, or ``None`` when it is not a string or nothing is left.

    * NFKC (full-width letters, ligatures and compatibility forms become their plain form, so
      "ＰＨＯＳＰＨＡＴＥ" is scanned like "PHOSPHATE");
    * every ``Cf`` (zero-width, soft hyphen, bidi controls, BOM), ``Cc`` (control) and ``Cs`` (lone
      surrogate) character is removed; CR, LF, the Unicode line and paragraph separators become a
      line break when ``keep_newlines`` (ingredient lists), otherwise a space; TAB becomes a space;
    * NFKC again (removing a character can bring a base letter and a combining mark together);
    * runs of spaces collapse to one, lines are trimmed, blank lines dropped;
    * the result is cut to ``max_len`` characters (then trimmed again).

    The function is idempotent: ``clean_text(clean_text(x)) == clean_text(x)``.
    """
    if not isinstance(value, str):
        return None
    if max_len < 1:
        raise ValueError("max_len must be at least 1")
    text = unicodedata.normalize("NFKC", value)
    text = _strip_invisible(text, keep_newlines)
    text = unicodedata.normalize("NFKC", text)
    text = _HORIZONTAL_SPACE.sub(" ", text)
    if keep_newlines:
        text = "\n".join(line.strip() for line in text.split("\n"))
        text = _BLANK_LINES.sub("\n", text).strip("\n")
    text = text.strip()[:max_len].strip()
    return text or None


def clean_label(value: Any, *, max_len: int) -> str | None:
    """A one-line label (product name, brand, serving text): :func:`clean_text` without line breaks."""
    return clean_text(value, max_len=max_len, keep_newlines=False)
