#!/usr/bin/env python3
"""Parity harness: the preview's in-page demo API (window.__kdlMock) vs the real FastAPI server.

    python tools/e2e/parity.py                                  # server on this interpreter
    python tools/e2e/parity.py --server-python venv312/bin/python  # server on Python 3.12
    python tools/e2e/parity.py --port 8061 --static-port 8062 --out /tmp/kh-parity

What it does
  * starts ``uvicorn app.main:app`` on 127.0.0.1:<port> (default 8061) with a fresh DATA_DIR in
    <out>/data, reads the first-run setup code from the server log and creates the first admin
    (v0.3 accounts: every /api call is made signed in, with the CSRF headers the app requires),
  * builds the preview with scripts/build_preview.py, wraps the fragment in a minimal skeleton and
    serves it on 127.0.0.1:<static-port> (default 8062), opens it in headless Chromium (in demo mode
    the person is a signed-in demo admin),
  * resets the demo (drops its seeded entries / saved meals, restores the default profile) and
    replays identical operations on both sides, comparing every field except ids and timestamps.

Sections
  0 sanity (profile, healthz, categories, empty day, suggest without weight)
  1 GET /api/foods/{id} for every builtin food, matched by name
  1b window.__kdlEvaluateWarnings vs app.nutrients.food_warnings (pure-function fuzz, boundaries)
  2 GET /api/foods?q= for 15 queries (fresh history); 2b again after sections 4-5 (with history)
  3 suggested targets: stage x dialysis x height/weight x diabetes (144) + 3b random weights/heights
  4 scripted day: profile, 8 entries (grams-based, 2 planned), GET /api/log?date=
  5 PUT entry, copy-day, mark-eaten, saved meals create/from-log/apply/list, shopping, range, CSV, quick add
  6 GET /api/log/summary: 7-day window with 4 logged days; hemodialysis [0,2,4] end on every weekday
  7 validation errors: status code + detail text
  8 bulk: every builtin food logged at an odd amount, entry/day/summary parity (summation order)
  9 custom foods (create/edit/copy/hide/delete, grams re-derivation), target variants, LIKE metacharacters
  10 accounts: the demo's /api/auth/status, /api/me, /api/me/settings and /api/me/keys answer with the
     same keys and value types as the server's (values differ: the demo is a demo admin); /api/handbook
     has the same keys and link groups (the demo serves no handbook)
  11 personalised targets and labs (v0.3 M2): the "About you" profile fields and their validation, lab
     entry with unit conversion and its validation, history filters, deletion, the kidney-function card
     for several profiles, and the suggestion (targets, notes, rules, derived, alerts, 422 refusals with
     their code) over a matrix of profiles x lab results x the targets.* settings

``--sections 0,11`` runs only those sections (section 1 always runs first: the others need its food ids).
Error answers are compared by status, detail and, when either side sends one, ``code``.

Exit status 0 when every comparison matched, 1 otherwise. Report: <out>/report.json.
The server, the static server and the browser are always stopped.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx2

from khserver import REPO, Api, Server, chromium_executable, first_admin, free_dir, port_in_use

HERE = Path(__file__).resolve().parent
OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "parity"
DATA_DIR = OUT / "data"
PREVIEW = OUT / "preview.html"
SITE = OUT / "site"
SERVER_PORT = 8061
STATIC_PORT = 8062
BASE = f"http://127.0.0.1:{SERVER_PORT}"


def configure(out: Path, port: int, static_port: int) -> None:
    global OUT, DATA_DIR, PREVIEW, SITE, SERVER_PORT, STATIC_PORT, BASE
    OUT = out
    DATA_DIR, PREVIEW, SITE = out / "data", out / "preview.html", out / "site"
    SERVER_PORT, STATIC_PORT = port, static_port
    BASE = f"http://127.0.0.1:{SERVER_PORT}"


IGNORE = frozenset({"id", "created_at", "updated_at"})

# --------------------------------------------------------------------------- #
# Comparison / recording
# --------------------------------------------------------------------------- #

_MEDIUM_KEYS = {"message", "detail", "notes", "food_name", "serving_desc", "kidney_notes", "name", "note", "order"}
_HIGH_STR_KEYS = {"level", "kidney_rating", "status", "flag", "nutrient", "assessment", "role", "date", "since", "next", "meal", "code"}


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def deep_diff(s: Any, m: Any, path: str, ignore: frozenset, out: list, leaves: list) -> None:
    if isinstance(s, dict) and isinstance(m, dict):
        keys = list(s.keys()) + [k for k in m.keys() if k not in s]
        for k in keys:
            if k in ignore:
                continue
            p = f"{path}/{k}"
            if k not in m:
                out.append((p, s[k], "<absent>"))
                continue
            if k not in s:
                out.append((p, "<absent>", m[k]))
                continue
            deep_diff(s[k], m[k], p, ignore, out, leaves)
        return
    if isinstance(s, list) and isinstance(m, list):
        if len(s) != len(m):
            out.append((f"{path}/len", len(s), len(m)))
        for i, (a, b) in enumerate(zip(s, m)):
            deep_diff(a, b, f"{path}[{i}]", ignore, out, leaves)
        return
    leaves[0] += 1
    if _is_num(s) and _is_num(m):
        if float(s) != float(m):
            out.append((path, s, m))
    elif isinstance(s, bool) or isinstance(m, bool):
        if type(s) is not type(m) or s != m:
            out.append((path, s, m))
    elif s != m:
        out.append((path, s, m))


def classify(path: str, s: Any, m: Any) -> str:
    leaf = path.rsplit("/", 1)[-1].split("[", 1)[0]
    if leaf == "len":
        return "high"
    if leaf in _MEDIUM_KEYS:
        return "medium"
    if isinstance(s, str) and isinstance(m, str) and leaf not in _HIGH_STR_KEYS:
        return "medium"
    return "high"


class Recorder:
    def __init__(self) -> None:
        self.sections: dict[str, dict[str, Any]] = {}

    def _sec(self, section: str) -> dict[str, Any]:
        return self.sections.setdefault(section, {"checks": 0, "passed": 0, "failed": 0, "leaves": 0, "mismatches": []})

    def compare(self, section: str, label: str, s: Any, m: Any, ignore: frozenset = IGNORE) -> bool:
        out: list = []
        leaves = [0]
        deep_diff(s, m, "", ignore, out, leaves)
        sec = self._sec(section)
        sec["checks"] += 1
        sec["leaves"] += leaves[0]
        if out:
            sec["failed"] += 1
            sec["mismatches"].append(
                {
                    "label": label,
                    "count": len(out),
                    "diffs": [
                        {"path": p, "server": a, "mock": b, "severity": classify(p, a, b)} for p, a, b in out[:60]
                    ],
                }
            )
            return False
        sec["passed"] += 1
        return True

    def compare_resp(self, section: str, label: str, rs: dict, rm: dict, ignore: frozenset = IGNORE) -> bool:
        ok_s = 200 <= rs["status"] < 300
        ok_m = 200 <= rm["status"] < 300
        if ok_s and ok_m:
            return self.compare(section, label, rs.get("body"), rm.get("body"), ignore)
        if not ok_s and not ok_m:
            err_s = {"status": rs["status"], "detail": rs.get("detail")}
            err_m = {"status": rm["status"], "detail": rm.get("detail")}
            if "code" in rs or "code" in rm:
                err_s["code"], err_m["code"] = rs.get("code"), rm.get("code")
            return self.compare(section, label, err_s, err_m)
        return self.compare(
            section,
            label,
            {"status": rs["status"], "detail": rs.get("detail")},
            {"status": rm["status"], "detail": rm.get("detail"), "error": rm.get("error")},
        )

    def note_failure(self, section: str, label: str, message: str) -> None:
        sec = self._sec(section)
        sec["checks"] += 1
        sec["failed"] += 1
        sec["mismatches"].append({"label": label, "count": 1, "diffs": [{"path": "", "server": message, "mock": None, "severity": "high"}]})


# --------------------------------------------------------------------------- #
# Sides
# --------------------------------------------------------------------------- #


class ServerSide:
    """The real server, signed in as the first admin (an :class:`khserver.Api` client)."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.client = api.client

    def call(self, method: str, path: str, body: Any = None) -> dict:
        if body is None:
            r = self.client.request(method, path)
        else:
            r = self.client.request(method, path, json=body)
        out: dict[str, Any] = {"status": r.status_code}
        ctype = r.headers.get("content-type", "")
        payload: Any = None
        if r.content:
            if "json" in ctype:
                payload = r.json()
            else:
                payload = r.text
        if 200 <= r.status_code < 300:
            out["body"] = payload
        else:
            out["detail"] = payload.get("detail") if isinstance(payload, dict) else payload
            if isinstance(payload, dict) and "code" in payload:  # e.g. the 422 refusals of suggested-targets
                out["code"] = payload["code"]
        return out


HELPERS_JS = r"""
() => {
  window.__parity = {
    async call(method, path, body) {
      try {
        const r = await window.__kdlMock.request(method, path, body === null ? undefined : body);
        return { status: 200, body: r === undefined ? null : r };
      } catch (e) {
        const out = { status: (e && e.status) || 500, detail: (e && e.detail) || String(e), error: e && e.status ? null : String((e && e.stack) || e) };
        if (e && e.extra && 'code' in e.extra) out.code = e.extra.code;
        return out;
      }
    },
    async seq(calls) { const out = []; for (const c of calls) out.push(await this.call(c[0], c[1], c[2])); return out; },
    async par(calls) { return Promise.all(calls.map((c) => this.call(c[0], c[1], c[2]))); },
    reset() {
      const m = window.__kdlMock;
      m._entries = []; m._nextEntryId = 1;
      m._templates = []; m._nextTemplateId = 1;
      m._labs = []; m._nextLabId = 1;
      m._profile = { id: 1, name: '', weight_kg: null, height_cm: null, ckd_stage: '3b', dialysis: 'none', diabetes: 'type1',
        warn_fraction: 0.8, dialysis_days: [], week_start: 'monday', targets: {}, updated_at: m._stamp() };
      return { foods: m._foods.length, custom: m._foods.filter((f) => f.source !== 'builtin').length, nextFoodId: m._nextFoodId, source: m.foodsSource };
    },
  };
  return true;
}
"""


