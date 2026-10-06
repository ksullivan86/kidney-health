"""Operator CLI ``python -m app.admin`` (note 01 §5.1, note 07 §4.12, §4.15)."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app import admin, audit, credentials, crypto, db
from app.settings_store import create_settings_tables

REPO = Path(__file__).resolve().parent.parent
KEY_OLD = "o" * 40
KEY_NEW = "n" * 40


def make_v3ish_db(data_dir: Path) -> Path:
    """A migrated database plus the schema-v3 tables this platform provides DDL for."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "kidney.db"
    db.init_db(path)
    conn = db.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id INTEGER)")
    create_settings_tables(conn)
    credentials.create_credentials_tables(conn)
    audit.create_audit_table(conn)
    conn.executemany("INSERT INTO users (id, username) VALUES (?, ?)", [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO sessions VALUES ('abc', 1)")
    conn.commit()
    conn.close()
    return path


def run(argv: list[str], env: dict[str, str]) -> tuple[int, str]:
    out = io.StringIO()
    code = admin.main(argv, env=env, out=out)
    return code, out.getvalue()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {"DATA_DIR": str(tmp_path / "data")}


def test_backup_to_file_is_consistent_private_and_never_overwrites(tmp_path, env):
    path = make_v3ish_db(tmp_path / "data")
    dest = tmp_path / "backup.db"
    code, out = run(["backup", str(dest)], env)
    assert code == 0 and "SECRET_KEY is not in it" in out
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    copy = sqlite3.connect(dest)
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    copy.close()
    code, _ = run(["backup", str(dest)], env)
    assert code == 1  # exists
    conn = db.connect(path)
    assert [r["action"] for r in audit.list_events(conn)] == ["backup.created"]
    conn.close()


def test_backup_to_stdout(tmp_path):
    make_v3ish_db(tmp_path / "data")
    proc = subprocess.run(
        [sys.executable, "-m", "app.admin", "backup", "-"],
        cwd=REPO,
        env={**os.environ, "DATA_DIR": str(tmp_path / "data"), "PYTHONPATH": str(REPO)},
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(b"SQLite format 3\x00")
    out = tmp_path / "piped.db"
    out.write_bytes(proc.stdout)
    copy = sqlite3.connect(out)
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    copy.close()


def test_backup_without_database_fails_cleanly(env):
    code, _ = run(["backup", "/tmp/never-written.db"], env)
    assert code == 1
    assert not Path("/tmp/never-written.db").exists()


def test_check_and_restore_check(tmp_path, env):
    code, out = run(["check"], env)
    assert code == 0 and "no database yet" in out and "created on first start" in out
    path = make_v3ish_db(tmp_path / "data")
    code, out = run(["check"], env)
    assert code == 0 and "ok: integrity_check" in out and "schema version 2" in out
    code, out = run(["restore-check", str(path), "--revoke-sessions"], env)
    assert code == 0 and "revoked 1 session" in out
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    conn.close()
    code, out = run(["check"], {**env, "AUTH_MODE": "bogus"})
    assert code == 1


def test_check_reports_unreadable_secrets(tmp_path):
    path = make_v3ish_db(tmp_path / "data")
    conn = db.connect(path)
    credentials.store_secret(conn, crypto.Keyring([KEY_OLD]), "usda", {"api_key": "k" * 24}, owner_user_id=None)
    conn.commit()
    conn.close()
    code, out = run(["check"], {"DATA_DIR": str(tmp_path / "data"), "SECRET_KEY": KEY_NEW})
    assert code == 1 and "cannot be decrypted" in out


def seal_rows(path: Path, ring: crypto.Keyring) -> None:
    conn = db.connect(path)
    credentials.store_secret(conn, ring, "usda", {"api_key": "shared-key-000000000000"}, owner_user_id=None)
    credentials.store_secret(conn, ring, "usda", {"api_key": "own-key-11111111111111"}, owner_user_id=2)
    conn.commit()
    conn.close()


def test_rotate_auto_secret_key(tmp_path, env):
    data = tmp_path / "data"
    path = make_v3ish_db(data)
    key_file = data / "secret.key"
    key_file.write_text(KEY_OLD + "\n")
    key_file.chmod(0o600)
    seal_rows(path, crypto.Keyring([KEY_OLD]))

    code, out = run(["rotate-secret-key"], env)
    assert code == 0, out
    lines = crypto.read_secret_key_file(key_file)
    assert len(lines) == 1 and lines[0] != KEY_OLD
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    new = crypto.Keyring(lines)
    conn = db.connect(path)
    assert credentials.load_secret(conn, new, "usda", owner_user_id=None) == {"api_key": "shared-key-000000000000"}
    assert credentials.load_secret(conn, new, "usda", owner_user_id=2) == {"api_key": "own-key-11111111111111"}
    with pytest.raises(crypto.InvalidToken):
        credentials.load_secret(conn, crypto.Keyring([KEY_OLD]), "usda", owner_user_id=2)
    assert {r[0] for r in conn.execute("SELECT key_id FROM secrets")} == {new.current_id}
    events = audit.list_events(conn)
    assert events[0]["action"] == "secret_key.rotated" and events[0]["details"] == {"reencrypted": 2, "unreadable": 0}
    conn.close()


def test_rotate_refuses_a_mounted_key_and_reencrypt_handles_it(tmp_path):
    data = tmp_path / "data"
    path = make_v3ish_db(data)
    seal_rows(path, crypto.Keyring([KEY_OLD]))
    key_file = tmp_path / "mounted.key"
    key_file.write_text(f"{KEY_NEW}\n{KEY_OLD}\n")
    env = {"DATA_DIR": str(data), "SECRET_KEY_FILE": str(key_file)}
    code, _ = run(["rotate-secret-key"], env)
    assert code == 1
    code, out = run(["reencrypt"], env)
    assert code == 0 and "re-encrypted 2 secret(s)" in out
    conn = db.connect(path)
    only_new = crypto.Keyring([KEY_NEW])
    assert credentials.load_secret(conn, only_new, "usda", owner_user_id=2) == {"api_key": "own-key-11111111111111"}
    conn.close()
    report = crypto.secret_report(db.connect(path), crypto.Keyring([KEY_NEW, KEY_OLD]))
    assert report == {"current": 2, "older_key": 0, "unreadable": 0}


def test_settings_commands(tmp_path, env):
    path = make_v3ish_db(tmp_path / "data")
    code, out = run(["settings", "get", "registration.mode"], env)
    assert code == 0 and json.loads(out) == {"key": "registration.mode", "value": "invite", "source": "default", "locked": False}
    code, out = run(["settings", "set", "registration.mode", "closed"], env)
    assert code == 0 and json.loads(out)["value"] == "closed"
    code, out = run(["settings", "set", "providers.usda.daily_limit_per_user", "25"], env)
    assert code == 0 and json.loads(out)["value"] == 25
    code, out = run(["settings", "set", "registration.mode", "everyone"], env)
    assert code == 1
    code, out = run(["settings", "set", "ui.theme", "dark", "--user", "2"], env)
    assert code == 0 and json.loads(out) == {"key": "ui.theme", "value": "dark", "source": "user"}
    code, out = run(["settings", "list"], env)
    assert code == 0 and "registration.mode = \"closed\"  [instance]" in out
    code, out = run(["settings", "unset", "registration.mode"], env)
    assert code == 0 and json.loads(out)["source"] == "default"
    code, out = run(["settings", "set", "registration.mode", "open"], {**env, "REGISTRATION_MODE": "invite"})
    assert code == 1  # locked by env
    code, _ = run(["settings", "get", "no.such.key"], env)
    assert code == 1
    conn = db.connect(path)
    changed = [e["details"] for e in audit.list_events(conn) if e["action"] == "settings.changed"]
    assert {"key": "registration.mode", "old": "invite", "new": "closed"} in changed
    conn.close()


def test_account_commands_are_stubs_for_now(env):
    code, _ = run(["create-admin"], env)
    assert code == admin.EXIT_USAGE
    code, _ = run(["reset-password", "--user", "2"], env)
    assert code == admin.EXIT_USAGE
