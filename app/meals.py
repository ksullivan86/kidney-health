"""Saved meals (templates): CRUD, build one from a logged meal, apply one to a day;
plus the shopping list aggregated from planned entries (``/api/plan/shopping``).

Saved meals belong to one person (``meal_templates.user_id``); every food in one must be visible
to that person (404 otherwise), and someone else's saved meal answers 404.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Mapping

from fastapi import APIRouter, Depends, HTTPException, Response

from .auth.deps import CurrentUser, current_user
from .db import get_db, utcnow
from .foods import fetch_food, fetch_user_food, get_food_or_404, parse_flags, raw_nutrients
from .log import fetch_entries, fetch_entry, insert_entry, parse_range, resolve_purpose, row_to_entry
from .models import (
    MealApply,
    MealApplyResult,
    MealFromLog,
    MealItemIn,
    MealList,
    MealTemplate,
    MealTemplateCreate,
    ShoppingList,
)
from .nutrients import (NUTRIENT_KEYS, add_totals, count_unknown, empty_totals, food_warnings, kidney_rating, round_nutrients,
                        scale_nutrients)

router = APIRouter(prefix="/api/meals", tags=["meals"], dependencies=[Depends(current_user)])
plan_router = APIRouter(prefix="/api/plan", tags=["plan"], dependencies=[Depends(current_user)])

_RATING_RANK = {"green": 0, "yellow": 1, "red": 2}


def worst_rating(ratings: Iterable[str]) -> str:
    return max(ratings, key=lambda r: _RATING_RANK.get(r, 0), default="green")


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #


def parse_items(items_json: str | None) -> list[dict[str, Any]]:
    """Stored ``items_json`` -> ``[{"food_id": int, "servings": float}]`` (malformed items dropped)."""
    try:
        value = json.loads(items_json or "[]")
    except json.JSONDecodeError:
        return []
    items: list[dict[str, Any]] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, Mapping):
            continue
        try:
            food_id = int(raw["food_id"])
            servings = float(raw.get("servings", 1))
        except (KeyError, TypeError, ValueError):
            continue
        if servings > 0:
            items.append({"food_id": food_id, "servings": servings})
    return items


def parse_steps(steps_json: str | None) -> list[str] | None:
    """Stored ``steps_json`` -> a list of strings, or ``None`` (malformed or empty)."""
    try:
        value = json.loads(steps_json) if steps_json else None
    except json.JSONDecodeError:
        return None
    steps = [step for step in value if isinstance(step, str) and step] if isinstance(value, list) else []
    return steps or None


def recipe_fields(row: sqlite3.Row) -> tuple[float | None, list[str] | None, str | None]:
    """``(servings_made, steps, source_url)`` of a row (schema step 21; ``None`` on a database before it)."""
    keys = row.keys()
    servings = row["servings_made"] if "servings_made" in keys else None
    steps = parse_steps(row["steps_json"]) if "steps_json" in keys else None
    url = row["source_url"] if "source_url" in keys else None
    return (float(servings) if servings is not None else None), steps, url


def per_serving(totals: Mapping[str, float], unknown: Mapping[str, int], items: int, servings_made: float | None) -> dict[str, float | None]:
    """One serving: the whole meal's totals divided by ``servings_made`` (1 for a plain saved meal). A nutrient that no item lists
    is ``None``, never 0; one that some items list is a lower bound, and ``unknown`` says how many do not."""
    divide = servings_made or 1.0
    out: dict[str, float | None] = {}
    for key in NUTRIENT_KEYS:
        out[key] = None if items and unknown.get(key, 0) >= items else totals.get(key, 0.0) / divide
    return round_nutrients(out)


def fetch_template(conn: sqlite3.Connection, user_id: int, meal_id: int) -> sqlite3.Row | None:
    try:
        return conn.execute("SELECT * FROM meal_templates WHERE id = ? AND user_id = ?", (meal_id, int(user_id))).fetchone()
    except OverflowError:  # id beyond SQLite's 64-bit INTEGER: no such row
        return None


def get_template_or_404(conn: sqlite3.Connection, user_id: int, meal_id: int) -> sqlite3.Row:
    row = fetch_template(conn, user_id, meal_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"saved meal {meal_id} not found")
    return row


def build_item(conn: sqlite3.Connection, item: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, float | None] | None]:
    """``(MealItem, unrounded scaled nutrients)``; a food row that vanished yields a hidden placeholder."""
    servings = float(item["servings"])
    food = fetch_food(conn, int(item["food_id"]))
    if food is None:
        placeholder = {
            "food_id": int(item["food_id"]),
            "food_name": "Deleted food",
            "servings": round(servings, 3),
            "serving_desc": "unknown",
            "nutrients": round_nutrients({}),
            "kidney_rating": "green",
            "hidden": True,
        }
        return placeholder, None
    scaled = scale_nutrients(raw_nutrients(food), servings)
    warnings = food_warnings(scaled, parse_flags(food["flags_json"]), food["kidney_notes"], scope="in this meal")
    built = {
        "food_id": food["id"],
        "food_name": food["name"],
        "servings": round(servings, 3),
        "serving_desc": food["serving_desc"],
        "nutrients": round_nutrients(scaled),
        "kidney_rating": kidney_rating(warnings),
        "hidden": bool(food["hidden"]),
    }
    return built, scaled


def row_to_template(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    totals = empty_totals()
    unknown: dict[str, int] = {}
    counted = 0  # items with a food row (a deleted food's placeholder has none)
    for raw_item in parse_items(row["items_json"]):
        item, scaled = build_item(conn, raw_item)
        if scaled is not None:
            add_totals(totals, scaled)
            count_unknown(unknown, scaled)
            counted += 1
        items.append(item)
    servings_made, steps, source_url = recipe_fields(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "note": row["note"],
        "meal_hint": row["meal_hint"] if "meal_hint" in row.keys() else None,  # schema step 5
        "items": items,
        "totals": round_nutrients(totals),
        "kidney_rating": worst_rating(i["kidney_rating"] for i in items),
        "servings_made": servings_made,
        "steps": steps,
        "source_url": source_url,
        "per_serving": per_serving(totals, unknown, counted, servings_made),
        "unknown": unknown,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def resolve_items(conn: sqlite3.Connection, user_id: int, items: Iterable[MealItemIn]) -> list[dict[str, Any]]:
    """Validate every food is visible to ``user_id`` (404 otherwise) and normalise to the stored shape."""
    out: list[dict[str, Any]] = []
    for item in items:
        get_food_or_404(conn, user_id, item.food_id)
        out.append({"food_id": item.food_id, "servings": float(item.servings)})
    return out


def steps_json(steps: list[str] | None) -> str | None:
    return json.dumps(steps) if steps else None


def insert_template(conn: sqlite3.Connection, *, user_id: int, name: str, note: str | None, items: list[dict[str, Any]],
                    meal_hint: str | None = None, created_at: str | None = None, updated_at: str | None = None,
                    servings_made: float | None = None, steps: list[str] | None = None, source_url: str | None = None) -> int:
    """Insert a saved meal; ``meal_hint`` is the slot it is for (note 06 §4.11), or ``None``. A recipe also has ``servings_made``
    (the items make that many servings), ``steps`` and ``source_url`` (note 16 §5.1). ``created_at`` and ``updated_at`` are for an
    import of the person's own export (``app/data_import.py``); left out they are now."""
    now = utcnow()
    created = created_at or now
    cur = conn.execute(
        """INSERT INTO meal_templates (user_id, name, note, items_json, meal_hint, servings_made, steps_json, source_url,
                                       created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (int(user_id), name, note, json.dumps(items), meal_hint, servings_made, steps_json(steps), source_url, created,
         updated_at or created),
    )
    return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
# Routes (static paths before ``/{meal_id}``)
# --------------------------------------------------------------------------- #


@router.get("", response_model=MealList)
def list_meals(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM meal_templates WHERE user_id = ? ORDER BY name COLLATE NOCASE, id", (user.id,)).fetchall()
    return {"meals": [row_to_template(conn, r) for r in rows]}


@router.post("", response_model=MealTemplate, status_code=201)
def create_meal(body: MealTemplateCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    items = resolve_items(conn, user.id, body.items)
    meal_id = insert_template(conn, user_id=user.id, name=body.name, note=body.note, items=items, meal_hint=body.meal_hint,
                              servings_made=body.servings_made, steps=body.steps, source_url=body.source_url)
    conn.commit()
    return row_to_template(conn, fetch_template(conn, user.id, meal_id))


@router.post("/from-log", response_model=MealTemplate, status_code=201)
def meal_from_log(body: MealFromLog, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Save that day's entries of one meal (eaten and planned) as a template for that meal slot
    (``meal_hint``). Entries that treated a low (``purpose = 'hypo'``) are not part of the meal."""
    rows = [r for r in fetch_entries(conn, user.id, body.date, body.date, meal=body.meal)
            if ("purpose" not in r.keys() or r["purpose"] != "hypo")]
    if not rows:
        raise HTTPException(status_code=400, detail=f"nothing logged for {body.meal} on {body.date}")
    items = [{"food_id": r["food_id"], "servings": float(r["servings"])} for r in rows]
    meal_id = insert_template(conn, user_id=user.id, name=body.name, note=body.note, items=items, meal_hint=body.meal)
    conn.commit()
    return row_to_template(conn, fetch_template(conn, user.id, meal_id))


@router.get("/{meal_id}", response_model=MealTemplate)
def get_meal(meal_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return row_to_template(conn, get_template_or_404(conn, user.id, meal_id))


@router.put("/{meal_id}", response_model=MealTemplate)
def update_meal(meal_id: int, body: MealTemplateCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    row = get_template_or_404(conn, user.id, meal_id)
    items = resolve_items(conn, user.id, body.items)
    # A client that does not send meal_hint (a v0.2 screen) keeps the stored one; null clears it.
    meal_hint = body.meal_hint if "meal_hint" in body.model_fields_set else row["meal_hint"]
    # The same for the recipe fields (a client from before schema step 21 never sends them).
    sent = body.model_fields_set
    servings_made = body.servings_made if "servings_made" in sent else row["servings_made"]
    steps = steps_json(body.steps) if "steps" in sent else row["steps_json"]
    source_url = body.source_url if "source_url" in sent else row["source_url"]
    conn.execute(
        """UPDATE meal_templates SET name = ?, note = ?, items_json = ?, meal_hint = ?, servings_made = ?, steps_json = ?,
                  source_url = ?, updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (body.name, body.note, json.dumps(items), meal_hint, servings_made, steps, source_url, utcnow(), meal_id, user.id),
    )
    conn.commit()
    return row_to_template(conn, fetch_template(conn, user.id, meal_id))


@router.delete("/{meal_id}", status_code=204, response_class=Response)
def delete_meal(meal_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    get_template_or_404(conn, user.id, meal_id)
    conn.execute("DELETE FROM meal_templates WHERE id = ? AND user_id = ?", (meal_id, user.id))
    conn.commit()
    return Response(status_code=204)


@router.post("/{meal_id}/apply", response_model=MealApplyResult, status_code=201)
def apply_meal(meal_id: int, body: MealApply, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Log every item of the template on ``date``/``meal`` with the given status, scaled."""
    return apply_template(conn, user.id, meal_id, body)


def apply_template(conn: sqlite3.Connection, user_id: int, meal_id: int, body: MealApply, *,
                   added_by: int | None = None) -> dict[str, Any]:
    """The work of ``POST /api/meals/{id}/apply`` for ``user_id``'s saved meal; ``added_by`` is the helper who applied it for
    the person (``app/sharing.py``, design note 29 §4). Commits."""
    row = get_template_or_404(conn, user_id, meal_id)
    items = parse_items(row["items_json"])
    if not items:
        raise HTTPException(status_code=400, detail="this saved meal has no items")
    created: list[int] = []
    for item in items:
        food = fetch_user_food(conn, user_id, item["food_id"])
        if food is None:
            raise HTTPException(
                status_code=404,
                detail=f"food {item['food_id']} used by this saved meal no longer exists; edit the meal first",
            )
        created.append(
            insert_entry(
                conn, user_id=user_id, date=body.date, meal=body.meal, food=food, servings=item["servings"] * body.scale,
                grams=None, note=None, status=body.status, added_by=added_by,
                # A food for treating a low stays marked as one, so nobody else can change it (note 29 §3).
                purpose=resolve_purpose(food, None),
            )
        )
    conn.commit()
    return {"entries": [row_to_entry(fetch_entry(conn, user_id, entry_id)) for entry_id in created]}


# --------------------------------------------------------------------------- #
# Shopping list
# --------------------------------------------------------------------------- #


@plan_router.get("/shopping", response_model=ShoppingList)
def shopping_list(user: CurrentUser, start: str | None = None, end: str | None = None,
                  conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's planned entries in ``[start, end]`` aggregated by food, ordered by name."""
    start_s, end_s = parse_range(start, end)
    rows = conn.execute(
        """
        SELECT e.food_id, f.name AS food_name, f.serving_desc, f.serving_g,
               SUM(e.servings) AS servings, COUNT(DISTINCT e.date) AS days
        FROM log_entries e
        JOIN foods f ON f.id = e.food_id
        WHERE e.user_id = ? AND e.status = 'planned' AND e.date >= ? AND e.date <= ?
        GROUP BY e.food_id
        ORDER BY f.name COLLATE NOCASE, e.food_id
        """,
        (user.id, start_s, end_s),
    ).fetchall()
    items = []
    for row in rows:
        servings = float(row["servings"])
        items.append(
            {
                "food_id": row["food_id"],
                "food_name": row["food_name"],
                "serving_desc": row["serving_desc"],
                "servings": round(servings, 3),
                "grams": round(servings * float(row["serving_g"]), 1),
                "days": int(row["days"]),
            }
        )
    return {"items": items}
