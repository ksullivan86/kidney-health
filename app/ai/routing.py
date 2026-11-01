"""Which shared AI each feature uses: provider roles and per-feature routing (ROADMAP "Privacy tiers", tier 1).

The app can have several shared providers at once. An admin gives at most one of them the role **local**
(a host on the private network that :mod:`app.ai.netpolicy` accepts, such as Ollama on a home GPU) and at most
one the role **cloud** (anything else). Both can come from the environment: ``AI_PROVIDER`` with ``AI_PROVIDER_ROLE=local``,
and ``AI_CLOUD_PROVIDER``, whose role is always cloud (a LiteLLM proxy on the LAN may be the cloud AI; it is then listed in
``AI_PRIVATE_HOSTS`` like any shared provider, but it is not the local AI and never serves ``labs``). Each AI feature is then
pinned to a role:

=============  ==========================================================  ====================
feature        what it covers                                              consent purpose
=============  ==========================================================  ====================
``photos``     reading a nutrition label, the plate photo                  ``photos``
``meal_ideas`` next-meal ideas, their order, swaps, the day plan           ``text``
``describe``   turning a described meal into search words                  ``text``
``chat``       the Ask screen                                              ``chat``
``labs``       reading a photo of a lab report                             ``labs``
``recipes``    AI recipes: suggest one, or rework a saved recipe           ``text``
=============  ==========================================================  ====================

Each feature is ``local``, ``cloud``, ``off`` or ``any`` (settings ``ai.route.<feature>``), except ``labs``, which is
``local`` or ``off`` only (see below). **The default is the
least-trusting one, ``local``**: with no local provider the feature is off until an admin pins it to ``cloud``.
``any`` is the rule from before routing existed (the shared provider the person chose, else the first usable one).
A server that already had a provider when this was added starts every feature on ``any`` so nothing changes
(:func:`initialise`); a new server starts on the defaults.

**Tier 3, ``local_then_cloud``** (:data:`FALLBACK_ROUTE`): the structured features (``photos``, ``meal_ideas``, ``describe``,
``recipes``) can
also be ``local_then_cloud``: the call goes to the local AI first, exactly as with ``local``, and the cloud AI is asked a
second time **only when the local AI's answer fails the schema or the app's rules** (the validator or the judge rejects it).
It is not asked when the local AI cannot be reached, takes too long, is over its quota or declines the question: those answer
as with ``local``. Ask (a conversation of several calls) and ``labs`` (local-only) never take it. Both roles must be held for
the fallback to exist: with no usable cloud AI the feature behaves as ``local``, with no local AI it is off (as ``local``
is). The person must also have agreed to send that purpose to the cloud host; without it nothing is sent there
(:func:`app.ai.routes.run_call`). A person's own provider is their own choice and is never a fallback and never given one.

Rules that keep "local" local:

* a provider can hold the role only while :func:`app.ai.netpolicy.is_private_host` says its host is private (checked
  when the role is set, when the provider's address is edited, and again before every call);
* a call to the local provider uses the network scope ``local`` (``ProviderConfig.local_only``), so the transport
  refuses any address that is not private, even if the name later resolves to a public one;
* ``labs`` is **local-only**: a lab report photo can show a name, a date of birth and record numbers that the app cannot
  remove from an image, so the setting accepts only ``local`` and ``off``, a person's own provider is never used for it
  (even one they chose), the upgrade rule never sets it to ``any``, and with no usable local provider it is off
  (:data:`LOCAL_ONLY`);
* ``off`` is off for everyone, including people with their own provider; a person's own provider is otherwise their
  own choice, counts as a cloud provider (the app lets people point only at public hosts) and is never replaced.

Consent, quota, the AI activity log and "What will be sent?" all use the provider the feature resolves to, so a
feature that moves to another provider asks for consent again for that provider.

**Tier 2, the privacy filter** (:mod:`app.ai.privacy_filter`, note 31) adds to these rules and never replaces them: every
provider this resolves that is not pinned to the private network gets the account's known names
(``ProviderConfig.privacy_terms``), and the client filters every request to it. Nothing here changes because of the filter:
a local-only feature stays local-only, and a feature that is off stays off.
"""
from __future__ import annotations

