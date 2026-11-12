"""Settings → Reminders (design note 35; ``js/views/reminders.js``), the service worker's push handlers (``sw.js``) and the demo's
twin (``js/mock/reminders.js``, run in Node)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import reminders

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "reminders.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "reminders.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_the_scripts_are_loaded_and_kept_offline() -> None:
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/mock/lists.js") < scripts.index("js/mock/reminders.js") < scripts.index("js/views/today.js")
    assert scripts.index("js/views/settings.js") < scripts.index("js/views/reminders.js") < scripts.index("js/main.js")
    assert "'/js/views/reminders.js'," in SW and "'/js/mock/reminders.js'," in SW


def test_the_section_is_hidden_until_the_server_has_it_on() -> None:
    assert ('<section class="card settings-section" id="set-reminders" data-title="Reminders" aria-labelledby="set-reminders-h" '
            "hidden>") in INDEX
    assert "const show = await KH.reminders.render($('#set-reminders-body'));" in SETTINGS
    assert "if (!res.enabled) { clear(body); return false; }" in VIEW
    assert "KH.deviceName = deviceName;" in SETTINGS
    for action in ("reminder.set", "reminder.removed", "reminder.device_added", "reminder.device_removed"):
        assert f"'{action}':" in SETTINGS


def test_the_safety_words_are_the_same_everywhere() -> None:
    assert reminders.SAFETY == "Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts."
    assert f'const SAFETY = "{reminders.SAFETY}";' in VIEW
    assert f'safety: "{reminders.SAFETY}",' in MOCK


def test_permission_is_asked_only_from_the_button() -> None:
    assert VIEW.count("Notification.requestPermission()") == 1
    turn_on = VIEW[VIEW.index("async function turnOn"):VIEW.index("async function turnOff")]
    assert "Notification.requestPermission()" in turn_on and "// The permission prompt comes only from this tap." in turn_on
    assert "pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(res.public_key) })" in turn_on


def test_iphone_in_a_safari_tab_gets_the_home_screen_how_to() -> None:
    assert "if (!MOCK && isIOS() && !standalone())" in VIEW
    assert "On iPhone and iPad, notifications work only in the app on your Home Screen." in VIEW
    assert "matchMedia('(display-mode: standalone)')" in VIEW


def test_no_html_no_outside_calls_and_the_demo_never_subscribes() -> None:
    for text in (VIEW, MOCK):
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "fetch(" not in text
    assert set(re.findall(r"'(/api/[^']+)'", VIEW)) == {"/api/reminders", "/api/reminders/subscriptions", "/api/reminders/test"}
    turn_on = VIEW[VIEW.index("async function turnOn"):VIEW.index("async function turnOff")]
    assert turn_on.index("if (MOCK) {") < turn_on.index("Notification.requestPermission()")
    assert "pushManager." not in MOCK and "Notification." not in MOCK


def test_the_service_worker_always_shows_a_notification_and_opens_only_this_server() -> None:
    push = SW[SW.index("self.addEventListener('push'"):SW.index("self.addEventListener('notificationclick'")]
    assert "event.waitUntil(self.registration.showNotification(title, {" in push
    assert "'Food log'" in push
    click = SW[SW.index("self.addEventListener('notificationclick'"):SW.index("function ownPage")]
    assert "ownPage(event.notification.data && event.notification.data.navigate)" in click
    assert "self.clients.openWindow(target)" in click
    own = SW[SW.index("function ownPage"):]
    assert "u.origin === self.location.origin && u.pathname === '/'" in own


def test_the_view_names_every_send_error() -> None:
    for code in ("gone", "blocked", "timeout", "unreachable", "auth", "rejected", "busy", "bad_answer"):
        assert re.search(rf"\b{code}: '", VIEW), code


@node
def test_the_demo_answers_like_the_server_and_sends_nothing() -> None:
    got = json.loads(subprocess.run(["node", str(ROOT / "tests" / "js" / "reminders_demo.mjs")], capture_output=True, text=True,
                                    check=True, timeout=120).stdout)
    assert got["get"]["enabled"] is True and got["get"]["max_reminders"] == reminders.MAX_REMINDERS
    assert got["get"]["max_devices"] == reminders.MAX_DEVICES and got["get"]["safety"] == reminders.SAFETY
    assert [k["kind"] for k in got["get"]["kinds"]] == list(reminders.KINDS)
    assert got["noDevice"] == {"status": 409, "detail": reminders.NO_DEVICES}
    assert {k: got["change"][k] for k in ("kind", "meal", "time", "days", "time_zone")} == {
        "kind": "log_meal", "meal": "lunch", "time": "12:30", "days": 31, "time_zone": "America/Chicago"}
    assert set(got["add"]) == set(reminders.ReminderOut.model_fields)
    assert got["noMeal"]["detail"] == reminders.MEAL_NEEDED and got["mealHere"]["detail"] == reminders.MEAL_NOT_HERE
    assert got["badTime"]["detail"] == reminders.BAD_TIME and got["noDays"]["detail"] == reminders.BAD_DAYS
    assert got["badZone"]["detail"] == reminders.BAD_ZONE and got["insulin"]["status"] == 400
    assert got["badHost"]["detail"] == reminders.BAD_ENDPOINT
    assert set(got["device"]) == set(reminders.ReminderDeviceOut.model_fields)
    assert got["test"] == {"devices": 1, "sent": 0, "failed": 0, "removed": 0, "demo": True}
    assert [r["time"] for r in got["export"]] == ["12:30"]
    assert (got["removeDevice"], got["remove"], got["removeAgain"]) == (200, 200, 404)
    texts = got["texts"]
    assert texts["too_many_reminders"] == reminders.TOO_MANY_REMINDERS and texts["too_many_devices"] == reminders.TOO_MANY_DEVICES
