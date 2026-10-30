#!/usr/bin/env python3
"""Food preferences and what the app learns from the log (note 09, part B: the screens) in Chromium, against a real server
and the Pages demo.

    python tools/e2e/prefs.py                       # port 8085
    python tools/e2e/prefs.py --port 8085 --out /tmp/kh-prefs
    python tools/e2e/prefs.py --only menu,settings  # parts: menu, swaps, plan, settings, low, offline, demo

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED`` (so the text for AI ideas has a place), finishes
first-run setup, gives the first person targets, type 1 diabetes and a log (a usual lunch, foods eaten often, a food planned and
passed over) and invites a second person with a preference of their own. Then, at 375x812 light and 1280x800 dark:

* ``menu``: What fits now: the "⋯" of a suggestion holds More like this, Less often and Not for me; each is a toggle (aria-pressed),
  the state is read from the server when the menu opens, pressing the pressed one clears it, a toast confirms every change and the
  server holds exactly that (``PUT`` / ``DELETE /api/guidance/preferences/{id}``); Not for me removes the food from the list;
* ``swaps``: a swap row has the same menu (and its Not for me reloads the list); the options "For your next low" have none;
* ``plan``: the plan sheet's items have it too; Not for me on one makes the plan again without that food;
* ``settings``: Settings → Meal guidance → Your food preferences: the three lists with their counts and limits, Remove / Suggest
  again and the row menu, a kind of food in one of None / Like / Less often / Never suggest (the server holds each choice, a kind
  is in one list at most), the Learn from my log switch (off: the learned list says so), the learned list with its reasons, Keep,
  Stop using this (then the food is under "Not learning about" with Learn again), Save as a meal (the saved-meal editor opens with
  the usual meal's foods and saves it), Not this meal and Show them again, the sentence of §4.10 word for word, the text for AI
  ideas saved through the same call as before, and Settings → AI features pointing to it;
* ``low``: with every low-treatment food on "Not for me" the Treating a low sheet still lists them, with the line "Shown although
  you marked them Not for me.", and no row of it has a preference menu;
* ``offline``: with the network gone a save says the server cannot be reached, changes nothing and queues nothing, and the lists say
  "Guidance needs a connection to your server.";
* ``demo`` (the Pages demo built by ``scripts/build_preview.py --pages``, served statically): the menu and the Settings section do the
  same with the demo's own data (no text for AI ideas there);
* every pass: the second person's preference is on no page, the browser asked no other host, no dialog, no console error, no
  sideways scroll, every control in the section at least 44 px high on the phone.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit
status 1 on any failure. The server and the browser are always stopped.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
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
OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "prefs"
PORT = 8085
RESULTS: list[dict[str, Any]] = []
USER = "taste"
PARTS = ("menu", "swaps", "plan", "settings", "low", "offline", "demo")
TASTE_NOTE = ("Less often and Not for me are about taste. They are not an allergy filter: the app cannot tell whether a food "
              "contains an allergen, so check labels.")
OFFLINE_WRITE = "Your server cannot be reached, so this change was not saved"
NEEDS_CONNECTION = "Guidance needs a connection to your server."
SHOWN_DESPITE = "Shown although you marked them Not for me."


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def day(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


class Watch:
    """Hosts asked, writes, dialogs, console errors and page errors of one page."""

    def __init__(self, page: Any) -> None:
        self.hosts: set[str] = set()
        self.writes: list[tuple[str, str]] = []
        self.posts: list[str] = []
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
        parts = urlsplit(r.url)
        if parts.scheme in ("http", "https"):
            self.hosts.add(parts.netloc)
        if r.method != "GET":
            self.writes.append((r.method, parts.path))
            self.posts.append(parts.path)


def wait_toast(page: Any, text: str) -> None:
    try:
        page.wait_for_function("(t) => { const el = document.querySelector('#toast'); return el.classList.contains('show') && el.textContent.includes(t); }",
                               arg=text, timeout=10000)
    except Exception as exc:
        raise AssertionError(f"no toast saying {text!r}; the toast reads {page.inner_text('#toast')!r}") from exc


def toast(page: Any) -> str:
    return page.inner_text("#toast")


def pressed(button: Any) -> str | None:
    return button.get_attribute("aria-pressed")


def shot(page: Any, out: Path, name: str) -> None:
    page.screenshot(path=str(out / "shots" / f"{name}.png"))


# --------------------------------------------------------------------------------------------------------------------- data
def pref_map(api: Any) -> dict[int, str]:
    return {f["food_id"]: f["preference"] for f in api.json("GET", "/api/guidance/preferences")["foods"]}


def reset(api: Any) -> None:
    """The first person's preferences, guidance settings and saved meals back to nothing."""
    for row in api.json("GET", "/api/guidance/preferences")["foods"]:
        api.call("DELETE", f"/api/guidance/preferences/{row['food_id']}")
    api.json("PATCH", "/api/me/settings", {"guidance": {}})
    for meal in api.json("GET", "/api/meals")["meals"]:
        api.call("DELETE", f"/api/meals/{meal['id']}")


