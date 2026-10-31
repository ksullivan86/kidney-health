#!/usr/bin/env python3
"""The Care team (design notes 19, 25 and 29) in Chromium, against a real server and the demo.

    python tools/e2e/sharing.py                     # port 8096
    python tools/e2e/sharing.py --port 8096 --out /tmp/kh-sharing

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup, turns sharing on and invites Ana, Sam and Kim.
Ana logs a banana and a potassium result. Walks:

* Ana at 375x812 light: Settings → Care team is its own section after Account and says what each role may do; under "Make a
  link instead" she unticks symptoms and makes a link, shown once with Copy link and the words that it works once;
* Sam at 1280x800 dark opens the link: the sheet names Ana and what she shares, and nothing is saved until Accept; Accept opens
  Ana's summary, read-only: her name, the banner, her lab result, "has not shared their symptoms", and the banana in the day view;
  the page has no control that changes data;
* the admin: People shows "Care team: 1" on Ana's row;
* Ana: her list names Sam as a Viewer and says he looked today; Remove asks first, then the list is empty;
* Sam: Settings says he is on nobody's Care team, and the shared routes answer 404;
* Ana invites "nobody-here" and "kim" by user name as a Care helper: the screen says the same for both;
* Kim at 375x812 dark accepts in her own Settings, presses Plan meals, sees whose plan she is changing, adds apple to Ana's
  tomorrow (planned, "added by kim", on Ana's shopping list, never in Kim's own log; every write to /api/shared), and goes back to
  her own plan; Ana's Today then says "Added by kim";
* Ana turns on more switches for Kim in Settings → Care team (log food she ate, then her saved meals and suggestions): the role
  says Caregiver, then Custom;
* Kim, now able to log, marks the planned apple eaten, adds a banana as eaten today, adds Ana's saved meal to her plan, sees that
  Ana's low treatment is hers alone to change, and sends a suggestion with a note: the answer shows how it fits Ana's day;
* Ana's Plan tab shows the suggestion from kim; Add to my plan puts it on her plan, and Kim's list then says it was added;
  Ana's Today says "Added by kim" on the banana Kim logged;
* the demo (``/?mock=1``): a sample Care team, a suggestion from Jordan on your own Plan tab, and helping Ana (log, saved meals,
  suggest), with no shared route asked over the network;
* no console error, no CSP violation, no browser dialog, no sideways scroll at 375, no other host.

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

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "sharing"
PORT = 8096
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


class Watch:
    def __init__(self, page: Any) -> None:
        self.hosts: set[str] = set()
        self.requests: list[str] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self.refused: list[str] = []  # 400 answers: a refusal the walk asked for on purpose is checked by the walk itself
        page.on("request", self._request)
        page.on("response", lambda r: self.refused.append(f"{r.request.method} {urlsplit(r.url).path}") if r.status == 400 else None)
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)
        page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")

    def _console(self, m: Any) -> None:
        if m.type != "error":
            return
        # A signed-out page's first status check and an "enter your password again" answer (both asked for).
        if "status of 401" in m.text or "status of 403" in m.text:
            return
        if "status of 400" in m.text:  # listed in .refused; finish() checks it holds only what the walk expected
            return
        self.errors.append(m.text)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def _request(self, r: Any) -> None:
        parts = urlsplit(r.url)
        if parts.scheme in ("http", "https"):
            self.hosts.add(parts.netloc)
            self.requests.append(f"{r.method} {parts.path}")


class Pass:
    def __init__(self, browser: Any, base: str, out: Path, width: int, height: int, scheme: str, tag: str,
                 cookies: dict[str, str] | None = None) -> None:
        self.base, self.out, self.tag = base, out, tag
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
        self.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
        if cookies:
            self.ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in cookies.items()])
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self.watch = Watch(self.page)

    def shot(self, name: str, selector: str | None = None) -> None:
        path = str(self.out / "shots" / f"{name}-{self.tag}.png")
        target = self.page.locator(selector) if selector else None
        if target is not None and target.count():
            target.first.screenshot(path=path)
        else:
            self.page.screenshot(path=path)

    def no_overflow(self, where: str) -> None:
        wide = self.page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        check(f"[{self.tag}] no sideways scroll ({where})", not wide)

    def finish(self, demo: bool = False, refused: list[str] | None = None) -> None:
        check(f"[{self.tag}] the server refused only what the walk meant it to", sorted(self.watch.refused) == sorted(refused or []),
              str(self.watch.refused))
        csp = self.page.evaluate("window.__csp || []")
        check(f"[{self.tag}] no console error, no CSP violation, no browser dialog", not self.watch.errors and not csp and not self.watch.dialogs,
              "; ".join(self.watch.errors + csp + self.watch.dialogs))
        others = sorted(h for h in self.watch.hosts if h != urlsplit(self.base).netloc)
        check(f"[{self.tag}] the browser asked no other host", not others, str(others))
        if demo:
            check(f"[{self.tag}] the demo asked the network for no shared route",
                  not any(" /api/shared" in r or " /api/me/shares" in r for r in self.watch.requests), str(self.watch.requests[-5:]))
        self.ctx.close()


def answer_reauth(page: Any) -> bool:
    try:
        page.wait_for_selector("#sheet-reauth[open]", timeout=3000)
    except Exception:  # noqa: BLE001 - not asked
        return False
    page.fill("#reauth-password", khserver.DEFAULT_PASSWORD)
    page.click("#reauth-submit")
    return True


def open_sharing(page: Any) -> None:
    page.goto("/")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-sharing p:not(.muted.small), #set-sharing-off", timeout=20000)
    page.locator("#set-sharing").scroll_into_view_if_needed()


def walk_ana_shares(p: Pass) -> str:
    page = p.page
    open_sharing(page)
    check(f"[{p.tag}] Settings → Care team says who it is for and what each role may do",
          "caregiver or a dietitian" in text_of(page, "#set-sharing") and "never change anything" in text_of(page, "#set-sharing")
          and "Care helper can also plan your meals" in text_of(page, "#set-sharing") and "Nobody yet." in text_of(page, "#set-sharing"))
    check(f"[{p.tag}] the Care team is its own Settings section, after Account",
          page.evaluate("() => { const s = [...document.querySelectorAll('#view-settings .settings-section')].filter((x) => !x.hidden);"
                        " return s.indexOf(document.querySelector('#set-care')) === 1; }"))
    page.click("#set-share-form summary")  # Make a link instead
    page.uncheck("#set-share-symptoms")
    page.uncheck("#set-share-activity")
    page.select_option("#set-share-days", "30")
    page.click("#set-sharing-make")
    answer_reauth(page)
    page.wait_for_selector("#set-share-link", timeout=20000)
    link = page.input_value("#set-share-link")
    box = text_of(page, "#set-sharing [aria-label='New share link']")
    check(f"[{p.tag}] the link is shown once with the areas and the words that it works once",
          "/#/share/" in link and "food log, lab results and weight and blood pressure" in box and "works once" in box, box[:200])
    check(f"[{p.tag}] it says the share will last 30 days", "you share for 30 days" in box, box[:300])
    page.click("#set-sharing [aria-label='New share link'] button:has-text('Copy link')")
    check(f"[{p.tag}] Copy link puts exactly the link on the clipboard", page.evaluate("() => navigator.clipboard.readText()") == link)
    check(f"[{p.tag}] the unused link is listed with when it ends", "works until" in text_of(page, "#set-sharing-codes"))
    p.shot("link", "#set-sharing")
    p.no_overflow("link")
    return link


def walk_sam_accepts(p: Pass, link: str) -> None:
    page = p.page
    page.goto("/")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.goto(link.replace(urlsplit(link).netloc, urlsplit(p.base).netloc))
    page.wait_for_selector("#sheet-share[open]", timeout=20000)
    wait_text(page, "#share-question", "wants to add you")
    q = text_of(page, "#share-question")
    check(f"[{p.tag}] the sheet names Ana and what she shares, and says he cannot change anything",
          "ana wants to add you to their Care team and share their food log, lab results and weight and blood pressure with you" in q
          and "not change anything" in q, q)
    check(f"[{p.tag}] the sheet says it ends by itself after 30 days", "ends by itself after 30 days" in q, q)
    check(f"[{p.tag}] the link left the address bar", "/share/" not in page.url, page.url)
    p.shot("question", "#sheet-share")
    page.click("#share-accept")
    page.wait_for_selector("#view-visit:not([hidden])", timeout=20000)
    wait_text(page, "#visit-title", "ana's summary")
    wait_text(page, "#visit-labs-body", "Potassium")
    wait_text(page, "#visit-day-body", "Banana")
    check(f"[{p.tag}] Accept opens Ana's summary with her name and the read-only banner",
          "You can look, but not change anything" in text_of(page, "#visit-shared") and "Shared by ana" in text_of(page, "#visit-who"))
    check(f"[{p.tag}] her lab result and her day are there, and the symptoms say they were not shared",
          "4.8" in text_of(page, "#visit-labs-body") and "has not shared their symptoms" in text_of(page, "#visit-sym-body"),
          text_of(page, "#visit-sym-body"))
    writes = [r for r in p.watch.requests if r.split(" ", 1)[0] in ("POST", "PUT", "PATCH", "DELETE") and "/api/" in r
              and r != "POST /api/shared/info"]  # info is a POST that reads: who the link is from
    check(f"[{p.tag}] the only write was accepting the link", writes == ["POST /api/shared/accept"], str(writes))
    buttons = page.evaluate("() => [...document.querySelectorAll('#view-visit button')].filter((b) => b.offsetParent).map((b) => b.innerText.trim())")
    allowed = {"Back to Settings", "Print / Save as PDF", "Add", "2 weeks", "4 weeks", "3 months"}
    check(f"[{p.tag}] the page has no control that changes data (only the period, print, back and the page's own questions)",
          set(buttons) <= allowed, str(buttons))
    p.shot("summary")
    p.no_overflow("summary")


def walk_sam_trends(p: Pass) -> None:
    """Sam opens Ana's Trends from Settings: her charts read-only, then the Trends tab is his own again."""
    page = p.page
    open_sharing(page)
    wait_text(page, "#set-shared-list", "ana")
    before = len(p.watch.requests)
    page.get_by_role("button", name="Open ana's trends").click()
    page.wait_for_selector("#view-trends:not([hidden])", timeout=20000)
    wait_text(page, "#trends-shared", "ana's trends")
    page.wait_for_selector("#charts > *", timeout=20000)
    wait_text(page, "#period-sub", "of")
    charts = text_of(page, "#charts")
    check(f"[{p.tag}] Trends opens Ana's trends with the read-only banner and her name in the title",
          "You can look, but not change anything" in text_of(page, "#trends-shared") and "ana" in text_of(page, "#trends-title").lower(),
          text_of(page, "#trends-title"))
    check(f"[{p.tag}] her period is read from her log (1 day logged), and nothing sends him to her Profile",
          "1 of" in text_of(page, "#period-sub") and "Profile" not in charts + text_of(page, "#period-body"),
          text_of(page, "#period-sub") + " | " + charts[:120])
    check(f"[{p.tag}] there is no CSV export and no Get-ready link on her trends",
          not page.is_visible("#export-csv") and not page.is_visible("#visit-open"))
    wait_text(page, "#symptoms-trends-body", "has not shared")
    check(f"[{p.tag}] her symptoms say they were not shared", "has not shared their symptoms" in text_of(page, "#symptoms-trends-body"))
    asked = [r for r in p.watch.requests[before:] if "/api/" in r]
    check(f"[{p.tag}] her trends read only the shared routes, with GET",
          all(r.startswith("GET /api/shared/") or r.startswith("GET /api/me") or r.startswith("GET /api/auth") for r in asked)
          and any("/log/range" in r for r in asked), str(asked))
    p.shot("trends")
    p.no_overflow("trends")
    page.click("#tab-trends")
    page.wait_for_selector("#trends-shared", state="hidden", timeout=20000)
    check(f"[{p.tag}] the Trends tab then shows his own trends, with the export back", page.is_visible("#export-csv")
          and "ana" not in text_of(page, "#trends-title").lower(), text_of(page, "#trends-title"))


