"""Test accounts: ``tester`` and ``tester-helper`` (design note 26; ARCHITECTURE.md "Test accounts"; schema step 28).

One server switch, ``test_accounts.enabled`` (``TEST_ACCOUNT_ENABLED``, off), lets testers use the real app on the owner's server
without a real account. :func:`sync` runs at start-up, after the first-run setup and whenever an admin changes the switch:

* **On** (``AUTH_MODE=local`` and the first admin set up): make the two accounts if they are missing, with the one password read
  from ``TEST_ACCOUNT_PASSWORD_FILE``. ``tester`` starts with the sample person Sam (:func:`seed_patient`, a port of the demo's
  ``app/static/js/mock/seed.js``: CKD stage 4, type 1 diabetes, the same profile, log, saved meals, lab results, weights and
  blood pressure, dates counted from today). ``tester-helper`` is already a Care helper on tester's Care team. A disabled or
  locked test account is enabled again, and a password that no longer matches the file is set again.
* **Off**: both are disabled (not deleted), signed out, and their tokens revoked.

A missing, unreadable or weak password file, or a real account that already uses one of the names, makes nothing: the reason is
logged and shown in Server administration → Test accounts (:func:`status`).

The rules for test accounts live where each feature decides (each calls :func:`is_test` or :func:`same_kind`): never an admin
(the People page, single sign-on groups, and the two triggers of step 28 underneath), a Care team only with another test account
(``app/sharing.py``), the server's AI only with ``test_accounts.ai`` (``app/ai/config.py``, ``app/ai/routing.py``), and the
password stays the file's (``app/auth/me.py``). :func:`reset` deletes both accounts with everything they made and makes them
again; the feedback they sent stays (``app/feedback.py``).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from . import brand
from .audit import audit, register_action
from .config import ConfigError, Settings, read_secret
from .db import table_exists, utcnow
from .settings_store import SettingsStore

log = logging.getLogger(f"{brand.LOGGER_NAME}.test_accounts")

SWITCH = "test_accounts.enabled"
AI_SWITCH = "test_accounts.ai"
TESTER = "tester"
HELPER = "tester-helper"
NAMES = (TESTER, HELPER)
DISPLAY = {TESTER: "Sam", HELPER: "Jo"}
HELPER_AREAS = ["food", "labs", "body", "symptoms"]

for _action in ("test_accounts.created", "test_accounts.enabled", "test_accounts.disabled", "test_accounts.reset"):
    register_action(_action)


class ResetRefused(Exception):
    """Reset cannot run now (the message says why); nothing was changed."""


# --------------------------------------------------------------------------- #
# Who is a test account
# --------------------------------------------------------------------------- #


def _has_column(conn: sqlite3.Connection) -> bool:
    return any(r[1] == "is_test_account" for r in conn.execute("PRAGMA table_info(users)").fetchall())


def is_test(conn: sqlite3.Connection, user_id: int | None) -> bool:
    if user_id is None:
        return False
    try:
        row = conn.execute("SELECT is_test_account FROM users WHERE id = ?", (int(user_id),)).fetchone()
    except (sqlite3.OperationalError, OverflowError):  # before step 28, or an id SQLite cannot hold
        return False
    return bool(row is not None and row[0])


def same_kind(conn: sqlite3.Connection, a: int | None, b: int | None) -> bool:
    """Two accounts may be on one Care team only when both are test accounts or neither is."""
    return is_test(conn, a) == is_test(conn, b)


def ai_allowed(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> bool:
    """The server's AI is off for a test account unless the admin turned on ``test_accounts.ai``."""
    return not is_test(conn, user_id) or bool(store.get(conn, AI_SWITCH))


def _rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    if not _has_column(conn):
        return []
    return conn.execute("SELECT id, username, username_norm, status, is_test_account, password_hash, last_login_at "
                        "FROM users WHERE is_test_account = 1 ORDER BY id").fetchall()


# --------------------------------------------------------------------------- #
# The password file
# --------------------------------------------------------------------------- #


