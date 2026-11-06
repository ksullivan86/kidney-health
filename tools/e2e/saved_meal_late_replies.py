#!/usr/bin/env python3
"""Saved-meal search and writes with delayed real replies, at phone and desktop sizes.

    python tools/e2e/saved_meal_late_replies.py --out /tmp/kh-saved-meal-late

Starts a fresh server. Holds local API replies after the real server completes them. No outside service is called.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright


def walk(browser: Any, server: Server, api: Any, out: Path, width: int, theme: str) -> int:
    day = date.today().isoformat()
    later = (date.today() + timedelta(days=5)).isoformat()
    food = next(f["id"] for f in api.json("GET", "/api/foods", params={"q": "apple"})["foods"] if "raw" in f["name"].lower())
    dinners_before = len([e for e in api.json("GET", "/api/log", params={"date": day})["entries"] if e["meal"] == "dinner"])
    meals = [api.json("POST", "/api/meals", {"name": f"Meal {width}-{i}", "items": [{"food_id": food, "servings": 1}]})
             for i in range(2)]
    api.json("POST", "/api/log", {"date": day, "meal": "lunch", "food_id": food, "servings": 1})
    ctx = browser.new_context(base_url=server.base, viewport={"width": width, "height": 850}, color_scheme=theme,
                              service_workers="block")
    ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in api.cookies().items()])
    page = ctx.new_page()
    held: list[tuple[Any, Any]] = []
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    checks = 0

    def hold(route: Any) -> None:
        held.append((route, route.fetch()))

    def wait_held() -> None:
        for _ in range(100):
            if held:
                return
            page.wait_for_timeout(50)
        raise AssertionError("the request was not issued")

    def release(method: str) -> None:
        before = page.evaluate("method => window.finishedApi[method] || 0", method)
        route, response = held.pop()
        route.fulfill(response=response)
        page.wait_for_function("([method, before]) => (window.finishedApi[method] || 0) > before", arg=[method, before])
        page.evaluate("async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }")

    def editor(index: int) -> None:
        page.evaluate("id => KH.views.plan.openMealEditor(KH.state.meals.find(t => t.id === id))", meals[index]["id"])
        page.wait_for_selector("#sheet-meal[open]")

    def close(sheet: str) -> None:
        page.locator(f"#sheet-{sheet} [data-close]").first.click()

    try:
        page.goto("/#plan")
        page.wait_for_selector("#saved-meals .saved-meal")
        page.evaluate("""() => {
          window.finishedApi = {};
          for (const method of ['foods', 'updateMeal', 'mealFromLog', 'applyMeal', 'copyDay']) {
            const original = KH.api[method];
            KH.api[method] = async (...args) => {
              try { return await original(...args); }
              finally { window.finishedApi[method] = (window.finishedApi[method] || 0) + 1; }
            };
          }
        }""")
        page.route("**/api/foods?*", hold)
        editor(0)
        page.fill("#meal-search", "banana")
        wait_held()
        close("meal")
        editor(1)
        page.fill("#meal-name", "Keep this new draft")
        release("foods")
        assert page.locator("#meal-search-results button").count() == 0
        assert page.input_value("#meal-name") == "Keep this new draft"
        checks += 2
        page.unroute("**/api/foods?*", hold)

        page.route(f"**/api/meals/{meals[1]['id']}", hold)
        page.fill("#meal-name", f"Saved once {width}")
        page.click("#meal-save")
        wait_held()
        assert page.is_disabled("#meal-name") and page.is_disabled("#meal-delete")
        close("meal")
        editor(0)
        page.fill("#meal-name", "Another draft stays open")
        assert page.is_disabled("#meal-save")
        release("updateMeal")
        page.wait_for_function("() => !document.querySelector('#meal-save').disabled")
        assert page.locator("#sheet-meal[open]").count() == 1
        assert page.input_value("#meal-name") == "Another draft stays open"
        assert api.json("GET", f"/api/meals/{meals[1]['id']}")["name"] == f"Saved once {width}"
        checks += 5
        close("meal")
        page.unroute(f"**/api/meals/{meals[1]['id']}", hold)

        page.route("**/api/meals/from-log", hold)
        page.evaluate("day => KH.views.plan.openSaveMealSheet(day, 'lunch', [])", day)
        page.fill("#savemeal-name", f"From lunch {width}")
        page.click("#savemeal-save")
        wait_held()
        assert page.is_disabled("#savemeal-name")
        close("savemeal")
        page.evaluate("day => KH.views.plan.openSaveMealSheet(day, 'dinner', [])", later)
        page.fill("#savemeal-name", "Future dinner draft")
        release("mealFromLog")
        assert page.locator("#sheet-savemeal[open]").count() == 1
        assert page.input_value("#savemeal-name") == "Future dinner draft"
        assert len([m for m in api.json("GET", "/api/meals")["meals"] if m["name"] == f"From lunch {width}"]) == 1
        checks += 4
        close("savemeal")
        page.unroute("**/api/meals/from-log", hold)

        page.route(f"**/api/meals/{meals[0]['id']}/apply", hold)
        page.evaluate("args => KH.views.plan.openApplySheet(args)", {"mealId": meals[0]["id"], "date": day, "meal": "dinner"})
        page.click("#apply-save")
        wait_held()
        assert page.is_disabled("#apply-date")
        close("apply")
        page.evaluate("args => KH.views.plan.openApplySheet(args)", {"mealId": meals[1]["id"], "date": later})
        page.wait_for_selector("#sheet-apply[open]")
        release("applyMeal")
        assert page.locator("#sheet-apply[open]").count() == 1
        assert page.input_value("#apply-date") == later
        assert len([e for e in api.json("GET", "/api/log", params={"date": day})["entries"] if e["meal"] == "dinner"]) == dinners_before + 1
        checks += 4
        close("apply")
        page.unroute(f"**/api/meals/{meals[0]['id']}/apply", hold)

        before = len(api.json("GET", "/api/log", params={"date": later})["entries"])
        page.evaluate("() => KH.router.show('today')")
        page.wait_for_selector("#view-today:not([hidden])")
        current_day = page.evaluate("KH.state.date")
        page.route("**/api/log/copy-day", hold)
        page.evaluate("args => KH.views.plan.openCopySheet(args)", {"from": day, "to": later})
        page.click("#copy-save")
        wait_held()
        created = held[0][1].json()["created"]
        assert page.is_disabled("#copy-from")
        close("copy")
        next_day = (date.today() + timedelta(days=6)).isoformat()
        page.evaluate("args => KH.views.plan.openCopySheet(args)", {"from": later, "to": next_day})
        release("copyDay")
        assert page.locator("#sheet-copy[open]").count() == 1
        assert page.input_value("#copy-to") == next_day
        assert page.evaluate("KH.state.date") == current_day
        assert len(api.json("GET", "/api/log", params={"date": later})["entries"]) == before + created
        checks += 5
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        checks += 2
        page.screenshot(path=str(out / f"saved-meals-{width}-{theme}.png"))
        print(f"PASS {width}px {theme}: old search, editor save, Save as meal, Apply and Copy day preserve new drafts", flush=True)
        return checks
    finally:
        ctx.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8116)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "kh-saved-meals")
    args = parser.parse_args()
    out = khserver.free_dir(args.out)
    with Server(args.port, out / "data", env={"HANDBOOK_DIR": str(out / "no-handbook")}) as server:
        api = first_admin(server, "owner")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                checks = sum(walk(browser, server, api, out, width, theme) for width, theme in ((375, "light"), (1280, "dark")))
            finally:
                browser.close()
    (out / "report.json").write_text(json.dumps({"passed": checks}), encoding="utf-8")
    print(f"{checks} checks passed")


if __name__ == "__main__":
    main()
