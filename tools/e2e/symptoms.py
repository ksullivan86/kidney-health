#!/usr/bin/env python3
"""The symptoms log (schema step 15) in Chromium, against a real server and the demo.

    python tools/e2e/symptoms.py                       # port 8078
    python tools/e2e/symptoms.py --port 8078 --out /tmp/kh-symptoms

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``HANDBOOK_PUBLIC_URL`` set (so the Get help now link has a
place to go), finishes first-run setup and invites a second person who records a symptom of their own. Then, at 375x812
light and 1280x800 dark:

* Today shows the Symptoms card with an Add button; Save with nothing chosen says what is missing and sends nothing;
  choosing Swelling or Breathlessness shows the handbook's line in the sheet, choosing Itching shows none;
* a severe breathlessness is saved, listed first as a block with the handbook's words and a link ending in
  ``/get-help-now/``; a mild itching has no such line; Edit changes the severity; Delete asks in the page first;
* Trends lists the symptom days (a row per symptom, the number of days, the worst severity, the dates in words);
* the other person's symptom is visible nowhere and the browser sent nothing to any other host;
* the demo (``/?mock=1``) does the same add, edit and delete with its own data;
* no sideways scroll, no console error, no dialog.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``;
exit status 1 on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from khserver import Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "symptoms"
PORT = 8078
RESULTS: list[dict[str, Any]] = []
USER = "symptom"
HANDBOOK = "https://handbook.example.org/"


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


class Watch:
    """Hosts asked, dialogs, console errors and page errors of one page."""

    def __init__(self, page: Any) -> None:
        self.hosts: set[str] = set()
        self.writes: list[tuple[str, str]] = []
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


def add_symptom(page: Any, kind: str, severity: int, note: str = "", label: str = "") -> None:
    page.click("#symptoms-add")
    page.wait_for_selector("#sheet-symptom[open]", timeout=10000)
    page.select_option("#symptom-kind", kind)
    if label:
        page.fill("#symptom-label", label)
    page.click(f"label[for=symptom-sev-{severity}]")
    if note:
        page.fill("#symptom-note", note)
    page.click("#symptom-save")
    page.wait_for_selector("#sheet-symptom", state="hidden", timeout=10000)


def today_pass(browser: Any, admin: Any, base: str, out: Path, width: int, height: int, scheme: str, mock: bool = False) -> None:
    tag = f"{'demo-' if mock else ''}{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    if not mock:
        ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    page.goto("/?mock=1" if mock else "/")
    page.wait_for_selector("#symptoms-add", state="visible", timeout=30000)
    page.wait_for_selector("#symptoms-today-body .symptoms-empty, #symptoms-today-body .sym-list", timeout=20000)
    if not mock:
        check(f"[{tag}] Today has the Symptoms card, empty to begin with", "No symptoms recorded for this day" in page.inner_text("#symptoms-today-body"),
              page.inner_text("#symptoms-today-body"))
    # nothing chosen: the sheet says what is missing and sends nothing
    before = len(watch.writes)
    page.click("#symptoms-add")
    page.wait_for_selector("#sheet-symptom[open]", timeout=10000)
    page.click("#symptom-save")
    check(f"[{tag}] saving with nothing chosen says what to choose and writes nothing",
          "Choose which symptom" in page.inner_text("#symptom-error") and len(watch.writes) == before, page.inner_text("#symptom-error"))
    page.select_option("#symptom-kind", "swelling")
    flag = page.inner_text("#symptom-flag")
    check(f"[{tag}] choosing swelling shows the handbook's line in the sheet", "new swelling of the legs, ankles or face" in flag and "Call your care team today" in flag, flag)
    page.select_option("#symptom-kind", "itching")
    check(f"[{tag}] choosing itching shows no such line", page.inner_text("#symptom-flag").strip() == "")
    page.select_option("#symptom-kind", "other")
    check(f"[{tag}] other asks for a name", page.is_visible("#symptom-label"))
    page.click("#symptom-save")
    check(f"[{tag}] other without a name is refused in the sheet", "Name the symptom" in page.inner_text("#symptom-error"), page.inner_text("#symptom-error"))
    page.screenshot(path=str(out / "shots" / f"sheet-{tag}.png"))
    page.click("#sheet-symptom [data-close].btn")
    page.wait_for_selector("#sheet-symptom", state="hidden", timeout=10000)
    # a mild itching, then a severe breathlessness
    add_symptom(page, "itching", 1, note="at night")
    add_symptom(page, "breathlessness", 3, note="<b>after the stairs</b>")
    page.wait_for_selector("#symptoms-today-body .sym-flag.prominent", timeout=10000)
    items = page.locator("#symptoms-today-body .sym-item").all_inner_texts()
    check(f"[{tag}] both are listed, the severe red flag first", len(items) == 2 and items[0].startswith("Breathlessness") and items[1].startswith("Itching"), str(items))
    prominent = page.inner_text("#symptoms-today-body .sym-flag.prominent")
    check(f"[{tag}] the severe one carries the handbook's words", "severe breathlessness" in prominent and "Call 911 now" in prominent and prominent.startswith("Severe."), prominent)
    link = page.locator("#symptoms-today-body .sym-flag.prominent a")
    if mock:
        # the demo without the published handbook next to it shows no Learn links anywhere (js/mock/handbook.js); the line stays
        check(f"[{tag}] the demo has no handbook to link to, so no link, and the handbook's words stay", link.count() == 0, str(link.count()))
    else:
        check(f"[{tag}] the link goes to the handbook's Get help now page", link.count() == 1 and link.get_attribute("href") == HANDBOOK + "get-help-now/",
              link.get_attribute("href") if link.count() else "no link")
    check(f"[{tag}] the itching line has no handbook line and no link", page.locator(".sym-item", has_text="Itching").locator(".sym-flag").count() == 0)
    check(f"[{tag}] a note is shown as text, never as markup", "<b>after the stairs</b>" in page.inner_text("#symptoms-today-body") and page.locator("#symptoms-today-body b").count() == 1,
          "the only <b> is the 'Severe.' lead")
    page.screenshot(path=str(out / "shots" / f"today-{tag}.png"))
    # edit: the severity of the itching
    page.locator(".sym-item", has_text="Itching").get_by_role("button", name="Edit").click()
    page.wait_for_selector("#sheet-symptom[open]", timeout=10000)
    check(f"[{tag}] edit opens with the saved values", page.input_value("#symptom-kind") == "itching" and page.is_checked("#symptom-sev-1")
          and page.input_value("#symptom-note") == "at night")
    page.click("label[for=symptom-sev-2]")
    page.click("#symptom-save")
    page.wait_for_selector("#sheet-symptom", state="hidden", timeout=10000)
    page.wait_for_function("() => /Moderate/.test(document.querySelector('#symptoms-today-body').innerText)", timeout=10000)
    check(f"[{tag}] the change is shown", "Moderate" in page.locator(".sym-item", has_text="Itching").inner_text())
    # delete asks in the page first
    page.locator(".sym-item", has_text="Itching").get_by_role("button", name="Delete").click()
    page.wait_for_selector(".confirm-row", timeout=10000)
    check(f"[{tag}] delete asks in the page, with no browser dialog", not watch.dialogs and "Delete Itching" in page.inner_text(".confirm-row"), page.inner_text(".confirm-row"))
    page.screenshot(path=str(out / "shots" / f"confirm-{tag}.png"))
    page.click(".confirm-row .btn.danger-solid")
    page.wait_for_function("() => document.querySelectorAll('#symptoms-today-body .sym-item').length === 1", timeout=10000)
    # Trends
    page.click("#tab-trends")
    page.wait_for_selector("#symptoms-trends-body .sym-group", timeout=20000)
    trends = page.inner_text("#symptoms-trends-body")
    check(f"[{tag}] Trends lists the symptom with its days and worst severity", "Breathlessness" in trends and "1 day, worst: severe" in trends and "Itching" not in trends, trends)
    check(f"[{tag}] Trends shows the handbook's line for the red flag", "Call 911 now" in trends)
    check(f"[{tag}] the marks are decoration; the dates are in words", page.locator(".sym-strip[aria-hidden='true'] i[data-sev='3']").count() == 1 and "severe" in page.inner_text(".sym-dates"))
    page.screenshot(path=str(out / "shots" / f"trends-{tag}.png"))
    check(f"[{tag}] no sideways scroll on Trends", not overflow(page))
    check(f"[{tag}] the other person's symptom is on no page", "secret" not in page.inner_text("body").lower())
    page.click("#tab-today")
    page.wait_for_selector("#symptoms-today-body .sym-item", timeout=10000)
    check(f"[{tag}] no sideways scroll on Today, no console error, no dialog", not overflow(page) and not watch.errors and not watch.dialogs, "; ".join(watch.errors))
    if not mock:
        others = sorted(h for h in watch.hosts if h not in (urlsplit(base).netloc,))
        check(f"[{tag}] the browser asked no other host", not others, str(others))
    ctx.close()


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
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_PUBLIC_URL": HANDBOOK}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, USER)
        admin.json("PUT", "/api/profile", {"weight_kg": 70})
        sam = invite_user(server, admin, "sam")
        today = date.today().isoformat()
        secret = sam.json("POST", "/api/symptoms", {"date": today, "symptom": "other", "label": "Sam's secret symptom", "severity": 2})
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    today_pass(browser, admin, base, out, width, height, scheme)
                    mine = admin.json("GET", "/api/symptoms", params={"start": today, "end": today})["symptoms"]
                    check(f"[{width}-{scheme}] the server holds the one symptom left, Sam's is not in the list",
                          [s["symptom"] for s in mine] == ["breathlessness"], str(mine))
                    for s in mine:
                        admin.call("DELETE", f"/api/symptoms/{s['id']}")  # leave the day empty for the next pass
                theirs = sam.json("GET", "/api/symptoms", params={"start": today, "end": today})["symptoms"]
                check("Sam's symptom is still there, untouched", [s["id"] for s in theirs] == [secret["id"]])
                today_pass(browser, admin, base, out, 375, 812, "light", mock=True)
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
