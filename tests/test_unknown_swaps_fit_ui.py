"""The swap ideas and the Fit to my targets sheet never show a value a food does not list as 0 or as an exact number (roadmap
"Unknown, zero and partial, the same on every screen"). Static checks of the screen code and the demo's twin texts; the server
and the twin are compared by the UNKNOWN cases of tests/data/guidance_vectors.json, and the engine by
tests/guidance/test_swaps.py and tests/guidance/test_recipe_fit.py."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from app.guidance import messages as M

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
PLAN = (JS / "views" / "plan.js").read_text(encoding="utf-8")
GUIDANCE = (JS / "views" / "guidance.js").read_text(encoding="utf-8")
MESSAGES = (JS / "engine" / "guidance" / "messages.js").read_text(encoding="utf-8")
SWAPS = (JS / "engine" / "guidance" / "swaps.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "css" / "plan.css").read_text(encoding="utf-8")
VECTORS = json.loads((ROOT / "tests" / "data" / "guidance_vectors.json").read_text(encoding="utf-8"))


def _between(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def test_the_fit_sheet_rows_say_at_least_or_not_listed():
    # The rows themselves are rendered by tests/js/recipe_fit_unknown.test.mjs.
    number = _between(PLAN, "function fitNumber(", "function fitRow(")
    assert "fig.per_serving[key] == null) return 'not listed';" in number
    assert "atLeast(fmtNum(check.used, key), unknownOf(fig.unknown, key))" in number
    row = _between(PLAN, "function fitRow(", "function renderFit(")
    assert "fitNumber(before, c, key)" in row and "fitNumber(after, now, key)" in row
    assert "'fit-unknown'" in row  # within the room on what is known: grey, never the green "fits"
    assert "fitRow(c, r.before, after)" in PLAN
    assert ".fit-checks li.fit-unknown" in CSS


def test_the_fit_sheet_note_names_only_the_nutrients_it_shows():
    sheet = _between(PLAN, "function renderFit(", "const MAX_RECIPE_SERVINGS")
    assert "r.before.checks.map((c) => c.nutrient)" in sheet and "after.unknown" in sheet
    # In words ("potassium and phosphorus"), never the chip letters ("k, p").
    assert "joinWords(unknown.map((k) => NUT[k].label.toLowerCase()))" in sheet and ".short.toLowerCase()" not in sheet


def test_a_low_treatment_row_says_which_value_is_not_listed():
    # The row shows the food's own numbers: a value it does not list reads "potassium not listed", never 0 and never left out.
    numbers = _between(GUIDANCE, "const KEY_NUMBERS", "function ratingOf")
    assert "n[k] != null || unknown.includes(k)" in numbers and "KEY_NUMBERS.filter((k) => n && n[k] == null)" in numbers
    assert "keyNumbers(o.nutrients, notListedIn(o.nutrients))" in _between(GUIDANCE, "function lowOption(", "\n  }\n")


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


# The same calls on the server's texts and the demo's twin (app/static/js/engine/guidance/messages.js): with a value not
# listed, a value some foods do not list ("at least") and every value listed.
_TWIN_CALLS: list[tuple[str, str, list]] = [
    ("amount_text", "amountText", ["potassium_mg", 600, True, False]),
    ("amount_text", "amountText", ["phosphorus_mg", None, True, True]),
    ("amount_word", "amountWord", ["carbs_g", None]),
    ("amount_word", "amountWord", ["potassium_mg", 1234]),
    ("fit_text", "fitText", [{"carbs_g": None, "potassium_mg": 55, "phosphorus_mg": None}, ["potassium_mg", "phosphorus_mg"], True]),
    ("fit_text", "fitText", [{"carbs_g": 45, "potassium_mg": 55, "phosphorus_mg": 70}, ["potassium_mg", "phosphorus_mg"], True]),
    ("swap_hypo_text", "swapHypoText", ["Apple juice", 1.25, "1/2 cup (124 g)", 18, None]),
    ("swap_hypo_text", "swapHypoText", ["Glucose tablets", 1, "4 tablets", 16, 0]),
    ("swap_avoid_text", "swapAvoidText", ["Blueberries", 1, "1/2 cup (74 g)", {"carbs_g": None, "potassium_mg": 55}, "Star fruit"]),
    ("portion_option_text", "portionOptionText", [0.5, None, {"potassium_mg": None, "phosphorus_mg": 40}, ["potassium_mg", "phosphorus_mg"]]),
    ("recipe_smaller_text", "recipeSmallerText", [0.75, "phosphorus_mg", "this dinner's room", 215, 161, 167, True]),
    ("recipe_smaller_text", "recipeSmallerText", [0.5, "potassium_mg", "this dinner's room", None, None, 750, False]),
    ("recipe_no_fit_text", "recipeNoFitText", ["what is left today", {"nutrient": "phosphorus_mg", "used": 460, "room": 167}, True]),
    ("recipe_lowered_text", "recipeLoweredText", ["Potato, baked", "1 medium (173 g)", 4, 3.25, "potassium_mg", "this dinner's room",
                                                  925, 752, True, True]),
    ("recipe_swapped_text", "recipeSwappedText", ["Chicken", "Egg white", "1 large", 6, "potassium_mg", "this lunch's room",
                                                  {"potassium_mg": 1850, "protein_g": 8}, {"potassium_mg": 100, "protein_g": 6.9},
                                                  {"potassium_mg": 1, "protein_g": 1}, {}]),
]

_TWIN_RUNNER = """
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const [root, calls] = [process.argv[1], JSON.parse(readFileSync(0, 'utf8'))];
const ctx = vm.createContext({ console });
for (const rel of ['engine/rules.js', 'engine/guidance/rules.js', 'engine/guidance/messages.js']) {
  vm.runInContext(readFileSync(`${root}/${rel}`, 'utf8'), ctx, { filename: rel });
}
const M = vm.runInContext('globalThis.KH.guidanceEngine.M', ctx);
process.stdout.write(JSON.stringify(calls.map(([fn, args]) => M[fn](...args))));
"""


def test_the_twin_texts_match_the_server_for_values_not_listed():
    assert shutil.which("node"), "Node.js is required for the twin checks"
    calls = [[js, args] for _, js, args in _TWIN_CALLS]
    run = subprocess.run(["node", "--input-type=module", "-e", _TWIN_RUNNER, str(JS)], input=json.dumps(calls),
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    for (py, _, args), js_text in zip(_TWIN_CALLS, json.loads(run.stdout), strict=True):
        assert getattr(M, py)(*args) == js_text, (py, args)
