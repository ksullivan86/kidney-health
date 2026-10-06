#!/usr/bin/env python3
"""Real-app regression harness for kidney-health: the INSTALLED app (real uvicorn server, no
window.KDL_PREVIEW, no ?mock=1), driven with Playwright at 375x812 and 1280x800, light and dark.

    python tools/e2e/regress.py              # static checks + 4 UI configs + probes
    python tools/e2e/regress.py --no-pytest  # skip the pytest run
    python tools/e2e/regress.py --only 375-light --port 8063 --out /tmp/kh-regress

Each UI config starts uvicorn on 127.0.0.1:<port> (default 8063) with a freshly wiped DATA_DIR
(first launch, empty profile), finishes first-run setup **in the page** with the setup code from the
server log (v0.3 accounts: nothing works before someone signs in), and stops the server afterwards.
Direct API reads use a second signed-in session with the app's CSRF headers. Prints PASS / FAIL /
INFO lines, writes <out>/report.json and screenshots to <out>/shots/. Exit status 1 when any check
fails. Does not modify the repository.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx2
from playwright.sync_api import sync_playwright

import khserver
from khserver import DEFAULT_PASSWORD, REPO, Api, chromium_executable, setup_code

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "regress"
DATA = OUT / "data"
SHOTS = OUT / "shots"
PORT = 8063
BASE = f"http://127.0.0.1:{PORT}"
USERNAME = "regress"


def configure(out: Path, port: int) -> None:
    global OUT, DATA, SHOTS, PORT, BASE
    OUT, DATA, SHOTS, PORT = out, out / "data", out / "shots", port
    BASE = f"http://127.0.0.1:{PORT}"


CONFIGS = [
    ("375-light", 375, 812, "light"),
    ("375-dark", 375, 812, "dark"),
    ("1280-light", 1280, 800, "light"),
    ("1280-dark", 1280, 800, "dark"),
]
INT_KEYS = {"calories_kcal", "sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg", "fluid_ml"}
KEY_NUMBERS = ["carbs_g", "protein_g", "potassium_mg", "phosphorus_mg", "sodium_mg"]

RESULTS: list[dict] = []


def check(area: str, name: str, ok, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"area": area, "check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} [{area}] {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def info(area: str, name: str, detail: str = "") -> None:
    RESULTS.append({"area": area, "check": name, "ok": None, "detail": detail})
    print(f"INFO [{area}] {name}" + (f" :: {detail}" if detail else ""), flush=True)


# --------------------------------------------------------------------------- server
API: Api | None = None  # the harness's own signed-in session (direct API reads and writes)


class Server:
    """A fresh server per config (:class:`khserver.Server`); :meth:`start` returns ``/healthz``."""

    def __init__(self) -> None:
        self.srv: khserver.Server | None = None

    def start(self) -> dict:
        global API
        try:
            httpx2.get(BASE + "/healthz", timeout=0.5, trust_env=False)
            raise RuntimeError(f"port {PORT} is already in use; stop that server first")
        except httpx2.TransportError:
            pass
        OUT.mkdir(parents=True, exist_ok=True)
        self.srv = khserver.Server(PORT, DATA, log_path=OUT / "server.log").start()
        API = None
        return httpx2.get(BASE + "/healthz", timeout=5, trust_env=False).json()

    def code(self) -> str:
        assert self.srv is not None
        return setup_code(self.srv)

    def admin_via_api(self) -> Api:
        """First-run setup through the API (probes that do not test the setup screen)."""
        global API
        assert self.srv is not None
        API = khserver.first_admin(self.srv, USERNAME)
        return API

    def stop(self) -> None:
        global API
        if API is not None:
            API.close()
            API = None
        if self.srv is not None:
            self.srv.stop()
            self.srv = None


def api_login() -> Api:
    """A second session for the harness's direct API calls (the page keeps its own)."""
    global API
    API = Api(BASE)
    API.login(USERNAME, DEFAULT_PASSWORD)
    return API


def sget(path: str):
    assert API is not None, "sign in first"
    return API.call("GET", path)


def ui_setup(page, server: Server) -> None:
    """Finish first-run setup on the setup screen (fresh server), as a person would."""
    page.wait_for_selector("#form-setup:not([hidden])", timeout=15000)
    page.fill("#setup-code", server.code())
    page.fill("#setup-username", USERNAME)
    page.fill("#setup-password", DEFAULT_PASSWORD)
    page.click("#setup-submit")
    page.wait_for_selector("#view-today:not([hidden])", timeout=15000)


def ui_sign_in(page) -> None:
    page.wait_for_selector("#form-login:not([hidden])", timeout=15000)
    page.fill("#login-username", USERNAME)
    page.fill("#login-password", DEFAULT_PASSWORD)
    page.click("#login-submit")
    page.wait_for_selector("#view-today:not([hidden])", timeout=15000)


# --------------------------------------------------------------------------- page instrumentation
INIT_SCRIPT = r"""
(() => {
  const rec = { getById: [], qs: [] };
  Object.defineProperty(window, '__regress', { value: rec, enumerable: false });
  const gid = Document.prototype.getElementById;
  Document.prototype.getElementById = function (id) { rec.getById.push(String(id)); return gid.call(this, id); };
  const qsel = Document.prototype.querySelector;
  Document.prototype.querySelector = function (sel) { if (/kdl-foods/.test(String(sel))) rec.qs.push(String(sel)); return qsel.call(this, sel); };
})();
"""


class Recorder:
    def __init__(self, page) -> None:
        self.requests: list[tuple] = []
        self.responses: list[tuple] = []
        self.console: list[tuple] = []
        self.pageerrors: list[str] = []
        self.dialogs: list[tuple] = []
        self.failed: list[tuple] = []
        page.on("request", lambda r: self.requests.append((r.method, r.url, r.post_data, r.resource_type)))
        page.on("response", lambda r: self.responses.append((r.request.method, r.url, r.status)))
        page.on("console", lambda m: self.console.append((m.type, m.text)))
        page.on("pageerror", lambda e: self.pageerrors.append(str(e)))
        page.on("dialog", self._dialog)
        page.on("requestfailed", lambda r: self.failed.append((r.method, r.url, r.failure)))

    def _dialog(self, d) -> None:
        self.dialogs.append((d.type, d.message))
        d.dismiss()

    def calls(self, method: str, path: str, exact: bool = False) -> list[tuple]:
        out = []
        for m, url, body, _rt in self.requests:
            p = urlparse(url).path
            if m == method and (p == path if exact else p.startswith(path)):
                out.append((m, url, body))
        return out


# --------------------------------------------------------------------------- helpers
def fmt_num(v, key) -> str:
    """app.js fmtNum for already-rounded server values."""
    if v is None:
        return "–"
    if key in INT_KEYS:
        return f"{int(round(v)):,}"
    r = round(float(v) * 10) / 10
    return f"{int(r):,}" if r == int(r) else f"{r:,.1f}"


def expected_warning_texts(warnings: list[dict]) -> list[str]:
    return [("High. " if w["level"] == "high" else "Moderate. ") + w["message"] for w in warnings]


READ_WARNINGS = """(sel) => Array.from(document.querySelectorAll(sel + ' > .warning')).map((w) => {
  const d = w.querySelector(':scope > div'); return (d ? d.textContent : w.textContent).trim(); })"""


# The Profile targets editor (v0.3): single numbers, {min, max} ranges (protein, calcium) and the fiber goal.
READ_TARGET_FORM = """() => {
  const out = {};
  for (const i of document.querySelectorAll('input[data-target]')) out[i.dataset.target] = i.value;
  for (const i of document.querySelectorAll('input[data-range-min]')) out[i.dataset.rangeMin + '.min'] = i.value;
  for (const i of document.querySelectorAll('input[data-range-max]')) out[i.dataset.rangeMax + '.max'] = i.value;
  for (const i of document.querySelectorAll('input[data-target-goal]')) out[i.dataset.targetGoal + '.min'] = i.value;
  return out; }"""


def expected_target_form(form: dict, targets: dict) -> dict:
    """What the editor shows for a suggestion: numbers as typed, ranges split into their boxes."""
    out = {}
    for field in form:
        key, _, bound = field.partition(".")
        v = targets.get(key)
        if v is None:
            out[field] = ""
        elif isinstance(v, dict):
            out[field] = "" if v.get(bound or "max") is None else str(v.get(bound or "max"))
        else:
            out[field] = "" if bound == "min" else str(v)
    return out


