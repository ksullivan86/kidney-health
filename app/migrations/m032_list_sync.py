"""Step 32: your own list app (design note 30 §4; ARCHITECTURE "Your own list app").

One new table, hanging off ``users`` with ``ON DELETE CASCADE``, so deleting an account deletes it:

* ``list_sync``: at most one row per person: which list app (``grocy``, ``kitchenowl`` or ``mealie``), its address, the list the
  person chose (its id in that app, and its name to show), and the person's key for it. ``key_enc`` is the key sealed with the
  app's keyring (purpose ``list-sync``, owner the person's id) and ``key_id`` the key line that sealed it. ``last_test_error`` is a
  short code (NULL after a test that worked); ``last_sent_at`` and ``last_sent_count`` describe the last send.

No CHECK on ``app``: a later version may add list apps. Recipe import needs no table (a recipe is a saved meal). Idempotent:
``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 32
DESCRIPTION = "your own list app: list_sync"

SCHEMA = ""  # references users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS list_sync (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  app TEXT NOT NULL,                           -- grocy | kitchenowl | mealie
  base_url TEXT NOT NULL,                      -- http(s)://host[:port][/path], no trailing slash
  list_id TEXT,                                -- the chosen list's id in that app
  list_name TEXT,
  key_enc BLOB,                                -- the person's key, sealed (app.crypto.Keyring)
  key_id TEXT,
  last_test_at TEXT,                           -- UTC
  last_test_error TEXT,                        -- a short code, NULL after a test that worked
  last_sent_at TEXT,                           -- UTC
  last_sent_count INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
