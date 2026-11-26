#!/usr/bin/env python3
"""Generate tests/data/export_vectors.json: parity vectors for the browser twin of the export archive's CSV files and README.

    python3 tests/data/gen_export_vectors.py           # rewrite the file
    python3 tests/data/gen_export_vectors.py --check   # exit 1 when the committed file is stale

The iPhone app with no server builds the export .zip in the page (``app/static/js/mock/export.js``, ``M.exportZip``). Its CSV files
and README must be the server's for the same data (``app/account.py`` ``build_export``). This script fills one account on a fresh
server through the ordinary routes (and the Whoop tables directly, since Whoop is not reachable here), with values that test the
writer: commas, quotes, line breaks, text a spreadsheet would run as a formula, accents, whole numbers stored as decimals, a planned
entry, a low treatment, a deleted food's meal item, null cells. Then it downloads ``GET /api/me/export.zip`` and keeps:

* ``doc``: the export.json document (``exported_at`` and the user's ``created_at`` as given; the twin does not read them);
* ``food_sources``: ``{food_id: [source, source_license]}`` for every food an entry uses (log.csv takes these from the food row);
* ``files``: every CSV file's text and ``README.txt``, in the archive's order;
* ``readme_brand``: the product name and export format the README is written with;
* ``filename``: the archive's name for the username ``me`` on a fixed day, from ``account.export_filename``.

``node tests/js/run_vectors.mjs`` rebuilds every file from ``doc`` and ``food_sources`` and compares the text exactly.

Needs the app's dependencies (it starts the app against a temporary database and the real built-in food list).
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "export_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

D1, D2, D3 = "2026-10-05", "2026-10-06", "2026-10-07"
NOW = "2026-10-07T09:00:00Z"


def fill(client: Any, db_path: Path) -> None:
    def ok(r: Any) -> Any:
        assert r.status_code in (200, 201), r.text
        return r.json()

    def builtin(query: str) -> dict[str, Any]:
        return client.get("/api/foods", params={"q": query}).json()["foods"][0]

    banana, tablets = builtin("banana, raw"), builtin("glucose tablet")
    stew = ok(client.post("/api/foods", json={
        "name": 'Mum\'s "special" stew, with rice', "brand": "=HYPERLINK(\"http://evil\")", "category": "Mixed dishes",
        "serving_desc": "1 bowl, about 300 g", "serving_g": 300, "nutrients": {"potassium_mg": 410.4, "phosphorus_mg": 120, "carbs_g": 20,
                                                                                "protein_g": 12.25, "sodium_mg": 700.5},
        "kidney_notes": "Soak the potatoes first.\nThen boil them."}))
    tea = ok(client.post("/api/foods", json={
        "name": "-Crème brûlée tea ＝", "serving_desc": "1 cup", "serving_g": 240.5, "flags": ["counts_as_fluid"],
        "nutrients": {"fluid_ml": 240, "potassium_mg": 50}}))
    gone = ok(client.post("/api/foods", json={"name": "Old crackers", "serving_desc": "4", "serving_g": 20, "nutrients": {"sodium_mg": 180}}))
    ok(client.post("/api/log", json={"date": D1, "meal": "breakfast", "food_id": banana["id"], "servings": 1.5, "note": "+cmd|' /C calc'!A0"}))
    ok(client.post("/api/log", json={"date": D1, "meal": "lunch", "food_id": stew["id"], "grams": 150, "note": "half, \"warm\""}))
    ok(client.post("/api/log", json={"date": D2, "meal": "snack", "food_id": tablets["id"], "servings": 4}))
    ok(client.post("/api/log", json={"date": D3, "meal": "dinner", "food_id": tea["id"], "status": "planned", "note": "@later\nmaybe"}))
    ok(client.post("/api/meals", json={"name": "@SUM(1+1) lunch", "note": "for work, packed", "items": [
        {"food_id": banana["id"], "servings": 2}, {"food_id": stew["id"], "servings": 0.333}, {"food_id": gone["id"], "servings": 1}]}))
    ok(client.post("/api/meals", json={"name": "Just tea", "items": [{"food_id": tea["id"], "servings": 1}]}))
    assert client.delete(f"/api/foods/{gone['id']}").status_code in (200, 204)
    ok(client.post("/api/labs", json={"analyte": "potassium", "value": 5, "unit": "mmol/L", "taken_on": D1}))
    ok(client.post("/api/labs", json={"analyte": "creatinine", "value": 110, "unit": "µmol/L", "taken_on": D2, "note": "=fasting, early"}))
    ok(client.post("/api/labs", json={"analyte": "phosphate", "value": 4.65, "unit": "mg/dL", "taken_on": D3}))
    ok(client.post("/api/symptoms", json={"date": D1, "symptom": "tiredness", "severity": 1, "note": "after dialysis"}))
    ok(client.post("/api/symptoms", json={"date": D2, "symptom": "other", "severity": 2, "label": "Dry mouth, \"bad\"", "note": "line one\nline two"}))
    ok(client.post("/api/body/weights", json={"date": D1, "kg": 70.25, "context": "morning", "time": "07:30", "note": "-before breakfast"}))
    ok(client.post("/api/body/weights", json={"date": D2, "kg": 72, "context": "other"}))
    ok(client.post("/api/body/blood-pressure", json={"date": D1, "systolic": 128, "diastolic": 78, "pulse": 66, "context": "morning", "time": "07:35"}))
    ok(client.post("/api/body/blood-pressure", json={"date": D2, "systolic": 141, "diastolic": 90, "context": "other", "note": "after the stairs, tired"}))
    uid = client.get("/api/me").json()["id"]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""INSERT INTO activity_days (user_id, date, source, source_key, kcal, strain, recovery_pct, resting_hr, hrv_ms, sleep_minutes,
                        sleep_performance_pct, finished, created_at, updated_at) VALUES (?, ?, 'whoop', 'whoop:cycle:1', 2210, 12.5, 64, 58, 41.0, 431, 88, 1, ?, ?)""",
                     (uid, D1, NOW, NOW))
        conn.execute("""INSERT INTO activity_days (user_id, date, source, source_key, kcal, strain, finished, created_at, updated_at)
                        VALUES (?, ?, 'whoop', 'whoop:cycle:2', NULL, 3.0, 0, ?, ?)""", (uid, D2, NOW, NOW))
        conn.execute("""INSERT INTO activity_workouts (user_id, date, start_time, end_time, minutes, sport, kcal, strain, source, source_key, created_at, updated_at)
                        VALUES (?, ?, '17:05', '17:50', 45, 'Walking, brisk', 210, 6.25, 'whoop', 'whoop:workout:a', ?, ?)""", (uid, D1, NOW, NOW))
        # Fixed times, so the file is the same at every run (the twin copies them from the document either way).
        for table in ("log_entries", "foods", "meal_templates", "lab_results", "symptoms", "weights", "blood_pressures"):
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            sets = ", ".join(f"{c} = ?" for c in ("created_at", "updated_at") if c in cols)
            conn.execute(f"UPDATE {table} SET {sets} WHERE {'user_id' if 'user_id' in cols else 'owner_user_id'} = ?",
                         [NOW] * sets.count("?") + [uid])
        conn.commit()
    finally:
        conn.close()