def ui_warnings(page, sel: str) -> list[str]:
    """Rendered warnings; the 'No warnings.' placeholder (shown when the list is empty) reads as []."""
    out = page.evaluate(READ_WARNINGS, sel)
    return [] if len(out) == 1 and out[0].startswith("No warnings.") else out


def ui_key_numbers(page) -> list[str]:
    return page.evaluate("() => Array.from(document.querySelectorAll('#entry-preview-key .kn-v')).map((e) => e.textContent)")


def wait_toast(page, text: str, timeout: int = 6000) -> bool:
    try:
        page.wait_for_function("(t) => (document.getElementById('toast').textContent || '').includes(t)", arg=text, timeout=timeout)
        return True
    except Exception:
        return False


def toast_text(page) -> str:
    return page.eval_on_selector("#toast", "e => e.textContent")


def shot(page, cfg: str, name: str, full: bool = False) -> str:
    p = SHOTS / f"{cfg}_{name}.png"
    page.screenshot(path=str(p), full_page=full)
    return str(p)


def go_tab(page, view: str) -> None:
    page.click(f"#tab-{view}")
    page.wait_for_selector(f"#view-{view}:not([hidden])")


def is_api(r, method: str, path: str, regex: bool = False) -> bool:
    if r.request.method != method:
        return False
    p = urlparse(r.url).path
    return bool(re.fullmatch(path, p)) if regex else p == path


def dialog_open(page, dlg_id: str) -> bool:
    return page.evaluate("(id) => !!document.getElementById(id).open", dlg_id)


def wait_dialog(page, dlg_id: str, open_: bool = True, timeout: int = 5000) -> bool:
    try:
        page.wait_for_function("([id, o]) => !!document.getElementById(id).open === o", arg=[dlg_id, open_], timeout=timeout)
        if open_:
            page.wait_for_timeout(120)  # openDialog() moves focus to the first field after 30 ms; type after that, as a person would
        return True
    except Exception:
        return False


def search_and_open(page, query: str, name: str) -> None:
    """Add view: search, wait for the server's answer, open the row whose title is exactly `name`."""
    go_tab(page, "add")
    with page.expect_response(lambda r: urlparse(r.url).path == "/api/foods" and parse_qs(urlparse(r.url).query).get("q", [""])[0] == query):
        page.fill("#food-search", query)
    page.wait_for_timeout(350)  # let the debounce settle so the list is not re-rendered under the click
    page.wait_for_function(
        """(n) => Array.from(document.querySelectorAll('#food-results .row-btn .row-title')).some((t) => t.firstChild && t.firstChild.textContent === n)""",
        arg=name, timeout=5000)
    idx = page.evaluate(
        """(n) => Array.from(document.querySelectorAll('#food-results .row-btn')).findIndex((b) => {
             const t = b.querySelector('.row-title'); return t && t.firstChild && t.firstChild.textContent === n; })""", name)
    page.locator("#food-results .row-btn").nth(idx).click()
    wait_dialog(page, "sheet-entry")
    page.wait_for_timeout(100)


def today_entry_titles(page) -> list[str]:
    return page.evaluate("""() => Array.from(document.querySelectorAll('#meals .row-btn .row-title')).map((t) => t.firstChild.textContent)""")


def click_today_entry(page, name: str):
    idx = page.evaluate(
        """(n) => Array.from(document.querySelectorAll('#meals .row-btn')).findIndex((b) => {
             const t = b.querySelector('.row-title'); return t && t.firstChild && t.firstChild.textContent === n; })""", name)
    if idx < 0:
        raise AssertionError(f"Today has no entry titled {name!r}")
    with page.expect_response(lambda r: is_api(r, "GET", r"/api/foods/\d+", regex=True)) as ri:
        page.locator("#meals .row-btn").nth(idx).click()
    wait_dialog(page, "sheet-entry")
    page.wait_for_function("() => !document.getElementById('entry-grams').disabled")
    page.wait_for_timeout(100)
    return ri.value


def day(date: str) -> dict:
    return sget(f"/api/log?date={date}").json()


def wait_day_render(page, timeout: int = 6000) -> None:
    page.wait_for_selector("#view-today:not([hidden])")
    page.wait_for_function("() => document.getElementById('meals').style.opacity === ''", timeout=timeout)


def contrast(c1: str, c2: str) -> float:
    def parse(c):
        nums = [float(x) for x in re.findall(r"[\d.]+", c)[:3]]
        return nums

    def lum(rgb):
        out = []
        for v in rgb:
            v = v / 255
            out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    a, b = lum(parse(c1)), lum(parse(c2))
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def confirm_row_metrics(page, scope_sel: str) -> dict:
    try:
        page.wait_for_function("(sel) => { const r = document.querySelector(sel + ' .confirm-row'); return r && document.activeElement === r.querySelector('.btn.danger-solid'); }",
                               arg=scope_sel, timeout=1500)
    except Exception:
        pass  # reported by the caller through `focused`
    return page.evaluate(
        """(sel) => {
          const scope = document.querySelector(sel);
          const row = scope && scope.querySelector('.confirm-row');
          if (!row) return null;
          const msg = row.querySelector('.confirm-msg');
          const ok = row.querySelector('.btn.danger-solid');
          const cancel = Array.from(row.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Cancel');
          const rr = row.getBoundingClientRect(), okr = ok.getBoundingClientRect(), cr = cancel.getBoundingClientRect();
          const cs = (e) => getComputedStyle(e);
          // the row's effective background (walk up while transparent)
          let bgEl = row, bg = cs(row).backgroundColor;
          while (bgEl && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) { bgEl = bgEl.parentElement; bg = bgEl ? cs(bgEl).backgroundColor : 'rgb(255,255,255)'; }
          return {
            text: msg.textContent, okText: ok.textContent, focused: document.activeElement === ok,
            msgColor: cs(msg).color, rowBg: bg, okColor: cs(ok).color, okBg: cs(ok).backgroundColor,
            row: [rr.left, rr.top, rr.right, rr.bottom], ok: [okr.left, okr.top, okr.right, okr.bottom], cancel: [cr.left, cr.top, cr.right, cr.bottom],
            okH: okr.height, cancelH: cr.height, vw: window.innerWidth, vh: window.innerHeight,
            rowOverflow: row.scrollWidth > row.clientWidth + 1,
          };
        }""", scope_sel)


def no_hscroll(page) -> tuple[bool, str]:
    sw, iw = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    return sw <= iw, f"scrollWidth {sw} > innerWidth {iw}"


