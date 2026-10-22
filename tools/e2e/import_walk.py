#!/usr/bin/env python3
"""Settings -> Account -> Your data -> **Import from a file**, walked against a real server in Chromium.

    python tools/e2e/import_walk.py                       # port 8086
    python tools/e2e/import_walk.py --port 8086 --out /tmp/kh-import-walk

``tests/js/import_page.mjs`` runs the page's code against a fake page and ``demo_local.py`` walks the demo's twin; this
is the one that drives the server's own page and ``POST /api/me/import`` together (``app/data_import.py``).

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup and fills person A through the API: a
banana and two foods of her own, five entries (eaten and planned, today and yesterday, one with a note), a saved meal, two
lab results, a symptom, a liked food, a profile with targets and two settings (the lab units and a meal-guidance
tolerance). A signs in on the page and presses **Export my data (.zip)**; the harness opens the zip, takes ``export.json``
out of it and checks what it holds. Then, on each of two screens (375x812 light and 1280x800 dark), a fresh person B
(invited, no data) signs in on the page and walks the import:

* the files a person can pick by mistake: the whole ``.zip``, a text file and a JSON list are turned away in the page
  (nothing is sent); a JSON file that is not an export and an export of another version are refused in the server's words;
* the recent-password requirement: B's last password entry is made older than ``REAUTH_MINUTES`` (a stored time, as a wait
  leaves it); choosing the file opens "Enter your password again"; Cancel says it was not checked; a wrong password is
  refused in the sheet; the right one carries on and the file is checked. It is asked for again when Import is pressed
  after another wait;
* the preview says what the file would add, offers "Add to my existing data" and "Also replace my profile, targets and
  settings" (both off), says what was not chosen, and changes nothing on the server until Import is pressed;
* Import without "Add to my existing data": the message names the counts, B's log, foods, saved meal, lab results, symptom
  and food preference equal A's through the API, B's Today shows A's entries, and B's profile and settings are still B's own;
* the same file again: refused because the account has data (Import disabled, nothing written); with "Add to my existing
  data": everything is "already here", "Nothing new was imported", no duplicates; after B removes an entry and a lab
  result, the same choice adds exactly those two back;
* "Also replace my profile, targets and settings": B's profile (targets included) and the two settings then equal A's;
* A's own data is untouched, the browser asked no other host, and there is no console error, dialog, CSP violation or
  sideways scroll.

What it cannot show: a real phone's file picker (the harness hands the file to the input) and a real person's eyes on the
layout; those stay in the manual device matrix (docs/maintainers.md).

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``;
exit status 1 on any failure. The server and the browser are always stopped.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import traceback
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

import khserver
from device import Watch, wait_js
from khserver import DEFAULT_PASSWORD, Api, Server, first_admin, invite_user

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "import_walk"
PORT = 8086
TIMEOUT_MS = 20_000
RESULTS: list[dict[str, Any]] = []
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
LAST_WEEK = TODAY - timedelta(days=7)
DAYS = (LAST_WEEK, YESTERDAY, TODAY)
ALICE = "alice"
SCREENS = (("375-light", 375, 812, "light", "bea"), ("1280-dark", 1280, 800, "dark", "cal"))
ALICE_SETTINGS = {"guidance": {"carb_tolerance_g": 15}, "user.units.labs": "si"}
# What the page says for A's file (5 entries, 2 foods of hers, 1 saved meal, 2 lab results, 1 symptom, 1 food preference).
SIZES = "5 log entries, 2 foods of yours, 1 saved meal, 2 lab results, 1 symptom"
ADDED = "5 log entries, 2 foods of yours, 1 saved meal, 2 lab results, 1 symptom, 1 food preference"


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


# --------------------------------------------------------------------------- what the server holds


def scrub(value: Any, drop: tuple[str, ...] = ("id", "food_id")) -> Any:
    """The same data without the ids a server assigns (they differ between accounts)."""
    if isinstance(value, dict):
        return {k: scrub(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [scrub(v, drop) for v in value]
    return value


def first_difference(a: Any, b: Any, path: str = "") -> str:
    if type(a) is not type(b):
        return f"{path or '.'}: {str(a)[:80]} != {str(b)[:80]}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}.{key}: only on one side"
            if a[key] != b[key]:
                return first_difference(a[key], b[key], f"{path}.{key}")
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path or '.'}: {len(a)} items != {len(b)} items"
        for index, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return first_difference(x, y, f"{path}[{index}]")
    return "" if a == b else f"{path or '.'}: {str(a)[:80]} != {str(b)[:80]}"


def data_of(api: Api) -> dict[str, Any]:
    """Everything the import writes besides the profile and settings, as the API shows it, without server-made ids."""
    foods = api.json("GET", "/api/foods", params={"q": ""})["foods"]
    return scrub({
        "log": {d.isoformat(): api.json("GET", "/api/log", params={"date": d.isoformat()})["entries"] for d in DAYS},
        "own_foods": sorted((f for f in foods if f["source"] == "custom"), key=lambda f: f["name"]),
        "meals": api.json("GET", "/api/meals"),
        "labs": api.json("GET", "/api/labs"),
        "symptoms": api.json("GET", "/api/symptoms", params={"start": LAST_WEEK.isoformat(), "end": TODAY.isoformat()}),
        "preferences": api.json("GET", "/api/guidance/preferences"),
    }, ("id", "food_id", "version"))


def profile_of(api: Api) -> dict[str, Any]:
    profile = api.json("GET", "/api/profile")
    profile.pop("id"), profile.pop("updated_at")
    return profile


def settings_of(api: Api) -> dict[str, Any]:
    settings = api.json("GET", "/api/me/settings")["settings"]
    return {key: settings[key]["value"] for key in ALICE_SETTINGS}


def counts_of(data: dict[str, Any]) -> dict[str, int]:
    return {"entries": sum(len(v) for v in data["log"].values()), "own_foods": len(data["own_foods"]), "meals": len(data["meals"]["meals"]),
            "labs": len(data["labs"]["labs"]), "symptoms": len(data["symptoms"]["symptoms"]), "preferences": len(data["preferences"]["foods"])}


def seed_alice(api: Api) -> dict[str, Any]:
    """Person A's account: foods of her own, entries, a saved meal, labs, a symptom, a liked food, profile and settings."""
    banana = api.json("GET", "/api/foods", params={"q": "banana"})["foods"][0]
    soup = api.json("POST", "/api/foods", {"name": "Walk soup", "brand": "Home", "serving_desc": "1 bowl", "serving_g": 300,
                                           "nutrients": {"potassium_mg": 400, "phosphorus_mg": 120, "carbs_g": 20},
                                           "flags": ["processed"], "kidney_notes": "Watch the salt."})
    muffin = api.json("POST", "/api/foods", {"name": "Walk muffin", "serving_desc": "1 muffin", "serving_g": 60,
                                             "nutrients": {"carbs_g": 28, "sugar_g": 12, "potassium_mg": 90}})
    for day, meal, food, extra in (
        (TODAY, "breakfast", banana, {"servings": 1}),
        (TODAY, "lunch", soup, {"servings": 1.5, "note": "with bread"}),
        (TODAY, "snack", muffin, {"servings": 1, "status": "planned"}),
        (YESTERDAY, "breakfast", banana, {"servings": 2}),
        (YESTERDAY, "dinner", soup, {"servings": 1}),
    ):
        api.json("POST", "/api/log", {"date": day.isoformat(), "meal": meal, "food_id": food["id"], **extra})
    api.json("POST", "/api/meals", {"name": "Walk lunch", "note": "weekdays", "meal_hint": "lunch",
                                    "items": [{"food_id": soup["id"], "servings": 1}, {"food_id": banana["id"], "servings": 2}]})
    api.json("POST", "/api/labs", {"analyte": "potassium", "value": 4.8, "unit": "mmol/L", "taken_on": YESTERDAY.isoformat()})
    api.json("POST", "/api/labs", {"analyte": "creatinine", "value": 110, "unit": "µmol/L", "taken_on": LAST_WEEK.isoformat(), "note": "fasting"})
    api.json("POST", "/api/symptoms", {"date": TODAY.isoformat(), "symptom": "itching", "severity": 1, "note": "at night"})
    api.json("PUT", "/api/profile", {"name": "Alice", "weight_kg": 70, "height_cm": 168, "ckd_stage": "4",
                                     "targets": {"potassium_mg": 2500, "protein_g": {"min": 50, "max": 60}}})
    api.json("PATCH", "/api/me/settings", ALICE_SETTINGS)
    api.json("PUT", f"/api/guidance/preferences/{banana['id']}", {"preference": "like"})
    return {"banana": banana, "soup": soup, "muffin": muffin}


