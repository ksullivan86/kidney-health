"""The AI recipes screens (note 16 §10, phase 3): "Suggest recipes with AI" in Plan and "Rework with AI" in the fit sheet, shown
only when the server offers the feature; the sheet asks through the consent flow with the feature "recipes"; a card saves only
on a tap, through the ordinary saved-meal route, and never twice; the consent wording names recipes (static checks)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
PLAN = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
AI = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
HANDBOOK = (ROOT / "handbook" / "docs" / "app" / "planning-and-menus.md").read_text(encoding="utf-8")


def test_the_buttons_start_hidden_and_follow_the_servers_answer():
    assert '<p class="settings-actions" id="ai-recipes-row" hidden>' in INDEX and 'id="btn-ai-recipes"' in INDEX
    assert 'id="fit-rework" hidden' in INDEX
    assert "st.features && st.features.recipes" in PLAN
    assert "$('#ai-recipes-row').hidden = !on" in PLAN and "$('#fit-rework').hidden = !on" in PLAN


def test_the_request_goes_through_the_consent_flow_of_its_own_feature():
    assert "recipes: (b, dry) => request('POST', `/api/ai/recipes${dry ? '?dry_run=true' : ''}`, b)" in AI
    assert "withConsent('text', () => api.recipes(b), () => api.recipes(b, true), btn, 'recipes')" in AI
    assert "showSent(await api.recipes(reqBody(), true)" in AI  # "What will be sent?"
    assert "openRecipes" in AI.split("KH.ai = {", 1)[1]


def test_a_card_saves_only_on_a_tap_and_only_once():
    card = AI[AI.index("function recipeCard"):AI.index("function renderRecipes")]
    assert "api.createMeal(card.body)" in card and "if (btn.dataset.saved) return;" in card
    assert "status: 'planned'" in card  # Add to plan plans one serving; nothing is eaten without the person
    assert "card.steps_label" in card and "card.notice" in card


def test_a_rework_says_what_is_never_sent_and_the_consent_names_recipes():
    assert "Its name, note, steps and link are never sent." in AI
    assert "the foods and amounts of a recipe (never its name, note, steps or link)" in AI


def test_the_handbook_explains_it():
    for needle in ("Suggest recipes with AI", "Rework with AI", "(reworked)", "never sent", "not for cooking times or food safety"):
        assert needle in HANDBOOK, needle
