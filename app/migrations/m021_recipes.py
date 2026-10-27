"""Step 21: a saved meal can be a recipe (note 16 §5.1).

``meal_templates`` gains three nullable columns:

* ``servings_made REAL``: how many servings the items make, greater than 0 and at most 100. NULL is a plain saved meal, whose items
  are one serving, as before.
* ``steps_json TEXT``: a JSON list of cooking steps (strings), or NULL.
* ``source_url TEXT``: an http or https link, kept as text and never opened, or NULL.

Back-fill: until now ``save_recipe`` (Ask and MCP) kept the count and the link in the note, as the exact sentence
``Makes N serving(s).`` with or without `` Source: <link>``. A row whose note is exactly that sentence gets ``servings_made`` and
``source_url``. The note itself is left alone; the screen hides a note equal to the sentence. Any other note leaves the columns NULL,
because text a person typed cannot be divided safely. Idempotent: the columns are added only when missing, and the back-fill only
touches rows whose ``servings_made`` is still NULL.
"""
from __future__ import annotations

import re
import sqlite3

from ..db import add_column_if_missing

VERSION = 21
DESCRIPTION = "meal_templates: servings_made, steps_json and source_url (recipes), back-filled from the note save_recipe wrote"

SCHEMA = ""  # alters a table that step 2 creates, so everything runs below
ATOMIC = True

MAX_SERVINGS_MADE = 100
MAX_SOURCE_URL = 900

COLUMNS = {
    "servings_made": f"REAL CHECK (servings_made IS NULL OR (servings_made > 0 AND servings_made <= {MAX_SERVINGS_MADE}))",
    "steps_json": "TEXT",
    "source_url": f"TEXT CHECK (source_url IS NULL OR length(source_url) <= {MAX_SOURCE_URL})",
}

# The sentence app.mcp.tools.recipe_note wrote before this step, and nothing else.
NOTE_PATTERN = re.compile(r"Makes (\d+(?:\.\d+)?) servings?\.(?: Source: (https?://\S+))?")


def recipe_sentence(servings: float, source_url: str | None) -> str:
    """The note ``save_recipe`` wrote before step 21 (a copy, so this step never changes when that code does)."""
    note = f"Makes {servings:g} serving{'' if servings == 1 else 's'}."
    return f"{note} Source: {source_url}" if source_url else note


def parse_recipe_note(note: str | None) -> tuple[float, str | None] | None:
    """``(servings_made, source_url)`` for a note that is exactly the old sentence, else ``None``."""
    match = NOTE_PATTERN.fullmatch(note or "")
    if match is None:
        return None
    servings = float(match.group(1))
    url = match.group(2)
    if not 0 < servings <= MAX_SERVINGS_MADE or (url is not None and len(url) > MAX_SOURCE_URL):
        return None
    if recipe_sentence(servings, url) != note:  # "Makes 1 servings." or "Makes 4.0 servings." was typed, not written
        return None
    return servings, url


def migrate(conn: sqlite3.Connection) -> None:
    for column, ddl in COLUMNS.items():
        add_column_if_missing(conn, "meal_templates", column, ddl)
    rows = conn.execute("SELECT id, note FROM meal_templates WHERE servings_made IS NULL AND note LIKE 'Makes %'").fetchall()
    for row in rows:
        parsed = parse_recipe_note(row["note"])
        if parsed is not None:
            conn.execute("UPDATE meal_templates SET servings_made = ?, source_url = ? WHERE id = ?", (parsed[0], parsed[1], row["id"]))
