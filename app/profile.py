"""Each person's profile (``user_profiles``, one row per account) with their targets, dialysis
weekdays and week start, plus (v0.3) the "About you" fields of note 05 §4.2 and the personalised
suggestion. The v0.2 singleton ``profile`` table was copied into user 1's row by schema step 3 and
is never read again."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import targets as targets_engine
from .auth.deps import CurrentUser, current_user
from .db import get_db, table_exists, utcnow
from .models import Profile, ProfileUpdate, SuggestedTargets
from .periods import WEEK_STARTS
from .settings_store import SettingsStore, default_store
from .target_rules import ACTIVITIES, SEXES

log = logging.getLogger("kidney_health.profile")

router = APIRouter(prefix="/api/profile", tags=["profile"], dependencies=[Depends(current_user)])

# Columns a PUT may change. Nullable ones store an explicit null; v0.2's NOT NULL columns ignore it;
# the v0.3 NOT NULL ones go back to their default ("empty or null clears them", note 05 §4.6).
_NULLABLE_COLUMNS = (
    "weight_kg", "height_cm", "birth_month", "activity", "transplant_date", "weight_6_months_ago_kg",
    "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal",
)
_NOT_NULL_COLUMNS = ("name", "ckd_stage", "dialysis", "diabetes", "warn_fraction", "week_start")
_RESET_TO_DEFAULT: dict[str, Any] = {
    "sex": "unspecified", "frail_or_sarcopenic": 0, "pregnant_or_breastfeeding": 0, "hyperkalemia_history": 0,
}
_BOOL_COLUMNS = ("frail_or_sarcopenic", "pregnant_or_breastfeeding", "hyperkalemia_history")
_BIRTH_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def _column(row: sqlite3.Row, name: str, default: Any = None) -> Any:
    """``row[name]``, or ``default`` on a database without that column (before schema step 4)."""
    return row[name] if name in row.keys() else default


def _v03_fields(row: sqlite3.Row) -> dict[str, Any]:
    """The note 05 §4.2 fields; a stored value the API would refuse reads as unset (never a 500)."""
    birth_month = _column(row, "birth_month")
    transplant_date = _column(row, "transplant_date")
    sex = _column(row, "sex", "unspecified")
    activity = _column(row, "activity")
    out: dict[str, Any] = {
        "birth_month": birth_month if isinstance(birth_month, str) and _BIRTH_MONTH_RE.match(birth_month) else None,
        "sex": sex if sex in SEXES else "unspecified",
        "activity": activity if activity in ACTIVITIES else None,
        "transplant_date": transplant_date if isinstance(transplant_date, str) and _DATE_RE.match(transplant_date) else None,
    }
    for name in _BOOL_COLUMNS:
        out[name] = bool(_column(row, name, 0))
    for name in ("weight_6_months_ago_kg", "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal"):
        out[name] = _column(row, name)
    return out


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
        **_v03_fields(row),
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
    for col, default in _RESET_TO_DEFAULT.items():
        if col in data:
            value = default if data[col] is None else data[col]
            sets.append(f"{col} = ?")
            params.append(int(value) if col in _BOOL_COLUMNS else value)
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


def settings_store(request: Request) -> SettingsStore:
    """The app's settings store (tests build their own app; a bare router falls back to the default)."""
    return getattr(request.app.state, "settings_store", None) or default_store()


def target_settings(conn: sqlite3.Connection, store: SettingsStore) -> dict[str, Any]:
    """The instance settings the rules read (note 05 §4.9), as keyword arguments for app.targets."""
    return {
        "lab_rules_enabled": bool(store.get(conn, "targets.lab_rules_enabled")),
        "default_activity": store.get(conn, "targets.default_activity"),
        "fresh_days": {a: int(store.get(conn, f"targets.lab_fresh_days.{a}")) for a in targets_engine.DEFAULT_FRESH_DAYS},
    }


def today() -> Any:
    """The server's local date ("today" of note 05 §4.2); one function so tests can move it."""
    return datetime.now().date()


@router.get(
    "/suggested-targets",
    response_model=SuggestedTargets,
    responses={422: {"description": "Out of scope (pregnancy, under 18, first 12 weeks after a transplant): "
                                    '{"detail": "<message>", "code": "out_of_scope_…"}'}},
)
def suggested_targets(
    request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any] | JSONResponse:
    """Personalised starting points (note 05 §4.3–§4.6), never saved. 400 without a weight; 422 with a
    ``code`` when the rules do not cover the person; otherwise targets, notes, rules, derived values,
    missing inputs and safety alerts."""
    from .labs import latest_results

    profile = get_profile(conn, user.id)
    if profile["weight_kg"] is None:
        raise HTTPException(
            status_code=400,
            detail="Save your weight in the profile first; the suggestions are per kg of body weight",
        )
    labs = latest_results(conn, user.id, targets_engine.TARGET_LABS) if table_exists(conn, "lab_results") else []
    try:
        return targets_engine.suggest_from_records(profile, labs, today(), **target_settings(conn, settings_store(request)))
    except targets_engine.OutOfScope as exc:
        # The ARCHITECTURE error shape: "detail" stays a message; "code" says which refusal (note 05 §4.5).
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=422)
    except ValueError as exc:
        log.info("suggested targets: profile of user %d cannot be used: %s", user.id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
