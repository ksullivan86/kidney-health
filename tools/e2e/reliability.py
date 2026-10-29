#!/usr/bin/env python3
"""Reliability walk (the 2026-10-29 audit): three bugs, each made to happen in Chromium against a real server, and the fix seen.

1. **Today after a failed load.** Ana has a banana today. She goes to yesterday while the server's answer for that day fails: the
   banana and today's totals must not stay under yesterday's heading. The page says the day could not be loaded and offers Retry;
   Retry then loads it.
2. **Unknown values in saved meals.** A saved meal of a food that lists no potassium or phosphorus shows "not listed", never
   "0 mg", and one where only some foods list a value shows "≥", on Plan and in the Add tab's shortcuts.
3. **A fitted recipe that makes 100 servings.** The fit answer is the server's own, changed to "fits as half a serving" (the case
   the audit found). Save must send a recipe the server accepts (at most 100 servings, one serving the size that fits), and the
   server answers 201.
4. **A slow day, then another.** The answer for the day before waits while Ana goes back to today; when it comes, today stays.
5. **A save that fails.** The entry sheet stays open with the amount typed and its button works again; the next try saves once.

    python3 tools/e2e/reliability.py            # a real server on 127.0.0.1:8097, Chromium; exit 1 on any failed check
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "reliability"
PORT = 8097
RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def text_of(page: Any, selector: str) -> str:
    return page.evaluate("(sel) => { const el = document.querySelector(sel); return el ? el.innerText.replace(/\\s+/g, ' ').trim() : ''; }", selector)


def wait_text(page: Any, selector: str, needle: str, timeout: int = 15000) -> None:
    page.wait_for_function("([sel, t]) => { const el = document.querySelector(sel); return !!el && el.innerText.includes(t); }",
                           arg=[selector, needle], timeout=timeout)


def walk_today(page: Any) -> None:
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    page.goto("/")
    wait_text(page, "#meals", "Banana")
    failing = f"**/api/log?date={yesterday}*"
    page.route(failing, lambda route: route.fulfill(status=500, content_type="application/json",
                                                    body=json.dumps({"detail": "The server had a problem."})))
    page.click("#date-prev")
    page.wait_for_selector("#day-unavailable", timeout=15000)
    meals = text_of(page, "#meals")
    check("Today: after a failed load, the other day's food is gone from the page", "Banana" not in meals, meals[:200])
    check("Today: the page says the day could not be loaded and offers Retry",
          "could not be loaded" in meals and page.is_visible("#day-retry"), meals[:200])
    check("Today: no totals or status bars are left from the other day",
          text_of(page, "#totals-all") == "" and text_of(page, "#status-bars") == "",
          text_of(page, "#totals-all")[:80] + " | " + text_of(page, "#status-bars")[:80])
    page.unroute(failing)
    page.click("#day-retry")
    page.wait_for_selector("#day-unavailable", state="detached", timeout=15000)
    check("Today: Retry loads the day", "could not be loaded" not in text_of(page, "#meals") and text_of(page, "#status-bars") != "")


def walk_slow_then_switch(page: Any) -> None:
    """A day that answers slowly must not replace the day the person switched to meanwhile."""
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    page.click("#tab-today")
    page.goto("/")
    wait_text(page, "#meals", "Banana")
    held: list[Any] = []
    slow = f"**/api/log?date={yesterday}*"
    page.route(slow, lambda route: held.append(route))  # the answer for yesterday waits until the check releases it
    page.click("#date-prev")
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    page.click("#date-next")
    wait_text(page, "#meals", "Banana")
    page.unroute(slow)
    for route in held:
        try:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"date": yesterday, "entries": [], "totals": {}, "targets": {}, "alerts": []}))
        except Exception:  # noqa: BLE001 - the page already gave up on it (the request was cancelled): also fine
            pass
    page.wait_for_timeout(800)
    check("Today: a slow answer for the day before does not replace the day shown now",
          "Banana" in text_of(page, "#meals") and not page.is_visible("#day-unavailable"), text_of(page, "#meals")[:160])


def walk_failed_save(page: Any) -> None:
    """A save that fails keeps the sheet open with what was typed, says why, and the next try saves once."""
    page.click("#tab-add")
    page.fill("#food-search", "apple")
    page.wait_for_selector("#food-results .row-btn")
    page.click("#food-results .row-btn >> text=/apple/i >> nth=0")
    page.wait_for_selector("#sheet-entry[open]")
    page.fill("#entry-servings", "2")
    failing = "**/api/log"
    page.route(failing, lambda route: route.fulfill(status=500, content_type="application/json",
                                                    body=json.dumps({"detail": "The server had a problem."}))
               if route.request.method == "POST" else route.continue_())
    page.click("#entry-save")
    page.wait_for_timeout(800)
    still_open = page.is_visible("#sheet-entry[open]")
    kept = page.input_value("#entry-servings") == "2"
    check("Add: a save that fails keeps the sheet open with the amount typed", still_open and kept,
          f"open={still_open} servings={page.input_value('#entry-servings') if still_open else '-'}")
    check("Add: the button can be pressed again after a failed save", page.is_enabled("#entry-save"))
    page.unroute(failing)
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" and urlsplit(r.url).path == "/api/log" else None)
    page.click("#entry-save")
    page.wait_for_selector("#sheet-entry", state="hidden")
    wait_text(page, "#meals", "Apple")
    check("Add: the second try saves the entry once", len(sent) == 1, str(sent))


def walk_saved_meals(page: Any) -> None:
    page.click("#tab-plan")
    wait_text(page, "#saved-meals", "Crackers only")
    rows = page.evaluate("() => [...document.querySelectorAll('#saved-meals .saved-meal')].map((li) => li.innerText.replace(/\\s+/g, ' '))")
    only = next((r for r in rows if "Crackers only" in r), "")
    mixed = next((r for r in rows if "Crackers and banana" in r), "")
    check("Plan: a saved meal whose food lists no potassium or phosphorus says 'not listed', never 0",
          "K not listed" in only and "not listed" in only.split("P", 1)[-1] and " 0 mg" not in only, only)
    check("Plan: a saved meal where only some foods list potassium shows '≥' and how many do not",
          "K ≥" in mixed and "(+ 1 not listed)" in mixed, mixed)
    page.click("#tab-add")
    page.wait_for_selector("#saved-shortcuts-list .meal-chip", timeout=15000)
    chips = text_of(page, "#saved-shortcuts-list")
    check("Add: the saved-meal shortcuts say 'not listed' and '≥' the same way", "K not listed" in chips and "K ≥" in chips, chips)


def walk_recipe(page: Any, recipe_id: int) -> None:
    def halve(route: Any) -> None:
        answer = route.fetch().json()
        fitted = answer.get("fitted") or {"items": [{"food_id": i["food_id"], "servings": i["servings"], "name": i.get("name", ""),
                                                      "portion_text": i.get("portion_text", "")} for i in (answer.get("closest") or {}).get("items", [])]}
        fitted["serving_fraction"] = 0.5
        answer.update(status="fits_smaller_serving", fitted=fitted, servings_made=100)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))

    page.route("**/api/guidance/fit-recipe", halve)
    sent: list[dict[str, Any]] = []
    answers: list[int] = []
    page.on("request", lambda r: sent.append(json.loads(r.post_data)) if r.method == "POST" and urlsplit(r.url).path == "/api/meals" else None)
    page.on("response", lambda r: answers.append(r.status) if r.request.method == "POST" and urlsplit(r.url).path == "/api/meals" else None)
    page.click("#tab-plan")
    wait_text(page, "#saved-meals", "Big pot")
    page.locator("#saved-meals .saved-meal", has_text="Big pot").get_by_role("button", name="Fit to my targets").click()
    page.wait_for_selector("#fit-save:not([hidden])", timeout=20000)
    page.click("#fit-save")
    page.wait_for_function("() => !document.querySelector('#sheet-fit[open]')", timeout=15000)
    body = sent[-1] if sent else {}
    check("Recipe: a fit as half a serving of a 100-serving recipe is saved as at most 100 servings",
          body.get("servings_made") == 100, json.dumps(body)[:300])
    check("Recipe: every food is halved, so one saved serving is the size that fits",
          [i["servings"] for i in body.get("items", [])] == [5.0], json.dumps(body.get("items")))
    check("Recipe: the server accepts it (201)", answers and answers[-1] == 201, str(answers))
    page.unroute("**/api/guidance/fit-recipe")


def walk_lab_cache(page: Any) -> None:
    """Deferred list/function replies reproduce a save invalidating an older read, without writes."""
    result = page.evaluate("""async () => {
      const api = KH.api;
      const saved = {labs: api.labs, kidneyFunction: api.kidneyFunction};
      const pending = [];
      const finish = (batch, marker) => {
        batch.list({labs: [{id: 1, analyte: 'potassium', value: 4.8, label: 'Potassium',
          display: marker, taken_on: '2026-10-29'}], alerts: []});
        batch.kf({message: marker + ' summary'});
      };
      try {
        api.labs = () => new Promise(resolve => pending.push({list: resolve}));
        api.kidneyFunction = () => new Promise(resolve => { pending[pending.length - 1].kf = resolve; });
        KH.labs.invalidate();
        const old = KH.labs.load();
        KH.labs.invalidate();
        const current = KH.labs.load();
        if (pending.length !== 2) {
          for (const batch of pending) finish(batch, 'Old result');
          await Promise.all([old, current]);
          return {calls: pending.length};
        }
        finish(pending[1], 'New result');
        const newest = await current;
        finish(pending[0], 'Old result');
        const redirected = await old;
        await KH.views.labs.refresh();
        return {calls: pending.length, newest: newest.labs[0].display, redirected: redirected.labs[0].display,
          history: document.querySelector('#labs-history').innerText,
          kidney: document.querySelector('#kf-body').innerText};
      } finally {
        Object.assign(api, saved);
        KH.labs.invalidate();
        await KH.views.labs.refresh();
      }
    }""")
    check("Lab cache: invalidation starts a fresh list/function read", result["calls"] == 2)
    check("Lab cache: a late pre-save reply converges on the new result",
          result.get("newest") == result.get("redirected") == "New result")
    check("Lab cache: history and kidney-function text keep the refreshed result",
          "New result" in result.get("history", "") and "Old result" not in result.get("history", "")
          and "New result summary" in result.get("kidney", ""))


def walk_shared_state_cache(page: Any) -> None:
    """Hold real core-helper reads across synthetic completed saves; no server write is made."""
    results = page.evaluate("""async () => {
      const results = [];
      for (const key of ['profile', 'meals']) {
        const method = KH.api[key], before = KH.state[key];
        let resolve;
        const load = key === 'profile' ? KH.loadProfile : KH.loadMeals;
        const saved = key === 'profile' ? {...before, cache_test: 'saved'} : [];
        try {
          KH.api[key] = () => new Promise(r => { resolve = r; });
          const pending = load(true);
          KH.state[key] = saved;
          resolve(key === 'profile' ? {...before} : {meals: before || []});
          const returned = await pending;
          results.push({key, keptSave: KH.state[key] === saved && returned === saved});
        } finally {
          KH.api[key] = method;
          KH.state[key] = before;
        }
      }
      KH.invalidateSharedCaches();
      await Promise.all([KH.loadProfile(), KH.loadMeals()]);
      return results;
    }""")
    for result in results:
        check(f"Shared cache: a late {result['key']} reply cannot undo a completed save", result["keptSave"])


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
        ana.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000}})
        banana = ana.json("GET", "/api/foods", params={"q": "banana"})["foods"][0]["id"]
        ana.json("POST", "/api/log", {"date": date.today().isoformat(), "meal": "breakfast", "food_id": banana, "servings": 1})
        crackers = ana.json("POST", "/api/foods", {"name": "Plain crackers (test)", "serving_desc": "5 crackers (30 g)", "serving_g": 30,
                                                   "nutrients": {"calories_kcal": 120, "carbs_g": 20, "sodium_mg": 180}})["id"]
        ana.json("POST", "/api/meals", {"name": "Crackers only", "items": [{"food_id": crackers, "servings": 1}]})
        ana.json("POST", "/api/meals", {"name": "Crackers and banana", "items": [{"food_id": crackers, "servings": 1}, {"food_id": banana, "servings": 1}]})
        recipe = ana.json("POST", "/api/meals", {"name": "Big pot", "items": [{"food_id": banana, "servings": 10}], "servings_made": 100})["id"]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                ctx = browser.new_context(viewport={"width": 390, "height": 844}, base_url=server.base)
                ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in ana.cookies().items()])
                page = ctx.new_page()
                page.set_default_timeout(15000)
                for name, walk in (("Today", lambda: walk_today(page)), ("Slow day", lambda: walk_slow_then_switch(page)),
                                   ("Failed save", lambda: walk_failed_save(page)), ("Lab cache", lambda: walk_lab_cache(page)),
                                   ("Shared cache", lambda: walk_shared_state_cache(page)), ("Saved meals", lambda: walk_saved_meals(page)),
                                   ("Recipe", lambda: walk_recipe(page, recipe))):
                    try:  # each step on its own, so one bug does not hide the others
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
