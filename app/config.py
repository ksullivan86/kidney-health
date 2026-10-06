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
* ``SECRET_KEY[_FILE]`` [auto-generated ``$DATA_DIR/secret.key``, mode 0600, with a warning]
* ``ENABLE_API_DOCS`` (alias ``DOCS_ENABLED``) [false], ``MAX_BODY_BYTES`` [1 MiB],
  ``MAX_IMAGE_BYTES`` [4 MiB], ``HSTS_MAX_AGE`` [31536000], ``PWA_ENABLED`` [true],
  ``LOG_LEVEL`` [INFO], ``USDA_API_KEY[_FILE]``
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
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOODS_JSON = REPO_ROOT / "data" / "foods.json"
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"
# `mkdocs build` from handbook/ writes here; the image sets HANDBOOK_DIR=/app/learn instead.
DEFAULT_HANDBOOK_DIR = REPO_ROOT / "handbook" / "site"
DB_FILENAME = "kidney.db"
SECRET_KEY_FILENAME = "secret.key"
SECRET_KEY_MIN_LENGTH = 32

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
    password_min_length: int = 15
    password_breach_check: bool = False
    password_hash: str = "argon2id"
    login_ip_max_failures: int = 20
    proxy_auto_create_users: bool = False
    proxy_logout_url: str | None = None

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

    # Secrets at rest (note 07 §4.12). ``secret_key`` holds the raw SECRET_KEY text (one key per
    # line); None means "use or create $DATA_DIR/secret.key" (see app.crypto.load_keyring).
    secret_key: str | None = field(default=None, repr=False)
    secret_key_source: str = "auto"  # "env" | "file" | "auto"
    secret_key_file: Path | None = None

    # HTTP behaviour.
    docs_enabled: bool = False
    max_body_bytes: int = 1_048_576
    max_image_bytes: int = 4_194_304
    hsts_max_age: int = 31_536_000
    pwa_enabled: bool = True
    log_level: str = "INFO"

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
        """Create ``DATA_DIR`` (and parents) if it does not exist yet."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

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
        values = [self.usda_api_key, self.app_password, self.admin_password, self.trusted_proxy_secret]
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
        password_min_length=parse_int(env, "PASSWORD_MIN_LENGTH", 15, 8, 64),
        password_breach_check=parse_bool(env, "PASSWORD_BREACH_CHECK", False),
        password_hash=_choice(env, "PASSWORD_HASH", "argon2id", PASSWORD_HASHES),
        login_ip_max_failures=parse_int(env, "LOGIN_IP_MAX_FAILURES", 20, 1, 100_000),
        proxy_auto_create_users=parse_bool(env, "PROXY_AUTO_CREATE_USERS", False),
        proxy_logout_url=_raw(env, "PROXY_LOGOUT_URL"),
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
        hsts_max_age=parse_int(env, "HSTS_MAX_AGE", 31_536_000, 0, 63_072_000),
        pwa_enabled=parse_bool(env, "PWA_ENABLED", True),
        log_level=_choice(env, "LOG_LEVEL", "INFO", LOG_LEVELS, upper=True),
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
