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
* the iPhone's own AI (step 5), with a stand-in for the app's model: Settings → AI features has one switch; once it is on, Add offers
  Describe a meal, which sends the server's cleaned data to the app and shows the matches and the server's notice; a low gets the
  Treating a low card and the model is not asked;
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
STUB = ("window.__kh = { copies: [], phone: [], ai: [] };"
        "window.webkit = { messageHandlers: { safetyCopy: { postMessage: (t) => window.__kh.copies.push(String(t)) },"
        " phone: { postMessage: (m) => window.__kh.phone.push(String(m)) },"
        " bridge: { postMessage: async (r) => {"
        "   if (r.kind === 'aiStatus') return { ok: true, available: true, reason: null };"
        "   if (r.kind === 'ai') { window.__kh.ai.push(r); return { ok: true, answer: { status: 'ok', items: ["
        "     { text: '2 eggs', search: 'egg', amount: 2, unit: 'serving' }] } }; }"
        "   return { error: 'bad_request', message: 'not in this walk' }; } } } };")


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
    page.goto(f"{base}/index.html#today")
    page.reload()
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    check(f"[{tag}] the entry survives a reload", food["name"].split(",")[0].lower() in page.locator("#view-today").inner_text().lower())
    ai_walk(page, base, tag)
    over = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    check(f"[{tag}] no sideways scroll", not over)
    check(f"[{tag}] no request to another host", not others, "; ".join(others[:3]))
    check(f"[{tag}] no console or page error", not errors, "; ".join(errors[:3]))
    ctx.close()


def ai_walk(page, base: str, tag: str) -> None:
    """Design note 38 §5.6: describe a meal on the iPhone's own model (a stand-in answers for it)."""
    page.goto(f"{base}/index.html#settings")
    page.wait_for_selector("#view-settings:not([hidden])", timeout=30000)
    page.wait_for_selector("#set-ai-slot input[type=checkbox]", timeout=30000)
    text = page.locator("#set-ai-slot").inner_text()
    check(f"[{tag}] AI settings say it runs on this iPhone", "runs on this iPhone" in text, text[:160])
    page.locator("#set-ai-slot input[type=checkbox]").check()
    page.wait_for_timeout(500)
    page.goto(f"{base}/index.html#add")
    page.wait_for_selector("#view-add:not([hidden])", timeout=30000)
    button = page.get_by_role("button", name="Describe a meal (AI)")
    button.wait_for(timeout=30000)
    button.click()
    page.wait_for_selector("#sheet-ai[open] textarea", timeout=10000)
    page.fill("#sheet-ai textarea", "2 eggs, scrambled")
    page.get_by_role("button", name="Find foods").click()
    page.wait_for_selector("#sheet-ai .ai-parse-item", timeout=10000)
    results = page.locator("#sheet-ai .ai-results").inner_text()
    sent = page.evaluate("window.__kh.ai")
    check(f"[{tag}] describe a meal asks the app with the server's data",
          sent[-1:] == [{"kind": "ai", "task": "parse_meal", "text": '{"text":"2 eggs, scrambled"}'}], json.dumps(sent)[:160])
    check(f"[{tag}] the matches and the server's notice are shown",
          "egg" in results.lower() and "Nothing is logged until you add it" in results, results[:160])
    page.fill("#sheet-ai textarea", "my sugar is 55")
    page.get_by_role("button", name="Find foods").click()
    page.wait_for_selector("#sheet-ai .ai-card-alert", timeout=10000)
    check(f"[{tag}] a low gets the Treating a low card, and the model is not asked",
          "Treating a low" in page.locator("#sheet-ai .ai-results").inner_text() and len(page.evaluate("window.__kh.ai")) == len(sent))
    page.keyboard.press("Escape")


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
