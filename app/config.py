"""Runtime settings read from environment variables, validated once at start-up.

Every key is documented in ``docs/dev/research/01-rootless-and-security.md`` §5.5 and
``07-accounts-settings-secrets.md`` §4.3. The platform reads them all here so that feature code
never touches ``os.environ`` directly.

**Secrets and the ``*_FILE`` rule.** Every secret (``SECRET_KEY``, ``USDA_API_KEY``,
``APP_PASSWORD``, ``ADMIN_PASSWORD``, ``TRUSTED_PROXY_SECRET``, and any AI key a later note adds
through :func:`read_secret`) can be given either as ``NAME`` or as ``NAME_FILE`` (a path, as Podman
secrets, compose ``secrets:`` and Kubernetes secret volumes provide). Setting both is a start-up
error. A file is read once; trailing ``\\r``/``\\n`` are stripped and an empty file means "unset".

Configuration problems raise :class:`ConfigError` with a message that names the key and says what
to do; :mod:`app.main` turns it into a clean exit instead of a traceback. Non-fatal problems are
collected in :attr:`Settings.warnings` and logged at start-up.

Keys (defaults in brackets):

* ``DATA_DIR`` [``/data`` in a container, else ``./data-local``], ``FOODS_JSON`` [repo data file]
* ``AUTH_MODE`` [``local``] ``local`` | ``proxy`` | ``none`` (note 07)
* ``ADMIN_USERNAME``, ``ADMIN_PASSWORD[_FILE]``, ``APP_PASSWORD[_FILE]`` (deprecated),
  ``SETUP_CODE_TTL_MINUTES`` [60], ``SESSION_IDLE_DAYS`` [14], ``SESSION_MAX_DAYS`` [30],
  ``REAUTH_MINUTES`` [10], ``PASSWORD_MIN_LENGTH`` [15], ``PASSWORD_BREACH_CHECK`` [false],
  ``PASSWORD_HASH`` [argon2id], ``LOGIN_IP_MAX_FAILURES`` [20], ``PROXY_AUTO_CREATE_USERS`` [false],
  ``PROXY_LOGOUT_URL``
* ``ALLOWED_HOSTS`` [localhost, any IP literal and the host of ``PUBLIC_URL`` are always allowed],
  ``PUBLIC_URL``, ``TRUSTED_PROXIES`` [``127.0.0.1,::1``], ``TRUSTED_PROXY_USER_HEADER``,
  ``TRUSTED_PROXY_GROUPS_HEADER``, ``TRUSTED_PROXY_NAME_HEADER``, ``TRUSTED_PROXY_ADMIN_GROUP``,
  ``TRUSTED_PROXY_SECRET[_FILE]``, ``TRUSTED_PROXY_SECRET_OPTIONAL`` [false]
* ``ALLOW_INSECURE_HTTP`` [automatic: allowed while one account exists]
* Sign-in with an OpenID Connect provider (design note 24; :class:`OidcEnv`, ``Settings.oidc``): ``OIDC_ENABLED`` [false],
  ``OIDC_ISSUER``, ``OIDC_CLIENT_ID``, ``OIDC_CLIENT_SECRET_FILE`` (only as a file: ``OIDC_CLIENT_SECRET`` is refused),
  ``OIDC_SCOPES`` [``openid email profile``], ``OIDC_ALLOW_PRIVATE_ISSUER`` [false]; ``OIDC_PROVIDERS`` (named providers, each with
  ``OIDC_<NAME>_*``, at most four in all) and ``OIDC_ONLY`` [false] (note 24 §13). Env only: what the server connects to is never
  changed at run time. Who may sign in is in the settings registry (``auth.oidc.*``). On needs ``AUTH_MODE=local`` and ``PUBLIC_URL``.
* Connected devices (design note 27; :class:`WithingsEnv`, ``Settings.withings``): ``WITHINGS_ENABLED`` [false],
  ``WITHINGS_CLIENT_ID``, ``WITHINGS_CLIENT_SECRET_FILE`` (only as a file: ``WITHINGS_CLIENT_SECRET`` is refused). Env only, like
  OIDC. On needs ``PUBLIC_URL`` (Withings sends people back to ``<PUBLIC_URL>/api/devices/withings/callback``). The switches
  ``DEVICES_ENABLED`` and ``DEVICES_SYNC_HOURS`` are settings (``devices.*``). Whoop (design note 28; :class:`WhoopEnv`,
  ``Settings.whoop``): ``WHOOP_ENABLED`` [false], ``WHOOP_CLIENT_ID``, ``WHOOP_CLIENT_SECRET_FILE`` (only as a file:
  ``WHOOP_CLIENT_SECRET`` is refused), the same way; the return address is ``<PUBLIC_URL>/api/devices/whoop/callback``.
* Test accounts (design note 26): ``TEST_ACCOUNT_PASSWORD_FILE`` (only as a file: ``TEST_ACCOUNT_PASSWORD`` is refused). The file
  is read when the accounts are made or reset. The switches ``TEST_ACCOUNT_ENABLED`` and ``TEST_ACCOUNT_AI`` are settings
  (``test_accounts.*``).
* ``SECRET_KEY[_FILE]`` [auto-generated ``$DATA_DIR/secret.key``, mode 0600, with a warning]
* ``ENABLE_API_DOCS`` (alias ``DOCS_ENABLED``) [false], ``MAX_BODY_BYTES`` [1 MiB],
  ``MAX_IMAGE_BYTES`` [4 MiB], ``MAX_IMPORT_BYTES`` [16 MiB: only ``POST /api/me/import``],
  ``HSTS_MAX_AGE`` [31536000], ``PWA_ENABLED`` [true],
  ``LOG_LEVEL`` [INFO], ``USDA_API_KEY[_FILE]``, ``BACKUP_REMINDER_DAYS`` [7: Server administration reminds an admin when the
  last backup is older; 0 turns the reminder off]
* Optional AI (note 04 R4, §9 A5; ``app/ai/``), parsed into :class:`AiEnv` (``Settings.ai``): the
  server-defined provider ``AI_PROVIDER``, ``AI_BASE_URL``, ``AI_API_KEY[_FILE]`` (``OPENAI_API_KEY[_FILE]``
  is accepted for ``AI_PROVIDER=openai``), ``AI_MODEL``, ``AI_VISION_MODEL``, ``AI_TIMEOUT_S``,
  ``AI_VISION_TIMEOUT_S`` [120], ``AI_MAX_TOKENS`` [1500], ``AI_STRUCTURED_OUTPUT`` [auto],
  ``AI_REASONING_EFFORT``, ``AI_CONTEXT_TOKENS``, ``AI_OPENROUTER_ZDR`` [false]; and the network policy
  ``AI_PRIVATE_HOSTS``, ``AI_DENY_CIDRS``, ``AI_MAX_RESPONSE_BYTES`` [262144], ``AI_HTTP_PROXY``. These are
  env-only on purpose (an SSRF allowlist is never runtime-editable); the switches (``AI_ENABLED`` …) are
  settings-registry keys with env locks. ``app/ai/config.py`` checks the values at start-up.
* A second server-defined provider, always the cloud AI (:class:`AiCloudEnv`, ``Settings.ai.cloud``):
  ``AI_CLOUD_PROVIDER``, ``AI_CLOUD_BASE_URL``, ``AI_CLOUD_API_KEY[_FILE]``, ``AI_CLOUD_MODEL``,
  ``AI_CLOUD_VISION_MODEL``, ``AI_CLOUD_TIMEOUT_S``, ``AI_CLOUD_MAX_TOKENS`` [1500], ``AI_CLOUD_CONTEXT_TOKENS``
  [32768], ``AI_CLOUD_STRUCTURED_OUTPUT`` [auto], ``AI_CLOUD_REASONING_EFFORT`` and ``AI_CLOUD_UPSTREAM`` (the
  company a proxy forwards to; required when the preset is not a cloud one). Read like their ``AI_*`` twins.
* Speech to text for the Ask microphone (assistant step 2, part B; ``app/ai/stt.py``), also in :class:`AiEnv`:
  ``STT_BASE_URL`` (ends in ``/v1``, same address rules as ``AI_BASE_URL``), ``STT_API_KEY[_FILE]`` (optional),
  ``STT_MODEL``, ``STT_TIMEOUT_S`` [60], ``STT_DAILY_LIMIT`` [100]; and ``STT_MAX_AUDIO_BYTES`` [1.5 MiB] (``Settings.max_audio_bytes``).
* How well each AI is doing (``app/ai/quality.py``), also in :class:`AiEnv`: ``AI_EVAL_REPORTS_DIR`` [unset], a read-only folder of the
  ``*.json`` reports ``scripts/ai_eval.py`` writes. Only read (at most 200 files of 1 MiB); unset means "no reports folder".
* ``OFF_BASE_URL`` [``https://world.openfoodfacts.org``]: the Open Food Facts server barcode lookups
  ask (staging ``https://world.openfoodfacts.net`` or a self-hosted Product Opener). Env only, never a
  runtime setting (note 03 §9 B5): ``https://`` (plain ``http://`` only for localhost), no path. A
  host other than the default may resolve to a private address (the operator chose it).
* ``HANDBOOK_DIR`` [``/app/learn`` in the image, else ``<repo>/handbook/site``]: the built handbook
  served at ``/learn`` (``/learn`` answers 404 when it has no ``index.html``);
  ``HANDBOOK_PUBLIC_URL`` [unset]: the published copy (GitHub Pages), where the app's Learn links
  point when this server has no built handbook (note 08 §4.6)

The image runs uvicorn with ``--no-proxy-headers``: ``X-Forwarded-*`` are applied exactly once, by
:mod:`app.security`, and only from ``TRUSTED_PROXIES``. ``FORWARDED_ALLOW_IPS`` is ignored.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from . import brand

log = logging.getLogger(f"{brand.LOGGER_NAME}.config")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOODS_JSON = REPO_ROOT / "data" / "foods.json"
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"
# `mkdocs build` from handbook/ writes here; the image sets HANDBOOK_DIR=/app/learn instead.
DEFAULT_HANDBOOK_DIR = REPO_ROOT / "handbook" / "site"
DB_FILENAME = brand.DB_FILENAME
SECRET_KEY_FILENAME = "secret.key"
SECRET_KEY_MIN_LENGTH = 32
# Who may open DATA_DIR: its owner and the owner's group (the image's 10001:0 and OpenShift's GID 0), nobody else.
DATA_DIR_MODE = 0o770

def _restrict_data_dir(path: Path, *, created: bool) -> None:
    try:
        info = path.stat()
        mode = stat.S_IMODE(info.st_mode)
        owned = not hasattr(os, "geteuid") or info.st_uid == os.geteuid()
        if created and owned:
            path.chmod(DATA_DIR_MODE)  # mkdir's mode is cut down by the umask
        elif mode & 0o007 and owned:
            path.chmod(mode & ~0o007)
            log.warning("%s was open to other users (mode %o); removed their access (now %o)", path, mode, mode & ~0o007)
        elif mode & 0o007:
            log.warning(
                "%s is open to other users (mode %o) and this process does not own it, so it cannot change that;"
                " run: chmod o-rwx %s", path, mode, path,
            )
    except OSError as exc:
        log.warning("could not check or set the mode of %s (%s); run: chmod 770 %s", path, exc, path)


# Files that exist only inside an OCI container (podman / docker).
_CONTAINER_MARKERS = ("/run/.containerenv", "/.dockerenv")

AUTH_MODES = ("local", "proxy", "none")
PASSWORD_HASHES = ("argon2id", "scrypt")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULT_TRUSTED_PROXIES = ("127.0.0.1", "::1")

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
_HOST_LABELS = re.compile(r"^(\*\.)?[a-z0-9_]([a-z0-9_-]{0,62})(\.[a-z0-9_]([a-z0-9_-]{0,62}))*$")


class ConfigError(ValueError):
    """A setting is missing, malformed or contradicts another one. The message names the key."""


def in_container() -> bool:
    return any(os.path.exists(p) for p in _CONTAINER_MARKERS)


def default_data_dir() -> Path:
    return Path("/data") if in_container() else Path("./data-local")


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AiEnv:
    """The optional AI layer's environment (note 04 R4): the server-defined provider and the network
    policy. Parsed here, checked against the presets and the SSRF rules by ``app/ai/config.py``."""

    provider: str | None = None  # AI_PROVIDER: a preset name (app/ai/presets.py)
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    model: str | None = None
    vision_model: str | None = None
    timeout_s: float | None = None  # None: the preset's read timeout
    vision_timeout_s: float = 120.0
    max_tokens: int = 1500
    structured: str = "auto"  # auto | json_schema | json_object | prompt
    reasoning_effort: str | None = None
    context_tokens: int | None = None  # None: 8192 for self-hosted presets, 32768 for cloud ones
    private_hosts: tuple[str, ...] = ()  # AI_PRIVATE_HOSTS entries (host:port, ip:port, CIDR)
    deny_cidrs: tuple[str, ...] = ()  # AI_DENY_CIDRS
    max_response_bytes: int = 262_144
    http_proxy: str | None = None  # AI_HTTP_PROXY; HTTP(S)_PROXY are ignored for AI calls
    openrouter_zdr: bool = False
    provider_role: str | None = None  # AI_PROVIDER_ROLE: local | cloud, the role of the AI_PROVIDER provider (docs/ai.md "Which AI does each feature use?")
    cloud: "AiCloudEnv" = field(default_factory=lambda: AiCloudEnv())  # AI_CLOUD_*: the second server-defined provider, always the cloud AI
    # Speech to text for the Ask screen's microphone (assistant step 2, part B; app/ai/stt.py): one OpenAI-compatible
    # ``{STT_BASE_URL}/audio/transcriptions`` endpoint, under the same address rules as the AI provider.
    stt_base_url: str | None = None  # STT_BASE_URL, ends in /v1 like AI_BASE_URL
    stt_api_key: str | None = field(default=None, repr=False)  # STT_API_KEY_FILE (optional; never returned by any API)
    stt_model: str | None = None  # STT_MODEL
    stt_timeout_s: float = 60.0  # STT_TIMEOUT_S: how long the transcription server may take
    stt_daily_limit: int = 100  # STT_DAILY_LIMIT: recordings per person per day (0 = unlimited)
    # A read-only folder of the reports ``scripts/ai_eval.py`` writes (app/ai/eval_reports.py): Server administration → AI providers
    # says, per feature, whether the model in use passed the live evaluation. Unset: it says there is no reports folder.
    eval_reports_dir: str | None = None  # AI_EVAL_REPORTS_DIR


# A company's plain name, shown to people in the consent line. A proxy that falls back from one company to another names them in
# order, separated by ";" ("OpenAI (ChatGPT); Anthropic (Claude)"): the first is used, the next only when the one before is busy or down.
UPSTREAM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&()-]{0,59}$")
UPSTREAM_MAX_CHARS = 60  # all names with their separators (the ai_providers.upstream column holds 60)
UPSTREAM_MAX_NAMES = 3


def upstream_names(raw: str) -> list[str]:
    """The company names in ``AI_CLOUD_UPSTREAM``, in order (``ConfigError`` when one is not a plain name or there are too many)."""
    names = [part.strip() for part in raw.split(";")]
    if (len(raw) > UPSTREAM_MAX_CHARS or not 1 <= len(names) <= UPSTREAM_MAX_NAMES
            or not all(UPSTREAM_PATTERN.fullmatch(n) for n in names)):
        raise ConfigError(f"AI_CLOUD_UPSTREAM must name the company (or up to {UPSTREAM_MAX_NAMES}, in the order the proxy tries them, "
                          f"separated by ;): letters, digits, spaces and . & ( ) - only, at most {UPSTREAM_MAX_CHARS} characters in all "
                          f"(for example Anthropic, or OpenAI (ChatGPT); Anthropic (Claude)), not {raw[:80]!r}.")
    return names


@dataclass(frozen=True)
class AiCloudEnv:
    """The second server-defined AI provider, always the cloud AI (``AI_CLOUD_*``; docs/ai.md "A local AI and a cloud AI, both
    from the environment"). The fields read like their ``AI_*`` twins; a value that is not set is ``None`` (the defaults are applied
    where the row is written, ``app/ai/config.py``), so a stray value without ``AI_CLOUD_PROVIDER`` can be told from an unset one."""

    provider: str | None = None  # AI_CLOUD_PROVIDER: a preset name (never hermes)
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)  # AI_CLOUD_API_KEY_FILE (or AI_CLOUD_API_KEY); write-only like AI_API_KEY
    model: str | None = None
    vision_model: str | None = None
    timeout_s: float | None = None  # None: the preset's read timeout
    max_tokens: int | None = None  # None: 1500
    structured: str | None = None  # None: auto
    reasoning_effort: str | None = None
    context_tokens: int | None = None  # None: 32768, even for a self-hosted preset (a cloud model sits behind it)
    upstream: str | None = None  # AI_CLOUD_UPSTREAM: who a proxy forwards to ("Anthropic"); required for a non-cloud preset

    def stray(self) -> list[str]:
        """The ``AI_CLOUD_*`` names that are set (the key as AI_CLOUD_API_KEY, whichever of it and _FILE was used), for the "without AI_CLOUD_PROVIDER" warning."""
        pairs = (("AI_CLOUD_BASE_URL", self.base_url), ("AI_CLOUD_API_KEY", self.api_key), ("AI_CLOUD_MODEL", self.model),
                 ("AI_CLOUD_VISION_MODEL", self.vision_model), ("AI_CLOUD_TIMEOUT_S", self.timeout_s),
                 ("AI_CLOUD_MAX_TOKENS", self.max_tokens), ("AI_CLOUD_CONTEXT_TOKENS", self.context_tokens),
                 ("AI_CLOUD_STRUCTURED_OUTPUT", self.structured), ("AI_CLOUD_REASONING_EFFORT", self.reasoning_effort),
                 ("AI_CLOUD_UPSTREAM", self.upstream))
        return [name for name, value in pairs if value is not None]


def load_ai_cloud_env(env: Mapping[str, str]) -> AiCloudEnv:
    """``AiCloudEnv`` from the environment, read, defaulted and range-checked like ``AI_*`` (meaning is checked by ``app/ai/config.py``)."""
    key, _, _ = read_secret(env, "AI_CLOUD_API_KEY")
    key = (key or "").strip() or None
    upstream = _raw(env, "AI_CLOUD_UPSTREAM")
    if upstream is not None:
        upstream = "; ".join(upstream_names(upstream))
    return AiCloudEnv(
        provider=(_raw(env, "AI_CLOUD_PROVIDER") or "").lower() or None,
        base_url=_raw(env, "AI_CLOUD_BASE_URL"),
        api_key=key,
        model=_raw(env, "AI_CLOUD_MODEL"),
        vision_model=_raw(env, "AI_CLOUD_VISION_MODEL"),
        timeout_s=_parse_float(env, "AI_CLOUD_TIMEOUT_S", 5.0, 600.0),
        max_tokens=(parse_int(env, "AI_CLOUD_MAX_TOKENS", 1500, 64, 32_768) if _raw(env, "AI_CLOUD_MAX_TOKENS") else None),
        structured=(_choice(env, "AI_CLOUD_STRUCTURED_OUTPUT", "auto", ("auto", "json_schema", "json_object", "prompt")) if _raw(env, "AI_CLOUD_STRUCTURED_OUTPUT") else None),
        reasoning_effort=(_raw(env, "AI_CLOUD_REASONING_EFFORT") or "").lower() or None,
        context_tokens=(parse_int(env, "AI_CLOUD_CONTEXT_TOKENS", 32_768, 1024, 2_000_000) if _raw(env, "AI_CLOUD_CONTEXT_TOKENS") else None),
        upstream=upstream,
    )


def _parse_float(env: Mapping[str, str], name: str, lo: float, hi: float) -> float | None:
    raw = _raw(env, name)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number of seconds, not {raw!r}.") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo:g} and {hi:g}, not {value:g}.")
    return value


def load_ai_env(env: Mapping[str, str]) -> AiEnv:
    """``AiEnv`` from the environment (types and ranges only; ``app/ai/config.py`` checks the meaning)."""
    provider = (_raw(env, "AI_PROVIDER") or "").lower() or None
    key, _, _ = read_secret(env, "AI_API_KEY")
    if key is None and provider == "openai":
        key, _, _ = read_secret(env, "OPENAI_API_KEY")  # note 01's name, accepted as an alias for OpenAI
    key = (key or "").strip() or None
    vision_timeout = _parse_float(env, "AI_VISION_TIMEOUT_S", 5.0, 600.0)
    stt_key = (read_secret(env, "STT_API_KEY")[0] or "").strip() or None
    stt_timeout = _parse_float(env, "STT_TIMEOUT_S", 5.0, 300.0)
    return AiEnv(
        provider=provider,
        base_url=_raw(env, "AI_BASE_URL"),
        api_key=key,
        model=_raw(env, "AI_MODEL"),
        vision_model=_raw(env, "AI_VISION_MODEL"),
        timeout_s=_parse_float(env, "AI_TIMEOUT_S", 5.0, 600.0),
        vision_timeout_s=120.0 if vision_timeout is None else vision_timeout,
        max_tokens=parse_int(env, "AI_MAX_TOKENS", 1500, 64, 32_768),
        structured=_choice(env, "AI_STRUCTURED_OUTPUT", "auto", ("auto", "json_schema", "json_object", "prompt")),
        reasoning_effort=(_raw(env, "AI_REASONING_EFFORT") or "").lower() or None,
        context_tokens=(parse_int(env, "AI_CONTEXT_TOKENS", 8192, 1024, 2_000_000) if _raw(env, "AI_CONTEXT_TOKENS") else None),
        private_hosts=_split_list(env.get("AI_PRIVATE_HOSTS")),
        deny_cidrs=_split_list(env.get("AI_DENY_CIDRS")),
        max_response_bytes=parse_int(env, "AI_MAX_RESPONSE_BYTES", 262_144, 4096, 16 * 1024 * 1024),
        http_proxy=_raw(env, "AI_HTTP_PROXY"),
        openrouter_zdr=parse_bool(env, "AI_OPENROUTER_ZDR", False),
        provider_role=(_choice(env, "AI_PROVIDER_ROLE", "", ("", "local", "cloud")) or None),
        cloud=load_ai_cloud_env(env),
        stt_base_url=_raw(env, "STT_BASE_URL"),
        stt_api_key=stt_key,
        stt_model=_raw(env, "STT_MODEL"),
        stt_timeout_s=60.0 if stt_timeout is None else stt_timeout,
        stt_daily_limit=parse_int(env, "STT_DAILY_LIMIT", 100, 0, 10_000),
        eval_reports_dir=_raw(env, "AI_EVAL_REPORTS_DIR"),
    )


OIDC_DEFAULT_SCOPES = "openid email profile"
_SCOPE_TOKEN = re.compile(r"^[\x21\x23-\x5b\x5d-\x7e]{1,64}$")  # RFC 6749 §3.3 scope-token


OIDC_MAX_PROVIDERS = 4
OIDC_DEFAULT_ID = "default"  # the id of the provider of OIDC_ISSUER… (no name); named ones use their name
_OIDC_NAME = re.compile(r"^[a-z][a-z0-9]{1,19}$")
_OIDC_LABEL = re.compile(r"^[^\x00-\x1f\x7f]{1,60}$")
_OIDC_DOMAINS = re.compile(r"^[A-Za-z0-9., -]{0,500}$")
_OIDC_GROUPS = re.compile(r"^[^\x00-\x1f\x7f]{0,500}$")


@dataclass(frozen=True)
class OidcEnv:
    """Sign-in with OpenID Connect providers (design note 24 §4, §13): the connection, from the environment only.

    The top-level object is the first provider, from ``OIDC_ISSUER``, ``OIDC_CLIENT_ID``… (its ``name`` is empty; its words,
    domains, groups and sign-up switch are the registry settings ``auth.oidc.*``). ``providers`` holds the named ones of
    ``OIDC_PROVIDERS`` (``OIDC_<NAME>_ISSUER``…), each of which may override those four. ``only`` is ``OIDC_ONLY``."""

    enabled: bool = False  # OIDC_ENABLED
    issuer: str | None = None  # OIDC_ISSUER, exactly as the provider names it (a trailing / is kept)
    client_id: str | None = None  # OIDC_CLIENT_ID
    client_secret: str | None = field(default=None, repr=False)  # OIDC_CLIENT_SECRET_FILE; None: a public client (PKCE only)
    scopes: str = OIDC_DEFAULT_SCOPES  # OIDC_SCOPES, space-separated, always with openid
    allow_private_issuer: bool = False  # OIDC_ALLOW_PRIVATE_ISSUER: the provider may be on a private address (a home Authentik)
    name: str = ""  # "" for the first provider; the lower-case name from OIDC_PROVIDERS for the others
    button_label: str | None = None  # OIDC_<NAME>_BUTTON_LABEL; None: the registry's (first) or "Sign in with <Name>"
    allowed_domains: str | None = None  # OIDC_<NAME>_ALLOWED_DOMAINS; None: the registry's auth.oidc.allowed_domains
    admin_groups: str | None = None  # OIDC_<NAME>_ADMIN_GROUPS; None: the registry's auth.oidc.admin_groups
    allow_signup: bool | None = None  # OIDC_<NAME>_ALLOW_SIGNUP; None: the registry's auth.oidc.allow_signup
    providers: tuple["OidcEnv", ...] = ()  # OIDC_PROVIDERS: the named providers (only on the top-level object)
    only: bool = False  # OIDC_ONLY: no password sign-in (design note 24 §13)

    @property
    def secret_set(self) -> bool:
        return bool(self.client_secret)

    @property
    def id(self) -> str:
        return self.name or OIDC_DEFAULT_ID

    @property
    def var_prefix(self) -> str:
        """``OIDC_`` for the first provider, ``OIDC_<NAME>_`` for a named one (for messages)."""
        return f"OIDC_{self.name.upper()}_" if self.name else "OIDC_"

    def all(self) -> tuple["OidcEnv", ...]:
        """Every configured provider in order (the first one only when it has an issuer); empty while ``OIDC_ENABLED`` is off."""
        if not self.enabled:
            return ()
        first = (self,) if self.issuer else ()
        return first + tuple(self.providers)


@dataclass(frozen=True)
class WithingsEnv:
    """The server's Withings developer app (design note 27): ``WITHINGS_ENABLED``, ``WITHINGS_CLIENT_ID`` and
    ``WITHINGS_CLIENT_SECRET_FILE``. The secret is never returned by any API; Server administration says only "set"."""

    enabled: bool = False
    client_id: str | None = None
    client_secret: str | None = field(default=None, repr=False)

    @property
    def secret_set(self) -> bool:
        return bool(self.client_secret)

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.client_id and self.client_secret)


_WITHINGS_CLIENT_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def load_withings_env(env: Mapping[str, str]) -> WithingsEnv:
    if env.get("WITHINGS_CLIENT_SECRET"):
        raise ConfigError("Give the Withings client secret as a file: put it in a file and set WITHINGS_CLIENT_SECRET_FILE to its "
                          "path. Remove WITHINGS_CLIENT_SECRET.")
    value, _, _ = read_secret({k: v for k, v in env.items() if k == "WITHINGS_CLIENT_SECRET_FILE"}, "WITHINGS_CLIENT_SECRET")
    return WithingsEnv(enabled=parse_bool(env, "WITHINGS_ENABLED", False), client_id=_raw(env, "WITHINGS_CLIENT_ID"),
                       client_secret=(value or "").strip() or None)


def _validate_withings(s: "Settings") -> list[str]:
    w = s.withings
    if not w.enabled:
        return ["WITHINGS_CLIENT_ID set without WITHINGS_ENABLED=true: Withings stays off."] if w.client_id else []
    if not w.client_id or not _WITHINGS_CLIENT_ID.match(w.client_id):
        raise ConfigError("WITHINGS_ENABLED=true needs WITHINGS_CLIENT_ID: the client id of your Withings developer app "
                          "(letters, digits, dots, dashes and underscores; see docs/devices.md).")
    if not w.client_secret:
        raise ConfigError("WITHINGS_ENABLED=true needs WITHINGS_CLIENT_SECRET_FILE: a file holding your Withings app's client "
                          "secret (see docs/devices.md).")
    if not s.public_url:
        raise ConfigError("WITHINGS_ENABLED=true needs PUBLIC_URL: Withings sends people back to "
                          "<PUBLIC_URL>/api/devices/withings/callback.")
    if urlsplit(s.public_url).scheme != "https":
        return ["WITHINGS_ENABLED=true with a PUBLIC_URL that is not https: Withings only accepts an https return address."]
    return []


@dataclass(frozen=True)
class WhoopEnv(WithingsEnv):
    """The server's Whoop developer app (design note 28): ``WHOOP_ENABLED``, ``WHOOP_CLIENT_ID`` and ``WHOOP_CLIENT_SECRET_FILE``.
    The secret is never returned by any API; Server administration says only "set"."""


def load_whoop_env(env: Mapping[str, str]) -> WhoopEnv:
    if env.get("WHOOP_CLIENT_SECRET"):
        raise ConfigError("Give the Whoop client secret as a file: put it in a file and set WHOOP_CLIENT_SECRET_FILE to its "
                          "path. Remove WHOOP_CLIENT_SECRET.")
    value, _, _ = read_secret({k: v for k, v in env.items() if k == "WHOOP_CLIENT_SECRET_FILE"}, "WHOOP_CLIENT_SECRET")
    return WhoopEnv(enabled=parse_bool(env, "WHOOP_ENABLED", False), client_id=_raw(env, "WHOOP_CLIENT_ID"),
                    client_secret=(value or "").strip() or None)


def _validate_whoop(s: "Settings") -> list[str]:
    w = s.whoop
    if not w.enabled:
        return ["WHOOP_CLIENT_ID set without WHOOP_ENABLED=true: Whoop stays off."] if w.client_id else []
    if not w.client_id or not _WITHINGS_CLIENT_ID.match(w.client_id):
        raise ConfigError("WHOOP_ENABLED=true needs WHOOP_CLIENT_ID: the client id of your Whoop developer app "
                          "(letters, digits, dots, dashes and underscores; see docs/devices.md).")
    if not w.client_secret:
        raise ConfigError("WHOOP_ENABLED=true needs WHOOP_CLIENT_SECRET_FILE: a file holding your Whoop app's client "
                          "secret (see docs/devices.md).")
    if not s.public_url:
        raise ConfigError("WHOOP_ENABLED=true needs PUBLIC_URL: Whoop sends people back to "
                          "<PUBLIC_URL>/api/devices/whoop/callback.")
    if urlsplit(s.public_url).scheme != "https":
        return ["WHOOP_ENABLED=true with a PUBLIC_URL that is not https: register an https return address with Whoop."]
    return []


def check_oidc_issuer(raw: str, var: str = "OIDC_ISSUER") -> str:
    """``OIDC_ISSUER``: ``https://`` with a host (plain ``http://`` only for a loopback host, for tests), no query, no fragment."""
    try:
        parts = urlsplit(raw)
        _ = parts.port
    except ValueError:
        raise ConfigError(f"{var} is not a valid URL: {raw!r}.") from None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("https", "http") or not host:
        raise ConfigError(f"{var} must look like https://accounts.google.com, not {raw!r}.")
    if scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"):
        raise ConfigError(f"{var} must use https:// (plain http:// only for localhost).")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ConfigError(f"{var} must not contain a user name, a password, a ?query or a #fragment.")
    return raw


