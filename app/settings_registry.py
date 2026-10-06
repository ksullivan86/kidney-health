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

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator

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


# --------------------------------------------------------------------------- #
# Note 03 (barcodes, Open Food Facts): the two keys the M1 setup screen and Settings already use.
# Registered early by the M1 sign-in/settings work (ARCHITECTURE v0.3 item 8: the first-run setup
# screen offers the Open Food Facts checkbox); the M2 barcode work owns them and adds its other
# food.off_* keys next to these. OFF_BASE_URL stays env-only (note 03 security review B5).
# --------------------------------------------------------------------------- #

register(
    SettingDef(
        key="food.off_enabled",
        model=bool,
        default=False,
        scope="instance",
        env="OFF_ENABLED",
        label="Look up barcodes with Open Food Facts",
        help="Off by default. When on, a barcode that is not in this server's food list is looked up at "
        "world.openfoodfacts.org (only the barcode number is sent). Product data is under the Open Database License.",
    ),
    SettingDef(
        key="food.off_consent",
        model=bool,
        default=False,
        scope="user",
        label="Send barcodes I scan to Open Food Facts",
        help="Your own choice, used only when the admin has turned Open Food Facts lookups on.",
    ),
)


# --------------------------------------------------------------------------- #
# Note 05 (personalised targets and labs), §4.9. Owner: M2 targets (app/targets.py reads them through
# app/profile.py and app/labs.py).
# --------------------------------------------------------------------------- #

FreshDays = Annotated[int, Field(ge=1, le=365)]

register(
    SettingDef(
        key="targets.lab_rules_enabled",
        model=bool,
        default=True,
        scope="instance",
        label="Let lab results change suggested targets",
        help="Off: potassium and phosphorus suggestions use the stage defaults and lab notes are left out. The warning "
        "for a very high potassium result is always shown. Keep it off on public demo servers until a clinician has "
        "reviewed the lab rules.",
    ),
    SettingDef(
        key="targets.lab_fresh_days.potassium",
        model=FreshDays,
        default=90,
        scope="instance",
        label="A potassium result counts for (days)",
    ),
    SettingDef(
        key="targets.lab_fresh_days.phosphate",
        model=FreshDays,
        default=90,
        scope="instance",
        label="A phosphate result counts for (days)",
    ),
    SettingDef(
        key="targets.lab_fresh_days.albumin",
        model=FreshDays,
        default=180,
        scope="instance",
        label="An albumin result counts for (days)",
    ),
    SettingDef(
        key="targets.lab_fresh_days.bicarbonate",
        model=FreshDays,
        default=180,
        scope="instance",
        label="A bicarbonate result counts for (days)",
    ),
    SettingDef(
        key="targets.default_activity",
        model=Literal["inactive", "low_active", "active", "very_active"],
        default="inactive",
        scope="instance",
        label="Activity level used until a person chooses theirs",
        help="Used for the calorie estimate (2023 Dietary Reference Intakes).",
    ),
    SettingDef(
        key="user.units.labs",
        model=Literal["us", "si"],
        default="us",
        scope="user_default",
        label="Units for lab results",
        help="us: mg/dL (creatinine, phosphate), g/dL (albumin), mg/g (urine albumin), % (HbA1c). si: µmol/L, mmol/L, "
        "g/L, mg/mmol, mmol/mol. Only the unit offered first changes; any unit can still be entered.",
    ),
)


# --------------------------------------------------------------------------- #
# Note 06 (meal guidance), §4.14 with note 07's key names. Owner: M2 guidance (read by
# app/guidance/context.py and app/guidance/api.py). "Not for me" foods are rows of food_preferences
# (schema step 5), not part of this object, so a deleted food disappears from the list by itself.
# --------------------------------------------------------------------------- #

CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class GuidancePreferences(BaseModel):
    """The person's guidance settings (one object, note 07 §3.10)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True  # "Show meal guidance"
    carb_tolerance_g: Annotated[int, Field(ge=5, le=20)] = 10  # "How close to my meal carb goal counts as on target"
    hypo_dose_g: Annotated[int, Field(ge=5, le=30)] = 15  # "Carbs I take to treat a low (from my diabetes team)"
    exclude_categories: Annotated[list[CategoryName], Field(max_length=50)] = []  # "Never suggest"
    show_plan_builder: bool = True
    show_insights: bool = True
    ai_enrich: bool = False  # note 04: AI may re-rank and explain the rule results (opt-in)

    @field_validator("exclude_categories")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for name in value:
            if name not in out:
                out.append(name)
        return out


register(
    SettingDef(
        key="guidance.enabled",
        model=bool,
        default=True,
        scope="instance",
        env="GUIDANCE_ENABLED",
        label="Meal guidance",
        help="Rule-based suggestions for the next meal, swap ideas, plan-the-day and insights. Works without AI.",
    ),
    SettingDef(
        key="guidance.pool_per_role",
        model=Annotated[int, Field(ge=20, le=2000)],
        default=200,
        scope="instance",
        env="GUIDANCE_POOL_PER_ROLE",
        label="Plan builder: foods considered per role",
        help="Lower it (for example to 120) if planning a day is slow on a small server such as a Raspberry Pi 4.",
    ),
    SettingDef(
        key="guidance.beam_width",
        model=Annotated[int, Field(ge=1, le=64)],
        default=16,
        scope="instance",
        env="GUIDANCE_BEAM_WIDTH",
        label="Plan builder: search width",
        help="Partial meals kept at each step. 8 is about 15 % faster and finds slightly worse meals.",
    ),
    SettingDef(
        key="guidance",
        model=GuidancePreferences,
        default=GuidancePreferences(),
        scope="user",
        label="Meal guidance preferences",
        help="carb_tolerance_g (5–20) and hypo_dose_g (5–30) come from your diabetes team.",
    ),
)
