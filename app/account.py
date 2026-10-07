"""A person's own data: the export archive and account deletion (note 07 §4.14).

* :func:`build_export` returns a ``.zip`` with ``export.json`` (the documented shape below),
  ``log.csv``, ``foods.csv``, ``meals.csv``, ``labs.csv`` and ``README.txt``. It never contains
  passwords, session data or API keys (not even their last four characters). Every CSV cell that a
  spreadsheet would run as a formula is escaped (:func:`app.log.csv_safe`).
* :func:`delete_user` audits, then ``DELETE FROM users`` (every personal table cascades: entries,
  custom foods, saved meals, profile, settings, keys, sessions, usage, links), then checkpoints the
  WAL. Every connection uses ``PRAGMA secure_delete = FAST``; ``python -m app.admin vacuum`` removes
  what is left on free pages. Backups taken earlier still hold the data until they expire.

``export.json``::

    {"format": "kidney-health-export", "version": 1, "exported_at", "app_version",
     "user": {username, display_name, created_at}, "profile", "settings", "log_entries",
     "custom_foods", "linked_foods", "meal_templates", "lab_results", "ai_audit", "activity",
     "food_preferences", "ai_usage", "ai_consents", "ai_provider"}

``food_preferences`` (v0.3, schema step 5) lists the foods the person marked "Not for me" in meal
guidance: ``[{food_id, name, preference, created_at}]``.

AI (v0.3, schema step 6; note 04 §9 A8): ``ai_audit`` is the person's AI activity (what was sent and
received while kept, never images), ``ai_usage`` the daily call and token counts, ``ai_consents`` the
hosts they agreed to send data to, and ``ai_provider`` their own provider without its key (``null``
when they have none).
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from .audit import USER_VISIBLE_ACTIONS, audit, list_events
from .db import table_columns, table_exists, utcnow

EXPORT_FORMAT = "kidney-health-export"
EXPORT_VERSION = 1
FOOD_CSV_FIELDS = ("id", "name", "brand", "category", "source", "fdc_id", "serving_desc", "serving_g",
                   "gtin", "source_license", "source_url")  # v0.3 barcodes: the ODbL notice travels with the data
README = """\
Kidney Health export
====================

This archive holds everything this server stores about your account, in two forms:

* export.json  - every record, in a documented JSON format ("kidney-health-export", version 1) that
                 a later version of the app can import.
* log.csv      - your food log (eaten and planned entries) with the nutrient snapshot of each entry.
* foods.csv    - foods you created, and shared foods you imported or scanned.
* meals.csv    - your saved meals, one line per food.
* labs.csv     - your lab results (empty if you have none).

export.json also holds your AI activity (what the app sent to an AI provider for you and what came
back, for as long as the server keeps it; never photos), your daily AI call counts and the AI
providers you agreed to send data to.

What is NOT in it: your password, your sign-in sessions and any API keys you stored (not even part
of them). The person who runs the server keeps backups of the whole database; deleting your account
does not reach those backups until they expire.

Where a food's data came from is in the "source" and "source_license" columns. Rows marked ODbL-1.0
contain information from Open Food Facts (https://world.openfoodfacts.org), which is made available
under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/). Rows marked CC0-1.0
come from USDA FoodData Central (public domain).

The numbers are what the app recorded. They are not medical advice; talk to your kidney team or
dietitian about your targets.
"""


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in conn.execute(sql, params).fetchall()]


def _per_user_table(conn: sqlite3.Connection, table: str, user_id: int) -> list[dict[str, Any]]:
    """Rows of an optional per-user table added by a later step (labs, AI audit); [] if absent."""
    if not table_exists(conn, table) or "user_id" not in table_columns(conn, table):
        return []
    return _rows(conn, f"SELECT * FROM {table} WHERE user_id = ? ORDER BY rowid", (int(user_id),))


def _food_preferences(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """The person's "Not for me" foods (schema step 5); [] on an older schema."""
    if not table_exists(conn, "food_preferences"):
        return []
    return _rows(conn, """SELECT p.food_id, f.name, p.preference, p.created_at FROM food_preferences p
                          JOIN foods f ON f.id = p.food_id WHERE p.user_id = ? ORDER BY p.food_id""", (int(user_id),))


def _ai_rows(conn: sqlite3.Connection, table: str, user_id: int, order: str) -> list[dict[str, Any]]:
    """Rows of a per-user AI table (``WITHOUT ROWID``, so ordered by its key); [] on an older schema."""
    if not table_exists(conn, table):
        return []
    return _rows(conn, f"SELECT * FROM {table} WHERE user_id = ? ORDER BY {order}", (int(user_id),))


