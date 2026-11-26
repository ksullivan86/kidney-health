"""Withings and Whoop from the iPhone app (owner, 2026-11-26: "Should Withings and Whoop be set up from the phone?" "yes").

``tests/js/phone_devices.mjs`` runs the page's side (``js/mock/devices.js`` and ``activity.js`` in device mode) against a stand-in
app. Here: it passes, and the screens, the app's Swift side and the relay page keep their rules.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_the_page_side_against_a_stand_in_app() -> None:
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "phone_devices.mjs")], capture_output=True, text=True, timeout=300,
                          cwd=ROOT)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["ok"] is True and out["checks"] >= 40


def test_connected_devices_shows_on_the_phone() -> None:
    css = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    assert ".device-mode #set-connected" not in css
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    left_out = settings[settings.index("const DEVICE_LEFT_OUT"):settings.index("function renderNav()")]
    assert "set-connected" not in left_out


def test_the_screen_says_where_each_company_is_connected() -> None:
    view = (STATIC / "js" / "views" / "devices.js").read_text(encoding="utf-8")
    assert "' On this iPhone.' : ' Through your server.'" in view
    assert "if (out.url) { window.location.assign(out.url); return; }" in view  # the web app still goes to the company
    assert "'Open your server'" in view and "Press Done to come back." in view
    assert "with your own developer app" in view and "Keys and services" in view
    # the server's own page opened by the app: #/devices/open/<provider> opens Settings here, with no toast
    assert "m[1] === 'open'" in view and "if (word === 'open')" in view
    mock = (STATIC / "js" / "mock" / "devices.js").read_text(encoding="utf-8")
    for kind in ("deviceStatus", "deviceConnect", "deviceFetch", "deviceDisconnect", "serverPage"):
        assert f"kind: '{kind}'" in mock, kind
    # the page never asks for a secret or a token: the app keeps them
    for word in ("client_secret", "access_token", "refresh_token"):
        assert word not in mock, word
