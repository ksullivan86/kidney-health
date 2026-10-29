#!/usr/bin/env python3
"""Reliability walk (the 2026-10-29 audit and ROADMAP item 1): each bug made to happen in Chromium against a real server, and the fix seen.

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
6. **Recipe fit data gaps.** Missing potassium says "not listed", partial potassium says "≥", and known zero still says 0 mg.
7. **The other screens that save.** The same failed save on Plan's saved meal editor and "Add to a day", Labs, Profile, and the
   weight and blood pressure sheets: the sheet stays open, what was typed is kept, the error is on top (a toast under an open
   sheet is not seen; `error_in_view` checks with elementFromPoint), the button works again, and the next try saves once.
8. **Slow lists.** Labs answers late (old results, then an error) while Ana goes to Today and back; "Lab cache" holds a read
   across a save in the page itself. The weight card's day before answers late while Ana goes back to today. Neither old answer
   is drawn, and the weight card says "Loading…" while a day loads, never the other day's weights.

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
    seen = error_in_view(page)
    check("Add: the error is shown where it can be seen, not under the sheet", seen == "ok", seen)
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


def walk_meal_editor(page: Any) -> None:
    page.click("#tab-plan")
    wait_text(page, "#saved-meals", "Crackers only")
    for name, expected in (("Crackers only", "not listed"), ("Crackers and banana", "≥")):
        page.locator("#saved-meals .saved-meal", has_text=name).get_by_role("button", name="Edit", exact=True).click()
        amount = page.locator('#meal-preview-key .kn[aria-label^="Potassium:"] .kn-v').inner_text()
        check(f"Meal editor: {name} shows {expected} for potassium", expected in amount, amount)
        check(f"Meal editor: {name} fits the phone sheet without sideways scrolling",
              page.evaluate("() => { const sheet = document.querySelector('#sheet-meal'); return sheet.scrollWidth <= sheet.clientWidth + 1; }"))
        page.evaluate("() => document.querySelector('#sheet-meal').close()")
    page.locator("#saved-meals .saved-meal", has_text="Crackers and banana").get_by_role("button", name="Edit", exact=True).click()
    potassium = page.locator('#meal-preview-key .kn[aria-label^="Potassium:"] .kn-v')
    before = float(potassium.inner_text().replace("≥", "").replace(",", "").strip())
    page.fill("#meal-makes", "4")
    divided = potassium.inner_text()
    check("Meal editor: Makes divides the known amount and keeps the partial marker",
          divided.startswith("≥") and 0 < float(divided.replace("≥", "").replace(",", "").strip()) < before, divided)
    page.fill("#meal-note", "Keep this note for retry")
    pattern = "**/api/meals/*"
    page.route(pattern, lambda route: route.fulfill(status=500, content_type="application/json",
                                                   body=json.dumps({"detail": "Test save failure"})))
    with page.expect_response(lambda response: response.request.method == "PUT" and "/api/meals/" in response.url):
        page.click("#meal-save")
    page.wait_for_function("() => !document.querySelector('#meal-save').disabled")
    check("Meal editor: a failed save keeps the sheet, note and Makes for retry",
          page.is_visible("#sheet-meal") and page.input_value("#meal-note") == "Keep this note for retry" and page.input_value("#meal-makes") == "4")
    page.unroute(pattern)
    unchanged = page.evaluate("async () => (await KH.api.meals()).meals.find(meal => meal.name === 'Crackers and banana')")
    check("Meal editor: the failed save did not change the stored meal", unchanged.get("note") != "Keep this note for retry")
    with page.expect_response(lambda response: response.request.method == "PUT" and "/api/meals/" in response.url):
        page.click("#meal-save")
    page.wait_for_selector("#sheet-meal", state="hidden")
    saved = page.evaluate("async () => (await KH.api.meals()).meals.filter(meal => meal.name === 'Crackers and banana')")
    check("Meal editor: retry saves the preserved fields to the same meal once",
          len(saved) == 1 and saved[0].get("note") == "Keep this note for retry" and saved[0].get("servings_made") == 4)


def walk_fit_unknown(page: Any) -> None:
    page.click("#tab-plan")
    wait_text(page, "#saved-meals", "Known zero")
    for name, expected in (("Crackers only", "Potassium not listed"), ("Crackers and banana", "Potassium ≥"),
                           ("Known zero", "Potassium 0 mg")):
        page.locator("#saved-meals .saved-meal", has_text=name).get_by_role("button", name="Fit to my targets").click()
        page.wait_for_selector("#fit-result .fit-checks")
        rows = page.locator("#fit-result .fit-checks li").all_inner_texts()
        potassium = next((" ".join(row.split()) for row in rows if row.startswith("Potassium")), "")
        check(f"Fit: {name} shows {expected}", expected in potassium, potassium)
        page.evaluate("() => document.querySelector('#sheet-fit').close()")


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
    wait_text(page, "#saved-meals", "Big pot (fitted)")
    walk_fit_context(page, recipe_id)
    page.unroute("**/api/guidance/fit-recipe")


def walk_fit_context(page: Any, recipe_id: int) -> None:
    """A's delayed Replace must never expose its old body as Undo on B; verify B on the server."""
    before_b = page.evaluate("async () => (await KH.api.meals()).meals.find(meal => meal.name === 'Crackers only')")
    page.evaluate("""() => {
      window.originalFitLoadMeals = KH.loadMeals;
      window.fitCacheLoads = 0;
      KH.loadMeals = async (...args) => { const result = await window.originalFitLoadMeals(...args); window.fitCacheLoads++; return result; };
    }""")
    held: list[Any] = []
    pattern = f"**/api/meals/{recipe_id}"
    page.route(pattern, lambda route: held.append(route))

    def open_recipe(name: str) -> None:
        page.evaluate("(name) => KH.views.plan.openFitSheet(KH.state.meals.find(meal => meal.name === name), null)", name)
        page.wait_for_selector("#fit-replace:not([hidden])")

    def replace() -> None:
        page.click("#fit-replace")
        page.locator("#sheet-fit .confirm-row").get_by_role("button", name="Replace", exact=True).click()

    try:
        open_recipe("Big pot")
        replace()
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        if not held:
            raise AssertionError("the Replace request was not held")
        page.evaluate("() => document.querySelector('#sheet-fit').close()")
        open_recipe("Crackers only")
        held.pop().continue_()
        page.wait_for_function("() => window.fitCacheLoads === 1")
        check("Recipe race: the old Replace cannot attach A's Undo to B",
              page.locator("#fit-result").get_by_role("button", name="Undo", exact=True).count() == 0)
        check("Recipe race: B's Fit sheet remains open after A's write",
              page.is_visible("#sheet-fit") and "Crackers only" in text_of(page, "#sheet-fit-sub"))
        after_b = page.evaluate("async () => (await KH.api.meals()).meals.find(meal => meal.name === 'Crackers only')")
        check("Recipe race: B's stored recipe is unchanged", after_b == before_b)
        page.unroute(pattern)
        page.evaluate("() => document.querySelector('#sheet-fit').close()")
        before_undo = page.evaluate("async (id) => (await KH.api.meals()).meals.find(meal => meal.id === id)", recipe_id)
        open_recipe("Big pot")
        replace()
        page.wait_for_function("() => window.fitCacheLoads === 2")
        check("Recipe: an unchanged result still offers Undo after Replace",
              page.locator("#fit-result").get_by_role("button", name="Undo", exact=True).is_visible())
        page.locator("#fit-result").get_by_role("button", name="Undo", exact=True).click()
        page.wait_for_function("() => window.fitCacheLoads === 3")
        restored = page.evaluate("async (id) => (await KH.api.meals()).meals.find(meal => meal.id === id)", recipe_id)
        check("Recipe: Undo restores that recipe's original foods and serving count",
              restored["items"] == before_undo["items"] and restored["servings_made"] == before_undo["servings_made"])
    finally:
        page.unroute(pattern)
        for route in held:
            route.abort()
        page.evaluate("() => { KH.loadMeals = window.originalFitLoadMeals; document.querySelector('#sheet-fit').close(); }")


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