def walk_admin(p: Pass, admin: Any) -> None:
    page = p.page
    ana_id = next(u["id"] for u in admin.json("GET", "/api/admin/users")["users"] if u["username"] == "ana")
    page.goto("/#admin")
    page.wait_for_selector(f"#user-{ana_id}", timeout=30000)
    check(f"[{p.tag}] People shows Care team: 1 on Ana's row", "care team: 1" in text_of(page, f"#user-{ana_id}").lower(), text_of(page, f"#user-{ana_id}")[:200])
    p.finish()


def walk_ana_stops(p: Pass) -> None:
    page = p.page
    open_sharing(page)
    wait_text(page, "#set-sharing-list", "sam")
    line = text_of(page, "#set-sharing-list")
    check(f"[{p.tag}] her list names Sam and says he looked today", "looked today" in line and "food log" in line, line)
    check(f"[{p.tag}] and when the share ends", " · until " in line, line)
    check(f"[{p.tag}] the role is shown and can be changed in place", "Viewer" in line and page.is_visible("#set-sharing-list select"), line)
    page.get_by_role("button", name="Remove sam from your Care team").click()
    check(f"[{p.tag}] Remove asks first", "can no longer see any of your data" in text_of(page, "#set-sharing-list"))
    page.locator("#set-sharing-list").get_by_role("button", name="Remove", exact=True).click()
    page.wait_for_selector("#set-sharing-none", timeout=15000)
    check(f"[{p.tag}] then nobody can see her data", "Nobody yet." in text_of(page, "#set-sharing"))