def _oidc_connection(env: Mapping[str, str], prefix: str) -> dict[str, Any]:
    """``<prefix>ISSUER``, ``CLIENT_ID``, ``CLIENT_SECRET_FILE``, ``SCOPES`` and ``ALLOW_PRIVATE_ISSUER`` of one provider."""
    if env.get(f"{prefix}CLIENT_SECRET"):
        raise ConfigError(f"Give the client secret as a file: put it in a file and set {prefix}CLIENT_SECRET_FILE to its path. "
                          f"Remove {prefix}CLIENT_SECRET.")
    value, _, _ = read_secret({k: v for k, v in env.items() if k == f"{prefix}CLIENT_SECRET_FILE"}, f"{prefix}CLIENT_SECRET")
    return dict(
        issuer=_raw(env, f"{prefix}ISSUER"),
        client_id=_raw(env, f"{prefix}CLIENT_ID"),
        client_secret=(value or "").strip() or None,
        scopes=" ".join((_raw(env, f"{prefix}SCOPES") or OIDC_DEFAULT_SCOPES).split()),
        allow_private_issuer=parse_bool(env, f"{prefix}ALLOW_PRIVATE_ISSUER", False),
    )


def oidc_provider_names(env: Mapping[str, str]) -> list[str]:
    """``OIDC_PROVIDERS``: the names of the extra providers, lower case, in order."""
    names = [part.strip().lower() for part in (_raw(env, "OIDC_PROVIDERS") or "").split(",") if part.strip()]
    for name in names:
        if not _OIDC_NAME.match(name) or name == OIDC_DEFAULT_ID:
            raise ConfigError(f"OIDC_PROVIDERS: {name!r} is not a usable name. Use 2 to 20 letters and digits, starting with a "
                              f"letter, for example authentik or google (not {OIDC_DEFAULT_ID!r}).")
    if len(set(names)) != len(names):
        raise ConfigError("OIDC_PROVIDERS names the same provider twice.")
    return names


