#!/usr/bin/env python3
"""Phone shortcuts (schema step 19, design note 12 §4.4 to §4.6) in Chromium, against a real server and the demo.

    python tools/e2e/push.py                       # port 8088
    python tools/e2e/push.py --port 8088 --out /tmp/kh-push

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``HANDBOOK_PUBLIC_URL`` set, finishes first-run setup and invites four people:
Ana and Bob (one walk each), Sam (a token and rows of his own, which no one else may see or delete) and nobody else. The harness plays the
Shortcut itself: a plain HTTP client that sends ``POST /push/v1/body`` with ``Authorization: Bearer <token>`` and no cookie and no Origin,
as a phone does. Walks at 375x812 light (Ana) and 1280x800 dark (Bob):

* Settings → Account → Your data → Phone shortcuts while the admin switch is off: what it is for, "Your admin has not turned this on", no
  form, a link to the handbook's recipe (``#from-a-phone-shortcut``); the admin, in a second browser window, turns "Let people send weights
  and blood pressure from a phone shortcut" on in Server administration and the block shows the form;
* making a token: a name is asked for in words; after a long wait the password is asked for again (a stored time, as a wait leaves it) and
  the token is made once it is typed; the token is shown once, with Copy token (the clipboard holds exactly it) and the address to send to
  (``location.origin`` + ``/push/v1/body``); drawn again, the page no longer holds the token, only its start in the list;
* the harness posts a weight, a blood pressure reading and a watch reading (refused, counted) and the same again (already there); the list
  says "last used" and "sent 1 weight and 1 blood pressure reading"; no cookie, a revoked token and another person's token cannot do what
  this one did;
* Today and the Trends tables say "from a shortcut (NAME)" on exactly those rows and nothing on a typed one (the "From" column only appears
  when some row has an origin); the name is drawn as text (Bob's token is called ``<i>Night</i> & "scale"``: no element is made of it);
* "Delete what it sent": Cancel sends nothing, the question names how many weights and readings, Delete removes exactly those rows (the typed
  rows and Sam's stay), the list says nothing is left, and Today and Trends no longer show the origin; for a lost phone the order is Revoke
  first (the shortcut gets 401 at once) and the ended token still offers Delete what it sent;
* Admin: People shows "Revoke tokens (n)" while a token is active and the switch is on, the Activity log names "Phone shortcut token
  created / revoked" and "Phone shortcut data deleted" with the counts; switching the setting off puts the off text in front of Ana's and Sam's
  block, hides "Revoke tokens", and every token gets 401;
* the demo (``/?mock=1``): the block says the preview has no server to send to, has no form and asks the network for nothing;
* no console error, no CSP violation, no browser dialog, no sideways scroll, no other host, and no write to a path outside the token routes.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on any
failure. The server is always stopped. What it cannot show: an iPhone's Shortcuts app, and the handbook's steps on a real phone.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx2
import khserver
from khserver import DEFAULT_PASSWORD, Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "push"
PORT = 8088
RESULTS: list[dict[str, Any]] = []
HANDBOOK = "https://handbook.example.org/"
TODAY = date.today()
ONE = "1 weight and 1 blood pressure reading"


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
        self.requests: list[str] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self.expect_403 = 0  # the browser's own "Failed to load resource" line for an answer the page asked for (the password prompt's 403)
        page.on("request", self._request)
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)
        page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")

    def _console(self, m: Any) -> None:
        if m.type != "error":
            return
        if self.expect_403 and "status of 403" in m.text:
            self.expect_403 -= 1
            return
        self.errors.append(m.text)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def _request(self, r: Any) -> None:
        parts = urlsplit(r.url)
        if parts.scheme in ("http", "https"):
            self.hosts.add(parts.netloc)
            self.requests.append(parts.path)
        if r.method != "GET":
            self.writes.append((r.method, parts.path))


class Pass:
    """One person, one browser context, one page, one tag for the messages."""

    def __init__(self, browser: Any, base: str, out: Path, width: int, height: int, scheme: str, tag: str, cookies: dict[str, str] | None = None) -> None:
        self.base, self.out, self.tag = base, out, tag
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base,
                                       permissions=["clipboard-read", "clipboard-write"])
        if cookies:
            self.ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in cookies.items()])
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self.watch = Watch(self.page)

    def shot(self, name: str, selector: str | None = None) -> None:
        target = self.page.locator(selector) if selector else None
        path = str(self.out / "shots" / f"{name}-{self.tag}.png")
        if target is not None and target.count():
            target.first.screenshot(path=path)
        else:
            self.page.screenshot(path=path)

    def finish(self, server_mode: bool) -> None:
        csp = self.page.evaluate("window.__csp || []")
        check(f"[{self.tag}] no console error, no CSP violation, no browser dialog", not self.watch.errors and not csp and not self.watch.dialogs,
              "; ".join(self.watch.errors + csp + self.watch.dialogs))
        if server_mode:
            others = sorted(h for h in self.watch.hosts if h != urlsplit(self.base).netloc)
            check(f"[{self.tag}] the browser asked no other host", not others, str(others))
            stray = sorted({f"{m} {p}" for m, p in self.watch.writes
                            if not (p.startswith("/api/me/tokens") or p in ("/api/auth/reauth", "/api/body/weights", "/api/body/blood-pressure")
                                    or p.startswith("/api/admin/settings") or p.startswith("/api/admin/users"))})
            check(f"[{self.tag}] the page wrote nothing outside the token, password and admin routes", not stray, str(stray))
        self.ctx.close()


# ------------------------------------------------------------------------------------------------ small helpers
def text_of(page: Any, selector: str) -> str:
    """What a person reads in the element: its visible text with the blank space collapsed."""
    return page.evaluate("(sel) => { const el = document.querySelector(sel); return el ? el.innerText.replace(/\\s+/g, ' ').trim() : ''; }", selector)


def wait_text(page: Any, selector: str, needle: str, timeout: int = 15000) -> None:
    page.wait_for_function("([sel, t]) => { const el = document.querySelector(sel); return !!el && el.innerText.includes(t); }", arg=[selector, needle], timeout=timeout)


def make_password_old(server: Server, username: str, minutes: int = 30) -> None:
    """The person last typed the password ``minutes`` ago: a stored time, as a wait would leave it (REAUTH_MINUTES is 10)."""
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn = sqlite3.connect(server.data_dir / "kidney.db", timeout=20)
    try:
        conn.execute("UPDATE sessions SET reauth_at = ? WHERE user_id = (SELECT id FROM users WHERE username = ?)", (old, username))
        conn.commit()
    finally:
        conn.close()


def shortcut(base: str, token: str | None, body: Any, headers: dict[str, str] | None = None) -> Any:
    """What the Shortcuts app sends: JSON with a bearer token, no cookie and no Origin."""
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    with httpx2.Client(base_url=base, trust_env=False, timeout=30) as client:
        return client.post("/push/v1/body", json=body, headers=hdrs)


def sent_body(day: str) -> dict[str, Any]:
    return {"weights": [{"at": f"{day}T06:30:00-04:00", "value": 154.3, "unit": "lb", "source": "Scale app"}],
            "readings": [{"at": f"{day}T06:35:00-04:00", "systolic": 128, "diastolic": 82, "source": "Omron Connect"},
                         {"at": f"{day}T06:36:00-04:00", "systolic": 131, "diastolic": 84, "source": "Sam's Apple Watch"}]}


def open_settings(page: Any) -> None:
    """Settings, then the Phone shortcuts block drawn (a person scrolls to it)."""
    if not page.is_visible("#view-settings:not([hidden])"):
        page.click("#settings-open")
    page.wait_for_selector("#set-push-off, #set-push-name, #set-push-demo, #set-push-list, #set-push-none", timeout=20000)
    page.locator("#set-push").scroll_into_view_if_needed()


def settings_fresh(page: Any) -> None:
    """A new page load, then Settings."""
    page.goto("/")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    open_settings(page)


def go_today(page: Any) -> None:
    page.goto("/")
    page.wait_for_selector("#body-add-weight", state="visible", timeout=30000)
    page.wait_for_function("() => document.querySelector('#body-today-body') && document.querySelector('#body-today-body').children.length > 0", timeout=15000)


def origins(page: Any) -> list[str]:
    return page.locator("#body-today-body .body-origin").all_inner_texts()


def trends_cells(page: Any, block: str) -> tuple[list[str], list[str]]:
    """The header cells of the table under a chart and the "From" column's cells."""
    page.locator(f"#{block} details summary").click()
    head = page.locator(f"#{block} table thead th").all_inner_texts()
    if "From" not in head:
        return head, []
    index = head.index("From")
    return head, page.locator(f"#{block} table tbody tr td:nth-child({index + 1})").all_inner_texts()


