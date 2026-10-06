"""AI providers, resolution, quotas, consent and the AI activity log (note 04 R4, R9; §9 A1, A5–A8).

Configuration comes from two places only (contract item 2, note 07):

* **The settings registry** (``app/settings_registry.py``, "Note 04" block): the instance switches
  ``ai.*`` (env locks ``AI_ENABLED``, ``AI_ALLOW_USER_KEYS``, …) and each person's ``ai`` object
  (opt-in, provider choice, preferences, ``share_age_sex``; **no key field**, §9 A6).
* **The environment** (``app.config.AiEnv``): the server-defined provider (``AI_PROVIDER``,
  ``AI_BASE_URL``, ``AI_API_KEY[_FILE]``, ``AI_MODEL``, …) and the network policy (``AI_PRIVATE_HOSTS``,
  ``AI_DENY_CIDRS``, ``AI_HTTP_PROXY``, ``AI_MAX_RESPONSE_BYTES``), which are never runtime-editable.

Providers are rows of ``ai_providers`` (schema step 6): shared ones (an admin's, or the env provider,
``locked = 1``, kept in step with the environment at start-up; its key is never stored) and at most
one per person. Keys are sealed with :class:`app.crypto.Keyring` (``purpose = "ai_provider:<id>"``,
``owner`` = the owner's user id or ``None``) and shown write-only (``{set, last4}``).

**Resolution** (:func:`resolve`): the person's own provider when they chose it and it is usable;
otherwise the shared provider they chose (or the first one); otherwise no AI. A failing own provider
never falls back to the shared one (that would send data somewhere the person did not agree to).

Every function takes ``user_id`` explicitly and never commits unless its name says so.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping

from ..config import ConfigError, Settings
from ..crypto import InvalidToken, Keyring
from ..db import table_exists, utcnow
from ..security import register_secret
from ..settings_store import SettingsStore
from .client import ProviderConfig
from .netpolicy import BaseUrl, NetPolicy, PolicyError, kubernetes_api_addresses, parse_base_url, parse_deny_cidrs, parse_private_hosts
from .presets import PRESETS, POLICY_VERSION, STRUCTURED_SETTINGS, REASONING_EFFORTS, Preset, get as get_preset, policy_line

log = logging.getLogger("kidney_health.ai")

LAST4_MIN_LENGTH = 20
SAFETY_ID_INFO = "kidney-health/v1/openai-safety-id"  # §9 A6
MAX_TOKENS_RANGE = (64, 32_768)
TIMEOUT_RANGE = (5.0, 600.0)
CONTEXT_RANGE = (1024, 2_000_000)
DISABLED_REASONS = ("hermes_tools", "hermes_check_failed")
Purpose = Literal["text", "photos"]


# --------------------------------------------------------------------------- #
# Environment: the network policy and the env provider
# --------------------------------------------------------------------------- #


def build_policy(settings: Settings, *, kubernetes_host: str | None = None) -> NetPolicy:
    """The :class:`NetPolicy` from ``AI_PRIVATE_HOSTS``, ``AI_DENY_CIDRS``, ``AI_HTTP_PROXY`` (ConfigError if bad)."""
    env = settings.ai
    try:
        hosts = parse_private_hosts(env.private_hosts)
        deny = parse_deny_cidrs(env.deny_cidrs)
    except PolicyError as exc:
        raise ConfigError(str(exc)) from None
    return NetPolicy(private_hosts=hosts, deny=deny, kubernetes_api=kubernetes_api_addresses(kubernetes_host), proxy=env.http_proxy)


def check_env(settings: Settings) -> list[str]:
    """Validate the env provider at start-up; returns warnings, raises :class:`ConfigError`."""
    env = settings.ai
    warnings: list[str] = []
    build_policy(settings)
    if env.http_proxy:
        try:
            parts = parse_proxy(env.http_proxy)
        except ValueError as exc:
            raise ConfigError(f"AI_HTTP_PROXY: {exc}") from None
        del parts
    if not env.provider:
        stray = [n for n, v in (("AI_BASE_URL", env.base_url), ("AI_MODEL", env.model), ("AI_API_KEY", env.api_key)) if v]
        if stray:
            warnings.append(f"{', '.join(stray)} {'is' if len(stray) == 1 else 'are'} set but AI_PROVIDER is not, so no server AI provider is defined.")
        return warnings
    try:
        preset = get_preset(env.provider)
    except KeyError as exc:
        raise ConfigError(f"AI_PROVIDER: {exc.args[0]}") from None
    base = env.base_url or preset.base_url
    if not base:
        raise ConfigError(f"AI_PROVIDER={preset.name} needs AI_BASE_URL (the server's address ending in /v1).")
    try:
        parse_base_url(base)
    except PolicyError as exc:
        raise ConfigError(f"AI_BASE_URL: {exc}") from None
    if not (env.model or preset.default_model):
        raise ConfigError(f"AI_PROVIDER={preset.name} needs AI_MODEL (the model name the server knows).")
    if preset.key_required and not env.api_key:
        raise ConfigError(f"AI_PROVIDER={preset.name} needs AI_API_KEY_FILE (or AI_API_KEY).")
    if env.structured not in STRUCTURED_SETTINGS:
        raise ConfigError(f"AI_STRUCTURED_OUTPUT must be one of {', '.join(STRUCTURED_SETTINGS)}.")
    if env.reasoning_effort and env.reasoning_effort not in REASONING_EFFORTS:
        raise ConfigError(f"AI_REASONING_EFFORT must be one of {', '.join(REASONING_EFFORTS)}.")
    if preset.name == "hermes":
        warnings.append("AI_PROVIDER=hermes: use the dedicated tool-free profile's key, never your main profile's; the app "
                        "checks GET /v1/toolsets before every use and refuses a profile with tools (docs/ai.md).")
    return warnings


def parse_proxy(raw: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("must look like http://proxy.internal:3128")
    return raw


def sync_env_provider(conn: sqlite3.Connection, settings: Settings) -> int | None:
    """Keep the ``locked`` shared provider in step with ``AI_PROVIDER`` (no commit). Returns its id.

    The key stays in the environment. When the host changes, consents given for the old host are
    deleted, so everyone is asked again (R9 step 3).
    """
    if not table_exists(conn, "ai_providers"):
        return None
    env = settings.ai
    row = conn.execute("SELECT * FROM ai_providers WHERE locked = 1").fetchone()
    if not env.provider:
        if row is not None:
            conn.execute("DELETE FROM ai_providers WHERE id = ?", (row["id"],))  # consents cascade
        return None
    preset = get_preset(env.provider)
    base = parse_base_url(env.base_url or preset.base_url or "").url
    values = {
        "preset": preset.name, "label": preset.label, "base_url": base,
        "model": env.model or preset.default_model or "", "vision_model": env.vision_model or None,
        "timeout_s": env.timeout_s, "max_tokens": env.max_tokens, "context_tokens": env.context_tokens,
        "structured": env.structured, "reasoning_effort": env.reasoning_effort,
    }
    now = utcnow()
    if row is None:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cur = conn.execute(
            f"INSERT INTO ai_providers (scope, locked, enabled, {cols}, created_at, updated_at) VALUES ('shared', 1, 1, {marks}, ?, ?)",
            (*values.values(), now, now),
        )
        return int(cur.lastrowid)
    changed = {k: v for k, v in values.items() if row[k] != v}
    if changed:
        if "base_url" in changed and parse_base_url(row["base_url"]).host_port != parse_base_url(base).host_port:
            conn.execute("DELETE FROM ai_consents WHERE provider_id = ?", (row["id"],))
        sets = ", ".join(f"{k} = ?" for k in changed)
        conn.execute(f"UPDATE ai_providers SET {sets}, probe_json = NULL, probed_at = NULL, disabled_reason = NULL, updated_at = ? WHERE id = ?",
                     (*changed.values(), now, row["id"]))
    return int(row["id"])


# --------------------------------------------------------------------------- #
# Provider rows
# --------------------------------------------------------------------------- #


def provider_row(conn: sqlite3.Connection, provider_id: int) -> sqlite3.Row | None:
    try:
        return conn.execute("SELECT * FROM ai_providers WHERE id = ?", (int(provider_id),)).fetchone()
    except OverflowError:
        return None


def shared_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Shared providers, the env one first, then by id."""
    if not table_exists(conn, "ai_providers"):
        return []
    return conn.execute("SELECT * FROM ai_providers WHERE scope = 'shared' ORDER BY locked DESC, id").fetchall()