def load_oidc_env(env: Mapping[str, str]) -> OidcEnv:
    named = []
    for name in oidc_provider_names(env):
        prefix = f"OIDC_{name.upper()}_"
        signup = _raw(env, f"{prefix}ALLOW_SIGNUP")
        named.append(OidcEnv(
            enabled=True, name=name, **_oidc_connection(env, prefix),
            button_label=_raw(env, f"{prefix}BUTTON_LABEL"),
            allowed_domains=_raw(env, f"{prefix}ALLOWED_DOMAINS"),
            admin_groups=_raw(env, f"{prefix}ADMIN_GROUPS"),
            allow_signup=None if signup is None else parse_bool(env, f"{prefix}ALLOW_SIGNUP", False),
        ))
    return OidcEnv(enabled=parse_bool(env, "OIDC_ENABLED", False), **_oidc_connection(env, "OIDC_"), providers=tuple(named),
                   only=parse_bool(env, "OIDC_ONLY", False))


def _check_oidc_provider(o: OidcEnv) -> list[str]:
    """The connection of one provider (``o.var_prefix`` names its variables in the messages)."""
    v = o.var_prefix
    if not o.issuer:
        raise ConfigError(f"{v}ISSUER is missing: the provider's issuer, for example https://accounts.google.com.")
    check_oidc_issuer(o.issuer, f"{v}ISSUER")
    if not o.client_id:
        raise ConfigError(f"{v}CLIENT_ID is missing: the client ID your provider gave you.")
    if len(o.client_id) > 255 or any(ord(c) < 0x21 or ord(c) > 0x7E for c in o.client_id):
        raise ConfigError(f"{v}CLIENT_ID must be printable characters without spaces, at most 255.")
    scopes = o.scopes.split()
    if "openid" not in scopes or len(scopes) > 20 or not all(_SCOPE_TOKEN.match(t) for t in scopes):
        raise ConfigError(f"{v}SCOPES must be a space-separated list that includes openid (the default is {OIDC_DEFAULT_SCOPES!r}).")
    if o.button_label is not None and not _OIDC_LABEL.match(o.button_label):
        raise ConfigError(f"{v}BUTTON_LABEL must be 1 to 60 characters on one line.")
    if o.allowed_domains is not None and not _OIDC_DOMAINS.match(o.allowed_domains):
        raise ConfigError(f"{v}ALLOWED_DOMAINS must be a comma list of domains, for example example.org, family.net.")
    if o.admin_groups is not None and not _OIDC_GROUPS.match(o.admin_groups):
        raise ConfigError(f"{v}ADMIN_GROUPS must be a comma list of group names on one line, at most 500 characters.")
    if not o.secret_set:
        return [f"{v}CLIENT_SECRET_FILE is not set: the server signs in to this provider as a public client (PKCE only)."]
    return []