def open_trends(page: Any) -> None:
    page.click("#tab-trends")
    page.click("button.seg[data-days='14']")
    page.wait_for_function("() => document.querySelector('#body-trends-sub').innerText.includes('14')", timeout=10000)
    page.wait_for_selector("#body-trends-body svg.body-chart-svg", timeout=20000)


def open_admin(page: Any) -> None:
    """Server administration, drawn afresh (a hash change alone would keep what the page loaded before)."""
    page.goto("/#admin")
    page.reload()
    page.wait_for_selector("#view-admin:not([hidden]) #adm-push-enabled", timeout=30000)


def push_switch(admin_pass: Pass, on: bool) -> None:
    """The admin turns the instance switch on or off in Server administration."""
    page = admin_pass.page
    open_admin(page)
    box = page.locator("#adm-push-enabled")
    if box.is_checked() != on:
        box.click()
        page.wait_for_function("(want) => { const b = document.querySelector('#adm-push-enabled'); return b.checked === want && !b.disabled; }", arg=on, timeout=15000)
        wait_text(page, "#toast", "saved")


def settle_people(page: Any) -> None:
    page.wait_for_selector("#set-people .user-row", timeout=20000)


def manage_text(page: Any, user_id: int) -> str:
    """One person's row in People with its Manage panel opened: what an admin reads there."""
    details = page.locator(f"#user-{user_id} details.user-manage")
    if details.get_attribute("open") is None:
        details.locator("summary").first.click()
    return text_of(page, f"#user-{user_id}")