# ---- the other screens that save: a failed save, then the next try ----------------------------------------------------------
SERVER_PROBLEM = "The server had a problem."


def fail_500(page: Any, path: str, method: str = "POST") -> Any:
    """Answers 500 to `method` on `path` (any query string); everything else goes to the server. Returns what to unroute."""
    def matches(url: str) -> bool:
        return urlsplit(url).path == path

    page.route(matches, lambda route: route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": SERVER_PROBLEM}))
               if route.request.method == method else route.continue_())
    return matches


def error_in_view(page: Any) -> str:
    """'ok' when the server's error is on screen and on top: a toast under an open sheet (the top layer) is not seen."""
    return page.evaluate("""(needle) => {
      const inline = [...document.querySelectorAll('dialog[open] [role=alert], dialog[open] .form-error, .view:not([hidden]) [role=alert]')]
        .find((el) => el.offsetParent !== null && el.innerText.includes(needle));
      if (inline) return 'ok';
      const t = document.getElementById('toast');
      if (!t || !t.classList.contains('show') || !t.textContent.includes(needle)) return `no error shown (toast: "${t ? t.textContent : ''}")`;
      const r = t.getBoundingClientRect();
      const was = t.style.pointerEvents;
      t.style.pointerEvents = 'auto';  // the toast never takes a tap; for this look only
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      t.style.pointerEvents = was;
      return top && t.contains(top) ? 'ok' : `the toast is hidden under ${top ? (top.id ? '#' + top.id : top.tagName.toLowerCase()) : 'nothing'}`;
    }""", SERVER_PROBLEM)