class MockSide:
    def __init__(self, page) -> None:
        self.page = page

    def call(self, method: str, path: str, body: Any = None) -> dict:
        return self.page.evaluate("([m, p, b]) => window.__parity.call(m, p, b)", [method, path, body])

    def seq(self, calls: list) -> list:
        out: list = []
        for i in range(0, len(calls), 120):
            out += self.page.evaluate("(calls) => window.__parity.seq(calls)", calls[i : i + 120])
        return out

    def par(self, calls: list) -> list:
        return self.page.evaluate("(calls) => window.__parity.par(calls)", calls)


# --------------------------------------------------------------------------- #
# Process management
# --------------------------------------------------------------------------- #

PROCS: list[subprocess.Popen] = []
SERVER: Server | None = None


def _wait_http(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = httpx2.get(url, timeout=2, trust_env=False)
            if r.status_code < 500:
                return
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"{url} did not come up: {last}")


def start_processes(server_python: str) -> Api:
    """Start the server (fresh DATA_DIR) and the static preview site; returns the admin's client."""
    global SERVER
    if port_in_use(STATIC_PORT):
        raise RuntimeError(f"port {STATIC_PORT} is already in use; pick another with --static-port")
    free_dir(OUT)
    SERVER = Server(SERVER_PORT, DATA_DIR, log_path=OUT / "server.log", python=server_python)
    SERVER.start()
    admin = first_admin(SERVER, "parity")
    # Preview build + skeleton + static server.
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_preview.py"), "--out", str(PREVIEW)],
        check=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    SITE.mkdir(exist_ok=True)
    fragment = PREVIEW.read_text(encoding="utf-8")
    (SITE / "index.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n'
        + fragment + "</body>\n</html>\n",
        encoding="utf-8",
    )
    slog = open(OUT / "static.log", "w")
    PROCS.append(
        subprocess.Popen(
            [sys.executable, "-m", "http.server", str(STATIC_PORT), "--bind", "127.0.0.1", "--directory", str(SITE)],
            stdout=slog, stderr=subprocess.STDOUT, start_new_session=True,
        )
    )
    _wait_http(f"http://127.0.0.1:{STATIC_PORT}/index.html")
    return admin


def stop_processes() -> None:
    if SERVER is not None:
        SERVER.stop()
    for p in PROCS:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for p in PROCS:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=5)


# --------------------------------------------------------------------------- #
# Scenario helpers
# --------------------------------------------------------------------------- #


def d(s: str, n: int = 0) -> str:
    return (date.fromisoformat(s) + timedelta(days=n)).isoformat()


