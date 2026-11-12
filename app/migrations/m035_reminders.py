"""Step 35: reminders by phone notification (design note 35).

Two new tables, both hanging off ``users`` with ``ON DELETE CASCADE``, so deleting an account deletes them:

* ``push_subscriptions``: one row per device a person turned notifications on for. ``endpoint`` is the push service's address
  for that browser (unique: one browser profile has one subscription for this site), ``p256dh`` and ``auth`` are the browser's
  public key and auth secret (base64url) used to encrypt each message. ``user_agent`` is the browser's User-Agent, cut short, to
  name the device in the list. ``last_ok_at`` and ``last_error`` (a short code) describe the last send.
* ``reminders``: what to send and when. ``kind`` is ``log_meal`` (with ``meal``), ``plan_tomorrow`` or ``weigh_in``.
  ``time_local`` is ``HH:MM`` in ``time_zone`` (an IANA name from the browser; empty means the server's own time). ``days`` is a
  bitmask, bit 0 Monday to bit 6 Sunday. ``last_sent_on`` is the local date it last went out, so it goes out at most once a day.

Nothing about lows, insulin, medicines or glucose: the kinds are fixed by a CHECK. Idempotent: ``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 35
DESCRIPTION = "reminders by phone notification: push_subscriptions, reminders"

SCHEMA = ""  # references users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE,               -- https on a known push service (app/webpush.py)
  p256dh TEXT NOT NULL,                        -- the browser's public key, base64url
  auth TEXT NOT NULL,                          -- the browser's auth secret, base64url
  user_agent TEXT,                             -- to name the device ("Safari on iPhone")
  created_at TEXT NOT NULL,
  last_ok_at TEXT,                             -- UTC
  last_error TEXT                              -- a short code, NULL after a send that worked
);
CREATE INDEX IF NOT EXISTS push_subscriptions_user ON push_subscriptions(user_id);
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('log_meal', 'plan_tomorrow', 'weigh_in')),
  meal TEXT CHECK (meal IS NULL OR meal IN ('breakfast', 'lunch', 'dinner', 'snack')),
  time_local TEXT NOT NULL,                    -- HH:MM
  days INTEGER NOT NULL DEFAULT 127 CHECK (days BETWEEN 1 AND 127),
  time_zone TEXT NOT NULL DEFAULT '',          -- IANA name; '' = the server's own time
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_sent_on TEXT                            -- YYYY-MM-DD in time_zone
);
CREATE INDEX IF NOT EXISTS reminders_user ON reminders(user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