def own_row(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    if not table_exists(conn, "ai_providers"):
        return None
    return conn.execute("SELECT * FROM ai_providers WHERE scope = 'user' AND owner_user_id = ?", (int(user_id),)).fetchone()


def _hint(key: str) -> str | None:
    return key[-4:] if len(key) >= LAST4_MIN_LENGTH else None


def seal_key(conn: sqlite3.Connection, keyring: Keyring, provider_id: int, owner_user_id: int | None, key: str | None) -> None:
    """Store (or with ``None`` remove) a provider's key, sealed to its row and owner (no commit)."""
    if key is None:
        conn.execute("UPDATE ai_providers SET api_key_enc = NULL, api_key_hint = NULL WHERE id = ?", (provider_id,))
        return
    token, _key_id = keyring.seal(purpose=f"ai_provider:{provider_id}", owner=owner_user_id, fields={"api_key": key})
    conn.execute("UPDATE ai_providers SET api_key_enc = ?, api_key_hint = ? WHERE id = ?", (token, _hint(key), provider_id))
    register_secret(key)


def provider_key(row: Mapping[str, Any], keyring: Keyring, settings: Settings) -> str | None:
    """The key in plaintext (env provider: from the environment). ``InvalidToken`` when unreadable."""
    if row["locked"]:
        return settings.ai.api_key
    if row["api_key_enc"] is None:
        return None
    owner = row["owner_user_id"]
    fields = keyring.unseal(row["api_key_enc"], purpose=f"ai_provider:{row['id']}", owner=None if owner is None else int(owner))
    key = fields.get("api_key")
    if key:
        register_secret(key)
    return key


def key_status(row: Mapping[str, Any], keyring: Keyring, settings: Settings) -> dict[str, Any]:
    """The write-only view: ``{"set": false}``, ``{"set": true, "last4"?}``, ``{"set": true, "source": "env"}``
    or ``{"set": true, "status": "unreadable"}``."""
    if row["locked"]:
        return {"set": bool(settings.ai.api_key), "source": "env", "locked": True}
    if row["api_key_enc"] is None:
        return {"set": False}
    try:
        provider_key(row, keyring, settings)
    except InvalidToken:
        return {"set": True, "status": "unreadable"}
    out: dict[str, Any] = {"set": True}
    if row["api_key_hint"]:
        out["last4"] = row["api_key_hint"]
    return out


def _probe(row: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        data = json.loads(row["probe_json"]) if row["probe_json"] else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def provider_view(row: Mapping[str, Any], keyring: Keyring, settings: Settings) -> dict[str, Any]:
    """A provider as the API shows it (never the key)."""
    preset = get_preset(row["preset"])
    base = parse_base_url(row["base_url"])
    probe = _probe(row)
    return {
        "id": int(row["id"]),
        "scope": row["scope"],
        "preset": row["preset"],
        "label": row["label"],
        "base_url": row["base_url"],
        "host": base.display_host,
        "model": row["model"],
        "vision_model": row["vision_model"],
        "timeout_s": row["timeout_s"],
        "max_tokens": row["max_tokens"],
        "context_tokens": row["context_tokens"],
        "structured": row["structured"],
        "reasoning_effort": row["reasoning_effort"],
        "locked": bool(row["locked"]),
        "enabled": bool(row["enabled"]),
        "disabled_reason": row["disabled_reason"],
        "key": key_status(row, keyring, settings),
        "policy": policy_line(preset, scope=row["scope"]),
        "kind": preset.kind,
        "photos": bool(row["vision_model"]),
        "probe": None if probe is None else {k: probe.get(k) for k in ("ok", "structured", "vision", "tools", "models", "warnings", "errors")},
        "probed_at": row["probed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@dataclass(frozen=True)
class ProviderInput:
    """Validated fields for creating or changing a provider (admin form or a person's own)."""

    preset: str
    label: str
    base_url: BaseUrl
    model: str
    vision_model: str | None
    timeout_s: float | None
    max_tokens: int | None
    context_tokens: int | None
    structured: str
    reasoning_effort: str | None


def insert_provider(conn: sqlite3.Connection, data: ProviderInput, *, owner_user_id: int | None, updated_by: int | None) -> int:
    now = utcnow()
    scope = "shared" if owner_user_id is None else "user"
    cur = conn.execute(
        """INSERT INTO ai_providers (scope, owner_user_id, preset, label, base_url, model, vision_model, timeout_s,
             max_tokens, context_tokens, structured, reasoning_effort, enabled, created_at, updated_at, updated_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        (scope, owner_user_id, data.preset, data.label, data.base_url.url, data.model, data.vision_model, data.timeout_s,
         data.max_tokens, data.context_tokens, data.structured, data.reasoning_effort, now, now, updated_by),
    )
    return int(cur.lastrowid)


def update_provider(conn: sqlite3.Connection, row: Mapping[str, Any], data: ProviderInput, *, updated_by: int | None) -> bool:
    """Apply ``data``; a new host deletes the provider's consents, a new URL, model or preset clears the
    probe (it must be tested again). Returns whether the host changed."""
    old_host = parse_base_url(row["base_url"]).host_port
    host_changed = old_host != data.base_url.host_port
    reprobe = (row["base_url"] != data.base_url.url or row["model"] != data.model or row["preset"] != data.preset
               or row["vision_model"] != data.vision_model)
    conn.execute(
        """UPDATE ai_providers SET preset = ?, label = ?, base_url = ?, model = ?, vision_model = ?, timeout_s = ?,
             max_tokens = ?, context_tokens = ?, structured = ?, reasoning_effort = ?, updated_at = ?, updated_by = ? WHERE id = ?""",
        (data.preset, data.label, data.base_url.url, data.model, data.vision_model, data.timeout_s, data.max_tokens,
         data.context_tokens, data.structured, data.reasoning_effort, utcnow(), updated_by, row["id"]),
    )
    if reprobe:
        clear_probe(conn, int(row["id"]))
    if host_changed:
        conn.execute("DELETE FROM ai_consents WHERE provider_id = ?", (row["id"],))
    return host_changed


def clear_probe(conn: sqlite3.Connection, provider_id: int) -> None:
    conn.execute("UPDATE ai_providers SET probe_json = NULL, probed_at = NULL, disabled_reason = NULL WHERE id = ?", (provider_id,))


def save_probe(conn: sqlite3.Connection, provider_id: int, probe: Mapping[str, Any]) -> None:
    """Store a probe result; a Hermes tool check that failed sets ``disabled_reason`` (§9 A1)."""
    tools = probe.get("tools")
    reason = None
    if isinstance(tools, Mapping) and not tools.get("ok"):
        reason = "hermes_tools" if "tools enabled" in str(tools.get("reason") or "") else "hermes_check_failed"
    conn.execute("UPDATE ai_providers SET probe_json = ?, probed_at = ?, disabled_reason = ? WHERE id = ?",
                 (json.dumps(probe, separators=(",", ":"), default=str), utcnow(), reason, provider_id))


def record_tool_check(conn: sqlite3.Connection, row: Mapping[str, Any], ok: bool, reason: str | None) -> None:
    """The pre-call Hermes check (§9 A1): remember when it last passed, or switch the provider off."""
    probe = _probe(row) or {}
    probe["tools_checked_at"] = datetime.now(timezone.utc).timestamp() if ok else None
    if ok:
        conn.execute("UPDATE ai_providers SET probe_json = ?, disabled_reason = NULL WHERE id = ?",
                     (json.dumps(probe, separators=(",", ":"), default=str), row["id"]))
    else:
        code = "hermes_tools" if reason and "tools enabled" in reason else "hermes_check_failed"
        conn.execute("UPDATE ai_providers SET probe_json = ?, disabled_reason = ? WHERE id = ?",
                     (json.dumps(probe, separators=(",", ":"), default=str), code, row["id"]))


def tools_checked_at(row: Mapping[str, Any]) -> float | None:
    probe = _probe(row) or {}
    value = probe.get("tools_checked_at")
    return float(value) if isinstance(value, (int, float)) else None


# --------------------------------------------------------------------------- #
# Building a call configuration
# --------------------------------------------------------------------------- #


def structured_mode(row: Mapping[str, Any], preset: Preset) -> str:
    """``json_schema``, ``json_object`` or ``prompt``: the row's choice, else the probe's, else the preset's."""
    if row["structured"] and row["structured"] != "auto":
        return str(row["structured"])
    probe = _probe(row) or {}
    if probe.get("structured") in ("json_schema", "json_object", "prompt"):
        return str(probe["structured"])
    return preset.default_structured


def safety_identifier(keyring: Keyring, user_id: int) -> str:
    """§9 A6: an HMAC of the user id under a key derived from ``SECRET_KEY`` (not reversible by counting)."""
    return keyring.mac(SAFETY_ID_INFO, str(int(user_id))).hex()[:32]


def to_config(row: Mapping[str, Any], keyring: Keyring, settings: Settings, *, user_id: int) -> ProviderConfig:
    """The call configuration for ``row`` (``InvalidToken`` if its key cannot be decrypted)."""
    preset = get_preset(row["preset"])
    env = settings.ai
    key = provider_key(row, keyring, settings)
    extra = {k: json.loads(json.dumps(v)) for k, v in preset.extra_body.items()}
    if preset.name == "openrouter" and env.openrouter_zdr:
        extra.setdefault("provider", {})["zdr"] = True
    scope = row["scope"]
    return ProviderConfig(
        id=int(row["id"]),
        scope=scope,
        preset=preset.name,
        label=row["label"],
        base=parse_base_url(row["base_url"]),
        model=row["model"],
        api_key=key,
        vision_model=row["vision_model"] or None,
        timeout_s=float(row["timeout_s"] or preset.timeout_s),
        vision_timeout_s=float(max(env.vision_timeout_s, row["timeout_s"] or 0.0)),
        max_tokens=int(row["max_tokens"] or env.max_tokens),
        structured=structured_mode(row, preset),  # type: ignore[arg-type]
        reasoning_effort=row["reasoning_effort"] if row["reasoning_effort"] is not None else preset.reasoning_effort,
        temperature=preset.temperature,
        extra_body=extra,
        context_tokens=int(row["context_tokens"] or preset.context_tokens),
        max_response_bytes=int(env.max_response_bytes),
        key_scope="own" if scope == "user" else "shared",
        safety_identifier=safety_identifier(keyring, user_id) if preset.name == "openai" and scope == "shared" else None,
    )


# --------------------------------------------------------------------------- #
# Resolution (R4: own → shared → none, never a fallback from a failing own provider)
# --------------------------------------------------------------------------- #


@dataclass
class Resolved:
    row: sqlite3.Row | None
    cfg: ProviderConfig | None
    reason: str | None  # None = usable; else disabled | not_opted_in | not_configured | not_allowed | own_unavailable | own_key_unreadable | provider_disabled

    @property
    def ok(self) -> bool:
        return self.cfg is not None


MESSAGES = {
    "disabled": "AI is switched off on this server.",
    "not_opted_in": "Turn on AI ideas in Settings → AI ideas first.",
    "not_configured": "No AI provider is set up on this server.",
    "not_allowed": "Your admin has not shared an AI provider with your account.",
    "own_unavailable": "Your own AI provider is switched off or not allowed on this server; it is never replaced by the shared one.",
    "own_key_unreadable": "Your AI key can no longer be read (the server's secret key changed); enter it again in Settings.",
    "provider_disabled": "The AI provider is switched off until its connection test passes (an admin can test it in Settings).",
}


def ai_prefs(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> dict[str, Any]:
    value = store.get(conn, "ai", user_id)
    return value.model_dump() if hasattr(value, "model_dump") else dict(value or {})


def usable(row: Mapping[str, Any]) -> bool:
    """Enabled and not switched off by a failed tool check (a Hermes provider is re-checked before calls)."""
    if not row["enabled"]:
        return False
    return row["disabled_reason"] is None or row["disabled_reason"] in DISABLED_REASONS and get_preset(row["preset"]).tool_check


def resolve(conn: sqlite3.Connection, store: SettingsStore, keyring: Keyring, settings: Settings, *, user_id: int,
            can_use_shared: bool, require_opt_in: bool = True) -> Resolved:
    """Which provider serves ``user_id`` now (no quota is taken here)."""
    if not store.get(conn, "ai.enabled"):
        return Resolved(None, None, "disabled")
    prefs = ai_prefs(conn, store, user_id)
    if require_opt_in and not prefs.get("opt_in"):
        return Resolved(None, None, "not_opted_in")
    choice = str(prefs.get("provider") or "auto")
    if choice == "own":
        row = own_row(conn, user_id)
        if row is None or not store.get(conn, "ai.user_keys_allowed") or not usable(row):
            return Resolved(row, None, "own_unavailable")
        if get_preset(row["preset"]).kind == "custom" and (not store.get(conn, "ai.allow_user_base_url") or settings.ai.http_proxy):
            return Resolved(row, None, "own_unavailable")
        try:
            return Resolved(row, to_config(row, keyring, settings, user_id=user_id), None)
        except InvalidToken:
            return Resolved(row, None, "own_key_unreadable")
    rows = [r for r in shared_rows(conn)]
    if not rows:
        return Resolved(None, None, "not_configured")
    if not can_use_shared:
        return Resolved(None, None, "not_allowed")
    if choice.startswith("shared:"):
        wanted = choice.split(":", 1)[1]
        rows = [r for r in rows if str(r["id"]) == wanted]
        if not rows:
            return Resolved(None, None, "not_configured")
    candidates = [r for r in rows if usable(r)]
    if not candidates:
        return Resolved(rows[0], None, "provider_disabled")
    row = candidates[0]
    try:
        return Resolved(row, to_config(row, keyring, settings, user_id=user_id), None)
    except InvalidToken:
        log.warning("the key of shared AI provider %s cannot be decrypted with the current SECRET_KEY; set it again", row["id"])
        return Resolved(row, None, "provider_disabled")


# --------------------------------------------------------------------------- #
# Quota and usage (ai_usage)
# --------------------------------------------------------------------------- #


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def shared_used_today(conn: sqlite3.Connection, user_id: int, day: str | None = None) -> int:
    if not table_exists(conn, "ai_usage"):
        return 0
    row = conn.execute("SELECT COALESCE(SUM(requests), 0) FROM ai_usage WHERE user_id = ? AND day = ? AND key_scope = 'shared'",
                       (int(user_id), day or today())).fetchone()
    return int(row[0])


def take_quota(conn: sqlite3.Connection, user_id: int, cfg: ProviderConfig, limit: int, *, requests: int = 1, day: str | None = None) -> bool:
    """Count ``requests`` calls for ``user_id`` (no commit); False (nothing counted) when the shared
    daily limit would be passed. Own keys are counted but never limited. Run inside a write
    transaction (``BEGIN IMMEDIATE``) so two calls cannot both take the last one."""
    day = day or today()
    if cfg.key_scope == "shared" and limit > 0 and shared_used_today(conn, user_id, day) + requests > limit:
        return False
    conn.execute(
        """INSERT INTO ai_usage (user_id, day, provider_id, key_scope, requests) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (user_id, day, provider_id) DO UPDATE SET requests = requests + excluded.requests""",
        (int(user_id), day, cfg.id, cfg.key_scope, int(requests)),
    )
    return True


def add_tokens(conn: sqlite3.Connection, user_id: int, cfg: ProviderConfig, usage: Mapping[str, int], *, day: str | None = None) -> None:
    conn.execute(
        """INSERT INTO ai_usage (user_id, day, provider_id, key_scope, requests, prompt_tokens, completion_tokens)
           VALUES (?, ?, ?, ?, 0, ?, ?)
           ON CONFLICT (user_id, day, provider_id) DO UPDATE SET prompt_tokens = prompt_tokens + excluded.prompt_tokens,
             completion_tokens = completion_tokens + excluded.completion_tokens""",
        (int(user_id), day or today(), cfg.id, cfg.key_scope, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
    )


def remaining_today(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> int | None:
    limit = int(store.get(conn, "ai.shared_daily_limit"))
    return None if limit <= 0 else max(0, limit - shared_used_today(conn, user_id))


# --------------------------------------------------------------------------- #
# Consent (R9 step 3)
# --------------------------------------------------------------------------- #


def consent(conn: sqlite3.Connection, user_id: int, cfg: ProviderConfig, purpose: Purpose) -> dict[str, Any] | None:
    """The person's consent for this provider, host, purpose and the current policy version, or None."""
    row = conn.execute("SELECT * FROM ai_consents WHERE user_id = ? AND provider_id = ? AND purpose = ?",
                       (int(user_id), cfg.id, purpose)).fetchone()
    if row is None or row["host"] != cfg.host or row["policy_version"] != POLICY_VERSION:
        return None
    return {"host": row["host"], "policy_version": row["policy_version"], "skip_preview": bool(row["skip_preview"]), "at": row["created_at"]}


def give_consent(conn: sqlite3.Connection, user_id: int, cfg: ProviderConfig, purpose: Purpose, *, skip_preview: bool) -> dict[str, Any]:
    now = utcnow()
    conn.execute(
        """INSERT INTO ai_consents (user_id, provider_id, purpose, host, policy_version, skip_preview, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (user_id, provider_id, purpose) DO UPDATE SET host = excluded.host,
             policy_version = excluded.policy_version, skip_preview = excluded.skip_preview, created_at = excluded.created_at""",
        (int(user_id), cfg.id, purpose, cfg.host, POLICY_VERSION, int(bool(skip_preview)), now),
    )
    return {"host": cfg.host, "policy_version": POLICY_VERSION, "skip_preview": bool(skip_preview), "at": now}


def withdraw_consent(conn: sqlite3.Connection, user_id: int, provider_id: int, purpose: Purpose | None = None) -> int:
    if purpose is None:
        cur = conn.execute("DELETE FROM ai_consents WHERE user_id = ? AND provider_id = ?", (int(user_id), int(provider_id)))
    else:
        cur = conn.execute("DELETE FROM ai_consents WHERE user_id = ? AND provider_id = ? AND purpose = ?",
                           (int(user_id), int(provider_id), purpose))
    return int(cur.rowcount or 0)


def consents_of(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT c.provider_id, c.purpose, c.host, c.policy_version, c.skip_preview, c.created_at, p.label
           FROM ai_consents c JOIN ai_providers p ON p.id = c.provider_id WHERE c.user_id = ? ORDER BY c.provider_id, c.purpose""",
        (int(user_id),),
    ).fetchall()
    return [{"provider_id": r["provider_id"], "provider_label": r["label"], "purpose": r["purpose"], "host": r["host"],
             "policy_version": r["policy_version"], "current": r["policy_version"] == POLICY_VERSION,
             "skip_preview": bool(r["skip_preview"]), "at": r["created_at"]} for r in rows]


def consent_request(cfg: ProviderConfig, purpose: Purpose) -> dict[str, Any]:
    """What the consent sheet shows before the first call to a host (R9 step 3)."""
    preset = cfg.preset_def
    return {"provider_id": cfg.id, "provider_label": cfg.label, "host": cfg.host, "purpose": purpose,
            "policy": policy_line(preset, scope=cfg.scope), "policy_version": POLICY_VERSION, "kind": preset.kind}


# --------------------------------------------------------------------------- #
# The AI activity log (ai_audit)
# --------------------------------------------------------------------------- #


def write_audit(conn: sqlite3.Connection, user_id: int, *, feature: str, cfg: ProviderConfig, model: str, prompt_version: str,
                request: Any, response_text: str | None, verdict: Mapping[str, Any], latency_ms: int, status: str,
                keep_bodies: bool) -> int:
    """One row per call (no commit). With ``ai.audit_retention_days = 0`` only metadata is kept."""
    cur = conn.execute(
        """INSERT INTO ai_audit (user_id, created_at, feature, provider_id, model, destination_host, prompt_version,
             request_json, response_text, verdict_json, latency_ms, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (int(user_id), utcnow(), feature, cfg.id, model, cfg.host, prompt_version,
         json.dumps(request, ensure_ascii=False, separators=(",", ":")) if keep_bodies and request is not None else None,
         (response_text or "")[:65_536] if keep_bodies and response_text is not None else None,
         json.dumps(verdict, ensure_ascii=False, separators=(",", ":"), default=str), int(latency_ms), status),
    )
    return int(cur.lastrowid)


def audit_rows(conn: sqlite3.Connection, user_id: int, *, before: int | None, limit: int) -> list[dict[str, Any]]:
    params: list[Any] = [int(user_id)]
    where = "user_id = ?"
    if before is not None:
        where += " AND id < ?"
        params.append(int(before))
    rows = conn.execute(f"SELECT * FROM ai_audit WHERE {where} ORDER BY id DESC LIMIT ?", (*params, int(limit))).fetchall()
    out = []
    for r in rows:
        item = {k: r[k] for k in r.keys() if k != "user_id"}
        for key in ("request_json", "verdict_json"):
            if item.get(key):
                try:
                    item[key] = json.loads(item[key])
                except ValueError:
                    pass
        out.append(item)
    return out


def purge(conn: sqlite3.Connection, *, body_days: int, row_days: int, now: datetime | None = None) -> dict[str, int]:
    """Daily retention (§9 A8): clear request/response bodies older than ``body_days`` (all of them
    when 0), delete AI activity and usage rows older than ``row_days`` (no commit)."""
    if not table_exists(conn, "ai_audit"):
        return {"bodies_cleared": 0, "rows_deleted": 0, "usage_deleted": 0}
    now = now or datetime.now(timezone.utc)
    body_cut = (now - timedelta(days=max(0, body_days))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    row_cut = (now - timedelta(days=max(1, row_days))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cleared = conn.execute(
        "UPDATE ai_audit SET request_json = NULL, response_text = NULL WHERE created_at < ? AND (request_json IS NOT NULL OR response_text IS NOT NULL)",
        (body_cut if body_days > 0 else "9999",),
    ).rowcount
    deleted = conn.execute("DELETE FROM ai_audit WHERE created_at < ?", (row_cut,)).rowcount
    usage = conn.execute("DELETE FROM ai_usage WHERE day < ?", (row_cut[:10],)).rowcount
    return {"bodies_cleared": int(cleared or 0), "rows_deleted": int(deleted or 0), "usage_deleted": int(usage or 0)}


def presets_view(*, user: bool, allow_custom: bool) -> list[dict[str, Any]]:
    """The presets a form may offer (a person: public presets, plus a custom server when allowed)."""
    out = []
    for p in PRESETS.values():
        if user and not (p.user_allowed or (allow_custom and p.kind == "custom")):
            continue
        out.append({"name": p.name, "label": p.label, "kind": p.kind, "base_url": p.base_url, "default_model": p.default_model,
                    "key_required": p.key_required, "policy": policy_line(p, scope="user" if user else "shared"),
                    "tool_check": p.tool_check})
    return out
