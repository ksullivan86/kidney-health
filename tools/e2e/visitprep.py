#!/usr/bin/env python3
"""Visit prep (ARCHITECTURE.md "Visit prep") in Chromium, against a real server and the demo.

    python tools/e2e/visitprep.py                       # port 8079
    python tools/e2e/visitprep.py --port 8079 --out /tmp/kh-visitprep

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup with a display name, gives the person
targets, five days of food (one food that does not list potassium), lab results, symptoms, and invites a second person with
a symptom and a lab result of their own. Then, at 375x812 light and 1280x800 dark:

* Trends has "Get ready for a visit"; it opens Visit prep with the period, the date it was made and the chosen name;
* the averages equal ``GET /api/log/summary`` for the period (the average, the target, the days over, the counts of foods that
  do not list a value; potassium reads "≥" with its counts, never 0); the lab rows show the newest result, the one before and
  an arrow; the symptoms are grouped with the handbook's line for a severe breathlessness; the other person's data is nowhere;
* a question is added with Enter, shown as text (markup stays text), removed, and gone after a reload; nothing is written to
  localStorage, sessionStorage or the server; the handbook checklist has its six items and can be ticked;
* the period buttons change the summary request (14 days, 90 days); Print / Save as PDF calls ``window.print()`` once (stubbed)
  and adds a question that was typed but not yet added;
* printed (``emulate_media print``): the header, tabs, controls and banners are gone, text is black on white even in the dark
  theme, and a PDF of the page is made (its sheet count is reported, A4 and Letter);
* the browser asks no other host and sends no write (POST, PUT, DELETE); no console error, no dialog, no sideways scroll;
* the demo (``/?mock=1``) shows the page from its own data with the same numbers as its period summary.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``;
exit status 1 on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import json
import re
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

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "visitprep"
PORT = 8079
RESULTS: list[dict[str, Any]] = []
NAME = "Sam Visit"
HANDBOOK = "https://handbook.example.org/"
TODAY = date.today()


def day(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


class Watch:
    """Hosts asked, writes sent, dialogs, console errors and page errors of one page."""

    def __init__(self, page: Any) -> None:
        self.hosts: set[str] = set()
        self.gets: list[str] = []
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
        elif parts.path.startswith("/api/"):
            self.gets.append(parts.path + ("?" + parts.query if parts.query else ""))


def seed(admin: Any, sam: Any) -> None:
    admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {
        "potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": 60, "fluid_ml": 1500}})
    foods = {q: admin.json("GET", "/api/foods", params={"q": q})["foods"][0]["id"] for q in ("banana", "chicken", "rice")}
    bar = admin.json("POST", "/api/foods", {"name": "Mystery bar", "serving_desc": "1 bar", "serving_g": 50,
                                            "nutrients": {"sodium_mg": 120, "potassium_mg": None, "phosphorus_mg": 40}})["id"]
    for n in (1, 2, 3, 5, 8):
        for meal, fid, servings in (("breakfast", foods["banana"], 2), ("lunch", foods["chicken"], 1), ("dinner", foods["rice"], 1), ("snack", bar, 1)):
            admin.json("POST", "/api/log", {"date": day(n), "meal": meal, "food_id": fid, "servings": servings})
    for analyte, value, unit, n in (("potassium", 4.9, "mmol/L", 60), ("potassium", 5.3, "mmol/L", 9), ("phosphate", 5.2, "mg/dL", 60),
                                    ("phosphate", 4.4, "mg/dL", 9), ("albumin", 3.9, "g/dL", 9), ("a1c", 7.1, "%", 60), ("a1c", 7.1, "%", 20)):
        admin.json("POST", "/api/labs", {"analyte": analyte, "value": value, "unit": unit, "taken_on": day(n)})
    admin.json("POST", "/api/symptoms", {"date": day(2), "symptom": "breathlessness", "severity": 3})
    admin.json("POST", "/api/symptoms", {"date": day(4), "symptom": "itching", "severity": 1})
    admin.json("POST", "/api/symptoms", {"date": day(6), "symptom": "itching", "severity": 2})
    sam.json("POST", "/api/symptoms", {"date": day(1), "symptom": "other", "label": "Sam's secret symptom", "severity": 2})
    sam.json("POST", "/api/labs", {"analyte": "potassium", "value": 3.1, "unit": "mmol/L", "taken_on": day(1)})


def expected_rows(page: Any, summary: dict[str, Any]) -> dict[str, dict[str, str]]:
    """What the page must print for each nutrient, formatted the way Trends formats the same summary (KH.rules.fmtNum)."""
    return page.evaluate("""(sum) => {
      const out = {};
      for (const [key, nt] of Object.entries(sum.nutrients)) {
        if (!KH.rules.NUT[key]) continue;
        out[KH.rules.NUT[key].label] = { average: KH.rules.fmtNum(nt.average, key), target: KH.rules.fmtNum(nt.target, key),
          daysOver: nt.days_over, unknownDays: nt.unknown_days || 0, unknownEntries: nt.unknown_entries || 0 };
      }
      return out; }""", summary)


def check_averages(tag: str, page: Any, summary: dict[str, Any], real: bool) -> None:
    exp = expected_rows(page, summary)
    rows = page.locator("#visit-avg-body .visit-avg-row")
    shown = {}
    for i in range(rows.count()):
        row = rows.nth(i)
        shown[row.locator(".visit-avg-name").inner_text()] = {"nums": row.locator(".visit-avg-nums").inner_text(), "foot": row.inner_text()}
    wanted = [k for k in ("Sodium", "Potassium", "Phosphorus", "Protein", "Fluid") if k in exp]
    check(f"[{tag}] the rows are sodium, potassium, phosphorus, protein, then fluid (the targets that are set)", list(shown) == wanted, f"{list(shown)} vs {wanted}")
    bad = []
    for label, e in exp.items():
        row = shown.get(label)
        if not row:
            continue
        first = row["nums"].split(" / ")[0].replace("≥", "").strip()
        if e["unknownDays"] and first != "Not listed":
            ok_avg = row["nums"].startswith("≥ ") and first == e["average"]
        else:
            ok_avg = first == (e["average"] if first != "Not listed" else first)
        if not (ok_avg and f"/ {e['target']}" in row["nums"] and f"{e['daysOver']} day" in row["foot"]):
            bad.append((label, e, row))
        if e["unknownDays"] and f"{e['unknownEntries']} food" not in row["foot"]:
            bad.append((label, "counts", row))
    check(f"[{tag}] every average, target, days over and count of foods not listing a value equals the period endpoint", not bad, str(bad))
    sub = page.inner_text("#visit-avg-sub")
    check(f"[{tag}] it says how many days had entries", f"{summary['logged_days']} of {summary['days']} days had food entries" in sub, sub)
    if real:
        pot = shown.get("Potassium", {})
        check(f"[{tag}] potassium (a food does not list it) is '≥' with the counts, not a plain number or 0",
              pot.get("nums", "").startswith("≥ ") and "do not list potassium" in pot.get("foot", "") and "may be higher" in pot.get("foot", ""), str(pot))


def open_visit(page: Any) -> None:
    page.click("#tab-trends")
    page.wait_for_selector("#visit-open", state="visible", timeout=20000)
    page.click("#visit-open")
    page.wait_for_selector("#view-visit:not([hidden])", timeout=10000)
    page.wait_for_function("() => !document.querySelector('#visit-avg-body').innerText.includes('Loading')"
                           " && !document.querySelector('#visit-sym-body').innerText.includes('Loading')"
                           " && !document.querySelector('#visit-labs-body').innerText.includes('Loading')", timeout=20000)


def storage_snapshot(page: Any) -> str:
    return page.evaluate("() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")


def visit_pass(browser: Any, admin: Any, base: str, out: Path, width: int, height: int, scheme: str, mock: bool = False) -> None:
    tag = f"{'demo-' if mock else ''}{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    if not mock:
        ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    page.add_init_script("window.__prints = 0; window.print = () => { window.__prints += 1; };")
    page.goto("/?mock=1" if mock else "/")
    page.wait_for_selector("#tab-trends", state="visible", timeout=30000)
    open_visit(page)
    before_storage = storage_snapshot(page)
    shot = lambda name: page.screenshot(path=str(out / "shots" / f"{name}-{tag}.png"), full_page=True)  # noqa: E731
    check(f"[{tag}] Trends has the way in, and Visit prep opens with the page", page.is_visible("#visit-page") and "Visit prep" in page.inner_text("#visit-title"))
    head = page.inner_text(".visit-doc-head")
    start, end = day(27), day(0)
    check(f"[{tag}] the page names the period, the date it was made and (when the person gave one) the display name",
          "Last 4 weeks" in head and TODAY.strftime("%Y") in head and "Made on" in head and ((NAME in head) if not mock else True), head)
    check(f"[{tag}] nothing but the chosen name identifies the person", "visit" not in head.lower().replace("visit summary", "").replace("sam visit", ""), head)
    # ---- the averages equal the endpoint
    if mock:
        summary = page.evaluate("async (u) => KH.mock.instance.request('GET', u)", f"/api/log/summary?start={start}&end={end}")
    else:
        summary = admin.json("GET", "/api/log/summary", params={"start": start, "end": end})
    check_averages(tag, page, summary, real=not mock)
    # ---- labs
    labs = page.inner_text("#visit-labs-body")
    rows = page.locator("#visit-labs-body .visit-lab")
    check(f"[{tag}] the lab rows show the newest result, the one before it and an arrow", rows.count() >= 2 and "Before that:" in labs and re.search(r"[↑↓→]", labs), labs)
    if not mock:
        pot = rows.filter(has_text="Potassium").inner_text()
        check(f"[{tag}] potassium 5.3 after 4.9 is ↑, phosphate 4.4 after 5.2 is ↓, a single albumin has no arrow",
              "5.3" in pot and "4.9" in pot and "↑" in pot and "↓" in rows.filter(has_text="Phosphate").inner_text()
              and not re.search(r"[↑↓→]", rows.filter(has_text="Albumin").inner_text()) and "No earlier result" in rows.filter(has_text="Albumin").inner_text(), labs)
        check(f"[{tag}] the arrow is explained to screen readers, and the page says it does not interpret it",
              page.locator(".visit-lab-trend .sr-only").first.inner_text() != "" and "does not say whether the change matters" in labs)
        check(f"[{tag}] a result that is not the person's is nowhere", "3.1" not in labs and "secret" not in page.inner_text("#visit-page").lower())
    # ---- symptoms
    sym = page.inner_text("#visit-sym-body")
    groups = page.locator("#visit-sym-body .visit-sym-row")
    if not mock:
        check(f"[{tag}] the symptoms are grouped with days and the worst severity", groups.count() == 2 and "Itching" in sym and "2 days, worst: moderate" in sym
              and "Breathlessness" in sym and "1 day, worst: severe" in sym, sym)
        check(f"[{tag}] the severe breathlessness comes first, with the handbook's words", groups.first.inner_text().startswith("Breathlessness") and "Call 911 now" in sym
              and groups.first.locator(".sym-flag.prominent").count() == 1, sym)
        link = groups.first.locator("a")
        check(f"[{tag}] the Get help now link is the one the symptoms screens use", link.count() == 1 and link.get_attribute("href") == HANDBOOK + "get-help-now/")
        check(f"[{tag}] the itching has no handbook line", groups.nth(1).locator(".sym-flag").count() == 0)
    # ---- questions
    q = page.locator("#visit-q-input")
    q.fill("Who do I call with questions between visits?")
    q.press("Enter")
    q.fill("<b>bold?</b> <img src=x onerror=alert(1)>")
    q.press("Enter")
    items = page.locator("#visit-q-list .visit-q-text").all_inner_texts()
    check(f"[{tag}] questions are added with Enter and markup stays text", len(items) == 2 and items[1].startswith("<b>bold?</b>") and page.locator("#visit-q-list b, #visit-q-list img").count() == 0, str(items))
    check(f"[{tag}] the empty-list lines for writing by hand are for paper only", page.locator("#visit-blank-lines").is_hidden() and page.locator("#visit-blank-lines").get_attribute("hidden") is not None)
    page.click("#visit-q-add")
    check(f"[{tag}] Add with nothing typed says what to do and adds nothing", "Write a question first" in page.inner_text("#visit-q-error") and page.locator("#visit-q-list li").count() == 2)
    page.locator("#visit-q-list li").nth(1).get_by_role("button", name="Remove").click()
    check(f"[{tag}] a question can be removed", page.locator("#visit-q-list li").count() == 1)
    boxes = page.locator("#visit-checklist input[type=checkbox]")
    check(f"[{tag}] the handbook's six checklist items are there to tick", boxes.count() == 6)
    boxes.nth(0).check()
    check(f"[{tag}] a ticked item stays ticked", boxes.nth(0).is_checked() and not boxes.nth(1).is_checked())
    link = page.locator("#visit-check-link a")
    if mock:
        check(f"[{tag}] the demo has no handbook to link to", link.count() == 0)
    else:
        check(f"[{tag}] the checklist links to the handbook's appointments page", link.count() == 1 and link.get_attribute("href") == HANDBOOK + "living/appointments/", link.get_attribute("href") if link.count() else "none")
    # ---- the questions go nowhere
    check(f"[{tag}] questions and ticks are written to no storage", storage_snapshot(page) == before_storage and "Who do I call" not in storage_snapshot(page), storage_snapshot(page))
    check(f"[{tag}] and no request carries them: the browser sent no write at all", not watch.writes, str(watch.writes))
    # ---- periods
    watch.gets.clear()
    page.click("#visit-periods .seg[data-period='14']")
    page.wait_for_function("() => document.querySelector('#visit-period').innerText.includes('Last 2 weeks')", timeout=10000)
    page.wait_for_function("() => !document.querySelector('#visit-avg-body').innerText.includes('Loading')", timeout=10000)
    if not mock:
        check(f"[{tag}] choosing 2 weeks asks the endpoint for those 14 days", any(f"/api/log/summary?start={day(13)}&end={day(0)}" in g for g in watch.gets), str(watch.gets))
    check(f"[{tag}] the question and tick survive a change of period (same page)", page.locator("#visit-q-list li").count() == 1 and page.locator("#visit-checklist input").nth(0).is_checked())
    page.click("#visit-periods .seg[data-period='90']")
    page.wait_for_function("() => document.querySelector('#visit-period').innerText.includes('Last 3 months')", timeout=10000)
    page.wait_for_function("() => !document.querySelector('#visit-avg-body').innerText.includes('Loading')", timeout=10000)
    if not mock:
        check(f"[{tag}] 3 months asks for 90 days", any(f"/api/log/summary?start={day(89)}&end={day(0)}" in g for g in watch.gets), str(watch.gets))
    page.click("#visit-periods .seg[data-period='28']")
    page.wait_for_function("() => document.querySelector('#visit-period').innerText.includes('Last 4 weeks')", timeout=10000)
    page.wait_for_function("() => !document.querySelector('#visit-avg-body').innerText.includes('Loading')", timeout=10000)
    shot("visit")
    # ---- print
    page.fill("#visit-q-input", "Typed but not added yet")
    page.click("#visit-print")
    check(f"[{tag}] Print / Save as PDF calls window.print() once", page.evaluate("() => window.__prints") == 1)
    check(f"[{tag}] a question typed but not added is added first", page.locator("#visit-q-list .visit-q-text").all_inner_texts()[-1] == "Typed but not added yet")
    page.emulate_media(media="print")
    hidden = {sel: not page.locator(sel).first.is_visible() for sel in (".topbar", "#visit-print", "#visit-periods", "#visit-q-add", "#visit-q-input", "#visit-back", ".visit-q .link-btn", ".visit-check-link")}
    check(f"[{tag}] printed: the header, tabs, buttons and the question box are gone", all(hidden.values()), str(hidden))
    colours = page.evaluate("""() => { const c = (s) => getComputedStyle(document.querySelector(s)); return {
      body: c('body').backgroundColor, text: c('.visit-avg-name').color, who: c('.visit-doc-title').color, avg: c('.visit-avg-nums b').color,
      page: c('#visit-page').backgroundColor, sym: c('.visit-h').color }; }""")
    check(f"[{tag}] printed: black on white whatever the theme", colours["body"] == "rgb(255, 255, 255)" and all(colours[k] == "rgb(0, 0, 0)" for k in ("text", "who", "avg", "sym"))
          and colours["page"] in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)"), str(colours))
    check(f"[{tag}] printed: the handbook's line for the severe breathlessness is still there" if not mock else f"[{tag}] printed: the page is there",
          page.is_visible("#visit-page") and ((not mock and "Call 911 now" in page.inner_text(".visit-sym")) or mock), "")
    if width == 1280:
        for fmt in ("A4", "Letter"):
            pdf = page.pdf(format=fmt, print_background=False, prefer_css_page_size=False)
            sheets = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
            (out / "shots" / f"visit-{fmt}.pdf").write_bytes(pdf)
            check(f"[{tag}] the page makes a PDF on {fmt} ({sheets} sheet{'s' if sheets != 1 else ''})", pdf.startswith(b"%PDF") and sheets == 1, f"{sheets} (this person has five targets, four tests and two symptoms: one sheet is expected)")
            RESULTS[-1]["sheets"] = sheets
        page.screenshot(path=str(out / "shots" / f"print-{tag}.png"), full_page=True)
    page.emulate_media(media="screen")
    check(f"[{tag}] the screen shows the header and controls again", page.is_visible("#visit-print") and page.is_visible(".topbar"))
    # ---- leaving and coming back: the questions are gone after a reload
    page.reload()
    page.wait_for_selector("#tab-trends", state="visible", timeout=30000)
    page.wait_for_selector("#view-visit:not([hidden])", timeout=20000)
    check(f"[{tag}] after a reload the questions and ticks are gone", page.locator("#visit-q-list li").count() == 0 and not page.locator("#visit-checklist input").nth(0).is_checked())
    page.click("#visit-back")
    page.wait_for_selector("#view-trends:not([hidden])", timeout=10000)
    check(f"[{tag}] Back to Trends goes back", page.is_visible("#period-summary"))
    check(f"[{tag}] no sideways scroll, no console error, no dialog", not overflow(page) and not watch.errors and not watch.dialogs, "; ".join(watch.errors))
    page.click("#visit-open")
    page.wait_for_selector("#view-visit:not([hidden])", timeout=10000)
    check(f"[{tag}] no sideways scroll on Visit prep", not overflow(page))
    if not mock:
        others = sorted(h for h in watch.hosts if h != urlsplit(base).netloc)
        check(f"[{tag}] the browser asked no other host and sent no write", not others and not watch.writes, f"{others} {watch.writes}")
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
        admin = first_admin(server, "visit", display_name=NAME)
        sam = invite_user(server, admin, "other")
        seed(admin, sam)
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    visit_pass(browser, admin, base, out, width, height, scheme)
                visit_pass(browser, admin, base, out, 375, 812, "light", mock=True)
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
