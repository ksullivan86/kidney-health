#!/usr/bin/env python3
"""Menu-plan drafts survive late batch replies, at phone and desktop widths."""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright


def walk(browser: Any, server: Server, api: Any, out: Path, width: int, scheme: str) -> int:
    foods = [f for f in api.json("GET", "/api/foods/builtin")["foods"] if f["fdc_id"] > 0][:2]
    links = [f"#plan-menu?items=b{f['fdc_id']}x1" for f in foods]
    ctx = browser.new_context(base_url=server.base, viewport={"width": width, "height": 850}, color_scheme=scheme,
                              service_workers="block")
    ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in api.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    held: list[Any] = []
    checks = 0

    def check(ok: bool, message: str) -> None:
        nonlocal checks
        assert ok, message
        checks += 1

    def open_menu(link: str) -> None:
        page.evaluate("link => KH.menuPlan.openLink(link)", link)
        page.wait_for_selector("#sheet-menuplan[open]")

    def close() -> None:
        page.locator("#sheet-menuplan [data-close]").first.click()
        page.wait_for_selector("#sheet-menuplan", state="hidden")

    def wait_held() -> None:
        for _ in range(100):
            if held:
                return
            page.wait_for_timeout(50)
        raise AssertionError("batch request did not arrive")

    def hold(route: Any) -> None:
        held.append((route, route.fetch()))

    try:
        page.goto("/#plan")
        page.wait_for_function("() => !!(window.KH && KH.menuPlan && KH.state.me)")
        page.add_init_script("window.menuCsp=[]; document.addEventListener('securitypolicyviolation',e=>menuCsp.push(e.violatedDirective));")
        page.evaluate("() => { window.menuCsp=[]; document.addEventListener('securitypolicyviolation',e=>menuCsp.push(e.violatedDirective)); }")
        for index, outcome in enumerate(("success", "error")):
            target = (date.today() + timedelta(days=30 + index + (10 if width > 400 else 0))).isoformat()
            open_menu(links[0])
            page.fill("#menuplan-date", target)
            pattern = "**/api/log/batch"
            page.route(pattern, hold)
            page.click("#menuplan-save")
            wait_held()
            check(page.locator("#menuplan-date").is_disabled(), "submitted date freezes")
            check(page.locator("#menuplan-groups input").first.is_disabled(), "submitted choices freeze")
            check(page.locator("#menuplan-save").is_disabled(), "duplicate submit stops")
            close()
            open_menu(links[1])
            check(page.locator("#menuplan-date").is_enabled(), "new date stays editable")
            check(page.locator("#menuplan-groups input").first.is_enabled(), "new choices stay editable")
            check(page.locator("#menuplan-save").is_disabled(), "new save waits for old write")
            snapshot = page.evaluate("() => JSON.stringify(KH.menuPlan.state.rows)")
            page.evaluate("() => document.querySelector('#menuplan-form').requestSubmit()")
            page.wait_for_timeout(100)
            check(len(held) == 1, "reopened submit sends no second batch")
            route, response = held.pop()
            if outcome == "success":
                route.fulfill(response=response)
            else:
                # The server accepted the write, but the reply was lost: preserve the new draft
                # and say the earlier save failed rather than silently discarding its error.
                route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "Earlier reply lost"}))
            page.unroute(pattern, hold)
            page.wait_for_function("() => !KH.menuPlan.state.busy")
            check(page.locator("#sheet-menuplan").is_visible(), "late reply keeps new sheet open")
            check(page.evaluate("() => JSON.stringify(KH.menuPlan.state.rows)") == snapshot, "late reply keeps rows")
            check(page.locator("#menuplan-error").is_hidden(), "old error does not fill new sheet")
            check(page.locator("#menuplan-save").is_enabled(), "new draft can save after old reply")
            rows = api.json("GET", "/api/log", params={"date": target})["entries"]
            check(len(rows) == 1 and rows[0]["status"] == "planned", "one server write on submitted date")
            if outcome == "error":
                check("an earlier save did not go through" in page.locator("#toast").inner_text().lower(), "late failure is said")
            page.screenshot(path=str(out / f"{width}-{outcome}.png"))
            close()
        open_menu(links[0])
        page.click("#menuplan-save")
        page.wait_for_selector("#sheet-menuplan", state="hidden")
        check(page.evaluate("() => KH.state.view") == "plan", "current success still opens Plan")
        check(not page.evaluate("() => menuCsp.length"), "no CSP violation")
        check(not errors, f"no page error: {errors}")
        check(not page.evaluate("() => document.documentElement.scrollWidth > innerWidth + 1"), "no sideways scroll")
        return checks
    finally:
        ctx.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/tmp/kh-menu-late"))
    args = parser.parse_args()
    out = khserver.free_dir(args.out)
    server = Server(8104, out / "data", log_path=out / "server.log")
    try:
        server.start()
        api = first_admin(server, "menuaudit")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                checks = sum(walk(browser, server, api, out, width, theme) for width, theme in [(375, "light"), (1280, "dark")])
            finally:
                browser.close()
        (out / "report.json").write_text(json.dumps({"checks": checks, "passed": True}), encoding="utf-8")
        print(f"{checks} browser checks passed")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
