"""Step 5: meal guidance and the offline outbox (note 06 §4.11, note 02 R5).

1. ``log_entries.purpose`` (``'hypo'`` or NULL): the entry treated a low. Low treatments count toward
   potassium, phosphorus, sodium and fluid, but never toward a meal's carbohydrate, the carb insights
   or swap ideas that shrink them (note 06 F5). Existing rows stay NULL: the step does not guess
   which past entries were low treatments; new entries of ``hypo_treatment`` foods default to
   ``'hypo'`` in ``app/log.py``.
2. ``log_entries.client_id`` (a UUID from the offline outbox, at most 36 characters) with the
   partial unique index ``log_client_id (user_id, client_id) WHERE client_id IS NOT NULL``: a replay
   of the same entry is recognised and answered with the existing row (note 02 R5). Two people may
   use the same ``client_id``.
3. ``meal_templates.meal_hint`` (a meal slot or NULL): the slot a saved meal belongs to, so the plan
   builder never plans "Usual dinner" as a snack (note 06 F10).
4. ``food_preferences (user_id, food_id, preference)``: "Not for me" foods that guidance never
   suggests (note 06 §4.14). Both keys cascade, so deleting the account or the food removes the row.
   The other guidance preferences live in the settings registry (key ``guidance``, note 07 §4.11),
   which supersedes note 06's ``guidance_json`` profile column.
5. ``meta.foods_rev``: an integer bumped by triggers on every insert, update and delete of ``foods``
   and ``user_food_links`` (food writes, hides, imports, links), so the guidance vector cache
   (``app/guidance/context.py``) can never serve a stale food list, whichever code path wrote it.

Idempotent: columns are added only when missing; the table, index and triggers use ``IF NOT EXISTS``;
the revision row is inserted only when absent.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 5
DESCRIPTION = "v0.3 guidance and offline log: entry purpose and client_id, saved-meal slot, food preferences"

SCHEMA = ""  # food_preferences references users (created by step 3's migrate()), so everything runs below
ATOMIC = True

FOODS_REV_KEY = "foods_rev"

LOG_COLUMNS: tuple[tuple[str, str], ...] = (
    ("purpose", "TEXT"),
    ("client_id", "TEXT"),
)
TEMPLATE_COLUMNS: tuple[tuple[str, str], ...] = (("meal_hint", "TEXT"),)

_BUMP = f"UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = '{FOODS_REV_KEY}';"

DDL = f"""
CREATE UNIQUE INDEX IF NOT EXISTS log_client_id ON log_entries(user_id, client_id) WHERE client_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS food_preferences (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
  preference TEXT NOT NULL,              -- 'not_for_me' (validated by app/guidance/api.py)
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, food_id)
);
CREATE INDEX IF NOT EXISTS food_preferences_food ON food_preferences(food_id);

CREATE TRIGGER IF NOT EXISTS foods_rev_insert AFTER INSERT ON foods BEGIN {_BUMP} END;
CREATE TRIGGER IF NOT EXISTS foods_rev_update AFTER UPDATE ON foods BEGIN {_BUMP} END;
CREATE TRIGGER IF NOT EXISTS foods_rev_delete AFTER DELETE ON foods BEGIN {_BUMP} END;
CREATE TRIGGER IF NOT EXISTS food_links_rev_insert AFTER INSERT ON user_food_links BEGIN {_BUMP} END;
CREATE TRIGGER IF NOT EXISTS food_links_rev_delete AFTER DELETE ON user_food_links BEGIN {_BUMP} END;
"""


def migrate(conn: sqlite3.Connection) -> None:
    for column, ddl in LOG_COLUMNS:
        add_column_if_missing(conn, "log_entries", column, ddl)
    for column, ddl in TEMPLATE_COLUMNS:
        add_column_if_missing(conn, "meal_templates", column, ddl)
    conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, '0')", (FOODS_REV_KEY,))
    execute_script(conn, DDL)
