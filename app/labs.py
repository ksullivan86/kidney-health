"""Lab results: entry with unit conversion, per-person history, and the kidney-function card.

Routes (note 05 §4.6; every one needs a signed-in person and reads or writes only that person's rows;
a result that is not yours is a 404, like one that does not exist):

* ``POST /api/labs`` ``{analyte, value, unit, taken_on, note?}`` → 201, the stored row with the value
  converted to the analyte's canonical unit (:mod:`app.units`) and ``alerts``: a potassium of
  6.0 mmol/L or more always returns the KDIGO 2024 Table 28 safety alert, whatever
  ``targets.lab_rules_enabled`` says. An unknown unit, an implausible value or a future date is a
  400 (the app's validation status; the message says what to fix).
* ``GET /api/labs?analyte=&limit=`` → ``{labs: [...], alerts: [...]}`` newest first (``taken_on``, then entry
  order). ``alerts`` holds the safety alert of the person's newest potassium while it is fresh under
  ``targets.lab_fresh_days.potassium`` (whatever the filters), the window ``GET /api/profile/suggested-targets``
  uses, so the Labs and Profile banners and the suggestion agree.
* ``DELETE /api/labs/{id}`` → 204.
* ``GET /api/labs/kidney-function`` → eGFR and albuminuria from the person's results
  (:func:`app.kidney_function.assess`); never changes the saved stage.

Lab values are health data: they are never logged, and they leave the server only in the person's
own export (``/api/me/export.zip``); deleting the account deletes them (``ON DELETE CASCADE``).
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Iterable, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from . import units
from .auth.deps import CurrentUser, current_user
from .db import get_db, utcnow
from .kidney_function import KIDNEY_ANALYTES, assess
from .models import MAX_SQLITE_INT, Analyte, KidneyFunction, LabCreate, LabCreated, LabList
from . import profile as profile_module
from .targets import Lab, fresh_labs, mode_of, potassium_alert

router = APIRouter(prefix="/api/labs", tags=["labs"], dependencies=[Depends(current_user)])

DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 1000
COLUMNS = "id, analyte, value, entered_value, entered_unit, taken_on, note, created_at"
# labs.csv in the export archive (app/account.py): the stored row plus the canonical unit.
CSV_COLUMNS: tuple[str, ...] = ("id", "analyte", "value", "unit", "entered_value", "entered_unit", "taken_on", "note", "created_at")


def row_to_lab(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """The API shape of a stored result (value rounded to the analyte's shown decimals)."""
    analyte = units.analyte_def(row["analyte"])
    entered_value = float(row["entered_value"])
    entered_unit = row["entered_unit"]
    shown = f"{units.format_value(analyte.key, row['value'])} {analyte.canonical_unit}"
    display = shown if entered_unit == analyte.canonical_unit else f"{entered_value:g} {entered_unit} = {shown}"
    value = units.display_value(analyte.key, row["value"])
    return {
        "id": row["id"],
        "analyte": analyte.key,
        "label": analyte.label,
        "value": int(value) if analyte.decimals == 0 else value,
        "unit": analyte.canonical_unit,
        "entered_value": int(entered_value) if entered_value.is_integer() else entered_value,
        "entered_unit": entered_unit,
        "display": display,
        "taken_on": row["taken_on"],
        "note": row["note"] or "",
        "created_at": row["created_at"],
    }


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in conn.execute(sql, params).fetchall()]


def latest_results(conn: sqlite3.Connection, user_id: int, analytes: Iterable[str]) -> list[dict[str, Any]]:
    """The newest stored result of each analyte for ``user_id`` (uses the ``lab_results_lookup`` index)."""
    out: list[dict[str, Any]] = []
    for analyte in analytes:
        out += _rows(
            conn,
            f"SELECT {COLUMNS} FROM lab_results WHERE user_id = ? AND analyte = ? ORDER BY taken_on DESC, id DESC LIMIT 1",
            (int(user_id), analyte),
        )
    return out


