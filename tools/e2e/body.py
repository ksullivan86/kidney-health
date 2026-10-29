#!/usr/bin/env python3
"""Weight and blood pressure (schema step 18, note 10 Part B) in Chromium, against a real server and the demo.

    python tools/e2e/body.py                       # port 8079
    python tools/e2e/body.py --port 8079 --out /tmp/kh-body

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``HANDBOOK_PUBLIC_URL`` set (so the Get help now link has a place to go),
finishes first-run setup and invites a few people (one per pass, and a second person with data of their own). Then, in a full walk at
375x812 light and at 1280x800 dark, and in a shorter walk at 375x812 dark and 1280x800 light:

* Today: the card under Symptoms with Add weight and Add blood pressure (44 px tall); the weight sheet in the person's unit (pounds), the
  other unit echoed ("154.3 lb = 70.0 kg"), when it was taken (morning / other: no dialysis choices off dialysis), nothing saved until Save
  and the missing things said in words; add, edit (a note-only edit keeps the stored weight to the hundredth) and delete (asked in the
  page, no browser dialog); the blood pressure sheet with the top number then the bottom number, the one hint, the echo ("Top 180, bottom
  95") and, for 180/95, the handbook's block in the sheet before Save; a 180/95 reading saved shows the prominent block first on Today
  with the server's own words (checked against ``flag.text``) and the 911 quote before the care-team line, and a link ending in
  ``/get-help-now/``; editing it to a normal reading takes the block away; a save without a connection says so and saves nothing;
* Settings: the unit, the alarm ("Call my team if my weight goes up by more than ... in 1 day") and the goal, saved in kilograms; the
  Today card then names the two weights it compared and says "Over your alarm" with the handbook's line for a weight, and the goal line
  gives the 7-day average;
* Trends: the weight chart and the blood pressure chart as SVG, one mark per row, a table under each with every row, the goal as
  dashed lines, the 7-day averages, and (on hemodialysis) the dry weight as a dashed line and a diamond for each weight after dialysis;
  no inline style anywhere in them;
* Profile: "Latest in your log ... Use this" under Weight and "In your log ... Use this" under Weight 6 months ago, each only filling the
  box (the saved profile is unchanged until Save profile); the first is hidden when the form says dialysis, the second is not;
* Visit prep: the weight and blood pressure section (latest weight, six-month change, 7-day and 30-day averages, readings at or above
  the goal, the flagged reading with its date and the handbook's block) and, on hemodialysis, the gains between sessions with "over
  your alarm";
* the Apple Health buttons (Trends and Settings → Your data) are hidden until a ``KH.bodyImport`` exists, then call its ``open()``;
* the other person's weights and readings are on no page; the browser asked no other host and sent no write to a path outside
  ``/api/body`` (and the settings, profile) ones; no console error, no CSP violation, no sideways scroll, no browser dialog;
* the demo (``/?mock=1``) does the add, edit and delete with its own data (its sample data has one weight over the sample alarm and no
  reading at 180/120, so no emergency block until one is saved), the charts, Settings, Profile and visit prep, and
  ``/?mock=1&hd=1`` the dialysis version.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on
any failure. The server is always stopped.
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
from khserver import Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "body"
PORT = 8079
RESULTS: list[dict[str, Any]] = []
HANDBOOK = "https://handbook.example.org/"
TODAY = date.today()
KG_PER_LB = 0.45359237


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def iso(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


class Watch:
    """Hosts asked, writes made, dialogs, console errors, page errors and CSP violations of one page."""

    def __init__(self, page: Any) -> None:
        self.hosts: set[str] = set()
        self.writes: list[tuple[str, str]] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self.offline = False  # while the harness has cut the connection, the browser's own "failed to load" lines are expected
        page.on("request", self._request)
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)
        page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")

    def _console(self, m: Any) -> None:
        if m.type == "error" and not (self.offline and "Failed to load resource" in m.text):
            self.errors.append(m.text)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def _request(self, r: Any) -> None:
        parts = urlsplit(r.url)
        if parts.scheme in ("http", "https"):
            self.hosts.add(parts.netloc)
        if r.method != "GET":
            self.writes.append((r.method, parts.path))


def body_writes(watch: Watch, since: int = 0) -> list[tuple[str, str]]:
    return [w for w in watch.writes[since:] if w[1].startswith("/api/body")]


# ------------------------------------------------------------------------------------------------ small helpers
def say(page: Any) -> str:
    return page.inner_text("#body-today-body")


def wait_today(page: Any, text: str | None = None, timeout: int = 15000) -> None:
    """The card has drawn (and, with ``text``, says it)."""
    if text is None:
        page.wait_for_function("() => document.querySelector('#body-today-body') && document.querySelector('#body-today-body').children.length > 0 && !document.querySelector('#body-today-loading')", timeout=timeout)
    else:
        page.wait_for_function("(t) => document.querySelector('#body-today-body') && document.querySelector('#body-today-body').innerText.includes(t)", arg=text, timeout=timeout)


def open_settings(page: Any) -> None:
    page.click("#settings-open")
    page.wait_for_selector("#set-body-alarm", timeout=20000)


def go_today(page: Any) -> None:
    page.click("#tab-today")
    page.wait_for_selector("#body-add-weight", state="visible", timeout=20000)
    wait_today(page)


def add_weight(page: Any, text: str, context: str, note: str = "", time: str = "") -> None:
    page.click("#body-add-weight")
    page.wait_for_selector("#sheet-weight[open]", timeout=10000)
    page.fill("#weight-value", text)
    page.click(f"label[for=weight-context-{context.replace('_', '-')}]")
    if time:
        page.fill("#weight-time", time)
    if note:
        page.fill("#weight-note", note)
    page.click("#weight-save")
    page.wait_for_selector("#sheet-weight", state="hidden", timeout=10000)


def add_reading(page: Any, top: str, bottom: str, context: str, pulse: str = "", note: str = "") -> None:
    page.click("#body-add-bp")
    page.wait_for_selector("#sheet-bp[open]", timeout=10000)
    page.fill("#bp-systolic", top)
    page.fill("#bp-diastolic", bottom)
    if pulse:
        page.fill("#bp-pulse", pulse)
    page.click(f"label[for=bp-context-{context.replace('_', '-')}]")
    if note:
        page.fill("#bp-note", note)
    page.click("#bp-save")
    page.wait_for_selector("#sheet-bp", state="hidden", timeout=10000)


def seed(person: Any, hd: bool = False) -> None:
    """Fifteen days of weights and readings; the days before today only (today's are added in the walk)."""
    for back in range(15, 0, -1):
        day = iso(-back)
        if hd and back % 2 == 0:
            person.json("POST", "/api/body/weights", {"date": day, "time": "06:40", "kg": 71.0 + (back % 3) * 0.3, "context": "before_dialysis"})
            person.json("POST", "/api/body/weights", {"date": day, "time": "11:20", "kg": 70.0 + (back % 2) * 0.1, "context": "after_dialysis"})
        else:
            person.json("POST", "/api/body/weights", {"date": day, "time": "07:15", "kg": 70.0 + (back % 4) * 0.1, "context": "morning"})
        person.json("POST", "/api/body/blood-pressure", {"date": day, "time": "07:20", "systolic": 126 + (back * 3) % 12, "diastolic": 76 + (back * 2) % 8, "pulse": 64, "context": "morning"})


def set_settings(person: Any, values: dict[str, Any]) -> None:
    person.json("PATCH", "/api/me/settings", values)


class Pass:
    """One person, one browser context, one page, one tag for the messages."""

    def __init__(self, browser: Any, base: str, out: Path, width: int, height: int, scheme: str, tag: str, cookies: dict[str, str] | None = None) -> None:
        self.base, self.out, self.width, self.tag = base, out, width, tag
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
        if cookies:
            self.ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in cookies.items()])
        self.page = self.ctx.new_page()
        self.watch = Watch(self.page)

    def shot(self, name: str) -> None:
        self.page.screenshot(path=str(self.out / "shots" / f"{name}-{self.tag}.png"))

    def finish(self, server_mode: bool, base: str) -> None:
        csp = self.page.evaluate("window.__csp || []")
        check(f"[{self.tag}] no console error, no CSP violation, no browser dialog", not self.watch.errors and not csp and not self.watch.dialogs,
              "; ".join(self.watch.errors + csp + self.watch.dialogs))
        if server_mode:
            others = sorted(h for h in self.watch.hosts if h != urlsplit(base).netloc)
            check(f"[{self.tag}] the browser asked no other host", not others, str(others))
        self.ctx.close()


