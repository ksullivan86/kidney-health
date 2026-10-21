"""Step 17: who set a food preference, and when it last changed (note 09 §4.2, "Learn my food preferences").

``food_preferences`` (step 5) held only ``'not_for_me'``. Part A of the preference profile widens ``preference`` to
``like``, ``less``, ``not_for_me`` and ``neutral`` (validated by ``app/guidance/api.py``, still no ``CHECK``: a later value must
not need a table rebuild) and records two more facts per row:

* ``source`` (``'person'`` or ``'ask'``): a change the person made themselves, or one the Ask chat proposed and the
  person confirmed. Existing rows are the person's own, so they get ``'person'``.
* ``updated_at`` (UTC): when the row last changed, so the lists can show the most recent first. Existing rows get their
  ``created_at``.

Idempotent: a column is added only when missing, and a back-fill touches only rows still ``NULL``, so a re-run (or a row
written by the app between the two statements) is never changed. The key, the foreign keys and the index stay as step 5
made them.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing

VERSION = 17
DESCRIPTION = "food_preferences: source (person or ask) and updated_at, for the preference profile"

SCHEMA = ""  # the table is made by step 5's migrate(), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

COLUMNS: tuple[tuple[str, str], ...] = (("source", "TEXT"), ("updated_at", "TEXT"))


def migrate(conn: sqlite3.Connection) -> None:
    for column, ddl in COLUMNS:
        add_column_if_missing(conn, "food_preferences", column, ddl)
    conn.execute("UPDATE food_preferences SET source = 'person' WHERE source IS NULL")
    conn.execute("UPDATE food_preferences SET updated_at = created_at WHERE updated_at IS NULL")
