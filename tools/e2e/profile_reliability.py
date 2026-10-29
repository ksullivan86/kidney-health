#!/usr/bin/env python3
"""Profile reliability: delayed suggestions preserve edits; failed saves keep entries for retry.

    PLAYWRIGHT_CHROMIUM=/usr/bin/chromium python tools/e2e/profile_reliability.py

Uses a temporary local server and synthetic delays; no external AI or clinical service is called.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "kidney-health-e2e" / "profile-reliability")
    args = parser.parse_args()
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    results = []

    def check(name: str, ok: bool) -> None:
        results.append({"check": name, "ok": bool(ok)})
        print(f"{'PASS' if ok else 'FAIL'} {name}", flush=True)

    server = Server(args.port, out / "data", log_path=out / "server.log",
                    env={"HANDBOOK_DIR": str(out / "no-handbook")})
    try:
        server.start()
        ana = first_admin(server, "ana")
        ana.json("PUT", "/api/profile", {"weight_kg": 70, "height_cm": 170, "ckd_stage": "3b", "diabetes": "type1",
                                         "targets": {"potassium_mg": 2500}})
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                ctx = browser.new_context(viewport={"width": 390, "height": 844}, base_url=server.base)
                ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in ana.cookies().items()])
                page = ctx.new_page()
                page.goto("/")
                page.click("#tab-profile")
                page.wait_for_function("() => document.querySelector('#pf-weight').value === '70'")
                page.evaluate("""async () => {
                  window.suggestionReply = await KH.api.suggested();
                  window.originalSuggested = KH.api.suggested;
                  KH.api.suggested = () => new Promise(resolve => { window.releaseSuggestion = resolve; });
                }""")
                for selector, changed, label in (("#tg-potassium_mg", "1800", "care-team target"),
                                                  ("#pf-weight", "90", "profile weight")):
                    page.evaluate("() => KH.views.profile.renderProfile()")
                    page.click("#btn-suggest")
                    page.wait_for_function("() => typeof window.releaseSuggestion === 'function'")
                    page.fill(selector, changed)
                    page.evaluate("() => { window.releaseSuggestion(window.suggestionReply); window.releaseSuggestion = null; }")
                    page.wait_for_function("() => !document.querySelector('#btn-suggest').disabled")
                    check(f"A late suggestion keeps the edited {label}", page.input_value(selector) == changed)
                    check(f"The changed {label} has a notice and no suggestion panel",
                          "kept" in page.inner_text("#suggest-live") and not page.is_visible("#suggest-notes"))
                page.evaluate("() => { KH.api.suggested = window.originalSuggested; KH.views.profile.renderProfile(); }")
                page.click("#btn-suggest")
                page.wait_for_function("() => !document.querySelector('#btn-suggest').disabled")
                check("Suggest again fills an unchanged form and leaves it unsaved",
                      page.is_visible("#suggest-notes") and ana.json("GET", "/api/profile")["targets"]["potassium_mg"] == 2500)
                page.fill("#pf-name", "Retry profile")
                page.fill("#tg-potassium_mg", "1800")
                pattern = "**/api/profile"
                page.route(pattern, lambda route: route.fulfill(status=500, content_type="application/json",
                                                                body=json.dumps({"detail": "Test save failure"})))
                with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith("/api/profile")):
                    page.click("#btn-save-profile")
                page.wait_for_function("() => !document.querySelector('#btn-save-profile').disabled")
                check("A failed save keeps the name and target available to retry",
                      page.input_value("#pf-name") == "Retry profile" and page.input_value("#tg-potassium_mg") == "1800")
                check("A failed save has not changed the stored target", ana.json("GET", "/api/profile")["targets"]["potassium_mg"] == 2500)
                page.unroute(pattern)
                with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith("/api/profile")):
                    page.click("#btn-save-profile")
                page.wait_for_function("() => !document.querySelector('#btn-save-profile').disabled")
                saved = ana.json("GET", "/api/profile")
                check("Retry saves the preserved profile entries", saved["name"] == "Retry profile" and saved["targets"]["potassium_mg"] == 1800)
                ctx.close()
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        check("The walk ran to the end", False)
    finally:
        server.stop()
    (out / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    failed = sum(not item["ok"] for item in results)
    print(f"{len(results) - failed} passed, {failed} failed; report: {out / 'report.json'}")
    return 1 if failed or not results else 0


if __name__ == "__main__":
    sys.exit(main())