def walk_sam_after(p: Pass, sam: Any, share_id: int) -> None:
    page = p.page
    open_sharing(page)
    page.wait_for_selector("#set-shared-none", timeout=15000)
    check(f"[{p.tag}] Settings says he is on nobody's Care team", "You are not on anyone's Care team yet." in text_of(page, "#set-sharing"))
    check(f"[{p.tag}] the shared routes answer 404", sam.call("GET", f"/api/shared/{share_id}/labs").status_code == 404)
    p.finish()


def walk_ana_invites(p: Pass) -> None:
    """Ana invites Kim by user name as a Care helper, and a name nobody has: the screen answers the same way."""
    page = p.page
    open_sharing(page)
    sent = []
    for name in ("nobody-here", "kim"):
        page.fill("#set-care-invite-name", name)
        page.check("#set-care-role-care_helper")
        page.click("#set-care-invite")
        answer_reauth(page)
        wait_text(page, "#set-care-sent", "Invite sent to")
        sent.append(text_of(page, "#set-care-sent").replace(name, "<name>"))
    check(f"[{p.tag}] an invite says the same thing whether or not the name is an account", sent[0] == sent[1], " | ".join(sent))
    waiting = text_of(page, "#set-care-invites")
    check(f"[{p.tag}] both wait for an answer, as Care helper with the food log", "nobody-here" in waiting and "kim" in waiting
          and "Care helper" in waiting and "food log" in waiting, waiting)
    p.shot("invites", "#set-sharing")
    p.no_overflow("invites")