def seed(admin: Any, sam: Any) -> dict[str, int]:
    """Targets, type 1 diabetes and a log that gives the app something to notice."""
    admin.json("PUT", "/api/profile", {"weight_kg": 70, "diabetes": "type1", "targets": {
        "potassium_mg": 3000, "phosphorus_mg": 1000, "sodium_mg": 2300, "protein_g": {"min": 50, "max": 80}, "carbs_per_meal_g": 60}})
    ids = {q: admin.json("GET", "/api/foods", params={"q": q})["foods"][0]["id"] for q in ("chicken breast", "rice, white", "green beans", "cauliflower")}
    for n in (1, 2, 3, 5):  # a usual lunch, eaten often
        for key in ("chicken breast", "rice, white", "green beans"):
            admin.json("POST", "/api/log", {"date": day(n), "meal": "lunch", "food_id": ids[key], "servings": 1})
    for n in (2, 3, 4):  # a food planned for dinner again and again, and a different dinner eaten
        admin.json("POST", "/api/log", {"date": day(n), "meal": "dinner", "food_id": ids["cauliflower"], "servings": 1, "status": "planned"})
        admin.json("POST", "/api/log", {"date": day(n), "meal": "dinner", "food_id": ids["rice, white"], "servings": 1})
    secret = sam.json("POST", "/api/foods", {"name": "Sam's secret stew", "serving_desc": "1 bowl", "serving_g": 300, "nutrients": {"potassium_mg": 300}})
    sam.json("PUT", f"/api/guidance/preferences/{secret['id']}", {"preference": "like"})
    return {**ids, "secret": secret["id"]}


# ------------------------------------------------------------------------------------------------------------------ pages
def open_tab(page: Any, tab: str, ready: str) -> None:
    page.click(f"#tab-{tab}")
    page.wait_for_selector(ready, timeout=20000)


def open_fits(page: Any, meal: str = "lunch") -> None:
    open_tab(page, "add", "#guidance-fits-meal")
    page.click(f"#guidance-fits-meal label[for=gfm-{meal}]")
    page.wait_for_selector("#guidance-fits-body .g-food", timeout=20000)


def open_settings(page: Any) -> None:
    page.click("#settings-open")
    page.wait_for_selector("#set-g-prefs", state="attached", timeout=20000)
    page.wait_for_selector("#set-g-prefs .g-pref-foods .g-pref-group", timeout=20000)
    page.wait_for_function("() => !/Loading/.test(document.querySelector('#set-g-prefs .g-learned').textContent)", timeout=20000)


def section_top(page: Any) -> None:
    page.locator("#set-g-prefs-h").scroll_into_view_if_needed()


def list_names(page: Any, value: str) -> list[str]:
    return page.locator(f"#set-g-pref-list-{value} li.g-pref-row .row-title").all_inner_texts()


# ------------------------------------------------------------------------------------------------------------------- parts
def part_menu(page: Any, api: Any, out: Path, tag: str, mock: bool) -> None:
    open_fits(page)
    row = page.locator("#guidance-fits-body .g-food").first
    fid = int(row.get_attribute("data-food-id"))
    name = row.locator(".row-title").inner_text()
    row.locator("button.g-more").click()
    menu = row.locator(".g-menu")
    page.wait_for_function("(el) => !el.hasAttribute('aria-busy')", arg=menu.element_handle(), timeout=10000)
    labels = menu.locator("button.g-pref").all_inner_texts()
    check(f"[{tag}] the menu offers More like this, Less often and Not for me", labels == ["More like this", "Less often", "Not for me"], str(labels))
    check(f"[{tag}] none is pressed before the person chooses", all(pressed(menu.locator(f"button[data-pref={p}]")) == "false" for p in ("like", "less", "not_for_me")))
    row.scroll_into_view_if_needed()
    shot(page, out, f"menu-open-{tag}")
    menu.locator("button[data-pref=like]").click()
    wait_toast(page, f"{name}: more like this. Settings → Meal guidance lists it.")
    check(f"[{tag}] More like this is confirmed by a toast and shows pressed", pressed(menu.locator("button[data-pref=like]")) == "true"
          and pressed(menu.locator("button[data-pref=less]")) == "false", toast(page))
    if not mock:
        check(f"[{tag}] the server holds the like", pref_map(api).get(fid) == "like", str(pref_map(api)))
    shot(page, out, f"menu-liked-{tag}")
    # closing and opening again reads the state again
    page.keyboard.press("Escape")
    check(f"[{tag}] Escape closes the menu and the focus returns to the button", menu.is_hidden() and page.evaluate("document.activeElement.classList.contains('g-more')"))
    row.locator("button.g-more").click()
    page.wait_for_function("(el) => !el.hasAttribute('aria-busy')", arg=menu.element_handle(), timeout=10000)
    check(f"[{tag}] opened again, the state is shown", pressed(menu.locator("button[data-pref=like]")) == "true")
    menu.locator("button[data-pref=like]").click()
    wait_toast(page, f"{name}: no preference now.")
    check(f"[{tag}] pressing the pressed one clears it", pressed(menu.locator("button[data-pref=like]")) == "false")
    if not mock:
        check(f"[{tag}] the server holds nothing for the food", fid not in pref_map(api), str(pref_map(api)))
    menu.locator("button[data-pref=less]").click()
    wait_toast(page, f"{name} will be suggested less often.")
    check(f"[{tag}] Less often is pressed and confirmed", pressed(menu.locator("button[data-pref=less]")) == "true")
    if not mock:
        check(f"[{tag}] the server holds 'less'", pref_map(api).get(fid) == "less")
    menu.locator("button[data-pref=not_for_me]").click()
    wait_toast(page, f"{name} will not be suggested again.")
    page.wait_for_function("(id) => !document.querySelector(`#guidance-fits-body [data-food-id=\"${id}\"]`)", arg=fid, timeout=15000)
    check(f"[{tag}] Not for me takes the food out of the list", page.locator(f"#guidance-fits-body [data-food-id='{fid}']").count() == 0)
    if not mock:
        check(f"[{tag}] the server holds 'not_for_me' (and the older route lists it)", pref_map(api).get(fid) == "not_for_me"
              and fid in [f["food_id"] for f in api.json("GET", "/api/guidance/not-for-me")["foods"]])