def make_password_old(server: Server, username: str, minutes: int = 30) -> None:
    """The person last typed the password ``minutes`` ago: a stored time, as a wait would leave it (REAUTH_MINUTES is 10)."""
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn = sqlite3.connect(server.data_dir / "kidney.db", timeout=20)
    try:
        conn.execute("UPDATE sessions SET reauth_at = ? WHERE user_id = (SELECT id FROM users WHERE username = ?)", (old, username))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- the page


def sign_in(page: Page, base: str, username: str) -> None:
    page.goto(f"{base}/")
    page.wait_for_selector("#form-login:not([hidden])")
    page.fill("#login-username", username)
    page.fill("#login-password", DEFAULT_PASSWORD)
    page.click("#login-submit")
    page.wait_for_selector("#view-today:not([hidden])")


def open_import(page: Page) -> None:
    """Settings, then the Import from a file block (a person scrolls to it)."""
    if not page.is_visible("#view-settings:not([hidden])"):
        page.click("#settings-open")
        page.wait_for_selector("#view-settings:not([hidden]) #set-import-file", state="attached")
    page.locator("#set-import").scroll_into_view_if_needed()


def text_of(page: Page, selector: str) -> str:
    """What a person reads in the element: its visible text with the blank space collapsed."""
    return page.evaluate("(sel) => { const el = document.querySelector(sel); return el ? el.innerText.replace(/\\s+/g, ' ').trim() : ''; }", selector)