def _validate_oidc(s: "Settings") -> list[str]:
    o = s.oidc
    if not o.enabled:
        if o.only:
            raise ConfigError("OIDC_ONLY=true needs a sign-in provider: set OIDC_ENABLED=true and the provider's OIDC_ISSUER and "
                              "OIDC_CLIENT_ID (or OIDC_PROVIDERS). Without one nobody could sign in. Remove OIDC_ONLY to start.")
        stray = [n for n, val in (("OIDC_ISSUER", o.issuer), ("OIDC_CLIENT_ID", o.client_id), ("OIDC_PROVIDERS", o.providers)) if val]
        return [f"{', '.join(stray)} set without OIDC_ENABLED=true: sign-in with a provider stays off."] if stray else []
    if s.auth_mode != "local":
        raise ConfigError("OIDC_ENABLED=true needs AUTH_MODE=local (with AUTH_MODE=proxy your proxy signs people in).")
    if not o.issuer and not o.providers:
        raise ConfigError("OIDC_ENABLED=true needs OIDC_ISSUER, for example https://accounts.google.com (or OIDC_PROVIDERS "
                          "with OIDC_<NAME>_ISSUER for each).")
    if not s.public_url:
        raise ConfigError("OIDC_ENABLED=true needs PUBLIC_URL: the provider sends people back to <PUBLIC_URL>/api/auth/oidc/callback.")
    providers = o.all()
    if len(providers) > OIDC_MAX_PROVIDERS:
        raise ConfigError(f"At most {OIDC_MAX_PROVIDERS} sign-in providers are allowed (OIDC_ISSUER counts as one, "
                          "plus each name in OIDC_PROVIDERS).")
    warnings: list[str] = []
    for provider in providers:
        warnings += _check_oidc_provider(provider)
    issuers = [p.issuer for p in providers]
    if len(set(issuers)) != len(issuers):
        raise ConfigError("Two sign-in providers have the same issuer. Each provider needs its own issuer; remove one of them.")
    if o.only:
        warnings.append("OIDC_ONLY=true: nobody can sign in with a password (test accounts still can). If the provider is down, "
                        "set OIDC_ONLY=false and restart to sign in with a password (docs/accounts.md).")
    return warnings


