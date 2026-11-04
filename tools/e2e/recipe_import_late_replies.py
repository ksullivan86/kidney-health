#!/usr/bin/env python3
"""Recipe import with delayed real parse, search and save responses, at phone and desktop sizes.

    python3 tools/e2e/recipe_import_late_replies.py --out /tmp/kh-recipe-import-late

Runs a fresh real server. Playwright fetches local API responses and holds their delivery. No recipe site or AI is called.
Checks a parse after reopening, independent ingredient searches, a real save after reopening, callback ownership, and layout.
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


def walk(browser: Any, server: Server, api: Any, out: Path, width: int, theme: str) -> int:
    ctx = browser.new_context(base_url=server.base, viewport={"width": width, "height": 850}, color_scheme=theme,
                              service_workers="block")
    ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in api.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    checks = 0
    held: list[tuple[Any, Any]] = []

    def hold(route: Any) -> None:
        held.append((route, route.fetch()))

    def wait_count(n: int) -> None:
        for _ in range(100):
            if len(held) >= n:
                return
            page.wait_for_timeout(50)
        raise AssertionError(f"expected {n} held requests, got {len(held)}")

    def release(index: int) -> None:
        route, response = held[index]
        with page.expect_response(lambda value: value.url == route.request.url):
            route.fulfill(response=response)
        page.evaluate("async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }")

    def opened(label: str) -> None:
        page.evaluate("label => KH.recipeImportView.open({onSaved: meal => { window.savedImports ||= []; "
                      "window.savedImports.push({label, name: meal.name}); }})", label)
        page.wait_for_selector("#ri-text")

    def read(name: str) -> None:
        page.fill("#ri-text", "2 cups cooked rice\n1 tbsp olive oil")
        page.fill("#ri-name", name)
        page.click("#recipe-import-go")

    try:
        page.goto("/#plan")
        page.wait_for_function("() => window.KH && KH.recipeImportView && !document.querySelector('#view-plan').hidden")
        page.route("**/api/recipe-import/text", hold)
        opened("old-parse")
        read("Old recipe")
        wait_count(1)
        page.click("#sheet-recipe-import [data-close]")
        opened("new-parse")
        page.fill("#ri-text", "Keep these new ingredients")
        release(0)
        assert page.input_value("#ri-text") == "Keep these new ingredients"
        checks += 1
        read("Recipe for searches")
        wait_count(2)
        release(1)
        page.wait_for_selector("#ri-lines input[type=checkbox]")
        page.unroute("**/api/recipe-import/text", hold)
        assert page.input_value("#ri-review-name") == "Recipe for searches"
        checks += 1

        held.clear()
        page.route("**/api/foods?*", hold)
        for index, word in enumerate(("rice", "chicken")):
            page.select_option(f"#ri-food-{index}", "search")
            page.fill(f"#ri-search-{index}", word)
            wait_count(index + 1)
        release(1)
        release(0)
        for index in (0, 1):
            rows = page.locator(f"#ri-line-{index} .ri-search button")
            rows.first.wait_for(state="visible")
            assert rows.count() > 0
            rows.first.click()
            page.fill(f"#ri-sv-{index}", "1")
            page.check(f"#ri-ok-{index}")
            checks += 1
        page.unroute("**/api/foods?*", hold)

        held.clear()
        name = f"Saved recipe {width} {theme}"
        page.fill("#ri-review-name", name)
        page.route("**/api/meals", hold)
        page.click("#recipe-import-go")
        wait_count(1)
        assert page.is_disabled("#ri-review-name") and page.is_disabled("#recipe-import-go")
        checks += 1
        assert page.is_disabled("#recipe-import-back")
        checks += 1
        page.click("#sheet-recipe-import [data-close]")
        opened("new-save")
        page.fill("#ri-text", "Keep this typing after the old save")
        release(0)
        page.wait_for_function("() => (window.savedImports || []).length === 1")
        assert page.locator("#sheet-recipe-import").evaluate("el => el.open")
        assert page.input_value("#ri-text") == "Keep this typing after the old save"
        checks += 1
        assert page.evaluate("window.savedImports") == [{"label": "new-parse", "name": name}]
        checks += 1
        meals = api.json("GET", "/api/meals")["meals"]
        assert sum(meal["name"] == name for meal in meals) == 1
        checks += 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        checks += 1
        page.screenshot(path=str(out / f"reopened-{width}-{theme}.png"))
        page.click("#sheet-recipe-import [data-close]")
        print(f"PASS {width}px {theme}: old parse, independent searches, old save, original callback, saved once, layout", flush=True)
        return checks
    finally:
        ctx.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8114)
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "kh-recipe-import-late")
    args = ap.parse_args()
    out = khserver.free_dir(args.out)
    with Server(args.port, out / "data", log_path=out / "server.log", env={"SHARING_ENABLED": "true",
                "HANDBOOK_DIR": str(out / "no-handbook")}) as server:
        admin = first_admin(server, "recipe-tester")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                total = sum(walk(browser, server, admin, out, width, theme)
                            for width, theme in ((375, "light"), (1280, "dark")))
            finally:
                browser.close()
    (out / "report.json").write_text(json.dumps({"passed": total}), encoding="utf-8")
    print(f"{total} checks passed; report {out / 'report.json'}")


if __name__ == "__main__":
    main()
