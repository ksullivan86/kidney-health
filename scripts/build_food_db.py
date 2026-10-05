#!/usr/bin/env python3
"""Build ``data/foods.json`` (the builtin food database) from USDA SR Legacy.

How to regenerate
=================

    python3 scripts/build_food_db.py

That is all. The script:

1. downloads the USDA FoodData Central *SR Legacy* CSV release (April 2018,
   ~6 MB zip) into ``scripts/.cache/`` -- the download is skipped when the
   zip is already there, so re-runs are offline and take a few seconds;
2. reads ``food.csv``, ``nutrient.csv``, ``food_nutrient.csv``,
   ``food_portion.csv`` and ``measure_unit.csv`` straight out of the zip;
3. for every entry in ``scripts/curated_foods.py`` pulls the 12 nutrients the
   app tracks (per 100 g), scales them to the curated household serving,
   derives ``fluid_ml`` from the water content for foods flagged
   ``counts_as_fluid``, rounds (mg -> integer, g/kcal -> 1 decimal) and
   validates categories, flags and ids;
4. writes ``data/foods.json`` in the shape defined in ARCHITECTURE.md and
   prints a per-category count plus a few sanity checks against well-known
   values (banana potassium, milk phosphorus, ...).

It fails loudly (non-zero exit, clear message) if a curated ``fdc_id`` is not
in SR Legacy, a required nutrient is missing, a flag/category is misspelled,
or a sanity check is out of range. Sugars, fibre and saturated fat are allowed
to be ``null`` because SR Legacy lacks them for some foods.

Options::

    --version 2026-10-05.2   version string stored in the JSON (default: today + ".1").
                             The backend re-imports builtin foods only when this changes,
                             so bump the suffix when regenerating on the same day.
    --cache-dir DIR          where the zip is cached (default scripts/.cache)
    --out FILE               output path (default data/foods.json)
    --verbose                list every serving size that does not match a USDA portion

To add or change foods edit ``scripts/curated_foods.py`` (find fdc_ids by
searching ``food.csv`` descriptions -- never guess them), re-run this script and
commit both the script change and the regenerated ``data/foods.json``.

Entries in ``curated_foods.py`` that carry ``manual_nutrients`` (glucose tablets,
salt substitute ...) have no USDA record; they are written with
``fdc_id = -manual_id`` so they still get a stable, unique id for the backend's
upsert without ever colliding with a real USDA id.

Data source: USDA Agricultural Research Service, FoodData Central, SR Legacy
(2018-04), https://fdc.nal.usda.gov/download-datasets.html -- public domain.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from curated_foods import CATEGORIES, CURATED_FOODS, FLAGS  # noqa: E402

ZIP_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip"
ZIP_NAME = "FoodData_Central_sr_legacy_food_csv_2018-04.zip"

SOURCE = (
    "USDA FoodData Central, SR Legacy (April 2018 release), "
    "https://fdc.nal.usda.gov/ - public domain. Nutrients are per the listed "
    "household serving, scaled from the USDA per-100 g values. Entries with a "
    "negative fdc_id are not USDA records; their values come from product labels."
)

# Registry key -> (SR Legacy nutrient id, expected unit). Order = output order.
NUTRIENTS = [
    ("calories_kcal", 1008, "KCAL"),
    ("protein_g", 1003, "G"),
    ("fat_g", 1004, "G"),
    ("sat_fat_g", 1258, "G"),
    ("carbs_g", 1005, "G"),
    ("fiber_g", 1079, "G"),
    ("sugar_g", 2000, "G"),
    ("sodium_mg", 1093, "MG"),
    ("potassium_mg", 1092, "MG"),
    ("phosphorus_mg", 1091, "MG"),
    ("calcium_mg", 1087, "MG"),
]
WATER_ID = 1051  # "Water", G -> fluid_ml for counts_as_fluid foods
NUTRIENT_KEYS = [k for k, _, _ in NUTRIENTS] + ["fluid_ml"]
NUTRIENT_IDS = {nid for _, nid, _ in NUTRIENTS} | {WATER_ID}
# SR Legacy does not report these for every food; null is acceptable.
OPTIONAL_IDS = {1258, 1079, 2000}
MG_KEYS = {"sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg", "fluid_ml"}

# (fdc_id, nutrient key, min, max) per 100 g -- guards against a broken
# column/unit mapping. Values are from the USDA records themselves.
SANITY_PER_100G = [
    (173944, "potassium_mg", 330, 390, "Banana, raw"),
    (169098, "potassium_mg", 180, 220, "Orange juice, raw"),
    (171267, "potassium_mg", 125, 155, "Milk, 2%"),
    (171267, "phosphorus_mg", 80, 105, "Milk, 2%"),
    (168878, "potassium_mg", 25, 45, "Rice, white, cooked"),
]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fail(msg: str) -> None:
    log(f"ERROR: {msg}")
    sys.exit(1)


# --------------------------------------------------------------------- download
def ensure_zip(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / ZIP_NAME
    if target.exists() and zipfile.is_zipfile(target):
        log(f"Using cached {target}")
        return target
    log(f"Downloading {ZIP_URL} -> {target}")
    ctx = ssl.create_default_context()  # honours SSL_CERT_FILE / system CA store
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(),  # reads HTTPS_PROXY / NO_PROXY from the env
        urllib.request.HTTPSHandler(context=ctx),
    )
    req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "kidney-health-build-food-db/1.0"})
    fd, tmp_name = tempfile.mkstemp(dir=cache_dir, suffix=".part")
    try:
        with opener.open(req, timeout=120) as resp, os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(resp, out, 1 << 16)
        if not zipfile.is_zipfile(tmp_name):
            fail("downloaded file is not a zip archive (proxy or network problem?)")
        os.chmod(tmp_name, 0o644)  # mkstemp creates 0600; make the cache shareable
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    log(f"Downloaded {target.stat().st_size / 1e6:.1f} MB")
    return target


# ------------------------------------------------------------------ zip readers
def open_member(zf: zipfile.ZipFile, basename: str):
    """Return a text reader for the CSV called ``basename`` wherever it sits in the zip."""
    matches = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == basename]
    if len(matches) != 1:
        fail(f"expected exactly one {basename} in the zip, found {matches}")
    return csv.DictReader(io.TextIOWrapper(zf.open(matches[0]), encoding="utf-8", newline=""))


def read_nutrient_units(zf: zipfile.ZipFile) -> None:
    units = {int(r["id"]): r["unit_name"].upper() for r in open_member(zf, "nutrient.csv")}
    for key, nid, unit in NUTRIENTS + [("fluid_ml (water)", WATER_ID, "G")]:
        if nid not in units:
            fail(f"nutrient id {nid} ({key}) is not in nutrient.csv")
        if units[nid] != unit:
            fail(f"nutrient {nid} ({key}) is reported in {units[nid]}, expected {unit}")


def read_foods(zf: zipfile.ZipFile, wanted: set[int]) -> dict[int, str]:
    found = {}
    for r in open_member(zf, "food.csv"):
        fid = int(r["fdc_id"])
        if fid in wanted:
            found[fid] = r["description"]
    return found


def read_food_nutrients(zf: zipfile.ZipFile, wanted: set[int]) -> dict[int, dict[int, float]]:
    per100: dict[int, dict[int, float]] = defaultdict(dict)
    wanted_s = {str(i) for i in wanted}
    nutrient_s = {str(i) for i in NUTRIENT_IDS}
    for r in open_member(zf, "food_nutrient.csv"):  # ~36 MB, streamed
        if r["fdc_id"] in wanted_s and r["nutrient_id"] in nutrient_s:
            per100[int(r["fdc_id"])][int(r["nutrient_id"])] = float(r["amount"])
    return per100


def read_portions(zf: zipfile.ZipFile, wanted: set[int]) -> dict[int, list[tuple[str, float]]]:
    units = {r["id"]: r["name"] for r in open_member(zf, "measure_unit.csv")}
    portions: dict[int, list[tuple[str, float]]] = defaultdict(list)
    wanted_s = {str(i) for i in wanted}
    for r in open_member(zf, "food_portion.csv"):
        if r["fdc_id"] not in wanted_s or not r["gram_weight"]:
            continue
        unit = units.get(r["measure_unit_id"], "")
        unit = "" if unit == "undetermined" else unit
        desc = " ".join(p for p in (r["amount"], unit, r["modifier"]) if p).strip()
        portions[int(r["fdc_id"])].append((desc, float(r["gram_weight"])))
    return portions


# --------------------------------------------------------------------- helpers
def fmt_grams(g: float) -> str:
    return f"{g:.0f}" if float(g).is_integer() else f"{g:.1f}"


def round_value(key: str, value):
    if value is None:
        return None
    return int(round(value)) if key in MG_KEYS else round(value, 1)


def validate_entry(e: dict, seen_names: set, seen_ids: set) -> None:
    name = e.get("name")
    if not name or not isinstance(name, str):
        fail(f"entry without a name: {e!r}")
    if name in seen_names:
        fail(f"duplicate food name: {name!r}")
    seen_names.add(name)
    if e.get("category") not in CATEGORIES:
        fail(f"{name!r}: unknown category {e.get('category')!r}")
    bad = [fl for fl in e.get("flags", []) if fl not in FLAGS]
    if bad:
        fail(f"{name!r}: unknown flags {bad}")
    if not e.get("serving_desc"):
        fail(f"{name!r}: missing serving_desc")
    if not isinstance(e.get("serving_g"), (int, float)) or e["serving_g"] <= 0:
        fail(f"{name!r}: serving_g must be a positive number")
    has_fdc = "fdc_id" in e
    has_manual = "manual_nutrients" in e
    if has_fdc == has_manual:
        fail(f"{name!r}: needs exactly one of fdc_id / manual_nutrients")
    if has_manual:
        if not isinstance(e.get("manual_id"), int) or e["manual_id"] <= 0:
            fail(f"{name!r}: manual entries need a positive integer manual_id")
        unknown = set(e["manual_nutrients"]) - set(NUTRIENT_KEYS)
        if unknown:
            fail(f"{name!r}: unknown manual nutrient keys {sorted(unknown)}")
        if "counts_as_fluid" in e["flags"] and not e["manual_nutrients"].get("fluid_ml"):
            fail(f"{name!r}: counts_as_fluid manual entry must give fluid_ml")
        out_id = -e["manual_id"]
    else:
        if not isinstance(e["fdc_id"], int) or e["fdc_id"] <= 0:
            fail(f"{name!r}: fdc_id must be a positive integer")
        out_id = e["fdc_id"]
    if out_id in seen_ids:
        fail(f"{name!r}: duplicate id {out_id}")
    seen_ids.add(out_id)


def build_usda_entry(e: dict, descriptions: dict, per100: dict) -> dict:
    fid = e["fdc_id"]
    if fid not in descriptions:
        fail(f"{e['name']!r}: fdc_id {fid} is not in SR Legacy food.csv")
    amounts = per100.get(fid, {})
    scale = e["serving_g"] / 100.0
    nutrients = {}
    for key, nid, _unit in NUTRIENTS:
        if nid in amounts:
            nutrients[key] = round_value(key, amounts[nid] * scale)
        elif nid in OPTIONAL_IDS:
            nutrients[key] = None
        else:
            fail(f"{e['name']!r} (fdc {fid}, {descriptions[fid]!r}): nutrient {nid} ({key}) is missing")
    if "counts_as_fluid" in e["flags"]:
        if WATER_ID not in amounts:
            fail(f"{e['name']!r} (fdc {fid}): flagged counts_as_fluid but SR Legacy has no water value")
        nutrients["fluid_ml"] = round_value("fluid_ml", amounts[WATER_ID] * scale)
    else:
        nutrients["fluid_ml"] = 0
    return finish_entry(e, fid, nutrients)


def build_manual_entry(e: dict) -> dict:
    src = e["manual_nutrients"]
    nutrients = {k: round_value(k, src.get(k, 0)) for k in NUTRIENT_KEYS}
    if "counts_as_fluid" not in e["flags"]:
        nutrients["fluid_ml"] = 0
    return finish_entry(e, -e["manual_id"], nutrients)


def finish_entry(e: dict, out_id: int, nutrients: dict) -> dict:
    return {
        "fdc_id": out_id,
        "name": e["name"],
        "category": e["category"],
        "serving_desc": f"{e['serving_desc']} ({fmt_grams(e['serving_g'])} g)",
        "serving_g": e["serving_g"],
        "nutrients": {k: nutrients[k] for k in NUTRIENT_KEYS},
        "flags": list(e["flags"]),
        "kidney_notes": e.get("kidney_notes") or None,
    }


def check_portions(entries: list[dict], portions: dict, verbose: bool) -> None:
    """Report curated serving sizes that match no USDA household portion (informational)."""
    unmatched = []
    for e in entries:
        if "fdc_id" not in e:
            continue
        g = float(e["serving_g"])
        candidates = portions.get(e["fdc_id"], [])
        if not candidates:
            continue
        # accept exact portions, halves/quarters/doubles, and the 3 oz = 85 g convention
        ok = any(abs(g - w * m) <= max(0.6, 0.02 * w * m)
                 for _d, w in candidates for m in (1, 0.5, 0.25, 2, 0.75, 1.5, 3))
        if not ok and abs(g - 85) > 0.6 and abs(g - 28.35) > 0.6:
            unmatched.append((e["name"], g, candidates[:4]))
    log(f"Serving sizes not matching a listed USDA portion (hand-chosen gram weights): {len(unmatched)}")
    if verbose:
        for name, g, cands in unmatched:
            log(f"  {name}: {g} g; USDA lists " + "; ".join(f"{d}={w:g} g" for d, w in cands))


def run_sanity(per100: dict) -> None:
    ok = True
    for fid, key, lo, hi, label in SANITY_PER_100G:
        nid = next(n for k, n, _ in NUTRIENTS if k == key)
        value = per100.get(fid, {}).get(nid)
        status = "ok" if value is not None and lo <= value <= hi else "FAIL"
        ok &= status == "ok"
        log(f"sanity {label:22s} {key:14s} {value} per 100 g (expected {lo}-{hi}) {status}")
    if not ok:
        fail("sanity check failed - the nutrient mapping is probably broken")


# ------------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", default=f"{dt.date.today():%Y-%m-%d}.1")
    ap.add_argument("--cache-dir", type=Path, default=HERE / ".cache")
    ap.add_argument("--out", type=Path, default=REPO / "data" / "foods.json")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    seen_names: set = set()
    seen_ids: set = set()
    for e in CURATED_FOODS:
        validate_entry(e, seen_names, seen_ids)
    wanted = {e["fdc_id"] for e in CURATED_FOODS if "fdc_id" in e}

    zip_path = ensure_zip(args.cache_dir)
    with zipfile.ZipFile(zip_path) as zf:
        read_nutrient_units(zf)
        descriptions = read_foods(zf, wanted)
        missing = sorted(wanted - set(descriptions))
        if missing:
            fail(f"fdc_ids not found in food.csv: {missing}")
        log(f"Reading food_nutrient.csv for {len(wanted)} foods ...")
        per100 = read_food_nutrients(zf, wanted)
        portions = read_portions(zf, wanted)

    run_sanity(per100)

    foods = []
    for e in CURATED_FOODS:
        foods.append(build_usda_entry(e, descriptions, per100) if "fdc_id" in e else build_manual_entry(e))

    check_portions(CURATED_FOODS, portions, args.verbose)

    doc = {"version": args.version, "source": SOURCE, "foods": foods}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, args.out)

    counts = Counter(f["category"] for f in foods)
    log(f"\nWrote {args.out} (version {args.version}): {len(foods)} foods")
    for cat in CATEGORIES:
        log(f"  {cat:24s} {counts.get(cat, 0):4d}")
    nulls = Counter(k for f in foods for k, v in f["nutrients"].items() if v is None)
    log(f"  null nutrient values: {dict(nulls) or 'none'}")

    by_id = {f["fdc_id"]: f for f in foods}
    log("\nPer-serving spot checks:")
    for fid, key in [(173944, "potassium_mg"), (169098, "potassium_mg"), (171267, "potassium_mg"),
                     (171267, "phosphorus_mg"), (168878, "potassium_mg")]:
        if fid in by_id:
            f = by_id[fid]
            log(f"  {f['name']:28s} {f['serving_desc']:24s} {key} = {f['nutrients'][key]}")


if __name__ == "__main__":
    main()