def read_password(conn: sqlite3.Connection, settings: Settings, store: SettingsStore) -> tuple[str | None, str | None]:
    """``(password, None)``, or ``(None, why not)`` when the file is not set, cannot be read or fails the password policy."""
    from .auth import policy

    path = settings.test_account_password_file
    if path is None:
        return None, ("Set TEST_ACCOUNT_PASSWORD_FILE to a file that holds the test accounts' password "
                      "(a Podman or compose secret), then restart.")
    try:
        password, _, _ = read_secret({"TEST_ACCOUNT_PASSWORD_FILE": str(path)}, "TEST_ACCOUNT_PASSWORD")
    except ConfigError as exc:
        return None, str(exc)
    if not password:
        return None, f"TEST_ACCOUNT_PASSWORD_FILE: {path} is empty. Put the test accounts' password in it."
    instance = str(store.get(conn, "instance.name"))
    for name in NAMES:
        problems = policy.validate_new_password(password, username=name, display_name=DISPLAY[name], instance_name=instance,
                                                min_length=settings.password_min_length)
        if problems:
            return None, "The password in TEST_ACCOUNT_PASSWORD_FILE does not meet the password policy: " + " ".join(problems)
    return password, None


# --------------------------------------------------------------------------- #
# Make, enable, disable
# --------------------------------------------------------------------------- #


def _blocked(conn: sqlite3.Connection, settings: Settings) -> str | None:
    from .auth.models import setup_required

    if settings.auth_mode != "local":
        return f"Test accounts sign in with a password, so they need AUTH_MODE=local (this server uses AUTH_MODE={settings.auth_mode})."
    if not _has_column(conn) or setup_required(conn):
        return "Test accounts are made once the first admin is set up."
    for name in NAMES:
        row = conn.execute("SELECT is_test_account FROM users WHERE username_norm = ?", (name,)).fetchone()
        if row is not None and not row["is_test_account"]:
            return (f"A real account already uses the user name {name}, so the test accounts were not made. "
                    "Rename or delete that account first.")
    return None


def _disable(conn: sqlite3.Connection, row: sqlite3.Row, *, actor_id: int | None, ip: str | None, why: str) -> None:
    from .auth import api_tokens, sessions, tokens

    uid = int(row["id"])
    conn.execute("UPDATE users SET status = 'disabled', updated_at = ? WHERE id = ?", (utcnow(), uid))
    sessions.revoke_user_sessions(conn, uid)
    tokens.void_reset_links(conn, uid)
    api_tokens.revoke_all(conn, uid, reason="account_disabled", actor_id=actor_id, ip=ip)
    audit(conn, actor_id, "test_accounts.disabled", "user", uid, ip=ip, username=row["username"], why=why)


def disable_all(conn: sqlite3.Connection, *, actor_id: int | None = None, ip: str | None = None, why: str = "switch_off") -> int:
    """Disable every active test account and sign it out (no commit). Returns how many."""
    done = 0
    for row in _rows(conn):
        if row["status"] != "disabled":
            _disable(conn, row, actor_id=actor_id, ip=ip, why=why)
            done += 1
    return done


