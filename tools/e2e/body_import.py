#!/usr/bin/env python3
"""The Health app import sheet for weights and blood pressure (note 10 section 4.8, Part C) in Chromium, against a real server and the demo.

    python tools/e2e/body_import.py                    # port 8087
    python tools/e2e/body_import.py --port 8087 --out /tmp/kh-body-import

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` (every outside proxy points at a closed port, so an outside request fails
loudly), finishes first-run setup and then, for each of 375x812 light, 1280x800 dark, 375x812 dark and 1280x800 light, signs in a
fresh person and opens the sheet with ``KH.bodyImport.open()`` (the Trends and Settings buttons are another part's). A small
generated ``export.xml`` (a DTD at the top, kg and lb weights, blood pressure in a Correlation and loose, a lone half, an
out-of-range weight and reading, a weight in grams, a source named with markup, readings from "Sam's Apple Watch", and heart rate,
glucose, insulin and step records that must be ignored) is chosen, and:

* the steps are on the sheet; export.zip and export_cda.xml are refused with a reason; nothing is written while the file is read
  or reviewed;
* the review says what was found, kept and left out in words, the date range, the last 3 months by default with its counts,
  "everything" with its own, the watch readings listed apart and unticked with the cuffless line, the sources as text (a name
  made of markup is text and runs nothing); at the phone width the Import button is in view and nothing scrolls sideways;
* Import adds the weights and readings of the period (the server's rows are read back through the API: values, contexts,
  ``source`` apple_health, none from the watch), the batch bodies carry no ``sourceName`` and no file name, and the page
  reloads Today;
* the same file again adds 0 ("already here"); "everything" with the watch ticked adds the rest;
* a file with a day of 25 weights: the review says how many will be left out, the server ends with 20 on that day (the earliest
  by time; with 3 weights typed in by hand on that day, 17 of the file's), the result says "n more on 1 day were left out",
  and the same file again adds 0;
* a refusal from the server in the middle (the blood pressure batch answers 400) stops with the server's words and says what was
  already added; pressing Import again carries on without repeating the weights;
* Cancel while a slow read is in progress aborts it (the stream is cancelled), shows the progress line first, and sends nothing;
* no console error, no CSP violation, no dialog, no request to any other host.

The demo (``/?mock=1``, the sheet against ``js/mock/body.js``) runs the same steps at 375x812 light and 1280x800 dark, except the
refusal (its calls are not network requests).

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``;
exit status 1 on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
import zipfile
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from khserver import Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "body_import"
PORT = 8087
RESULTS: list[dict[str, Any]] = []
TODAY = date.today()
HOSTILE = "<img src=x onerror=alert(1)> Scale"
WATCH = "Sam’s Apple Watch"
LB = Decimal("0.45359237")


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


def words(d: str) -> str:
    """'Oct 4, 2026' as the sheet writes a day."""
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{date(y, m, dd).strftime('%b')} {dd}, {y}"


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


# --------------------------------------------------------------------------- the generated export.xml

def attr(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def context_of(kind: str, hhmm: str) -> str:
    """The note's windows, written out again here: morning 04:00-10:59; a reading is evening 17:00-23:59; else other."""
    minutes = int(hhmm[:2]) * 60 + int(hhmm[3:])
    if 240 <= minutes <= 659:
        return "morning"
    if kind == "reading" and minutes >= 1020:
        return "evening"
    return "other"