def walk_kim_plans(p: Pass, kim: Any, ana: Any) -> None:
    """Kim accepts in her own Settings, then plans a food on Ana's tomorrow from the Plan tab, and goes back to her own plan."""
    page = p.page
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    open_sharing(page)
    wait_text(page, "#set-care-for-me", "ana")
    check(f"[{p.tag}] the invite waits in her Settings → Care team with what it means",
          "as a Care helper" in text_of(page, "#set-care-for-me"), text_of(page, "#set-care-for-me"))
    p.shot("invite-for-me", "#set-sharing")
    page.get_by_role("button", name="Accept the invite from ana").click()
    wait_text(page, "#set-shared-list", "Care helper")
    page.get_by_role("button", name="Plan meals for ana").click()
    page.wait_for_selector("#care-banner", timeout=20000)
    banner = text_of(page, "#care-banner")
    check(f"[{p.tag}] the Plan tab says whose plan she is changing", "You are planning for ana. Changes go to ana's plan, not yours." in banner, banner)
    check(f"[{p.tag}] her own plan is hidden while she plans for Ana", not page.is_visible("#plan-grid") and page.is_visible("#care-for-select"))
    page.wait_for_selector("#care-add-q", timeout=20000)
    page.fill("#care-add-q", "apple")
    page.wait_for_selector("#care-add-results button", timeout=20000)
    page.locator("#care-add-results button").first.click()
    page.select_option("#care-add-meal", "lunch")
    page.fill("#care-add-servings", "2")
    page.click("#care-add")
    wait_text(page, "#care-day", "added by kim")
    day = text_of(page, "#care-day")
    check(f"[{p.tag}] the food is on Ana's day, planned, with who added it", "Apple" in day and "planned" in day and "added by kim" in day, day[:300])
    wait_text(page, "#care-shopping", "Apple")
    check(f"[{p.tag}] Ana's shopping list has it, with Copy list", page.is_visible("#care-shopping-copy"))
    p.shot("care-plan")
    p.no_overflow("care-plan")
    anas = ana.json("GET", "/api/log", params={"date": tomorrow})["entries"]
    kims = kim.json("GET", "/api/log", params={"date": tomorrow})["entries"]
    check(f"[{p.tag}] the entry is in Ana's log as planned and added by kim, and never in Kim's own",
          [(e["status"], e["added_by"]) for e in anas] == [("planned", "kim")] and kims == [], f"{anas} | {kims}")
    writes = [r for r in p.watch.requests if r.split(" ", 1)[0] in ("POST", "PUT", "DELETE") and "/api/" in r]
    check(f"[{p.tag}] every write went to the shared routes or her Settings", all("/api/shared" in r for r in writes), str(writes))
    page.click("#care-back")
    page.wait_for_selector("#care-plan", state="hidden", timeout=15000)
    page.wait_for_selector("#plan-grid", state="visible", timeout=15000)
    check(f"[{p.tag}] Back to my own plan shows her own week again", page.input_value("#care-for-select") == "")


