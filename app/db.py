"""SQLite helpers: connection factory, migration runner, per-request dependency.

The schema lives in :mod:`app.migrations`, one module per step (``m001_base``, ``m002_planning``,
...). :func:`migrate` first runs every step's idempotent ``SCHEMA`` (``CREATE ... IF NOT EXISTS``
in the current shape), so a fresh database gets everything in one go, and then applies, in order,
every step newer than ``meta.schema_version``. Because ``CREATE TABLE IF NOT EXISTS`` never adds
columns to an existing table, each step inspects ``PRAGMA table_info`` and issues ``ALTER TABLE ...
ADD COLUMN`` only when the column is missing, so an old ``kidney.db`` upgrades in place on startup.
``meta.schema_version`` records the last step applied. Columns are never dropped or renamed.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, Sequence

from fastapi import Request

if TYPE_CHECKING:  # pragma: no cover
    from .migrations import Step

log = logging.getLogger("kidney_health.db")

SCHEMA_VERSION_KEY = "schema_version"

META_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class MigrationError(RuntimeError):
    """A migration step failed a post-condition; the step was rolled back."""


def utcnow() -> str:
    """ISO-8601 UTC timestamp with microseconds and a ``Z`` suffix.

    Microseconds keep ``created_at`` ordering stable when several entries are
    added within the same second.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with the project's standard pragmas.

    ``check_same_thread=False`` is required because FastAPI may run a sync
    dependency and the endpoint it feeds on different worker threads; each
    connection is still used by exactly one request at a time.
    """
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    # Zero deleted b-tree content when it costs no extra I/O (note 07 §4.14: account deletion).
    conn.execute("PRAGMA secure_delete = FAST")
    return conn


# --------------------------------------------------------------------------- #
# Helpers for migration steps
# --------------------------------------------------------------------------- #


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Column names of ``table`` (empty set when the table does not exist)."""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """``ALTER TABLE table ADD COLUMN column ddl`` unless the column already exists.

    Returns ``True`` when the column was added. ``ddl`` is the type and
    constraints, e.g. ``"TEXT NOT NULL DEFAULT 'eaten'"``; SQLite back-fills
    existing rows with the default.
    """
    if column in table_columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    log.info("migration: added column %s.%s", table, column)
    return True


def split_sql(script: str) -> list[str]:
    """Split a script into single statements (trigger bodies, strings and comments are respected)."""
    statements: list[str] = []
    buf = ""
    for piece in script.split(";"):
        buf += piece + ";"
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            body = "\n".join(line for line in stmt.rstrip(";").splitlines() if not line.strip().startswith("--")).strip()
            if body:
                statements.append(stmt)
            buf = ""
    rest = buf[:-1]
    leftover = "\n".join(line for line in rest.splitlines() if not line.strip().startswith("--")).strip()
    if leftover:
        candidate = rest + "\n;"  # a last statement without a semicolon (possibly followed by a comment)
        if not sqlite3.complete_statement(candidate):
            raise ValueError(f"incomplete SQL statement at the end of the script: {leftover[:60]!r}")
        statements.append(candidate.strip())
    return statements


def execute_script(conn: sqlite3.Connection, script: str) -> None:
    """Like ``conn.executescript`` but statement by statement, so it stays inside the current transaction."""
    for statement in split_sql(script):
        conn.execute(statement)


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #


def _steps() -> tuple["Step", ...]:
    from .migrations import steps

    return steps()


def full_schema(steps: Sequence["Step"] | None = None) -> str:
    """Every step's ``SCHEMA`` in order, then the ``meta`` table: the shape of a fresh database."""
    return "".join(step.schema for step in (steps if steps is not None else _steps())) + META_DDL


def __getattr__(name: str) -> Any:
    # Lazy so that migration modules may import helpers from this module without a cycle.
    if name == "SCHEMA":
        return full_schema()
    if name == "MIGRATIONS":
        migrations: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = tuple(
            (s.version, s.description, s.migrate) for s in _steps()
        )
        return migrations
    if name == "SCHEMA_VERSION":
        return _steps()[-1].version
    if name == "MEAL_TEMPLATES_DDL":
        from .migrations.m002_planning import MEAL_TEMPLATES_DDL

        return MEAL_TEMPLATES_DDL
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Stored ``meta.schema_version`` (0 for a v0.1 database that never recorded one)."""
    if "meta" not in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
        return 0
    value = get_meta(conn, SCHEMA_VERSION_KEY)
    try:
        return int(value) if value is not None else 0
    except ValueError:
        return 0


def database_file(conn: sqlite3.Connection) -> str:
    """Path of the main database file ('' for an in-memory or temporary database)."""
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row[1] == "main":
            return row[2] or ""
    return ""


def backup_to(conn: sqlite3.Connection, dest: Path | str, *, mode: int = 0o600) -> Path:
    """Consistent copy of ``conn``'s database to a new file ``dest`` (created with ``mode``; never overwritten)."""
    dest = Path(dest)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    os.close(fd)
    target = sqlite3.connect(str(dest))
    try:
        conn.backup(target)
    except BaseException:
        target.close()
        dest.unlink(missing_ok=True)
        raise
    target.close()
    return dest


def _backup_before(conn: sqlite3.Connection, version: int) -> Path | None:
    path = database_file(conn)
    if not path:
        return None
    dest = Path(f"{path}.pre-v{version}.bak")
    if dest.exists():
        log.info("migration %d: backup %s already exists, not overwritten", version, dest)
        return None
    if conn.in_transaction:
        conn.commit()
    backup_to(conn, dest)
    log.warning("migration %d: copied the database to %s before upgrading (keep it until the upgrade is confirmed)", version, dest)
    return dest


def _apply_step(conn: sqlite3.Connection, step: "Step") -> None:
    if step.atomic:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
    try:
        step.migrate(conn)
        if step.foreign_key_check:
            problems = conn.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise MigrationError(
                    f"migration {step.version} ({step.name}) left {len(problems)} foreign-key violation(s), e.g. "
                    f"{tuple(problems[0])}; rolled back"
                )
        set_meta(conn, SCHEMA_VERSION_KEY, str(step.version))
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def migrate(conn: sqlite3.Connection, steps: Sequence["Step"] | None = None) -> list[int]:
    """Create missing tables, then apply every migration step newer than the stored version.

    Returns the versions applied (empty when the database was already current).
    """
    steps = tuple(steps) if steps is not None else _steps()
    had_tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0] > 0
    conn.executescript(full_schema(steps))
    current = get_schema_version(conn)
    applied: list[int] = []
    for step in steps:
        if step.version <= current:
            continue
        if step.backup_before and had_tables:
            _backup_before(conn, step.version)
        _apply_step(conn, step)
        applied.append(step.version)
        log.info("migration %d applied: %s", step.version, step.description)
    return applied


def init_db(path: Path | str) -> list[int]:
    """Create the database file, apply the schema and pending migrations (idempotent)."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        return migrate(conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else {k: row[k] for k in row.keys()}


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, closed afterwards."""
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()
