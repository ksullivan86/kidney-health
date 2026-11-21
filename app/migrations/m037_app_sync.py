"""Step 37: what the iPhone app sent to this server (design note 38 §5.5, step 4; ARCHITECTURE "Device tokens and /push/v1").

One new table, ``app_sync_rows``: one row (a receipt) for each row the iPhone app sent with an app token (scope ``app:add``) to
``POST /push/v1/sync`` (:mod:`app.app_sync`) and that the server either added or found already here.

* ``kind`` is ``food``, ``entry``, ``lab``, ``symptom``, ``weight`` or ``reading``; ``client_id`` is the UUID the phone made for
  the row, stored lower-case. ``(user_id, kind, client_id)`` is unique: sending the same row again adds nothing, even after the
  row was deleted here, and a food the phone made is found again by its ``client_id``.
* ``row_id`` is the id of the row in its own table (``foods``, ``log_entries``, ``lab_results``, ``symptoms``, ``weights``,
  ``blood_pressures``). It has no foreign key because it points at one of six tables. Each of them uses ``AUTOINCREMENT``,
  so a deleted row's id is never given to another row, and a receipt can never point at a row the app did not send.
* ``added`` is 1 when this request added the row and 0 when it found the row already here (a food the person already had, a
  weight with the same Health key). "Delete what it sent" removes only rows with ``added = 1``.
* ``api_token_id`` is the token that sent it, ``ON DELETE SET NULL``: purging a token 30 days after it ended keeps the
  receipts (so a late resend still adds nothing) and the rows. Deleting the account deletes the receipts (``ON DELETE CASCADE``).

Receipts are server-local, like ``api_tokens``: they are not in the export.

The step does not touch any earlier table. Idempotent: everything is ``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 37
DESCRIPTION = "app_sync_rows: what the iPhone app sent with an app token"

SCHEMA = ""  # references api_tokens (step 10) and users (step 3), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS app_sync_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  api_token_id INTEGER REFERENCES api_tokens(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK (kind IN ('food', 'entry', 'lab', 'symptom', 'weight', 'reading')),
  client_id TEXT NOT NULL CHECK (length(client_id) = 36),
  row_id INTEGER NOT NULL,
  added INTEGER NOT NULL CHECK (added IN (0, 1)),
  created_at TEXT NOT NULL,
  UNIQUE (user_id, kind, client_id)
);
CREATE INDEX IF NOT EXISTS app_sync_rows_token ON app_sync_rows(api_token_id, created_at) WHERE api_token_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS app_sync_rows_row ON app_sync_rows(user_id, kind, row_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