# ------------------------------------------------------------------------------------------------ the walks
def walk_person(p: Pass, server: Server, base: str, admin_pass: Pass, person: Any, others: dict[str, Any], name: str, username: str, hostile: bool) -> None:
    """One person's whole walk. ``name`` is the token's name; ``hostile`` makes it markup and takes the lost-phone order (revoke first)."""
    page, tag = p.page, p.tag
    person.json("POST", "/api/body/weights", {"date": iso(-1), "time": "07:15", "kg": 70.0, "context": "morning", "note": "typed by hand"})
    person.json("POST", "/api/body/blood-pressure", {"date": iso(-1), "time": "07:20", "systolic": 120, "diastolic": 78, "context": "morning"})
    me_id = person.json("GET", "/api/me")["id"]

    # ---- the switch is off
    push_switch(admin_pass, False)
    settings_fresh(page)
    block = text_of(page, "#set-push")
    check(f"[{tag}] while the admin switch is off the block says what it is for and 'Your admin has not turned this on'",
          "A shortcut on your iPhone can send your latest weight and blood pressure here." in block and "it cannot see your log" in block
          and "Your admin has not turned this on." in block and "Turned off on this server" in block, block)
    check(f"[{tag}] and shows no form, no token and no admin instructions to a person who is not an admin",
          page.locator("#set-push-name, #set-push-create").count() == 0 and "Admins:" not in block, block)
    link = page.locator("#set-push-recipe a")
    href = link.first.get_attribute("href") if link.count() else ""
    check(f"[{tag}] the handbook's recipe is linked, opening in a new tab", bool(href) and href.startswith(HANDBOOK) and href.endswith("#from-a-phone-shortcut")
          and link.first.get_attribute("target") == "_blank" and "noopener" in (link.first.get_attribute("rel") or ""), str(href))
    check(f"[{tag}] a token cannot be made with the switch off (the server says 409) and nothing was created",
          person.call("POST", "/api/me/tokens", {"name": "too early", "expires_in_days": 90, "family": "device"}).status_code in (409, 403, 404)
          and person.json("GET", "/api/me/tokens", params={"family": "device"})["tokens"] == [])
    p.shot("off", "#set-push")

    # ---- the admin turns it on, in a second window
    push_switch(admin_pass, True)
    admin_pass.shot("admin-switch-on", "#set-server")
    settings_fresh(page)
    page.wait_for_selector("#set-push-name", timeout=15000)
    block = text_of(page, "#set-push")
    check(f"[{tag}] switched on, the block offers a name and an expiry (90 days to start with) and no off text",
          "Your admin has not turned this on" not in block and "No tokens yet." in block
          and page.input_value("#set-push-expiry") == "90" and page.locator("#set-push-expiry option").count() == 3, block)
    heights = page.evaluate("() => [...document.querySelectorAll('#set-push button')].map((b) => Math.round(b.getBoundingClientRect().height))")
    check(f"[{tag}] its buttons are at least 44 px tall and nothing scrolls sideways", min(heights) >= 44 and not overflow(page), str(heights))

    # ---- make a token
    page.click("#set-push-create")
    check(f"[{tag}] Make token with no name says what is missing and sends nothing",
          "Give the token a name" in text_of(page, "#set-push") and not [w for w in p.watch.writes if w[0] == "POST" and w[1] == "/api/me/tokens"], text_of(page, "#set-push"))
    page.fill("#set-push-name", name)
    make_password_old(server, username)
    p.watch.expect_403 = 1  # the server answers 403 reauth_required, and the browser logs it
    page.click("#set-push-create")
    page.wait_for_selector("#sheet-reauth[open]", timeout=10000)
    check(f"[{tag}] after a long wait Make token asks for the password again and makes nothing yet",
          "Enter your password again" in text_of(page, "#sheet-reauth-title")
          and person.json("GET", "/api/me/tokens", params={"family": "device"})["tokens"] == [])
    page.fill("#reauth-password", DEFAULT_PASSWORD)
    page.click("#reauth-submit")
    page.wait_for_selector("#set-push-body input.link-input", timeout=15000)
    inputs = page.locator("#set-push-body input.link-input")
    token = inputs.nth(0).input_value()
    address = inputs.nth(1).input_value()
    check(f"[{tag}] the token is shown, a khd_ token, with the words that it is shown once",
          token.startswith("khd_") and len(token) > 24 and "It is shown only now. Paste it into your shortcut." in text_of(page, "#set-push"), token[:6])
    check(f"[{tag}] and the address to send to is this server's origin and /push/v1/body", address == f"{base}/push/v1/body", address)
    p.shot("token-shown", "#set-push")
    page.click("#set-push-body [aria-label='New token'] button:has-text('Copy token')")
    wait_text(page, "#toast", "Token copied")
    check(f"[{tag}] Copy token puts exactly the token on the clipboard", page.evaluate("() => navigator.clipboard.readText()") == token)
    page.click("#set-push-body [aria-label='Address to send to'] button:has-text('Copy address')")
    wait_text(page, "#toast", "Address copied")
    check(f"[{tag}] Copy address puts the address on the clipboard", page.evaluate("() => navigator.clipboard.readText()") == address)
    listed = person.json("GET", "/api/me/tokens", params={"family": "device"})
    item = listed["tokens"][0]
    check(f"[{tag}] the server holds one active device token with that name, 90 days", len(listed["tokens"]) == 1 and item["name"] == name and item["state"] == "active"
          and item["sent"] == {"weights": 0, "readings": 0}, json.dumps(item))
    row = text_of(page, "#set-push-list")
    check(f"[{tag}] the list names it with its start, 'never used', when it expires and that nothing was sent",
          name in row and f"{token[:8]}" in row and "never used" in row and "expires" in row and "nothing sent that is still in your log" in row, row)
    check(f"[{tag}] a token that has not sent anything has Revoke and no Delete what it sent",
          page.locator("#set-push-list button:has-text('Revoke')").count() == 1 and page.locator("#set-push-list button:has-text('Delete what it sent')").count() == 0)
    # drawn again, the token is gone
    settings_fresh(page)
    held = page.evaluate("(t) => document.body.innerText.includes(t) || [...document.querySelectorAll('input')].some((i) => i.value.includes(t))", token)
    check(f"[{tag}] drawn again, the page no longer holds the token anywhere (only its start in the list)", not held and token[:8] in text_of(page, "#set-push-list"))

    # ---- the Shortcut sends
    day = iso(0)
    r = shortcut(base, None, sent_body(day))
    check(f"[{tag}] a request with no token is the generic 401", r.status_code == 401, r.text[:120])
    r = shortcut(base, token, sent_body(day))
    body = r.json() if r.status_code == 200 else {}
    check(f"[{tag}] the Shortcut's POST adds 1 weight and 1 reading, refuses the watch reading, and echoes counts only",
          r.status_code == 200 and body == {"added": {"weights": 1, "readings": 1}, "already_there": {"weights": 0, "readings": 0}, "refused": {"watch": 1}}, r.text[:300])
    r = shortcut(base, token, sent_body(day))
    check(f"[{tag}] the same again adds nothing ('already there')", r.status_code == 200 and r.json()["added"] == {"weights": 0, "readings": 0}
          and r.json()["already_there"] == {"weights": 1, "readings": 1}, r.text[:300])
    mine_cookie = person.call("POST", "/push/v1/body", sent_body(day))
    check(f"[{tag}] a signed-in browser session alone cannot post to it (bearer only)", mine_cookie.status_code == 401, str(mine_cookie.status_code))
    stolen = shortcut(base, others["sam_token"], sent_body(iso(-2)))
    check(f"[{tag}] another person's token adds to that person's log only", stolen.status_code == 200
          and not [w for w in person.json("GET", "/api/body/weights", params={"start": iso(-2), "end": iso(-2)})["weights"]])

    # ---- the screens
    settings_fresh(page)
    row = text_of(page, "#set-push-list")
    check(f"[{tag}] the list now says it was used and what it sent", "last used" in row and f"sent {ONE}" in row and "never used" not in row, row)
    go_today(page)
    want = f"from a shortcut ({name})"
    got = origins(page)
    check(f"[{tag}] Today marks the weight and the reading '{want}' and nothing else", sorted(got) == [want, want], str(got))
    made_of = page.evaluate("() => document.querySelectorAll('#body-today-body .body-origin *, #set-push-list .row-title *').length")
    check(f"[{tag}] the token's name is text on Today (no element is made of it)", made_of == 0, str(made_of))
    p.shot("today", "#body-today")
    open_trends(page)
    head_w, from_w = trends_cells(page, "body-trends-weight")
    head_b, from_b = trends_cells(page, "body-trends-bp")
    check(f"[{tag}] the Trends tables have a From column, the shortcut rows say '{want}' and the typed ones '—'",
          "From" in head_w and "From" in head_b and sorted(from_w) == sorted(["—", want]) and sorted(from_b) == sorted(["—", want]), f"{head_w} {from_w} {head_b} {from_b}")
    p.shot("trends-table", "#body-trends-weight")

    # ---- the admin's views
    ap = admin_pass.page
    open_admin(ap)
    settle_people(ap)
    row_text = manage_text(ap, me_id)
    check(f"[{tag}] the admin's People list offers 'Revoke tokens (1)' for this person while a token is active", "Revoke tokens (1)" in row_text, row_text)
    admin_pass.shot("people", f"#user-{me_id}")

    # ---- Delete what it sent / Revoke
    settings_fresh(page)
    if hostile:
        revoke_it(p, person, name, token, base)
        delete_it(p, person, name, others, base, still_active=False, day=day, username=username)
    else:
        delete_it(p, person, name, others, base, still_active=True, day=day, username=username)
        revoke_it(p, person, name, token, base)
    p.shot("end", "#set-push")
    p.finish(True)