def sync(conn: sqlite3.Connection, settings: Settings, store: SettingsStore, *, actor_id: int | None = None,
         ip: str | None = None) -> str | None:
    """Bring the test accounts in line with the switch (see the module docstring) and commit. Returns the problem that kept
    them from being made or enabled, or None. Never raises for a configuration problem: it logs it."""
    from .auth import passwords
    from .auth.accounts import create_user

    if not table_exists(conn, "users") or not _has_column(conn):
        return None
    if not store.get(conn, SWITCH):
        n = disable_all(conn, actor_id=actor_id, ip=ip)
        conn.commit()
        if n:
            log.warning("test accounts turned off: %d test account(s) disabled and signed out", n)
        return None
    problem = _blocked(conn, settings)
    if problem:
        if settings.auth_mode != "local":
            disable_all(conn, actor_id=actor_id, ip=ip, why="auth_mode")
            conn.commit()
        log.warning("test accounts: %s", problem)
        return problem
    password, problem = read_password(conn, settings, store)
    existing = {r["username_norm"]: r for r in _rows(conn)}
    if password is None:
        log.warning("test accounts were not made: %s", problem)
        return problem
    made: dict[str, int] = {}
    for name in NAMES:
        row = existing.get(name)
        if row is None:
            uid = create_user(conn, username=name, username_norm=name, display_name=DISPLAY[name], role="user",
                              password_hash=passwords.hash_password(password))
            conn.execute("UPDATE users SET is_test_account = 1 WHERE id = ?", (uid,))
            audit(conn, actor_id, "test_accounts.created", "user", uid, ip=ip, username=name)
            made[name] = uid
            continue
        uid = int(row["id"])
        if not passwords.verify_password(password, row["password_hash"]):
            conn.execute("UPDATE users SET password_hash = ?, password_changed_at = ?, must_change_password = 0, updated_at = ? "
                         "WHERE id = ?", (passwords.hash_password(password), utcnow(), utcnow(), uid))
        if row["status"] != "active":
            conn.execute("UPDATE users SET status = 'active', updated_at = ? WHERE id = ?", (utcnow(), uid))
            audit(conn, actor_id, "test_accounts.enabled", "user", uid, ip=ip, username=name)
    ids = {name: made.get(name) or int(existing[name]["id"]) for name in NAMES}
    if TESTER in made:
        seed_patient(conn, store, ids[TESTER])
    if TESTER in made or HELPER in made:
        link_helper(conn, ids[TESTER], ids[HELPER])
    conn.commit()
    if made:
        log.warning("test accounts made: %s (password from TEST_ACCOUNT_PASSWORD_FILE)", ", ".join(sorted(made)))
    return None


def reset(conn: sqlite3.Connection, settings: Settings, store: SettingsStore, *, actor_id: int | None, ip: str | None = None) -> None:
    """Delete both test accounts and everything they made, then make them again from the start (Sam's sample data and the Care
    team link). The feedback they sent stays. Raises :class:`ResetRefused` (nothing changed) while the switch is off or the
    accounts could not be made again."""
    from .auth import api_tokens

    if not store.get(conn, SWITCH):
        raise ResetRefused("Turn on test accounts first (Server settings → Test accounts, or TEST_ACCOUNT_ENABLED).")
    problem = _blocked(conn, settings)
    if problem is None:
        _, problem = read_password(conn, settings, store)
    if problem:
        raise ResetRefused(problem)
    names = []
    for row in _rows(conn):  # as deleting an account does (app/account.py), with one activity row for the reset
        api_tokens.revoke_all(conn, int(row["id"]), reason="account_deleted", actor_id=actor_id, ip=ip)
        conn.execute("DELETE FROM users WHERE id = ?", (int(row["id"]),))
        names.append(row["username"])
    audit(conn, actor_id, "test_accounts.reset", "setting", SWITCH, ip=ip, accounts=names)
    problem = sync(conn, settings, store, actor_id=actor_id, ip=ip)
    if problem:  # the file changed between the check and now
        raise ResetRefused(problem)


def status(conn: sqlite3.Connection, settings: Settings, store: SettingsStore) -> dict[str, Any]:
    """What Server administration → Test accounts shows: the switches, the problem (if any) and each account's state."""
    enabled = bool(store.get(conn, SWITCH))
    problem = None
    if enabled:
        problem = _blocked(conn, settings)
        if problem is None:
            _, problem = read_password(conn, settings, store)
    accounts = [{"id": int(r["id"]), "username": r["username"], "status": r["status"], "last_login_at": r["last_login_at"]}
                for r in _rows(conn)]
    return {"enabled": enabled, "ai": bool(store.get(conn, AI_SWITCH)), "problem": problem, "accounts": accounts}


# --------------------------------------------------------------------------- #
# The Care team link
# --------------------------------------------------------------------------- #


