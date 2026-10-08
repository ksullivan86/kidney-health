"""Step 8: "Not chosen yet" for the kidney stage and the diabetes type (v0.3.1; ROADMAP, Accounts).

``user_profiles`` gains ``ckd_stage_set_at`` and ``diabetes_set_at`` (TEXT, UTC timestamps; NULL means
"not chosen yet"). A profile save that sends a stage (or a diabetes type) records the time. A new
account's profile row starts with both NULL, so the Profile form shows "Not chosen yet" until the person
picks. Meanwhile the stored schema defaults (stage 3b, type 1 diabetes) keep driving targets and
guidance, so nothing safety-related (such as the Treating a low card) disappears before they choose.

Rows that exist when this step runs are marked as chosen at their ``updated_at``: their values were
saved by the person, or accepted by them, before this release, and showing them as unchosen now would
only confuse. On a fresh database there are no rows yet.

Idempotent: the columns are added only when missing, and the back-fill runs only in the same run that
added them (the step is atomic, so a failed run leaves neither).
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing

VERSION = 8
DESCRIPTION = 'v0.3.1 profile: "Not chosen yet" for the kidney stage and the diabetes type'

SCHEMA = ""
ATOMIC = True

COLUMNS: tuple[str, ...] = ("ckd_stage_set_at", "diabetes_set_at")


def migrate(conn: sqlite3.Connection) -> None:
    for column in COLUMNS:
        if add_column_if_missing(conn, "user_profiles", column, "TEXT"):
            conn.execute(f"UPDATE user_profiles SET {column} = updated_at WHERE {column} IS NULL")
