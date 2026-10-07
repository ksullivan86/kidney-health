"""Step 3: v0.3 accounts, per-user data, settings, secrets, audit (note 07 §4.4 + §9 security review).

Everything happens inside :func:`migrate` (``SCHEMA`` is empty), so on an existing database the
automatic ``kidney.db.pre-v3.bak`` copy (``BACKUP_BEFORE``) is taken *before* any v3 table exists,
and a fresh database runs exactly the same statements as an upgraded one: the two paths never
diverge. The step runs in one transaction (``ATOMIC``) and must leave ``PRAGMA foreign_key_check``
empty (``FOREIGN_KEY_CHECK``), otherwise it is rolled back.

What it does, in order:

1. Creates the identity tables (``users``, ``sessions`` with hashed verifiers, ``auth_tokens`` for
   setup codes / invites / reset links, ``login_failures`` keyed by an HMAC of the typed name),
   ``user_profiles`` and ``user_food_links``; then the settings tables
   (:func:`app.settings_store.create_settings_tables`), ``secrets`` / ``usage_daily``
   (:func:`app.credentials.create_credentials_tables`) and the append-only ``audit_log``
   (:func:`app.audit.create_audit_table`).
2. Inserts user 1 as a ``pending_setup`` admin when ``users`` is empty. Its name is a placeholder
   that no local account can type (``#setup``); first-run setup, ``ADMIN_PASSWORD_FILE``, the legacy
   ``APP_PASSWORD`` import or ``python -m app.admin create-admin`` claim it, so the migrated data
   stays with whoever sets the server up.
3. Adds the nullable ``user_id`` (``log_entries``, ``meal_templates``) and ``owner_user_id``
   (``foods``, NULL = shared) columns with ``ON DELETE CASCADE``; SQLite cannot add a non-NULL
   ``REFERENCES`` column, so triggers refuse NULL instead.
4. Back-fills every existing entry, saved meal and custom food to user 1, links every shared
   ``usda``/``off`` food to user 1, and copies the singleton ``profile`` row into user 1's
   ``user_profiles`` row (the old table stays, frozen, and is never read again).
5. Indexes and triggers that name the new columns (never in ``SCHEMA``: note 07 "ordering gotcha").
"""
from __future__ import annotations

import sqlite3

from ..audit import create_audit_table
from ..credentials import create_credentials_tables
from ..db import add_column_if_missing, execute_script, set_meta, table_exists, utcnow
from ..settings_store import create_settings_tables

VERSION = 3
DESCRIPTION = "v0.3 accounts, per-user data, settings, secrets, audit"

SCHEMA = ""  # all DDL runs inside migrate(), after the pre-v3 backup
ATOMIC = True
BACKUP_BEFORE = True
FOREIGN_KEY_CHECK = True

# meta key holding when the accounts migration ran (the pre-v3 backup expires 30 days later, §9 N11).
MIGRATED_AT_KEY = "accounts_migrated_at"
# user 1 before anyone claims it; '#' is not allowed in local usernames, so nobody can register it.
PLACEHOLDER_USERNAME_NORM = "#setup"

ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,
  username_norm TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending_setup','active','disabled','locked')),
  auth_source TEXT NOT NULL DEFAULT 'local' CHECK (auth_source IN ('local','proxy','oidc')),
  external_subject TEXT,
  password_hash TEXT,
  password_changed_at TEXT,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  can_use_shared INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS users_external ON users(auth_source, external_subject)
  WHERE external_subject IS NOT NULL;

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  verifier_hash BLOB NOT NULL,
  created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  reauth_at TEXT,
  user_agent TEXT,
  ip_prefix TEXT
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS auth_tokens (
  id TEXT PRIMARY KEY,
  purpose TEXT NOT NULL CHECK (purpose IN ('setup','invite','reset')),
  verifier_hash BLOB NOT NULL,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  role TEXT CHECK (role IN ('admin','user')),
  note TEXT,
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT
);

