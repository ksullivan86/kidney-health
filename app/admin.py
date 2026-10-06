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
* ``create-admin``, ``reset-password``: provided by the accounts module (schema v3).
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


def cmd_todo(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    # TODO(accounts, schema v3): implemented by the accounts builder in app/auth (note 07 §3.8, §4.5):
    #   create-admin   read a password from stdin, apply the NIST policy, create or update user 1
    #   reset-password print a one-time reset link for --user (built from PUBLIC_URL)
    print(f"'{args.command}' is not available yet: it arrives with accounts (schema v3).", file=sys.stderr)
    return EXIT_USAGE


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

    for name in ("create-admin", "reset-password"):
        p = sub.add_parser(name, help="arrives with accounts (schema v3)")
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=cmd_todo)
    return parser


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    if unknown and getattr(args, "func", None) is not cmd_todo:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    args.env = os.environ if env is None else env
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
