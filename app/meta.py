"""``GET /api/meta``: what this server is and what the signed-in person can use on it (design note 14 change 4).

For a client that is not the web page (the native iOS app of the ROADMAP, a script): ask once after sign-in, show only what works, and
read the nutrient list and the meal names from the server instead of keeping its own copy.

* ``app_version``: the server's version (``info.version`` of the OpenAPI document). ``api_version``: the integer of
  :mod:`app.api_version`, raised only for a breaking change (``docs/api/README.md``).
* ``capabilities``: booleans, true when **this person can use the thing right now**. Each one is read from a switch or a status function that
  already exists, never worked out again here:

  * ``ai``, ``ai_next_meal``, ``ai_parse_meal``, ``ai_label``, ``ai_plate``, ``ai_lab_report``, ``chat``, ``voice``: from
    :func:`app.ai.routes.status_view` (the answer of ``GET /api/ai/status``: ``available`` and ``features``), so they follow ``ai.enabled``, the
    person's opt-in, the routing of each feature, consent-independent availability, the chat switch and the voice server. All false while
    ``ai.enabled`` is off.
  * ``assistant`` and ``push``: the instance switches ``assistant.enabled`` and ``push.enabled`` (:func:`app.auth.api_tokens.is_enabled`).
  * ``barcode_off`` and ``barcode_usda``: :func:`app.barcode.providers_available` (the admin switch and, for Open Food Facts, the person's own
    consent; for USDA, a key they can use); ``barcode`` is either. A person's own foods are found by barcode without any of them.
  * ``handbook``: this server serves the built handbook at ``/learn`` (``GET /api/handbook`` ``available``).

* ``nutrients``: the registry of :mod:`app.nutrient_core`, in the server's order, with its key, label, unit and role.
* ``meals``: the meal names, in order (:data:`app.nutrient_core.MEALS`).

Signed in only, like every ``/api`` route (least trust: no anonymous listing of what a server offers). The answer holds no secret, no host name,
no key and nothing about another person, and a new capability is a new key (an additive change). The demo's copy is ``js/mock/meta.js``.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from . import barcode, handbook
from .ai import routes as ai_routes
from .api_version import API_VERSION
from .auth import api_tokens
from .auth.context import auth_context
from .auth.deps import CurrentUser, current_user
from .db import get_db
from .nutrient_core import MEALS, NUTRIENTS

router = APIRouter(prefix="/api/meta", tags=["meta"], dependencies=[Depends(current_user)])


class MetaNutrient(BaseModel):
    key: str = Field(description="The key used in every nutrient object and target.")
    label: str = Field(description="The name shown to people.")
    unit: str = Field(description="`kcal`, `g`, `mg` or `mL`.")
    role: str = Field(description="How the app treats it: `goal`, `range`, `track`, `limit` or `info`.")


class Capabilities(BaseModel):
    """True when the signed-in person can use it now. New capabilities arrive as new keys."""

    ai: bool = Field(description="The optional AI is on, the person opted in and a provider answers for at least one feature.")
    ai_next_meal: bool = Field(description="AI meal ideas (`POST /api/ai/next-meal`).")
    ai_parse_meal: bool = Field(description="Describe a meal in words (`POST /api/ai/parse-meal`).")
    ai_label: bool = Field(description="Read a nutrition label photo (`POST /api/vision/label`).")
    ai_plate: bool = Field(description="Estimate a plate from a photo (`POST /api/vision/plate`).")
    ai_lab_report: bool = Field(description="Read a lab report photo or PDF page (`POST /api/ai/read-lab-report`).")
    chat: bool = Field(description="The Ask chat (`POST /api/ai/chat`).")
    voice: bool = Field(description="Voice input for Ask (`POST /api/ai/transcribe`).")
    assistant: bool = Field(description="Assistant access tokens and the MCP server at `/mcp` are switched on (`assistant.enabled`).")
    push: bool = Field(description="Device tokens and `POST /push/v1/body` are switched on (`push.enabled`).")
    barcode: bool = Field(description="At least one barcode provider can be asked for this person.")
    barcode_off: bool = Field(description="Open Food Facts: the admin turned it on and this person agreed.")
    barcode_usda: bool = Field(description="USDA branded foods by barcode: switched on and this person has a key they can use.")
    handbook: bool = Field(description="This server serves the patient handbook at `/learn/`.")


class Meta(BaseModel):
    app_version: str = Field(description="The server's version (`info.version` of the OpenAPI document).")
    api_version: int = Field(description="The API version: an integer that is raised only for a breaking change.")
    capabilities: Capabilities
    nutrients: list[MetaNutrient] = Field(description="The nutrient registry in the server's order.")
    meals: list[str] = Field(description="The meal names in order.")


def ai_flags(request: Request, conn: sqlite3.Connection, user: Any) -> tuple[bool, dict[str, bool]]:
    """``(available, features)`` of the AI status for this person; nothing is available while ``ai.enabled`` is off."""
    if not ai_routes.ai_state(request).store.get(conn, "ai.enabled"):
        return False, {}
    view = ai_routes.status_view(request, conn, user)
    return bool(view["available"]), {name: bool(on) for name, on in view["features"].items()}


def capabilities(request: Request, conn: sqlite3.Connection, user: Any) -> dict[str, bool]:
    ctx = auth_context(request)
    available, features = ai_flags(request, conn, user)
    providers = barcode.providers_available(conn, request, user)
    served = handbook.info(getattr(request.app.state, "handbook", None), request.app.state.settings)["available"]
    return {
        "ai": available,
        "ai_next_meal": features.get("next_meal", False),
        "ai_parse_meal": features.get("parse_meal", False),
        "ai_label": features.get("label", False),
        "ai_plate": features.get("plate", False),
        "ai_lab_report": features.get("lab_report", False),
        "chat": features.get("chat", False),
        "voice": features.get("voice", False),
        "assistant": api_tokens.is_enabled(conn, ctx, api_tokens.ASSISTANT),
        "push": api_tokens.is_enabled(conn, ctx, api_tokens.DEVICE),
        "barcode": providers["off"] or providers["usda"],
        "barcode_off": providers["off"],
        "barcode_usda": providers["usda"],
        "handbook": bool(served),
    }


@router.get("", response_model=Meta)
def meta_info(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The server's version and API version, what this person can use now, the nutrient registry and the meal names."""
    return {
        "app_version": request.app.version,
        "api_version": API_VERSION,
        "capabilities": capabilities(request, conn, user),
        "nutrients": [{"key": n.key, "label": n.label, "unit": n.unit, "role": n.role} for n in NUTRIENTS],
        "meals": list(MEALS),
    }
