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

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator, model_validator

from . import brand

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
        default=brand.NAME,
        scope="instance",
        env="INSTANCE_NAME",
        label="Server name",
        help="Shown on the sign-in, invite and password pages, and in Settings under About & privacy.",
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
        env="INVITE_TTL_DAYS",
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
        env="USDA_SHARED_ENABLED",
        label="Share the server's USDA key",
        help="Effective only when a shared key is set.",
    ),
    SettingDef(
        key="providers.usda.user_keys_allowed",
        model=bool,
        default=True,
        scope="instance",
        env="USDA_ALLOW_USER_KEYS",
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
        env="UI_THEME",
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
    # Note 03 R10, user "Prefer live camera" (on, HTTPS only): js/scan.js reads it when the sheet opens.
    SettingDef(
        key="food.scan_prefer_camera",
        model=bool,
        default=True,
        scope="user",
        label="Start the camera when I open Scan",
        help="On a secure (HTTPS) address the Scan sheet starts the live camera at once. Off: it waits for you"
        " to choose the camera, a photo or typing the digits.",
    ),
)

# The other barcode keys (note 03 R10; M2 barcode). OFF_BASE_URL is env-only (app/config.py), never a
# runtime setting: an admin-editable upstream would be an SSRF path and a way to feed made-up nutrient
# values to every person on the server (note 03 §9 B5).
# Printable ASCII without parentheses or backslash: it is written into the User-Agent header as
# "KidneyHealth/<version> (<contact>)", so no control character can reach the header.
OffContact = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200, pattern=r"^[\x20-\x27\x2a-\x5b\x5d-\x7e]+$")
]

register(
    SettingDef(
        key="food.off_contact",
        model=OffContact,
        default=brand.PROJECT_URL,
        scope="instance",
        env="OFF_CONTACT",
        label="Contact sent to Open Food Facts",
        help="Goes into the User-Agent of every lookup, as Open Food Facts asks of API users. An admin email address "
        "is better than the default project address. Letters, digits and punctuation only (no round brackets or backslash).",
    ),
    SettingDef(
        key="food.off_rate_per_minute",
        model=Annotated[int, Field(ge=1, le=15)],
        default=10,
        scope="instance",
        env="OFF_RATE_PER_MINUTE",
        label="Open Food Facts lookups per minute (whole server)",
        help="Open Food Facts allows 15 product lookups a minute from one address and may block an address that "
        "sends more. Everyone on this server shares this budget; products already looked up do not count.",
    ),
    SettingDef(
        key="food.barcode_negative_ttl_hours",
        model=Annotated[int, Field(ge=1, le=720)],
        default=24,
        scope="instance",
        env="BARCODE_NEGATIVE_TTL_HOURS",
        label="Remember barcodes that were not found for (hours)",
        help="A barcode that Open Food Facts or USDA did not know is not asked again for this long.",
    ),
    SettingDef(
        key="food.usda_branded_barcode",
        model=bool,
        default=True,
        scope="instance",
        env="USDA_BRANDED_BARCODE",
        label="Also look barcodes up in USDA FoodData Central",
        help="Uses the person's USDA key or the shared one, when Open Food Facts does not know a product, has no "
        "nutrition facts for it, or lacks potassium or sodium for a US product.",
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
        env="LAB_RULES_ENABLED",
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
        env="LAB_FRESH_DAYS_POTASSIUM",
        label="A potassium result counts for (days)",
    ),
    SettingDef(
        key="targets.lab_fresh_days.phosphate",
        model=FreshDays,
        default=90,
        scope="instance",
        env="LAB_FRESH_DAYS_PHOSPHATE",
        label="A phosphate result counts for (days)",
    ),
    SettingDef(
        key="targets.lab_fresh_days.albumin",
        model=FreshDays,
        default=180,
        scope="instance",
        env="LAB_FRESH_DAYS_ALBUMIN",
        label="An albumin result counts for (days)",
    ),
    SettingDef(
        key="targets.lab_fresh_days.bicarbonate",
        model=FreshDays,
        default=180,
        scope="instance",
        env="LAB_FRESH_DAYS_BICARBONATE",
        label="A bicarbonate result counts for (days)",
    ),
    SettingDef(
        key="targets.default_activity",
        model=Literal["inactive", "low_active", "active", "very_active"],
        default="inactive",
        scope="instance",
        env="DEFAULT_ACTIVITY",
        label="Activity level used until a person chooses theirs",
        help="Used for the calorie estimate (2023 Dietary Reference Intakes).",
    ),
    SettingDef(
        key="user.units.labs",
        model=Literal["us", "si"],
        default="us",
        scope="user_default",
        env="LAB_UNITS",
        label="Units for lab results",
        help="us: mg/dL (creatinine, phosphate), g/dL (albumin), mg/g (urine albumin), % (HbA1c). si: µmol/L, mmol/L, "
        "g/L, mg/mmol, mmol/mol. Only the unit offered first changes; any unit can still be entered.",
    ),
)


