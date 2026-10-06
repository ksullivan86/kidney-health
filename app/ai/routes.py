"""HTTP routes of the optional AI layer (note 04 R3, R4, R9; §9 A1, A5–A8; ARCHITECTURE "M2 API: AI and photos").

* ``/api/ai/*`` (status, next-meal, parse-meal, consent, the person's AI activity): every route needs a
  signed-in person **and** ``ai.enabled``; while AI is off they answer ``404 {"detail": "Not Found"}``,
  exactly as if they were not registered (checked per request, so switching AI on in Settings needs no
  restart).
* ``/api/me/ai`` (the person's AI choices and own provider; always registered so Settings can show the
  "AI is off on this server" state; the probe needs AI on).
* ``/api/admin/ai-providers`` and ``/api/admin/ai-usage`` (admins; writes need a recent password).
  With ``AUTH_MODE=none`` every provider write answers 403 (§9 A7): providers then come only from env.

AI routes are ``async def`` (a slow model must not hold one of the threads the SQLite routes need);
their database work runs in the thread pool on the request's own connection. Every call goes through
:mod:`app.ai.transport`; the dry run (``?dry_run=true``) returns the exact body and sends nothing.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from starlette.concurrency import run_in_threadpool

from ..auth.context import auth_context, request_ip
from ..auth.deps import AdminUser, CurrentUser, RecentAdmin, RecentUser, current_user, require_admin
from ..auth.errors import ApiProblem
from ..auth.models import User
from ..auth.ratelimit import register_limit
from ..audit import audit
from ..config import Settings
from ..credentials import InvalidCredential, validate_api_key
from ..crypto import InvalidToken
from ..db import connect, get_db
from ..guidance import ai_bridge
from ..guidance import api as guidance_api
from ..guidance import context as guidance_context
from ..guidance import messages as gmessages
from ..models import MAX_SQLITE_INT, Meal
from ..settings_store import SettingsStore
from . import client as C
from . import config as K
from . import features as F
from . import presets as P
from .netpolicy import BaseUrl, PolicyError, check_url, parse_base_url
from .prompts import PROMPT_VERSION

log = logging.getLogger("kidney_health.ai")

register_limit("ai_probe_admin", 20, 3600, "Too many connection tests. Try again later.")
NONE_MODE_DETAIL = "Set AI providers with environment variables when sign-in is off"  # §9 A7
PURGE_EVERY_S = 86_400
PROBE_LIMIT = "ai_probe"
PROBE_LIMIT_ADMIN = "ai_probe_admin"
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/@+\-]+$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

ERROR_TEXT = {
    "dns_failed": "The AI server could not be reached.",
    "connect_failed": "The AI server could not be reached.",
    "timeout": "The AI server took too long to answer.",
    "blocked_address": "This AI server's address is not allowed on this server (docs/ai.md, \"Addresses\").",
    "invalid_url": "This AI server's address is not valid.",
    "http_401": "The AI server refused the key.",
    "http_403": "The AI server refused the request (key or model not allowed).",
    "http_404": "The AI server does not know this model or address.",
    "http_429": "The AI server is busy or out of credit. Try again later.",
    "http_4xx": "The AI server refused the request.",
    "http_5xx": "The AI server had an error.",
    "invalid_response": "The AI answer could not be used.",
    "no_json": "The AI answer could not be used.",
    "schema": "The AI answer could not be used.",
    "empty": "The AI answer was empty.",
    "truncated": "The AI answer was cut short.",
}


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


@dataclass
class AiState:
    settings: Settings
    store: SettingsStore
    client: C.ChatClient
    gate: C.ConcurrencyGate = field(default_factory=C.ConcurrencyGate)
    last_purge: float = 0.0
    reprobe_attempts: dict[int, float] = field(default_factory=dict)  # provider id → monotonic time of the last try
    auto_reprobe: bool = True  # the daily background test (R4 step 5); tests that replay exact request sequences turn it off

    @property
    def policy(self):  # noqa: ANN201 - NetPolicy
        return self.client.policy


def ai_state(request: Request) -> AiState:
    return request.app.state.ai


def require_ai_enabled(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> None:
    """``/api/ai/*`` and ``/api/vision/*`` behave as unregistered (404) while ``ai.enabled`` is off."""
    if not ai_state(request).store.get(conn, "ai.enabled"):
        raise HTTPException(status_code=404, detail="Not Found")


def _keyring(request: Request):  # noqa: ANN202 - Keyring
    return auth_context(request).require_keyring()


def _policy_for(request: Request):  # noqa: ANN202
    return ai_state(request).policy.with_self_port(_server_port(request))


def _client_for(request: Request) -> C.ChatClient:
    state = ai_state(request)
    policy = _policy_for(request)
    if policy is state.client.policy:
        return state.client
    return C.ChatClient(policy, app_version=state.client.app_version, transport_factory=state.client.transport_factory,
                        sleep=state.client._sleep)


def housekeeping(conn: sqlite3.Connection, state: AiState, *, force: bool = False) -> None:
    """Daily retention purge (§9 A8), run at start-up and from AI request paths (no background threads)."""
    now = time.monotonic()
    if not force and now - state.last_purge < PURGE_EVERY_S:
        return
    state.last_purge = now
    try:
        result = K.purge(conn, body_days=int(state.store.get(conn, "ai.audit_retention_days")),
                         row_days=int(state.store.get(conn, "audit.retention_days")))
        conn.commit()
        if any(result.values()):
            log.info("AI activity retention: %s", result)
    except sqlite3.Error:
        log.exception("AI activity retention purge failed")
        if conn.in_transaction:
            conn.rollback()


def unavailable(reason: str) -> ApiProblem:
    return ApiProblem(503, K.MESSAGES.get(reason, "AI is not available."), reason=reason)


def _resolve(request: Request, conn: sqlite3.Connection, user: User) -> K.Resolved:
    state = ai_state(request)
    return K.resolve(conn, state.store, _keyring(request), state.settings, user_id=user.id, can_use_shared=user.can_use_shared)


def _seconds_to_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((tomorrow - now).total_seconds()))


# --------------------------------------------------------------------------- #
# The call pipeline shared by every feature
# --------------------------------------------------------------------------- #


def _check_consent(conn: sqlite3.Connection, user: User, prep: F.Prepared) -> None:
    if K.consent(conn, user.id, prep.cfg, prep.purpose) is None:  # type: ignore[arg-type]
        raise ApiProblem(409, "Agree to send this to the AI provider first.", consent_required=True,
                         consent=K.consent_request(prep.cfg, prep.purpose))  # type: ignore[arg-type]


async def tool_gate(request: Request, conn: sqlite3.Connection, prep: F.Prepared, client: C.ChatClient) -> None:
    """§9 A1: a Hermes provider's tools are checked at most 5 minutes before a call and before every
    photo call; a failed check switches the provider off until a check passes."""
    if not prep.cfg.preset_def.tool_check:
        return
    row = await run_in_threadpool(K.provider_row, conn, prep.cfg.id)
    checked = K.tools_checked_at(row) if row is not None else None
    if not prep.vision and checked is not None and time.time() - checked < C.HERMES_CHECK_TTL_S and row["disabled_reason"] is None:
        return
    check = await C.hermes_tools_check(client, prep.cfg)

    def store() -> None:
        current = K.provider_row(conn, prep.cfg.id)
        if current is not None:
            K.record_tool_check(conn, current, check.ok, check.reason)
            conn.commit()

    await run_in_threadpool(store)
    if not check.ok:
        code = "hermes_tools" if check.reason == C.HERMES_TOOLS_REASON else "hermes_check_failed"
        log.warning("AI provider %s refused: Hermes tool check failed (%s)", prep.cfg.id, code)
        raise ApiProblem(503, check.reason or C.HERMES_CHECK_FAILED, reason=code)


def _take_quota(conn: sqlite3.Connection, state: AiState, user: User, cfg: C.ProviderConfig, requests: int = 1,
                enforce: bool = True) -> None:
    limit = int(state.store.get(conn, "ai.shared_daily_limit")) if enforce else 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        ok = K.take_quota(conn, user.id, cfg, limit, requests=requests)
    except Exception:
        conn.rollback()
        raise
    if not ok:
        conn.rollback()
        raise ApiProblem(429, "Today's shared AI calls are used up. They start again at midnight (UTC).",
                         headers={"Retry-After": str(_seconds_to_midnight())}, reason="quota_exhausted")
    conn.commit()


def _finish(conn: sqlite3.Connection, state: AiState, user: User, prep: F.Prepared, result: C.CallResult,
            verdict: dict[str, Any], status: str) -> int:
    keep = int(state.store.get(conn, "ai.audit_retention_days")) > 0
    K.add_tokens(conn, user.id, prep.cfg, result.usage)
    audit_id = K.write_audit(
        conn, user.id, feature=prep.feature if prep.mode is None else f"{prep.feature}:{prep.mode}", cfg=prep.cfg,
        model=prep.model, prompt_version=PROMPT_VERSION, request=prep.audit_copy(), response_text=result.text,
        verdict={k: v for k, v in verdict.items() if k in ("status", "dropped", "claims_corrected", "reason", "error", "repaired", "retried",
                                                          "trimmed")},
        latency_ms=result.latency_ms, status=status, keep_bodies=keep,
    )
    conn.commit()
    housekeeping(conn, state)
    return audit_id


def _claim_reprobe(conn: sqlite3.Connection, state: AiState, provider_id: int) -> bool:
    """Whether this call should start the daily re-test of a shared provider (R4 step 5): the test is
    due and nobody started one in the last hour (a failing provider is not hammered)."""
    if not K.reprobe_due(K.provider_row(conn, provider_id)):
        return False
    now = time.monotonic()
    last = state.reprobe_attempts.get(provider_id)
    if last is not None and now - last < K.REPROBE_RETRY_S:
        return False
    state.reprobe_attempts[provider_id] = now
    return True


async def maintenance_probe(app: FastAPI, provider_id: int, server_port: int | None = None) -> None:
    """The daily connection test of a shared provider, run after a response has been sent (R4 step 5).

    It opens its own database connection, takes a server slot under a pseudo-person (or skips when the
    server is busy), stores the result like "Test connection" does (a failed Hermes tool check switches
    the provider off, §9 A1) and counts toward nobody's quota. Errors are logged, never raised."""
    state: AiState = app.state.ai
    keyring = getattr(app.state, "keyring", None)
    if keyring is None:
        return
    conn = connect(state.settings.db_path)
    slot = -int(provider_id)  # never a real user id
    try:
        row = await run_in_threadpool(K.provider_row, conn, provider_id)
        if not K.reprobe_due(row):
            return
        try:
            cfg = await run_in_threadpool(K.to_config, row, keyring, state.settings, user_id=0)
        except InvalidToken:
            log.warning("AI provider %s: daily connection test skipped, its key cannot be decrypted", provider_id)
            return
        try:
            state.gate.enter(slot, int(await run_in_threadpool(state.store.get, conn, "ai.max_concurrency")))
        except C.Busy:
            return
        try:
            client = state.client
            if server_port:
                policy = state.policy.with_self_port(server_port)
                if policy is not state.policy:
                    client = C.ChatClient(policy, app_version=client.app_version, transport_factory=client.transport_factory,
                                          sleep=client._sleep)
            result = await C.probe(client, cfg)
        finally:
            state.gate.leave(slot)
        if row["locked"]:
            result["key_fp"] = K.key_fingerprint(keyring, state.settings.ai.api_key)

        def store() -> None:
            current = K.provider_row(conn, provider_id)
            if current is not None and (current["base_url"], current["model"]) == (row["base_url"], row["model"]):
                K.save_probe(conn, provider_id, result)
                conn.commit()

        await run_in_threadpool(store)
        log.info("AI provider %s: daily connection test ok=%s structured=%s", provider_id, result.get("ok"), result.get("structured"))
    except Exception:  # a background job must never take the server down
        log.exception("AI provider %s: daily connection test failed", provider_id)
    finally:
        conn.close()


def _server_port(request: Request) -> int | None:
    server = request.scope.get("server")
    return server[1] if isinstance(server, (tuple, list)) and len(server) > 1 else None


async def run_call(request: Request, conn: sqlite3.Connection, user: User, prep: F.Prepared,
                   background: BackgroundTasks | None = None) -> dict[str, Any]:
    """Consent → tool check → concurrency slot → quota → call → judge → audit. Never writes anything
    the person did not ask for; nothing AI-generated reaches the log or the food list (G12).

    With ``background``, a shared provider that is due for its daily connection test gets one after
    the response is sent (:func:`maintenance_probe`)."""
    state = ai_state(request)
    client = _client_for(request)
    await run_in_threadpool(_check_consent, conn, user, prep)
    await tool_gate(request, conn, prep, client)
    try:
        state.gate.enter(user.id, int(await run_in_threadpool(state.store.get, conn, "ai.max_concurrency")))
    except C.Busy as busy:
        detail = ("Your previous AI request is still running." if busy.scope == "person"
                  else "The AI is busy with other requests. Try again in a few seconds.")
        raise ApiProblem(429, detail, headers={"Retry-After": str(busy.retry_after)}, reason=f"busy_{busy.scope}") from None
    try:
        await run_in_threadpool(_take_quota, conn, state, user, prep.cfg)
        result = await client.complete_json(prep.cfg, prep.body, prep.validator, vision=prep.vision)
    finally:
        state.gate.leave(user.id)
    if result.status == "ok":
        try:
            verdict = await run_in_threadpool(prep.judge, result.parsed)
        except Exception:  # a judge bug must not show unchecked output: drop everything
            log.exception("AI judge failed for %s", prep.feature)
            verdict = {"status": "error", "reason": "judge_failed", "message": "The AI answer could not be checked, so it is not shown."}
        status = str(verdict.get("status", "ok"))
        if status in ("dropped_all", "no_fit") and prep.fallback is not None:
            verdict["fallback"] = prep.fallback
    elif result.status == "refused":
        verdict = {"status": "refused", "message": "This is outside what the app's AI helps with. Your care team can answer it."}
        status = "refused"
    else:
        reason = result.error or result.status
        verdict = {"status": "error", "reason": reason, "message": ERROR_TEXT.get(reason, "The AI request failed.")}
        if prep.fallback is not None:
            verdict["fallback"] = prep.fallback
        status = "invalid" if result.status == "invalid" else f"error:{reason}"
    verdict["repaired"] = result.repaired
    verdict["retried"] = result.retried
    verdict["trimmed"] = prep.trimmed
    audit_id = await run_in_threadpool(_finish, conn, state, user, prep, result, verdict, status)
    if (background is not None and state.auto_reprobe and prep.cfg.scope == "shared"
            and await run_in_threadpool(_claim_reprobe, conn, state, prep.cfg.id)):
        background.add_task(maintenance_probe, request.app, prep.cfg.id, _server_port(request))
    log.info("ai call feature=%s provider=%s preset=%s model=%s host=%s latency_ms=%d prompt_tokens=%d completion_tokens=%d status=%s",
             prep.feature, prep.cfg.id, prep.cfg.preset, prep.model, prep.cfg.host, result.latency_ms,
             result.usage.get("prompt_tokens", 0), result.usage.get("completion_tokens", 0), status)
    if prep.cfg.preset_def.kind == "self_hosted" and 3900 <= result.usage.get("prompt_tokens", 0) <= 4096:
        log.warning("AI provider %s used %d prompt tokens: Ollama may be cutting prompts at 4096 tokens; set "
                    "OLLAMA_CONTEXT_LENGTH (docs/ai.md, Troubleshooting)", prep.cfg.id, result.usage["prompt_tokens"])
    return {
        **verdict,
        "feature": prep.feature,
        "mode": prep.mode,
        "provider": {"id": prep.cfg.id, "label": prep.cfg.label, "model": prep.model, "host": prep.cfg.host},
        "prompt_version": PROMPT_VERSION,
        "audit_id": audit_id,
        "notes": [gmessages.DISCLAIMER],
    }


# --------------------------------------------------------------------------- #
# /api/ai
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(current_user), Depends(require_ai_enabled)])


class NextMealBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meal: Meal
    date: str | None = None
    mode: Literal["ideas", "rerank", "swap", "plan"] = "ideas"
    entry_id: Annotated[int, Field(ge=1, le=MAX_SQLITE_INT)] | None = None  # swap: a planned entry
    food_id: Annotated[int, Field(ge=1, le=MAX_SQLITE_INT)] | None = None  # swap: a food not logged yet
    servings: Annotated[float, Field(gt=0, le=20, allow_inf_nan=False)] | None = None


class ParseMealBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    meal: Meal | None = None
    date: str | None = None


class ConsentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: Annotated[int, Field(ge=1, le=MAX_SQLITE_INT)]
    purpose: Literal["text", "photos"] = "text"
    skip_preview: bool = False


def _person(conn: sqlite3.Connection, state: AiState, user_id: int) -> dict[str, Any]:
    from ..profile import get_profile

    return F.person_for(get_profile(conn, user_id), K.ai_prefs(conn, state.store, user_id), _date.today())


def _prepare_next_meal(request: Request, conn: sqlite3.Connection, user: User, body: NextMealBody) -> F.Prepared | dict[str, Any]:
    state = ai_state(request)
    day = guidance_api.parse_day(body.date)
    off = guidance_api.gate(conn, state.store, user.id, "plan" if body.mode == "plan" else None)
    if off is not None:
        return off
    resolved = _resolve(request, conn, user)
    if not resolved.ok:
        raise unavailable(resolved.reason or "not_configured")
    ctx = guidance_api.load_ctx(request, conn, user.id, day)
    if not guidance_context.has_targets(ctx.profile):
        return guidance_api.unavailable("no_targets", gmessages.NO_TARGETS)
    swap = None
    meal = body.meal
    if body.mode == "swap":
        if (body.entry_id is None) == (body.food_id is None):
            raise HTTPException(status_code=400, detail="swap mode needs either entry_id or food_id (with servings)")
        if body.entry_id is not None:
            row = guidance_context.entry_for_swap(conn, user.id, body.entry_id)
            if row is None or int(row["food_id"]) not in ctx.foods:
                raise HTTPException(status_code=404, detail=f"log entry {body.entry_id} not found")
            if row["date"] != day:
                ctx = guidance_api.load_ctx(request, conn, user.id, row["date"])
            food, servings, purpose, meal = ctx.foods[int(row["food_id"])], float(row["servings"]), row["purpose"], row["meal"]
            ctx = ctx.with_day(tuple(e for e in ctx.day if e.id != int(row["id"])))
        else:
            if body.food_id not in ctx.foods:
                raise HTTPException(status_code=404, detail=f"food {body.food_id} not found")
            food, servings, purpose = ctx.foods[body.food_id], float(body.servings or 1.0), None
        if purpose == "hypo" or food.hypo:
            return {"status": "treating_a_low", "cards": [gmessages.treating_a_low_card(ctx.prefs.hypo_dose_g)], "ai_called": False,
                    "message": "Low treatments are never sent to AI."}
        swap = (food, servings, purpose)
    try:
        return F.prepare_next_meal(ctx, resolved.cfg, meal=meal, mode=body.mode, person=_person(conn, state, user.id), swap=swap)  # type: ignore[arg-type]
    except F.ContextTooSmall:
        raise ApiProblem(503, "The AI provider's prompt budget (AI_CONTEXT_TOKENS) is too small for this request.",
                         reason="context_too_small") from None
    except ValueError as exc:
        if "low treatments" in str(exc):
            return {"status": "treating_a_low", "cards": [gmessages.treating_a_low_card(ctx.prefs.hypo_dose_g)], "ai_called": False}
        raise


@router.get("/status")
def ai_status_route(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """What the person's AI buttons can do now (provider, consent, quota, photo features)."""
    state = ai_state(request)
    resolved = K.resolve(conn, state.store, _keyring(request), state.settings, user_id=user.id,
                         can_use_shared=user.can_use_shared, require_opt_in=False)
    prefs = K.ai_prefs(conn, state.store, user.id)
    cfg = resolved.cfg
    available = cfg is not None and bool(prefs.get("opt_in"))
    reason = resolved.reason if cfg is None else (None if prefs.get("opt_in") else "not_opted_in")
    photos = bool(cfg and cfg.vision_model and _photos_allowed(conn, state, cfg))
    housekeeping(conn, state)
    return {
        "enabled": True,
        "opted_in": bool(prefs.get("opt_in")),
        "available": available,
        "reason": reason,
        "message": K.MESSAGES.get(reason) if reason else None,
        "provider": None if cfg is None else {
            "id": cfg.id, "label": cfg.label, "host": cfg.host, "model": cfg.model, "vision_model": cfg.vision_model,
            "scope": cfg.scope, "kind": cfg.preset_def.kind, "policy": P.policy_line(cfg.preset_def, scope=cfg.scope),
        },
        "consent": None if cfg is None else {p: K.consent(conn, user.id, cfg, p) for p in ("text", "photos")},
        "policy_version": P.POLICY_VERSION,
        "daily_limit": int(state.store.get(conn, "ai.shared_daily_limit")) or None,
        "remaining_today": K.remaining_today(conn, state.store, user.id) if cfg is None or cfg.key_scope == "shared" else None,
        "features": {"next_meal": available, "parse_meal": available, "label": available and photos,
                     "plate": available and photos and bool(state.store.get(conn, "ai.vision_plate_enabled"))},
        "prompt_version": PROMPT_VERSION,
    }


def _photos_allowed(conn: sqlite3.Connection, state: AiState, cfg: C.ProviderConfig) -> bool:
    return cfg.preset_def.photos_by_default or bool(state.store.get(conn, "ai.vision_allow_agent"))


@router.post("/next-meal")
async def next_meal(body: NextMealBody, request: Request, user: CurrentUser, background: BackgroundTasks,
                    dry_run: bool = Query(False), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """AI ideas, order, swap picks or plan picks for one meal, checked by the rules (R3, note 06 §4.13)."""
    prep = await run_in_threadpool(_prepare_next_meal, request, conn, user, body)
    if isinstance(prep, dict):
        return prep
    if dry_run:
        return prep.dry_run(request.app.version)
    return await run_call(request, conn, user, prep, background)


def _prepare_parse(request: Request, conn: sqlite3.Connection, user: User, body: ParseMealBody) -> F.Prepared | dict[str, Any]:
    state = ai_state(request)
    prefs = guidance_context.load_prefs(conn, state.store, user.id)
    cards = F.prefilter(body.text, prefs.hypo_dose_g)  # G7, G8: before anything else, AI is not called
    if cards is not None:
        return cards
    resolved = _resolve(request, conn, user)
    if not resolved.ok:
        raise unavailable(resolved.reason or "not_configured")
    return F.prepare_parse_meal(resolved.cfg, body.text, search=F.search_function(conn, user.id))  # type: ignore[arg-type]


@router.post("/parse-meal")
async def parse_meal(body: ParseMealBody, request: Request, user: CurrentUser, background: BackgroundTasks,
                     dry_run: bool = Query(False), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """"2 eggs, toast with butter": phrases with search terms; the person picks each match (R3)."""
    prep = await run_in_threadpool(_prepare_parse, request, conn, user, body)
    if isinstance(prep, dict):
        return prep
    if dry_run:
        return prep.dry_run(request.app.version)
    return await run_call(request, conn, user, prep, background)


@router.post("/consent")
def give_consent(body: ConsentBody, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Agree to send data to the provider that serves you now, for text or for photos (R9 step 3)."""
    resolved = _resolve(request, conn, user)
    if not resolved.ok:
        raise unavailable(resolved.reason or "not_configured")
    cfg = resolved.cfg
    assert cfg is not None
    if cfg.id != body.provider_id:
        raise ApiProblem(409, "The AI provider changed; review what will be sent again.", consent=K.consent_request(cfg, body.purpose))
    given = K.give_consent(conn, user.id, cfg, body.purpose, skip_preview=body.skip_preview)
    conn.commit()
    return {"consent": given, **K.consent_request(cfg, body.purpose)}


@router.delete("/consent/{provider_id}", status_code=204, response_class=Response)
def withdraw_consent(provider_id: Annotated[int, Path(ge=1, le=MAX_SQLITE_INT)], user: CurrentUser,
                     purpose: Literal["text", "photos"] | None = None, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    if not K.withdraw_consent(conn, user.id, provider_id, purpose):
        raise HTTPException(status_code=404, detail="no consent for this provider")
    conn.commit()
    return Response(status_code=204)


@router.get("/audit")
def my_ai_activity(user: CurrentUser, before: Annotated[int, Query(ge=1, le=MAX_SQLITE_INT)] | None = None,
                   limit: Annotated[int, Query(ge=1, le=200)] = 50, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's own AI activity: what was sent, what came back, what the rules decided (R9 step 5)."""
    return {"events": K.audit_rows(conn, user.id, before=before, limit=limit)}


@router.delete("/audit", status_code=204, response_class=Response)
def delete_my_ai_activity(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """"Delete my AI history" (R9 step 5). Usage counts stay (they hold no content)."""
    conn.execute("DELETE FROM ai_audit WHERE user_id = ?", (user.id,))
    conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# /api/me/ai
# --------------------------------------------------------------------------- #

me_router = APIRouter(prefix="/api/me/ai", tags=["ai"], dependencies=[Depends(current_user)])


class MeAiPatch(BaseModel):
    """Any subset of the ``ai`` setting (no key fields: §9 A6)."""

    model_config = ConfigDict(extra="forbid")
    opt_in: bool | None = None
    provider: Annotated[str, StringConstraints(pattern=r"^(auto|own|shared:[1-9][0-9]{0,17})$")] | None = None
    share_age_sex: bool | None = None
    preferences: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class OwnProviderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str
    model: ModelName
    base_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    vision_model: ModelName | None = None
    api_key: SecretStr | None = None  # write-only; leave out to keep the stored key
    remove_key: bool = False


def _none_mode_refusal(request: Request) -> None:
    if ai_state(request).settings.auth_mode == "none":
        raise ApiProblem(403, NONE_MODE_DETAIL)


def _secret(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    key = value.get_secret_value()
    try:
        return validate_api_key(key)
    except InvalidCredential as exc:
        raise ApiProblem(400, f"api_key: {exc}", field="api_key") from None


def me_view(request: Request, conn: sqlite3.Connection, user: User) -> dict[str, Any]:
    state = ai_state(request)
    keyring = _keyring(request)
    enabled = bool(state.store.get(conn, "ai.enabled"))
    allow_custom = bool(state.store.get(conn, "ai.allow_user_base_url")) and not state.settings.ai.http_proxy
    own = K.own_row(conn, user.id)
    shared = [] if not user.can_use_shared else [
        {"id": int(r["id"]), "label": r["label"], "host": parse_base_url(r["base_url"]).display_host, "kind": P.get(r["preset"]).kind,
         "policy": P.policy_line(P.get(r["preset"]), scope="shared"), "photos": bool(r["vision_model"]), "usable": K.usable(r)}
        for r in K.shared_rows(conn)
    ]
    return {
        "enabled": enabled,
        "settings": K.ai_prefs(conn, state.store, user.id),
        "user_keys_allowed": bool(state.store.get(conn, "ai.user_keys_allowed")),
        "allow_user_base_url": allow_custom,
        "own": None if own is None else K.provider_view(own, keyring, state.settings),
        "shared": shared,
        "presets": K.presets_view(user=True, allow_custom=allow_custom),
        "consents": K.consents_of(conn, user.id),
        "daily_limit": int(state.store.get(conn, "ai.shared_daily_limit")) or None,
        "remaining_today": K.remaining_today(conn, state.store, user.id),
    }


@me_router.get("")
def read_my_ai(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return me_view(request, conn, user)


@me_router.patch("")
def update_my_ai(body: MeAiPatch, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    state = ai_state(request)
    merged = {**K.ai_prefs(conn, state.store, user.id), **body.model_dump(exclude_none=True)}
    from ..settings_store import InvalidSettingValue

    try:
        state.store.set_user(conn, user.id, "ai", merged)
    except InvalidSettingValue as exc:
        conn.rollback()
        raise ApiProblem(400, str(exc)) from None
    conn.commit()
    return me_view(request, conn, user)


def _own_input(conn: sqlite3.Connection, state: AiState, body: OwnProviderBody) -> K.ProviderInput:
    if not state.store.get(conn, "ai.user_keys_allowed"):
        raise ApiProblem(403, "Your admin has turned off personal AI providers.")
    try:
        preset = P.get(body.preset)
    except KeyError:
        raise ApiProblem(400, f"preset: use one of {', '.join(P.USER_PRESETS)}", field="preset") from None
    custom = preset.kind == "custom"
    if not (preset.user_allowed or custom):
        raise ApiProblem(400, f"preset: use one of {', '.join(P.USER_PRESETS)}", field="preset")
    if custom and (not state.store.get(conn, "ai.allow_user_base_url") or state.settings.ai.http_proxy):
        raise ApiProblem(403, "Your admin has not allowed personal AI server addresses.")
    raw = body.base_url if custom else preset.base_url
    if custom and not raw:
        raise ApiProblem(400, "base_url: enter the server's address (https://…/v1)", field="base_url")
    base = _checked_url(raw or "", "user", state)
    return K.ProviderInput(preset=preset.name, label=preset.label if not custom else f"Your server ({base.display_host})",
                           base_url=base, model=body.model, vision_model=body.vision_model, timeout_s=None, max_tokens=None,
                           context_tokens=None, structured="auto", reasoning_effort=None)


def _checked_url(raw: str, scope: Literal["shared", "user"], state: AiState) -> BaseUrl:
    try:
        base = parse_base_url(raw)
        check_url(base, scope, state.policy)
    except PolicyError as exc:
        raise ApiProblem(400, f"base_url: {exc}", field="base_url", reason=exc.category) from None
    return base


@me_router.put("/provider")
def set_my_provider(body: OwnProviderBody, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's own provider (OpenAI, OpenRouter, Nous Portal; a custom https server when allowed).
    The key is write-only: it is sealed to this row and shown as ``{set, last4}`` only."""
    _none_mode_refusal(request)
    state = ai_state(request)
    data = _own_input(conn, state, body)
    key = _secret(body.api_key)
    row = K.own_row(conn, user.id)
    preset = P.get(data.preset)
    if row is None:
        if preset.key_required and key is None:
            raise ApiProblem(400, "api_key: this provider needs your key", field="api_key")
        pid = K.insert_provider(conn, data, owner_user_id=user.id, updated_by=user.id)
    else:
        pid = int(row["id"])
        K.update_provider(conn, row, data, updated_by=user.id)
        if key is None and (body.remove_key or row["preset"] != data.preset):
            K.seal_key(conn, _keyring(request), pid, user.id, None)
    if key is not None:
        K.seal_key(conn, _keyring(request), pid, user.id, key)
        K.clear_probe(conn, pid)
        audit(conn, user.id, "secret.set", "secret", f"ai:{pid}", ip=request_ip(request), provider="ai", scope="user")
    stored = K.provider_row(conn, pid)
    if preset.key_required and stored is not None and stored["api_key_enc"] is None:
        conn.rollback()
        raise ApiProblem(400, "api_key: this provider needs your key", field="api_key")
    conn.commit()
    return me_view(request, conn, user)


@me_router.delete("/provider", status_code=204, response_class=Response)
def delete_my_provider(request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    row = K.own_row(conn, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="you have no AI provider of your own")
    conn.execute("DELETE FROM ai_providers WHERE id = ?", (row["id"],))
    audit(conn, user.id, "secret.removed", "secret", f"ai:{row['id']}", ip=request_ip(request), provider="ai", scope="user")
    prefs = K.ai_prefs(conn, ai_state(request).store, user.id)
    if prefs.get("provider") == "own":
        ai_state(request).store.set_user(conn, user.id, "ai", {**prefs, "provider": "auto"})
    conn.commit()
    return Response(status_code=204)


async def _probe_row(request: Request, conn: sqlite3.Connection, user: User, row: Any, *, admin: bool) -> dict[str, Any]:
    state = ai_state(request)
    try:
        cfg = await run_in_threadpool(K.to_config, row, _keyring(request), state.settings, user_id=user.id)
    except InvalidToken:
        raise unavailable("own_key_unreadable" if row["scope"] == "user" else "provider_disabled") from None
    await run_in_threadpool(_take_quota, conn, state, user, cfg, 1, not admin)
    snippets: list[str] = []

    def snippet(data: bytes) -> None:
        from ..security import redact

        snippets.append(redact(data.decode("utf-8", "replace"))[:300])

    client = _client_for(request)
    try:
        state.gate.enter(user.id, int(await run_in_threadpool(state.store.get, conn, "ai.max_concurrency")))
    except C.Busy as busy:
        raise ApiProblem(429, "The AI is busy. Try again in a few seconds.", headers={"Retry-After": str(busy.retry_after)},
                         reason=f"busy_{busy.scope}") from None
    try:
        result = await C.probe(client, cfg, error_snippet=snippet if admin and row["scope"] == "shared" else None)
    finally:
        state.gate.leave(user.id)

    if row["locked"]:
        result["key_fp"] = K.key_fingerprint(_keyring(request), state.settings.ai.api_key)

    def store() -> None:
        current = K.provider_row(conn, int(row["id"]))
        if current is not None:
            K.save_probe(conn, int(row["id"]), result)
            extra = max(0, int(result.get("requests", 1)) - 1)
            if extra:
                K.take_quota(conn, user.id, cfg, 0, requests=extra)  # counted, never refused afterwards
        conn.commit()

    await run_in_threadpool(store)
    out = {k: result.get(k) for k in ("ok", "structured", "vision", "tools", "models", "warnings", "errors")}
    if snippets:
        out["error_body"] = snippets[0]  # shared providers, admins only (R5 step 6)
    return out


@me_router.post("/probe")
async def probe_my_provider(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Test your own provider (5 per hour; counts toward today's AI calls; §9 A5 e)."""
    state = ai_state(request)
    if not await run_in_threadpool(state.store.get, conn, "ai.enabled"):
        raise HTTPException(status_code=404, detail="Not Found")
    row = await run_in_threadpool(K.own_row, conn, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="you have no AI provider of your own")
    auth_context(request).limits.take(PROBE_LIMIT, f"user:{user.id}")
    return {"probe": await _probe_row(request, conn, user, row, admin=False)}


# --------------------------------------------------------------------------- #
# /api/admin/ai-providers, /api/admin/ai-usage
# --------------------------------------------------------------------------- #

admin_router = APIRouter(prefix="/api/admin", tags=["admin", "ai"], dependencies=[Depends(require_admin)])


class AdminProviderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str
    model: ModelName
    label: Label | None = None
    base_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    vision_model: ModelName | None = None
    api_key: SecretStr | None = None
    remove_key: bool = False
    timeout_s: Annotated[float, Field(ge=K.TIMEOUT_RANGE[0], le=K.TIMEOUT_RANGE[1], allow_inf_nan=False)] | None = None
    max_tokens: Annotated[int, Field(ge=K.MAX_TOKENS_RANGE[0], le=K.MAX_TOKENS_RANGE[1])] | None = None
    context_tokens: Annotated[int, Field(ge=K.CONTEXT_RANGE[0], le=K.CONTEXT_RANGE[1])] | None = None
    structured: Literal["auto", "json_schema", "json_object", "prompt"] = "auto"
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    enabled: bool = True

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str | None) -> str | None:
        from ..textclean import clean_label

        return clean_label(value, max_len=80) if value else value


def _admin_input(state: AiState, body: AdminProviderBody) -> K.ProviderInput:
    try:
        preset = P.get(body.preset)
    except KeyError as exc:
        raise ApiProblem(400, f"preset: {exc.args[0]}", field="preset") from None
    raw = body.base_url or preset.base_url
    if not raw:
        raise ApiProblem(400, "base_url: this preset needs the server's address (…/v1)", field="base_url")
    base = _checked_url(raw, "shared", state)
    return K.ProviderInput(preset=preset.name, label=body.label or preset.label, base_url=base, model=body.model,
                           vision_model=body.vision_model, timeout_s=body.timeout_s, max_tokens=body.max_tokens,
                           context_tokens=body.context_tokens, structured=body.structured, reasoning_effort=body.reasoning_effort)


def _shared_row_or_404(conn: sqlite3.Connection, provider_id: int) -> Any:
    row = K.provider_row(conn, provider_id)
    if row is None or row["scope"] != "shared":
        raise HTTPException(status_code=404, detail=f"AI provider {provider_id} not found")
    return row


def admin_list(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    state = ai_state(request)
    keyring = _keyring(request)
    presets = K.presets_view(user=False, allow_custom=True)
    for p in presets:
        if p["tool_check"]:
            p["key_help"] = "Paste the key of the dedicated tool-free profile, never your main Hermes profile's key."
    return {
        "providers": [K.provider_view(r, keyring, state.settings) for r in K.shared_rows(conn)],
        "presets": presets,
        "private_hosts": state.policy.private_hosts.entries(),  # AI_PRIVATE_HOSTS, read-only
        "deny_cidrs": [str(n) for n in state.policy.deny],
        "proxy": bool(state.policy.proxy),
        "env_provider": bool(state.settings.ai.provider),
        "writable": state.settings.auth_mode != "none",
    }


@admin_router.get("/ai-providers")
def list_ai_providers(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return admin_list(request, conn)


@admin_router.post("/ai-providers", status_code=201)
def create_ai_provider(body: AdminProviderBody, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _none_mode_refusal(request)
    state = ai_state(request)
    data = _admin_input(state, body)
    key = _secret(body.api_key)
    if P.get(data.preset).key_required and key is None:
        raise ApiProblem(400, "api_key: this provider needs a key", field="api_key")
    pid = K.insert_provider(conn, data, owner_user_id=None, updated_by=admin.id)
    if not body.enabled:
        conn.execute("UPDATE ai_providers SET enabled = 0 WHERE id = ?", (pid,))
    if key is not None:
        K.seal_key(conn, _keyring(request), pid, None, key)
    audit(conn, admin.id, "ai_provider.changed", "ai_provider", pid, ip=request_ip(request), change="created",
          preset=data.preset, host=data.base_url.display_host, model=data.model, key_set=key is not None)
    conn.commit()
    return K.provider_view(K.provider_row(conn, pid), _keyring(request), state.settings)


@admin_router.put("/ai-providers/{provider_id}")
def update_ai_provider(provider_id: Annotated[int, Path(ge=1, le=MAX_SQLITE_INT)], body: AdminProviderBody, request: Request,
                       admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _none_mode_refusal(request)
    state = ai_state(request)
    row = _shared_row_or_404(conn, provider_id)
    if row["locked"]:
        raise ApiProblem(409, "This provider is set by the server's environment (AI_PROVIDER) and cannot be changed here.", locked=True)
    data = _admin_input(state, body)
    key = _secret(body.api_key)
    host_changed = K.update_provider(conn, row, data, updated_by=admin.id)
    conn.execute("UPDATE ai_providers SET enabled = ? WHERE id = ?", (int(body.enabled), provider_id))
    if key is not None:
        K.seal_key(conn, _keyring(request), provider_id, None, key)
        K.clear_probe(conn, provider_id)
    elif body.remove_key:
        K.seal_key(conn, _keyring(request), provider_id, None, None)
    stored = K.provider_row(conn, provider_id)
    if P.get(data.preset).key_required and stored["api_key_enc"] is None:
        conn.rollback()
        raise ApiProblem(400, "api_key: this provider needs a key", field="api_key")
    audit(conn, admin.id, "ai_provider.changed", "ai_provider", provider_id, ip=request_ip(request), change="updated",
          preset=data.preset, host=data.base_url.display_host, model=data.model, key_set=key is not None,
          consents_reset=host_changed, enabled=body.enabled)
    conn.commit()
    return K.provider_view(K.provider_row(conn, provider_id), _keyring(request), state.settings)


@admin_router.delete("/ai-providers/{provider_id}", status_code=204, response_class=Response)
def delete_ai_provider(provider_id: Annotated[int, Path(ge=1, le=MAX_SQLITE_INT)], request: Request, admin: RecentAdmin,
                       conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _none_mode_refusal(request)
    row = _shared_row_or_404(conn, provider_id)
    if row["locked"]:
        raise ApiProblem(409, "This provider is set by the server's environment (AI_PROVIDER); unset it there.", locked=True)
    conn.execute("DELETE FROM ai_providers WHERE id = ?", (provider_id,))
    audit(conn, admin.id, "ai_provider.changed", "ai_provider", provider_id, ip=request_ip(request), change="deleted")
    conn.commit()
    return Response(status_code=204)


@admin_router.post("/ai-providers/{provider_id}/probe")
async def probe_ai_provider(provider_id: Annotated[int, Path(ge=1, le=MAX_SQLITE_INT)], request: Request, admin: RecentAdmin,
                            conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Test connection (R4): models, structured mode, vision, and the Hermes tool check (20 per hour)."""
    row = await run_in_threadpool(_shared_row_or_404, conn, provider_id)
    auth_context(request).limits.take(PROBE_LIMIT_ADMIN, f"user:{admin.id}")
    probe = await _probe_row(request, conn, admin, row, admin=True)
    view = await run_in_threadpool(lambda: K.provider_view(K.provider_row(conn, provider_id), _keyring(request), ai_state(request).settings))
    return {"probe": probe, "provider": view}


@admin_router.get("/ai-usage")
def ai_usage(admin: AdminUser, days: Annotated[int, Query(ge=1, le=366)] = 30, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Counts only (requests and tokens per person and provider); admins never see AI content (R9)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT u.user_id, us.username, u.provider_id, u.key_scope, SUM(u.requests) AS requests,
                  SUM(u.prompt_tokens) AS prompt_tokens, SUM(u.completion_tokens) AS completion_tokens
           FROM ai_usage u LEFT JOIN users us ON us.id = u.user_id WHERE u.day >= ?
           GROUP BY u.user_id, u.provider_id, u.key_scope ORDER BY u.user_id, u.provider_id""",
        (since,),
    ).fetchall()
    return {"days": days, "usage": [{k: r[k] for k in r.keys()} for r in rows]}


# --------------------------------------------------------------------------- #
# Installation
# --------------------------------------------------------------------------- #

combined = APIRouter()
combined.include_router(router)
combined.include_router(me_router)
combined.include_router(admin_router)


def status_provider(app: FastAPI):  # noqa: ANN201 - the ai_bridge status callable
    """``next-meal``'s ``ai`` block (note 06 §4.13): available when AI is on, the person opted in and a
    provider resolves. Takes no quota and sends nothing."""

    def provider(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
        state: AiState = app.state.ai
        keyring = getattr(app.state, "keyring", None)
        if keyring is None or not state.store.get(conn, "ai.enabled"):
            return {"available": False, "provider_label": None}
        row = conn.execute("SELECT can_use_shared FROM users WHERE id = ?", (int(user_id),)).fetchone()
        resolved = K.resolve(conn, state.store, keyring, state.settings, user_id=user_id,
                             can_use_shared=bool(row["can_use_shared"]) if row is not None else False)
        return {"available": resolved.ok, "provider_label": resolved.cfg.label if resolved.cfg else None}

    return provider


def install(app: FastAPI, settings: Settings, store: SettingsStore, *, app_version: str) -> AiState:
    """Check the AI environment (``ConfigError`` stops the start), create the client, add the routes,
    feed guidance's ``ai`` block. Nothing is contacted until a person asks."""
    for warning in K.check_env(settings):
        log.warning("configuration: %s", warning)
    import os

    policy = K.build_policy(settings, kubernetes_host=os.environ.get("KUBERNETES_SERVICE_HOST"))
    state = AiState(settings=settings, store=store, client=C.ChatClient(policy, app_version=app_version))
    app.state.ai = state
    app.include_router(combined)
    ai_bridge.register_ai_status(status_provider(app))
    return state


def startup(app: FastAPI, conn: sqlite3.Connection) -> None:
    """At start-up: keep the env provider row in step with ``AI_PROVIDER`` and run the retention purge."""
    state: AiState = app.state.ai
    K.sync_env_provider(conn, state.settings, getattr(app.state, "keyring", None))
    conn.commit()
    housekeeping(conn, state, force=True)


__all__ = ["AiState", "install", "startup", "run_call", "require_ai_enabled", "ai_state"]
