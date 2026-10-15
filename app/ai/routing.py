"""Which shared AI each feature uses: provider roles and per-feature routing (ROADMAP "Privacy tiers", tier 1).

The app can have several shared providers at once. An admin gives at most one of them the role **local**
(a host on the private network that :mod:`app.ai.netpolicy` accepts, such as Ollama on a home GPU) and at most
one the role **cloud** (anything else). Each AI feature is then pinned to a role:

=============  ==========================================================  ====================
feature        what it covers                                              consent purpose
=============  ==========================================================  ====================
``photos``     reading a nutrition label, the plate photo                  ``photos``
``meal_ideas`` next-meal ideas, their order, swaps, the day plan           ``text``
``describe``   turning a described meal into search words                  ``text``
``chat``       the Ask screen                                              ``chat``
=============  ==========================================================  ====================

Each feature is ``local``, ``cloud``, ``off`` or ``any`` (settings ``ai.route.<feature>``). **The default is the
least-trusting one, ``local``**: with no local provider the feature is off until an admin pins it to ``cloud``.
``any`` is the rule from before routing existed (the shared provider the person chose, else the first usable one).
A server that already had a provider when this was added starts every feature on ``any`` so nothing changes
(:func:`initialise`); a new server starts on the defaults.

Rules that keep "local" local:

* a provider can hold the role only while :func:`app.ai.netpolicy.is_private_host` says its host is private (checked
  when the role is set, when the provider's address is edited, and again before every call);
* a call to the local provider uses the network scope ``local`` (``ProviderConfig.local_only``), so the transport
  refuses any address that is not private, even if the name later resolves to a public one;
* ``off`` is off for everyone, including people with their own provider; a person's own provider is otherwise their
  own choice, counts as a cloud provider (the app lets people point only at public hosts) and is never replaced.

Consent, quota, the AI activity log and "What will be sent?" all use the provider the feature resolves to, so a
feature that moves to another provider asks for consent again for that provider.
"""
from __future__ import annotations

import dataclasses
import logging
import sqlite3
from typing import Any, Literal, Mapping

from ..config import Settings
from ..crypto import InvalidToken, Keyring
from ..db import get_meta, set_meta, table_exists
from ..settings_store import SettingLocked, SettingsStore
from . import config as K
from .netpolicy import NetPolicy, PolicyError, is_private_host, parse_base_url

log = logging.getLogger("kidney_health.ai")

Feature = Literal["photos", "meal_ideas", "describe", "chat"]
Role = Literal["local", "cloud"]
FEATURES: tuple[str, ...] = ("photos", "meal_ideas", "describe", "chat")
HEADLINE: tuple[str, ...] = ("meal_ideas", "describe", "photos", "chat")  # the status endpoint's top-level provider: the first that resolves
ROLES: tuple[str, ...] = ("local", "cloud")
ROUTES: tuple[str, ...] = ("local", "cloud", "off", "any")
# The consent purpose each feature is agreed under (ai_consents.purpose).
PURPOSE: dict[str, K.Purpose] = {"photos": "photos", "meal_ideas": "text", "describe": "text", "chat": "chat"}
LABEL = {"photos": "Photos (labels and plates)", "meal_ideas": "Meal ideas", "describe": "Describe a meal", "chat": "Ask"}
# What leaves the server for each feature, in the words of the admin warning and the consent sheet.
SENDS = {
    "photos": "your photos of labels and plates",
    "meal_ideas": "your meal data (stage, targets, today's totals and the foods the rules offered)",
    "describe": "the meals you describe in words",
    "chat": "your messages in Ask and the app's own numbers the AI looks up",
}
INITIALISED_KEY = "ai_routing_initialised"  # meta: set once, whichever way the first start-up decided


def route_key(feature: str) -> str:
    return f"ai.route.{feature}"


def role_key(role: str) -> str:
    return f"ai.route.{role}_provider"


def features_for_purpose(purpose: str) -> tuple[str, ...]:
    return tuple(f for f in FEATURES if PURPOSE[f] == purpose)


# --------------------------------------------------------------------------- #
# Which provider holds a role
# --------------------------------------------------------------------------- #


