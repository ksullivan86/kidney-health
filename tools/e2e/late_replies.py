#!/usr/bin/env python3
"""Late replies walk: answers that come after the person moved on, made to happen in Chromium against a real server.

1. **Scan, then close.** A barcode lookup waits while Ana closes the Scan sheet. When the answer comes, no entry sheet opens.
2. **Search USDA twice.** Two searches wait; the newer answers first, then the older. Only the newer list is shown.
3. **Server administration, tapped twice.** The two-step check of the first load waits while the shield is tapped again.
   Each part of the page is there once.
4. **Add tab search fails.** After a search that worked, the next one gets a server error. The list says "Could not search"
   with Retry under the new search, and the old results are gone. Retry shows the answer.
5. **Signed-in devices.** Ana signs out two other devices quickly. The list for the first answers last, with both devices still
   in it (a slow server). The second device does not come back.
6. **Sharing.** Ana stops sharing with Bob, then makes a link before the list has loaded again. The two loads answer newest
   first. The new link is on the screen.

The answers are held with Playwright routes, so no USDA key or Open Food Facts is needed and nothing leaves the machine.

    python3 tools/e2e/late_replies.py            # a real server on 127.0.0.1:8098, Chromium; exit 1 on any failed check
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import khserver
from khserver import Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "late-replies"
PORT = 8098
RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def wait_for(page: Any, held: list[Any], n: int) -> None:
    for _ in range(100):
        if len(held) >= n:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected {n} held requests, got {len(held)}")


def answer(route: Any, body: Any, status: int = 200) -> None:
    try:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
    except Exception:  # noqa: BLE001 - the page gave up on the request: also fine
        pass


def walk_scan(page: Any, food: dict[str, Any]) -> None:
    page.click("#tab-add")
    page.click("#btn-scan")
    page.wait_for_selector("#sheet-scan[open]")
    held: list[Any] = []
    page.route("**/api/foods/barcode", lambda route: held.append(route))
    page.fill("#scan-code", "4006381333931")
    page.click("#scan-go")
    wait_for(page, held, 1)
    page.keyboard.press("Escape")
    page.wait_for_selector("#sheet-scan", state="hidden")
    answer(held[0], {"food": food})
    page.wait_for_timeout(800)
    check("Scan: a lookup that answers after the sheet was closed opens nothing", not page.is_visible("#sheet-entry[open]"))
    if page.is_visible("#sheet-entry[open]"):
        page.keyboard.press("Escape")
    page.unroute("**/api/foods/barcode")


def walk_usda(page: Any) -> None:
    page.click("#tab-add")
    held: list[Any] = []
    page.route("**/api/foods/usda/search*", lambda route: held.append(route))
    page.click("#btn-usda")
    page.wait_for_selector("#sheet-usda[open]")
    page.fill("#usda-q", "apple")
    page.click("#usda-go")
    page.fill("#usda-q", "apples raw")
    page.click("#usda-go")
    wait_for(page, held, 2)
    food = lambda i, name: {"fdc_id": 1000 + i, "description": name, "data_type": "Foundation", "brand": None, "category": "Fruits"}  # noqa: E731
    answer(held[1], {"foods": [food(1, "Apples, raw, with skin")]})
    page.wait_for_timeout(300)
    answer(held[0], {"foods": [food(2, "Apple pie"), food(3, "Apple juice")]})
    page.wait_for_timeout(800)
    rows = page.evaluate("() => [...document.querySelectorAll('#usda-results .row-title')].map((e) => e.innerText.trim())")
    check("USDA: two searches in flight show only the newer list", rows == ["Apples, raw, with skin"], json.dumps(rows))
    status = page.inner_text("#usda-status")
    check("USDA: the status line counts the newer list", status.startswith("1 results"), status)
    page.keyboard.press("Escape")
    page.unroute("**/api/foods/usda/search*")


def walk_admin(page: Any) -> None:
    page.click("#tab-today")
    held: list[Any] = []
    page.route("**/api/me/totp", lambda route: held.append(route))
    page.click("#admin-open")
    wait_for(page, held, 1)
    page.click("#admin-open")
    wait_for(page, held, 2)
    for route in held:
        answer(route, {"required": False, "enabled": False})
    page.wait_for_selector("#set-people .user-row", timeout=15000)
    page.wait_for_timeout(500)
    counts = page.evaluate("""() => Object.fromEntries(['set-people', 'set-server', 'set-shared', 'set-usage', 'set-audit',
      'set-server-about'].map((id) => [id, document.querySelectorAll('#' + id).length]))""")
    check("Admin: two overlapping loads show each part once", all(n == 1 for n in counts.values()), json.dumps(counts))
    page.unroute("**/api/me/totp")


def walk_search_failed(page: Any) -> None:
    page.click("#tab-add")
    page.fill("#food-search", "banana")
    page.press("#food-search", "Enter")
    page.wait_for_selector("#food-results .row-title")
    page.route("**/api/foods?*", lambda route: answer(route, {"detail": "The server had a problem"}, 500))
    page.fill("#food-search", "apple")
    page.press("#food-search", "Enter")
    page.wait_for_selector("#food-results button:has-text('Retry')")
    text = page.inner_text("#food-results")
    check("Search: a failed search says so in place of the old results",
          "Could not search" in text and "Banana" not in text and page.inner_text("#results-heading") == "Results for “apple”", text)
    page.unroute("**/api/foods?*")
    page.click("#food-results button:has-text('Retry')")
    page.wait_for_selector("#food-results .row-title")
    rows = page.evaluate("() => [...document.querySelectorAll('#food-results .row-title')].map((e) => e.innerText.trim())")
    check("Search: Retry shows the answer", rows and all("apple" in r.lower() for r in rows), json.dumps(rows[:5]))


def open_settings(page: Any, ready: str) -> None:
    page.click("#settings-open")
    page.wait_for_selector(ready, timeout=20000)
    page.locator(ready).first.scroll_into_view_if_needed()


def walk_devices(page: Any, stale: dict[str, Any]) -> None:
    open_settings(page, "#set-devices li")
    held: list[Any] = []
    page.route("**/api/me/sessions", lambda route: held.append(route) if route.request.method == "GET" else route.continue_())
    others = page.locator("#set-devices li:not(:has(.this-device)) button")
    others.nth(0).click()
    wait_for(page, held, 1)
    others.nth(1).click()
    wait_for(page, held, 2)
    held[1].continue_()  # the newer load: the real list, with only this device
    page.wait_for_function("() => document.querySelectorAll('#set-devices li').length === 1")
    answer(held[0], stale)  # the older load answers last, with the list from before both sign-outs
    page.wait_for_timeout(800)
    n = page.evaluate("() => document.querySelectorAll('#set-devices li').length")
    check("Devices: a slow older list does not bring back a signed-out device", n == 1, f"{n} devices shown")
    page.unroute("**/api/me/sessions")


def walk_sharing(page: Any) -> None:
    open_settings(page, "#set-sharing-list")
    held: list[Any] = []
    page.route("**/api/me/shares", lambda route: held.append(route) if route.request.method == "GET" else route.continue_())
    page.get_by_role("button", name="Stop sharing with bob").click()
    page.locator("#set-sharing-list").get_by_role("button", name="Stop sharing", exact=True).click()
    wait_for(page, held, 1)
    page.click("#set-sharing-make")
    wait_for(page, held, 2)
    held[1].continue_()  # the load after Make a link answers first
    page.wait_for_selector("#set-share-link")
    page.wait_for_timeout(300)
    held[0].continue_()  # then the load after Stop sharing
    page.wait_for_timeout(1000)
    link = page.input_value("#set-share-link") if page.is_visible("#set-share-link") else ""
    check("Sharing: Stop sharing, then Make a link at once keeps the new link on screen", "/#/share/" in link, link[:60])
    page.unroute("**/api/me/shares")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost",
           "HANDBOOK_DIR": str(out / "no-handbook"), "SHARING_ENABLED": "true"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        ana = first_admin(server, "ana")
        banana = ana.json("GET", "/api/foods", params={"q": "banana"})["foods"][0]
        for _ in range(2):  # two more devices for the Signed-in devices step
            khserver.Api(server.base).login("ana")
        stale = ana.json("GET", "/api/me/sessions")
        bo = invite_user(server, ana, "bob")
        made = ana.json("POST", "/api/me/shares", {"areas": ["food"], "days": None})
        bo.json("POST", "/api/shared/accept", {"code": made["link"].rsplit("/", 1)[-1]})
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                ctx = browser.new_context(viewport={"width": 390, "height": 844}, base_url=server.base)
                ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in ana.cookies().items()])
                page = ctx.new_page()
                page.set_default_timeout(15000)
                for name, walk in (("Scan", lambda: walk_scan(page, banana)), ("USDA", lambda: walk_usda(page)),
                                   ("Admin", lambda: walk_admin(page)), ("Search", lambda: walk_search_failed(page)),
                                   ("Devices", lambda: walk_devices(page, stale)), ("Sharing", lambda: walk_sharing(page))):
                    try:  # each step on its own, from a fresh page, so one bug does not hide the others
                        page.goto("/")
                        page.wait_for_selector("#view-today:not([hidden])")
                        walk()
                    except Exception:
                        traceback.print_exc(limit=2)
                        check(f"{name}: the step ran to the end", False, traceback.format_exc(limit=2).strip().splitlines()[-1])
                        page.unroute_all()
                        page.goto("/")
                ctx.close()
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc(limit=3))
    finally:
        server.stop()
    failed = [r for r in RESULTS if not r["ok"]]
    (out / "report.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}")
    return 1 if failed or not RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
