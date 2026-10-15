"""The Ask screen's frontend (``app/static/js/views/ask.js``, ``css/ask.css``, the tab and view in ``index.html``)
against the contract of ``POST /api/ai/chat``: the pieces exist and load in the right order, the page holds no inline
script or style (CSP), the model's text is never put into the page as HTML, the demo has no mock answers, and the
consent sheet says what the chat sends. Browser behaviour (consent sheet, answers, cards, sizes at 375 and 1280 px in
light and dark, no sideways scroll) is checked in Chromium by hand against a fake provider; these tests keep the
contract from drifting."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
ASK_JS = (STATIC / "js" / "views" / "ask.js").read_text(encoding="utf-8")
ASK_CSS = (STATIC / "css" / "ask.css").read_text(encoding="utf-8")
AI_JS = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
CORE_JS = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
MOCK_AI = (STATIC / "js" / "mock" / "ai.js").read_text(encoding="utf-8")


def ask_section() -> str:
    start = INDEX.index('<section id="view-ask"')
    return INDEX[start:INDEX.index("</section>", start)]


def test_the_tab_the_view_and_the_files_are_in_the_shell():
    # a sixth tab, hidden until js/views/ask.js sees that the chat is available; between Trends and Profile
    tab = re.search(r'<button role="tab" class="tab" id="tab-ask"[^>]*>', INDEX)
    assert tab and 'aria-controls="view-ask"' in tab.group(0) and 'data-view="ask"' in tab.group(0) and tab.group(0).endswith(" hidden>")
    assert INDEX.index('id="tab-trends"') < INDEX.index('id="tab-ask"') < INDEX.index('id="tab-profile"')
    section = ask_section()
    assert 'role="tabpanel"' in section and 'aria-labelledby="tab-ask"' in section and section.startswith('<section id="view-ask" class="view ask-view"')
    for element in ('id="ask-thread" role="log"', 'id="ask-input"', 'id="ask-send"', 'id="ask-new"', 'id="ask-intro"', 'id="ask-demo"', 'id="ask-note"'):
        assert element in section, element
    assert '<link rel="stylesheet" href="css/ask.css">' in INDEX
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/ask.js") > scripts.index("js/views/ai.js") > scripts.index("js/core.js")
    assert scripts.index("js/views/ask.js") < scripts.index("js/main.js")
    assert "const TAB_VIEWS = ['today', 'add', 'plan', 'trends', 'ask', 'profile'];" in CORE_JS
    assert "KH.views.ask.refreshTab()" in MAIN_JS  # the tab follows the server's answer after sign-in


def test_no_inline_script_and_no_style_attribute_anywhere_in_the_ask_pieces():
    assert "<script" not in ask_section() and " style=" not in ask_section() and "onclick=" not in ask_section()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", INDEX)  # the page as a whole: only script files
    assert "setAttribute('style'" not in ASK_JS and "setAttribute(\"style\"" not in ASK_JS and "style:" not in ASK_JS
    assert "@import" not in ASK_CSS and "url(" not in ASK_CSS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", ASK_CSS), "colours come from the app's tokens (light and dark)"


def test_model_text_is_never_put_into_the_page_as_html():
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on"):
        assert banned not in ASK_JS, banned
    assert "textContent" in ASK_JS and "createTextNode" in ASK_JS
    # the answer, the notes, the figures and the labels all go through h() children (text nodes)
    assert "...textNodes(answer.text || '')" in ASK_JS and "h('p', { class: 'hint ask-note-line' }, note)" in ASK_JS
    assert "h('span', { class: 'ask-value' }, row.value)" in ASK_JS
    # only the app's own handbook paths become links, and only through KH.learn.href
    assert "KH.learn.href(match[0])" in ASK_JS and "target: '_blank', rel: 'noopener'" in ASK_JS


def test_the_conversation_stays_in_the_page_and_goes_through_the_shared_ai_flow():
    assert "KH.ai.withConsent('chat'" in ASK_JS and "KH.ai.api.chat(body())" in ASK_JS and "KH.ai.api.chat(body(), true)" in ASK_JS
    assert "chat: (b, dry) => request('POST', `/api/ai/chat${dry ? '?dry_run=true' : ''}`, b)," in AI_JS
    assert "localStorage" not in ASK_JS and "sessionStorage" not in ASK_JS and "indexedDB" not in ASK_JS
    assert "const MAX_SENT = 20;" in ASK_JS and "slice(-MAX_SENT)" in ASK_JS and "const MAX_CHARS = 2000;" in ASK_JS
    assert "KH.ai.cardEl(card, card.handbook === 'get-help-now')" in ASK_JS  # the existing alert cards
    # nothing is saved or logged from the chat
    assert "/api/log" not in ASK_JS and "/api/foods" not in ASK_JS and "/api/meals" not in ASK_JS


def test_the_keys_the_words_and_the_states():
    assert "e.key === 'Enter' && !e.shiftKey && !e.isComposing" in ASK_JS  # Enter sends, Shift+Enter is a new line
    for text in ("Thinking…", "New conversation", "From the app", "Not medical advice."):
        assert text in ASK_JS or text in ask_section(), text
    assert "Answers come from an AI model; every number is the app\\'s own. Not medical advice." in ASK_JS
    for kind in ("treat_low", "get_help_now", "withheld", "unfinished", "error"):
        assert kind in ASK_JS, kind
    assert 'maxlength="2000"' in ask_section() and 'rows="2"' in ask_section()


def test_the_demo_shows_the_tab_with_a_note_and_never_a_mock_answer():
    assert "if (MOCK) { tab.hidden = false; return true; }" in ASK_JS
    assert "Ask works in the installed app, with an AI provider your admin sets up." in ASK_JS
    assert "els.composer.hidden = true;" in ASK_JS  # no input in the demo
    assert "chat" not in MOCK_AI  # js/mock/ai.js still answers every /api/ai/* route 404, like a server with AI off
    assert re.search(r"route\('\*', /\^\\/api\\/\(\?:ai\|vision\)\\//", MOCK_AI)


def test_the_consent_sheet_says_what_the_chat_sends_and_what_it_never_does():
    purpose = re.search(r"chat: 'your messages in this conversation[^']*(?:\\'[^']*)*',", AI_JS)
    assert purpose, "PURPOSE_TEXT.chat"
    assert "your messages in this conversation" in purpose.group(0) and "targets" in purpose.group(0) and "food names" in purpose.group(0)
    never = AI_JS[AI_JS.index("const NEVER_SENT_TEXT"):AI_JS.index("const FEATURE_TEXT")]
    for phrase in ("Never sent: your name, user name, e-mail, weight, height, exact age or notes.", "several AI calls",
                   "never gives insulin doses or medicine advice", "checks every number in an answer"):
        assert phrase in never, phrase
    assert "NEVER_SENT_TEXT[consent.purpose]" in AI_JS
    assert "chat: 'Ask conversations'" in AI_JS and "chat: 'your Ask conversations'" in AI_JS  # Settings lists and withdraws it
    assert "chat: 'Ask'" in AI_JS  # the AI activity list names the feature


def test_the_layout_rules_keep_a_phone_free_of_sideways_scroll():
    for rule in (".ask-text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }", "min-width: 0;", ".ask-dock {",
                 "position: sticky; bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom, 0px));", ".ask-composer textarea:focus"):
        assert rule in ASK_CSS, rule
    assert "overflow-x" not in ASK_CSS.replace("overflow-x: hidden", "")  # no hiding of overflow as a fix