def role_row(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, role: str) -> sqlite3.Row | None:
    """The shared provider that holds ``role``, or None.

    The environment provider holds the role ``AI_PROVIDER_ROLE`` names (a server without sign-in cannot use the
    admin screen), and then holds no other; any other shared provider holds the role the setting names."""
    env_role = settings.ai.provider_role
    locked = K.shared_rows(conn)[:1]
    env_row = locked[0] if locked and locked[0]["locked"] else None
    if env_row is not None and env_role == role:
        return env_row
    try:
        provider_id = int(store.get(conn, role_key(role)) or 0)
    except (TypeError, ValueError):
        return None
    if provider_id <= 0:
        return None
    row = K.provider_row(conn, provider_id)
    if row is None or row["scope"] != "shared":
        return None
    if row["locked"] and env_role:
        return None
    return row


def role_of(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, row: Mapping[str, Any]) -> str | None:
    """The role ``row`` holds (``local`` wins if both settings name it), or None."""
    for role in ROLES:
        held = role_row(conn, store, settings, role)
        if held is not None and int(held["id"]) == int(row["id"]):
            return role
    return None


def is_private(row: Mapping[str, Any], policy: NetPolicy) -> bool:
    """Does the network policy treat this provider's host as private (the only hosts that may be local)?"""
    try:
        return is_private_host(parse_base_url(row["base_url"]), policy)
    except PolicyError:
        return False


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def resolve_feature(conn: sqlite3.Connection, store: SettingsStore, keyring: Keyring, settings: Settings, policy: NetPolicy, *,
                    user_id: int, can_use_shared: bool, feature: str, require_opt_in: bool = True) -> K.Resolved:
    """Which provider serves ``feature`` for ``user_id`` now (no quota is taken, nothing is sent)."""
    if not store.get(conn, "ai.enabled"):
        return K.Resolved(None, None, "disabled", feature=feature)
    prefs = K.ai_prefs(conn, store, user_id)
    if require_opt_in and not prefs.get("opt_in"):
        return K.Resolved(None, None, "not_opted_in", feature=feature)
    route = str(store.get(conn, route_key(feature)))
    if route == "off":
        return K.Resolved(None, None, "feature_off", feature=feature, route=route)
    if str(prefs.get("provider") or "auto") == "own" or route == "any":
        # A person's own provider is their choice; "any" is the rule from before routing existed.
        resolved = K.resolve(conn, store, keyring, settings, user_id=user_id, can_use_shared=can_use_shared, require_opt_in=require_opt_in)
        resolved.feature, resolved.route = feature, route
        if resolved.cfg is None:
            return resolved
        if resolved.cfg.scope == "user":
            resolved.role = "own"
            return resolved
        return _holding(conn, store, settings, policy, resolved)
    if not K.shared_rows(conn):
        return K.Resolved(None, None, "not_configured", feature=feature, route=route)
    if not can_use_shared:
        return K.Resolved(None, None, "not_allowed", feature=feature, route=route)
    row = role_row(conn, store, settings, route)
    if row is None:
        return K.Resolved(None, None, f"no_{route}_provider", feature=feature, route=route)
    if not K.usable(row):
        return K.Resolved(row, None, "provider_disabled", feature=feature, route=route)
    try:
        cfg = K.to_config(row, keyring, settings, user_id=user_id)
    except InvalidToken:
        log.warning("the key of shared AI provider %s cannot be decrypted with the current SECRET_KEY; set it again", row["id"])
        return K.Resolved(row, None, "provider_disabled", feature=feature, route=route)
    return _holding(conn, store, settings, policy, K.Resolved(row, cfg, None, feature=feature, route=route))


def _holding(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, policy: NetPolicy, resolved: K.Resolved) -> K.Resolved:
    """Note the role the chosen shared provider holds; a local one must still be private, and is pinned to private addresses."""
    assert resolved.row is not None and resolved.cfg is not None
    role = role_of(conn, store, settings, resolved.row)
    resolved.role = role
    if role == "local":
        if not is_private(resolved.row, policy):
            return K.Resolved(resolved.row, None, "local_not_private", feature=resolved.feature, route=resolved.route, role=role)
        resolved.cfg = dataclasses.replace(resolved.cfg, local_only=True)
    return resolved


def pin_if_local(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, row: Mapping[str, Any], cfg: Any) -> Any:
    """The connection tests too stay on the private network when the provider holds the local role."""
    if role_of(conn, store, settings, row) == "local":
        return dataclasses.replace(cfg, local_only=True)
    return cfg


