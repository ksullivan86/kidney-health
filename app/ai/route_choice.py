"""A person's own choice of the server's local or cloud AI, per feature (design note 32; docs/ai.md "Choosing the server's local
or cloud AI yourself").

Three things must all hold for a choice to count, and they are read from the database on every request, never from the page:

1. the server switch ``ai.person_route_choice`` (``AI_PERSON_ROUTE_CHOICE_ENABLED``), default off;
2. the person's privilege ``users.can_choose_ai`` (schema step 33), which only an admin sets in Server administration → Users;
3. the person's setting ``ai.route_choice``: ``default``, ``local`` or ``cloud`` for each of :data:`FEATURES`.

When the switch or the privilege goes, the stored choices are kept and ignored (decision 5 of the note): from the next request the
person is back on the admin's routes. :func:`app.ai.routing.resolve_feature` reads :func:`choice_for`; everything else it does
(``off`` for everyone, lab report photos local-only, a person's own provider first, consent, the privacy filter) is unchanged.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from ..audit import audit
from ..settings_store import SettingsStore

SWITCH = "ai.person_route_choice"
SETTING = "ai.route_choice"
# The features a person may choose for: every routed feature except the local-only lab report photos (routing.LOCAL_ONLY), which are
# never offered, never stored (the setting has no field for them) and never read here.
FEATURES: tuple[str, ...] = ("photos", "meal_ideas", "describe", "chat", "recipes")
CHOICES: tuple[str, ...] = ("default", "local", "cloud")
ROLES: tuple[str, ...] = ("local", "cloud")

NOT_ALLOWED = "Your admin has not let you choose which of the server's AIs you use."


def has_privilege(conn: sqlite3.Connection, user_id: int) -> bool:
    """The admin's tick for this person (``users.can_choose_ai``). False on a database without the column."""
    try:
        row = conn.execute("SELECT can_choose_ai FROM users WHERE id = ?", (int(user_id),)).fetchone()
    except sqlite3.OperationalError:  # below schema step 33
        return False
    return bool(row is not None and row["can_choose_ai"])


def allowed(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> bool:
    """The server switch is on and the admin ticked this person."""
    return bool(store.get(conn, SWITCH)) and has_privilege(conn, user_id)


def stored(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> dict[str, str]:
    """What the person chose, as stored (``default`` for every feature they never chose)."""
    value = store.get(conn, SETTING, user_id)
    data = value.model_dump() if hasattr(value, "model_dump") else dict(value or {})
    return {f: str(data.get(f) or "default") for f in FEATURES}


def choice_for(conn: sqlite3.Connection, store: SettingsStore, user_id: int, feature: str) -> str | None:
    """``local`` or ``cloud`` when the person's choice counts for ``feature`` now, else None (the admin's route applies)."""
    if feature not in FEATURES or not allowed(conn, store, user_id):
        return None
    choice = stored(conn, store, user_id)[feature]
    return choice if choice in ROLES else None


def write(conn: sqlite3.Connection, store: SettingsStore, user_id: int, changes: Mapping[str, str], *, ip: str | None) -> list[tuple[str, str, str]]:
    """Save the changed features (no commit) and record each change in the person's activity list. Returns ``(feature, old, new)``.
    The caller has checked :func:`allowed` and what each choice may be."""
    before = stored(conn, store, user_id)
    after = {**before, **{f: str(v) for f, v in changes.items()}}
    store.set_user(conn, user_id, SETTING, after)
    changed = [(f, before[f], after[f]) for f in FEATURES if before[f] != after[f]]
    for feature, old, new in changed:
        audit(conn, user_id, "ai.route_choice_changed", None, None, ip=ip, feature=feature, old=old, new=new)
    return changed


def view(conn: sqlite3.Connection, store: SettingsStore, user_id: int, *, roles: Mapping[str, Any], admin_routes: Mapping[str, str],
         own: bool) -> dict[str, Any] | None:
    """``GET /api/me/ai`` → ``route_choice``: None unless the person may choose now. ``roles`` maps ``local``/``cloud`` to
    ``{label, host}`` or None (only the AI that exists is offered); ``admin_routes`` is the admin's route per feature (a feature
    that is ``off`` is off for everyone and has no choice); ``own``: the person uses their own provider, which wins."""
    if not allowed(conn, store, user_id):
        return None
    from .routing import LABEL  # routing imports this module

    choices = stored(conn, store, user_id)
    return {
        "choices": choices,
        "features": [{"feature": f, "label": LABEL[f], "choice": choices[f], "admin_off": admin_routes.get(f) == "off"} for f in FEATURES],
        "local": roles.get("local"),
        "cloud": roles.get("cloud"),
        "own_wins": own,
    }
