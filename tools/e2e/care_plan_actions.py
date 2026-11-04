#!/usr/bin/env python3
"""Care team Clear and an interrupted multi-batch plan, with a real server and Chromium.

    python3 tools/e2e/care_plan_actions.py --out /tmp/kh-care-actions

Clear must use its displayed dates after the fields change. A batch whose reply is lost after
the server saves it must not be resent. Runs at phone/light and desktop/dark sizes. No external service is called.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import khserver
from khserver import Server, first_admin, invite_user
from playwright.sync_api import sync_playwright


def walk(browser: Any, server: Server, owner: Any, helper: Any, share_id: int, out: Path, width: int, theme: str) -> int:
    first = (date.today() + timedelta(days=30 + (0 if width == 375 else 7))).isoformat()
    other = (date.fromisoformat(first) + timedelta(days=1)).isoformat()
    foods = owner.json("GET", "/api/foods", params={"q": "apple", "limit": 200})["foods"]
    food = next(f["id"] for f in foods if "raw" in f["name"].lower() and "hypo_treatment" not in f["flags"])
    for day in (first, other):
        owner.json("POST", "/api/log", {"date": day, "meal": "lunch", "food_id": food, "servings": 1, "status": "planned"})
    low = owner.json("GET", "/api/foods", params={"q": "glucose"})["foods"][0]["id"]
    owner.json("POST", "/api/log", {"date": first, "meal": "snack", "food_id": low, "servings": 1, "status": "planned"})
    ctx = browser.new_context(base_url=server.base, viewport={"width": width, "height": 850}, color_scheme=theme,
                              service_workers="block")
    ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in helper.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    count = 0
    try:
        page.goto("/#plan")
        page.wait_for_selector(f'#care-for-select option[value="{share_id}"]', state="attached")
        page.select_option("#care-for-select", str(share_id))
        page.wait_for_selector("#care-clear")
        page.fill("#care-clear-start", first)
        page.fill("#care-clear-end", first)
        page.click("#care-clear")
        page.fill("#care-clear-start", other)
        page.fill("#care-clear-end", other)
        with page.expect_response(lambda r: "/log/clear-planned" in r.url) as reply:
            page.get_by_role("button", name="Clear", exact=True).click()
        assert reply.value.status == 200
        left = owner.json("GET", "/api/log", params={"date": first})["entries"]
        assert len(left) == 1 and left[0]["purpose"] == "hypo"
        assert len(owner.json("GET", "/api/log", params={"date": other})["entries"]) == 1
        count += 2
        entries = [{"date": first, "meal": "dinner", "food_id": food, "servings": 1, "status": "planned"} for _ in range(65)]
        page.route("**/guidance/plan-days", lambda route: route.fulfill(json={"status": "ok", "days": [], "apply": {"entries": entries}}))
        batches: list[int] = []

        def batch(route: Any) -> None:
            response = route.fetch()  # the real server saves both batches
            batches.append(len(route.request.post_data_json["entries"]))
            if len(batches) == 2:
                route.abort("failed")  # the second success never reaches the browser
            else:
                route.fulfill(response=response)

        page.route("**/log/batch", batch)
        page.click("#care-plan-make")
        page.wait_for_selector("#care-plan-apply")
        page.click("#care-plan-apply")
        page.get_by_role("button", name="Review the plan", exact=True).wait_for()
        assert page.is_disabled("#care-plan-apply")
        assert batches == [40, 25]
        count += 2
        page.eval_on_selector("#care-plan-apply", "el => el.click()")
        stored = owner.json("GET", "/api/log", params={"date": first})["entries"]
        assert len([entry for entry in stored if entry["purpose"] != "hypo"]) == 65
        assert batches == [40, 25]
        count += 2
        page.screenshot(path=str(out / f"failed-batch-{width}-{theme}.png"))
        page.get_by_role("button", name="Review the plan", exact=True).click()
        page.wait_for_function("() => document.querySelector('#care-day').innerText.includes('Apple')")
        assert not page.is_visible("#care-plan-apply")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        count += 3
        print(f"PASS {width}px {theme}: confirmed dates, committed-but-lost reply, no duplicate, review the saved day", flush=True)
        return count
    finally:
        ctx.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8115)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "kh-care-actions")
    args = parser.parse_args()
    out = khserver.free_dir(args.out)
    with Server(args.port, out / "data", env={"SHARING_ENABLED": "true", "HANDBOOK_DIR": str(out / "no-handbook")}) as server:
        owner = first_admin(server, "owner")
        helper = invite_user(server, owner, "helper")
        invite = owner.json("POST", "/api/me/shares/invite", {"username": "helper", "role": "care_helper", "areas": ["food"]})
        joined = helper.json("POST", f"/api/shared/invites/{invite['id']}/accept")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                checks = sum(walk(browser, server, owner, helper, joined["id"], out, width, theme)
                             for width, theme in ((375, "light"), (1280, "dark")))
            finally:
                browser.close()
    (out / "report.json").write_text(json.dumps({"passed": checks}), encoding="utf-8")
    print(f"{checks} checks passed")


if __name__ == "__main__":
    main()
