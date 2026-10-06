"""Append-only audit log (note 07 §4.13)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import audit, db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.migrate(c)
    audit.create_audit_table(c)
    yield c
    c.close()


def test_audit_rows_and_listing(conn):
    first = audit.audit(conn, 1, "user.invited", "invite", "abc", ip="192.168.1.77", role="user")
    second = audit.audit(conn, None, "backup.created", target="file")
    third = audit.audit(conn, 2, "login.succeeded", "user", 2, ip="2001:db8:1234:5678::1")
    conn.commit()
    assert first < second < third
    rows = audit.list_events(conn)
    assert [r["id"] for r in rows] == [third, second, first]
    assert rows[2]["ip_prefix"] == "192.168.1.0/24" and rows[2]["details"] == {"role": "user"}
    assert rows[0]["ip_prefix"] == "2001:db8:1234::/48" and rows[0]["target_id"] == "2"
    assert [r["id"] for r in audit.list_events(conn, before=third, limit=1)] == [second]
    mine = audit.list_events(conn, actor_user_id=2, actions=audit.USER_VISIBLE_ACTIONS)
    assert [r["action"] for r in mine] == ["login.succeeded"]
    assert audit.list_events(conn, actions=[]) == []


def test_audit_log_is_append_only(conn):
    row_id = audit.audit(conn, 1, "settings.changed", key="instance.name", old="A", new="B")
    conn.commit()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE audit_log SET action = 'x' WHERE id = ?", (row_id,))


@pytest.mark.parametrize("key", ["password", "new_password", "api_key", "apikey", "token", "last4", "secret", "code", "setup_code"])
def test_details_must_not_carry_secrets(conn, key):
    with pytest.raises(ValueError, match="must not carry secrets"):
        audit.audit(conn, 1, "secret.set", **{key: "x"})


def test_harmless_detail_names_are_fine(conn):
    audit.audit(conn, 1, "secret.set", provider="usda", scope="shared", status_code=200)


def test_unknown_actions_must_be_registered(conn):
    with pytest.raises(ValueError, match="unknown audit action"):
        audit.audit(conn, 1, "made.up")
    audit.register_action("guidance.reviewed")
    audit.audit(conn, 1, "guidance.reviewed")
    with pytest.raises(ValueError):
        audit.register_action("Bad Name")


def test_retention(conn):
    audit.audit(conn, 1, "login.failed")
    old = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute("INSERT INTO audit_log (at, action) VALUES (?, 'login.failed')", (old,))
    assert audit.purge_expired(conn, 365) == 1
    assert len(audit.list_events(conn)) == 1


def test_ip_prefix():
    assert audit.ip_prefix("10.1.2.3") == "10.1.2.0/24"
    assert audit.ip_prefix("::ffff:10.1.2.3") == "10.1.2.0/24"
    assert audit.ip_prefix("testclient") is None and audit.ip_prefix(None) is None


def test_audit_if_available_skips_old_databases():
    from app import migrations

    c = db.connect(":memory:")
    db.migrate(c, migrations.steps()[:2])  # schema v2: no audit table
    assert audit.audit_if_available(c, None, "backup.created") is None
    c.close()


def test_startup_purges_expired_rows(settings):
    from app.main import create_app

    from conftest import TestClient

    settings.ensure_data_dir()
    db.init_db(settings.db_path)
    c = db.connect(settings.db_path)
    audit.create_audit_table(c)
    c.execute("INSERT INTO audit_log (at, action) VALUES ('2000-01-01T00:00:00.000000Z', 'login.failed')")
    c.commit()
    c.close()
    with TestClient(create_app(settings)):
        pass
    c = db.connect(settings.db_path)
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE at < '2001'").fetchone()[0] == 0
    c.close()