import dataclasses
import logging
import sqlite3
from typing import Any, Literal, Mapping

from .. import brand, test_accounts
from ..config import Settings
from ..crypto import InvalidToken, Keyring
from ..db import get_meta, set_meta, table_exists
from ..settings_store import SettingLocked, SettingsStore
from . import config as K
from . import privacy_filter
from .netpolicy import NetPolicy, PolicyError, is_private_host, parse_base_url

log = logging.getLogger(f"{brand.LOGGER_NAME}.ai")

Feature = Literal["photos", "meal_ideas", "describe", "chat", "labs", "recipes"]
Role = Literal["local", "cloud"]
FEATURES: tuple[str, ...] = ("photos", "meal_ideas", "describe", "chat", "labs", "recipes")
# Features that run only on the local AI: their route is ``local`` or ``off`` (the setting refuses the rest), and neither a
# person's own provider nor the pre-routing rule ``any`` ever serves them.
LOCAL_ONLY: tuple[str, ...] = ("labs",)
LOCAL_ONLY_ROUTES: tuple[str, ...] = ("local", "off")
# Tier 3: "local first, cloud only when the local answer fails". Only the features whose answer is one structured reply that the
# app checks in code (the validator, then the judge) can use it; Ask is a loop of calls and a lab report never leaves the network.
FALLBACK_ROUTE = "local_then_cloud"
FALLBACK_FEATURES: tuple[str, ...] = ("photos", "meal_ideas", "describe", "recipes")
HEADLINE: tuple[str, ...] = ("meal_ideas", "describe", "photos", "chat")  # the status endpoint's top-level provider: the first that resolves
ROLES: tuple[str, ...] = ("local", "cloud")
ROUTES: tuple[str, ...] = ("local", "cloud", "off", "any")
# The consent purpose each feature is agreed under (ai_consents.purpose).
PURPOSE: dict[str, K.Purpose] = {"photos": "photos", "meal_ideas": "text", "describe": "text", "chat": "chat", "labs": "labs",
                                  "recipes": "text"}
LABEL = {"photos": "Photos (labels and plates)", "meal_ideas": "Meal ideas", "describe": "Describe a meal", "chat": "Ask",
         "labs": "Lab report photos", "recipes": "Recipes"}
# What leaves the server for each feature, in the words of the admin warning and the consent sheet.
SENDS = {
    "photos": "your photos of labels and plates",
    "meal_ideas": "your meal data (stage, targets, today's totals and the foods the rules offered)",
    "describe": "the meals you describe in words",
    "chat": "your messages in Ask and the app's own numbers the AI looks up",
    "labs": "your photos of lab reports (which can show your name, date of birth and record numbers)",
    "recipes": "your meal data and the foods and amounts of a recipe (never its name, note, steps or link)",
}
INITIALISED_KEY = "ai_routing_initialised"  # meta: set once, whichever way the first start-up decided


def route_key(feature: str) -> str:
    return f"ai.route.{feature}"


def role_key(role: str) -> str:
    return f"ai.route.{role}_provider"


def features_for_purpose(purpose: str) -> tuple[str, ...]:
    return tuple(f for f in FEATURES if PURPOSE[f] == purpose)


def allowed_routes(feature: str) -> tuple[str, ...]:
    """The routes the setting accepts for ``feature``: every feature but the local-only ones also takes ``cloud`` and ``any``,
    and the structured ones (:data:`FALLBACK_FEATURES`) also ``local_then_cloud``."""
    if feature in LOCAL_ONLY:
        return LOCAL_ONLY_ROUTES
    return (*ROUTES, FALLBACK_ROUTE) if feature in FALLBACK_FEATURES else ROUTES


# --------------------------------------------------------------------------- #
# Which provider holds a role
# --------------------------------------------------------------------------- #


