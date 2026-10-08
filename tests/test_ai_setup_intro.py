"""Settings → AI ideas opens with "How AI help is set up: three questions" (docs/ROADMAP.md, "Explain the AI setup in
plain words"; the same three questions as docs/ai.md "The setup in three questions" and the handbook's AI page).

Shown only when AI is on for this server (with AI off there is nothing to set up), never in the demo, closed by
default, before the person's own choices, and linking to the handbook page through the server's link table.
"""
from __future__ import annotations

from pathlib import Path

from app.handbook import LINKS

ROOT = Path(__file__).resolve().parents[1]
AI_JS = (ROOT / "app" / "static" / "js" / "views" / "ai.js").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_the_intro_asks_the_three_questions():
    intro = _between(AI_JS, "function setupIntro()", "\n  }\n")
    assert "h('details', { class: 'settings-details ai-setup', id: 'set-ai-setup' }" in intro  # closed by default
    for question in ("Which model answers? ", "What may it do? ", "Whose key pays, and who can read the request? "):
        assert question in intro, question
    # what the docs promise, in the person's words
    for words in ("a model that runs at home, or a company\\'s AI service", "your own key", "checked again",
                  "It cannot chat, give insulin or medicine doses, ", "or save anything by itself", "your admin can read what is sent",
                  "the consent step says where requests go", "“What will be sent?” shows each request before it leaves"):
        assert words in intro, words
    assert "KH.learn.link('pages', 'ai'" in intro


def test_it_is_shown_only_with_ai_on_and_before_the_choices():
    render = _between(AI_JS, "async function renderSettings()", "// Server administration → AI providers")
    mock_branch = _between(render, "if (MOCK) {", "return;\n    }")
    assert "setupIntro" not in mock_branch
    assert render.index("if (me.enabled) parts.push(setupIntro());") < render.index("parts.push(personalPart(me));")


def test_the_handbook_page_is_in_the_link_table():
    assert LINKS["pages"]["ai"] == {"path": "app/ai/", "title": "Optional AI"}
    page = (ROOT / "handbook" / "docs" / "app" / "ai.md").read_text(encoding="utf-8")
    assert page.startswith("---\ntitle: Optional AI\n")
