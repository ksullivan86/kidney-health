#!/usr/bin/env python3
""""Plan several days" on the Plan tab (design note 23) in Chromium, against a real server and the demo.

    python tools/e2e/plandays.py                       # port 8231
    python tools/e2e/plandays.py --port 8231 --out /tmp/kh-plandays
    python tools/e2e/plandays.py --no-demo             # skip the Pages demo build

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup, sets targets (type 1 diabetes), and logs
on the days to plan: an eaten bread breakfast, an eaten soup that lists no potassium, and a planned low treatment (apple
juice). A second person plans food on the same days. Then, at 375x812 light:

* **Plan several days…** opens the sheet; **7 days**, **14 days**, **30 days** and **Rest of this week** set the count; 61
  days is refused in the sheet and never sent (the server's cap is 60); opening and previewing write nothing;
* the owner's answers (note 23 §12): the snack is off at first, and ticking **Plan a snack too** plans one on every day and is
  remembered on the server; ticking **Breakfast** under "Meals that may repeat" gives the same breakfast on several days and is
  remembered; 30 days are added in batches of 40 and Undo takes them all off;
* the preview has one box per day, the first open, the day's totals read "≥" for potassium on the soup's day, and the
  shopping list for the range has foods;
* **Add to plan** asks first ("Nothing is marked as eaten"); Cancel sends nothing; confirming sends the foods in batches of at
  most 40, one ``client_id`` each, all planned with purpose "none"; the server then holds them as planned food and the eaten
  food, the low treatment and the other person's food are as they were;
* **Undo** takes off exactly the foods it added (the ids the batches answered with);
* **Clear planned days…** asks first, says it is a reset (it also takes off food planned by hand), and then takes every
  planned food off the days, never the eaten food, the planned low treatment or the other person's food; another person's
  entry id sent to ``/api/log/clear-planned`` is 404;
* with the browser's clock frozen at 13:30 on today, breakfast is not planned (its time has passed) and the sheet asks
  "Lunch was at 12:30. Plan it anyway?" with **Plan it** and **Skip**, in the app's own confirm; Add to plan waits for the
  answer; Skip sends ``skip_first_day: ["breakfast", "lunch"]`` and Plan it only ``["breakfast"]``; the low treatment logged
  this morning stays as it was;
* at 1280x800 dark the sheet previews 14 days; no sideways scroll and no console error anywhere;
* the Pages demo (``scripts/build_preview.py --pages``, served statically) plans, adds and clears days in its own data and
  sends no request to any ``/api`` route.

Nothing leaves the machine and no screenshot is taken. Prints PASS / FAIL lines and writes ``<out>/report.json``; exit
status 1 on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import math
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from khserver import Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "plandays"
PORT = 8231
RESULTS: list[dict[str, Any]] = []
USER = "days"
TARGETS = {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": {"min": 50, "max": 70},
           "carbs_per_meal_g": 60}


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


class Watch:
    """Requests (with the JSON bodies of the plan routes), dialogs, console errors and page errors of one page."""

    WATCHED = ("/api/log/batch", "/api/log/clear-planned", "/api/guidance/plan-days")

    def __init__(self, page: Any) -> None:
        self.requests: list[tuple[str, str]] = []
        self.bodies: dict[str, list[Any]] = {p: [] for p in self.WATCHED}
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        page.on("request", self._request)
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def _request(self, r: Any) -> None:
        path = urlsplit(r.url).path
        self.requests.append((r.method, path))
        if r.method == "POST" and path in self.bodies:
            self.bodies[path].append(r.post_data_json)

    def writes(self) -> list[tuple[str, str]]:
        return [q for q in self.requests if q[0] in ("POST", "PUT", "PATCH", "DELETE") and q[1] != "/api/guidance/plan-days"]


def food_id(api: Any, name: str) -> int:
    foods = api.json("GET", "/api/foods", params={"q": name})["foods"]
    return next(f["id"] for f in foods if f["name"] == name)


def entries(api: Any, days: list[str]) -> list[dict[str, Any]]:
    return [e for d in days for e in api.json("GET", "/api/log", params={"date": d})["entries"]]


def planned_food(api: Any, days: list[str]) -> list[dict[str, Any]]:
    return [e for e in entries(api, days) if e["status"] == "planned" and e["purpose"] != "hypo"]


def kept(api: Any, days: list[str]) -> list[int]:
    """The ids that must never be cleared: eaten food and planned low treatments."""
    return sorted(e["id"] for e in entries(api, days) if e["status"] == "eaten" or e["purpose"] == "hypo")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-demo", action="store_true", help="skip the Pages demo (it builds the preview first)")
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, USER)
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "diabetes": "type1", "dialysis": "none", "week_start": "monday",
                                           "targets": TARGETS})
        sam = invite_user(server, admin, "sam")
        start = (date.today() + timedelta(days=1)).isoformat()
        days = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(7)]
        soup = admin.json("POST", "/api/foods", {"name": "Grandma's soup", "serving_desc": "1 bowl", "serving_g": 300,
                                                 "nutrients": {"carbs_g": 20, "sodium_mg": 600}})  # lists no potassium
        admin.json("POST", "/api/log", {"date": days[1], "meal": "breakfast", "food_id": food_id(admin, "Bread, white"), "servings": 2})
        admin.json("POST", "/api/log", {"date": days[1], "meal": "lunch", "food_id": soup["id"], "servings": 1})
        low = admin.json("POST", "/api/log", {"date": days[2], "meal": "snack", "food_id": food_id(admin, "Apple juice"), "servings": 1,
                                              "status": "planned"})
        check("setup: the apple juice is a planned low treatment", low["purpose"] == "hypo" and low["status"] == "planned", str(low))
        theirs = sam.json("POST", "/api/log", {"date": days[0], "meal": "dinner", "food_id": food_id(sam, "Bread, white"), "servings": 1,
                                               "status": "planned"})
        morning_low = admin.json("POST", "/api/log", {"date": date.today().isoformat(), "meal": "breakfast",
                                                      "food_id": food_id(admin, "Apple juice"), "servings": 1})
        check("setup: the low treatment this morning is a low treatment", morning_low["purpose"] == "hypo", str(morning_low))
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                phone(browser, admin, sam, base, days, theirs)
                choices(browser, admin, base, days)
                past_meals(browser, admin, base, morning_low)
                wide(browser, admin, base, start)
                if not args.no_demo:
                    demo(browser, out)
            finally:
                browser.close()
        r = admin.call("POST", "/api/log/clear-planned", {"start": days[0], "end": days[-1], "ids": [theirs["id"]]})
        check("another person's entry id is 404 and stays", r.status_code == 404
              and [e["id"] for e in planned_food(sam, days)] == [theirs["id"]], f"{r.status_code} {r.text[:200]}")
        admin.close()
        sam.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        server.stop()
    (out / "report.json").write_text(json.dumps(RESULTS, indent=1) + "\n", encoding="utf-8")
    failed = [r["check"] for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report: {out / 'report.json'}")
    return 1 if failed else 0


def open_sheet(page: Any, start: str) -> None:
    page.goto("/")
    page.click("#tab-plan")
    page.wait_for_selector("#btn-plan-days", state="visible", timeout=20000)
    page.click("#btn-plan-days")
    page.wait_for_selector("#sheet-guidance[open][data-kind='plan-days']", timeout=20000)
    page.fill("#g-days-start", start)
    page.dispatch_event("#g-days-start", "change")


def wait_days(page: Any, n: int) -> None:
    page.wait_for_function("(n) => document.querySelectorAll('#g-days-out .g-days-day').length === n", arg=n, timeout=60000)


def phone(browser: Any, admin: Any, sam: Any, base: str, days: list[str], theirs: dict[str, Any]) -> None:
    tag = "375-light"
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light", base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    keep = kept(admin, days)
    open_sheet(page, days[0])
    page.click("#g-days-7")
    wait_days(page, 7)
    check(f"[{tag}] 7 days: one box a day, the first open", page.locator(".g-days-day").count() == 7
          and page.locator(".g-days-day").first.get_attribute("open") is not None)
    page.click(f".g-days-day[data-date='{days[1]}'] > summary")  # open the soup's day, as a person would
    potassium = page.locator(f".g-days-day[data-date='{days[1]}'] .g-after-row", has_text="Potassium").inner_text()
    check(f"[{tag}] the soup's day reads '≥' for potassium", "≥" in potassium, potassium)
    shop = page.locator(".g-days-shop-list li").count()
    check(f"[{tag}] the shopping list for these days has foods", shop > 0, str(shop))
    check(f"[{tag}] previewing writes nothing", not watch.writes() and not planned_food(admin, days), str(watch.writes()))
    page.click("#g-days-14")
    wait_days(page, 14)
    check(f"[{tag}] 14 days: 14 boxes", page.locator(".g-days-day").count() == 14)
    page.click("#g-days-week")
    rest = 7 - date.fromisoformat(days[0]).weekday()
    wait_days(page, rest)
    check(f"[{tag}] Rest of this week counts to Sunday", page.input_value("#g-days-count") == str(rest), page.input_value("#g-days-count"))
    page.click("#g-days-30")
    wait_days(page, 30)
    check(f"[{tag}] 30 days: 30 boxes, and 60 days is offered", page.locator(".g-days-day").count() == 30
          and page.is_visible("#g-days-60") and page.input_value("#g-days-count") == "30")
    page.fill("#g-days-count", "61")
    page.wait_for_selector("#g-days-out .empty-state", timeout=20000)
    asked = [b["days"] for b in watch.bodies["/api/guidance/plan-days"]]
    check(f"[{tag}] 61 days is refused in the sheet and never sent", page.is_disabled("#g-days-add") and max(asked) <= 60
          and "1 to 60 days" in page.inner_text("#g-days-out"), str(asked))
    page.click("#g-days-7")
    wait_days(page, 7)
    page.wait_for_selector("#g-days-add:not([disabled])", timeout=20000)
    page.click("#g-days-add")
    page.wait_for_selector(".confirm-row", timeout=10000)
    msg = page.inner_text(".confirm-row .confirm-msg")
    check(f"[{tag}] Add to plan asks first and says nothing is eaten", "Nothing is marked as eaten." in msg and "to 7 days" in msg, msg)
    page.click(".confirm-row .btn.secondary")
    check(f"[{tag}] Cancel sends nothing", not watch.bodies["/api/log/batch"] and not planned_food(admin, days))
    page.click("#g-days-add")
    page.click(".confirm-row .btn.primary")
    page.wait_for_selector("#g-days-undo", timeout=60000)
    batches = [b["entries"] for b in watch.bodies["/api/log/batch"]]
    sent = [e for b in batches for e in b]
    check(f"[{tag}] the foods go in batches of at most 40, one client_id each, planned with purpose none",
          len(batches) == math.ceil(len(sent) / 40) and all(len(b) <= 40 for b in batches)
          and len({e["client_id"] for e in sent}) == len(sent) and all(e["status"] == "planned" and e["purpose"] == "none" for e in sent),
          f"{[len(b) for b in batches]}")
    now = planned_food(admin, days)
    check(f"[{tag}] the server holds them as planned food; eaten food and the low treatment are as they were",
          len(now) == len(sent) and kept(admin, days) == keep, f"{len(now)} vs {len(sent)}")
    check(f"[{tag}] the other person's food is as it was", [e["id"] for e in planned_food(sam, days)] == [theirs["id"]])
    said = page.inner_text(".g-days-added")
    check(f"[{tag}] after adding, Undo says it takes off only what this plan added", "Undo takes off only what this plan added." in said, said)
    page.click("#g-days-undo")
    wait_days(page, 7)
    undo = watch.bodies["/api/log/clear-planned"][-1]
    check(f"[{tag}] Undo sends exactly the ids it added and takes them off",
          sorted(undo["ids"]) == sorted(e["id"] for e in now) and not planned_food(admin, days) and kept(admin, days) == keep, str(undo)[:200])
    page.wait_for_selector("#g-days-add:not([disabled])", timeout=20000)
    page.click("#g-days-add")
    page.click(".confirm-row .btn.primary")
    page.wait_for_selector("#g-days-undo", timeout=60000)
    again = len(planned_food(admin, days))
    page.dispatch_event("#g-days-start", "change")  # leave the added state: the preview comes back for the same days
    wait_days(page, 7)
    page.click("#g-days-clear")
    page.wait_for_selector(".confirm-row .btn.danger-solid", timeout=10000)
    msg = page.inner_text(".confirm-row .confirm-msg")
    check(f"[{tag}] Clear planned days asks first, says it is a reset and what stays",
          "Eaten food and planned low treatments stay." in msg and "This is a reset" in msg
          and "also takes off food you planned yourself" in msg, msg)
    page.click(".confirm-row .btn.danger-solid")
    page.wait_for_function("() => !document.querySelector('.confirm-row')", timeout=20000)
    wait_days(page, 7)
    check(f"[{tag}] clearing took every planned food off and kept the eaten food and the low treatment",
          again > 0 and not planned_food(admin, days) and kept(admin, days) == keep, f"{again} added, {len(planned_food(admin, days))} left")
    check(f"[{tag}] the other person's planned food is still there", [e["id"] for e in planned_food(sam, days)] == [theirs["id"]])
    check(f"[{tag}] no sideways scroll, no console error, no dialog", not overflow(page) and not watch.errors and not watch.dialogs,
          "; ".join(watch.errors))
    ctx.close()


def meal_foods(page: Any, meal: str) -> list[list[int]]:
    """The food ids of ``meal`` on each day of the preview (closed days too: their content is in the page)."""
    return page.evaluate("""(meal) => [...document.querySelectorAll('#g-days-out .g-days-day')].map((d) => {
        const sec = [...d.querySelectorAll('.g-plan-meal')].find((s) => s.querySelector('.g-plan-title').textContent.startsWith(meal));
        return sec ? [...sec.querySelectorAll('li[data-food-id]')].map((li) => Number(li.dataset.foodId)) : null;
      })""", meal)


def remembered(api: Any) -> dict[str, Any]:
    return api.json("GET", "/api/me/settings")["settings"]["guidance"]["value"]


def saved(page: Any, action: Any) -> None:
    """Run ``action`` (a tick or an untick) and wait until the sheet has remembered it (``PATCH /api/me/settings``)."""
    with page.expect_response(lambda r: r.request.method == "PATCH" and urlsplit(r.url).path == "/api/me/settings", timeout=60000):
        action()


def choices(browser: Any, admin: Any, base: str, days: list[str]) -> None:
    """The snack and "Meals that may repeat" (note 23 §12.2, §12.5), remembered on the server; 30 days added and undone."""
    tag = "375-choices"
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light", base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    start = (date.fromisoformat(days[0]) + timedelta(days=20)).isoformat()  # days with nothing logged
    open_sheet(page, start)
    wait_days(page, 7)
    snacks = meal_foods(page, "Snack")
    check(f"[{tag}] the snack is off at first: no day plans one", not page.is_checked("#g-days-snack") and snacks == [None] * 7,
          str(snacks))
    saved(page, lambda: page.check("#g-days-snack"))
    page.wait_for_function("() => document.querySelectorAll('#g-days-out .g-plan-meal').length > 21", timeout=60000)
    snacks = meal_foods(page, "Snack")
    check(f"[{tag}] Plan a snack too plans one on every day and is remembered",
          all(s for s in snacks) and remembered(admin)["plan_snack"] is True
          and watch.bodies["/api/guidance/plan-days"][-1]["snack"] is True, str(snacks))
    saved(page, lambda: page.uncheck("#g-days-snack"))
    page.wait_for_function("() => !document.querySelector('#g-days-out[aria-busy]') && document.querySelectorAll('#g-days-out .g-days-day').length === 7"
                           " && ![...document.querySelectorAll('#g-days-out .g-plan-title')].some((t) => t.textContent.startsWith('Snack'))",
                           timeout=60000)
    check(f"[{tag}] turning it off again plans no snack and is remembered", remembered(admin)["plan_snack"] is False)
    rotating = meal_foods(page, "Breakfast")
    check(f"[{tag}] without the choice, breakfast changes from day to day", len({tuple(b) for b in rotating if b}) > 1, str(rotating))
    with page.expect_response(lambda r: urlsplit(r.url).path == "/api/guidance/plan-days", timeout=60000):
        saved(page, lambda: page.check("#g-days-repeat-breakfast"))
    page.wait_for_function("() => !document.querySelector('#g-days-out[aria-busy]')", timeout=60000)
    wait_days(page, 7)
    same = meal_foods(page, "Breakfast")
    last = watch.bodies["/api/guidance/plan-days"][-1]
    check(f"[{tag}] breakfast may repeat: the same breakfast on several days, and it is remembered",
          last["repeat_meals"] == ["breakfast"] and len({tuple(b) for b in same if b}) < len({tuple(b) for b in rotating if b})
          and max(same.count(b) for b in same) >= 3 and remembered(admin)["plan_repeat_meals"] == ["breakfast"],
          f"before {rotating} after {same}")
    saved(page, lambda: page.uncheck("#g-days-repeat-breakfast"))
    wait_days(page, 7)
    check(f"[{tag}] unticking it is remembered too", remembered(admin)["plan_repeat_meals"] == [])
    span = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(30)]
    page.click("#g-days-30")
    wait_days(page, 30)
    page.wait_for_selector("#g-days-add:not([disabled])", timeout=20000)
    before = len(watch.bodies["/api/log/batch"])
    page.click("#g-days-add")
    page.click(".confirm-row .btn.primary")
    page.wait_for_selector("#g-days-undo", timeout=120000)
    batches = [b["entries"] for b in watch.bodies["/api/log/batch"][before:]]
    sent = [e for b in batches for e in b]
    check(f"[{tag}] 30 days go in batches of at most 40 with one client_id each",
          len(batches) >= 5 and all(len(b) <= 40 for b in batches) and len({e["client_id"] for e in sent}) == len(sent)
          and len(planned_food(admin, span)) == len(sent), f"{[len(b) for b in batches]}")
    page.click("#g-days-undo")
    wait_days(page, 30)
    check(f"[{tag}] Undo takes all 30 days' foods off again", not planned_food(admin, span))
    check(f"[{tag}] no sideways scroll, no console error, no dialog", not overflow(page) and not watch.errors and not watch.dialogs,
          "; ".join(watch.errors))
    ctx.close()


def past_meals(browser: Any, admin: Any, base: str, low: dict[str, Any]) -> None:
    """Today's past meals (note 23 §12.6) with the browser's clock frozen at 13:30: breakfast is left out, lunch is asked."""
    tag = "375-13:30"
    today = date.today().isoformat()
    for answer in ("Skip", "Plan it"):
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light", base_url=base, timezone_id="UTC")
        ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
        page = ctx.new_page()
        page.clock.set_fixed_time(f"{today}T13:30:00Z")
        watch = Watch(page)
        open_sheet(page, today)
        page.wait_for_selector("#g-days-ask + .confirm-row", timeout=60000)
        msg = page.inner_text("#g-days-ask + .confirm-row .confirm-msg")
        buttons = page.locator("#g-days-ask + .confirm-row button").all_inner_texts()
        check(f"[{tag}] the sheet asks about lunch in its own confirm, and Add to plan waits",
              msg == "Lunch was at 12:30. Plan it anyway?" and buttons == ["Skip", "Plan it"] and page.is_disabled("#g-days-add")
              and not watch.dialogs, f"{msg!r} {buttons}")
        note = page.inner_text("#g-days-past")
        first = watch.bodies["/api/guidance/plan-days"][-1]
        check(f"[{tag}] breakfast is more than 2 hours past: not planned, and said",
              "Breakfast is not planned for today: its time has passed." in note and first["skip_first_day"] == ["breakfast"]
              and meal_foods(page, "Breakfast")[0] is None, f"{note!r} {first.get('skip_first_day')}")
        page.click(f"#g-days-ask + .confirm-row button:text-is('{answer}')")
        if answer == "Skip":
            page.wait_for_function("() => !document.querySelector('#g-days-out[aria-busy]') && !document.querySelector('#g-days-ask + .confirm-row')",
                                   timeout=60000)
            page.wait_for_function("() => document.querySelectorAll('#g-days-out .g-days-day').length === 7", timeout=60000)
            last = watch.bodies["/api/guidance/plan-days"][-1]
            check(f"[{tag}] Skip leaves lunch out of today", last["skip_first_day"] == ["breakfast", "lunch"]
                  and meal_foods(page, "Lunch")[0] is None and meal_foods(page, "Lunch")[1] is not None, str(last["skip_first_day"]))
        else:
            page.wait_for_function("() => !document.querySelector('#g-days-ask + .confirm-row')", timeout=20000)
            check(f"[{tag}] Plan it keeps lunch on today and Add to plan is ready again",
                  watch.bodies["/api/guidance/plan-days"][-1]["skip_first_day"] == ["breakfast"]
                  and meal_foods(page, "Lunch")[0] is not None and not page.is_disabled("#g-days-add"))
        now = next(e for e in admin.json("GET", "/api/log", params={"date": today})["entries"] if e["id"] == low["id"])
        check(f"[{tag}] {answer}: the low treatment this morning is as it was and nothing was written",
              (now["purpose"], now["status"], now["servings"]) == ("hypo", "eaten", low["servings"]) and not watch.writes(),
              str(watch.writes()))
        check(f"[{tag}] {answer}: no sideways scroll, no console error", not overflow(page) and not watch.errors, "; ".join(watch.errors))
        ctx.close()


def wide(browser: Any, admin: Any, base: str, start: str) -> None:
    tag = "1280-dark"
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, color_scheme="dark", base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    open_sheet(page, start)
    page.click("#g-days-14")
    wait_days(page, 14)
    check(f"[{tag}] 14 days preview, nothing written", page.locator(".g-days-day").count() == 14 and not watch.writes(), str(watch.writes()))
    check(f"[{tag}] no sideways scroll, no console error", not overflow(page) and not watch.errors, "; ".join(watch.errors))
    ctx.close()


def demo(browser: Any, out: Path) -> None:
    """The Pages demo (scripts/build_preview.py --pages: the app's mock API) served by a static server."""
    site = out / "demo-site"
    subprocess.run([sys.executable, str(REPO / "scripts" / "build_preview.py"), "--pages", str(site)], check=True, capture_output=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://localhost:{httpd.server_address[1]}"
    try:
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light", base_url=base)
        page = ctx.new_page()
        watch = Watch(page)
        page.goto("/")
        page.wait_for_selector("#tab-plan", state="visible", timeout=30000)
        start = page.evaluate("KH.util.addDays(KH.util.todayStr(), 30)")  # after the demo's sample plan
        days = page.evaluate("(s) => [0, 1, 2].map((i) => KH.util.addDays(s, i))", start)
        open_sheet(page, start)
        page.fill("#g-days-count", "3")
        wait_days(page, 3)
        page.wait_for_selector("#g-days-add:not([disabled])", timeout=20000)
        page.click("#g-days-add")
        page.click(".confirm-row .btn.primary")
        page.wait_for_selector("#g-days-undo", timeout=60000)
        count = "async (ds) => { let n = 0; for (const d of ds) n += (await KH.api.day(d)).entries.filter((e) => e.status === 'planned').length; return n; }"
        added = page.evaluate(count, days)
        check("[demo] Add to plan puts planned food in the demo's own data", added > 0, str(added))
        page.dispatch_event("#g-days-start", "change")
        wait_days(page, 3)
        page.click("#g-days-clear")
        page.click(".confirm-row .btn.danger-solid")
        page.wait_for_function("() => !document.querySelector('.confirm-row')", timeout=20000)
        wait_days(page, 3)
        check("[demo] Clear planned days takes it off again", page.evaluate(count, days) == 0)
        others = [q for q in watch.requests if q[1].startswith("/api/")]
        check("[demo] no request to any /api route, no error", not others and not watch.errors, f"{others[:5]} {watch.errors}")
        ctx.close()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