def part_swaps(page: Any, api: Any, out: Path, tag: str) -> None:
    open_tab(page, "add", "#food-search")
    with page.expect_response(lambda r: "/api/foods?" in r.url and "q=banana" in r.url):
        page.fill("#food-search", "banana")
    page.click("#food-results .row-btn >> text=/^Banana, raw/ >> nth=0")
    page.wait_for_selector("#sheet-entry[open]")
    page.click("#sheet-entry label[for=meal-lunch]")
    page.click("#entry-guidance summary")
    page.wait_for_selector("#entry-guidance .g-swap-list .g-food", timeout=20000)
    rows = page.locator("#entry-guidance .g-swap-list .g-food")
    check(f"[{tag}] every swap row has the menu", rows.count() >= 1 and page.locator("#entry-guidance .g-swap-list .g-food button.g-more").count() == rows.count(),
          str(rows.count()))
    first = rows.first
    fid = int(first.get_attribute("data-food-id"))
    name = first.locator(".row-title").inner_text()
    first.locator("button.g-more").click()
    first.locator("button[data-pref=less]").click()
    wait_toast(page, f"{name} will be suggested less often.")
    check(f"[{tag}] Less often on a swap is saved", pref_map(api).get(fid) == "less", str(pref_map(api)))
    shot(page, out, f"swap-menu-{tag}")
    first.locator("button[data-pref=not_for_me]").click()
    wait_toast(page, f"{name} will not be suggested again.")
    page.wait_for_function("(id) => !document.querySelector(`#entry-guidance [data-food-id=\"${id}\"]`)", arg=fid, timeout=15000)
    check(f"[{tag}] Not for me on a swap loads the ideas again without that food", pref_map(api).get(fid) == "not_for_me"
          and page.locator(f"#entry-guidance [data-food-id='{fid}']").count() == 0)
    # the options for the next low carry no menu: taste does not rank a low treatment
    page.check("#entry-hypo")
    page.wait_for_selector("#entry-guidance summary:has-text('For your next low')", timeout=10000)
    if not page.locator("#entry-guidance details[open]").count():
        page.click("#entry-guidance summary")
    page.wait_for_selector("#entry-guidance .g-lowcard", timeout=20000)
    check(f"[{tag}] the options for the next low have no preference menu", page.locator("#entry-guidance button.g-more").count() == 0)
    page.click("#sheet-entry [data-close]")
    page.wait_for_selector("#sheet-entry", state="hidden")


def part_plan(page: Any, api: Any, out: Path, tag: str) -> None:
    open_tab(page, "today", "#guidance-today-actions button")
    page.click("#guidance-today-actions button >> text=/Plan the rest of my day|Plan this day/")
    page.wait_for_selector("#g-plan-out .g-plan-meal .g-portions li", timeout=30000)
    items = page.locator("#g-plan-out .g-plan-meal .g-portions li")
    check(f"[{tag}] each food of the plan has the menu", items.count() >= 2 and page.locator("#g-plan-out .g-portions li button.g-more").count() == items.count(), str(items.count()))
    first = items.first
    fid = int(first.get_attribute("data-food-id"))
    name = first.locator(".ci-name").inner_text().split(" · ")[0]
    first.locator("button.g-more").click()
    first.locator("button[data-pref=like]").click()
    wait_toast(page, f"{name}: more like this.")
    check(f"[{tag}] More like this on a plan item is saved", pref_map(api).get(fid) == "like")
    shot(page, out, f"plan-menu-{tag}")
    second = None
    for i in range(items.count()):
        cand = items.nth(i)
        if int(cand.get_attribute("data-food-id")) != fid:
            second = cand
            break
    sid = int(second.get_attribute("data-food-id"))
    sname = second.locator(".ci-name").inner_text().split(" · ")[0]
    plans = len([r for r in page.evaluate("() => performance.getEntriesByType('resource').map((r) => r.name)") if "plan-day" in r])
    second.locator("button.g-more").click()
    second.locator("button[data-pref=not_for_me]").click()
    wait_toast(page, f"{sname} will not be suggested again.")
    page.wait_for_function("(id) => !document.querySelector(`#g-plan-out [data-food-id=\"${id}\"]`) && !document.querySelector('#g-plan-out[aria-busy]')",
                           arg=sid, timeout=30000)
    again = len([r for r in page.evaluate("() => performance.getEntriesByType('resource').map((r) => r.name)") if "plan-day" in r])
    check(f"[{tag}] Not for me on a plan item makes the plan again without that food", pref_map(api).get(sid) == "not_for_me"
          and page.locator(f"#g-plan-out [data-food-id='{sid}']").count() == 0 and again == plans + 1, f"{plans} -> {again}")
    check(f"[{tag}] the focus stays in the sheet", page.evaluate("document.querySelector('#sheet-guidance').contains(document.activeElement)"))
    page.click("#sheet-guidance [data-close]")
    page.wait_for_selector("#sheet-guidance", state="hidden")