def walk_ana_sees_who(p: Pass) -> None:
    """Ana's Today shows the planned food with "Added by kim"."""
    page = p.page
    page.goto("/")
    page.wait_for_selector("#date-next", state="visible", timeout=30000)
    page.click("#date-next")
    wait_text(page, "#view-today", "Added by kim")
    check(f"[{p.tag}] Today says who planned it", "Added by kim" in text_of(page, "#view-today"))
    p.shot("added-by")


def switch_on(page: Any, share_id: int, switch: str) -> None:
    """Tick one of the "may do" switches of share ``share_id`` in Settings → Care team, and wait for it to be saved."""
    box = f"#set-care-switches-{share_id}"
    if not page.evaluate("(sel) => !!document.querySelector(sel) && document.querySelector(sel).open", box):
        page.click(f"{box} summary")
    page.check(f"#set-care-{share_id}-{switch}")
    noun = {"may-plan": "planning", "may-log": "logging food", "may-use-saved-meals": "saved meals", "may-suggest": "suggestions"}[switch]
    wait_text(page, "#set-sharing-list .row-sub", noun)  # saved: the list was drawn again from the server
    page.wait_for_selector(f"{box}[open]", timeout=15000)


def walk_ana_switches(p: Pass, ana: Any) -> int:
    """Ana turns on logging for Kim (Caregiver), then her saved meals and suggestions (Custom), each saved at once."""
    page = p.page
    open_sharing(page)
    wait_text(page, "#set-sharing-list", "kim")
    share_id = next(s["id"] for s in ana.json("GET", "/api/me/shares")["sharing"] if s["username"] == "kim")
    switch_on(page, share_id, "may-log")
    wait_text(page, "#set-sharing-list .row-sub", "Caregiver")
    line = text_of(page, "#set-sharing-list .row-sub")
    check(f"[{p.tag}] turning on Log food I ate makes Kim a Caregiver", "Caregiver" in line and "logging food" in line, line[:300])
    switch_on(page, share_id, "may-use-saved-meals")
    switch_on(page, share_id, "may-suggest")
    wait_text(page, "#set-sharing-list .row-sub", "saved meals and suggestions")
    line = text_of(page, "#set-sharing-list .row-sub")
    check(f"[{p.tag}] with saved meals and suggestions too, the role says Custom and lists what Kim may do",
          "Custom" in line and "may: planning, logging food, saved meals and suggestions" in line, line[:300])
    item = next(s for s in ana.json("GET", "/api/me/shares")["sharing"] if s["id"] == share_id)
    check(f"[{p.tag}] the server has all four switches on", all(item[k] for k in ("may_plan", "may_log", "may_use_saved_meals", "may_suggest")), str(item))
    p.shot("switches", "#set-sharing")
    p.no_overflow("switches")
    return share_id


