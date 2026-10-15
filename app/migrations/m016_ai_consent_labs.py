"""Step 16: reading a lab report from a photo can be agreed to (ROADMAP "Lab results from a PDF report", photo version).

Step 14 made ``ai_consents.purpose`` ``CHECK (purpose IN ('text','photos','chat','voice'))``. A photo of a lab report is a
different thing to agree to than a photo of a food label (it can show a name, a date of birth and record numbers, and it
runs only on the local AI), so it has its own purpose, ``labs``. SQLite cannot change a CHECK constraint, so the table is
rebuilt, as steps 12 and 14 did: every column, the key, the foreign keys and the index stay as they are, the purposes
become ``text``, ``photos``, ``chat``, ``voice`` and ``labs``, and every row is copied as it is.

The new table is the stored definition of the old one with ``'labs'`` added to that one list (not a second copy of the
DDL), so a column or constraint that a step between 14 and this one added to ``ai_consents`` is kept.

Idempotent: a table whose stored definition already allows ``labs`` is left alone, and a database without the table gets
it created in its final shape.
"""
from __future__ import annotations

import re
import sqlite3

from ..db import execute_script

VERSION = 16
DESCRIPTION = "ai_consents accepts the purpose 'labs' (a lab report photo read by the local AI)"

SCHEMA = ""  # references users and ai_providers, which exist only after steps 3 and 6, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

FINAL_DDL = """
CREATE TABLE ai_consents (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider_id INTEGER NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('text','photos','chat','voice','labs')),
  host TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  skip_preview INTEGER NOT NULL DEFAULT 0 CHECK (skip_preview IN (0,1)),
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, provider_id, purpose)
) WITHOUT ROWID;
"""

INDEX = "CREATE INDEX IF NOT EXISTS ai_consents_provider ON ai_consents(provider_id);"

_PURPOSE_CHECK = re.compile(r"(CHECK\s*\(\s*purpose\s+IN\s*\()([^)]*)(\)\s*\))", re.IGNORECASE)
_TABLE_NAME = re.compile(r'^(\s*CREATE\s+TABLE\s+)"?ai_consents"?', re.IGNORECASE)


def widened_ddl(stored: str) -> str:
    """The stored ``CREATE TABLE`` of ``ai_consents`` named ``ai_consents_new`` with ``'labs'`` in the purpose list."""
    if not _PURPOSE_CHECK.search(stored) or not _TABLE_NAME.match(stored):
        raise RuntimeError("ai_consents has an unexpected definition; schema step 16 cannot add the purpose 'labs'")
    widened = _PURPOSE_CHECK.sub(lambda m: f"{m.group(1)}{m.group(2).rstrip()},'labs'{m.group(3)}", stored, count=1)
    return _TABLE_NAME.sub(lambda m: f"{m.group(1)}ai_consents_new", widened, count=1)


def migrate(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ai_consents'").fetchone()
    if row is None:
        execute_script(conn, FINAL_DDL + INDEX)
        return
    stored = row["sql"] or ""
    if "'labs'" in stored:
        return
    columns = ", ".join(f'"{r["name"]}"' for r in conn.execute("PRAGMA table_info(ai_consents)").fetchall())
    execute_script(conn, "DROP TABLE IF EXISTS ai_consents_new;")
    conn.execute(widened_ddl(stored))
    conn.execute(f"INSERT INTO ai_consents_new ({columns}) SELECT {columns} FROM ai_consents")
    conn.execute("DROP TABLE ai_consents")
    conn.execute("ALTER TABLE ai_consents_new RENAME TO ai_consents")
    execute_script(conn, INDEX)
