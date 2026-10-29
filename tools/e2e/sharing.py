#!/usr/bin/env python3
"""Read-only sharing (design note 19) in Chromium, against a real server and the demo.

    python tools/e2e/sharing.py                     # port 8096
    python tools/e2e/sharing.py --port 8096 --out /tmp/kh-sharing

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup, turns sharing on and invites Ana and Sam. Ana
logs a banana and a potassium result. Walks:

* Ana at 375x812 light: Settings → Account → Sharing says what it is; she unticks symptoms and makes a link, shown once with
  Copy link and the words that it works once;
* Sam at 1280x800 dark opens the link: the sheet names Ana and what she shares, and nothing is saved until Accept; Accept opens
  Ana's summary, read-only: her name, the banner, her lab result, "has not shared their symptoms", and the banana in the day view;
  the page has no control that changes data;
* the admin: People shows "Sharing: 1" on Ana's row;
* Ana: her list names Sam and says he looked today; Stop sharing asks first, then the list is empty;
* Sam: Settings says nobody shares with him, and the shared routes answer 404;
* the demo (``/?mock=1``): the block says the demo has nobody to share with and asks the network for no shared route;
* no console error, no CSP violation, no browser dialog, no sideways scroll at 375, no other host.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on
any failure. The server is always stopped.
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

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "sharing"
PORT = 8096
RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def text_of(page: Any, selector: str) -> str:
    return page.evaluate("(sel) => { const el = document.querySelector(sel); return el ? el.innerText.replace(/\\s+/g, ' ').trim() : ''; }", selector)


def wait_text(page: Any, selector: str, needle: str, timeout: int = 15000) -> None:
    page.wait_for_function("([sel, t]) => { const el = document.querySelector(sel); return !!el && el.innerText.includes(t); }",
                           arg=[selector, needle], timeout=timeout)


class Watch:
    def __init__(self, page: Any) -> None:
        self.hosts: set[str] = set()
        self.requests: list[str] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        page.on("request", self._request)
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)
        page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")

    def _console(self, m: Any) -> None:
        if m.type != "error":
            return
        # A signed-out page's first status check and an "enter your password again" answer (both asked for).
        if "status of 401" in m.text or "status of 403" in m.text:
            return
        self.errors.append(m.text)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def _request(self, r: Any) -> None:
        parts = urlsplit(r.url)
        if parts.scheme in ("http", "https"):
            self.hosts.add(parts.netloc)
            self.requests.append(f"{r.method} {parts.path}")


class Pass:
    def __init__(self, browser: Any, base: str, out: Path, width: int, height: int, scheme: str, tag: str,
                 cookies: dict[str, str] | None = None) -> None:
        self.base, self.out, self.tag = base, out, tag
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
        self.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
        if cookies:
            self.ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in cookies.items()])
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self.watch = Watch(self.page)

    def shot(self, name: str, selector: str | None = None) -> None:
        path = str(self.out / "shots" / f"{name}-{self.tag}.png")
        target = self.page.locator(selector) if selector else None
        if target is not None and target.count():
            target.first.screenshot(path=path)
        else:
            self.page.screenshot(path=path)

    def no_overflow(self, where: str) -> None:
        wide = self.page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        check(f"[{self.tag}] no sideways scroll ({where})", not wide)

    def finish(self, demo: bool = False) -> None:
        csp = self.page.evaluate("window.__csp || []")
        check(f"[{self.tag}] no console error, no CSP violation, no browser dialog", not self.watch.errors and not csp and not self.watch.dialogs,
              "; ".join(self.watch.errors + csp + self.watch.dialogs))
        others = sorted(h for h in self.watch.hosts if h != urlsplit(self.base).netloc)
        check(f"[{self.tag}] the browser asked no other host", not others, str(others))
        if demo:
            check(f"[{self.tag}] the demo asked the network for no shared route",
                  not any(" /api/shared" in r or " /api/me/shares" in r for r in self.watch.requests), str(self.watch.requests[-5:]))
        self.ctx.close()


def answer_reauth(page: Any) -> bool:
    try:
        page.wait_for_selector("#sheet-reauth[open]", timeout=3000)
    except Exception:  # noqa: BLE001 - not asked
        return False
    page.fill("#reauth-password", khserver.DEFAULT_PASSWORD)
    page.click("#reauth-submit")
    return True


def open_sharing(page: Any) -> None:
    page.goto("/")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-sharing p:not(.muted.small), #set-sharing-off", timeout=20000)
    page.locator("#set-sharing").scroll_into_view_if_needed()


def walk_ana_shares(p: Pass) -> str:
    page = p.page
    open_sharing(page)
    check(f"[{p.tag}] the block says who it is for and that they cannot change anything",
          "caregiver or dietitian" in text_of(page, "#set-sharing") and "never change anything" in text_of(page, "#set-sharing")
          and "Nobody yet." in text_of(page, "#set-sharing"))
    page.uncheck("#set-share-symptoms")
    page.select_option("#set-share-days", "30")
    page.click("#set-sharing-make")
    answer_reauth(page)
    page.wait_for_selector("#set-share-link", timeout=20000)
    link = page.input_value("#set-share-link")
    box = text_of(page, "#set-sharing [aria-label='New share link']")
    check(f"[{p.tag}] the link is shown once with the areas and the words that it works once",
          "/#/share/" in link and "food log, lab results and weight and blood pressure" in box and "works once" in box, box[:200])
    check(f"[{p.tag}] it says the share will last 30 days", "you share for 30 days" in box, box[:300])
    page.click("#set-sharing [aria-label='New share link'] button:has-text('Copy link')")
    check(f"[{p.tag}] Copy link puts exactly the link on the clipboard", page.evaluate("() => navigator.clipboard.readText()") == link)
    check(f"[{p.tag}] the unused link is listed with when it ends", "works until" in text_of(page, "#set-sharing-codes"))
    p.shot("link", "#set-sharing")
    p.no_overflow("link")
    return link


def walk_sam_accepts(p: Pass, link: str) -> None:
    page = p.page
    page.goto("/")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.goto(link.replace(urlsplit(link).netloc, urlsplit(p.base).netloc))
    page.wait_for_selector("#sheet-share[open]", timeout=20000)
    wait_text(page, "#share-question", "wants to share")
    q = text_of(page, "#share-question")
    check(f"[{p.tag}] the sheet names Ana and what she shares, and says he cannot change anything",
          "ana wants to share their food log, lab results and weight and blood pressure with you" in q and "not change anything" in q, q)
    check(f"[{p.tag}] the sheet says it ends by itself after 30 days", "ends by itself after 30 days" in q, q)
    check(f"[{p.tag}] the link left the address bar", "/share/" not in page.url, page.url)
    p.shot("question", "#sheet-share")
    page.click("#share-accept")
    page.wait_for_selector("#view-visit:not([hidden])", timeout=20000)
    wait_text(page, "#visit-title", "ana's summary")
    wait_text(page, "#visit-labs-body", "Potassium")
    wait_text(page, "#visit-day-body", "Banana")
    check(f"[{p.tag}] Accept opens Ana's summary with her name and the read-only banner",
          "You can look, but not change anything" in text_of(page, "#visit-shared") and "Shared by ana" in text_of(page, "#visit-who"))
    check(f"[{p.tag}] her lab result and her day are there, and the symptoms say they were not shared",
          "4.8" in text_of(page, "#visit-labs-body") and "has not shared their symptoms" in text_of(page, "#visit-sym-body"),
          text_of(page, "#visit-sym-body"))
    writes = [r for r in p.watch.requests if r.split(" ", 1)[0] in ("POST", "PUT", "PATCH", "DELETE") and "/api/" in r
              and r != "POST /api/shared/info"]  # info is a POST that reads: who the link is from
    check(f"[{p.tag}] the only write was accepting the link", writes == ["POST /api/shared/accept"], str(writes))
    buttons = page.evaluate("() => [...document.querySelectorAll('#view-visit button')].filter((b) => b.offsetParent).map((b) => b.innerText.trim())")
    allowed = {"Back to Settings", "Print / Save as PDF", "Add", "2 weeks", "4 weeks", "3 months"}
    check(f"[{p.tag}] the page has no control that changes data (only the period, print, back and the page's own questions)",
          set(buttons) <= allowed, str(buttons))
    p.shot("summary")
    p.no_overflow("summary")


def walk_sam_trends(p: Pass) -> None:
    """Sam opens Ana's Trends from Settings: her charts read-only, then the Trends tab is his own again."""
    page = p.page
    open_sharing(page)
    wait_text(page, "#set-shared-list", "ana")
    before = len(p.watch.requests)
    page.get_by_role("button", name="Open ana's trends").click()
    page.wait_for_selector("#view-trends:not([hidden])", timeout=20000)
    wait_text(page, "#trends-shared", "ana's trends")
    page.wait_for_selector("#charts > *", timeout=20000)
    wait_text(page, "#period-sub", "of")
    charts = text_of(page, "#charts")
    check(f"[{p.tag}] Trends opens Ana's trends with the read-only banner and her name in the title",
          "You can look, but not change anything" in text_of(page, "#trends-shared") and "ana" in text_of(page, "#trends-title").lower(),
          text_of(page, "#trends-title"))
    check(f"[{p.tag}] her period is read from her log (1 day logged), and nothing sends him to her Profile",
          "1 of" in text_of(page, "#period-sub") and "Profile" not in charts + text_of(page, "#period-body"),
          text_of(page, "#period-sub") + " | " + charts[:120])
    check(f"[{p.tag}] there is no CSV export and no Get-ready link on her trends",
          not page.is_visible("#export-csv") and not page.is_visible("#visit-open"))
    wait_text(page, "#symptoms-trends-body", "has not shared")
    check(f"[{p.tag}] her symptoms say they were not shared", "has not shared their symptoms" in text_of(page, "#symptoms-trends-body"))
    asked = [r for r in p.watch.requests[before:] if "/api/" in r]
    check(f"[{p.tag}] her trends read only the shared routes, with GET",
          all(r.startswith("GET /api/shared/") or r.startswith("GET /api/me") or r.startswith("GET /api/auth") for r in asked)
          and any("/log/range" in r for r in asked), str(asked))
    p.shot("trends")
    p.no_overflow("trends")
    page.click("#tab-trends")
    page.wait_for_selector("#trends-shared", state="hidden", timeout=20000)
    check(f"[{p.tag}] the Trends tab then shows his own trends, with the export back", page.is_visible("#export-csv")
          and "ana" not in text_of(page, "#trends-title").lower(), text_of(page, "#trends-title"))