def walk_kim_helps(p: Pass, kim: Any, ana: Any) -> None:
    """Kim, now a helper with every switch: marks a planned food eaten, logs a food eaten, adds Ana's saved meal, leaves Ana's low
    treatment alone and sends a suggestion."""
    page = p.page
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    chicken = ana.json("GET", "/api/foods", params={"q": "chicken"})["foods"][0]["id"]
    ana.json("POST", "/api/log", {"date": tomorrow, "meal": "dinner", "food_id": chicken, "servings": 1, "status": "planned"})
    page.goto("/#plan")
    page.wait_for_selector("#care-for:not([hidden])", timeout=30000)
    page.select_option("#care-for-select", label="ana")
    page.wait_for_selector("#care-banner", timeout=20000)
    wait_text(page, "#care-banner", "You are helping")  # opening someone reads their switches as they are now
    banner = text_of(page, "#care-banner")
    check(f"[{p.tag}] the banner says what she adds goes into Ana's food log", "You are helping ana. What you add goes into ana's food log" in banner, banner)
    wait_text(page, "#care-day", "Chicken")
    page.locator("#care-day li", has_text="Chicken").locator("button", has_text="Mark eaten").click()
    page.wait_for_function("() => [...document.querySelectorAll('#care-day li')].some((li) => li.innerText.includes('Chicken') && li.innerText.includes('serving · eaten'))",
                           timeout=15000)
    check(f"[{p.tag}] Mark eaten turns Ana's planned chicken into eaten food",
          [e["status"] for e in ana.json("GET", "/api/log", params={"date": tomorrow})["entries"] if e["food_name"].startswith("Chicken")] == ["eaten"])
    # today: a banana eaten, through the form
    page.locator("#care-grid button[aria-label^='Today,']").click()
    wait_text(page, "#care-day-h", "Today,")
    wait_text(page, "#care-day", "A low treatment: only ana changes it.")
    low_row = page.locator("#care-day li", has_text="Glucose")
    check(f"[{p.tag}] Ana's low treatment says only she changes it, with no button to change it",
          low_row.count() == 1 and low_row.locator("button").count() == 0, text_of(page, "#care-day")[:300])
    page.fill("#care-add-q", "banana")
    page.wait_for_selector("#care-add-results button", timeout=20000)
    page.locator("#care-add-results button").first.click()
    page.select_option("#care-add-meal", "snack")
    page.select_option("#care-add-status", "eaten")
    check(f"[{p.tag}] the button says it goes into the food log as eaten", "as eaten" in page.inner_text("#care-add"))
    page.click("#care-add")
    page.wait_for_function("() => [...document.querySelectorAll('#care-day li')].some((li) => li.innerText.includes('Banana') && li.innerText.includes('eaten · added by kim'))",
                           timeout=15000)
    eaten = [(e["food_name"], e["status"], e["added_by"]) for e in ana.json("GET", "/api/log", params={"date": today})["entries"]]
    check(f"[{p.tag}] the banana is in Ana's log as eaten, added by kim", ("Banana, raw", "eaten", "kim") in eaten, str(eaten))
    # Ana's saved meal, added to her plan
    wait_text(page, "#care-meals", "Ana's lunch")
    page.locator("#care-meals-list li", has_text="Ana's lunch").get_by_role("button", name="Add to plan").click()
    page.wait_for_function("() => [...document.querySelectorAll('#care-day li')].filter((li) => li.innerText.includes('planned · added by kim')).length >= 1",
                           timeout=15000)
    check(f"[{p.tag}] Ana's saved meal is on her plan, added by kim, and the meal itself is unchanged",
          any(e["added_by"] == "kim" and e["status"] == "planned" for e in ana.json("GET", "/api/log", params={"date": today})["entries"])
          and [m["name"] for m in ana.json("GET", "/api/meals")["meals"]] == ["Ana's lunch"])
    # a suggestion with a note
    page.wait_for_selector("#care-suggest-q", timeout=20000)

    def pick(word: str) -> None:
        page.fill("#care-suggest-q", word)
        page.wait_for_function("(w) => { const b = document.querySelector('#care-suggest-results button'); "
                               "return !!b && b.innerText.toLowerCase().includes(w); }", arg=word, timeout=20000)
        page.locator("#care-suggest-results button").first.click()
        page.wait_for_function("() => !document.querySelector('#care-suggest-items li.muted')", timeout=15000)

    page.fill("#care-suggest-date", tomorrow)
    page.select_option("#care-suggest-meal", "dinner")
    pick("rice")
    page.fill("#care-suggest-note", "Apples are in the fruit bowl.")
    page.click("#care-suggest-send")
    wait_text(page, "#care-suggest-result", "for the day with this meal")
    check(f"[{p.tag}] the answer shows how the suggestion fits Ana's day", "Potassium" in text_of(page, "#care-suggest-result"),
          text_of(page, "#care-suggest-result")[:200])
    wait_text(page, "#care-sent", "waiting for an answer")
    pick("apple")  # the first is apple juice, a food for treating a low
    page.click("#care-suggest-send")
    wait_text(page, "#care-suggest-result", "for treating a low")
    check(f"[{p.tag}] a food for treating a low is left out of suggestions, said plainly",
          "how to treat a low stays ana's choice" in text_of(page, "#care-suggest-result"), text_of(page, "#care-suggest-result"))
    page.locator("#care-suggest-items button", has_text="Take out").first.click()
    pick("rice")
    page.fill("#care-suggest-note", "Take your insulin first")
    page.click("#care-suggest-send")
    wait_text(page, "#care-suggest-result", "Please leave out")
    check(f"[{p.tag}] a note about insulin is refused with a plain reason", "insulin" in text_of(page, "#care-suggest-result"))
    p.shot("care-helps")
    p.no_overflow("care-helps")
    writes = [r for r in p.watch.requests if r.split(" ", 1)[0] in ("POST", "PUT", "DELETE") and "/api/" in r]
    check(f"[{p.tag}] every write went to the shared routes or her Settings", all("/api/shared" in r for r in writes), str(writes))
    p.page.evaluate("() => KH.carePlan.leave()")


