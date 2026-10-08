#!/usr/bin/env python3
"""The patient handbook at /learn in a real browser (docs/dev/research/08-handbook-site.md §4.6, §4.8).

    python tools/e2e/learn.py --site handbook/site      # after: cd handbook && mkdocs build
    python tools/e2e/learn.py --site /tmp/learn --port 8064 --out /tmp/kh-learn --server-python .venv/bin/python

Starts ``uvicorn app.main:app`` (khserver.Server) with ``HANDBOOK_DIR=<site>`` and a fresh DATA_DIR,
finishes first-run setup through the API, then in headless Chromium at 375x812 (touch) and 1280x800:

1. ``/learn/``: the theme's hashed inline scripts and its bundle ran, the stylesheet and logo loaded,
   the "Back to the food log" and "Get help now" links are there;
2. a stage page (``stages/g4/``) and the potassium page (``eat/potassium/``), switching a unit tab;
3. the dark/light palette switch;
4. search: type "potassium", results appear (the lunr worker runs under the /learn CSP), open one;
5. an unknown page: the site's own 404 page with status 404;
   on the start, stage and potassium pages (light), the potassium and 404 pages (dark): every visible text run
   meets WCAG 2.2 AA contrast (1.4.3: 4.5:1, or 3:1 from 24 px or 18.66 px bold), measured from the computed
   text colour, its alpha and the opacity on the way, over the stacked background colours;
6. "Back to the food log" → the app's sign-in screen → sign in → the header's Learn entry points at
   /learn/; a banana's potassium warning links to eat/potassium/ in a new tab; Settings → About &
   privacy links to the handbook; the Learn entry opens it in the same window;
7. offline (v0.3.1): with the app's service worker in control, the server is stopped and the browser set
   offline (Chromium's offline switch alone does not reach the worker's own requests); the potassium page
   opened before opens from the worker's copy (``kdl-learn-<version>``), styled; a page never opened
   (``eat/sodium/``) answers 503 with the worker's short note. Requests failing meanwhile are expected and
   not counted; the server is started again for the next viewport.

It fails (exit status 1) on any ``securitypolicyviolation`` event (CSP or Trusted Types), uncaught page
error, console error, failed request, request to another origin, or HTTP error status other than the
deliberate 404. Writes ``<out>/report.json`` and screenshots in ``<out>/shots/``. CI runs it in the
"handbook" job with the runner's Google Chrome (``PLAYWRIGHT_CHROMIUM=/usr/bin/google-chrome``).
The server and the browser are always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

import khserver
from khserver import DEFAULT_PASSWORD, REPO, chromium_executable

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "learn"
PORT = 8064
USERNAME = "learn"
VIEWPORTS = (("phone", 375, 812, True), ("desktop", 1280, 800, False))
TIMEOUT_MS = 15_000

# Every CSP or Trusted Types violation in a document is reported to the harness (the binding is
# injected by the browser driver, so the page's own CSP does not apply to it).
WATCH_SCRIPT = """
document.addEventListener('securitypolicyviolation', (e) => {
  window.__khViolation({ directive: e.violatedDirective, blocked: e.blockedURI, source: e.sourceFile,
                         line: e.lineNumber, sample: e.sample, page: location.href });
});
"""

# WCAG 2.2 AA text contrast (success criterion 1.4.3) of every visible text run on a page. Returns the number
# measured and the failures, grouped by element and colours. Background images (gradients) are not part of the
# measure: the handbook draws none under text.
CONTRAST_JS = r"""() => {
  // WCAG 2.2 AA text contrast (1.4.3) of every visible text run on the page: the text colour (with its alpha and
  // the opacity of the element and its ancestors) over the background colours stacked under it.
  const parse = (c) => {
    const m = /^rgba?\(([^)]+)\)$/.exec(c || '');
    if (!m) return null;
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const over = (top, under) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat([1]);
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => { const x = lum(a); const y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const label = (el) => `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : ''}`;
  const fails = new Map();
  let measured = 0;
  let unmeasured = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const el = node.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'OPTION'].includes(el.tagName)) continue;
    if (el.closest('[hidden], [disabled]')) continue;
    if (typeof el.checkVisibility === 'function' && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    const rects = el.getClientRects();
    if (!rects.length || ![...rects].some((r) => r.width > 1 && r.height > 1)) continue;
    const cs = getComputedStyle(el);
    let fg = parse(cs.color);
    if (!fg) { unmeasured += 1; continue; }
    // Background layers from the element up to the first opaque one, and the opacity on the way.
    const layers = [];
    let opacity = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const ns = getComputedStyle(n);
      opacity *= Number(ns.opacity);
      const bg = parse(ns.backgroundColor);
      if (bg && bg[3] > 0) { layers.push(bg); if (bg[3] >= 1) break; }
    }
    let bg = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i -= 1) bg = over(layers[i], bg);
    const shown = over([fg[0], fg[1], fg[2], fg[3] * opacity], bg);
    const size = parseFloat(cs.fontSize);
    const bold = Number(cs.fontWeight) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const need = large ? 3 : 4.5;
    const r = ratio(shown, bg);
    measured += 1;
    if (r + 1e-9 < need) {
      const key = `${label(el)} ${hex(shown)} on ${hex(bg)}`;
      const seen = fails.get(key);
      if (seen) seen.count += 1;
      else fails.set(key, { where: label(el), text: text.slice(0, 40), ratio: Math.round(r * 100) / 100, need,
                            fg: hex(shown), bg: hex(bg), size: Math.round(size * 10) / 10, bold, count: 1 });
    }
  }
  return { measured, unmeasured, failures: [...fails.values()].sort((a, b) => a.ratio - b.ratio) };
}"""

RESULTS: list[dict[str, Any]] = []


def check(area: str, name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"area": area, "check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} [{area}] {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class Watch:
    """Collects problems from one browser context."""

    def __init__(self, base: str) -> None:
        self.origin = base
        self.problems: list[str] = []
        self.expected: set[tuple[str, int]] = set()  # (path, status) the harness asks for on purpose
        self.offline = False  # step 7: requests failing while the browser is offline are the point

    def attach(self, context: Any) -> None:
        context.expose_binding("__khViolation", lambda _source, v: self.problems.append(f"CSP violation: {json.dumps(v)}"))
        context.add_init_script(WATCH_SCRIPT)
        context.on("request", self._request)
        context.on("requestfailed", lambda r: None if self.offline else
                   self.problems.append(f"request failed: {r.method} {r.url} ({r.failure})"))
        context.on("response", self._response)
        context.on("page", self._page)

    def _page(self, page: Page) -> None:
        page.on("pageerror", lambda e: self.problems.append(f"page error: {e}"))
        page.on("console", self._console)

    def _console(self, message: Any) -> None:
        # "Failed to load resource" duplicates the HTTP status, which _response judges (with the
        # deliberate 404 allowed); anything else logged as an error is a problem.
        if message.type == "error" and not message.text.startswith("Failed to load resource"):
            self.problems.append(f"console error: {message.text}")

    def _request(self, request: Any) -> None:
        scheme = urlsplit(request.url).scheme
        if scheme in ("data", "blob", "about"):
            return
        if not request.url.startswith(self.origin + "/"):
            self.problems.append(f"request to another origin: {request.url}")

    def _response(self, response: Any) -> None:
        if response.status < 400:
            return
        path = urlsplit(response.url).path
        if (path, response.status) not in self.expected:
            self.problems.append(f"HTTP {response.status}: {response.request.method} {response.url}")

    def take(self) -> list[str]:
        out, self.problems = self.problems, []
        return out


def goto(page: Page, url: str, status: int = 200) -> bool:
    response = page.goto(url, wait_until="load")
    page.wait_for_load_state("networkidle")
    return response is not None and response.status == status


def heading(page: Page) -> str:
    """The page's h1 without the "¶" permalink."""
    return (page.text_content("h1") or "").replace("\u00b6", "").strip()


