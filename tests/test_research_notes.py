"""The research notes the targets rule catalogue cites state the rules the app ships (v0.3.0 review, L1).

``app/target_rules.py`` points at ``docs/research/ckd-diet.md`` (rule K-0's source line), and maintainers check
the app's numbers against these notes. Design note 05 changed three things they first said: protein with diabetes
at G3a-G5 is 0.8 g/kg (fact-check H1), the KDOQI 2020 statement numbers are the published guideline's, not the
2019 draft's (F1: 3.0.1-3.0.4 protein, 3.1.1 energy), and grams per kg use a reference weight, not "ideal body
weight" (F2, KDOQI 1.1.6). Each note carries a dated "superseded in part" banner, and outside that banner none
repeats the old wording. ``docs/research/fact-check.md`` is the record of the first check and keeps its rows; it
only needs the banner.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1] / "docs" / "research"
NOTES = ("ckd-diet.md", "food-lists.md", "t1d-and-ckd.md")
BANNER = "**Superseded in part by design note 05 (v0.3"

# The old wording: the draft's statement numbers for protein and energy, ideal body weight, and 0.6 as the
# diabetes default.
STALE = {
    "draft KDOQI protein numbering": re.compile(r"KDOQI(?: 2020)? 3\.1\.[2-4]|3\.1\.2/3\.1\.4|Statements 3\.1\.1–3\.1\.4"),
    "draft KDOQI protein numbering in the statement list": re.compile(r"^\s*- 3\.1\.(?:[2-4]|1 Non-diabetic) ", re.M),
    "draft KDOQI energy numbering": re.compile(r"3\.0\.1[,:]?\s*(?:\(?1C|\*\*25–35|25–35 kcal)|Statement 3\.0\.1"),
    "ideal body weight": re.compile(r"ideal body weight|\bIBW\b|\*\*ideal\*\* body weight", re.I),
    "0.6-0.8 as the diabetes default": re.compile(r"With diabetes: 0\.6–0\.8|tracker default is \*\*0\.6–0\.8"),
}


def _outside_banner(text: str) -> str:
    """The note without its superseded banner (the blockquote that starts with the banner's first line)."""
    lines, out, in_banner = text.splitlines(), [], False
    for line in lines:
        if line.startswith("> " + BANNER):
            in_banner = True
        elif in_banner and not line.startswith(">"):
            in_banner = False
        if not in_banner:
            out.append(line)
    return "\n".join(out)


@pytest.mark.parametrize("name", [*NOTES, "fact-check.md"])
def test_each_research_note_says_it_is_superseded_where_note_05_differs(name: str) -> None:
    text = (RESEARCH / name).read_text(encoding="utf-8")
    head = text[:4000]
    assert "> " + BANNER in head, f"{name}: the superseded banner belongs at the top"
    assert "2026-10-07" in head and "note 05" in head


@pytest.mark.parametrize("name", NOTES)
def test_research_notes_no_longer_state_the_pre_v03_protein_rule(name: str) -> None:
    body = _outside_banner((RESEARCH / name).read_text(encoding="utf-8"))
    found = {label: m.group(0) for label, rx in STALE.items() if (m := rx.search(body))}
    assert not found, f"{name} still says: {found}"


def test_the_banner_check_would_catch_the_old_rows() -> None:
    """The patterns match the rows the review quoted, so the test above is not vacuous."""
    old_rows = [
        "| **Protein** (g/kg/day) | **With diabetes: 0.6–0.8** (KDOQI 3.1.3, OPINION) [1];",
        "| **Energy** (kcal/kg/day) | **25–35** (KDOQI 3.0.1, 1C) [1] |",
        "### 2.1 Summary table (adult, ideal body weight; see 2.2–2.9 for sources and caveats)",
        "| Protein | **0.6–0.8 g/kg ideal body weight/day** with diabetes (KDOQI 3.1.3); | **1.0–1.2 g/kg** (KDOQI 3.1.2/3.1.4; ADA)",
        "KDOQI 2020 energy guidance is 25–35 kcal/kg ideal body weight/day (Statement 3.0.1, 1C;",
        "  - 3.1.3 CKD 3–5 **with diabetes**: **0.6–0.8 g/kg IBW/day**",
    ]
    for row in old_rows:
        assert any(rx.search(row) for rx in STALE.values()), row


def test_the_handbook_review_no_longer_waits_for_the_targets_change() -> None:
    review = (Path(__file__).resolve().parents[1] / "handbook" / "REVIEW.md").read_text(encoding="utf-8")
    open_items = re.sub(r"~~.*?~~", "", review, flags=re.S)  # struck-through items are done
    assert "the app still suggests 0.6–0.8 g/kg protein with diabetes" not in open_items
