#!/usr/bin/env python3
"""Password reset by email (design note 34) in Chromium, against a real server and a fake mail server.

    python3 tools/e2e/reset_email.py                    # port 8117
    python3 tools/e2e/reset_email.py --port 8117 --out /tmp/kh-reset-email

Starts the real app on a fresh ``DATA_DIR`` with ``EMAIL_ENABLED``, ``SMTP_SECURITY=none`` and ``SMTP_HOST=127.0.0.1``, pointing at
the small SMTP server of ``tests/fake_smtp.py`` in this process. Walks, at 375x812 light:

* Settings → Account → Email for password resets: save an address, the confirmation email arrives, its link (opened in the same
  tab) confirms the address and leaves the address bar; the block then says "Confirmed".
* Signed out: a confirmation link opened on a fresh page says the email is confirmed on the sign-in screen.
* Signed out: Forgot your password? → the user name → the same sentence as for any name; the reset email's link opens the
  reset screen with the user name; a new password signs in.
* No console error, CSP violation, dialog, sideways scroll or other host; the server log never holds an address or a link.

Nothing leaves the machine. Prints PASS / FAIL lines and writes ``<out>/report.json`` and screenshots; exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import email
import email.policy
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright
from sharing import RESULTS, Pass, check, text_of, wait_text

sys.path.insert(0, str(khserver.REPO / "tests"))
from fake_smtp import FakeSmtp  # noqa: E402

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "reset-email"
PORT = 8117
NEW_PASSWORD = "a fresh walk through the meadow"


def link_in(message: dict, kind: str) -> str:
    body = email.message_from_string(message["data"], policy=email.policy.default).get_content()
    found = re.search(rf"(http://\S+/#/{kind}/\S+)", body)
    assert found, body
    return found.group(1)


def walk_settings(p: Pass, smtp: FakeSmtp) -> str:
    page = p.page
    page.goto("/#settings")
    page.wait_for_selector("#set-email-input", timeout=30000)
    check(f"[{p.tag}] Settings shows Email for password resets", "Email for password resets" in text_of(page, "#set-email"))
    page.fill("#set-email-input", "Mum@Example.org")
    page.click("#set-email-save")
    wait_text(page, "#set-email-msg", "We sent a link to mum@example.org")
    check(f"[{p.tag}] the address is not confirmed yet", "Not confirmed yet" in text_of(page, "#set-email"))
    p.shot("email-saved", "#set-email")
    link = link_in(smtp.wait(1)[0], "confirm-email")
    page.goto(link)  # the same document: the hashchange path
    page.wait_for_function("() => !location.hash.includes('confirm-email')", timeout=15000)
    wait_text(page, "body", "Your email is confirmed")
    check(f"[{p.tag}] the link left the address bar", "confirm-email" not in page.url, page.url)
    page.goto("/#settings")
    page.reload()
    wait_text(page, "#set-email", "Confirmed")
    check(f"[{p.tag}] the block says Confirmed", "Confirmed" in text_of(page, "#set-email"))
    p.no_overflow("Settings → Account")
    p.shot("email-confirmed", "#set-email")
    return link


def walk_confirm_signed_out(p: Pass, link: str) -> None:
    page = p.page
    page.goto(link)
    page.wait_for_function("() => (document.querySelector('#auth-notice')?.innerText || '') + (document.querySelector('#auth-error')?.innerText || '')",
                           timeout=15000)
    check(f"[{p.tag}] a used confirmation link says so on the sign-in screen", "not valid any more" in text_of(page, "#auth-error"),
          text_of(page, "#auth-error"))
    check(f"[{p.tag}] the link left the address bar", "confirm-email" not in page.url, page.url)


def walk_forgot(p: Pass, smtp: FakeSmtp) -> None:
    page = p.page
    page.goto("/")
    page.wait_for_selector("#login-forgot:not([hidden])", timeout=30000)
    check(f"[{p.tag}] the sign-in page offers Forgot your password?", text_of(page, "#login-forgot") == "Forgot your password?")
    check(f"[{p.tag}] the ask-your-admin hint is hidden", not page.is_visible("#login-forgot-help"))
    page.click("#login-forgot")
    page.wait_for_selector("#form-forgot:not([hidden])")
    p.shot("forgot", "#view-auth")
    page.fill("#forgot-username", "nobody-here")
    page.click("#forgot-submit")
    wait_text(page, "#auth-notice", "If that account has a confirmed email")
    unknown = text_of(page, "#auth-notice")
    page.click("#login-forgot")
    page.fill("#forgot-username", "mum")
    page.click("#forgot-submit")
    wait_text(page, "#auth-notice", "If that account has a confirmed email")
    check(f"[{p.tag}] the same words for an unknown name and a real one", text_of(page, "#auth-notice") == unknown, unknown)
    messages = smtp.wait(2)
    check(f"[{p.tag}] one reset email, to mum", len(messages) == 2 and messages[-1]["rcpt"] == ["mum@example.org"])
    link = link_in(messages[-1], "reset")
    page.goto(link)
    page.wait_for_selector("#form-reset:not([hidden])")
    check(f"[{p.tag}] the reset screen shows the user name", page.input_value("#reset-username") == "mum")
    page.fill("#reset-password", NEW_PASSWORD)
    page.click("#reset-submit")
    page.wait_for_selector("#view-auth", state="hidden", timeout=15000)
    check(f"[{p.tag}] the new password signed in", page.is_hidden("#view-auth"))
    p.no_overflow("after the reset")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{args.port}"
    with FakeSmtp() as smtp:
        env = {"EMAIL_ENABLED": "true", "PUBLIC_URL": base, "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(smtp.port),
               "SMTP_SECURITY": "none", "SMTP_FROM": "Kidney Health <kidney@example.org>", "SMTP_TIMEOUT_S": "5"}
        server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
        try:
            server.start()
            admin = first_admin(server, "mum")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
                try:
                    p = Pass(browser, server.base, out, 375, 812, "light", "settings-375-light", admin.cookies())
                    link = walk_settings(p, smtp)
                    p.finish()
                    p = Pass(browser, server.base, out, 375, 812, "light", "confirm-375-light")
                    walk_confirm_signed_out(p, link)
                    p.finish(refused=["POST /api/auth/email/confirm"])
                    p = Pass(browser, server.base, out, 375, 812, "light", "forgot-375-light")
                    walk_forgot(p, smtp)
                    p.finish()
                finally:
                    browser.close()
            log = server.log()
            check("the server log holds no address and no link", "example.org" not in log.replace("kidney@example.org", "")
                  and "#/reset/" not in log and "#/confirm-email/" not in log)
            check("the server log says email sent", "email sent" in log)
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