def delete_it(p: Pass, person: Any, name: str, others: dict[str, Any], base: str, *, still_active: bool, day: str, username: str) -> None:
    page, tag = p.page, p.tag
    page.wait_for_selector("#set-push-list button:has-text('Delete what it sent')", timeout=10000)
    mark = len(p.watch.writes)
    page.click("#set-push-list button:has-text('Delete what it sent')")
    page.wait_for_selector("#set-push-list .confirm-row, #set-push-body .confirm-row", timeout=10000)
    message = text_of(page, ".confirm-msg")
    check(f"[{tag}] Delete what it sent asks in the page, names the count and the token, and says that typed rows stay",
          f"Delete the {ONE} that “{name}” sent?" in message and "stay" in message and "cannot be undone" in message, message)
    p.shot("delete-confirm", "#set-push")
    page.click(".confirm-row button:has-text('Cancel')")
    check(f"[{tag}] Cancel deletes nothing", not [w for w in p.watch.writes[mark:] if w[0] == "DELETE"]
          and person.json("GET", "/api/me/tokens", params={"family": "device"})["tokens"][0]["sent"] == {"weights": 1, "readings": 1})
    page.click("#set-push-list button:has-text('Delete what it sent')")
    page.wait_for_selector(".confirm-row", timeout=10000)
    page.click(".confirm-row button:has-text('Delete')")
    wait_text(page, "#toast", f"Deleted {ONE}")
    page.wait_for_function("() => !document.querySelector('#set-push-list button[aria-label^=\"Delete what\"]')", timeout=10000)
    deletes = [w for w in p.watch.writes[mark:] if w[0] == "DELETE"]
    check(f"[{tag}] Delete sent one DELETE to the token's body-rows route, and the list says nothing of its rows is left",
          len(deletes) == 1 and deletes[0][1].endswith("/body-rows") and "nothing sent that is still in your log" in text_of(page, "#set-push-list"),
          f"{deletes} {text_of(page, '#set-push-list')}")
    weights = person.json("GET", "/api/body/weights", params={"start": iso(-3), "end": iso(0)})["weights"]
    readings = person.json("GET", "/api/body/blood-pressure", params={"start": iso(-3), "end": iso(0)})["readings"]
    check(f"[{tag}] the server kept the typed weight and reading and nothing from the shortcut",
          [w["note"] for w in weights] == ["typed by hand"] and len(readings) == 1 and readings[0]["systolic"] == 120
          and all(x["source"] == "manual" and x["via"] is None for x in weights + readings), json.dumps(weights + readings)[:300])
    sam_rows = others["sam"].json("GET", "/api/body/weights", params={"start": iso(-3), "end": iso(0)})["weights"]
    check(f"[{tag}] Sam's rows from his own shortcut are untouched", len(sam_rows) >= 1 and all(x["source"] in ("shortcut", "manual") for x in sam_rows)
          and any(x["via"] == "Sam's phone" for x in sam_rows), json.dumps(sam_rows)[:200])
    go_today(page)
    check(f"[{tag}] Today no longer shows the shortcut's rows or any origin", origins(page) == [] and "154.3" not in text_of(page, "#body-today-body"), text_of(page, "#body-today-body")[:200])
    open_trends(page)
    head_w, from_w = trends_cells(page, "body-trends-weight")
    check(f"[{tag}] the weight table has no From column once no row has an origin", "From" not in head_w, str(head_w))
    page.click("#settings-open")
    page.wait_for_selector("#set-push-list", timeout=15000)
    ended = page.locator("#set-push-list .token-ended").count()
    check(f"[{tag}] the token's row is still listed ({'active' if still_active else 'ended'}), without Delete what it sent",
          page.locator("#set-push-list li").count() == 1 and page.locator("#set-push-list button:has-text('Delete what it sent')").count() == 0
          and bool(ended) == (not still_active))


