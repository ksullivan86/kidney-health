"""The screens of test accounts (design note 26; ``js/views/feedback.js``): the Send feedback button and sheet, Server
administration → Test accounts and Feedback, and their absence from the demo. Static checks of the page; a tester and an admin
in a real browser are walked by ``tools/e2e/test_accounts.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
FEEDBACK = (STATIC / "js" / "views" / "feedback.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
AUTH = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")


def test_the_script_is_loaded_kept_offline_and_left_out_of_the_preview():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/settings.js") < scripts.index("js/views/feedback.js") < scripts.index("js/main.js")
    assert '<script src="js/views/feedback.js" data-preview="omit"></script>' in INDEX
    assert "'/js/views/feedback.js'," in SW


def test_the_button_is_for_test_accounts_only():
    button = re.search(r'<button id="feedback-open"[^>]*>', INDEX).group(0)
    assert 'aria-label="Send feedback"' in button and "data-signed-in" in button and "data-test-only" in button and " hidden" in button
    assert "el.hasAttribute('data-test-only') && !tester" in AUTH
    assert "const tester = !!(state.me && state.me.test_account);" in AUTH
    assert "if (!dlg || !(state.me && state.me.test_account)) return;" in FEEDBACK


def test_the_sheet_asks_the_four_things_and_says_what_is_sent():
    sheet = INDEX[INDEX.index('<dialog id="sheet-feedback"'):INDEX.index("</dialog>", INDEX.index('<dialog id="sheet-feedback"'))]
    for text in ("What were you trying to do?", "What happened?", "Was this screen useful?", "This looked wrong or unsafe",
                 "Only what you type here is sent, with the name of this screen, the app version and the time. No screenshot, and nothing from the log.",
                 "treating a low", "insulin or medicine dose", "What you sent"):
        assert text in sheet, text
    assert sheet.count('maxlength="2000"') == 2
    assert "<script" not in sheet and "onclick" not in sheet


def test_only_what_was_typed_is_sent():
    body = re.search(r"await A\.send\((\{[^}]*\})\)", FEEDBACK).group(1)
    assert body == "{ screen, trying, happened, useful, unsafe: $('#feedback-unsafe').checked }"
    assert "innerHTML" not in FEEDBACK and "insertAdjacentHTML" not in FEEDBACK
    assert "trying.value = `${screen}: `;" in FEEDBACK  # started with the screen's name
    assert "if (trying === `${screen}:`) trying = '';" in FEEDBACK  # only the screen's name counts as nothing typed


def test_screen_names_are_the_apps_own():
    names = dict(re.findall(r"(\w+): '([^']+)'", FEEDBACK[FEEDBACK.index("const SCREEN = {"):FEEDBACK.index("};", FEEDBACK.index("const SCREEN = {"))]))
    tabs = re.findall(r'id="tab-(\w+)"[^>]*>(?:(?!</button>).)*?<span>([^<]+)</span>', INDEX, re.S)
    for view, label in tabs:
        assert names[view] == label, (view, label)
    assert names["labs"] == "Lab results" and '<h2 id="labs-title" class="labs-title" tabindex="-1">Lab results</h2>' in INDEX
    assert names["visit"] == "Visit prep" and names["admin"] == "Server administration"


def test_server_administration_has_test_accounts_and_feedback_but_not_in_the_demo():
    assert "const testers = !none && !MOCK && KH.feedback;" in SETTINGS
    assert "subtitle('Test accounts', 'set-testers-h')" in SETTINGS and "subtitle('Feedback', 'set-feedback-h')" in SETTINGS
    assert "['Test accounts', ['test_accounts.enabled', 'test_accounts.ai']]," in SETTINGS
    assert "const shown = (k) => all[k] && !(MOCK && k.startsWith('test_accounts.'));" in SETTINGS
    for text in ("'Reset test accounts'", "'Mark done'", "'Export CSV'", "'Delete done'", "docs/test-the-full-app.md"):
        assert text in FEEDBACK, text
    assert "request('POST', '/api/admin/test-accounts/reset')" in FEEDBACK
    assert "confirm.inline(actions, reset," in FEEDBACK  # Reset asks first


def test_people_marks_test_accounts_and_never_offers_admin():
    assert "if (u.test_account) badges.push(h('span', { class: 'badge test-account' }, 'Test account'));" in SETTINGS
    assert "if (u.test_account) roleSel.disabled = true;" in SETTINGS
    assert "${me.test_account ? ' · test account' : ''}" in SETTINGS


def test_the_activity_log_names_the_test_account_rows():
    for action in ("test_accounts.created", "test_accounts.enabled", "test_accounts.disabled", "test_accounts.reset"):
        assert f"'{action}':" in SETTINGS, action