def link_helper(conn: sqlite3.Connection, owner_id: int, helper_id: int) -> None:
    """``tester-helper`` on ``tester``'s Care team as a Care helper who sees all four areas (no commit). Skipped when a share
    between them is already active."""
    from .auth import clock

    found = conn.execute("SELECT 1 FROM shares WHERE owner_user_id = ? AND grantee_user_id = ? AND accepted_at IS NOT NULL "
                         "AND ended_at IS NULL", (owner_id, helper_id)).fetchone()
    if found is not None:
        return
    now = clock.now_iso()
    conn.execute("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at, role) VALUES (?, ?, ?, ?, ?, ?)",
                 (owner_id, helper_id, json.dumps(HELPER_AREAS), now, now, "care_helper"))


# --------------------------------------------------------------------------- #
# Sam's sample data: a port of the demo's seed (app/static/js/mock/seed.js, the non-dialysis person)
# --------------------------------------------------------------------------- #

# Foods by USDA FDC id, with a name fallback (the same table as the demo).
FOODS: dict[str, tuple[int, str]] = {
    "apple": (171688, r"^apple, raw"), "blueberries": (171711, r"^blueberries"), "strawberries": (167762, r"^strawberries"),
    "grapes": (174683, r"^grapes"), "applesauce": (171695, r"^applesauce"), "pineapple": (169126, r"^pineapple, canned"),
    "pears": (169936, r"^pears, canned"), "rice": (168878, r"^rice, white"), "bread": (174924, r"^bread, white"),
    "pasta": (169737, r"^pasta, cooked"), "creamOfWheat": (171657, r"^cream of wheat"), "englishMuffin": (175063, r"^english muffin, plain"),
    "riceCakes": (170250, r"^rice cakes"), "riceMilk": (171942, r"^rice milk"), "saltines": (172746, r"^saltine"),
    "popcorn": (167959, r"^popcorn, air"), "vanillaWafers": (174974, r"^vanilla wafers"), "sugarCookies": (174971, r"^cookies, sugar"),
    "chicken": (171477, r"^chicken breast, roasted"), "turkey": (171496, r"^turkey breast, roasted"), "cod": (171956, r"^cod"),
    "eggWhite": (172183, r"^egg white"), "greenBeans": (169141, r"^green beans"), "cauliflower": (170397, r"^cauliflower, boiled"),
    "cabbage": (169976, r"^cabbage, boiled"), "cucumber": (168409, r"^cucumber"), "lettuce": (169248, r"^lettuce, iceberg"),
    "redPepper": (170108, r"^bell pepper, red"), "onion": (170000, r"^onion, raw"), "carrots": (170394, r"^carrots, boiled"),
    "butter": (173430, r"^butter, unsalted"), "creamCheese": (173418, r"^cream cheese"), "oliveOil": (171413, r"^olive oil"),
    "mayonnaise": (171009, r"^mayonnaise"), "jam": (169641, r"^jam"), "brownSugar": (168833, r"^sugar, brown"),
    "salt": (173468, r"^salt, table"), "coffee": (171890, r"^coffee, brewed"), "water": (173647, r"^water, tap"),
    "tea": (173227, r"^tea, black"), "banana": (173944, r"^banana"), "potato": (170093, r"^potato, baked"),
    "deliTurkey": (172941, r"^deli turkey"), "cola": (174852, r"^cola, regular"), "orangeJuice": (169098, r"^orange juice"),
    "cheeseburger": (170691, r"^cheeseburger"), "fries": (170698, r"^french fries, fast food"),
    "soup": (172909, r"^soup, chicken noodle"), "pretzels": (167555, r"^pretzels"), "glucose": (-10, r"^glucose tablet"),
}
Items = list[tuple[Any, ...]]  # (food key, servings[, item note])
BREAKFASTS: list[Items] = [
    [("eggWhite", 2), ("bread", 2), ("butter", 1), ("jam", 1), ("blueberries", 1), ("coffee", 1)],
    [("creamOfWheat", 1), ("riceMilk", 0.5), ("brownSugar", 1), ("strawberries", 1), ("coffee", 1)],
    [("englishMuffin", 1), ("creamCheese", 1), ("jam", 1), ("applesauce", 1), ("tea", 1)],
    [("eggWhite", 3), ("bread", 2), ("butter", 1), ("pears", 1), ("coffee", 1)],
]
LUNCHES: list[Items] = [
    [("chicken", 0.5), ("rice", 1), ("greenBeans", 1), ("oliveOil", 1), ("salt", 0.25), ("water", 1)],
    [("bread", 2), ("turkey", 0.5), ("mayonnaise", 1), ("lettuce", 0.5), ("cucumber", 1), ("apple", 1), ("water", 1)],
    [("pasta", 1), ("chicken", 0.5), ("redPepper", 1), ("onion", 0.5), ("oliveOil", 1), ("salt", 0.25), ("water", 1)],
]
DINNERS: list[Items] = [
    [("cod", 0.75), ("rice", 1), ("cauliflower", 2), ("butter", 1), ("salt", 0.5), ("water", 1)],
    [("chicken", 0.75), ("pasta", 1), ("cabbage", 1), ("oliveOil", 1), ("salt", 0.25), ("water", 1)],
    [("turkey", 0.75), ("rice", 1), ("greenBeans", 1), ("carrots", 1), ("butter", 1), ("salt", 0.25)],
    [("eggWhite", 3), ("bread", 1), ("cauliflower", 2), ("redPepper", 1), ("oliveOil", 1), ("salt", 0.5)],
]
SNACKS: list[Items] = [[("apple", 1)], [("riceCakes", 1), ("jam", 1)], [("grapes", 1)], [("pineapple", 1)], [("vanillaWafers", 1)],
                       [("popcorn", 1)], [("sugarCookies", 1), ("coffee", 1)], [("saltines", 1), ("pears", 1)]]