def part_low(page: Any, api: Any, out: Path, tag: str) -> None:
    options = api.json("GET", "/api/guidance/hypo-options")["options"]
    check(f"[{tag}] the account has low-treatment foods", len(options) >= 1, str(len(options)))
    for o in options:
        api.json("PUT", f"/api/guidance/preferences/{o['food_id']}", {"preference": "not_for_me"})
    page.reload()
    open_tab(page, "today", "#guidance-today-actions .g-low-btn")
    page.click("#guidance-today-actions .g-low-btn")
    page.wait_for_selector("#sheet-guidance .g-low .g-foods .g-food", timeout=20000)
    text = page.inner_text("#sheet-guidance")
    check(f"[{tag}] every low treatment is on Not for me, yet Treating a low lists them with the note", SHOWN_DESPITE in text, text[-300:])
    check(f"[{tag}] the card is there and no row has a preference menu", "Treating a low" in text and page.locator("#sheet-guidance .g-low button.g-more").count() == 0)
    shot(page, out, f"low-{tag}")
    page.click("#sheet-guidance [data-close]")
    for o in options:
        api.call("DELETE", f"/api/guidance/preferences/{o['food_id']}")


def tap_targets(page: Any, tag: str) -> None:
    small = page.evaluate("""() => {
      const bad = [];
      const root = document.querySelector('#set-g-prefs');
      for (const el of root.querySelectorAll('button, .meal-seg label, .check, summary, a')) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0 || el.closest('[hidden]')) continue;
        if (r.height < 43.5) bad.push((el.textContent || el.className).trim().slice(0, 30) + ' ' + Math.round(r.height));
      }
      return bad; }""")
    check(f"[{tag}] every button, choice and switch in the section is at least 44 px high", not small, str(small[:6]))