def wait_text(page: Page, selector: str, needle: str, timeout: int = TIMEOUT_MS) -> None:
    page.wait_for_function("([sel, text]) => { const el = document.querySelector(sel); return !!el && el.textContent.includes(text); }",
                           arg=[selector, needle], timeout=timeout)


def choose(page: Page, path: Path) -> None:
    open_import(page)
    page.set_input_files("#set-import-file", str(path))


def wait_preview(page: Page) -> str:
    """The 'What this file would add' block has drawn (after the check came back); returns its text."""
    page.wait_for_selector("#set-import-result #set-import-title", timeout=TIMEOUT_MS)
    wait_js(page, "!document.querySelector('#set-import-msg').textContent.startsWith('Checking')")
    return text_of(page, "#set-import-result")


def tick(page: Page, box: str) -> str:
    """Tick (or untick) an option. The page checks the file again and draws the preview again, with the box in focus; the
    old preview is marked first so that the new one is told apart from it (the box already has the focus after the click)."""
    page.evaluate("() => { const t = document.querySelector('#set-import-title'); if (t) t.dataset.old = '1'; }")
    page.click(f"#{box}")
    wait_js(page, "(() => { const t = document.querySelector('#set-import-title'); return !!t && !t.dataset.old "
                  f"&& !!document.activeElement && document.activeElement.id === '{box}'; }})()")
    return text_of(page, "#set-import-result")


def sheet_open(page: Page) -> bool:
    try:
        page.wait_for_selector("#sheet-reauth[open]", timeout=8000)
        return True
    except Exception:  # noqa: BLE001 - not asked
        return False


def overflow(page: Page) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


class Posts:
    """The writes one page sent (method, path), so a refusal in the page can be shown to have sent nothing."""

    def __init__(self, page: Page) -> None:
        self.log: list[tuple[str, str]] = []
        page.on("request", lambda r: self.log.append((r.method, urlsplit(r.url).path)) if r.method != "GET" else None)

    def to_import(self) -> int:
        """Requests to POST /api/me/import: every check (dry run) and every real import counts against the hourly allowance."""
        return sum(1 for method, path in self.log if (method, path) == ("POST", "/api/me/import"))


# --------------------------------------------------------------------------- export, as person A


