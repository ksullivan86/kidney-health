"""The screens of Activity and recovery and the active-day calorie extra (design note 28): the Trends card, Today's lines, the
Whoop setting in Settings → Connected devices (``js/views/activity.js``), the Care team area's name, and the demo's sample Whoop
days (``js/mock/activity.js``) run in Node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import activity, sharing

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "activity.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "activity.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "activity.js").read_text(encoding="utf-8")
SHARING = (STATIC / "js" / "views" / "sharing.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
TODAY = (STATIC / "js" / "views" / "today.js").read_text(encoding="utf-8")
TRENDS = (STATIC / "js" / "views" / "trends.js").read_text(encoding="utf-8")
DEVICES = (STATIC / "js" / "views" / "devices.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_the_scripts_are_loaded_in_order_and_kept_offline() -> None:
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/engine/activity.js") < scripts.index("js/mock/core.js")
    assert scripts.index("js/mock/devices.js") < scripts.index("js/mock/activity.js") < scripts.index("js/mock/seed.js")
    assert scripts.index("js/views/body_trends.js") < scripts.index("js/views/activity.js") < scripts.index("js/main.js")
    for path in ("/js/engine/activity.js", "/js/mock/activity.js", "/js/views/activity.js"):
        assert f"'{path}'," in SW


def test_the_card_is_hidden_until_there_is_data_and_is_accessible() -> None:
    card = '<section class="card activity-card" id="activity-trends" aria-labelledby="activity-trends-h" hidden>'
    assert INDEX.index('id="body-trends"') < INDEX.index(card) < INDEX.index('id="charts"')
    assert '<h3 id="activity-trends-h" class="card-title">Activity and recovery</h3>' in INDEX
    assert "if (!days.length && !workouts.length) { card.hidden = true; clear(body); return; }" in VIEW
    assert "role: 'img'" in VIEW and "The table under the chart lists every day." in VIEW
    assert "h('th', { scope: 'row' }" in VIEW and "role: 'region'" in VIEW
    assert "KH.activityViews.show(start, end, src)" in TRENDS
    assert "if (source && !(source.areas || []).includes('activity')) { card.hidden = true;" in VIEW


def test_today_shows_base_and_extra_as_separate_lines_and_the_one_care_team_line() -> None:
    assert "if (day.calorie_extra && KH.activityViews) statusBarsEl.append(KH.activityViews.todayBlock(day.calorie_extra));" in TODAY
    assert "`Base target: ${fmtKcal(x.base_kcal)}`, `Active-day extra (from Whoop): +${fmtKcal(x.extra_kcal)}`" in VIEW
    assert ("const CARBS_LINE = 'Extra calories on active days change your carbs; your care team can help you plan insulin for "
            "exercise.';") in VIEW
    assert "'Why this number'" in VIEW and "Tracker calories can be off by a lot, in either direction." in VIEW


def test_nothing_acts_on_hrv_or_gives_insulin_or_low_advice() -> None:
    for text in (VIEW, MOCK, ENGINE, Path(activity.__file__).read_text(encoding="utf-8")):
        lowered = text.lower()
        for word in ("units of insulin", "bolus", "basal", "reduce your insulin", "skip", "do not treat", "don't treat"):
            assert word not in lowered, word
    # HRV is read for the card only: the engine and the extra never see it.
    assert "hrv" not in ENGINE.lower().replace("hrv, recovery, sleep and strain never change anything", "")
    assert "hrv" not in Path(activity.__file__).read_text(encoding="utf-8").split("def calorie_extra")[1].split("def extra_setting")[0].lower()


def test_the_setting_lives_with_whoop_and_says_only_calories_change() -> None:
    assert "if (id === 'whoop' && c && c.status === 'active' && KH.activityViews) box.append(KH.activityViews.extraBlock());" in DEVICES
    assert "' Add active-day calories to my target'" in VIEW
    assert "Only calories change: protein, potassium, phosphorus, sodium and fluid stay the same." in VIEW
    assert "min: String(A.SHARE_MIN)" in VIEW and "A.CEILING_MAX" in VIEW


def test_no_html_and_only_these_routes() -> None:
    for text in (VIEW, MOCK, ENGINE):
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "fetch(" not in text
    assert "api.activity(" in VIEW and "api.setActivityExtra(" in VIEW and "source.reads.activity(" in VIEW


def test_the_care_team_area_has_a_name_and_the_activity_list_labels() -> None:
    assert list(sharing.AREAS)[-1] == "activity"
    assert "activity: 'activity and recovery' };" in SHARING and "'activity']" in SHARING
    assert "'activity.extra_on': 'Active-day calories turned on', 'activity.extra_off': 'Active-day calories turned off'," in SETTINGS


@node
def test_the_today_lines_in_node() -> None:
    script = f"""
      const window = {{ KH: {{ h() {{ return {{}}; }}, s() {{ return {{}}; }}, $() {{ return null; }}, clear(x) {{ return x; }},
        api: {{}}, toast() {{}}, toastError() {{}}, util: {{}} }} }};
      globalThis.window = window;
      const vm = require('vm'), fs = require('fs');
      vm.runInThisContext(fs.readFileSync({json.dumps(str(STATIC / "js" / "engine" / "activity.js"))}, 'utf8'));
      vm.runInThisContext(fs.readFileSync({json.dumps(str(STATIC / "js" / "views" / "activity.js"))}, 'utf8'));
      const V = window.KH.activityViews;
      const base = {{ base_kcal: 2000, burned_kcal: 3000, share_pct: 100, ceiling_kcal: null, history_days: 20, source: 'whoop' }};
      console.log(JSON.stringify({{
        active: V.todayLines({{ ...base, extra_kcal: 750, quiet_kcal: 2250 }}),
        capped: V.todayLines({{ ...base, extra_kcal: 400, quiet_kcal: 2250, share_pct: 50, ceiling_kcal: 400 }}),
        quiet: V.todayLines({{ ...base, burned_kcal: 1200, extra_kcal: 0, quiet_kcal: 2250 }}),
        waiting: V.todayLines({{ ...base, extra_kcal: 0, quiet_kcal: null, history_days: 9 }}) }}));
    """
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout)
    assert got["active"]["lines"] == ["Base target: 2,000 kcal", "Active-day extra (from Whoop): +750 kcal"] and got["active"]["active"]
    assert "Your usual quiet day is 2,250 kcal" in got["active"]["why"] and "counts 100% of the difference." in got["active"]["why"]
    assert "50% of the difference, at most 400 kcal a day." in got["capped"]["why"]
    assert got["quiet"]["active"] is False and "No active-day extra today so far" in got["quiet"]["lines"][0]
    assert got["waiting"]["lines"] == ["Active-day calories start once Whoop has 14 finished days in the last 28 (9 so far)."]


@node
def test_the_demo_has_sample_whoop_days_and_the_same_numbers_as_the_server() -> None:
    script = f"""
      import {{ loadDemo, newDemo }} from {json.dumps(str(ROOT / "tests" / "js" / "demo_loader.mjs"))};
      const KH = loadDemo();
      const api = newDemo(KH);
      const t = KH.util.todayStr();
      const call = (m, p, b) => {{ try {{ return {{ status: 200, body: JSON.parse(JSON.stringify(api.handle(m, p, b) ?? null)) }}; }}
        catch (e) {{ return {{ status: e.status || 500, detail: e.detail }}; }} }};
      const out = {{}};
      out.off = call('GET', `/api/log?date=${{t}}`).body;
      out.list = call('GET', '/api/activity').body;
      out.bad = call('PUT', '/api/activity/extra', {{ enabled: true, share_pct: 5 }});
      out.on = call('PUT', '/api/activity/extra', {{ enabled: true, share_pct: 100, ceiling_kcal: null }}).body;
      out.day = call('GET', `/api/log?date=${{t}}`).body;
      const st = api._activity();
      const hist = st.days.filter((d) => d.date < t && d.date >= KH.util.addDays(t, -28) && d.finished).map((d) => d.kcal);
      out.history = hist;
      out.burned = st.days.find((d) => d.date === t).kcal;
      out.export = Object.keys(call('GET', '/api/me/export.json').body).filter((k) => k.startsWith('activity_'));
      out.devices = call('GET', '/api/devices').body.providers.map((p) => p.id);
      out.remove = call('DELETE', '/api/devices/whoop?delete_readings=true').body;
      out.after = call('GET', '/api/activity').body.days.length;
      console.log(JSON.stringify(out));
    """
    path = ROOT / "tests" / "js" / "_activity_probe.mjs"
    path.write_text(script, encoding="utf-8")
    try:
        got = json.loads(subprocess.run(["node", str(path)], capture_output=True, text=True, check=True, timeout=120).stdout)
    finally:
        path.unlink()
    assert got["off"]["calorie_extra"] is None
    assert got["list"]["extra"]["enabled"] is False and len(got["list"]["days"]) == 30 and got["list"]["workouts"]
    assert got["bad"]["status"] == 400
    info = activity.calorie_extra(got["on"], got["off"]["targets"]["calories_kcal"], got["burned"], got["history"])
    assert got["day"]["calorie_extra"] == info and info["extra_kcal"] > 0
    assert got["day"]["targets"]["calories_kcal"] == activity.raised(got["off"]["targets"]["calories_kcal"], info["extra_kcal"])
    assert {k: v for k, v in got["day"]["targets"].items() if k != "calories_kcal"} == \
        {k: v for k, v in got["off"]["targets"].items() if k != "calories_kcal"}
    assert got["export"] == ["activity_days", "activity_workouts", "activity_extra"]
    assert got["devices"] == ["withings", "whoop"]
    assert got["remove"]["removed"]["days"] == 45 and got["after"] == 0