class Harness:
    def __init__(self, server: ServerSide, mock: MockSide, rec: Recorder) -> None:
        self.server = server
        self.mock = mock
        self.rec = rec
        self.food_id: dict[str, int] = {}  # name -> id (verified identical on both sides)
        self.entry_ids: dict[str, tuple[int, int]] = {}
        self.tpl_ids: dict[str, tuple[int, int]] = {}

    def fid(self, name: str) -> int:
        return self.food_id[name]

    def both(self, section: str, label: str, method: str, path: Any, body: Any = None, ignore: frozenset = IGNORE):
        ps = path(0) if callable(path) else path
        pm = path(1) if callable(path) else path
        bs = body(0) if callable(body) else body
        bm = body(1) if callable(body) else body
        rs = self.server.call(method, ps, bs)
        rm = self.mock.call(method, pm, bm)
        self.rec.compare_resp(section, label, rs, rm, ignore)
        return rs, rm

    def entry_path(self, key: str, suffix: str = "") -> Callable[[int], str]:
        return lambda side: f"/api/log/{self.entry_ids[key][side]}{suffix}"

    def tpl_path(self, key: str, suffix: str = "") -> Callable[[int], str]:
        return lambda side: f"/api/meals/{self.tpl_ids[key][side]}{suffix}"

    def log(self, section: str, key: str, date_: str, meal: str, food: str, *, servings=None, grams=None, note=None, status=None):
        body: dict[str, Any] = {"date": date_, "meal": meal, "food_id": self.fid(food)}
        if servings is not None:
            body["servings"] = servings
        if grams is not None:
            body["grams"] = grams
        if note is not None:
            body["note"] = note
        if status is not None:
            body["status"] = status
        rs, rm = self.both(section, f"POST /api/log {key}", "POST", "/api/log", body)
        if 200 <= rs["status"] < 300 and 200 <= rm["status"] < 300:
            self.entry_ids[key] = (rs["body"]["id"], rm["body"]["id"])
        return rs, rm

    def put_profile(self, section: str, label: str, body: dict) -> None:
        self.both(section, f"PUT /api/profile {label}", "PUT", "/api/profile", body)

    # ------------------------------------------------------------------ #
    def section0(self) -> None:
        S = "0 sanity"
        self.both(S, "GET /api/profile (after reset)", "GET", "/api/profile")
        self.both(S, "GET /healthz", "GET", "/healthz")
        self.both(S, "GET /api/foods/categories", "GET", "/api/foods/categories")
        self.both(S, "GET /api/meals (empty)", "GET", "/api/meals")
        self.both(S, "GET /api/log?date= empty day, no targets", "GET", "/api/log?date=2026-06-01")
        self.both(S, "GET /api/profile/suggested-targets without weight", "GET", "/api/profile/suggested-targets")
        self.both(S, "GET /api/foods (empty q, no history, limit 25)", "GET", "/api/foods")
        self.both(S, "GET /api/foods?category=Beverages&limit=200", "GET", "/api/foods?category=Beverages&limit=200")

    def section1(self) -> None:
        S = "1 foods"
        server_foods: list[dict] = []
        i = 1
        while True:
            r = self.server.call("GET", f"/api/foods/{i}")
            if r["status"] == 404:
                break
            server_foods.append(r["body"])
            i += 1
        mock_ids = self.mock.page.evaluate(
            "() => window.__kdlMock._foods.filter((f) => f.source === 'builtin').map((f) => [f.id, f.name])"
        )
        mock_res = self.mock.par([["GET", f"/api/foods/{fid}", None] for fid, _ in mock_ids])
        mock_by_name = {r["body"]["name"]: r["body"] for r in mock_res if r["status"] == 200}
        server_by_name = {f["name"]: f for f in server_foods if f["source"] == "builtin"}
        self.rec.compare(S, "builtin food count", len(server_by_name), len(mock_by_name))
        self.rec.compare(S, "builtin food names", sorted(server_by_name), sorted(mock_by_name))
        same_ids = {n: f["id"] for n, f in server_by_name.items()} == {n: f["id"] for n, f in mock_by_name.items()}
        self.rec.compare(S, "food ids identical on both sides", True, same_ids)
        for name, sf in server_by_name.items():
            self.food_id[name] = sf["id"]
            mf = mock_by_name.get(name)
            if mf is None:
                self.rec.note_failure(S, name, "missing in mock")
                continue
            self.rec.compare(S, f"GET /api/foods/{{id}} {name}", sf, mf)
        self.n_builtin = len(server_by_name)

    def section1b(self) -> None:
        S = "1b evaluateWarnings"
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(REPO))
        from app.nutrients import food_warnings  # noqa: E402  (pure function, no I/O)

        rnd = random.Random(20261005)
        boundary = {
            "potassium_mg": [100.4, 100.5, 100.49999, 101, 199.5, 200, 200.4, 200.5, 200.6, 0.5, 1e-9],
            "phosphorus_mg": [100.5, 100.4, 149.5, 150.4, 150.5, 151],
            "sodium_mg": [140.4, 140.5, 141, 399.5, 400.4, 400.5],
            "carbs_g": [0.04, 0.05, 0.06, 4, 14.94, 14.95, 14.96, 15, 22.5, 29.95, 29.96, 30, 30.04, 30.05, 37.5, 52.5, 67.5, 7.5],
            "protein_g": [14.94, 14.95, 15, 24.95, 25, 25.04, 25.05, 25.06],
        }
        flag_pool = ["high_gi", "hypo_treatment", "phosphate_additive", "avoid_ckd", "counts_as_fluid"]
        scopes = ["per serving", "in this entry", "in this meal"]
        cases = []
        for key, vals in boundary.items():
            for v in vals:
                for flags in ([], ["high_gi"], ["hypo_treatment"], ["phosphate_additive"], ["hypo_treatment", "high_gi"]):
                    cases.append(({key: v}, flags, None, "per serving"))
        base_vals = [26.95, 422, 105, 0.15, 1.29, 33.3, 12.25, 0.35, 2.45, 18.75]
        factors = [0.25, 0.333, 0.5, 0.75, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.3, 7]
        for _ in range(4000):
            nut = {}
            for key in boundary:
                r = rnd.random()
                if r < 0.1:
                    nut[key] = None
                elif r < 0.4:
                    nut[key] = rnd.choice(boundary[key])
                elif r < 0.7:
                    nut[key] = rnd.choice(base_vals) * rnd.choice(factors)
                else:
                    nut[key] = round(rnd.uniform(0, 600), rnd.choice([0, 1, 2, 3]))
            flags = [f for f in flag_pool if rnd.random() < 0.2]
            notes = rnd.choice([None, "", "  Star fruit contains caramboxin.  ", "Avoid."])
            cases.append((nut, flags, notes, rnd.choice(scopes)))
        py = [food_warnings(n, f, k, scope=sc) for n, f, k, sc in cases]
        js = self.mock.page.evaluate(
            "(cases) => cases.map(([n, f, k, sc]) => window.__kdlEvaluateWarnings(n, f, k, sc))",
            [list(c) for c in cases],
        )
        for i, (a, b) in enumerate(zip(py, js)):
            self.rec.compare(S, f"case {i}: {json.dumps(cases[i])}", a, b, frozenset())

    QUERIES = ["banana", "rice", "egg white", "glucose", "cola", "chicken", "cheese", "juice", "potato", "bread",
               "milk", "apple", "soda", "turkey", "star"]

    def section2(self, S: str = "2 search") -> None:
        for q in self.QUERIES:
            for extra in ("", "&limit=10"):
                path = f"/api/foods?q={q.replace(' ', '%20')}{extra}"
                rs = self.server.call("GET", path)
                rm = self.mock.call("GET", path)
                sn = [f["name"] for f in rs["body"]["foods"]]
                mn = [f["name"] for f in (rm.get("body") or {}).get("foods", [])]
                self.rec.compare(S, f"{path} top-10 order", sn[:10], mn[:10])
                if not extra:
                    self.rec.compare(S, f"{path} full order ({len(sn)})", sn, mn)
                    self.rec.compare_resp(S, f"{path} full objects", rs, rm)
        # Multi-word / casing / whitespace variants.
        for q in ["  Egg   WHITE ", "white egg", "rice cooked white", "milk 2%", "fast food", "gluc"]:
            path = "/api/foods?" + httpx2.QueryParams({"q": q}).__str__()
            self.both(S, f"{path}", "GET", path)

    def section3(self) -> None:
        S = "3 targets"
        heights = [("no height, 70 kg", 70, None), ("170 cm, 70 kg", 70, 170), ("150 cm, 70 kg", 70, 150), ("190 cm, 60 kg", 60, 190)]
        for stage in ["1", "2", "3a", "3b", "4", "5"]:
            for dialysis in ["none", "hemodialysis", "peritoneal"]:
                for hlabel, weight, height in heights:
                    for diabetes in ["type1", "none"]:
                        label = f"stage {stage}, {dialysis}, {hlabel}, diabetes {diabetes}"
                        body = {"ckd_stage": stage, "dialysis": dialysis, "diabetes": diabetes, "weight_kg": weight, "height_cm": height}
                        self.put_profile(S, label, body)
                        self.both(S, f"suggested-targets {label}", "GET", "/api/profile/suggested-targets")
        S = "3b targets fuzz"
        rnd = random.Random(7)
        for i in range(60):
            weight = round(rnd.uniform(35, 160), rnd.choice([0, 1, 2]))
            height = rnd.choice([None, round(rnd.uniform(140, 210), rnd.choice([0, 1]))])
            body = {"ckd_stage": rnd.choice(["1", "2", "3a", "3b", "4", "5"]), "dialysis": rnd.choice(["none", "hemodialysis", "peritoneal"]),
                    "diabetes": rnd.choice(["none", "type1", "type2"]), "weight_kg": weight, "height_cm": height}
            self.put_profile(S, json.dumps(body), body)
            self.both(S, f"suggested-targets {json.dumps(body)}", "GET", "/api/profile/suggested-targets")

    D = "2026-06-10"

    PROFILE = {
        "name": "Parity", "weight_kg": 70, "height_cm": 170, "ckd_stage": "4", "dialysis": "none", "diabetes": "type1",
        "warn_fraction": 0.8, "dialysis_days": [], "week_start": "monday",
        "targets": {"calories_kcal": 2100, "protein_g": {"min": 42, "max": 56}, "carbs_g": 236, "carbs_per_meal_g": 60,
                    "sodium_mg": 2000, "potassium_mg": 2500, "phosphorus_mg": 900, "calcium_mg": 1000, "fluid_ml": 1500,
                    "fat_g": None, "fiber_g": None},
    }

    def section4(self) -> None:
        S = "4 scripted day"
        D = self.D
        self.put_profile(S, "scripted-day profile", self.PROFILE)
        self.both(S, "GET /api/profile", "GET", "/api/profile")
        self.log(S, "banana", D, "breakfast", "Banana, raw", servings=1.5)
        self.log(S, "milk_g", D, "breakfast", "Milk, 2% reduced fat", grams=300, note="weighed")
        self.log(S, "burger", D, "lunch", "Cheeseburger, fast food, with condiments", servings=1)
        self.log(S, "cola", D, "lunch", "Cola, regular", servings=0.75)
        self.log(S, "potato", D, "dinner", "Potato, baked, with skin", servings=0.333)
        self.log(S, "glucose", D, "snack", "Glucose tablet (4 g carb)", servings=4, note="hypo 3.6")
        self.log(S, "chicken_p", D, "dinner", "Chicken breast, roasted, skinless", servings=1.25, status="planned")
        self.log(S, "star_p", D, "snack", "Star fruit (carambola)", servings=1, status="planned")
        self.both(S, f"GET /api/log?date={D}", "GET", f"/api/log?date={D}")
        # The same day viewed through /range and an empty neighbour.
        self.both(S, f"GET /api/log/range {D}..{d(D, 1)}", "GET", f"/api/log/range?start={D}&end={d(D, 1)}")

    def section5(self) -> None:
        S = "5 edits & planning"
        D = self.D
        self.both(S, "PUT entry servings+status (banana -> 0.5 planned)", "PUT", self.entry_path("banana"), {"servings": 0.5, "status": "planned"})
        self.both(S, "PUT grams-based entry meal only (milk -> snack)", "PUT", self.entry_path("milk_g"), {"meal": "snack"})
        self.both(S, "PUT entry grams (potato -> 250 g)", "PUT", self.entry_path("potato"), {"grams": 250})
        self.both(S, "PUT entry grams null (potato)", "PUT", self.entry_path("potato"), {"grams": None})
        self.both(S, "PUT entry status eaten + note (chicken)", "PUT", self.entry_path("chicken_p"), {"status": "eaten", "note": "  done  "})
        self.both(S, "PUT entry date move (cola -> D+4)", "PUT", self.entry_path("cola"), {"date": d(D, 4)})
        self.both(S, "PUT entry date back (cola -> D)", "PUT", self.entry_path("cola"), {"date": D})
        self.both(S, f"GET /api/log?date={D} after edits", "GET", f"/api/log?date={D}")
        # copy-day
        self.both(S, "copy-day D -> D+1 (defaults)", "POST", "/api/log/copy-day", {"from_date": D, "to_date": d(D, 1)})
        self.both(S, "copy-day D -> D+2 lunch+dinner eaten only, as eaten", "POST", "/api/log/copy-day",
                  {"from_date": D, "to_date": d(D, 2), "meals": ["lunch", "dinner", "lunch"], "include": "eaten", "status": "eaten"})
        self.both(S, "copy-day D -> D+2 planned only", "POST", "/api/log/copy-day", {"from_date": D, "to_date": d(D, 2), "include": "planned"})
        self.both(S, "copy-day from empty day (400)", "POST", "/api/log/copy-day", {"from_date": d(D, 30), "to_date": d(D, 2), "include": "eaten"})
        for n in (1, 2):
            self.both(S, f"GET /api/log?date=D+{n} after copy-day", "GET", f"/api/log?date={d(D, n)}")
        # mark-eaten
        self.both(S, "mark-eaten D+1 lunch", "POST", "/api/log/mark-eaten", {"date": d(D, 1), "meal": "lunch"})
        self.both(S, "GET D+1 after mark-eaten lunch", "GET", f"/api/log?date={d(D, 1)}")
        self.both(S, "mark-eaten D+1 (all)", "POST", "/api/log/mark-eaten", {"date": d(D, 1)})
        self.both(S, "mark-eaten D+1 again (0)", "POST", "/api/log/mark-eaten", {"date": d(D, 1)})
        self.both(S, "GET D+1 after mark-eaten all", "GET", f"/api/log?date={d(D, 1)}")
        # saved meals
        rs, rm = self.both(S, "POST /api/meals", "POST", "/api/meals", {
            "name": "Parity breakfast", "note": "  weekday  ",
            "items": [{"food_id": self.fid("Egg white, raw"), "servings": 2}, {"food_id": self.fid("Bread, white"), "servings": 1.5},
                      {"food_id": self.fid("Cola, regular"), "servings": 0.5}, {"food_id": self.fid("Star fruit (carambola)"), "servings": 0.25}]})
        self.tpl_ids["bk"] = (rs["body"]["id"], rm["body"]["id"])
        rs, rm = self.both(S, "POST /api/meals/from-log D lunch", "POST", "/api/meals/from-log", {"date": D, "meal": "lunch", "name": "lunch from log", "note": ""})
        self.tpl_ids["lunch"] = (rs["body"]["id"], rm["body"]["id"])
        rs, rm = self.both(S, "POST /api/meals/from-log D snack (mixed statuses, grams)", "POST", "/api/meals/from-log",
                           {"date": D, "meal": "snack", "name": "Apple snack"})
        self.tpl_ids["snack"] = (rs["body"]["id"], rm["body"]["id"])
        self.both(S, "from-log empty meal (400)", "POST", "/api/meals/from-log", {"date": d(D, 30), "meal": "lunch", "name": "x"})
        self.both(S, "apply bk D+3 dinner planned x1.5", "POST", self.tpl_path("bk", "/apply"), {"date": d(D, 3), "meal": "dinner", "status": "planned", "scale": 1.5})
        self.both(S, "apply lunch D+3 lunch (defaults)", "POST", self.tpl_path("lunch", "/apply"), {"date": d(D, 3), "meal": "lunch"})
        self.both(S, "apply snack D+3 snack eaten x0.333", "POST", self.tpl_path("snack", "/apply"), {"date": d(D, 3), "meal": "snack", "status": "eaten", "scale": 0.333})
        self.both(S, "GET /api/meals", "GET", "/api/meals")
        self.both(S, "GET /api/meals/{id} bk", "GET", self.tpl_path("bk"))
        self.both(S, "PUT /api/meals/{id} bk", "PUT", self.tpl_path("bk"), {"name": "aaa first", "items": [{"food_id": self.fid("Orange juice"), "servings": 1.75}]})
        self.both(S, "GET /api/meals after rename", "GET", "/api/meals")
        self.both(S, "GET /api/log?date=D+3", "GET", f"/api/log?date={d(D, 3)}")
        # shopping, range, quick add, CSV
        self.both(S, "GET /api/plan/shopping D..D+6", "GET", f"/api/plan/shopping?start={D}&end={d(D, 6)}")
        self.both(S, "GET /api/plan/shopping D+2..D+3", "GET", f"/api/plan/shopping?start={d(D, 2)}&end={d(D, 3)}")
        self.both(S, "GET /api/log/range D..D+6", "GET", f"/api/log/range?start={D}&end={d(D, 6)}")
        rs, rm = self.both(S, "POST /api/log/quick", "POST", "/api/log/quick", {
            "date": d(D, 3), "meal": "snack", "name": "Homemade cookie", "serving_desc": "1 cookie (30 g)", "serving_g": 30,
            "nutrients": {"calories_kcal": 140, "carbs_g": 21.25, "sugar_g": 11, "sodium_mg": 95.5, "potassium_mg": 60, "phosphorus_mg": 40.5, "protein_g": 1.95},
            "servings": 1.5, "flags": ["High_GI", " processed "], "status": "planned"})
        if 200 <= rs["status"] < 300 and 200 <= rm["status"] < 300:
            self.entry_ids["quick"] = (rs["body"]["id"], rm["body"]["id"])
            self.both(S, "GET quick-added food", "GET", lambda side: f"/api/foods/{(rs, rm)[side]['body']['food_id']}")
        self.both(S, "GET /api/log?date=D+3 after quick add", "GET", f"/api/log?date={d(D, 3)}")
        self.both(S, "GET /api/plan/shopping D..D+6 (with quick-add food)", "GET", f"/api/plan/shopping?start={D}&end={d(D, 6)}")
        self.both(S, "DELETE entry (glucose)", "DELETE", self.entry_path("glucose"))
        self.both(S, "GET /api/log?date=D after delete", "GET", f"/api/log?date={D}")
        self.both(S, "GET /api/log/summary D..D+6", "GET", f"/api/log/summary?start={D}&end={d(D, 6)}")
        self.compare_csv(S, f"/api/log/export.csv?start={D}&end={d(D, 6)}")

    def compare_csv(self, S: str, path: str) -> None:
        rs = self.server.call("GET", path)
        rm = self.mock.call("GET", path)

        def rows(text: str) -> list[dict]:
            rdr = csv.DictReader(io.StringIO(text, newline=""))
            return [{k: v for k, v in r.items() if k not in ("id", "created_at", "updated_at", "food_id")} for r in rdr]

        st, mt = rs.get("body") or "", rm.get("body") or ""
        self.rec.compare(S, f"{path} header", st.split("\r\n", 1)[0], mt.split("\r\n", 1)[0])
        self.rec.compare(S, f"{path} rows", rows(st), rows(mt))
        self.rec.compare(S, f"{path} line endings", st.count("\r\n"), mt.count("\r\n"))

    E6 = "2026-07-19"

    def section6(self) -> None:
        S = "6 period summary"
        E = self.E6
        S0 = d(E, -6)
        self.put_profile(S, "summary profile (stage 4, no dialysis)", self.PROFILE)
        plan = [
            # previous window [E-13, E-7]: 3 logged days
            (d(E, -13), "breakfast", "Rice, white, long-grain, cooked", {"servings": 1.5}, "eaten"),
            (d(E, -13), "lunch", "Chicken breast, roasted, skinless", {"servings": 1}, "eaten"),
            (d(E, -13), "dinner", "Water, tap", {"servings": 3}, "eaten"),
            (d(E, -10), "lunch", "Cheeseburger, fast food, with condiments", {"servings": 1}, "eaten"),
            (d(E, -10), "lunch", "Orange juice", {"grams": 400}, "eaten"),
            (d(E, -8), "dinner", "Potato, baked, with skin", {"servings": 1.75}, "eaten"),
            (d(E, -8), "dinner", "Milk, 2% reduced fat", {"servings": 2}, "eaten"),
            (d(E, -8), "snack", "Banana, raw", {"servings": 1}, "planned"),
            # current window [E-6, E]: eaten on E-6, E-4, E-3, E; planned-only on E-2
            (d(E, -6), "breakfast", "Banana, raw", {"servings": 2}, "eaten"),
            (d(E, -6), "lunch", "Potato, baked, with skin", {"servings": 1.5}, "eaten"),
            (d(E, -6), "dinner", "Orange juice", {"servings": 3}, "eaten"),
            (d(E, -6), "snack", "Cola, regular", {"servings": 2}, "eaten"),
            (d(E, -4), "breakfast", "Egg white, raw", {"servings": 3}, "eaten"),
            (d(E, -4), "breakfast", "Bread, white", {"servings": 2}, "eaten"),
            (d(E, -4), "lunch", "Deli turkey breast, sliced", {"servings": 1.5}, "eaten"),
            (d(E, -4), "dinner", "Water, tap", {"grams": 500}, "eaten"),
            (d(E, -4), "dinner", "Milk, 2% reduced fat", {"servings": 1}, "planned"),
            (d(E, -3), "lunch", "Cheeseburger, fast food, with condiments", {"servings": 2}, "eaten"),
            (d(E, -3), "snack", "Cola, regular", {"servings": 1}, "eaten"),
            (d(E, -3), "dinner", "Coffee, brewed", {"servings": 4}, "eaten"),
            (d(E, -2), "dinner", "Potato, baked, with skin", {"servings": 3}, "planned"),
            (d(E, -2), "dinner", "Star fruit (carambola)", {"servings": 1}, "planned"),
            (E, "breakfast", "Rice, white, long-grain, cooked", {"servings": 1}, "eaten"),
            (E, "lunch", "Chicken breast, roasted, skinless", {"servings": 0.75}, "eaten"),
            (E, "dinner", "Milk, 2% reduced fat", {"grams": 610}, "eaten"),
            (E, "snack", "Glucose tablet (4 g carb)", {"servings": 4}, "eaten"),
            (E, "snack", "Banana, raw", {"servings": 1}, "planned"),
        ]
        for i, (dt, meal, food, amount, status) in enumerate(plan):
            self.log(S, f"s6-{i}", dt, meal, food, status=status, **amount)
        self.both(S, f"GET /api/log/summary?start={S0}&end={E}", "GET", f"/api/log/summary?start={S0}&end={E}")
        self.both(S, f"GET /api/log/summary?end={E}", "GET", f"/api/log/summary?end={E}")
        self.both(S, f"GET /api/log/summary?start={S0}", "GET", f"/api/log/summary?start={S0}")
        self.both(S, "GET /api/log/summary 14 days", "GET", f"/api/log/summary?start={d(E, -13)}&end={E}")
        self.both(S, "GET /api/log/summary 1 day", "GET", f"/api/log/summary?start={E}&end={E}")
        self.both(S, "GET /api/log/summary empty period", "GET", f"/api/log/summary?start={d(E, 30)}&end={d(E, 36)}")
        self.both(S, f"GET /api/log/range {d(E, -13)}..{E}", "GET", f"/api/log/range?start={d(E, -13)}&end={E}")
        # hemodialysis without days, then with Mon/Wed/Fri
        self.put_profile(S, "hemodialysis, no days", {"dialysis": "hemodialysis", "dialysis_days": []})
        self.both(S, "summary hemodialysis without dialysis days", "GET", f"/api/log/summary?start={S0}&end={E}")
        self.put_profile(S, "hemodialysis [4,0,2,2]", {"dialysis": "hemodialysis", "dialysis_days": [4, 0, 2, 2]})
        for back in range(6, -1, -1):
            end = d(E, -back)
            wd = date.fromisoformat(end).strftime("%a")
            self.both(S, f"hemodialysis summary end {end} ({wd})", "GET", f"/api/log/summary?start={d(end, -6)}&end={end}")
        # A target change mid-way: protein as a min-only range, potassium null.
        self.put_profile(S, "targets edit", {"targets": {"protein_g": {"min": 50}, "potassium_mg": None, "fat_g": 70}})
        self.both(S, "summary after target edit", "GET", f"/api/log/summary?start={S0}&end={E}")
        self.both(S, "day after target edit", "GET", f"/api/log?date={E}")
        self.put_profile(S, "peritoneal", {"dialysis": "peritoneal"})
        self.both(S, "summary peritoneal (dialysis days kept)", "GET", f"/api/log/summary?start={S0}&end={E}")
        self.put_profile(S, "restore", self.PROFILE)

    def section7(self) -> None:
        S = "7 validation"
        D = self.D
        f1 = self.fid("Banana, raw")
        req = [
            ("POST /api/log servings 0", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": f1, "servings": 0}),
            ("POST /api/log unknown meal", "POST", "/api/log", {"date": D, "meal": "brunch", "food_id": f1}),
            ("POST /api/log missing date", "POST", "/api/log", {"meal": "lunch", "food_id": f1}),
        ]
        for label, method, path, body in req:
            self.both(S, label, method, path, body)
        S = "7b validation (extended)"
        big = 2**63
        self.log(S, "ws", d(D, 40), "lunch", "Banana, raw", servings=1, status="planned")
        ext = [
            ("POST /api/log missing date+bad meal+servings 0", "POST", "/api/log", {"meal": "brunch", "food_id": f1, "servings": 0}),
            ("POST /api/log servings -1", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": f1, "servings": -1}),
            ("POST /api/log servings 1001", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": f1, "servings": 1001}),
            ("POST /api/log servings 'abc'", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": f1, "servings": "abc"}),
            ("POST /api/log servings true", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "servings": True}),
            ("POST /api/log grams 0", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": f1, "grams": 0}),
            ("POST /api/log date 2026-02-30", "POST", "/api/log", {"date": "2026-02-30", "meal": "lunch", "food_id": f1}),
            ("POST /api/log date 2026-6-1", "POST", "/api/log", {"date": "2026-6-1", "meal": "lunch", "food_id": f1}),
            ("POST /api/log date number", "POST", "/api/log", {"date": 20260610, "meal": "lunch", "food_id": f1}),
            ("POST /api/log date null", "POST", "/api/log", {"date": None, "meal": "lunch", "food_id": f1}),
            ("POST /api/log meal null", "POST", "/api/log", {"date": D, "meal": None, "food_id": f1}),
            ("POST /api/log meal ' lunch '", "POST", "/api/log", {"date": d(D, 40), "meal": " lunch ", "food_id": f1}),
            ("POST /api/log food_id missing", "POST", "/api/log", {"date": D, "meal": "lunch"}),
            ("POST /api/log food_id 1.5", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": 1.5}),
            ("POST /api/log food_id 0", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": 0}),
            ("POST /api/log food_id 2^63", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": big}),
            ("POST /api/log food_id unknown", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": 999999}),
            ("POST /api/log note 501 chars", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": f1, "note": "x" * 501}),
            ("POST /api/log status eatn", "POST", "/api/log", {"date": D, "meal": "lunch", "food_id": f1, "status": "eatn"}),
            ("PUT /api/log/{id} servings 0", "PUT", self.entry_path("banana"), {"servings": 0}),
            ("PUT /api/log/{id} meal brunch", "PUT", self.entry_path("banana"), {"meal": "brunch"}),
            ("PUT /api/log/999999", "PUT", "/api/log/999999", {"servings": 1}),
            ("PUT /api/log/999999 bad body", "PUT", "/api/log/999999", {"servings": 0}),
            ("DELETE /api/log/999999", "DELETE", "/api/log/999999", None),
            ("POST /api/log/quick missing date", "POST", "/api/log/quick", {"meal": "lunch", "name": "x", "nutrients": {}}),
            ("POST /api/log/quick unknown nutrient", "POST", "/api/log/quick", {"date": D, "meal": "lunch", "name": "x", "nutrients": {"zinc_mg": 1, "iron": 2}}),
            ("POST /api/log/quick negative nutrient", "POST", "/api/log/quick", {"date": D, "meal": "lunch", "name": "x", "nutrients": {"sodium_mg": -1}}),
            ("POST /api/log/quick bad flag", "POST", "/api/log/quick", {"date": D, "meal": "lunch", "name": "x", "flags": ["no way"]}),
            ("POST /api/log/mark-eaten {}", "POST", "/api/log/mark-eaten", {}),
            ("POST /api/log/mark-eaten meal brunch", "POST", "/api/log/mark-eaten", {"date": D, "meal": "brunch"}),
            ("POST /api/log/copy-day missing to_date", "POST", "/api/log/copy-day", {"from_date": D}),
            ("POST /api/log/copy-day same day", "POST", "/api/log/copy-day", {"from_date": D, "to_date": D}),
            ("POST /api/log/copy-day meals [lunch, brunch]", "POST", "/api/log/copy-day", {"from_date": D, "to_date": d(D, 9), "meals": ["lunch", "brunch"]}),
            ("POST /api/log/copy-day meals []", "POST", "/api/log/copy-day", {"from_date": D, "to_date": d(D, 9), "meals": []}),
            ("POST /api/log/copy-day missing to_date + bad meals", "POST", "/api/log/copy-day", {"from_date": D, "meals": ["brunch"]}),
            ("POST /api/log/copy-day include bad", "POST", "/api/log/copy-day", {"from_date": D, "to_date": d(D, 9), "include": "some"}),
            ("POST /api/meals items []", "POST", "/api/meals", {"name": "x", "items": []}),
            ("POST /api/meals item servings 0", "POST", "/api/meals", {"name": "x", "items": [{"food_id": f1, "servings": 0}]}),
            ("POST /api/meals unknown food", "POST", "/api/meals", {"name": "x", "items": [{"food_id": 999999, "servings": 1}]}),
            ("POST /api/meals name blank", "POST", "/api/meals", {"name": "   ", "items": [{"food_id": f1, "servings": 1}]}),
            ("POST /api/meals/{id}/apply meal brunch", "POST", self.tpl_path("bk", "/apply"), {"date": D, "meal": "brunch"}),
            ("POST /api/meals/{id}/apply scale 0", "POST", self.tpl_path("bk", "/apply"), {"date": D, "meal": "lunch", "scale": 0}),
            ("POST /api/meals/999999/apply", "POST", "/api/meals/999999/apply", {"date": D, "meal": "lunch"}),
            ("GET /api/meals/999999", "GET", "/api/meals/999999", None),
            ("GET /api/log?date=2026-13-01", "GET", "/api/log?date=2026-13-01", None),
            ("GET /api/log?date=yesterday", "GET", "/api/log?date=yesterday", None),
            ("GET /api/log/range missing start", "GET", f"/api/log/range?end={D}", None),
            ("GET /api/log/range end before start", "GET", f"/api/log/range?start={D}&end={d(D, -1)}", None),
            ("GET /api/log/range 367 days", "GET", f"/api/log/range?start={D}&end={d(D, 366)}", None),
            ("GET /api/log/summary end before start", "GET", f"/api/log/summary?start={D}&end={d(D, -3)}", None),
            ("GET /api/plan/shopping missing end", "GET", f"/api/plan/shopping?start={D}", None),
            ("GET /api/foods/999999", "GET", "/api/foods/999999", None),
            ("GET /api/foods/2^63", "GET", f"/api/foods/{big}", None),
            ("GET /api/foods?q=201 chars", "GET", "/api/foods?q=" + "a" * 201, None),
            ("GET /api/foods?limit=0", "GET", "/api/foods?limit=0", None),
            ("PUT /api/foods/{builtin}", "PUT", f"/api/foods/{f1}", {"name": "x", "serving_desc": "1", "serving_g": 1}),
            ("DELETE /api/foods/{builtin}", "DELETE", f"/api/foods/{f1}", None),
            ("POST /api/foods serving_g 0", "POST", "/api/foods", {"name": "x", "serving_desc": "1", "serving_g": 0}),
            ("PUT /api/profile ckd_stage 6", "PUT", "/api/profile", {"ckd_stage": "6"}),
            ("PUT /api/profile weight 0", "PUT", "/api/profile", {"weight_kg": 0}),
            ("PUT /api/profile warn_fraction 1.5", "PUT", "/api/profile", {"warn_fraction": 1.5}),
            ("PUT /api/profile dialysis_days [7]", "PUT", "/api/profile", {"dialysis_days": [7]}),
            ("PUT /api/profile dialysis_days [1.5]", "PUT", "/api/profile", {"dialysis_days": [1.5]}),
            ("PUT /api/profile targets negative", "PUT", "/api/profile", {"targets": {"potassium_mg": -1}}),
            ("PUT /api/profile targets unknown key", "PUT", "/api/profile", {"targets": {"zinc_mg": 1}}),
            ("PUT /api/profile targets min > max", "PUT", "/api/profile", {"targets": {"protein_g": {"min": 60, "max": 50}}}),
            ("PUT /api/profile targets empty range", "PUT", "/api/profile", {"targets": {"protein_g": {}}}),
            ("PUT /api/profile targets string", "PUT", "/api/profile", {"targets": {"sodium_mg": "lots"}}),
            ("PUT /api/profile week_start friday", "PUT", "/api/profile", {"week_start": "friday"}),
            # whitespace around enum values (str_strip_whitespace does not apply to Literal fields?)
            ("PUT /api/log/{id} meal ' dinner '", "PUT", self.entry_path("ws"), {"meal": " dinner "}),
            ("PUT /api/log/{id} status ' eaten '", "PUT", self.entry_path("ws"), {"status": " eaten "}),
            ("POST /api/log status ' planned '", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "status": " planned "}),
            ("POST /api/log/mark-eaten meal ' lunch '", "POST", "/api/log/mark-eaten", {"date": d(D, 40), "meal": " lunch "}),
            ("POST /api/log/copy-day include ' all '", "POST", "/api/log/copy-day", {"from_date": d(D, 40), "to_date": d(D, 41), "include": " all "}),
            ("POST /api/log/copy-day meals [' lunch ']", "POST", "/api/log/copy-day", {"from_date": d(D, 40), "to_date": d(D, 41), "meals": [" lunch "]}),
            ("POST /api/meals/{id}/apply status ' eaten '", "POST", self.tpl_path("bk", "/apply"), {"date": d(D, 40), "meal": "lunch", "status": " eaten "}),
            ("PUT /api/profile ckd_stage ' 4 '", "PUT", "/api/profile", {"ckd_stage": " 4 "}),
            ("PUT /api/profile week_start ' sunday '", "PUT", "/api/profile", {"week_start": " sunday "}),
            ("POST /api/log date ' D '", "POST", "/api/log", {"date": f" {d(D, 40)} ", "meal": "lunch", "food_id": f1}),
            # booleans and strings in number fields
            ("POST /api/log grams true", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "grams": True}),
            ("POST /api/log servings false", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "servings": False}),
            ("POST /api/log food_id true", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": True}),
            ("POST /api/log servings '2'", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "servings": "2"}),
            ("POST /api/log servings ' 2 '", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "servings": " 2 "}),
            ("POST /api/log servings ''", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "servings": ""}),
            ("POST /api/log servings '1e2'", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "servings": "1e2"}),
            ("POST /api/log servings [1]", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": f1, "servings": [1]}),
            ("POST /api/log food_id '5'", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": "5"}),
            ("POST /api/log food_id 'abc'", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": "abc"}),
            ("POST /api/log food_id 3.0", "POST", "/api/log", {"date": d(D, 40), "meal": "lunch", "food_id": 3.0}),
            ("PUT /api/profile weight_kg true", "PUT", "/api/profile", {"weight_kg": True}),
            ("PUT /api/profile weight_kg 'abc'", "PUT", "/api/profile", {"weight_kg": "abc"}),
            ("POST /api/meals/{id}/apply scale true", "POST", self.tpl_path("bk", "/apply"), {"date": d(D, 40), "meal": "lunch", "scale": True}),
            ("GET /api/foods?limit=201", "GET", "/api/foods?limit=201", None),
            ("GET /api/foods?limit=abc", "GET", "/api/foods?limit=abc", None),
            ("GET /api/foods?limit=1.5", "GET", "/api/foods?limit=1.5", None),
            ("GET /api/foods?q=banana&limit=%201%20", "GET", "/api/foods?q=banana&limit=%201%20", None),
            # several errors in one request (order / completeness of the joined detail)
            ("POST /api/meals two bad items", "POST", "/api/meals", {"name": "x", "items": [{"food_id": f1, "servings": 0}, {"food_id": 1.5, "servings": 1}]}),
            ("POST /api/meals blank name + no items", "POST", "/api/meals", {"name": "", "items": []}),
            ("POST /api/meals missing items", "POST", "/api/meals", {"name": "x"}),
            ("POST /api/log/quick missing date + unknown nutrient", "POST", "/api/log/quick", {"meal": "lunch", "name": "x", "nutrients": {"zinc_mg": 1}}),
            ("POST /api/log/quick unknown nutrient + bad flag", "POST", "/api/log/quick", {"date": D, "meal": "lunch", "name": "x", "nutrients": {"zinc_mg": 1}, "flags": ["no way"]}),
            ("PUT /api/profile warn_fraction + targets + week_start bad", "PUT", "/api/profile", {"warn_fraction": 2, "targets": {"zinc_mg": 1}, "week_start": "friday"}),
            ("PUT /api/profile ckd_stage + dialysis_days bad", "PUT", "/api/profile", {"ckd_stage": "9", "dialysis_days": [8]}),
            ("POST /api/foods name blank + bad nutrients", "POST", "/api/foods", {"name": " ", "serving_desc": "1", "serving_g": 1, "nutrients": {"sodium_mg": -5}}),
            ("POST /api/foods/usda/import missing fdc_id", "POST", "/api/foods/usda/import", {}),
            ("GET /api/foods/usda/search?q=apple", "GET", "/api/foods/usda/search?q=apple", None),
        ]
        for label, method, path, body in ext:
            if isinstance(path, str) and path.startswith("/api/foods/usda/search"):
                # Both answer 503, by design with different words: the server says how to add a key
                # (reason "not_configured"); the demo has no server, and the UI shows its own
                # "needs the installed app" text (ARCHITECTURE.md, "Frontend modules").
                rs, rm = self.server.call(method, path, body), self.mock.call(method, path, body)
                self.rec.compare(S, f"{label} (status only)", rs["status"], rm["status"])
                continue
            self.both(S, label, method, path, body)
        # State after the requests above: differs only where one side accepted what the other rejected.
        S2 = "7c state after 7b (consequential, informative)"
        self.both(S2, "GET /api/log?date=D", "GET", f"/api/log?date={D}")
        self.both(S2, "GET /api/log?date=D+40", "GET", f"/api/log?date={d(D, 40)}")
        self.both(S2, "GET /api/log?date=D+41", "GET", f"/api/log?date={d(D, 41)}")
        self.both(S2, "GET /api/profile", "GET", "/api/profile")
        # Resync: drop the scratch days on both sides, restore the profile; from here state must match again.
        for side in (self.server, self.mock):
            for dt in (d(D, 40), d(D, 41)):
                r = side.call("GET", f"/api/log?date={dt}")
                for e in r["body"]["entries"]:
                    side.call("DELETE", f"/api/log/{e['id']}")
        S3 = "7d resync"
        self.put_profile(S3, "restore", self.PROFILE)
        self.both(S3, "GET /api/log?date=D", "GET", f"/api/log?date={D}")
        self.both(S3, "GET /api/log?date=D+40 (empty)", "GET", f"/api/log?date={d(D, 40)}")
        self.both(S3, "GET /api/log/range D-1..D+45", "GET", f"/api/log/range?start={d(D, -1)}&end={d(D, 45)}")

    def section9(self) -> None:
        S = "9 custom foods & target variants"
        D = "2026-08-20"
        rs, rm = self.both(S, "POST /api/foods custom", "POST", "/api/foods", {
            "name": '  Cookie, "homemade"  ', "brand": "  ", "category": "Home baking", "serving_desc": "1 cookie (50 g)", "serving_g": 50,
            "nutrients": {"calories_kcal": 210.25, "carbs_g": 29.95, "protein_g": 2.5, "sodium_mg": 140.5, "potassium_mg": 100.5,
                          "phosphorus_mg": 60, "fluid_ml": 12, "fiber_g": None, "sugar_g": ""},
            "flags": ["High_GI", "processed", "high_gi"], "kidney_notes": "  "})
        cid = (rs["body"]["id"], rm["body"]["id"])
        food = lambda suffix="": (lambda side: f"/api/foods/{cid[side]}{suffix}")
        self.both(S, "GET /api/foods/categories with custom category", "GET", "/api/foods/categories")
        self.both(S, "GET /api/foods?source=custom", "GET", "/api/foods?source=custom")
        self.both(S, "GET /api/foods?q=cookie", "GET", "/api/foods?q=cookie")
        rs, rm = self.both(S, "log custom by grams 120", "POST", "/api/log", lambda side: {"date": D, "meal": "snack", "food_id": cid[side], "grams": 120})
        eid = (rs["body"]["id"], rm["body"]["id"])
        self.both(S, "PUT custom food serving_g 40 + counts_as_fluid", "PUT", food(), {
            "name": "Cookie, homemade", "serving_desc": "1 cookie (40 g)", "serving_g": 40, "category": "",
            "nutrients": {"calories_kcal": 170, "carbs_g": 24.05, "potassium_mg": 80.5, "sodium_mg": 112}, "flags": ["counts_as_fluid", "hypo_treatment"]})
        self.both(S, "PUT grams-based entry note only -> servings follow new serving_g", "PUT", lambda side: f"/api/log/{eid[side]}", {"note": "after resize"})
        self.both(S, "copy-day custom entry", "POST", "/api/log/copy-day", {"from_date": D, "to_date": d(D, 1), "status": "eaten"})
        rs, rm = self.both(S, "POST /api/foods/{builtin}/copy", "POST", f"/api/foods/{self.fid('Cola, regular')}/copy")
        copy_id = (rs["body"]["id"], rm["body"]["id"])
        self.both(S, "PUT copied food", "PUT", lambda side: f"/api/foods/{copy_id[side]}", {
            "name": "Cola, regular (small)", "serving_desc": "8 fl oz (247 g)", "serving_g": 247,
            "nutrients": {"calories_kcal": 103, "carbs_g": 25.6, "sodium_mg": 7, "potassium_mg": 12, "phosphorus_mg": 22}, "flags": ["phosphate_additive", "high_gi", "counts_as_fluid"]})
        rs, rm = self.both(S, "POST /api/meals with custom + copy", "POST", "/api/meals", lambda side: {"name": "Treats", "items": [{"food_id": cid[side], "servings": 1.5}, {"food_id": copy_id[side], "servings": 1}]})
        tid = (rs["body"]["id"], rm["body"]["id"])
        self.both(S, "DELETE copied food (referenced by a meal -> hidden)", "DELETE", lambda side: f"/api/foods/{copy_id[side]}")
        self.both(S, "GET hidden copied food", "GET", lambda side: f"/api/foods/{copy_id[side]}")
        self.both(S, "GET meal with hidden item", "GET", lambda side: f"/api/meals/{tid[side]}")
        self.both(S, "apply meal with hidden item", "POST", lambda side: f"/api/meals/{tid[side]}/apply", {"date": d(D, 2), "meal": "dinner"})
        self.both(S, "search excludes hidden", "GET", "/api/foods?q=cola")
        rs, rm = self.both(S, "POST /api/foods unreferenced", "POST", "/api/foods", {"name": "Temp", "serving_desc": "1", "serving_g": 0.1, "nutrients": {"potassium_mg": 0.5}})
        tmp = (rs["body"]["id"], rm["body"]["id"])
        self.both(S, "DELETE unreferenced custom food", "DELETE", lambda side: f"/api/foods/{tmp[side]}")
        self.both(S, "GET deleted food -> 404", "GET", lambda side: f"/api/foods/{tmp[side]}")
        self.both(S, "GET /healthz after custom foods", "GET", "/healthz")
        self.compare_csv(S, f"/api/log/export.csv?start={D}&end={d(D, 2)}")
        self.compare_csv(S, "/api/log/export.csv")
        # target variants on the same days
        variants = [
            ("warn 0.55, decimals", {"warn_fraction": 0.55, "targets": {"potassium_mg": 2345.6, "calories_kcal": 1999.95, "carbs_per_meal_g": {"min": 30, "max": 45}, "sodium_mg": 0}}),
            ("warn 1.0, min-only protein", {"warn_fraction": 1, "targets": {"protein_g": {"min": 40}, "carbs_per_meal_g": 20, "fluid_ml": 1}}),
            ("week_start sunday, all null", {"week_start": "sunday", "targets": {k: None for k in ["calories_kcal", "protein_g", "carbs_g", "carbs_per_meal_g", "sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg", "fluid_ml"]}}),
            ("info targets", {"targets": {"fat_g": 10, "sat_fat_g": 2.25, "fiber_g": 30, "sugar_g": 5, "calcium_mg": 50.5}}),
        ]
        for label, body in variants:
            self.put_profile(S, label, body)
            for n in range(3):
                self.both(S, f"GET day D+{n} [{label}]", "GET", f"/api/log?date={d(D, n)}")
            self.both(S, f"summary D..D+6 [{label}]", "GET", f"/api/log/summary?start={D}&end={d(D, 6)}")
            self.both(S, f"range D..D+2 [{label}]", "GET", f"/api/log/range?start={D}&end={d(D, 2)}")
        self.put_profile(S, "restore", self.PROFILE)
        for q in ["%", "_", "2%", "(", "93%", "a_b", "'"]:
            path = "/api/foods?" + str(httpx2.QueryParams({"q": q}))
            self.both(S, f"search {q!r}", "GET", path)

    def section8(self) -> None:
        S = "8 bulk entries"
        start = "2025-03-03"
        amounts = [0.37, 0.5, 0.75, 1.25, 1.5, 2, 2.5, 3.3, 0.333, 1.1]
        meals = ["breakfast", "lunch", "dinner", "snack"]
        names = sorted(self.food_id, key=lambda n: self.food_id[n])
        calls: list = []
        for i, name in enumerate(names):
            body: dict[str, Any] = {"date": d(start, i % 7), "meal": meals[i % 4], "food_id": self.food_id[name],
                                    "status": "planned" if i % 5 == 0 else "eaten"}
            if i % 3 == 0:
                body["grams"] = [37.5, 55, 120, 250, 333, 18.25][i % 6]
            else:
                body["servings"] = amounts[i % len(amounts)]
            calls.append(["POST", "/api/log", body])
        server_res = [self.server.call(*c) for c in calls]
        mock_res = self.mock.seq(calls)
        for c, rs, rm in zip(calls, server_res, mock_res):
            self.rec.compare_resp(S, f"POST /api/log bulk food {c[2]['food_id']} {c[2].get('servings', c[2].get('grams'))}", rs, rm)
        for n in range(7):
            self.both(S, f"GET /api/log?date={d(start, n)}", "GET", f"/api/log?date={d(start, n)}")
        self.both(S, "GET /api/log/range bulk week", "GET", f"/api/log/range?start={start}&end={d(start, 6)}")
        self.both(S, "GET /api/log/summary bulk week", "GET", f"/api/log/summary?start={start}&end={d(start, 6)}")
        self.both(S, "GET /api/log/summary bulk next week (previous = bulk)", "GET", f"/api/log/summary?start={d(start, 7)}&end={d(start, 13)}")
        self.both(S, "GET /api/plan/shopping bulk week", "GET", f"/api/plan/shopping?start={start}&end={d(start, 6)}")
        self.compare_csv(S, f"/api/log/export.csv?start={start}&end={d(start, 6)}")
        self.both(S, "GET /api/foods (empty q, with history)", "GET", "/api/foods?limit=60")
        self.put_profile(S, "hemodialysis Tue/Thu/Sat", {"dialysis": "hemodialysis", "dialysis_days": [1, 3, 5]})
        for n in range(7):
            end = d(start, n)
            self.both(S, f"hemodialysis summary bulk end {end}", "GET", f"/api/log/summary?start={d(end, -6)}&end={end}")

    def section10(self) -> None:
        """Accounts routes: same keys and value types (the values differ by design)."""
        S = "10 accounts (shape)"

        def shape(v: Any) -> Any:
            if isinstance(v, dict):
                return {k: shape(x) for k, x in v.items()}
            if isinstance(v, list):
                return [shape(v[0])] if v else []
            if isinstance(v, bool):
                return "bool"
            if _is_num(v):
                return "number"
            return "null" if v is None else type(v).__name__

        for path in ("/api/auth/status", "/api/me", "/api/me/settings", "/api/me/keys"):
            rs, rm = self.server.call("GET", path), self.mock.call("GET", path)
            if rs["status"] != 200 or rm["status"] != 200:
                self.rec.compare(S, f"GET {path} status", rs["status"], rm["status"])
                continue
            self.rec.compare(S, f"GET {path} shape", shape(rs["body"]), shape(rm["body"]), ignore=frozenset())

        # GET /api/handbook: the demo has no handbook, so it answers like a server without one (url null,
        # no Learn links); its link table is empty, so only the groups are compared, not their entries.
        rs, rm = self.server.call("GET", "/api/handbook"), self.mock.call("GET", "/api/handbook")
        if rs["status"] != 200 or rm["status"] != 200:
            self.rec.compare(S, "GET /api/handbook status", rs["status"], rm["status"])
        else:
            top = lambda body: {k: shape(v) for k, v in body.items() if k != "links"}  # noqa: E731
            self.rec.compare(S, "GET /api/handbook shape", top(rs["body"]), top(rm["body"]), ignore=frozenset())
            self.rec.compare(S, "GET /api/handbook link groups", sorted(rs["body"]["links"]), sorted(rm["body"]["links"]),
                             ignore=frozenset())


    def section11(self) -> None:
        """Personalised targets and labs (note 05; ARCHITECTURE.md "M2 API: targets and labs")."""
        today = date.today()
        T = today.isoformat()
        ago = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
        month = lambda years: f"{today.year - years}-{today.month:02d}"  # noqa: E731
        base = {"name": "Targets", "weight_kg": 70, "height_cm": 170, "ckd_stage": "4", "dialysis": "none", "diabetes": "type1",
                "birth_month": None, "sex": None, "activity": None, "transplant_date": None, "frail_or_sarcopenic": None,
                "weight_6_months_ago_kg": None, "pregnant_or_breastfeeding": None, "hyperkalemia_history": None,
                "urine_output_ml": None, "pd_uf_ml": None, "pd_dialysate_kcal": None}

        S = "11a profile fields"
        self.put_profile(S, "baseline (every v0.3 field cleared)", base)
        for label, body in [
            ("every field set", {"birth_month": "1971-03", "sex": "female", "activity": "low_active", "transplant_date": "2019-05-02",
                                 "frail_or_sarcopenic": True, "weight_6_months_ago_kg": 74.5, "pregnant_or_breastfeeding": False,
                                 "hyperkalemia_history": True, "urine_output_ml": 800, "pd_uf_ml": 900, "pd_dialysate_kcal": 350}),
            ("blank strings clear (sex back to unspecified, bools to false)", {"birth_month": "  ", "sex": "", "activity": "", "transplant_date": "",
                                                                               "frail_or_sarcopenic": "", "urine_output_ml": " ", "hyperkalemia_history": None}),
            ("strings are stripped and parsed", {"birth_month": " 1971-03 ", "transplant_date": " 2020-01-01 ", "urine_output_ml": " 800 ",
                                                 "pd_dialysate_kcal": "1e3", "weight_6_months_ago_kg": "80.25"}),
            ("lax booleans", {"frail_or_sarcopenic": "Yes", "hyperkalemia_history": "off", "pregnant_or_breastfeeding": 0}),
            ("bool 1.0 and 1", {"frail_or_sarcopenic": 1.0, "hyperkalemia_history": 1}),
            ("birth month bad format", {"birth_month": "1971-13"}),
            ("birth month not a string", {"birth_month": 197103}),
            ("birth month next year", {"birth_month": f"{today.year + 1}-01"}),
            ("birth month 121 years ago", {"birth_month": f"{today.year - 121}-01"}),
            ("birth month year 0", {"birth_month": "0000-01"}),
            ("sex other", {"sex": "other"}),
            ("sex with a space", {"sex": " male"}),
            ("activity unknown", {"activity": "athlete"}),
            ("transplant date not a calendar date", {"transplant_date": "2026-02-30"}),
            ("transplant date in two days", {"transplant_date": (today + timedelta(days=2)).isoformat()}),
            ("transplant date tomorrow (time-zone slack)", {"transplant_date": (today + timedelta(days=1)).isoformat()}),
            ("transplant date before 1900", {"transplant_date": "1899-12-31"}),
            ("transplant date wrong format", {"transplant_date": "01/02/2020"}),
            ("transplant date a number", {"transplant_date": 20200101}),
            ("bool maybe", {"frail_or_sarcopenic": "maybe"}),
            ("bool padded", {"frail_or_sarcopenic": " true "}),
            ("bool 2", {"frail_or_sarcopenic": 2}),
            ("bool 1.5", {"frail_or_sarcopenic": 1.5}),
            ("bool list", {"frail_or_sarcopenic": []}),
            ("weight 6 months ago 19.9", {"weight_6_months_ago_kg": 19.9}),
            ("weight 6 months ago 400.0001", {"weight_6_months_ago_kg": 400.0001}),
            ("weight 6 months ago abc", {"weight_6_months_ago_kg": "abc"}),
            ("urine -1", {"urine_output_ml": -1}),
            ("urine 5001", {"urine_output_ml": 5001}),
            ("uf 4001", {"pd_uf_ml": 4001}),
            ("uf Infinity", {"pd_uf_ml": "Infinity"}),
            ("dialysate 1001 + sex x + birth month x (order)", {"pd_dialysate_kcal": 1001, "sex": "x", "birth_month": "x"}),
            ("v0.2 weight empty + v0.3 empty", {"weight_kg": "", "urine_output_ml": ""}),
        ]:
            self.put_profile(S, label, body)
            self.both(S, f"GET /api/profile after {label}", "GET", "/api/profile")

        S = "11b labs"
        self.put_profile(S, "labs profile", {**base, "birth_month": "1976-10", "sex": "female"})
        for label, body in [
            ("potassium 4.6 mEq/L", {"analyte": "potassium", "value": 4.6, "unit": "mEq/L", "taken_on": ago(20), "note": " clinic "}),
            ("potassium 6.3 urgent", {"analyte": "potassium", "value": 6.3, "unit": "mmol/L", "taken_on": ago(3)}),
            ("potassium 6.5 emergency", {"analyte": "potassium", "value": 6.45, "unit": "mmol/L", "taken_on": ago(2)}),
            ("potassium 5.94 (shown 5.9, no alert)", {"analyte": "potassium", "value": 5.94, "unit": "mmol/L", "taken_on": ago(1), "note": None}),
            ("phosphate 1.94 mmol/L", {"analyte": "phosphate", "value": 1.94, "unit": "mmol/L", "taken_on": ago(4)}),
            ("albumin 34 g/L", {"analyte": "albumin", "value": 34, "unit": "g/L", "taken_on": ago(30)}),
            ("bicarbonate 21 meq/l", {"analyte": "bicarbonate", "value": 21, "unit": "meq/l", "taken_on": ago(30)}),
            ("uacr 3.0 mg/mmol", {"analyte": "uacr", "value": 3.0, "unit": "mg/mmol", "taken_on": ago(30)}),
            ("creatinine 106 umol/l", {"analyte": "creatinine", "value": 106, "unit": "umol/l", "taken_on": ago(10)}),
            ("cystatin 1.6", {"analyte": "cystatin_c", "value": 1.6, "unit": "mg/L", "taken_on": ago(10)}),
            ("egfr 58.4 ml/min/1.73m2", {"analyte": "egfr", "value": 58.4, "unit": "ml/min/1.73m2", "taken_on": ago(200)}),
            ("a1c 53 mmol/mol", {"analyte": "a1c", "value": 53, "unit": "mmol/mol", "taken_on": ago(60)}),
            ("strings stripped and parsed", {"analyte": "potassium", "value": "4.5", "unit": " mmol/L ", "taken_on": f" {ago(400)} "}),
            ("uacr 0 mg/g", {"analyte": "uacr", "value": 0, "unit": "mg/g", "taken_on": ago(400)}),
            ("taken tomorrow (time-zone slack)", {"analyte": "albumin", "value": 4.1, "unit": "g/dL", "taken_on": (today + timedelta(days=1)).isoformat()}),
            # refused
            ("unknown analyte", {"analyte": "sodium", "value": 140, "unit": "mmol/L", "taken_on": T}),
            ("unit for another analyte", {"analyte": "potassium", "value": 4.2, "unit": "mg/dL", "taken_on": T}),
            ("implausible in the canonical unit", {"analyte": "potassium", "value": 42, "unit": "mmol/L", "taken_on": T}),
            ("implausible after conversion", {"analyte": "phosphate", "value": 15, "unit": "mmol/L", "taken_on": T}),
            ("value true (lax: 1.0, implausible)", {"analyte": "potassium", "value": True, "unit": "mmol/L", "taken_on": T}),
            ("negative", {"analyte": "potassium", "value": -1, "unit": "mmol/L", "taken_on": T}),
            ("over the ceiling", {"analyte": "potassium", "value": 1000001, "unit": "mmol/L", "taken_on": T}),
            ("NaN text", {"analyte": "potassium", "value": "NaN", "unit": "mmol/L", "taken_on": T}),
            ("empty unit", {"analyte": "potassium", "value": 4.2, "unit": "", "taken_on": T}),
            ("unit over 40 characters", {"analyte": "potassium", "value": 4.2, "unit": "x" * 41, "taken_on": T}),
            ("in two days", {"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": (today + timedelta(days=2)).isoformat()}),
            ("before 1900", {"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": "1899-10-01"}),
            ("not a calendar date", {"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": "2026-02-30"}),
            ("note over 500", {"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": T, "note": "x" * 501}),
            ("unknown field", {"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": T, "extra": 1}),
            ("every field wrong + extra (order)", {"extra": 1, "analyte": "x", "value": "abc", "unit": 5, "taken_on": 3, "note": 7}),
            ("missing fields", {"value": 4.2}),
            ("a list", [1, 2]),
            ("no body", None),
        ]:
            self.both(S, f"POST /api/labs {label}", "POST", "/api/labs", body)
        for q in ["", "?analyte=potassium", "?analyte=potassium&limit=1", "?limit=2", "?limit=5.0", "?analyte=", "?analyte=sodium",
                  "?limit=0", "?limit=1001", "?limit=abc", "?analyte=x&limit=0"]:
            self.both(S, f"GET /api/labs{q}", "GET", f"/api/labs{q}")
        listed = self.server.call("GET", "/api/labs?analyte=cystatin_c")["body"]["labs"], self.mock.call("GET", "/api/labs?analyte=cystatin_c")["body"]["labs"]
        if listed[0] and listed[1]:
            path = lambda side: f"/api/labs/{listed[side][0]['id']}"  # noqa: E731
            self.both(S, "DELETE /api/labs/{cystatin}", "DELETE", path)
            self.both(S, "DELETE /api/labs/{cystatin} again -> 404", "DELETE", path)
        else:
            self.rec.note_failure(S, "cystatin result listed", f"server {len(listed[0])}, mock {len(listed[1])}")
        for label, path in [("0", "/api/labs/0"), ("unknown id", "/api/labs/999999"), ("2**63", "/api/labs/9223372036854775808"),
                            ("not a number", "/api/labs/abc"), ("kidney-function", "/api/labs/kidney-function")]:
            self.both(S, f"DELETE /api/labs/{label}", "DELETE", path)
        self.both(S, "GET /api/labs after delete", "GET", "/api/labs")
        for label, body in [
            ("female 49", {}), ("male", {"sex": "male"}), ("sex unspecified", {"sex": None}), ("no birth month", {"birth_month": None}),
            ("transplant", {"transplant_date": "2019-01-01"}), ("hemodialysis", {"dialysis": "hemodialysis", "ckd_stage": "5"}),
            ("pregnant", {"pregnant_or_breastfeeding": True}), ("17 years old", {"birth_month": month(17)}),
            ("stage 3a", {"ckd_stage": "3a"}),
        ]:
            self.put_profile(S, f"kidney-function profile: {label}", {**base, "birth_month": "1976-10", "sex": "female", **body})
            self.both(S, f"GET /api/labs/kidney-function [{label}]", "GET", "/api/labs/kidney-function")

        S = "11c suggestions"
        profiles = [
            ("TV-like stage 4 adult", {}),
            ("no height, no age", {"height_cm": None}),
            ("older G3b female, low active", {"ckd_stage": "3b", "birth_month": "1952-04", "sex": "female", "activity": "low_active"}),
            ("G2 male active", {"ckd_stage": "2", "birth_month": "1986-01", "sex": "male", "activity": "active", "diabetes": "none"}),
            ("hemodialysis with urine", {"ckd_stage": "5", "dialysis": "hemodialysis", "urine_output_ml": 325, "birth_month": "1960-07"}),
            ("peritoneal with dialysate", {"ckd_stage": "5", "dialysis": "peritoneal", "urine_output_ml": 800, "pd_uf_ml": 913,
                                           "pd_dialysate_kcal": 350, "birth_month": "1976-05", "sex": "female"}),
            ("peritoneal, dialysate floor", {"ckd_stage": "5", "dialysis": "peritoneal", "pd_dialysate_kcal": 1000, "diabetes": "none"}),
            ("transplant G2, 6 years", {"ckd_stage": "2", "transplant_date": "2020-01-01", "birth_month": "1955-01"}),
            ("transplant G4", {"ckd_stage": "4", "transplant_date": "2020-01-01"}),
            ("nutrition risk", {"weight_kg": 50, "weight_6_months_ago_kg": 60, "frail_or_sarcopenic": True, "birth_month": "1950-01"}),
            ("BMI 34.6", {"weight_kg": 100}),
            ("high potassium history", {"hyperkalemia_history": True}),
            ("refusal: pregnant", {"pregnant_or_breastfeeding": True}),
            ("refusal: 17", {"birth_month": month(17)}),
            ("refusal: transplant 30 days ago", {"transplant_date": ago(30)}),
            ("transplant 84 days ago", {"transplant_date": ago(84)}),
        ]
        lab_sets = [
            ("no labs", []),
            ("normal labs", [("potassium", 4.4, "mmol/L", 5), ("phosphate", 3.6, "mg/dL", 5), ("albumin", 4.0, "g/dL", 5)]),
            ("abnormal labs", [("potassium", 5.8, "mmol/L", 2), ("phosphate", 1.94, "mmol/L", 2), ("albumin", 32, "g/L", 2),
                               ("bicarbonate", 17, "mmol/L", 2), ("uacr", 35, "mg/mmol", 2), ("a1c", 8.1, "%", 2)]),
            ("very high potassium, stale phosphate", [("potassium", 6.6, "mmol/L", 1), ("phosphate", 5.5, "mg/dL", 120)]),
        ]
        for lab_label, labs in lab_sets:
            self._clear_labs(S)
            for analyte, value, unit, days in labs:
                self.both(S, f"POST /api/labs [{lab_label}] {analyte}", "POST", "/api/labs",
                          {"analyte": analyte, "value": value, "unit": unit, "taken_on": ago(days)})
            for label, body in profiles:
                self.put_profile(S, f"{label} [{lab_label}]", {**base, "birth_month": "1971-03", **body})
                self.both(S, f"GET suggested-targets {label} [{lab_label}]", "GET", "/api/profile/suggested-targets")
        # The admin settings of note 05 §4.9 (both sides are admins; signing in counts as entering the password).
        self.put_profile(S, "settings profile", {**base, "birth_month": "1971-03"})
        for label, patch in [
            ("lab rules off", {"targets.lab_rules_enabled": False}),
            ("potassium counts for 1 day", {"targets.lab_rules_enabled": None, "targets.lab_fresh_days.potassium": 1}),
            ("default activity active", {"targets.lab_fresh_days.potassium": None, "targets.default_activity": "active"}),
            ("restored", {"targets.default_activity": None}),
        ]:
            self.both(S, f"PATCH /api/admin/settings {label}", "PATCH", "/api/admin/settings", patch, ignore=frozenset({"settings"}))
            self.both(S, f"GET suggested-targets [{label}]", "GET", "/api/profile/suggested-targets")
        self.put_profile(S, "no weight", {"weight_kg": None})
        self.both(S, "GET suggested-targets without a weight", "GET", "/api/profile/suggested-targets")
        self._clear_labs(S)
        self.put_profile(S, "restore", {**base, **self.PROFILE})

    def _clear_labs(self, section: str) -> None:
        """Delete every lab result on both sides (ids differ between the sides)."""
        for side, caller in ((0, self.server), (1, self.mock)):
            for row in caller.call("GET", "/api/labs?limit=1000")["body"]["labs"]:
                r = caller.call("DELETE", f"/api/labs/{row['id']}")
                if r["status"] != 204 and not (side == 1 and r["status"] == 200):
                    self.rec.note_failure(section, f"clear labs side {side}", json.dumps(r))

# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--server-python", default=sys.executable, help="interpreter that runs uvicorn (default: this one)")
    ap.add_argument("--port", type=int, default=SERVER_PORT, help=f"uvicorn port (default {SERVER_PORT})")
    ap.add_argument("--static-port", type=int, default=STATIC_PORT, help=f"preview site port (default {STATIC_PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory, wiped first (default {OUT})")
    ap.add_argument("--report", type=Path, default=None, help="report path (default <out>/report.json)")
    ap.add_argument("--sections", default="", help="comma-separated sections to run, e.g. 0,11 (section 1 always runs; default: all)")
    args = ap.parse_args(argv)
    args.server_python = os.path.abspath(args.server_python)  # the server runs in REPO; keep venv symlinks
    configure(args.out.resolve(), args.port, args.static_port)
    report_path = args.report or (OUT / "report.json")

    from playwright.sync_api import sync_playwright

    chrome = chromium_executable()
    rec = Recorder()
    console: list[str] = []
    server_version = subprocess.run([args.server_python, "-c", "import sys, sqlite3; print(sys.version.split()[0], sqlite3.sqlite_version)"],
                                    capture_output=True, text=True).stdout.strip()
    started = time.time()
    try:
        admin = start_processes(args.server_python)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
                page.on("console", lambda m: console.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
                page.goto(f"http://127.0.0.1:{STATIC_PORT}/index.html")
                page.wait_for_function("() => !!window.__kdlMock && typeof window.__kdlEvaluateWarnings === 'function'", timeout=30000)
                page.wait_for_timeout(1500)  # let the UI's first renders settle before resetting state
                page.evaluate(HELPERS_JS)
                reset = page.evaluate("() => window.__parity.reset()")
                print("mock reset:", reset)
                h = Harness(ServerSide(admin), MockSide(page), rec)
                steps = [("0", h.section0), ("1", h.section1), ("1b", h.section1b), ("2", h.section2), ("3", h.section3),
                         ("4", h.section4), ("5", h.section5), ("2b", lambda: h.section2("2b search (with history)")),
                         ("6", h.section6), ("7", h.section7), ("8", h.section8), ("9", h.section9), ("10", h.section10),
                         ("11", h.section11)]
                if args.sections:
                    wanted = {"1", *args.sections.split(",")}
                    steps = [(name, fn) for name, fn in steps if name in wanted]
                for name, fn in steps:
                    t0 = time.time()
                    try:
                        fn()
                    except Exception:  # noqa: BLE001
                        import traceback

                        rec.note_failure(f"{name} harness error", name, traceback.format_exc())
                    print(f"section {name} done in {time.time() - t0:.1f}s")
            finally:
                browser.close()
    finally:
        stop_processes()

    total_checks = sum(s["checks"] for s in rec.sections.values())
    total_failed = sum(s["failed"] for s in rec.sections.values())
    total_leaves = sum(s["leaves"] for s in rec.sections.values())
    report = {
        "server_python": args.server_python, "server_version": server_version, "seconds": round(time.time() - started, 1),
        "total_checks": total_checks, "total_failed": total_failed, "total_leaf_comparisons": total_leaves,
        "console": console, "sections": rec.sections,
    }
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nserver: {args.server_python} ({server_version})")
    print(f"{'section':34} {'checks':>7} {'passed':>7} {'failed':>7} {'leaves':>8}")
    for name, s in rec.sections.items():
        print(f"{name:34} {s['checks']:7} {s['passed']:7} {s['failed']:7} {s['leaves']:8}")
    print(f"{'TOTAL':34} {total_checks:7} {total_checks - total_failed:7} {total_failed:7} {total_leaves:8}")
    if console:
        print("\nbrowser console:")
        for line in console[:30]:
            print("  ", line[:300])
    for name, s in rec.sections.items():
        for mm in s["mismatches"]:
            print(f"\n[{name}] {mm['label']} ({mm['count']} diffs)")
            for df in mm["diffs"][:8]:
                print(f"   {df['severity']:6} {df['path']}: server={json.dumps(df['server'], default=str)[:400]} mock={json.dumps(df['mock'], default=str)[:400]}")
    print(f"\nreport: {report_path}")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
