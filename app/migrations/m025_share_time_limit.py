"""Step 25: a share can end on a date (design note 19 §11, built 2026-10-29).

``shares`` gains two columns:

* ``lasts_days`` (``INTEGER``, 1 to 365, or NULL): what the owner chose when making the link, "until I stop it" (NULL) or a number
  of days;
* ``ends_at`` (``TEXT``, or NULL): set when the link is accepted, to the moment the share ends. A share past it is ended by the
  server the next time anyone uses sharing (``app/sharing.py`` ``expire``), as if the owner stopped it.

Existing rows get NULL in both: they last until someone stops them, as before. Idempotent: a column is added only when missing.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing

VERSION = 25
DESCRIPTION = "shares: lasts_days and ends_at (a share can end on a date)"

SCHEMA = ""  # alters the table step 24 creates
ATOMIC = True
FOREIGN_KEY_CHECK = True


def migrate(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "shares", "lasts_days", "INTEGER CHECK (lasts_days IS NULL OR lasts_days BETWEEN 1 AND 365)")
    add_column_if_missing(conn, "shares", "ends_at", "TEXT")