@dataclass(frozen=True)
class Settings:
    """Validated runtime configuration. Secret fields are kept out of ``repr()``."""

    data_dir: Path
    usda_api_key: str | None = field(default=None, repr=False)
    app_password: str | None = field(default=None, repr=False)
    foods_json: Path = DEFAULT_FOODS_JSON
    static_dir: Path = DEFAULT_STATIC_DIR
    # Patient handbook (note 08 §4.6). None = no handbook (the default for Settings built in code, so
    # tests stay hermetic); load_settings() fills in HANDBOOK_DIR or DEFAULT_HANDBOOK_DIR.
    handbook_dir: Path | None = None
    handbook_public_url: str | None = None  # normalised to end with "/"
    # Open Food Facts server for barcode lookups (note 03 R10, §9 B5); env only.
    off_base_url: str = "https://world.openfoodfacts.org"

    # Identity (note 07 §4.3). Enforced by app/auth; parsed and validated here.
    auth_mode: str = "local"
    admin_username: str | None = None
    admin_password: str | None = field(default=None, repr=False)
    setup_code_ttl_minutes: int = 60
    session_idle_days: int = 14
    session_max_days: int = 30
    reauth_minutes: int = 10
    backup_reminder_days: int = 7  # 0: no reminder
    password_min_length: int = 15
    password_breach_check: bool = False
    password_hash: str = "argon2id"
    login_ip_max_failures: int = 20
    proxy_auto_create_users: bool = False
    proxy_logout_url: str | None = None
    # Test accounts (design note 26): the path of the file that holds their one password, read when they are made or reset,
    # never the password itself (TEST_ACCOUNT_PASSWORD is refused). The switches are settings (test_accounts.*).
    test_account_password_file: Path | None = None

    # Network edge (note 01 §5.5 and §10 S1, S2, S4).
    allowed_hosts: tuple[str, ...] = ()
    public_url: str | None = None
    trusted_proxies: tuple[str, ...] = DEFAULT_TRUSTED_PROXIES
    trusted_proxy_user_header: str | None = None
    trusted_proxy_groups_header: str | None = None
    trusted_proxy_name_header: str | None = None
    trusted_proxy_admin_group: str | None = None
    trusted_proxy_secret: str | None = field(default=None, repr=False)
    trusted_proxy_secret_optional: bool = False
    allow_insecure_http: bool | None = None  # None = automatic (note 07 §4.3)

    # Sign-in with an OpenID Connect provider (design note 24); off for Settings built in code.
    oidc: OidcEnv = field(default_factory=OidcEnv, repr=False)
    # Connected devices (design note 27): the server's Withings developer app; off for Settings built in code.
    withings: WithingsEnv = field(default_factory=WithingsEnv, repr=False)
    # Whoop (design note 28): the server's Whoop developer app; off for Settings built in code.
    whoop: WhoopEnv = field(default_factory=WhoopEnv, repr=False)

    # Secrets at rest (note 07 §4.12). ``secret_key`` holds the raw SECRET_KEY text (one key per
    # line); None means "use or create $DATA_DIR/secret.key" (see app.crypto.load_keyring).
    secret_key: str | None = field(default=None, repr=False)
    secret_key_source: str = "auto"  # "env" | "file" | "auto"
    secret_key_file: Path | None = None

    # HTTP behaviour.
    docs_enabled: bool = False
    max_body_bytes: int = 1_048_576
    max_image_bytes: int = 4_194_304
    max_audio_bytes: int = 1_572_864  # one voice clip for POST /api/ai/transcribe (STT_MAX_AUDIO_BYTES)
    max_import_bytes: int = 16_777_216  # POST /api/me/import only (app/data_import.py): an export of several years
    hsts_max_age: int = 31_536_000
    pwa_enabled: bool = True
    log_level: str = "INFO"

    # Optional AI (note 04): the env provider and the network policy; Settings built in code have none.
    ai: AiEnv = field(default_factory=AiEnv, repr=False)

    warnings: tuple[str, ...] = field(default=(), compare=False, repr=False)

    # ------------------------------------------------------------------ paths
    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @property
    def secret_key_path(self) -> Path:
        """Where the auto-generated key lives (used only when SECRET_KEY[_FILE] is unset)."""
        return self.data_dir / SECRET_KEY_FILENAME

    def ensure_data_dir(self) -> Path:
        """Create ``DATA_DIR`` (and parents) if it does not exist yet, with mode 0770.

        The process umask would otherwise decide (0755 under the usual 022), which lets every local user list and
        open the database. A folder that already exists and is open to "other" loses that access, but only when this
        process owns it. This never stops the start: a folder it cannot fix is reported in the log."""
        path = self.data_dir
        created = not path.exists()
        path.mkdir(parents=True, exist_ok=True, mode=DATA_DIR_MODE)
        _restrict_data_dir(path, created=created)
        return path

    # ------------------------------------------------------------------ derived values
    @property
    def public_origin(self) -> str | None:
        """``scheme://host[:port]`` of ``PUBLIC_URL`` (None when unset)."""
        return normalize_origin(self.public_url) if self.public_url else None

    @property
    def public_host(self) -> str | None:
        if not self.public_url:
            return None
        return (urlsplit(self.public_url).hostname or "").lower() or None

    def secret_key_lines(self) -> list[str]:
        """Usable SECRET_KEY lines (blank lines and ``#`` comments dropped). Empty when auto."""
        return parse_secret_key_lines(self.secret_key) if self.secret_key else []

    def secret_values(self) -> list[str]:
        """Every secret value loaded from the environment, for the log-redaction filter."""
        values = [self.usda_api_key, self.app_password, self.admin_password, self.trusted_proxy_secret, self.ai.api_key,
                  self.ai.cloud.api_key, self.ai.stt_api_key, self.oidc.client_secret,
                  *(p.client_secret for p in self.oidc.providers), self.withings.client_secret, self.whoop.client_secret]
        return [v for v in values if v] + self.secret_key_lines()

    def validate(self) -> tuple[str, ...]:
        """Check cross-field rules; raise :class:`ConfigError` or return warnings."""
        return tuple(_validate(self))