def revoke_it(p: Pass, person: Any, name: str, token: str, base: str) -> None:
    page, tag = p.page, p.tag
    if not page.is_visible("#view-settings:not([hidden])"):
        page.click("#settings-open")
    page.wait_for_selector("#set-push-list", timeout=15000)
    page.click("#set-push-list button:has-text('Revoke')")
    page.wait_for_selector(".confirm-row", timeout=10000)
    message = text_of(page, ".confirm-msg")
    check(f"[{tag}] Revoke asks in the page and says what it keeps", f"Revoke “{name}”?" in message and "stops working at once" in message and "stays in your log" in message, message)
    page.click(".confirm-row button:has-text('Revoke')")
    wait_text(page, "#toast", f"Revoked {name}")
    page.wait_for_function("() => !document.querySelector('#set-push-list button[aria-label^=\"Revoke\"]')", timeout=10000)
    row = text_of(page, "#set-push-list")
    r = shortcut(base, token, sent_body(iso(0)))
    check(f"[{tag}] revoked: the list says so, offers no Revoke, and the Shortcut gets 401 at once",
          "revoked" in row and r.status_code == 401 and r.headers.get("www-authenticate", "").lower().startswith("bearer"), f"{row} {r.status_code}")


def walk_admin_end(admin_pass: Pass, base: str, people: dict[str, Any], tokens: dict[str, str]) -> None:
    """The activity log, then the switch off: every token gets 401 and the blocks say so."""
    ap, page = admin_pass, admin_pass.page
    open_admin(page)
    page.wait_for_selector("#set-audit-list li", timeout=20000)
    log = text_of(page, "#set-audit-list")
    check("[admin] the Activity log names 'Phone shortcut token created' (valid for 90 days), 'Phone shortcut token revoked' and 'Phone shortcut data deleted' with the counts",
          "Phone shortcut token created" in log and "valid for 90 days" in log and "Phone shortcut token revoked" in log
          and "Phone shortcut data deleted" in log and ONE in log and "Assistant token created" not in log, log[:700])
    ap.shot("activity", "#set-audit")
    sam_id = people["sam_id"]
    settle_people(page)
    check("[admin] Sam, who still has an active token, has 'Revoke tokens (1)'", "Revoke tokens (1)" in manage_text(page, sam_id), manage_text(page, sam_id))
    push_switch(ap, False)
    settle_people(page)
    check("[admin] with the switch off again 'Revoke tokens' is gone from People, even with Sam's Manage panel open",
          "Revoke tokens" not in manage_text(page, sam_id) and "Revoke tokens" not in page.evaluate("document.querySelector('#set-people').textContent"),
          manage_text(page, sam_id))
    r = shortcut(base, tokens["sam"], sent_body(iso(0)))
    check("[admin] with the switch off Sam's still-valid token gets the generic 401", r.status_code == 401, r.text[:120])
    sam_cookies = people["sam_api"].cookies()
    sp = Pass(ap.ctx.browser, base, ap.out, 375, 812, "light", "375-light-sam", sam_cookies)
    try:
        settings_fresh(sp.page)
        block = text_of(sp.page, "#set-push")
        check("[sam] with the switch off again the block says so, lists his token, says it does not work, and still offers Revoke and Delete what it sent",
              "Your admin has not turned this on." in block and "Your tokens do not work while phone shortcuts are off." in block and "Sam's phone" in block
              and sp.page.locator("#set-push-list button:has-text('Revoke')").count() == 1 and sp.page.locator("#set-push-list button:has-text('Delete what it sent')").count() == 1
              and sp.page.locator("#set-push-name").count() == 0, block)
        sp.shot("off-with-token", "#set-push")
        sp.finish(True)
    except Exception:
        sp.shot("failure")
        sp.ctx.close()
        raise
    push_switch(ap, True)
    r = shortcut(base, tokens["sam"], sent_body(iso(0)))
    check("[admin] switched on again, Sam's token that was never revoked works again", r.status_code == 200, r.text[:120])


