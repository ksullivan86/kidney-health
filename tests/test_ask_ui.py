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
    section = ask_section().lower()  # HTML tag and attribute names are case-insensitive
    assert "<script" not in section and " style=" not in section and "onclick=" not in section
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)  # the page as a whole: only script files
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
    # the page never talks to a route itself: a card's Save, import and Undo go through the shared API object, whose
    # entries are the app's normal routes (the model is never involved in a write)
    code = re.sub(r"/\*.*?\*/", "", ASK_JS, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$|\s//\s.*$", "", code, flags=re.MULTILINE)
    assert not re.search(r"\bfetch\(|(?<![\w.])request\(|['\"`]/api/", code)
    for route in ("logBatch: (entries) => request('POST', '/api/log/batch', { entries }),",
                  "importUsda: (fdcId) => request('POST', '/api/foods/usda/import', { fdc_id: fdcId }),",
                  "createMeal: (b) => request('POST', '/api/meals', b),",
                  "deleteEntry: (id) => request('DELETE', `/api/log/${id}`),",
                  "deleteMeal: (id) => request('DELETE', `/api/meals/${id}`),"):
        assert route in AI_JS, route


def test_the_keys_the_words_and_the_states():
    assert "e.key === 'Enter' && !e.shiftKey && !e.isComposing" in ASK_JS  # Enter sends, Shift+Enter is a new line
    for text in ("Thinking…", "New conversation", "From the app", "Not medical advice."):
        assert text in ASK_JS or text in ask_section(), text
    assert "Answers come from an AI model; every number is the app\\'s own. Not medical advice." in ASK_JS
    for kind in ("treat_low", "get_help_now", "withheld", "unfinished", "error", "confirm_save"):
        assert kind in ASK_JS, kind
    assert 'maxlength="2000"' in ask_section() and 'rows="2"' in ask_section()


def test_the_demo_shows_the_tab_with_a_note_and_never_a_mock_answer():
    assert "if (MOCK) { tab.hidden = false; return true; }" in ASK_JS
    assert "Ask works in the installed app, with an AI provider your admin sets up." in ASK_JS
    assert "els.composer.hidden = true;" in ASK_JS  # no input in the demo
    assert "chat_enabled: false" in MOCK_AI  # the demo is a server with the chat off (and no trusted saves)
    assert "chat" not in MOCK_AI.replace("chat_enabled: false", "")  # js/mock/ai.js still answers every /api/ai/* route 404, like a server with AI off
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


# --------------------------------------------------------------------------- #
# Saving from the chat, with a trust setting (assistant step 2, part C)
# --------------------------------------------------------------------------- #

SETTINGS_JS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
SAVING_JS = ASK_JS[ASK_JS.index("// Saving from the chat (assistant step 2, part C)"):ASK_JS.index("  // Wiring\n")]
TRUST_JS = AI_JS[AI_JS.index("// How much the person trusts the assistant to save"):AI_JS.index("// Server administration \u2192 AI providers")]


def trust_sheet() -> str:
    start = INDEX.index('<dialog id="sheet-ai-trust"')
    return INDEX[start:INDEX.index("</dialog>", start)]


def test_the_warning_sheet_is_a_dialog_with_no_inline_script_or_style():
    sheet = trust_sheet()
    assert 'class="sheet"' in sheet and 'aria-labelledby="sheet-ai-trust-title"' in sheet and 'id="sheet-ai-trust-title"' in sheet
    assert '<div class="sheet-body"></div>' in sheet and '<div class="sheet-foot"></div>' in sheet  # filled by ai.js with textContent
    lowered = sheet.lower()  # tag and attribute names are case-insensitive
    assert "<script" not in lowered and " style=" not in lowered and "onclick=" not in lowered and "javascript:" not in lowered
    assert not re.search(r"\son\w+\s*=", sheet, re.IGNORECASE)
    assert 'src="' not in lowered and "http://" not in lowered and "https://" not in lowered  # loads nothing


def test_the_warning_says_what_it_must_and_the_safe_button_has_the_focus():
    for words in ("The assistant will save food and recipes without asking you first.",
                  "It can pick the wrong food or the wrong amount.",
                  "Every number still comes from the app. The low and emergency rules and the dose checks always stay on.",
                  "You can undo each save, from the chat or from Today.",
                  "Photo and label readings are always shown to you to check first."):
        assert words in TRUST_JS, words
    assert "'I understand, trust it'" in TRUST_JS and "'Keep asking me'" in TRUST_JS
    assert "return awaitChoice(trustEl, ok, trigger, keep);" in TRUST_JS  # the focus starts on "Keep asking me"
    # only the OK button says yes; closing the sheet any other way is false and changes nothing
    assert "okButton.addEventListener('click', () => { finish(true); dlg.close(); });" in AI_JS
    assert "dlg.addEventListener('close', () => finish(false), { once: true });" in AI_JS
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in TRUST_JS, banned


def test_the_choice_in_settings_has_three_options_the_default_marked_and_a_warning_before_trust():
    for label in ("Ask me before every save (recommended)", "Trust it for this conversation", "Trust it always"):
        assert label in TRUST_JS, label
    assert "How much do you trust the assistant?" in TRUST_JS
    assert "disabled: value !== 'ask' && !allowed" in TRUST_JS  # the admin switch off: only "ask" can be chosen
    # conversation and always open the warning first and change nothing unless it is confirmed
    assert "if (value !== 'ask' && !(await confirmTrust(value, radio))) { show(); return; }" in TRUST_JS
    assert TRUST_JS.index("confirmTrust(value, radio)") < TRUST_JS.index("await save({ trust: value }")
    assert "Your admin turned trusted saves off, so Ask asks you before every save for now." in TRUST_JS
    assert "if (me.chat_enabled) wrap.append(trustPart(me, save));" in AI_JS  # only while the Ask chat is on
    assert "KH.ai = { status, forget, cardEl, confirmTrust," in AI_JS
    assert "'ai.allow_trusted_saves'" in SETTINGS_JS  # shown with the other AI switches in Server administration


def test_ask_sends_trust_only_for_a_conversation_the_person_trusted_and_only_for_twelve_hours():
    assert "const CONVERSATION_MS = 12 * 3600 * 1000;" in SAVING_JS
    fields = SAVING_JS[SAVING_JS.index("function saveFields()"):SAVING_JS.index("// The server says which trust")]
    assert "fields.trust = 'conversation'" in fields and "'always'" not in fields  # always is never sent: the stored choice alone
    assert "conversationTrusted() && trustInfo.allowed && trustInfo.setting === 'conversation'" in fields
    assert "if (Date.now() - grantedAt >= CONVERSATION_MS) { grantedAt = null; return false; }" in SAVING_JS
    assert "localStorage" not in SAVING_JS and "sessionStorage" not in SAVING_JS  # the grant lives in the page only
    new_conversation = ASK_JS[ASK_JS.index("function newConversation()"):ASK_JS.index("// Saving from the chat")]
    assert "resetSaving();" in new_conversation  # New conversation ends the trust
    assert "function body() { return { messages: thread.slice(-MAX_SENT).map((m) => ({ role: m.role, text: m.text })), ...saveFields() }; }" in ASK_JS
    assert "answer.trust === 'ask'" in SAVING_JS  # a server that used less trust ends the page's belief
    # a change of the choice in Settings ends a trusted conversation too
    assert "KH.views.ask.endTrust()" in TRUST_JS and "endTrust: resetSaving" in ASK_JS


def test_the_cards_have_the_buttons_and_post_through_the_shared_routes_only():
    for label in ("'Save as eaten'", "'Save as planned'", "'Cancel'", "'Save recipe'", "'Undo'", "Add to your log?"):
        assert label in SAVING_JS, label
    assert "card.status === 'planned' ? 'planned' : 'eaten'" in SAVING_JS  # what the model asked is preselected
    for call in ("api.importUsda(fdcId)", "api.logBatch(", "api.createMeal(", "api.deleteMeal(", "api.deleteEntry("):
        assert call in SAVING_JS, call
    assert "card.payload.entries.map((e) => ({ ...withFood(e), status }))" in SAVING_JS  # the card's body, with the chosen status
    assert "Nothing has been saved" in ASK_JS or "not saved" in SAVING_JS.lower()
    # a save and an Undo change the log: the other screens reload their day (the same call the other AI saves make)
    assert SAVING_JS.count("dayChanged();") >= 3 and "function dayChanged() { KH.ai.refreshDayCaches(); }" in SAVING_JS
    assert "KH.ai = { status, forget, cardEl, confirmTrust, refreshDayCaches," in AI_JS
    # an id that is not the person's is a 404 from the route: already gone counts as undone, anything else is shown
    assert "err.status === 404" in SAVING_JS
    # everything the server sends goes in as text
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "setAttribute('on"):
        assert banned not in SAVING_JS, banned
    assert "style:" not in SAVING_JS and "setAttribute('style'" not in SAVING_JS


def test_the_trust_line_and_the_link_to_settings_are_in_the_ask_view():
    section = ask_section()
    assert 'id="ask-trust"' in section and 'id="ask-trust-line"' in section and 'id="ask-trust-actions"' in section
    assert "'Change this in Settings'" in SAVING_JS and "target.focus({ preventScroll: true })" in SAVING_JS and "$('#set-ai-trust')" in SAVING_JS
    assert "id: 'set-ai-trust'" in TRUST_JS
    for css in (".ask-trust {", ".ask-save {", ".ask-save-items {", ".ask-save-actions {", ".trust-points {"):
        assert css in ASK_CSS, css
    assert "if (MOCK) { box.hidden = true; return; }" in SAVING_JS  # the demo has no assistant, so no trust line