def after_failed_save(page: Any, screen: str, button: str, fields: dict[str, str], sheet: str | None = None) -> None:
    page.wait_for_function("(sel) => { const b = document.querySelector(sel); return !!b && !b.disabled; }", arg=button)
    page.wait_for_timeout(300)
    if sheet:
        check(f"{screen}: a save that fails keeps the sheet open", page.is_visible(f"{sheet}[open]"))
    got = {sel: page.input_value(sel) for sel in fields}
    check(f"{screen}: what was typed is kept", got == fields, json.dumps(got))
    seen = error_in_view(page)
    check(f"{screen}: a plain error is shown where it can be seen", seen == "ok", seen)
    check(f"{screen}: the button works again", page.is_enabled(button))


def next_try_saves_once(page: Any, screen: str, button: str, path: str, done: Any, method: str = "POST") -> None:
    sent: list[str] = []

    def note(r: Any) -> None:
        if r.method == method and urlsplit(r.url).path == path:
            sent.append(r.url)

    page.on("request", note)
    page.click(button)
    done()
    page.wait_for_timeout(500)
    page.remove_listener("request", note)
    check(f"{screen}: the next try saves once", len(sent) == 1, str(sent))


def walk_plan_editor(page: Any) -> None:
    """Plan → New saved meal: a save that fails keeps the name, note and foods."""
    page.click("#tab-plan")
    wait_text(page, "#saved-meals", "Crackers only")
    page.click("#btn-new-meal")
    page.wait_for_selector("#sheet-meal[open]")
    page.fill("#meal-name", "Lunch bowl (test)")
    page.fill("#meal-note", "with lime")
    page.fill("#meal-search", "banana")
    page.wait_for_selector("#meal-search-results .row-btn")
    page.click("#meal-search-results .row-btn >> nth=0")
    page.fill("#meal-items input", "2")
    failing = fail_500(page, "/api/meals")
    page.click("#meal-save")
    after_failed_save(page, "Plan, saved meal editor", "#meal-save",
                      {"#meal-name": "Lunch bowl (test)", "#meal-note": "with lime", "#meal-items input": "2"}, sheet="#sheet-meal")
    page.unroute(failing)

    def saved() -> None:
        page.wait_for_selector("#sheet-meal", state="hidden")
        wait_text(page, "#saved-meals", "Lunch bowl (test)")

    next_try_saves_once(page, "Plan, saved meal editor", "#meal-save", "/api/meals", saved)
    meals = [m for m in page.request.get("/api/meals").json()["meals"] if m["name"] == "Lunch bowl (test)"]
    check("Plan, saved meal editor: the server has the meal once, with 2 servings",
          len(meals) == 1 and [i["servings"] for i in meals[0]["items"]] == [2], json.dumps(meals)[:300])


def walk_plan_apply(page: Any, meal_id: int, food_id: int) -> None:
    """Plan → a saved meal → Add to a day: a failed save keeps the date and the scale."""
    today = date.today().isoformat()
    page.click("#tab-plan")
    wait_text(page, "#saved-meals", "Crackers only")
    page.locator("#saved-meals .saved-meal", has_text="Crackers only").get_by_role("button", name="Add to a day").click()
    page.wait_for_selector("#sheet-apply[open]")
    page.fill("#apply-date", today)
    page.fill("#apply-scale", "2")
    path = f"/api/meals/{meal_id}/apply"
    failing = fail_500(page, path)
    page.click("#apply-save")
    after_failed_save(page, "Plan, Add a saved meal", "#apply-save", {"#apply-date": today, "#apply-scale": "2"}, sheet="#sheet-apply")
    page.unroute(failing)
    next_try_saves_once(page, "Plan, Add a saved meal", "#apply-save", path, lambda: page.wait_for_selector("#sheet-apply", state="hidden"))
    entries = [e for e in page.request.get(f"/api/log?date={today}").json()["entries"] if e["food_id"] == food_id]
    check("Plan, Add a saved meal: the day has the food once, twice the amount",
          [e["servings"] for e in entries] == [2], json.dumps(entries)[:300])