def part_settings(page: Any, api: Any, out: Path, tag: str, mock: bool, phone: bool) -> None:
    # a like, a less and a not-for-me to list
    open_settings(page)
    section = page.locator("#set-g-prefs")
    check(f"[{tag}] the section has its heading and the sentence of the note, word for word", "Your food preferences" in section.inner_text()
          and page.locator("#set-g-prefs .g-taste-note").inner_text() == TASTE_NOTE, page.locator("#set-g-prefs .g-taste-note").inner_text())
    check(f"[{tag}] the three lists are there, with the limits", [h.strip() for h in page.locator("#set-g-prefs .g-pref-foods .g-pref-head").all_inner_texts()] == ["More like this", "Less often", "Not for me"]
          and "of 1000 food preferences" in page.inner_text("#set-g-prefs .g-pref-count") and "of 500 “Not for me”" in page.inner_text("#set-g-prefs .g-pref-count"),
          page.inner_text("#set-g-prefs .g-pref-count"))
    check(f"[{tag}] the Learn from my log switch has its line", page.is_checked("#set-g-learn-from-log")
          and "Off: suggestions use only your limits and variety, not what you usually eat." in page.inner_text("label[for=set-g-learn-from-log]"))
    # food rows come from the menu in What fits now (a food of the list) so the lists have something in them
    open_fits(page)
    rows = page.locator("#guidance-fits-body .g-food:visible")  # two per group show before "Show more"
    names = []
    for i, pref in enumerate(("like", "less", "not_for_me")):
        row = rows.nth(i)
        names.append(row.locator(".row-title").inner_text())
        row.locator("button.g-more").click()
        row.locator(f"button[data-pref={pref}]").click()
        wait_toast(page, names[-1])
        if pref == "not_for_me":
            page.wait_for_function("(n) => ![...document.querySelectorAll('#guidance-fits-body .g-food .row-title')].some((e) => e.textContent === n)", arg=names[-1], timeout=15000)
        else:
            page.wait_for_timeout(200)
    open_settings(page)
    section_top(page)
    check(f"[{tag}] each food is in its list", list_names(page, "like") == [names[0]] and list_names(page, "less") == [names[1]] and list_names(page, "not_for_me") == [names[2]],
          str((list_names(page, "like"), list_names(page, "less"), list_names(page, "not_for_me"))))
    check(f"[{tag}] the count line follows", "3 of 1000 food preferences · 1 of 500" in page.inner_text("#set-g-prefs .g-pref-count"), page.inner_text("#set-g-prefs .g-pref-count"))
    shot(page, out, f"settings-lists-{tag}")
    # the row menu of a liked food: its state is known, Less often moves it
    like_row = page.locator("#set-g-pref-list-like li.g-pref-row").first
    like_row.locator("button.g-more").click()
    check(f"[{tag}] the row's menu shows the current state without asking", pressed(like_row.locator("button[data-pref=like]")) == "true")
    like_row.locator("button[data-pref=less]").click()
    wait_toast(page, f"{names[0]} will be suggested less often.")
    page.wait_for_function("(n) => [...document.querySelectorAll('#set-g-pref-list-less li.g-pref-row .row-title')].some((e) => e.textContent === n)", arg=names[0], timeout=10000)
    check(f"[{tag}] the food moved to Less often and the focus is on its menu button", names[0] in list_names(page, "less") and not list_names(page, "like")
          and page.evaluate("document.activeElement.classList.contains('g-more')"))
    # Remove, Suggest again
    page.locator("#set-g-pref-list-less li.g-pref-row", has_text=names[0]).get_by_role("button", name=f"Remove {names[0]} from Less often").click()
    wait_toast(page, f"{names[0]} was removed from “Less often”.")
    page.wait_for_function("(n) => ![...document.querySelectorAll('#set-g-pref-list-less li.g-pref-row .row-title')].some((e) => e.textContent === n)", arg=names[0], timeout=10000)
    page.get_by_role("button", name=f"Suggest {names[2]} again").click()
    wait_toast(page, f"{names[2]} can be suggested again.")
    page.wait_for_function("() => document.querySelectorAll('#set-g-pref-list-not_for_me li.g-pref-row').length === 0", timeout=10000)
    if not mock:
        check(f"[{tag}] Remove and Suggest again left only the 'less' food on the server", sorted(pref_map(api).values()) == ["less"], str(pref_map(api)))
    check(f"[{tag}] the empty lists say how to fill them", "None yet" in page.inner_text("#set-g-pref-list-like") and "Use “⋯ → Not for me”" in page.inner_text("#set-g-pref-list-not_for_me"))

    # kinds of food
    kinds = page.locator("#set-g-kinds .g-kind")
    n_kinds = kinds.count()
    check(f"[{tag}] a row per kind of food with None, Like, Less often and Never suggest", n_kinds >= 10 and
          kinds.first.locator("label").all_inner_texts() == ["None", "Like", "Less often", "Never suggest"], str(n_kinds))
    first_kind = kinds.first.locator("legend").inner_text()
    guidance = lambda: api.json("GET", "/api/me/settings")["settings"]["guidance"]["value"]  # noqa: E731
    for value, field in (("like", "like_categories"), ("less", "less_categories"), ("exclude", "exclude_categories")):
        page.click(f"label[for=set-g-kind-0-{value}]")
        page.wait_for_function("() => /Saved\\./.test(document.querySelector('#set-g-kinds-msg').textContent)", timeout=10000)
        if not mock:
            g = guidance()
            check(f"[{tag}] {first_kind}: {value} is saved in {field} and in no other list",
                  g[field] == [first_kind] and sum(first_kind in g[f] for f in ("like_categories", "less_categories", "exclude_categories")) == 1, json.dumps(g))
        page.evaluate("document.querySelector('#set-g-kinds-msg').textContent = ''")
    page.click("label[for=set-g-kind-0-none]")
    page.wait_for_function("() => /Saved\\./.test(document.querySelector('#set-g-kinds-msg').textContent)", timeout=10000)
    if not mock:
        g = guidance()
        check(f"[{tag}] None takes the kind out of all three lists", not any(g[f] for f in ("like_categories", "less_categories", "exclude_categories")), json.dumps(g))
    page.click("label[for=set-g-kind-1-like]")
    page.wait_for_function("() => document.querySelector('#set-g-kind-1-like').checked", timeout=10000)
    shot(page, out, f"settings-kinds-{tag}")

    # learned
    learned = page.locator("#set-g-prefs .g-learned")
    text = learned.inner_text()
    check(f"[{tag}] Learned from your log lists what the app saw, with the reason", "Learned from your log" in text and "Eaten on" in text and "of the last 14 days" in text, text[:200])
    check(f"[{tag}] every learned food has Keep and Stop using this; every usual meal Save as a meal and Not this meal",
          page.locator("#set-g-prefs .g-learned li.g-pref-row button:has-text('Keep')").count() >= 1
          and page.locator("#set-g-prefs .g-learned li.g-pref-row button:has-text('Stop using this')").count() >= 1
          and page.locator("#set-g-prefs .g-learned li.g-pref-row button:has-text('Save as a meal')").count() >= 1
          and page.locator("#set-g-prefs .g-learned li.g-pref-row button:has-text('Not this meal')").count() >= 1)
    section_top(page)
    page.locator("#set-g-learned-h").scroll_into_view_if_needed()
    shot(page, out, f"settings-learned-{tag}")
    keep_row = page.locator("#set-g-prefs .g-learned .g-learned-list li.g-pref-row", has=page.locator("button:has-text('Keep')")).first
    keep_name = keep_row.locator(".row-title").inner_text()
    keep_row.get_by_role("button", name=f"Keep {keep_name} as more like this").click()
    wait_toast(page, f"{keep_name} is now under “More like this”.")
    page.wait_for_function("(n) => [...document.querySelectorAll('#set-g-pref-list-like li.g-pref-row .row-title')].some((e) => e.textContent === n)", arg=keep_name, timeout=10000)
    check(f"[{tag}] Keep makes it an explicit like (listed under More like this, the learned row says Kept)", keep_name in list_names(page, "like")
          and "Kept: More like this" in page.locator("#set-g-prefs .g-learned").inner_text())
    if not mock:
        check(f"[{tag}] the server holds the kept food as a like", "like" in pref_map(api).values())
    stop_row = page.locator("#set-g-prefs .g-learned .g-learned-list li.g-pref-row", has=page.locator("button:has-text('Stop using this')")).first
    stop_name = stop_row.locator(".row-title").inner_text()
    stop_row.get_by_role("button", name=f"Stop using what the app saw about {stop_name}").click()
    wait_toast(page, f"{stop_name}: the app will stop using what it saw in your log.")
    page.wait_for_selector("#set-g-neutral-list", timeout=10000)
    check(f"[{tag}] Stop using this lists the food under Not learning about", stop_name in page.inner_text("#set-g-neutral-list")
          and "not learning about" in page.inner_text("#set-g-prefs .g-learned").lower())
    if not mock:
        check(f"[{tag}] the server holds 'neutral' for it", "neutral" in pref_map(api).values())
    check(f"[{tag}] a food stopped is no longer in the learned lists", stop_name not in page.locator("#set-g-prefs .g-learned .g-learned-list .row-title").all_inner_texts()
          or page.locator("#set-g-prefs .g-learned .g-learned-list .row-title", has_text=stop_name).count() == 0)
    page.locator("#set-g-neutral-list").scroll_into_view_if_needed()
    shot(page, out, f"settings-neutral-{tag}")
    page.get_by_role("button", name=f"Learn about {stop_name} again").click()
    wait_toast(page, f"{stop_name}: the app can use your log for this food again.")
    page.wait_for_function("() => !document.querySelector('#set-g-neutral-list')", timeout=10000)
    check(f"[{tag}] Learn again takes it back (the section is gone, the food learns again)", True)
    # usual meals: Save as a meal, Not this meal, Show them again
    meal_row = page.locator("#set-g-prefs .g-learned li.g-pref-row", has=page.locator("button:has-text('Save as a meal')")).first
    meal_name = meal_row.locator(".row-title").inner_text()
    meal_row.get_by_role("button", name=f"Save {meal_name} as a meal").click()
    page.wait_for_selector("#sheet-meal[open]", timeout=15000)
    foods = page.locator("#meal-items li.meal-item .row-title").all_inner_texts()
    check(f"[{tag}] Save as a meal opens a new saved meal with the usual meal's foods", page.inner_text("#sheet-meal-title") == "New saved meal"
          and page.input_value("#meal-name") == meal_name[:80] and len(foods) >= 2 and page.is_hidden("#meal-delete"), f"{foods} {page.input_value('#meal-name')}")
    check(f"[{tag}] its 'Meant for' is the meal it was eaten at", page.input_value("#meal-hint") in ("breakfast", "lunch", "dinner", "snack"), page.input_value("#meal-hint"))
    shot(page, out, f"settings-save-meal-{tag}")
    page.fill("#meal-name", f"Usual lunch {tag}")
    page.click("#meal-save")
    page.wait_for_selector("#sheet-meal", state="hidden", timeout=15000)
    if not mock:
        names_saved = [m["name"] for m in api.json("GET", "/api/meals")["meals"]]
        check(f"[{tag}] the meal is saved with those foods", f"Usual lunch {tag}" in names_saved, str(names_saved))
    page.wait_for_selector("#set-g-prefs .g-learned li.g-pref-row")
    meal_row = page.locator("#set-g-prefs .g-learned li.g-pref-row", has=page.locator("button:has-text('Not this meal')")).first
    meal_name = meal_row.locator(".row-title").inner_text()
    meals_before = page.locator("#set-g-prefs .g-learned li.g-pref-row button:has-text('Not this meal')").count()
    meal_row.get_by_role("button", name=f"Not this meal: {meal_name}").click()
    wait_toast(page, "will not be offered as a usual meal.")
    page.wait_for_selector("#set-g-hidden-usual-meals", timeout=10000)
    check(f"[{tag}] Not this meal hides it and says how many are hidden", "You hid 1 usual meal" in page.inner_text("#set-g-hidden-usual-meals"), page.inner_text("#set-g-hidden-usual-meals"))
    if not mock:
        g = guidance()
        check(f"[{tag}] its key is in hidden_usual_meals", len(g["hidden_usual_meals"]) == 1 and g["hidden_usual_meals"][0].split(":")[0] in ("breakfast", "lunch", "dinner", "snack"), json.dumps(g["hidden_usual_meals"]))
    check(f"[{tag}] the meal left the learned list", page.locator("#set-g-prefs .g-learned li.g-pref-row button:has-text('Not this meal')").count() == meals_before - 1)
    page.get_by_role("button", name="Show them again").click()
    page.wait_for_function("() => !document.querySelector('#set-g-hidden-usual-meals')", timeout=10000)
    if not mock:
        check(f"[{tag}] Show them again empties hidden_usual_meals", guidance()["hidden_usual_meals"] == [])

    # Learn from my log
    page.locator("label[for=set-g-learn-from-log]").scroll_into_view_if_needed()
    page.click("label[for=set-g-learn-from-log]")
    page.wait_for_function("() => /Learning from your log is off/.test(document.querySelector('#set-g-prefs .g-learned').textContent)", timeout=10000)
    check(f"[{tag}] switched off, the learned list says nothing from the log changes the suggestions", page.locator("#set-g-prefs .g-learned li.g-pref-row button:has-text('Keep')").count() == 0)
    if not mock:
        check(f"[{tag}] the server holds learn_from_log false", guidance()["learn_from_log"] is False)
    shot(page, out, f"settings-learn-off-{tag}")
    page.click("label[for=set-g-learn-from-log]")
    page.wait_for_selector("#set-g-prefs .g-learned li.g-pref-row button:has-text('Keep'), #set-g-prefs .g-learned li.g-pref-row:has-text('Kept')", timeout=10000)
    if not mock:
        check(f"[{tag}] switched on again, the list is back", guidance()["learn_from_log"] is True)

    # the text for AI ideas
    ai_field = page.locator("#set-g-prefs .g-ai-pref label:has-text('Food preferences for AI ideas')")
    if mock:
        check(f"[{tag}] the demo has no AI, so no text for AI ideas in this section", ai_field.count() == 0 and "AI ideas" not in page.inner_text("#set-g-prefs").split("Learned from your log")[-1][:0])
    else:
        page.wait_for_selector("#set-g-prefs .g-ai-pref input", timeout=15000)
        page.locator("#set-g-prefs .g-ai-pref input").scroll_into_view_if_needed()
        page.fill("#set-g-prefs .g-ai-pref input", "vegetarian, no fish")
        with page.expect_response(lambda r: r.url.endswith("/api/me/ai") and r.request.method == "PATCH"):
            page.click("#set-g-prefs .g-ai-pref button:has-text('Save')")
        page.wait_for_function("() => /Preferences saved/.test(document.querySelector('#set-g-prefs .g-ai-pref .status-msg').textContent)", timeout=10000)
        check(f"[{tag}] the text for AI ideas is saved through the same call (ai.preferences)", api.json("GET", "/api/me/ai")["settings"]["preferences"] == "vegetarian, no fish")
        shot(page, out, f"settings-ai-text-{tag}")
        page.locator("#set-ai-pref-moved").scroll_into_view_if_needed()
        moved = page.inner_text("#set-ai-pref-moved")
        check(f"[{tag}] Settings → AI features has one line pointing to the new place, and no field", "Your food preferences for AI ideas are in" in moved
              and page.locator("#set-ai-body label:has-text('Food preferences for AI ideas')").count() == 0, moved)
        page.locator("#set-ai-pref-moved button").click()
        page.wait_for_function("() => document.activeElement && document.activeElement.id === 'set-g-prefs-h'", timeout=10000)
        check(f"[{tag}] the link takes the person to Your food preferences", True)
        api.json("PATCH", "/api/me/ai", {"preferences": ""})
    if phone:
        tap_targets(page, tag)