# ------------------------------------------------------------------------------------------------ the walk
def walk_today(p: Pass, person: Any | None, mock: bool, hd: bool = False) -> None:
    page, tag = p.page, p.tag
    page.goto("/?mock=1" if mock else "/")
    page.wait_for_selector("#body-add-weight", state="visible", timeout=30000)
    wait_today(page)
    h = page.evaluate("[document.querySelector('#body-add-weight'), document.querySelector('#body-add-bp')].map((b) => b.getBoundingClientRect().height)")
    check(f"[{tag}] the two Add buttons are at least 44 px tall", min(h) >= 44, str(h))
    check(f"[{tag}] the card sits under Symptoms and above the meal ideas",
          page.evaluate("() => { const a = document.querySelector('#symptoms-today'), b = document.querySelector('#body-today'); "
                        "return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING); }"))
    if not mock:
        check(f"[{tag}] an empty day says so, and says where the care team's numbers go", "No weight or blood pressure recorded" in say(page) and "Settings" in say(page), say(page))
    p.shot("today-empty")

    # ---- the weight sheet
    mark = len(p.watch.writes)
    page.click("#body-add-weight")
    page.wait_for_selector("#sheet-weight[open]", timeout=10000)
    wanted = ["Morning", "Before dialysis", "After dialysis", "Other"] if hd else ["Morning", "Other"]
    check(f"[{tag}] the weight sheet is in pounds and offers the dialysis choices only on dialysis", page.inner_text("#weight-label") == "Weight (lb)" and
          page.locator("#weight-context label").all_inner_texts() == wanted, str(page.locator("#weight-context label").all_inner_texts()))
    page.click("#weight-save")
    check(f"[{tag}] Save with nothing typed says what is missing and writes nothing", "Enter your weight" in page.inner_text("#weight-error") and not body_writes(p.watch, mark))
    page.fill("#weight-value", "154.3")
    check(f"[{tag}] the other unit is echoed", page.inner_text("#weight-echo") == "154.3 lb = 70.0 kg", page.inner_text("#weight-echo"))
    page.click("#weight-save")
    check(f"[{tag}] Save without saying when it was taken says so and writes nothing", "Choose when it was taken" in page.inner_text("#weight-error") and not body_writes(p.watch, mark))
    page.fill("#weight-value", "20")
    page.click("#weight-save")
    check(f"[{tag}] a weight that cannot be right is refused in the person's unit", "between 44.1 and 881.8 lb" in page.inner_text("#weight-error"), page.inner_text("#weight-error"))
    page.fill("#weight-value", "154.3")
    page.click("label[for=weight-context-morning]")
    p.shot("weight-sheet")
    page.click("#sheet-weight [data-close].btn")
    page.wait_for_selector("#sheet-weight", state="hidden", timeout=10000)
    check(f"[{tag}] closing the sheet saved nothing", not body_writes(p.watch, mark) and "154.3" not in say(page))
    add_weight(page, "154.3", "morning", note="<b>bathroom scale</b>", time="07:15")
    wait_today(page, "154.3 lb")
    check(f"[{tag}] the weight is listed in pounds with its kind and time, a note as text only",
          "154.3 lb" in say(page) and "Morning, 7:15 AM" in say(page) and "<b>bathroom scale</b>" in say(page) and page.locator("#body-today-body b").count() <= 2)
    if person is not None:
        rows = person.json("GET", "/api/body/weights", params={"start": iso(0), "end": iso(0)})["weights"]
        check(f"[{tag}] the server holds 69.99 kg, the 154.3 lb converted", [r["kg"] for r in rows] == [round(154.3 * KG_PER_LB, 2)] and rows[0]["source"] == "manual", str(rows))

    # ---- edit: the weight as shown, a note-only edit keeps the stored weight
    if person is not None:
        kept = person.json("POST", "/api/body/weights", {"date": iso(0), "time": "20:00", "kg": 70.23, "context": "other", "note": ""})
        page.reload()
        page.wait_for_selector("#body-add-weight", state="visible", timeout=30000)
        wait_today(page, "Other")
        page.locator(".body-item", has_text="Other").get_by_role("button", name="Edit").click()
        page.wait_for_selector("#sheet-weight[open]", timeout=10000)
        check(f"[{tag}] edit opens with the saved values", page.input_value("#weight-value") == "154.8" and page.is_checked("#weight-context-other"), page.input_value("#weight-value"))
        page.fill("#weight-note", "after lunch")
        page.click("#weight-save")
        page.wait_for_selector("#sheet-weight", state="hidden", timeout=10000)
        wait_today(page, "after lunch")
        after = person.json("GET", "/api/body/weights", params={"start": iso(0), "end": iso(0)})["weights"]
        check(f"[{tag}] a note-only edit keeps the stored weight to the hundredth (70.23 kg, not 154.8 lb converted back)",
              [r["kg"] for r in after if r["id"] == kept["id"]] == [70.23], str(after))
        page.locator(".body-item", has_text="Other").get_by_role("button", name="Delete").click()
        page.wait_for_selector(".confirm-row", timeout=10000)
        check(f"[{tag}] delete asks in the page, with no browser dialog", not p.watch.dialogs and "Delete the weight" in page.inner_text(".confirm-row"), page.inner_text(".confirm-row"))
        page.click(".confirm-row .btn.danger-solid")
        page.wait_for_function("() => document.querySelectorAll('#body-today-body .body-item').length === 1", timeout=10000)

    # ---- the blood pressure sheet
    page.click("#body-add-bp")
    page.wait_for_selector("#sheet-bp[open]", timeout=10000)
    order = page.evaluate("() => ['bp-systolic', 'bp-diastolic', 'bp-pulse'].map((id) => document.getElementById(id).getBoundingClientRect().top)")
    check(f"[{tag}] the top number comes first and both have plain names",
          order[0] <= order[1] <= order[2] and "Top number (systolic)" in page.inner_text("#sheet-bp") and "Bottom number (diastolic)" in page.inner_text("#sheet-bp"))
    check(f"[{tag}] the sheet says how to measure in one line",
          "Rest about 5 minutes first, sit with your feet flat, and put the cuff on your upper arm." in page.inner_text("#bp-hint"), page.inner_text("#bp-hint"))
    how = page.locator("#bp-hint a")
    check(f"[{tag}] the hint links to How to measure on the handbook's page", how.count() == 1 and how.get_attribute("href") == HANDBOOK + "app/weight-and-blood-pressure/#how-to-measure",
          how.get_attribute("href") if how.count() else "no link")
    page.fill("#bp-systolic", "180")
    page.fill("#bp-diastolic", "95")
    check(f"[{tag}] the reading is echoed before Save", page.inner_text("#bp-echo") == "Top 180, bottom 95", page.inner_text("#bp-echo"))
    flag = page.inner_text("#bp-flag")
    check(f"[{tag}] a very high reading shows the handbook's block in the sheet, the 911 line first",
          "Call 911 now" in flag and flag.index("Call 911 now") < flag.index("Call your care team today") and page.locator("#bp-flag .body-flag.prominent").count() == 1, flag)
    page.fill("#bp-diastolic", "59")
    check(f"[{tag}] a slip (59 for 95) is seen in the echo", page.inner_text("#bp-echo") == "Top 180, bottom 59", page.inner_text("#bp-echo"))
    page.fill("#bp-systolic", "40")
    page.click("#bp-save")
    check(f"[{tag}] a number out of range is refused in words", "between 50 and 300" in page.inner_text("#bp-error"), page.inner_text("#bp-error"))
    page.fill("#bp-systolic", "95")
    page.fill("#bp-diastolic", "180")
    page.click("#bp-save")
    check(f"[{tag}] a bottom number that is not below the top one is refused", "top number must be higher" in page.inner_text("#bp-error"), page.inner_text("#bp-error"))
    page.fill("#bp-systolic", "132")
    page.fill("#bp-diastolic", "82")
    check(f"[{tag}] a normal reading shows no block", page.inner_text("#bp-flag").strip() == "")
    page.click("#bp-save")
    check(f"[{tag}] Save without saying when it was measured says so", "Choose when it was taken" in page.inner_text("#bp-error"), page.inner_text("#bp-error"))
    p.shot("bp-sheet")
    page.click("#sheet-bp [data-close].btn")
    page.wait_for_selector("#sheet-bp", state="hidden", timeout=10000)

    # ---- a 180/95 reading: the prominent block, first, with the server's words
    add_reading(page, "180", "95", "evening", pulse="82")
    wait_today(page, "180/95")
    block = page.locator("#body-today-body > .body-flag.prominent")
    check(f"[{tag}] the block for a very high reading is the first thing on the card and prominent", block.count() == 1 and
          page.evaluate("() => document.querySelector('#body-today-body').firstElementChild.classList.contains('prominent')"))
    text = block.inner_text()
    twin = page.evaluate("KH.bodyRules.flagOf('blood_pressure').text")
    server_text = None
    if person is not None:
        reading = person.json("GET", "/api/body/blood-pressure", params={"start": iso(0), "end": iso(0)})["readings"]
        server_text = [r for r in reading if r["systolic"] == 180][0]["flag"]["text"]
    check(f"[{tag}] it quotes the handbook's own words: the server's text as is (and the twin's copy is the same)",
          twin in text and (server_text is None or (server_text in text and server_text == twin)), text)
    check(f"[{tag}] the 911 line comes first, then rest 5 minutes and measure again", text.index("Call 911 now") < text.index("Call your care team today")
          and text.index("with a sudden severe headache") < text.index("that is still that high"), text)
    check(f"[{tag}] it names the reading", "Reading 180/95" in text, text)
    link = block.locator("a")
    if mock:
        check(f"[{tag}] the demo has no handbook to link to, so no link, and the words stay", link.count() == 0)
    else:
        check(f"[{tag}] the link goes to the handbook's Get help now page", link.count() == 1 and link.get_attribute("href") == HANDBOOK + "get-help-now/" and link.get_attribute("target") == "_blank",
              link.get_attribute("href") if link.count() else "no link")
    check(f"[{tag}] the reading's own row is marked in words, not only in colour", "See the handbook note" in say(page))
    p.shot("today-flag")
    # edit it to a normal reading: the block goes
    page.locator(".body-item.flagged").get_by_role("button", name="Edit").click()
    page.wait_for_selector("#sheet-bp[open]", timeout=10000)
    check(f"[{tag}] edit opens with the saved reading", page.input_value("#bp-systolic") == "180" and page.input_value("#bp-diastolic") == "95" and page.input_value("#bp-pulse") == "82"
          and page.is_checked("#bp-context-evening"))
    page.fill("#bp-systolic", "128")
    page.fill("#bp-diastolic", "78")
    page.click("#bp-save")
    page.wait_for_selector("#sheet-bp", state="hidden", timeout=10000)
    page.wait_for_function("() => !document.querySelector('#body-today-body .body-flag.prominent')", timeout=10000)
    wait_today(page)
    check(f"[{tag}] edited to a normal reading, the block is gone and the new numbers are shown", "128/78" in say(page) and "180/95" not in say(page))
    # a note is text, delete asks first
    page.locator(".body-item", has_text="128/78").get_by_role("button", name="Delete").click()
    page.wait_for_selector(".confirm-row", timeout=10000)
    page.click(".confirm-row .btn.danger-solid")
    page.wait_for_function("() => !document.querySelector('#body-today-body').innerText.includes('128/78')", timeout=10000)
    check(f"[{tag}] the reading is deleted", "128/78" not in say(page))

    # ---- a save without a connection says so
    if not mock:
        p.ctx.set_offline(True)
        p.watch.offline = True
        page.click("#body-add-weight")
        page.wait_for_selector("#sheet-weight[open]", timeout=10000)
        page.fill("#weight-value", "150")
        page.click("label[for=weight-context-morning]")
        page.click("#weight-save")
        page.wait_for_function("() => document.querySelector('#weight-error') && !document.querySelector('#weight-error').hidden", timeout=15000)
        err = page.inner_text("#weight-error")
        check(f"[{tag}] a save offline says the connection is needed and keeps the sheet", "need a connection to your server" in err and "Nothing was saved" in err
              and page.evaluate("document.querySelector('#sheet-weight').open") and page.input_value("#weight-value") == "150", err)
        p.ctx.set_offline(False)
        p.watch.offline = False
        page.click("#sheet-weight [data-close].btn")
        page.wait_for_selector("#sheet-weight", state="hidden", timeout=10000)
        check(f"[{tag}] and nothing was saved", len(person.json("GET", "/api/body/weights", params={"start": iso(0), "end": iso(0)})["weights"]) == 1)
    check(f"[{tag}] nobody else's weight or reading is on the card", "secret" not in page.inner_text("body").lower() and "177/97" not in say(page) and "99.8" not in say(page) and "219.9" not in say(page))