def resolve_all(conn: sqlite3.Connection, store: SettingsStore, keyring: Keyring, settings: Settings, policy: NetPolicy, *,
                user_id: int, can_use_shared: bool, require_opt_in: bool = True) -> dict[str, K.Resolved]:
    return {f: resolve_feature(conn, store, keyring, settings, policy, user_id=user_id, can_use_shared=can_use_shared,
                               feature=f, require_opt_in=require_opt_in) for f in FEATURES}


# --------------------------------------------------------------------------- #
# What a person is told
# --------------------------------------------------------------------------- #

_MISSING = {
    "no_local_provider": "Needs a local AI, which is not set up on this server, so it is off.",
    "no_cloud_provider": "Needs a cloud AI, which your admin has not chosen, so it is off.",
    "local_not_private": "Its local AI is not on a private address any more, so it is off.",
    "feature_off": "Switched off by your admin.",
}


def runs_on_text(resolved: K.Resolved) -> str:
    """One line for Settings and the Add view: where this feature runs (or why it does not)."""
    cfg = resolved.cfg
    if cfg is None:
        return _MISSING.get(resolved.reason or "") or K.MESSAGES.get(resolved.reason or "", "Not available.")
    if resolved.role == "local":
        return f"Runs on your local AI ({cfg.host})."
    if resolved.role == "own":
        return f"Runs on your own AI provider, {cfg.label} ({cfg.host}), outside your network."
    if resolved.role == "cloud":
        return f"Runs on {cfg.label} ({cfg.host}), a cloud AI outside your network."
    return f"Runs on {cfg.label} ({cfg.host})."


def provider_summary(cfg: Any) -> dict[str, Any]:
    from .presets import policy_line

    return {"id": cfg.id, "label": cfg.label, "host": cfg.host, "model": cfg.model, "vision_model": cfg.vision_model,
            "scope": cfg.scope, "kind": cfg.preset_def.kind, "policy": policy_line(cfg.preset_def, scope=cfg.scope)}


def route_view(conn: sqlite3.Connection, user_id: int, feature: str, resolved: K.Resolved, *, consent: bool = True) -> dict[str, Any]:
    """The status endpoint's entry for one feature."""
    cfg = resolved.cfg
    out: dict[str, Any] = {
        "feature": feature, "label": LABEL[feature], "purpose": PURPOSE[feature], "route": resolved.route,
        "role": resolved.role, "available": cfg is not None, "reason": resolved.reason,
        "message": K.MESSAGES.get(resolved.reason) if resolved.reason else None,
        "text": runs_on_text(resolved), "runs_on": None if cfg is None else provider_summary(cfg),
    }
    if consent:
        out["consent"] = None if cfg is None else K.consent(conn, user_id, cfg, PURPOSE[feature])
    return out