def walk_labs_save(page: Any) -> None:
    """Labs → Add a result: a failed save keeps the test, the value and the note."""
    page.click("#tab-profile")
    page.click("#pf-open-labs")
    page.wait_for_selector("#lab-unit option", state="attached")
    page.select_option("#lab-analyte", "potassium")
    page.fill("#lab-value", "4.6")
    page.fill("#lab-note", "after lunch")
    failing = fail_500(page, "/api/labs")
    page.click("#lab-save")
    after_failed_save(page, "Labs", "#lab-save", {"#lab-analyte": "potassium", "#lab-value": "4.6", "#lab-note": "after lunch"})
    page.unroute(failing)
    next_try_saves_once(page, "Labs", "#lab-save", "/api/labs", lambda: wait_text(page, "#labs-history", "4.6"))
    rows = [r for r in page.request.get("/api/labs").json()["labs"] if r["analyte"] == "potassium"]
    check("Labs: the server has the result once", len(rows) == 1, json.dumps(rows)[:300])


def walk_labs_slow(page: Any) -> None:
    """The list of results answers slowly; the person goes to Today and comes back. The old answer, late, is never drawn."""
    for late in ("old results", "an error"):
        page.click("#tab-profile")
        page.wait_for_selector("#pf-open-labs")
        held: list[Any] = []

        def is_list(url: str) -> bool:
            return urlsplit(url).path == "/api/labs"

        def hold_first(route: Any) -> None:
            if route.request.method == "GET" and not held:
                held.append(route)
            else:
                route.continue_()

        page.route(is_list, hold_first)
        page.click("#pf-open-labs")
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        page.click("#tab-today")
        page.wait_for_timeout(300)
        page.click("#tab-profile")
        with page.expect_response(lambda r: urlsplit(r.url).path == "/api/me/settings"):
            page.click("#pf-open-labs")  # Labs asks for the unit setting, then for the list
        page.wait_for_timeout(500)  # so the old answer comes after this visit asked for the list
        for route in held:
            if late == "old results":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"labs": [], "alerts": []}))
            else:
                route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": SERVER_PROBLEM}))
        page.wait_for_timeout(800)
        page.unroute(is_list)
        shown = text_of(page, "#labs-history")
        check(f"Labs: a slow answer from before ({late}) is not drawn over the results shown now",
              held and "4.1" in shown and "could not be loaded" not in shown and "No results yet" not in shown, shown[:160])


def walk_profile(page: Any) -> None:
    """Profile → Save profile with new targets: a failed save keeps the numbers typed."""
    page.click("#tab-profile")
    page.wait_for_function("() => document.querySelector('#tg-potassium_mg').value === '2500'")
    page.wait_for_timeout(300)
    page.fill("#tg-potassium_mg", "2200")
    page.fill("#tg-phosphorus_mg", "900")
    failing = fail_500(page, "/api/profile", method="PUT")
    page.click("#btn-save-profile")
    after_failed_save(page, "Profile", "#btn-save-profile", {"#tg-potassium_mg": "2200", "#tg-phosphorus_mg": "900"})
    page.unroute(failing)
    next_try_saves_once(page, "Profile", "#btn-save-profile", "/api/profile", lambda: wait_text(page, "#toast", "Profile saved"), method="PUT")
    targets = page.request.get("/api/profile").json()["targets"]
    check("Profile: the server has the new targets", targets.get("potassium_mg") == 2200 and targets.get("phosphorus_mg") == 900,
          json.dumps(targets)[:200])


def walk_body_save(page: Any) -> None:
    """Today → Add weight and Add blood pressure: a failed save keeps the numbers and the note."""
    page.goto("/")
    wait_text(page, "#meals", "Banana")
    wait_text(page, "#body-today-body", "158.7")
    for screen, add, sheet, typed, save, path, shows in (
            ("Weight", "#body-add-weight", "#sheet-weight", {"#weight-value": "154.3", "#weight-note": "after breakfast"},
             "#weight-save", "/api/body/weights", "154.3"),
            ("Blood pressure", "#body-add-bp", "#sheet-bp", {"#bp-systolic": "128", "#bp-diastolic": "82", "#bp-note": "left arm"},
             "#bp-save", "/api/body/blood-pressure", "128")):
        page.click(add)
        page.wait_for_selector(f"{sheet}[open]")
        for sel, value in typed.items():
            page.fill(sel, value)
        page.click(f"{sheet} [id$=-context] label >> nth=0")  # "when it was taken": the label is what is tapped
        failing = fail_500(page, path)
        page.click(save)
        after_failed_save(page, screen, save, typed, sheet=sheet)
        page.unroute(failing)

        def saved(sheet: str = sheet, shows: str = shows) -> None:
            page.wait_for_selector(sheet, state="hidden")
            wait_text(page, "#body-today-body", shows)

        next_try_saves_once(page, screen, save, path, saved)


