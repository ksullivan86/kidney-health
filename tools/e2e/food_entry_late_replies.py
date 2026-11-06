#!/usr/bin/env python3
"""Food-entry and Quick add drafts with held real replies at phone and desktop sizes.

    python tools/e2e/food_entry_late_replies.py --out /tmp/kh-entry-late

Starts a fresh local server. No outside service is used. Checks saves/deletes, current drafts,
single server writes, entry-control freezing and competing reads for the same entry object.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright


def walk(browser: Any, server: Server, api: Any, out: Path, width: int, theme: str) -> int:
    day = date.today().isoformat()
    nutrition = {"calories_kcal": 100, "potassium_mg": 20, "protein_g": 1}

    def make_food(name: str) -> dict[str, Any]:
        return api.json("POST", "/api/foods", {"name": name, "serving_desc": "1 serving", "serving_g": 100, "nutrients": nutrition})

    foods = [make_food(f"Entry audit {width}-{i}") for i in range(2)]
    ctx = browser.new_context(base_url=server.base, viewport={"width": width, "height": 850}, color_scheme=theme,
                              service_workers="block")
    ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in api.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    hosts: set[str] = set()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("request", lambda request: hosts.add(urlsplit(request.url).netloc) if request.url.startswith(("http:", "https:")) else None)
    page.add_init_script("window.entryCsp = []; document.addEventListener('securitypolicyviolation', e => window.entryCsp.push(e.violatedDirective));")
    held: list[Any] = []
    checks = 0

    def hold(route: Any) -> None:
        held.append((route, route.fetch()))

    def wait_held(count: int = 1) -> None:
        for _ in range(100):
            if len(held) >= count:
                return
            page.wait_for_timeout(50)
        raise AssertionError("the expected request was not sent")

    def open_entry(food: dict[str, Any] | None = None, entry: dict[str, Any] | None = None) -> None:
        page.evaluate("args => { KH.views.add.openEntrySheet(args.entry ? 'edit' : 'add', args); }", {"food": food, "entry": entry})
        page.wait_for_selector("#sheet-entry[open]")
        if entry:
            page.wait_for_function("() => !document.querySelector('#entry-grams-hint').textContent.includes('Loading')")

    def close(kind: str = "entry") -> None:
        page.locator(f"#sheet-{kind} [data-close]").first.click()

    def entries() -> list[dict[str, Any]]:
        return api.json("GET", "/api/log", params={"date": day})["entries"]

    try:
        page.goto("/#add")
        page.wait_for_function("() => !!(window.KH && KH.views && KH.views.add && KH.state.me)")
        page.evaluate("""() => {
          window.entryFinished = {};
          for (const name of ['addEntry', 'updateEntry', 'deleteEntry', 'deleteFood', 'quick', 'food']) {
            const original = KH.api[name];
            KH.api[name] = async (...args) => {
              try { return await original(...args); }
              finally { window.entryFinished[name] = (window.entryFinished[name] || 0) + 1; }
            };
          }
        }""")
        for action in ("add", "edit", "deleteEntry", "deleteFood"):
            row = None
            target = make_food(f"Delete target {width}") if action == "deleteFood" else foods[0]
            if action in ("edit", "deleteEntry"):
                row = api.json("POST", "/api/log", {"date": day, "meal": "lunch", "food_id": target["id"], "servings": 1})
            open_entry(entry=row) if row else open_entry(food=target)
            note = f"Earlier {action} {width}"
            if action in ("add", "edit"):
                page.fill("#entry-note", note)
            method = {"add": "POST", "edit": "PUT", "deleteEntry": "DELETE", "deleteFood": "DELETE"}[action]
            path = "/api/log" if action == "add" else f"/api/foods/{target['id']}" if action == "deleteFood" else f"/api/log/{row['id']}"
            pattern = f"**{path}"

            def hold_write(route: Any) -> None:
                if route.request.method == method:
                    hold(route)
                else:
                    route.continue_()

            page.route(pattern, hold_write)
            try:
                if action in ("add", "edit"):
                    page.click("#entry-save")
                else:
                    page.click("#entry-delete" if action == "deleteEntry" else "#entry-delete-food")
                    page.locator("#sheet-entry .confirm-row").get_by_role("button", name="Delete entry" if action == "deleteEntry" else "Delete food", exact=True).click()
                wait_held()
                assert page.is_disabled("#entry-note") and page.is_disabled("#entry-servings")
                assert page.locator("#sheet-entry [data-close]").first.is_enabled()
                checks += 2
                close()
                open_entry(food=foods[1])
                page.fill("#entry-note", "Keep this new entry draft")
                assert page.is_disabled("#entry-save") and not page.is_disabled("#entry-note")
                checks += 1
                route, response = held.pop()
                route.fulfill(response=response)
                page.wait_for_function("() => !document.querySelector('#entry-save').disabled")
                assert page.locator("#sheet-entry[open]").count() == 1
                assert page.input_value("#entry-note") == "Keep this new entry draft"
                assert page.evaluate("KH.state.view") == "add"
                checks += 3
                close()
                if action in ("add", "edit"):
                    saved = [item for item in entries() if item["note"] == note]
                    assert len(saved) == 1
                    api.json("DELETE", f"/api/log/{saved[0]['id']}")
                elif action == "deleteEntry":
                    assert all(item["id"] != row["id"] for item in entries())
                else:
                    assert api.call("GET", f"/api/foods/{target['id']}").status_code == 404
                checks += 1
            finally:
                page.unroute(pattern, hold_write)

        quick_name = f"Earlier Quick add {width}"
        page.evaluate("name => KH.views.add.openQuick({name})", quick_name)
        page.fill("#qn-calories_kcal", "100")
        page.route("**/api/log/quick", hold)
        page.click("#quick-save")
        wait_held()
        close("quick")
        page.evaluate("() => KH.views.add.openQuick({name: 'Keep this Quick draft'})")
        assert page.is_disabled("#quick-save")
        route, response = held.pop()
        route.fulfill(response=response)
        page.wait_for_function("() => !document.querySelector('#quick-save').disabled")
        assert page.locator("#sheet-quick[open]").count() == 1
        assert page.input_value("#q-name") == "Keep this Quick draft"
        assert page.evaluate("KH.state.view") == "add"
        assert len([item for item in entries() if item["food_name"] == quick_name]) == 1
        checks += 5
        close("quick")
        page.unroute("**/api/log/quick", hold)

        row = api.json("POST", "/api/log", {"date": day, "meal": "lunch", "food_id": foods[0]["id"], "servings": 1})
        page.evaluate("row => { window.sameAuditEntry = row; }", row)
        pattern = f"**/api/foods/{foods[0]['id']}"
        page.route(pattern, hold)
        page.evaluate("() => { KH.views.add.openEntrySheet('edit', {entry: window.sameAuditEntry}); }")
        wait_held()
        close()
        updated = api.json("PUT", f"/api/foods/{foods[0]['id']}", {"name": "Newest metadata", "serving_desc": "1 serving", "serving_g": 100, "nutrients": nutrition})
        page.evaluate("() => { KH.views.add.openEntrySheet('edit', {entry: window.sameAuditEntry}); }")
        wait_held(2)
        route, response = held.pop()
        route.fulfill(response=response)
        page.wait_for_function("() => document.querySelector('#sheet-entry-food').textContent.includes('Newest metadata')")
        before = page.evaluate("window.entryFinished.food || 0")
        route, response = held.pop()
        route.fulfill(response=response)
        page.wait_for_function("before => (window.entryFinished.food || 0) > before", arg=before)
        page.evaluate("async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }")
        assert updated["name"] == "Newest metadata"
        assert "Newest metadata" in page.inner_text("#sheet-entry-food")
        checks += 2
        close()
        page.unroute(pattern, hold)
        assert not errors, errors
        assert not page.evaluate("window.entryCsp"), "CSP violation"
        assert hosts == {urlsplit(server.base).netloc}, hosts
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "sideways scroll"
        checks += 4
        page.screenshot(path=str(out / f"entry-{width}-{theme}.png"))
        return checks
    finally:
        for route, _ in held:
            route.abort()
        ctx.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--port", type=int, default=8094)
    parser.add_argument("--out", type=Path, default=Path("/tmp/kh-entry-late"))
    args = parser.parse_args()
    out = khserver.free_dir(args.out)
    server = Server(args.port, out / "data", log_path=out / "server.log")
    try:
        server.start()
        api = first_admin(server, "entryaudit")
        api.json("PUT", "/api/profile", {"weight_kg": 70, "ckd_stage": "3b", "diabetes": "type1"})
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                counts = [walk(browser, server, api, out, width, theme) for width, theme in [(375, "light"), (1280, "dark")]]
            finally:
                browser.close()
        report = {"checks": sum(counts), "passed": True}
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"All {sum(counts)} food-entry browser checks passed")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
