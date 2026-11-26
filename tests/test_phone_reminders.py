"""Reminders as the iPhone's own notifications (design note 35 §7).

In the iPhone app there is no server and no Web Push. The page keeps the reminders in the log, plans the next 7 days
(``js/mock/phone_reminders.js``) and asks the app (``{kind: "reminders"}`` through the bridge) to replace its pending
notifications. ``tests/js/phone_reminders.mjs`` runs the page side; this file checks the plan against the server's own rule
(``app/reminders.py`` ``is_due`` and the meal already eaten), and pins the app's words, kinds and screens to the server's.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import reminders

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
SWIFT = (ROOT / "ios" / "KidneyHealth" / "Phone" / "LocalReminders.swift").read_text(encoding="utf-8")
CODE = re.sub(r"//[^\n]*", "", SWIFT)
PAGE = (STATIC / "js" / "mock" / "phone_reminders.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "reminders.js").read_text(encoding="utf-8")
VECTORS = json.loads((ROOT / "tests" / "data" / "phone_reminder_vectors.json").read_text(encoding="utf-8"))


def test_the_page_side_in_node():
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "phone_reminders.mjs")], capture_output=True, text=True, timeout=180,
                          check=False, env={**os.environ, "TZ": "UTC"})
    assert done.returncode == 0, done.stdout + done.stderr
    assert "checks passed" in done.stdout


def _server_plan(case: dict) -> list[dict]:
    """The same plan from the server's rule: a reminder goes out at its time on a day is_due says, unless the meal was eaten today."""
    zone = ZoneInfo("UTC")
    now = datetime.fromisoformat(case["now"]).replace(tzinfo=zone)
    out = []
    for offset in range(VECTORS["days_ahead"]):
        day: date = now.date() + timedelta(days=offset)
        for r in case["reminders"]:
            hh, mm = (int(x) for x in r["time"].split(":"))
            at = datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone)
            row = {"enabled": r["enabled"], "days": r["days"], "time_local": r["time"], "time_zone": "UTC", "last_sent_on": None}
            if at <= now or reminders.is_due(row, at) != day.isoformat():
                continue
            if offset == 0 and r["kind"] == "log_meal" and r["meal"] in case["eaten"]:
                continue
            out.append({"id": f"reminder-{r['id']}-{day.isoformat()}", "at": f"{day.isoformat()}T{r['time']}", "kind": r["kind"],
                        "meal": r["meal"] if r["kind"] == "log_meal" else None, "_t": at})
    out.sort(key=lambda x: (x["_t"], x["id"]))
    return [{k: v for k, v in x.items() if k != "_t"} for x in out[: VECTORS["max_pending"]]]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[c["name"] for c in VECTORS["cases"]])
def test_the_vectors_follow_the_servers_rule(case):
    assert _server_plan(case) == case["expect"]


def test_the_app_writes_the_servers_words_and_nothing_about_health():
    assert 'static let title = "Food log"' in CODE and reminders.DEFAULT_TITLE == "Food log"
    assert f'static let testBody = "{reminders.TEST_BODY}"' in CODE
    bodies = dict(re.findall(r'"([a-z_:]+)": "(Time to [^"]+)"', CODE))
    assert bodies == {(f"{k}:{m}" if m else k): v for (k, m), v in reminders.BODIES.items()}
    screens = dict(re.findall(r'"(\w+)": "(add|plan|today)"', CODE[CODE.index("static let screens"):]))
    assert screens == reminders.PAGES
    assert 'static let allowedScreens: Set<String> = ["add", "plan", "today", "settings"]' in CODE
    # the page sends only ids, times, kinds and meals; the text comes from the table above
    assert 'item["body"]' not in CODE and 'item["title"]' not in CODE and "content.body = body" in CODE
    for word in ("insulin", "glucose", "medic", "dose", "low blood", "hypo", "kidney", "potassium", "phosph", "sodium"):
        assert word not in CODE.lower(), word


def test_the_app_plans_single_notifications_in_the_phones_time_zone():
    assert "UNCalendarNotificationTrigger(dateMatching: when, repeats: false)" in CODE
    assert "timeZone" not in CODE  # calendar parts with no zone: the phone's own when it goes off
    assert "static let maxItems = 60" in CODE and "const MAX_PENDING = 60;" in PAGE and "const DAYS_AHEAD = 7;" in PAGE
    assert "items.count <= Self.maxItems" in CODE
    # only our own pending notifications are replaced; the permission prompt comes only from the "allow" action
    assert "$0.hasPrefix(Self.idPrefix)" in CODE and 'static let idPrefix = "reminder-"' in CODE
    assert CODE.count("requestAuthorization(") == 1
    allow = CODE[CODE.index('case "allow":'):CODE.index('case "schedule":')]
    assert "requestAuthorization(options: [.alert, .sound])" in allow
    assert "UIApplication.openNotificationSettingsURLString" in CODE
    for word in ("print(", "NSLog", "os_log", "Logger(", "URLSession", "Keychain"):
        assert word not in CODE, word


def test_the_bridge_kind_and_the_tap_are_wired():
    services = (ROOT / "ios" / "KidneyHealth" / "Services" / "FoodServices.swift").read_text(encoding="utf-8")
    assert 'case "reminders":' in services and "LocalReminders.shared.answer(request)" in services
    app = (ROOT / "ios" / "KidneyHealth" / "KidneyHealthApp.swift").read_text(encoding="utf-8")
    assert "LocalReminders.shared.install()" in app
    assert "LocalReminders.shared.run()" in (ROOT / "ios" / "KidneyHealth" / "WebShell" / "WebShellConfig.swift").read_text(encoding="utf-8")
    assert 'callAsyncJavaScript("return await window.KH.openScreen(name);"' in CODE
    main = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
    assert "const REMINDER_SCREENS = ['add', 'plan', 'today', 'settings'];" in main
    assert "if (!DEVICE || !REMINDER_SCREENS.includes(name)) return false;" in main
    for action in ("status", "allow", "schedule", "test", "openSettings"):
        assert f'"{action}"' in CODE and f"'{action}'" in PAGE, action
    assert "kind: 'reminders'" in PAGE


def test_settings_shows_reminders_on_the_iphone_with_the_safety_line():
    css = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    assert "#set-reminders" not in css[css.index("/* The iPhone app with no server"):]
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    left_out = settings[settings.index("const DEVICE_LEFT_OUT"):settings.index("function renderNav()")]
    assert "set-reminders" not in left_out
    assert "Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts." in VIEW
    assert "Reminders set here are for this iPhone only. They are not sent to a server." in VIEW
    assert "'Turn on notifications on this iPhone'" in VIEW and "'Open iPhone Settings'" in VIEW
    assert "tap Notifications, then Kidney Health, and turn on Allow Notifications." in VIEW
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert index.index('src="js/mock/persist.js"') < index.index('src="js/mock/phone_reminders.js"') < index.index('src="js/mock/seed.js"')
    assert "'/js/mock/phone_reminders.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")
