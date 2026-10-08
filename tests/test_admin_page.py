"""v0.3.1 item 3 (docs/dev/plans/v0.3.1.md): Server administration on its own page.

Members never see an admin entry: the header shield (``#admin-open``) and Settings → Admin (``#set-admin-link``)
are shown to admins only, the admin view itself draws a short note and makes no request for a member, and every
``/api/admin`` route still answers 403 to a member (the server is the real guard; the page only hides).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SETTINGS_JS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
AUTH_JS = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
AI_JS = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
CORE_JS = (STATIC / "js" / "core.js").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_the_admin_view_is_its_own_page_with_people_server_and_ai():
    view = _between(INDEX, '<section id="view-admin"', "</main>")
    assert 'class="view settings-view" aria-labelledby="admin-title" hidden' in view
    assert 'id="admin-title"' in view and ">Server administration<" in view
    for part in ('id="set-admin-body"', 'id="set-admin-ai-body"', 'id="admin-nav"'):
        assert part in view, part
    assert "'admin'" in CORE_JS.split("const VIEWS = ", 1)[1].split(";", 1)[0]


def test_only_admins_see_the_entries():
    # the header shield waits for sign-in and for the admin role
    assert ('<button id="admin-open" class="icon-btn" type="button" aria-label="Server administration" '
            'title="Server administration" data-signed-in data-admin-only hidden>') in INDEX
    chrome = _between(AUTH_JS, "function setSignedInChrome(on)", "\n  }\n")
    assert "el.hasAttribute('data-admin-only') && !admin" in chrome and "state.me.role === 'admin'" in chrome
    # Settings keeps a link card, hidden unless the person is an admin
    assert 'id="set-admin-link" data-title="Admin" aria-labelledby="set-admin-link-h" hidden' in INDEX
    sync = _between(SETTINGS_JS, "function syncAdminEntry()", "\n  }\n")
    assert "shield.hidden = !isAdmin();" in sync and "$('#set-admin-link').hidden = !isAdmin();" in sync


def test_a_member_on_the_admin_view_gets_a_note_and_no_request():
    frame = _between(SETTINGS_JS, "function renderAdminFrame()", "// ---- People: accounts and invites")
    refusal = frame.index("if (!isAdmin()) {")
    first_request = min(frame.index(call) for call in ("loadServerSettings()", "loadPeople()", "loadSharedKeys()", "loadUsage()",
                                                        "loadAudit()", "loadServerAbout()"))
    assert refusal < first_request
    assert "Server administration is for admins." in frame[refusal:first_request] and "return;" in frame[refusal:first_request]
    # Settings no longer draws the admin blocks
    load = _between(SETTINGS_JS, "  async function load() {", "\n  }\n")
    assert "renderAdminFrame()" not in load
    # the AI providers moved too: Settings → AI ideas only points to them
    settings_render = _between(AI_JS, "async function renderSettings()", "// Server administration → AI providers")
    assert "adminPart" not in settings_render
    admin_render = _between(AI_JS, "async function renderAdmin()", "\n  }\n")
    assert "if (!isAdmin()) { clear(body); return; }" in admin_render
    assert "whenShown('view-admin', () => { renderAdmin().catch(toastError); });" in AI_JS


def test_admin_routes_still_refuse_members(two_clients):
    admin, member = two_clients
    for path in ("/api/admin/users", "/api/admin/invites", "/api/admin/settings", "/api/admin/keys", "/api/admin/usage",
                 "/api/admin/audit", "/api/admin/about"):
        assert admin.get(path).status_code == 200, path
        assert member.get(path).status_code == 403, path
    assert member.get("/api/me").json()["role"] == "user"
