"""The screens of the Care team (design note 25 §1, §8): Settings → Care team, the Profile link, "Added by" on Today, and
"Planning for" on the Plan tab (``js/views/careplan.js``), with static checks of the page and the pure helpers run in Node, and the
demo's sample Care team (``js/mock/care.js``) run in Node. A Care helper planning a day in a real browser is walked by
``tools/e2e/sharing.py``.
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
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
CARE = (STATIC / "js" / "views" / "careplan.js").read_text(encoding="utf-8")
SHARING = (STATIC / "js" / "views" / "sharing.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
OFFLINE = (STATIC / "js" / "offline.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "care.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_the_scripts_are_loaded_in_order_and_kept_offline():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/plandays.js") < scripts.index("js/views/careplan.js") < scripts.index("js/main.js")
    assert scripts.index("js/views/plan.js") < scripts.index("js/views/careplan.js")
    assert scripts.index("js/mock/auth.js") < scripts.index("js/mock/care.js") < scripts.index("js/mock/seed.js")
    assert "'/js/views/careplan.js'," in SW and "'/js/mock/care.js'," in SW


def test_settings_has_its_own_care_team_section_near_the_top():
    account = INDEX.index('id="set-account"')
    care = INDEX.index('<section class="card settings-section" id="set-care" data-title="Care team" aria-labelledby="set-care-h" hidden>')
    assert account < care < INDEX.index('id="set-prefs"')
    assert "KH.sharing.block()" not in SETTINGS[SETTINGS.index("function renderAccount()"):SETTINGS.index("function renderAccount()") + 4000]
    assert "sec.hidden = authMode() === 'none' || !KH.sharing;" in SETTINGS
    assert "['Care team', ['sharing.enabled']]," in SETTINGS


def test_the_screens_say_care_team_not_sharing():
    visible = re.findall(r"'([^'\n]*)'|`([^`\n]*)`", SHARING)
    words = [a or b for a, b in visible]
    assert not [w for w in words if re.search(r"\bSharing\b|\bStop sharing\b|\bShared with you\b", w)]
    assert "'Your Care team'" in SHARING and "'Care teams you are on'" in SHARING and "'Invites for you'" in SHARING
    assert "'Waiting for an answer'" in SHARING and "'Send invite'" in SHARING and "'Make a link instead'" in SHARING


def test_switched_off_a_person_and_an_admin_are_told_what_to_do():
    assert "const OFF = 'The Care team is off on this server. Your admin can turn it on.';" in SHARING
    assert "Server administration → Server settings → Care team, '\n    + 'or with SHARING_ENABLED=true.'" in SHARING
    assert "KH.router.show('admin')" in SHARING


def test_profile_links_to_the_care_team():
    assert '<button class="btn secondary" type="button" id="profile-open-care">Open Care team</button>' in INDEX
    profile = (STATIC / "js" / "views" / "profile.js").read_text(encoding="utf-8")
    assert "KH.views.settings.openSection('set-care')" in profile
    assert "function openSection(id)" in SETTINGS


def test_today_says_who_added_an_entry():
    today = (STATIC / "js" / "views" / "today.js").read_text(encoding="utf-8")
    assert "e.added_by ? h('span', { class: 'entry-added-by' }, ` · Added by ${e.added_by}`) : null" in today
    assert "e.added_by ? `added by ${e.added_by}` : null" in SHARING  # the shared day view


def test_planning_for_someone_calls_only_their_shared_routes():
    assert "innerHTML" not in CARE and "insertAdjacentHTML" not in CARE
    assert set(re.findall(r"'(/api/[^'`$]+)", CARE)) == set()
    templated = set(re.findall(r"`(/api/[^`]+)`", CARE))
    assert templated == {"/api/shared/${encodeURIComponent(id)}"}
    for word in ("KH.api", "api.add", "state.plan", "state.date", "state.dayLoadedFor", "sessionStorage", "indexedDB"):
        assert word not in CARE[CARE.index("(() => {"):], word
    # the person's ticks never share a key with the helper's own list
    assert "return `${SHOP_KEY}:care:${shareId}:${start}`;" in CARE


def test_the_outbox_and_the_offline_copies_never_hold_someone_elses_plan():
    """js/offline.js queues and saves only the person's own routes, by exact path: a write to /api/shared/… is never queued
    (so never replayed into the helper's own log) and a read of it is never saved as the helper's day."""
    assert "/api/shared" not in OFFLINE
    assert "const KINDS = { 'POST /api/log': 'entry', 'POST /api/log/quick': 'quick', 'POST /api/log/mark-eaten': 'mark' };" in OFFLINE
    assert "if (p === '/api/log') {" in OFFLINE and "if (p === '/api/log/range' || p === '/api/log/summary') return `${p}${u.search}`;" in OFFLINE


def test_the_plan_tab_hands_over_to_the_care_plan():
    plan = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
    assert "router.register('plan', () => { if (KH.carePlan && KH.carePlan.onShow()) return; loadPlan(); });" in plan
    view = INDEX[INDEX.index('<section id="view-plan"'):INDEX.index('<div class="date-nav week-nav">', INDEX.index('<section id="view-plan"'))]
    assert '<div id="care-for" class="care-for" hidden>' in view and '<div id="care-plan" class="care-plan" hidden></div>' in view
    assert "'Back to my own plan'" in CARE and "use_saved_meals: false" in CARE


@node
def test_the_pure_helpers():
    rules = (STATIC / "js" / "engine" / "rules.js").read_text(encoding="utf-8")
    script = f"""
      const stub = () => ({{ addEventListener() {{}}, children: [], append() {{}}, dataset: {{}}, hidden: true }});
      const calls = [];
      const window = {{ KH: {{ h() {{ return stub(); }}, $() {{ return stub(); }}, clear(x) {{ return x; }},
        request: (m, p, b, o) => {{ calls.push([m, p, b === undefined ? null : b, o || null]); return Promise.resolve({{}}); }},
        toast() {{}}, toastError() {{}}, confirm: {{}}, sheets: {{ setup() {{}}, open() {{}}, onSubmit() {{}} }}, state: {{ me: {{ role: 'user' }} }},
        flags: {{ MOCK: false }}, views: {{}}, keys: {{ SHOP_KEY: 'kdl-shop' }},
        util: {{ qs: (p) => new URLSearchParams(Object.entries(p).filter(([, v]) => v != null)).toString(), todayStr: () => '2026-10-30',
          addDays: (d, n) => new Date(Date.parse(d + 'T12:00:00Z') + n * 864e5).toISOString().slice(0, 10), fmtDateLong: (d) => d,
          fmtMonthDay: (d) => d, fmtRange: (a, b) => a + ' – ' + b, weekStartOf: (d) => d, parseDate: (d) => new Date(d + 'T12:00:00'),
          debounce: (f) => f }} }}, addEventListener() {{}} }};
      globalThis.window = window;
      globalThis.location = {{ hash: '', pathname: '/', search: '' }};
      globalThis.history = {{ replaceState() {{}} }};
      require('vm').runInThisContext({json.dumps(rules)});
      require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(STATIC / "js" / "views" / "sharing.js"))}, 'utf8'));
      require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(STATIC / "js" / "views" / "careplan.js"))}, 'utf8'));
      const S = window.KH.sharing, C = window.KH.carePlan;
      const ana = {{ id: 3, name: 'Ana', username: 'ana' }};
      const rt = C.routes(3);
      rt.day('2026-10-31'); rt.foods('rice'); rt.add({{ date: '2026-10-31' }}); rt.batch([1]); rt.change(9, {{ servings: 2 }}, 'abcdef0123456789');
      rt.remove(9); rt.clearPlanned('2026-10-31', '2026-11-01'); rt.planDays('2026-10-31', 3); rt.shopping('2026-10-27', '2026-11-02');
      console.log(JSON.stringify({{
        banner: C.bannerText(ana), key: C.shopKey(3, '2026-10-27'),
        offline: C.failText({{ status: 0 }}, ana), gone: C.failText({{ status: 404, detail: 'Not shared with you.' }}, ana),
        other: C.failText({{ status: 400, detail: 'servings: too big' }}, ana),
        levels: [C.dayLevel({{ counts: {{ planned: 0, eaten: 0 }} }}), C.dayLevel({{ counts: {{ planned: 1 }}, projected_status: {{ potassium_mg: {{ level: 'ok' }}, sodium_mg: {{ level: 'caution' }} }} }}),
                 C.dayLevel({{ counts: {{ eaten: 1 }}, projected_status: {{ phosphorus_mg: {{ level: 'over' }} }} }})],
        text: C.shoppingText(ana, {{ start: '2026-10-27', end: '2026-11-02', items: [{{ food_id: 1, food_name: 'Rice', servings: 3, serving_desc: '1 cup' }}, {{ food_id: 2, food_name: 'Apple', servings: 1, serving_desc: null }}] }}, new Set([2])),
        roles: [S.roleText('viewer'), S.roleText('care_helper'), S.roleText(undefined)],
        changes: [S.changesText({{ day: '2026-10-30', added: 3, changed: 0, removed: 1 }}, '2026-10-30'), S.changesText({{ day: '2026-10-30', added: 0, changed: 0, removed: 0 }}, '2026-10-30')],
        line: S.sharingLine({{ role: 'care_helper', areas: ['food'], since: '2026-10-29T08:00:00Z', last_viewed_at: null, helper_changes: {{ day: '2026-10-30', added: 2 }} }}, '2026-10-30'),
        person: S.personLine({{ role: 'viewer', areas: ['labs'], since: '2026-10-29T08:00:00Z' }}),
        helper: S.questionText({{ name: 'Ana', username: 'ana', areas: ['food'], role: 'care_helper' }}),
        viewer: S.questionText({{ name: 'Ana', username: 'ana', areas: ['food'], role: 'viewer' }}),
        calls,
      }}));
    """
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout)
    assert got["banner"] == "You are planning for Ana. Changes go to Ana's plan, not yours."
    assert got["key"] == "kdl-shop:care:3:2026-10-27"
    assert got["offline"] == "Not saved: planning for Ana needs a connection to your server."
    assert got["gone"] == "You can no longer plan for Ana." and got["other"] == "servings: too big"
    assert got["levels"] == [None, "caution", "over"]
    assert got["text"] == "Shopping list for Ana, 2026-10-27 – 2026-11-02\n\n- Rice: 3 servings of 1 cup"
    assert got["roles"] == ["Viewer", "Care helper", "Viewer"]
    assert got["changes"] == ["changed your plan today: 3 added, 1 removed", None]
    assert got["line"].startswith("Care helper · food log · since Oct 29") and got["line"].endswith("changed your plan today: 2 added")
    assert got["person"].startswith("Viewer · lab results")
    assert "as a Care helper. You can see this and plan their meals and use their shopping list, but not change what they ate" in got["helper"]
    assert "You can look, but not change anything." in got["viewer"]
    paths = [c[:2] for c in got["calls"]]
    assert paths == [["GET", "/api/shared/3/log?date=2026-10-31"], ["GET", "/api/shared/3/foods?q=rice&limit=8"], ["POST", "/api/shared/3/log"],
                     ["POST", "/api/shared/3/log/batch"], ["PUT", "/api/shared/3/log/9"], ["DELETE", "/api/shared/3/log/9"],
                     ["POST", "/api/shared/3/log/clear-planned"], ["POST", "/api/shared/3/guidance/plan-days"],
                     ["GET", "/api/shared/3/plan/shopping?start=2026-10-27&end=2026-11-02"]]
    assert got["calls"][4][3] == {"ifMatch": "abcdef0123456789"}
    assert got["calls"][7][2] == {"start": "2026-10-31", "days": 3, "use_saved_meals": False}


@node
def test_the_demo_shows_a_sample_care_team_and_a_helper_plans_anas_days():
    got = json.loads(subprocess.run(["node", str(ROOT / "tests" / "js" / "care_demo.mjs")], capture_output=True, text=True, check=True,
                                    timeout=120).stdout)
    assert got["mine"]["enabled"] is True and [s["role"] for s in got["mine"]["sharing"]] == ["care_helper"]
    assert [i["username"] for i in got["mine"]["invites"]] == ["riley"]
    assert [(p["name"], p["role"]) for p in got["shared"]["people"]] == [("Ana", "care_helper")]
    assert [i["name"] for i in got["shared"]["invites"]] == ["Lee"]
    assert got["invite"]["username"] == "robin" and got["invite"]["areas"] == ["food", "labs"]
    assert got["own"]["status"] == 400 and got["role"]["role"] == "viewer"
    assert got["accept"]["name"] == "Lee" and got["accept"]["role"] == "viewer"
    assert got["anaPlanned"] and all(status == "planned" for _, status in got["anaPlanned"])
    assert got["added"]["status"] == 200 and got["added"]["status_field"] == "planned" and got["added"]["added_by"]
    assert got["eaten"] == 400 and got["changeEaten"] == 404 and got["statusChange"] == 400 and got["change"] == 1
    assert "Apple, raw, with skin" in got["shopping"]
    assert got["viewer"]["status"] == 404 and got["labs"] == 404 and got["remove"] == 200
    assert got["ownAfter"] == got["ownBefore"], "the demo person's own day never changes"
    assert got["plan"] == {"status": 200, "kind": "ok"} and got["link"]["status"] == 404
    assert "use_saved_meals: false" in MOCK