def walk_ana_suggestion(p: Pass, ana: Any, kim: Any, share_id: int) -> None:
    """Ana sees Kim's suggestion on her Plan tab and adds it with one tap; Kim's list then says so."""
    page = p.page
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    page.goto("/#plan")
    page.wait_for_selector("#plan-suggestions:not([hidden])", timeout=30000)
    card = text_of(page, "#plan-suggestions")
    check(f"[{p.tag}] her Plan tab shows the suggestion from kim, with the note and how it fits her day",
          "1 suggestion from your Care team" in card and "kim suggests dinner" in card.lower() and "Apples are in the fruit bowl." in card
          and "for the day with this meal" in card, card[:400])
    p.shot("suggestion", "#plan-suggestions")
    p.no_overflow("suggestion")
    before = len(ana.json("GET", "/api/log", params={"date": tomorrow})["entries"])
    page.locator("#plan-suggestions").get_by_role("button", name="Add to my plan").click()
    page.wait_for_selector("#plan-suggestions", state="hidden", timeout=15000)
    after = ana.json("GET", "/api/log", params={"date": tomorrow})["entries"]
    check(f"[{p.tag}] Add to my plan puts it on her plan as her own planned food",
          len(after) == before + 1 and after[-1]["status"] == "planned" and after[-1]["meal"] == "dinner" and after[-1]["added_by"] is None, str(after))
    answers = [sg["answer"] for sg in kim.json("GET", f"/api/shared/{share_id}/suggestions")["suggestions"]]
    check(f"[{p.tag}] Kim's list then says it was added", answers == ["accepted"], str(answers))
    page.goto("/")
    page.wait_for_selector("#date-next", state="visible", timeout=30000)
    wait_text(page, "#view-today", "Added by kim")
    check(f"[{p.tag}] Today says kim added the banana she ate", "Banana" in text_of(page, "#view-today") and "Added by kim" in text_of(page, "#view-today"))


def walk_demo(p: Pass) -> None:
    page = p.page
    page.goto("/?mock=1")
    page.wait_for_selector("#form-login:not([hidden]), #settings-open", timeout=30000)
    if page.is_visible("#form-login"):
        page.fill("#login-username", "sam")
        page.fill("#login-password", "any demo password at all 15")
        page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-sharing-list", timeout=20000)
    text = text_of(page, "#set-sharing")
    check(f"[{p.tag}] the demo shows a sample Care team", "Jordan" in text and "invites for you" in text.lower() and "Ana" in text, text[:300])
    page.click("#tab-plan")
    page.wait_for_selector("#care-for:not([hidden])", timeout=20000)
    page.wait_for_selector("#plan-suggestions:not([hidden])", timeout=20000)
    check(f"[{p.tag}] the demo shows a suggestion from Jordan on your own Plan tab", "jordan suggests dinner" in text_of(page, "#plan-suggestions").lower(),
          text_of(page, "#plan-suggestions")[:200])
    page.select_option("#care-for-select", label="Ana")
    page.wait_for_selector("#care-banner", timeout=20000)
    check(f"[{p.tag}] the demo can help Ana", "You are helping Ana" in text_of(page, "#care-banner"))
    check(f"[{p.tag}] helping someone hides your own suggestions", not page.is_visible("#plan-suggestions"))
    wait_text(page, "#care-meals", "Rice and chicken")
    page.wait_for_selector("#care-suggest-send", timeout=20000)
    check(f"[{p.tag}] the demo shows Ana's saved meal and Suggest a meal", page.is_visible("#care-suggest-send"))
    p.no_overflow("demo")
    p.finish(demo=True)


