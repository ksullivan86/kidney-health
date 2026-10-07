"""JSON errors that carry extra keys next to ``detail`` (``reauth_required``, ``setup_required``...).

``HTTPException(detail={...})`` would nest the object under ``detail`` and break the contract
shape, so these are plain exceptions with their own handler (registered by :func:`app.auth.install`).
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiProblem(Exception):
    """``{"detail": detail, **extra}`` with ``status`` and optional headers."""

    def __init__(self, status: int, detail: str, *, headers: dict[str, str] | None = None, **extra: Any) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra

    def response(self) -> JSONResponse:
        return JSONResponse({"detail": self.detail, **self.extra}, status_code=self.status, headers=self.headers)


def setup_required() -> ApiProblem:
    return ApiProblem(503, "Setup required", setup_required=True)


def sign_in_required(detail: str = "Sign in required") -> ApiProblem:
    return ApiProblem(401, detail)


def reauth_required() -> ApiProblem:
    return ApiProblem(403, "Please enter your password again", reauth_required=True)


def password_change_required() -> ApiProblem:
    return ApiProblem(403, "Choose a new password first", password_change_required=True)


def too_many(retry_after: int, detail: str | None = None) -> ApiProblem:
    seconds = max(1, int(retry_after))
    text = detail or f"Too many attempts. Try again in {_human(seconds)}."
    return ApiProblem(429, text, headers={"Retry-After": str(seconds)}, retry_after=seconds)


def busy() -> ApiProblem:
    return ApiProblem(503, "The server is busy. Try again in a moment.", headers={"Retry-After": "1"})


def https_required() -> ApiProblem:
    return ApiProblem(
        400,
        "HTTPS required: this server has more than one account, so signing in over plain HTTP is turned off. "
        "See docs/https.md.",
        https_required=True,
        help="docs/https.md",
    )


def _human(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} seconds"
    minutes = (seconds + 59) // 60
    return f"{minutes} minutes"


async def api_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiProblem)
    return exc.response()