# --------------------------------------------------------------------------- #
# Parsing helpers (public: later notes use read_secret for their own keys)
# --------------------------------------------------------------------------- #


def _raw(env: Mapping[str, str], name: str) -> str | None:
    """Stripped value, or None when unset or blank."""
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def read_secret(env: Mapping[str, str], name: str) -> tuple[str | None, str | None, Path | None]:
    """Read ``NAME`` or ``NAME_FILE``. Returns ``(value, source, path)``.

    ``source`` is ``"env"``, ``"file"`` or None (unset). Setting both is a :class:`ConfigError`.
    File contents lose trailing CR/LF; an empty file means unset. Env values are used as given
    (an empty string means unset).
    """
    direct = env.get(name) or None
    file_name = (env.get(f"{name}_FILE") or "").strip() or None
    if direct is not None and file_name is not None:
        raise ConfigError(f"Set either {name} or {name}_FILE, not both.")
    if file_name is not None:
        path = Path(file_name)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ConfigError(f"{name}_FILE points to {path}, which does not exist.") from None
        except IsADirectoryError:
            raise ConfigError(f"{name}_FILE points to {path}, which is a directory, not a file.") from None
        except PermissionError:
            raise ConfigError(f"{name}_FILE: cannot read {path} (permission denied; check the file's owner and mode).") from None
        except UnicodeDecodeError:
            raise ConfigError(f"{name}_FILE: {path} is not UTF-8 text.") from None
        except OSError as exc:
            raise ConfigError(f"{name}_FILE: cannot read {path}: {exc.strerror or exc}") from None
        value = text.rstrip("\r\n")
        return (value or None), ("file" if value else None), (path if value else None)
    if direct is not None:
        return direct, "env", None
    return None, None, None


def secret_value(env: Mapping[str, str], name: str) -> str | None:
    """Just the value of :func:`read_secret`."""
    return read_secret(env, name)[0]


def parse_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _raw(env, name)
    if raw is None:
        return default
    low = raw.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, not {raw!r}.")


def _optional_bool(env: Mapping[str, str], name: str) -> bool | None:
    raw = _raw(env, name)
    if raw is None or raw.lower() == "auto":
        return None
    return parse_bool(env, name, False)


def parse_int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = _raw(env, name)
    if raw is None:
        return default
    try:
        value = int(raw.replace("_", ""))
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, not {raw!r}.") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}, not {value}.")
    return value


def _choice(env: Mapping[str, str], name: str, default: str, choices: tuple[str, ...], *, upper: bool = False) -> str:
    raw = _raw(env, name)
    if raw is None:
        return default
    value = raw.upper() if upper else raw.lower()
    if value not in choices:
        raise ConfigError(f"{name} must be one of {', '.join(choices)}, not {raw!r}.")
    return value


def _split_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(p for p in re.split(r"[,\s]+", raw) if p)