# --------------------------------------------------------------------------- the flow
def run_config(pw_browser, cfg: str, w: int, h: int, scheme: str) -> None:
    A = cfg
    server = Server()
    health = server.start()
    check(A, "server healthz ok with builtin foods", health.get("status") == "ok" and health.get("foods", 0) > 300, str(health))
    ctx = pw_browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, accept_downloads=True,
                                 has_touch=w < 720, is_mobile=False, device_scale_factor=1)
    ctx.add_init_script(INIT_SCRIPT)
    page = ctx.new_page()
    rec = Recorder(page)
    today = None
    try:
        # ---------------------------------------------------------------- 1. first launch
        page.goto(BASE + "/", wait_until="load")
        check(A, "fresh server: the setup screen is shown first", page.wait_for_selector("#form-setup:not([hidden])", timeout=15000) is not None)
        check(A, "fresh server: tabs hidden before sign-in", not page.is_visible(".tabs") and not page.is_visible("#settings-open"))
        ui_setup(page, server)
        check(A, "setup in the page signs in and opens Today", page.is_visible("#view-today") and page.is_visible("#settings-open"))
        api_login()
        wait_day_render(page)
        page.wait_for_function("() => document.getElementById('status-bars').children.length > 0")
        today = page.evaluate("() => { const d = new Date(); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; }")
        flags = page.evaluate("""() => ({ mock: typeof window.__kdlMock, ev: typeof window.__kdlEvaluateWarnings,
             preview: typeof window.KDL_PREVIEW, search: location.search, foodsEl: Array.from(document.scripts).some((s) => s.id === 'kdl-foods'),
             pillHidden: document.getElementById('brand-pill').hidden, bannerHidden: document.getElementById('preview-banner').hidden,
             title: document.title })""")
        check(A, "real app: window.__kdlMock is not exposed", flags["mock"] == "undefined", str(flags))
        check(A, "real app: window.__kdlEvaluateWarnings is not exposed", flags["ev"] == "undefined", str(flags))
        check(A, "real app: no KDL_PREVIEW flag and no query string", flags["preview"] == "undefined" and flags["search"] == "", str(flags))
        check(A, "real app: no embedded kdl-foods element in served page", not flags["foodsEl"], str(flags))
        check(A, "real app: Preview pill and preview banner hidden", flags["pillHidden"] and flags["bannerHidden"]
              and not page.is_visible("#brand-pill") and not page.is_visible("#preview-banner"), str(flags))
        check(A, "first launch: Today shows 'No targets set yet'", "No targets set yet" in page.inner_text("#status-bars"), page.inner_text("#status-bars"))
        check(A, "first launch: no entries", today_entry_titles(page) == [], str(today_entry_titles(page)))
        dark = page.evaluate("() => { const c = getComputedStyle(document.body).backgroundColor.match(/\\d+/g).map(Number); return (c[0] + c[1] + c[2]) / 3 < 80; }")
        check(A, f"theme follows prefers-color-scheme={scheme}", dark == (scheme == "dark"),
              page.evaluate("() => getComputedStyle(document.body).backgroundColor"))
        ok, d = no_hscroll(page)
        check(A, "no horizontal scroll on Today (first launch)", ok, d)
        shot(page, A, "01-first-launch")

        # ---------------------------------------------------------------- 2. profile
        go_tab(page, "profile")
        page.wait_for_timeout(200)
        check(A, "first launch: Profile has no 'Last saved'", page.inner_text("#profile-saved").strip() == "", page.inner_text("#profile-saved"))
        shot(page, A, "02-profile-empty")
        page.fill("#pf-name", "Alex Regress")
        page.fill("#pf-weight", "70")
        page.fill("#pf-height", "175")
        page.select_option("#pf-stage", "3b")
        page.select_option("#pf-dialysis", "none")
        page.select_option("#pf-diabetes", "type1")
        n_sugg = len(rec.calls("GET", "/api/profile/suggested-targets"))
        page.click("#btn-suggest")
        check(A, "Suggest before saving: client-side 'Save profile first' message, no server call",
              wait_toast(page, "Save profile first") and len(rec.calls("GET", "/api/profile/suggested-targets")) == n_sugg, toast_text(page))
        with page.expect_response(lambda r: is_api(r, "PUT", "/api/profile")) as ri:
            page.click("#btn-save-profile")
        check(A, "Save profile: PUT /api/profile 200", ri.value.status == 200, str(ri.value.status))
        wait_toast(page, "Profile saved")
        with page.expect_response(lambda r: is_api(r, "GET", "/api/profile/suggested-targets")) as ri:
            page.click("#btn-suggest")
        sugg = ri.value.json()
        check(A, "Suggest targets: GET suggested-targets 200", ri.value.status == 200, str(ri.value.status))
        page.wait_for_selector("#suggest-notes:not([hidden])")
        form = page.evaluate(READ_TARGET_FORM)
        t = sugg["targets"]
        exp_form = expected_target_form(form, t)
        norm = lambda d: {k: (str(float(v)) if v not in ("", None) else "") for k, v in d.items()}
        check(A, "Suggest targets fills the form with the server's numbers (not saved yet)", norm(form) == norm(exp_form), f"form={form} expected={exp_form}")
        check(A, "Suggested targets for 70 kg / 175 cm / 3b / type 1 match note 05 (0.8 g/kg protein floor, fiber goal)",
              t == {"calories_kcal": 2100, "protein_g": {"min": 56, "max": 56}, "carbs_g": 236, "carbs_per_meal_g": 60, "fiber_g": {"min": 29},
                    "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": None}, str(t))
        notes_text = page.inner_text("#suggest-notes")
        n_why = page.locator("#suggest-notes details.why").count()
        check(A, "Suggestion explains every target ('Why this number?' per target, protein 'about 56 g/day')",
              n_why >= 9 and "about 56 g/day" in notes_text, f"{n_why} disclosures; {notes_text[:300]!r}")
        page.locator("#suggest-notes details.why").first.click()
        check(A, "'Why this number?' shows the rule, its source and grade",
              "Rule E-2" in page.inner_text("#suggest-notes") and "Grade:" in page.inner_text("#suggest-notes"), page.inner_text("#suggest-notes")[:400])
        check(A, "Missing inputs are offered (birth month, sex, activity)",
              all(w in notes_text.lower() for w in ("your birth month", "the sex used in formulas", "your activity")), notes_text[-400:])
        shot(page, A, "03-profile-suggested")
        with page.expect_response(lambda r: is_api(r, "PUT", "/api/profile")) as ri:
            page.click("#btn-save-profile")
        body = json.loads(ri.value.request.post_data)
        prof = sget("/api/profile").json()
        # A range keeps its absent bound as null on the server ({"min": 29} reads back {"min": 29.0, "max": null}).
        bare = lambda d: {k: ({b: x for b, x in v.items() if x is not None} if isinstance(v, dict) else v) for k, v in d.items() if v is not None}  # noqa: E731
        stored = bare(prof["targets"])
        check(A, "Save profile with suggested targets: server stores them", ri.value.status == 200 and stored == bare(t),
              f"stored={stored} suggested={t} body={body.get('targets')}")
        check(A, "Profile name / weight / height saved", prof["name"] == "Alex Regress" and prof["weight_kg"] == 70 and prof["height_cm"] == 175, str(prof))
        page.wait_for_function("() => document.getElementById('profile-saved').textContent.includes('Last saved')")
        check(A, "'Last saved' appears after saving", "Last saved" in page.inner_text("#profile-saved"))

        # ---------------------------------------------------------------- 2b. about you (v0.3, note 05 §4.2)
        page.fill("#pf-birth-month", "1960-05")
        page.select_option("#pf-sex", "female")
        page.check("#pf-act-low_active")
        with page.expect_response(lambda r: is_api(r, "PUT", "/api/profile")) as ri:
            page.click("#btn-save-profile")
        body = json.loads(ri.value.request.post_data)
        check(A, "About you: PUT carries birth month, sex and activity",
              ri.value.status == 200 and body.get("birth_month") == "1960-05" and body.get("sex") == "female" and body.get("activity") == "low_active", str(body)[:300])
        with page.expect_response(lambda r: is_api(r, "GET", "/api/profile/suggested-targets")) as ri:
            page.click("#btn-suggest")
        sugg2 = ri.value.json()
        page.wait_for_selector("#suggest-notes:not([hidden])")
        notes_text = page.inner_text("#suggest-notes")
        check(A, "Age 66 raises protein to 0.8-1.0 g/kg and the change list says so",
              sugg2["targets"]["protein_g"] == {"min": 56, "max": 70} and "about 56 g/day → 56–70 g/day" in notes_text, notes_text[:500])
        check(A, "Opinion rules carry the 'Expert opinion' badge", page.locator("#suggest-notes .badge.opinion").count() >= 1)
        shot(page, A, "03b-profile-personal", full=True)
        go_tab(page, "today")  # leave without saving the second suggestion: the saved targets stay
        go_tab(page, "profile")
        page.wait_for_timeout(300)
        check(A, "Unsaved suggestion is dropped when Profile is shown again", page.input_value("#tg-protein_min") == "56" and page.input_value("#tg-protein_max") == "56",
              f"{page.input_value('#tg-protein_min')}–{page.input_value('#tg-protein_max')}")

        # ---------------------------------------------------------------- 2c. lab results (note 05 §4.8)
        page.click("#pf-open-labs")
        page.wait_for_selector("#view-labs:not([hidden])")
        page.wait_for_timeout(300)
        page.select_option("#lab-analyte", "phosphate")
        page.select_option("#lab-unit", "mmol/L")
        page.fill("#lab-value", "1.94")
        check(A, "Lab entry echoes the conversion before saving", "1.94 mmol/L = 6.0 mg/dL" in page.inner_text("#lab-echo"), page.inner_text("#lab-echo"))
        with page.expect_response(lambda r: is_api(r, "POST", "/api/labs")) as ri:
            page.click("#lab-save")
        lab = ri.value.json()
        check(A, "Save result: POST /api/labs 201 stores 6.0 mg/dL", ri.value.status == 201 and lab["value"] == 6.0 and lab["entered_unit"] == "mmol/L", str(lab)[:200])
        page.wait_for_selector("#labs-review:not([hidden])")
        review = page.inner_text("#labs-review")
        check(A, "What it changed: phosphorus 1,000 → 800 mg/day (never applied)", "Phosphorus: 1,000 mg/day → 800 mg/day" in review, review)
        page.select_option("#lab-analyte", "creatinine")
        page.select_option("#lab-unit", "mg/dL")
        page.fill("#lab-value", "1.2")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/labs")) as ri:
            page.click("#lab-save")
        page.wait_for_selector("#kf-body .kf-tile")
        kf = sget("/api/labs/kidney-function").json()
        check(A, "Kidney-function card shows the server's eGFR message", kf["message"] in page.inner_text("#kf-body") and kf["egfr"] is not None, f"{kf['message']!r}")
        page.select_option("#lab-analyte", "potassium")
        page.fill("#lab-value", "6.3")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/labs")) as ri:
            page.click("#lab-save")
        alerts = ri.value.json().get("alerts", [])
        page.wait_for_selector("#labs-alert .lab-alert.level-urgent")
        check(A, "Potassium 6.3: the server's urgent alert is shown as a red banner",
              alerts and alerts[0]["level"] == "urgent" and alerts[0]["message"] in page.inner_text("#labs-alert"), str(alerts)[:300])
        ok, d = no_hscroll(page)
        check(A, "no horizontal scroll on Lab results", ok, d)
        shot(page, A, "03c-labs", full=True)
        page.locator("#labs-history .labs-group[aria-label='Potassium'] .lab-row-actions button").first.click()
        with page.expect_response(lambda r: is_api(r, "DELETE", r"/api/labs/\d+$", regex=True)) as ri:
            page.locator("#labs-history .confirm-row .btn.danger-solid").click()
        check(A, "Delete result: DELETE /api/labs/{id} 204 and the banner goes", ri.value.status == 204
              and page.wait_for_function("() => !document.querySelector('#labs-alert .lab-alert')") is not None, str(ri.value.status))
        page.click("#labs-back")
        page.wait_for_selector("#view-profile:not([hidden])")
        page.wait_for_selector("#targets-review:not([hidden])")
        check(A, "Profile offers 'Review suggested targets' after the phosphate result", "Phosphorus" in page.inner_text("#targets-review"), page.inner_text("#targets-review"))
        page.click("#targets-review-dismiss")

        # ---------------------------------------------------------------- 3. add four foods
        # (a) Milk, whole x 2.5 servings, breakfast: live warning preview must equal the saved entry's warnings
        search_and_open(page, "milk whole", "Milk, whole")
        page.click('label[for="meal-breakfast"]')
        page.click('label[for="status-eaten"]')
        page.fill("#entry-servings", "2.5")
        page.wait_for_timeout(150)
        prev_w = ui_warnings(page, "#entry-warnings")
        prev_k = ui_key_numbers(page)
        shot(page, A, "04-add-sheet-2.5-servings")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log")) as ri:
            page.click("#entry-save")
        e_milk = ri.value.json()
        b = json.loads(ri.value.request.post_data)
        check(A, "Add 2.5 servings: POST /api/log 201 with servings 2.5 and no grams", ri.value.status == 201 and b.get("servings") == 2.5 and "grams" not in b and b.get("status") == "eaten", f"{ri.value.status} {b}")
        exp_w = expected_warning_texts(e_milk["warnings"])
        check(A, "2.5 servings: live warning preview == server warnings for the saved entry", prev_w == exp_w, f"preview={prev_w} server={exp_w}")
        exp_k = [fmt_num(e_milk["nutrients"][k], k) for k in KEY_NUMBERS]
        check(A, "2.5 servings: 'For this amount' key numbers == saved entry", prev_k == exp_k, f"preview={prev_k} server={exp_k}")
        wait_toast(page, "Added Milk, whole to breakfast")
        wait_day_render(page)

        # (b) Rice by grams (150 g), lunch
        search_and_open(page, "rice white long", "Rice, white, long-grain, cooked")
        page.click('label[for="meal-lunch"]')
        page.fill("#entry-grams", "150")
        page.wait_for_timeout(150)
        prev_w = ui_warnings(page, "#entry-warnings")
        prev_k = ui_key_numbers(page)
        sv_box = page.input_value("#entry-servings")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log")) as ri:
            page.click("#entry-save")
        e_rice = ri.value.json()
        b = json.loads(ri.value.request.post_data)
        check(A, "Add by grams: POST body carries grams 150", ri.value.status == 201 and b.get("grams") == 150, str(b))
        check(A, "Add by grams: entry grams 150, servings = 150/158", e_rice["grams"] == 150 and abs(e_rice["servings"] - round(150 / 158, 3)) < 1e-9,
              f"grams={e_rice['grams']} servings={e_rice['servings']} (box showed {sv_box})")
        check(A, "Add by grams: live warning preview == server warnings", prev_w == expected_warning_texts(e_rice["warnings"]),
              f"preview={prev_w} server={expected_warning_texts(e_rice['warnings'])}")
        check(A, "Add by grams: key numbers == saved entry", prev_k == [fmt_num(e_rice["nutrients"][k], k) for k in KEY_NUMBERS],
              f"preview={prev_k} server={[fmt_num(e_rice['nutrients'][k], k) for k in KEY_NUMBERS]}")
        wait_toast(page, "Added Rice")
        wait_day_render(page)

        # (c) Bread planned, dinner
        search_and_open(page, "bread white", "Bread, white")
        page.click('label[for="meal-dinner"]')
        page.click('label[for="status-planned"]')
        page.wait_for_timeout(100)
        title, cta = page.inner_text("#sheet-entry-title"), page.inner_text("#entry-save")
        check(A, "Planned toggle: sheet titled 'Plan food', button 'Plan for dinner'", title == "Plan food" and cta == "Plan for dinner", f"{title!r} / {cta!r}")
        shot(page, A, "05-add-sheet-planned")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log")) as ri:
            page.click("#entry-save")
        e_bread = ri.value.json()
        check(A, "Planned add: POST status planned, entry status planned", json.loads(ri.value.request.post_data).get("status") == "planned" and e_bread["status"] == "planned", str(e_bread.get("status")))
        wait_toast(page, "Planned Bread, white for dinner")
        wait_day_render(page)

        # (d) Blueberries, 1 serving, snack
        search_and_open(page, "blueberries", "Blueberries, raw")
        page.click('label[for="meal-snack"]')
        page.click('label[for="status-eaten"]')
        page.wait_for_timeout(100)
        prev1 = ui_warnings(page, "#entry-warnings")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log")) as ri:
            page.click("#entry-save")
        e_blue = ri.value.json()
        lv = lambda texts: [t.split(". ", 1)[0] for t in texts]
        check(A, "1 serving: preview warning levels == server entry levels", lv(prev1) == lv(expected_warning_texts(e_blue["warnings"])),
              f"preview={prev1} server={expected_warning_texts(e_blue['warnings'])}")
        wait_toast(page, "Added Blueberries")
        wait_day_render(page)
        titles = today_entry_titles(page)
        check(A, "Today lists the 4 added foods", sorted(titles) == sorted(["Milk, whole", "Rice, white, long-grain, cooked", "Bread, white", "Blueberries, raw"]), str(titles))
        check(A, "Planned entry rendered with planned badge and Eaten button", page.locator("#meals li.entry-planned .eaten-btn").count() == 1)
        shot(page, A, "06-today-4-foods", full=True)

        # ---------------------------------------------------------------- 4. mark planned eaten
        with page.expect_response(lambda r: is_api(r, "PUT", rf"/api/log/{e_bread['id']}", regex=True)) as ri:
            page.click("#meals li.entry-planned .eaten-btn")
        check(A, "Mark eaten: PUT /api/log/{id} {status: eaten} 200", ri.value.status == 200 and json.loads(ri.value.request.post_data) == {"status": "eaten"}, ri.value.request.post_data)
        wait_toast(page, "marked as eaten")
        page.wait_for_function("() => document.querySelectorAll('#meals li.entry-planned').length === 0")
        srv = {e["id"]: e for e in day(today)["entries"]}
        check(A, "Mark eaten: server entry status eaten, UI has no planned rows", srv[e_bread["id"]]["status"] == "eaten")

        # ---------------------------------------------------------------- 5. edit servings
        click_today_entry(page, "Blueberries, raw")
        check(A, "Edit sheet opens in edit mode", page.get_attribute("#sheet-entry", "data-mode") == "edit" and page.inner_text("#sheet-entry-title") == "Edit entry")
        page.fill("#entry-servings", "3")
        page.wait_for_timeout(150)
        prev_w = ui_warnings(page, "#entry-warnings")
        with page.expect_response(lambda r: is_api(r, "PUT", rf"/api/log/{e_blue['id']}", regex=True)) as ri:
            page.click("#entry-save")
        e_blue2 = ri.value.json()
        b = json.loads(ri.value.request.post_data)
        check(A, "Edit servings: PUT body servings 3 -> entry servings 3", ri.value.status == 200 and b.get("servings") == 3 and e_blue2["servings"] == 3, f"{b} -> {e_blue2.get('servings')}")
        check(A, "Edit servings: live warning preview == server warnings", prev_w == expected_warning_texts(e_blue2["warnings"]),
              f"preview={prev_w} server={expected_warning_texts(e_blue2['warnings'])}")
        wait_toast(page, "Entry updated")
        wait_day_render(page)
        page.wait_for_function("() => Array.from(document.querySelectorAll('#meals .row-btn')).some((b) => b.textContent.includes('Blueberries, raw') && b.textContent.includes('3 servings'))")
        check(A, "Today shows '3 servings' for the edited entry", True)

        # ---------------------------------------------------------------- 6. quick add (creates the custom food)
        go_tab(page, "add")
        page.click("#btn-quick")
        wait_dialog(page, "sheet-quick")
        page.fill("#q-name", "Regress rice cakes")
        page.fill("#q-serving-desc", "2 cakes")
        page.fill("#q-serving-g", "18")
        page.click('label[for="qmeal-snack"]')
        page.fill("#q-servings", "2")
        for k, v in {"calories_kcal": "70", "carbs_g": "14.6", "protein_g": "1.4", "sodium_mg": "40", "potassium_mg": "58", "phosphorus_mg": "70"}.items():
            page.fill(f"#qn-{k}", v)
        page.wait_for_timeout(150)
        q_prev = ui_warnings(page, "#quick-warnings")
        shot(page, A, "07-quick-add")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log/quick")) as ri:
            page.click("#quick-save")
        e_quick = ri.value.json()
        check(A, "Quick add: POST /api/log/quick 201", ri.value.status == 201 and e_quick["food_name"] == "Regress rice cakes", f"{ri.value.status} {e_quick.get('food_name')}")
        check(A, "Quick add: live warning preview == server warnings", q_prev == expected_warning_texts(e_quick["warnings"]),
              f"preview={q_prev} server={expected_warning_texts(e_quick['warnings'])}")
        wait_toast(page, "Logged Regress rice cakes to snack")
        wait_day_render(page)
        check(A, "Quick add: entry visible in Today", "Regress rice cakes" in today_entry_titles(page), str(today_entry_titles(page)))
        custom_food_id = e_quick["food_id"]

        # ---------------------------------------------------------------- 6b. USDA without a key: the real-app message
        go_tab(page, "add")
        page.click("#btn-usda")
        wait_dialog(page, "sheet-usda")
        check(A, "USDA sheet opens without the preview's notice in the real app", page.inner_text("#usda-status").strip() == "", page.inner_text("#usda-status"))
        page.fill("#usda-q", "apple")
        with page.expect_response(lambda r: is_api(r, "GET", "/api/foods/usda/search")) as ri:
            page.click("#usda-go")
        page.wait_for_function("() => document.getElementById('usda-status').textContent.length > 30")
        ust = page.inner_text("#usda-status")
        reason = (ri.value.json() or {}).get("reason")
        check(A, "USDA without a key: server 503 not_configured -> the server's 'add a key in Settings' text (not the preview text)",
              ri.value.status == 503 and reason == "not_configured" and "No USDA key is set up" in ust and "Settings" in ust
              and "preview" not in ust.lower(), f"{ri.value.status} {reason} {ust!r}")
        page.click("#sheet-usda .sheet-head [data-close]")
        wait_dialog(page, "sheet-usda", False)
        go_tab(page, "today")
        wait_day_render(page)

        # ---------------------------------------------------------------- 6c. a confirm row must not survive closing its sheet
        n_del = len(rec.calls("DELETE", "/api/log/"))
        click_today_entry(page, "Milk, whole")
        page.click("#entry-delete")
        page.wait_for_selector("#sheet-entry .confirm-row")
        page.click("#sheet-entry .sheet-head [data-close]")
        wait_dialog(page, "sheet-entry", False)
        click_today_entry(page, "Rice, white, long-grain, cooked")
        st = page.evaluate("""() => ({ row: !!document.querySelector('#sheet-entry .confirm-row'),
             footHidden: document.querySelector('#sheet-entry .sheet-foot').hidden,
             saveVisible: !!document.getElementById('entry-save').offsetParent, deleteVisible: !!document.getElementById('entry-delete').offsetParent })""")
        check(A, "Closing a sheet with an open confirm row restores its footer for the next entry (no DELETE sent)",
              not st["row"] and not st["footHidden"] and st["saveVisible"] and st["deleteVisible"] and len(rec.calls("DELETE", "/api/log/")) == n_del, str(st))
        page.click("#sheet-entry .sheet-head [data-close]")
        wait_dialog(page, "sheet-entry", False)

        # ---------------------------------------------------------------- 7. delete an entry (in-page confirmation)
        click_today_entry(page, "Milk, whole")
        n_del = len(rec.calls("DELETE", "/api/log/"))
        page.click("#entry-delete")
        page.wait_for_selector("#sheet-entry .confirm-row")
        m = confirm_row_metrics(page, "#sheet-entry")
        orig_foot_hidden = page.evaluate("() => document.querySelector('#sheet-entry .sheet-foot:not(.confirm-row)').hidden")
        check(A, "Delete entry: in-page confirm row replaces the sheet footer", orig_foot_hidden and m is not None, str(m))
        check(A, "Delete entry: confirm names the food and meal; focus on 'Delete entry'",
              m["text"].startswith("Delete Milk, whole from breakfast") and m["okText"] == "Delete entry" and m["focused"], str(m))
        check(A, "Delete entry: no window.confirm/alert dialog", rec.dialogs == [], str(rec.dialogs))
        check(A, "Confirm row: message contrast >= 4.5", contrast(m["msgColor"], m["rowBg"]) >= 4.5, f"{m['msgColor']} on {m['rowBg']} = {contrast(m['msgColor'], m['rowBg']):.2f}")
        check(A, "Confirm row: 'Delete entry' button contrast >= 4.5", contrast(m["okColor"], m["okBg"]) >= 4.5, f"{m['okColor']} on {m['okBg']} = {contrast(m['okColor'], m['okBg']):.2f}")
        check(A, "Confirm row: buttons inside the viewport, no overflow",
              m["ok"][2] <= m["vw"] + 0.5 and m["ok"][3] <= m["vh"] + 0.5 and m["cancel"][0] >= 0 and not m["rowOverflow"], str(m))
        if w < 720:
            check(A, "Confirm row: buttons >= 44 px tall on phone", m["okH"] >= 44 and m["cancelH"] >= 44, f"ok {m['okH']} cancel {m['cancelH']}")
        shot(page, A, "08-confirm-delete-entry")
        # Cancel puts the footer back and sends nothing
        page.click("#sheet-entry .confirm-row >> text=Cancel")
        page.wait_for_timeout(100)
        st = page.evaluate("() => ({ row: !!document.querySelector('#sheet-entry .confirm-row'), footHidden: document.querySelector('#sheet-entry .sheet-foot').hidden, focus: document.activeElement && document.activeElement.id })")
        check(A, "Confirm Cancel: row removed, footer back, focus on Delete, no DELETE sent",
              not st["row"] and not st["footHidden"] and st["focus"] == "entry-delete" and len(rec.calls("DELETE", "/api/log/")) == n_del, str(st))
        # Escape closes only the confirm row
        page.click("#entry-delete")
        page.wait_for_selector("#sheet-entry .confirm-row")
        page.wait_for_timeout(50)
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        st = page.evaluate("() => ({ row: !!document.querySelector('#sheet-entry .confirm-row'), open: document.getElementById('sheet-entry').open, focus: document.activeElement && document.activeElement.id })")
        check(A, "Confirm Escape: row closes, sheet stays open, no DELETE sent", not st["row"] and st["open"] and len(rec.calls("DELETE", "/api/log/")) == n_del, str(st))
        if not st["open"]:
            click_today_entry(page, "Milk, whole")
        # Confirm
        page.click("#entry-delete")
        page.wait_for_selector("#sheet-entry .confirm-row")
        with page.expect_response(lambda r: is_api(r, "DELETE", rf"/api/log/{e_milk['id']}", regex=True)) as ri:
            page.click("#sheet-entry .confirm-row .btn.danger-solid")
        check(A, "Delete entry: DELETE /api/log/{id} reached the server (204)", ri.value.status == 204, str(ri.value.status))
        check(A, "Delete entry: sheet closes, toast", wait_dialog(page, "sheet-entry", False) and wait_toast(page, "Entry deleted"), toast_text(page))
        page.wait_for_function("() => !Array.from(document.querySelectorAll('#meals .row-title')).some((t) => t.firstChild.textContent === 'Milk, whole')")
        srv_ids = [e["id"] for e in day(today)["entries"]]
        check(A, "Delete entry: gone from the UI and from the server", e_milk["id"] not in srv_ids and "Milk, whole" not in today_entry_titles(page), str(srv_ids))

        # ---------------------------------------------------------------- 8. delete a custom food (in-page confirmation)
        search_and_open(page, "Regress rice", "Regress rice cakes")
        check(A, "Custom food: 'Delete food' button shown in the add sheet", page.is_visible("#entry-delete-food"))
        check(A, "Builtin-only button state: entry Delete hidden in add mode", not page.is_visible("#entry-delete"))
        page.click("#entry-delete-food")
        page.wait_for_selector("#sheet-entry .confirm-row")
        m = confirm_row_metrics(page, "#sheet-entry")
        check(A, "Delete food: confirm text names the food, focus on 'Delete food'",
              m["text"].startswith('Delete the food "Regress rice cakes"') and m["okText"] == "Delete food" and m["focused"], str(m))
        shot(page, A, "09-confirm-delete-food")
        with page.expect_response(lambda r: is_api(r, "DELETE", rf"/api/foods/{custom_food_id}", regex=True)) as ri:
            with page.expect_response(lambda r: urlparse(r.url).path == "/api/foods" and parse_qs(urlparse(r.url).query).get("q", [""])[0] == "Regress rice"):
                page.dblclick("#sheet-entry .confirm-row .btn.danger-solid")  # a double tap must not send two DELETEs
        check(A, "Delete food: DELETE /api/foods/{id} reached the server (204)", ri.value.status == 204, str(ri.value.status))
        page.wait_for_timeout(300)
        check(A, "Double tap on the confirm button sends exactly one DELETE", len(rec.calls("DELETE", f"/api/foods/{custom_food_id}", exact=True)) == 1,
              str(rec.calls("DELETE", f"/api/foods/{custom_food_id}", exact=True)))
        check(A, "Delete food: sheet closes, toast", wait_dialog(page, "sheet-entry", False) and wait_toast(page, "Food deleted"), toast_text(page))
        page.wait_for_timeout(200)
        res_titles = page.evaluate("() => Array.from(document.querySelectorAll('#food-results .row-title')).map((t) => t.firstChild.textContent)")
        fsrv = sget(f"/api/foods/{custom_food_id}").json()
        check(A, "Delete food: search re-ran and no longer lists it; server hid it (still referenced)",
              "Regress rice cakes" not in res_titles and fsrv.get("hidden") is True, f"results={res_titles} server hidden={fsrv.get('hidden')}")

        # ---------------------------------------------------------------- 9. saved meals: create from log, delete from list and from editor
        go_tab(page, "today")
        wait_day_render(page)
        for meal_key, name in (("lunch", "Regress lunch"), ("dinner", "Regress dinner")):
            page.locator(f"#meals section.meal:has(#meal-h-{meal_key}) .meal-actions button", has_text="Save as meal").click()
            wait_dialog(page, "sheet-savemeal")
            page.fill("#savemeal-name", name)
            with page.expect_response(lambda r: is_api(r, "POST", "/api/meals/from-log")) as ri:
                page.click("#savemeal-save")
            check(A, f"Save as meal ({meal_key}): POST /api/meals/from-log 201", ri.value.status == 201, str(ri.value.status))
            wait_dialog(page, "sheet-savemeal", False)
        meals_srv = {m_["name"]: m_["id"] for m_ in sget("/api/meals").json()["meals"]}
        go_tab(page, "plan")
        page.wait_for_function("() => document.querySelectorAll('#saved-meals li.saved-meal').length === 2", timeout=6000)
        page.wait_for_function("() => document.querySelectorAll('#plan-grid > *').length === 7")
        check(A, "Plan view: 7 day cards, 2 saved meals", True)
        ok, d = no_hscroll(page)
        check(A, "no horizontal scroll on Plan", ok, d)
        shot(page, A, "10-plan", full=True)
        # apply a saved meal to today as planned -> shopping list
        page.locator("#saved-meals li.saved-meal", has_text="Regress dinner").locator("button", has_text="Add to a day").click()
        wait_dialog(page, "sheet-apply")
        page.click('label[for="ameal-dinner"]')
        page.click('label[for="astatus-planned"]')
        with page.expect_response(lambda r: is_api(r, "POST", rf"/api/meals/{meals_srv['Regress dinner']}/apply", regex=True)) as ri:
            page.click("#apply-save")
        ap = ri.value.json()
        check(A, "Apply saved meal: POST /api/meals/{id}/apply 201 -> planned entries", ri.value.status == 201 and ap["entries"] and all(e_["status"] == "planned" for e_ in ap["entries"]),
              f"{ri.value.status} {[(e_['food_name'], e_['status']) for e_ in ap.get('entries', [])]}")
        try:
            page.wait_for_function("() => document.getElementById('shopping-list').textContent.includes('Bread, white')", timeout=6000)
            shop_ok = True
        except Exception:
            shop_ok = False
        check(A, "Shopping list shows the planned food for this week", shop_ok, page.inner_text("#shopping-list")[:200])
        # copy today to tomorrow as planned
        tomorrow = page.evaluate("(t) => { const d = new Date(t + 'T00:00:00'); d.setDate(d.getDate() + 1); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; }", today)
        page.click("#btn-copy-day")
        wait_dialog(page, "sheet-copy")
        check(A, "Copy day sheet defaults: from today to tomorrow", page.input_value("#copy-from") == today and page.input_value("#copy-to") == tomorrow,
              f"{page.input_value('#copy-from')} -> {page.input_value('#copy-to')}")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log/copy-day")) as ri:
            page.click("#copy-save")
        cp = ri.value.json()
        n_today = len(day(today)["entries"])
        tm = day(tomorrow)
        check(A, "Copy day: POST /api/log/copy-day copies every entry to tomorrow as planned",
              ri.value.status < 300 and cp["created"] == n_today == tm["counts"]["planned"], f"{ri.value.status} created={cp.get('created')} today={n_today} tomorrow={tm['counts']}")
        wait_dialog(page, "sheet-copy", False)
        page.wait_for_timeout(400)
        shot(page, A, "10b-plan-after-apply-copy", full=True)
        # delete from the list row
        page.click('button[aria-label="Delete saved meal Regress lunch"]')
        page.wait_for_selector("#saved-meals .confirm-row")
        m = confirm_row_metrics(page, "#saved-meals")
        host_hidden = page.evaluate("() => document.querySelector('#saved-meals .confirm-row').previousElementSibling.hidden")
        check(A, "Delete saved meal (list): confirm row replaces the actions, names the meal, focus on 'Delete meal'",
              host_hidden and m["text"].startswith('Delete the saved meal "Regress lunch"') and m["okText"] == "Delete meal" and m["focused"], str(m))
        check(A, "Saved-meal confirm row: inside viewport, no overflow", m["ok"][2] <= m["vw"] + 0.5 and not m["rowOverflow"], str(m))
        page.locator("#saved-meals .confirm-row").scroll_into_view_if_needed()
        shot(page, A, "11-confirm-delete-saved-meal")
        with page.expect_response(lambda r: is_api(r, "DELETE", rf"/api/meals/{meals_srv['Regress lunch']}", regex=True)) as ri:
            page.click("#saved-meals .confirm-row .btn.danger-solid")
        check(A, "Delete saved meal (list): DELETE /api/meals/{id} reached the server (204)", ri.value.status == 204, str(ri.value.status))
        wait_toast(page, 'Saved meal "Regress lunch" deleted')
        page.wait_for_function("() => document.querySelectorAll('#saved-meals li.saved-meal').length === 1")
        check(A, "Delete saved meal (list): UI list and server updated", "Regress lunch" not in [m_["name"] for m_ in sget("/api/meals").json()["meals"]])
        # delete from the editor sheet
        page.locator("#saved-meals li.saved-meal .saved-meal-actions button", has_text="Edit").click()
        wait_dialog(page, "sheet-meal")
        check(A, "Meal editor: Delete button visible for an existing meal", page.is_visible("#meal-delete"))
        page.click("#meal-delete")
        page.wait_for_selector("#sheet-meal .confirm-row")
        m = confirm_row_metrics(page, "#sheet-meal")
        check(A, "Delete saved meal (editor): confirm in the sheet footer, focus on 'Delete meal'", m["okText"] == "Delete meal" and m["focused"], str(m))
        shot(page, A, "12-confirm-delete-meal-editor")
        with page.expect_response(lambda r: is_api(r, "DELETE", rf"/api/meals/{meals_srv['Regress dinner']}", regex=True)) as ri:
            page.click("#sheet-meal .confirm-row .btn.danger-solid")
        check(A, "Delete saved meal (editor): DELETE reached the server (204), sheet closes",
              ri.value.status == 204 and wait_dialog(page, "sheet-meal", False), str(ri.value.status))
        page.wait_for_function("() => document.querySelectorAll('#saved-meals li.saved-meal').length === 0")
        check(A, "Delete saved meal (editor): list shows the empty state, server has none",
              sget("/api/meals").json()["meals"] == [] and "No saved meals yet" in page.inner_text("#saved-meals"))
        check(A, "No window.confirm / alert dialogs during deletes", rec.dialogs == [], str(rec.dialogs))

        # ---------------------------------------------------------------- 10. trends + CSV
        with page.expect_response(lambda r: is_api(r, "GET", "/api/log/range")):
            go_tab(page, "trends")
        page.wait_for_function("() => document.getElementById('charts').children.length > 0")
        start14 = page.evaluate("(t) => { const d = new Date(t + 'T00:00:00'); d.setDate(d.getDate() - 13); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; }", today)
        attrs = page.evaluate("""() => { const a = document.getElementById('export-csv');
            return { href: a.getAttribute('href'), download: a.getAttribute('download'), role: a.getAttribute('role'), popup: a.getAttribute('aria-haspopup'), onclick: a.onclick === null }; }""")
        exp_href = f"/api/log/export.csv?start={start14}&end={today}"
        check(A, "Export CSV link points at /api/log/export.csv for the 14-day range", attrs["href"] == exp_href, f"{attrs} expected href {exp_href}")
        check(A, "Export CSV is a plain download link (download attr, no button role / dialog popup / click handler)",
              attrs["download"] == f"kidney-log_{start14}_{today}.csv" and attrs["role"] is None and attrs["popup"] is None and attrs["onclick"], str(attrs))
        r = page.request.get(BASE + attrs["href"])
        ctype = r.headers.get("content-type", "")
        check(A, "Export CSV href returns 200 text/csv as an attachment", r.status == 200 and ctype.startswith("text/csv") and "attachment" in r.headers.get("content-disposition", ""),
              f"{r.status} {ctype} {r.headers.get('content-disposition')}")
        rows = list(csv.reader(io.StringIO(r.text())))
        n_srv = len(day(today)["entries"])
        check(A, "CSV has a header and one row per entry", len(rows) - 1 == n_srv and rows[0][:4] == ["id", "date", "meal", "status"], f"rows={len(rows) - 1} entries={n_srv} header={rows[0][:6]}")
        with page.expect_download(timeout=8000) as dl:
            page.click("#export-csv")
        d_ = dl.value
        dpath = OUT / f"{A}_export.csv"
        d_.save_as(str(dpath))
        check(A, "Clicking Export CSV downloads a file (no CSV sheet)", d_.suggested_filename == f"kidney-log_{start14}_{today}.csv" and not dialog_open(page, "sheet-csv")
              and dpath.read_text().splitlines()[0].startswith("id,date,meal,status"), f"{d_.suggested_filename} sheet-csv open={dialog_open(page, 'sheet-csv')}")
        page.click('.segmented .seg[data-days="7"]')
        page.wait_for_timeout(300)
        start7 = page.evaluate("(t) => { const d = new Date(t + 'T00:00:00'); d.setDate(d.getDate() - 6); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; }", today)
        check(A, "Export CSV href follows the 7-day range", page.get_attribute("#export-csv", "href") == f"/api/log/export.csv?start={start7}&end={today}", page.get_attribute("#export-csv", "href"))
        ok, d = no_hscroll(page)
        check(A, "no horizontal scroll on Trends", ok, d)
        shot(page, A, "13-trends", full=True)

        # ---------------------------------------------------------------- 11. final Today + global checks
        go_tab(page, "today")
        wait_day_render(page)
        ok, d = no_hscroll(page)
        check(A, "no horizontal scroll on Today (with entries)", ok, d)
        shot(page, A, "14-today-final", full=True)
        go_tab(page, "add")
        page.fill("#food-search", "")
        page.wait_for_timeout(400)
        ok, d = no_hscroll(page)
        check(A, "no horizontal scroll on Add", ok, d)
        shot(page, A, "15-add")

        reg = page.evaluate("() => window.__regress")
        check(A, "real app never looked up the embedded foods element (getElementById / querySelector 'kdl-foods')",
              "kdl-foods" not in reg["getById"] and not reg["qs"], f"getById calls: {sorted(set(reg['getById']))} qs: {reg['qs']}")
        check(A, "sheet-csv never opened", not dialog_open(page, "sheet-csv"))
        external = [u for (_m, u, _b, _rt) in rec.requests if not (u.startswith(BASE) or u.startswith("data:") or u.startswith("blob:"))]
        check(A, "no requests leave the same origin", not external, str(external[:5]))
        bad = [x for x in rec.responses if x[2] >= 400 and not (urlparse(x[1]).path == "/api/foods/usda/search" and x[2] == 503)]
        check(A, "no HTTP error responses during the flow", not bad, str(bad))
        n503 = sum(1 for x in rec.responses if x[2] == 503)  # Chromium logs each expected USDA 503 as a console error
        errs = [c for c in rec.console if c[0] == "error"]
        errs = [c for c in errs if not c[1].startswith("Failed to load resource: the server responded with a status of 503")] + \
               [c for c in errs if c[1].startswith("Failed to load resource: the server responded with a status of 503")][n503:]
        check(A, "no console errors", not errs, str(errs[:5]))
        check(A, "no page errors", not rec.pageerrors, str(rec.pageerrors[:5]))
        got204 = {(m_, u) for (m_, u, st_) in rec.responses if st_ == 204}
        benign = [f for f in rec.failed if f[2] == "net::ERR_ABORTED" and (f[0], f[1]) in got204]
        real_failed = [f for f in rec.failed if f not in benign]
        if benign:
            info(A, "Chromium reports ERR_ABORTED for 204 DELETEs whose empty body app.js never reads (server answered 204 first; harmless)", str(len(benign)))
        check(A, "no failed requests", not real_failed, str(real_failed[:5]))
        check(A, "no window.confirm/alert/prompt dialogs at all", not rec.dialogs, str(rec.dialogs))

        # ---------------------------------------------------------------- 12. theme toggle persists
        want = "light" if scheme == "dark" else "dark"
        page.click("#theme-toggle")
        got = page.evaluate("() => [document.documentElement.getAttribute('data-theme'), localStorage.getItem('kdl-theme')]")
        page.reload()
        page.wait_for_selector("#view-add:not([hidden])")  # the hash (#add) brings the same view back
        page.wait_for_timeout(300)
        got2 = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
        check(A, f"Theme toggle switches to {want} and survives a reload", got == [want, want] and got2 == want, f"{got} after reload {got2}")
        shot(page, A, f"16-toggled-{want}")
    except Exception as exc:  # keep going with the other configs
        check(A, "flow completed without an exception", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
        try:
            shot(page, A, "zz-exception", full=True)
        except Exception:
            pass
    finally:
        server.stop()
        try:
            ctx.close()
        except Exception as exc:  # never let teardown leak the server or hide the summary
            info(A, "context close raised", f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- probes
def probe_embedded_json_ignored(pw_browser) -> None:
    """Serve the real index.html with a bogus <script id="kdl-foods"> injected: the real app must ignore it."""
    A = "probe-embedded"
    server = Server()
    server.start()
    server.admin_via_api()
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(INIT_SCRIPT)
    page = ctx.new_page()
    Recorder(page)  # listens for dialogs and requests
    bogus = {"version": "bogus", "source": "regress", "foods": [{"fdc_id": 999001, "name": "ZZEMBEDDED bogus food", "category": "Fruits",
             "serving_desc": "1 piece (10 g)", "serving_g": 10, "nutrients": {"potassium_mg": 1}, "flags": [], "kidney_notes": ""}]}

    def handler(route):
        resp = route.fetch()
        text = resp.text()
        first = re.search(r'<script src="(?:app\.js|js/engine/rules\.js)"></script>', text).group(0)
        html = text.replace(first, f'<script type="application/json" id="kdl-foods">{json.dumps(bogus)}</script>\n{first}', 1)
        route.fulfill(response=resp, body=html, headers={**resp.headers, "content-type": "text/html; charset=utf-8"})

    try:
        page.route(BASE + "/", handler)
        page.goto(BASE + "/")
        ui_sign_in(page)
        wait_day_render(page)
        check(A, "injected kdl-foods element is present in the page", page.evaluate("() => Array.from(document.scripts).some((s) => s.id === 'kdl-foods')"))
        go_tab(page, "add")
        with page.expect_response(lambda r: urlparse(r.url).path == "/api/foods" and parse_qs(urlparse(r.url).query).get("q", [""])[0] == "ZZEMBEDDED"):
            page.fill("#food-search", "ZZEMBEDDED")
        page.wait_for_timeout(400)
        txt = page.inner_text("#food-results")
        check(A, "with an embedded foods JSON present, search still goes to the server and ignores it",
              "ZZEMBEDDED bogus food" not in txt and "No foods match" in txt, txt[:200])
        reg = page.evaluate("() => window.__regress")
        app_lookups = [x for x in reg["getById"] if x == "kdl-foods"]
        check(A, "app.js did not read the embedded foods element", not app_lookups and not reg["qs"], f"kdl-foods lookups={len(app_lookups)} qs={reg['qs']}")
        check(A, "no mock hooks even with embedded data present", page.evaluate("() => typeof window.__kdlMock === 'undefined' && document.getElementById('brand-pill').hidden"))
    finally:
        server.stop()
        try:
            ctx.close()
        except Exception as exc:  # never let teardown leak the server or hide the summary
            info(A, "context close raised", f"{type(exc).__name__}: {exc}")


def probe_preview_parity(pw_browser, label: str) -> None:
    """Add-sheet live warnings vs server for (a) grams on a builtin food near a threshold and
    (b) 2.5 servings of a custom food whose label values are not whole numbers."""
    A = label
    chk = check
    server = Server()
    server.start()
    server.admin_via_api()
    ctx = pw_browser.new_context(viewport={"width": 375, "height": 812})
    page = ctx.new_page()
    try:
        API.json("PUT", "/api/profile", {"weight_kg": 70, "height_cm": 175})
        page.goto(BASE + "/")
        ui_sign_in(page)
        wait_day_render(page)
        # (a) Cantaloupe by weight: 367 g
        search_and_open(page, "cantaloupe", "Cantaloupe, raw")
        page.fill("#entry-grams", "367")
        page.wait_for_timeout(150)
        prev = ui_warnings(page, "#entry-warnings")
        prev_k = ui_key_numbers(page)
        shot(page, A, "grams-367-cantaloupe-preview")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log")) as ri:
            page.click("#entry-save")
        e = ri.value.json()
        chk(A, "grams 367 g cantaloupe: preview warnings == server warnings", prev == expected_warning_texts(e["warnings"]),
              f"preview={prev} server={expected_warning_texts(e['warnings'])}")
        chk(A, "grams 367 g cantaloupe: preview key numbers == server", prev_k == [fmt_num(e["nutrients"][k], k) for k in KEY_NUMBERS],
              f"preview={prev_k} server={[fmt_num(e['nutrients'][k], k) for k in KEY_NUMBERS]}")
        # (b) custom food with decimals (as typed from a label / imported from USDA), 2.5 servings
        food = API.json("POST", "/api/foods", {"name": "Probe granola bar", "serving_desc": "1 bar (40 g)", "serving_g": 40,
                          "nutrients": {"potassium_mg": 80.4, "phosphorus_mg": 40.3, "sodium_mg": 56.2, "carbs_g": 11.98, "protein_g": 5.98, "calories_kcal": 150}})
        info(A, "custom food as returned by GET /api/foods/{id}", f"nutrients K={food['nutrients']['potassium_mg']} P={food['nutrients']['phosphorus_mg']} Na={food['nutrients']['sodium_mg']} carbs={food['nutrients']['carbs_g']} protein={food['nutrients']['protein_g']} (stored 80.4 / 40.3 / 56.2 / 11.98 / 5.98)")
        search_and_open(page, "Probe granola", "Probe granola bar")
        page.fill("#entry-servings", "2.5")
        page.wait_for_timeout(150)
        prev = ui_warnings(page, "#entry-warnings")
        prev_k = ui_key_numbers(page)
        shot(page, A, "custom-2.5-preview")
        with page.expect_response(lambda r: is_api(r, "POST", "/api/log")) as ri:
            page.click("#entry-save")
        e = ri.value.json()
        chk(A, "2.5 servings of a custom food with decimal label values: preview warnings == server warnings",
              prev == expected_warning_texts(e["warnings"]), f"preview={prev} server={expected_warning_texts(e['warnings'])}")
        chk(A, "2.5 servings of a custom food: preview key numbers == server", prev_k == [fmt_num(e["nutrients"][k], k) for k in KEY_NUMBERS],
              f"preview={prev_k} server={[fmt_num(e['nutrients'][k], k) for k in KEY_NUMBERS]}")
    except Exception as exc:
        chk(A, "probe completed without an exception", False, f"{type(exc).__name__}: {exc}")
    finally:
        server.stop()
        try:
            ctx.close()
        except Exception as exc:  # never let teardown leak the server or hide the summary
            info(A, "context close raised", f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- static checks
def static_checks(run_pytest: bool) -> None:
    A = "static"
    js_files = sorted(str(p) for p in (REPO / "app/static").rglob("*.js")) or [str(REPO / "app/static/app.js")]
    bad = []
    for f in js_files:
        r = subprocess.run(["node", "--check", f], capture_output=True, text=True)
        if r.returncode:
            bad.append(f"{f}: {r.stderr.strip()[:300]}")
    check(A, f"node --check app/static/**/*.js ({len(js_files)} files)", not bad, "; ".join(bad))
    vec = REPO / "tests/js/run_vectors.mjs"
    if vec.exists():
        r = subprocess.run(["node", str(vec)], capture_output=True, text=True)
        check(A, "node tests/js/run_vectors.mjs", r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])
    if run_pytest:
        r = subprocess.run([sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider"], cwd=REPO, capture_output=True, text=True)
        tail = (r.stdout.strip().splitlines() or [""])[-1]
        check(A, "python -m pytest", r.returncode == 0, tail)
        info(A, "pytest summary", tail)
    st = subprocess.run(["git", "status", "--porcelain", "--", "app", "data", "tools/e2e"], cwd=REPO, capture_output=True, text=True).stdout
    info(A, "git status of app/, data/, tools/e2e/ (the harness must not change it)", st.strip().replace("\n", " | "))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pytest", action="store_true")
    ap.add_argument("--only", default=None, help="run one config, e.g. 375-light")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--port", type=int, default=PORT, help=f"uvicorn port (default {PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory for data, logs, screenshots (default {OUT})")
    args = ap.parse_args()
    configure(args.out.resolve(), args.port)
    SHOTS.mkdir(parents=True, exist_ok=True)
    # Only paths this harness could touch; other work in the tree does not count.
    watched = ["git", "status", "--porcelain", "--", "app", "data", "tools/e2e"]
    git_before = subprocess.run(watched, cwd=REPO, capture_output=True, text=True).stdout
    static_checks(not args.no_pytest)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium_executable(), args=["--no-sandbox"])
        try:
            for cfg, w, h, scheme in CONFIGS:
                if args.only and cfg != args.only:  # --only probes runs no config
                    continue
                print(f"=== {cfg} ===", flush=True)
                run_config(browser, cfg, w, h, scheme)
            if not args.no_probes and (not args.only or args.only == "probes"):
                print("=== probes ===", flush=True)
                probe_embedded_json_ignored(browser)
                probe_preview_parity(browser, "probe-parity")
        finally:
            browser.close()
    git_after = subprocess.run(watched, cwd=REPO, capture_output=True, text=True).stdout
    check("static", "repository unchanged by the harness", git_before == git_after, f"before={git_before!r} after={git_after!r}")
    (OUT / "report.json").write_text(json.dumps(RESULTS, indent=1))
    print(f"report: {OUT / 'report.json'}; screenshots: {SHOTS}")
    fails = [r for r in RESULTS if r["ok"] is False]
    print(f"\n{sum(1 for r in RESULTS if r['ok'])} passed, {len(fails)} failed, {sum(1 for r in RESULTS if r['ok'] is None)} info")
    for f in fails:
        print(f"  FAIL [{f['area']}] {f['check']} :: {f['detail'][:400]}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
