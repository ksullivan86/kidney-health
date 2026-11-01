"""Step 33: chosen people may pick the server's local or cloud AI (design note 32).

* ``users.can_choose_ai`` (0 or 1, default 0): an admin ticked "May choose the server's local or cloud AI" for this person in
  Server administration → Users. It counts only while the server switch ``AI_PERSON_ROUTE_CHOICE_ENABLED`` is on. Every
  existing account starts without it.

The person's choices themselves are a personal setting (``ai.route_choice``), not a column. Nothing else changes. Idempotent:
the column is added only when missing.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing

VERSION = 33
DESCRIPTION = "a person may choose the server's local or cloud AI: users.can_choose_ai"

SCHEMA = ""  # alters users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True


def migrate(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "users", "can_choose_ai", "INTEGER NOT NULL DEFAULT 0 CHECK (can_choose_ai IN (0, 1))")