CREATE TABLE IF NOT EXISTS login_failures (
  name_mac BLOB PRIMARY KEY,
  consecutive INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT, last_failure_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS user_profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '', weight_kg REAL, height_cm REAL,
  ckd_stage TEXT NOT NULL DEFAULT '3b', dialysis TEXT NOT NULL DEFAULT 'none',
  diabetes TEXT NOT NULL DEFAULT 'type1', warn_fraction REAL NOT NULL DEFAULT 0.8,
  targets_json TEXT NOT NULL DEFAULT '{}', dialysis_days_json TEXT NOT NULL DEFAULT '[]',
  week_start TEXT NOT NULL DEFAULT 'monday',
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS user_food_links (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, food_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS user_food_links_food ON user_food_links(food_id);
"""

# Indexes and triggers naming the columns this step adds (step 5).
SCOPING_DDL = """
CREATE INDEX IF NOT EXISTS log_user_date ON log_entries(user_id, date);
CREATE INDEX IF NOT EXISTS meal_templates_user ON meal_templates(user_id, name);
CREATE INDEX IF NOT EXISTS foods_owner ON foods(owner_user_id) WHERE owner_user_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS log_entries_user_required_ins BEFORE INSERT ON log_entries
  WHEN NEW.user_id IS NULL BEGIN SELECT RAISE(ABORT, 'log_entries.user_id is required'); END;
CREATE TRIGGER IF NOT EXISTS log_entries_user_required_upd BEFORE UPDATE OF user_id ON log_entries
  WHEN NEW.user_id IS NULL BEGIN SELECT RAISE(ABORT, 'log_entries.user_id is required'); END;
CREATE TRIGGER IF NOT EXISTS meal_templates_user_required_ins BEFORE INSERT ON meal_templates
  WHEN NEW.user_id IS NULL BEGIN SELECT RAISE(ABORT, 'meal_templates.user_id is required'); END;
CREATE TRIGGER IF NOT EXISTS meal_templates_user_required_upd BEFORE UPDATE OF user_id ON meal_templates
  WHEN NEW.user_id IS NULL BEGIN SELECT RAISE(ABORT, 'meal_templates.user_id is required'); END;
CREATE TRIGGER IF NOT EXISTS foods_custom_owner_ins BEFORE INSERT ON foods
  WHEN NEW.source = 'custom' AND NEW.owner_user_id IS NULL
  BEGIN SELECT RAISE(ABORT, 'foods.owner_user_id is required for custom foods'); END;
CREATE TRIGGER IF NOT EXISTS foods_custom_owner_upd BEFORE UPDATE OF source, owner_user_id ON foods
  WHEN NEW.source = 'custom' AND NEW.owner_user_id IS NULL
  BEGIN SELECT RAISE(ABORT, 'foods.owner_user_id is required for custom foods'); END;
"""

_PROFILE_COLUMNS = (
    "name", "weight_kg", "height_cm", "ckd_stage", "dialysis", "diabetes", "warn_fraction",
    "targets_json", "dialysis_days_json", "week_start", "updated_at",
)


def migrate(conn: sqlite3.Connection) -> None:
    now = utcnow()

    # 1. tables
    execute_script(conn, ACCOUNTS_DDL)
    create_settings_tables(conn)
    create_credentials_tables(conn)
    create_audit_table(conn)

    # 2. user 1 (claimed later by setup)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            """INSERT INTO users (id, username, username_norm, display_name, role, status, auth_source,
                                  created_at, updated_at)
               VALUES (1, '', ?, '', 'admin', 'pending_setup', 'local', ?, ?)""",
            (PLACEHOLDER_USERNAME_NORM, now, now),
        )

    # 3. owner columns (nullable: SQLite refuses a non-NULL default on an added REFERENCES column)
    add_column_if_missing(conn, "log_entries", "user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")
    add_column_if_missing(conn, "meal_templates", "user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")
    add_column_if_missing(conn, "foods", "owner_user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")

    # 4. back-fill: everything that exists belonged to the one v0.2 person
    conn.execute("UPDATE log_entries SET user_id = 1 WHERE user_id IS NULL")
    conn.execute("UPDATE meal_templates SET user_id = 1 WHERE user_id IS NULL")
    conn.execute("UPDATE foods SET owner_user_id = 1 WHERE source = 'custom' AND owner_user_id IS NULL")
    conn.execute(
        """INSERT OR IGNORE INTO user_food_links (user_id, food_id, created_at)
           SELECT 1, id, ? FROM foods WHERE source IN ('usda', 'off') AND owner_user_id IS NULL""",
        (now,),
    )
    if table_exists(conn, "profile"):
        cols = ", ".join(_PROFILE_COLUMNS)
        conn.execute(f"INSERT OR IGNORE INTO user_profiles (user_id, {cols}) SELECT 1, {cols} FROM profile WHERE id = 1")

    # 5. indexes and NULL-blocking triggers
    execute_script(conn, SCOPING_DDL)
    set_meta(conn, MIGRATED_AT_KEY, now)
