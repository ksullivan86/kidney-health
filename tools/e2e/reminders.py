#!/usr/bin/env python3
"""Reminders by phone notification (design note 35) in Chromium, against a real server and the demo.

    python3 tools/e2e/reminders.py                    # port 8118
    python3 tools/e2e/reminders.py --port 8118 --out /tmp/kh-reminders

Starts the real app (``reminders_app:app``: the push services answered by a fake inside the process, behind the app's real sender
and checked transport) on a fresh ``DATA_DIR`` with ``REMINDERS_ENABLED``. The page's ``PushManager.subscribe`` is stubbed with a
fixed subscription on Apple's push host, holding the RFC 8291 example's browser key, so the fake can decrypt what the server sent.
Walks:

* the person at 375x812 light: Settings → Reminders shows the safety words; Turn on notifications on this device (permission
  granted to the page beforehand); the device is listed as This device; add a lunch reminder; change it; Send a test, which
  the fake receives as Declarative Web Push with the generic words; a reminder due now goes out from the loop within about a
  minute; Turn off on this device.
* an iPhone Safari tab (not from the Home Screen): the how-to instead of the button.
* the demo (``/?mock=1``): turn on, Send a test, "no notification was sent", and no request to the server's reminder routes.
* no console error, no CSP violation, no browser dialog, no sideways scroll, no other host from the app's page.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1
on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import khserver
from khserver import Api, Server, first_admin
from playwright.sync_api import sync_playwright
from reminders_app import AUTH, ENDPOINT, UA_PUBLIC
from sharing import RESULTS, Pass, check, text_of, wait_text

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "reminders"
PORT = 8118
SAFETY = "Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts."
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Mobile/15E148 Safari/604.1"

# The page's push subscription: a fixed one on Apple's push host (Chromium without a push service cannot make a real one).
STUB = """
(() => {
  const state = { sub: null, unsubscribed: 0 };
  window.__push = state;
  const make = () => ({
    endpoint: %(endpoint)s, expirationTime: null, options: {},
    toJSON() { return { endpoint: this.endpoint, expirationTime: null, keys: { p256dh: %(p256dh)s, auth: %(auth)s } }; },
    unsubscribe() { state.sub = null; state.unsubscribed += 1; return Promise.resolve(true); },
  });
  if (window.PushManager) {
    PushManager.prototype.subscribe = function (opts) {
      state.key = opts && opts.applicationServerKey ? opts.applicationServerKey.byteLength : 0;
      state.sub = make();
      return Promise.resolve(state.sub);
    };
    PushManager.prototype.getSubscription = function () { return Promise.resolve(state.sub); };
  }
})();
""" % {"endpoint": json.dumps(ENDPOINT), "p256dh": json.dumps(UA_PUBLIC), "auth": json.dumps(AUTH)}


def pushed(server: Server) -> list[dict[str, Any]]:
    out = []
    for line in server.log().splitlines():
        if "push fake: " in line:
            out.append(json.loads(line.split("push fake: ", 1)[1]))
    return out


def open_reminders(page: Any) -> None:
    page.goto("/#settings")
    page.wait_for_selector("#set-reminders:not([hidden])", timeout=30000)
    page.wait_for_selector("#set-reminders-body .settings-subtitle, #set-reminders-ios, #set-reminders-test-account", timeout=15000)


def walk_person(p: Pass, server: Server, api: Api) -> None:
    page = p.page
    p.ctx.grant_permissions(["notifications"], origin=p.base)
    page.add_init_script(STUB)
    page.goto("/")
    page.wait_for_function("() => navigator.serviceWorker && navigator.serviceWorker.getRegistration().then((r) => !!r)", timeout=30000)
    page.evaluate("() => navigator.serviceWorker.ready.then(() => true)")
    open_reminders(page)
    check(f"[{p.tag}] the safety words are shown", text_of(page, "#set-reminders-safety") == SAFETY, text_of(page, "#set-reminders-safety"))
    check(f"[{p.tag}] Settings has a Reminders chip", "Reminders" in text_of(page, "#settings-nav"))
    check(f"[{p.tag}] no reminders yet", "No reminders yet." in text_of(page, "#set-reminders-list"))
    p.shot("reminders-start", "#set-reminders")

    page.click("#set-reminders-on")
    page.wait_for_selector("#set-reminders-off", timeout=15000)
    check(f"[{p.tag}] the page subscribed with the server's 65-byte key", page.evaluate("window.__push.key") == 65)
    check(f"[{p.tag}] this device is on and listed", "Notifications are on for this device." in text_of(page, "#set-reminders-device")
          and "this device" in text_of(page, "#set-reminders-devices").lower())

    page.click("#set-reminders-add")
    page.select_option("#set-reminder-what", "log_meal:lunch")
    page.fill("#set-reminder-time", "12:30")
    page.uncheck("#set-reminder-day-5")
    page.uncheck("#set-reminder-day-6")
    page.click("#set-reminder-save")
    page.wait_for_selector("#set-reminder-form", state="detached", timeout=15000)
    check(f"[{p.tag}] the reminder is listed with its time and days", "Weekdays" in text_of(page, "#set-reminders-list")
          and "12:30" in text_of(page, "#set-reminders-list"), text_of(page, "#set-reminders-list"))
    saved = api.json("GET", "/api/reminders")["reminders"]
    check(f"[{p.tag}] it was saved with the browser's time zone", len(saved) == 1 and saved[0]["days"] == 31 and saved[0]["time_zone"],
          json.dumps(saved))
    page.click("#set-reminders-list button:has-text('Change')")
    page.select_option("#set-reminder-what", "log_meal:dinner")
    page.fill("#set-reminder-time", "18:00")
    page.click("#set-reminder-save")
    page.wait_for_selector("#set-reminder-form", state="detached", timeout=15000)
    check(f"[{p.tag}] the change is listed", "Log dinner" in text_of(page, "#set-reminders-list"), text_of(page, "#set-reminders-list"))
    p.shot("reminders-list", "#set-reminders")

    page.click("#set-reminders-test")
    wait_text(page, "#set-reminders-device-msg", "Sent to 1 device")
    got = pushed(server)
    msg = got[-1]["message"] if got else {}
    check(f"[{p.tag}] the push service got one encrypted Declarative Web Push", len(got) == 1 and got[0]["host"] == "web.push.apple.com"
          and got[0]["vapid"] and got[0]["ttl"] == "3600" and got[0]["urgency"] == "normal" and msg.get("web_push") == 8030, json.dumps(got)[:400])
    note = msg.get("notification", {})
    check(f"[{p.tag}] the words are generic", note.get("title") == "Food log" and note.get("body") == "This is a test. Your reminders will look like this."
          and note.get("navigate", "").endswith("/#settings"), json.dumps(note))

    # A reminder due now (UTC), sent by the loop within about a minute.
    now = datetime.now(timezone.utc)
    api.json("POST", "/api/reminders", {"kind": "plan_tomorrow", "time": now.strftime("%H:%M"), "time_zone": "UTC"})
    deadline = time.time() + 95
    while time.time() < deadline and not any(x["message"].get("notification", {}).get("body") == "Time to plan tomorrow's meals."
                                             for x in pushed(server)):
        time.sleep(2)
    sent = [x for x in pushed(server) if x["message"].get("notification", {}).get("body") == "Time to plan tomorrow's meals."]
    check(f"[{p.tag}] the loop sent the due reminder once", len(sent) == 1 and sent[0]["message"]["notification"]["navigate"].endswith("/#plan"),
          json.dumps(pushed(server))[-400:])

    page.click("#set-reminders-off")
    page.wait_for_selector("#set-reminders-on", timeout=15000)
    check(f"[{p.tag}] turning off unsubscribes and removes the device", page.evaluate("window.__push.unsubscribed") == 1
          and api.json("GET", "/api/reminders")["devices"] == [])
    events = json.dumps(api.json("GET", "/api/me/activity"))
    check(f"[{p.tag}] the activity list has the reminder rows", all(a in events for a in (
        "reminder.set", "reminder.device_added", "reminder.device_removed")))
    p.no_overflow("settings")
    p.finish()


def walk_iphone_tab(p: Pass) -> None:
    page = p.page
    page.add_init_script(f"Object.defineProperty(navigator, 'userAgent', {{ get: () => {json.dumps(IPHONE)} }});")
    open_reminders(page)
    wait_text(page, "#set-reminders-ios", "Home Screen")
    check(f"[{p.tag}] an iPhone Safari tab gets the Home Screen how-to, no button", not page.is_visible("#set-reminders-on"))
    p.shot("reminders-iphone-tab", "#set-reminders")
    p.finish()


def walk_demo(p: Pass) -> None:
    page = p.page
    page.goto("/?mock=1")
    page.wait_for_selector("#form-login:not([hidden]), #settings-open", timeout=30000)
    if page.is_visible("#form-login"):
        page.fill("#login-username", "sam")
        page.fill("#login-password", "any demo password at all 15")
        page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.goto("/?mock=1#settings")
    page.wait_for_selector("#set-reminders:not([hidden])", timeout=30000)
    page.wait_for_selector("#set-reminders-on", timeout=15000)
    check(f"[{p.tag}] the demo says it never sends", "never sends a notification" in text_of(page, "#set-reminders-demo"))
    page.click("#set-reminders-on")
    page.wait_for_selector("#set-reminders-test", timeout=15000)
    page.click("#set-reminders-test")
    wait_text(page, "#set-reminders-device-msg", "Demo: no notification was sent.")
    check(f"[{p.tag}] the demo said no notification was sent", True)
    p.shot("reminders-demo", "#set-reminders")
    check(f"[{p.tag}] the demo asked the network for no reminder route",
          not any("/api/reminders" in r for r in p.watch.requests), str(p.watch.requests[-5:]))
    p.no_overflow("demo")
    p.finish()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook"),
           "PUBLIC_URL": f"http://127.0.0.1:{args.port}", "REMINDERS_ENABLED": "true", "VAPID_SUBJECT": "mailto:admin@example.org"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env, app_spec="reminders_app:app")
    try:
        server.start()
        admin = first_admin(server, "mum")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                walk_person(Pass(browser, server.base, out, 375, 812, "light", "person-375-light", admin.cookies()), server, admin)
                walk_iphone_tab(Pass(browser, server.base, out, 375, 812, "light", "iphone-tab-375-light", admin.cookies()))
                walk_demo(Pass(browser, server.base, out, 375, 812, "light", "demo-375-light"))
            finally:
                browser.close()
        key = (out / "data" / "vapid_private.pem").read_text(encoding="utf-8")
        body = "".join(line for line in key.splitlines() if not line.startswith("-----"))
        check("the server log never holds the push key", body[:40] not in server.log() and body[-40:] not in server.log())
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc(limit=3))
    finally:
        server.stop()
    failed = any(not r["ok"] for r in RESULTS)
    (out / "report.json").write_text(json.dumps({"results": RESULTS, "failed": failed}, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in RESULTS)} passed, {sum(not r['ok'] for r in RESULTS)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
