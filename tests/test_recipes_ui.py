"""The recipe screens (note 16 §10, phase 2): the editor's Makes, link and steps fields, the "Fit to my targets" sheet, Save as
"<name> (fitted)", Replace with a confirm that shows carbohydrate before and after and an Undo, the old note hidden, and the demo's
twin wired in (static checks; the twin itself is checked by the parity vectors)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
PLAN = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "guidance.js").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "plan.css").read_text(encoding="utf-8")
BASE_CSS = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
HANDBOOK = (ROOT / "handbook" / "docs" / "app" / "planning-and-menus.md").read_text(encoding="utf-8")


def test_the_editor_has_labelled_fields_for_makes_link_and_steps():
    for field in ("meal-makes", "meal-source", "meal-steps"):
        assert f'id="{field}"' in INDEX and f'for="{field}"' in INDEX, field
    assert 'id="meal-source" type="url"' in INDEX and "never opens it" in INDEX
    body = PLAN[PLAN.index("const makes = $('#meal-makes')"):PLAN.index("mealEd.busy = true")]
    assert "servings_made" in body and "steps" in body and "source_url" in body


def test_the_fit_sheet_is_wired_to_the_route_and_saves_only_on_a_tap():
    assert 'id="sheet-fit"' in INDEX and 'for="fit-target"' in INDEX and 'id="fit-result" aria-live="polite"' in INDEX
    assert "fitRecipe: (b) => request('POST', '/api/guidance/fit-recipe', b)" in CORE
    assert "api.fitRecipe(" in PLAN and "'Fit to my targets'" in PLAN
    # Save makes a new recipe; Replace asks first, shows carbohydrate before and after, and can be undone (decision 7).
    assert "`${fit.meal.name} (fitted)`" in PLAN and "api.createMeal(fittedBody(" in PLAN
    replace = PLAN[PLAN.index("$('#fit-replace').addEventListener"):PLAN.index("async function undoReplace")]
    assert "confirm.inline(" in replace and "carbsLine()" in replace and "fit.undo = old" in replace
    assert "Carbohydrate per serving goes from" in PLAN and "'Undo'" in PLAN
    # Nothing to save when it fits as it is or does not fit.
    assert "const canSave = !!r.fitted && r.status !== 'fits';" in PLAN


def test_the_old_recipe_sentence_is_hidden_only_for_a_recipe():
    match = re.search(r"const OLD_RECIPE_NOTE = /(.+)/;", PLAN)
    assert match
    pattern = re.compile(match.group(1).replace("\\/", "/"))
    assert pattern.fullmatch("Makes 4 servings.") and pattern.fullmatch("Makes 1 serving. Source: https://example.com/a")
    assert not pattern.fullmatch("Makes 4 servings, freezes well.")
    assert "t.servings_made != null && OLD_RECIPE_NOTE.test(t.note)" in PLAN


def test_the_demo_runs_the_twin_and_works_offline():
    assert "'/js/engine/guidance/recipes.js'," in SW
    srcs = re.findall(r'<script src="([^"]+)"', INDEX)
    assert srcs.index("js/engine/guidance/recipes.js") == srcs.index("js/engine/guidance/hypo.js") + 1
    route = MOCK[MOCK.index("route('POST', '/api/guidance/fit-recipe'"):]
    assert "GE.fitRecipe(ctx, recipe, servingsMade" in route and "this._guidanceGate()" in route


def test_the_colours_come_from_the_theme():
    for token in re.findall(r"var\((--[a-z0-9-]+)\)", CSS[CSS.index("Fit to my targets"):]):
        assert f"{token}:" in BASE_CSS, token


def test_the_handbook_explains_the_order_and_the_choices():
    for needle in ("Fit to my targets", "never below half", "never takes away protein", "at most 2 swaps", "¾, then ½",
                   "(fitted)", "Replace this recipe", "undo it", "never opens"):
        assert needle in HANDBOOK, needle