def walk_date_loading(p: Pass) -> None:
    """The other day's rows disappear while delayed reads wait; an old reply cannot restore them."""
    page, tag = p.page, p.tag
    original = say(page)
    yesterday = iso(-1)
    pattern = f"**/api/body/weights?start={yesterday}&end={yesterday}"
    held: list[Any] = []
    page.route(pattern, lambda route: held.append(route))
    try:
        page.click("#date-prev")
        page.wait_for_selector("#body-today-loading")
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        check(f"[{tag}] the delayed date has no old readings, alarm or goal",
              bool(held) and page.locator("#body-today-body .body-item, #body-today-body .body-flag, #body-today-body .body-hint-line").count() == 0)
        page.click("#date-next")
        wait_today(page)
        page.wait_for_function("(text) => document.querySelector('#body-today-body').innerText === text", arg=original)
        for route in held:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"weights": []}))
        held.clear()
        page.wait_for_timeout(100)
        check(f"[{tag}] a late weight reply cannot replace the day shown now", say(page) == original)
    finally:
        page.unroute(pattern)
        for route in held:
            route.abort()


def walk_settings_and_alarm(p: Pass, person: Any | None, mock: bool, hd: bool = False) -> None:
    page, tag = p.page, p.tag
    open_settings(page)
    check(f"[{tag}] Settings has the section with the unit, the alarm and the goal, each saying it is the care team's",
          "from my care team" in page.inner_text("#set-body-alarm") and "care team gave you" in page.inner_text("#set-body-alarm") and "my team: under" in page.inner_text("#set-body-goal")
          and "Unit for weight" in page.inner_text("#set-body"))
    options = page.locator("#set-body-alarm-over option").all_inner_texts()
    check(f"[{tag}] 'between sessions' is offered only on hemodialysis", ("between sessions" in options) == hd, str(options))
    link = page.locator("#set-body a.learn-more")
    check(f"[{tag}] the section links to the handbook page", link.count() == 1 and link.get_attribute("href") == HANDBOOK + "app/weight-and-blood-pressure/",
          link.get_attribute("href") if link.count() else "no link")
    p.shot("settings")
    # the unit: kilograms, echoed in the sheet the other way round, then back to pounds
    page.select_option("#set-body-unit", "kg")
    page.wait_for_function("() => document.querySelector('#set-body-unit-msg') && document.querySelector('#set-body-unit-msg').innerText.includes('kilograms')", timeout=10000)
    check(f"[{tag}] the unit is changed and the box of the alarm is in kilograms", "(kg)" in page.inner_text("#set-body-alarm"))
    go_today(page)
    page.click("#body-add-weight")
    page.wait_for_selector("#sheet-weight[open]", timeout=10000)
    page.fill("#weight-value", "70.2")
    check(f"[{tag}] in kilograms the sheet echoes pounds", page.inner_text("#weight-label") == "Weight (kg)" and page.inner_text("#weight-echo") == "70.2 kg = 154.8 lb", page.inner_text("#weight-echo"))
    page.click("#sheet-weight [data-close].btn")
    page.wait_for_selector("#sheet-weight", state="hidden", timeout=10000)
    open_settings(page)
    page.select_option("#set-body-unit", "lb")
    page.wait_for_function("() => document.querySelector('#set-body-unit-msg') && document.querySelector('#set-body-unit-msg').innerText.includes('pounds')", timeout=10000)
    # the alarm: a bad number is refused next to the box; a good one is saved in kilograms
    page.fill("#set-body-alarm-amount", "abc")
    page.click("#set-body-alarm-save")
    check(f"[{tag}] a number that is not a number is refused next to the alarm box", "Enter a number" in page.inner_text("#set-body-alarm"))
    if hd:
        page.select_option("#set-body-alarm-over", "between_sessions")
        page.fill("#set-body-alarm-amount", "4.4")  # lb: 2.0 kg
    else:
        page.select_option("#set-body-alarm-over", "days")
        page.fill("#set-body-alarm-days", "1")
        page.fill("#set-body-alarm-amount", "2.2")  # lb: 1.0 kg
    sentence = page.inner_text("#set-body-alarm-sentence")
    expected = "Call my team if my weight goes up by more than " + ("4.4 lb between sessions" if hd else "2.2 lb in 1 day")
    check(f"[{tag}] the alarm reads as the sentence the care team gave it", expected in sentence, sentence)
    page.click("#set-body-alarm-save")
    page.wait_for_function("() => document.querySelector('#set-body-alarm-msg').innerText.includes('Saved')", timeout=10000)
    page.fill("#set-body-goal-systolic", "130")
    page.fill("#set-body-goal-diastolic", "130")
    page.click("#set-body-goal-save")
    check(f"[{tag}] a goal with the top number not above the bottom one is refused", "top number must be higher" in page.inner_text("#set-body-goal"), page.inner_text("#set-body-goal"))
    page.fill("#set-body-goal-diastolic", "80")
    page.click("#set-body-goal-save")
    page.wait_for_function("() => document.querySelector('#set-body-goal-msg').innerText.includes('Saved')", timeout=10000)
    if person is not None:
        mine = person.json("GET", "/api/me/settings")["settings"]
        alarm, goal = mine["body.weight_alarm"]["value"], mine["body.bp_goal"]["value"]
        check(f"[{tag}] the server holds the alarm in kilograms and the goal", alarm["amount_kg"] == (2.0 if hd else 1.0) and alarm["over"] == ("between_sessions" if hd else "days")
              and goal == {"systolic": 130, "diastolic": 80}, f"{alarm} {goal}")
    check(f"[{tag}] no sideways scroll on Settings", not overflow(page))
    p.shot("settings-saved")


