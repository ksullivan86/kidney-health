"""Start-up tasks for accounts (note 07 §4.5, §4.6, §4.7 and §9 N2, N11).

Run once by the app's lifespan after the database is migrated:

1. Password self-test (Argon2id, or scrypt with ``PASSWORD_HASH=scrypt``).
2. Sign everybody out when ``AUTH_MODE`` changed since the last start (``meta.auth_mode``, §9 N2).
3. Housekeeping: expired sessions, idle throttle rows, the pre-v3 backup 30 days after the
   migration (§9 N11).
4. First run, when no admin has been set up:
   * ``ADMIN_USERNAME`` + ``ADMIN_PASSWORD[_FILE]`` → that admin (a password that fails the policy
     stops the start with a clear message);
   * otherwise the deprecated ``APP_PASSWORD`` → user 1's password (``must_change_password`` when it
     fails today's policy);
   * otherwise a one-time **setup code** in the log at WARNING:
     ``FIRST-RUN SETUP: open https://<this server>/#/setup and enter the code XXXX-XXXX-XXXX-XXXX``.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from pathlib import Path

from ..audit import audit
from ..db import database_file, get_meta, set_meta
from . import clock, passwords, policy, sessions, tokens
from .accounts import claim_first_admin
from .context import AuthContext
from .models import normalize_username, setup_required, valid_local_username

log = logging.getLogger("kidney_health.auth")

AUTH_MODE_KEY = "auth_mode"
PRE_V3_BACKUP_DAYS = 30
DEFAULT_LEGACY_USERNAME = "admin"


class StartupError(RuntimeError):
    """A configuration problem found while starting (the message says what to do)."""


def _auth_mode_changed(conn: sqlite3.Connection, mode: str) -> None:
    previous = get_meta(conn, AUTH_MODE_KEY)
    if previous is not None and previous != mode:
        removed = conn.execute("DELETE FROM sessions").rowcount
        log.warning("AUTH_MODE changed from %s to %s: signed out every device (%d sessions)", previous, mode, removed)
    if previous != mode:
        set_meta(conn, AUTH_MODE_KEY, mode)


def expire_pre_v3_backup(conn: sqlite3.Connection, *, days: int = PRE_V3_BACKUP_DAYS) -> bool:
    """Delete ``kidney.db.pre-v3.bak`` once the migration is ``days`` old (it holds every v0.2 meal)."""
    path = database_file(conn)
    migrated = clock.parse(get_meta(conn, "accounts_migrated_at"))
    if not path or migrated is None:
        return False
    backup = Path(f"{path}.pre-v3.bak")
    if not backup.exists() or clock.now() - migrated < timedelta(days=days):
        return False
    backup.unlink()
    log.warning("deleted %s: the v0.3 upgrade is more than %d days old", backup, days)
    return True


def setup_line(ctx: AuthContext, code: str) -> str:
    base = ctx.settings.public_origin or "https://<this server>"
    return (
        f"FIRST-RUN SETUP: open {base}/#/setup and enter the code {code} (valid {ctx.settings.setup_code_ttl_minutes} min; "
        'restart or run "python -m app.admin setup-code" for a new one)'
    )


def _admin_from_env(conn: sqlite3.Connection, ctx: AuthContext) -> bool:
    s = ctx.settings
    if not s.admin_password:
        return False
    if s.auth_mode != "local":
        log.warning("ADMIN_PASSWORD is ignored with AUTH_MODE=%s; finish setup with the setup code", s.auth_mode)
        return False
    username = s.admin_username or ""
    norm = normalize_username(username)
    if not valid_local_username(norm):
        raise StartupError("ADMIN_USERNAME must be 3 to 64 characters: letters, digits and . _ @ + -")
    problems = policy.validate_new_password(
        s.admin_password, username=username, instance_name=str(ctx.store.get(conn, "instance.name")),
        min_length=s.password_min_length,
    )
    if problems:
        raise StartupError(f"ADMIN_PASSWORD does not meet the password policy: {' '.join(problems)}")
    user_id = claim_first_admin(conn, username=username, username_norm=norm, password_hash=passwords.hash_password(s.admin_password))
    audit(conn, None, "setup.completed", "user", user_id, via="admin_password_env")
    log.warning('admin "%s" created from ADMIN_PASSWORD (or ADMIN_PASSWORD_FILE)', username)
    return True


def _legacy_app_password(conn: sqlite3.Connection, ctx: AuthContext) -> bool:
    s = ctx.settings
    if not s.app_password or s.auth_mode != "local":
        return False
    username = s.admin_username or DEFAULT_LEGACY_USERNAME
    norm = normalize_username(username)
    if not valid_local_username(norm):
        raise StartupError("ADMIN_USERNAME must be 3 to 64 characters: letters, digits and . _ @ + -")
    problems = policy.validate_new_password(s.app_password, username=username, min_length=s.password_min_length)
    user_id = claim_first_admin(
        conn, username=username, username_norm=norm, password_hash=passwords.hash_password(s.app_password),
        must_change_password=bool(problems),
    )
    audit(conn, None, "setup.completed", "user", user_id, via="app_password_import")
    log.warning(
        'APP_PASSWORD is deprecated and was imported once as the password of admin "%s"%s. HTTP Basic sign-in is gone: '
        "sign in on the app's page. Remove APP_PASSWORD from your configuration.",
        username,
        "; it is too weak for today's policy, so a new one must be chosen at the first sign-in" if problems else "",
    )
    return True


def ensure_user_one(conn: sqlite3.Connection) -> bool:
    """``AUTH_MODE=none`` serves every request as user 1: recreate that row (empty, ``pending_setup``,
    as schema step 3 made it) when it is gone, for example after it was deleted in local mode before
    the switch. Returns True when it had to be created (no commit)."""
    from ..db import utcnow
    from ..migrations.m003_accounts import PLACEHOLDER_USERNAME_NORM

    if conn.execute("SELECT 1 FROM users WHERE id = 1").fetchone() is not None:
        return False
    taken = conn.execute("SELECT 1 FROM users WHERE username_norm = ?", (PLACEHOLDER_USERNAME_NORM,)).fetchone()
    norm = "#user-1" if taken else PLACEHOLDER_USERNAME_NORM
    now = utcnow()
    conn.execute(
        """INSERT INTO users (id, username, username_norm, display_name, role, status, auth_source, created_at, updated_at)
           VALUES (1, '', ?, '', 'admin', 'pending_setup', 'local', ?, ?)""",
        (norm, now, now),
    )
    log.warning("AUTH_MODE=none: user 1 was missing, so it was created again (with no data)")
    return True


def startup(conn: sqlite3.Connection, ctx: AuthContext) -> None:
    s = ctx.settings
    passwords.configure(s.password_hash)
    try:
        passwords.self_test()
    except passwords.PasswordBackendUnavailable as exc:
        raise StartupError(str(exc)) from None
    passwords.dummy_hash()  # computed now, so the first unknown-user sign-in is not slower

    _auth_mode_changed(conn, s.auth_mode)
    removed = sessions.purge_expired(conn, idle_days=s.session_idle_days)
    if removed:
        log.info("removed %d expired sessions", removed)
    ctx.throttle.prune(conn)
    expire_pre_v3_backup(conn)

    if s.auth_mode == "none":
        ensure_user_one(conn)
        log.warning(
            "AUTH_MODE=none: there is no sign-in; anyone who can open this server can read and change all data"
        )
        conn.commit()
        return

    if setup_required(conn):
        done = _admin_from_env(conn, ctx) or _legacy_app_password(conn, ctx)
        if not done:
            code, _ = tokens.new_setup_code(conn, s.setup_code_ttl_minutes)
            conn.commit()
            log.warning(setup_line(ctx, code))
            return
    else:
        conn.execute("DELETE FROM auth_tokens WHERE purpose = 'setup'")
        if s.admin_password:
            log.warning("ADMIN_PASSWORD is set but an admin already exists; it is ignored (remove it from your configuration)")
        if s.app_password:
            log.warning("APP_PASSWORD is deprecated and ignored: accounts exist. Remove it from your configuration.")
    ctx.setup_complete = not setup_required(conn)
    conn.commit()
