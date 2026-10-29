"""Step 26: receipt keys prevent an acknowledged-late POST from writing twice.

The first response is retained for a day; its key/hash stays until account deletion so an old
key never runs again after the response expires. All fields belong to the signed-in user.
"""
from __future__ import annotations

import sqlite3

VERSION = 26
DESCRIPTION = "per-user receipts for retry-safe manual health and plan writes"
ATOMIC = True
FOREIGN_KEY_CHECK = True
SCHEMA = """
CREATE TABLE IF NOT EXISTS write_receipts (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, operation, request_key),
    CHECK (length(request_key) BETWEEN 8 AND 128),
    CHECK (length(body_hash) = 64)
);
CREATE INDEX IF NOT EXISTS write_receipts_response_age
    ON write_receipts(user_id, created_at) WHERE response_json IS NOT NULL;
"""


def migrate(conn: sqlite3.Connection) -> None:
    # SCHEMA creates the complete table for both new and upgraded databases.
    pass
