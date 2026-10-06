"""Food search and CRUD, builtin JSON import, USDA FoodData Central proxy."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .config import Settings
from .db import get_db, get_meta, set_meta, utcnow
from .models import Categories, Food, FoodCreate, FoodList, UsdaImport, UsdaSearchResult
from .nutrients import NUTRIENT_BY_KEY, NUTRIENT_KEYS, food_warnings, kidney_rating, round_nutrients, round_value

log = logging.getLogger("kidney_health.foods")
router = APIRouter(prefix="/api/foods", tags=["foods"])

# Exact category strings from ARCHITECTURE.md.
CATEGORIES: tuple[str, ...] = (
    "Fruits",
    "Vegetables",
    "Grains & Breads",
    "Dairy & Alternatives",
    "Meat, Poultry & Eggs",
    "Fish & Seafood",
    "Legumes, Nuts & Seeds",
    "Beverages",
    "Sweets & Snacks",
    "Condiments & Sauces",
    "Prepared & Fast Food",
    "Diabetes supplies",
)

FOODS_JSON_VERSION_KEY = "foods_json_version"

USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"
USDA_TIMEOUT_S = 10.0
USDA_PAGE_SIZE = 25

MAX_SEARCH_QUERY_CHARS = 200
MAX_SEARCH_WORDS = 10

# USDA nutrient numbers (SR Legacy style) and nutrient ids (FDC style) -> registry key.
# 255/1051 is water in grams; it becomes fluid_ml only for foods that count as fluid.
USDA_NUTRIENT_NUMBERS: dict[str, str] = {
    "208": "calories_kcal", "1008": "calories_kcal",
    "203": "protein_g", "1003": "protein_g",
    "204": "fat_g", "1004": "fat_g",
    "606": "sat_fat_g", "1258": "sat_fat_g",
    "205": "carbs_g", "1005": "carbs_g",
    "291": "fiber_g", "1079": "fiber_g",
    "269": "sugar_g", "2000": "sugar_g",
    "307": "sodium_mg", "1093": "sodium_mg",
    "306": "potassium_mg", "1092": "potassium_mg",
    "305": "phosphorus_mg", "1091": "phosphorus_mg",
    "301": "calcium_mg", "1087": "calcium_mg",
    "255": "fluid_ml", "1051": "fluid_ml",
}

# SR Legacy / Foundation food groups -> contract categories (unmapped names are kept verbatim).
USDA_CATEGORY_MAP: dict[str, str] = {
    "Fruits and Fruit Juices": "Fruits",
    "Vegetables and Vegetable Products": "Vegetables",
    "Cereal Grains and Pasta": "Grains & Breads",
    "Baked Products": "Grains & Breads",
    "Breakfast Cereals": "Grains & Breads",
    "Dairy and Egg Products": "Dairy & Alternatives",
    "Beef Products": "Meat, Poultry & Eggs",
    "Pork Products": "Meat, Poultry & Eggs",
    "Poultry Products": "Meat, Poultry & Eggs",
    "Lamb, Veal, and Game Products": "Meat, Poultry & Eggs",
    "Sausages and Luncheon Meats": "Meat, Poultry & Eggs",
    "Finfish and Shellfish Products": "Fish & Seafood",
    "Legumes and Legume Products": "Legumes, Nuts & Seeds",
    "Nut and Seed Products": "Legumes, Nuts & Seeds",
    "Beverages": "Beverages",
    "Sweets": "Sweets & Snacks",
    "Snacks": "Sweets & Snacks",
    "Soups, Sauces, and Gravies": "Condiments & Sauces",
    "Spices and Herbs": "Condiments & Sauces",
    "Fats and Oils": "Condiments & Sauces",
    "Fast Foods": "Prepared & Fast Food",
    "Meals, Entrees, and Side Dishes": "Prepared & Fast Food",
    "Restaurant Foods": "Prepared & Fast Food",
}

_NUTRIENT_COLS = ", ".join(NUTRIENT_KEYS)
_NUTRIENT_PLACEHOLDERS = ", ".join("?" for _ in NUTRIENT_KEYS)


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #


def parse_flags(flags_json: str | None) -> list[str]:
    try:
        value = json.loads(flags_json or "[]")
    except json.JSONDecodeError:
        return []
    return [str(f) for f in value] if isinstance(value, list) else []


def raw_nutrients(row: Mapping[str, Any]) -> dict[str, float | None]:
    """Unrounded per-serving nutrients from a ``foods`` (or ``log_entries``) row."""
    return {key: row[key] for key in NUTRIENT_KEYS}


def normalise_fluid(nutrients: Mapping[str, float | None], flags: Iterable[str], serving_g: float) -> dict[str, float | None]:
    """Apply the contract's fluid rule.

    ``fluid_ml`` only counts for foods flagged ``counts_as_fluid``; for those an
    unknown value defaults to the serving weight (liquids are ~1 g/mL). For all
    other foods it is forced to 0.
    """
    out = {key: nutrients.get(key) for key in NUTRIENT_KEYS}
    if "counts_as_fluid" in set(flags):
        if out.get("fluid_ml") is None:
            out["fluid_ml"] = float(serving_g)
    else:
        out["fluid_ml"] = 0.0
    return out


def stored_food_values(
    nutrients: Mapping[str, float | None], flags: Iterable[str], serving_g: float
) -> tuple[float, dict[str, float | int | None]]:
    """``(serving_g, nutrients)`` as a food row stores them: at the precision the API shows.

    Per-serving values are kept the way ``data/foods.json`` already is (mg and mL whole, the rest
    to 1 decimal; ``serving_g`` to 1 decimal), so the numbers a client sees for a food are the
    ones every entry is scaled from. Storing a label's 80.4 mg while showing 80 made a client's
    2.5-serving preview say 200 mg (moderate) where the saved entry said 201 mg (high).
    """
    serving = round(float(serving_g), 1)
    values = normalise_fluid(nutrients, flags, serving)
    return serving, {key: round_value(key, values[key]) for key in NUTRIENT_KEYS}


def row_to_food(row: sqlite3.Row) -> dict[str, Any]:
    flags = parse_flags(row["flags_json"])
    nutrients = raw_nutrients(row)
    warnings = food_warnings(nutrients, flags, row["kidney_notes"])
    return {
        "id": row["id"],
        "name": row["name"],
        "brand": row["brand"],
        "category": row["category"],
        "source": row["source"],
        "fdc_id": row["fdc_id"],
        "serving_desc": row["serving_desc"],
        "serving_g": round(float(row["serving_g"]), 1),
        "nutrients": round_nutrients(nutrients),
        "flags": flags,
        "kidney_notes": row["kidney_notes"],
        "hidden": bool(row["hidden"]),
        "warnings": warnings,
        "kidney_rating": kidney_rating(warnings),
    }


def fetch_food(conn: sqlite3.Connection, food_id: int) -> sqlite3.Row | None:
    try:
        return conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
    except OverflowError:  # id beyond SQLite's 64-bit INTEGER: no such row
        return None


def food_is_referenced(conn: sqlite3.Connection, food_id: int) -> bool:
    """True when a log entry or a saved meal (``meal_templates.items_json``) points at the food."""
    if conn.execute("SELECT 1 FROM log_entries WHERE food_id = ? LIMIT 1", (food_id,)).fetchone() is not None:
        return True
    row = conn.execute(
        """SELECT 1 FROM meal_templates m, json_each(m.items_json) j
           WHERE json_extract(j.value, '$.food_id') = ? LIMIT 1""",
        (food_id,),
    ).fetchone()
    return row is not None


def get_food_or_404(conn: sqlite3.Connection, food_id: int) -> sqlite3.Row:
    row = fetch_food(conn, food_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"food {food_id} not found")
    return row


def insert_food(
    conn: sqlite3.Connection,
    *,
    name: str,
    serving_desc: str,
    serving_g: float,
    nutrients: Mapping[str, float | None],
    source: str = "custom",
    brand: str | None = None,
    category: str | None = None,
    fdc_id: int | None = None,
    flags: Iterable[str] = (),
    kidney_notes: str | None = None,
    hidden: bool = False,
) -> int:
    flag_list = list(flags)
    serving_g, values = stored_food_values(nutrients, flag_list, serving_g)
    now = utcnow()
    cur = conn.execute(
        f"""INSERT INTO foods (name, brand, category, source, fdc_id, serving_desc, serving_g,
                {_NUTRIENT_COLS}, flags_json, kidney_notes, hidden, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, {_NUTRIENT_PLACEHOLDERS}, ?, ?, ?, ?, ?)""",
        (
            name, brand, category, source, fdc_id, serving_desc, float(serving_g),
            *[values[k] for k in NUTRIENT_KEYS],
            json.dumps(flag_list), kidney_notes, int(hidden), now, now,
        ),
    )
    return int(cur.lastrowid)


def update_food_row(
    conn: sqlite3.Connection,
    food_id: int,
    *,
    name: str,
    serving_desc: str,
    serving_g: float,
    nutrients: Mapping[str, float | None],
    brand: str | None = None,
    category: str | None = None,
    flags: Iterable[str] = (),
    kidney_notes: str | None = None,
    hidden: bool | None = None,
    fdc_id: Any = ...,  # Ellipsis = leave unchanged
) -> None:
    flag_list = list(flags)
    serving_g, values = stored_food_values(nutrients, flag_list, serving_g)
    sets = ["name = ?", "brand = ?", "category = ?", "serving_desc = ?", "serving_g = ?"]
    params: list[Any] = [name, brand, category, serving_desc, float(serving_g)]
    for key in NUTRIENT_KEYS:
        sets.append(f"{key} = ?")
        params.append(values[key])
    sets += ["flags_json = ?", "kidney_notes = ?", "updated_at = ?"]
    params += [json.dumps(flag_list), kidney_notes, utcnow()]
    if hidden is not None:
        sets.append("hidden = ?")
        params.append(int(hidden))
    if fdc_id is not ...:
        sets.append("fdc_id = ?")
        params.append(fdc_id)
    params.append(food_id)
    conn.execute(f"UPDATE foods SET {', '.join(sets)} WHERE id = ?", params)


# --------------------------------------------------------------------------- #
# Builtin import
# --------------------------------------------------------------------------- #


def _parse_builtin_item(item: Mapping[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("missing name")
    serving_g = item.get("serving_g")
    try:
        serving_g = float(serving_g)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name!r}: serving_g must be a number") from exc
    if serving_g <= 0:
        raise ValueError(f"{name!r}: serving_g must be positive")
    fdc_id = item.get("fdc_id")
    if fdc_id is not None:
        try:
            fdc_id = int(fdc_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name!r}: fdc_id must be an integer") from exc
    raw = item.get("nutrients")
    if not isinstance(raw, Mapping):
        raw = item  # tolerate flat files
    nutrients: dict[str, float | None] = {}
    for key in NUTRIENT_KEYS:
        v = raw.get(key)
        nutrients[key] = None if v is None else float(v)
    flags = item.get("flags") or []
    if not isinstance(flags, list):
        raise ValueError(f"{name!r}: flags must be a list")
    return {
        "name": name,
        "brand": (item.get("brand") or None),
        "category": (item.get("category") or None),
        "fdc_id": fdc_id,
        "serving_desc": str(item.get("serving_desc") or f"{serving_g:g} g"),
        "serving_g": serving_g,
        "nutrients": nutrients,
        "flags": [str(f) for f in flags],
        "kidney_notes": (item.get("kidney_notes") or None),
    }


def import_builtin_foods(conn: sqlite3.Connection, path: Path | str) -> dict[str, Any]:
    """Upsert ``data/foods.json`` into the ``foods`` table.

    * Matched by ``fdc_id`` for ``source='builtin'``; entries without ``fdc_id``
      are matched by case-insensitive name.
    * Row ids are preserved so log entries keep pointing at the right food.
    * Builtin foods that disappeared from the file are hidden, never deleted.
    * The file's ``version`` is stored in ``meta`` and the import is skipped when
      it has not changed. A missing or unreadable file is logged and ignored so
      the app still starts.
    """
    path = Path(path)
    if not path.is_file():
        log.warning("builtin food database %s not found; starting without builtin foods", path)
        return {"status": "missing", "count": 0, "version": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("could not read builtin food database %s: %s", path, exc)
        return {"status": "error", "count": 0, "version": None}
    if not isinstance(data, Mapping) or not isinstance(data.get("foods"), list):
        log.error("builtin food database %s has an unexpected shape; expected {version, foods: [...]}", path)
        return {"status": "error", "count": 0, "version": None}

    version = str(data.get("version") or "")
    current = get_meta(conn, FOODS_JSON_VERSION_KEY)
    if version and current == version:
        count = conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'builtin' AND hidden = 0").fetchone()[0]
        log.info("builtin food database version %s already imported (%d foods)", version, count)
        return {"status": "unchanged", "count": count, "version": version}

    rows = conn.execute("SELECT id, fdc_id, name FROM foods WHERE source = 'builtin'").fetchall()
    by_fdc = {r["fdc_id"]: r["id"] for r in rows if r["fdc_id"] is not None}
    by_name = {r["name"].strip().lower(): r["id"] for r in rows if r["fdc_id"] is None}
    seen: set[int] = set()
    imported = skipped = 0

    with conn:  # one transaction
        for item in data["foods"]:
            try:
                parsed = _parse_builtin_item(item)
            except (ValueError, AttributeError) as exc:
                log.warning("skipping builtin food: %s", exc)
                skipped += 1
                continue
            fdc_id = parsed["fdc_id"]
            existing_id = by_fdc.get(fdc_id) if fdc_id is not None else by_name.get(parsed["name"].lower())
            if existing_id is not None:
                update_food_row(conn, existing_id, hidden=False, **parsed)
                seen.add(existing_id)
            else:
                new_id = insert_food(conn, source="builtin", **parsed)
                if fdc_id is not None:
                    by_fdc[fdc_id] = new_id
                else:
                    by_name[parsed["name"].lower()] = new_id
                seen.add(new_id)
            imported += 1
        stale = [(r["id"],) for r in rows if r["id"] not in seen]
        if stale:
            conn.executemany("UPDATE foods SET hidden = 1, updated_at = ? WHERE id = ?", [(utcnow(), i) for (i,) in stale])
        if version:
            set_meta(conn, FOODS_JSON_VERSION_KEY, version)

    log.info(
        "imported builtin food database version %s: %d foods (%d skipped, %d hidden as stale)",
        version or "<unversioned>", imported, skipped, len(stale),
    )
    return {"status": "imported", "count": imported, "skipped": skipped, "hidden": len(stale), "version": version or None}


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def search_rank(name: str, brand: str | None, query: str, words: list[str]) -> int:
    """0 = name starts with the whole query, 1 = a word in the name starts with the
    first query word, 2 = brand starts with the query, 3 = plain substring match."""
    n = name.lower()
    if n.startswith(query):
        return 0
    if words and any(tok.startswith(words[0]) for tok in _TOKEN_RE.split(n) if tok):
        return 1
    if brand and brand.lower().startswith(query):
        return 2
    return 3


def search_foods(
    conn: sqlite3.Connection,
    q: str = "",
    category: str | None = None,
    source: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    query = " ".join((q or "").lower().split())
    # One LIKE pair per word; SQLite rejects expression trees deeper than 1000, so cap the words.
    words = query.split()[:MAX_SEARCH_WORDS]
    where = ["f.hidden = 0"]
    params: list[Any] = []
    if category:
        where.append("f.category = ?")
        params.append(category)
    if source:
        where.append("f.source = ?")
        params.append(source)
    for w in words:
        where.append("(LOWER(f.name) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(f.brand, '')) LIKE ? ESCAPE '\\')")
        params += [_like(w), _like(w)]
    sql = f"""
        SELECT f.*, l.last_logged
        FROM foods f
        LEFT JOIN (SELECT food_id, MAX(created_at) AS last_logged FROM log_entries GROUP BY food_id) l
               ON l.food_id = f.id
        WHERE {' AND '.join(where)}
        ORDER BY (l.last_logged IS NULL), l.last_logged DESC, f.name COLLATE NOCASE, f.id
    """
    if not words:
        rows = conn.execute(sql + " LIMIT ?", [*params, int(limit)]).fetchall()
    else:
        rows = conn.execute(sql, params).fetchall()
        # Stable sort: rank first, then the SQL order (recently logged, then name).
        rows.sort(key=lambda r: search_rank(r["name"], r["brand"], query, words))
        rows = rows[: int(limit)]
    return [row_to_food(r) for r in rows]


# --------------------------------------------------------------------------- #
# USDA proxy
# --------------------------------------------------------------------------- #


def usda_client() -> httpx2.Client:
    """HTTP client for FoodData Central (tests monkeypatch this)."""
    return httpx2.Client(
        base_url=USDA_BASE_URL,
        timeout=USDA_TIMEOUT_S,
        headers={"User-Agent": "kidney-health/0.1 (self-hosted food log)"},
    )


def _require_usda_key(settings: Settings) -> str:
    if not settings.usda_api_key:
        raise HTTPException(status_code=503, detail="USDA_API_KEY not configured")
    return settings.usda_api_key


def _usda_get(path: str, params: Mapping[str, Any], api_key: str) -> Any:
    try:
        with usda_client() as client:
            resp = client.get(path, params=params, headers={"X-Api-Key": api_key})
    except httpx2.HTTPError as exc:
        log.warning("USDA request failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"USDA request failed: {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="USDA food not found")
    if resp.status_code in (401, 403):
        raise HTTPException(status_code=503, detail="USDA API key was rejected")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"USDA returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="USDA returned invalid JSON") from exc


def _usda_category_str(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("description") or value.get("name")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _usda_serving(data: Mapping[str, Any]) -> tuple[float, str]:
    """``(serving_g, serving_desc)``: first household portion, else branded serving size, else 100 g."""
    for portion in data.get("foodPortions") or []:
        try:
            grams = float(portion.get("gramWeight"))
        except (TypeError, ValueError):
            continue
        if grams <= 0:
            continue
        amount = portion.get("amount")
        unit = str((portion.get("measureUnit") or {}).get("name") or "").strip()
        modifier = str(portion.get("modifier") or "").strip()
        description = str(portion.get("portionDescription") or "").strip()
        parts: list[str] = []
        try:
            if amount:
                parts.append(f"{float(amount):g}")
        except (TypeError, ValueError):
            pass
        if unit and unit.lower() != "undetermined":
            parts.append(unit)
        if modifier and modifier.lower() != unit.lower():
            parts.append(modifier)
        if len(parts) <= 1 and description and description.lower() != "quantity not specified":
            parts = [description]
        label = " ".join(parts).strip() or "1 serving"
        return grams, f"{label} ({grams:g} g)"

    serving_size = data.get("servingSize")
    unit = str(data.get("servingSizeUnit") or "").lower()
    if serving_size and unit in ("g", "grm", "ml", "mlt"):
        grams = float(serving_size)
        household = str(data.get("householdServingFullText") or "").strip()
        return grams, (f"{household} ({grams:g} g)" if household else f"{grams:g} g")
    return 100.0, "100 g"


def usda_record_to_food(data: Mapping[str, Any], fdc_id: int) -> dict[str, Any]:
    """Map a FoodData Central ``/food/{id}`` record to ``insert_food`` keyword arguments."""
    description = str(data.get("description") or f"USDA food {fdc_id}").strip()
    brand = data.get("brandOwner") or data.get("brandName") or None
    usda_category = _usda_category_str(data.get("foodCategory")) or _usda_category_str(data.get("brandedFoodCategory"))
    category = USDA_CATEGORY_MAP.get(usda_category or "", usda_category)

    per_100g: dict[str, float] = {}
    for item in data.get("foodNutrients") or []:
        if not isinstance(item, Mapping):
            continue
        nutrient = item.get("nutrient") or {}
        candidates = (
            str(nutrient.get("number") or ""),
            str(nutrient.get("id") or ""),
            str(item.get("nutrientNumber") or ""),
            str(item.get("nutrientId") or ""),
        )
        key = next((USDA_NUTRIENT_NUMBERS[c] for c in candidates if c in USDA_NUTRIENT_NUMBERS), None)
        if key is None or key in per_100g:
            continue
        amount = item.get("amount", item.get("value"))
        if amount is None:
            continue
        try:
            per_100g[key] = float(amount)
        except (TypeError, ValueError):
            continue

    serving_g, serving_desc = _usda_serving(data)
    scale = serving_g / 100.0
    nutrients: dict[str, float | None] = {
        key: (per_100g[key] * scale if key in per_100g else None) for key in NUTRIENT_KEYS if key != "fluid_ml"
    }
    flags: list[str] = []
    is_beverage = category == "Beverages" or bool(usda_category and "beverage" in usda_category.lower())
    if is_beverage:
        flags.append("counts_as_fluid")
        water = per_100g.get("fluid_ml")
        nutrients["fluid_ml"] = water * scale if water is not None else serving_g
    else:
        nutrients["fluid_ml"] = 0.0

    missing = [NUTRIENT_BY_KEY[k].label.lower() for k in ("potassium_mg", "phosphorus_mg") if k not in per_100g]
    kidney_notes = (
        f"USDA record does not report {' or '.join(missing)}; treat it as unknown, not zero."
        if missing
        else None
    )
    return {
        "name": description,
        "brand": str(brand).strip() if brand else None,
        "category": category,
        "serving_desc": serving_desc,
        "serving_g": serving_g,
        "nutrients": nutrients,
        "flags": flags,
        "kidney_notes": kidney_notes,
    }


# --------------------------------------------------------------------------- #
# Routes (static paths before ``/{food_id}``)
# --------------------------------------------------------------------------- #


@router.get("", response_model=FoodList)
def list_foods(
    q: str = Query("", max_length=MAX_SEARCH_QUERY_CHARS),
    category: str | None = Query(None, max_length=100),
    source: str | None = Query(None, max_length=20),
    limit: int = Query(25, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return {"foods": search_foods(conn, q=q, category=category, source=source, limit=limit)}


@router.get("/categories", response_model=Categories)
def list_categories(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM foods WHERE category IS NOT NULL AND category != '' AND hidden = 0"
    ).fetchall()
    extras = sorted({r["category"] for r in rows} - set(CATEGORIES))
    return {"categories": [*CATEGORIES, *extras]}


@router.get("/usda/search", response_model=UsdaSearchResult)
def usda_search(request: Request, q: str = Query("", max_length=200)) -> dict[str, Any]:
    api_key = _require_usda_key(request.app.state.settings)
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="q is required")
    data = _usda_get("/foods/search", {"query": query, "pageSize": USDA_PAGE_SIZE}, api_key)
    foods = []
    for item in (data or {}).get("foods") or []:
        fdc_id = item.get("fdcId")
        if fdc_id is None:
            continue
        foods.append(
            {
                "fdc_id": int(fdc_id),
                "description": str(item.get("description") or "").strip() or f"USDA food {fdc_id}",
                "data_type": item.get("dataType"),
                "brand": item.get("brandOwner") or item.get("brandName") or None,
                "category": _usda_category_str(item.get("foodCategory")),
            }
        )
    return {"foods": foods}


@router.post("/usda/import", response_model=Food)
def usda_import(body: UsdaImport, request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    api_key = _require_usda_key(request.app.state.settings)
    data = _usda_get(f"/food/{body.fdc_id}", {}, api_key)
    if not isinstance(data, Mapping):
        raise HTTPException(status_code=502, detail="USDA returned an unexpected record")
    parsed = usda_record_to_food(data, body.fdc_id)
    existing = conn.execute("SELECT id FROM foods WHERE source = 'usda' AND fdc_id = ?", (body.fdc_id,)).fetchone()
    if existing is not None:
        food_id = existing["id"]
        update_food_row(conn, food_id, hidden=False, **parsed)
    else:
        food_id = insert_food(conn, source="usda", fdc_id=body.fdc_id, **parsed)
    conn.commit()
    return row_to_food(fetch_food(conn, food_id))


@router.get("/{food_id}", response_model=Food)
def get_food(food_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return row_to_food(get_food_or_404(conn, food_id))


@router.post("", response_model=Food, status_code=201)
def create_food(body: FoodCreate, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    food_id = insert_food(
        conn,
        source="custom",
        name=body.name,
        brand=body.brand,
        category=body.category,
        serving_desc=body.serving_desc,
        serving_g=body.serving_g,
        nutrients=body.nutrients,
        flags=body.flags,
        kidney_notes=body.kidney_notes,
    )
    conn.commit()
    return row_to_food(fetch_food(conn, food_id))


@router.put("/{food_id}", response_model=Food)
def update_food(food_id: int, body: FoodCreate, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    row = get_food_or_404(conn, food_id)
    if row["source"] == "builtin":
        raise HTTPException(
            status_code=409,
            detail="Builtin foods cannot be edited; make an editable copy with POST /api/foods/{id}/copy",
        )
    update_food_row(
        conn,
        food_id,
        name=body.name,
        brand=body.brand,
        category=body.category,
        serving_desc=body.serving_desc,
        serving_g=body.serving_g,
        nutrients=body.nutrients,
        flags=body.flags,
        kidney_notes=body.kidney_notes,
    )
    conn.commit()
    return row_to_food(fetch_food(conn, food_id))


@router.post("/{food_id}/copy", response_model=Food, status_code=201)
def copy_food(food_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    row = get_food_or_404(conn, food_id)
    new_id = insert_food(
        conn,
        source="custom",
        fdc_id=row["fdc_id"],
        name=row["name"],
        brand=row["brand"],
        category=row["category"],
        serving_desc=row["serving_desc"],
        serving_g=row["serving_g"],
        nutrients=raw_nutrients(row),
        flags=parse_flags(row["flags_json"]),
        kidney_notes=row["kidney_notes"],
    )
    conn.commit()
    return row_to_food(fetch_food(conn, new_id))


@router.delete("/{food_id}", status_code=204, response_class=Response)
def delete_food(food_id: int, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    row = get_food_or_404(conn, food_id)
    if row["source"] == "builtin":
        raise HTTPException(status_code=409, detail="Builtin foods cannot be deleted")
    if food_is_referenced(conn, food_id):
        conn.execute("UPDATE foods SET hidden = 1, updated_at = ? WHERE id = ?", (utcnow(), food_id))
    else:
        conn.execute("DELETE FROM foods WHERE id = ?", (food_id,))
    conn.commit()
    return Response(status_code=204)