def part_offline(page: Any, ctx: Any, api: Any, out: Path, tag: str, watch: Watch) -> None:
    # an online page, then the network goes: a save says so and changes nothing
    open_fits(page)
    row = page.locator("#guidance-fits-body .g-food").first
    fid = int(row.get_attribute("data-food-id"))
    name = row.locator(".row-title").inner_text()
    row.locator("button.g-more").click()
    page.wait_for_function("(el) => !el.hasAttribute('aria-busy')", arg=row.locator(".g-menu").element_handle(), timeout=10000)
    ctx.set_offline(True)
    before = pref_map(api)
    row.locator("button[data-pref=not_for_me]").click()
    wait_toast(page, OFFLINE_WRITE)
    check(f"[{tag}] offline, Not for me says the change needs a connection and the food stays", page.locator(f"#guidance-fits-body [data-food-id='{fid}']").count() == 1
          and pressed(row.locator("button[data-pref=not_for_me]")) == "false" and name, toast(page))
    shot(page, out, f"offline-menu-{tag}")
    waiting = page.evaluate("() => KH.offline.pendingCount()")
    ctx.set_offline(False)
    check(f"[{tag}] nothing was queued and the server's list is unchanged", pref_map(api) == before and not waiting, f"{pref_map(api)} {before}")
    # Settings online, then offline: a switch and a kind of food refuse in words, the lists say they need a connection
    open_settings(page)
    ctx.set_offline(True)
    page.locator("label[for=set-g-learn-from-log]").scroll_into_view_if_needed()
    page.click("label[for=set-g-learn-from-log]")
    page.wait_for_function("() => /cannot be reached/.test(document.querySelector('#set-g-learn-error').textContent)", timeout=15000)
    check(f"[{tag}] offline, the switch says the change needs a connection and goes back", page.is_checked("#set-g-learn-from-log"))
    page.click("label[for=set-g-kind-0-like]")
    page.wait_for_function("() => /cannot be reached/.test(document.querySelector('#set-g-kinds-error').textContent)", timeout=15000)
    check(f"[{tag}] offline, a kind of food goes back to what it was", page.is_checked("#set-g-kind-0-none"))
    shot(page, out, f"offline-settings-{tag}")
    page.click("#tab-today")
    page.click("#settings-open")
    page.wait_for_selector("#set-g-prefs .g-pref-foods", timeout=15000)
    page.wait_for_function("() => document.querySelector('#set-g-prefs .g-pref-foods').textContent.includes('Guidance needs a connection')", timeout=15000)
    check(f"[{tag}] offline, the lists say Guidance needs a connection to your server.", NEEDS_CONNECTION in page.inner_text("#set-g-prefs .g-pref-foods")
          and NEEDS_CONNECTION in page.inner_text("#set-g-prefs .g-learned"))
    ctx.set_offline(False)
    expected = [e for e in watch.errors if "ERR_INTERNET_DISCONNECTED" in e or "cannot be reached" in e]
    check(f"[{tag}] the only console errors while offline are the refused requests and their messages", expected == watch.errors, str(watch.errors)[:300])
    watch.errors.clear()


