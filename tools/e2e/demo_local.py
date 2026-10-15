#!/usr/bin/env python3
"""The Pages demo with "Keep my data in this browser" (ARCHITECTURE.md "Keep my data in this browser") in Chromium.

    python tools/e2e/demo_local.py                       # no server: the demo is built and served statically
    python tools/e2e/demo_local.py --out /tmp/kh-demo-local --only keep,private

Builds the GitHub Pages demo (``scripts/build_preview.py --pages``), serves it from a throw-away static server on localhost and
walks it the way a person does, at 375x812 light and 1280x800 dark, each part in a fresh browser context (a fresh profile):

* ``keep``: nothing is stored before the person chooses (no database in the browser after a reload); the banner button opens the sheet,
  which says plainly that the data stays in this browser, can be lost, should be exported, is visible on a shared device, and that a
  real server is the way for real use; the button stays off until "I understand" is ticked; turning it on (an empty log of one's own)
  stores a copy and asks the browser to keep it (a stubbed ``navigator.storage.persist`` answers, and the sheet shows the answer);
  an entry is added, the page reloaded: the entry is still there and the mode still on;
* ``export``: Settings → Your data downloads ``export.json`` in the server's shape; ``stop``: "Stop keeping data here" asks in the page
  (no browser dialog), Cancel keeps the copy, Delete removes the database and the sample demo is back; then the file is imported into
  an empty log through Settings → Import from a file (what it would add is shown first; nothing before Import), a refused file is
  refused in the server's words, and importing the same file again adds nothing;
* ``tabs``: two tabs of the same demo: the second to save stops and says so instead of overwriting the first;
* ``private``: a browser that refuses IndexedDB (private browsing, a sandboxed frame): the sheet says so, the button stays off, the
  demo keeps working in memory; ``newer``: a copy saved by a newer version is not loaded, not overwritten, and the sheet says why;
* every part: no request to any other host or to an /api route, no console or page error (CSP violations included), no sideways scroll.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1
on any failure. The static server and the browser are always stopped.
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
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "demo-local"
RESULTS: list[dict[str, Any]] = []
SECTIONS = ("keep", "export", "stop", "tabs", "private", "newer")
# app/account.py export_data, in its order (tests/test_demo_local_ui.py keeps this list equal to the server's)
EXPORT_KEYS = ["format", "version", "exported_at", "app_version", "user", "profile", "settings", "log_entries", "custom_foods", "linked_foods",
               "meal_templates", "lab_results", "symptoms", "ai_audit", "activity", "food_preferences", "ai_usage", "ai_consents", "ai_provider",
               "builtin_foods"]
ENTRY = "Oat bar for the test"
# a browser that grants the request (and remembers it across a reload, as persisted() does)
PERSIST_YES = ("() => { Object.defineProperty(navigator, 'storage', { value: { persist: async () => { sessionStorage.setItem('stub-persisted', '1'); return true; }, "
               "persisted: async () => sessionStorage.getItem('stub-persisted') === '1' }, configurable: true }); }")
PERSIST_NO = "() => { Object.defineProperty(navigator, 'storage', { value: { persist: async () => false, persisted: async () => false }, configurable: true }); }"
NO_IDB = "() => { Object.defineProperty(window, 'indexedDB', { get() { throw new DOMException('The operation is insecure.', 'SecurityError'); }, configurable: true }); }"
READ_COPY = """() => new Promise((resolve) => {
  const open = indexedDB.open('kdl-demo-local');
  open.onupgradeneeded = () => { open.transaction.abort(); resolve(null); };
  open.onerror = (e) => { e.preventDefault(); resolve(null); };
  open.onsuccess = () => {
    const db = open.result;
    const get = db.transaction('state').objectStore('state').get('current');
    get.onsuccess = () => {
      db.close();
      const v = get.result;
      resolve(v ? { format: v.format, schema: v.schema, rev: v.rev, names: v.state._entries.map((e) => e.food_name), entries: v.state._entries.length } : null);
    };
  };
})"""
PUT_COPY = """(rec) => new Promise((resolve, reject) => {
  const open = indexedDB.open('kdl-demo-local', 1);
  open.onupgradeneeded = () => open.result.createObjectStore('state');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result;
    const tx = db.transaction('state', 'readwrite');
    tx.objectStore('state').put(rec, 'current');
    tx.oncomplete = () => { db.close(); resolve(true); };
  };
})"""
DB_NAMES = "async () => (await indexedDB.databases()).map((d) => d.name)"
ADD_ENTRY = """async (name) => {
  const day = KH.util.todayStr();
  return KH.request('POST', '/api/log/quick', { date: day, meal: 'lunch', name, serving_desc: '1 bar', serving_g: 40, servings: 1,
    nutrients: { calories_kcal: 160, protein_g: 3, carbs_g: 24, potassium_mg: 150, phosphorus_mg: 80, sodium_mg: 90 } });
}"""


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class Watch:
    """Requests, dialogs, console errors and page errors of one page."""

    def __init__(self, page: Any, base: str) -> None:
        self.base = base
        self.requests: list[tuple[str, str, str]] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        page.on("request", lambda r: self.requests.append((r.method, urlsplit(r.url).netloc, urlsplit(r.url).path)))
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def foreign(self) -> list[tuple[str, str, str]]:
        host = urlsplit(self.base).netloc
        return [q for q in self.requests if q[1] != host and not q[1] == "" or q[2].startswith("/api/")]


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def wide(page: Any) -> str:
    """The elements that reach past the right edge (for a failure's detail)."""
    return str(page.evaluate("""() => [...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1 && e.offsetParent !== null)
      .slice(0, 6).map((e) => `${e.tagName}#${e.id}.${e.className} ${Math.round(e.getBoundingClientRect().right)}`)"""))


def banner_has(page: Any, text: str, timeout: int = 30000) -> None:
    """Wait until the banner's text contains ``text`` (null-safe: the page may be in the middle of a reload)."""
    page.wait_for_function("(t) => { const el = document.querySelector('#preview-banner-text'); return !!el && el.textContent.includes(t); }", arg=text, timeout=timeout)


def boot(page: Any) -> None:
    """Wait until the demo has started and shown a view."""
    page.wait_for_function("() => !!(window.KH && KH.state && KH.state.me)", timeout=30000)
    page.wait_for_selector("#tab-today", state="visible", timeout=30000)
    page.wait_for_timeout(300)


def today_has(page: Any, name: str, timeout: int = 15000) -> bool:
    """Today lists ``name`` (the log is read again first: an entry added through the page's API does not redraw by itself)."""
    page.click("#tab-plan")
    page.click("#tab-today")
    try:
        page.wait_for_function("(n) => { const el = document.querySelector('#view-today'); return !!el && el.innerText.includes(n); }", arg=name, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def copy_with(page: Any, rev: int, timeout: float = 8.0) -> dict[str, Any] | None:
    """The stored copy once its revision reaches ``rev`` (saves are debounced by 1.5 s)."""
    end = time.time() + timeout
    got = page.evaluate(READ_COPY)
    while time.time() < end and not (got and got["rev"] >= rev):
        page.wait_for_timeout(250)
        got = page.evaluate(READ_COPY)
    return got


def open_settings(page: Any) -> None:
    page.click("#settings-open")
    page.wait_for_selector("#view-settings:not([hidden])")
    page.wait_for_selector("#set-export", state="attached", timeout=15000)
    page.locator("#set-export").scroll_into_view_if_needed()


def serve(site: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://localhost:{httpd.server_address[1]}"


def context(browser: Any, base: str, width: int, height: int, scheme: str, script: str | None = PERSIST_YES, **kw: Any) -> Any:
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base, accept_downloads=True, **kw)
    if script:
        ctx.add_init_script(f"({script})()")
    return ctx


# --------------------------------------------------------------------------------------------------------------- keep
def keep(browser: Any, base: str, out: Path, width: int, height: int, scheme: str) -> str:
    tag = f"{width}-{scheme}"
    ctx = context(browser, base, width, height, scheme)
    page = ctx.new_page()
    watch = Watch(page, base)
    page.goto("/")
    boot(page)
    check(f"[{tag}] the banner offers the mode, and the sample demo is showing", page.is_visible("#preview-banner-keep")
          and "Keep my data in this browser" in page.inner_text("#preview-banner-keep") and today_has(page, "Chicken"), page.inner_text("#preview-banner"))
    check(f"[{tag}] nothing is stored before the person chooses", page.evaluate(DB_NAMES) == [], str(page.evaluate(DB_NAMES)))
    page.reload()
    boot(page)
    check(f"[{tag}] still nothing after a reload", page.evaluate(DB_NAMES) == [])
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    sheet = page.inner_text("#sheet-demo-local")
    for sentence in ("Your data stays only in this browser, on this device. Nothing is sent anywhere.",
                     "Clearing site data, private browsing, or the browser deciding to free up space can delete it.",
                     "Export it regularly", "other people who use this browser can see it", "run your own server", "I understand"):
        check(f"[{tag}] the sheet says: {sentence[:48]}", sentence.lower() in sheet.lower().replace("\n", " "), sheet[:300])
    check(f"[{tag}] the button is off until I understand is ticked", page.is_disabled("#dl-enable") and not page.is_checked("#dl-understand"))
    check(f"[{tag}] opening the sheet stored nothing", page.evaluate(DB_NAMES) == [])
    page.screenshot(path=str(out / "shots" / f"keep-sheet-{tag}.png"))
    check(f"[{tag}] the sheet fits the screen", not overflow(page))
    page.check("#dl-understand")
    check(f"[{tag}] ticking it turns the button on", page.is_enabled("#dl-enable"))
    page.uncheck("#dl-understand")
    check(f"[{tag}] unticking turns it off again", page.is_disabled("#dl-enable"))
    page.check("#dl-understand")
    page.check("#dl-start-empty")
    page.click("#dl-enable")
    banner_has(page, "kept in this browser only")
    boot(page)
    copy = copy_with(page, 1)
    check(f"[{tag}] turning it on stores a copy (format, schema, no sample days)", copy and copy["format"] == "kidney-health-demo-local" and copy["schema"] == 1 and copy["entries"] == 0, str(copy))
    check(f"[{tag}] the banner now says where the data is", "kept in this browser only" in page.inner_text("#preview-banner-text")
          and page.inner_text("#preview-banner-keep").strip() == "Manage")
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    check(f"[{tag}] the sheet shows that the browser agreed to keep it", "has agreed to keep this data" in page.inner_text("#dl-persist"), page.inner_text("#dl-persist"))
    check(f"[{tag}] and offers export and stop", page.is_visible("#dl-export") and page.is_visible("#dl-stop") and not page.is_visible("#dl-enable"))
    page.screenshot(path=str(out / "shots" / f"keep-manage-{tag}.png"))
    page.keyboard.press("Escape")
    check(f"[{tag}] the empty log is empty", not today_has(page, "Chicken", 1500))
    page.evaluate(ADD_ENTRY, ENTRY)
    check(f"[{tag}] an entry is added and shown", today_has(page, ENTRY))
    saved = copy_with(page, 2)
    check(f"[{tag}] it is saved (after the debounce) with a higher revision", saved and ENTRY in saved["names"], str(saved))
    page.reload()
    boot(page)
    check(f"[{tag}] after a reload the entry is still there", today_has(page, ENTRY))
    check(f"[{tag}] and the mode is still on", "kept in this browser only" in page.inner_text("#preview-banner-text"))
    check(f"[{tag}] no horizontal scroll", not overflow(page))
    if width == 375:
        page.screenshot(path=str(out / "shots" / f"keep-today-{tag}.png"))
    check(f"[{tag}] no request to another host or to an /api route, no error, no browser dialog", not watch.foreign() and not watch.errors and not watch.dialogs,
          f"{watch.foreign()} {watch.errors} {watch.dialogs}")
    ctx.close()
    return tag


# ------------------------------------------------------------------------------------- export, stop, import (one profile)
def export_stop_import(browser: Any, base: str, out: Path) -> None:
    ctx = context(browser, base, 375, 812, "light")
    page = ctx.new_page()
    watch = Watch(page, base)
    page.goto("/")
    boot(page)
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    page.check("#dl-understand")
    page.check("#dl-start-empty")
    page.click("#dl-enable")
    banner_has(page, "kept in this browser only")
    boot(page)
    page.evaluate(ADD_ENTRY, ENTRY)
    page.evaluate("""async () => KH.request('POST', '/api/labs', { analyte: 'potassium', value: 4.8, unit: 'mmol/L', taken_on: KH.util.todayStr() })""")
    page.evaluate("""async () => KH.request('POST', '/api/symptoms', { date: KH.util.todayStr(), symptom: 'swelling', severity: 2, note: 'ankles' })""")
    check("[export] an entry, a lab result and a symptom are added", today_has(page, ENTRY))
    copy_with(page, 4)
    # Settings -> Your data -> export
    open_settings(page)
    check("[export] the button is the export.json one", "export.json" in page.inner_text("#set-export"), page.inner_text("#set-export"))
    with page.expect_download() as dl:
        page.click("#set-export")
    download = dl.value
    check("[export] the download is named export.json", download.suggested_filename == "export.json", download.suggested_filename)
    path = Path(download.path())
    doc = json.loads(path.read_text(encoding="utf-8"))
    check("[export] it has the server's keys in the server's order", list(doc) == EXPORT_KEYS, str(list(doc)))
    check("[export] format, version, the entry, the lab result and the symptom", doc["format"] == "kidney-health-export" and doc["version"] == 1
          and [e["food_name"] for e in doc["log_entries"]] == [ENTRY] and len(doc["lab_results"]) == 1 and len(doc["symptoms"]) == 1,
          json.dumps({k: doc[k] for k in ("log_entries",)})[:200])
    check("[export] no password, session or key in it", not any(word in json.dumps(doc).lower() for word in ("api_key", "password_hash", "session_id", "\"token\"")))
    keep_file = out / "export.json"
    keep_file.write_bytes(path.read_bytes())
    check("[export] the page says it saved the file", "Saved export.json" in page.inner_text("#set-export-msg"), page.inner_text("#set-export-msg"))
    # stop keeping data
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    page.click("#dl-stop")
    page.wait_for_selector("#sheet-demo-local .confirm-row")
    check("[stop] it asks in the page, says what happens, and no browser dialog opened", not watch.dialogs and "cannot be undone" in page.inner_text("#sheet-demo-local .confirm-row")
          and "sample data" in page.inner_text("#sheet-demo-local .confirm-row"), page.inner_text("#sheet-demo-local .confirm-row"))
    page.click("#sheet-demo-local .confirm-row button:has-text('Cancel')")
    check("[stop] Cancel keeps the copy", page.evaluate(DB_NAMES) == ["kdl-demo-local"] and page.is_visible("#dl-stop"))
    page.click("#dl-stop")
    page.wait_for_selector("#sheet-demo-local .confirm-row")
    page.click("#sheet-demo-local .confirm-row button:has-text('Delete my stored data')")
    banner_has(page, "Nothing is saved")
    boot(page)
    check("[stop] the stored copy is gone", page.evaluate(DB_NAMES) == [], str(page.evaluate(DB_NAMES)))
    check("[stop] the in-memory sample demo is back", today_has(page, "Chicken") and not today_has(page, ENTRY, 1000) and page.is_visible("#preview-banner-keep"))
    page.reload()
    boot(page)
    check("[stop] and stays off after a reload", page.evaluate(DB_NAMES) == [] and not today_has(page, ENTRY, 1000))
    # in the in-memory demo the Settings page points to the mode instead of pretending
    open_settings(page)
    page.click("#set-export")
    page.wait_for_function("() => { const el = document.querySelector('#set-export-msg'); return !!el && el.textContent.length > 0; }")
    check("[import] without the mode, export and import say they need it", "Keep my data in this browser" in page.inner_text("#set-export-msg")
          and page.is_visible("#set-import-demo") and not page.locator("#set-import-file").count())
    # turn it on again with an empty log and import the file
    page.click("#set-demo-local")
    page.wait_for_selector("#sheet-demo-local[open]")
    page.check("#dl-understand")
    page.check("#dl-start-empty")
    page.click("#dl-enable")
    banner_has(page, "kept in this browser only")
    boot(page)
    open_settings(page)
    page.locator("#set-import-file").scroll_into_view_if_needed()
    page.set_input_files("#set-import-file", str(keep_file))
    page.wait_for_selector("#set-import-result #set-import-title", timeout=15000)
    shown = page.inner_text("#set-import-result")
    check("[import] it shows what the file would add before anything changes", "What this file would add" in shown and "Will be added" in shown and "1 log entry" in shown
          and "1 lab result" in shown and "1 symptom" in shown, shown[:400])
    check("[import] nothing is imported yet", not today_has_after_nav(page, ENTRY))
    open_settings(page)
    page.set_input_files("#set-import-file", str(keep_file))
    page.wait_for_selector("#set-import-go", timeout=15000)
    check("[import] a file with a profile offers to replace it, off by default", page.locator("#set-import-profile").count() == 1 and not page.is_checked("#set-import-profile"))
    page.click("#set-import-go")
    page.wait_for_function("() => { const el = document.querySelector('#set-import-msg'); return !!el && el.textContent.startsWith('Imported'); }", timeout=15000)
    page.click("#tab-today")
    check("[import] after Import the entry is in the log", today_has(page, ENTRY))
    copy = copy_with(page, 2)
    end = time.time() + 8
    while time.time() < end and not (copy and ENTRY in copy["names"]):
        page.wait_for_timeout(250)
        copy = page.evaluate(READ_COPY)
    check("[import] and the imported data is saved in this browser", copy and ENTRY in copy["names"], str(copy))
    # the same file again adds nothing
    open_settings(page)
    page.set_input_files("#set-import-file", str(keep_file))
    page.wait_for_selector("#set-import-result #set-import-title", timeout=15000)
    shown = page.inner_text("#set-import-result")
    check("[import] the account has data now: nothing is imported unless adding is chosen", "already has data" in shown and page.is_disabled("#set-import-go"), shown[:300])
    page.check("#set-import-merge")
    page.wait_for_function("() => { const el = document.querySelector('#set-import-result'); return !!el && el.innerText.includes('Nothing new to add'); }", timeout=15000)
    check("[import] adding the same file again adds nothing", "Already here, so left out" in page.inner_text("#set-import-result"))
    # a file that is not an export
    bad = out / "not-an-export.json"
    bad.write_text(json.dumps({"format": "something-else", "version": 1}), encoding="utf-8")
    page.set_input_files("#set-import-file", str(bad))
    page.wait_for_function("() => { const el = document.querySelector('#set-import-result'); return !!el && el.innerText.includes('not a Kidney Health export'); }", timeout=15000)
    check("[import] a file that is not an export is refused in the server's words", "its \"format\" is not" in page.inner_text("#set-import-result"), page.inner_text("#set-import-result"))
    page.screenshot(path=str(out / "shots" / "import-375.png"))
    check("[import] no sideways scroll", not overflow(page), wide(page))
    check("[export/stop/import] no request to another host or to an /api route, no error", not watch.foreign() and not watch.errors, f"{watch.foreign()} {watch.errors}")
    ctx.close()


def today_has_after_nav(page: Any, name: str) -> bool:
    return today_has(page, name, 1500)


# ------------------------------------------------------------------------------------------------------- two tabs
def tabs(browser: Any, base: str, out: Path) -> None:
    ctx = context(browser, base, 375, 812, "light")
    a = ctx.new_page()
    watch_a = Watch(a, base)
    a.goto("/")
    boot(a)
    a.click("#preview-banner-keep")
    a.wait_for_selector("#sheet-demo-local[open]")
    a.check("#dl-understand")
    a.check("#dl-start-sample")
    a.click("#dl-enable")
    banner_has(a, "kept in this browser only", 30000)
    check("[tabs] keeping the sample data as it is stores it", copy_with(a, 1)["entries"] > 30)
    b = ctx.new_page()
    watch_b = Watch(b, base)
    b.goto("/")
    boot(b)
    check("[tabs] a second tab loads the same copy", "kept in this browser only" in b.inner_text("#preview-banner-text"))
    a.evaluate(ADD_ENTRY, "From tab A")
    check("[tabs] tab A saves", "From tab A" in (copy_with(a, 2) or {"names": []})["names"])
    b.evaluate(ADD_ENTRY, "From tab B")
    banner_has(b, "Another tab changed", 12000)
    check("[tabs] tab B says another tab changed the data and stops saving", True)
    after = a.evaluate(READ_COPY)
    check("[tabs] tab B did not overwrite tab A's save", "From tab A" in after["names"] and "From tab B" not in after["names"], str(after["names"][-3:]))
    b.screenshot(path=str(out / "shots" / "tabs-conflict-375.png"))
    check("[tabs] no request to another host, no error", not watch_a.foreign() and not watch_b.foreign() and not watch_a.errors, f"{watch_a.errors} {watch_b.errors}")
    ctx.close()


# --------------------------------------------------------------------------------- a browser that refuses storage
def private(browser: Any, base: str, out: Path) -> None:
    ctx = context(browser, base, 375, 812, "light", script=NO_IDB)
    page = ctx.new_page()
    watch = Watch(page, base)
    page.goto("/")
    boot(page)
    check("[private] the demo starts in memory without a word of complaint", today_has(page, "Chicken") and not watch.errors, str(watch.errors))
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    page.wait_for_function("() => { const el = document.querySelector('#dl-problem'); return !!el && !el.hidden; }", timeout=10000)
    problem = page.inner_text("#dl-problem")
    check("[private] the sheet says storage is not available and nothing is saved", "does not let this page store data" in problem and "stays in memory" in problem, problem)
    page.check("#dl-understand")
    check("[private] the button stays off", page.is_disabled("#dl-enable"))
    page.screenshot(path=str(out / "shots" / "private-375.png"))
    page.keyboard.press("Escape")
    page.evaluate(ADD_ENTRY, ENTRY)
    check("[private] the demo keeps working in memory", today_has(page, ENTRY))
    check("[private] no request to another host, no browser dialog", not watch.foreign() and not watch.dialogs, str(watch.foreign()))
    ctx.close()
    # the browser did not grant persistent storage: the sheet says so
    ctx = context(browser, base, 375, 812, "light", script=PERSIST_NO)
    page = ctx.new_page()
    page.goto("/")
    boot(page)
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    page.check("#dl-understand")
    page.click("#dl-enable")
    banner_has(page, "kept in this browser only")
    boot(page)
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    check("[private] a browser that does not promise to keep it is quoted", "has not agreed to keep this data for good" in page.inner_text("#dl-persist"), page.inner_text("#dl-persist"))
    ctx.close()


def newer(browser: Any, base: str, out: Path) -> None:
    ctx = context(browser, base, 375, 812, "light")
    page = ctx.new_page()
    watch = Watch(page, base)
    page.goto("/")
    boot(page)
    record = {"format": "kidney-health-demo-local", "schema": 99, "rev": 5, "savedAt": "2026-10-15T10:00:00Z", "state": {"_entries": []}}
    page.evaluate(PUT_COPY, record)
    page.reload()
    boot(page)
    text = page.inner_text("#preview-banner-text")
    check("[newer] the banner says the stored copy is from a newer version and was not loaded", "newer version" in text and "will not be changed or deleted" in text, text)
    check("[newer] the demo runs in memory with its sample data", today_has(page, "Chicken"))
    page.click("#preview-banner-keep")
    page.wait_for_selector("#sheet-demo-local[open]")
    check("[newer] the sheet explains and offers no way to overwrite it", page.is_visible("#dl-blocked-text") and not page.is_visible("#dl-enable") and not page.is_visible("#dl-stop"))
    page.screenshot(path=str(out / "shots" / "newer-375.png"))
    page.keyboard.press("Escape")
    page.evaluate(ADD_ENTRY, "Not saved")
    page.wait_for_timeout(2500)
    after = page.evaluate("""() => new Promise((resolve) => { const o = indexedDB.open('kdl-demo-local'); o.onsuccess = () => { const g = o.result.transaction('state').objectStore('state').get('current');
      g.onsuccess = () => { o.result.close(); resolve(g.result); }; }; })""")
    check("[newer] after more changes the newer copy is exactly as it was", after == record, str(after)[:200])
    check("[newer] no error", not watch.errors and not watch.foreign(), str(watch.errors))
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default=",".join(SECTIONS), help=f"a comma-separated subset of {', '.join(SECTIONS)} (export covers stop and the import)")
    args = ap.parse_args(argv)
    only = set(args.only.split(","))
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    site = out / "demo-site"
    subprocess.run([sys.executable, str(REPO / "scripts" / "build_preview.py"), "--pages", str(site)], check=True, capture_output=True)
    httpd, base = serve(site)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                if "keep" in only:
                    keep(browser, base, out, 375, 812, "light")
                    keep(browser, base, out, 1280, 800, "dark")
                if only & {"export", "stop"}:
                    export_stop_import(browser, base, out)
                if "tabs" in only:
                    tabs(browser, base, out)
                if "private" in only:
                    private(browser, base, out)
                if "newer" in only:
                    newer(browser, base, out)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        httpd.shutdown()
    (out / "report.json").write_text(json.dumps(RESULTS, indent=1) + "\n", encoding="utf-8")
    failed = [r["check"] for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report: {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