def role_row(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, role: str) -> sqlite3.Row | None:
    """The shared provider that holds ``role``, or None.

    The environment provider ``AI_CLOUD_PROVIDER`` is always the cloud AI, and holds no other role. The environment provider
    ``AI_PROVIDER`` holds the role ``AI_PROVIDER_ROLE`` names (a server without sign-in cannot use the admin screen), and then
    holds no other; any other shared provider holds the role the setting names."""
    env_role = settings.ai.provider_role
    cloud_env = K.env_row(conn, "cloud")
    if role == "cloud" and cloud_env is not None:
        return cloud_env
    main_env = K.env_row(conn, "main")
    if main_env is not None and env_role == role:
        return main_env
    try:
        provider_id = int(store.get(conn, role_key(role)) or 0)
    except (TypeError, ValueError):
        return None
    if provider_id <= 0:
        return None
    row = K.provider_row(conn, provider_id)
    if row is None or row["scope"] != "shared":
        return None
    if row["locked"] and (K.env_slot_of(row) == "cloud" or env_role):
        return None  # an environment provider's role is the environment's to give, never a setting's
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
    """Which provider serves ``feature`` for ``user_id`` now (no quota is taken, nothing is sent). A provider that is not local
    (and a cloud fallback) carries the account's known names for the privacy filter."""
    resolved = _resolve_feature(conn, store, keyring, settings, policy, user_id=user_id, can_use_shared=can_use_shared,
                                feature=feature, require_opt_in=require_opt_in)
    return with_privacy_terms(conn, user_id, resolved)


def with_privacy_terms(conn: sqlite3.Connection, user_id: int, resolved: K.Resolved) -> K.Resolved:
    """Attach :func:`app.ai.privacy_filter.known_terms` to every provider of ``resolved`` the filter runs for. The provider
    choice itself is never changed."""
    targets = [r for r in (resolved, resolved.fallback) if r is not None and r.cfg is not None and privacy_filter.applies(r.cfg)]
    if not targets:
        return resolved
    terms = privacy_filter.known_terms(conn, user_id)
    for item in targets:
        item.cfg = dataclasses.replace(item.cfg, privacy_terms=terms)
    return resolved


def _resolve_feature(conn: sqlite3.Connection, store: SettingsStore, keyring: Keyring, settings: Settings, policy: NetPolicy, *,
                     user_id: int, can_use_shared: bool, feature: str, require_opt_in: bool = True) -> K.Resolved:
    if not store.get(conn, "ai.enabled") or not test_accounts.ai_allowed(conn, store, user_id):
        return K.Resolved(None, None, "disabled", feature=feature)
    prefs = K.ai_prefs(conn, store, user_id)
    if require_opt_in and not prefs.get("opt_in"):
        return K.Resolved(None, None, "not_opted_in", feature=feature)
    route = str(store.get(conn, route_key(feature)))
    if route == "off" or (feature in LOCAL_ONLY and route != "local"):  # a local-only feature is local or off, nothing in between
        return K.Resolved(None, None, "feature_off", feature=feature, route="off")
    if feature not in LOCAL_ONLY and (str(prefs.get("provider") or "auto") == "own" or route == "any"):
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
    # ``local_then_cloud`` starts on the local AI, exactly as ``local`` does (same reasons when there is none); the cloud AI is only
    # looked up afterwards, as the second call's provider.
    fallback_wanted = route == FALLBACK_ROUTE and feature in FALLBACK_FEATURES
    role = "local" if route == FALLBACK_ROUTE else route
    row = role_row(conn, store, settings, role)
    if row is None:
        return K.Resolved(None, None, f"no_{role}_provider", feature=feature, route=route)
    if not K.usable(row):
        return K.Resolved(row, None, "provider_disabled", feature=feature, route=route)
    try:
        cfg = K.to_config(row, keyring, settings, user_id=user_id)
    except InvalidToken:
        log.warning("the key of shared AI provider %s cannot be decrypted with the current SECRET_KEY; set it again", row["id"])
        return K.Resolved(row, None, "provider_disabled", feature=feature, route=route)
    held = _holding(conn, store, settings, policy, K.Resolved(row, cfg, None, feature=feature, route=route))
    if feature in LOCAL_ONLY and held.cfg is not None and not (held.role == "local" and held.cfg.local_only):
        # Belt and braces: whatever the settings say, a local-only feature is never served by a provider that is not pinned to the private network.
        return K.Resolved(row, None, "local_not_private", feature=feature, route=route, role=held.role)
    if fallback_wanted and held.cfg is not None:
        held.fallback = _cloud_fallback(conn, store, keyring, settings, user_id=user_id, feature=feature, first=row)
    return held


