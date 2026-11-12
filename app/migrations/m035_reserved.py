"""Step 35: reserved, does nothing.

Step 35 belongs to the Web Push reminders work (``m035_reminders.py``), built on another branch at the same time as the
clinician notes (step 36). The migration runner needs the steps numbered without gaps, so this branch holds the number with an
empty step. When the two branches are merged, delete this file and keep ``m035_reminders.py``: ``app.migrations.discover``
refuses two steps with the same number, so the merge cannot keep both by mistake.
"""
from __future__ import annotations

import sqlite3

VERSION = 35
DESCRIPTION = "reserved for the reminders step (no change)"

SCHEMA = ""
ATOMIC = True


def migrate(conn: sqlite3.Connection) -> None:
    return None
