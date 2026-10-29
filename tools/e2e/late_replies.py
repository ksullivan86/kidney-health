#!/usr/bin/env python3
"""Late replies walk: answers that come after the person moved on, made to happen in Chromium against a real server.

1. **Scan, then close.** A barcode lookup waits while Ana closes the Scan sheet. When the answer comes, no entry sheet opens.
2. **Search USDA twice.** Two searches wait; the newer answers first, then the older. Only the newer list is shown.
3. **Server administration, tapped twice.** The two-step check of the first load waits while the shield is tapped again.
   Each part of the page is there once.

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
from khserver import Server, first_admin
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
           "HANDBOOK_DIR": str(out / "no-handbook")}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        ana = first_admin(server, "ana")
        banana = ana.json("GET", "/api/foods", params={"q": "banana"})["foods"][0]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                ctx = browser.new_context(viewport={"width": 390, "height": 844}, base_url=server.base)
                ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in ana.cookies().items()])
                page = ctx.new_page()
                page.set_default_timeout(15000)
                for name, walk in (("Scan", lambda: walk_scan(page, banana)), ("USDA", lambda: walk_usda(page)),
                                   ("Admin", lambda: walk_admin(page))):
                    try:  # each step on its own, from a fresh page, so one bug does not hide the others
                        page.goto("/")
                        page.wait_for_selector("#view-today:not([hidden])")
                        walk()
                    except Exception:
                        check(f"{name}: the step ran to the end", False, traceback.format_exc(limit=2).splitlines()[-1])
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
