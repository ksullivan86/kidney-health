"""Meal totals never show an unknown value as 0 (the 2026-10-29 review, roadmap "Unknown, zero and partial"): the guidance meal
chips, meal sheet and plan, the AI idea cards and the "Add a saved meal" sheet read ``unknown`` (or the saved meal's ``unknown`` and
``per_serving``) and say "≥" or "not listed" (static checks; the server and the demo's twin are compared by the UNKNOWN cases of
tests/data/guidance_vectors.json and tests/guidance/test_api_guidance.py)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "app" / "static" / "js" / "views"
GUIDANCE = (VIEWS / "guidance.js").read_text(encoding="utf-8")
AI = (VIEWS / "ai.js").read_text(encoding="utf-8")
PLAN = (VIEWS / "plan.js").read_text(encoding="utf-8")


def test_guidance_meals_mark_unknown_totals():
    key = GUIDANCE[GUIDANCE.index("function keyNumber("):GUIDANCE.index("function ratingOf")]
    assert "`≥ ${fmtNum(n[k], k)} ${NUT[k].unit} ${word}`" in key and "`${word} not listed`" in key
    assert GUIDANCE.count("keyNumbers(m.totals, m.unknown)") == 2  # the meal sheet and the plan
    chip = GUIDANCE[GUIDANCE.index("function mealChip"):GUIDANCE.index("function mealChip") + 600]
    assert "keyNumber(m.totals, 'carbs_g', m.unknown)" in chip and "keyNumber(m.totals, 'potassium_mg', m.unknown)" in chip


def test_ai_ideas_mark_unknown_totals():
    line = AI[AI.index("function nutrientLine"):AI.index("function refreshDayCaches")]
    assert "≥ ${fmtNum(v, key)}" in line and "not listed" in line
    assert "nutrientLine(idea.totals, ['carbs_g', 'protein_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg'], idea.unknown || [])" in AI


def test_the_add_saved_meal_sheet_marks_unknown_totals():
    sheet = PLAN[PLAN.index("const scaled = scaledNutrients(t.totals, scale);"):PLAN.index("const date = $('#apply-date').value;")]
    assert "t.per_serving[k] == null" in sheet and "'not listed'" in sheet
    assert "unknownOf(t.unknown, k)" in sheet and "atLeast(fmtNum(scaled[k], k), unk)" in sheet