def kg_of(value: str, unit: str) -> float:
    kg = Decimal(value) if unit == "kg" else Decimal(value) * LB
    return float(kg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class Export:
    """Records for an export.xml and, written independently of the page, what the page must find in them."""

    def __init__(self) -> None:
        self.records: list[str] = []
        self.weights: list[dict[str, Any]] = []  # kept: {offset, time, kg, source}
        self.readings: list[dict[str, Any]] = []  # kept: {offset, time, sys, dia, source}
        self.counts = {"found_w": 0, "found_r": 0, "unit": 0, "half": 0, "bad_w": 0, "bad_r": 0}

    def stamp(self, offset: int, hhmm: str) -> str:
        return f"{day(offset)} {hhmm}:00 -0400"

    def weight(self, offset: int, hhmm: str, value: str, unit: str, source: str) -> None:
        self.records.append(f'<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="{attr(source)}" sourceVersion="1" unit="{unit}" '
                            f'creationDate="{self.stamp(offset, hhmm)}" startDate="{self.stamp(offset, hhmm)}" endDate="{self.stamp(offset, hhmm)}" value="{value}"/>')
        if unit not in ("kg", "lb"):
            self.counts["unit"] += 1
            return
        self.counts["found_w"] += 1
        kg = kg_of(value, unit)
        if not 20 <= kg <= 400:
            self.counts["bad_w"] += 1
            return
        self.weights.append({"offset": offset, "time": hhmm, "kg": kg, "source": source})

    def reading(self, offset: int, hhmm: str, sys_: int, dia: int, source: str, *, correlation: bool = True) -> None:
        st = self.stamp(offset, hhmm)
        common = f'sourceName="{attr(source)}" sourceVersion="1" unit="mmHg" creationDate="{st}" startDate="{st}" endDate="{st}"'
        d = f'<Record type="HKQuantityTypeIdentifierBloodPressureDiastolic" {common} value="{dia}"/>'
        s = f'<Record type="HKQuantityTypeIdentifierBloodPressureSystolic" {common} value="{sys_}"/>'
        if correlation:
            self.records.append(f'<Correlation type="HKCorrelationTypeIdentifierBloodPressure" sourceName="{attr(source)}" sourceVersion="1" '
                                f'creationDate="{st}" startDate="{st}" endDate="{st}">\n  <MetadataEntry key="HKWasUserEntered" value="0"/>\n  {d}\n  {s}\n </Correlation>')
        else:
            self.records.extend([d, s])
        self.counts["found_r"] += 1
        if not (50 <= sys_ <= 300 and 20 <= dia <= 200 and sys_ > dia):
            self.counts["bad_r"] += 1
            return
        self.readings.append({"offset": offset, "time": hhmm, "sys": sys_, "dia": dia, "source": source})

    def half(self, offset: int, hhmm: str, sys_: int, source: str) -> None:
        st = self.stamp(offset, hhmm)
        self.records.append(f'<Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="{attr(source)}" unit="mmHg" startDate="{st}" value="{sys_}"/>')
        self.counts["half"] += 1

    def ignored(self) -> None:
        st = self.stamp(1, "07:00")
        for kind, unit, value in (("HeartRate", "count/min", "61"), ("BloodGlucose", "mg/dL", "104"), ("InsulinDelivery", "IU", "3"), ("StepCount", "count", "812")):
            self.records.append(f'<Record type="HKQuantityTypeIdentifier{kind}" sourceName="Health" unit="{unit}" startDate="{st}" value="{value}"/>')

    def write(self, path: Path) -> Path:
        head = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE HealthData [\n<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout)*)>\n'
                '<!ATTLIST HealthData locale CDATA #REQUIRED>\n<!ENTITY lol "ha">\n]>\n<HealthData locale="en_US">\n'
                f' <ExportDate value="{TODAY.isoformat()} 08:00:00 -0400"/>\n <Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexNotSet"/>\n')
        path.write_text(head + "".join(f" {r}\n" for r in self.records) + "</HealthData>\n", encoding="utf-8")
        return path


def main_export() -> Export:
    x = Export()
    for i in range(1, 11):  # ten days of weights, kg and lb, from a scale
        if i % 2:
            x.weight(i, "07:30", f"{70 + i / 10:.1f}", "kg", "Withings Body+")
        else:
            x.weight(i, "07:30", f"{154 + i / 5:.1f}", "lb", "Withings Body+")
    x.weight(2, "21:10", "69.9", "kg", HOSTILE)  # a source named with markup
    for i in range(130, 135):  # older than three months
        x.weight(i, "07:30", f"{71 + (i - 130) / 10:.1f}", "kg", "Withings Body+")
    x.weight(3, "12:00", "500", "kg", "Health")  # outside 20-400 kg
    x.weight(4, "12:00", "70000", "g", "Health")  # a unit the app does not read
    for i in range(1, 7):
        x.reading(i, "08:05", 118 + i, 76 + i, "Omron Connect")
    x.reading(7, "20:15", 131, 84, "Omron Connect", correlation=False)  # a loose pair, an evening reading
    for i in (140, 141):
        x.reading(i, "08:05", 125, 80, "Omron Connect")
    for i in (1, 2, 3):
        x.reading(i, "09:00", 118, 76, WATCH)
    x.reading(150, "09:00", 117, 75, WATCH)
    x.half(8, "10:00", 119, "Omron Connect")
    x.reading(9, "10:30", 400, 80, "Omron Connect")  # outside 50-300
    x.ignored()
    return x


