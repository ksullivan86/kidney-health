"""Cleaning untrusted text before it is stored or scanned (note 03 §9 B3)."""
from __future__ import annotations

import random
import unicodedata

import pytest

from app.textclean import clean_label, clean_text

ZWSP, SOFT_HYPHEN, ZWJ, BOM, WORD_JOINER = "​", "­", "‍", "﻿", "⁠"
BIDI = ["‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩", "‎", "‏"]


@pytest.mark.parametrize("hidden", [ZWSP, SOFT_HYPHEN, ZWJ, BOM, WORD_JOINER, *BIDI])
def test_invisible_format_characters_are_removed(hidden: str) -> None:
    assert clean_label(f"sodium phos{hidden}phate", max_len=100) == "sodium phosphate"


def test_bidi_override_cannot_disguise_a_name() -> None:
    # "Banana" written with a right-to-left override would display reversed.
    assert clean_label("‮ananab‬", max_len=50) == "ananab"


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b", "\x7f", "\x9b"])
def test_control_characters_are_removed(control: str) -> None:
    assert clean_label(f"Diet{control} Coke", max_len=50) == "Diet Coke"


def test_lone_surrogates_are_removed() -> None:
    assert clean_label("Cola\ud800 Zero", max_len=50) == "Cola Zero"


def test_nfkc_makes_full_width_and_ligatures_plain() -> None:
    assert clean_label("ＰＨＯＳＰＨＡＴＥ", max_len=50) == "PHOSPHATE"
    assert clean_label("ﬁsh", max_len=50) == "fish"


def test_whitespace_collapses_and_tabs_become_spaces() -> None:
    assert clean_label("  Diet \t\t Coke  12 oz  ", max_len=50) == "Diet Coke 12 oz"


def test_line_breaks_are_spaces_in_labels_and_kept_in_ingredient_lists() -> None:
    text = "Water,\r\n\r\n  sugar phosphoric acid\n\n\nsalt"
    assert clean_label(text, max_len=100) == "Water, sugar phosphoric acid salt"
    assert clean_text(text, max_len=100, keep_newlines=True) == "Water,\nsugar\nphosphoric acid\nsalt"


def test_length_cap() -> None:
    assert clean_label("x" * 500, max_len=200) == "x" * 200
    assert clean_label("abc " + "d" * 10, max_len=4) == "abc"  # trimmed after the cut


@pytest.mark.parametrize("value", [None, 5, 1.5, ["a"], {"a": 1}, b"bytes", "", "   ", ZWSP * 3, "\x00\x01"])
def test_nothing_left_is_none(value: object) -> None:
    assert clean_label(value, max_len=10) is None


def test_max_len_must_be_positive() -> None:
    with pytest.raises(ValueError):
        clean_label("x", max_len=0)


def test_idempotent_and_free_of_removed_categories_on_random_text() -> None:
    rnd = random.Random(20261006)
    alphabet = ("abcXYZ019 ,.-'()\t\n\r" + ZWSP + SOFT_HYPHEN + BOM + "".join(BIDI) + "́̈é ﬁＡ \x00\x1f\x85 "
                "фосфат磷酸盐\ud800")
    for _ in range(3000):
        text = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 40)))
        for keep in (False, True):
            once = clean_text(text, max_len=25, keep_newlines=keep)
            if once is None:
                continue
            assert clean_text(once, max_len=25, keep_newlines=keep) == once
            assert len(once) <= 25
            assert once == once.strip()
            assert unicodedata.is_normalized("NFKC", once)
            for ch in once:
                assert unicodedata.category(ch) not in ("Cf", "Cs") and (unicodedata.category(ch) != "Cc" or ch == "\n")
            if not keep:
                assert "\n" not in once