def walk_alarm_line(p: Pass, person: Any | None, mock: bool, hd: bool) -> None:
    """Today with an alarm and a goal set: the line names the two weights; over it, the handbook's line for a weight."""
    page, tag = p.page, p.tag
    go_today(page)
    if mock:
        wait_today(page, "alarm")
    else:
        # today's weight is over the alarm (+1.5 kg against yesterday's morning weight, or against the weight after the last session)
        if hd:
            person.json("POST", "/api/body/weights", {"date": iso(0), "time": "23:30", "kg": 72.6, "context": "before_dialysis"})
        else:
            person.json("POST", "/api/body/weights", {"date": iso(0), "time": "23:30", "kg": 71.8, "context": "morning"})
        page.reload()
        page.wait_for_selector("#body-add-weight", state="visible", timeout=30000)
        wait_today(page, "alarm")
    line = page.inner_text("#body-alarm-line")
    check(f"[{tag}] the alarm line says it is over the alarm and names the alarm", "Over your alarm" in line and "Your alarm: more than" in line, line)
    check(f"[{tag}] it names the two weights compared, as the server words it", "Compared with your" in line and "Latest:" in line, line)
    check(f"[{tag}] it shows the handbook's line for a weight over the alarm, not prominent",
          "weight gain above the alarm number your team gave you" in line and page.locator("#body-alarm-line .body-flag.prominent").count() == 0, line)
    goal = page.inner_text("#body-goal-line")
    check(f"[{tag}] the goal line gives the goal and the 7-day average", "Blood pressure goal from your care team: under 130/80" in goal and "Last 7 days: average" in goal, goal)
    check(f"[{tag}] no emergency block without a reading at 180/120", page.locator("#body-today-body .body-flag.prominent").count() == 0)
    p.shot("today-alarm")
    check(f"[{tag}] no sideways scroll on Today", not overflow(page))


