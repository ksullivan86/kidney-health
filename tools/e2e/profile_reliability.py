#!/usr/bin/env python3
"""Profile reliability: delayed suggestions preserve edits; failed saves keep entries for retry; height and weight units.

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


def height_walk(page, person, check) -> None:
    """Height in feet and inches by default, centimetres from Settings (user.units.height); the profile keeps centimetres."""
    person.json("PUT", "/api/profile", {"height_cm": 170.2})
    page.evaluate("() => KH.loadProfile(true).then(() => KH.views.profile.renderProfile())")
    page.wait_for_function("() => document.querySelector('#pf-height-ft').value === '5'")
    check("A saved 170.2 cm shows as 5 ft 7 in, in two labelled boxes",
          page.is_visible("#pf-height-ftin-field") and not page.is_visible("#pf-height-cm-field")
          and page.input_value("#pf-height-in") == "7" and page.get_by_label("Height (feet)").count() == 1
          and page.get_by_role("group", name="Height").count() == 1)
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/profile")):
        page.click("#btn-save-profile")
    check("Saving without touching the height keeps 170.2 cm", person.json("GET", "/api/profile")["height_cm"] == 170.2)
    page.fill("#pf-height-ft", "5")
    page.fill("#pf-height-in", "10")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/profile")):
        page.click("#btn-save-profile")
    check("5 ft 10 in is saved as 178 cm", person.json("GET", "/api/profile")["height_cm"] == 178)
    page.click("#settings-open")
    page.wait_for_function("() => document.querySelector('#set-height-units').value === 'ft_in'")
    with page.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith("/api/me/settings")):
        page.select_option("#set-height-units", "cm")
    check("Settings saves Units for height", person.json("GET", "/api/me/settings")["settings"]["user.units.height"]["value"] == "cm")
    page.click("#tab-profile")
    page.wait_for_function("() => !document.querySelector('#pf-height-cm-field').hidden")
    check("Profile then shows the height in centimetres", page.input_value("#pf-height") == "178" and not page.is_visible("#pf-height-ftin-field"))
    person.json("PATCH", "/api/me/settings", {"user.units.height": "ft_in"})


def weight_walk(page, person, check) -> None:
    """Profile's two weights in pounds by default, kilograms from Settings (user.units.weight); the profile keeps kilograms."""
    person.json("PUT", "/api/profile", {"weight_kg": 70.23, "weight_6_months_ago_kg": 74})
    page.click("#tab-profile")
    page.evaluate("() => KH.loadProfile(true).then(() => KH.views.profile.renderProfile())")
    page.wait_for_function("() => document.querySelector('#pf-weight').value === '154.8'")
    check("A saved 70.23 kg shows as 154.8 lb, and 74 kg six months ago as 163.1 lb",
          page.input_value("#pf-weight-6mo") == "163.1" and page.get_by_label("Weight (lb)").count() == 1
          and page.get_by_label("Weight 6 months ago (lb)").count() == 1)
    check("The pounds boxes take 44.1 to 661.3 and 44.1 to 881.8, in steps of 0.1",
          page.evaluate("() => ['#pf-weight', '#pf-weight-6mo'].map((s) => { const b = document.querySelector(s); return [b.min, b.max, b.step].join(' '); })")
          == ["44.1 661.3 0.1", "44.1 881.8 0.1"])
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/profile")):
        page.click("#btn-save-profile")
    saved = person.json("GET", "/api/profile")
    check("Saving without touching the weights keeps 70.23 and 74 kg", (saved["weight_kg"], saved["weight_6_months_ago_kg"]) == (70.23, 74))
    page.fill("#pf-weight", "155")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/profile")):
        page.click("#btn-save-profile")
    check("155 lb is saved as 70.31 kg", person.json("GET", "/api/profile")["weight_kg"] == 70.31)
    page.fill("#pf-weight", "")
    page.click("#btn-suggest")
    page.wait_for_function("() => document.querySelector('#toast').innerText.includes('Enter your weight')")
    check("Suggest with no weight asks for it in pounds", "Enter your weight (lb) first" in page.inner_text("#toast"))
    page.click("#settings-open")
    page.wait_for_selector("#set-body-unit", timeout=20000)
    with page.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith("/api/me/settings")):
        page.select_option("#set-body-unit", "kg")
    check("Settings saves Unit for weight", person.json("GET", "/api/me/settings")["settings"]["user.units.weight"]["value"] == "kg")
    page.wait_for_function("() => /kilograms/.test((document.querySelector('#set-body-unit-msg') || {}).textContent || '')")
    check("Settings has already turned Profile's boxes to kilograms", page.evaluate("() => KH.state.weightUnit") == "kg"
          and page.evaluate("() => document.querySelector('#pf-weight-label').textContent") == "Weight (kg)")
    page.click("#tab-profile")
    page.wait_for_function("() => document.querySelector('#pf-weight').value === '70.31'")
    check("Profile then shows the weights in kilograms", page.input_value("#pf-weight-6mo") == "74"
          and page.get_by_label("Weight (kg)").count() == 1 and page.get_by_label("Weight 6 months ago (kg)").count() == 1)
    page.select_option("#pf-dialysis", "hemodialysis")
    check("On dialysis the label is Dry weight (kg, after dialysis)", page.get_by_label("Dry weight (kg, after dialysis)").count() == 1)
    page.select_option("#pf-dialysis", "none")
    person.json("PATCH", "/api/me/settings", {"user.units.weight": "lb"})


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
                page.wait_for_function("() => document.querySelector('#pf-weight').value === '154.3'")  # 70 kg in pounds, the default unit
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
                height_walk(page, ana, check)
                weight_walk(page, ana, check)
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
