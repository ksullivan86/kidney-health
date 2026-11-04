#!/usr/bin/env python3
"""Shopping previews and send completions after reopening, in Chromium at phone and desktop sizes.

    python3 tools/e2e/shopping_late_replies.py --out /tmp/kh-shopping-late

Starts a fresh real server and signs in. Playwright holds and answers the two integrations' preview/send routes, so no food
list goes to another service. Checks the actual request bodies, stale previews, late success, the send lock and retry.
The helpers open the real sheets directly with two date ranges. No personal data or service key is needed.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright


def walk(browser: Any, server: Server, cookies: dict[str, str], out: Path, width: int, theme: str) -> int:
    ctx = browser.new_context(base_url=server.base, viewport={"width": width, "height": 850}, color_scheme=theme,
                              service_workers="block")
    ctx.add_cookies([{"name": name, "value": value, "url": server.base} for name, value in cookies.items()])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    checks = 0
    try:
        for kind in ("instacart", "list-sync"):
            held: dict[str, list[Any]] = {"preview": [], "send": []}

            def hold(route: Any) -> None:
                held[route.request.url.rsplit("/", 1)[1]].append(route)

            page.route(f"**/api/{kind}/preview", hold)
            page.route(f"**/api/{kind}/send", hold)
            page.goto("/#plan")
            page.wait_for_function("() => window.KH && KH.instacart && KH.listSync && !document.querySelector('#view-plan').hidden")
            prefix = "instacart" if kind == "instacart" else "list-send"
            dialog = "sheet-instacart" if kind == "instacart" else "sheet-list-send"
            method = "KH.instacart.open" if kind == "instacart" else "KH.listSync.openSend"

            def opened(day: str) -> None:
                page.evaluate("([method, day]) => { const [_, view, fn] = method.split('.'); "
                              "KH[view][fn]({start: day, end: day, checks: new Set()}); }", [method, day])

            def wait_count(name: str, count: int) -> None:
                for _ in range(100):
                    if len(held[name]) >= count:
                        return
                    page.wait_for_timeout(50)
                raise AssertionError(f"{kind}: expected {count} {name} requests")

            def answer(route: Any, body: Any) -> None:
                with page.expect_response(lambda response: response.url == route.request.url):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
                page.evaluate("async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }")

            def preview(food_id: int, name: str) -> dict[str, Any]:
                return {"ready": True, "app_name": "Grocy", "list_name": "Weekly", "items": [
                    {"food_id": food_id, "name": name, "text": f"{name}: 1 serving", "amount": "1 serving"}]}

            opened("2026-11-02")
            wait_count("preview", 1)
            page.click(f"#{dialog} [data-close]")
            opened("2026-11-09")
            wait_count("preview", 2)
            answer(held["preview"][1], preview(2, "Apples"))
            page.wait_for_selector(f"#{prefix}-body input")
            answer(held["preview"][0], preview(1, "Rice"))
            assert "Apples" in page.inner_text(f"#{prefix}-body") and "Rice" not in page.inner_text(f"#{prefix}-body")
            checks += 1
            page.click(f"#{prefix}-go")
            wait_count("send", 1)
            assert held["send"][0].request.post_data_json == {"start": "2026-11-09", "end": "2026-11-09", "food_ids": [2]}
            checks += 1
            page.click(f"#{dialog} [data-close]")
            opened("2026-11-16")
            wait_count("preview", 3)
            answer(held["preview"][2], preview(3, "Pears"))
            page.wait_for_selector(f"#{prefix}-body input")
            page.locator(f"#{prefix}-body input").uncheck()
            page.locator(f"#{prefix}-body input").check()
            assert page.is_disabled(f"#{prefix}-go")
            checks += 1
            pages_before = len(ctx.pages)
            # Unexpected tabs stay local as well, so the regression never calls Instacart.
            ctx.route("https://www.instacart.com/**", lambda route: route.fulfill(status=200, body="fake page"))
            success = {"url": "https://www.instacart.com/list/old", "items": 1} if kind == "instacart" else {"sent": 1}
            answer(held["send"][0], success)
            page.wait_for_function("id => !document.getElementById(id).disabled", arg=f"{prefix}-go")
            assert page.locator(f"#{dialog}").evaluate("el => el.open")
            assert "Pears" in page.inner_text(f"#{prefix}-body")
            assert len(ctx.pages) == pages_before
            checks += 1
            page.screenshot(path=str(out / f"{kind}-{width}-{theme}.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            checks += 1
            page.click(f"#{prefix}-go")
            wait_count("send", 2)
            assert held["send"][1].request.post_data_json == {"start": "2026-11-16", "end": "2026-11-16", "food_ids": [3]}
            checks += 1
            answer(held["send"][1], {"error": "timeout", "message": "Try this send again.", "sent": 0})
            assert page.locator(f"#{dialog}").evaluate("el => el.open") and not page.is_disabled(f"#{prefix}-go")
            checks += 1
            page.click(f"#{dialog} [data-close]")
            page.unroute(f"**/api/{kind}/preview", hold)
            page.unroute(f"**/api/{kind}/send", hold)
            print(f"PASS {kind}, {width}px {theme}: stale preview, request bodies, lock, late send, retry, layout", flush=True)
        assert not errors, errors
        return checks + 1
    finally:
        ctx.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8113)
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "kh-shopping-late")
    args = ap.parse_args()
    out = khserver.free_dir(args.out)
    with Server(args.port, out / "data", log_path=out / "server.log", env={"SHARING_ENABLED": "true",
                "HANDBOOK_DIR": str(out / "no-handbook")}) as server:
        admin = first_admin(server, "shopping-tester")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                total = sum(walk(browser, server, admin.cookies(), out, width, theme)
                            for width, theme in ((375, "light"), (1280, "dark")))
            finally:
                browser.close()
    (out / "report.json").write_text(json.dumps({"passed": total}), encoding="utf-8")
    print(f"{total} checks passed; report {out / 'report.json'}")


if __name__ == "__main__":
    main()