def open_table(page: Any, block: str) -> int:
    page.locator(f"#{block} details summary").click()
    return page.locator(f"#{block} table tbody tr").count()


def walk_trends(p: Pass, person: Any | None, mock: bool, hd: bool) -> None:
    page, tag = p.page, p.tag
    page.click("#tab-trends")
    page.click("button.seg[data-days='14']")
    page.wait_for_function("() => document.querySelector('#body-trends-sub').innerText.includes('14')", timeout=10000)
    page.wait_for_selector("#body-trends-body svg.body-chart-svg", timeout=20000)
    svgs = page.locator("#body-trends-body svg.body-chart-svg")
    check(f"[{tag}] Trends has the weight chart and the blood pressure chart as SVG", svgs.count() == 2)
    weights = page.locator("#body-trends-weight svg.body-chart-svg .mark").all()
    rows_w = open_table(page, "body-trends-weight")
    rows_b = open_table(page, "body-trends-bp")
    check(f"[{tag}] the weight chart has one mark per weight and its table has a row for each", len(weights) == rows_w > 10, f"{len(weights)} marks, {rows_w} rows")
    check(f"[{tag}] the blood pressure chart has a mark for the top and the bottom number of every reading, and a table row for each",
          page.locator("#body-trends-bp svg.body-chart-svg .mark.top").count() == page.locator("#body-trends-bp svg.body-chart-svg .mark.bottom").count() == rows_b > 10)
    check(f"[{tag}] the weight chart is one line", page.locator("#body-trends-weight svg.body-chart-svg path.series.weight").count() == 1)
    check(f"[{tag}] the blood pressure chart has the top and bottom number as two lines and the goal as two dashed lines",
          page.locator("#body-trends-bp svg.body-chart-svg path.series.top").count() == 1 and page.locator("#body-trends-bp svg.body-chart-svg path.series.bottom").count() == 1
          and page.locator("#body-trends-bp svg.body-chart-svg line.ref.goal-top").count() == 1 and page.locator("#body-trends-bp svg.body-chart-svg line.ref.goal-bottom").count() == 1)
    dashed = page.evaluate("() => getComputedStyle(document.querySelector('#body-trends-bp svg.body-chart-svg line.ref.goal-top')).strokeDasharray")
    check(f"[{tag}] the goal lines are dashed (by the stylesheet)", dashed not in ("none", ""), dashed)
    if hd:
        check(f"[{tag}] on hemodialysis the dry weight is a dashed line and each weight after dialysis has its own marker",
              page.locator("#body-trends-weight svg.body-chart-svg line.ref.dry").count() == 1 and page.locator("#body-trends-weight svg.body-chart-svg polygon.mark.after").count() >= 5, "")
        check(f"[{tag}] the legend names them", "Dry weight in Profile" in page.inner_text("#body-trends-weight .body-legend") and "After dialysis" in page.inner_text("#body-trends-weight .body-legend"))
    else:
        check(f"[{tag}] off dialysis there is no dry weight line and no after-dialysis marker", page.locator("#body-trends-weight .ref.dry, #body-trends-weight polygon.mark.after").count() == 0)
    text = page.inner_text("#body-trends-body")
    check(f"[{tag}] the 7-day averages are written out", "Last 7 days" in text and "average" in text and "Goal from your care team: under 130/80" in text, text[:300])
    check(f"[{tag}] the legend names every line", "Top number" in page.inner_text("#body-trends-bp .body-legend") and "Bottom number" in page.inner_text("#body-trends-bp .body-legend"))
    check(f"[{tag}] the legend names the goal lines with their numbers, and no text is drawn over the readings",
          "Top goal: under 130" in page.inner_text("#body-trends-bp .body-legend") and "Bottom goal: under 80" in page.inner_text("#body-trends-bp .body-legend")
          and page.locator("#body-trends svg.body-chart-svg text.direct").count() == 0)
    styled = page.evaluate("() => document.querySelectorAll('#body-trends [style]').length")
    check(f"[{tag}] the charts carry no inline style", styled == 0, str(styled))
    labels = page.evaluate("() => [...document.querySelectorAll('#body-trends-body svg[role=img]')].map((s) => s.getAttribute('aria-label'))")
    check(f"[{tag}] each chart has a description for a screen reader that points to the table", all(a and "table under the chart" in a for a in labels), str(labels))
    has_import = page.evaluate("() => !!(window.KH && KH.bodyImport)")
    check(f"[{tag}] the Apple Health button is there exactly when the import module is", has_import and page.locator("#body-trends-actions").is_visible()
          and page.locator("#body-import-trends").count() == 1 if has_import else page.locator("#body-trends-actions").is_hidden()
          and page.locator("#body-import-trends").count() == 0, f"import module: {has_import}")
    check(f"[{tag}] no sideways scroll on Trends", not overflow(page))
    check(f"[{tag}] nobody else's numbers are in the charts or their tables", "219.9" not in text and "99.8" not in page.inner_text("#body-trends-body") and "177" not in page.inner_text("#body-trends-bp table"))
    p.shot("trends")
    # 30 days: the same, on a phone as well
    page.click("button.seg[data-days='30']")
    page.wait_for_function("() => document.querySelector('#body-trends-sub').innerText.includes('30')", timeout=10000)
    page.wait_for_selector("#body-trends-body svg.body-chart-svg", timeout=20000)
    check(f"[{tag}] 30 days: still two charts and no sideways scroll", page.locator("#body-trends-body svg.body-chart-svg").count() == 2 and not overflow(page))
    # the button for the import: shown once a module for it exists, and calls its open()
    page.evaluate("() => { window.__opened = 0; KH.bodyImport = { open() { window.__opened += 1; } }; }")
    page.click("button.seg[data-days='14']")
    page.wait_for_selector("#body-import-trends", timeout=10000)
    page.click("#body-import-trends")
    check(f"[{tag}] with KH.bodyImport the button appears on Trends and calls open()", page.evaluate("window.__opened") == 1 and page.inner_text("#body-import-trends") == "Import from Apple Health")
    p.shot("trends-import")
    page.evaluate("() => { delete KH.bodyImport; }")  # the stub was only for this check


