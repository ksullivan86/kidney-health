#!/usr/bin/env python3
"""Generate tests/data/lists_recipes_vectors.json: parity vectors for the browser twins of design note 30.

    python3 tests/data/gen_lists_recipes_vectors.py           # rewrite the file
    python3 tests/data/gen_lists_recipes_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code and replayed by ``node tests/js/run_vectors.mjs``:

* ``app/recipe_import/parse.py`` against ``app/static/js/engine/recipe_import.js``: text cleaning, finding the ``Recipe`` in
  JSON-LD, the yield, the steps, ingredient lines, pasted text, the ingredient-line parser, search words and amounts;
* ``app/list_sync/api.py`` (``list_item``) against the demo's ``js/mock/lists.js``: the words each list line is sent with.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "lists_recipes_vectors.json"
sys.path.insert(0, str(ROOT))

from app.list_sync.api import list_item  # noqa: E402
from app.recipe_import import parse as P  # noqa: E402

TEXTS = ["  Plain  text ", "<b>Bold</b> and <i>it</i>.", "Fish &amp; chips &#38; peas &#x27;n&#x27; &frac12; cup",
         "Tab\tand\nnew line", "Ends with a tag <br/>.", "&nbsp;Lead", 42, None, True, ["x"], "",
         "Quote &quot;this&quot; &lt;tag&gt;", "Control\u0007char"]

RECIPE_DOCS: list[Any] = [
    {"@type": "Recipe", "name": "Plain", "recipeYield": "4 servings", "recipeIngredient": ["1 cup rice", "2 eggs"],
     "recipeInstructions": "Cook the rice.\nAdd the eggs."},
    {"@context": "https://schema.org", "@graph": [{"@type": "WebSite", "name": "Site"},
                                                  {"@type": ["Recipe"], "name": "In a graph", "recipeYield": ["6", "6 bowls"],
                                                   "recipeIngredient": ["200 g pasta"],
                                                   "recipeInstructions": [{"@type": "HowToSection", "name": "Sauce",
                                                                           "itemListElement": [{"@type": "HowToStep", "text": "Stir."},
                                                                                               {"@type": "HowToStep", "name": "Serve."}]}]}]},
    [{"@type": "Organization"}, {"@type": "http://schema.org/Recipe", "name": "Second in an array", "ingredients": "3 cups milk"}],
    {"@type": "WebPage", "mainEntity": {"@type": "schema:Recipe", "name": "Main entity", "recipeYield": 2.5}},
    {"@type": "Article", "name": "No recipe"},
    {"@type": "Recipe", "name": "<b>Tagged</b> &amp; long", "recipeYield": "0",
     "recipeIngredient": [f"{i} g flour" for i in range(65)],
     "recipeInstructions": [f"Step {i}." for i in range(24)]},
    {"@type": "Recipe", "recipeInstructions": [" ".join(f"Sentence {i} is quite long, with words." for i in range(30)), "x" * 1100]},
    "just a string",
]

YIELDS = [4, "6 servings", ["2", "2 bowls"], "Makes 8", "4-6", "1.5", "0", 500, "a big pot", None, True, {"v": 4}, [], ["x", 3]]

LINES = [
    "2 cups white rice, rinsed", "1 1/2 lb boneless chicken breast", "½ cup low-sodium chicken broth", "1½ cups whole milk",
    "1 (14.5 oz) can diced tomatoes", "2 15-ounce cans black beans, drained", "3 cloves garlic, minced", "Salt and pepper, to taste",
    "2-3 carrots, peeled", "1 to 2 tbsp honey", "1 tablespoon olive oil", "200 g pasta", "1,5 kg potatoes", "1,000 g flour",
    "a pinch of salt", "a few sprigs thyme", "an apple", "One onion, diced", "twelve eggs", "2 large eggs", "1 cup (240 ml) milk",
    "350 g/12 oz flour", "▢ 1 c. sugar", "• 2 Tbsp. unsalted butter or margarine", "8 fl oz apple juice", "1 fl. oz lemon juice",
    "3 1/4 cups water", "1⁄2 tsp salt", "1/0 cup nothing", "2 (8 ounce) packages cream cheese, softened", "1 (large) onion",
    "4 slices bread", "Juice of 1 lemon", "(optional) parsley", ", just a note", "1 l stock", "500ml milk", "2lbs beef",
    "1 chicken, cut up", "10 1/2 oz soup", "  ", "1 cup/240 ml water", "3 ½ cups flour", "¾", "2 cans (15 oz each) beans",
]

PASTES = ["For the sauce:\n1 cup tomato\n\n2 tsp sugar\nStep 3:\n", "\r\n1 egg\r\n  • 2 cups milk  \r\n",
          "\n".join(f"{i} g banana" for i in range(1, 66)), ""]

FOODS = ["boneless skinless chicken breasts", "diced tomatoes", "butter or margarine", "fresh berries (any kind)",
         "Salt and pepper to taste", "", "chopped", "low-sodium chicken broth", "large eggs", "Jalapeño peppers", "olive oil, for frying",
         "rice/quinoa", "whole wheat flour plus more for dusting", "a b c d e f g h", "dishes boxes glasses", "asparagus hummus",
         "cheese for serving", "optional parsley", "dried thyme", "extra virgin olive oil", "chicken thighs, bone-in, skin-on"]

SERVINGS = [
    (2, "cup", "1/2 cup (79 g)", 79), (1.5, "lb", "3 oz (85 g)", 85), (200, "g", "1 cup (140 g)", 140),
    (2, None, "1 large (50 g)", 50), (3, "clove", "1 clove (3 g)", 3), (1, "tbsp", "1 tsp (5 g)", 5),
    (8, "fl_oz", "1 cup, 8 fl oz (248 g)", 248), (2, None, "3 oz (85 g)", 85), (1, "cup", "3 oz (85 g)", 85),
    (1, "pinch", "1 tsp (6 g)", 6), (None, "cup", "1 cup", 240), (2, "slice", "1 medium (118 g)", 118),
    (0.001, "g", "1 cup (240 g)", 240), (4, "slice", "2 slices (60 g)", 60), (1, "can", "1 can, 12 fl oz (355 g)", 355),
    (1, "l", "1 cup (240 g)", 240), (500, "ml", "1/2 cup (120 g)", 120), (1, "kg", "1 cup (0 g)", 0), (5000, "kg", "1 oz (28 g)", 28),
    (8, None, "4 spears (60 g)", 60), (1, None, "1 cup, chopped (160 g)", 160), (2, "piece", "1 piece (30 g)", 30),
    (1, "tsp", "1 1/2 tsp (7 g)", 7), (3, None, "", 0), (1, "cup", "½ cup (60 g)", 60),
]

LIST_ITEMS = [("Banana, raw", 2, "1 medium (118 g)"), ("Chicken breast, roasted", 1, "3 oz (85 g)"), ("Rice", 0.5, "1/2 cup"),
              ("Milk", 1.255, "1 cup"), ("Water", 1200, "1 cup (240 g)"), ("Salt", 0.333, ""), ("Oil", 2.005, "1 tbsp")]


def build() -> dict[str, Any]:
    recipe_cases = []
    for doc in RECIPE_DOCS:
        found = P.find_recipe(doc)
        recipe_cases.append({"doc": doc, "found": found is not None,
                             "recipe": P.recipe_from_jsonld(found) if found is not None else None})
    return {
        "constants": {"max_lines": P.MAX_LINES, "max_line_chars": P.MAX_LINE_CHARS, "max_steps": P.MAX_STEPS,
                      "max_step_chars": P.MAX_STEP_CHARS},
        "text_cases": [{"value": v, "text": P.text_of(v)} for v in TEXTS],
        "recipe_cases": recipe_cases,
        "yield_cases": [{"value": v, "servings": P.yield_of(v)} for v in YIELDS],
        "line_cases": [{"line": line, "parsed": P.parse_line(line)} for line in LINES],
        "paste_cases": [{"text": t, "lines": list(P.lines_of_text(t)[0]), "cut": P.lines_of_text(t)[1]} for t in PASTES],
        "term_cases": [{"food": f, "terms": P.search_terms(f)} for f in FOODS],
        "serving_cases": [{"amount": a, "unit": u, "serving_desc": d, "serving_g": g, "servings": P.recipe_servings(a, u, d, g)}
                          for a, u, d, g in SERVINGS],
        "list_text_cases": [{"food_name": n, "servings": s, "serving_desc": d,
                             **{k: v for k, v in vars(list_item({"food_id": 1, "food_name": n, "servings": s, "serving_desc": d})).items()
                                if k in ("name", "amount", "text")}} for n, s, d in LIST_ITEMS],
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_lists_recipes_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    data = build()
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['line_cases'])} lines, {len(data['recipe_cases'])} recipes, "
          f"{len(data['serving_cases'])} amounts, {len(data['term_cases'])} searches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