def visible(page: Page, selector: str) -> Any:
    """The first visible element matching ``selector`` (Material repeats some controls for small screens)."""
    for handle in page.query_selector_all(selector):
        if handle.is_visible():
            return handle
    return None


def contrast(page: Page, area: str, label: str) -> None:
    """Check WCAG AA text contrast on the page as shown now (scheme, width and all), once running transitions
    (a tooltip fading in after a click) have ended: their final colours are what a reader sees."""
    page.evaluate("""() => Promise.race([
        Promise.all(document.getAnimations()
          .filter((a) => Number.isFinite(a.effect && a.effect.getComputedTiming().endTime))
          .map((a) => a.finished.catch(() => null))),
        new Promise((resolve) => setTimeout(resolve, 3000))])""")
    got = page.evaluate(CONTRAST_JS)
    worst = "; ".join(f"{f['where']} \"{f['text']}\" {f['fg']} on {f['bg']} = {f['ratio']}:1 (needs {f['need']}:1, "
                      f"{f['size']} px{' bold' if f['bold'] else ''}, ×{f['count']})" for f in got["failures"][:8])
    check(area, f"text contrast meets WCAG AA ({label}: {got['measured']} text runs)",
          got["measured"] > 0 and not got["failures"], worst)


def run_viewport(browser: Any, server: khserver.Server, shots: Path, name: str, width: int, height: int, touch: bool) -> None:
    base = server.base
    area = f"{name} {width}x{height}"
    watch = Watch(base)
    # Service workers stay on, as for a person: the app's worker answers /learn network-first (step 7).
    context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=touch, has_touch=touch,
                                  color_scheme="light")
    watch.attach(context)
    context.set_default_timeout(TIMEOUT_MS)
    page = context.new_page()
    try:
        # 1. the start page
        check(area, "/learn/ answers 200", goto(page, f"{base}/learn/"))
        state = page.evaluate("""() => ({
            scope: typeof window.__md_scope !== 'undefined',
            bundle: typeof window.document$ !== 'undefined',
            styled: getComputedStyle(document.querySelector('.md-header')).backgroundColor !== 'rgba(0, 0, 0, 0)',
            logo: [...document.querySelectorAll('.md-logo img')].some((i) => i.complete && i.naturalWidth > 0),
            back: [...document.querySelectorAll('a.kh-announce__app')].some((a) => new URL(a.href).pathname === '/'),
            help: [...document.querySelectorAll('a')].some((a) => /get help now/i.test(a.textContent || '')),
            overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        })""")
        check(area, "the theme's inline scripts ran (allowed by hash)", state["scope"])
        check(area, "the theme bundle ran", state["bundle"])
        check(area, "the stylesheet applied", state["styled"])
        check(area, "the logo loaded", state["logo"])
        check(area, "'Back to the food log' and 'Get help now' links", state["back"] and state["help"])
        check(area, "no horizontal page overflow", not state["overflow"])
        page.screenshot(path=str(shots / f"{name}-1-start.png"))
        contrast(page, area, "start page, light")

        # 2. a stage page and the potassium page (with a unit tab switch)
        check(area, "stage page stages/g4/ answers 200", goto(page, f"{base}/learn/stages/g4/"))
        check(area, "stage page heading", "G4" in heading(page))
        page.screenshot(path=str(shots / f"{name}-2-stage.png"))
        contrast(page, area, "stage page, light")
        check(area, "eat/potassium/ answers 200", goto(page, f"{base}/learn/eat/potassium/"))
        check(area, "potassium page heading", heading(page) == "Potassium", heading(page))
        tab = visible(page, ".tabbed-labels > label:nth-child(2)")
        if tab is not None:
            tab.click()
            check(area, "a unit tab switches", page.evaluate(
                "() => [...document.querySelectorAll('.tabbed-set')].some((s) => s.querySelectorAll('input')[1]?.checked)"))
        page.screenshot(path=str(shots / f"{name}-3-potassium.png"))
        contrast(page, area, "potassium page, light")

        # 3. the palette switch
        before = page.get_attribute("body", "data-md-color-scheme")
        toggle = visible(page, "label.md-header__button[for^='__palette']")
        check(area, "palette switch is there", toggle is not None)
        if toggle is not None:
            toggle.click()
            page.wait_for_function("(b) => document.body.getAttribute('data-md-color-scheme') !== b", arg=before)
            check(area, "palette switch changes the colour scheme", page.get_attribute("body", "data-md-color-scheme") != before)
            page.screenshot(path=str(shots / f"{name}-4-dark.png"))
            contrast(page, area, "potassium page, dark")

        # 4. search (lunr in a web worker, under the /learn CSP)
        opener = visible(page, "label.md-header__button[for='__search']")
        if opener is not None:
            opener.click()
        page.click(".md-search__input")
        page.keyboard.type("potassium", delay=40)
        page.wait_for_selector(".md-search-result__item", state="visible")
        hits = page.query_selector_all(".md-search-result__item")
        check(area, "search finds results", len(hits) > 0, f"{len(hits)} results")
        page.screenshot(path=str(shots / f"{name}-5-search.png"))
        with page.expect_navigation():
            page.click(".md-search-result__item .md-search-result__link")
        page.wait_for_load_state("networkidle")
        check(area, "a search result opens a handbook page", urlsplit(page.url).path.startswith("/learn/"), page.url)

        # 5. an unknown page: the site's 404 page, styled
        watch.expected.add(("/learn/no-such-page/", 404))
        check(area, "unknown page answers 404", goto(page, f"{base}/learn/no-such-page/", 404))
        check(area, "the 404 page is the handbook's", page.query_selector(".md-header") is not None)
        page.screenshot(path=str(shots / f"{name}-6-404.png"))
        contrast(page, area, "404 page, dark")

        # 6. back to the app, sign in, and the app's way into the handbook
        goto(page, f"{base}/learn/")
        # Material's script makes every href absolute, so find the link by its class.
        with page.expect_navigation():
            page.click("a.kh-announce__app")
        page.wait_for_load_state("networkidle")
        check(area, "'Back to the food log' opens the app", urlsplit(page.url).path == "/", page.url)
        page.wait_for_selector("#form-login", state="visible")
        page.fill("#login-username", USERNAME)
        page.fill("#login-password", DEFAULT_PASSWORD)
        page.click("#login-submit")
        page.wait_for_selector("#learn-link", state="visible")
        learn = page.get_by_role("link", name="Learn", exact=True)
        check(area, "the header's Learn entry is a link named 'Learn'", learn.count() == 1)
        check(area, "the Learn entry points at /learn/", page.get_attribute("#learn-link", "href") == "/learn/")
        page.screenshot(path=str(shots / f"{name}-7-app.png"))
        # A food warning links to its handbook page, in a new tab (an entry being typed is kept).
        page.click("#tab-add")
        page.fill("#food-search", "banana")
        banana = "#food-results li .row-btn:has-text('Banana')"
        page.wait_for_selector(banana)
        page.click(banana)
        more = page.wait_for_selector("#entry-warnings a.learn-more", state="visible")
        check(area, "a potassium warning links to the potassium page",
              more.get_attribute("href") == "/learn/eat/potassium/" and more.get_attribute("target") == "_blank"
              and "noopener" in (more.get_attribute("rel") or ""), more.get_attribute("href") or "")
        check(area, "the warning link says where it goes", (more.text_content() or "").startswith("Learn: Potassium"))
        page.screenshot(path=str(shots / f"{name}-8-warning.png"))
        page.keyboard.press("Escape")
        page.click("#settings-open")
        about = page.get_by_role("link", name="Open the handbook")
        about.wait_for(state="attached")
        check(area, "Settings → About links to the handbook", about.get_attribute("href") == "/learn/")
        with page.expect_navigation():
            page.click("#learn-link")
        page.wait_for_load_state("networkidle")
        check(area, "the Learn entry opens the handbook in the same window",
              urlsplit(page.url).path == "/learn/" and len(context.pages) == 1, page.url)

        # 7. offline: pages opened before come from the app's service worker (kdl-learn-<version>)
        page.evaluate("() => navigator.serviceWorker.ready.then(() => true)")
        goto(page, f"{base}/learn/eat/potassium/")  # online, through the worker, which keeps a copy
        check(area, "the handbook page is served through the app's service worker",
              page.evaluate("() => !!navigator.serviceWorker.controller"))
        kept = page.evaluate("""async () => {
            const names = (await caches.keys()).filter((n) => n.startsWith('kdl-learn-'));
            if (names.length !== 1) return names;
            const cache = await caches.open(names[0]);
            return (await cache.keys()).map((r) => new URL(r.url).pathname);
        }""")
        check(area, "the page and its files are kept for reading offline",
              "/learn/eat/potassium/" in kept and any(k.endswith(".css") for k in kept), json.dumps(kept)[:300])
        watch.offline = True
        server.stop()  # the home server is out of reach, as on a phone with no signal
        context.set_offline(True)
        try:
            check(area, "offline: a page opened before opens from the copy", goto(page, f"{base}/learn/eat/potassium/"))
            styled = page.evaluate(
                "() => getComputedStyle(document.querySelector('.md-header')).backgroundColor !== 'rgba(0, 0, 0, 0)'")
            check(area, "offline: the copy has its heading and styles", heading(page) == "Potassium" and styled, heading(page))
            page.screenshot(path=str(shots / f"{name}-9-offline.png"))
            watch.expected.add(("/learn/eat/sodium/", 503))
            check(area, "offline: a page never opened answers 503", goto(page, f"{base}/learn/eat/sodium/", 503))
            check(area, "offline: ... and says it is not saved on this device",
                  "not saved on this device" in (page.text_content("h1") or ""), page.text_content("body") or "")
            page.screenshot(path=str(shots / f"{name}-10-offline-not-saved.png"))
        finally:
            context.set_offline(False)
            server.start()
            watch.offline = False
    except Exception as exc:  # report and keep going with the next viewport
        check(area, "walk finished", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        try:
            page.screenshot(path=str(shots / f"{name}-error.png"))
        except Exception:  # noqa: BLE001 - the page may be gone
            pass
    finally:
        problems = watch.take()
        check(area, "no CSP/Trusted Types violations, page or console errors, failed or outside requests",
              not problems, "; ".join(problems[:20]))
        context.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", type=Path, default=REPO / "handbook" / "site", help="the built handbook (default handbook/site)")
    ap.add_argument("--port", type=int, default=PORT, help=f"uvicorn port (default {PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory: data, server log, report, screenshots (default {OUT})")
    ap.add_argument("--server-python", default=sys.executable, help="interpreter that runs the server (default: this one)")
    args = ap.parse_args(argv)

    site = args.site.resolve()
    if not (site / "index.html").is_file():
        print(f"no built handbook at {site}: build it first (cd handbook && mkdocs build), or pass --site", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    shots = out / "shots"
    shots.mkdir()
    server = khserver.Server(args.port, out / "data", log_path=out / "server.log", python=args.server_python,
                             env={"HANDBOOK_DIR": str(site)})
    try:
        server.start()
        khserver.first_admin(server, USERNAME).close()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chromium_executable(), args=["--no-sandbox"])
            try:
                for name, width, height, touch in VIEWPORTS:
                    run_viewport(browser, server, shots, name, width, height, touch)
            finally:
                browser.close()
    except Exception as exc:
        check("harness", "server and browser started", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        server.stop()
    failed = [r for r in RESULTS if r["ok"] is False]
    (out / "report.json").write_text(json.dumps({"failed": len(failed), "results": RESULTS}, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}, screenshots {shots}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
