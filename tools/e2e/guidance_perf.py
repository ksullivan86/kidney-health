#!/usr/bin/env python3
"""Time the browser twin of the meal guidance engine in Chromium with a slowed-down CPU.

    python tools/e2e/guidance_perf.py                       # builds the preview, 4x CPU throttling
    python tools/e2e/guidance_perf.py --rate 6 --runs 50 --out /tmp/kh-perf --preview build/preview.html

The demo / preview mode answers ``/api/guidance/*`` in the page (``js/mock/guidance.js`` over
``js/engine/guidance/*.js``), so on a slow phone the person waits for this code, not for a server.
Note 06 §4.12 budgets a guidance request at p95 < 200 ms on a Raspberry Pi 4; this harness holds the
twin to the same number on an emulated slow device.

What it does: builds the preview fragment with ``scripts/build_preview.py`` (or uses ``--preview``),
wraps it in a minimal page served on 127.0.0.1 (``--port``, default 8065), opens it in headless
Chromium, turns on CPU throttling through the DevTools protocol (``Emulation.setCPUThrottlingRate``)
and calls the demo API directly (``KH.mock.MockApi.handle``, no network, no rendering) for two data sets:

1. the demo as shipped: 395 foods and the seeded weeks of entries;
2. the note's benchmark size: 5 perturbed copies of ``data/foods.json`` (1,975 foods), 60 days of
   history (3 to 5 entries a day, a fixed pseudo-random sequence) and 100 saved meals.

Per route: the first (cold) call, then 3 warm-up calls and ``--runs`` timed calls (p50, p95, max).
The x86 CI engine budgets of note 06 §4.12 are printed next to them for reference (they apply to the
server's engine on an unthrottled CI runner, so they are not a pass mark here).

Exit status 1 when a route answers anything but ``status: "ok"`` or any p95 is above ``--max-p95``
(default 200 ms). Writes ``<out>/report.json``. The static server and the browser are always stopped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import khserver
from khserver import REPO, chromium_executable

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "guidance_perf"
PORT = 8065
# Engine time on the x86 CI runner (note 06 §4.12), shown for reference.
SERVER_BUDGET_MS = {"next-meal (what fits)": 25, "swaps": 5, "plan-day (4 slots)": 40, "insights/day": 15,
                    "insights/period (7 d)": 15}

BENCH_JS = r"""
async ({ runs, big }) => {
  const KH = window.KH;
  const M = KH.mock;
  let api;
  if (!big) {
    api = M.instance;
  } else {
    // 5 copies of the builtin foods, each copy's nutrients scaled by 1 + 0.07 × copy (as scripts/bench_guidance.py).
    const base = JSON.parse(document.getElementById('kdl-foods').textContent);
    const foods = [];
    for (let copy = 0; copy < 5; copy++) {
      const f = 1 + copy * 0.07;
      for (const item of base.foods) {
        const n = {};
        for (const [k, v] of Object.entries(item.nutrients || {})) n[k] = v == null ? v : Math.round(v * f * 10) / 10;
        foods.push({ ...item, fdc_id: item.fdc_id == null ? null : item.fdc_id + copy * 10000000,
          name: copy ? `${item.name} (${copy})` : item.name, nutrients: n });
      }
    }
    api = new M.MockApi({ foodsData: { ...base, foods: foods.slice(0, 2000) } });
    // 60 days of history and 100 saved meals, written through the demo's own routes.
    const today = KH.util.todayStr();
    const ids = api._foods.filter((x) => !x.hidden).map((x) => x.id);
    let seed = 7;
    const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
    const meals = ['breakfast', 'lunch', 'dinner', 'snack'];
    for (let d = 1; d <= 60; d++) {
      const date = KH.util.addDays(today, -d);
      const n = 3 + Math.floor(rnd() * 3);
      for (let i = 0; i < n; i++) {
        api.handle('POST', '/api/log', { date, meal: meals[i % 4], food_id: ids[Math.floor(rnd() * ids.length)],
          servings: 0.5 + Math.floor(rnd() * 4) * 0.5 });
      }
    }
    for (let t = 0; t < 100; t++) {
      api.handle('POST', '/api/meals', { name: `Meal ${t}`, meal_hint: t % 5 === 4 ? null : meals[t % 4],
        items: [0, 1, 2].map(() => ({ food_id: ids[Math.floor(rnd() * ids.length)], servings: 1 })) });
    }
  }
  // Stage 4, type 1 diabetes: every guidance feature is on (carb goals, K/P/Na/fluid targets).
  api.handle('PUT', '/api/profile', { weight_kg: 70, height_cm: 170, ckd_stage: '4', dialysis: 'none', diabetes: 'type1',
    targets: { calories_kcal: 2100, protein_g: { min: 42, max: 56 }, carbs_g: 236, carbs_per_meal_g: 60, sodium_mg: 2000,
      potassium_mg: 2500, phosphorus_mg: 900, fluid_ml: 1500 } });
  const today = KH.util.todayStr();
  const empty = KH.util.addDays(today, 30); // nothing logged: plan-day fills all four slots
  const banana = api._foods.find((x) => x.name === 'Banana, raw');
  if (!banana) throw new Error('the builtin food "Banana, raw" is missing');
  const cases = {
    'next-meal (what fits)': () => api.handle('GET', `/api/guidance/next-meal?meal=dinner&date=${today}`),
    'swaps': () => api.handle('GET', `/api/guidance/swaps?food_id=${banana.id}&meal=dinner&servings=2&date=${today}`),
    'plan-day (4 slots)': () => api.handle('POST', '/api/guidance/plan-day', { date: empty }),
    'insights/day': () => api.handle('GET', `/api/guidance/insights/day?date=${KH.util.addDays(today, -1)}`),
    'insights/period (7 d)': () => api.handle('GET', '/api/guidance/insights/period'),
    'hypo-options': () => api.handle('GET', '/api/guidance/hypo-options'),
  };
  const out = { foods: api._foods.length, entries: api._entries.length, saved: api._templates.length, results: {}, errors: [] };
  for (const [name, fn] of Object.entries(cases)) {
    const first = performance.now();
    const r = fn();
    const cold = performance.now() - first;
    if (!r || r.status !== 'ok') { out.errors.push(`${name}: ${JSON.stringify(r).slice(0, 300)}`); continue; }
    for (let i = 0; i < 3; i++) fn();
    const t = [];
    for (let i = 0; i < runs; i++) { const a = performance.now(); fn(); t.push(performance.now() - a); }
    t.sort((x, y) => x - y);
    const q = (p) => t[Math.min(t.length - 1, Math.ceil(p * t.length) - 1)];
    out.results[name] = { cold: +cold.toFixed(1), p50: +q(0.5).toFixed(1), p95: +q(0.95).toFixed(1), max: +t[t.length - 1].toFixed(1) };
  }
  return out;
}
"""


def page_html(fragment: str) -> str:
    """The preview fragment in the document skeleton an Artifact host adds (plus an empty favicon)."""
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n<link rel="icon" href="data:,">\n'
            f"</head>\n<body>\n{fragment}</body>\n</html>\n")


def serve(directory: Path, port: int) -> ThreadingHTTPServer:
    """A quiet static server for ``directory`` on 127.0.0.1:<port>, running in a daemon thread."""

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # the harness prints its own report
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(Quiet, directory=str(directory)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def measure(url: str, rate: float, runs: int) -> tuple[str, dict[str, Any]]:
    """Run BENCH_JS for both data sets with the CPU slowed down ``rate`` times; returns (browser version, report)."""
    report: dict[str, Any] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium_executable(), headless=True)
        try:
            for big in (False, True):
                page = browser.new_page(viewport={"width": 375, "height": 812})
                page.goto(url)
                page.wait_for_function("() => !!(window.KH && KH.mock && KH.mock.instance)", timeout=30_000)
                page.wait_for_timeout(1_000)  # let the first render settle before the clock starts
                cdp = page.context.new_cdp_session(page)
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
                try:
                    res = page.evaluate(BENCH_JS, {"runs": runs, "big": big})
                finally:
                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
                report["benchmark size (2,000 foods, 60 days, 100 saved meals)" if big else "demo as shipped"] = res
                page.close()
            version = browser.version
        finally:
            browser.close()
    return version, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rate", type=float, default=4, help="CPU slow-down factor (default 4, a mid-range phone)")
    ap.add_argument("--runs", type=int, default=30, help="timed calls per route after 3 warm-ups (default 30)")
    ap.add_argument("--max-p95", type=float, default=200, help="fail when a route's p95 is above this many ms (default 200)")
    ap.add_argument("--port", type=int, default=PORT, help=f"port of the static server (default {PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory, wiped first (default {OUT})")
    ap.add_argument("--preview", type=Path, default=None, help="use this built fragment instead of building one")
    args = ap.parse_args()
    if args.runs < 1 or args.rate < 1:
        sys.exit("--runs must be at least 1 and --rate at least 1")
    if khserver.port_in_use(args.port):
        sys.exit(f"port {args.port} is in use: pick another with --port")
    fragment = None
    if args.preview is not None:  # read before the work directory is wiped (it may live there)
        if not args.preview.is_file():
            sys.exit(f"{args.preview} missing: python scripts/build_preview.py --out {args.preview}")
        fragment = args.preview.read_text(encoding="utf-8")
    out = khserver.free_dir(args.out)
    site = out / "site"
    site.mkdir()
    if fragment is None:
        subprocess.run([sys.executable, str(REPO / "scripts" / "build_preview.py"), "--out", str(out / "preview.html")], check=True)
        fragment = (out / "preview.html").read_text(encoding="utf-8")
    (site / "index.html").write_text(page_html(fragment), encoding="utf-8")

    httpd = serve(site, args.port)
    try:
        version, report = measure(f"http://127.0.0.1:{args.port}/index.html", args.rate, args.runs)
    finally:
        httpd.shutdown()
        httpd.server_close()

    failures: list[str] = []
    print(f"Chromium {version}, CPU throttling x{args.rate:g}, {args.runs} timed runs after 3 warm-ups (ms)")
    for label, res in report.items():
        print(f"\n{label}: {res['foods']} foods, {res['entries']} entries, {res['saved']} saved meals")
        print(f"  {'route':26} {'cold':>7} {'p50':>7} {'p95':>7} {'max':>7}   x86 CI engine budget (server, reference)")
        for name, r in res["results"].items():
            print(f"  {name:26} {r['cold']:7} {r['p50']:7} {r['p95']:7} {r['max']:7}   {SERVER_BUDGET_MS.get(name, '-')}")
            if r["p95"] > args.max_p95:
                failures.append(f"{label}: {name} p95 {r['p95']} ms > {args.max_p95:g} ms")
        failures.extend(f"{label}: {e}" for e in res["errors"])
    (out / "report.json").write_text(json.dumps({"chromium": version, "rate": args.rate, "runs": args.runs,
                                                 "max_p95_ms": args.max_p95, "report": report, "failures": failures}, indent=2),
                                     encoding="utf-8")
    print(f"\nreport: {out / 'report.json'}")
    for f in failures:
        print(f"FAIL {f}")
    print("FAILED" if failures else f"OK: every p95 is within {args.max_p95:g} ms")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
