#!/usr/bin/env python3
"""Failed health saves keep entries for retry: weight, blood pressure and Labs, against a temporary real server.

    python tools/e2e/health_save_retry.py

Routes the first POST to a 500, then lets the identical retry reach the server. No external service is used.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8102)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "kidney-health-e2e" / "health-save-retry")
    args = parser.parse_args()
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    results = []

    def check(name: str, ok: bool) -> None:
        results.append({"check": name, "ok": bool(ok)})
        print(f"{'PASS' if ok else 'FAIL'} {name}", flush=True)

    server = Server(args.port, out / "data", log_path=out / "server.log", env={"HANDBOOK_DIR": str(out / "no-handbook")})
    try:
        server.start()
        admin = first_admin(server, "retryadmin")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for index, (width, height, scheme) in enumerate(((375, 812, "light"), (1280, 800, "dark"))):
                    tag = f"{width}-{scheme}"
                    person = invite_user(server, admin, f"retry{index}")
                    person.json("PUT", "/api/profile", {"weight_kg": 70, "ckd_stage": "3b", "diabetes": "type1"})
                    person.json("PATCH", "/api/me/settings", {"user.units.weight": "kg"})
                    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=server.base)
                    try:
                        ctx.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in person.cookies().items()])
                        page = ctx.new_page()
                        page.goto("/")
                        page.wait_for_function("() => document.querySelector('#body-today-body').innerText.includes('No weight or blood pressure')")

                        def retry(name: str, path: str, key: str, button: str, fields: dict[str, str], host: str) -> None:
                            attempts: list[dict[str, Any]] = []
                            params = {"start": date.today().isoformat(), "end": date.today().isoformat()} if path.startswith("/api/body/") else None

                            def sent(request: Any) -> None:
                                if request.method == "POST" and urlsplit(request.url).path == path:
                                    attempts.append(json.loads(request.post_data))

                            def fail(route: Any) -> None:
                                if route.request.method == "POST":
                                    route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "Test save failure"}))
                                else:
                                    route.continue_()

                            pattern = f"**{path}"
                            page.on("request", sent)
                            page.route(pattern, fail)
                            try:
                                with page.expect_response(lambda response: response.request.method == "POST" and urlsplit(response.url).path == path) as response:
                                    page.click(button)
                                check(f"[{tag}] {name}: the first save reached the injected 500", response.value.status == 500)
                                page.wait_for_function("(selector) => !document.querySelector(selector).disabled", arg=button)
                                check(f"[{tag}] {name}: failed save keeps every typed field for retry",
                                      page.is_visible(host) and all(page.input_value(selector) == value for selector, value in fields.items()))
                                check(f"[{tag}] {name}: no row was stored after failure", person.json("GET", path, params=params)[key] == [])
                                page.unroute(pattern, fail)
                                with page.expect_response(lambda response: response.request.method == "POST" and urlsplit(response.url).path == path) as response:
                                    page.click(button)
                                check(f"[{tag}] {name}: retry is accepted by the server", response.value.status == 201)
                                page.wait_for_function("(selector) => !document.querySelector(selector).disabled", arg=button)
                                rows = person.json("GET", path, params=params)[key]
                                check(f"[{tag}] {name}: exactly one row is stored and retry sent the same body",
                                      len(rows) == 1 and len(attempts) == 2 and attempts[0] == attempts[1])
                            finally:
                                page.unroute(pattern, fail)
                                page.remove_listener("request", sent)

                        page.click("#body-add-weight")
                        weight = {"#weight-value": "70.2", "#weight-note": "Keep weight note", "#weight-time": "07:15"}
                        for selector, value in weight.items():
                            page.fill(selector, value)
                        page.click("label[for=weight-context-morning]")
                        retry("Weight", "/api/body/weights", "weights", "#weight-save", weight, "#sheet-weight")

                        page.click("#body-add-bp")
                        bp = {"#bp-systolic": "128", "#bp-diastolic": "78", "#bp-pulse": "65", "#bp-note": "Keep reading note"}
                        for selector, value in bp.items():
                            page.fill(selector, value)
                        page.click("label[for=bp-context-morning]")
                        retry("Blood pressure", "/api/body/blood-pressure", "readings", "#bp-save", bp, "#sheet-bp")

                        page.click("#tab-profile")
                        page.click("#pf-open-labs")
                        page.select_option("#lab-analyte", "potassium")
                        page.select_option("#lab-unit", "mmol/L")
                        lab = {"#lab-value": "4.6", "#lab-date": date.today().isoformat(), "#lab-note": "Keep result note"}
                        for selector, value in lab.items():
                            page.fill(selector, value)
                        retry("Lab result", "/api/labs", "labs", "#lab-save", lab, "#lab-form")
                    finally:
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
