"""The registry of runtime settings (note 07 §4.11).

Every setting an admin or a user can change at runtime is declared here, once, with its type,
default, scope and optional env lock. Other notes add their keys with :func:`register` (one block
per feature, next to the owner's comment) instead of inventing another store. Values are stored by
:mod:`app.settings_store` in ``instance_settings`` / ``user_settings``.

Scopes:

* ``instance``: one value for the whole server (admin only).
* ``user``: each person's own value (no admin default).
* ``user_default``: the admin sets the default, each person may override it.

``env`` names an environment variable that **locks** the key: when set, its value wins and the UI
shows "Set by the server (``ENV``)".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, TypeAdapter

Scope = Literal["instance", "user", "user_default"]
SCOPES: tuple[str, ...] = ("instance", "user", "user_default")


@dataclass(frozen=True)
class SettingDef:
    key: str  # dotted, e.g. "providers.usda.daily_limit_per_user"
    model: Any  # pydantic-validated type: bool, int, Literal[...], an Annotated constraint or a BaseModel
    default: Any
    scope: Scope  # user_default: admin default, user may override
    env: str | None = None  # env var that LOCKS it
    label: str = ""
    help: str = ""
    adapter: TypeAdapter[Any] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            raise ValueError(f"{self.key}: scope must be one of {SCOPES}")
        object.__setattr__(self, "adapter", _adapter(self.model))
        # The default must itself be valid, so a fallback can never produce a bad value.
        self.adapter.validate_python(self.default)

    @property
    def user_editable(self) -> bool:
        return self.scope in ("user", "user_default")

    @property
    def admin_editable(self) -> bool:
        return self.scope in ("instance", "user_default")

    def validate(self, value: Any) -> Any:
        """Validated value (raises pydantic.ValidationError)."""
        return self.adapter.validate_python(value)

    def to_json(self, value: Any) -> str:
        return self.adapter.dump_json(self.validate(value)).decode("utf-8")

    def from_json(self, text: str) -> Any:
        return self.adapter.validate_json(text)

    def from_env(self, raw: str) -> Any:
        """Parse an env-lock value: plain text for strings, ``true``/``5`` for scalars, JSON otherwise."""
        try:
            return self.adapter.validate_strings(raw)
        except Exception:
            pass
        try:
            return self.adapter.validate_python(raw)
        except Exception:
            return self.adapter.validate_json(raw)

    def to_python_json(self, value: Any) -> Any:
        """Value as plain JSON-compatible data (for API responses)."""
        return self.adapter.dump_python(value, mode="json")


@lru_cache(maxsize=None)
def _adapter_cached(model: Any) -> TypeAdapter[Any]:
    return TypeAdapter(model)


def _adapter(model: Any) -> TypeAdapter[Any]:
    try:
        return _adapter_cached(model)
    except TypeError:  # unhashable annotation
        return TypeAdapter(model)


REGISTRY: dict[str, SettingDef] = {}


def register(*defs: SettingDef) -> None:
    """Add settings. A key may be registered once; registering the identical definition again is a no-op."""
    for d in defs:
        existing = REGISTRY.get(d.key)
        if existing is not None:
            if existing == d:
                continue
            raise ValueError(f"setting {d.key!r} is already registered")
        if d.env is not None and any(o.env == d.env for o in REGISTRY.values()):
            raise ValueError(f"env lock {d.env!r} is already used by another setting")
        REGISTRY[d.key] = d


def get(key: str) -> SettingDef:
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown setting {key!r}") from None


def all_settings() -> list[SettingDef]:
    return sorted(REGISTRY.values(), key=lambda d: d.key)


# --------------------------------------------------------------------------- #
# Note 07 (accounts, settings, secrets): the initial keys
# --------------------------------------------------------------------------- #

InstanceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

register(
    SettingDef(
        key="instance.name",
        model=InstanceName,
        default="Kidney Health",
        scope="instance",
        env="INSTANCE_NAME",
        label="Server name",
        help="Shown on the sign-in page and in the app's title.",
    ),
    SettingDef(
        key="registration.mode",
        model=Literal["invite", "closed", "open"],
        default="invite",
        scope="instance",
        env="REGISTRATION_MODE",
        label="Registration",
        help="invite: admins send single-use links. closed: admins create accounts. open: anyone who reaches the page can register (HTTPS required).",
    ),
    SettingDef(
        key="registration.invite_ttl_days",
        model=Annotated[int, Field(ge=1, le=90)],
        default=7,
        scope="instance",
        label="Invite links expire after (days)",
    ),
    SettingDef(
        key="audit.retention_days",
        model=Annotated[int, Field(ge=1, le=3650)],
        default=365,
        scope="instance",
        env="AUDIT_RETENTION_DAYS",
        label="Keep the activity log for (days)",
    ),
    SettingDef(
        key="providers.usda.shared_enabled",
        model=bool,
        default=True,
        scope="instance",
        label="Share the server's USDA key",
        help="Effective only when a shared key is set.",
    ),
    SettingDef(
        key="providers.usda.user_keys_allowed",
        model=bool,
        default=True,
        scope="instance",
        label="People may add their own USDA key",
    ),
    SettingDef(
        key="providers.usda.daily_limit_per_user",
        model=Annotated[int, Field(ge=0, le=100_000)],
        default=200,
        scope="instance",
        env="USDA_SHARED_DAILY_LIMIT",
        label="Shared USDA lookups per person per day",
        help="0 means unlimited.",
    ),
    SettingDef(
        key="ui.theme",
        model=Literal["system", "light", "dark"],
        default="system",
        scope="user_default",
        label="Theme",
    ),
)