def build() -> dict[str, Any]:
    """The whole document (also what ``tests/test_export_vectors.py`` compares the committed file with)."""
    from starlette.testclient import TestClient as BareClient

    from app import account, brand
    from app.main import create_app
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, CSRF_HEADERS, make_settings

    foods = ROOT / "data" / "foods.json"
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), foods)
        with BareClient(create_app(settings), base_url="http://localhost", headers=dict(CSRF_HEADERS)) as client:
            r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
            assert r.status_code == 200, r.text
            fill(client, settings.db_path)
            r = client.get("/api/me/export.zip")
            assert r.status_code == 200, r.text
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names = z.namelist()
                texts = {name: z.read(name).decode("utf-8") for name in names}
        conn = sqlite3.connect(settings.db_path)
        try:
            doc = json.loads(texts["export.json"])
            used = sorted({e["food_id"] for e in doc["log_entries"]})
            sources = {str(row[0]): [row[1], row[2]] for row in conn.execute(
                f"SELECT id, source, source_license FROM foods WHERE id IN ({', '.join('?' for _ in used)})", used)}
        finally:
            conn.close()
    stamp = "2026-11-26"
    filename = account.export_filename("me").rsplit("-", 3)[0] + f"-{stamp}.zip"
    return {
        "names": names,
        "doc": doc,
        "food_sources": sources,
        "files": {name: texts[name] for name in names if name != "export.json"},
        "readme_brand": {"name": brand.NAME, "export_format": brand.EXPORT_FORMAT},
        "filename": {"username": "me", "day": stamp, "name": filename},
        "filename_cases": [{"username": u, "safe": account.export_filename(u).removeprefix(f"{brand.SLUG}-").rsplit("-", 3)[0]}
                           for u in ("me", "sam.o'neil", "Zoë Smith", "a" * 50, "")],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    built = build()
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8"))["files"] != built["files"]:
            print(f"{OUT} is stale: run python3 tests/data/gen_export_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(json.dumps(built, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
