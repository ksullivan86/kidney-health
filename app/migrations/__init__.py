"""Schema migrations: one module per step, applied in order by :func:`app.db.migrate`.

Each step is a module named ``mNNN_<topic>.py`` (``NNN`` = its version, contiguous from 001) with:

* ``VERSION: int`` equal to ``NNN``;
* ``DESCRIPTION: str`` (logged when the step runs);
* ``migrate(conn) -> None``: the step itself. It must be **idempotent**: inspect
  ``PRAGMA table_info`` (``app.db.add_column_if_missing``) before ``ALTER TABLE`` and use
  ``IF NOT EXISTS`` for tables, indexes and triggers, so a partly upgraded database (or a re-run)
  never fails;
* optionally ``SCHEMA: str``: idempotent ``CREATE ... IF NOT EXISTS`` statements in their *current*
  shape. :func:`app.db.migrate` runs every step's ``SCHEMA`` (in order) before any step, so a fresh
  database gets whole tables at once. Never put an index or trigger that names a column added by a
  later ``ALTER TABLE`` into ``SCHEMA``: on an old database that column does not exist yet when
  ``SCHEMA`` runs (note 07 §4.4 "ordering gotcha"). Put those in ``migrate()``;
* optionally ``ATOMIC: bool = True``: run the step inside one transaction (``BEGIN IMMEDIATE`` …
  ``COMMIT``, rolled back on error). Inside an atomic step use ``conn.execute`` or
  :func:`app.db.execute_script`; ``conn.executescript`` commits first and ends the transaction;
* optionally ``BACKUP_BEFORE: bool = False``: copy the database to ``<db>.pre-vNNN.bak`` with the
  SQLite backup API before the step runs on an existing database (once; skipped if the file exists);
* optionally ``FOREIGN_KEY_CHECK: bool = False``: after the step, ``PRAGMA foreign_key_check`` must
  return no rows or the step is rolled back.

Steps are append-only: never edit, renumber or delete a released step. The numbering is fixed in
ARCHITECTURE.md ("Database migrations").
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Callable

_STEP_NAME = re.compile(r"^m(\d{3})_[a-z0-9_]+$")


@dataclass(frozen=True)
class Step:
    version: int
    name: str
    description: str
    migrate: Callable[[sqlite3.Connection], None]
    schema: str = ""
    atomic: bool = True
    backup_before: bool = False
    foreign_key_check: bool = False


class MigrationLayoutError(RuntimeError):
    """The migrations package is inconsistent (gap in numbering, missing attribute...)."""


def _step_from_module(module: ModuleType, number: int, name: str) -> Step:
    version = getattr(module, "VERSION", None)
    if version != number:
        raise MigrationLayoutError(f"{name}: VERSION must be {number}, found {version!r}")
    description = getattr(module, "DESCRIPTION", None)
    if not isinstance(description, str) or not description:
        raise MigrationLayoutError(f"{name}: DESCRIPTION must be a non-empty string")
    step = getattr(module, "migrate", None)
    if not callable(step):
        raise MigrationLayoutError(f"{name}: migrate(conn) is missing")
    schema = getattr(module, "SCHEMA", "") or ""
    if not isinstance(schema, str):
        raise MigrationLayoutError(f"{name}: SCHEMA must be a string")
    return Step(
        version=number,
        name=name,
        description=description,
        migrate=step,
        schema=schema,
        atomic=bool(getattr(module, "ATOMIC", True)),
        backup_before=bool(getattr(module, "BACKUP_BEFORE", False)),
        foreign_key_check=bool(getattr(module, "FOREIGN_KEY_CHECK", False)),
    )


def discover(package: str = __name__, path: list[str] | None = None) -> tuple[Step, ...]:
    """Import every ``mNNN_*`` module of ``package`` and return the steps in order.

    Raises :class:`MigrationLayoutError` on a gap, a duplicate number or a malformed module, so a
    missing step can never be skipped silently (a database stamped with a later version would never
    run it).
    """
    search = path if path is not None else list(importlib.import_module(package).__path__)
    found: dict[int, str] = {}
    for info in pkgutil.iter_modules(search):
        match = _STEP_NAME.match(info.name)
        if not match:
            continue
        number = int(match.group(1))
        if number in found:
            raise MigrationLayoutError(f"two migration steps use number {number}: {found[number]} and {info.name}")
        found[number] = info.name
    expected = list(range(1, len(found) + 1))
    if sorted(found) != expected:
        missing = sorted(set(range(1, max(found, default=0) + 1)) - set(found))
        raise MigrationLayoutError(f"migration steps must be numbered 1..N without gaps; missing {missing}")
    steps = []
    for number in expected:
        name = found[number]
        module = importlib.import_module(f"{package}.{name}")
        steps.append(_step_from_module(module, number, name))
    return tuple(steps)


@lru_cache(maxsize=1)
def steps() -> tuple[Step, ...]:
    """The application's migration steps (discovered once per process)."""
    return discover()
