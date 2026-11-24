"""Step 38: one ID for every synced row, and the change feed (design note 39 §8.2 and §8.4, plan step 5; ARCHITECTURE "The change
feed").

* **``client_id`` on every synced table.** ``foods`` (the person's own foods only: shared rows have no owner and stay NULL),
  ``meal_templates``, ``lab_results``, ``symptoms``, ``weights`` and ``blood_pressures`` get a ``client_id`` column (a UUID in its
  36-character form, lower-case), as ``log_entries`` has had since step 5. Unique per person (an index on the owner and the ID).
* **Step 37's receipts carry over.** For a receipt with ``added = 1`` the row takes the phone's ``client_id``, so the phone and the
  server already agree. A receipt with ``added = 0`` names a row that was already here: that row keeps an ID of its own, and
  ``POST /push/v1/match`` tells the phone.
* **Every other row gets a new random ID** (UUID version 4), and so does every row made later without one: an ``AFTER INSERT``
  trigger per table fills it, so every writer (the web app, the import, the assistant, the Care team, the phone, housekeeping) is
  covered.
* **``sync_changes``**: one row per synced row, the latest change of it, with an ``AUTOINCREMENT`` id that serves as the cursor
  (SQLite never gives an id twice). ``AFTER INSERT``, ``AFTER UPDATE`` and ``AFTER DELETE`` triggers on each synced table replace
  the row's earlier change with a new one; a delete leaves a tombstone (``deleted = 1``) with the row's ``client_id``. There is no
  foreign key on ``user_id``: the tombstones of an account being deleted are not written (the trigger checks the person still
  exists), and a trigger on ``users`` deletes the account's changes.
* **``sync_purged``**: per person, the highest change id of the tombstones the daily housekeeping removed after 180 days. A cursor
  below it is too old: the feed answers ``410`` and the phone reads everything again.
* Every row that exists now is written to ``sync_changes`` once, so a feed read from the start returns all of them.

Idempotent: columns are added only when missing, IDs only where NULL, the rest is ``IF NOT EXISTS``, and the seeding skips rows that
already have a change.
"""
from __future__ import annotations

import sqlite3
import uuid

from ..db import add_column_if_missing, execute_script, table_exists

VERSION = 38
DESCRIPTION = "one client_id for every synced row, and the change feed (sync_changes, sync_purged, triggers)"

SCHEMA = ""  # alters tables of earlier steps and reads app_sync_rows (step 37), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

# kind → (table, the column that names the person, an extra condition for rows that sync)
SYNCED: dict[str, tuple[str, str, str]] = {
    "food": ("foods", "owner_user_id", "owner_user_id IS NOT NULL"),
    "entry": ("log_entries", "user_id", "user_id IS NOT NULL"),
    "meal": ("meal_templates", "user_id", "user_id IS NOT NULL"),
    "lab": ("lab_results", "user_id", "1"),
    "symptom": ("symptoms", "user_id", "1"),
    "weight": ("weights", "user_id", "1"),
    "reading": ("blood_pressures", "user_id", "1"),
}
NEW_COLUMNS = ("foods", "meal_templates", "lab_results", "symptoms", "weights", "blood_pressures")

# A random UUID (version 4) in SQL, for the rows made after this step without an ID.
UUID_SQL = ("lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))), 2) || '-' "
            "|| substr('89ab', 1 + (abs(random()) % 4), 1) || substr(lower(hex(randomblob(2))), 2) || '-' || lower(hex(randomblob(6)))")
NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

DDL = """
CREATE TABLE IF NOT EXISTS sync_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('food', 'entry', 'meal', 'lab', 'symptom', 'weight', 'reading')),
  row_id INTEGER NOT NULL,
  client_id TEXT,
  deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sync_changes_feed ON sync_changes(user_id, id);
CREATE INDEX IF NOT EXISTS sync_changes_row ON sync_changes(kind, row_id);
CREATE INDEX IF NOT EXISTS sync_changes_tombstones ON sync_changes(at) WHERE deleted = 1;
CREATE TABLE IF NOT EXISTS sync_purged (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  through_id INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS sync_changes_user_deleted AFTER DELETE ON users BEGIN
  DELETE FROM sync_changes WHERE user_id = OLD.id;
END;
"""