EMPTY = {9, 16, 23}
SPECIAL: dict[int, dict[str, Any]] = {
    2: {"lunch": [("bread", 2), ("deliTurkey", 1.5), ("mayonnaise", 1), ("lettuce", 0.5), ("apple", 1), ("water", 1)],
        "dinner": [("soup", 1), ("saltines", 1), ("chicken", 0.5), ("cucumber", 1), ("water", 1)]},
    4: {"hypo": "Hypo 3.5 mmol/L before dinner; 5.8 after 15 minutes"},
    5: {"lunch": [("cheeseburger", 1), ("cola", 1, "lunch out")]},
    7: {"breakfast": [("banana", 1), ("creamOfWheat", 1), ("riceMilk", 0.5), ("coffee", 1)],
        "dinner": [("chicken", 0.75), ("potato", 1), ("butter", 1), ("greenBeans", 1), ("water", 1)]},
    11: {"dinner": [("cod", 0.75), ("potato", 1), ("butter", 1), ("cauliflower", 2), ("water", 1)]},
    13: {"dinner": [("cheeseburger", 1), ("fries", 1), ("cola", 1, "takeaway")], "hypo": "Hypo 3.7 mmol/L mid-morning; 5.4 after 15 minutes"},
    18: {"lunch": [("bread", 2), ("deliTurkey", 1.5), ("mayonnaise", 1), ("lettuce", 0.5), ("water", 1)],
         "snack": [("cola", 1), ("pretzels", 1)]},
    21: {"breakfast": [("banana", 1), ("bread", 2), ("butter", 1), ("orangeJuice", 1), ("coffee", 1)],
         "dinner": [("turkey", 0.75), ("potato", 1.5, "big one"), ("butter", 1), ("cabbage", 1), ("water", 1)]},
    26: {"lunch": [("cheeseburger", 1), ("water", 1)]},
    28: {"lunch": [("bread", 2), ("deliTurkey", 1), ("mayonnaise", 1), ("cucumber", 1), ("water", 1)], "snack": [("banana", 1)]},
}
TIMES = {"breakfast": 7.45, "lunch": 12.3, "dinner": 18.4, "snack": 15.3}
MEALS = ("breakfast", "lunch", "dinner", "snack")
PROFILE = {"name": "Sam", "weight_kg": 70, "height_cm": 170, "ckd_stage": "4", "dialysis": "none", "diabetes": "type1",
           "warn_fraction": 0.8, "dialysis_days": [], "week_start": "monday", "birth_month": "1971-03", "activity": "low_active"}
