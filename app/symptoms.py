"""Symptoms log: a person records a symptom with a date and a severity; the app records and shows, nothing more.

Routes (every one needs a signed-in person and reads or writes only that person's rows; a symptom that is not yours
is a 404, like one that does not exist):

* ``GET /api/symptoms?start=&end=`` (``YYYY-MM-DD``, both required, at most 366 days) → ``{symptoms: [...]}``, oldest
  day first, then entry order.
* ``POST /api/symptoms`` ``{date, symptom, severity, label?, note?}`` → 201, the stored symptom. ``symptom`` is one of
  :data:`SYMPTOMS`; ``severity`` is 1 (mild), 2 (moderate) or 3 (severe); ``label`` (at most 60 characters) is required
  for ``other`` and refused for the others; ``note`` is at most 300 characters. A date in the future, an unknown
  symptom, a severity outside 1 to 3 and an unknown field are 400s; so is a 31st symptom on one day.
* ``PUT /api/symptoms/{id}`` the same body → 200, the symptom after the change (it replaces the editable fields;
  ``created_at`` stays).
* ``DELETE /api/symptoms/{id}`` → 204.

**What the app says about a symptom.** Nothing about a cause and nothing about a treatment or a dose. The one thing
it adds is a pointer to the handbook: a symptom that the handbook's Get help now page
(``handbook/docs/get-help-now.md``) sorts under "Call 911 now" or "Call your care team today" carries ``red_flag``:
the handbook's own words for it, a link to ``/learn/get-help-now/`` and ``prominent`` (the symptom is recorded as
severe). The table below is that list; ``tests/test_symptoms.py`` checks every quoted phrase against the page, so a
change to the page that drops a phrase fails a test instead of leaving the app quoting words that are gone. Itching,
tiredness, cramps, nausea and poor appetite are under "Mention at your next visit" on that page and carry no
``red_flag``.

Symptoms are health data: they are never logged, they leave the server only in the person's own export, and they are
never sent to an AI provider or the assistant (``app/ai/``, ``app/mcp/`` and ``app/guidance/`` do not read the
table; ``tests/test_symptoms.py`` checks). Deleting the account deletes them (``ON DELETE CASCADE``).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Sequence, get_args

from fastapi import APIRouter, Depends, HTTPException, Response

from .auth.deps import CurrentUser, current_user
from .db import get_db, utcnow
from .write_receipts import IdempotencyKey, WriteReceipt
from .log import parse_range
from .models import (
    MAX_SQLITE_INT,
    MAX_SYMPTOMS_PER_DAY,
    SymptomCreate,
    SymptomKey,
    SymptomList,
    SymptomOut,
)

router = APIRouter(prefix="/api/symptoms", tags=["symptoms"], dependencies=[Depends(current_user)])

# (key, name shown) in the order the app lists them. "other" is named by the person's own label.
SYMPTOMS: tuple[tuple[str, str], ...] = (
    ("swelling", "Swelling"),
    ("itching", "Itching"),
    ("tiredness", "Tiredness"),
    ("cramps", "Cramps"),
    ("nausea", "Nausea"),
    ("breathlessness", "Breathlessness"),
    ("poor_appetite", "Poor appetite"),
    ("other", "Other"),
)
SYMPTOM_NAMES: dict[str, str] = dict(SYMPTOMS)
assert tuple(SYMPTOM_NAMES) == get_args(SymptomKey), "app.symptoms.SYMPTOMS and app.models.SymptomKey must list the same keys"

SEVERITY_LABELS: dict[int, str] = {1: "Mild", 2: "Moderate", 3: "Severe"}

GET_HELP_NOW_HREF = "/learn/get-help-now/"
GET_HELP_NOW_LINK_TEXT = "Get help now"
EMERGENCY = "emergency"  # the handbook's "Call 911 now" group
TODAY = "today"  # the handbook's "Call your care team today" group
HANDBOOK_GROUP_HEADINGS: dict[str, str] = {EMERGENCY: "Call 911 now", TODAY: "Call your care team today"}

# The symptoms the handbook lists as warning signs. ``quotes`` are phrases copied from the page (without its bold
# marks); ``text`` is the line the app shows and is built only from those quotes and the page's own group headings.
RED_FLAGS: dict[str, dict[str, Any]] = {
    "breathlessness": {
        "level": EMERGENCY,
        "quotes": ("Severe breathlessness", "sudden breathlessness or fainting with no clear cause"),
        "text": "The handbook lists “severe breathlessness” and “sudden breathlessness or fainting with no clear cause” "
                "under “Call 911 now”.",
    },
    "swelling": {
        "level": TODAY,
        "quotes": ("new swelling of the legs, ankles or face",),
        "text": "The handbook lists “new swelling of the legs, ankles or face” under “Call your care team today”.",
    },
}
assert set(RED_FLAGS) <= set(SYMPTOM_NAMES) - {"other"}


def red_flag(symptom: str, severity: int) -> dict[str, Any] | None:
    """The handbook pointer for ``symptom`` recorded at ``severity``, or ``None`` for a symptom the page does not list."""
    entry = RED_FLAGS.get(symptom)
    if entry is None:
        return None
    return {"level": entry["level"], "text": entry["text"], "href": GET_HELP_NOW_HREF,
            "link_text": GET_HELP_NOW_LINK_TEXT, "prominent": severity == 3}


COLUMNS = "id, date, symptom, label, severity, note, created_at"
# symptoms.csv in the export archive (app/account.py): the stored row.
CSV_COLUMNS: tuple[str, ...] = ("id", "date", "symptom", "label", "severity", "note", "created_at")


def row_to_symptom(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """The API shape of a stored symptom."""
    key = row["symptom"]
    label = row["label"] or ""
    severity = int(row["severity"])
    return {
        "id": row["id"],
        "date": row["date"],
        "symptom": key,
        "label": label,
        "name": label if key == "other" else SYMPTOM_NAMES[key],
        "severity": severity,
        "severity_label": SEVERITY_LABELS[severity],
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "red_flag": red_flag(key, severity),
    }


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any]) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def export_rows(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """Every symptom of ``user_id`` for the export: the stored columns, oldest day first (also a key this version does
    not know, so nothing the person recorded is left out of their file)."""
    rows = _rows(conn, f"SELECT {COLUMNS} FROM symptoms WHERE user_id = ? ORDER BY date, id", (int(user_id),))
    return [{k: row[k] for k in CSV_COLUMNS} for row in rows]


def count_on_day(conn: sqlite3.Connection, user_id: int, day: str, *, except_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) FROM symptoms WHERE user_id = ? AND date = ?"
    params: list[Any] = [int(user_id), day]
    if except_id is not None:
        sql += " AND id <> ?"
        params.append(int(except_id))
    return int(conn.execute(sql, params).fetchone()[0])


def _check_day_not_full(conn: sqlite3.Connection, user_id: int, day: str, *, except_id: int | None = None) -> None:
    if count_on_day(conn, user_id, day, except_id=except_id) >= MAX_SYMPTOMS_PER_DAY:
        raise HTTPException(status_code=400, detail=f"too many symptoms for one day (max {MAX_SYMPTOMS_PER_DAY})")


def _fetch(conn: sqlite3.Connection, user_id: int, symptom_id: int) -> sqlite3.Row:
    """The person's own symptom, or a 404 (the same for a symptom that is somebody else's and one that does not exist)."""
    row = None
    if 1 <= symptom_id <= MAX_SQLITE_INT:
        row = conn.execute(f"SELECT {COLUMNS} FROM symptoms WHERE id = ? AND user_id = ?", (symptom_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Symptom not found")
    return row


@router.get("", response_model=SymptomList)
def list_symptoms(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db), start: str | None = None,
                  end: str | None = None) -> dict[str, Any]:
    start_s, end_s = parse_range(start, end)
    rows = _rows(conn, f"SELECT {COLUMNS} FROM symptoms WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date, id",
                 (user.id, start_s, end_s))
    # a row written by a later version (a key this one does not know) is kept, never shown
    return {"symptoms": [row_to_symptom(r) for r in rows if r["symptom"] in SYMPTOM_NAMES]}


@router.post("", status_code=201, response_model=SymptomOut)
def create_symptom(body: SymptomCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db),
                   idempotency_key: IdempotencyKey = None) -> dict[str, Any]:
    receipt = WriteReceipt(conn, user.id, "symptoms.create", idempotency_key, body)
    if receipt.replay is not None:
        return receipt.replay
    _check_day_not_full(conn, user.id, body.date)
    cur = conn.execute(
        "INSERT INTO symptoms (user_id, date, symptom, label, severity, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user.id, body.date, body.symptom, body.label, body.severity, body.note, utcnow()),
    )
    return receipt.commit(row_to_symptom(_fetch(conn, user.id, int(cur.lastrowid))), SymptomOut)


@router.put("/{symptom_id}", response_model=SymptomOut)
def update_symptom(symptom_id: int, body: SymptomCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _fetch(conn, user.id, symptom_id)
    _check_day_not_full(conn, user.id, body.date, except_id=symptom_id)
    conn.execute(
        "UPDATE symptoms SET date = ?, symptom = ?, label = ?, severity = ?, note = ? WHERE id = ? AND user_id = ?",
        (body.date, body.symptom, body.label, body.severity, body.note, symptom_id, user.id),
    )
    conn.commit()
    return row_to_symptom(_fetch(conn, user.id, symptom_id))


@router.delete("/{symptom_id}", status_code=204)
def delete_symptom(symptom_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _fetch(conn, user.id, symptom_id)
    conn.execute("DELETE FROM symptoms WHERE id = ? AND user_id = ?", (symptom_id, user.id))
    conn.commit()
    return Response(status_code=204)