def parse_secret_key_lines(text: str | None) -> list[str]:
    """SECRET_KEY text → key lines: one per line, first is current, ``#`` comments and blanks ignored."""
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def check_secret_key_lines(lines: list[str], what: str = "SECRET_KEY") -> None:
    """Raise :class:`ConfigError` unless there is at least one line and every line is long enough."""
    if not lines:
        raise ConfigError(f"{what} contains no key. Put one key of at least {SECRET_KEY_MIN_LENGTH} characters per line.")
    for number, line in enumerate(lines, start=1):
        if len(line) < SECRET_KEY_MIN_LENGTH:
            raise ConfigError(
                f"{what}: key line {number} is {len(line)} characters long; each line must be at least "
                f"{SECRET_KEY_MIN_LENGTH} characters (generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\")."
            )


def normalize_origin(url: str) -> str:
    """``https://Kidney.Example.org:443/`` → ``https://kidney.example.org`` (scheme://host[:port])."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    if ":" in host:
        host = f"[{host}]"
    if port is None or (scheme, port) in (("http", 80), ("https", 443)):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _check_public_url(raw: str) -> str:
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise ConfigError(f"PUBLIC_URL is not a valid URL: {raw!r}.") from None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ConfigError(f"PUBLIC_URL must look like https://kidney.example.org, not {raw!r}.")
    if parts.username is not None or parts.password is not None:
        raise ConfigError("PUBLIC_URL must not contain a user name or password.")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ConfigError(
            f"PUBLIC_URL must be the site root (scheme, host and optional port only); the app must be served at the "
            f"root of its own host name, not {raw!r}."
        )
    del port
    return normalize_origin(raw)


def _check_handbook_public_url(raw: str) -> str:
    """``HANDBOOK_PUBLIC_URL`` → ``https://host[:port]/path/`` (always ending in ``/``)."""
    example = "https://ksullivan86.github.io/kidney-health/"
    try:
        parts = urlsplit(raw.strip())
        _ = parts.port  # raises ValueError for a malformed port
    except ValueError:
        raise ConfigError(f"HANDBOOK_PUBLIC_URL is not a valid URL: {raw!r}. Use the handbook's address, such as {example}.") from None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ConfigError(f"HANDBOOK_PUBLIC_URL must be an http:// or https:// address, such as {example}, not {raw!r}.")
    if parts.username is not None or parts.password is not None:
        raise ConfigError("HANDBOOK_PUBLIC_URL must not contain a user name or password.")
    if parts.query or parts.fragment or any(c.isspace() for c in raw.strip()):
        raise ConfigError(f"HANDBOOK_PUBLIC_URL must be the handbook's base address without ?query or #fragment, not {raw!r}.")
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return normalize_origin(raw.strip()) + path


def _check_off_base_url(raw: str) -> str:
    from .off import check_base_url

    try:
        return check_base_url(raw)
    except ValueError as exc:
        raise ConfigError(f"OFF_BASE_URL {exc} (got {raw!r}).") from None


def _check_allowed_host(entry: str) -> str:
    value = entry.strip().lower().rstrip(".")
    if value == "*":
        return value
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if ":" in value or "/" in value:
        raise ConfigError(f"ALLOWED_HOSTS takes host names without a scheme, port or path; {entry!r} is not one.")
    if "*" in value[1:] or not _HOST_LABELS.match(value):
        raise ConfigError(
            f"ALLOWED_HOSTS entry {entry!r} is not a host name. Use names such as kidney.example.org or *.example.org."
        )
    return value


def _check_trusted_proxy(entry: str) -> str:
    if entry == "*":
        raise ConfigError(
            "TRUSTED_PROXIES='*' would let every client forge its address and identity. List the address of your "
            "reverse proxy instead (see docs/security.md)."
        )
    try:
        if "/" in entry:
            return str(ipaddress.ip_network(entry, strict=False))
        return str(ipaddress.ip_address(entry))
    except ValueError:
        raise ConfigError(f"TRUSTED_PROXIES entry {entry!r} is not an IP address or CIDR network.") from None


