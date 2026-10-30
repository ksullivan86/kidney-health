"""Schema step 26 (``app/migrations/m026_oidc.py``): ``oidc_links`` and ``sessions.signed_in_with`` (design note 24 §6).

A schema-v25 database with sessions upgrades with every session kept and ``signed_in_with`` NULL, a re-run changes nothing, one
provider account links to one account, a person links one account per provider, and links go with the account."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from conftest import insert_users


def test_step_26_follows_step_25():
    step = migrations.steps()[25]
    assert step.version == 26 and step.name == "m026_oidc" and step.atomic and step.foreign_key_check


def test_a_v25_database_keeps_its_sessions_and_gains_the_links_table(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    db.migrate(conn, migrations.steps()[:25])
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO sessions (id, user_id, verifier_hash, created_at, last_seen_at, expires_at) "
                 "VALUES ('a' || hex(randomblob(15)), 2, x'00', 'now', 'now', 'later')")
    conn.commit()
    conn.close()

    conn = db.connect(path)
    assert db.migrate(conn)[0] == 26
    assert [tuple(r) for r in conn.execute("SELECT user_id, signed_in_with FROM sessions")] == [(2, None)]
    assert db.migrate(conn) == []
    conn.execute("INSERT INTO oidc_links (user_id, issuer, subject, created_at) VALUES (2, 'https://idp/', 's1', 'now')")
    with pytest.raises(sqlite3.IntegrityError):  # one provider account, one account here
        conn.execute("INSERT INTO oidc_links (user_id, issuer, subject, created_at) VALUES (1, 'https://idp/', 's1', 'now')")
    with pytest.raises(sqlite3.IntegrityError):  # one link per person per provider
        conn.execute("INSERT INTO oidc_links (user_id, issuer, subject, created_at) VALUES (2, 'https://idp/', 's2', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE sessions SET signed_in_with = 'password'")
    conn.execute("UPDATE sessions SET signed_in_with = 'oidc'")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM oidc_links").fetchone()[0] == 0
    conn.close()