def walk_admin(p: Pass, admin: Any) -> None:
    page = p.page
    ana_id = next(u["id"] for u in admin.json("GET", "/api/admin/users")["users"] if u["username"] == "ana")
    page.goto("/#admin")
    page.wait_for_selector(f"#user-{ana_id}", timeout=30000)
    check(f"[{p.tag}] People shows Sharing: 1 on Ana's row", "sharing: 1" in text_of(page, f"#user-{ana_id}").lower(), text_of(page, f"#user-{ana_id}")[:200])
    p.finish()


def walk_ana_stops(p: Pass) -> None:
    page = p.page
    open_sharing(page)
    wait_text(page, "#set-sharing-list", "sam")
    line = text_of(page, "#set-sharing-list")
    check(f"[{p.tag}] her list names Sam and says he looked today", "looked today" in line and "food log" in line, line)
    check(f"[{p.tag}] and when the share ends", " · until " in line, line)
    page.get_by_role("button", name="Stop sharing with sam").click()
    check(f"[{p.tag}] Stop sharing asks first", "can no longer see any of your data" in text_of(page, "#set-sharing-list"))
    page.locator("#set-sharing-list").get_by_role("button", name="Stop sharing", exact=True).click()
    page.wait_for_selector("#set-sharing-none", timeout=15000)
    check(f"[{p.tag}] then nobody can see her data", "Nobody yet." in text_of(page, "#set-sharing"))
    p.finish()