def walk_profile(p: Pass, person: Any | None, mock: bool, hd: bool) -> None:
    page, tag = p.page, p.tag
    page.click("#tab-profile")
    page.wait_for_selector("#pf-weight", timeout=20000)
    page.wait_for_function("() => !document.querySelector('#pf-weight-log').hidden || document.querySelector('#pf-dialysis').value !== 'none'", timeout=15000)
    latest = page.locator("#pf-weight-log")
    if hd:
        check(f"[{tag}] on dialysis Profile offers no latest weight (it holds the dry weight)", latest.is_hidden())
    else:
        text = latest.inner_text()
        check(f"[{tag}] under Weight: the latest weight in the log, with Use this", text.startswith("Latest in your log: ") and " kg" in text and " on " in text and "Use this" in text, text)
        before = page.input_value("#pf-weight")
        latest.get_by_role("button", name="Use this").click()
        filled = page.input_value("#pf-weight")
        check(f"[{tag}] Use this fills the box and says Save profile keeps it", filled != "" and "Save profile" in latest.inner_text(), f"{before} -> {filled}")
        if person is not None:
            saved = person.json("GET", "/api/profile")["weight_kg"]
            check(f"[{tag}] nothing is saved by tapping it: the profile still says {before or 'nothing'}", (saved is None and before == "") or saved == float(before), str(saved))
        # the form says dialysis: the latest-weight line goes, the six-month line stays (when there is one)
        six = page.locator("#pf-weight-6mo-log")
        had_six = six.is_visible()
        page.select_option("#pf-dialysis", "hemodialysis")
        check(f"[{tag}] choosing dialysis in the form hides the latest weight, not the six-month one", latest.is_hidden() and six.is_visible() == had_six)
        page.select_option("#pf-dialysis", "none")
        check(f"[{tag}] and choosing none brings it back", latest.is_visible())
    six = page.locator("#pf-weight-6mo-log")
    page.wait_for_load_state("networkidle")  # the hints ask for the log a moment after the form has drawn (on dialysis nothing else waits for them)
    if person is not None:
        check(f"[{tag}] the log holds a weight from about six months before, so Weight 6 months ago has its line", six.is_visible())
    if six.is_visible():
        text = six.inner_text()
        check(f"[{tag}] under Weight 6 months ago: the weight about six months before, with Use this", text.startswith("In your log: ") and "Use this" in text, text)
        six.get_by_role("button", name="Use this").click()
        check(f"[{tag}] Use this fills that box", page.input_value("#pf-weight-6mo") != "")
    page.locator("#pf-weight").scroll_into_view_if_needed()
    p.shot("profile")
    check(f"[{tag}] no sideways scroll on Profile", not overflow(page))
    if person is not None and not hd:
        page.click("#btn-save-profile")
        page.wait_for_function("() => document.querySelector('#toast').innerText.includes('Profile saved')", timeout=15000)
        check(f"[{tag}] Save profile then saves what Use this filled", person.json("GET", "/api/profile")["weight_kg"] == float(page.input_value("#pf-weight")))