# --------------------------------------------------------------------------- #
# Note 10 (weight and blood pressure), §4.3. Owner: the body log (app/body.py reads them). The alarm and the goal are the numbers
# the person's care team gave them: there is no default, and the app never suggests either (note 10 §2, F3).
# --------------------------------------------------------------------------- #


class WeightAlarm(BaseModel):
    """"Call my team if my weight goes up by more than [amount] [between sessions | in [days] days]" (note 10 §4.3, §4.4).
    ``between_sessions`` is offered only on hemodialysis. Stored in kg whatever unit the person types."""

    model_config = ConfigDict(extra="forbid")

    amount_kg: Annotated[float, Field(ge=0.2, le=10, allow_inf_nan=False)] | None = None  # null: no alarm
    over: Literal["between_sessions", "days"] = "days"
    days: Annotated[int, Field(ge=1, le=7)] = 1


class BpGoal(BaseModel):
    """"My blood pressure goal from my team: under [systolic] / [diastolic]" (note 10 §4.3); null leaves a number out."""

    model_config = ConfigDict(extra="forbid")

    systolic: Annotated[int, Field(ge=80, le=200)] | None = None
    diastolic: Annotated[int, Field(ge=40, le=130)] | None = None

    @model_validator(mode="after")
    def _top_above_bottom(self) -> "BpGoal":
        if self.systolic is not None and self.diastolic is not None and self.systolic <= self.diastolic:
            raise ValueError("systolic must be greater than diastolic")
        return self


register(
    SettingDef(
        key="user.units.weight",
        model=Literal["kg", "lb"],
        default="lb",
        scope="user_default",
        env="WEIGHT_UNITS",
        label="Units for weight",
        help="lb or kg (the app's US default is lb). Only how a weight is shown and typed changes; weights are stored in kilograms.",
    ),
    SettingDef(
        key="body.weight_alarm",
        model=WeightAlarm,
        default=WeightAlarm(),
        scope="user",
        label="My weight-gain alarm (from my care team)",
        help="amount_kg (0.2–10, or null for none), over (between_sessions, on hemodialysis, or days) and days (1–7). The app never "
        "suggests a number: enter the one your team gave you.",
    ),
    SettingDef(
        key="body.bp_goal",
        model=BpGoal,
        default=BpGoal(),
        scope="user",
        label="My blood pressure goal (from my care team)",
        help="systolic (80–200) and diastolic (40–130), or null for none. The app never suggests a goal: enter the numbers your "
        "team gave you.",
    ),
)


# --------------------------------------------------------------------------- #
# Note 06 (meal guidance), §4.14 with note 07's key names. Owner: M2 guidance (read by
# app/guidance/context.py and app/guidance/api.py). "Not for me" foods are rows of food_preferences
# (schema step 5), not part of this object, so a deleted food disappears from the list by itself.
# --------------------------------------------------------------------------- #

CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# A usual meal's key (note 09 §4.2): ``"<meal>:<food id>x<quarter servings>,…"`` over its items sorted by food id,
# e.g. ``lunch:12x4,30x2``. Integers only, so the server and the browser twin write the same text.
USUAL_MEAL_KEY_PATTERN = r"^(?:breakfast|lunch|dinner|snack):[0-9]+x[0-9]+(?:,[0-9]+x[0-9]+)*$"
UsualMealKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400, pattern=USUAL_MEAL_KEY_PATTERN)]
CATEGORY_CONFLICT = "a food group can be in only one of Like, Less often and Never suggest: "
PlanMeal = Literal["breakfast", "lunch", "dinner", "snack"]
# A food or saved meal id in the person's "OK to repeat" lists (design note 23 §12.2). Only the person's own foods and saved
# meals are ever read from these lists (app/guidance/context.py), so an id that is not theirs does nothing.
RepeatId = Annotated[int, Field(ge=1, le=2_147_483_647)]
REPEAT_OK_FOODS_MAX = 200
REPEAT_OK_MEALS_MAX = 100


class GuidancePreferences(BaseModel):
    """The person's guidance settings (one object, note 07 §3.10; the preference profile of note 09 §4.2)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True  # "Show meal guidance"
    carb_tolerance_g: Annotated[int, Field(ge=5, le=20)] = 10  # "How close to my meal carb goal counts as on target"
    hypo_dose_g: Annotated[int, Field(ge=5, le=30)] = 15  # "Carbs I take to treat a low (from my diabetes team)"
    exclude_categories: Annotated[list[CategoryName], Field(max_length=50)] = []  # "Never suggest"
    show_plan_builder: bool = True
    show_insights: bool = True
    ai_enrich: bool = False  # note 04: AI may re-rank and explain the rule results (opt-in)
    learn_from_log: bool = True  # "Learn from my log": off removes every learned term (note 09 §4.4)
    like_categories: Annotated[list[CategoryName], Field(max_length=50)] = []  # food groups ranked a little higher
    less_categories: Annotated[list[CategoryName], Field(max_length=50)] = []  # food groups ranked lower, never hidden
    hidden_usual_meals: Annotated[list[UsualMealKey], Field(max_length=50)] = []  # "Not this meal" on a learned usual meal
    # Planning several days (design note 23 §12): the plan sheet's remembered choices and the "OK to repeat" marks.
    plan_repeat_meals: Annotated[list[PlanMeal], Field(max_length=4)] = []  # meals that may be the same on following days
    plan_snack: bool = False  # "Plan a snack too" (off by default)
    repeat_ok_foods: Annotated[list[RepeatId], Field(max_length=REPEAT_OK_FOODS_MAX)] = []  # foods OK to have every day
    repeat_ok_meals: Annotated[list[RepeatId], Field(max_length=REPEAT_OK_MEALS_MAX)] = []  # saved meals OK to have every day

    @field_validator("exclude_categories", "like_categories", "less_categories", "hidden_usual_meals", "plan_repeat_meals",
                     "repeat_ok_foods", "repeat_ok_meals")
    @classmethod
    def _unique(cls, value: list[Any]) -> list[Any]:
        out: list[Any] = []
        for name in value:
            if name not in out:
                out.append(name)
        return out

    @model_validator(mode="after")
    def _one_list_per_group(self) -> "GuidancePreferences":
        """A food group is liked, ranked lower or never suggested, not two of them (note 09 §4.2)."""
        seen: set[str] = set()
        clash: list[str] = []
        for name in (*self.like_categories, *self.less_categories, *self.exclude_categories):
            if name in seen and name not in clash:
                clash.append(name)
            seen.add(name)
        if clash:
            raise ValueError(CATEGORY_CONFLICT + ", ".join(clash))
        return self


PLAN_DAYS_CEILING = 90  # the most PLAN_DAYS_MAX and PLAN_DAYS_AI_MAX may be (design note 23 §12.1)

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
        key="guidance.plan_days_max",
        model=Annotated[int, Field(ge=1, le=PLAN_DAYS_CEILING)],
        default=60,
        scope="instance",
        env="PLAN_DAYS_MAX",
        label="Plan several days: most days at once",
        help="Plans from the person's own foods, without AI. About 30 ms a day on a laptop; lower it on a small server.",
    ),
    SettingDef(
        key="guidance.plan_days_ai_max",
        model=Annotated[int, Field(ge=1, le=PLAN_DAYS_CEILING)],
        default=31,
        scope="instance",
        env="PLAN_DAYS_AI_MAX",
        label="Plan several days with AI ideas: most days at once",
        help="Each day costs AI calls. Never more than the plain cap. The several-days plan uses no AI yet.",
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


# --------------------------------------------------------------------------- #
# Note 04 (optional AI), R4 with §9 A5–A7. Owner: M2 ai (read by app/ai/config.py and app/ai/routes.py).
# Providers and their keys are rows of ai_providers (schema step 6), never settings: the person's `ai`
# object below has no key field (§9 A6). The env-only parts (AI_PROVIDER, AI_BASE_URL, AI_API_KEY_FILE,
# AI_PRIVATE_HOSTS, AI_DENY_CIDRS, AI_HTTP_PROXY, …) live in app/config.py `AiEnv`: an SSRF allowlist is
# never runtime-editable.
# --------------------------------------------------------------------------- #

# Keys only the environment may set while the server runs without sign-in (AUTH_MODE=none): then everybody
# on the network is an admin and could re-point AI at their own server (note 04 §9 A7). PATCH
# /api/admin/settings answers 403 for them in that mode.
NO_SIGNIN_ENV_ONLY: set[str] = set()

AiPreferencesText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]

# How much a person trusts the Ask chat to save for them (assistant step 2, part C): "ask" = a card to confirm before
# every save (the default), "conversation" = saves at once in a conversation the person trusted (the page holds that,
# ends with New conversation or after 12 hours), "always" = saves at once. Both of the last two need the admin switch
# ``ai.allow_trusted_saves``; with it off the effective choice is "ask" whatever is stored.
TRUST_CHOICES: tuple[str, ...] = ("ask", "conversation", "always")


class AiPreferences(BaseModel):
    """The person's AI choices (note 04 R4 "User settings"; Settings → AI ideas). No key field (§9 A6):
    a personal key goes only to ``ai_providers.api_key_enc`` through ``PUT /api/me/ai/provider``."""

    model_config = ConfigDict(extra="forbid")

    opt_in: bool = False  # "Use AI ideas"
    provider: Annotated[str, StringConstraints(pattern=r"^(auto|own|shared:[1-9][0-9]{0,17})$")] = "auto"
    share_age_sex: bool = False  # send a 10-year age band and sex with meal requests
    preferences: AiPreferencesText = ""  # e.g. "vegetarian, no fish" (sent as untrusted data)
    trust: Annotated[str, StringConstraints(pattern=r"^(ask|conversation|always)$")] = "ask"  # TRUST_CHOICES; Settings → AI


register(
    SettingDef(
        key="ai.enabled",
        model=bool,
        default=False,
        scope="instance",
        env="AI_ENABLED",
        label="Optional AI ideas",
        help="Off by default. When on, people who opt in can ask an AI provider you set up for meal ideas and photo help. "
        "The rules always run first and check every AI idea; nothing is sent anywhere while this is off.",
    ),
    SettingDef(
        key="ai.user_keys_allowed",
        model=bool,
        default=True,
        scope="instance",
        env="AI_ALLOW_USER_KEYS",
        label="People may use their own AI key",
        help="For OpenAI, OpenRouter or Nous Portal. Their key is encrypted and never shown again.",
    ),
    SettingDef(
        key="ai.allow_user_base_url",
        model=bool,
        default=False,
        scope="instance",
        env="AI_ALLOW_USER_BASE_URL",
        label="People may enter their own AI server address",
        help="Only https on port 443 to public addresses. Off by default; always off when AI_HTTP_PROXY is set.",
    ),
    SettingDef(
        key="ai.shared_daily_limit",
        model=Annotated[int, Field(ge=0, le=100_000)],
        default=30,
        scope="instance",
        env="AI_SHARED_DAILY_LIMIT",
        label="Shared AI calls per person per day",
        help="Counts meal ideas, described meals, photos and connection tests on shared providers. 0 means unlimited.",
    ),
    SettingDef(
        key="ai.max_concurrency",
        model=Annotated[int, Field(ge=1, le=32)],
        default=2,
        scope="instance",
        env="AI_MAX_CONCURRENCY",
        label="AI calls at the same time (whole server)",
        help="Each person has at most one call running. Extra calls are told to try again in a few seconds.",
    ),
    SettingDef(
        key="ai.audit_retention_days",
        model=Annotated[int, Field(ge=0, le=365)],
        default=30,
        scope="instance",
        env="AI_AUDIT_RETENTION_DAYS",
        label="Keep what was sent to and received from AI for (days)",
        help="Each person sees their own AI activity in Settings. 0 keeps only the time, provider and outcome. "
        "Backups keep it until they expire.",
    ),
    SettingDef(
        key="ai.vision_plate_enabled",
        model=bool,
        default=False,
        scope="instance",
        env="AI_VISION_PLATE_ENABLED",
        label="Plate photos (AI estimate of what is on a plate)",
        help="Off by default. Needs a provider with a vision model. Portion estimates from photos are rough: the app "
        "says so on every result and never logs them without a tap.",
    ),
    SettingDef(
        key="ai.vision_allow_agent",
        model=bool,
        default=False,
        scope="instance",
        env="AI_VISION_ALLOW_AGENT",
        label="Allow photos to go to a Hermes agent",
        help="Off by default. Text printed on a package could try to instruct an agent; even when on, the app only uses "
        "a Hermes profile whose tool check passes.",
    ),
    SettingDef(
        key="ai.chat_enabled",
        model=bool,
        default=False,
        scope="instance",
        env="AI_CHAT_ENABLED",
        label="Ask (a chat with the AI inside the app)",
        help="Off by default. Needs AI on. When on, people who opted in get an Ask screen: they type a question, the AI "
        "looks up the app's own numbers, and the app checks the answer before it is shown. Lows and emergencies are "
        "answered by the app's rules without asking the AI. Each question can use several AI calls.",
    ),
    SettingDef(
        key="ai.voice_enabled",
        model=bool,
        default=False,
        scope="instance",
        env="AI_VOICE_ENABLED",
        label="Voice input for Ask (a microphone button)",
        help="Off by default. Needs Ask on and a transcription server set with STT_BASE_URL. When on, people can record "
        "a question; the recording goes to that server to become text, is deleted at once, and the text appears in the "
        "box for them to read and edit before anything is sent to the AI.",
    ),
    SettingDef(
        key="ai.allow_trusted_saves",
        model=bool,
        default=False,
        scope="instance",
        env="AI_ALLOW_TRUSTED_SAVES",
        label="Let people trust Ask to save without asking",
        help="Off by default. Needs Ask on. When on, a person can choose in Settings → AI ideas to let Ask save food and "
        "recipes at once (for one conversation, or always), after a warning. Off: Ask always shows a card and saves only "
        "when the person presses Save. Either way the app's numbers, the low and emergency rules and the dose checks stay "
        "on, and every save can be undone.",
    ),
    SettingDef(
        key="ai",
        model=AiPreferences,
        default=AiPreferences(),
        scope="user",
        label="AI ideas",
        help="opt_in, provider (auto, own or shared:<id>), share_age_sex, preferences (at most 200 characters) and trust "
        "(ask, conversation or always).",
    ),
)
# Privacy tiers, tier 1: which shared AI each feature uses (docs/ai.md "Which AI does each feature use?"; read by
# app/ai/routing.py). A feature is pinned to the shared provider holding the role `local` (a host on the private
# network that the server's own network policy accepts) or `cloud`, is `off`, or is `any` (the pre-routing rule:
# whichever shared provider the person chose). The default is the least-trusting one, `local`: with no local provider
# the feature is off until an admin pins it to `cloud`. An upgraded server that already had a provider keeps `any`
# until an admin changes it (app/ai/routing.py `initialise`). The two provider settings hold the id of the shared
# provider that has each role (0: none); the admin screen sets them through PUT /api/admin/ai-routing, which refuses
# a host that is not private for `local`, and the resolution checks that again before every call.
AiRoute = Literal["local", "cloud", "off", "any"]
# Privacy tiers, tier 3 (docs/ai.md "Local first, cloud only when the local answer fails"): the structured features (photos,
# meal ideas, describe a meal) also take `local_then_cloud`: the request goes to the local AI first and to the cloud AI only
# when the local AI's answer fails the schema or the app's rules (never when the local AI is unreachable, too slow, over its
# quota or declines). Ask (a chat of several calls) and the local-only lab report photos do not take it.
AiStructuredRoute = Literal["local", "cloud", "off", "any", "local_then_cloud"]
# Reading a lab report from a photo (app/ai/routing.py `labs`): the report can show a name, a date of birth and record
# numbers that the app cannot remove from an image, so this feature runs only on the local AI (or not at all). `cloud` and
# `any` are refused here, whoever asks and whatever the environment says.
AiLocalOnlyRoute = Literal["local", "off"]
AiProviderId = Annotated[int, Field(ge=0, le=1_000_000_000)]

register(
    SettingDef(
        key="ai.route.photos",
        model=AiStructuredRoute,
        default="local",
        scope="instance",
        env="AI_ROUTE_PHOTOS",
        label="Which AI reads photos (labels and plates)",
        help="local, cloud, off, any (any shared provider a person chose, as before routing) or local_then_cloud (the local "
        "AI first; the cloud AI only when the local answer fails the app's checks). A kitchen photo can show "
        "more than a label, so the default is local: with no local AI the feature is off.",
    ),
    SettingDef(
        key="ai.route.meal_ideas",
        model=AiStructuredRoute,
        default="local",
        scope="instance",
        env="AI_ROUTE_MEAL_IDEAS",
        label="Which AI suggests meals (ideas, order, swaps, day plan)",
        help="local, cloud, off, any or local_then_cloud (the cloud AI only when the local answer fails the app's checks). "
        "Default local.",
    ),
    SettingDef(
        key="ai.route.describe",
        model=AiStructuredRoute,
        default="local",
        scope="instance",
        env="AI_ROUTE_DESCRIBE",
        label="Which AI turns a described meal into search words",
        help="local, cloud, off, any or local_then_cloud (the cloud AI only when the local answer fails the app's checks). "
        "Default local.",
    ),
    SettingDef(
        key="ai.route.chat",
        model=AiRoute,
        default="local",
        scope="instance",
        env="AI_ROUTE_CHAT",
        label="Which AI answers in Ask",
        help="local, cloud, off or any. Default local. Needs Ask (ai.chat_enabled) on as well.",
    ),
    SettingDef(
        key="ai.route.labs",
        model=AiLocalOnlyRoute,
        default="local",
        scope="instance",
        env="AI_ROUTE_LABS",
        label="Which AI reads a photo of a lab report",
        help="local or off, never cloud: a lab report can show a name, a date of birth and record numbers that cannot be "
        "removed from a photo, so it is read only by the local AI. Default local: with no local AI the feature is off.",
    ),
    SettingDef(
        key="ai.route.recipes",
        model=AiStructuredRoute,
        default="local",
        scope="instance",
        env="AI_ROUTE_RECIPES",
        label="Which AI suggests and reworks recipes",
        help="local, cloud, off, any or local_then_cloud (the cloud AI only when the local answer fails the app's checks). "
        "Default local. It sends the foods and amounts of a recipe, never its name, note, steps or link.",
    ),
    SettingDef(
        key="ai.recipe_steps",
        model=bool,
        default=False,
        scope="instance",
        env="AI_RECIPE_STEPS",
        label="Cooking steps written by AI in AI recipes",
        help="Off by default. When on, an AI recipe may come with up to 8 cooking steps. The app removes any step that talks about "
        "medicines, a low, nutrients or amounts, and labels the rest as not checked for cooking times or food safety. Turn it on "
        "only after a live run with your model (docs/ai.md).",
    ),
    SettingDef(
        key="ai.route.local_provider",
        model=AiProviderId,
        default=0,
        scope="instance",
        label="The local AI (shared provider id)",
        help="The shared provider that runs on your own network (0: none). Only a provider whose host is in AI_PRIVATE_HOSTS "
        "can be local. Set it in Server administration → AI providers, not here.",
    ),
    SettingDef(
        key="ai.route.cloud_provider",
        model=AiProviderId,
        default=0,
        scope="instance",
        label="The cloud AI (shared provider id)",
        help="The shared provider that runs outside your network (0: none). Set it in Server administration → AI providers, not here.",
    ),
)
NO_SIGNIN_ENV_ONLY.update(
    {"ai.enabled", "ai.user_keys_allowed", "ai.allow_user_base_url", "ai.shared_daily_limit", "ai.max_concurrency",
     "ai.audit_retention_days", "ai.vision_plate_enabled", "ai.vision_allow_agent", "ai.chat_enabled", "ai.voice_enabled",
     "ai.allow_trusted_saves",
     "ai.route.photos", "ai.route.meal_ideas", "ai.route.describe", "ai.route.chat", "ai.route.labs", "ai.route.recipes",
     "ai.recipe_steps", "ai.route.local_provider", "ai.route.cloud_provider"}
)


# --------------------------------------------------------------------------- #
# Assistant access (docs/dev/plans/assistant-step1.md part A; read by app/auth/api_tokens.py). The tokens
# themselves are rows of api_tokens (schema step 10), never settings.
# --------------------------------------------------------------------------- #

register(
    SettingDef(
        key="assistant.enabled",
        model=bool,
        default=False,
        scope="instance",
        env="ASSISTANT_ENABLED",
        label="Assistant access (personal tokens for a chat assistant)",
        help="Off by default. When on, each person can make tokens in Settings → Assistant access that let a chat "
        "assistant they connect read their own food log and targets and, if the person allows it for that token, "
        "also save food and recipes. While off, no token can be made or used; "
        "turned on again, tokens that have not expired or been revoked work again.",
    ),
)


# --------------------------------------------------------------------------- #
# Phone shortcuts (design note 12; read by app/auth/api_tokens.py and app/push.py). The device tokens are rows of
# api_tokens (the "device" family), never settings.
# --------------------------------------------------------------------------- #

register(
    SettingDef(
        key="auth.require_two_step_admins",
        model=bool,
        default=False,
        scope="instance",
        env="AUTH_REQUIRE_TWO_STEP_ADMINS",
        label="Admins must use two-step sign-in",
        help='Off by default. When on, an admin must use two-step sign-in (a code from an authenticator app) to open Server administration. An admin without it can still use the app and turns it on in Settings → Account → Two-step sign-in. Has no effect when a sign-in proxy or no sign-in is used. You can turn it on only after turning on your own two-step sign-in.',
    ),
)
# --------------------------------------------------------------------------- #
# Sign-in with an OpenID Connect provider (design note 24 §4; read by app/auth/oidc_api.py). Who may sign in. The connection itself
# (OIDC_ENABLED, OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET_FILE, OIDC_SCOPES, OIDC_ALLOW_PRIVATE_ISSUER) is env only
# (app/config.py OidcEnv): what the server connects to, and its secret, never change at run time.
# --------------------------------------------------------------------------- #

OidcButtonLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60, pattern=r"^[^\x00-\x1f\x7f]+$")]
OidcDomains = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^[A-Za-z0-9., -]*$")]
OidcGroups = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^[^\x00-\x1f\x7f]*$")]


def comma_list(value: str) -> list[str]:
    """``"a, b,,c"`` → ``["a", "b", "c"]`` (the list settings below are typed as one comma-separated line)."""
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


register(
    SettingDef(
        key="auth.oidc.button_label",
        model=OidcButtonLabel,
        default="Sign in with single sign-on",
        scope="instance",
        env="OIDC_BUTTON_LABEL",
        label="Words on the single sign-on button",
        help="Shown on the sign-in page when sign-in with a provider is on (OIDC_ENABLED). For example: Sign in with Authentik, "
        "or Sign in with Google.",
    ),
    SettingDef(
        key="auth.oidc.allow_signup",
        model=bool,
        default=False,
        scope="instance",
        env="OIDC_ALLOW_SIGNUP",
        label="Make an account for someone new who signs in with the provider",
        help="Off by default: only people who already have an account (and linked it), or who have an invite link, get in. "
        "Turn it on only for a provider where you choose who has an account, such as your own Authentik. With Google, anyone "
        "in the world has an account: then also set the allowed email domains.",
    ),
    SettingDef(
        key="auth.oidc.link_by_email",
        model=bool,
        default=False,
        scope="instance",
        env="OIDC_LINK_BY_EMAIL",
        label="Give someone the account you made for their email address",
        help="Off by default. When on, someone the provider says has a verified email gets the account you made for them in People "
        "with that email as its username, if nobody has used it yet (no password, passkey or link). The address must match exactly, "
        "in plain letters. Never an admin account, an account someone registered themselves, or an unverified email.",
    ),
    SettingDef(
        key="auth.oidc.allowed_domains",
        model=OidcDomains,
        default="",
        scope="instance",
        env="OIDC_ALLOWED_DOMAINS",
        label="Only let in email addresses from these domains",
        help="A comma list, for example example.org, family.net. Empty: any address. When set, the provider must say the email is "
        "verified. With Google, only Workspace accounts of a listed domain get in: a personal Google account with a work address does not.",
    ),
    SettingDef(
        key="auth.oidc.admin_groups",
        model=OidcGroups,
        default="",
        scope="instance",
        env="OIDC_ADMIN_GROUPS",
        label="Provider groups that make someone an admin",
        help="A comma list of group names, for example authentik Admins. Empty: roles are set here only. When set, and the provider "
        "sends a groups claim, the role follows it at each sign-in: in a listed group means admin, otherwise user. The last admin "
        "is never demoted.",
    ),
)
register(
    SettingDef(
        key="sharing.enabled",
        model=bool,
        default=False,
        scope="instance",
        env="SHARING_ENABLED",
        label="Let people share their log, read-only, with someone else on this server",
        help="Off by default. When on, each person can make a link in Settings → Account → Sharing and send it to a caregiver "
        "or dietitian with an account here. Once they accept it, they can read the parts that were ticked (food log, lab results, "
        "weight and blood pressure, symptoms) and never change anything. Either side can stop it at any time. While off, nobody "
        "can see anyone else's data; turned on again, shares that were not stopped work again.",
    ),
)
register(
    SettingDef(
        key="push.enabled",
        model=bool,
        default=False,
        scope="instance",
        env="PUSH_ENABLED",
        label="Let people send weights and blood pressure from a phone shortcut",
        help="Off by default. When on, each person can make tokens in Settings → Phone shortcuts; a shortcut on their phone "
        "can use one to add weights and blood pressure readings to that person's own log. A token can only add: it cannot "
        "read or change anything. While off, no token can be made or used; turned on again, tokens that have not expired "
        "or been revoked work again.",
    ),
)