def walk_body_slow(page: Any) -> None:
    """The day before's weights answer slowly; the person goes back to today. Neither day's card shows the other's weight."""
    for late in ("the day before's weights", "an error"):
        page.goto("/")
        wait_text(page, "#body-today-body", "158.7")
        held: list[Any] = []
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        def is_weights(url: str) -> bool:
            u = urlsplit(url)
            return u.path == "/api/body/weights" and f"start={yesterday}" in u.query

        page.route(is_weights, lambda route: held.append(route))
        page.click("#date-prev")
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        page.wait_for_timeout(300)
        waiting = text_of(page, "#body-today-body")
        check(f"Weight and blood pressure ({late}): while the day before loads, today's weight is not shown under it",
              held and "158.7" not in waiting, waiting[:160])
        page.click("#date-next")
        wait_text(page, "#body-today-body", "158.7")
        page.unroute(is_weights)
        for route in held:
            try:
                if late == "an error":
                    route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": SERVER_PROBLEM}))
                else:
                    route.fulfill(response=route.fetch())
            except Exception:  # noqa: BLE001 - the page gave up on it (the request was cancelled): also fine
                pass
        page.wait_for_timeout(800)
        shown = text_of(page, "#body-today-body")
        check(f"Weight and blood pressure: a slow answer for the day before ({late}) is not drawn over today",
              "158.7" in shown and "149.9" not in shown and "could not be loaded" not in shown, shown[:160])


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
        crackers_only = ana.json("POST", "/api/meals", {"name": "Crackers only", "items": [{"food_id": crackers, "servings": 1}]})["id"]
        ana.json("POST", "/api/meals", {"name": "Crackers and banana", "items": [{"food_id": crackers, "servings": 1}, {"food_id": banana, "servings": 1}]})
        zero = ana.json("POST", "/api/foods", {"name": "Known zero test food", "serving_desc": "1 portion", "serving_g": 30,
                                               "nutrients": {"calories_kcal": 20, "carbs_g": 5, "potassium_mg": 0, "phosphorus_mg": 0, "sodium_mg": 0}})["id"]
        ana.json("POST", "/api/meals", {"name": "Known zero", "items": [{"food_id": zero, "servings": 1}]})
        recipe = ana.json("POST", "/api/meals", {"name": "Big pot", "items": [{"food_id": banana, "servings": 10}], "servings_made": 100})["id"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        ana.json("POST", "/api/body/weights", {"date": date.today().isoformat(), "kg": 72, "context": "morning"})  # 158.7 lb
        ana.json("POST", "/api/body/weights", {"date": yesterday, "kg": 68, "context": "morning"})  # 149.9 lb
        ana.json("POST", "/api/labs", {"analyte": "phosphate", "value": 4.1, "unit": "mg/dL", "taken_on": yesterday})
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
                                   ("Meal editor", lambda: walk_meal_editor(page)),
                                   ("Fit data gaps", lambda: walk_fit_unknown(page)), ("Recipe", lambda: walk_recipe(page, recipe)),
                                   ("Plan editor", lambda: walk_plan_editor(page)),
                                   ("Plan, Add a saved meal", lambda: walk_plan_apply(page, crackers_only, crackers)),
                                   ("Labs", lambda: walk_labs_save(page)), ("Labs, slow list", lambda: walk_labs_slow(page)),
                                   ("Weight and blood pressure", lambda: walk_body_save(page)),
                                   ("Weight and blood pressure, slow day", lambda: walk_body_slow(page)),
                                   ("Profile", lambda: walk_profile(page))):
                    try:  # each step on its own, so one bug does not hide the others
                        walk()
                    except Exception as e:  # noqa: BLE001 - reported, then the next step runs
                        why = (str(e).strip().splitlines() or [""])[0]
                        check(f"{name}: the step ran to the end", False, f"{type(e).__name__}: {why}")
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
