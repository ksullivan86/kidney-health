#!/usr/bin/env python3
"""The web app as the iPhone app packs it (design note 38, step 1: device mode) in Chromium.

    python tools/e2e/device_mode.py                    # no server: the copy is built and served statically
    python tools/e2e/device_mode.py --out /tmp/kh-device

Builds the iPhone app's copy (``scripts/build_preview.py --device``), serves it from a throw-away static server on localhost, and
stands in for the iPhone app's message handlers. At 375x812 light and 1280x800 dark, each in a fresh browser profile:

* there is no demo pill, no demo banner and no "Keep my data in this browser" button; the log starts empty with no sample person;
* the one person is not an admin, and Settings has no sign-out button and no signed-in devices list; This device says the data is
  kept on this iPhone and offers "Apple Health and server", which asks the app to open its settings;
* an entry is added, the page reloaded: the entry is still on Today; after the save the app was handed the safety copy, which holds it;
* no request to any other host, no console or page error (CSP violations included), no sideways scroll.

Nothing leaves the machine. Prints PASS / FAIL lines and writes ``<out>/report.json``; exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import khserver
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "device-mode"
RESULTS: list[dict] = []
STUB = ("window.__kh = { copies: [], phone: [] };"
        "window.webkit = { messageHandlers: { safetyCopy: { postMessage: (t) => window.__kh.copies.push(String(t)) },"
        " phone: { postMessage: (m) => window.__kh.phone.push(String(m)) },"
        " bridge: { postMessage: async (r) => r.kind === 'services' ? { ok: true, off: false, usda: false, scan: true }"
        " : r.kind === 'scanBarcode' ? { ok: true, code: '3017624010701', format: 'ean_13' } : { error: 'off_off', message: 'off' } } } };")


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail and not ok else ""))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # the walk prints its own lines
        pass


def walk(browser, base: str, width: int, height: int, scheme: str) -> None:
    tag = f"{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
    ctx.add_init_script(STUB)
    page = ctx.new_page()
    errors: list[str] = []
    others: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: others.append(r.url) if not r.url.startswith(base) else None)
    page.goto(f"{base}/index.html#today")
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    check(f"[{tag}] no demo pill or banner", page.locator("#brand-pill").is_hidden() and page.locator("#preview-banner").is_hidden())
    check(f"[{tag}] no Keep my data button", page.locator("#preview-banner-keep").is_hidden())
    # The first-start setup (js/views/welcome.js): an empty log of one's own, the profile basics, the optional server, done.
    page.wait_for_selector("#sheet-welcome[open]", timeout=10000)
    check(f"[{tag}] the setup opens at the first start", page.locator("#welcome-title").inner_text() == "Welcome to Kidney Health")
    page.click("#welcome-next")
    page.fill("#welcome-name", "Kim")
    page.select_option("#welcome-stage", "4")
    page.select_option("#welcome-diabetes", "type1")
    page.click("#welcome-about-next")
    page.wait_for_selector("#welcome-server-next")
    page.click("#welcome-server")
    check(f"[{tag}] the server step opens the phone settings", page.evaluate("window.__kh.phone") == ["settings"])
    page.click("#welcome-server-next")
    page.click("#welcome-done")
    page.wait_for_timeout(300)
    profile = page.evaluate("KH.request('GET', '/api/profile')")
    check(f"[{tag}] the setup saved the profile", profile.get("name") == "Kim" and profile.get("ckd_stage") == "4" and profile.get("diabetes_chosen") is True)
    check(f"[{tag}] the setup is closed", not page.locator("#sheet-welcome[open]").count())
    page.evaluate("window.__kh.phone.length = 0")
    start = page.evaluate("KH.request('GET', '/api/log?date=' + KH.state.date)")
    check(f"[{tag}] the log starts empty", len(start.get("entries", [])) == 0)
    me = page.evaluate("KH.request('GET', '/api/auth/status')")
    user = me.get("user") or {}
    check(f"[{tag}] one person, not an admin", user.get("username") == "me" and user.get("role") == "user", json.dumps(user)[:120])
    page.goto(f"{base}/index.html#settings")
    page.wait_for_selector("#view-settings:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    check(f"[{tag}] no sign-out and no device list", page.locator("#set-signout").count() == 0 and page.locator("#set-devices").count() == 0)
    body = page.locator("#set-device-body").inner_text()
    check(f"[{tag}] This device says the data is on this iPhone", "kept on this iPhone" in body, body[:120])
    page.click("#set-phone-settings")
    check(f"[{tag}] Apple Health and server asks the app", page.evaluate("window.__kh.phone") == ["settings"])
    food = page.evaluate("KH.request('GET', '/api/foods?q=banana&limit=1')")["foods"][0]
    page.evaluate(f"KH.request('POST', '/api/log', {{ date: KH.state.date, meal: 'lunch', food_id: {food['id']}, servings: 1 }})")
    for _ in range(100):  # the page's CSP forbids the string evaluation wait_for_function uses
        if page.evaluate("window.__kh.copies.length"):
            break
        page.wait_for_timeout(100)
    copy = json.loads(page.evaluate("window.__kh.copies[window.__kh.copies.length - 1]"))
    check(f"[{tag}] the safety copy holds the entry", len(copy.get("log_entries", [])) == 1 and copy.get("format") == "kidney-health-export")
    # The native barcode scanner (owner, 2026-11-21): the Scan sheet offers Apple's scanner, and its code goes to the usual look-up.
    page.goto(f"{base}/index.html#add")
    page.wait_for_selector("#view-add:not([hidden])", timeout=30000)
    page.evaluate("KH.scan.open()")
    page.wait_for_selector("#scan-camera:not([hidden])", timeout=10000)
    check(f"[{tag}] Scan offers the iPhone's own scanner", page.locator("#scan-camera").inner_text() == "Scan with the camera")
    page.wait_for_timeout(1500)
    check(f"[{tag}] the scanned code goes to the usual look-up", page.locator("#scan-code").input_value() == "3017624010701",
          page.locator("#scan-status").inner_text()[:120])
    page.keyboard.press("Escape")
    page.goto(f"{base}/index.html#today")
    page.reload()
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    check(f"[{tag}] the entry survives a reload", food["name"].split(",")[0].lower() in page.locator("#view-today").inner_text().lower())
    check(f"[{tag}] the setup does not come back once finished", not page.locator("#sheet-welcome[open]").count())
    over = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    check(f"[{tag}] no sideways scroll", not over)
    check(f"[{tag}] no request to another host", not others, "; ".join(others[:3]))
    check(f"[{tag}] no console or page error", not errors, "; ".join(errors[:3]))
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    out = khserver.free_dir(args.out)
    site = out / "site"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_preview.py"), "--device", str(site)], check=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, base, width, height, scheme)
            finally:
                browser.close()
    finally:
        server.shutdown()
    failed = any(not r["ok"] for r in RESULTS)
    (out / "report.json").write_text(json.dumps({"results": RESULTS, "failed": failed}, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in RESULTS)} passed, {sum(not r['ok'] for r in RESULTS)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
