""""Show other foods", "Other ideas" and "Other recipes" (the owner, 2026-10-29): each asks again without what is already shown
(static checks of the screens; the server side is in tests/guidance/test_api_guidance.py, tests/test_ai_routes.py and
tests/test_ai_recipes.py, and the demo's twin in the OTHER case of tests/data/guidance_vectors.json)."""
from __future__ import annotations

from pathlib import Path

from app.guidance.api import MAX_EXCLUDE

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
GUIDANCE = (JS / "views" / "guidance.js").read_text(encoding="utf-8")
AI = (JS / "views" / "ai.js").read_text(encoding="utf-8")
MOCK = (JS / "mock" / "guidance.js").read_text(encoding="utf-8")


def test_what_fits_asks_again_without_the_foods_on_the_list():
    assert f"const MAX_EXCLUDE = {MAX_EXCLUDE};" in GUIDANCE and f"const MAX_EXCLUDE = {MAX_EXCLUDE};" in MOCK
    load = GUIDANCE[GUIDANCE.index("async function loadFits"):GUIDANCE.index("function renderFits(res")]
    assert "api.nextMeal(exclude ? { meal, date, exclude } : { meal, date })" in load
    assert "`next:${date}:${meal}:${exclude}`" in load  # an offline copy is kept per list, never mixed up
    assert "fits.excludeFor !== `${date}:${meal}`" in load  # another meal or day starts over
    other = GUIDANCE[GUIDANCE.index("function otherFoods"):GUIDANCE.index("function tipTitle")]
    assert "'Show other foods'" in other and "'Back to the first choices'" in other
    assert "next.length > MAX_EXCLUDE" in other
    assert "No other foods in your list fit" in GUIDANCE


def test_ai_ideas_and_recipes_send_the_foods_already_shown():
    assert "const MAX_SEEN = 60;" in AI and MAX_EXCLUDE == 60
    ideas = AI[AI.index("function mountIdeas"):AI.index("function openIdeas")]
    assert "button('Other ideas'" in ideas and "exclude_food_ids: exclude" in ideas
    assert "moreSeen(ctx.seen, ctx.last)" in ideas and "other.hidden = !ctx.last.length" in ideas
    recipes = AI[AI.index("function openRecipes"):AI.index("function closeButton")]
    assert "'Other recipes'" in recipes and "'Another way'" in recipes and "exclude_food_ids: exclude" in recipes
    assert "for (const el of [dish, makes]) el.addEventListener('change', reset);" in recipes
