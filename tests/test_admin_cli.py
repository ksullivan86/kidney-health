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
from conftest import insert_users

from app import admin, audit, credentials, crypto, db
from app.settings_store import create_settings_tables

REPO = Path(__file__).resolve().parent.parent
KEY_OLD = "o" * 40
KEY_NEW = "n" * 40


def make_v3ish_db(data_dir: Path) -> Path:
    """A migrated (schema v3) database with two accounts and one session."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "kidney.db"
    db.init_db(path)
    conn = db.connect(path)
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO sessions (id, user_id, verifier_hash, created_at, last_seen_at, expires_at)
           VALUES ('abc', 1, x'00', '2026-10-05T00:00:00.000000Z', '2026-10-05T00:00:00.000000Z', '2099-01-01T00:00:00.000000Z')"""
    )
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


def test_backups_are_rollback_journal_files_that_open_read_only_anywhere(tmp_path, env):
    """A WAL-mode file needs a -shm file next to it even to be read, which fails on a read-only mount
    or in a directory UID 10001 cannot write (the documented restore). Backups are written in
    rollback-journal mode, and restore-check opens a read-only file as immutable."""
    live = make_v3ish_db(tmp_path / "data")
    assert live.read_bytes()[18:20] == b"\x02\x02"  # the live database is WAL
    to_file = tmp_path / "file" / "kidney.db"
    to_file.parent.mkdir()
    assert run(["backup", str(to_file)], env)[0] == 0
    proc = subprocess.run(
        [sys.executable, "-m", "app.admin", "backup", "-"],
        cwd=REPO, env={**os.environ, **env, "PYTHONPATH": str(REPO)}, capture_output=True, timeout=60,
    )
    piped = tmp_path / "piped" / "kidney.db"
    piped.parent.mkdir()
    piped.write_bytes(proc.stdout)
    old_style = tmp_path / "old" / "kidney.db"  # a WAL-mode copy, as earlier versions wrote
    old_style.parent.mkdir()
    old_style.write_bytes(live.read_bytes())
    for path in (to_file, piped):
        assert path.read_bytes()[18:20] == b"\x01\x01", path
    for path in (to_file, piped, old_style):
        code, out = run(["restore-check", str(path)], env)
        assert code == 0 and "ok: integrity_check" in out, out
        assert sorted(p.name for p in path.parent.iterdir()) == ["kidney.db"], path  # no -shm/-wal created
    # without the app's secret the key check is skipped, and it says so
    assert "the stored API keys were not checked" in out
    # the restored copy goes back to WAL once the app opens it
    restored = tmp_path / "restored" / "kidney.db"
    restored.parent.mkdir()
    restored.write_bytes(to_file.read_bytes())
    db.init_db(restored)
    assert restored.read_bytes()[18:20] == b"\x02\x02"


def test_backup_without_database_fails_cleanly(env):
    code, _ = run(["backup", "/tmp/never-written.db"], env)
    assert code == 1
    assert not Path("/tmp/never-written.db").exists()


def test_check_and_restore_check(tmp_path, env):
    code, out = run(["check"], env)
    assert code == 0 and "no database yet" in out and "created on first start" in out
    path = make_v3ish_db(tmp_path / "data")
    code, out = run(["check"], env)
    assert code == 0 and "ok: integrity_check" in out and f"schema version {db.SCHEMA_VERSION}" in out  # every step applied
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




# --------------------------------------------------------------------------- #
# Accounts: create-admin, reset-password, list-users, setup-code, revoke-sessions (note 07 §3.8, §4.5)
# --------------------------------------------------------------------------- #

GOOD_PASSWORD = "plum-orbit-candle-73"


def run_with_stdin(argv: list[str], env: dict[str, str], stdin_text: str) -> tuple[int, str]:
    out = io.StringIO()
    code = admin.main(argv, env=env, out=out, stdin=io.StringIO(stdin_text))
    return code, out.getvalue()


