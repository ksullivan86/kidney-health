"""Step 12: the in-app Ask chat can be agreed to (``docs/dev/plans/assistant-step2.md``; ARCHITECTURE "Ask chat").

Step 6 made ``ai_consents.purpose`` ``CHECK (purpose IN ('text','photos'))``. The chat has its own consent
purpose, ``chat`` (what the person agrees to send is different: their messages in the conversation and the
app's own numbers the assistant looks up), and SQLite cannot change a CHECK constraint, so the table is
rebuilt: the same columns, the same key, the same index, the purposes ``text``, ``photos`` and ``chat``.
Every row is copied as it is.

Nothing references ``ai_consents`` (it references ``users`` and ``ai_providers``), so the rebuild touches no
other table. Idempotent: a table whose stored definition already allows ``chat`` is left alone, and a
database without the table gets it created in its final shape (it cannot happen after step 6, but the step
does not depend on that).
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 12
DESCRIPTION = "ai_consents accepts the purpose 'chat' (the in-app Ask chat)"

SCHEMA = ""  # references users and ai_providers, which exist only after steps 3 and 6, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

COLUMNS = "user_id, provider_id, purpose, host, policy_version, skip_preview, created_at"


def table_ddl(name: str) -> str:
    return f"""
CREATE TABLE {name} (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider_id INTEGER NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('text','photos','chat')),
  host TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  skip_preview INTEGER NOT NULL DEFAULT 0 CHECK (skip_preview IN (0,1)),
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, provider_id, purpose)
) WITHOUT ROWID;
"""


INDEX = "CREATE INDEX IF NOT EXISTS ai_consents_provider ON ai_consents(provider_id);"


def migrate(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ai_consents'").fetchone()
    if row is None:
        execute_script(conn, table_ddl("ai_consents") + INDEX)
        return
    if "'chat'" in (row["sql"] or ""):
        return
    execute_script(conn, "DROP TABLE IF EXISTS ai_consents_new;" + table_ddl("ai_consents_new"))
    conn.execute(f"INSERT INTO ai_consents_new ({COLUMNS}) SELECT {COLUMNS} FROM ai_consents")
    conn.execute("DROP TABLE ai_consents")
    conn.execute("ALTER TABLE ai_consents_new RENAME TO ai_consents")
    execute_script(conn, INDEX)
