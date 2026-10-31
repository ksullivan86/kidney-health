#!/usr/bin/env python3
"""Your own list app and recipe import (design note 30) in Chromium, against a real server and the demo.

    python3 tools/e2e/lists_recipes.py                    # port 8110 (and 8111 for the fake Grocy)
    python3 tools/e2e/lists_recipes.py --port 8110 --out /tmp/kh-lists

Starts the real app (``lists_recipes_app:app``: recipe pages answered by a fake site inside the process, behind the app's real
fetcher) on a fresh ``DATA_DIR`` with ``LIST_SYNC_ENABLED``, ``RECIPE_IMPORT_ENABLED`` and ``LIST_SYNC_ALLOWED_HOSTS=127.0.0.1``,
and a fake Grocy (a real HTTP server on 127.0.0.1) that checks the key and keeps what it was sent. Walks:

* the person at 375x812 light: Plan → Import a recipe from a page link: the draft's name and servings, Save off until every line
  is checked, the estimate sentence, a match fixed with Search, a line left out; Save; the saved recipe keeps the link and the
  note. A link to a home address is refused. Pasted ingredients, saved too.
* Settings → Shopping list app: Grocy, the address and key, Save, Test (the one list is chosen); the key box stays empty.
  Plan → Shopping list → Send to Grocy: the exact lines, one unticked, Send; the fake Grocy got exactly the ticked lines with the key.
* the demo (``/?mock=1``) at 375x812: the sample page, a saved recipe, the sample Grocy, Send.
* no console error (but the one refusal asked for), no CSP violation, no browser dialog, no sideways scroll, no other host.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on
any failure. The servers are always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import traceback
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import khserver
from khserver import Api, Server, first_admin
from playwright.sync_api import sync_playwright
from sharing import RESULTS, Pass, check, text_of, wait_text

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "lists-recipes"
PORT = 8110
KEY = "grocy-e2e-key-0123456789abcdef"


class FakeGrocy(BaseHTTPRequestHandler):
    added: list[dict[str, Any]] = []
    keys: list[str | None] = []

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _send(self, status: int, body: Any) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorised(self) -> bool:
        FakeGrocy.keys.append(self.headers.get("GROCY-API-KEY"))
        return self.headers.get("GROCY-API-KEY") == KEY

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorised():
            return self._send(401, {"error_message": "no"})
        if self.path == "/api/system/info":
            return self._send(200, {"grocy_version": {"Version": "4.5.0"}})
        if self.path == "/api/objects/shopping_lists":
            return self._send(200, [{"id": 1, "name": "Groceries"}])
        return self._send(404, {})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorised():
            return self._send(401, {"error_message": "no"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
        if self.path == "/api/objects/shopping_list":
            FakeGrocy.added.append(body)
            return self._send(200, {"created_object_id": len(FakeGrocy.added)})
        return self._send(404, {})


def open_import(page: Any) -> None:
    page.goto("/#plan")
    page.wait_for_selector("#btn-import-recipe", state="visible", timeout=30000)
    page.click("#btn-import-recipe")
    page.wait_for_selector("#sheet-recipe-import[open] #ri-text", timeout=15000)


def check_all_lines(page: Any) -> int:
    boxes = page.locator("#ri-lines input[type=checkbox]")
    for i in range(boxes.count()):
        if not boxes.nth(i).is_checked():
            boxes.nth(i).check()
    return boxes.count()


def walk_person(p: Pass, api: Api, grocy_port: int) -> None:
    page = p.page
    # ---- Import from a page --------------------------------------------------------------------------------------
    open_import(page)
    check(f"[{p.tag}] the import sheet offers a page link (pages are on)", page.is_visible("#ri-url"))
    page.fill("#ri-url", "https://recipes.test/garlic-chicken")
    page.click("#ri-read-page")
    page.wait_for_selector("#ri-lines li", timeout=20000)
    check(f"[{p.tag}] the page's name and servings", page.input_value("#ri-review-name") == "Garlic chicken and rice"
          and page.input_value("#ri-review-makes") == "4", page.input_value("#ri-review-name"))
    check(f"[{p.tag}] the estimate sentence is shown", "These numbers are estimates" in text_of(page, "#ri-estimate"))
    check(f"[{p.tag}] the link is kept", "https://recipes.test/garlic-chicken" in text_of(page, "#ri-source"))
    check(f"[{p.tag}] Save is off until every line is checked", page.is_disabled("#recipe-import-go")
          and "Check every line" in text_of(page, "#recipe-import-go"))
    lines = page.locator("#ri-lines > li")
    check(f"[{p.tag}] five ingredient lines", lines.count() == 5, str(lines.count()))
    thyme = text_of(page, "#ri-line-4")
    check(f"[{p.tag}] the thyme has no match and is left out", "No food in your list matches" in thyme, thyme[:200])
    # Fix the oil: search for canola oil instead.
    page.select_option("#ri-food-3", "search")
    page.wait_for_selector("#ri-search-3")
    page.fill("#ri-search-3", "canola")
    page.locator("#ri-line-3 .row-btn").first.wait_for(timeout=10000)
    page.locator("#ri-line-3 .row-btn").first.click()
    check(f"[{p.tag}] the oil now reads canola oil", "Canola oil" in page.locator("#ri-food-3 option:checked").inner_text())
    check(f"[{p.tag}] its servings are worked out (1 tbsp)", page.input_value("#ri-sv-3") == "1", page.input_value("#ri-sv-3"))
    key = text_of(page, "#ri-key")
    check(f"[{p.tag}] one serving's numbers show", "K" in key or "Potassium" in key or "mg" in key, key[:200])
    p.shot("import-review", "#sheet-recipe-import")
    n = check_all_lines(page)
    check(f"[{p.tag}] with every line checked Save is on", n == 5 and not page.is_disabled("#recipe-import-go")
          and text_of(page, "#recipe-import-go") == "Save recipe")
    page.click("#recipe-import-go")
    wait_text(page, "#toast", "Saved")
    meals = api.json("GET", "/api/meals")["meals"]
    saved = next((m for m in meals if m["name"] == "Garlic chicken and rice"), None)
    check(f"[{p.tag}] the recipe is saved with its link, servings and steps", saved is not None
          and saved["source_url"] == "https://recipes.test/garlic-chicken" and saved["servings_made"] == 4
          and saved["steps"] == ["Cook the chicken and garlic in the oil.", "Serve over the rice."], json.dumps(saved)[:300])
    check(f"[{p.tag}] the fixed match and the left-out line", saved is not None
          and any(i["food_name"] == "Canola oil" for i in saved["items"]) and saved["note"] == "Not counted: 1 tsp dried thyme",
          json.dumps(saved)[:400] if saved else "")
    # ---- A link to a home address is refused -----------------------------------------------------------------------
    open_import(page)
    page.fill("#ri-url", "https://home.test/x")
    page.click("#ri-read-page")
    wait_text(page, "#toast", "does not open that address")
    check(f"[{p.tag}] a home address is refused", True)
    # The refusal the walk asked for (the 422 and the error the screen reports to the console).
    p.watch.errors[:] = [e for e in p.watch.errors if "status of 422" not in e and "does not open that address" not in e]
    page.click("#sheet-recipe-import [data-close]")
    # ---- Pasted ingredients ------------------------------------------------------------------------------------------
    open_import(page)
    page.fill("#ri-text", "For the rice:\n2 cups cooked white rice\n1 tbsp olive oil")
    page.fill("#ri-name", "Rice side")
    page.fill("#ri-makes", "2")
    page.click("#recipe-import-go")
    page.wait_for_selector("#ri-lines li", timeout=20000)
    check(f"[{p.tag}] pasted lines (the heading left out)", page.locator("#ri-lines > li").count() == 2)
    check(f"[{p.tag}] no link for pasted ingredients", not page.is_visible("#ri-source"))
    check_all_lines(page)
    page.click("#recipe-import-go")
    wait_text(page, "#toast", "Saved")
    rice = next((m for m in api.json("GET", "/api/meals")["meals"] if m["name"] == "Rice side"), None)
    check(f"[{p.tag}] the pasted recipe is saved", rice is not None and rice["servings_made"] == 2 and rice["source_url"] is None
          and len(rice["items"]) == 2, json.dumps(rice)[:300])
    p.no_overflow("import")
    # ---- Settings → Shopping list app ----------------------------------------------------------------------------------
    page.goto("/#settings")
    page.wait_for_selector("#set-lists:not([hidden]) #set-lists-url", timeout=30000)
    page.select_option("#set-lists-app", "grocy")
    page.fill("#set-lists-url", f"http://127.0.0.1:{grocy_port}")
    page.fill("#set-lists-key", KEY)
    page.click("#set-lists-save")
    wait_text(page, "#toast", "Saved")
    page.wait_for_selector("#set-lists-test-btn", timeout=10000)
    check(f"[{p.tag}] the key box is empty and says Saved", page.input_value("#set-lists-key") == ""
          and "Saved" in (page.get_attribute("#set-lists-key", "placeholder") or ""))
    page.click("#set-lists-test-btn")
    wait_text(page, "#toast", "It works")
    wait_text(page, "#set-lists-status", "Groceries")
    check(f"[{p.tag}] Test chose the one list", "List: Groceries" in text_of(page, "#set-lists-status"), text_of(page, "#set-lists-status"))
    check(f"[{p.tag}] the key was sent in Grocy's header", KEY in FakeGrocy.keys)
    check(f"[{p.tag}] the key is never in a response", KEY not in json.dumps(api.json("GET", "/api/list-sync")))
    p.shot("settings-lists", "#set-lists")
    p.no_overflow("settings")
    # ---- Plan → Send ---------------------------------------------------------------------------------------------------
    page.goto("/#plan")
    page.wait_for_selector("#shopping-send:not([hidden])", timeout=30000)
    check(f"[{p.tag}] Plan says Send to Grocy", text_of(page, "#shopping-send") == "Send to Grocy", text_of(page, "#shopping-send"))
    page.click("#shopping-send")
    page.wait_for_selector("#list-send-items li", timeout=15000)
    lines_text = [t.strip() for t in page.locator("#list-send-items .check-text").all_inner_texts()]
    check(f"[{p.tag}] the sheet shows the exact lines", len(lines_text) == 2 and all(": " in t and "serving" in t for t in lines_text),
          str(lines_text))
    check(f"[{p.tag}] it says nothing else is sent", "Nothing else about you is sent" in text_of(page, "#list-send-body"))
    page.locator("#list-send-items input[type=checkbox]").nth(1).uncheck()
    check(f"[{p.tag}] Send counts the ticked lines", text_of(page, "#list-send-go") == "Send 1 item")
    p.shot("send", "#sheet-list-send")
    page.click("#list-send-go")
    wait_text(page, "#toast", "Sent 1 item")
    check(f"[{p.tag}] Grocy got exactly the ticked line", FakeGrocy.added == [{"shopping_list_id": 1, "note": lines_text[0]}],
          json.dumps(FakeGrocy.added))
    p.no_overflow("plan")
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
    page.wait_for_selector("#btn-import-recipe", state="visible", timeout=30000)
    page.click("#btn-import-recipe")
    page.wait_for_selector("#sheet-recipe-import[open] #ri-url", timeout=15000)
    page.fill("#ri-url", "https://any.example/recipe")
    page.click("#ri-read-page")
    page.wait_for_selector("#ri-lines li", timeout=15000)
    check(f"[{p.tag}] the demo answers with its sample page", page.input_value("#ri-review-name") == "Lemon garlic chicken with rice")
    check_all_lines(page)
    page.click("#recipe-import-go")
    wait_text(page, "#toast", "Saved")
    wait_text(page, "#saved-meals", "Lemon garlic chicken with rice")
    check(f"[{p.tag}] the demo saved the recipe", True)
    page.goto("/?mock=1#settings")
    page.wait_for_selector("#set-lists:not([hidden])", timeout=30000)
    check(f"[{p.tag}] the demo shows a sample Grocy", "grocy.example" in text_of(page, "#set-lists")
          and "never contacts a list app" in text_of(page, "#set-lists"))
    page.goto("/?mock=1#plan")
    page.wait_for_selector("#shopping-send:not([hidden])", timeout=30000)
    page.click("#shopping-send")
    page.wait_for_selector("#list-send-items li", timeout=15000)
    page.click("#list-send-go")
    wait_text(page, "#toast", "Sent")
    check(f"[{p.tag}] the demo sends to its fake list app", True)
    check(f"[{p.tag}] the demo asked the network for none of the new routes",
          not any("/api/list-sync" in r or "/api/recipe-import" in r for r in p.watch.requests), str(p.watch.requests[-5:]))
    p.no_overflow("demo")
    p.finish()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    grocy_port = args.port + 1
    if khserver.port_in_use(args.port) or khserver.port_in_use(grocy_port):
        print(f"port {args.port} or {grocy_port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    grocy = ThreadingHTTPServer(("127.0.0.1", grocy_port), FakeGrocy)
    threading.Thread(target=grocy.serve_forever, daemon=True).start()
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook"),
           "LIST_SYNC_ENABLED": "true", "LIST_SYNC_ALLOWED_HOSTS": "127.0.0.1", "RECIPE_IMPORT_ENABLED": "true",
           "SHARING_ENABLED": "true"}  # the Care team on, as on a family server (Settings asks /api/shared, a 404 while off)
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env, app_spec="lists_recipes_app:app")
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
                walk_person(Pass(browser, server.base, out, 375, 812, "light", "person-375-light", admin.cookies()), admin, grocy_port)
                walk_demo(Pass(browser, server.base, out, 375, 812, "light", "demo-375-light"))
            finally:
                browser.close()
        check("the server log never holds the list key", KEY not in server.log())
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc(limit=3))
    finally:
        server.stop()
        grocy.shutdown()
    failed = any(not r["ok"] for r in RESULTS)
    (out / "report.json").write_text(json.dumps({"results": RESULTS, "failed": failed}, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in RESULTS)} passed, {sum(not r['ok'] for r in RESULTS)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