# (days ago, analyte, value, unit, note): typed from the person's blood tests, some in SI units.
LABS = [(96, "potassium", 5.3, "mmol/L", ""), (96, "creatinine", 2.3, "mg/dL", ""), (96, "egfr", 26, "mL/min/1.73 m²", ""),
        (41, "albumin", 39, "g/L", ""), (41, "a1c", 58, "mmol/mol", ""),
        (12, "potassium", 4.8, "mmol/L", "Clinic visit"), (12, "phosphate", 1.58, "mmol/L", ""), (12, "bicarbonate", 21, "mmol/L", ""),
        (12, "creatinine", 212, "µmol/L", ""), (12, "egfr", 25, "mL/min/1.73 m²", ""), (12, "uacr", 25, "mg/mmol", "")]
MORNING_KG = [70.2, 70.0, 70.3, 70.1, 69.9, 70.2, 70.4, 70.1, 70.0, 70.3, 70.2, 70.1, 70.3, 70.2, 71.5]  # 14 days ago … today
MORNING_BP = [(126, 76, 64), (130, 80, 66), (132, 82, 68), (128, 78, 63), (134, 84, 70), (129, 79, 65), (131, 80, 64), (127, 77, 62),
              (133, 83, 69), (130, 79, 66), (128, 78, 64), (135, 85, 71), (129, 78, 65), (131, 81, 67), (132, 80, 66)]
EVENING_BP = {12: (138, 86, 72), 9: (136, 84, 70), 6: (140, 88, 74), 3: (134, 82, 69), 1: (137, 85, 71)}
# A sample alarm and goal, as if "from the care team" (the app never suggests either; note 10 §2).
BODY_SETTINGS = {"body.weight_alarm": {"amount_kg": 1, "over": "days", "days": 1}, "body.bp_goal": {"systolic": 130, "diastolic": 80}}
SAVED_MEALS = [
    ("Usual breakfast", "Weekday default", BREAKFASTS[0]),
    ("Chicken & rice lunch", None, [("chicken", 0.5), ("rice", 1), ("greenBeans", 1), ("oliveOil", 1), ("water", 1)]),
    ("Hypo kit: glucose tablets", "4 tablets = 16 g fast carbohydrate with no potassium. Recheck in 15 minutes.", [("glucose", 4)]),
]
_M32 = 0xFFFFFFFF


def mulberry32(seed: int) -> Callable[[], float]:
    """The demo's random numbers (mulberry32 with the same seed), so the sample plan is the same as the demo's."""
    state = [seed & _M32]

    def rnd() -> float:
        state[0] = (state[0] + 0x6D2B79F5) & _M32
        s = state[0]
        t = ((s ^ (s >> 15)) * (1 | s)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _M32)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return rnd


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _at(day: date, hhmm: float) -> int:
    """Milliseconds of ``day`` at ``hhmm`` (7.45 is 7:45) on the server's clock, as the demo's ``at``."""
    hours = int(hhmm)
    minutes = round((hhmm % 1) * 100)
    return int(datetime(day.year, day.month, day.day, hours, minutes).astimezone().timestamp() * 1000)


def _food_finder(conn: sqlite3.Connection) -> Callable[[str], sqlite3.Row | None]:
    rows = conn.execute("SELECT id, fdc_id, name FROM foods WHERE source = 'builtin' ORDER BY id").fetchall()
    cache: dict[str, sqlite3.Row | None] = {}

    def find(key: str) -> sqlite3.Row | None:
        if key not in cache:
            fdc, pattern = FOODS[key]
            hit = next((r for r in rows if r["fdc_id"] == fdc), None)
            if hit is None:
                rx = re.compile(pattern, re.I)
                hit = next((r for r in rows if rx.search(r["name"] or "")), None)
            cache[key] = None if hit is None else conn.execute("SELECT * FROM foods WHERE id = ?", (hit["id"],)).fetchone()
        return cache[key]

    return find


