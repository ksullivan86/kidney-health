#!/usr/bin/env python3
"""The whole v0.3 journey on a real server, the way two people use it, in Chromium.

    python tools/e2e/journey.py --site handbook/site
    python tools/e2e/journey.py --site handbook/site --port 8068 --ai-port 8069 --off-port 8070 --out /tmp/kh-journey

Starts the real app (``replay_app:app``: the app with USDA FoodData Central answered from ``tests/fixtures/usda``)
with a fresh ``DATA_DIR``, the built handbook at ``HANDBOOK_DIR``, a fake OpenAI-compatible server (``--ai-port``)
as the env AI provider and a fake Open Food Facts (``--off-port``, ``OFF_BASE_URL``) that answers from
``tests/fixtures/off``. The server's outbound proxy points nowhere, so nothing leaves the machine. Then, in one
story, at 375×812 (phone, light):

1. ``setup``     first-run setup in the page with the logged code and "Look up barcodes with Open Food Facts"
                 ticked; the admin switches "Optional AI ideas" on in Admin → Server settings and opts in.
2. ``profile``   About you (birth month, height, weight, sex, activity), Kidneys and diabetes; Save; Suggest targets.
3. ``labs``      potassium 5.8 mmol/L and phosphate 1.9 mmol/L: the conversion echo, "What this result changed",
                 then Profile's suggestion lists the changed targets with the rule's reason and "Why this number?".
4. ``day``       a barcode USDA knows (typed), a barcode only Open Food Facts knows (the agreement panel first),
                 a label photo read by AI (consent, fields "from photo"), What fits now → Add, Not for me, a swap
                 ("Use this instead"), and "Plan the rest of my day" → "Use this plan".
5. ``offline``   with the service worker in control: two entries logged offline, reconnect, synced exactly once.
6. ``insights``  a week of history; Trends shows the period insights.
7. ``learn``     the header's Learn entry opens /learn/, a warning's Learn link opens the potassium page.
8. ``second``    a second person (invited) sees none of the first person's labs, guidance choices, AI activity or
                 entries; an entry the first person left waiting offline on this browser is never sent as theirs.
9. ``export``    the first person's export zip (Settings → Download my data) holds the v0.3 data.
10. ``delete``   the second person deletes their account in Settings: every row of theirs is gone.
11. ``screens``  the new screens at 375×812 and 1280×800, light and dark: screenshots and layout checks.

Fails (exit status 1) on any CSP or Trusted Types violation, page or console error, failed request, request to
another origin or HTTP error a step did not expect, and on every failed check. Writes ``<out>/report.json`` and
screenshots in ``<out>/shots/``. Every server and browser it starts is stopped. What it cannot show: a live AI
provider, the live Open Food Facts and USDA services, a real phone.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
import sys
import tempfile
import threading
import traceback
import zipfile
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

import khserver
from device import UPLOAD_SPY, FakeAi, Watch, layout_problems, wait_js
from khserver import DEFAULT_PASSWORD, REPO, chromium_executable

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "journey"
PORT, AI_PORT, OFF_PORT = 8068, 8069, 8070
TIMEOUT_MS = 20_000
SECTIONS = ("setup", "profile", "labs", "day", "offline", "insights", "learn", "second", "export", "delete", "screens")
RESULTS: list[dict[str, Any]] = []
TODAY = date.today()
DIET_COKE = "049000028911"  # USDA FoodData Central knows it (recorded); so does Open Food Facts
NUTELLA = "3017624010701"  # only Open Food Facts knows it (recorded)
ADMIN, SECOND = "mum", "sam"
OFF_FIXTURES = REPO / "tests" / "fixtures" / "off"
PER_PERSON_TABLES = ("log_entries", "meal_templates", "user_profiles", "user_settings", "sessions", "usage_daily",
                     "user_food_links", "lab_results", "food_preferences", "ai_consents", "ai_usage", "ai_audit")


def check(area: str, name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"area": area, "check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} [{area}] {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


# --------------------------------------------------------------------------- fake Open Food Facts

class FakeOff:
    """``GET /api/v3.4/product/<code>`` answered from the recorded fixtures; any other code is the recorded 404."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.requests: list[str] = []
        docs: dict[str, dict[str, Any]] = {}
        for path in sorted(OFF_FIXTURES.glob("*_v3.4.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            docs[doc["request"]["url"].split("/product/", 1)[1].split("?", 1)[0]] = doc
        missing = json.loads((OFF_FIXTURES / "not_found_v3.4.json").read_text(encoding="utf-8"))
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                outer.requests.append(self.path)
                code = self.path.split("/product/", 1)[-1].split("?", 1)[0]
                doc = docs.get(code, missing)
                raw = json.dumps(doc["body"]).encode("utf-8")
                self.send_response(int(doc["status"]))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FakeOff":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# --------------------------------------------------------------------------- the story

class Journey:
    def __init__(self, browser: Any, server: khserver.Server, out: Path, base: str, fake_ai: FakeAi, fake_off: FakeOff) -> None:
        self.browser = browser
        self.server = server
        self.out = out
        self.shots = out / "shots"
        self.base = base
        self.ai = fake_ai
        self.off = fake_off
        self.ctx: Any = None
        self.watch: Watch | None = None
        self.page: Page | None = None
        self.api: dict[str, khserver.Api] = {}
        self.state: dict[str, Any] = {}

    # ---- plumbing
    def context(self, *, width: int = 375, height: int = 812, scheme: str = "light", service_workers: str = "allow",
                init: str | None = None) -> tuple[Any, Watch, Page]:
        touch = width < 700
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, is_mobile=touch,
                                       has_touch=touch, service_workers=service_workers, accept_downloads=True)
        ctx.set_default_timeout(TIMEOUT_MS)
        watch = Watch(self.base)
        watch.attach(ctx)
        if init:
            ctx.add_init_script(init)
        page = ctx.new_page()
        return ctx, watch, page

    def main_page(self) -> Page:
        if self.page is None:
            self.ctx, self.watch, self.page = self.context(init=UPLOAD_SPY)
        return self.page

    def shot(self, page: Page, name: str, full: bool = False) -> None:
        page.screenshot(path=str(self.shots / f"{name}.png"), full_page=full)

    def problems(self, area: str, watch: Watch | None = None) -> None:
        found = (watch or self.watch).take() if (watch or self.watch) else []
        check(area, "no CSP/Trusted Types violations, page or console errors, failed, outside or unexpected requests",
              not found, "; ".join(found[:12]))

    def person(self, username: str) -> khserver.Api:
        if username not in self.api:
            api = khserver.Api(self.server.base)
            api.login(username)
            self.api[username] = api
        return self.api[username]

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.server.data_dir / "kidney.db")
        conn.row_factory = sqlite3.Row
        return conn

    def entries(self, username: str, day: date = TODAY) -> list[dict[str, Any]]:
        return self.person(username).json("GET", f"/api/log?date={day.isoformat()}")["entries"]

    def reauth_if_asked(self, page: Page) -> None:
        """The "Enter your password again" sheet appears for sensitive changes after REAUTH_MINUTES."""
        try:
            page.wait_for_selector("#sheet-reauth[open]", timeout=1500)
        except Exception:  # noqa: BLE001 - not asked
            return
        page.fill("#reauth-password", DEFAULT_PASSWORD)
        page.click("#reauth-submit")
        wait_js(page, "!document.querySelector('#sheet-reauth').open")

    def goto(self, page: Page, hash_: str, ready: str) -> None:
        page.goto(f"{self.base}/{hash_}")
        page.wait_for_selector(ready)

    # ---- 1. first-run setup, AI on, opt in
    def setup(self) -> None:
        area = "1 setup"
        page = self.main_page()
        page.goto(f"{self.base}/")
        page.wait_for_selector("#form-setup:not([hidden])")
        check(area, "a fresh server opens on the first-run setup screen", page.is_visible("#setup-code"))
        check(area, "Open Food Facts is off unless ticked", not page.is_checked("#setup-off"))
        page.fill("#setup-code", khserver.setup_code(self.server))
        page.fill("#setup-username", ADMIN)
        page.fill("#setup-display", "Mum")
        page.fill("#setup-password", DEFAULT_PASSWORD)
        page.check("#setup-off")
        self.shot(page, "01-setup")
        page.click("#setup-submit")
        page.wait_for_selector("#view-today:not([hidden])")
        check(area, "setup signs the admin in and opens Today", page.is_visible("#tab-today"))
        admin = self.person(ADMIN)
        settings = admin.json("GET", "/api/admin/settings")["settings"]
        check(area, "the setup box switched Open Food Facts lookups on", settings["food.off_enabled"]["value"] is True)
        check(area, "AI is off by default", settings["ai.enabled"]["value"] is False)
        check(area, "nothing was sent to the AI provider or Open Food Facts yet", not self.ai.requests and not self.off.requests,
              f"ai {len(self.ai.requests)}, off {len(self.off.requests)}")
        # The admin switches AI on (Admin → Server settings) and opts in (Settings → AI ideas).
        self.goto(page, "#settings", "#adm-ai-enabled")
        with page.expect_response(lambda r: "/api/admin/settings" in r.url and r.request.method == "PATCH"):
            page.check("#adm-ai-enabled")
        self.reauth_if_asked(page)
        wait_js(page, "document.querySelector('#adm-ai-enabled').checked && !document.querySelector('#adm-ai-enabled').disabled")
        check(area, "Admin → Server settings: Optional AI ideas switched on", admin.json("GET", "/api/admin/settings")["settings"]["ai.enabled"]["value"])
        # No reload: Settings → AI ideas above draws again by itself (v0.3.0 review), once, with the opt-in box.
        page.wait_for_selector("#set-ai-slot input[type=checkbox]")
        check(area, "Settings → AI ideas updates in place after the switch (no 'Off on this server', one copy)",
              "Off on this server" not in page.inner_text("#set-ai-slot") and page.locator("#set-ai-slot .ai-admin").count() == 1,
              page.inner_text("#set-ai-slot")[:200])
        if not page.is_checked("#set-ai-slot input[type=checkbox] >> nth=0"):
            page.click("#set-ai-slot label.check >> nth=0")
        page.wait_for_selector("#set-ai-slot >> text=AI ideas are on for you.")
        check(area, "Settings → AI ideas: opted in", admin.json("GET", "/api/me/ai")["settings"]["opt_in"] is True)
        self.shot(page, "01-ai-settings")
        self.problems(area)

    # ---- 2. profile with the personalised inputs
    def profile(self) -> None:
        area = "2 profile"
        page = self.main_page()
        self.goto(page, "#profile", "#view-profile:not([hidden]) #profile-form")
        page.fill("#pf-name", "Mum")
        page.fill("#pf-birth-month", "1968-04")
        page.fill("#pf-height", "165")
        page.fill("#pf-weight", "68")
        page.select_option("#pf-sex", "female")
        page.check("#pf-act-low_active")
        page.select_option("#pf-stage", "3b")
        page.select_option("#pf-dialysis", "none")
        page.select_option("#pf-diabetes", "type1")
        with page.expect_response(lambda r: r.url.endswith("/api/profile") and r.request.method == "PUT") as saved:
            page.click("#btn-save-profile")
        check(area, "Save profile stores the about-you fields", saved.value.status == 200 and saved.value.json()["activity"] == "low_active",
              saved.value.text()[:200])
        with page.expect_response(lambda r: "/api/profile/suggested-targets" in r.url) as sug:
            page.click("#btn-suggest")
        body = sug.value.json()
        notes = page.inner_text("#suggest-notes")
        check(area, "the suggestion uses the personal inputs (age, sex, activity, reference weight)",
              body["derived"]["age"] == TODAY.year - 1968 - (1 if TODAY.month < 4 else 0) and body["derived"]["sex"] == "female"
              and body["derived"]["activity"] == "low_active" and "Worked out for: age" in notes, json.dumps(body["derived"])[:300])
        check(area, "every target has 'Why this number?'", page.locator("#suggest-notes details.why").count() >= 8)
        check(area, "suggested, not saved: the form is filled and says so", "not saved yet" in notes)
        # the diabetes team's snack carbohydrate goal (note 06 §4.11; v0.3.0 review L11): a field of its own
        page.fill("#tg-carbs_per_snack_g", "20")
        with page.expect_response(lambda r: r.url.endswith("/api/profile") and r.request.method == "PUT") as saved:
            page.click("#btn-save-profile")
        targets = saved.value.json()["targets"]
        check(area, "Carbohydrate per snack is saved with the targets", targets.get("carbs_per_snack_g") == 20, json.dumps(targets))
        self.state["targets_before_labs"] = targets
        check(area, "the suggested targets are saved when the person presses Save", targets["potassium_mg"] == body["targets"]["potassium_mg"]
              and targets["carbs_per_meal_g"] == body["targets"]["carbs_per_meal_g"], json.dumps(targets))
        self.shot(page, "02-profile-suggested", full=True)
        self.problems(area)

    # ---- 3. labs change the targets, with explanations
    def labs(self) -> None:
        area = "3 labs"
        page = self.main_page()
        self.goto(page, "#profile", "#view-profile:not([hidden]) #pf-open-labs")
        page.click("#pf-open-labs")
        page.wait_for_selector("#view-labs:not([hidden]) #lab-form")
        changed: list[str] = []
        for analyte, value, unit, echo in (("potassium", "5.8", "mmol/L", "Will be saved as 5.8 mmol/L."),
                                           ("phosphate", "1.9", "mmol/L", "Will be saved as 1.9 mmol/L = 5.9 mg/dL.")):
            page.select_option("#lab-analyte", analyte)
            page.select_option("#lab-unit", unit)
            page.fill("#lab-value", value)
            page.fill("#lab-date", TODAY.isoformat())
            wait_js(page, f"document.querySelector('#lab-echo').textContent.includes({json.dumps(echo)})")
            check(area, f"{analyte}: the conversion echo before saving", True)
            with page.expect_response(lambda r: r.url.endswith("/api/labs") and r.request.method == "POST") as posted:
                page.click("#lab-save")
            check(area, f"{analyte}: saved", posted.value.status == 201, posted.value.text()[:200])
            label = analyte.capitalize()
            wait_js(page, "document.querySelector('#labs-review') && !document.querySelector('#labs-review').hidden"
                    f" && document.querySelector('#labs-review').textContent.includes('{label} {value}')")
            changed.append(page.inner_text("#labs-review"))
        check(area, "'What this result changed' names the potassium target change", "Potassium: 3,500 mg/day → 2,500 mg/day" in changed[0], changed[0][:300])
        check(area, "'What this result changed' names the phosphorus target change", "Phosphorus: 1,000 mg/day → 800 mg/day" in changed[1], changed[1][:300])
        self.shot(page, "03-labs", full=True)
        page.click("#labs-review-go")
        page.wait_for_selector("#view-profile:not([hidden])")
        if not page.locator("#suggest-notes details.why").count():
            with page.expect_response(lambda r: "/api/profile/suggested-targets" in r.url):
                page.click("#btn-suggest")
        wait_js(page, "document.querySelector('#suggest-notes').textContent.includes('Compared with your saved targets')")
        notes = page.inner_text("#suggest-notes")
        check(area, "the suggestion compares with the saved targets and says why each changed",
              "Potassium: 3,500 mg/day → 2,500 mg/day" in notes and "Why: your blood potassium (5.8 mmol/L" in notes
              and "Phosphorus: 1,000 mg/day → 800 mg/day" in notes and "Why: your phosphate (5.9 mg/dL" in notes, notes[:600])
        why = page.locator("#suggest-notes details.why", has_text="(potassium)")
        why.locator("summary").click()
        text = why.inner_text()
        check(area, "'Why this number?' shows the rule, its grade and its source", "Rule K-4" in text and "Source:" in text
              and "your care team sets the number" in text, text[:400])
        with page.expect_response(lambda r: r.url.endswith("/api/profile") and r.request.method == "PUT") as saved:
            page.click("#btn-save-profile")
        targets = saved.value.json()["targets"]
        check(area, "the new targets are saved", targets["potassium_mg"] == 2500 and targets["phosphorus_mg"] == 800, json.dumps(targets))
        check(area, "a suggestion never blanks the snack carbohydrate goal (it does not suggest one)",
              targets.get("carbs_per_snack_g") == 20, json.dumps(targets))
        self.shot(page, "03-profile-after-labs", full=True)
        self.goto(page, "#today", "#view-today:not([hidden]) #meal-h-snack")
        try:  # Today may first draw the day it already had, then the fresh answer
            wait_js(page, "(() => { const h = document.querySelector('#meal-h-snack'); const c = h && h.closest('section').querySelector('.meal-carbs');"
                    " return !!c && c.textContent.includes('of 20 g'); })()")
        except Exception:  # noqa: BLE001 - the check below reports what is shown
            pass
        snack = page.locator("section.meal", has=page.locator("#meal-h-snack")).locator(".meal-carbs").inner_text()
        lunch = page.locator("section.meal", has=page.locator("#meal-h-lunch")).locator(".meal-carbs").inner_text()
        check(area, "Today: the snack is counted against its own goal, the meals against the per-meal goal",
              "of 20 g" in snack and f"of {targets['carbs_per_meal_g']:g} g" in lunch, f"{snack!r} {lunch!r}")
        self.problems(area)

    # ---- 4. a logged day
    def scan(self, page: Page, code: str) -> None:
        self.goto(page, "#add", "#view-add:not([hidden]) #btn-scan")
        page.click("#btn-scan")
        page.wait_for_selector("#sheet-scan[open]")
        page.fill("#scan-code", code)
        page.click("#scan-go")

    def save_entry(self, page: Page, meal: str) -> dict[str, Any]:
        page.click(f"#sheet-entry label[for=meal-{meal}]")
        with page.expect_response(lambda r: re.search(r"/api/log(\?|$)", r.url) is not None and r.request.method == "POST") as posted:
            page.click("#entry-save")
        page.wait_for_selector("#view-today:not([hidden])")
        return posted.value.json()

    def day(self) -> None:
        area = "4 day"
        page = self.main_page()
        admin = self.person(ADMIN)
        # a) A barcode USDA knows: no Open Food Facts agreement needed.
        self.scan(page, DIET_COKE)
        page.wait_for_selector("#sheet-entry[open]")
        prov = page.inner_text("#sheet-entry-provenance")
        check(area, "barcode (USDA): provenance with the CC0 attribution and the barcode", "USDA FoodData Central" in prov
              and "Barcode 0049000028911" in prov, prov[:300])
        check(area, "barcode (USDA): unknown phosphorus reads 'not listed', never 0", "not listed" in page.inner_text("#entry-preview-key"))
        self.shot(page, "04-barcode-usda-entry")
        entry = self.save_entry(page, "breakfast")
        check(area, "barcode (USDA): logged", entry["food_name"].startswith("Diet Coke"))
        check(area, "Open Food Facts was not asked without the person's agreement", not self.off.requests, str(self.off.requests))
        # b) A barcode only Open Food Facts knows: the agreement panel first.
        self.watch.expect("/api/foods/barcode", 503)
        self.scan(page, NUTELLA)
        page.wait_for_selector("#scan-result >> text=Look this up in Open Food Facts?")
        self.shot(page, "04-barcode-off-consent")
        check(area, "barcode (Open Food Facts): asks first, sends nothing before", not self.off.requests)
        page.click("#scan-result >> text=Send barcodes to Open Food Facts and look up")
        page.wait_for_selector("#sheet-entry[open]")
        prov = page.inner_text("#sheet-entry-provenance")
        link = page.get_attribute("#sheet-entry-provenance a", "href") or ""
        check(area, "barcode (Open Food Facts): ODbL attribution with an https product link",
              "Open Food Facts contributors, ODbL" in prov and link.startswith("https://world.openfoodfacts.org/product/"), prov[:300] + " " + link)
        check(area, "Open Food Facts was asked once, for this barcode only", len(self.off.requests) == 1 and NUTELLA in self.off.requests[0],
              str(self.off.requests))
        check(area, "the agreement is the person's setting", admin.json("GET", "/api/me/settings")["settings"]["food.off_consent"]["value"] is True)
        self.save_entry(page, "breakfast")
        # The spread lists no potassium or phosphorus: every total says so and none looks complete (v0.3.0 review, C1).
        day = admin.json("GET", f"/api/log?date={TODAY.isoformat()}")
        check(area, "the day counts the spread's potassium and phosphorus as not listed",
              day["unknown"].get("potassium_mg", 0) >= 1 and day["meal_unknown"]["breakfast"].get("phosphorus_mg", 0) >= 1
              and day["status"]["potassium_mg"]["unknown"] >= 1, json.dumps({k: day[k] for k in ("unknown", "meal_unknown")}))
        self.goto(page, "#today", "#view-today:not([hidden]) #status-bars .stat")
        shown = page.evaluate("""() => {
          const stat = [...document.querySelectorAll('#status-bars .stat')].find((el) => /^Potassium/.test(el.querySelector('.stat-label').textContent));
          const meal = document.querySelector('#meal-h-breakfast').closest('.meal').querySelector('.meal-sum');
          return { stat: stat ? stat.innerText : '', meal: meal ? meal.innerText : '' };
        }""")
        check(area, "Today: the potassium bar says '≥', 'Not complete' (or a warning) and why, and never 'mg left'",
              ("≥" in shown["stat"] or "not listed" in shown["stat"]) and "does not list potassium" in shown["stat"] and "left" not in shown["stat"]
              and ("Not complete" in shown["stat"] or "limit" in shown["stat"]), shown["stat"])
        check(area, "Today: breakfast's line says potassium and phosphorus are not listed (never 'K 0')",
              "not listed" in shown["meal"] and "K 0 " not in shown["meal"] + " ", shown["meal"])
        self.shot(page, "04-today-not-listed")
        self.goto(page, "#trends", "#view-trends:not([hidden]) #charts .chart-card")
        chart = page.inner_text("#charts .chart-card:has(#chart-h-potassium_mg)")
        check(area, "Trends: the potassium chart says the day is not complete", "not complete" in chart and "≥" in chart, chart[:300])
        # c) A label photo read by AI.
        self.goto(page, "#add", "#view-add:not([hidden]) #btn-quick")
        page.click("#btn-quick")
        page.wait_for_selector("#sheet-quick[open]")
        label = self.out / "label.jpg"
        jpeg_b64 = page.evaluate("""(() => { const c = document.createElement('canvas'); c.width = 2400; c.height = 1800;
          const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 2400, 1800); g.fillStyle = '#000';
          for (let y = 100; y < 1700; y += 80) g.fillRect(150, y, 2000, 26); return c.toDataURL('image/jpeg', 0.9).split(',')[1]; })()""")
        label.write_bytes(base64.b64decode(jpeg_b64))
        page.set_input_files("#q-photo", str(label))
        page.wait_for_selector("#q-photo-ai >> text=Read the label for me (AI)")
        self.watch.expect("/api/vision/label", 409)
        page.click("#q-photo-ai >> text=Read the label for me (AI)")
        page.wait_for_selector("#sheet-ai-consent[open]")
        self.shot(page, "04-ai-consent")
        page.click("#sheet-ai-consent >> text=Agree and send")
        wait_js(page, "document.querySelector('#q-name').value === 'Harness rye crackers'")
        check(area, "label photo: AI filled Quick add, the fields marked 'from photo'", page.locator("#sheet-quick .ai-tag").count() >= 5)
        check(area, "label photo: the ingredient list flags the phosphate additive before saving",
              "Phosphate additives" in page.inner_text("#q-ingredients-scan"))
        self.shot(page, "04-label-filled")
        page.click("#sheet-quick label[for=qmeal-lunch]")
        page.click("#quick-save")
        page.wait_for_selector("#view-today:not([hidden])")
        check(area, "label photo: logged", any(e["food_name"] == "Harness rye crackers" for e in self.entries(ADMIN)))
        # d) What fits now → Add; Not for me.
        self.goto(page, "#add", "#guidance-fits:not([hidden])")
        page.click("#guidance-fits-meal label[for=gfm-lunch]")
        page.wait_for_selector("#guidance-fits-body .g-food")
        names = page.locator("#guidance-fits-body .g-food .row-title").all_inner_texts()
        for meal in ("breakfast", "lunch", "dinner", "snack"):
            fits = admin.json("GET", f"/api/guidance/next-meal?meal={meal}&date={TODAY.isoformat()}&limit=20")
            alcohol = [f["name"] for f in fits["foods"] if "alcohol" in admin.json("GET", f"/api/foods/{f['food_id']}")["flags"]]
            check(area, f"What fits now ({meal}) never suggests an alcoholic drink", fits["status"] == "ok" and not alcohol, json.dumps(alcohol))
        check(area, "What fits now lists foods for lunch", names, json.dumps(names[:8]))
        check(area, "What fits now says what is left for the meal", "Left for lunch" in page.inner_text("#guidance-fits"))
        # Note 06 R10: the answer says which targets it used and when the profile holding them was saved.
        k_target = admin.json("GET", "/api/profile")["targets"].get("potassium_mg")
        used = page.inner_text("#guidance-fits-body .g-targets")
        check(area, "What fits now names the targets it used and when they were saved, with a way to Profile",
              used.startswith("Using the targets in your profile, saved ") and f"potassium {int(k_target):,} mg" in used
              and "Check them in Profile" in used, used)
        self.shot(page, "04-what-fits")
        page.click("#guidance-fits-body .g-targets button")
        page.wait_for_selector("#view-profile:not([hidden])")
        check(area, "'Check them in Profile' opens Profile", True)
        self.goto(page, "#add", "#guidance-fits:not([hidden])")
        page.click("#guidance-fits-meal label[for=gfm-lunch]")
        page.wait_for_selector("#guidance-fits-body .g-food")
        first = page.locator("#guidance-fits-body .g-food").first
        picked = first.locator(".row-title").inner_text()
        first.locator("button.g-act", has_text="Add").click()
        page.wait_for_selector("#sheet-entry[open]")
        self.save_entry(page, "lunch")
        check(area, "What fits now → Add logs that food for lunch", any(e["food_name"] == picked and e["meal"] == "lunch" for e in self.entries(ADMIN)), picked)
        self.goto(page, "#add", "#guidance-fits:not([hidden])")
        page.click("#guidance-fits-meal label[for=gfm-lunch]")
        page.wait_for_selector("#guidance-fits-body .g-food")
        row = page.locator("#guidance-fits-body .g-food").nth(1)
        nfm_name = row.locator(".row-title").inner_text()
        row.locator("button.g-more").click()
        with page.expect_response(lambda r: "/api/guidance/not-for-me/" in r.url and r.request.method == "PUT"):
            row.locator("button.g-nfm").click()
        self.state["not_for_me"] = nfm_name
        listed = [f["name"] for f in admin.json("GET", "/api/guidance/not-for-me")["foods"]]
        check(area, "Not for me is saved for this person", listed == [nfm_name], json.dumps(listed))
        # e) A swap: banana at lunch has a high potassium warning; "Use this instead".
        self.goto(page, "#add", "#food-search")
        with page.expect_response(lambda r: "/api/foods?" in r.url and "q=banana" in r.url):
            page.fill("#food-search", "banana")
        page.click("#food-results .row-btn >> text=/^Banana, raw/ >> nth=0")
        page.wait_for_selector("#sheet-entry[open]")
        page.click("#sheet-entry label[for=meal-lunch]")
        warn = page.inner_text("#entry-warnings")
        learn = page.locator("#entry-warnings a", has_text="Learn")
        self.state["warning_learn_href"] = learn.first.get_attribute("href") if learn.count() else None
        check(area, "banana: a high potassium warning with a Learn link", "potassium" in warn.lower() and learn.count() >= 1, warn[:200])
        page.click("#entry-guidance summary")
        page.wait_for_selector("#entry-guidance .g-food")
        swap_name = page.locator("#entry-guidance .g-food .row-title").first.inner_text()
        self.shot(page, "04-swap-ideas")
        page.locator("#entry-guidance .g-food").first.locator("button", has_text="Use this instead").click()
        wait_js(page, f"document.querySelector('.sheet-food-name') && document.querySelector('.sheet-food-name').textContent.includes({json.dumps(swap_name.split(',')[0])})")
        self.save_entry(page, "lunch")
        lunch = [e["food_name"] for e in self.entries(ADMIN) if e["meal"] == "lunch"]
        check(area, "the swap was logged instead of the banana", swap_name in lunch and not any(n.startswith("Banana") for n in lunch), json.dumps(lunch))
        # f) Plan the rest of my day.
        before = len(self.entries(ADMIN))
        self.goto(page, "#today", "#guidance-today-actions")
        page.click("#guidance-today-actions button >> text=Plan the rest of my day")
        page.wait_for_selector("#sheet-guidance[open] #g-plan-use:not([disabled])")
        used = page.inner_text("#g-plan-out .g-targets")
        check(area, "the plan names the targets it used and when they were saved",
              used.startswith("Using the targets in your profile, saved ") and f"potassium {int(k_target):,} mg" in used, used)
        self.shot(page, "04-plan")
        planned_n = int(re.search(r"plan (\d+)", page.get_attribute("#g-plan-use", "aria-label") or "plan 0").group(1))
        with page.expect_response(lambda r: r.url.endswith("/api/log/batch")) as batch:
            page.click("#g-plan-use")
        check(area, "Use this plan sends the plan as planned entries in one batch", batch.value.status == 201, batch.value.text()[:200])
        after = self.entries(ADMIN)
        check(area, "the planned entries are on Today", len(after) == before + planned_n and planned_n > 0
              and sum(e["status"] == "planned" for e in after) == planned_n, f"{before} + {planned_n} → {len(after)}")
        self.problems(area)

    # ---- 5. offline: two entries, synced exactly once
    def offline(self) -> None:
        area = "5 offline"
        page = self.main_page()
        page.goto(f"{self.base}/")
        wait_js(page, "navigator.serviceWorker && navigator.serviceWorker.ready.then(() => true)")
        for _ in range(3):
            if page.evaluate("!!navigator.serviceWorker.controller"):
                break
            page.reload()
            page.wait_for_selector("#view-today:not([hidden])")
        check(area, "the service worker controls the page", page.evaluate("!!navigator.serviceWorker.controller"))
        self.goto(page, "#add", "#food-search")
        before = {e["id"] for e in self.entries(ADMIN)}
        names = []
        self.watch.offline = True
        self.ctx.set_offline(True)
        for query, pattern in (("apple raw", "/apple/i"), ("blueberries", "/blueberr/i")):
            page.fill("#food-search", query)
            page.wait_for_selector(f"#food-results .row-btn >> text={pattern}")
            page.click(f"#food-results .row-btn >> text={pattern} >> nth=0")
            page.wait_for_selector("#sheet-entry[open]")
            names.append(page.inner_text(".sheet-food-name"))
            page.click("#sheet-entry label[for=meal-snack]")
            page.click("#entry-save")
            page.wait_for_selector("#view-today:not([hidden]) .badge.pending")
            self.goto(page, "#add", "#food-search") if query == "apple raw" else None
        self.goto(page, "#today", "#view-today:not([hidden]) .badge.pending")
        check(area, "offline: both entries wait on this device", page.evaluate("KH.offline.counts().pending") == 2)
        check(area, "the header badge says 2 to sync", "2 to sync" in (page.get_attribute("#sync-badge", "aria-label") or "")
              or page.inner_text("#sync-badge").strip() == "2")
        self.shot(page, "05-offline-waiting")
        self.ctx.set_offline(False)
        self.watch.offline = False
        wait_js(page, "KH.offline.counts().pending === 0", TIMEOUT_MS)
        new = [e for e in self.entries(ADMIN) if e["id"] not in before]
        check(area, "reconnected: synced exactly once (two new rows, each with its own client_id)",
              sorted(e["food_name"] for e in new) == sorted(names) and len({e["client_id"] for e in new}) == 2, json.dumps([(e["food_name"], e["client_id"]) for e in new]))
        page.evaluate("KH.offline.syncNow()")
        page.reload()
        page.wait_for_selector("#view-today:not([hidden])")
        again = [e for e in self.entries(ADMIN) if e["id"] not in before]
        check(area, "another sync and a reload add nothing", len(again) == 2)
        self.problems(area)

    # ---- 6. insights in Trends
    def insights(self) -> None:
        area = "6 insights"
        admin = self.person(ADMIN)
        foods = {q: admin.json("GET", f"/api/foods?q={q}")["foods"][0]["id"] for q in ("banana", "rice", "chicken", "milk")}
        items = []
        for back in range(1, 8):
            d = (TODAY - timedelta(days=back)).isoformat()
            items += [{"date": d, "meal": "breakfast", "food_id": foods["milk"], "servings": 2},
                      {"date": d, "meal": "lunch", "food_id": foods["banana"], "servings": 2},
                      {"date": d, "meal": "dinner", "food_id": foods["chicken"], "servings": 1.5},
                      {"date": d, "meal": "dinner", "food_id": foods["rice"], "servings": 1}]
        admin.json("POST", "/api/log/batch", {"entries": items[:40]})
        page = self.main_page()
        self.goto(page, "#trends", "#guidance-period:not([hidden])")
        wait_js(page, "document.querySelectorAll('#guidance-period-body li, #guidance-period-body .g-insight').length > 0")
        text = page.inner_text("#guidance-period")
        check(area, "Trends shows period insights for the last 7 days, with numbers", "potassium" in text.lower() and re.search(r"\d", text), text[:400])
        self.shot(page, "06-trends-insights", full=True)
        self.problems(area)

    # ---- 7. Learn links
    def learn(self) -> None:
        area = "7 learn"
        page = self.main_page()
        self.goto(page, "#today", "#learn-link:not([hidden])")
        with page.expect_navigation():
            page.click("#learn-link")
        check(area, "the header's Learn entry opens the handbook start page in the same window", page.url.rstrip("/").endswith("/learn"),
              page.url)
        check(area, "the handbook page has its title", "handbook" in page.title().lower() or page.locator("h1").count() == 1, page.title())
        self.shot(page, "07-learn-home")
        href = self.state.get("warning_learn_href")
        check(area, "the potassium warning links to the potassium page", href and href.endswith("/learn/eat/potassium/"), str(href))
        if href:
            page.goto(href if href.startswith("http") else f"{self.base}{href}")
            check(area, "the potassium page opens", "potassium" in page.locator("h1").first.inner_text().lower())
            self.shot(page, "07-learn-potassium")
        page.goto(f"{self.base}/")
        page.wait_for_selector("#view-today:not([hidden])")
        self.problems(area)

    # ---- 8. a second person
    def second(self) -> None:
        area = "8 second person"
        admin = self.person(ADMIN)
        token = khserver.invite_token(admin)
        # The first person leaves one entry waiting offline on this browser, then their session ends (cookies gone).
        page = self.main_page()
        self.goto(page, "#add", "#food-search")
        page.fill("#food-search", "grapes")
        page.wait_for_selector("#food-results .row-btn >> text=/grape/i")
        self.watch.offline = True
        self.ctx.set_offline(True)
        page.click("#food-results .row-btn >> text=/grape/i >> nth=0")
        page.wait_for_selector("#sheet-entry[open]")
        waiting_name = page.inner_text(".sheet-food-name")
        page.click("#entry-save")
        page.wait_for_selector("#view-today:not([hidden]) .badge.pending")
        self.ctx.clear_cookies()
        self.ctx.set_offline(False)
        self.watch.offline = False
        for path in ("/api/log/batch", "/api/foods/categories", "/api/foods", "/api/profile", "/api/me", "/api/handbook"):
            self.watch.expect(path, 401)  # background reads and the sync while nobody is signed in
        # The second person opens the invite link on the same browser (a new page load, as from a message).
        self.watch.expected_failures.add(("/icons/icon.svg", "net::ERR_ABORTED"))  # the tab icon, cut off by leaving the page
        page.goto("about:blank")
        page.goto(f"{self.base}/#/invite/{token}")
        page.wait_for_selector("#form-register:not([hidden])")
        page.fill("#reg-username", SECOND)
        page.fill("#reg-password", DEFAULT_PASSWORD)
        with page.expect_response(lambda r: r.url.endswith("/api/auth/register")) as reg:
            page.click("#reg-submit")
        check(area, "the second person registers from the invite link", reg.value.status == 201, reg.value.text()[:200])
        page.wait_for_selector("#view-today:not([hidden])")
        page.wait_for_timeout(1500)  # give any (wrong) sync a chance
        sam = self.person(SECOND)
        sam_entries = sam.json("GET", f"/api/log?date={TODAY.isoformat()}")["entries"]
        check(area, "the first person's waiting entry is not sent as the second person's", not sam_entries, json.dumps(sam_entries)[:200])
        check(area, "Today shows none of the first person's entries", waiting_name not in page.inner_text("#meals")
              and page.locator("#meals .entry").count() == 0)
        self.goto(page, "#labs", "#view-labs:not([hidden]) #labs-history")
        check(area, "Lab results: none of the first person's", "5.8" not in page.inner_text("#labs-history"))
        check(area, "GET /api/labs is empty for the second person", sam.json("GET", "/api/labs")["labs"] == [])
        self.goto(page, "#settings", "#set-guidance-body")
        wait_js(page, "document.querySelector('#set-guidance-body').textContent.length > 20")
        check(area, "Settings → Meal guidance: the first person's 'Not for me' food is not listed",
              self.state.get("not_for_me", "\u0000") not in page.inner_text("#set-guidance-body"))
        check(area, "the second person's 'Not for me' list is empty", sam.json("GET", "/api/guidance/not-for-me")["foods"] == [])
        me_ai = sam.json("GET", "/api/me/ai")
        check(area, "no AI activity, consent or provider of the first person", me_ai["own"] is None and not me_ai["consents"])
        check(area, "AI activity is empty for the second person", sam.json("GET", "/api/ai/audit")["events"] == [])
        self.shot(page, "08-second-settings", full=True)
        # The first person signs in again on this browser: their waiting entry goes to them.
        page.click("#set-signout") if page.is_visible("#set-signout") else None
        if page.is_visible("#sheet-unsynced[open]"):
            page.click("#sheet-unsynced >> text=Sign out and lose them")
        page.wait_for_selector("#form-login:not([hidden])")
        page.fill("#login-username", ADMIN)
        page.fill("#login-password", DEFAULT_PASSWORD)
        page.click("#login-submit")
        page.wait_for_selector("#view-today:not([hidden])")
        mine = [e for e in self.entries(ADMIN) if e["food_name"] == waiting_name]
        check(area, "after signing out and in, the first person's account holds the waiting entry at most once", len(mine) <= 1)
        check(area, "the second person's account never got it", not sam.json("GET", f"/api/log?date={TODAY.isoformat()}")["entries"])
        self.problems(area)

    # ---- 9. export
    def export(self) -> None:
        area = "9 export"
        page = self.main_page()
        self.goto(page, "#settings", "#set-account-body")
        page.wait_for_selector("#set-export")
        with page.expect_download() as dl:
            page.click("#set-export")
            self.reauth_if_asked(page)
        path = self.out / "export.zip"
        dl.value.save_as(str(path))
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            doc = json.loads(z.read("export.json"))
            labs_csv = z.read("labs.csv").decode("utf-8")
            log_csv = z.read("log.csv").decode("utf-8")
            foods_csv = z.read("foods.csv").decode("utf-8")
            readme = z.read("README.txt").decode("utf-8")
        check(area, "the zip has export.json, log.csv, foods.csv, meals.csv, labs.csv, README.txt",
              {"export.json", "log.csv", "foods.csv", "meals.csv", "labs.csv", "README.txt"} <= names, str(sorted(names)))
        check(area, "lab results (export.json and labs.csv)", len(doc["lab_results"]) == 2 and "potassium" in labs_csv and "phosphate" in labs_csv)
        check(area, "the profile's v0.3 fields", doc["profile"].get("activity") == "low_active" and doc["profile"].get("sex") == "female")
        check(area, "'Not for me' foods", [f.get("name") for f in doc["food_preferences"]] == [self.state.get("not_for_me")], json.dumps(doc["food_preferences"])[:200])
        check(area, "AI activity, usage and consents (no keys)", doc["ai_audit"] and doc["ai_usage"] and doc["ai_consents"])
        check(area, "log entries carry client_id and purpose; log.csv has purpose, source and source_license",
              any(e.get("client_id") for e in doc["log_entries"]) and "purpose" in log_csv.splitlines()[0]
              and "source_license" in log_csv.splitlines()[0])
        check(area, "foods.csv carries the scanned barcode and the ODbL notice is in the README",
              "03017624010701" in foods_csv and "ODbL" in readme)
        self.problems(area)

    # ---- 10. account deletion
    def delete(self) -> None:
        area = "10 delete"
        sam = self.person(SECOND)
        sam.json("POST", "/api/labs", {"analyte": "potassium", "value": 4.1, "unit": "mmol/L", "taken_on": TODAY.isoformat()})
        banana = sam.json("GET", "/api/foods?q=banana")["foods"][0]["id"]
        sam.json("PUT", f"/api/guidance/not-for-me/{banana}")
        sam.json("POST", "/api/log", {"date": TODAY.isoformat(), "meal": "lunch", "food_id": banana,
                                      "client_id": "0b6f3a52-1c1e-4b7a-9d8e-5f6a7b8c9d0e"})
        sam_id = sam.json("GET", "/api/me")["id"]
        ctx, watch, page = self.context(width=1280, height=800, service_workers="block")
        try:
            ctx.add_cookies([{"name": k, "value": v, "url": self.base} for k, v in sam.cookies().items()])
            watch.expected_failures.add(("/icons/icon.svg", "net::ERR_ABORTED"))  # the page reloads after the deletion
            self.goto(page, "#settings", "#set-account-body")
            page.click("#set-delete summary")
            page.fill("#set-delete-password", DEFAULT_PASSWORD)
            page.fill("#set-delete-confirm", "DELETE")
            with page.expect_response(lambda r: r.url.endswith("/api/me") and r.request.method == "DELETE") as deleted:
                page.click("#set-delete-save")
            check(area, "Settings → Delete my account answers 204", deleted.value.status == 204, str(deleted.value.status))  # the page reloads: no body
            page.wait_for_selector("#view-auth:not([hidden])")
        finally:
            self.problems(area, watch)
            ctx.close()
        conn = self.db()
        try:
            left = {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id = ?", (sam_id,)).fetchone()[0] for t in PER_PERSON_TABLES}
            left["foods (custom)"] = conn.execute("SELECT COUNT(*) FROM foods WHERE owner_user_id = ?", (sam_id,)).fetchone()[0]
            left["ai_providers"] = conn.execute("SELECT COUNT(*) FROM ai_providers WHERE owner_user_id = ?", (sam_id,)).fetchone()[0]
            left["users"] = conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (sam_id,)).fetchone()[0]
            first = conn.execute("SELECT COUNT(*) FROM lab_results WHERE user_id = 1").fetchone()[0]
        finally:
            conn.close()
        check(area, "every row of the deleted person is gone (log, labs, guidance choices, AI, sessions, settings)",
              not any(left.values()), json.dumps(left))
        check(area, "the first person's rows are untouched", first == 2)
        self.api.pop(SECOND, None)

    # ---- 11. screens at both sizes and themes
    def screens(self) -> None:
        for width, height in ((375, 812), (1280, 800)):
            for scheme in ("light", "dark"):
                self.walk(width, height, scheme)

    def walk(self, width: int, height: int, scheme: str) -> None:
        area = f"11 screens {width}x{height} {scheme}"
        admin = self.person(ADMIN)
        ctx, watch, page = self.context(width=width, height=height, scheme=scheme, service_workers="block")
        tag = f"{width}-{scheme}"
        try:
            ctx.add_cookies([{"name": k, "value": v, "url": self.base} for k, v in admin.cookies().items()])
            views = (("#today", "#view-today:not([hidden]) #guidance-today", "today"),
                     ("#add", "#view-add:not([hidden]) #guidance-fits", "add"),
                     ("#trends", "#view-trends:not([hidden]) #guidance-period", "trends"),
                     ("#profile", "#view-profile:not([hidden]) #profile-form", "profile"),
                     ("#labs", "#view-labs:not([hidden]) #lab-form", "labs"),
                     ("#settings", "#view-settings:not([hidden]) #set-guidance", "settings"))
            for hash_, ready, name in views:
                self.goto(page, hash_, ready)
                page.wait_for_timeout(400)
                self.shot(page, f"11-{name}-{tag}", full=True)
                problems = [p for p in layout_problems(page, "#main") if "sideways" in p]
                check(area, f"{name}: no sideways scroll", not problems, "; ".join(problems))
            self.goto(page, "#add", "#view-add:not([hidden]) #btn-scan")
            page.click("#btn-scan")
            page.wait_for_selector("#sheet-scan[open]")
            self.shot(page, f"11-scan-{tag}")
            problems = layout_problems(page, "#sheet-scan") if width < 720 else [p for p in layout_problems(page, "#sheet-scan") if "sideways" in p or "cut off" in p]
            check(area, "scan sheet lays out (on a phone: 44 px targets; never cut-off buttons)", not problems, "; ".join(problems[:6]))
            page.keyboard.press("Escape")
            self.goto(page, "#today", "#guidance-today-actions")
            page.click("#guidance-today-actions button >> text=Treating a low")
            page.wait_for_selector("#sheet-guidance[open]")
            self.shot(page, f"11-low-{tag}")
            problems = layout_problems(page, "#sheet-guidance") if width < 720 else [p for p in layout_problems(page, "#sheet-guidance") if "sideways" in p]
            check(area, "Treating a low lays out (on a phone: 44 px targets)", not problems, "; ".join(problems[:6]))
        finally:
            self.problems(area, watch)
            ctx.close()


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", type=Path, required=True, help="a built handbook (cd handbook && mkdocs build): HANDBOOK_DIR")
    ap.add_argument("--port", type=int, default=PORT, help=f"the app (default {PORT})")
    ap.add_argument("--ai-port", type=int, default=AI_PORT, help=f"the fake OpenAI-compatible server (default {AI_PORT})")
    ap.add_argument("--off-port", type=int, default=OFF_PORT, help=f"the fake Open Food Facts (default {OFF_PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory (default {OUT})")
    ap.add_argument("--only", default="", help=f"comma-separated sections, in story order ({', '.join(SECTIONS)}); default all")
    ap.add_argument("--server-python", default=sys.executable, help="interpreter that runs the server (default: this one)")
    args = ap.parse_args(argv)
    only = [s for s in args.only.split(",") if s] or list(SECTIONS)
    unknown = [s for s in only if s not in SECTIONS]
    if unknown:
        ap.error(f"unknown section(s): {', '.join(unknown)}")
    if not (args.site / "index.html").is_file():
        ap.error(f"{args.site} is not a built handbook (no index.html); build it with: cd handbook && mkdocs build")
    for port in (args.port, args.ai_port, args.off_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick others with --port / --ai-port / --off-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    nowhere = "http://127.0.0.1:9"  # no call may leave this machine
    env = {"AI_PROVIDER": "openai_compatible", "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1", "AI_MODEL": "fake-text",
           "AI_VISION_MODEL": "fake-vision", "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port}", "AI_VISION_PLATE_ENABLED": "true",
           "OFF_BASE_URL": f"http://localhost:{args.off_port}", "USDA_API_KEY": "replayed-usda-key-0123456789",
           "HANDBOOK_DIR": str(args.site.resolve()),
           "HTTPS_PROXY": nowhere, "HTTP_PROXY": nowhere, "ALL_PROXY": nowhere, "https_proxy": nowhere, "http_proxy": nowhere,
           "all_proxy": nowhere, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = khserver.Server(args.port, out / "data", log_path=out / "server.log", python=args.server_python, env=env,
                             app_spec="replay_app:app")
    journey: Journey | None = None
    try:
        with FakeAi(args.ai_port) as fake_ai, FakeOff(args.off_port) as fake_off:
            server.start()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=chromium_executable(), args=["--no-sandbox"])
                journey = Journey(browser, server, out, f"http://localhost:{args.port}", fake_ai, fake_off)
                try:
                    for name in only:
                        try:
                            getattr(journey, name)()
                        except Exception as exc:  # report, keep a screenshot, go on with the next section
                            check(name, "section finished", False, f"{type(exc).__name__}: {exc}")
                            traceback.print_exc()
                            if journey.page is not None:
                                try:
                                    journey.shot(journey.page, f"error-{name}")
                                except Exception:  # noqa: BLE001
                                    pass
                finally:
                    browser.close()
            for api in journey.api.values():
                api.close()
    except Exception as exc:
        check("harness", "servers and browser started", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        server.stop()
    failed = [r for r in RESULTS if not r["ok"]]
    (out / "report.json").write_text(json.dumps({"failed": len(failed), "results": RESULTS}, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}, screenshots {out / 'shots'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