# --------------------------------------------------------------------------------------------------------------- passes
def finish(page: Any, watch: Watch, tag: str, base: str, mock: bool) -> None:
    check(f"[{tag}] no sideways scroll", not overflow(page))
    check(f"[{tag}] no console error, no page error, no dialog", not watch.errors and not watch.dialogs, "; ".join(watch.errors)[:300])
    if not mock:
        others = sorted(h for h in watch.hosts if h != urlsplit(base).netloc)
        check(f"[{tag}] the browser asked no other host", not others, str(others))
    else:
        check(f"[{tag}] the demo sent nothing to a server", not watch.writes, str(watch.writes[:3]))


def real_pass(browser: Any, admin: Any, sam: Any, ids: dict[str, int], base: str, out: Path, width: int, height: int, scheme: str, parts: set[str]) -> None:
    tag = f"{width}-{scheme}"
    reset(admin)
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    page.goto("/")
    page.wait_for_selector("#tab-today", state="visible", timeout=30000)
    if "menu" in parts:
        part_menu(page, admin, out, tag, mock=False)
    reset(admin)
    if "swaps" in parts:
        part_swaps(page, admin, out, tag)
    reset(admin)
    if "plan" in parts:
        part_plan(page, admin, out, tag)
    reset(admin)
    if "settings" in parts:
        part_settings(page, admin, out, tag, mock=False, phone=width < 500)
        check(f"[{tag}] the second person's preference is on no page", "secret stew" not in page.inner_text("body").lower())
    reset(admin)
    if "low" in parts:
        part_low(page, admin, out, tag)
    reset(admin)
    if "offline" in parts and width < 500:
        part_offline(page, ctx, admin, out, tag, watch)
    check(f"[{tag}] the second person still has their own preference", pref_map(sam).get(ids["secret"]) == "like", str(pref_map(sam)))
    finish(page, watch, tag, base, mock=False)
    ctx.close()


