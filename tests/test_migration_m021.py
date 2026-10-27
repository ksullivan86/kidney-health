"""Schema step 21 (``app/migrations/m021_recipes.py``): ``meal_templates`` gains ``servings_made``, ``steps_json`` and ``source_url``
(note 16 §5.1).

On a populated schema-v20 database every saved meal stays. Only a note that is exactly the sentence ``save_recipe`` wrote
(``Makes N serving(s).`` with or without `` Source: <link>``) fills the new columns; any other note leaves them NULL, and no note is
changed. A re-run changes nothing. The "before" database is built from ``steps()[:20]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m021_recipes as m021
from conftest import insert_users

NOW = "2026-10-27T08:00:00.000000Z"
ITEMS = '[{"food_id": 1, "servings": 4}]'

NOTES = {
    "pot": ("Makes 4 servings.", 4.0, None),
    "one": ("Makes 1 serving.", 1.0, None),
    "half": ("Makes 2.5 servings.", 2.5, None),
    "linked": ("Makes 4 servings. Source: https://example.com/r?id=7", 4.0, "https://example.com/r?id=7"),
    "typed": ("Makes 4 servings, freezes well.", None, None),
    "plural": ("Makes 1 servings.", None, None),
    "padded": ("Makes 4.0 servings.", None, None),
    "huge": ("Makes 500 servings.", None, None),
    "ftp": ("Makes 4 servings. Source: ftp://example.com/r", None, None),
    "plain": (None, None, None),
}


def build_v20_with_meals(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:20]) == list(range(1, 21))
    insert_users(conn, [(1, "admin")])
    for name, (note, _, _) in NOTES.items():
        conn.execute("INSERT INTO meal_templates (user_id, name, note, items_json, created_at, updated_at) VALUES (1, ?, ?, ?, ?, ?)",
                     (name, note, ITEMS, NOW, NOW))
    conn.commit()
    assert not {"servings_made", "steps_json", "source_url"} & db.table_columns(conn, "meal_templates")
    conn.close()


def test_step_21_follows_step_20():
    steps = migrations.steps()
    assert [s.version for s in steps][:21] == list(range(1, 22))
    step = steps[20]
    assert step.name == "m021_recipes" and step.atomic and step.schema == ""


def test_only_the_exact_sentence_is_back_filled_and_no_note_changes(tmp_path):
    path = tmp_path / "kidney.db"
    build_v20_with_meals(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 21 and applied == list(range(21, db.SCHEMA_VERSION + 1))
    rows = {r["name"]: r for r in conn.execute("SELECT * FROM meal_templates")}
    assert set(rows) == set(NOTES)
    for name, (note, servings, url) in NOTES.items():
        row = rows[name]
        assert row["note"] == note, name  # the note is left alone
        assert (row["servings_made"], row["source_url"], row["steps_json"]) == (servings, url, None), name
        assert row["items_json"] == ITEMS
    m021.migrate(conn)  # a re-run changes nothing
    conn.commit()
    assert db.migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM meal_templates WHERE servings_made IS NOT NULL").fetchone()[0] == 4
    conn.close()


def test_the_columns_refuse_what_the_api_refuses(tmp_path):
    path = tmp_path / "kidney.db"
    db.init_db(path)
    conn = db.connect(path)
    insert_users(conn, [(1, "admin")])
    conn.execute("INSERT INTO meal_templates (user_id, name, items_json, servings_made, created_at, updated_at) "
                 "VALUES (1, 'ok', ?, 100, ?, ?)", (ITEMS, NOW, NOW))
    for column, value in (("servings_made", 0), ("servings_made", 100.5), ("source_url", "h" * 901)):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE meal_templates SET {column} = ?", (value,))
    conn.close()


def test_parse_matches_what_save_recipe_wrote():
    for servings, url in ((4, None), (1, None), (2.5, "https://example.com/a"), (100, None), (0.5, None)):
        assert m021.parse_recipe_note(m021.recipe_sentence(servings, url)) == (servings, url)
    for note in (None, "", "makes 4 servings.", "Makes 4 servings. Source: https://a.example/b c", "Makes 0 servings."):
        assert m021.parse_recipe_note(note) is None
