"""Request bodies for the account, admin and key routes.

Every field that carries a secret is a ``SecretStr`` (note 07 §9 N4): it never appears in ``repr``,
logs or validation errors (the error handler drops ``input``/``ctx`` anyway).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

PASSWORD_FIELD_MAX = 1024  # login/re-auth accept long input; new passwords are capped at 128 by policy
USERNAME_MAX = 255


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore", str_max_length=4096)


class LoginBody(_Body):
    username: str = Field(min_length=1, max_length=USERNAME_MAX)
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_FIELD_MAX)


class SetupBody(_Body):
    code: SecretStr = Field(min_length=1, max_length=64)
    username: str | None = Field(default=None, max_length=USERNAME_MAX)
    display_name: str | None = Field(default=None, max_length=200)
    password: SecretStr | None = Field(default=None, max_length=PASSWORD_FIELD_MAX)
    off_enabled: bool | None = None  # first-run checkbox for Open Food Facts (ARCHITECTURE v0.3 item 8)


class RegisterBody(_Body):
    token: SecretStr | None = Field(default=None, max_length=200)
    username: str = Field(min_length=1, max_length=USERNAME_MAX)
    display_name: str | None = Field(default=None, max_length=200)
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_FIELD_MAX)


class ResetBody(_Body):
    token: SecretStr = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_FIELD_MAX)


class LinkInfoBody(_Body):
    token: SecretStr = Field(min_length=1, max_length=200)


class ReauthBody(_Body):
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_FIELD_MAX)


class PasswordChangeBody(_Body):
    current_password: SecretStr = Field(min_length=1, max_length=PASSWORD_FIELD_MAX)
    new_password: SecretStr = Field(min_length=1, max_length=PASSWORD_FIELD_MAX)


class MePatch(_Body):
    display_name: str = Field(max_length=200)


class DeleteMeBody(_Body):
    password: SecretStr | None = Field(default=None, max_length=PASSWORD_FIELD_MAX)
    confirm: str = Field(max_length=20)


class KeyPut(_Body):
    api_key: SecretStr = Field(min_length=1, max_length=1024)
    test: bool = False


class InviteCreate(_Body):
    role: Literal["admin", "user"] = "user"
    note: str | None = Field(default=None, max_length=200)
    ttl_days: int | None = Field(default=None, ge=1, le=90)


class UserCreate(_Body):
    username: str = Field(min_length=1, max_length=USERNAME_MAX)
    display_name: str | None = Field(default=None, max_length=200)
    role: Literal["admin", "user"] = "user"


class UserPatch(_Body):
    role: Literal["admin", "user"] | None = None
    status: Literal["active", "disabled"] | None = None
    can_use_shared: bool | None = None
    must_change_password: bool | None = None
    display_name: str | None = Field(default=None, max_length=200)


class UserDeleteBody(_Body):
    confirm_username: str = Field(max_length=USERNAME_MAX)

