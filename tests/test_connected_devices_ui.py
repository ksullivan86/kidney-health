"""The screens of Connected devices (design note 27): Settings → Connected devices (``js/views/devices.js``), the way back from
Withings, the "from Withings" mark on a reading, Server administration's rows, and the demo's sample connection
(``js/mock/devices.js``) run in Node.
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
VIEW = (STATIC / "js" / "views" / "devices.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "devices.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
MAIN = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_the_scripts_are_loaded_in_order_and_kept_offline() -> None:
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/mock/care.js") < scripts.index("js/mock/devices.js") < scripts.index("js/mock/seed.js")
    assert scripts.index("js/views/settings.js") < scripts.index("js/views/devices.js") < scripts.index("js/main.js")
    assert "'/js/views/devices.js'," in SW and "'/js/mock/devices.js'," in SW


def test_settings_has_its_own_section_hidden_until_the_server_answers() -> None:
    sec = '<section class="card settings-section" id="set-connected" data-title="Connected devices" aria-labelledby="set-connected-h" hidden>'
    assert INDEX.index('id="set-body"') < INDEX.index(sec) < INDEX.index('id="set-guidance"')
    # Its own id: #set-devices is Account → Signed-in devices, which comes first, so $('#set-devices') never found this section.
    assert "const sec = $('#set-connected');" in SETTINGS and "const sec = $('#set-connected');" in VIEW
    assert INDEX.count('id="set-devices"') == 0 and "id: 'set-devices'" in SETTINGS
    assert "const show = await KH.devices.render($('#set-devices-body'));" in SETTINGS
    assert "['Connected devices', ['devices.enabled', 'devices.sync_hours']]," in SETTINGS
    assert "if (err && err.status === 404) { clear(body); return false; }" in VIEW


def test_the_consent_says_what_is_fetched_and_that_nothing_is_sent() -> None:
    assert "'Before you connect'" in VIEW
    assert "This server then fetches your ${whatText(provider)} from ${provider.name} every few hours." in VIEW
    assert "Nothing about you is sent to ${provider.name}: the server only signs in and reads. It never changes a reading you typed." in VIEW
    assert "Also delete the readings that came from ${provider.name} (readings you edited stay)" in VIEW
    assert "const TEST_ACCOUNT = 'Test accounts cannot connect a device." in VIEW


def test_no_html_and_no_other_routes() -> None:
    for text in (VIEW, MOCK):
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text
    assert set(re.findall(r"`(/api/[^`]+)`", VIEW)) == {
        "/api/devices/${encodeURIComponent(p)}/start", "/api/devices/${encodeURIComponent(p)}/sync",
        "/api/devices/${encodeURIComponent(p)}${alsoReadings ? '?delete_readings=true' : ''}"}
    assert set(re.findall(r"'(/api/[^']+)'", VIEW)) == {"/api/devices"}


def test_every_way_back_has_a_sentence_and_the_server_words_match() -> None:
    from app.devices import api

    words = set(re.findall(r"^    ([a-z_]+): \{ (?:ok: true, )?text:", VIEW, re.M))
    assert words == set(api.RESULTS)
    assert "if (KH.devices) KH.devices.openPending()" in MAIN
    errors = set(re.findall(r"^    ([a-z_]+): '", VIEW[VIEW.index("const ERRORS = {"):VIEW.index("const RESULTS = {")], re.M))
    assert errors == {"auth", "rate_limited", "unreachable", "provider_error", "scope", "account_taken"}


def test_activity_and_server_administration_name_it() -> None:
    assert "'device.connected': 'Device connected'" in SETTINGS and "'device.sync_failed': 'Device sync stopped working'" in SETTINGS
    assert "...deviceRows(a.devices)," in SETTINGS and "secret ${p.secret}" in SETTINGS


@node
def test_the_result_address_is_read_once_and_replaced() -> None:
    script = f"""
      const calls = [];
      const window = {{ KH: {{ h() {{ return {{}}; }}, $() {{ return null; }}, clear(x) {{ return x; }},
        request: (m, p) => {{ calls.push([m, p]); return Promise.resolve({{}}); }}, toast() {{}}, toastError() {{}},
        state: {{ me: null }}, flags: {{ MOCK: false }}, views: {{}} }} }};
      globalThis.window = window;
      let replaced = null;
      globalThis.location = {{ hash: '#/devices/connected/withings', pathname: '/', search: '' }};
      globalThis.history = {{ replaceState(a, b, url) {{ replaced = url; location.hash = url.slice(url.indexOf("#")); }} }};
      require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(STATIC / "js" / "views" / "devices.js"))}, 'utf8'));
      const D = window.KH.devices;
      console.log(JSON.stringify({{ replaced, again: D.takeResult(),
        status: D.statusText({{ name: 'Withings', connection: {{ status: 'active', last_success_at: null, imported: {{ weights: 1, readings: 2 }} }} }}),
        reconnect: D.statusText({{ name: 'Withings', connection: {{ status: 'needs_reconnect' }} }}),
        none: D.syncText({{ added: {{ weights: 0, readings: 0 }} }}), some: D.syncText({{ added: {{ weights: 1, readings: 0 }} }}) }}));
    """
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout)
    assert got["replaced"] == "/#settings" and got["again"] is False
    assert got["status"] == "Connected. Not synced yet. 1 weight and 2 blood pressure readings came from Withings."
    assert got["reconnect"] == "Withings needs you to connect again."
    assert got["none"] == "Nothing new from Withings." and got["some"] == "Added 1 weight and 0 blood pressure readings."


@node
def test_the_demo_shows_a_sample_connection_and_never_calls_out() -> None:
    got = json.loads(subprocess.run(["node", str(ROOT / "tests" / "js" / "devices_demo.mjs")], capture_output=True, text=True,
                                    check=True, timeout=120).stdout)
    w, whoop = got["list"]["providers"]
    assert whoop["id"] == "whoop" and whoop["connection"]["imported"]["days"] > 0
    assert w["available"] is True and w["connection"]["status"] == "active" and w["connection"]["imported"]["readings"] > 0
    assert got["sources"] == ["manual", "withings"] and got["origin"] == "from Withings"
    assert got["start"]["status"] == 400 and "demo cannot go to Withings" in got["start"]["detail"]
    assert got["sync"]["error"] is None and got["sync"]["result"]["added"] == {"weights": 0, "readings": 0, "days": 0, "workouts": 0}
    assert got["remove"]["removed"]["readings"] == w["connection"]["imported"]["readings"]
    assert got["after"] is None and "withings" not in got["left"]
    assert "fetch(" not in MOCK and "location.assign" not in MOCK