def seed_patient(conn: sqlite3.Connection, store: SettingsStore, user_id: int, today: date | None = None,
                 now_ms: int | None = None) -> dict[str, int]:
    """Sam's sample data for ``user_id`` (no commit): about 30 days of renal-diet meals with a few higher days, two low
    treatments and three empty days, today partly eaten with dinner planned, three days ahead planned, three saved meals, the
    profile and the targets its suggestion gives, lab results, two weeks of weights and blood pressure, and a sample weight-gain
    alarm and blood pressure goal. Returns counts."""
    from . import log as log_module
    from . import meals as meals_module
    from . import targets as targets_engine
    from . import units
    from .labs import latest_results
    from .models import ProfileUpdate
    from .profile import apply_profile_changes, get_profile, target_settings

    today = today or date.today()
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    rnd = mulberry32(0x5EED2610)

    def pick(options: list[Any]) -> Any:
        return options[int(rnd() * len(options))]

    food = _food_finder(conn)
    items: list[tuple[int, date, str, str, float, str, str | None]] = []

    def add(day: date, meal: str, entries: Iterable[tuple[Any, ...]], *, status: str = "eaten", when: int | None = None,
            note: str | None = None) -> None:
        for i, entry in enumerate(entries):
            key, servings = entry[0], entry[1]
            item_note = entry[2] if len(entry) > 2 else None
            start = when if when is not None else _at(day, TIMES[meal])
            items.append((start + i * 60000 + len(items), day, meal, key, servings, status, item_note or (note if i == 0 else None)))

    for back in range(30, 0, -1):
        day = today - timedelta(days=back)
        breakfast, lunch, dinner = pick(BREAKFASTS), pick(LUNCHES), pick(DINNERS)
        snack_count = 2 if rnd() < 0.4 else 1
        snacks: Items = []
        for _ in range(snack_count):
            snacks.extend(pick(SNACKS))
        extra_water = rnd() < 0.5
        if back in EMPTY:
            continue
        sp = SPECIAL.get(back, {})
        add(day, "breakfast", sp.get("breakfast", breakfast))
        add(day, "lunch", sp.get("lunch", lunch))
        add(day, "dinner", sp.get("dinner", dinner))
        add(day, "snack", sp.get("snack", snacks))
        if extra_water:
            add(day, "snack", [("water", 1)], when=_at(day, 20.15))
        if sp.get("hypo"):
            add(day, "snack", [("glucose", 4)], when=_at(day, 17.5 if back == 4 else 10.4), note=sp["hypo"])
    # Today: breakfast and a bigger lunch eaten, an afternoon snack; dinner and an evening snack planned.
    add(today, "breakfast", BREAKFASTS[0])
    add(today, "lunch", [("chicken", 1), ("rice", 1), ("greenBeans", 1), ("oliveOil", 1), ("water", 1)])
    add(today, "snack", [("apple", 1), ("water", 1)])
    plan_night = _at(today - timedelta(days=1), 20.3)
    add(today, "dinner", [("cod", 0.75), ("rice", 1), ("cauliflower", 2), ("butter", 1), ("strawberries", 1), ("water", 1)],
        status="planned", when=plan_night)
    add(today, "snack", [("riceCakes", 1, "evening"), ("jam", 1)], status="planned", when=plan_night + 600000)
    # Three days ahead, planned this morning.
    plan_morning = _at(today, 7.15)
    ahead: list[dict[str, Items]] = [
        {"breakfast": BREAKFASTS[1], "lunch": LUNCHES[0], "dinner": DINNERS[2], "snack": [("grapes", 1)]},
        {"breakfast": BREAKFASTS[0], "lunch": LUNCHES[1], "dinner": DINNERS[1], "snack": [("vanillaWafers", 1)]},
        {"breakfast": BREAKFASTS[3], "dinner": DINNERS[0]},
    ]
    for i, plan in enumerate(ahead):
        day = today + timedelta(days=i + 1)
        for meal in MEALS:
            if meal in plan:
                add(day, meal, plan[meal], status="planned", when=plan_morning + (i * 4 + MEALS.index(meal)) * 120000)
    # Insert in time order; nothing is stamped in the future.
    items.sort(key=lambda it: it[0])
    last = 0
    cap = now_ms - 5 * 60000
    entries = 0
    for time_ms, day, meal, key, servings, status, note in items:
        row = food(key)
        if row is None:
            continue
        stamp = max(min(time_ms, cap), last + 1)
        last = stamp
        log_module.insert_entry(conn, user_id=user_id, date=day.isoformat(), meal=meal, food=row, servings=float(servings), grams=None,
                                note=note, status=status, purpose=log_module.resolve_purpose(row, None), created_at=_stamp(stamp))
        entries += 1
    # Saved meals.
    saved_at = _stamp(_at(today - timedelta(days=20), 21))
    saved = 0
    for name, note, plate in SAVED_MEALS:
        found = [(food(k), s) for k, s, *_ in plate]
        its = [{"food_id": int(f["id"]), "servings": float(s)} for f, s in found if f is not None]
        if its:
            meals_module.insert_template(conn, user_id=user_id, name=name, note=note, items=its, created_at=saved_at)
            saved += 1
    # Profile.
    apply_profile_changes(conn, user_id, ProfileUpdate(**PROFILE).model_dump(exclude_unset=True), get_profile(conn, user_id))
    # Lab results.
    for days_ago, analyte, value, unit, note in LABS:
        day = today - timedelta(days=days_ago)
        result = units.convert(analyte, value, unit)
        conn.execute("INSERT INTO lab_results (user_id, analyte, value, entered_value, entered_unit, taken_on, note, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user_id, result["analyte"], result["value"], result["entered_value"],
                                                         result["entered_unit"], day.isoformat(), note,
                                                         _stamp(min(_at(day, 17.3), cap))))
    # Weight and blood pressure: two weeks; exactly one weight (today's) is over the sample alarm, no reading near 180/120.
    for i, kg in enumerate(MORNING_KG):
        back = 14 - i
        day = today - timedelta(days=back)
        stamp = _stamp(min(_at(day, 7.15), cap))
        conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at) "
                     "VALUES (?, ?, '07:15', ?, 'morning', NULL, 'manual', NULL, ?, ?)", (user_id, day.isoformat(), kg, stamp, stamp))
        readings = [("07:20", "morning", 7.2, MORNING_BP[i])]
        if back in EVENING_BP:
            readings.append(("19:10", "evening", 19.1, EVENING_BP[back]))
        for clock_time, context, hhmm, (systolic, diastolic, pulse) in readings:
            stamp = _stamp(min(_at(day, hhmm), cap))
            conn.execute("INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, "
                         "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'manual', NULL, ?, ?)",
                         (user_id, day.isoformat(), clock_time, systolic, diastolic, pulse, context, stamp, stamp))
    for key, value in BODY_SETTINGS.items():
        try:
            store.set_user(conn, user_id, key, value)
        except Exception as exc:  # locked by the environment: the server's value applies
            log.info("test accounts: %s not set for tester: %s", key, exc)
    # Targets: what the suggestion gives for this person.
    profile = get_profile(conn, user_id)
    labs = latest_results(conn, user_id, targets_engine.TARGET_LABS)
    try:
        suggestion = targets_engine.suggest_from_records(profile, labs, today, **target_settings(conn, store))
    except (targets_engine.OutOfScope, ValueError) as exc:  # never for Sam; keep the defaults rather than fail the start
        log.warning("test accounts: no suggested targets for tester: %s", exc)
    else:
        apply_profile_changes(conn, user_id, ProfileUpdate(targets=suggestion["targets"]).model_dump(exclude_unset=True), profile)
    return {"entries": entries, "saved_meals": saved, "labs": len(LABS), "weights": len(MORNING_KG)}
