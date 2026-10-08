"""Step 9: a tolerance for "about" targets (v0.3.1; docs/dev/plans/v0.3.1.md item 2).

``user_profiles`` gains ``about_tolerance_pct`` (INTEGER NOT NULL DEFAULT 0): how far above a target whose
minimum equals its maximum (protein "about 56 g", note 05 §4.8) still counts as on target, 0 to 10 %. The
default 0 keeps the behaviour before this step: "Above target" as soon as the number is passed. No guideline
gives a tolerance, so the value is the person's, from their care team (``handbook/REVIEW.md``, "Food targets").

Idempotent: the column is added only when missing; existing rows get the default.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing

VERSION = 9
DESCRIPTION = 'v0.3.1 profile: a tolerance above "about" targets'

SCHEMA = ""
ATOMIC = True


def migrate(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "user_profiles", "about_tolerance_pct", "INTEGER NOT NULL DEFAULT 0")