def walk_visit(p: Pass, person: Any | None, mock: bool, hd: bool, flagged: bool) -> None:
    page, tag = p.page, p.tag
    page.click("#tab-trends")
    page.click("#visit-open")
    page.wait_for_selector("#visit-body-body .visit-body-list", timeout=20000)
    text = page.inner_text("#visit-body-body")
    check(f"[{tag}] visit prep has the weight and blood pressure section with the latest weight and the 7-day and 30-day averages",
          "Latest weight:" in text and "last 7 days: average" in text and "last 30 days: average" in text, text[:400])
    check(f"[{tag}] it says how many readings were at or above the goal",
          "Goal from your care team: under 130/80" in text and " of " in text and "had a top number at or above 130 or a bottom number at or above 80" in text, text)
    check(f"[{tag}] it says what it could not compare for the six-month change, or shows it", "six months" in text or "Change over" in text, text)
    if hd:
        check(f"[{tag}] on hemodialysis it lists the gains between the last sessions, up to 6, with the alarm",
              "Gains between the last sessions" in text and "Your alarm from your care team: more than" in text and 1 <= page.locator("#visit-body-body .visit-body-gains li").count() <= 6,
              text)
        if not mock:
            check(f"[{tag}] a gain over the alarm says so in words", "over your alarm" in text, text)
    else:
        check(f"[{tag}] off dialysis it has no list of gains between sessions", "Gains between the last sessions" not in text)
    if flagged:
        check(f"[{tag}] a reading at 180/120 is listed with its date, and the handbook's block is there", "185/95" in text and page.locator("#visit-body-body .body-flag.prominent").count() == 1, text)
    else:
        check(f"[{tag}] with no reading at 180/120 it says none", "in this period: none" in text, text)
    p.shot("visit")
    check(f"[{tag}] no sideways scroll on Visit prep", not overflow(page))


def settings_import_button(p: Pass) -> None:
    page, tag = p.page, p.tag
    open_settings(page)
    page.wait_for_selector("#set-import", timeout=20000)
    check(f"[{tag}] Settings → Your data shows no Apple Health button without an import module (the block is empty and hidden)", page.locator("#set-body-import").count() == 0 or page.locator("#set-body-import").is_hidden())
    # with a module for it, the account block shows the button once it is drawn again
    page.evaluate("() => { window.__opened = 0; KH.bodyImport = { open() { window.__opened += 1; } }; return KH.views.settings.load(); }")
    page.wait_for_selector("#set-body-import-open", timeout=10000)
    page.click("#set-body-import-open")
    check(f"[{tag}] with KH.bodyImport Settings → Your data has Import from Apple Health, and it calls open()", page.evaluate("window.__opened") == 1)


def pass_full(browser: Any, server: Server | None, admin: Any | None, base: str, out: Path, width: int, height: int, scheme: str, *, n: int, hd: bool = False,
              mock: bool = False, mock_url: str = "/?mock=1") -> None:
    tag = f"{'demo-' if mock else ''}{'hd-' if hd else ''}{width}-{scheme}"
    person = None
    if not mock:
        person = invite_user(server, admin, f"walk{n}")
        prof: dict[str, Any] = {"weight_kg": 70, "ckd_stage": "3b", "diabetes": "type1"}
        if hd:
            prof.update(dialysis="hemodialysis", dialysis_days=[0, 2, 4])
        person.json("PUT", "/api/profile", prof)
        seed(person, hd)
        # a weight about six months before the latest one, for the Profile helper
        person.json("POST", "/api/body/weights", {"date": iso(-182), "time": "07:00", "kg": 74.0, "context": "morning"})
    p = Pass(browser, base, out, width, height, scheme, tag, person.cookies() if person else None)
    try:
        if not mock:
            # the walk through Today runs on a person with no alarm or goal yet: the card says where to enter them
            walk_today(p, person, mock, hd)
            walk_date_loading(p)
        else:
            p.page.goto(mock_url)
            p.page.wait_for_selector("#body-add-weight", state="visible", timeout=30000)
            wait_today(p.page)
            walk_today_demo(p, hd)
        if not mock:
            walk_settings_and_alarm(p, person, mock, hd)
            walk_alarm_line(p, person, mock, hd)
            person.json("POST", "/api/body/blood-pressure", {"date": iso(-3), "time": "19:30", "systolic": 185, "diastolic": 95, "context": "evening"})
        else:
            walk_alarm_line(p, None, mock, hd)
            walk_settings_demo(p, hd)
        walk_trends(p, person, mock, hd)
        walk_profile(p, person, mock, hd)
        walk_visit(p, person, mock, hd, flagged=not mock)
        if not mock:
            settings_import_button(p)
        p.finish(not mock, base)
    except Exception:
        p.shot("failure")
        p.ctx.close()
        raise
    finally:
        if person is not None:
            person.close()


