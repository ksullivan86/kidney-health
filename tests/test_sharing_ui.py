"""The screens of read-only sharing (design note 19 §7): static checks of the page and the views, and the pure helpers of
js/views/sharing.js run in Node.

Two people sharing and stopping in a real browser is walked by ``tools/e2e/sharing.py``.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VIEW = STATIC / "js" / "views" / "sharing.js"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CODE = VIEW.read_text(encoding="utf-8")
VISIT = (STATIC / "js" / "views" / "visit.js").read_text(encoding="utf-8")


def test_the_view_is_loaded_after_passkeys_and_kept_offline():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/sharing.js") == scripts.index("js/views/passkeys.js") + 1
    assert scripts.index("js/views/visit.js") < scripts.index("js/views/sharing.js") < scripts.index("js/main.js")
    assert "'/js/views/sharing.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_view_draws_with_elements_and_calls_only_its_routes():
    assert "innerHTML" not in CODE and "insertAdjacentHTML" not in CODE and "import(" not in CODE
    assert not re.search(r"localStorage|sessionStorage|indexedDB|document\.cookie", CODE), "nothing about a link is kept in the browser"
    routes = set(re.findall(r"'(/api/[^'`$]+)", CODE))
    assert routes == {"/api/me/shares", "/api/shared", "/api/shared/info", "/api/shared/accept"}
    templated = set(re.findall(r"`(/api/[^`]+)`", CODE))
    assert templated == {"/api/me/shares/${id}", "/api/shared/${id}", "/api/shared/${encodeURIComponent(id)}"}
    methods = re.findall(r"request\('(\w+)'", CODE)
    assert set(methods) == {"GET", "POST", "DELETE"}
    reads = CODE[CODE.index("function reads(id)"):CODE.index("// Pure helpers")]
    assert set(re.findall(r"request\('(\w+)'", reads)) == {"GET"}, "the shared reads are reads only"


def test_settings_shows_the_block_outside_no_sign_in_mode_and_the_admin_can_end_sharing():
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "if (authMode() !== 'none' && KH.sharing) body.append(KH.sharing.block());" in settings
    assert "endUserShares: (id) => request('DELETE', `/api/admin/users/${id}/shares`)" in settings
    assert "if (u.shares)" in settings and "'End sharing'" in settings
    assert "['Sharing', ['sharing.enabled']]," in settings


def test_the_form_offers_how_long_a_share_lasts():
    assert "const DAY_CHOICES = [['', 'Until I stop it'], ['7', '1 week'], ['30', '30 days'], ['90', '90 days'], ['365', '1 year']];" in CODE
    assert "A.make(areas, Number(lasts.value) || null)" in CODE
    assert "make: (areas, days) => request('POST', '/api/me/shares', { areas, days: days || null })," in CODE
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "time: 'on the end date you chose'" in settings


def test_the_link_is_taken_into_memory_and_asked_about_after_sign_in():
    assert "takeLink(); // the link the page was opened with" in CODE
    assert "history.replaceState(null, '', location.pathname + location.search)" in CODE
    main = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
    assert "KH.sharing.openPending()" in main
    sheet = INDEX[INDEX.index('<dialog id="sheet-share"'):INDEX.index("</dialog>", INDEX.index('<dialog id="sheet-share"'))]
    assert 'id="share-accept">Accept</button>' in sheet and "data-close>No, thanks</button>" in sheet
    # nothing is accepted until the button is pressed: openPending only asks the server who the link is from
    pending = CODE[CODE.index("async function openPending()"):CODE.index("function setupSheet()")]
    assert "A.info(code)" in pending and "A.accept(" not in pending


def test_the_visit_page_shows_a_share_read_only_with_the_other_persons_name():
    page = INDEX[INDEX.index('<section id="view-visit"'):INDEX.index("<!-- ===================== SETTINGS")]
    assert '<p id="visit-shared" class="visit-shared" role="note" hidden></p>' in page
    assert '<section class="visit-section" id="visit-day" aria-labelledby="visit-day-h" hidden>' in page
    assert "function openShared(person)" in VISIT and "S.source = S.pendingSource;" in VISIT
    assert "You can look, but not change anything." in VISIT
    assert "has not shared ${what} with you." in VISIT
    for word in ("api.add", "api.update", "api.delete", "request('POST'", "request('PUT'", "request('DELETE'"):
        assert word not in VISIT, word


def test_trends_show_a_share_read_only():
    trends = (STATIC / "js" / "views" / "trends.js").read_text(encoding="utf-8")
    body = (STATIC / "js" / "views" / "body_trends.js").read_text(encoding="utf-8")
    symptoms = (STATIC / "js" / "views" / "symptoms.js").read_text(encoding="utf-8")
    assert '<p id="trends-shared" class="visit-shared" role="note" hidden></p>' in INDEX
    assert "T.source = T.pending; // set by openShared just before; the Trends tab shows the person's own data" in trends
    assert "const reads = src ? src.reads : api;" in trends and "reads.range(start, end)" in trends
    assert "$('#export-csv').hidden = shared;" in trends and "if (KH.guidance && !src)" in trends
    assert "KH.symptoms.trends(start, end, src)" in trends and "KH.bodyTrends.show(start, end, src)" in trends
    assert "await (source ? source.reads : api).symptoms(start, end)" in symptoms
    assert "const reads = source ? source.reads : api;" in body and "clear($('#body-trends-actions')).hidden = true;" in body
    assert "button('Trends', 'secondary', () => openTrends(p)" in CODE and "range: (start, end) => request('GET', `${base}/log/range?" in CODE
    for code in (trends, body, symptoms):
        shared_part = code[code.find("source"):]
        for word in ("api.add", "api.update", "api.delete"):
            assert word not in shared_part or "source ? source.reads : api" in code, word


def test_the_demo_answers_as_a_server_with_sharing_off():
    mock = (STATIC / "js" / "mock" / "auth.js").read_text(encoding="utf-8")
    assert "route('GET', '/api/me/shares', function () { this._currentUser(); return { enabled: false," in mock
    assert "shares: 0 }" in mock and "route('DELETE', userIdRoute('/shares')" in mock


def test_the_activity_list_names_every_share_event_in_words():
    from app.audit import ACTIONS, USER_VISIBLE_ACTIONS

    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    labels = settings[settings.index("const ACTION_LABEL = {"):settings.index("};", settings.index("const ACTION_LABEL = {"))]
    actions = sorted(a for a in ACTIONS if a.startswith("share."))
    assert actions == ["share.accepted", "share.code_cancelled", "share.code_created", "share.ended", "share.viewed"]
    for action in actions:
        assert action in USER_VISIBLE_ACTIONS and f"'{action}':" in labels, action


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_pure_helpers():
    rules = (STATIC / "js" / "engine" / "rules.js").read_text(encoding="utf-8")
    script = f"""
      const listeners = {{}};
      const calls = [];
      const window = {{ KH: {{ h() {{}}, $() {{ return null; }}, clear() {{}}, request: (m, p) => {{ calls.push([m, p]); return Promise.resolve({{}}); }}, toast() {{}}, toastError() {{}}, confirm: {{}},
        sheets: {{ setup() {{}}, open() {{}}, onSubmit() {{}} }}, state: {{}}, flags: {{ MOCK: false }}, views: {{}},
        util: {{ qs: (p) => new URLSearchParams(Object.entries(p).filter(([, v]) => v != null)).toString() }} }},
        addEventListener(t, f) {{ listeners[t] = f; }} }};
      globalThis.window = window;
      globalThis.location = {{ hash: '', pathname: '/', search: '' }};
      globalThis.history = {{ replaceState() {{}} }};
      require('vm').runInThisContext({json.dumps(rules)});
      require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(VIEW))}, 'utf8'));
      const S = window.KH.sharing;
      const rd = S.reads(7);
      rd.summary('2026-10-01', '2026-10-14'); rd.range('2026-10-01', '2026-10-14'); rd.labs({{ limit: 1000 }}); rd.day('2026-10-29'); rd.profile(); rd.bloodPressures('a', 'b');
      console.log(JSON.stringify({{
        one: S.areasText(['labs']), two: S.areasText(['symptoms', 'food']), all: S.areasText(['body', 'labs', 'food', 'symptoms']),
        today: S.lastLooked('2026-10-29T08:00:00Z', '2026-10-29'), never: S.lastLooked(null, '2026-10-29'),
        before: S.lastLooked('2026-10-27T08:00:00Z', '2026-10-29'),
        who: [S.whoText({{ name: 'Ana', username: 'ana' }}), S.whoText({{ name: 'ana', username: 'ana' }})],
        question: S.questionText({{ name: 'Ana', username: 'ana2', areas: ['food', 'labs'] }}),
        line: S.sharingLine({{ areas: ['food'], since: '2026-10-29T08:00:00Z', last_viewed_at: null, active: false }}, '2026-10-29'),
        dated: S.sharingLine({{ areas: ['labs'], since: '2026-10-29T08:00:00Z', until: '2026-11-28T08:00:00Z', last_viewed_at: null }}, '2026-10-29'),
        person: S.personLine({{ areas: ['food'], since: '2026-10-29T08:00:00Z', until: '2026-11-28T08:00:00Z' }}),
        lasts: [S.lastsText(null), S.lastsText(1), S.lastsText(30)],
        ending: S.questionText({{ name: 'Ana', username: 'ana', areas: ['food'], days: 30 }}),
        entries: [S.entryLine({{ food_name: 'Banana', servings: 1, grams: null, status: 'eaten' }}),
                  S.entryLine({{ food_name: 'Juice', servings: 0.5, grams: null, status: 'planned', purpose: 'hypo' }}),
                  S.entryLine({{ food_name: 'Rice', servings: 1, grams: 150.4, status: 'eaten' }})],
        calls,
      }}));
    """
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout)
    assert got["one"] == "lab results" and got["two"] == "food log and symptoms"
    assert got["all"] == "food log, lab results, weight and blood pressure and symptoms"
    assert got["today"] == "looked today" and got["never"] == "has not looked yet" and got["before"].startswith("last looked Oct 27")
    assert got["who"] == ["Ana (ana)", "ana"]
    assert got["question"] == ("Ana (ana2) wants to share their food log and lab results with you. You can look, but not change "
                               "anything. Ana (ana2) can stop this at any time, and so can you.")
    assert got["line"].startswith("food log · since Oct 29") and got["line"].endswith("has not looked yet · their account is turned off")
    assert "until" not in got["line"] and " · until Nov 28, 2026 · has not looked yet" in got["dated"]
    assert got["person"].endswith(" · until Nov 28, 2026")
    assert got["lasts"] == ["until one of you stops it", "for 1 day", "for 30 days"]
    assert got["ending"].endswith("and so can you. It ends by itself after 30 days.")
    assert got["entries"] == ["Banana, 1 serving", "Juice, 0.5 servings (planned, to treat a low)", "Rice, 150 g"]
    assert got["calls"] == [["GET", "/api/shared/7/log/summary?start=2026-10-01&end=2026-10-14"],
                            ["GET", "/api/shared/7/log/range?start=2026-10-01&end=2026-10-14"], ["GET", "/api/shared/7/labs?limit=1000"],
                            ["GET", "/api/shared/7/log?date=2026-10-29"], ["GET", "/api/shared/7/profile"],
                            ["GET", "/api/shared/7/body/blood-pressure?start=a&end=b"]]
