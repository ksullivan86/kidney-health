#!/usr/bin/env python3
"""Upgrade a populated older database to this version's schema and check every row came along.

    python tools/e2e/upgrade.py                      # both: v0.2 (8b8d4ec) and the M1 schema v3 (9ef9151)
    python tools/e2e/upgrade.py --only v3 --port 8071 --out /tmp/kh-upgrade

For each starting point it unpacks that commit of this repository with ``git archive`` (no worktree, the
checkout is not touched) into ``<out>/src-<name>``, runs that version's server on a fresh ``DATA_DIR`` and fills it
through its own API (two people for v3: profile, eaten and planned entries by servings and by grams, a quick add, a
custom food, a saved meal, a personal setting and a USDA key), stops it, then starts **this** checkout's server on
a copy of that directory and compares, through the API and in SQLite:

* every entry (food, meal, status, servings, grams, nutrients), the day totals, the profile and its targets, saved
  meals, custom foods and the CSV rows are the same as before;
* the new columns hold their "nothing yet" values (``purpose`` and ``client_id`` null, ``meal_hint`` null, ``gtin``
  null, empty ``additives``/``quality``) and every step 4–7 table exists; ``meta.schema_version`` is the newest step;
* the v0.3 features work on the old data: a lab result changes the suggestion, What fits now and the plan answer,
  ``POST /api/log/batch`` and a ``client_id`` replay, the export zip carries the old rows and the new ones;
* v0.2 only: the old ``APP_PASSWORD`` becomes the admin's password (user 1 keeps the data), ``kidney.db.pre-v3.bak``
  is written once with mode 0600, HTTP Basic is gone; v3 only: the second person's rows stay theirs, the USDA key
  still opens (same ``SECRET_KEY`` file on the volume).

Prints PASS / FAIL lines, writes ``<out>/report.json``; exit status 1 on any failure. Every server is stopped.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

import httpx2

import khserver
from khserver import REPO, Api, Server

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "upgrade"
PORT = 8071
STARTS = {"v0.2": "8b8d4ec", "v3": "9ef9151"}  # the v0.2 release; the M1 build (schema step 3) before M2 started
RESULTS: list[dict[str, Any]] = []
DAY, NEXT = "2026-09-30", "2026-10-01"
APP_PASSWORD = "violet harbour 9 compass ridge"
USDA_KEY = "own-usda-key-for-the-upgrade-0123456789"
NEW_TABLES = ("lab_results", "food_preferences", "ai_providers", "ai_consents", "ai_usage", "ai_audit", "barcode_cache")


def check(area: str, name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"area": area, "check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} [{area}] {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def unpack(rev: str, dest: Path) -> Path:
    """``git archive <rev>`` into ``dest`` (a scratch copy: the repository's checkout is never touched)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(REPO), "archive", rev], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
    return dest


ENTRY_KEYS = ("food_name", "meal", "status", "servings", "grams", "note", "nutrients", "date")


def core(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: entry.get(k) for k in ENTRY_KEYS}


def fill(api: Api, *, custom: str) -> dict[str, Any]:
    """The same story in either old version: what one person typically has after some weeks."""
    api.json("PUT", "/api/profile", {"name": custom.split("'")[0], "weight_kg": 64, "ckd_stage": "4", "dialysis": "hemodialysis",
                                     "dialysis_days": [0, 2, 4], "week_start": "sunday",
                                     "targets": {"potassium_mg": 2500, "phosphorus_mg": 900, "sodium_mg": 2000, "carbs_per_meal_g": 60,
                                                 "protein_g": {"min": 70, "max": 84}, "fluid_ml": 1500}})
    banana = api.json("GET", "/api/foods?q=banana")["foods"][0]
    rice = api.json("GET", "/api/foods?q=rice white")["foods"][0]
    soup = api.json("POST", "/api/foods", {"name": custom, "serving_desc": "1 bowl", "serving_g": 250,
                                           "nutrients": {"potassium_mg": 210, "sodium_mg": 480, "carbs_g": 12}})
    api.json("POST", "/api/log", {"date": DAY, "meal": "breakfast", "food_id": banana["id"], "servings": 1})
    api.json("POST", "/api/log", {"date": DAY, "meal": "dinner", "food_id": soup["id"], "grams": 300, "note": "with bread"})
    api.json("POST", "/api/log", {"date": DAY, "meal": "lunch", "food_id": rice["id"], "servings": 0.75})
    api.json("POST", "/api/log", {"date": NEXT, "meal": "lunch", "food_id": soup["id"], "status": "planned"})
    api.json("POST", "/api/log/quick", {"date": NEXT, "meal": "snack", "name": "Rice cake", "nutrients": {"carbs_g": 7}})
    meal = api.json("POST", "/api/meals", {"name": "Usual breakfast", "items": [{"food_id": banana["id"], "servings": 0.5},
                                                                               {"food_id": rice["id"], "servings": 1}]})
    return {"banana": banana, "rice": rice, "soup": soup, "meal": meal}


def snapshot(api: Api) -> dict[str, Any]:
    return {
        "day": api.json("GET", f"/api/log?date={DAY}"),
        "next": api.json("GET", f"/api/log?date={NEXT}"),
        "profile": api.json("GET", "/api/profile"),
        "meals": api.json("GET", "/api/meals")["meals"],
        "csv": api.call("GET", f"/api/log/export.csv?start={DAY}&end={NEXT}").text,
    }


def compare(area: str, before: dict[str, Any], api: Api, custom: str) -> None:
    after = snapshot(api)
    for key in ("day", "next"):
        check(area, f"entries of {before[key]['date']} unchanged (food, meal, status, servings, grams, note, nutrients)",
              [core(e) for e in after[key]["entries"]] == [core(e) for e in before[key]["entries"]],
              json.dumps([core(e) for e in after[key]["entries"]])[:400])
        check(area, f"totals of {before[key]['date']} unchanged", after[key]["totals"] == before[key]["totals"])
        check(area, f"entries of {before[key]['date']} have no purpose or client_id yet",
              all(e.get("purpose") is None and e.get("client_id") is None for e in after[key]["entries"]))
    keys = ("name", "weight_kg", "ckd_stage", "dialysis", "dialysis_days", "week_start", "targets")
    check(area, "profile and targets unchanged", {k: after["profile"][k] for k in keys} == {k: before["profile"][k] for k in keys},
          json.dumps({k: after["profile"].get(k) for k in keys})[:300])
    check(area, "the new profile fields start empty", after["profile"].get("birth_month") is None and after["profile"].get("sex") == "unspecified"
          and after["profile"].get("activity") is None)
    strip = lambda m: {k: v for k, v in m.items() if k not in ("updated_at", "meal_hint")}  # noqa: E731
    check(area, "saved meals unchanged", [strip(m) for m in after["meals"]] == [strip(m) for m in before["meals"]])
    check(area, "saved meals have no meal_hint yet", all(m.get("meal_hint") is None for m in after["meals"]))
    old_rows, new_rows = before["csv"].splitlines(), after["csv"].splitlines()
    check(area, "CSV: the same rows, with the v0.3 columns added at the end", len(old_rows) == len(new_rows)
          and all(n.startswith(o) for o, n in zip(old_rows[1:], new_rows[1:])), f"{old_rows[:2]} / {new_rows[:2]}")
    food = api.json("GET", f"/api/foods?q={custom.split()[0]}")["foods"][0]
    check(area, "the custom food carries over without barcode data", food["name"] == custom and food.get("gtin") is None
          and food.get("additives") == [] and food.get("quality") == [], json.dumps(food)[:300])


def new_features(area: str, api: Api) -> None:
    """v0.3 on old data: labs, suggestion, guidance, batch with client_id, export."""
    r = api.call("POST", "/api/labs", {"analyte": "potassium", "value": 5.9, "unit": "mmol/L", "taken_on": DAY})
    check(area, "a lab result can be added", r.status_code == 201, r.text[:200])
    sug = api.json("GET", "/api/profile/suggested-targets")
    check(area, "the suggestion reads the lab and the old profile", sug["derived"]["labs_used"]["potassium"] is not None
          and sug["derived"]["mode"] == "hemodialysis", json.dumps(sug["derived"])[:300])
    fits = api.json("GET", f"/api/guidance/next-meal?meal=dinner&date={NEXT}")
    check(area, "What fits now answers on the old log", fits["status"] == "ok" and fits["foods"], json.dumps(fits)[:200])
    plan = api.json("POST", "/api/guidance/plan-day", {"date": NEXT})
    check(area, "Plan the rest of my day answers", plan["status"] == "ok" and plan["meals"])
    usual = [m["name"] for m in fits.get("saved_meals", [])]
    check(area, "the old saved meal is offered as a saved meal (no meal_hint: any main meal)", "Usual breakfast" in usual, json.dumps(usual))
    body = {"entries": [{"date": NEXT, "meal": "dinner", "food_id": api.json("GET", "/api/foods?q=apple")["foods"][0]["id"],
                         "client_id": "5b2c6a1e-9f0d-4c3b-8a7e-6d5c4b3a2f10"}]}
    first, again = api.call("POST", "/api/log/batch", body), api.call("POST", "/api/log/batch", body)
    check(area, "POST /api/log/batch with a client_id: created once, then 'existing'", first.status_code == 201 and again.status_code == 200
          and again.json()["results"][0]["result"] == "existing")
    z = api.call("GET", "/api/me/export.zip")
    with zipfile.ZipFile(io.BytesIO(z.content)) as arc:
        doc = json.loads(arc.read("export.json"))
    check(area, "the export holds the old entries and the new lab result", z.status_code == 200 and len(doc["log_entries"]) >= 6
          and len(doc["lab_results"]) == 1)


def schema(area: str, db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    newest = max(int(p.name[1:4]) for p in (REPO / "app" / "migrations").glob("m0*.py"))
    check(area, f"schema migrated to the newest step ({newest})", int(version) == newest, version)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    check(area, "the tables of steps 4–7 exist", set(NEW_TABLES) <= tables, str(sorted(set(NEW_TABLES) - tables)))
    check(area, "SQLite integrity check", conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    check(area, "no foreign key violations", conn.execute("PRAGMA foreign_key_check").fetchall() == [])
    return conn


# --------------------------------------------------------------------------- v0.2 → now

def from_v02(out: Path, port: int, python: str) -> None:
    area = "v0.2"
    src = unpack(STARTS["v0.2"], out / "src-v0.2")
    old = Server(port, out / "data-v0.2", log_path=out / "server-v0.2.log", env={"APP_PASSWORD": APP_PASSWORD}, repo=src, python=python)
    old.start()
    try:
        api = Api(old.base, auth=("anyone", APP_PASSWORD))
        check(area, "v0.2 answers with HTTP Basic and the APP_PASSWORD", api.call("GET", "/api/profile").status_code == 200)
        fill(api, custom="Grandma's leek soup")
        before = snapshot(api)
        api.close()
    finally:
        old.stop()
    data = out / "data-v0.2-upgraded"
    shutil.copytree(out / "data-v0.2", data)
    new = Server(port + 1, data, log_path=out / "server-v0.2-upgraded.log", env={"APP_PASSWORD": APP_PASSWORD}, fresh=False, python=python)
    new.start()
    try:
        log = new.log()
        check(area, "APP_PASSWORD is imported once as the first admin's password", "APP_PASSWORD is deprecated and was imported once" in log)
        bak = data / "kidney.db.pre-v3.bak"
        check(area, "kidney.db.pre-v3.bak written, mode 0600", bak.is_file() and stat.S_IMODE(bak.stat().st_mode) == 0o600)
        check(area, "HTTP Basic is gone", httpx2.get(f"{new.base}/api/profile", auth=("anyone", APP_PASSWORD), trust_env=False).status_code == 401)
        api = Api(new.base)
        me = api.json("POST", "/api/auth/login", {"username": "admin", "password": APP_PASSWORD})["user"]
        check(area, "the admin is user 1 and keeps the v0.2 data", me["id"] == 1 and me["role"] == "admin")
        compare(area, before, api, "Grandma's leek soup")
        new_features(area, api)
        conn = schema(area, data / "kidney.db")
        try:
            owners = {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM log_entries")}
            check(area, "every entry belongs to user 1", owners == {1}, str(owners))
        finally:
            conn.close()
        api.close()
    finally:
        new.stop()


# --------------------------------------------------------------------------- M1 (schema v3) → now

def from_v3(out: Path, port: int, python: str) -> None:
    area = "v3 (M1)"
    src = unpack(STARTS["v3"], out / "src-v3")
    old = Server(port, out / "data-v3", log_path=out / "server-v3.log", repo=src, python=python)
    old.start()
    try:
        admin = khserver.first_admin(old, "mum")
        sam = khserver.invite_user(old, admin, "sam")
        admin.json("PATCH", "/api/me/settings", {"ui.theme": "dark"})
        key = admin.call("PUT", "/api/me/keys/usda", {"api_key": USDA_KEY})
        check(area, "M1: a personal USDA key is stored", key.status_code == 200, key.text[:200])
        fill(admin, custom="Mum's lentil stew")
        fill(sam, custom="Sam's bean chili")
        before = {"mum": snapshot(admin), "sam": snapshot(sam)}
        conn = sqlite3.connect(out / "data-v3" / "kidney.db")
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        conn.close()
        check(area, "the starting database is schema v3", version == "3", version)
        admin.close()
        sam.close()
    finally:
        old.stop()
    data = out / "data-v3-upgraded"
    shutil.copytree(out / "data-v3", data)
    new = Server(port + 1, data, log_path=out / "server-v3-upgraded.log", fresh=False, python=python)
    new.start()
    try:
        apis = {name: Api(new.base) for name in ("mum", "sam")}
        for name, api in apis.items():
            api.login(name)
            compare(f"{area} {name}", before[name], api, "Mum's lentil stew" if name == "mum" else "Sam's bean chili")
        new_features(f"{area} mum", apis["mum"])
        keys = apis["mum"].json("GET", "/api/me/keys")["providers"]
        usda = next(k for k in keys if k["provider"] == "usda")
        check(area, "the USDA key still opens (same SECRET_KEY on the volume) and is never shown",
              usda["own"]["set"] is True and usda["own"].get("status") != "unreadable" and USDA_KEY not in json.dumps(keys), json.dumps(usda)[:300])
        check(area, "the personal setting carries over", apis["mum"].json("GET", "/api/me/settings")["settings"]["ui.theme"]["value"] == "dark")
        sam_labs = apis["sam"].json("GET", "/api/labs")["labs"]
        check(area, "the second person sees none of the first person's new lab results", sam_labs == [])
        conn = schema(area, data / "kidney.db")
        try:
            per_user = {r[0]: r[1] for r in conn.execute("SELECT user_id, COUNT(*) FROM log_entries GROUP BY user_id")}
            check(area, "each person's entries stay theirs", set(per_user) == {1, 2}, json.dumps(per_user))
        finally:
            conn.close()
        check(area, "no pre-v3 backup is written for a v3 database", not (data / "kidney.db.pre-v3.bak").exists())
        for api in apis.values():
            api.close()
    finally:
        new.stop()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT, help=f"the old server; the upgraded one uses the next port (default {PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory (default {OUT})")
    ap.add_argument("--only", default="", help="v0.2, v3 or both (default)")
    ap.add_argument("--server-python", default=sys.executable, help="interpreter that runs the servers (default: this one)")
    args = ap.parse_args(argv)
    only = [s for s in args.only.split(",") if s] or list(STARTS)
    if any(s not in STARTS for s in only):
        ap.error(f"--only takes {', '.join(STARTS)}")
    for port in (args.port, args.port + 1):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    steps: dict[str, Callable[[Path, int, str], None]] = {"v0.2": from_v02, "v3": from_v3}
    for name in only:
        try:
            steps[name](out, args.port, args.server_python)
        except Exception as exc:  # report and go on
            import traceback
            check(name, "finished", False, f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
    failed = [r for r in RESULTS if not r["ok"]]
    (out / "report.json").write_text(json.dumps({"failed": len(failed), "results": RESULTS}, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