def fresh_v3(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "kidney.db"
    db.init_db(path)
    return path


def test_create_admin_claims_user_one_and_checks_the_policy(tmp_path, env, capsys):
    path = fresh_v3(tmp_path / "data")
    code, _ = run_with_stdin(["create-admin", "mum"], env, "short\n")
    assert code == 1 and "at least 15" in capsys.readouterr().err
    code, out = run_with_stdin(["create-admin", "Mum", "--display-name", "Mum"], env, GOOD_PASSWORD + "\n")
    assert code == 0 and "user 1" in out
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT username, username_norm, role, status, password_hash FROM users WHERE id = 1").fetchone()
    assert row[:4] == ("Mum", "mum", "admin", "active") and row[4].startswith("$argon2id$")
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'setup.completed'").fetchone()[0] == 1
    conn.close()
    # a second admin gets a new account; an existing name is refused
    code, out = run_with_stdin(["create-admin", "dad"], env, GOOD_PASSWORD + "x\n")
    assert code == 0 and "user 2" in out
    code, _ = run_with_stdin(["create-admin", "DAD"], env, GOOD_PASSWORD + "\n")
    assert code == 1 and "exists" in capsys.readouterr().err


def test_reset_password_link_and_stdin(tmp_path, env, capsys):
    path = fresh_v3(tmp_path / "data")
    run_with_stdin(["create-admin", "mum"], env, GOOD_PASSWORD + "\n")
    conn = sqlite3.connect(path)
    conn.execute("UPDATE users SET status = 'locked' WHERE id = 1")
    conn.execute(
        "INSERT INTO sessions (id, user_id, verifier_hash, created_at, last_seen_at, expires_at) VALUES ('s1', 1, x'00', 'a', 'a', 'z')"
    )
    conn.commit()
    code, out = run(["reset-password", "mum"], {**env, "PUBLIC_URL": "https://kidney.example.org"})
    assert code == 0 and "https://kidney.example.org/#/reset/" in out
    assert conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE purpose = 'reset' AND user_id = 1").fetchone()[0] == 1
    code, out = run_with_stdin(["reset-password", "mum", "--stdin"], env, "violet-meadow-compass-19\n")
    assert code == 0 and "1 session(s) signed out" in out
    row = conn.execute("SELECT status FROM users WHERE id = 1").fetchone()
    assert row[0] == "active"  # break-glass also unlocks
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    conn.close()
    code, _ = run(["reset-password", "nobody"], env)
    assert code == 1 and "no account" in capsys.readouterr().err


def test_list_users_setup_code_and_revoke_sessions(tmp_path, env, capsys):
    path = fresh_v3(tmp_path / "data")
    code, out = run(["list-users"], env)
    assert code == 0 and "(first-run setup pending)" in out
    code, out = run(["setup-code"], env)
    assert code == 0 and "FIRST-RUN SETUP: open this server's address followed by /#/setup (for example " in out
    code, out = run(["setup-code"], {**env, "PUBLIC_URL": "https://kidney.example.org/"})
    assert code == 0 and "FIRST-RUN SETUP: open https://kidney.example.org/#/setup and enter the code " in out
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE purpose = 'setup'").fetchone()[0] == 1  # the new code replaces the old
    conn.close()
    run_with_stdin(["create-admin", "mum"], env, GOOD_PASSWORD + "\n")
    code, _ = run(["setup-code"], env)
    assert code == 1 and "complete" in capsys.readouterr().err
    code, out = run(["list-users", "--json"], env)
    users = json.loads(out)
    assert users[0]["username"] == "mum" and "password_hash" not in users[0]
    code, out = run(["revoke-sessions", "mum"], env)
    assert code == 0 and "signed out 0" in out
    code, out = run(["revoke-sessions", "--all"], env)
    assert code == 0


def test_account_commands_need_schema_v3(tmp_path, env, capsys):
    from app import migrations

    data = tmp_path / "data"
    data.mkdir()
    conn = db.connect(data / "kidney.db")
    db.migrate(conn, migrations.steps()[:2])
    conn.close()
    code, _ = run(["list-users"], env)
    assert code == 1 and "schema below v3" in capsys.readouterr().err


def test_purge_pre_v3_backup_and_vacuum(tmp_path, env):
    path = fresh_v3(tmp_path / "data")
    backup = Path(f"{path}.pre-v3.bak")
    backup.write_bytes(b"old")
    code, out = run(["purge-pre-v3-backup"], env)
    assert code == 0 and not backup.exists()
    code, out = run(["vacuum"], env)
    assert code == 0 and "vacuumed" in out


# --------------------------------------------------------------------------- #
# export-user and disable-user (note 07 §4.18; v0.3.0 review L14)
# --------------------------------------------------------------------------- #


def _two_people(tmp_path: Path, foods_json: Path) -> None:
    """The admin and sam, each with a log entry, on a real app; the app is closed again before the CLI runs."""
    from conftest import HTTPS_URL, add_user, make_settings, signed_in_client

    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as admin_client:
        food = admin_client.get("/api/foods", params={"limit": 1}).json()["foods"][0]
        sam = add_user(admin_client)
        for client, meal in ((admin_client, "breakfast"), (sam, "dinner")):
            r = client.post("/api/log", json={"date": "2026-10-05", "meal": meal, "food_id": food["id"], "servings": 1})
            assert r.status_code == 201, r.text
        assert sam.put("/api/profile", json={"name": "Sam"}).status_code == 200


def test_export_user_writes_that_persons_export_privately_and_audits_it(tmp_path, env, foods_json, capsysbinary):
    import zipfile

    from app.main import APP_VERSION

    _two_people(tmp_path, foods_json)
    dest = tmp_path / "sam.zip"
    code, out = run(["export-user", "SAM", str(dest)], env)
    assert code == 0 and "written to" in out and "health data" in out
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    with zipfile.ZipFile(dest) as archive:
        assert {"export.json", "log.csv", "foods.csv", "meals.csv", "labs.csv", "README.txt"} <= set(archive.namelist())
        data = json.loads(archive.read("export.json"))
        log_csv = archive.read("log.csv").decode("utf-8")
    assert data["user"]["username"] == "sam" and data["profile"]["name"] == "Sam" and data["app_version"] == APP_VERSION
    assert "dinner" in log_csv and "breakfast" not in log_csv  # only sam's rows
    code, _ = run(["export-user", "sam", str(dest)], env)
    assert code == 1  # never overwrites
    conn = sqlite3.connect(env["DATA_DIR"] + "/kidney.db")
    rows = conn.execute("SELECT actor_user_id, target_id, details_json FROM audit_log WHERE action = 'export.created'").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0][0] is None and json.loads(rows[0][2])["via"] == "cli"
    code, _ = run(["export-user", "nobody", str(tmp_path / "x.zip")], env)
    assert code == 1 and not (tmp_path / "x.zip").exists()
    capsysbinary.readouterr()
    code = admin.main(["export-user", "sam", "-"], env=env)
    captured = capsysbinary.readouterr()
    assert code == 0 and captured.out[:2] == b"PK" and b"written to stdout" in captured.err


