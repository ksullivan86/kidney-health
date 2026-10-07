"""Per-app auth state: settings, the settings store, throttles and rate limits (``app.state.auth``)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from starlette.requests import Request

from ..security import client_ip, effective_scheme, is_loopback
from .ratelimit import RateLimits
from .throttle import Throttle

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings
    from ..crypto import Keyring
    from ..settings_store import SettingsStore


@dataclass
class AuthContext:
    settings: "Settings"
    store: "SettingsStore"
    keyring: "Keyring | None" = None
    setup_complete: bool = False  # cached once observed (setup never becomes required again)
    housekeeping: dict[str, float] = field(default_factory=dict)  # last run per period (app.auth.housekeeping)
    throttle: Throttle = field(init=False)
    limits: RateLimits = field(init=False)

    def __post_init__(self) -> None:
        self.throttle = Throttle(self.settings, self.require_keyring)
        self.limits = RateLimits()

    def require_keyring(self) -> "Keyring":
        if self.keyring is None:
            raise RuntimeError("the secret key is not loaded yet (the app has not started)")
        return self.keyring


def auth_context(request: Request) -> AuthContext:
    return request.app.state.auth


def request_ip(request: Request) -> str | None:
    """Client address after trusted-proxy handling (what limits and audit prefixes use)."""
    return client_ip(request.scope)


def plain_http(request: Request) -> bool:
    """True for plain HTTP from a non-loopback client (where ALLOW_INSECURE_HTTP matters)."""
    return effective_scheme(request.scope) != "https" and not is_loopback(client_ip(request.scope))


def public_base(request: Request, settings: "Settings") -> str:
    """``PUBLIC_URL`` when set (note 01 §10 S4), else this request's own origin."""
    if settings.public_origin:
        return settings.public_origin
    host = request.headers.get("host", "localhost")
    return f"{effective_scheme(request.scope)}://{host}"
