#!/usr/bin/env python3
"""Notes from the Care team (design note 37 phase 1) with a real server and Chromium, two people.

    python3 tools/e2e/clinician_notes.py --out /tmp/kh-clinician-notes

Ana (375 px, light) adds Dee to her Care team as a Clinician in Settings (the role says what a note is and that the app does not
check who someone is). Dee (1280 px, dark) accepts, opens Ana's summary, is refused a note about insulin, writes one about the
day she is looking at, sees Write a note in Trends too, and sees "Not read yet" in her Notes. Ana gets the Today card, reads the
note (it is marked read), sees the screen-only line in Visit prep that is not printed, and deletes it. Dee's list is then empty.
No console error, page error or sideways scroll. No external service is called.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import khserver
from khserver import Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}{'' if ok or not detail else f': {detail[:300]}'}", flush=True)


def context(browser: Any, server: Server, who: Any, width: int, theme: str) -> tuple[Any, Any, list[str]]:
    ctx = browser.new_context(base_url=server.base, viewport={"width": width, "height": 850}, color_scheme=theme, service_workers="block")
    ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in who.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    page.on("dialog", lambda d: (errors.append(f"dialog: {d.message}"), d.dismiss()))
    return ctx, page, errors


def text(page: Any, sel: str) -> str:
    return page.eval_on_selector(sel, "el => el.innerText") if page.query_selector(sel) else ""


def no_overflow(page: Any, tag: str) -> None:
    check(f"[{tag}] no sideways scroll", page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))


def open_care(page: Any) -> None:
    page.goto("/#settings")
    page.wait_for_selector("#set-sharing p:not(.muted.small), #set-sharing-off", timeout=30000)
    page.locator("#set-sharing").scroll_into_view_if_needed()


def ana_invites(page: Any, out: Path) -> None:
    open_care(page)
    page.wait_for_selector("#set-care-role-clinician", timeout=20000)
    hint = text(page, "#set-care-clinician-hint")
    check("[ana] the Clinician role says notes are not a medical record and the app does not check who someone is",
          "not a medical record" in hint and "does not check who someone is" in hint, hint)
    page.fill("#set-care-invite-name", "dee")
    page.check("#set-care-role-clinician")
    for area in ("body", "symptoms", "activity"):
        page.uncheck(f"input#set-care-{area}")  # input: the section body is also #set-care-body
    page.click("#set-care-invite")
    page.wait_for_selector("#set-care-sent:has-text('Invite sent')", timeout=20000)
    check("[ana] the invite waits with the Clinician role", "Clinician" in text(page, "#set-care-invites"), text(page, "#set-care-invites"))
    page.screenshot(path=str(out / "ana-invite.png"), full_page=True)
    no_overflow(page, "ana invite")


def dee_writes(page: Any, out: Path) -> None:
    open_care(page)
    page.wait_for_selector("#set-care-for-me", timeout=20000)
    question = text(page, "#set-care-for-me")
    check("[dee] the invite says it is Ana's personal app, not a clinic's record", "as a Clinician" in question
          and "not part of a clinic's record" in question, question)
    page.get_by_role("button", name="Accept the invite from ana").click()
    page.wait_for_selector("#set-shared-list", timeout=20000)
    page.get_by_role("button", name="Open what ana shares with you").click()
    page.wait_for_selector("#view-visit:not([hidden])", timeout=20000)
    page.wait_for_selector("#visit-note-actions:not([hidden])", timeout=20000)
    check("[dee] Ana's summary has Write a note", page.is_visible("#visit-write-note"))
    page.click("#visit-write-note")
    page.wait_for_selector("#sheet-note[open]", timeout=10000)
    check("[dee] the sheet fills in the day and the food log", page.input_value("#note-area") == "food"
          and page.input_value("#note-date") == date.today().isoformat(), f"{page.input_value('#note-area')} {page.input_value('#note-date')}")
    check("[dee] the sheet says what a note is not", "not a medical record" in text(page, "#note-what")
          and "nothing about treating a low" in text(page, "#note-what"))
    page.fill("#note-body", "Take 2 units of insulin before lunch")
    page.click("#note-send")
    page.wait_for_selector("#note-error:not([hidden])", timeout=10000)
    check("[dee] a note about insulin is refused with one sentence", "cannot be about lows, insulin or doses" in text(page, "#note-error"),
          text(page, "#note-error"))
    page.fill("#note-body", "Your potassium was lower on the days you swapped the potato for rice. Keep that up.")
    check("[dee] the counter counts characters", "of 1,000 characters" in text(page, "#note-count"), text(page, "#note-count"))
    with page.expect_response(lambda r: r.url.endswith("/notes") and r.request.method == "POST") as sent:
        page.click("#note-send")
    check("[dee] the note is sent", sent.value.status == 201, str(sent.value.status))
    page.wait_for_selector("#sheet-note[open]", state="hidden", timeout=10000)
    page.screenshot(path=str(out / "dee-summary.png"), full_page=True)
    no_overflow(page, "dee summary")
    open_care(page)
    page.get_by_role("button", name="Open ana's trends").click()
    page.wait_for_selector("#view-trends:not([hidden])", timeout=20000)
    check("[dee] Ana's Trends has Write a note", page.is_visible("#trends-write-note"))
    open_care(page)
    page.get_by_role("button", name="Your notes for ana").click()
    page.wait_for_selector("#view-notes:not([hidden]) .note-card", timeout=20000)
    cards = text(page, "#notes-list")
    check("[dee] her Notes for Ana say Not read yet, with Edit and Withdraw", "Not read yet" in cards
          and page.is_visible("#notes-list button:has-text('Edit')") and page.is_visible("#notes-list button:has-text('Withdraw')"), cards)


def ana_reads(page: Any, out: Path) -> None:
    page.goto("/#today")
    page.wait_for_selector("#today-notes:not([hidden])", timeout=30000)
    card = text(page, "#today-notes")
    check("[ana] Today shows 1 new note from dee", "1 new note from dee" in card, card)
    check("[ana] the card sits under the day's alerts", page.evaluate(
        "() => { const a = document.querySelector('#projected-alerts'), c = document.querySelector('#today-notes');"
        " return !!(a.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING); }"))
    page.screenshot(path=str(out / "ana-today.png"))
    with page.expect_response(lambda r: r.url.endswith("/read") and r.request.method == "POST") as read:
        page.click("#today-notes-read")
    check("[ana] showing the note marks it read", read.value.status == 204, str(read.value.status))
    body = text(page, "#notes-list")
    check("[ana] the note shows who wrote it, what it is about and the text", "dee" in body and "your food log" in body
          and "swapped the potato for rice" in body, body)
    page.screenshot(path=str(out / "ana-notes.png"), full_page=True)
    no_overflow(page, "ana notes")
    page.goto("/#visit")
    page.wait_for_selector("#visit-notes-line:not([hidden])", timeout=20000)
    line = text(page, "#visit-notes-line")
    check("[ana] Visit prep says 1 note from your Care team in this period", "1 note from your Care team in this period" in line, line)
    page.emulate_media(media="print")
    check("[ana] the line is not printed", not page.is_visible("#visit-notes-line"))
    page.emulate_media(media="screen")
    page.click("#visit-notes-open")
    page.wait_for_selector("#view-notes:not([hidden]) .note-card", timeout=20000)
    page.get_by_role("button", name="Delete the note from dee").click()
    page.get_by_role("button", name="Delete", exact=True).click()
    page.wait_for_selector("#notes-list:has-text('No notes from your Care team')", timeout=20000)
    check("[ana] Delete removes the note", True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8118)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "kh-clinician-notes")
    args = parser.parse_args()
    out = khserver.free_dir(args.out)
    env = {"SHARING_ENABLED": "true", "CARE_NOTES_ENABLED": "true", "HANDBOOK_DIR": str(out / "no-handbook")}
    with Server(args.port, out / "data", env=env) as server:
        ana = first_admin(server, "ana")
        dee = invite_user(server, ana, "dee")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                a_ctx, a_page, a_errors = context(browser, server, ana, 375, "light")
                d_ctx, d_page, d_errors = context(browser, server, dee, 1280, "dark")
                ana_invites(a_page, out)
                dee_writes(d_page, out)
                notes = ana.json("GET", "/api/me/notes")
                check("[api] Ana has one unread note before she opens the app", notes["unread"] == 1, json.dumps(notes)[:200])
                ana_reads(a_page, out)
                sid = dee.json("GET", "/api/shared")["people"][0]["id"]
                check("[api] the note is gone for Dee too", dee.json("GET", f"/api/shared/{sid}/notes")["notes"] == [])
                events = {e["action"] for e in ana.json("GET", "/api/me/activity")["events"]}
                check("[api] Ana's activity has the note written, deleted and Dee's looks",
                      {"care_note.written", "care_note.deleted", "share.viewed"} <= events, str(sorted(events)))
                check("[ana] no console error, page error or dialog", not a_errors, "; ".join(a_errors[:5]))
                # the refused note about insulin is the one expected 400 (the browser logs it as a failed resource)
                d_errors = [e for e in d_errors if "status of 400" not in e] if sum("status of 400" in e for e in d_errors) == 1 else d_errors
                check("[dee] no console error, page error or dialog", not d_errors, "; ".join(d_errors[:5]))
                a_ctx.close()
                d_ctx.close()
            finally:
                browser.close()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = [n for n, ok, _ in RESULTS if not ok]
    (out / "report.json").write_text(json.dumps({"passed": passed, "failed": failed}, indent=1), encoding="utf-8")
    print(f"{passed} passed, {len(failed)} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