def walk_today_demo(p: Pass, hd: bool) -> None:
    """The demo has sample data, an alarm and a goal: today's weight is over the alarm and no reading is at 180/120."""
    page, tag = p.page, p.tag
    text = say(page)
    check(f"[{tag}] the demo's card shows its sample weights, an alarm line over the alarm and the goal line", "Weight" in text and "Over your alarm" in text and "Blood pressure goal from your care team" in text, text[:300])
    check(f"[{tag}] the demo never shows the emergency block unasked", page.locator("#body-today-body .body-flag.prominent").count() == 0)
    n = page.locator("#body-today-body .body-item").count()
    add_reading(page, "180", "95", "evening", pulse="82")
    wait_today(page, "180/95")
    block = page.locator("#body-today-body > .body-flag.prominent")
    twin = page.evaluate("KH.bodyRules.flagOf('blood_pressure').text")
    check(f"[{tag}] a 180/95 reading in the demo shows the prominent block first, the twin's words, the 911 line first",
          block.count() == 1 and twin in block.inner_text() and block.inner_text().index("Call 911 now") < block.inner_text().index("Call your care team today"))
    page.locator(".body-item.flagged").get_by_role("button", name="Delete").click()
    page.wait_for_selector(".confirm-row", timeout=10000)
    page.click(".confirm-row .btn.danger-solid")
    page.wait_for_function("() => !document.querySelector('#body-today-body .body-flag.prominent')", timeout=10000)
    wait_today(page)
    check(f"[{tag}] deleting it takes the block away", page.locator("#body-today-body .body-item").count() == n)
    add_weight(page, "155", "morning", time="21:00")
    wait_today(page, "155.0 lb")
    page.locator(".body-item", has_text="155.0 lb").get_by_role("button", name="Edit").click()
    page.wait_for_selector("#sheet-weight[open]", timeout=10000)
    page.fill("#weight-value", "156")
    page.click("#weight-save")
    page.wait_for_selector("#sheet-weight", state="hidden", timeout=10000)
    wait_today(page, "156.0 lb")
    page.locator(".body-item", has_text="156.0 lb").get_by_role("button", name="Delete").click()
    page.wait_for_selector(".confirm-row", timeout=10000)
    page.click(".confirm-row .btn.danger-solid")
    page.wait_for_function("() => !document.querySelector('#body-today-body').innerText.includes('156.0 lb')", timeout=10000)
    check(f"[{tag}] the demo adds, edits and deletes a weight", True)
    if hd:
        page.click("#body-add-weight")
        page.wait_for_selector("#sheet-weight[open]", timeout=10000)
        check(f"[{tag}] on hemodialysis the weight sheet offers before and after dialysis",
              page.locator("#weight-context label").all_inner_texts() == ["Morning", "Before dialysis", "After dialysis", "Other"], str(page.locator("#weight-context label").all_inner_texts()))
        page.click("#sheet-weight [data-close].btn")
        page.wait_for_selector("#sheet-weight", state="hidden", timeout=10000)


def walk_settings_demo(p: Pass, hd: bool) -> None:
    page, tag = p.page, p.tag
    open_settings(page)
    check(f"[{tag}] the demo's Settings shows the sample alarm and goal", page.input_value("#set-body-goal-systolic") == "130" and page.input_value("#set-body-alarm-amount") != "")
    options = page.locator("#set-body-alarm-over option").all_inner_texts()
    check(f"[{tag}] 'between sessions' is there only on hemodialysis", ("between sessions" in options) == hd, str(options))


def short_pass(browser: Any, server: Server, admin: Any, base: str, out: Path, width: int, height: int, scheme: str, n: int) -> None:
    """The other two combinations of size and theme: the screens with data, no sideways scroll, no error."""
    tag = f"{width}-{scheme}-short"
    person = invite_user(server, admin, f"short{n}")
    person.json("PUT", "/api/profile", {"weight_kg": 70, "ckd_stage": "3b", "diabetes": "type1"})
    seed(person)
    set_settings(person, {"body.weight_alarm": {"amount_kg": 1, "over": "days", "days": 1}, "body.bp_goal": {"systolic": 130, "diastolic": 80}})
    person.json("POST", "/api/body/weights", {"date": iso(0), "time": "07:15", "kg": 71.8, "context": "morning"})
    person.json("POST", "/api/body/blood-pressure", {"date": iso(0), "time": "07:20", "systolic": 185, "diastolic": 95, "pulse": 80, "context": "morning"})
    p = Pass(browser, base, out, width, height, scheme, tag, person.cookies())
    try:
        page = p.page
        page.goto("/")
        page.wait_for_selector("#body-add-weight", state="visible", timeout=30000)
        wait_today(page, "185/95")
        check(f"[{tag}] Today: the prominent block, the alarm line, no sideways scroll", page.locator("#body-today-body > .body-flag.prominent").count() == 1 and "Over your alarm" in say(page) and not overflow(page))
        p.shot("today")
        page.click("#body-add-bp")
        page.wait_for_selector("#sheet-bp[open]", timeout=10000)
        page.fill("#bp-systolic", "185")
        page.fill("#bp-diastolic", "95")
        box = page.evaluate("() => { const r = document.querySelector('#sheet-bp').getBoundingClientRect(); return [r.left, r.right, window.innerWidth]; }")
        check(f"[{tag}] the blood pressure sheet with the block in it fits the screen", box[0] >= -1 and box[1] <= box[2] + 1, str(box))
        p.shot("bp-sheet")
        page.click("#sheet-bp [data-close].btn")
        page.wait_for_selector("#sheet-bp", state="hidden", timeout=10000)
        page.click("#tab-trends")
        page.wait_for_selector("#body-trends-body svg.body-chart-svg", timeout=20000)
        check(f"[{tag}] Trends: two charts, no sideways scroll", page.locator("#body-trends-body svg.body-chart-svg").count() == 2 and not overflow(page))
        p.shot("trends")
        open_settings(page)
        check(f"[{tag}] Settings: no sideways scroll", not overflow(page))
        p.shot("settings")
        p.finish(True, base)
    finally:
        person.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_PUBLIC_URL": HANDBOOK,
           # an empty folder: a handbook built at handbook/site would be served at /learn and the app's links would go there
           # instead of to the published address, so the checks of the links would depend on whether someone built the handbook
           "HANDBOOK_DIR": str(out / "no-handbook")}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, "bodyadmin")
        sam = invite_user(server, admin, "sam")
        secret = sam.json("POST", "/api/body/weights", {"date": iso(0), "kg": 99.77, "context": "morning", "note": "Sam's secret weight"})
        sam.json("POST", "/api/body/blood-pressure", {"date": iso(0), "systolic": 177, "diastolic": 97, "context": "morning", "note": "Sam's secret reading"})
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                n = 0
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    n += 1
                    pass_full(browser, server, admin, base, out, width, height, scheme, n=n)
                n += 1
                pass_full(browser, server, admin, base, out, 375, 812, "light", n=n, hd=True)
                for width, height, scheme in ((375, 812, "dark"), (1280, 800, "light")):
                    n += 1
                    short_pass(browser, server, admin, base, out, width, height, scheme, n)
                # nobody else's numbers anywhere
                theirs = sam.json("GET", "/api/body/weights", params={"start": iso(0), "end": iso(0)})["weights"]
                check("Sam's weight is still there, untouched", [x["id"] for x in theirs] == [secret["id"]] and theirs[0]["kg"] == 99.77)
                pass_full(browser, None, None, base, out, 375, 812, "light", n=0, mock=True)
                pass_full(browser, None, None, base, out, 1280, 800, "dark", n=0, mock=True, hd=True, mock_url="/?mock=1&hd=1")
            finally:
                browser.close()
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


if __name__ == "__main__":
    raise SystemExit(main())