def walk_sam_after(p: Pass, sam: Any, share_id: int) -> None:
    page = p.page
    open_sharing(page)
    page.wait_for_selector("#set-shared-none", timeout=15000)
    check(f"[{p.tag}] Settings says nobody shares with him", "Nobody shares with you yet." in text_of(page, "#set-sharing"))
    check(f"[{p.tag}] the shared routes answer 404", sam.call("GET", f"/api/shared/{share_id}/labs").status_code == 404)
    p.finish()


def walk_demo(p: Pass) -> None:
    page = p.page
    page.goto("/?mock=1")
    page.wait_for_selector("#form-login:not([hidden]), #settings-open", timeout=30000)
    if page.is_visible("#form-login"):
        page.fill("#login-username", "sam")
        page.fill("#login-password", "any demo password at all 15")
        page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-sharing-off", timeout=20000)
    check(f"[{p.tag}] the demo says it has nobody to share with", "nobody to share with" in text_of(page, "#set-sharing"))
    p.no_overflow("demo")
    p.finish(demo=True)


def walk_question_order(p: Pass) -> None:
    """Deferred synthetic link-info replies; no synthetic link is accepted on the server."""
    result = p.page.evaluate("""async () => {
      const realFetch = window.fetch;
      const oldUrl = location.pathname + location.search + location.hash;
      const pending = new Map();
      let accepts = 0;
      const code = (id, verifier) => id.repeat(16) + '.' + verifier.repeat(43);
      const a = code('a', 'B'), b = code('c', 'D'), c = code('e', 'F'), d = code('1', 'G'), e = code('2', 'H');
      const dlg = document.querySelector('#sheet-share'), accept = document.querySelector('#share-accept');
      const tick = () => new Promise(r => setTimeout(r, 0));
      const wait = async key => {
        for (let n = 0; n < 100 && !pending.has(key); ++n) await tick();
        if (!pending.has(key)) throw new Error('synthetic link-info read did not start');
      };
      const begin = code => {
        history.replaceState(null, '', '/#/share/' + code);
        KH.sharing.takeLink();
        return KH.sharing.openPending();
      };
      const info = name => ({name, username: name.toLowerCase(), areas: ['food']});
      window.fetch = (input, options = {}) => {
        const path = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
        if (path === '/api/shared/info') return new Promise(resolve => {
          pending.set(JSON.parse(options.body).code, person => resolve(new Response(JSON.stringify(person),
            {status: 200, headers: {'Content-Type': 'application/json'}})));
        });
        if (path === '/api/shared/accept') { ++accepts; throw new Error('synthetic link must not be accepted'); }
        return realFetch(input, options);
      };
      try {
        const first = begin(a), second = begin(b);
        await wait(a); await wait(b);
        pending.get(b)(info('Sam')); await second;
        pending.get(a)(info('Ana')); await first;
        const current = {question: document.querySelector('#share-question').innerText,
          codeMatches: accept.dataset.code === b, visible: !accept.hidden};
        const closing = begin(c);
        await wait(c); dlg.close();
        pending.get(c)(info('Closed')); await closing; await tick();
        const closed = !dlg.open && !accept.dataset.code && accept.hidden;
        const beforeReopen = begin(d);
        await wait(d); pending.get(d)(info('Before')); await beforeReopen;
        dlg.close();
        const reopened = begin(e);
        await wait(e); pending.get(e)(info('Latest')); await reopened; await tick();
        return {current, closed, reopened: dlg.open && accept.dataset.code === e && !accept.hidden,
          question: document.querySelector('#share-question').innerText, accepts};
      } finally {
        dlg.close(); await tick();
        window.fetch = realFetch;
        history.replaceState(null, '', oldUrl);
      }
    }""")
    check(f"[{p.tag}] delayed link info cannot replace the latest question or Accept code",
          result["current"]["question"].startswith("Sam") and result["current"]["codeMatches"] and result["current"]["visible"])
    check(f"[{p.tag}] closing a pending share question leaves no Accept code", result["closed"])
    check(f"[{p.tag}] reopening survives a queued close event from the older question",
          result["reopened"] and result["question"].startswith("Latest"))
    check(f"[{p.tag}] synthetic question checks accepted no link", result["accepts"] == 0)


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
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook")}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, "shareadmin")
        admin.json("PATCH", "/api/admin/settings", {"sharing.enabled": True})
        ana = invite_user(server, admin, "ana")
        sam = invite_user(server, admin, "sam")
        banana = ana.json("GET", "/api/foods", params={"q": "banana"})["foods"][0]["id"]
        ana.json("POST", "/api/log", {"date": date.today().isoformat(), "meal": "breakfast", "food_id": banana, "servings": 1})
        ana.json("POST", "/api/labs", {"analyte": "potassium", "value": 4.8, "unit": "mmol/L", "taken_on": date.today().isoformat()})
        base = server.base
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                ana_pass = Pass(browser, base, out, 375, 812, "light", "ana-375-light", ana.cookies())
                link = walk_ana_shares(ana_pass)
                sam_pass = Pass(browser, base, out, 1280, 800, "dark", "sam-1280-dark", sam.cookies())
                walk_sam_accepts(sam_pass, link)
                walk_question_order(sam_pass)
                walk_sam_trends(sam_pass)
                share_id = sam.json("GET", "/api/shared")["people"][0]["id"]
                walk_admin(Pass(browser, base, out, 1280, 800, "dark", "admin-1280-dark", admin.cookies()), admin)
                walk_ana_stops(ana_pass)
                walk_sam_after(sam_pass, sam, share_id)
                walk_demo(Pass(browser, base, out, 375, 812, "light", "demo-375-light"))
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc(limit=3))
    finally:
        server.stop()
    failed = any(not r["ok"] for r in RESULTS)
    (out / "report.json").write_text(json.dumps({"results": RESULTS, "failed": failed}, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in RESULTS)} passed, {sum(not r['ok'] for r in RESULTS)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
