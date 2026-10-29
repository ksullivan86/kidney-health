"""The swap ideas and the Fit to my targets sheet never show a value a food does not list as 0 or as an exact number (roadmap
"Unknown, zero and partial, the same on every screen"). Static checks of the screen code and the demo's twin texts; the server
and the twin are compared by the UNKNOWN cases of tests/data/guidance_vectors.json, and the engine by
tests/guidance/test_swaps.py and tests/guidance/test_recipe_fit.py."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
PLAN = (JS / "views" / "plan.js").read_text(encoding="utf-8")
MESSAGES = (JS / "engine" / "guidance" / "messages.js").read_text(encoding="utf-8")
SWAPS = (JS / "engine" / "guidance" / "swaps.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "css" / "plan.css").read_text(encoding="utf-8")
VECTORS = json.loads((ROOT / "tests" / "data" / "guidance_vectors.json").read_text(encoding="utf-8"))


def _between(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def test_the_fit_sheet_rows_say_at_least_or_not_listed():
    number = _between(PLAN, "function fitNumber(", "function fitRow(")
    assert "fig.per_serving[key] == null" in number and "return null;" in number
    assert "atLeast(fmtNum(check.used, key), unknownOf(fig.unknown, key))" in number
    row = _between(PLAN, "function fitRow(", "function renderFit(")
    assert "fitNumber(before, c, key)" in row and "fitNumber(after, now, key)" in row and "'not listed'" in row
    assert "'fit-unknown'" in row  # within the room on what is known: grey, never the green "fits"
    assert "fitRow(c, r.before, after)" in PLAN
    assert ".fit-checks li.fit-unknown" in CSS


def test_the_fit_sheet_note_names_only_the_nutrients_it_shows():
    sheet = _between(PLAN, "function renderFit(", "const MAX_RECIPE_SERVINGS")
    assert "r.before.checks.map((c) => c.nutrient)" in sheet and "after.unknown" in sheet


def test_the_saved_and_replaced_message_says_at_least_for_carbohydrate():
    line = _between(PLAN, "const carbsOf = ", "$('#fit-target').addEventListener")
    assert "atLeastWords(fmtNum(fig.per_serving.carbs_g, 'carbs_g'), unknownOf(fig.unknown, 'carbs_g'))" in line
    assert "'not listed'" in line and "No food in it lists carbohydrate." in line


def test_the_twin_texts_never_turn_a_missing_value_into_0():
    for name in ("function swapAvoidText", "function swapHypoText", "function portionOptionText"):
        body = _between(MESSAGES, name, "\n  }\n")
        assert "|| 0" not in body, name
    assert "${head}; potassium not listed" in MESSAGES and "not listed`" in MESSAGES
    assert "M.portionOptionText(fraction, a[R.CARBS], a," in SWAPS
    assert "neu[k] == null || orig[k] == null ? null" in SWAPS  # a swap's difference is null, never a difference from 0


def test_the_vectors_cover_the_swap_ideas_and_the_fit_sheet():
    ids = [c["id"] for c in VECTORS["cases"] if c["id"].startswith("UNKNOWN")]
    assert sum("swaps" in i for i in ids) >= 3 and any("low treatments" in i for i in ids)
    assert sum(i.startswith("UNKNOWN REC") for i in ids) >= 4
    texts = json.dumps([c["output"] for c in VECTORS["cases"] if c["id"].startswith("UNKNOWN")], ensure_ascii=False)
    for phrase in ("carbs not listed", "potassium not listed", "Potassium per serving: at least 925 → at least 752 mg",
                   "Still over: phosphorus at least"):
        assert phrase in texts, phrase
