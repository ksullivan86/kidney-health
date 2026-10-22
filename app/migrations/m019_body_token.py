"""Step 19: which device token sent a weight or a reading (design note 12 §4.3; ARCHITECTURE "Device tokens and /push/v1").

``weights`` and ``blood_pressures`` each gain ``api_token_id INTEGER REFERENCES api_tokens(id) ON DELETE SET NULL``: the id of
the device token (``khd_``, scope ``body:write``) whose request added the row, NULL for every other row (typed, Apple Health
import, file import) and, by the cascade, once the token has been purged 30 days after it ended. So:

* the weight and blood pressure screens can say "from a shortcut (Morning weight)" (``via`` in ``GET /api/body/*`` is the
  token's name);
* the person can delete everything one token sent in one step (``DELETE /api/me/tokens/{id}/body-rows``), which finds the rows by
  this column and the person's id;
* the rows themselves outlive the token: purging an ended token sets the column to NULL and keeps the row (it stays marked
  ``source = 'shortcut'``, without the token's name). Deleting the account deletes both the rows and the tokens (``ON DELETE
  CASCADE`` on ``user_id``).

Two partial indexes, ``(user_id, api_token_id) WHERE api_token_id IS NOT NULL``, make "what did this token send" and the cascade's
``SET NULL`` cheap without costing anything for the rows a person typed. **No** ``(user_id, date, time)`` index: the "same reading"
check (note 12 §4.3) looks rows up by person and date, which step 18's ``(user_id, date)`` index already serves (a person holds at most
20 weights and 30 readings per date, so the scan after the index is at most 30 rows).

SQLite allows ``ADD COLUMN`` with a ``REFERENCES`` clause when the default is NULL, with foreign keys on. Idempotent: the column is
added only when missing and the indexes use ``IF NOT EXISTS``. Nothing else changes; ``source`` still has no ``CHECK``, so the new
value ``'shortcut'`` needs no table rebuild.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 19
DESCRIPTION = "weights and blood_pressures: api_token_id (the device token that sent a row)"

SCHEMA = ""  # alters tables that step 18 creates, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

COLUMN = "INTEGER REFERENCES api_tokens(id) ON DELETE SET NULL"

DDL = """
CREATE INDEX IF NOT EXISTS weights_user_token ON weights(user_id, api_token_id) WHERE api_token_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS blood_pressures_user_token ON blood_pressures(user_id, api_token_id) WHERE api_token_id IS NOT NULL;
"""


def migrate(conn: sqlite3.Connection) -> None:
    for table in ("weights", "blood_pressures"):
        add_column_if_missing(conn, table, "api_token_id", COLUMN)
    execute_script(conn, DDL)
