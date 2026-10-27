"""Step 20: two AI providers can come from the environment (``AI_PROVIDER`` and ``AI_CLOUD_PROVIDER``; ARCHITECTURE "Environment
providers: main and cloud").

Until now one ``ai_providers`` row could be ``locked = 1`` (the provider the environment defines), and step 6's unique index
``ai_providers_one_env`` allowed only one. A second environment provider needs a way to tell the two apart, so:

* ``env_slot TEXT``: ``'main'`` for the row ``AI_PROVIDER`` defines, ``'cloud'`` for the row ``AI_CLOUD_PROVIDER`` defines, NULL for
  every other row. Every row that is locked today becomes ``'main'``. ``locked`` keeps its meaning ("set by the server's
  environment, read-only here"); the slot says which variable set it.
* ``upstream TEXT``: who a proxy forwards to ("Anthropic"), from ``AI_CLOUD_UPSTREAM``. The consent line for a proxy names it. NULL
  for every earlier row and for every provider that is not a proxy to a company. At most 60 characters; the start-up check allows
  only letters, digits, spaces and ``.&-``.
* ``ai_providers_one_env`` is dropped and ``ai_providers_one_per_env_slot`` takes its place: at most one locked row per slot
  (a locked row without a slot counts as ``'main'``, so the old guarantee holds for any row the code might still write that way).

Nothing else changes: the key of an environment provider is still never stored, consents and usage keep their ids. Idempotent: the
columns are added only when missing, the back-fill only touches rows without a slot, and the index uses ``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 20
DESCRIPTION = "ai_providers: env_slot (which environment variable set a locked provider) and upstream (who a proxy forwards to)"

SCHEMA = ""  # alters a table that step 6 creates, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

COLUMNS = {
    "env_slot": "TEXT CHECK (env_slot IS NULL OR env_slot IN ('main','cloud'))",
    "upstream": "TEXT CHECK (upstream IS NULL OR length(upstream) <= 60)",
}

DDL = """
DROP INDEX IF EXISTS ai_providers_one_env;
CREATE UNIQUE INDEX IF NOT EXISTS ai_providers_one_per_env_slot ON ai_providers(COALESCE(env_slot, 'main')) WHERE locked = 1;
"""


def migrate(conn: sqlite3.Connection) -> None:
    for column, ddl in COLUMNS.items():
        add_column_if_missing(conn, "ai_providers", column, ddl)
    conn.execute("UPDATE ai_providers SET env_slot = 'main' WHERE locked = 1 AND env_slot IS NULL")
    execute_script(conn, DDL)
