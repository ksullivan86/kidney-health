"""Step 14: the Ask microphone's speech-to-text can be agreed to (``docs/dev/plans/assistant-step2.md`` part B).

Step 12 made ``ai_consents.purpose`` ``CHECK (purpose IN ('text','photos','chat'))``. Sending a recording to a
transcription server is a different thing to agree to (the recording, to a different host), so it has its own
purpose, ``voice``. SQLite cannot change a CHECK constraint, so the table is rebuilt, as step 12 did: every column,
the key, the foreign keys and the index stay as they are, the purposes become ``text``, ``photos``, ``chat`` and
``voice``, and every row is copied as it is.

The new table is the stored definition of the old one with ``'voice'`` added to that one list (not a second copy of
the DDL), so a column or constraint that a step between 12 and this one added to ``ai_consents`` is kept. A voice
consent row keeps the transcription *host* in ``host`` and the id of the AI provider that serves the person in
``provider_id`` (the Ask screen needs one); no ``ai_providers`` row is made for the transcription server.

Idempotent: a table whose stored definition already allows ``voice`` is left alone, and a database without the
table gets it created in its final shape.
"""
from __future__ import annotations

import re
import sqlite3

from ..db import execute_script

VERSION = 14
DESCRIPTION = "ai_consents accepts the purpose 'voice' (speech to text for the Ask microphone)"

SCHEMA = ""  # references users and ai_providers, which exist only after steps 3 and 6, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

FINAL_DDL = """
CREATE TABLE ai_consents (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider_id INTEGER NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('text','photos','chat','voice')),
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
    """The stored ``CREATE TABLE`` of ``ai_consents`` named ``ai_consents_new`` with ``'voice'`` in the purpose list."""
    if not _PURPOSE_CHECK.search(stored) or not _TABLE_NAME.match(stored):
        raise RuntimeError("ai_consents has an unexpected definition; schema step 14 cannot add the purpose 'voice'")
    widened = _PURPOSE_CHECK.sub(lambda m: f"{m.group(1)}{m.group(2).rstrip()},'voice'{m.group(3)}", stored, count=1)
    return _TABLE_NAME.sub(lambda m: f"{m.group(1)}ai_consents_new", widened, count=1)


def migrate(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ai_consents'").fetchone()
    if row is None:
        execute_script(conn, FINAL_DDL + INDEX)
        return
    stored = row["sql"] or ""
    if "'voice'" in stored:
        return
    columns = ", ".join(f'"{r["name"]}"' for r in conn.execute("PRAGMA table_info(ai_consents)").fetchall())
    execute_script(conn, "DROP TABLE IF EXISTS ai_consents_new;")
    conn.execute(widened_ddl(stored))
    conn.execute(f"INSERT INTO ai_consents_new ({columns}) SELECT {columns} FROM ai_consents")
    conn.execute("DROP TABLE ai_consents")
    conn.execute("ALTER TABLE ai_consents_new RENAME TO ai_consents")
    execute_script(conn, INDEX)