def export_as_alice(browser: Any, base: str, files: Path) -> Path:
    """A presses Export my data (.zip) in Settings; the harness saves the zip under the name the server gave it, opens it
    (as a person must) and puts export.json next to it. Returns the zip's path."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=True, service_workers="block")
    ctx.set_default_timeout(TIMEOUT_MS)
    watch = Watch(base)
    watch.attach(ctx)
    page = ctx.new_page()
    try:
        sign_in(page, base, ALICE)
        page.click("#settings-open")
        page.wait_for_selector("#view-settings:not([hidden]) #set-export")
        with page.expect_download() as download:
            page.click("#set-export")
        name = download.value.suggested_filename
        saved = files / name
        download.value.save_as(str(saved))
        wait_text(page, "#set-export-msg", "Saved ")
        said = text_of(page, "#set-export-msg")
        check("[export] the file is named for A and the day, and A's page says it saved it",
              re.fullmatch(r"kidney-health-alice-\d{4}-\d{2}-\d{2}\.zip", name) is not None and f"Saved {name} (" in said and "Keep it somewhere private" in said, f"{name}: {said}")
        with zipfile.ZipFile(saved) as z:
            names = sorted(z.namelist())
            raw = z.read("export.json")
        (files / "export.json").write_bytes(raw)  # "open the .zip first"
        check("[export] the zip holds export.json and the CSV files", names == ["README.txt", "export.json", "foods.csv", "labs.csv", "log.csv", "meals.csv", "symptoms.csv"], str(names))
        doc = json.loads(raw)
        check("[export] export.json holds A's records", (doc["format"], doc["version"]) == ("kidney-health-export", 1)
              and (len(doc["log_entries"]), len(doc["custom_foods"]), len(doc["meal_templates"]), len(doc["lab_results"]), len(doc["symptoms"]),
                   len(doc["food_preferences"])) == (5, 2, 1, 2, 1, 1),
              str({k: len(v) for k, v in doc.items() if isinstance(v, list)}))
        check("[export] and no password, session or key", not any(word in raw.decode("utf-8").lower() for word in ("password_hash", "api_key\": \"", "verifier")))
        problems = watch.take()
        check("[export] no console error, failed or outside request", not problems, "; ".join(problems[:6]))
        return saved
    finally:
        ctx.close()


# --------------------------------------------------------------------------- person B's walk


def walk(browser: Any, server: Server, admin: Api, base: str, zipped: Path, files: Path, shots: Path, alice: dict[str, Any],
         label: str, width: int, height: int, scheme: str, name: str) -> None:
    tag = f"[{label}]"
    phone = width < 700
    bea = invite_user(server, admin, name)
    empty = data_of(bea)
    own_before = {"profile": profile_of(bea), "settings": settings_of(bea)}
    check(f"{tag} B starts empty: no entry, food, meal, lab result, symptom or preference",
          set(counts_of(empty).values()) == {0}, str(counts_of(empty)))
    check(f"{tag} and her profile and settings are her own, not A's", own_before["profile"] != alice["profile"] and own_before["settings"] != alice["settings"])

    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, is_mobile=phone, has_touch=phone, service_workers="block")
    ctx.set_default_timeout(TIMEOUT_MS)
    watch = Watch(base)
    for path, status in (("/api/me/import", 403), ("/api/me/import", 400), ("/api/auth/reauth", 403)):
        watch.expect(path, status)  # the refusals this walk causes on purpose
    watch.attach(ctx)
    page = ctx.new_page()
    posts = Posts(page)
    dialogs: list[str] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    try:
        sign_in(page, base, name)
        open_import(page)
        block = text_of(page, "#set-import")
        check(f"{tag} Settings -> Your data has Import from a file, with the file box and the promise to show what would be added first",
              "Import from a file" in block and "You see what would be added before anything is changed" in block
              and page.locator("#set-import-file").count() == 1 and "export.json" in text_of(page, "#set-import label"), block[:200])
        check(f"{tag} nothing is chosen yet, so there is no preview", page.locator("#set-import-title").count() == 0)

        # ---- files a person can pick by mistake: turned away in the page, nothing sent
        choose(page, zipped)
        wait_text(page, "#set-import-msg", "whole export")
        check(f"{tag} the whole .zip is turned away: 'Open the .zip on your device and choose the export.json inside it'",
              "That is the whole export. Open the .zip on your device and choose the export.json inside it." in text_of(page, "#set-import-msg"), text_of(page, "#set-import-msg"))
        choose(page, files / "shopping.txt")
        wait_text(page, "#set-import-msg", "not JSON")
        check(f"{tag} a text file is not JSON: 'Choose the export.json from your export'",
              "This is not an export.json file (it is not JSON). Choose the export.json from your export." in text_of(page, "#set-import-msg"), text_of(page, "#set-import-msg"))
        choose(page, files / "list.json")
        wait_text(page, "#set-import-msg", "not JSON")
        check(f"{tag} a JSON list is turned away the same way", page.locator("#set-import-title").count() == 0 and "not an export.json file" in text_of(page, "#set-import-msg"))
        check(f"{tag} none of these sent anything to the server", posts.to_import() == 0, str(posts.log))

        # ---- the recent-password requirement
        make_password_old(server, name)
        choose(page, files / "export.json")
        check(f"{tag} choosing the file after a long wait opens 'Enter your password again'", sheet_open(page))
        check(f"{tag} the sheet says why", "Enter your password again" in text_of(page, "#sheet-reauth-title")
              and "needs your password because you have not entered it in the last few minutes" in text_of(page, "#sheet-reauth-sub"), text_of(page, "#sheet-reauth"))
        page.screenshot(path=str(shots / f"reauth-{label}.png"))
        page.click("#sheet-reauth button:has-text('Cancel')")
        wait_text(page, "#set-import-msg", "Not checked")
        check(f"{tag} Cancel: 'Not checked: the password prompt was closed.', no preview, nothing written",
              "Not checked: the password prompt was closed." in text_of(page, "#set-import-msg") and page.locator("#set-import-title").count() == 0
              and data_of(bea) == empty, text_of(page, "#set-import-msg"))
        check(f"{tag} Cancel also empties the file box, so the same file can be chosen again",
              page.input_value("#set-import-file") == "", page.input_value("#set-import-file"))
        choose(page, files / "export.json")
        check(f"{tag} choosing the same file again asks again", sheet_open(page))
        page.fill("#reauth-password", "this is not my password 9")
        page.click("#reauth-submit")
        wait_text(page, "#reauth-error", "not right")
        check(f"{tag} a wrong password is refused in the sheet, which stays open: 'That password is not right.'",
              "That password is not right." in text_of(page, "#reauth-error") and page.is_visible("#sheet-reauth[open]"), text_of(page, "#reauth-error"))
        page.fill("#reauth-password", DEFAULT_PASSWORD)
        page.click("#reauth-submit")
        preview = wait_preview(page)
        check(f"{tag} the right password closes the sheet and the file is checked", not page.is_visible("#sheet-reauth[open]") and "What this file would add" in preview, preview[:200])

        # ---- two refusals in the server's words, then the real file
        choose(page, files / "not-an-export.json")
        page.wait_for_selector("#set-import-result .form-error", timeout=TIMEOUT_MS)
        check(f"{tag} JSON that is not an export: 'The file was not imported. This is not a Kidney Health export'",
              'The file was not imported. This is not a Kidney Health export (its "format" is not "kidney-health-export").' in text_of(page, "#set-import-result")
              and page.locator("#set-import-go").count() == 0, text_of(page, "#set-import-result"))
        choose(page, files / "version-2.json")
        wait_text(page, "#set-import-result", "version 2")
        check(f"{tag} an export of another version says which version this server reads",
              "This export is version 2 of the format; this server reads version 1." in text_of(page, "#set-import-result"), text_of(page, "#set-import-result"))
        check(f"{tag} still nothing written", data_of(bea) == empty)

        choose(page, files / "export.json")
        preview = wait_preview(page)
        page.screenshot(path=str(shots / f"preview-{label}.png"), full_page=True)
        check(f"{tag} the preview says what the file holds: {SIZES}", f": {SIZES}." in preview and preview.startswith("What this file would add Exported "), preview[:260])
        check(f"{tag} and what will be added: each kind with its count", "Will be added:" in preview and all(
            line in preview for line in ("5 log entries", "2 foods of yours", "1 saved meal", "2 lab results", "1 symptom", "1 food preference")), preview[:500])
        check(f"{tag} 'Add to my existing data' and the profile option are offered, both off",
              page.locator("#set-import-merge").count() == 1 and not page.is_checked("#set-import-merge")
              and page.locator("#set-import-profile").count() == 1 and not page.is_checked("#set-import-profile")
              and "Also replace my profile, targets and settings" in preview and "Add to my existing data" in preview)
        check(f"{tag} it says what was not chosen: profile, targets and settings",
              "Not imported, because you did not choose it: your profile and targets and your meal-guidance and display settings." in preview, preview[-400:])
        check(f"{tag} 'What is never imported' and 'How duplicates are handled' are there", page.locator("#set-import-never").count() == 1 and page.locator("#set-import-rule").count() == 1)
        check(f"{tag} Import is enabled and the server has not been changed", page.is_enabled("#set-import-go") and data_of(bea) == empty)

        # ---- Import without "Add to my existing data" (the password asked for again after another wait)
        make_password_old(server, name)
        page.click("#set-import-go")
        check(f"{tag} pressing Import after another wait asks for the password again", sheet_open(page))
        page.fill("#reauth-password", DEFAULT_PASSWORD)
        page.click("#reauth-submit")
        wait_text(page, "#set-import-msg", "Imported")
        said = text_of(page, "#set-import-msg")
        check(f"{tag} Import: 'Imported {ADDED}.'", said == f"Imported {ADDED}.", said)
        check(f"{tag} the preview is gone and the file box is empty", page.locator("#set-import-title").count() == 0 and page.input_value("#set-import-file") == "")
        mine = data_of(bea)
        check(f"{tag} B's log, foods, saved meal, lab results, symptom and food preference now equal A's (through the API)",
              mine == alice["data"], first_difference(mine, alice["data"]))
        check(f"{tag} and nothing else changed: B's profile and settings are still her own",
              profile_of(bea) == own_before["profile"] and settings_of(bea) == own_before["settings"])
        page.click("#tab-today")
        wait_text(page, "#view-today", "Walk soup")
        today_text = text_of(page, "#view-today")
        check(f"{tag} B's Today shows A's entries", all(food in today_text for food in ("Walk soup", "Banana", "Walk muffin")), today_text[:300])
        open_import(page)

        # ---- the same file again, without and with "Add to my existing data"
        choose(page, files / "export.json")
        blocked = wait_preview(page)
        check(f"{tag} the same file again: 'This account already has data (...), so nothing is imported unless you choose “Add to my existing data”'",
              f"This account already has data ({SIZES}), so nothing is imported unless you choose “Add to my existing data”." in blocked, blocked[:400])
        check(f"{tag} Import is disabled and nothing is written", page.is_disabled("#set-import-go") and data_of(bea) == alice["data"])
        page.screenshot(path=str(shots / f"blocked-{label}.png"), full_page=True)
        merged = tick(page, "set-import-merge")
        check(f"{tag} with 'Add to my existing data': 'Nothing new to add.' and everything is 'Already here, so left out'",
              "Nothing new to add." in merged and "Already here, so left out:" in merged and "Will be added:" not in merged
              and all(line in merged for line in ("5 log entries", "2 foods of yours", "1 saved meal", "2 lab results", "1 symptom", "1 food preference")), merged[:500])
        check(f"{tag} the account-has-data warning is gone and Import is enabled", "already has data" not in merged and page.is_enabled("#set-import-go"))
        page.click("#set-import-go")
        wait_text(page, "#set-import-msg", "Nothing new was imported.")
        check(f"{tag} Import says 'Nothing new was imported.' and B holds no duplicate", data_of(bea) == alice["data"], first_difference(data_of(bea), alice["data"]))

        # B removes an entry and a lab result; the same choice adds exactly those back
        gone = next(e for e in bea.json("GET", "/api/log", params={"date": YESTERDAY.isoformat()})["entries"] if e["meal"] == "dinner")
        bea.json("DELETE", f"/api/log/{gone['id']}")
        lab = bea.json("GET", "/api/labs")["labs"][0]
        bea.json("DELETE", f"/api/labs/{lab['id']}")
        short = data_of(bea)
        check(f"{tag} (B removes one entry and one lab result through the API)", counts_of(short)["entries"] == 4 and counts_of(short)["labs"] == 1, str(counts_of(short)))
        choose(page, files / "export.json")
        wait_preview(page)
        merged = tick(page, "set-import-merge")
        check(f"{tag} with 'Add to my existing data' the preview adds only what is missing: 1 log entry and 1 lab result",
              "Will be added:" in merged and "1 log entry" in merged and "1 lab result" in merged and "Already here, so left out:" in merged, merged[:600])
        page.click("#set-import-go")
        wait_text(page, "#set-import-msg", "Imported 1 log entry, 1 lab result.")
        check(f"{tag} 'Imported 1 log entry, 1 lab result.' and B equals A again, with no duplicate", data_of(bea) == alice["data"], first_difference(data_of(bea), alice["data"]))

        # ---- Also replace my profile, targets and settings
        check(f"{tag} (B's profile and settings are still her own)", profile_of(bea) == own_before["profile"] and settings_of(bea) == own_before["settings"])
        choose(page, files / "export.json")
        wait_preview(page)
        tick(page, "set-import-merge")
        replaced = tick(page, "set-import-profile")
        check(f"{tag} with the profile option on, the preview adds 'your profile and targets' and the settings and no longer says they were not chosen",
              "your profile and targets" in replaced and "2 settings" in replaced and "Not imported, because you did not choose it" not in replaced, replaced[:600])
        page.screenshot(path=str(shots / f"replace-{label}.png"), full_page=True)
        page.click("#set-import-go")
        wait_text(page, "#set-import-msg", "Imported")
        said = text_of(page, "#set-import-msg")
        check(f"{tag} Import: 'Imported 2 settings, your profile and targets.'", said == "Imported 2 settings, your profile and targets.", said)
        theirs, hers = profile_of(bea), alice["profile"]
        check(f"{tag} B's profile now equals A's, targets included (potassium 2,500 mg, protein 50-60 g)",
              theirs == hers and theirs["targets"]["potassium_mg"] == 2500 and theirs["targets"]["protein_g"] == {"min": 50.0, "max": 60.0},
              first_difference(theirs, hers))
        check(f"{tag} and her two settings equal A's (lab units, meal-guidance tolerance)", settings_of(bea) == alice["settings"], str(settings_of(bea)))
        check(f"{tag} and the data is still A's, once", data_of(bea) == alice["data"], first_difference(data_of(bea), alice["data"]))

        # ---- the page
        page.screenshot(path=str(shots / f"done-{label}.png"), full_page=True)
        check(f"{tag} no sideways scroll", not overflow(page))
        check(f"{tag} the walk stayed within the allowance of 20 import requests an hour (each check and each import is one)",
              0 < posts.to_import() <= 20, str(posts.to_import()))
        check(f"{tag} no browser dialog", not dialogs, str(dialogs))
        problems = watch.take()
        check(f"{tag} no CSP or Trusted Types violation, page or console error, failed, outside or unexpected request", not problems, "; ".join(problems[:8]))
    except Exception:
        try:
            page.screenshot(path=str(shots / f"error-{label}.png"), full_page=True)  # what the page showed when the step stopped
        except Exception:  # noqa: BLE001 - the page may be gone
            pass
        raise
    finally:
        ctx.close()
        bea.close()


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT, help=f"uvicorn port (default {PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help="work directory (wiped first)")
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    shots, files = out / "shots", out / "files"
    shots.mkdir()
    files.mkdir()
    (files / "shopping.txt").write_text("Milk, bread, apples. This is a shopping list, not an export.\n", encoding="utf-8")
    (files / "list.json").write_text("[1, 2, 3]\n", encoding="utf-8")
    (files / "not-an-export.json").write_text(json.dumps({"format": "something-else", "version": 1}), encoding="utf-8")
    (files / "version-2.json").write_text(json.dumps({"format": "kidney-health-export", "version": 2}), encoding="utf-8")
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, ALICE)
        base = server.base
        seed_alice(admin)
        alice = {"data": data_of(admin), "profile": profile_of(admin), "settings": settings_of(admin)}
        check("[A] A's account holds 5 entries, 2 foods of her own, a saved meal, 2 lab results, a symptom and a food preference",
              counts_of(alice["data"]) == {"entries": 5, "own_foods": 2, "meals": 1, "labs": 2, "symptoms": 1, "preferences": 1}, str(counts_of(alice["data"])))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                zipped = export_as_alice(browser, base, files)
                for label, width, height, scheme, name in SCREENS:
                    try:
                        walk(browser, server, admin, base, zipped, files, shots, alice, label, width, height, scheme, name)
                    except Exception as exc:  # noqa: BLE001 - report, then walk the other screen
                        check(f"[{label}] the walk reached its end", False, f"{type(exc).__name__}: {str(exc)[:300]}")
                        traceback.print_exc()
            finally:
                browser.close()
        after = {"data": data_of(admin), "profile": profile_of(admin), "settings": settings_of(admin)}
        check("[A] A's own data, profile and settings are untouched by B's imports", after == alice, first_difference(after, alice))
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
