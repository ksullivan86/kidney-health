#!/usr/bin/env python3
"""Open the shopping list at Instacart (design note 33) in Chromium, against a real server and the demo.

    python3 tools/e2e/instacart.py                    # port 8112
    python3 tools/e2e/instacart.py --port 8112 --out /tmp/kh-instacart

Starts the real app (``instacart_app:app``: Instacart answered by a fake inside the process, behind the app's real client and
checked transport) on a fresh ``DATA_DIR`` with ``INSTACART_ENABLED``, a key file and the development host. Walks:

* the person at 375x812 light: Plan → Shopping list → Open in Instacart: the exact lines, what is sent, Instacart's own terms;
  one line unticked; Send; the fake got exactly the title and the ticked line with the key, nothing about the person; the link
  opens in a new tab (answered inside the browser, never from the network) and is shown as a button.
* the demo (``/?mock=1``) at 375x812: Open in Instacart, Send, "nothing was sent", no new tab.
* no console error, no CSP violation, no browser dialog, no sideways scroll, no other host from the app's page.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on
any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path
from typing import Any

import khserver
from instacart_app import KEY, LINK
from khserver import Api, Server, first_admin
from playwright.sync_api import sync_playwright
from sharing import RESULTS, Pass, check, text_of, wait_text

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "instacart"
PORT = 8112


def sent_bodies(server: Server) -> list[dict[str, Any]]:
    out = []
    for line in server.log().splitlines():
        if "instacart fake: " in line:
            out.append(json.loads(line.split("instacart fake: ", 1)[1]))
    return out


def walk_person(p: Pass, server: Server, api: Api) -> None:
    page = p.page
    opened: list[str] = []
    p.ctx.route("https://customers.dev.instacart.tools/**", lambda route: (opened.append(route.request.url), route.fulfill(
        status=200, content_type="text/html", body="<!doctype html><title>Instacart (fake)</title><p>Fake Instacart page</p>")))
    page.goto("/#plan")
    page.wait_for_selector("#shopping-instacart:not([hidden])", timeout=30000)
    check(f"[{p.tag}] Plan shows Open in Instacart", text_of(page, "#shopping-instacart") == "Open in Instacart")
    page.click("#shopping-instacart")
    page.wait_for_selector("#instacart-items li", timeout=15000)
    lines = [t.strip() for t in page.locator("#instacart-items .check-text").all_inner_texts()]
    check(f"[{p.tag}] the sheet shows the exact lines", len(lines) == 2 and all(": " in t and "serving" in t for t in lines), str(lines))
    check(f"[{p.tag}] it says nothing else is sent", "Nothing else about you is sent" in text_of(page, "#instacart-what"))
    check(f"[{p.tag}] it says Instacart's own terms apply", "Instacart is another company" in text_of(page, "#instacart-terms")
          and "privacy policy" in text_of(page, "#instacart-terms"))
    page.locator("#instacart-items input[type=checkbox]").nth(1).uncheck()
    check(f"[{p.tag}] Send counts the ticked lines", text_of(page, "#instacart-go") == "Send 1 item to Instacart", text_of(page, "#instacart-go"))
    p.shot("instacart-sheet", "#sheet-instacart")
    check(f"[{p.tag}] nothing was sent before Send", sent_bodies(server) == [])
    with p.ctx.expect_page(timeout=15000) as popup_info:
        page.click("#instacart-go")
    popup = popup_info.value
    popup.wait_for_load_state()
    check(f"[{p.tag}] the link opened in a new tab", popup.url == LINK, popup.url)
    popup.close()
    page.wait_for_selector("#instacart-open", timeout=15000)
    check(f"[{p.tag}] the link is also a button", page.get_attribute("#instacart-open", "href") == LINK
          and page.get_attribute("#instacart-open", "target") == "_blank"
          and "noopener" in (page.get_attribute("#instacart-open", "rel") or ""))
    check(f"[{p.tag}] the Send button is gone", not page.is_visible("#instacart-go"))
    p.shot("instacart-ready", "#sheet-instacart")
    bodies = sent_bodies(server)
    want = {"title": "Shopping list", "link_type": "shopping_list", "expires_in": 7}
    check(f"[{p.tag}] Instacart got one request with the key", len(bodies) == 1 and bodies[0]["key_ok"]
          and bodies[0]["path"] == "/idp/v1/products/products_link", json.dumps(bodies)[:400])
    body = bodies[0]["body"] if bodies else {}
    check(f"[{p.tag}] only the title and the ticked line", {k: body.get(k) for k in want} == want
          and [i.get("display_text") for i in body.get("line_items", [])] == [lines[0]], json.dumps(body)[:400])
    text = json.dumps(body)
    check(f"[{p.tag}] nothing about the person", "mum" not in text and date.today().isoformat() not in text
          and "127.0.0.1" not in text and "Kidney" not in text, text[:300])
    check(f"[{p.tag}] the browser opened only the link", opened == [LINK], str(opened))
    page.click("#instacart-cancel")
    p.no_overflow("plan")
    events = api.json("GET", "/api/me/activity")
    check(f"[{p.tag}] the activity list has the send", "instacart.sent" in json.dumps(events) and LINK not in json.dumps(events))
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
    page.goto("/?mock=1#plan")
    page.wait_for_selector("#shopping-instacart:not([hidden])", timeout=30000)
    page.click("#shopping-instacart")
    page.wait_for_selector("#instacart-items li", timeout=15000)
    pages_before = len(p.ctx.pages)
    page.click("#instacart-go")
    wait_text(page, "#instacart-body", "nothing was sent")
    check(f"[{p.tag}] the demo says nothing was sent and opens no tab", len(p.ctx.pages) == pages_before
          and not page.is_visible("#instacart-open"))
    p.shot("instacart-demo", "#sheet-instacart")
    check(f"[{p.tag}] the demo asked the network for no Instacart route",
          not any("/api/instacart" in r for r in p.watch.requests), str(p.watch.requests[-5:]))
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
    key_file = out / "instacart_api_key"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    key_file.chmod(0o600)
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook"),
           "INSTACART_ENABLED": "true", "INSTACART_API_KEY_FILE": str(key_file),
           "INSTACART_BASE_URL": "https://connect.dev.instacart.tools",
           "SHARING_ENABLED": "true"}  # the Care team on, as on a family server (Plan asks /api/shared, a 404 while off)
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env, app_spec="instacart_app:app")
    try:
        server.start()
        admin = first_admin(server, "mum")
        today = date.today().isoformat()
        for query, servings in (("banana", 2), ("rice white", 1)):
            food = admin.json("GET", "/api/foods", params={"q": query, "limit": 1})["foods"][0]
            admin.json("POST", "/api/log", {"date": today, "meal": "lunch", "food_id": food["id"], "servings": servings, "status": "planned"})
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                walk_person(Pass(browser, server.base, out, 375, 812, "light", "person-375-light", admin.cookies()), server, admin)
                walk_demo(Pass(browser, server.base, out, 375, 812, "light", "demo-375-light"))
            finally:
                browser.close()
        check("the server log never holds the Instacart key", KEY not in server.log())
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