def _check_header_name(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not _HEADER_NAME.match(value):
        raise ConfigError(f"{name} must be an HTTP header name such as Remote-User, not {value!r}.")
    return value


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build and validate :class:`Settings` from ``env`` (defaults to ``os.environ``).

    Empty strings are treated as unset so that ``APP_PASSWORD=`` in a compose file does not
    accidentally enable authentication with an empty password.
    """
    env = os.environ if env is None else env

    if env.get("ALLOW_PRIVATE_AI_HOSTS"):
        raise ConfigError(
            "ALLOW_PRIVATE_AI_HOSTS was replaced by AI_PRIVATE_HOSTS, a list of the private hosts the AI client may "
            "reach (for example AI_PRIVATE_HOSTS=ollama.lan:11434). Remove ALLOW_PRIVATE_AI_HOSTS."
        )

    if env.get("TEST_ACCOUNT_PASSWORD"):
        raise ConfigError("Give the test accounts' password as a file: put it in a file and set TEST_ACCOUNT_PASSWORD_FILE to its path. "
                          "Remove TEST_ACCOUNT_PASSWORD.")
    test_password_file = _raw(env, "TEST_ACCOUNT_PASSWORD_FILE")

    data_dir = Path(env.get("DATA_DIR") or default_data_dir())
    usda_key, _, _ = read_secret(env, "USDA_API_KEY")
    usda_key = (usda_key or "").strip() or None
    app_password, _, _ = read_secret(env, "APP_PASSWORD")
    admin_password, _, _ = read_secret(env, "ADMIN_PASSWORD")
    proxy_secret, _, _ = read_secret(env, "TRUSTED_PROXY_SECRET")
    secret_key, secret_source, secret_path = read_secret(env, "SECRET_KEY")

    docs_new = _raw(env, "ENABLE_API_DOCS")
    docs_alias = _raw(env, "DOCS_ENABLED")
    docs_enabled = parse_bool(env, "ENABLE_API_DOCS", False)
    if docs_alias is not None:
        alias_value = parse_bool(env, "DOCS_ENABLED", False)
        if docs_new is not None and alias_value != docs_enabled:
            raise ConfigError("ENABLE_API_DOCS and its alias DOCS_ENABLED disagree; set only ENABLE_API_DOCS.")
        docs_enabled = alias_value

    trusted_raw = env.get("TRUSTED_PROXIES")
    trusted = DEFAULT_TRUSTED_PROXIES if trusted_raw is None else _split_list(trusted_raw)

    settings = Settings(
        data_dir=data_dir,
        usda_api_key=usda_key,
        app_password=app_password,
        foods_json=Path(env.get("FOODS_JSON") or DEFAULT_FOODS_JSON),
        handbook_dir=Path(_raw(env, "HANDBOOK_DIR") or DEFAULT_HANDBOOK_DIR),
        handbook_public_url=_raw(env, "HANDBOOK_PUBLIC_URL"),
        off_base_url=_raw(env, "OFF_BASE_URL") or "https://world.openfoodfacts.org",
        auth_mode=_choice(env, "AUTH_MODE", "local", AUTH_MODES),
        admin_username=_raw(env, "ADMIN_USERNAME"),
        admin_password=admin_password,
        setup_code_ttl_minutes=parse_int(env, "SETUP_CODE_TTL_MINUTES", 60, 5, 1440),
        session_idle_days=parse_int(env, "SESSION_IDLE_DAYS", 14, 1, 30),
        session_max_days=parse_int(env, "SESSION_MAX_DAYS", 30, 1, 30),
        reauth_minutes=parse_int(env, "REAUTH_MINUTES", 10, 1, 1440),
        backup_reminder_days=parse_int(env, "BACKUP_REMINDER_DAYS", 7, 0, 365),
        password_min_length=parse_int(env, "PASSWORD_MIN_LENGTH", 15, 8, 64),
        password_breach_check=parse_bool(env, "PASSWORD_BREACH_CHECK", False),
        password_hash=_choice(env, "PASSWORD_HASH", "argon2id", PASSWORD_HASHES),
        login_ip_max_failures=parse_int(env, "LOGIN_IP_MAX_FAILURES", 20, 1, 100_000),
        proxy_auto_create_users=parse_bool(env, "PROXY_AUTO_CREATE_USERS", False),
        proxy_logout_url=_raw(env, "PROXY_LOGOUT_URL"),
        test_account_password_file=Path(test_password_file) if test_password_file else None,
        allowed_hosts=_split_list(env.get("ALLOWED_HOSTS")),
        public_url=_raw(env, "PUBLIC_URL"),
        trusted_proxies=tuple(trusted),
        trusted_proxy_user_header=_raw(env, "TRUSTED_PROXY_USER_HEADER"),
        trusted_proxy_groups_header=_raw(env, "TRUSTED_PROXY_GROUPS_HEADER"),
        trusted_proxy_name_header=_raw(env, "TRUSTED_PROXY_NAME_HEADER"),
        trusted_proxy_admin_group=_raw(env, "TRUSTED_PROXY_ADMIN_GROUP"),
        trusted_proxy_secret=proxy_secret,
        trusted_proxy_secret_optional=parse_bool(env, "TRUSTED_PROXY_SECRET_OPTIONAL", False),
        allow_insecure_http=_optional_bool(env, "ALLOW_INSECURE_HTTP"),
        secret_key=secret_key,
        secret_key_source=secret_source or "auto",
        secret_key_file=secret_path,
        docs_enabled=docs_enabled,
        max_body_bytes=parse_int(env, "MAX_BODY_BYTES", 1_048_576, 1024, 64 * 1024 * 1024),
        max_image_bytes=parse_int(env, "MAX_IMAGE_BYTES", 4_194_304, 1024, 64 * 1024 * 1024),
        max_audio_bytes=parse_int(env, "STT_MAX_AUDIO_BYTES", 1_572_864, 65_536, 8 * 1024 * 1024),
        max_import_bytes=parse_int(env, "MAX_IMPORT_BYTES", 16_777_216, 1024 * 1024, 64 * 1024 * 1024),
        hsts_max_age=parse_int(env, "HSTS_MAX_AGE", 31_536_000, 0, 63_072_000),
        pwa_enabled=parse_bool(env, "PWA_ENABLED", True),
        log_level=_choice(env, "LOG_LEVEL", "INFO", LOG_LEVELS, upper=True),
        ai=load_ai_env(env),
        oidc=load_oidc_env(env),
        withings=load_withings_env(env),
        whoop=load_whoop_env(env),
    )
    extra: list[str] = []
    if env.get("FORWARDED_ALLOW_IPS"):
        extra.append(
            "FORWARDED_ALLOW_IPS is ignored: run uvicorn with --no-proxy-headers and list your proxy in TRUSTED_PROXIES."
        )
    settings = normalize(settings)
    return replace(settings, warnings=tuple(extra) + settings.validate())


def normalize(settings: Settings) -> Settings:
    """Canonical forms of list and URL settings (raises :class:`ConfigError` on bad entries)."""
    allowed = tuple(dict.fromkeys(_check_allowed_host(h) for h in settings.allowed_hosts))
    proxies = tuple(dict.fromkeys(_check_trusted_proxy(p) for p in settings.trusted_proxies))
    public = _check_public_url(settings.public_url) if settings.public_url else None
    handbook = _check_handbook_public_url(settings.handbook_public_url) if settings.handbook_public_url else None
    off_base = _check_off_base_url(settings.off_base_url)
    return replace(settings, allowed_hosts=allowed, trusted_proxies=proxies, public_url=public, handbook_public_url=handbook,
                   off_base_url=off_base)


def _validate(s: Settings) -> list[str]:
    warnings: list[str] = []
    if s.auth_mode not in AUTH_MODES:
        raise ConfigError(f"AUTH_MODE must be one of {', '.join(AUTH_MODES)}, not {s.auth_mode!r}.")
    if s.password_hash not in PASSWORD_HASHES:
        raise ConfigError(f"PASSWORD_HASH must be one of {', '.join(PASSWORD_HASHES)}, not {s.password_hash!r}.")
    if s.log_level not in LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, not {s.log_level!r}.")

    for host in s.allowed_hosts:
        _check_allowed_host(host)
    networks = [ipaddress.ip_network(_check_trusted_proxy(p), strict=False) for p in s.trusted_proxies]
    if s.public_url:
        _check_public_url(s.public_url)
    if s.handbook_public_url:
        _check_handbook_public_url(s.handbook_public_url)
    _check_off_base_url(s.off_base_url)
    for name in ("trusted_proxy_user_header", "trusted_proxy_groups_header", "trusted_proxy_name_header"):
        _check_header_name(name.upper(), getattr(s, name))

    if s.secret_key is not None:
        check_secret_key_lines(parse_secret_key_lines(s.secret_key), "SECRET_KEY_FILE" if s.secret_key_source == "file" else "SECRET_KEY")

    if s.admin_password and not s.admin_username:
        raise ConfigError("ADMIN_PASSWORD (or ADMIN_PASSWORD_FILE) needs ADMIN_USERNAME as well; there is no default admin name.")
    if s.admin_username is not None:
        if not 3 <= len(s.admin_username) <= 64 or any(c.isspace() for c in s.admin_username):
            raise ConfigError("ADMIN_USERNAME must be 3 to 64 characters without spaces.")

    if s.session_idle_days > s.session_max_days:
        warnings.append(
            f"SESSION_IDLE_DAYS ({s.session_idle_days}) is longer than SESSION_MAX_DAYS ({s.session_max_days}); "
            "sessions end after SESSION_MAX_DAYS."
        )
    if s.password_min_length < 15:
        warnings.append(
            f"PASSWORD_MIN_LENGTH={s.password_min_length} is below the NIST SP 800-63B-4 single-factor minimum of 15."
        )
    if s.trusted_proxy_secret is not None and len(s.trusted_proxy_secret) < 32:
        warnings.append("TRUSTED_PROXY_SECRET is shorter than 32 characters; use a long random value.")

    wide = [str(n) for n in networks if n.prefixlen == 0]
    if s.auth_mode == "proxy":
        if not s.trusted_proxy_user_header:
            raise ConfigError("AUTH_MODE=proxy needs TRUSTED_PROXY_USER_HEADER (for example Remote-User).")
        if not s.trusted_proxies:
            raise ConfigError("AUTH_MODE=proxy needs TRUSTED_PROXIES: the address(es) of the reverse proxy.")
        if wide:
            raise ConfigError(
                f"AUTH_MODE=proxy refuses TRUSTED_PROXIES containing {', '.join(wide)}: every client could claim any identity."
            )
        if not s.trusted_proxy_secret:
            if not s.trusted_proxy_secret_optional:
                raise ConfigError(
                    "AUTH_MODE=proxy needs TRUSTED_PROXY_SECRET_FILE: a shared secret your proxy sends as X-Proxy-Secret. "
                    "Only for proxies that cannot add headers (tailscale serve), set TRUSTED_PROXY_SECRET_OPTIONAL=true."
                )
            warnings.append(
                "AUTH_MODE=proxy without TRUSTED_PROXY_SECRET: any process that can connect from a TRUSTED_PROXIES "
                "address can claim any identity (TRUSTED_PROXY_SECRET_OPTIONAL=true)."
            )
    elif wide:
        warnings.append(f"TRUSTED_PROXIES contains {', '.join(wide)}: every client can set X-Forwarded-For and X-Forwarded-Proto.")

    if s.auth_mode == "none":
        names = [h for h in s.allowed_hosts if h == "*" or not _is_ip(h)]
        if names and not s.public_url:
            warnings.append(
                "AUTH_MODE=none with host names in ALLOWED_HOSTS and no PUBLIC_URL: anyone who can reach this server "
                "can read and change all data. Set PUBLIC_URL and use HTTPS, or switch to AUTH_MODE=local."
            )
    warnings += _validate_oidc(s)
    warnings += _validate_withings(s)
    warnings += _validate_whoop(s)
    if "*" in s.allowed_hosts:
        warnings.append("ALLOWED_HOSTS contains '*': the Host check (DNS-rebinding defence) is switched off.")
    if s.docs_enabled:
        warnings.append("ENABLE_API_DOCS=true: /docs, /redoc and /openapi.json are served with a relaxed CSP.")
    return warnings


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