def _triggers(kind: str, table: str, owner: str, where: str) -> str:
    new_ok = "1" if where == "1" else where.replace(owner, f"NEW.{owner}")
    old_ok = "1" if where == "1" else where.replace(owner, f"OLD.{owner}")
    record = ("DELETE FROM sync_changes WHERE kind = '{kind}' AND row_id = {ref}.id;\n"
              "  INSERT INTO sync_changes (user_id, kind, row_id, client_id, deleted, at) "
              "VALUES ({ref}.{owner}, '{kind}', {ref}.id, {ref}.client_id, {deleted}, {now});")
    return f"""
CREATE TRIGGER IF NOT EXISTS sync_{table}_client_id AFTER INSERT ON {table} WHEN NEW.client_id IS NULL AND {new_ok} BEGIN
  UPDATE {table} SET client_id = {UUID_SQL} WHERE id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS sync_{table}_inserted AFTER INSERT ON {table} WHEN {new_ok} BEGIN
  {record.format(kind=kind, ref="NEW", owner=owner, deleted=0, now=NOW_SQL)}
END;
CREATE TRIGGER IF NOT EXISTS sync_{table}_updated AFTER UPDATE ON {table} WHEN {new_ok} BEGIN
  {record.format(kind=kind, ref="NEW", owner=owner, deleted=0, now=NOW_SQL)}
END;
CREATE TRIGGER IF NOT EXISTS sync_{table}_deleted AFTER DELETE ON {table}
  WHEN {old_ok} AND EXISTS (SELECT 1 FROM users WHERE id = OLD.{owner}) BEGIN
  {record.format(kind=kind, ref="OLD", owner=owner, deleted=1, now=NOW_SQL)}
END;
"""


def _carry_over_receipts(conn: sqlite3.Connection) -> None:
    """A row the phone added (``added = 1``) takes the phone's ``client_id``, unless the person already has a row with it."""
    if not table_exists(conn, "app_sync_rows"):
        return
    for kind, (table, owner, _where) in SYNCED.items():
        receipts = conn.execute("SELECT user_id, client_id, row_id FROM app_sync_rows WHERE kind = ? AND added = 1 ORDER BY id",
                                (kind,)).fetchall()
        for user_id, client_id, row_id in receipts:
            conn.execute(
                f"""UPDATE {table} SET client_id = ? WHERE id = ? AND {owner} = ? AND client_id IS NULL
                    AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.{owner} = ? AND t.client_id = ?)""",
                (str(client_id).lower(), int(row_id), int(user_id), int(user_id), str(client_id).lower()))


def _fill_ids(conn: sqlite3.Connection) -> None:
    for _kind, (table, owner, where) in SYNCED.items():
        ids = [r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE client_id IS NULL AND {owner} IS NOT NULL AND {where}")]
        for row_id in ids:
            conn.execute(f"UPDATE {table} SET client_id = ? WHERE id = ?", (str(uuid.uuid4()), int(row_id)))


def _seed_changes(conn: sqlite3.Connection) -> None:
    for kind, (table, owner, where) in SYNCED.items():
        conn.execute(
            f"""INSERT INTO sync_changes (user_id, kind, row_id, client_id, deleted, at)
                SELECT t.{owner}, ?, t.id, t.client_id, 0, {NOW_SQL} FROM {table} t
                WHERE t.{owner} IS NOT NULL AND {where.replace(owner, 't.' + owner) if where != '1' else '1'}
                  AND NOT EXISTS (SELECT 1 FROM sync_changes c WHERE c.kind = ? AND c.row_id = t.id)
                ORDER BY t.id""",
            (kind, kind))


def migrate(conn: sqlite3.Connection) -> None:
    for table in NEW_COLUMNS:
        add_column_if_missing(conn, table, "client_id", "TEXT CHECK (client_id IS NULL OR length(client_id) = 36)")
    _carry_over_receipts(conn)
    _fill_ids(conn)
    execute_script(conn, """
CREATE UNIQUE INDEX IF NOT EXISTS foods_client_id ON foods(owner_user_id, client_id) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS meal_templates_client_id ON meal_templates(user_id, client_id) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS lab_results_client_id ON lab_results(user_id, client_id) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS symptoms_client_id ON symptoms(user_id, client_id) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS weights_client_id ON weights(user_id, client_id) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS blood_pressures_client_id ON blood_pressures(user_id, client_id) WHERE client_id IS NOT NULL;
""")
    execute_script(conn, DDL)
    for kind, (table, owner, where) in SYNCED.items():
        execute_script(conn, _triggers(kind, table, owner, where))
    _seed_changes(conn)