def test_disable_user_signs_out_voids_links_audits_and_keeps_the_last_admin(tmp_path, env, foods_json, capsys):
    from datetime import timedelta

    from app.auth import tokens

    _two_people(tmp_path, foods_json)
    path = Path(env["DATA_DIR"]) / "kidney.db"
    conn = sqlite3.connect(path)
    sam_id = conn.execute("SELECT id FROM users WHERE username_norm = 'sam'").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (sam_id,)).fetchone()[0] >= 1
    conn.close()
    assert run(["reset-password", "sam"], env)[0] == 0  # an open reset link for sam
    code, out = run(["disable-user", "sam"], env)
    assert code == 0 and "disabled" in out and "session(s) signed out" in out
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT status FROM users WHERE id = ?", (sam_id,)).fetchone()[0] == "disabled"
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE user_id = ? AND used_at IS NULL", (sam_id,)).fetchone()[0] == 0
    row = conn.execute("SELECT actor_user_id, details_json FROM audit_log WHERE action = 'user.disabled'").fetchone()
    assert row[0] is None and json.loads(row[1])["via"] == "cli"
    conn.close()
    code, out = run(["disable-user", "sam"], env)
    assert code == 0 and "disabled already" in out
    # The only active admin cannot be disabled.
    code, _ = run(["disable-user", "admin"], env)
    assert code == 1 and "only admin" in capsys.readouterr().err
    # With a second admin it can; the invites and links it issued stop working.
    assert run_with_stdin(["create-admin", "dad"], env, GOOD_PASSWORD + "\n")[0] == 0
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    admin_id = conn.execute("SELECT id FROM users WHERE username_norm = 'admin'").fetchone()[0]
    tokens.create_token(conn, tokens.INVITE, ttl=timedelta(days=7), role="user", created_by=admin_id)
    conn.commit()
    conn.close()
    code, out = run(["disable-user", "admin"], env)
    assert code == 0 and "1 invite or reset link(s) they issued voided" in out
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE created_by = ? AND used_at IS NULL", (admin_id,)).fetchone()[0] == 0
    conn.close()
    assert run(["disable-user", "nobody"], env)[0] == 1
