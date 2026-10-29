#!/usr/bin/env python3
"""Passkeys (design note 18) in Chromium, against a real server and the demo.

    python tools/e2e/passkeys.py                     # port 8093
    python tools/e2e/passkeys.py --port 8093 --out /tmp/kh-passkeys

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup and invites Ana. Chromium's virtual authenticator
(the DevTools ``WebAuthn`` domain: a platform authenticator that holds passkeys and says yes to the fingerprint check) plays Ana's
phone, so the page, the browser's WebAuthn code and the server's checks all run for real. Walks:

* Ana at 375x812 light: Settings → Account → Passkeys says "No passkeys yet"; Add a passkey (with a name; her password is asked
  again only if she typed it more than a few minutes ago), then the list shows the name, "not used yet" and no key or ID; adding a second passkey on the same device is refused in
  words (the browser's own "already has a passkey" answer); Rename changes the name;
* she signs out: the sign-in page shows "Sign in with a passkey"; it signs her in with no password and no code, and the list then
  says when it was last used;
* the admin at 1280x800 dark: People shows "1 passkey" on Ana's row; Remove passkeys asks first, then the badge is gone;
* Ana again: the passkey sign-in now fails with a plain message on the sign-in page, and her password still works;
* the demo (``/?mock=1``): no passkey button at sign-in; the block says the demo has no passkeys and asks the network for nothing
  about them;
* no console error, no CSP violation, no browser dialog, no sideways scroll at 375, no other host.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on
any failure. The server is always stopped. What it cannot show: a real phone's fingerprint reader and a synced passkey.
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

import khserver
from khserver import DEFAULT_PASSWORD, Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "passkeys"
PORT = 8093
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
        # A signed-out page's first status check, and the passkey sign-in refused after the admin removed it (asked for).
        if "status of 401" in m.text:
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
                 cookies: dict[str, str] | None = None, authenticator: bool = False) -> None:
        self.base, self.out, self.tag = base, out, tag
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
        if cookies:
            self.ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in cookies.items()])
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self.watch = Watch(self.page)
        self.authenticator_id = None
        if authenticator:
            self.cdp = self.ctx.new_cdp_session(self.page)
            self.cdp.send("WebAuthn.enable", {"enableUI": False})
            self.authenticator_id = self.cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
                "protocol": "ctap2", "ctap2Version": "ctap2_1", "transport": "internal", "hasResidentKey": True,
                "hasUserVerification": True, "isUserVerified": True, "automaticPresenceSimulation": True}})["authenticatorId"]

    def credentials(self) -> list[dict]:
        return self.cdp.send("WebAuthn.getCredentials", {"authenticatorId": self.authenticator_id})["credentials"]

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
            check(f"[{self.tag}] the demo asked the network for nothing about passkeys",
                  not any(p.startswith("/api/") and "passkey" in p for p in self.watch.requests), str(self.watch.requests[-5:]))
        self.ctx.close()


def open_passkeys(page: Any) -> None:
    page.goto("/")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-passkeys p.muted, #set-passkey-list, #set-passkeys p.hint", timeout=20000)
    page.locator("#set-passkeys").scroll_into_view_if_needed()


def answer_reauth(page: Any, password: str = DEFAULT_PASSWORD) -> bool:
    try:
        page.wait_for_selector("#sheet-reauth[open]", timeout=3000)
    except Exception:  # noqa: BLE001 - not asked
        return False
    page.fill("#reauth-password", password)
    page.click("#reauth-submit")
    return True


def sign_out(page: Any) -> None:
    page.evaluate("() => KH.auth.signOut()")
    page.wait_for_selector("#form-login:not([hidden])", timeout=20000)


# ------------------------------------------------------------------------------------------------ the walks
def walk_ana(p: Pass, ana_api: Any) -> None:
    page = p.page
    open_passkeys(page)
    check(f"[{p.tag}] the block says what a passkey is and that there are none yet",
          "fingerprint, face or phone PIN" in text_of(page, "#set-passkeys") and "No passkeys yet." in text_of(page, "#set-passkeys"))
    page.fill("#set-passkey-name", "Ana's phone")
    page.click("#set-passkey-add")
    asked = answer_reauth(page)
    page.wait_for_selector("#set-passkey-list .passkey-item", timeout=20000)
    item = text_of(page, "#set-passkey-list")
    check(f"[{p.tag}] Add a passkey lists it by name", "Ana's phone" in item and "not used yet" in item,
          f"{item} (password asked again: {asked})")
    creds = p.credentials()
    check(f"[{p.tag}] the device holds one passkey for localhost, made for Ana", len(creds) == 1 and creds[0]["rpId"] == "localhost"
          and creds[0]["isResidentCredential"], json.dumps([{k: c.get(k) for k in ("rpId", "isResidentCredential")} for c in creds]))
    stored = ana_api.json("GET", "/api/me/passkeys")["passkeys"]
    check(f"[{p.tag}] the server lists it without its key or ID", len(stored) == 1 and set(stored[0]) == {"id", "name", "created_at",
          "last_used_at", "backed_up"} and creds[0]["credentialId"] not in page.content(), str(stored))
    p.shot("added", "#set-passkeys")
    p.no_overflow("added")

    page.fill("#set-passkey-name", "Same phone again")
    page.click("#set-passkey-add")
    answer_reauth(page)
    wait_text(page, "#set-passkeys .form-error", "already has a passkey")
    check(f"[{p.tag}] a second passkey on the same device is refused in words", len(ana_api.json("GET", "/api/me/passkeys")["passkeys"]) == 1)

    page.get_by_role("button", name="Rename Ana's phone").click()
    page.fill(".passkey-rename input", "Phone")
    page.locator(".passkey-rename").get_by_role("button", name="Save").click()
    wait_text(page, "#set-passkey-list", "Phone")
    check(f"[{p.tag}] Rename changes the name", ana_api.json("GET", "/api/me/passkeys")["passkeys"][0]["name"] == "Phone")

    sign_out(page)
    page.wait_for_selector("#login-passkey:not([hidden])", timeout=10000)
    check(f"[{p.tag}] the sign-in page offers Sign in with a passkey", page.is_visible("#login-passkey-btn"))
    p.shot("sign-in", "#view-auth")
    p.no_overflow("sign-in")
    page.click("#login-passkey-btn")
    page.wait_for_selector("#settings-open", state="visible", timeout=20000)
    check(f"[{p.tag}] the passkey signs her in with no password and no code", page.is_visible("#settings-open"))
    open_passkeys(page)
    check(f"[{p.tag}] the list then says when it was last used", "last used" in text_of(page, "#set-passkey-list"), text_of(page, "#set-passkey-list"))


def walk_admin(p: Pass, admin: Any) -> None:
    page = p.page
    ana_id = next(u["id"] for u in admin.json("GET", "/api/admin/users")["users"] if u["username"] == "ana")
    row_sel = f"#user-{ana_id}"
    page.goto("/#admin")
    page.wait_for_selector(row_sel, timeout=30000)
    check(f"[{p.tag}] People shows 1 passkey on Ana's row", page.locator(f"{row_sel} .badge.passkeys-on").count() == 1
          and "1 passkey" in text_of(page, row_sel).lower(), text_of(page, row_sel)[:200])
    page.click(f"{row_sel} summary")
    page.get_by_role("button", name="Remove passkeys").click()
    check(f"[{p.tag}] Remove passkeys asks first", "lost or stolen" in text_of(page, row_sel))
    p.shot("remove", row_sel)
    page.get_by_role("button", name="Remove", exact=True).click()
    answer_reauth(page)
    page.wait_for_function(f"() => !document.querySelector('{row_sel} .badge.passkeys-on')", timeout=15000)
    check(f"[{p.tag}] the badge is gone", not page.locator(f"{row_sel} .badge.passkeys-on").count())
    p.no_overflow("people")
    p.finish(server_mode=True)


def walk_ana_after(p: Pass) -> None:
    page = p.page
    sign_out(page)
    page.click("#login-passkey-btn")
    wait_text(page, "#auth-error", "did not work")
    check(f"[{p.tag}] after the admin removed it, the passkey sign-in fails with a plain message",
          "sign in with your password" in text_of(page, "#auth-error"), text_of(page, "#auth-error"))
    page.fill("#login-username", "ana")
    page.fill("#login-password", DEFAULT_PASSWORD)
    page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=20000)
    check(f"[{p.tag}] her password still works", page.is_visible("#settings-open"))
    p.finish(server_mode=True)


def walk_demo(p: Pass) -> None:
    page = p.page
    page.goto("/?mock=1")
    page.wait_for_selector("#form-login:not([hidden]), #settings-open", timeout=30000)
    if page.is_visible("#form-login"):
        check(f"[{p.tag}] the demo's sign-in page has no passkey button", not page.is_visible("#login-passkey-btn"))
        page.fill("#login-username", "sam")
        page.fill("#login-password", "any demo password at all 15")
        page.click("#login-submit")
    page.wait_for_selector("#settings-open", state="visible", timeout=30000)
    page.click("#settings-open")
    page.wait_for_selector("#set-passkeys p.hint", timeout=20000)
    text = text_of(page, "#set-passkeys")
    check(f"[{p.tag}] the demo says it has no passkeys and shows no button",
          "demo has no real sign-in" in text and not page.locator("#set-passkey-add").count(), text)
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
    try:
        server.start()
        admin = first_admin(server, "passkeyadmin")
        ana_browser = invite_user(server, admin, "ana")
        ana_api = khserver.Api(server.base.replace("127.0.0.1", "localhost"))
        ana_api.login("ana")
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                ana = Pass(browser, base, out, 375, 812, "light", "ana-375-light", ana_browser.cookies(), authenticator=True)
                walk_ana(ana, ana_api)
                walk_admin(Pass(browser, base, out, 1280, 800, "dark", "admin-1280-dark", admin.cookies()), admin)
                walk_ana_after(ana)
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