def _own_ai_provider(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    """The person's own AI provider (schema step 6) without its key or key hint; None if they have none."""
    if not table_exists(conn, "ai_providers"):
        return None
    row = conn.execute(
        """SELECT preset, label, base_url, model, vision_model, created_at, updated_at, api_key_enc IS NOT NULL AS key_set
           FROM ai_providers WHERE scope = 'user' AND owner_user_id = ?""",
        (int(user_id),),
    ).fetchone()
    return None if row is None else {k: (bool(row[k]) if k == "key_set" else row[k]) for k in row.keys()}


def _lab_results(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """Lab results (schema step 4) with the canonical unit, unrounded; [] on an older schema."""
    if not table_exists(conn, "lab_results"):
        return []
    from .labs import export_rows

    return export_rows(conn, user_id)


def _csv(header: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    from .log import csv_safe

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(header))
    for row in rows:
        writer.writerow([csv_safe(v) for v in row])
    return buffer.getvalue()


def export_data(conn: sqlite3.Connection, user_id: int, *, app_version: str) -> dict[str, Any]:
    """The ``export.json`` document for ``user_id`` (only that person's rows)."""
    from .foods import row_to_food
    from .log import fetch_entries, row_to_entry
    from .meals import row_to_template
    from .profile import get_profile

    uid = int(user_id)
    user = conn.execute("SELECT username, display_name, created_at FROM users WHERE id = ?", (uid,)).fetchone()
    settings = {
        r["key"]: json.loads(r["value_json"])
        for r in conn.execute("SELECT key, value_json FROM user_settings WHERE user_id = ? ORDER BY key", (uid,))
    }
    custom = conn.execute("SELECT * FROM foods WHERE owner_user_id = ? ORDER BY id", (uid,)).fetchall()
    linked = conn.execute(
        """SELECT f.id, f.name, f.source, f.fdc_id, l.created_at AS linked_at FROM user_food_links l
           JOIN foods f ON f.id = l.food_id WHERE l.user_id = ? ORDER BY f.id""",
        (uid,),
    ).fetchall()
    templates = conn.execute("SELECT * FROM meal_templates WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": utcnow(),
        "app_version": app_version,
        "user": {"username": user["username"], "display_name": user["display_name"] or "", "created_at": user["created_at"]},
        "profile": get_profile(conn, uid),
        "settings": settings,
        "log_entries": [row_to_entry(r) for r in fetch_entries(conn, uid)],
        "custom_foods": [row_to_food(r) for r in custom],
        "linked_foods": [{k: r[k] for k in r.keys()} for r in linked],
        "meal_templates": [row_to_template(conn, r) for r in templates],
        "lab_results": _lab_results(conn, uid),
        "ai_audit": _per_user_table(conn, "ai_audit", uid),
        "activity": list_events(conn, actor_user_id=uid, actions=USER_VISIBLE_ACTIONS, limit=500),
        "food_preferences": _food_preferences(conn, uid),
        "ai_usage": _ai_rows(conn, "ai_usage", uid, "day, provider_id"),
        "ai_consents": _ai_rows(conn, "ai_consents", uid, "provider_id, purpose"),
        "ai_provider": _own_ai_provider(conn, uid),
    }


def build_export(conn: sqlite3.Connection, user_id: int, *, app_version: str) -> bytes:
    """The export archive (``.zip``) for ``user_id``."""
    from .log import CSV_COLUMNS, csv_row, fetch_entries
    from .nutrients import NUTRIENT_KEYS

    uid = int(user_id)
    data = export_data(conn, uid, app_version=app_version)

    entries = fetch_entries(conn, uid)
    log_csv = _csv(CSV_COLUMNS, (csv_row(r) for r in entries))  # source and source_license are columns since v0.3

    food_rows = []
    for food in [*data["custom_foods"], *(
        f for f in (_food_by_id(conn, row["id"]) for row in data["linked_foods"]) if f is not None
    )]:
        food_rows.append(
            [food.get(k) for k in FOOD_CSV_FIELDS]
            + [food["nutrients"].get(k) for k in NUTRIENT_KEYS]
            + [" ".join(food.get("flags") or []), food.get("kidney_notes")]
        )
    foods_csv = _csv((*FOOD_CSV_FIELDS, *NUTRIENT_KEYS, "flags", "kidney_notes"), food_rows)

    meal_rows = []
    for meal in data["meal_templates"]:
        for item in meal["items"] or [{}]:
            meal_rows.append([meal["id"], meal["name"], meal["note"], item.get("food_id"), item.get("food_name"), item.get("servings")])
    meals_csv = _csv(("meal_id", "meal_name", "note", "food_id", "food_name", "servings"), meal_rows)

    from .labs import CSV_COLUMNS as LAB_CSV_COLUMNS

    labs_csv = _csv(LAB_CSV_COLUMNS, ([lab.get(k) for k in LAB_CSV_COLUMNS] for lab in data["lab_results"]))

    buffer = io.BytesIO()
    stamp = datetime.now(timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in (
            ("export.json", json.dumps(data, ensure_ascii=False, indent=2, default=str)),
            ("log.csv", log_csv),
            ("foods.csv", foods_csv),
            ("meals.csv", meals_csv),
            ("labs.csv", labs_csv),
            ("README.txt", README),
        ):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text.encode("utf-8"))
    return buffer.getvalue()


def _food_by_id(conn: sqlite3.Connection, food_id: int) -> dict[str, Any] | None:
    from .foods import fetch_food, row_to_food

    row = fetch_food(conn, food_id)
    return None if row is None else row_to_food(row)


def export_filename(username: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in username)[:40] or "account"
    return f"kidney-health-{safe}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.zip"


def delete_user(conn: sqlite3.Connection, user_id: int, *, actor_id: int | None, ip: str | None = None,
                action: str = "account.deleted") -> None:
    """Audit, delete the account and everything it owns (cascade), commit, checkpoint the WAL.

    Invites and reset/setup links the account created are deleted first: ``auth_tokens.created_by``
    is ``ON DELETE SET NULL``, so after the delete nothing would tie them to the removed admin and they
    would keep working (one could be a reset link for the remaining admin's account)."""
    from .auth.tokens import void_issued_by

    uid = int(user_id)
    voided = void_issued_by(conn, uid)
    audit(conn, actor_id, action, "user", uid, ip=ip, **({"links_revoked": voided} if voided else {}))
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    except sqlite3.Error:  # another connection is reading; the next checkpoint finishes the job
        pass
