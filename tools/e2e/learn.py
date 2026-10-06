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
6. "Back to the food log" → the app's sign-in screen → sign in → the header's Learn entry points at
   /learn/; a banana's potassium warning links to eat/potassium/ in a new tab; Settings → About &
   privacy links to the handbook; the Learn entry opens it in the same window.

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

    def attach(self, context: Any) -> None:
        context.expose_binding("__khViolation", lambda _source, v: self.problems.append(f"CSP violation: {json.dumps(v)}"))
        context.add_init_script(WATCH_SCRIPT)
        context.on("request", self._request)
        context.on("requestfailed", lambda r: self.problems.append(f"request failed: {r.method} {r.url} ({r.failure})"))
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


def run_viewport(browser: Any, base: str, shots: Path, name: str, width: int, height: int, touch: bool) -> None:
    area = f"{name} {width}x{height}"
    watch = Watch(base)
    # Service workers stay on, as for a person: the app's worker must leave /learn to the network.
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

        # 2. a stage page and the potassium page (with a unit tab switch)
        check(area, "stage page stages/g4/ answers 200", goto(page, f"{base}/learn/stages/g4/"))
        check(area, "stage page heading", "G4" in heading(page))
        page.screenshot(path=str(shots / f"{name}-2-stage.png"))
        check(area, "eat/potassium/ answers 200", goto(page, f"{base}/learn/eat/potassium/"))
        check(area, "potassium page heading", heading(page) == "Potassium", heading(page))
        tab = visible(page, ".tabbed-labels > label:nth-child(2)")
        if tab is not None:
            tab.click()
            check(area, "a unit tab switches", page.evaluate(
                "() => [...document.querySelectorAll('.tabbed-set')].some((s) => s.querySelectorAll('input')[1]?.checked)"))
        page.screenshot(path=str(shots / f"{name}-3-potassium.png"))

        # 3. the palette switch
        before = page.get_attribute("body", "data-md-color-scheme")
        toggle = visible(page, "label.md-header__button[for^='__palette']")
        check(area, "palette switch is there", toggle is not None)
        if toggle is not None:
            toggle.click()
            page.wait_for_function("(b) => document.body.getAttribute('data-md-color-scheme') !== b", arg=before)
            check(area, "palette switch changes the colour scheme", page.get_attribute("body", "data-md-color-scheme") != before)
            page.screenshot(path=str(shots / f"{name}-4-dark.png"))

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
        base = server.base
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chromium_executable(), args=["--no-sandbox"])
            try:
                for name, width, height, touch in VIEWPORTS:
                    run_viewport(browser, base, shots, name, width, height, touch)
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
