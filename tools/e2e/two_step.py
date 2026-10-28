#!/usr/bin/env python3
"""Two-step sign-in (design note 17) in Chromium, against a real server and the demo.

    python tools/e2e/two_step.py                     # port 8092
    python tools/e2e/two_step.py --port 8092 --out /tmp/kh-two-step

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup and invites Ana and Bob. The harness plays the
authenticator app: it reads the key the page shows and works out the codes with ``app.auth.totp``. Walks:

* Ana at 375x812 light: Settings → Account → Two-step sign-in says Off; Turn on draws a QR code, and the barcode reader the page
  already vendors decodes that QR code to the same ``otpauth://`` link the server gave; a wrong code is refused in words and nothing
  changes; the right code turns it on, signs out her other device (an API client) and shows ten recovery codes once, with Download (the
  file holds exactly them) and "I saved them"; the block then says On and "10 recovery codes left";
* signing in again: the right password brings the code field with a note, not an error; a wrong code is an error under the field and
  the password stays; the next code signs in; a recovery code signs in and the notice says 9 are left;
* Make new recovery codes asks first, then shows ten new ones; an old code no longer works;
* the admin at 1280x800 dark: People shows "Two-step sign-in" on Ana's row; Remove two-step sign-in asks first, then the badge is gone and
  Ana signs in with her password alone;
* Bob turns it on through the API; an admin's reset link sets his new password, signs nobody in, and opens the sign-in screen with his
  username and a note; his password then brings the code field;
* the demo (``/?mock=1``): the block says the demo has no two-step sign-in, has no button and asks the network for nothing;
* no console error, no CSP violation, no browser dialog, no sideways scroll at 375, no other host.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on
any failure. The server is always stopped. What it cannot show: a real phone's camera and authenticator app.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from khserver import DEFAULT_PASSWORD, Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.auth import totp  # noqa: E402 - the repository root is on the path now

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "two-step"
PORT = 8092
RESULTS: list[dict[str, Any]] = []
NEW_PASSWORD = "harbour violet anchor 52 meadow"

# Decodes the QR code on the page with the vendored barcode reader (the same one js/scan.js uses): the modules are read back from the
# SVG path and drawn on a canvas, so no image URL is made (the page's CSP has no data: images).
DECODE_QR = """async () => {
  const API = window.BarcodeDetectionAPI;
  await API.prepareZXingModule({ overrides: { locateFile: (p, pre) => (p.endsWith('.wasm') ? '/vendor/zxing-wasm-3.1.3/' + p : pre + p) }, fireImmediately: true });
  const svg = document.querySelector('.two-step-qr');
  const size = Number(svg.getAttribute('viewBox').split(' ')[2]);
  const scale = 8;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size * scale;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#000';
  for (const m of svg.querySelector('.qr-dark').getAttribute('d').matchAll(/M(\\d+) (\\d+)h1v1h-1z/g)) ctx.fillRect(Number(m[1]) * scale, Number(m[2]) * scale, scale, scale);
  const found = await new API.BarcodeDetector({ formats: ['qr_code'] }).detect(canvas);
  return found.length ? found[0].rawValue : null;
}"""


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def code_for(key_text: str, offset: int = 0) -> str:
    key = totp.secret_from_text(key_text)
    return totp.hotp(key, totp.step_at(time.time()) + offset)


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
        self.expected_401 = 0
        page.on("request", self._request)
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)
        page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")

    def _console(self, m: Any) -> None:
        if m.type != "error":
            return
        # The sign-in answers it asked for (the code is needed, a code is wrong) and a signed-out page's first status check.
        if "status of 401" in m.text or "status of 400" in m.text:
            return
        self.errors.append(m.text)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def _request(self, r: Any) -> None:
        parts = urlsplit(r.url)
        if parts.scheme in ("http", "https"):
            self.hosts.add(parts.netloc)
            self.requests.append(parts.path)


class Pass:
    def __init__(self, browser: Any, base: str, out: Path, width: int, height: int, scheme: str, tag: str,
                 cookies: dict[str, str] | None = None) -> None:
        self.base, self.out, self.tag, self.width = base, out, tag, width
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base, accept_downloads=True)
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

    def finish(self, server_mode: bool) -> None:
        csp = self.page.evaluate("window.__csp || []")
        check(f"[{self.tag}] no console error, no CSP violation, no browser dialog", not self.watch.errors and not csp and not self.watch.dialogs,
              "; ".join(self.watch.errors + csp + self.watch.dialogs))
        others = sorted(h for h in self.watch.hosts if h != urlsplit(self.base).netloc)
        check(f"[{self.tag}] the browser asked no other host", not others, str(others))
        if not server_mode:
            check(f"[{self.tag}] the demo asked the network for nothing about two-step sign-in",
                  not any("/api/me/totp" in p for p in self.watch.requests), str(self.watch.requests[-5:]))
        self.ctx.close()


def open_two_step(page: Any) -> None:
    page.goto("/")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-two-step-on, #set-two-step-renew, #set-two-step p.hint", timeout=20000)
    page.locator("#set-two-step").scroll_into_view_if_needed()


def sign_out(page: Any) -> None:
    page.evaluate("() => KH.auth.signOut()")
    page.wait_for_selector("#form-login:not([hidden])", timeout=20000)


def sign_in(page: Any, username: str, password: str) -> None:
    page.fill("#login-username", username)
    page.fill("#login-password", password)
    page.click("#login-submit")


# ------------------------------------------------------------------------------------------------ the walks
def walk_ana(p: Pass, ana_api: Any) -> list[str]:
    page = p.page
    open_two_step(page)
    check(f"[{p.tag}] the block says Off and what the second step is", "Off." in text_of(page, "#set-two-step")
          and "6-digit code" in text_of(page, "#set-two-step"))
    page.click("#set-two-step-on")
    page.wait_for_selector(".two-step-qr .qr-dark", timeout=20000)
    key = page.inner_text("#set-two-step-key").replace(" ", "")
    uri = page.get_attribute(".two-step-open", "href")
    check(f"[{p.tag}] the key is shown in groups of four and the link is an otpauth link", len(key) == 32 and uri.startswith("otpauth://totp/")
          and f"secret={key}" in uri, uri)
    decoded = page.evaluate(DECODE_QR)
    check(f"[{p.tag}] the QR code on the page decodes to the server's otpauth link", decoded == uri, f"{decoded!r} vs {uri!r}")
    p.shot("setup", "#set-two-step")
    p.no_overflow("setup")

    wrong = "000000" if code_for(key) != "000000" else "111111"
    page.fill("#set-two-step-code", wrong)
    page.click("#set-two-step-confirm")
    wait_text(page, "#set-two-step .form-error", "not right")
    check(f"[{p.tag}] a wrong first code is refused in words and nothing changes", ana_api.json("GET", "/api/me/totp")["enabled"] is False)

    page.fill("#set-two-step-code", code_for(key))
    page.click("#set-two-step-confirm")
    page.wait_for_selector(".recovery-codes li", timeout=15000)
    codes = [c.strip() for c in page.locator(".recovery-codes code").all_inner_texts()]
    check(f"[{p.tag}] ten recovery codes are shown once", len(codes) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes), str(codes))
    check(f"[{p.tag}] turning it on signed out her other device", ana_api.call("GET", "/api/me").status_code == 401)
    with page.expect_download() as dl:
        page.click("#set-two-step-download")
    saved = Path(dl.value.path()).read_text(encoding="utf-8")
    check(f"[{p.tag}] Download saves a text file with exactly those codes", [ln for ln in saved.splitlines() if len(ln) == 11 and ln[5] == "-"] == codes
          and dl.value.suggested_filename == "recovery-codes.txt", saved[:200])
    p.shot("codes", "#set-two-step")
    p.no_overflow("codes")
    page.click("#set-two-step-done")
    wait_text(page, "#set-two-step", "10 recovery codes left.")
    check(f"[{p.tag}] the block then says On and 10 codes left", "On." in text_of(page, "#set-two-step"))

    # Signing in again
    sign_out(page)
    sign_in(page, "ana", DEFAULT_PASSWORD)
    page.wait_for_selector("#login-code-field:not([hidden])")
    check(f"[{p.tag}] the right password brings the code field with a note, not an error",
          "6-digit code" in text_of(page, "#auth-notice") and not text_of(page, "#auth-error")
          and page.get_attribute("#login-code", "autocomplete") == "one-time-code")
    p.shot("code-asked", "#view-auth")
    p.no_overflow("sign-in with code")
    page.fill("#login-code", wrong)
    page.click("#login-submit")
    wait_text(page, "#auth-error", "not right")
    check(f"[{p.tag}] a wrong code is an error under the field and the password stays",
          page.get_attribute("#login-code", "aria-invalid") == "true" and page.input_value("#login-password") == DEFAULT_PASSWORD)
    page.fill("#login-code", code_for(key, 1))  # the step after the one used to turn it on
    page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=20000)
    check(f"[{p.tag}] the next code signs in", page.is_visible("#settings-open"))

    sign_out(page)
    sign_in(page, "ana", DEFAULT_PASSWORD)
    page.wait_for_selector("#login-code-field:not([hidden])")
    page.fill("#login-code", codes[0].upper())
    page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=20000)
    page.wait_for_timeout(300)
    notice = page.evaluate("() => Array.from(document.querySelectorAll('.toast, #auth-notice, .notice, [role=status]')).map((e) => e.innerText).join(' | ')")
    check(f"[{p.tag}] a recovery code signs in and says 9 are left", "9 are left" in notice, notice[:300])

    # New recovery codes
    open_two_step(page)
    page.click("#set-two-step-renew")
    page.get_by_role("button", name="Make new codes").click()
    page.wait_for_selector(".recovery-codes li")
    new = [c.strip() for c in page.locator(".recovery-codes code").all_inner_texts()]
    check(f"[{p.tag}] Make new recovery codes asks first, then shows ten new ones", len(new) == 10 and not set(new) & set(codes))
    page.click("#set-two-step-done")
    p.finish(server_mode=True)
    return codes


def walk_admin(p: Pass, base: str, old_code: str) -> None:
    page = p.page
    page.goto("/#admin")
    page.wait_for_selector("#user-2", timeout=30000)
    row = text_of(page, "#user-2")
    check(f"[{p.tag}] People shows Two-step sign-in on Ana's row", "two-step sign-in" in row.lower()  # badges are drawn in capitals
          and page.locator("#user-2 .badge.two-step-on").count() == 1, row[:200])
    page.click("#user-2 summary")
    page.get_by_role("button", name="Remove two-step sign-in").click()
    check(f"[{p.tag}] Remove two-step sign-in asks first", "lost both the phone and the recovery codes" in text_of(page, "#user-2"))
    p.shot("remove", "#user-2")
    page.get_by_role("button", name="Remove", exact=True).click()
    page.wait_for_function("() => !document.querySelector('#user-2 .badge.two-step-on')", timeout=15000)
    check(f"[{p.tag}] the badge is gone", not page.locator("#user-2 .badge.two-step-on").count())
    p.no_overflow("people")
    probe = khserver.Api(base)
    r = probe.call("POST", "/api/auth/login", {"username": "ana", "password": DEFAULT_PASSWORD})
    check(f"[{p.tag}] Ana signs in with her password alone again", r.status_code == 200, r.text[:200])
    r = probe.call("POST", "/api/auth/login", {"username": "ana", "password": DEFAULT_PASSWORD, "code": old_code})
    check(f"[{p.tag}] (and her old recovery code means nothing now)", r.status_code == 200 and not (r.json().get("notice") or ""), r.text[:200])
    probe.close()
    p.finish(server_mode=True)


def walk_reset(p: Pass, admin: Any, bob: Any, base: str) -> None:
    page = p.page
    setup = bob.json("POST", "/api/me/totp/setup")
    bob.json("POST", "/api/me/totp/enable", {"code": code_for(setup["secret"])})
    bob_id = next(u["id"] for u in admin.json("GET", "/api/admin/users")["users"] if u["username"] == "bob")
    url = admin.json("POST", f"/api/admin/users/{bob_id}/reset-link")["url"]
    page.goto("/#/reset/" + url.split("/#/reset/", 1)[1])
    page.wait_for_selector("#reset-password", state="visible", timeout=30000)
    page.fill("#reset-password", NEW_PASSWORD)
    page.click("#reset-submit")
    page.wait_for_selector("#form-login:not([hidden])", timeout=20000)
    check(f"[{p.tag}] the reset link sets the password and opens sign-in with Bob's username and a note",
          page.input_value("#login-username") == "bob" and "code from your authenticator app" in text_of(page, "#auth-notice"),
          text_of(page, "#auth-notice"))
    check(f"[{p.tag}] nobody is signed in by the link", khserver.Api(base).call("GET", "/api/me").status_code == 401)
    page.fill("#login-password", NEW_PASSWORD)
    page.click("#login-submit")
    page.wait_for_selector("#login-code-field:not([hidden])")
    page.fill("#login-code", code_for(setup["secret"], 1))
    page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=20000)
    check(f"[{p.tag}] Bob then signs in with the new password and a code", page.is_visible("#settings-open"))
    p.finish(server_mode=True)


def walk_demo(p: Pass) -> None:
    page = p.page
    page.goto("/?mock=1")
    page.wait_for_selector("#form-login:not([hidden]), #settings-open", timeout=30000)
    if page.is_visible("#form-login"):
        sign_in(page, "sam", "any demo password at all 15")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-two-step p.hint", timeout=20000)
    text = text_of(page, "#set-two-step")
    check(f"[{p.tag}] the demo says it has no two-step sign-in and shows no button",
          "demo has no real sign-in" in text and not page.locator("#set-two-step-on").count(), text)
    p.no_overflow("demo")
    p.finish(server_mode=False)


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
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook"),
           }
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    failed = False
    try:
        server.start()
        admin = first_admin(server, "twostepadmin")
        ana_browser = invite_user(server, admin, "ana")
        ana_api = khserver.Api(server.base)
        ana_api.login("ana")
        bob = invite_user(server, admin, "bob")
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                codes = walk_ana(Pass(browser, base, out, 375, 812, "light", "ana-375-light", ana_browser.cookies()), ana_api)
                walk_admin(Pass(browser, base, out, 1280, 800, "dark", "admin-1280-dark", admin.cookies()), base, codes[1])
                walk_reset(Pass(browser, base, out, 375, 812, "dark", "bob-375-dark"), admin, bob, base)
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