def _cloud_fallback(conn: sqlite3.Connection, store: SettingsStore, keyring: Keyring, settings: Settings, *, user_id: int,
                    feature: str, first: Mapping[str, Any]) -> K.Resolved | None:
    """The shared provider holding the role ``cloud``, as the second call of a ``local_then_cloud`` feature, or None (the feature
    then behaves as ``local``): no cloud provider chosen, it is switched off, its key cannot be read, or it is not a cloud-only
    holder (the local AI is never its own fallback). A person's own provider is never a fallback. Nothing is sent from here."""
    row = role_row(conn, store, settings, "cloud")
    if row is None or int(row["id"]) == int(first["id"]) or not K.usable(row) or role_of(conn, store, settings, row) != "cloud":
        return None
    try:
        cfg = K.to_config(row, keyring, settings, user_id=user_id)
    except InvalidToken:
        log.warning("the key of shared AI provider %s cannot be decrypted with the current SECRET_KEY; set it again", row["id"])
        return None
    return K.Resolved(row, cfg, None, feature=feature, route=FALLBACK_ROUTE, role="cloud")


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


LABS_NEEDS_LOCAL = "Needs a local AI on your own network, which is not set up on this server, so it is off."


def runs_on_text(resolved: K.Resolved) -> str:
    """One line for Settings and the Add view: where this feature runs (or why it does not)."""
    cfg = resolved.cfg
    if cfg is None:
        if resolved.feature in LOCAL_ONLY and resolved.reason in ("no_local_provider", "not_configured"):
            return LABS_NEEDS_LOCAL
        return _MISSING.get(resolved.reason or "") or K.MESSAGES.get(resolved.reason or "", "Not available.")
    if resolved.role == "local":
        fallback = resolved.fallback.cfg if resolved.fallback is not None else None
        if fallback is not None:  # local_then_cloud with a usable cloud AI (tier 3)
            return f"Runs on your local AI ({cfg.host}); if its answer fails the app's checks, on the cloud AI ({fallback.host})."
        return f"Runs on your local AI ({cfg.host})."
    if resolved.role == "own":
        return f"Runs on your own AI provider, {cfg.label} ({cfg.host}), outside your network."
    if resolved.role == "cloud":
        return f"Runs on {cfg.label} ({cfg.host}), a cloud AI outside your network."
    return f"Runs on {cfg.label} ({cfg.host})."


def provider_summary(cfg: Any) -> dict[str, Any]:
    from .presets import policy_line

    return {"id": cfg.id, "label": cfg.label, "host": cfg.host, "model": cfg.model, "vision_model": cfg.vision_model,
            "scope": cfg.scope, "kind": cfg.preset_def.kind, "policy": policy_line(cfg.preset_def, scope=cfg.scope, upstream=cfg.upstream)}