def walk_demo(browser: Any, base: str, out: Path) -> None:
    p = Pass(browser, base, out, 375, 812, "light", "demo-375-light")
    try:
        p.page.goto("/?mock=1")
        p.page.wait_for_selector("#settings-open", state="visible", timeout=30000)
        p.page.click("#settings-open")
        p.page.wait_for_selector("#set-push-demo", timeout=20000)
        p.page.locator("#set-push").scroll_into_view_if_needed()
        block = text_of(p.page, "#set-push")
        check("[demo] the block says what it is for and that the preview has no server to send readings to",
              "A shortcut on your iPhone can send your latest weight and blood pressure here." in block and "The preview has no server to send readings to." in block, block)
        check("[demo] there is no name field, no Make token and no token list", p.page.locator("#set-push-name, #set-push-create, #set-push-list").count() == 0)
        check("[demo] and the demo asked the network for nothing about tokens", not [r for r in p.watch.requests if "/api/me/tokens" in r or "/push/" in r], str(p.watch.requests[-5:]))
        check("[demo] no sideways scroll", not overflow(p.page))
        p.shot("demo", "#set-push")
        p.finish(False)
    except Exception:
        p.shot("failure")
        p.ctx.close()
        raise


# ------------------------------------------------------------------------------------------------ main
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
           # an empty folder: a handbook built at handbook/site would be served at /learn and the app's links would go there instead
           "HANDBOOK_DIR": str(out / "no-handbook")}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, "pushadmin")
        ana = invite_user(server, admin, "ana")
        bob = invite_user(server, admin, "bob")
        sam = invite_user(server, admin, "sam")
        base = f"http://localhost:{args.port}"
        admin.json("PATCH", "/api/admin/settings", {"push.enabled": True})
        sam_made = sam.json("POST", "/api/me/tokens", {"name": "Sam's phone", "expires_in_days": 90, "family": "device"})
        check("Sam's token is made through the API (the switch is on for a moment)", sam_made["token"].startswith("khd_"))
        r = shortcut(base, sam_made["token"], {"weights": [{"at": f"{iso(-1)}T06:30:00-04:00", "value": 99.77, "unit": "kg", "source": "Sam's scale"}], "readings": []})
        check("Sam's shortcut adds a weight of his own", r.status_code == 200 and r.json()["added"]["weights"] == 1, r.text[:200])
        admin.json("PATCH", "/api/admin/settings", {"push.enabled": False})
        users = {u["username"]: u["id"] for u in admin.json("GET", "/api/admin/users")["users"]}
        others = {"sam": sam, "sam_token": sam_made["token"]}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                admin_pass = Pass(browser, base, out, 1280, 800, "light", "admin-1280-light", admin.cookies())
                try:
                    p = Pass(browser, base, out, 375, 812, "light", "375-light", ana.cookies())
                    try:
                        walk_person(p, server, base, admin_pass, ana, others, "Morning weight", "ana", hostile=False)
                    except Exception:
                        p.shot("failure")
                        p.ctx.close()
                        raise
                    p = Pass(browser, base, out, 1280, 800, "dark", "1280-dark", bob.cookies())
                    try:
                        walk_person(p, server, base, admin_pass, bob, others, '<i>Night</i> & "scale"', "bob", hostile=True)
                    except Exception:
                        p.shot("failure")
                        p.ctx.close()
                        raise
                    walk_admin_end(admin_pass, base, {"sam_id": users["sam"], "sam_api": sam}, {"sam": sam_made["token"]})
                    admin_pass.finish(True)
                except Exception:
                    admin_pass.shot("failure")
                    admin_pass.ctx.close()
                    raise
                walk_demo(browser, base, out)
            finally:
                browser.close()
        for api in (admin, ana, bob, sam):
            api.close()
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
