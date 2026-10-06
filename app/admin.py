"""Operator CLI: ``python -m app.admin <command>`` (no shell needed in the container).

Commands:

* ``backup FILE`` / ``backup -``: a consistent SQLite online-backup copy (mode 0600; ``-`` writes
  the database to stdout, e.g. ``kubectl exec deploy/kidney-health -- python -m app.admin backup - >
  kidney.db``). Never overwrites a file. The copy contains every person's health data and the
  encrypted keys but **not** ``SECRET_KEY``; back that up separately.
* ``check``: validate the configuration and the database (integrity, schema version, secret key).
* ``restore-check FILE [--revoke-sessions]``: the same checks against a backup before restoring it.
* ``rotate-secret-key``: for the auto-generated ``$DATA_DIR/secret.key``: add a new key, re-encrypt
  every stored secret, drop the old key. Restart the server afterwards.
* ``reencrypt``: re-encrypt every stored secret under the first ``SECRET_KEY`` line (rotation with a
  mounted ``SECRET_KEY_FILE``: add a new first line, restart, ``reencrypt``, remove the old line,
  restart).
* ``settings list|get|set|unset``: runtime settings (``--user ID`` for a person's own value).
* ``create-admin USERNAME``: the first admin (claims the migrated data of user 1 while setup is
  pending) or another admin; the password is read from stdin (one line) and checked against the
  policy.
* ``reset-password USERNAME``: print a one-time, 24-hour link where the person sets a new password
  (built from ``PUBLIC_URL``; a path otherwise). ``--stdin`` sets the password directly from stdin
  instead (break-glass, also unlocks a locked account). Both sign the person out everywhere.
* ``list-users``: id, username, role, status, sign-in source, last sign-in.
* ``setup-code``: a new first-run setup code (while setup is pending).
* ``revoke-sessions USERNAME`` / ``revoke-sessions --all``: sign out devices.
* ``purge-pre-v3-backup``: delete ``kidney.db.pre-v3.bak`` now (it is deleted automatically 30
  days after the upgrade).
* ``vacuum``: rebuild the database file so deleted data leaves no traces on free pages.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

from .config import ConfigError, Settings, load_settings
from .crypto import Keyring, load_secret_key, new_key_line, read_secret_key_file, reencrypt_all, secret_report

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_USAGE = 2


class CliError(Exception):
    """A user-facing error: printed without a traceback."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def open_existing(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open an existing database without ever creating one."""
    if not path.is_file():
        raise CliError(f"no database at {path}")
    mode = "ro" if readonly else "rw"
    conn = sqlite3.connect(f"file:{path}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    if not readonly:
        conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _db_path(args: argparse.Namespace, settings: Settings) -> Path:
    return Path(args.db) if getattr(args, "db", None) else settings.db_path


def _write_key_file(path: Path, lines: Sequence[str]) -> None:
    """Atomically replace ``path`` with ``lines`` (mode 0600)."""
    fd, tmp = tempfile.mkstemp(prefix=".secret.key.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, ("\n".join(lines) + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _audit(conn: sqlite3.Connection, action: str, **details: Any) -> None:
    from .audit import audit_if_available

    audit_if_available(conn, None, action, **details)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_backup(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from .db import backup_to

    source = open_existing(_db_path(args, settings))
    try:
        if args.file == "-":
            stream = sys.stdout.buffer
            if sys.stdout.isatty():
                raise CliError("refusing to write a database to a terminal; redirect it: backup - > kidney.db")
            memory = sqlite3.connect(":memory:")
            source.backup(memory)
            data = memory.serialize()
            memory.close()
            stream.write(data)
            stream.flush()
            target = "stdout"
        else:
            dest = Path(args.file)
            if dest.exists():
                raise CliError(f"{dest} exists; choose a new file name (backups are never overwritten)")
            backup_to(source, dest)
            target = str(dest)
            print(f"backup written to {dest} (mode 0600). SECRET_KEY is not in it; back that up separately.", file=out)
        try:
            _audit(source, "backup.created", target="stdout" if target == "stdout" else "file")
            source.commit()
        except sqlite3.Error:
            pass
    finally:
        source.close()
    return EXIT_OK


def _check_database(conn: sqlite3.Connection, settings: Settings | None, out: TextIO, *, current_version: int) -> list[str]:
    from .db import get_schema_version, table_exists

    problems: list[str] = []
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        problems.append(f"integrity_check: {result}")
    else:
        print("ok: integrity_check", file=out)
    version = get_schema_version(conn)
    if version > current_version:
        problems.append(f"schema version {version} is newer than this app ({current_version}); upgrade the app first")
    else:
        print(f"ok: schema version {version} (this app: {current_version}{', upgrades on start' if version < current_version else ''})", file=out)
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        problems.append(f"{len(fk)} foreign-key violation(s)")
    for table in ("users", "log_entries", "foods", "meal_templates"):
        if table_exists(conn, table):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"info: {table}: {count} rows", file=out)
    if settings is not None:
        try:
            loaded = _existing_key(settings)
        except ConfigError as exc:
            problems.append(str(exc))
        else:
            if loaded is not None:
                report = secret_report(conn, Keyring(loaded))
                print(
                    f"info: stored secrets readable with the current key: {report['current']}, "
                    f"with an older line: {report['older_key']}, unreadable: {report['unreadable']}",
                    file=out,
                )
                if report["unreadable"]:
                    problems.append(f"{report['unreadable']} stored secret(s) cannot be decrypted with SECRET_KEY")
    return problems


def _existing_key(settings: Settings) -> list[str] | None:
    """SECRET_KEY lines without creating the auto file (None when it does not exist yet)."""
    if settings.secret_key:
        return load_secret_key(settings).lines
    if settings.secret_key_path.exists():
        return read_secret_key_file(settings.secret_key_path)
    return None


def cmd_check(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from .db import _steps

    print("ok: configuration", file=out)
    for warning in settings.warnings:
        print(f"warning: {warning}", file=out)
    from .settings_store import SettingsStore

    locked = SettingsStore(env=args.env).validate_env_locks()
    if locked:
        print(f"info: settings locked by env: {', '.join(locked)}", file=out)
    problems: list[str] = []
    if settings.secret_key:
        print(f"ok: SECRET_KEY from {settings.secret_key_source}", file=out)
    elif settings.secret_key_path.exists():
        print(f"warning: SECRET_KEY lives on the data volume ({settings.secret_key_path}); mount SECRET_KEY_FILE instead", file=out)
    else:
        print(f"info: {settings.secret_key_path} will be created on first start", file=out)
    path = _db_path(args, settings)
    if path.is_file():
        conn = open_existing(path, readonly=True)
        try:
            problems += _check_database(conn, settings, out, current_version=_steps()[-1].version)
        finally:
            conn.close()
    else:
        print(f"info: no database yet at {path}; it is created on first start", file=out)
    for problem in problems:
        print(f"problem: {problem}", file=out)
    return EXIT_PROBLEM if problems else EXIT_OK


def cmd_restore_check(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from .db import _steps, table_exists

    path = Path(args.file)
    conn = open_existing(path, readonly=not args.revoke_sessions)
    try:
        problems = _check_database(conn, settings, out, current_version=_steps()[-1].version)
        if args.revoke_sessions:
            if table_exists(conn, "sessions"):
                removed = conn.execute("DELETE FROM sessions").rowcount
                conn.commit()
                print(f"ok: revoked {removed} session(s) in {path}", file=out)
            else:
                print("info: no sessions table (schema below v3)", file=out)
    finally:
        conn.close()
    for problem in problems:
        print(f"problem: {problem}", file=out)
    return EXIT_PROBLEM if problems else EXIT_OK


def _reencrypt_db(settings: Settings, keyring: Keyring, args: argparse.Namespace, out: TextIO) -> dict[str, int]:
    path = _db_path(args, settings)
    if not path.is_file():
        print(f"info: no database at {path}; nothing to re-encrypt", file=out)
        return {"reencrypted": 0, "unreadable": 0}
    conn = open_existing(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        counts = reencrypt_all(conn, keyring)
        _audit(conn, "secret_key.rotated", reencrypted=counts["reencrypted"], unreadable=counts["unreadable"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return counts


def cmd_reencrypt(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    lines = _existing_key(settings)
    if lines is None:
        raise CliError("no SECRET_KEY yet; nothing to re-encrypt")
    keyring = Keyring(lines)
    counts = _reencrypt_db(settings, keyring, args, out)
    print(
        f"re-encrypted {counts['reencrypted']} secret(s) under key {keyring.current_id}; unreadable: {counts['unreadable']}. "
        "You can now remove the old key line(s) and restart.",
        file=out,
    )
    return EXIT_PROBLEM if counts["unreadable"] else EXIT_OK


def cmd_rotate_secret_key(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    if settings.secret_key:
        raise CliError(
            "SECRET_KEY comes from the environment or SECRET_KEY_FILE, which this command cannot change. Add a new "
            "first line there, restart, run 'python -m app.admin reencrypt', then remove the old line and restart."
        )
    path = settings.secret_key_path
    if not path.exists():
        raise CliError(f"{path} does not exist yet (it is created on first start); nothing to rotate")
    old = read_secret_key_file(path)
    new = new_key_line()
    _write_key_file(path, [new, *old])  # both lines decrypt until the database is re-encrypted
    keyring = Keyring([new, *old])
    counts = _reencrypt_db(settings, keyring, args, out)
    if counts["unreadable"]:
        print(
            f"warning: {counts['unreadable']} secret(s) could not be decrypted with any key line; they stay unreadable",
            file=out,
        )
    _write_key_file(path, [new])
    print(
        f"rotated {path}: new key {keyring.current_id}, {counts['reencrypted']} secret(s) re-encrypted. "
        "Restart the server so it loads the new key, and update your separate copy of the key file.",
        file=out,
    )
    return EXIT_OK


def _parse_value(definition: Any, raw: str) -> Any:
    try:
        return definition.from_env(raw)
    except Exception:
        raise CliError(f"{definition.key}: invalid value") from None


def cmd_settings(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from .settings_store import (
        InvalidSettingValue,
        SettingLocked,
        SettingNotEditable,
        SettingsStore,
        SettingsUnavailable,
    )

    store = SettingsStore(env=args.env)
    path = _db_path(args, settings)
    conn = open_existing(path, readonly=args.action in ("list", "get"))
    try:
        user_id = args.user
        if args.action == "list":
            for d in store.definitions():
                eff = store.effective(conn, d.key, user_id)
                print(f"{d.key} = {json.dumps(d.to_python_json(eff.value))}  [{eff.source}{', locked by ' + eff.env if eff.locked and eff.env else ''}]", file=out)
            return EXIT_OK
        try:
            definition = store.definition(args.key)
        except KeyError as exc:
            raise CliError(str(exc.args[0])) from None
        if args.action == "get":
            eff = store.effective(conn, args.key, user_id)
            print(json.dumps({"key": args.key, "value": definition.to_python_json(eff.value), "source": eff.source, "locked": eff.locked}), file=out)
            return EXIT_OK
        value = None if args.action == "unset" else _parse_value(definition, args.value)
        old = definition.to_python_json(store.effective(conn, args.key, user_id).value)
        try:
            conn.execute("BEGIN IMMEDIATE")
            if user_id is None:
                eff = store.set_instance(conn, args.key, value, updated_by=None)
            else:
                eff = store.set_user(conn, user_id, args.key, value)
            new = definition.to_python_json(eff.value)
            if user_id is None and old != new:
                _audit(conn, "settings.changed", key=args.key, old=old, new=new)
            conn.commit()
        except (SettingLocked, SettingNotEditable, SettingsUnavailable, InvalidSettingValue) as exc:
            conn.rollback()
            raise CliError(str(exc)) from None
        print(json.dumps({"key": args.key, "value": new, "source": eff.source}), file=out)
        return EXIT_OK
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Accounts (note 07 §3.8, §4.5)
# --------------------------------------------------------------------------- #


def _accounts_db(args: argparse.Namespace, settings: Settings, *, readonly: bool = False) -> sqlite3.Connection:
    from .db import table_exists

    conn = open_existing(_db_path(args, settings), readonly=readonly)
    if not table_exists(conn, "users"):
        conn.close()
        raise CliError("this database has no accounts yet (schema below v3); start the server once to upgrade it")
    return conn


def _read_password(stdin: TextIO, prompt: str = "Password: ") -> str:
    if stdin.isatty():
        import getpass

        first = getpass.getpass(prompt)
        if getpass.getpass("Again: ") != first:
            raise CliError("the two passwords differ")
        return first
    line = stdin.readline()
    if not line:
        raise CliError("no password on stdin (pipe it in: printf '%s\\n' \"$PASSWORD\" | python -m app.admin ...)")
    return line.rstrip("\r\n")


def _check_password(conn: sqlite3.Connection, settings: Settings, password: str, username: str, display: str = "") -> None:
    from .auth import policy
    from .settings_store import SettingsStore

    problems = policy.validate_new_password(
        password,
        username=username,
        display_name=display,
        instance_name=str(SettingsStore(env=dict(os.environ)).get(conn, "instance.name")),
        min_length=settings.password_min_length,
    )
    if problems:
        raise CliError(" ".join(problems))


def _hash(settings: Settings, password: str) -> str:
    from .auth import passwords

    passwords.configure(settings.password_hash)
    return passwords.hash_password(password)


def _find_user(conn: sqlite3.Connection, username: str) -> sqlite3.Row:
    from .auth.models import USER_COLUMNS, normalize_username

    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE username_norm = ?", (normalize_username(username),)).fetchone()
    if row is None:
        raise CliError(f"no account named {username!r} (see: python -m app.admin list-users)")
    return row


def _forget_failures(conn: sqlite3.Connection, settings: Settings, username_norm: str) -> None:
    from .auth.throttle import NAME_MAC_INFO

    try:
        lines = _existing_key(settings)
    except ConfigError:
        return
    if lines:
        conn.execute("DELETE FROM login_failures WHERE name_mac = ?", (Keyring(lines).mac(NAME_MAC_INFO, username_norm),))


def cmd_create_admin(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from .audit import audit
    from .auth.accounts import claim_first_admin, create_user
    from .auth.models import USERNAME_HELP, clean_display, normalize_username, setup_required, valid_local_username

    typed = args.username.strip()
    norm = normalize_username(typed)
    if not valid_local_username(norm):
        raise CliError(f"username: {USERNAME_HELP}")
    display = clean_display(args.display_name)
    conn = _accounts_db(args, settings)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username_norm = ?", (norm,)).fetchone() is not None:
            raise CliError(f"{typed!r} exists already; use reset-password to give it a new password")
        password = _read_password(args.stdin)
        _check_password(conn, settings, password, typed, display)
        password_hash = _hash(settings, password)
        conn.execute("BEGIN IMMEDIATE")
        if setup_required(conn):
            user_id = claim_first_admin(conn, username=typed, username_norm=norm, display_name=display, password_hash=password_hash)
            audit(conn, None, "setup.completed", "user", user_id, via="cli")
            conn.execute("DELETE FROM auth_tokens WHERE purpose = 'setup'")
        else:
            user_id = create_user(conn, username=typed, username_norm=norm, display_name=display, role="admin", password_hash=password_hash)
            audit(conn, None, "user.registered", "user", user_id, via="cli", role="admin")
        conn.commit()
    finally:
        conn.close()
    print(f"admin {typed!r} created (user {user_id}). Sign in on the app's page.", file=out)
    return EXIT_OK


def cmd_reset_password(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from datetime import timedelta

    from .audit import audit
    from .auth import sessions, tokens
    from .auth.accounts import set_password
    from .db import utcnow

    conn = _accounts_db(args, settings)
    try:
        row = _find_user(conn, args.username)
        user_id = int(row["id"])
        if row["auth_source"] != "local" and not args.stdin_password:
            raise CliError("this account signs in through the proxy; use --stdin to give it a local break-glass password")
        if args.stdin_password:
            password = _read_password(args.stdin, "New password: ")
            _check_password(conn, settings, password, row["username"], row["display_name"] or "")
            password_hash = _hash(settings, password)
            conn.execute("BEGIN IMMEDIATE")
            set_password(conn, user_id, password_hash)
            conn.execute("UPDATE users SET status = 'active' WHERE id = ? AND status IN ('locked', 'pending_setup')", (user_id,))
            removed = sessions.revoke_user_sessions(conn, user_id)
            _forget_failures(conn, settings, row["username_norm"])
            audit(conn, None, "user.password_changed", "user", user_id, via="cli")
            conn.commit()
            print(f"new password set for {row['username']!r}; {removed} session(s) signed out.", file=out)
            return EXIT_OK
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE auth_tokens SET used_at = ? WHERE purpose = 'reset' AND user_id = ? AND used_at IS NULL",
                     (utcnow(), user_id))
        token, token_row = tokens.create_token(conn, tokens.RESET, ttl=timedelta(hours=24), user_id=user_id)
        _forget_failures(conn, settings, row["username_norm"])
        audit(conn, None, "user.reset_link_issued", "user", user_id, via="cli")
        conn.commit()
    finally:
        conn.close()
    print(f"Reset link for {row['username']!r} (single use, valid until {token_row['expires_at']}):", file=out)
    print(tokens.link(settings.public_origin, "reset", token), file=out)
    if not settings.public_origin:
        print("(PUBLIC_URL is not set: put your server's address in front, e.g. https://kidney.example.org/#/reset/...)", file=out)
    return EXIT_OK


def cmd_list_users(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    conn = _accounts_db(args, settings, readonly=True)
    try:
        rows = conn.execute(
            "SELECT id, username, username_norm, role, status, auth_source, last_login_at FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    if args.json:
        print(json.dumps([{k: r[k] for k in r.keys() if k != "username_norm"} for r in rows]), file=out)
        return EXIT_OK
    print(f"{'id':>4}  {'username':<24} {'role':<6} {'status':<14} {'source':<6} last sign-in", file=out)
    for r in rows:
        name = r["username"] or ("(first-run setup pending)" if r["username_norm"].startswith("#") else "")
        print(f"{r['id']:>4}  {name:<24} {r['role']:<6} {r['status']:<14} {r['auth_source']:<6} {r['last_login_at'] or '-'}", file=out)
    return EXIT_OK


def cmd_setup_code(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from .auth import tokens
    from .auth.models import setup_required

    conn = _accounts_db(args, settings)
    try:
        if not setup_required(conn):
            raise CliError("setup is complete already; sign in, or use reset-password")
        conn.execute("BEGIN IMMEDIATE")
        code, expires = tokens.new_setup_code(conn, settings.setup_code_ttl_minutes)
        conn.commit()
    finally:
        conn.close()
    base = settings.public_origin or "https://<this server>"
    print(f"FIRST-RUN SETUP: open {base}/#/setup and enter the code {code} (valid until {expires})", file=out)
    return EXIT_OK


def cmd_revoke_sessions(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    from .audit import audit

    conn = _accounts_db(args, settings)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if args.all:
            removed = conn.execute("DELETE FROM sessions").rowcount
            audit(conn, None, "sessions.revoked", None, None, via="cli", count=removed, scope="all")
        else:
            if not args.username:
                raise CliError("name an account, or pass --all")
            row = _find_user(conn, args.username)
            removed = conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],)).rowcount
            audit(conn, None, "sessions.revoked", "user", row["id"], via="cli", count=removed)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"signed out {removed} session(s)", file=out)
    return EXIT_OK


def cmd_purge_pre_v3_backup(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    path = Path(f"{_db_path(args, settings)}.pre-v3.bak")
    if not path.exists():
        print(f"info: {path} does not exist", file=out)
        return EXIT_OK
    path.unlink()
    print(f"deleted {path}", file=out)
    return EXIT_OK


def cmd_vacuum(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    conn = open_existing(_db_path(args, settings))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        conn.execute("VACUUM")
    finally:
        conn.close()
    print("database vacuumed: deleted data no longer lingers on free pages", file=out)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description="kidney-health operator commands")
    parser.add_argument("--db", help="database file (default: $DATA_DIR/kidney.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backup", help="consistent copy of the database (FILE, or - for stdout)")
    p.add_argument("file")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("check", help="validate configuration and database")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("restore-check", help="validate a backup before restoring it")
    p.add_argument("file")
    p.add_argument("--revoke-sessions", action="store_true", help="delete all sign-in sessions in FILE")
    p.set_defaults(func=cmd_restore_check)

    p = sub.add_parser("rotate-secret-key", help="new auto-generated SECRET_KEY; re-encrypt stored secrets")
    p.set_defaults(func=cmd_rotate_secret_key)

    p = sub.add_parser("reencrypt", help="re-encrypt stored secrets under the first SECRET_KEY line")
    p.set_defaults(func=cmd_reencrypt)

    p = sub.add_parser("settings", help="read or change runtime settings")
    ssub = p.add_subparsers(dest="action", required=True)
    for action in ("list", "get", "set", "unset"):
        sp = ssub.add_parser(action)
        if action != "list":
            sp.add_argument("key")
        if action == "set":
            sp.add_argument("value", help="text, number, true/false or JSON")
        sp.add_argument("--user", type=int, default=None, help="a person's own value (user id)")
        sp.set_defaults(func=cmd_settings)

    p = sub.add_parser("create-admin", help="create an admin (password on stdin)")
    p.add_argument("username")
    p.add_argument("--display-name", default="")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("reset-password", help="print a one-time reset link (or --stdin: set the password)")
    p.add_argument("username")
    p.add_argument("--stdin", dest="stdin_password", action="store_true", help="read the new password from stdin")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("list-users", help="list accounts")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list_users)

    p = sub.add_parser("setup-code", help="a new first-run setup code")
    p.set_defaults(func=cmd_setup_code)

    p = sub.add_parser("revoke-sessions", help="sign out one account's devices (or --all)")
    p.add_argument("username", nargs="?")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_revoke_sessions)

    p = sub.add_parser("purge-pre-v3-backup", help="delete kidney.db.pre-v3.bak now")
    p.set_defaults(func=cmd_purge_pre_v3_backup)

    p = sub.add_parser("vacuum", help="rebuild the database file (removes traces of deleted data)")
    p.set_defaults(func=cmd_vacuum)
    return parser


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    args.env = os.environ if env is None else env
    args.stdin = stdin or sys.stdin
    if getattr(args, "file", None) == "-":
        out = sys.stderr  # stdout carries the database
    try:
        settings = load_settings(env)
        return int(args.func(args, settings, out))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM
    except sqlite3.Error as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM


if __name__ == "__main__":
    sys.exit(main())
