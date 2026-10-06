"""Each person's profile (``user_profiles``, one row per account) with their targets, dialysis
weekdays and week start. The v0.2 singleton ``profile`` table was copied into user 1's row by
schema step 3 and is never read again."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .auth.deps import CurrentUser, current_user
from .db import get_db, utcnow
from .models import Profile, ProfileUpdate, SuggestedTargets
from .nutrients import suggest_targets
from .periods import WEEK_STARTS

router = APIRouter(prefix="/api/profile", tags=["profile"], dependencies=[Depends(current_user)])

# Columns a PUT may change (NOT NULL columns ignore explicit nulls).
_NULLABLE_COLUMNS = ("weight_kg", "height_cm")
_NOT_NULL_COLUMNS = ("name", "ckd_stage", "dialysis", "diabetes", "warn_fraction", "week_start")


def ensure_profile(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    """Return ``user_id``'s profile row, creating it with schema defaults on first access."""
    row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (int(user_id),)).fetchone()
    if row is None:
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles (user_id, updated_at, updated_by) VALUES (?, ?, ?)",
            (int(user_id), utcnow(), int(user_id)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (int(user_id),)).fetchone()
    return row


def parse_targets(targets_json: str | None) -> dict[str, Any]:
    try:
        value = json.loads(targets_json or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def parse_dialysis_days(days_json: str | None) -> list[int]:
    """Stored JSON list -> sorted unique weekdays 0..6 (anything odd is dropped, never raised)."""
    try:
        value = json.loads(days_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    days: set[int] = set()
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if float(v).is_integer() and 0 <= int(v) <= 6:
            days.add(int(v))
    return sorted(days)


def row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
    week_start = row["week_start"] if row["week_start"] in WEEK_STARTS else "monday"
    return {
        "id": row["user_id"],
        "name": row["name"],
        "weight_kg": row["weight_kg"],
        "height_cm": row["height_cm"],
        "ckd_stage": row["ckd_stage"],
        "dialysis": row["dialysis"],
        "diabetes": row["diabetes"],
        "warn_fraction": row["warn_fraction"],
        "dialysis_days": parse_dialysis_days(row["dialysis_days_json"]),
        "week_start": week_start,
        "targets": parse_targets(row["targets_json"]),
        "updated_at": row["updated_at"],
    }


def get_profile(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    return row_to_profile(ensure_profile(conn, user_id))


@router.get("", response_model=Profile)
def read_profile(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return get_profile(conn, user.id)


@router.put("", response_model=Profile)
def update_profile(body: ProfileUpdate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Merge the provided fields into the profile.

    ``targets`` is merged key by key: keys that are sent overwrite (``null`` means
    "not tracked"), keys that are not sent keep their stored value. ``dialysis_days``
    replaces the whole list (``null`` or ``[]`` clears it) and is stored for any
    ``dialysis`` value; only the hemodialysis summary uses it.
    """
    current = get_profile(conn, user.id)
    data = body.model_dump(exclude_unset=True)

    sets: list[str] = []
    params: list[Any] = []
    for col in _NULLABLE_COLUMNS:
        if col in data:
            sets.append(f"{col} = ?")
            params.append(data[col])
    for col in _NOT_NULL_COLUMNS:
        if col in data and data[col] is not None:
            sets.append(f"{col} = ?")
            params.append(data[col])
    if data.get("targets") is not None:
        merged = dict(current["targets"])
        merged.update(data["targets"])
        sets.append("targets_json = ?")
        params.append(json.dumps(merged))
    if "dialysis_days" in data:
        sets.append("dialysis_days_json = ?")
        params.append(json.dumps(data["dialysis_days"] or []))

    sets += ["updated_at = ?", "updated_by = ?"]
    params += [utcnow(), user.id]
    conn.execute(f"UPDATE user_profiles SET {', '.join(sets)} WHERE user_id = ?", [*params, user.id])
    conn.commit()
    return get_profile(conn, user.id)


@router.get("/suggested-targets", response_model=SuggestedTargets)
def suggested_targets(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    profile = get_profile(conn, user.id)
    if profile["weight_kg"] is None:
        raise HTTPException(
            status_code=400,
            detail="Save your weight in the profile first; the suggestions are per kg of body weight",
        )
    try:
        return suggest_targets(
            profile["weight_kg"],
            profile["ckd_stage"],
            profile["dialysis"],
            profile["diabetes"],
            height_cm=profile["height_cm"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
