#!/usr/bin/env python3
"""Sign-in with a provider (design note 24) in Chromium, against a real server and a fake OpenID Connect provider on localhost.

    python3 tools/e2e/oidc.py                    # the app on 8251, the providers on 8252 and 8253
    python3 tools/e2e/oidc.py --port 8251 --idp-port 8252 --out /tmp/kh-oidc

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``OIDC_ENABLED=true`` and ``OIDC_ISSUER`` at a small provider in this
process (discovery, an authorization page that says yes at once for the account the walk chooses, the token endpoint with PKCE and
the client secret, the keys; ID tokens signed with RS256, from ``tests/oidc_support.py``). ``OIDC_ALLOW_PRIVATE_ISSUER=true``
because the provider is on 127.0.0.1. Walks, at 375x812:

* the sign-in page shows "Sign in with Authentik" (a link, no script); pressing it as someone the server does not know comes back
  to the sign-in page with "There is no account here for that sign-in" and nobody signed in;
* the admin signs in with the password; Settings → Account → Linked sign-in → Link Authentik goes to the provider and back, the page
  says "Linked." and lists the link;
* signed out, the button signs the admin in with no password: the app shows Today;
* a second provider, "google" in ``OIDC_PROVIDERS`` (a public client on the next port, design note 24 §13): its own button on the
  sign-in page (``?provider=google``), **Link Google** in Settings next to the Authentik link, and its button signs the admin in;
* restarted with ``OIDC_ONLY=true``: no password form, the two provider buttons, and they still sign the admin in;
* the demo (``/?mock=1``): no button;
* no console error, no CSP violation, no browser dialog, no sideways scroll, and the browser asked only the app and the provider;
* the server's access log shows the callback's ``code`` and ``state`` as ``[redacted]``.

Nothing leaves the machine. Prints PASS / FAIL lines and writes ``<out>/report.json``; exit status 1 on any failure. No screenshots.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx2

import khserver
from khserver import DEFAULT_PASSWORD, Server, first_admin
from playwright.sync_api import sync_playwright

sys.path[:0] = [str(khserver.REPO), str(khserver.REPO / "tests")]
from oidc_support import FakeProvider  # noqa: E402

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "oidc"
PORT, IDP_PORT = 8251, 8252
CLIENT_ID, CLIENT_SECRET = "kidney-walk", "walk-secret-0123456789abcdef0123"
RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def serve_provider(port: int, client_secret: str | None = CLIENT_SECRET, who: dict[str, Any] | None = None
                   ) -> tuple[ThreadingHTTPServer, FakeProvider, dict[str, Any]]:
    """The fake provider over real HTTP. ``who["sub"]`` is the account its authorization page says yes for."""
    provider = FakeProvider(issuer=f"http://127.0.0.1:{port}", client_id=CLIENT_ID, client_secret=client_secret)
    who = who if who is not None else {"sub": "stranger", "email": "stranger@example.org"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # quiet
            pass

        def _send(self, response: httpx2.Response) -> None:
            self.send_response(response.status_code)
            for k, v in response.headers.items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(k, v)
            body = response.content
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.startswith("/authorize"):
                location = f"{provider.base}{self.path}"
                code, state, query = provider.authorize(location, claims={"sub": who["sub"], "email": who["email"]})
                self.send_response(302)
                self.send_header("Location", f"{query['redirect_uri']}?{urlencode({'code': code, 'state': state, 'iss': provider.issuer})}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send(provider.handler(httpx2.Request("GET", f"{provider.base}{self.path}")))

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            request = httpx2.Request("POST", f"{provider.base}{self.path}", content=body, headers=dict(self.headers))
            self._send(provider.handler(request))

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, provider, who


def text_of(page: Any, selector: str) -> str:
    return page.evaluate("(sel) => { const el = document.querySelector(sel); return el ? el.innerText.replace(/\\s+/g, ' ').trim() : ''; }", selector)


def walk(base: str, idp: str, idp2: str, who: dict[str, Any], out: Path) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=khserver.chromium_executable())
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, base_url=base)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        errors: list[str] = []
        dialogs: list[str] = []
        hosts: set[str] = set()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "status of 401" not in m.text else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        page.on("request", lambda r: hosts.add(urlsplit(r.url).netloc) if r.url.startswith("http") else None)
        page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")

        # 1. Someone the server does not know
        page.goto("/")
        page.wait_for_selector("#login-oidc-btn", state="visible")
        check("the sign-in page shows the provider's button in the admin's words", page.inner_text("#login-oidc-btn") == "Sign in with Authentik",
              page.inner_text("#login-oidc-btn"))
        check("the button is a plain link", page.get_attribute("#login-oidc-btn", "href") == "api/auth/oidc/start")
        page.click("#login-oidc-btn")
        page.wait_for_function("() => document.querySelector('#auth-error') && document.querySelector('#auth-error').innerText.length > 0")
        check("an unknown account comes back to the sign-in page with a plain sentence",
              "There is no account here for that sign-in" in text_of(page, "#auth-error"), text_of(page, "#auth-error"))
        check("the address bar no longer shows the result word", "#/oidc/" not in page.url, page.url)
        check("nobody is signed in", page.evaluate("() => document.body.classList.contains('signed-out')"))

        # 2. The admin links the provider from Settings
        page.fill("#login-username", "mum")
        page.fill("#login-password", DEFAULT_PASSWORD)
        page.click("#login-submit")
        page.wait_for_selector("#view-today:not([hidden])")
        page.goto("/#settings")
        page.wait_for_selector("#set-oidc-link", state="visible")
        check("Settings lists nothing linked yet", "Nothing linked yet." in text_of(page, "#set-oidc"), text_of(page, "#set-oidc"))
        who.update(sub="mum-sub", email="mum@example.org")
        page.click("#set-oidc-link")
        page.wait_for_selector("#set-oidc-list")
        page.wait_for_function("() => document.querySelector('.toast.show') && document.querySelector('.toast.show').innerText.includes('Linked.')")
        check("back in Settings, the page says it is linked", "Linked. You can now sign in with Authentik." in text_of(page, ".toast"))
        check("the link is listed with the provider and the email", "mum@example.org" in text_of(page, "#set-oidc-list"), text_of(page, "#set-oidc-list"))
        check("no sideways scroll in Settings", not page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))

        # 3. Signed out, the provider signs the admin in
        page.evaluate("() => KH.auth.signOut()")
        page.wait_for_selector("#login-oidc-btn", state="visible")
        page.click("#login-oidc-btn")
        page.wait_for_selector("#view-today:not([hidden])")
        me = page.evaluate("() => fetch('/api/me').then((r) => r.json())")
        check("the button signs the admin in with no password", me.get("username") == "mum", str(me))

        # 4. A second provider: its own button, its own link in Settings
        page.goto("/#settings")
        page.wait_for_selector("#set-oidc-link-google", state="visible")
        check("Settings offers to link the second provider by its name", page.inner_text("#set-oidc-link-google") == "Link Google",
              page.inner_text("#set-oidc-link-google"))
        who.update(sub="mum-google", email="mum@example.net")
        page.click("#set-oidc-link-google")
        page.wait_for_function("() => document.querySelector('.toast.show') && document.querySelector('.toast.show').innerText.includes('Linked.')")
        check("back in Settings, the page names the second provider", "Linked. You can now sign in with Google." in text_of(page, ".toast"),
              text_of(page, ".toast"))
        page.wait_for_function("() => document.querySelectorAll('#set-oidc-list li').length === 2")
        listed = text_of(page, "#set-oidc-list")
        check("both links are listed, each with its name", "Authentik" in listed and "Google" in listed and "mum@example.net" in listed, listed)
        check("nothing is left to link", not page.is_visible("#set-oidc-link") and not page.is_visible("#set-oidc-link-google"))
        page.evaluate("() => KH.auth.signOut()")
        page.wait_for_selector("#login-oidc-btn-google", state="visible")
        check("the sign-in page shows a button for each provider",
              page.inner_text("#login-oidc-btn") == "Sign in with Authentik" and page.inner_text("#login-oidc-btn-google") == "Sign in with Google")
        check("the second button is a plain link to its provider",
              page.get_attribute("#login-oidc-btn-google", "href") == "api/auth/oidc/start?provider=google")
        page.click("#login-oidc-btn-google")
        page.wait_for_selector("#view-today:not([hidden])")
        me = page.evaluate("() => fetch('/api/me').then((r) => r.json())")
        check("the second provider signs the admin in", me.get("username") == "mum", str(me))

        csp = page.evaluate("window.__csp || []")
        check("no console error, no CSP violation, no browser dialog", not errors and not csp and not dialogs, "; ".join(errors + csp + dialogs))
        allowed = {urlsplit(base).netloc, urlsplit(idp).netloc, urlsplit(idp2).netloc}
        check("the browser asked only the app and the providers", hosts <= allowed, str(sorted(hosts - allowed)))
        ctx.close()

        # 5. The demo has no provider
        demo = browser.new_context(viewport={"width": 375, "height": 812}, base_url=base)
        dpage = demo.new_page()
        dpage.goto("/?mock=1")
        dpage.wait_for_function("() => !!document.querySelector('#view-today:not([hidden])') || !!document.querySelector('#form-login:not([hidden])')")
        check("the demo shows no provider button", not dpage.is_visible("#login-oidc-btn"))
        demo.close()
        browser.close()


def walk_only(base: str, who: dict[str, Any]) -> None:
    """The same server restarted with OIDC_ONLY=true: only the provider buttons, and they still work."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=khserver.chromium_executable())
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, base_url=base)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        errors: list[str] = []
        # the 403 of the password the walk sends on purpose is expected; anything else is not
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not any(s in m.text for s in ("status of 401", "status of 403")) else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("/")
        page.wait_for_selector("#login-oidc-btn-google", state="visible")
        check("OIDC_ONLY: no username or password field and no Sign in button",
              not page.is_visible("#login-username") and not page.is_visible("#login-password") and not page.is_visible("#login-submit"))
        check("OIDC_ONLY: the page says how people sign in", page.is_visible("#login-only-note"), text_of(page, "#login-only-note"))
        check("OIDC_ONLY: no test-account button while the test accounts are off", not page.is_visible("#login-test-toggle"))
        r = page.evaluate("""() => fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json',
            'X-Requested-With': 'kidney-health'}, body: JSON.stringify({username: 'mum', password: 'x'.repeat(20)})}).then((r) => r.status)""")
        check("OIDC_ONLY: the server refuses a password", r == 403, str(r))
        who.update(sub="mum-sub", email="mum@example.org")
        page.click("#login-oidc-btn")
        page.wait_for_selector("#view-today:not([hidden])")
        me = page.evaluate("() => fetch('/api/me').then((r) => r.json())")
        check("OIDC_ONLY: the provider signs the admin in", me.get("username") == "mum", str(me))
        check("OIDC_ONLY: no console error", not errors, "; ".join(errors))
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--idp-port", type=int, default=IDP_PORT)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--python", default=None, help="the Python that runs the server (default: this one)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    httpd, provider, who = serve_provider(args.idp_port)
    httpd2, provider2, _ = serve_provider(args.idp_port + 1, client_secret=None, who=who)  # "google": a public client
    secret = args.out / "oidc_client_secret"
    secret.write_text(CLIENT_SECRET + "\n", encoding="utf-8")
    os.chmod(secret, 0o600)
    base = f"http://127.0.0.1:{args.port}"
    env = {"PUBLIC_URL": base, "OIDC_ENABLED": "true", "OIDC_ISSUER": provider.issuer, "OIDC_CLIENT_ID": CLIENT_ID,
           "OIDC_CLIENT_SECRET_FILE": str(secret), "OIDC_ALLOW_PRIVATE_ISSUER": "true", "OIDC_BUTTON_LABEL": "Sign in with Authentik",
           "OIDC_PROVIDERS": "google", "OIDC_GOOGLE_ISSUER": provider2.issuer, "OIDC_GOOGLE_CLIENT_ID": CLIENT_ID,
           "OIDC_GOOGLE_ALLOW_PRIVATE_ISSUER": "true",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, args.out / "data", env=env, python=args.python)
    try:
        server.start()
        first_admin(server, "mum")
        walk(base, provider.issuer, provider2.issuer, who, args.out)
        check("the server log holds no token and no secret",
              CLIENT_SECRET not in server.log() and "access-token-never-stored" not in server.log())
        check("the access log shows the callback's code and state redacted",
              "callback?code=[redacted]&state=[redacted]" in server.log() and "callback/google?code=[redacted]" in server.log())
        server.stop()
        server = Server(args.port, args.out / "data", env={**env, "OIDC_ONLY": "true"}, python=args.python, fresh=False,
                        log_path=args.out / "data-only-server.log")
        server.start()
        walk_only(base, who)
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc().splitlines()[-1])
    finally:
        server.stop()
        httpd.shutdown()
        httpd2.shutdown()
    (args.out / "report.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