def results_since(conn: sqlite3.Connection, user_id: int, analytes: Iterable[str], since: date) -> list[dict[str, Any]]:
    """Every result of ``analytes`` taken on or after ``since`` (the kidney-function card's 365 days)."""
    names = list(analytes)
    marks = ", ".join("?" for _ in names)
    return _rows(
        conn,
        f"SELECT {COLUMNS} FROM lab_results WHERE user_id = ? AND analyte IN ({marks}) AND taken_on >= ? "
        "ORDER BY taken_on DESC, id DESC",
        (int(user_id), *names, since.isoformat()),
    )


def export_rows(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """Every result of ``user_id`` for the export: stored values unrounded, plus the canonical unit."""
    rows = _rows(conn, f"SELECT {COLUMNS} FROM lab_results WHERE user_id = ? ORDER BY taken_on, id", (int(user_id),))
    for row in rows:
        try:
            row["unit"] = units.analyte_def(row["analyte"]).canonical_unit
        except units.UnitError:  # a row written by a later version: keep it, unit unknown here
            row["unit"] = ""
    return [{k: row[k] for k in CSV_COLUMNS} for row in rows]


@router.post("", status_code=201, response_model=LabCreated)
def create_lab(body: LabCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    result = units.convert(body.analyte, body.value, body.unit)  # validated by LabCreate already
    cur = conn.execute(
        """INSERT INTO lab_results (user_id, analyte, value, entered_value, entered_unit, taken_on, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user.id, result["analyte"], result["value"], result["entered_value"], result["entered_unit"], body.taken_on,
         body.note, utcnow()),
    )
    conn.commit()
    row = conn.execute(f"SELECT {COLUMNS} FROM lab_results WHERE id = ? AND user_id = ?", (cur.lastrowid, user.id)).fetchone()
    out = row_to_lab(row)
    alerts = []
    if result["analyte"] == "potassium":
        alert = potassium_alert(Lab(result["value"], body.taken_on, result["entered_value"], result["entered_unit"]))
        if alert is not None:
            alerts.append(alert)
    out["alerts"] = alerts
    return out


def current_alerts(conn: sqlite3.Connection, user_id: int, request: Request) -> list[dict[str, Any]]:
    """The safety alert of the newest potassium while it counts, with the suggestions' window."""
    windows = profile_module.target_settings(conn, profile_module.settings_store(request))["fresh_days"]
    fresh = fresh_labs(latest_results(conn, user_id, ("potassium",)), profile_module.today(), windows)
    alert = potassium_alert(fresh.get("potassium"))
    return [alert] if alert is not None else []


@router.get("", response_model=LabList)
def list_labs(
    user: CurrentUser,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    analyte: Analyte | None = None,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
) -> dict[str, Any]:
    sql = f"SELECT {COLUMNS} FROM lab_results WHERE user_id = ?"
    params: list[Any] = [user.id]
    if analyte is not None:
        sql += " AND analyte = ?"
        params.append(analyte)
    sql += " ORDER BY taken_on DESC, id DESC LIMIT ?"
    params.append(limit)
    labs = [row_to_lab(r) for r in conn.execute(sql, params).fetchall() if r["analyte"] in units.ANALYTES]
    return {"labs": labs, "alerts": current_alerts(conn, user.id, request)}


@router.get("/kidney-function", response_model=KidneyFunction)
def kidney_function(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    profile = profile_module.get_profile(conn, user.id)
    day = profile_module.today()
    window = max(units.fresh_days(a) or 0 for a in (*KIDNEY_ANALYTES, "uacr"))
    since = date.fromordinal(day.toordinal() - window)
    labs = results_since(conn, user.id, (*KIDNEY_ANALYTES, "uacr"), since)
    return assess(
        labs=labs,
        today=day,
        ckd_stage=profile["ckd_stage"],
        dialysis=profile["dialysis"],
        transplant=mode_of(profile["dialysis"], profile["transplant_date"]) == "transplant",
        birth_month=profile["birth_month"],
        sex=profile["sex"],
        pregnant_or_breastfeeding=profile["pregnant_or_breastfeeding"],
    )


@router.delete("/{lab_id}", status_code=204)
def delete_lab(lab_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    if lab_id < 1 or lab_id > MAX_SQLITE_INT:
        raise HTTPException(status_code=404, detail="Lab result not found")
    cur = conn.execute("DELETE FROM lab_results WHERE id = ? AND user_id = ?", (lab_id, user.id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Lab result not found")
    return Response(status_code=204)
