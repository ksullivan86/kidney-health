#!/usr/bin/env python3
"""Test accounts and Send feedback (design note 26) in Chromium, against a real server and the demo.

    python tools/e2e/test_accounts.py                     # port 8094
    python tools/e2e/test_accounts.py --port 8094 --out /tmp/kh-testers

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``TEST_ACCOUNT_ENABLED=true``, ``SHARING_ENABLED=true`` and a password
file, and finishes first-run setup (which makes tester and tester-helper). Walks:

* tester at 375x812 light: Today shows Sam's sample day; the Send feedback button is in the header; the sheet starts "Today: ",
  says only what is typed is sent, and sends; "What you sent" lists it; on Plan the sheet starts "Plan: ";
* tester-helper at 1280x800 dark: Settings → Care team lists Sam as a Care helper's person; Send feedback is there too;
* the admin at 1280x800 dark: no Send feedback button; Server administration shows Test accounts (both On) and Feedback (the
  item, marked "wrong or unsafe"); Mark done; Server settings has the Test accounts group; Reset test accounts asks first, then
  the testers' sessions end;
* the demo (``/?mock=1``): no Send feedback button and no test accounts in Server settings; nothing asked of /api/feedback;
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
from pathlib import Path

import khserver
import sharing
from khserver import Api, Server, first_admin
from playwright.sync_api import sync_playwright
from sharing import RESULTS, Pass, answer_reauth, check, text_of, wait_text

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "test-accounts"
PORT = 8094
TEST_PASSWORD = "lantern-meadow-quartz-91"


def send_feedback(p: Pass, view: str, screen: str, happened: str, unsafe: bool = False) -> None:
    page = p.page
    page.goto(f"/#{view}")
    page.wait_for_selector("#feedback-open", state="visible", timeout=30000)
    page.click("#feedback-open")
    page.wait_for_selector("#sheet-feedback[open]")
    trying = page.input_value("#feedback-trying")
    check(f"[{p.tag}] on {screen} the sheet starts with the screen's name", trying == f"{screen}: ", trying)
    check(f"[{p.tag}] the sheet says only what is typed is sent", "Only what you type here is sent" in text_of(page, "#sheet-feedback-sub"))
    page.fill("#feedback-trying", f"{screen}: look around")
    page.fill("#feedback-happened", happened)
    page.click("label[for=fuseful-somewhat]")
    if unsafe:
        page.check("#feedback-unsafe")
    p.shot(f"feedback-{view}", "#sheet-feedback")
    page.click("#feedback-send")
    page.wait_for_function("() => !document.querySelector('#sheet-feedback').open", timeout=15000)
    wait_text(page, "#toast", "Your feedback was sent")
    check(f"[{p.tag}] sent from {screen}", True)


def walk_tester(p: Pass) -> None:
    page = p.page
    page.goto("/#today")
    page.wait_for_selector("#feedback-open", state="visible", timeout=30000)
    check(f"[{p.tag}] Send feedback is in the header", page.get_attribute("#feedback-open", "aria-label") == "Send feedback")
    send_feedback(p, "today", "Today", "The low treatment button was easy to find", unsafe=True)
    page.click("#feedback-open")
    page.wait_for_selector("#sheet-feedback[open]")
    wait_text(page, "#feedback-mine", "easy to find")
    check(f"[{p.tag}] What you sent lists it", "Looked wrong or unsafe" in text_of(page, "#feedback-mine"))
    p.no_overflow("feedback sheet")
    page.click("#sheet-feedback [data-close]")
    send_feedback(p, "plan", "Plan", "The shopping list opened")
    p.no_overflow("plan")
    p.finish()


def walk_helper(p: Pass) -> None:
    page = p.page
    page.goto("/#settings")
    page.wait_for_selector("#set-care:not([hidden])", timeout=30000)
    wait_text(page, "#set-care", "Sam")
    check(f"[{p.tag}] tester-helper is on Sam's Care team", "Sam" in text_of(page, "#set-care"), text_of(page, "#set-care")[:300])
    check(f"[{p.tag}] Settings says it is a test account", "test account" in text_of(page, "#settings-who"))
    check(f"[{p.tag}] Send feedback is there too", page.is_visible("#feedback-open"))
    p.finish()


def walk_admin(p: Pass, tester: Api) -> None:
    page = p.page
    page.goto("/#admin")
    page.wait_for_selector("#set-testers li", timeout=30000)
    check(f"[{p.tag}] an admin has no Send feedback button", not page.is_visible("#feedback-open"))
    testers = text_of(page, "#set-testers")
    check(f"[{p.tag}] Test accounts lists both, on", "tester" in testers and "tester-helper" in testers and "On" in testers, testers[:300])
    wait_text(page, "#set-feedback", "easy to find")
    fb = text_of(page, "#set-feedback")
    check(f"[{p.tag}] Feedback shows what testers sent", "tester" in fb and "Looked wrong or unsafe" in fb and "Plan" in fb, fb[:400])
    check(f"[{p.tag}] Server settings has the Test accounts group", "Test accounts: let testers sign in" in text_of(page, "#set-server"))
    p.shot("admin-feedback", "#set-feedback")
    page.locator("#set-feedback").get_by_role("button", name="Mark done").first.click()
    answer_reauth(page)
    wait_text(page, "#set-feedback", "1 done")
    check(f"[{p.tag}] Mark done", "1 done" in text_of(page, "#set-feedback"))
    page.click("#testers-reset")
    check(f"[{p.tag}] Reset asks first", "start them again" in text_of(page, "#set-testers"))
    page.locator("#set-testers").get_by_role("button", name="Reset", exact=True).click()
    answer_reauth(page)
    wait_text(page, "#toast", "Test accounts reset")
    check(f"[{p.tag}] Reset signs the testers out", tester.call("GET", "/api/me").status_code == 401)
    p.no_overflow("admin")
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
    check(f"[{p.tag}] the demo has no Send feedback button", not page.is_visible("#feedback-open"))
    page.goto("/?mock=1#admin")
    page.wait_for_selector("#set-server .setting-list", timeout=30000)
    check(f"[{p.tag}] the demo has no test accounts in Server settings", "Test accounts" not in text_of(page, "#set-server"))
    check(f"[{p.tag}] the demo has no Test accounts or Feedback part", not page.is_visible("#set-testers") and not page.is_visible("#set-feedback"))
    check(f"[{p.tag}] the demo asked nothing of /api/feedback", not any("/api/feedback" in r or "/test-accounts" in r for r in p.watch.requests))
    p.finish()


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
    secret = out / "test-account-password"
    secret.write_text(TEST_PASSWORD + "\n", encoding="utf-8")
    secret.chmod(0o600)
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook"),
           "TEST_ACCOUNT_ENABLED": "true", "SHARING_ENABLED": "true", "TEST_ACCOUNT_PASSWORD_FILE": str(secret)}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, "testadmin")
        tester, helper = Api(server.base), Api(server.base)
        tester.login("tester", TEST_PASSWORD)
        helper.login("tester-helper", TEST_PASSWORD)
        check("first-run setup made both test accounts", tester.json("GET", "/api/me")["test_account"] is True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                walk_tester(Pass(browser, server.base, out, 375, 812, "light", "tester-375-light", tester.cookies()))
                walk_helper(Pass(browser, server.base, out, 1280, 800, "dark", "helper-1280-dark", helper.cookies()))
                walk_admin(Pass(browser, server.base, out, 1280, 800, "dark", "admin-1280-dark", admin.cookies()), tester)
                walk_demo(Pass(browser, server.base, out, 375, 812, "light", "demo-375-light"))
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


__all__ = ["main", "sharing"]

if __name__ == "__main__":
    sys.exit(main())