def walk_question_order(p: Pass) -> None:
    """Deferred synthetic link-info replies; no synthetic link is accepted on the server."""
    result = p.page.evaluate("""async () => {
      const realFetch = window.fetch;
      const oldUrl = location.pathname + location.search + location.hash;
      const pending = new Map();
      let accepts = 0;
      const code = (id, verifier) => id.repeat(16) + '.' + verifier.repeat(43);
      const a = code('a', 'B'), b = code('c', 'D'), c = code('e', 'F'), d = code('1', 'G'), e = code('2', 'H');
      const dlg = document.querySelector('#sheet-share'), accept = document.querySelector('#share-accept');
      const tick = () => new Promise(r => setTimeout(r, 0));
      const wait = async key => {
        for (let n = 0; n < 100 && !pending.has(key); ++n) await tick();
        if (!pending.has(key)) throw new Error('synthetic link-info read did not start');
      };
      const begin = code => {
        history.replaceState(null, '', '/#/share/' + code);
        KH.sharing.takeLink();
        return KH.sharing.openPending();
      };
      const info = name => ({name, username: name.toLowerCase(), areas: ['food']});
      window.fetch = (input, options = {}) => {
        const path = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
        if (path === '/api/shared/info') return new Promise(resolve => {
          pending.set(JSON.parse(options.body).code, person => resolve(new Response(JSON.stringify(person),
            {status: 200, headers: {'Content-Type': 'application/json'}})));
        });
        if (path === '/api/shared/accept') { ++accepts; throw new Error('synthetic link must not be accepted'); }
        return realFetch(input, options);
      };
      try {
        const first = begin(a), second = begin(b);
        await wait(a); await wait(b);
        pending.get(b)(info('Sam')); await second;
        pending.get(a)(info('Ana')); await first;
        const current = {question: document.querySelector('#share-question').innerText,
          codeMatches: accept.dataset.code === b, visible: !accept.hidden};
        const closing = begin(c);
        await wait(c); dlg.close();
        pending.get(c)(info('Closed')); await closing; await tick();
        const closed = !dlg.open && !accept.dataset.code && accept.hidden;
        const beforeReopen = begin(d);
        await wait(d); pending.get(d)(info('Before')); await beforeReopen;
        dlg.close();
        const reopened = begin(e);
        await wait(e); pending.get(e)(info('Latest')); await reopened; await tick();
        return {current, closed, reopened: dlg.open && accept.dataset.code === e && !accept.hidden,
          question: document.querySelector('#share-question').innerText, accepts};
      } finally {
        dlg.close(); await tick();
        window.fetch = realFetch;
        history.replaceState(null, '', oldUrl);
      }
    }""")
    check(f"[{p.tag}] delayed link info cannot replace the latest question or Accept code",
          result["current"]["question"].startswith("Sam") and result["current"]["codeMatches"] and result["current"]["visible"])
    check(f"[{p.tag}] closing a pending share question leaves no Accept code", result["closed"])
    check(f"[{p.tag}] reopening survives a queued close event from the older question",
          result["reopened"] and result["question"].startswith("Latest"))
    check(f"[{p.tag}] synthetic question checks accepted no link", result["accepts"] == 0)


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
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook")}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, "shareadmin")
        admin.json("PATCH", "/api/admin/settings", {"sharing.enabled": True})
        ana = invite_user(server, admin, "ana")
        sam = invite_user(server, admin, "sam")
        kim = invite_user(server, admin, "kim")
        banana = ana.json("GET", "/api/foods", params={"q": "banana"})["foods"][0]["id"]
        ana.json("POST", "/api/log", {"date": date.today().isoformat(), "meal": "breakfast", "food_id": banana, "servings": 1})
        ana.json("POST", "/api/labs", {"analyte": "potassium", "value": 4.8, "unit": "mmol/L", "taken_on": date.today().isoformat()})
        glucose = ana.json("GET", "/api/foods", params={"q": "glucose"})["foods"][0]["id"]
        ana.json("POST", "/api/log", {"date": date.today().isoformat(), "meal": "snack", "food_id": glucose, "servings": 1})
        ana.json("PUT", "/api/profile", {"targets": {"potassium_mg": 2000, "phosphorus_mg": 800, "sodium_mg": 1500}})
        rice = ana.json("GET", "/api/foods", params={"q": "rice"})["foods"][0]["id"]
        ana.json("POST", "/api/meals", {"name": "Ana's lunch", "meal_hint": "lunch", "items": [{"food_id": rice, "servings": 1}]})
        base = server.base
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                ana_pass = Pass(browser, base, out, 375, 812, "light", "ana-375-light", ana.cookies())
                link = walk_ana_shares(ana_pass)
                sam_pass = Pass(browser, base, out, 1280, 800, "dark", "sam-1280-dark", sam.cookies())
                walk_sam_accepts(sam_pass, link)
                walk_question_order(sam_pass)
                walk_sam_trends(sam_pass)
                share_id = sam.json("GET", "/api/shared")["people"][0]["id"]
                walk_admin(Pass(browser, base, out, 1280, 800, "dark", "admin-1280-dark", admin.cookies()), admin)
                walk_ana_stops(ana_pass)
                walk_sam_after(sam_pass, sam, share_id)
                walk_ana_invites(ana_pass)
                kim_pass = Pass(browser, base, out, 375, 812, "dark", "kim-375-dark", kim.cookies())
                walk_kim_plans(kim_pass, kim, ana)
                walk_ana_sees_who(ana_pass)
                kim_share = walk_ana_switches(ana_pass, ana)
                walk_kim_helps(kim_pass, kim, ana)
                kim_pass.finish(refused=[f"POST /api/shared/{kim_share}/suggestions"] * 2)  # a food for a low, and a note about insulin
                walk_ana_suggestion(ana_pass, ana, kim, kim_share)
                ana_pass.finish()
                walk_demo(Pass(browser, base, out, 375, 812, "light", "demo-375-light"))
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc(limit=3))
    finally:
        server.stop()
    failed = any(not r["ok"] for r in RESULTS)
    (out / "report.json").write_text(json.dumps({"results": RESULTS, "failed": failed}, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in RESULTS)} passed, {sum(not r['ok'] for r in RESULTS)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