def me_summary(routes: Mapping[str, K.Resolved], conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """Settings → AI: one line per feature (no consent detail)."""
    return [route_view(conn, user_id, f, routes[f], consent=False) for f in FEATURES]


# --------------------------------------------------------------------------- #
# The first start-up (the upgrade rule)
# --------------------------------------------------------------------------- #


def initialise(conn: sqlite3.Connection, store: SettingsStore) -> str | None:
    """Decide once per database how routing starts (no commit; call before the environment provider is synced).

    A database that already has a shared provider belongs to a server that was using it for every feature: each
    feature starts on ``any``, which changes nothing until an admin opens Server administration → AI providers and chooses.
    A database with no shared provider has nothing to preserve and starts on the least-trusting defaults.
    Returns ``as_before`` or ``least_trust`` the first time, None after that."""
    if not table_exists(conn, "ai_providers") or not store.tables_exist(conn) or get_meta(conn, INITIALISED_KEY):
        return None
    has_provider = conn.execute("SELECT 1 FROM ai_providers WHERE scope = 'shared' LIMIT 1").fetchone() is not None
    if has_provider:
        for feature in FEATURES:
            definition = store.definition(route_key(feature))
            if store.env_value(definition)[0] or store.effective(conn, route_key(feature)).source == "instance":
                continue
            store.set_instance(conn, route_key(feature), "any")
    verdict = "as_before" if has_provider else "least_trust"
    set_meta(conn, INITIALISED_KEY, verdict)
    return verdict


# --------------------------------------------------------------------------- #
# Server administration
# --------------------------------------------------------------------------- #


def overview(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, policy: NetPolicy) -> dict[str, Any]:
    """GET /api/admin/ai-routing: the table "Which AI does each feature use?"."""
    features = []
    for feature in FEATURES:
        eff = store.effective(conn, route_key(feature))
        features.append({"feature": feature, "label": LABEL[feature], "sends": SENDS[feature], "route": eff.value,
                         "source": eff.source, "locked_by_env": eff.env if eff.locked else None})
    roles: dict[str, Any] = {}
    for role in ROLES:
        row = role_row(conn, store, settings, role)
        roles[role] = None if row is None else {"id": int(row["id"]), "label": row["label"],
                                                "host": parse_base_url(row["base_url"]).display_host,
                                                "private": is_private(row, policy)}
    providers = []
    for row in K.shared_rows(conn):
        providers.append({"id": int(row["id"]), "label": row["label"], "host": parse_base_url(row["base_url"]).display_host,
                          "private": is_private(row, policy), "role": role_of(conn, store, settings, row),
                          "photos": bool(row["vision_model"]), "usable": K.usable(row), "locked": bool(row["locked"])})
    return {
        "features": features, "roles": roles, "providers": providers, "env_role": settings.ai.provider_role,
        "as_before": any(f["route"] == "any" for f in features),
        "defaults": {f: "local" for f in FEATURES},
        "writable": settings.auth_mode != "none",
    }


class RoutingError(ValueError):
    """The change is refused; ``status`` is the HTTP status, ``field`` the body field to point at."""

    def __init__(self, message: str, *, status: int = 400, field: str | None = None, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.field, self.extra = status, field, extra


def plan(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, policy: NetPolicy, *,
         features: Mapping[str, str], providers: Mapping[str, int]) -> dict[str, Any]:
    """Validate a routing change and return ``{setting key: new value}`` (:class:`RoutingError` if refused).

    ``providers`` maps a role to a shared provider id (0 clears it). A local provider must be private by the
    network policy; one provider cannot hold both roles; locked settings and the environment provider's role
    cannot be changed here."""
    changes: dict[str, Any] = {}
    for feature, route in features.items():
        key = route_key(feature)
        if store.env_value(store.definition(key))[0]:
            raise RoutingError(f"{feature} is set by the server ({store.definition(key).env}) and cannot be changed here.", status=409, field=feature, locked=True)
        changes[key] = route
    env_role = settings.ai.provider_role
    for role, provider_id in providers.items():
        key = role_key(role)
        if role == env_role:
            raise RoutingError(f"The {role} AI is the server's own provider (AI_PROVIDER_ROLE={role}); it cannot be changed here.",
                               status=409, field=f"{role}_provider", locked=True)
        if provider_id:
            row = K.provider_row(conn, provider_id)
            if row is None or row["scope"] != "shared":
                raise RoutingError(f"AI provider {provider_id} not found", status=404, field=f"{role}_provider")
            if row["locked"] and env_role:
                raise RoutingError(f"The server's own provider has its role from AI_PROVIDER_ROLE={env_role}; it cannot hold another.",
                                   status=409, field=f"{role}_provider", locked=True)
            if role == "local" and not is_private(row, policy):
                raise RoutingError(
                    f"{parse_base_url(row['base_url']).host_port} is not a private host, so it cannot be the local AI. "
                    "Only a provider on your own network can be: list its host:port in AI_PRIVATE_HOSTS first (docs/ai.md).",
                    field="local_provider", reason="not_private")
        changes[key] = int(provider_id)
    local = int(changes.get(role_key("local"), store.get(conn, role_key("local")) or 0))
    cloud = int(changes.get(role_key("cloud"), store.get(conn, role_key("cloud")) or 0))
    if local and local == cloud:
        raise RoutingError("One provider cannot be both the local and the cloud AI.", field="cloud_provider", reason="same_provider")
    return changes


def apply(conn: sqlite3.Connection, store: SettingsStore, changes: Mapping[str, Any], *, updated_by: int | None) -> list[tuple[str, Any, Any]]:
    """Write a validated change (no commit); returns ``(key, old, new)`` for the audit log."""
    try:
        return store.update_instance(conn, changes, updated_by=updated_by)
    except SettingLocked as exc:
        raise RoutingError(str(exc), status=409, locked=True) from None


def drop_role(conn: sqlite3.Connection, store: SettingsStore, provider_id: int, *, updated_by: int | None) -> list[str]:
    """A shared provider is being deleted: clear any role setting that names it (no commit). Returns the roles cleared."""
    cleared = []
    for role in ROLES:
        if int(store.get(conn, role_key(role)) or 0) == int(provider_id):
            store.set_instance(conn, role_key(role), None, updated_by=updated_by)
            cleared.append(role)
    return cleared