def serve(site: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://localhost:{httpd.server_address[1]}"


def part_low_demo(page: Any, out: Path, tag: str) -> None:
    """The demo's twin of ``part_low``: every low treatment on Not for me, and Treating a low still lists them with the note."""
    ids = page.evaluate("async () => (await KH.guidance.api.hypoOptions()).options.map((o) => o.food_id)")
    check(f"[{tag}] the demo has low-treatment foods", len(ids) >= 1, str(ids))
    for fid in ids:
        page.evaluate("(id) => KH.guidance.api.setPreference(id, 'not_for_me')", fid)
    open_tab(page, "today", "#guidance-today-actions .g-low-btn")
    page.click("#guidance-today-actions .g-low-btn")
    page.wait_for_selector("#sheet-guidance .g-low .g-foods .g-food", timeout=20000)
    text = page.inner_text("#sheet-guidance")
    check(f"[{tag}] every low treatment is on Not for me, yet Treating a low lists them with the note", SHOWN_DESPITE in text, text[-300:])
    check(f"[{tag}] no row of Treating a low has a preference menu", page.locator("#sheet-guidance .g-low button.g-more").count() == 0)
    shot(page, out, f"low-{tag}")
    page.click("#sheet-guidance [data-close]")


def demo_pass(browser: Any, base: str, out: Path, width: int, height: int, scheme: str) -> None:
    tag = f"demo-{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    page = ctx.new_page()
    watch = Watch(page)
    page.goto("/")
    page.wait_for_selector("#tab-today", state="visible", timeout=30000)
    part_menu(page, None, out, tag, mock=True)
    page.reload()  # the demo keeps its data in the page: a reload starts over
    page.wait_for_selector("#tab-today", state="visible", timeout=30000)
    part_settings(page, None, out, tag, mock=True, phone=width < 500)
    part_low_demo(page, out, tag)
    finish(page, watch, tag, base, mock=True)
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default=",".join(PARTS), help="comma-separated parts: " + ", ".join(PARTS))
    args = ap.parse_args(argv)
    parts = {p.strip() for p in args.only.split(",") if p.strip()}
    if not parts <= set(PARTS):
        print(f"unknown part(s): {sorted(parts - set(PARTS))}", file=sys.stderr)
        return 2
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "AI_ENABLED": "true"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    httpd = None
    try:
        server.start()
        admin = first_admin(server, USER)
        sam = invite_user(server, admin, "sam")
        ids = seed(admin, sam)
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                real_parts = parts - {"demo"}
                if real_parts:
                    for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                        real_pass(browser, admin, sam, ids, base, out, width, height, scheme, real_parts)
                if "demo" in parts:
                    site = out / "pages"
                    subprocess.run([sys.executable, str(REPO / "scripts" / "build_preview.py"), "--pages", str(site)], check=True, capture_output=True)
                    httpd, demo_base = serve(site)
                    for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                        demo_pass(browser, demo_base, out, width, height, scheme)
            finally:
                browser.close()
        admin.close()
        sam.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        if httpd is not None:
            httpd.shutdown()
        server.stop()
    (out / "report.json").write_text(json.dumps(RESULTS, indent=1) + "\n", encoding="utf-8")
    failed = [r["check"] for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report: {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
