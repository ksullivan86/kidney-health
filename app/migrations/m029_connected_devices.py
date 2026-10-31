"""Step 29: connected devices (design note 27 §3; ARCHITECTURE "Connected devices").

Two new tables, both hanging off ``users`` with ``ON DELETE CASCADE``, so deleting an account deletes them:

* ``device_connections``: one row per person and provider (``withings`` now, ``whoop`` later). ``external_user_id`` is the
  provider's id for the person; one provider account can be connected to one person on this server at a time.
  ``tokens_enc`` holds the access and refresh tokens sealed with the app's keyring (purpose ``device:<provider>``, owner the
  person's id) and ``key_id`` the key line that sealed them; ``access_expires_at`` is UTC. ``status`` is ``active`` or
  ``needs_reconnect``; ``sync_cursor`` is the provider's "changed since" mark; ``last_error`` a short code; ``next_sync_after``
  a pause after the provider said "too many requests".
* ``device_imports``: the import ledger. One row per provider measure the sync has seen, imported or skipped, so a reading the
  person deleted does not come back. ``row_id`` is the ``weights`` or ``blood_pressures`` id it became (NULL when skipped).

Imported rows go into ``weights`` and ``blood_pressures`` with ``source = 'withings'``; those tables have no CHECK on ``source``
(step 18), so nothing there changes.

There is no CHECK on ``provider`` or ``status`` either: a later version may add values. Idempotent: ``IF NOT EXISTS`` everywhere.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 29
DESCRIPTION = "connected devices: device_connections, device_imports"

SCHEMA = ""  # references users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS device_connections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,                      -- withings (whoop later)
  external_user_id TEXT,                       -- the provider's id for the person
  tokens_enc BLOB,                             -- access and refresh tokens, sealed (app.crypto.Keyring)
  key_id TEXT,
  access_expires_at TEXT,                      -- UTC
  scopes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',       -- active | needs_reconnect
  sync_cursor TEXT,                            -- the provider's "changed since" mark
  last_sync_at TEXT,                           -- UTC, the last try
  last_success_at TEXT,                        -- UTC, the last sync that worked
  last_error TEXT,                             -- a short code, NULL after a sync that worked
  next_sync_after TEXT,                        -- UTC, a pause after "too many requests"
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS device_connections_user_provider ON device_connections(user_id, provider);
CREATE UNIQUE INDEX IF NOT EXISTS device_connections_external ON device_connections(provider, external_user_id)
  WHERE external_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS device_imports (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  external_id TEXT NOT NULL,                   -- e.g. "<grpid>:weight"
  kind TEXT NOT NULL,                          -- weight | blood_pressure
  row_id INTEGER,                              -- the weights / blood_pressures id, NULL when skipped
  imported_at TEXT NOT NULL,
  PRIMARY KEY (user_id, provider, external_id)
) WITHOUT ROWID;
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