def crowded_export() -> Export:
    """25 weights on one day (the app keeps 20), and two on other days."""
    x = Export()
    x.weight(1, "07:30", "70.5", "kg", "Withings Body+")
    x.weight(25, "07:30", "70.7", "kg", "Withings Body+")
    for i in range(25):
        x.weight(20, f"06:{i:02d}", f"{70 + i / 100:.2f}", "kg", "Withings Body+")
    return x


def refusal_export() -> Export:
    x = Export()
    x.weight(30, "07:30", "71.9", "kg", "Withings Body+")
    x.reading(30, "08:00", 126, 81, "Omron Connect")
    return x


def big_export(path: Path, megabytes: int = 40) -> Path:
    """Mostly heart-rate records (ignored by the app), so reading takes a while."""
    line = f'<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Health" unit="count/min" startDate="{day(1)} 07:15:00 -0400" value="61"/>\n'
    block = line * 20000
    with path.open("w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<HealthData locale="en_US">\n')
        for _ in range(megabytes * 1024 * 1024 // len(block) + 1):
            f.write(block)
        f.write("</HealthData>\n")
    return path


# --------------------------------------------------------------------------- the page

SLOW_STREAM = """
(() => {
  window.__slow = 0; window.__cancelled = false; window.__csp = [];
  document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
  const orig = Blob.prototype.stream;
  Blob.prototype.stream = function () {
    const reader = orig.call(this).getReader();
    return new ReadableStream({
      async pull(controller) {
        if (window.__slow) await new Promise((r) => setTimeout(r, window.__slow));
        const { done, value } = await reader.read();
        if (done) controller.close(); else controller.enqueue(value);
      },
      cancel(reason) { window.__cancelled = true; return reader.cancel(reason); },
    });
  };
})();
"""


class Watch:
    """Hosts asked, writes sent (with the bodies of the batch posts), dialogs, console errors and page errors of one page."""

    def __init__(self, page: Any) -> None:
        self.hosts: set[str] = set()
        self.writes: list[tuple[str, str]] = []
        self.batches: list[tuple[str, str]] = []
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
            if parts.path.endswith("/batch"):
                self.batches.append((parts.path, r.post_data or ""))


def open_sheet(page: Any) -> None:
    page.evaluate("() => KH.bodyImport.open()")
    page.wait_for_selector("#sheet-body-import[open]", timeout=10000)


def choose(page: Any, path: Path) -> None:
    page.set_input_files("#body-import-file", str(path))


def await_review(page: Any) -> str:
    page.wait_for_selector("#body-import-summary", timeout=60000)
    return page.inner_text("#body-import-review")


def rows_of(page: Any) -> dict[str, set[tuple]]:
    """The weights and readings the page's API answers for the last 200 days (the server's rows, or the demo's)."""
    start, end = day(200), day(0)
    out = page.evaluate("async ([s, e]) => ({ w: (await KH.api.bodyWeights(s, e)).weights, r: (await KH.api.bloodPressures(s, e)).readings })", [start, end])
    return {
        "weights": {(w["date"], w["time"], w["kg"], w["context"], w["source"]) for w in out["w"]},
        "readings": {(r["date"], r["time"], r["systolic"], r["diastolic"], r["context"], r["source"]) for r in out["r"]},
        "all_w": out["w"],
    }


def want_weights(x: Export, *, since: int | None) -> set[tuple]:
    return {(day(w["offset"]), w["time"], w["kg"], context_of("weight", w["time"]), "apple_health") for w in x.weights if since is None or w["offset"] <= since}


def want_readings(x: Export, *, since: int | None, watch: bool) -> set[tuple]:
    return {(day(r["offset"]), r["time"], r["sys"], r["dia"], context_of("reading", r["time"]), "apple_health")
            for r in x.readings if (since is None or r["offset"] <= since) and (watch or r["source"] != WATCH)}


def import_now(page: Any, timeout: int = 60000) -> str:
    page.click("#body-import-go")
    page.wait_for_selector("#body-import-result, #body-import-problem:not([hidden])", timeout=timeout)
    return page.inner_text("#sheet-body-import .sheet-body")


def close_sheet(page: Any) -> None:
    if page.is_visible("#sheet-body-import"):
        if page.is_visible("#body-import-cancel"):
            page.click("#body-import-cancel")
        if page.is_visible("#sheet-body-import"):
            page.click("#sheet-body-import [data-close]")
    page.wait_for_selector("#sheet-body-import", state="hidden", timeout=10000)


# --------------------------------------------------------------------------- one pass

def one_pass(browser: Any, base: str, out: Path, files: dict[str, Path], width: int, height: int, scheme: str, *, mock: bool, admin: Any = None,
             manual_first: bool = False) -> None:
    tag = f"{'demo-' if mock else ''}{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    ctx.add_init_script(SLOW_STREAM)
    if not mock:
        ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    page.goto("/?mock=1" if mock else "/")
    page.wait_for_selector("#tab-today", state="visible", timeout=30000)
    page.wait_for_function("() => typeof KH !== 'undefined' && KH.bodyImport && typeof KH.bodyImport.open === 'function'", timeout=20000)
    main = main_export()  # what the page must find, written independently of the page

    # ---- the sheet, its steps, and the files it refuses
    open_sheet(page)
    steps = page.inner_text("#body-import-steps")
    check(f"[{tag}] the sheet shows the steps to export.xml", all(w in steps for w in ("Health", "Export All Health Data", "Files", "export.zip", "apple_health_export/export.xml")), steps)
    check(f"[{tag}] the file chooser takes one XML file and cannot capture", page.get_attribute("#body-import-file", "accept") == ".xml,text/xml,application/xml"
          and page.get_attribute("#body-import-file", "multiple") is None and page.get_attribute("#body-import-file", "capture") is None)
    zpath = out / "files" / "export.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("apple_health_export/export.xml", "<HealthData/>")
    choose(page, zpath)
    page.wait_for_selector("#body-import-problem:not([hidden])", timeout=10000)
    check(f"[{tag}] export.zip is refused with a reason", "whole export" in page.inner_text("#body-import-problem"), page.inner_text("#body-import-problem"))
    cda = out / "files" / "export_cda.xml"
    cda.write_text("<ClinicalDocument/>", encoding="utf-8")
    choose(page, cda)
    page.wait_for_function("() => /clinical documents/.test(document.querySelector('#body-import-problem').innerText)", timeout=10000)
    check(f"[{tag}] export_cda.xml is refused with a reason", "export.xml" in page.inner_text("#body-import-problem"))

    # ---- the review of the main file
    before = rows_of(page)
    writes_before = len(watch.writes)
    choose(page, files["main"])
    text = await_review(page)
    sk = main.counts
    found = f"Found {sk['found_w']} weights and {sk['found_r']} blood pressure readings. The app can keep {len(main.weights)} weights and {len(main.readings)} readings."
    check(f"[{tag}] the headline says what was found and what can be kept", found in text, text[:300])
    first, last = day(150), day(1)
    check(f"[{tag}] the review gives the date range", f"Dates in the file: {words(first)} to {words(last)}." in text, text[:500])
    left = page.inner_text("#body-import-left-out")
    check(f"[{tag}] it says in words what was left out and why",
          all(w in left for w in ("1 record in a unit the app does not read", "1 blood pressure record with only a top number or only a bottom number", "1 weight outside what the app accepts (20 to 400 kg)",
                                  "1 blood pressure reading outside what the app accepts")), left)
    check(f"[{tag}] nothing is written while the file is read and reviewed", len(watch.writes) == writes_before, str(watch.writes[writes_before:]))
    n_recent_w = len(want_weights(main, since=91))
    n_recent_r = len(want_readings(main, since=91, watch=False))
    n_all_w, n_all_r = len(want_weights(main, since=None)), len(want_readings(main, since=None, watch=False))
    check(f"[{tag}] the last 3 months is chosen by default", page.is_checked("#body-import-period-recent") and not page.is_checked("#body-import-period-all"))
    recent_hint = page.inner_text("#body-import-period-recent-hint")
    all_hint = page.inner_text("#body-import-period-all-hint")
    check(f"[{tag}] each period shows its counts (watch readings left out)", f"{n_recent_w} weights and {n_recent_r} readings" in recent_hint
          and f"{n_all_w} weights and {n_all_r} readings" in all_hint, f"{recent_hint} | {all_hint}")
    boxes = page.locator("#body-import-watch input[type=checkbox]")
    watch_text = page.inner_text("#body-import-watch")
    check(f"[{tag}] readings from the watch are listed apart, unticked, with the cuffless line",
          boxes.count() == 1 and not boxes.first.is_checked() and WATCH in watch_text and "not recommended for checking blood pressure" in watch_text
          and "3 readings in this period" in watch_text, watch_text)
    sources = page.inner_text("#body-import-sources")
    check(f"[{tag}] source names are text: markup in one is shown and runs nothing", HOSTILE in sources and page.locator("#sheet-body-import img").count() == 0
          and not watch.dialogs and page.evaluate("() => window.__csp.length") == 0, sources)
    go = page.inner_text("#body-import-go")
    check(f"[{tag}] the Import button says what it will import", go == f"Import {n_recent_w} weights and {n_recent_r} readings", go)
    box = page.evaluate("() => { const r = document.querySelector('#body-import-go').getBoundingClientRect(); return [r.top, r.bottom, r.left, r.right, innerHeight, innerWidth]; }")
    check(f"[{tag}] the Import button is in view and the page does not scroll sideways", 0 <= box[0] and box[1] <= box[4] and box[3] <= box[5] and not overflow(page), str(box))
    check(f"[{tag}] the button is a tap target of 44 px or more", box[1] - box[0] >= 44, str(box))
    page.screenshot(path=str(out / "shots" / f"review-{tag}.png"))
    page.evaluate("() => document.querySelector('#sheet-body-import .sheet-body').scrollTo(0, 99999)")
    page.screenshot(path=str(out / "shots" / f"review-end-{tag}.png"))

    # ---- import the default period
    sent = len(watch.batches)
    result = import_now(page)
    check(f"[{tag}] the result says what was added", f"Added {n_recent_w} weights and {n_recent_r} readings." in result
          and "were already here" not in result and "was already here" not in result, result[:300])
    after = rows_of(page)
    check(f"[{tag}] the weights are stored as the file says (kg, contexts, source apple_health)",
          after["weights"] - before["weights"] == want_weights(main, since=91), str(sorted((after["weights"] - before["weights"]) ^ want_weights(main, since=91))[:4]))
    check(f"[{tag}] the readings are stored as the file says, none from the watch",
          after["readings"] - before["readings"] == want_readings(main, since=91, watch=False), str(sorted((after["readings"] - before["readings"]) ^ want_readings(main, since=91, watch=False))[:4]))
    posted = watch.batches[sent:]
    body = "\n".join(b for _, b in posted)
    if mock:
        check(f"[{tag}] the demo's import is answered in the page: no request was sent", not posted and not watch.writes, str(watch.writes))
    else:
        check(f"[{tag}] the batches went to the two batch routes and carry no source name or file name",
              [p for p, _ in posted] == ["/api/body/weights/batch", "/api/body/blood-pressure/batch"] and "sourceName" not in body and "Withings" not in body
              and "Omron" not in body and "export.xml" not in body and '"source":"apple_health"' in body and WATCH not in body and "Watch" not in body, str([p for p, _ in posted]))
    if not mock:
        api_w = admin.json("GET", "/api/body/weights", params={"start": day(200), "end": day(0)})["weights"]
        check(f"[{tag}] the server's own list agrees", {(w["date"], w["time"], w["kg"]) for w in api_w} >= {(a[0], a[1], a[2]) for a in want_weights(main, since=91)}
              and all(w["source"] == "apple_health" for w in api_w if (w["date"], w["time"], w["kg"], w["context"], "apple_health") in want_weights(main, since=91)))
    page.screenshot(path=str(out / "shots" / f"result-{tag}.png"))
    check(f"[{tag}] the result is the focused line (read out)", page.evaluate("() => document.activeElement && document.activeElement.id") == "body-import-result")

    # ---- the same file again adds nothing
    close_sheet(page)
    open_sheet(page)
    choose(page, files["main"])
    await_review(page)
    sent = len(watch.batches)
    result = import_now(page)
    already = n_recent_w + n_recent_r
    check(f"[{tag}] the same file again adds nothing", f"Added 0 weights and 0 readings; {already} were already here." in result, result[:300])
    check(f"[{tag}] and the rows are the same", rows_of(page)["weights"] == after["weights"] and rows_of(page)["readings"] == after["readings"])

    # ---- everything, with the watch ticked
    close_sheet(page)
    open_sheet(page)
    choose(page, files["main"])
    await_review(page)
    page.check("#body-import-period-all")
    page.check("#body-import-watch-0")
    n_w = len(want_weights(main, since=None))
    n_r = len(want_readings(main, since=None, watch=True))
    go = page.inner_text("#body-import-go")
    check(f"[{tag}] choosing everything and ticking the watch changes the button", go == f"Import {n_w} weights and {n_r} readings", go)
    result = import_now(page)
    added_w, added_r = n_w - n_recent_w, n_r - n_recent_r
    check(f"[{tag}] it adds the rest and skips what is here", f"Added {added_w} weights and {added_r} readings; {already} were already here." in result, result[:300])
    final = rows_of(page)
    check(f"[{tag}] the stored rows now hold every kept weight and reading, the watch ones too",
          final["weights"] - before["weights"] == want_weights(main, since=None) and final["readings"] - before["readings"] == want_readings(main, since=None, watch=True))
    close_sheet(page)

    # ---- a refusal in the middle (a real server only: the demo's calls are not network requests)
    if not mock:
        page.route("**/api/body/blood-pressure/batch", lambda route: route.fulfill(
            status=400, content_type="application/json", body=json.dumps({"detail": "rows.0: too many blood pressure readings for one day (max 30)"})))
        open_sheet(page)
        choose(page, files["refusal"])
        await_review(page)
        result = import_now(page)
        problem = page.inner_text("#body-import-problem")
        check(f"[{tag}] a refusal stops, shows the server's words and says what was already added",
              "rows.0: too many blood pressure readings for one day (max 30)" in problem and "(the row dated" in problem and "Added 1 weight and 0 readings before it stopped." in problem
              and "Nothing that was added is lost" in problem, problem)
        w_rows = [w for w in admin.json("GET", "/api/body/weights", params={"start": day(40), "end": day(25)})["weights"] if w["date"] == day(30)]
        r_rows = [r for r in admin.json("GET", "/api/body/blood-pressure", params={"start": day(40), "end": day(25)})["readings"] if r["date"] == day(30)]
        check(f"[{tag}] the weight was kept and the reading was not", len(w_rows) == 1 and not r_rows, f"{w_rows} {r_rows}")
        check(f"[{tag}] the sheet is back at the review with Import ready", page.is_enabled("#body-import-go") and page.is_visible("#body-import-summary"))
        page.screenshot(path=str(out / "shots" / f"refused-{tag}.png"))
        refused_errors = [e for e in watch.errors if "status of 400" in e]
        check(f"[{tag}] the forced 400 is the one console line about it (the browser logs every failed request)", len(refused_errors) == 1, str(watch.errors))
        watch.errors[:] = [e for e in watch.errors if "status of 400" not in e]
        page.unroute("**/api/body/blood-pressure/batch")
        result = import_now(page)
        check(f"[{tag}] pressing Import again carries on without repeating the weight", "Added 0 weights and 1 reading; 1 was already here." in result, result[:300])
        close_sheet(page)

    # ---- a day of 25 weights
    day_w = day(20)
    if manual_first:
        for i in range(3):
            page.evaluate("async (b) => KH.api.addWeight(b)", {"date": day_w, "time": f"05:0{i}", "kg": 80 + i, "context": "other"})
    open_sheet(page)
    choose(page, files["crowded"])
    text = await_review(page)
    room = 17 if manual_first else 20
    cut = 25 - room
    note = "5 or more will be left out: 1 day in the file has more than the app keeps (at most 20 weights and 30 readings a day)."
    check(f"[{tag}] the review warns that some of the day's weights will be left out", note in text, text[:400])
    before_c = rows_of(page)
    result = import_now(page)
    added = room + 2
    gone = f"{cut} more on 1 day were left out (the app keeps at most 20 weights and 30 readings a day)."
    check(f"[{tag}] the result says what was added and what was left out", f"Added {added} weights and 0 readings." in result and gone in result, result[:400])
    after_c = rows_of(page)
    on_day = sorted(w["time"] for w in after_c["all_w"] if w["date"] == day_w)
    check(f"[{tag}] the day ends with 20 weights, the earliest of the file's by time", len(on_day) == 20 and (not manual_first or len(on_day) == 20)
          and [t for t in on_day if t.startswith("06:")] == [f"06:{i:02d}" for i in range(room)], str(on_day))
    check(f"[{tag}] only the kept weights were added", len(after_c["weights"] - before_c["weights"]) == added)
    close_sheet(page)
    open_sheet(page)
    choose(page, files["crowded"])
    await_review(page)
    result = import_now(page)
    check(f"[{tag}] the same crowded file again adds nothing and does not call stored weights left out",
          f"Added 0 weights and 0 readings; {added} were already here." in result and gone in result, result[:400])
    check(f"[{tag}] and the day still has 20", len([w for w in rows_of(page)["all_w"] if w["date"] == day_w]) == 20)
    page.screenshot(path=str(out / "shots" / f"crowded-{tag}.png"))
    close_sheet(page)

    # ---- Cancel while reading
    open_sheet(page)
    page.evaluate("() => { window.__slow = 20; window.__cancelled = false; }")
    writes_before = len(watch.writes)
    choose(page, files["big"])
    page.wait_for_function("() => /about/.test(document.querySelector('#body-import-status').innerText)", timeout=60000)
    progress = page.inner_text("#body-import-status")
    check(f"[{tag}] a long read shows a progress line", "Reading big.xml: about" in progress and "MB of" in progress, progress)
    check(f"[{tag}] and its button says Cancel", page.inner_text("#body-import-cancel") == "Cancel")
    page.click("#body-import-cancel")
    page.wait_for_function("() => window.__cancelled === true", timeout=20000)
    page.evaluate("() => { window.__slow = 0; }")
    check(f"[{tag}] Cancel aborts the read (the file stream is cancelled) and returns to the file chooser",
          page.is_visible("#body-import-file") and "Cancelled. Nothing was read or saved." in page.inner_text("#body-import-status")
          and not page.is_visible("#body-import-summary"), page.inner_text("#body-import-status"))
    page.wait_for_timeout(300)
    check(f"[{tag}] nothing was sent after Cancel", len(watch.writes) == writes_before, str(watch.writes[writes_before:]))
    page.screenshot(path=str(out / "shots" / f"cancelled-{tag}.png"))
    close_sheet(page)

    # ---- the whole pass
    check(f"[{tag}] no console error, no CSP violation, no dialog", not watch.errors and not watch.dialogs and page.evaluate("() => window.__csp.length") == 0,
          "; ".join(watch.errors + watch.dialogs + page.evaluate("() => window.__csp")))
    if not mock:
        others = sorted(h for h in watch.hosts if h != urlsplit(base).netloc)
        check(f"[{tag}] the browser asked no other host", not others, str(others))
    allowed = {"/api/body/weights/batch", "/api/body/blood-pressure/batch", "/api/body/weights"}  # the last: the hand-typed weights of the crowded day
    check(f"[{tag}] the browser wrote nothing but the batch posts (and the typed weights)", {p for _, p in watch.writes} <= allowed, str(sorted({p for _, p in watch.writes})))
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
    (out / "files").mkdir()
    files = {
        "main": main_export().write(out / "files" / "export.xml"),
        "crowded": crowded_export().write(out / "files" / "crowded.xml"),
        "refusal": refusal_export().write(out / "files" / "refusal.xml"),
        "big": big_export(out / "files" / "big.xml"),
    }
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, "imp")
        admin.json("PUT", "/api/profile", {"weight_kg": 70})
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for n, (width, height, scheme) in enumerate(((375, 812, "light"), (1280, 800, "dark"), (375, 812, "dark"), (1280, 800, "light"))):
                    person = invite_user(server, admin, f"ann{n}") if n else admin
                    one_pass(browser, base, out, files, width, height, scheme, mock=False, admin=person, manual_first=bool(n % 2))
                    if n:
                        person.close()
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    one_pass(browser, base, out, files, width, height, scheme, mock=True)
            finally:
                browser.close()
        admin.close()
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