def route_view(conn: sqlite3.Connection, user_id: int, feature: str, resolved: K.Resolved, *, consent: bool = True) -> dict[str, Any]:
    """The status endpoint's entry for one feature."""
    cfg = resolved.cfg
    out: dict[str, Any] = {
        "feature": feature, "label": LABEL[feature], "purpose": PURPOSE[feature], "route": resolved.route,
        "role": resolved.role, "available": cfg is not None, "reason": resolved.reason,
        "message": K.MESSAGES.get(resolved.reason) if resolved.reason else None,
        "text": runs_on_text(resolved), "runs_on": None if cfg is None else provider_summary(cfg),
    }
    # Tier 3: the cloud AI that is asked only if the local answer fails the app's checks (None for every other route).
    # ``given``: whether the person agreed to send this purpose to the cloud host (without it the cloud AI is never asked);
    # ``request``: the sheet Settings shows when they want to agree later.
    fallback = resolved.fallback.cfg if resolved.fallback is not None else None
    given = None if fallback is None else K.consent(conn, user_id, fallback, PURPOSE[feature])
    out["fallback"] = None if fallback is None else {
        "runs_on": provider_summary(fallback), "rule": K.FALLBACK_RULE, "given": given is not None,
        "request": {**K.consent_request(fallback, PURPOSE[feature]), "as_fallback": True, "rule": K.FALLBACK_RULE}}
    if consent:
        out["consent"] = None if cfg is None else K.consent(conn, user_id, cfg, PURPOSE[feature])
        if fallback is not None:
            out["fallback"]["consent"] = given
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
    A local-only feature (``labs``) never starts on ``any``: it starts on ``local``, whatever the server did before.
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
            # A local-only feature (a lab report photo) is new with routing: nothing was ever served "as before", so it starts
            # on the least-trusting setting, written out so that it does not depend on the registry default.
            store.set_instance(conn, route_key(feature), "local" if feature in LOCAL_ONLY else "any")
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
                         "source": eff.source, "locked_by_env": eff.env if eff.locked else None,
                         "allowed": list(allowed_routes(feature))})
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
                          "photos": bool(row["vision_model"]), "usable": K.usable(row), "locked": bool(row["locked"]),
                          "env": K.env_var(row)})
    return {
        "features": features, "roles": roles, "providers": providers, "env_role": settings.ai.provider_role,
        "env_cloud": bool(settings.ai.cloud.provider),  # AI_CLOUD_PROVIDER is set: the cloud AI is the server's own and is fixed
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
        if route not in allowed_routes(feature):
            if feature in LOCAL_ONLY:
                raise RoutingError(f"{LABEL[feature]} can only be local or off: a lab report can show your name, date of birth and record "
                                   "numbers, which cannot be removed from a photo, so it is never sent to a cloud AI.",
                                   field=feature, reason="local_only")
            if route == FALLBACK_ROUTE:
                raise RoutingError(f"{LABEL[feature]} cannot be local, then cloud: an Ask conversation is several AI calls in a row, so "
                                   "the app cannot start it on the local AI and finish it on the cloud AI. Choose local or cloud.",
                                   field=feature, reason="no_fallback")
            raise RoutingError(f"{LABEL[feature]} cannot be {route}.", field=feature, reason="route_not_allowed")
        if store.env_value(store.definition(key))[0]:
            raise RoutingError(f"{feature} is set by the server ({store.definition(key).env}) and cannot be changed here.", status=409, field=feature, locked=True)
        changes[key] = route
    env_role = settings.ai.provider_role
    for role, provider_id in providers.items():
        key = role_key(role)
        if role == "cloud" and settings.ai.cloud.provider:
            raise RoutingError("The cloud AI is the server's own provider (AI_CLOUD_PROVIDER); it cannot be changed here.",
                               status=409, field="cloud_provider", locked=True)
        if role == env_role:
            raise RoutingError(f"The {role} AI is the server's own provider (AI_PROVIDER_ROLE={role}); it cannot be changed here.",
                               status=409, field=f"{role}_provider", locked=True)
        if provider_id:
            row = K.provider_row(conn, provider_id)
            if row is None or row["scope"] != "shared":
                raise RoutingError(f"AI provider {provider_id} not found", status=404, field=f"{role}_provider")
            if row["locked"] and K.env_slot_of(row) == "cloud":
                raise RoutingError("The server's own cloud provider (AI_CLOUD_PROVIDER) is always the cloud AI; it cannot hold another role.",
                                   status=409, field=f"{role}_provider", locked=True)
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
