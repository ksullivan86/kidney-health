"""Food search and CRUD, builtin JSON import, USDA FoodData Central proxy.

Per-user visibility (note 07 §4.4 and §9 N5): ``builtin`` foods are shared and read-only;
``custom`` foods belong to their owner (``owner_user_id``) and nobody else sees them; ``usda`` (and
later ``off``) rows are shared, read-only, and visible to a person only after that person imported
or scanned them (a ``user_food_links`` row). Every query takes ``user_id`` explicitly; a food that
is not visible answers 404, exactly like one that does not exist.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import threading
import time

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from . import additives, credentials, egress
from .gtin import loose_gtin14, usda_candidates
from .off import quality_items
from .textclean import clean_label, clean_text
from .auth.deps import CurrentUser, current_user
from .auth.errors import ApiProblem
from .db import get_db, get_meta, set_meta, utcnow
from .models import Categories, Food, FoodCreate, FoodList, UsdaImport, UsdaSearchResult
from .nutrients import NUTRIENT_BY_KEY, NUTRIENT_KEYS, food_warnings, kidney_rating, round_nutrients, round_value

log = logging.getLogger("kidney_health.foods")
router = APIRouter(prefix="/api/foods", tags=["foods"], dependencies=[Depends(current_user)])

# Sources shared between people (read-only; edit = copy). ``off`` arrives with note 03.
SHARED_SOURCES: tuple[str, ...] = ("usda", "off")

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
USDA_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # decoded; note 03 §9 B6 (2 MiB for FoodData Central records)
USDA_BRANDED_PAGE_SIZE = 10
USDA_LICENSE = "CC0-1.0"
USDA_HOME_URL = "https://fdc.nal.usda.gov/"  # FoodData Central has no stable public per-food page
USDA_ATTRIBUTION_TEXT = "Product data: USDA FoodData Central (public domain, CC0)"

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


def parse_list(text: str | None) -> list[str]:
    """A stored JSON list of strings (``additives_json``, ``quality_json``); anything else is ``[]``."""
    try:
        value = json.loads(text or "[]")
    except json.JSONDecodeError:
        return []
    return [str(v) for v in value if isinstance(v, (str, int))] if isinstance(value, list) else []


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
        # v0.3 barcodes (schema step 7, note 03 R6)
        "gtin": row["gtin"],
        "source_url": row["source_url"],
        "source_license": row["source_license"],
        "quality": quality_items(parse_list(row["quality_json"])),
        "additives": parse_list(row["additives_json"]),
        "ingredients_text": row["ingredients_text"],
    }


def access_clause(alias: str = "f") -> str:
    """SQL condition: the food is one ``?`` (the user id, bound twice) may use.

    ``builtin`` rows, the person's own ``custom`` rows and shared rows they linked. Pair it with
    ``{alias}.hidden = 0`` for lists and search (the visible-foods predicate of note 07 §4.4);
    by id, hidden rows the person may use stay readable (an old entry or saved meal points at them).
    """
    return (
        f"({alias}.source = 'builtin' OR {alias}.owner_user_id = ? OR EXISTS "
        f"(SELECT 1 FROM user_food_links l WHERE l.user_id = ? AND l.food_id = {alias}.id))"
    )


def access_params(user_id: int) -> tuple[int, int]:
    return (int(user_id), int(user_id))


def fetch_food(conn: sqlite3.Connection, food_id: int) -> sqlite3.Row | None:
    """The row by id, whoever may see it (internal use: snapshots of the caller's own entries)."""
    try:
        return conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
    except OverflowError:  # id beyond SQLite's 64-bit INTEGER: no such row
        return None


def fetch_user_food(conn: sqlite3.Connection, user_id: int, food_id: int) -> sqlite3.Row | None:
    """The row by id if ``user_id`` may use it, else None."""
    try:
        return conn.execute(
            f"SELECT f.* FROM foods f WHERE f.id = ? AND {access_clause('f')}", (food_id, *access_params(user_id))
        ).fetchone()
    except OverflowError:
        return None


def food_is_referenced(conn: sqlite3.Connection, food_id: int, user_id: int) -> bool:
    """True when one of ``user_id``'s log entries or saved meals points at the food (§9 N5 (2))."""
    if conn.execute(
        "SELECT 1 FROM log_entries WHERE food_id = ? AND user_id = ? LIMIT 1", (food_id, int(user_id))
    ).fetchone() is not None:
        return True
    row = conn.execute(
        """SELECT 1 FROM meal_templates m, json_each(m.items_json) j
           WHERE m.user_id = ? AND json_extract(j.value, '$.food_id') = ? LIMIT 1""",
        (int(user_id), food_id),
    ).fetchone()
    return row is not None


def get_food_or_404(conn: sqlite3.Connection, user_id: int, food_id: int) -> sqlite3.Row:
    """The food if ``user_id`` may use it; 404 for both "no such food" and "not yours"."""
    row = fetch_user_food(conn, user_id, food_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"food {food_id} not found")
    return row


def link_food(conn: sqlite3.Connection, user_id: int, food_id: int) -> None:
    """Make a shared (``usda``/``off``) row visible to ``user_id``."""
    conn.execute(
        "INSERT OR IGNORE INTO user_food_links (user_id, food_id, created_at) VALUES (?, ?, ?)",
        (int(user_id), int(food_id), utcnow()),
    )


@dataclass(frozen=True)
class Provenance:
    """The barcode and provenance columns of a food row (schema step 7, note 03 R6)."""

    gtin: str | None = None
    source_url: str | None = None
    source_license: str | None = None
    retrieved_at: str | None = None
    ingredients_text: str | None = None
    additives: tuple[str, ...] = ()
    quality: tuple[str, ...] = ()

    def columns(self) -> dict[str, Any]:
        return {
            "gtin": self.gtin, "source_url": self.source_url, "source_license": self.source_license,
            "retrieved_at": self.retrieved_at, "ingredients_text": self.ingredients_text,
            "additives_json": json.dumps(list(self.additives)), "quality_json": json.dumps(list(self.quality)),
        }

    @classmethod
    def of_row(cls, row: Mapping[str, Any]) -> "Provenance":
        return cls(
            gtin=row["gtin"], source_url=row["source_url"], source_license=row["source_license"],
            retrieved_at=row["retrieved_at"], ingredients_text=row["ingredients_text"],
            additives=tuple(parse_list(row["additives_json"])), quality=tuple(parse_list(row["quality_json"])),
        )


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
    owner_user_id: int | None = None,
    provenance: Provenance | None = None,
) -> int:
    """Insert a food. ``custom`` rows need ``owner_user_id`` (a trigger refuses them otherwise)."""
    if source == "custom" and owner_user_id is None:
        raise ValueError("custom foods need an owner")
    flag_list = list(flags)
    serving_g, values = stored_food_values(nutrients, flag_list, serving_g)
    now = utcnow()
    extra = (provenance or Provenance()).columns()
    cur = conn.execute(
        f"""INSERT INTO foods (name, brand, category, source, fdc_id, serving_desc, serving_g,
                {_NUTRIENT_COLS}, flags_json, kidney_notes, hidden, owner_user_id, created_at, updated_at,
                {", ".join(extra)})
            VALUES (?, ?, ?, ?, ?, ?, ?, {_NUTRIENT_PLACEHOLDERS}, ?, ?, ?, ?, ?, ?, {", ".join("?" for _ in extra)})""",
        (
            name, brand, category, source, fdc_id, serving_desc, float(serving_g),
            *[values[k] for k in NUTRIENT_KEYS],
            json.dumps(flag_list), kidney_notes, int(hidden),
            None if source in ("builtin", *SHARED_SOURCES) else owner_user_id, now, now,
            *extra.values(),
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
    provenance: Provenance | None = None,  # None = leave the barcode columns unchanged
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
    if provenance is not None:
        for column, value in provenance.columns().items():
            sets.append(f"{column} = ?")
            params.append(value)
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
    user_id: int,
    q: str = "",
    category: str | None = None,
    source: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Visible foods matching ``q``; "recently logged first" uses only ``user_id``'s own log."""
    query = " ".join((q or "").lower().split())
    # One LIKE pair per word; SQLite rejects expression trees deeper than 1000, so cap the words.
    words = query.split()[:MAX_SEARCH_WORDS]
    where = ["f.hidden = 0", access_clause("f")]
    params: list[Any] = [*access_params(user_id)]
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
        LEFT JOIN (SELECT food_id, MAX(created_at) AS last_logged FROM log_entries WHERE user_id = ? GROUP BY food_id) l
               ON l.food_id = f.id
        WHERE {' AND '.join(where)}
        ORDER BY (l.last_logged IS NULL), l.last_logged DESC, f.name COLLATE NOCASE, f.id
    """
    params = [int(user_id), *params]
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
    """HTTP client for FoodData Central (tests monkeypatch this).

    Goes through the SSRF-checked transport (:mod:`app.egress`): the address of ``api.nal.usda.gov`` is
    resolved and checked on every request and redirects are never followed.
    """
    return httpx2.Client(
        base_url=USDA_BASE_URL,
        timeout=USDA_TIMEOUT_S,
        follow_redirects=False,
        trust_env=False,
        transport=egress.CheckedTransport(),
        headers={"User-Agent": "kidney-health/0.3 (self-hosted food log)", "Accept": "application/json",
                 "Accept-Encoding": "gzip"},
    )


USDA_UNAVAILABLE = {
    "not_configured": "No USDA key is set up. Add your own key in Settings → Food data, or ask your admin to share one.",
    "not_allowed": "Your admin has not shared a USDA key with you. Add your own key in Settings → Food data.",
    "quota_exhausted": "Today's shared USDA lookups are used up. Add your own key in Settings → Food data, or try tomorrow.",
    "own_key_unreadable": "Your USDA key can no longer be read on this server. Enter it again in Settings → Food data.",
}
# api.data.gov allows 1,000 requests per hour per key; stop below it (note 07 §4.12).
USDA_GUARD_REMAINING = 50
USDA_GUARD_WINDOW_S = 3600
_usda_guard: dict[str, float] = {}
_usda_guard_lock = threading.Lock()


def guard_id(cred: credentials.Credential, user_id: int) -> str:
    """Which key the hourly guard tracks: the shared key, or one person's own key (no key material)."""
    return f"{cred.provider}:shared:{cred.source}" if cred.scope == "shared" else f"{cred.provider}:user:{user_id}"


def usda_credential(request: Request, conn: sqlite3.Connection, user_id: int, can_use_shared: bool) -> credentials.Credential:
    """The key for this person's USDA call: own → shared (allowed, within today's quota) → 503."""
    auth = request.app.state.auth
    result = credentials.resolve(
        conn, auth.require_keyring(), request.app.state.settings,
        user_id=user_id, provider="usda", can_use_shared=can_use_shared, store=auth.store,
    )
    conn.commit()  # the quota counter
    if isinstance(result, credentials.Unavailable):
        raise ApiProblem(503, USDA_UNAVAILABLE.get(result.reason, "USDA lookups are not available"), reason=result.reason)
    with _usda_guard_lock:
        until = _usda_guard.get(guard_id(result, user_id), 0.0)
    if until > time.monotonic():
        raise ApiProblem(429, "USDA lookups are paused for a while (the key is close to its hourly limit). Try again later.",
                         headers={"Retry-After": str(int(until - time.monotonic()) + 1)})
    return result


def _note_rate_limit(guard: str, resp: httpx2.Response) -> None:
    raw = resp.headers.get("X-RateLimit-Remaining")
    try:
        remaining = int(raw) if raw is not None else None
    except ValueError:
        remaining = None
    if remaining is not None and remaining < USDA_GUARD_REMAINING:
        with _usda_guard_lock:
            _usda_guard[guard] = time.monotonic() + USDA_GUARD_WINDOW_S
        log.warning("a USDA key has %d requests left this hour; pausing lookups with it for an hour", remaining)


class UsdaError(Exception):
    """A FoodData Central call failed; ``status`` is what the API route answers (404, 429, 502, 503)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _usda_fetch(path: str, params: Mapping[str, Any], api_key: str, *, guard: str, own_key: bool = False) -> Any:
    """GET a FoodData Central path and return its JSON, or raise :class:`UsdaError`.

    The body is read with a cap of :data:`USDA_MAX_RESPONSE_BYTES` decoded bytes (note 03 §9 B6) and must
    be JSON. A rejected own key is reported as such and never retried with the shared one (note 04).
    """
    try:
        with usda_client() as client, client.stream("GET", path, params=params, headers={"X-Api-Key": api_key}) as resp:
            _note_rate_limit(guard, resp)
            status = resp.status_code
            content_type = resp.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            body = egress.read_capped(resp, USDA_MAX_RESPONSE_BYTES) if status == 200 and content_type == "application/json" else None
    except egress.ResponseTooLarge:
        log.warning("USDA answer was larger than %d bytes; refused", USDA_MAX_RESPONSE_BYTES)
        raise UsdaError(502, "USDA returned an answer that is too large") from None
    except httpx2.HTTPError as exc:
        log.warning("USDA request failed: %s", exc.__class__.__name__)
        raise UsdaError(502, f"USDA request failed: {exc.__class__.__name__}") from exc
    if status == 404:
        raise UsdaError(404, "USDA food not found")
    if status in (401, 403):
        detail = "Your USDA key was rejected. Check it in Settings → Food data." if own_key else "USDA API key was rejected"
        raise UsdaError(503, detail)
    if status == 429:
        raise UsdaError(429, "USDA says the key is over its rate limit. Try again later.")
    if status >= 300:
        raise UsdaError(502, f"USDA returned HTTP {status}")
    if body is None:
        raise UsdaError(502, "USDA did not answer with JSON")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise UsdaError(502, "USDA returned invalid JSON") from exc


def _usda_get(path: str, params: Mapping[str, Any], api_key: str, *, guard: str, own_key: bool = False) -> Any:
    """:func:`_usda_fetch` for the USDA routes: a failure becomes the matching HTTP error."""
    try:
        return _usda_fetch(path, params, api_key, guard=guard, own_key=own_key)
    except UsdaError as exc:
        headers = {"Retry-After": "3600"} if exc.status == 429 else None
        raise HTTPException(status_code=exc.status, detail=exc.detail, headers=headers) from exc


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
        if not isinstance(portion, Mapping):
            continue
        grams = _finite(portion.get("gramWeight"))
        if not grams or grams > 100_000:
            continue
        amount = portion.get("amount")
        measure = portion.get("measureUnit") if isinstance(portion.get("measureUnit"), Mapping) else {}
        unit = clean_label(measure.get("name"), max_len=40) or ""
        modifier = clean_label(portion.get("modifier"), max_len=60) or ""
        description = clean_label(portion.get("portionDescription"), max_len=80) or ""
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

    serving_size = _finite(data.get("servingSize"))
    unit = str(data.get("servingSizeUnit") or "").lower()
    if serving_size and 0 < serving_size <= 100_000 and unit in ("g", "grm", "ml", "mlt"):
        grams = serving_size
        shown = "mL" if unit in ("ml", "mlt") else "g"  # millilitres are counted as grams (1 mL ≈ 1 g)
        household = clean_label(data.get("householdServingFullText"), max_len=40)
        return grams, (f"{household} ({grams:g} {shown})" if household else f"{grams:g} {shown}")
    return 100.0, "100 g"


# labelNutrients (per serving, as printed on a branded label) → registry key. The FoodData Central
# OpenAPI spells potassium "postassium"; both spellings are accepted (note 03 F3).
USDA_LABEL_NUTRIENTS: dict[str, str] = {
    "calories": "calories_kcal", "protein": "protein_g", "fat": "fat_g", "saturatedFat": "sat_fat_g",
    "carbohydrates": "carbs_g", "fiber": "fiber_g", "sugars": "sugar_g", "sodium": "sodium_mg",
    "potassium": "potassium_mg", "postassium": "potassium_mg", "calcium": "calcium_mg",
}


@dataclass
class UsdaMapped:
    """A FoodData Central record mapped for ``insert_food`` plus the barcode fields (note 03 R4)."""

    kwargs: dict[str, Any]
    gtin14: str | None = None
    ingredients_text: str | None = None
    additives: list[str] = field(default_factory=list)
    quality: list[str] = field(default_factory=list)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _label_value(item: Any) -> float | None:
    return _finite(item.get("value")) if isinstance(item, Mapping) else _finite(item)


def map_usda_record(data: Mapping[str, Any], fdc_id: int) -> UsdaMapped:
    """Map a FoodData Central ``/food/{id}`` record (SR Legacy, Foundation or Branded).

    * Text (description, brand, ingredients) is cleaned like Open Food Facts text (note 03 §9 B3).
    * Serving: the first household portion, else the branded ``servingSize`` (g or mL), else 100 g.
    * Branded records with ``labelNutrients`` use those per-serving label values (they are what the
      package says); every other value is ``foodNutrients`` per 100 g scaled to the serving. A value
      the record does not report is ``None``, never 0.
    * The ingredient list goes through the additive scan, so ``phosphate_additive``,
      ``potassium_additive`` and ``avoid_ckd`` are set for FDC data as for Open Food Facts.
    """
    description = clean_label(data.get("description"), max_len=200) or f"USDA food {fdc_id}"
    brand = clean_label(data.get("brandOwner") or data.get("brandName"), max_len=200)
    usda_category = _usda_category_str(data.get("foodCategory")) or _usda_category_str(data.get("brandedFoodCategory"))
    usda_category = clean_label(usda_category, max_len=100)
    category = USDA_CATEGORY_MAP.get(usda_category or "", usda_category)

    per_100g: dict[str, float] = {}
    for item in data.get("foodNutrients") or []:
        if not isinstance(item, Mapping):
            continue
        nutrient = item.get("nutrient") if isinstance(item.get("nutrient"), Mapping) else {}
        candidates = (
            str(nutrient.get("number") or ""),
            str(nutrient.get("id") or ""),
            str(item.get("nutrientNumber") or ""),
            str(item.get("nutrientId") or ""),
        )
        key = next((USDA_NUTRIENT_NUMBERS[c] for c in candidates if c in USDA_NUTRIENT_NUMBERS), None)
        if key is None or key in per_100g:
            continue
        amount = _finite(item.get("amount", item.get("value")))
        if amount is not None:
            per_100g[key] = amount

    serving_g, serving_desc = _usda_serving(data)
    quality: list[str] = []
    if serving_desc == "100 g" and not data.get("foodPortions") and not data.get("servingSize"):
        quality.append("no_serving")
    unit = str(data.get("servingSizeUnit") or "").lower()
    is_ml = unit in ("ml", "mlt") and not data.get("foodPortions")
    if is_ml:
        quality.append("ml_as_g")
    scale = serving_g / 100.0
    nutrients: dict[str, float | None] = {
        key: (per_100g[key] * scale if key in per_100g else None) for key in NUTRIENT_KEYS if key != "fluid_ml"
    }
    labels = data.get("labelNutrients")
    if isinstance(labels, Mapping) and data.get("servingSize") and not data.get("foodPortions"):
        for label_key, key in USDA_LABEL_NUTRIENTS.items():
            value = _label_value(labels.get(label_key))
            if value is not None:
                nutrients[key] = value

    flags: list[str] = []
    ingredients = clean_text(data.get("ingredients"), max_len=additives.MAX_INGREDIENTS_CHARS, keep_newlines=True)
    scan = additives.scan([], ingredients, description)
    flags.extend(scan.flags)
    is_beverage = is_ml or category == "Beverages" or bool(usda_category and "beverage" in usda_category.lower())
    if is_beverage:
        flags.append("counts_as_fluid")
        water = per_100g.get("fluid_ml")
        nutrients["fluid_ml"] = water * scale if water is not None else serving_g
    else:
        nutrients["fluid_ml"] = 0.0

    missing = [NUTRIENT_BY_KEY[k].label.lower() for k in ("potassium_mg", "phosphorus_mg") if nutrients.get(k) is None]
    for k in ("potassium_mg", "phosphorus_mg"):
        if nutrients.get(k) is None:
            quality.append(k.split("_")[0] + "_unknown")
    notes: list[str] = []
    if scan.kidney_notes:
        notes.append(scan.kidney_notes)
    if missing:
        notes.append(f"USDA record does not report {' or '.join(missing)}; treat it as unknown, not zero.")
    notes.extend(n for n in scan.notes if not scan.kidney_notes)
    kidney_notes = " ".join(notes)[:1000] or None
    return UsdaMapped(
        kwargs={
            "name": description,
            "brand": brand,
            "category": category,
            "serving_desc": serving_desc,
            "serving_g": serving_g,
            "nutrients": nutrients,
            "flags": flags,
            "kidney_notes": kidney_notes,
        },
        gtin14=loose_gtin14(data.get("gtinUpc")),
        ingredients_text=ingredients,
        additives=scan.additives,
        quality=quality,
    )


def usda_provenance(mapped: UsdaMapped, *, retrieved_at: str | None = None) -> Provenance:
    """The provenance columns of a FoodData Central row (public domain; attribution requested)."""
    return Provenance(
        gtin=mapped.gtin14, source_url=USDA_HOME_URL, source_license=USDA_LICENSE, retrieved_at=retrieved_at or utcnow(),
        ingredients_text=mapped.ingredients_text, additives=tuple(mapped.additives), quality=tuple(mapped.quality),
    )


def upsert_usda_food(conn: sqlite3.Connection, fdc_id: int, kwargs: Mapping[str, Any], provenance: Provenance) -> int:
    """The one shared ``usda`` row for ``fdc_id``: updated in place when it exists, else inserted."""
    existing = conn.execute(
        "SELECT id FROM foods WHERE source = 'usda' AND fdc_id = ? AND owner_user_id IS NULL ORDER BY id LIMIT 1", (fdc_id,)
    ).fetchone()
    if existing is not None:
        update_food_row(conn, existing["id"], hidden=False, provenance=provenance, **kwargs)
        return int(existing["id"])
    return insert_food(conn, source="usda", fdc_id=fdc_id, provenance=provenance, **kwargs)


def usda_record_to_food(data: Mapping[str, Any], fdc_id: int) -> dict[str, Any]:
    """Map a FoodData Central ``/food/{id}`` record to ``insert_food`` keyword arguments."""
    return map_usda_record(data, fdc_id).kwargs


def usda_find_by_gtin(gtin14: str, api_key: str, *, guard: str, own_key: bool = False) -> tuple[int, dict[str, Any]] | None:
    """Find a branded FoodData Central record for a GTIN-14 (note 03 R4): search each form of
    :func:`app.gtin.usda_candidates` (at most three calls) and accept only a result whose ``gtinUpc``,
    padded to 14 digits, equals ours exactly; then fetch that record. ``None`` when no form matches.
    Raises :class:`UsdaError` on an upstream failure."""
    for form in usda_candidates(gtin14):
        data = _usda_fetch(
            "/foods/search", {"query": form, "dataType": "Branded", "pageSize": USDA_BRANDED_PAGE_SIZE},
            api_key, guard=guard, own_key=own_key,
        )
        foods = data.get("foods") if isinstance(data, Mapping) else None
        for item in foods if isinstance(foods, list) else []:
            if not isinstance(item, Mapping) or loose_gtin14(item.get("gtinUpc")) != gtin14:
                continue
            try:
                fdc_id = int(item.get("fdcId"))
            except (TypeError, ValueError):
                continue
            if not 0 < fdc_id < 2**63:
                continue
            record = _usda_fetch(f"/food/{fdc_id}", {}, api_key, guard=guard, own_key=own_key)
            if not isinstance(record, Mapping):
                raise UsdaError(502, "USDA returned an unexpected record")
            if loose_gtin14(record.get("gtinUpc")) not in (None, gtin14):
                log.warning("USDA record %s carries another barcode than its search result; ignored", fdc_id)
                return None
            return fdc_id, dict(record)
    return None


# --------------------------------------------------------------------------- #
# Routes (static paths before ``/{food_id}``)
# --------------------------------------------------------------------------- #


@router.get("", response_model=FoodList)
def list_foods(
    user: CurrentUser,
    q: str = Query("", max_length=MAX_SEARCH_QUERY_CHARS),
    category: str | None = Query(None, max_length=100),
    source: str | None = Query(None, max_length=20),
    limit: int = Query(25, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return {"foods": search_foods(conn, user.id, q=q, category=category, source=source, limit=limit)}


@router.get("/categories", response_model=Categories)
def list_categories(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    rows = conn.execute(
        f"""SELECT DISTINCT f.category FROM foods f
            WHERE f.category IS NOT NULL AND f.category != '' AND f.hidden = 0 AND {access_clause('f')}""",
        access_params(user.id),
    ).fetchall()
    extras = sorted({r["category"] for r in rows} - set(CATEGORIES))
    return {"categories": [*CATEGORIES, *extras]}


@router.get("/usda/search", response_model=UsdaSearchResult)
def usda_search(request: Request, user: CurrentUser, q: str = Query("", max_length=200),
                conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="q is required")
    cred = usda_credential(request, conn, user.id, user.can_use_shared)
    data = _usda_get("/foods/search", {"query": query, "pageSize": USDA_PAGE_SIZE}, cred.api_key,
                     guard=guard_id(cred, user.id), own_key=cred.scope == "own")
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
def usda_import(body: UsdaImport, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Fetch a FoodData Central record into the one shared ``usda`` row for that ``fdc_id`` and link
    it to the caller (another person's import of the same food is reused, never exposed)."""
    cred = usda_credential(request, conn, user.id, user.can_use_shared)
    data = _usda_get(f"/food/{body.fdc_id}", {}, cred.api_key, guard=guard_id(cred, user.id), own_key=cred.scope == "own")
    if not isinstance(data, Mapping):
        raise HTTPException(status_code=502, detail="USDA returned an unexpected record")
    mapped = map_usda_record(data, body.fdc_id)
    food_id = upsert_usda_food(conn, body.fdc_id, mapped.kwargs, usda_provenance(mapped))
    link_food(conn, user.id, food_id)
    conn.commit()
    return row_to_food(fetch_food(conn, food_id))


@router.get("/{food_id}", response_model=Food)
def get_food(food_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return row_to_food(get_food_or_404(conn, user.id, food_id))


def scan_custom_food(
    name: str, flags: Iterable[str], kidney_notes: str | None, ingredients_text: str | None
) -> tuple[list[str], str | None, str | None, list[str]]:
    """Run the additive scan (note 03 R5, R8) over a hand-entered food.

    Returns ``(flags, kidney_notes, ingredients_text, additives)``: the person's flags plus
    ``phosphate_additive`` / ``potassium_additive`` / ``avoid_ckd`` when the ingredient list (or the
    name, for a salt substitute) calls for them, so typing "sodium phosphate" sets the flag. The
    person's own notes win; a salt substitute without notes gets the standard warning text.
    """
    ingredients = clean_text(ingredients_text, max_len=additives.MAX_INGREDIENTS_CHARS, keep_newlines=True)
    scan = additives.scan([], ingredients, name)
    merged = list(dict.fromkeys([*flags, *scan.flags]))
    return merged, kidney_notes or scan.kidney_notes, ingredients, scan.additives


@router.post("", response_model=Food, status_code=201)
def create_food(body: FoodCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    flags, notes, ingredients, found = scan_custom_food(body.name, body.flags, body.kidney_notes, body.ingredients_text)
    food_id = insert_food(
        conn,
        source="custom",
        owner_user_id=user.id,
        name=body.name,
        brand=body.brand,
        category=body.category,
        serving_desc=body.serving_desc,
        serving_g=body.serving_g,
        nutrients=body.nutrients,
        flags=flags,
        kidney_notes=notes,
        provenance=Provenance(gtin=body.gtin, ingredients_text=ingredients, additives=tuple(found)),
    )
    conn.commit()
    return row_to_food(fetch_food(conn, food_id))


@router.put("/{food_id}", response_model=Food)
def update_food(food_id: int, body: FoodCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    row = get_food_or_404(conn, user.id, food_id)
    if row["source"] == "builtin":
        raise HTTPException(
            status_code=409,
            detail="Builtin foods cannot be edited; make an editable copy with POST /api/foods/{id}/copy",
        )
    if row["source"] != "custom" or row["owner_user_id"] != user.id:
        raise HTTPException(
            status_code=409,
            detail="Shared foods cannot be edited; make an editable copy with POST /api/foods/{id}/copy",
        )
    # A client that does not send gtin / ingredients_text (v0.2) keeps the stored ones.
    sent = body.model_fields_set
    kept = Provenance.of_row(row)
    ingredients_in = body.ingredients_text if "ingredients_text" in sent else kept.ingredients_text
    flags, notes, ingredients, found = scan_custom_food(body.name, body.flags, body.kidney_notes, ingredients_in)
    provenance = Provenance(
        gtin=body.gtin if "gtin" in sent else kept.gtin,
        source_url=kept.source_url, source_license=kept.source_license, retrieved_at=kept.retrieved_at,
        ingredients_text=ingredients, additives=tuple(found),
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
        flags=flags,
        kidney_notes=notes,
        provenance=provenance,
    )
    conn.commit()
    return row_to_food(fetch_food(conn, food_id))


@router.post("/{food_id}/copy", response_model=Food, status_code=201)
def copy_food(food_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """An editable custom copy. It keeps the barcode (so the next scan finds the copy first), the
    ingredient list and the attribution of the data it came from (ODbL needs it); the quality notes
    belong to the provider's data and are not copied."""
    row = get_food_or_404(conn, user.id, food_id)
    kept = Provenance.of_row(row)
    new_id = insert_food(
        conn,
        source="custom",
        owner_user_id=user.id,
        fdc_id=row["fdc_id"],
        name=row["name"],
        brand=row["brand"],
        category=row["category"],
        serving_desc=row["serving_desc"],
        serving_g=row["serving_g"],
        nutrients=raw_nutrients(row),
        flags=parse_flags(row["flags_json"]),
        kidney_notes=row["kidney_notes"],
        provenance=Provenance(
            gtin=kept.gtin, source_url=kept.source_url, source_license=kept.source_license,
            retrieved_at=kept.retrieved_at, ingredients_text=kept.ingredients_text, additives=kept.additives,
        ),
    )
    conn.commit()
    return row_to_food(fetch_food(conn, new_id))


@router.delete("/{food_id}", status_code=204, response_class=Response)
def delete_food(food_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Own custom food: hidden when your entries or saved meals use it, else deleted. Shared food:
    only your link is removed (other people keep theirs, §9 N5 (2))."""
    row = get_food_or_404(conn, user.id, food_id)
    if row["source"] == "builtin":
        raise HTTPException(status_code=409, detail="Builtin foods cannot be deleted")
    if row["source"] != "custom":
        cur = conn.execute("DELETE FROM user_food_links WHERE user_id = ? AND food_id = ?", (user.id, food_id))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail=f"food {food_id} not found")
    elif food_is_referenced(conn, food_id, user.id):
        conn.execute("UPDATE foods SET hidden = 1, updated_at = ? WHERE id = ? AND owner_user_id = ?", (utcnow(), food_id, user.id))
    else:
        conn.execute("DELETE FROM foods WHERE id = ? AND owner_user_id = ?", (food_id, user.id))
    conn.commit()
    return Response(status_code=204)
