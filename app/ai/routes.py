"""HTTP routes of the optional AI layer (note 04 R3, R4, R9; §9 A1, A5–A8; ARCHITECTURE "M2 API: AI and photos").

* ``/api/ai/*`` (status, next-meal, parse-meal, chat, consent, the person's AI activity): every route needs a
  signed-in person **and** ``ai.enabled``; while AI is off they answer ``404 {"detail": "Not Found"}``,
  exactly as if they were not registered (checked per request, so switching AI on in Settings needs no
  restart). ``POST /api/ai/chat`` (the Ask screen) also needs ``ai.chat_enabled``.
* ``/api/me/ai`` (the person's AI choices and own provider; always registered so Settings can show the
  "AI is off on this server" state; the probe needs AI on).
* ``/api/admin/ai-providers`` and ``/api/admin/ai-usage`` (admins; writes need a recent password).
  With ``AUTH_MODE=none`` every provider write answers 403 (§9 A7): providers then come only from env.

AI routes are ``async def`` (a slow model must not hold one of the threads the SQLite routes need);
their database work runs in the thread pool on the request's own connection. Every call goes through
:mod:`app.ai.transport`; the dry run (``?dry_run=true``) returns the exact body and sends nothing.
"""
from __future__ import annotations

import contextlib
import copy
import logging
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from starlette.concurrency import run_in_threadpool

from ..auth import housekeeping as auth_housekeeping
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
from ..guidance import rules as guidance_rules
from ..mcp import tools as T
from ..models import MAX_SQLITE_INT, Meal
from ..settings_store import SettingsStore
from . import chat as CH
from . import chat_save as CS
from . import client as C
from . import config as K
from .cache import AnswerCache, CachedAnswer
from . import features as F
from . import guard, prompts, schemas
from . import stt
from . import presets as P
from . import routing as R
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
    last_purge: float | None = None  # monotonic time of the last retention purge (None: never)
    reprobe_attempts: dict[int, float] = field(default_factory=dict)  # provider id → monotonic time of the last try
    auto_reprobe: bool = True  # the daily background test (R4 step 5); tests that replay exact request sequences turn it off
    answers: AnswerCache = field(default_factory=AnswerCache)  # note 06 §4.13: a meal's checked answer, 10 minutes

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
    if not force and state.last_purge is not None and now - state.last_purge < PURGE_EVERY_S:
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


def daily_retention(conn: sqlite3.Connection, ctx: Any) -> None:
    """The AI activity retention as a daily step of the app's own housekeeping (registered in
    :func:`install`): bodies after ``ai.audit_retention_days``, rows and usage after
    ``audit.retention_days``, whether AI is on, off or simply unused (docs/ai.md "Retention")."""
    result = K.purge(conn, body_days=int(ctx.store.get(conn, "ai.audit_retention_days")),
                     row_days=int(ctx.store.get(conn, "audit.retention_days")))
    conn.commit()
    if any(result.values()):
        log.info("AI activity retention: %s", result)


def unavailable(reason: str) -> ApiProblem:
    return ApiProblem(503, K.MESSAGES.get(reason, "AI is not available."), reason=reason)


def _resolve(request: Request, conn: sqlite3.Connection, user: User, feature: str) -> K.Resolved:
    """The provider ``feature`` (photos, meal_ideas, describe or chat) uses for this person: privacy tiers, tier 1."""
    state = ai_state(request)
    return R.resolve_feature(conn, state.store, _keyring(request), state.settings, state.policy, user_id=user.id,
                             can_use_shared=user.can_use_shared, feature=feature)


def _with_cloud(resolved: K.Resolved, prep: F.Prepared, build: Callable[[C.ProviderConfig], F.Prepared]) -> F.Prepared:
    """Privacy tiers, tier 3: for the route ``local_then_cloud``, prepare the same request for the cloud AI too, exactly as the
    route ``cloud`` would send it (its own model, structured mode and prompt budget). Nothing is sent from here: :func:`run_call`
    sends it only if the local answer fails the app's checks and the person agreed. A cloud prompt budget the request does not fit
    means there is no fallback for this request, not a half-sent one."""
    fallback = resolved.fallback
    if fallback is None or fallback.cfg is None:
        return prep
    try:
        prep.cloud = build(fallback.cfg)
    except (F.ContextTooSmall, ValueError):
        log.info("no cloud fallback for %s: the request does not fit the cloud AI's prompt budget", prep.feature)
        prep.cloud = None
    return prep


async def dry_run_of(conn: sqlite3.Connection, user: User, request: Request, prep: F.Prepared) -> dict[str, Any]:
    """"What will be sent?" for a prepared call: the exact request and, for a ``local_then_cloud`` feature, that a second request
    may go to the cloud host **only if the local answer fails the app's checks** (and whether the person agreed to that host)."""
    consent = None
    if prep.cloud is not None:
        consent = await run_in_threadpool(K.consent, conn, user.id, prep.cloud.cfg, prep.cloud.purpose) is not None  # type: ignore[arg-type]
    return prep.dry_run(request.app.version, consent)


def _seconds_to_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((tomorrow - now).total_seconds()))


# --------------------------------------------------------------------------- #
# The call pipeline shared by every feature
# --------------------------------------------------------------------------- #


BUSY_TEXT = {
    "person": "Your previous AI request is still running.",
    "server": "The AI is busy with other requests. Try again in a few seconds.",
}


def check_consent(conn: sqlite3.Connection, user: User, cfg: C.ProviderConfig, purpose: str,
                  fallback: C.ProviderConfig | None = None) -> None:
    """409 ``consent_required`` (with what the person would agree to) unless they agreed to send
    ``purpose`` (``text``, ``photos`` or ``chat``) to this provider.

    This is the consent for the provider the call goes to first. A ``local_then_cloud`` feature also passes the cloud provider
    as ``fallback``: the consent sheet then names both hosts and says when the cloud one is used, but the cloud consent is not
    required here: without it the cloud AI is simply never asked (:func:`run_call`)."""
    if K.consent(conn, user.id, cfg, purpose) is None:  # type: ignore[arg-type]
        given = fallback is not None and K.consent(conn, user.id, fallback, purpose) is not None  # type: ignore[arg-type]
        raise ApiProblem(409, "Agree to send this to the AI provider first.", consent_required=True,
                         consent=K.consent_request(cfg, purpose, fallback=fallback, fallback_given=given))  # type: ignore[arg-type]


def _check_consent(conn: sqlite3.Connection, user: User, prep: F.Prepared) -> None:
    check_consent(conn, user, prep.cfg, prep.purpose, prep.cloud.cfg if prep.cloud is not None else None)


@contextlib.asynccontextmanager
async def ai_slot(request: Request, conn: sqlite3.Connection, user_id: int) -> AsyncIterator[None]:
    """Hold the person's single AI slot and one of the server's ``ai.max_concurrency`` slots for the
    block. A busy slot is refused at once with 429 ``busy_person`` / ``busy_server`` and a
    ``Retry-After``; nothing queues behind a slow model.

    The photo routes enter it **before** reading the upload, so the bodies held in memory at any
    moment are bounded by ``ai.max_concurrency`` rather than by the number of open connections."""
    state = ai_state(request)
    limit = int(await run_in_threadpool(state.store.get, conn, "ai.max_concurrency"))
    try:
        state.gate.enter(user_id, limit)
    except C.Busy as busy:
        raise ApiProblem(429, BUSY_TEXT[busy.scope], headers={"Retry-After": str(busy.retry_after)},
                         reason=f"busy_{busy.scope}") from None
    try:
        yield
    finally:
        state.gate.leave(user_id)


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
            verdict: dict[str, Any], status: str, extra: dict[str, Any] | None = None) -> int:
    """The AI activity row of one call (and its tokens). ``extra`` is for the row only: with a cloud fallback (tier 3) the local
    row says ``cloud_fallback`` (``asked`` or why not) and the cloud row ``fallback_for`` (the local row's id)."""
    keep = int(state.store.get(conn, "ai.audit_retention_days")) > 0
    K.add_tokens(conn, user.id, prep.cfg, result.usage)
    audit_id = K.write_audit(
        conn, user.id, feature=prep.feature if prep.mode is None else f"{prep.feature}:{prep.mode}", cfg=prep.cfg,
        model=prep.model, prompt_version=PROMPT_VERSION, request=prep.audit_copy(),
        response_text=result.text if prep.keep_response else None,  # a lab report's answer is health data: the row keeps none of it
        verdict={**{k: v for k, v in verdict.items() if k in ("status", "dropped", "claims_corrected", "reason", "error", "repaired", "retried",
                                                             "trimmed")}, **(extra or {})},
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
            cfg = await run_in_threadpool(R.pin_if_local, conn, state.store, state.settings, row, cfg)
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


def _cache_key(user: User, prep: F.Prepared, *, fallback: bool = False) -> tuple[Any, ...] | None:
    """The :class:`~app.ai.cache.AnswerCache` key for a guidance answer (note 06 §4.13); ``None`` for the
    features that are never reused (parse-meal text, photos).

    ``fallback``: the call is the cloud request of a ``local_then_cloud`` feature. It is kept under its own key, so an answer the
    route ``cloud`` got is never shown as "the cloud AI answered because the local one failed", and the other way round."""
    if prep.feature != "next_meal":
        return None
    return AnswerCache.key(user.id, prep.cfg.id, prep.cfg.scope + (":fallback" if fallback else ""), prep.feature, prep.mode,
                           PROMPT_VERSION, guidance_rules.rules_hash(), prep.body)


def _judge(prep: F.Prepared, parsed: Any) -> dict[str, Any]:
    try:
        return prep.judge(parsed)
    except Exception:  # a judge bug must not show unchecked output: drop everything
        log.exception("AI judge failed for %s", prep.feature)
        return {"status": "error", "reason": "judge_failed", "message": "The AI answer could not be checked, so it is not shown."}


def _answer(prep: F.Prepared, verdict: dict[str, Any], audit_id: int, *, cached: bool) -> dict[str, Any]:
    return {
        **verdict,
        "feature": prep.feature,
        "mode": prep.mode,
        "provider": {"id": prep.cfg.id, "label": prep.cfg.label, "model": prep.model, "host": prep.cfg.host},
        "prompt_version": PROMPT_VERSION,
        "audit_id": audit_id,
        "cached": cached,
        "notes": list(prep.notes),
    }


def _reuse(conn: sqlite3.Connection, user: User, prep: F.Prepared, hit: CachedAnswer) -> dict[str, Any]:
    """Note 06 §4.13: the same question within 10 minutes. Nothing is sent and no daily call is spent; the
    kept answer is checked again by the rules on the current day, and the AI activity log gets a row with
    metadata only (status ``cached``, the call it came from) so the person sees what was shown and why."""
    verdict = _judge(prep, hit.fresh_copy())
    if str(verdict.get("status", "ok")) in ("dropped_all", "no_fit") and prep.fallback is not None:
        verdict["fallback"] = prep.fallback
    verdict["trimmed"] = prep.trimmed
    audit_id = K.write_audit(
        conn, user.id, feature=f"{prep.feature}:{prep.mode}" if prep.mode else prep.feature, cfg=prep.cfg, model=prep.model,
        prompt_version=PROMPT_VERSION, request=None, response_text=None,
        verdict={**{k: v for k, v in verdict.items() if k in ("status", "dropped", "claims_corrected", "reason", "error", "trimmed")},
                 "cached_from": hit.audit_id},
        latency_ms=0, status="cached", keep_bodies=False,
    )
    conn.commit()
    return _answer(prep, verdict, audit_id, cached=True)


@dataclass
class Attempt:
    """One call to one provider: what came back, what the app's rules made of it, and its AI activity row."""

    prep: F.Prepared
    result: C.CallResult
    verdict: dict[str, Any]
    status: str
    audit_id: int | None = None

    @property
    def failed_checks(self) -> bool:
        """Did the answer fail the schema or the app's rules? This, and nothing else, sends a ``local_then_cloud`` call on to the
        cloud AI (privacy tiers, tier 3).

        True: the reply was not the expected JSON (``invalid``: no JSON, wrong shape, empty, cut short), or the judge threw all of
        it out (:func:`app.ai.features.judge_rejected`). False, so the cloud AI is **not** asked: the AI could not be reached,
        took too long or answered with an HTTP error (``error``); the call was over quota (it never started); the model declined
        (``refused``, a safety refusal); or the answer passed. Those answer exactly as with the route ``local``."""
        if self.result.status == "invalid":
            return True
        return self.result.status == "ok" and F.judge_rejected(self.verdict)

    @property
    def usable(self) -> bool:
        """An answer that may stand in for the one that failed: valid and not thrown out by the rules, or the model's own decline."""
        if self.result.status == "refused":
            return True
        return self.result.status == "ok" and not F.judge_rejected(self.verdict) and self.verdict.get("status") != "error"


def _provider_view(prep: F.Prepared) -> dict[str, Any]:
    return {"id": prep.cfg.id, "label": prep.cfg.label, "model": prep.model, "host": prep.cfg.host}


def _verdict_of(prep: F.Prepared, result: C.CallResult) -> tuple[dict[str, Any], str]:
    """The checked answer (or why there is none) and the status the AI activity row records, from one call's result."""
    if result.status == "ok":
        # The judge gets its own copy, so the answer kept for reuse is the provider's, untouched.
        verdict = _judge(prep, copy.deepcopy(result.parsed))
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
    return verdict, status


async def _send(client: C.ChatClient, prep: F.Prepared) -> Attempt:
    """The call itself (slot, tool check and quota are already taken) and the app's check of what came back."""
    result = await client.complete_json(prep.cfg, prep.body, prep.validator, vision=prep.vision)
    verdict, status = await run_in_threadpool(_verdict_of, prep, result)
    return Attempt(prep, result, verdict, status)


# Tier 3: what the person is told about the cloud AI, in plain words (docs/ai.md "Local first, cloud only when the local answer fails").
FALLBACK_NOT_ASKED = {
    "no_consent": "because you have not agreed to send this there",
    "quota_exhausted": "because today's shared AI calls are used up",
}


def _fallback_view(local: F.Prepared, cloud: F.Prepared, *, asked: bool, answered: bool, reason: str | None = None,
                   local_audit_id: int | None = None, cloud_audit_id: int | None = None, cached: bool = False) -> dict[str, Any]:
    """The answer's ``cloud_fallback``: present only when the local AI's answer failed the app's checks and the route is
    ``local_then_cloud``. ``used``: the cloud AI was sent the request (or an answer kept from an earlier one is shown);
    ``answered``: its answer is the one shown; ``reason``: why it was not asked (``no_consent``, ``quota_exhausted``, ...)."""
    host = cloud.cfg.host
    if answered:
        message = f"The local AI's answer did not pass the app's checks, so the cloud AI ({host}) answered."
    elif asked:
        message = (f"The local AI's answer did not pass the app's checks, so the cloud AI ({host}) was asked as well, "
                   "but it gave no usable answer.")
    else:
        why = FALLBACK_NOT_ASKED.get(reason or "", "right now")
        message = f"The local AI's answer did not pass the app's checks. The cloud AI ({host}) was not asked {why}."
    out: dict[str, Any] = {"used": asked, "answered": answered, "reason": reason, "message": message, "cached": cached,
                           "local": _provider_view(local), "cloud": _provider_view(cloud),
                           "local_audit_id": local_audit_id, "audit_id": cloud_audit_id}
    if reason == "no_consent":  # the page can offer to agree to it (the same sheet as any consent)
        out["consent"] = {**K.consent_request(cloud.cfg, cloud.purpose), "as_fallback": True, "rule": K.FALLBACK_RULE}  # type: ignore[arg-type]
    return out


def _kept_cloud_answer(conn: sqlite3.Connection, state: AiState, user: User, prep: F.Prepared) -> dict[str, Any] | None:
    """A cloud answer kept from an earlier fallback of the same question (10 minutes): shown again without asking either AI,
    but only while the person still has their consent for the cloud host."""
    cloud = prep.cloud
    key = _cache_key(user, cloud, fallback=True) if cloud is not None else None
    if cloud is None or key is None:
        return None
    hit = state.answers.get(key)
    if hit is None or K.consent(conn, user.id, cloud.cfg, cloud.purpose) is None:  # type: ignore[arg-type]
        return None
    answer = _reuse(conn, user, cloud, hit)
    answer["cloud_fallback"] = _fallback_view(prep, cloud, asked=True, answered=True, cached=True)
    return answer


async def _clear_fallback(request: Request, conn: sqlite3.Connection, state: AiState, user: User, cloud: F.Prepared,
                          client: C.ChatClient) -> str | None:
    """Everything that must hold before the cloud AI is sent the second request: the person's consent for that host and
    purpose, the Hermes tool check and one unit of quota. None to go ahead, else the reason it is not asked (the local
    answer is then returned as it is, as with the route ``local``)."""
    if await run_in_threadpool(K.consent, conn, user.id, cloud.cfg, cloud.purpose) is None:  # type: ignore[arg-type]
        return "no_consent"
    try:
        await tool_gate(request, conn, cloud, client)
        await run_in_threadpool(_take_quota, conn, state, user, cloud.cfg)
    except ApiProblem as exc:
        return str(exc.extra.get("reason") or "unavailable")
    return None


def _log_attempt(attempt: Attempt) -> None:
    prep, result = attempt.prep, attempt.result
    log.info("ai call feature=%s provider=%s preset=%s model=%s host=%s latency_ms=%d prompt_tokens=%d completion_tokens=%d status=%s",
             prep.feature, prep.cfg.id, prep.cfg.preset, prep.model, prep.cfg.host, result.latency_ms,
             result.usage.get("prompt_tokens", 0), result.usage.get("completion_tokens", 0), attempt.status)
    if prep.cfg.preset_def.kind == "self_hosted" and 3900 <= result.usage.get("prompt_tokens", 0) <= 4096:
        log.warning("AI provider %s used %d prompt tokens: Ollama may be cutting prompts at 4096 tokens; set "
                    "OLLAMA_CONTEXT_LENGTH (docs/ai.md, Troubleshooting)", prep.cfg.id, result.usage["prompt_tokens"])


async def run_call(request: Request, conn: sqlite3.Connection, user: User, prep: F.Prepared,
                   background: BackgroundTasks | None = None, *, slot_held: bool = False) -> dict[str, Any]:
    """Consent → (a kept answer for the same question, note 06 §4.13) → concurrency slot → tool check →
    quota → call → judge → audit. Never writes anything the person did not ask for; nothing AI-generated
    reaches the log or the food list (G12).

    The Hermes tool check runs inside the slot, so a burst of requests from one person makes at most
    one check. ``slot_held=True`` means the caller already holds the person's slot (:func:`ai_slot`;
    the photo routes take it before reading the upload). With ``background``, a shared provider that
    is due for its daily connection test gets one after the response is sent (:func:`maintenance_probe`).

    **Local first, cloud only when the local answer fails** (route ``local_then_cloud``, ``prep.cloud`` set): the call above
    goes to the local AI. Only if its answer fails the schema or the app's rules (:attr:`Attempt.failed_checks`), the same
    request, prepared for the cloud AI exactly as the route ``cloud`` would send it, goes to the cloud AI, inside the same slot,
    and only if the person has agreed to send this purpose to that host (otherwise nothing is sent and the local failure is
    returned, with ``cloud_fallback.reason == "no_consent"``). An unreachable or slow local AI, an HTTP error, an exhausted quota
    or a refusal never reach the cloud AI: they answer as with ``local``. Each call has its own quota unit and AI activity row.
    The answer names the AI that gave it (``provider``) and, after a fallback, says so in ``cloud_fallback.message``."""
    if prep.local_only and not prep.cfg.local_only:  # a local-only feature (a lab report photo) never leaves the private network
        raise unavailable("local_not_private")
    if prep.local_only:  # and never has a cloud fallback, whatever prepared it (routing already refuses local_then_cloud for it)
        prep.cloud = None
    state = ai_state(request)
    client = _client_for(request)
    await run_in_threadpool(_check_consent, conn, user, prep)
    cache_key = _cache_key(user, prep)
    if cache_key is not None:
        hit = state.answers.get(cache_key)
        if hit is not None:
            return await run_in_threadpool(_reuse, conn, user, prep, hit)
    if prep.cloud is not None:
        kept = await run_in_threadpool(_kept_cloud_answer, conn, state, user, prep)
        if kept is not None:
            return kept
    cloud = prep.cloud
    skipped: str | None = None
    second: Attempt | None = None
    async with contextlib.nullcontext() if slot_held else ai_slot(request, conn, user.id):
        await tool_gate(request, conn, prep, client)
        await run_in_threadpool(_take_quota, conn, state, user, prep.cfg)
        first = await _send(client, prep)
        fall_back = cloud is not None and first.failed_checks
        if fall_back:
            assert cloud is not None
            skipped = await _clear_fallback(request, conn, state, user, cloud, client)
        first.audit_id = await run_in_threadpool(
            _finish, conn, state, user, prep, first.result, first.verdict, first.status,
            {"cloud_fallback": skipped or "asked"} if fall_back else None)
        if fall_back and skipped is None:
            assert cloud is not None
            second = await _send(client, cloud)
            second.audit_id = await run_in_threadpool(
                _finish, conn, state, user, cloud, second.result, second.verdict, second.status, {"fallback_for": first.audit_id})
    final = second if second is not None and second.usable else first
    assert final.audit_id is not None
    final_key = _cache_key(user, final.prep, fallback=second is not None and final is second)
    if final_key is not None and final.result.status == "ok" and final.status == "ok":
        state.answers.put(final_key, final.result.parsed, final.audit_id)
    for attempt in (first, second):
        if attempt is None:
            continue
        if (background is not None and state.auto_reprobe and attempt.prep.cfg.scope == "shared"
                and await run_in_threadpool(_claim_reprobe, conn, state, attempt.prep.cfg.id)):
            background.add_task(maintenance_probe, request.app, attempt.prep.cfg.id, _server_port(request))
        _log_attempt(attempt)
    answer = _answer(final.prep, final.verdict, final.audit_id, cached=False)
    if cloud is not None and first.failed_checks:  # the route is local_then_cloud and the local answer did not pass
        answer["cloud_fallback"] = _fallback_view(
            prep, cloud, asked=second is not None, answered=final is second, reason=skipped, local_audit_id=first.audit_id,
            cloud_audit_id=None if second is None else second.audit_id)
    return answer


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
    purpose: Literal["text", "photos", "chat", "voice", "labs"] = "text"
    skip_preview: bool = False


def _person(conn: sqlite3.Connection, state: AiState, user_id: int) -> dict[str, Any]:
    """The ``person`` object of the two features that send one (meal ideas and Ask), behind the gates they already pass: the AI is
    on, the person opted in, the feature's route and the per-host consent for ``text`` or ``chat`` (checked before the request
    is sent; the dry run shows this object). Besides the profile it carries the foods and groups the person marked Like, Less
    often and Not for me (note 09 §4.7): their explicit choices by name, never a learned signal. Describe-a-meal, the photo
    features and lab reports never call this."""
    from ..profile import get_profile

    return F.person_for(get_profile(conn, user_id), K.ai_prefs(conn, state.store, user_id), _date.today(),
                        guidance_context.explicit_preferences(conn, user_id, state.store))


def _prepare_next_meal(request: Request, conn: sqlite3.Connection, user: User, body: NextMealBody) -> F.Prepared | dict[str, Any]:
    state = ai_state(request)
    day = guidance_api.parse_day(body.date)
    off = guidance_api.gate(conn, state.store, user.id, "plan" if body.mode == "plan" else None)
    if off is not None:
        return off
    resolved = _resolve(request, conn, user, "meal_ideas")
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
    person = _person(conn, state, user.id)

    def build(cfg: C.ProviderConfig) -> F.Prepared:
        return F.prepare_next_meal(ctx, cfg, meal=meal, mode=body.mode, person=person, swap=swap)  # type: ignore[arg-type]

    try:
        return _with_cloud(resolved, build(resolved.cfg), build)  # type: ignore[arg-type]
    except F.ContextTooSmall:
        raise ApiProblem(503, "The AI provider's prompt budget (AI_CONTEXT_TOKENS) is too small for this request.",
                         reason="context_too_small") from None
    except ValueError as exc:
        if "low treatments" in str(exc):
            return {"status": "treating_a_low", "cards": [gmessages.treating_a_low_card(ctx.prefs.hypo_dose_g)], "ai_called": False}
        raise


@router.get("/status")
def ai_status_route(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """What the person's AI buttons can do now: per feature where it runs (``routes``), consent, quota, photo features."""
    state = ai_state(request)
    routes = R.resolve_all(conn, state.store, _keyring(request), state.settings, state.policy, user_id=user.id,
                           can_use_shared=user.can_use_shared, require_opt_in=False)
    prefs = K.ai_prefs(conn, state.store, user.id)
    opted_in = bool(prefs.get("opt_in"))
    head = next((routes[f] for f in R.HEADLINE if routes[f].cfg is not None), routes["meal_ideas"])  # the first feature that resolves
    cfg = head.cfg
    available = cfg is not None and opted_in
    reason = head.reason if cfg is None else (None if opted_in else "not_opted_in")

    def on(feature: str) -> bool:
        return routes[feature].cfg is not None and opted_in

    photo_cfg = routes["photos"].cfg
    photos = bool(photo_cfg and photo_cfg.vision_model and _photos_allowed(conn, state, photo_cfg))
    chat_cfg = routes["chat"].cfg
    labs_cfg = routes["labs"].cfg  # local-only: the shared provider holding the role "local", never a person's own
    lab_report = on("labs") and bool(labs_cfg and labs_cfg.vision_model and labs_cfg.local_only and _photos_allowed(conn, state, labs_cfg))
    chat_on = on("chat") and bool(state.store.get(conn, "ai.chat_enabled"))
    voice_cfg = voice_config(request, conn) if chat_on else None  # voice is part of Ask: it follows the chat route
    voice = None
    if voice_cfg is not None and chat_cfg is not None:
        voice = {"host": voice_cfg.host, "model": voice_cfg.model, "max_seconds": stt.MAX_SECONDS, "max_bytes": voice_cfg.max_audio_bytes,
                 "remaining_today": stt.remaining_today(conn, user.id, voice_cfg), "consent": stt.consent(conn, user.id, chat_cfg.id, voice_cfg),
                 "request": stt.consent_request(voice_cfg, _policy_for(request), chat_cfg.id)}
    housekeeping(conn, state)
    return {
        "enabled": True,
        "opted_in": opted_in,
        "available": available,
        "reason": reason,
        "message": K.MESSAGES.get(reason) if reason else None,
        "provider": None if cfg is None else R.provider_summary(cfg),
        "consent": {**{p: (K.consent(conn, user.id, c, p) if c is not None else None)
                       for p, c in (("text", routes["meal_ideas"].cfg), ("photos", photo_cfg), ("chat", chat_cfg), ("labs", labs_cfg))},
                    "voice": None if voice_cfg is None or chat_cfg is None else stt.consent(conn, user.id, chat_cfg.id, voice_cfg)},
        "routing": {"mode": "as_before" if any(r.route == "any" for r in routes.values()) else "routed"},
        "routes": {f: R.route_view(conn, user.id, f, routes[f]) for f in R.FEATURES},
        "policy_version": P.POLICY_VERSION,
        "daily_limit": int(state.store.get(conn, "ai.shared_daily_limit")) or None,
        "remaining_today": K.remaining_today(conn, state.store, user.id) if cfg is None or cfg.key_scope == "shared" else None,
        "features": {"next_meal": on("meal_ideas"), "parse_meal": on("describe"), "label": on("photos") and photos,
                     "plate": on("photos") and photos and bool(state.store.get(conn, "ai.vision_plate_enabled")),
                     "chat": chat_on, "voice": voice is not None, "lab_report": lab_report},
        "voice": voice,
        "trust": _trust_view(conn, state, prefs),
        "prompt_version": PROMPT_VERSION,
    }


def _trust_view(conn: sqlite3.Connection, state: AiState, prefs: dict[str, Any]) -> dict[str, Any]:
    """How much the person trusts Ask to save (``setting``), whether the admin allows trusted saves (``allowed``), and
    what counts before the page's own conversation choice (``effective``: ``ask`` when not allowed)."""
    allowed = bool(state.store.get(conn, "ai.allow_trusted_saves"))
    setting = str(prefs.get("trust") or "ask")
    return {"setting": setting, "allowed": allowed, "effective": setting if allowed else "ask"}


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
        return await dry_run_of(conn, user, request, prep)
    return await run_call(request, conn, user, prep, background)


def _prepare_parse(request: Request, conn: sqlite3.Connection, user: User, body: ParseMealBody) -> F.Prepared | dict[str, Any]:
    state = ai_state(request)
    prefs = guidance_context.load_prefs(conn, state.store, user.id)
    cards = F.prefilter(body.text, prefs.hypo_dose_g)  # G7, G8: before anything else, AI is not called
    if cards is not None:
        return cards
    resolved = _resolve(request, conn, user, "describe")
    if not resolved.ok:
        raise unavailable(resolved.reason or "not_configured")
    search = F.search_function(conn, user.id)

    def build(cfg: C.ProviderConfig) -> F.Prepared:
        return F.prepare_parse_meal(cfg, body.text, search=search)

    return _with_cloud(resolved, build(resolved.cfg), build)  # type: ignore[arg-type]


@router.post("/parse-meal")
async def parse_meal(body: ParseMealBody, request: Request, user: CurrentUser, background: BackgroundTasks,
                     dry_run: bool = Query(False), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """"2 eggs, toast with butter": phrases with search terms; the person picks each match (R3)."""
    prep = await run_in_threadpool(_prepare_parse, request, conn, user, body)
    if isinstance(prep, dict):
        return prep
    if dry_run:
        return await dry_run_of(conn, user, request, prep)
    return await run_call(request, conn, user, prep, background)


# --------------------------------------------------------------------------- #
# /api/ai/chat: the Ask screen (assistant step 2, part A; docs/dev/plans/assistant-step2.md)
# --------------------------------------------------------------------------- #


def require_chat_enabled(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> None:
    """``/api/ai/chat`` behaves as unregistered (404) while ``ai.chat_enabled`` is off, or its route is ``off``
    (``ai.route.chat``; checked before the body)."""
    store = ai_state(request).store
    if not store.get(conn, "ai.chat_enabled") or store.get(conn, R.route_key("chat")) == "off":
        raise HTTPException(status_code=404, detail="Not Found")


def voice_config(request: Request, conn: sqlite3.Connection) -> stt.SttConfig | None:
    """The transcription server (``STT_BASE_URL``) when voice is available to the Ask screen: configured, the admin
    switch ``ai.voice_enabled`` on and the chat on. ``None`` otherwise (the transcribe route is then a 404)."""
    state = ai_state(request)
    cfg = getattr(request.app.state, "stt", None)
    if cfg is None or not state.store.get(conn, "ai.voice_enabled") or not state.store.get(conn, "ai.chat_enabled"):
        return None
    if state.store.get(conn, R.route_key("chat")) == "off":  # voice is part of Ask: Ask switched off by routing takes it along
        return None
    return cfg


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CH.MAX_MESSAGE_CHARS)]


class ChatBody(BaseModel):
    """The conversation so far, kept in the page only: the server stores no transcript.

    ``request_id`` is made by the page for each send (and kept when the same text is sent again after a failure): a save
    the model makes in this request carries a key made from it, so a request sent twice saves once. ``trust:
    "conversation"`` is the page saying this conversation is trusted (it forgets that at New conversation and after 12
    hours); the server honours it only for a person who chose "Trust it for this conversation" and only while the admin
    switch ``ai.allow_trusted_saves`` is on (:func:`app.ai.chat_save.effective_trust`)."""

    model_config = ConfigDict(extra="forbid")
    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=CH.MAX_MESSAGES)]
    request_id: Annotated[str, StringConstraints(min_length=CS.REQUEST_ID_MIN, max_length=CS.REQUEST_ID_MAX,
                                                 pattern=CS.REQUEST_ID_PATTERN)] | None = None
    trust: Literal["ask", "conversation"] | None = None

    @field_validator("messages")
    @classmethod
    def last_is_the_person(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if value[-1].role != "user":
            raise ValueError("the last message must be from the person")
        return value


def _chat_answer(kind: str, text: str | None, *, cards: Any = (), numbers: Any = (), notes: Any = (),
                 cfg: C.ProviderConfig | None = None, model: str = "", model_calls: int = 0, tool_calls: int = 0,
                 audit_id: int | None = None, trust: str | None = None, pending_save: dict[str, Any] | None = None,
                 saved: Any = (), questions: Any = ()) -> dict[str, Any]:
    """The Ask answer (V9: where it came from). ``label`` says the AI wrote it and the app checked it; for the
    app's own rules (a low, an emergency) it says the AI was not asked."""
    if cfg is None:
        label: dict[str, Any] = {"source": "app", "checked": True, "notice": "From the app's own rules. The AI was not asked."}
        provider = None
    else:
        label = {**guard.label(cfg.label, model), "notice": CH.NOTICE.format(label=cfg.label, model=model)}
        provider = {"id": cfg.id, "label": cfg.label, "model": model, "host": cfg.host}
    return {"feature": "chat", "kind": kind, "text": text, "cards": list(cards), "numbers": list(numbers), "notes": list(notes),
            "label": label, "provider": provider, "ai_called": cfg is not None, "model_calls": model_calls,
            "tool_calls": tool_calls, "prompt_version": PROMPT_VERSION, "audit_id": audit_id,
            "trust": trust, "pending_save": pending_save, "saved": list(saved), "questions": list(questions)}


def _chat_rules(request: Request, conn: sqlite3.Connection, user: User, text: str) -> dict[str, Any] | None:
    """The rules first, on every message and before any provider is looked at: the step-1 ``safety_check`` (the
    Treating a low card with the person's own grams; the Get help now card). The model is not called."""
    result = T.run(T.TOOLS_BY_NAME["safety_check"], T.Call(request, conn, user), {"message": text})
    found = CH.safety_outcome(result)
    if found is None:
        return None
    kind, answer, cards = found
    return _chat_answer(kind, answer, cards=cards)


def _prepare_chat(request: Request, conn: sqlite3.Connection, user: User, body: ChatBody) -> F.Prepared:
    state = ai_state(request)
    resolved = _resolve(request, conn, user, "chat")
    if not resolved.ok:
        raise unavailable(resolved.reason or "not_configured")
    cfg = resolved.cfg
    assert cfg is not None
    history = CH.history_messages([m.model_dump() for m in body.messages])
    if not history or history[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="The last message is empty")
    schema = schemas.chat_step_schema(CH.OFFERED_TOOLS)
    system = prompts.chat_system(CH.tools_text(CS.tool_schemas()), schema, _person(conn, state, user.id))
    mode = "json_object" if cfg.structured == "json_schema" else cfg.structured  # free-form arguments: see chat_step_schema

    def make(messages: list[dict[str, str]]) -> dict[str, Any]:
        request_body = C.build_body(cfg, system=system, user_text="", schema=schema, schema_name="kidney_chat", mode=mode)
        request_body["messages"] = [{"role": "system", "content": system}, *messages]
        return request_body

    window = CH.fit_history(history, lambda messages: F._fits(cfg, make(messages)))
    if window is None:
        raise ApiProblem(503, "The AI provider's prompt budget (AI_CONTEXT_TOKENS) is too small for this request.",
                         reason="context_too_small")
    return F.Prepared(feature="chat", cfg=cfg, body=make(window), validator=schemas.model_validator_for(schemas.ChatStep),
                      judge=lambda parsed: {}, purpose="chat")


def _run_chat_tool(request: Request, conn: sqlite3.Connection, user: User, name: str,
                   arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """One of the step-1 tools for this person, in a worker thread; ``(result, None)`` or ``(None, message for the model)``."""
    try:
        return T.run(T.TOOLS_BY_NAME[name], T.Call(request, conn, user), arguments), None
    except T.ToolError as exc:
        return None, str(exc)
    except Exception:  # a tool bug must not end the conversation with a 500
        log.exception("Ask chat: tool %s failed", name)
        return None, prompts.CHAT_TOOL_FAILED
    finally:
        if conn.in_transaction:  # the tools only read; leave the connection clean for the next quota step
            conn.rollback()


def _finish_chat(conn: sqlite3.Connection, state: AiState, user: User, prep: F.Prepared, result: C.CallResult,
                 info: dict[str, Any]) -> int:
    """The activity row of one model call: metadata only. No message text and no request or response body are kept
    (the server stores no transcript); the verdict names the step, the tool and the outcome."""
    K.add_tokens(conn, user.id, prep.cfg, result.usage)
    status = {"ok": "ok", "refused": "refused", "invalid": "invalid"}.get(result.status, f"error:{result.error}")
    verdict = {**{k: v for k, v in info.items() if v is not None}, "repaired": result.repaired, "retried": result.retried}
    audit_id = K.write_audit(
        conn, user.id, feature="chat", cfg=prep.cfg, model=prep.model, prompt_version=PROMPT_VERSION, request=None,
        response_text=None, verdict=verdict, latency_ms=result.latency_ms, status=status, keep_bodies=False)
    conn.commit()
    housekeeping(conn, state)
    return audit_id


def _trust_for(request: Request, conn: sqlite3.Connection, user: User, body: ChatBody) -> str:
    """``ask``, ``conversation`` or ``always`` for this request (:func:`app.ai.chat_save.effective_trust`)."""
    state = ai_state(request)
    return CS.effective_trust(admin_allows=bool(state.store.get(conn, "ai.allow_trusted_saves")),
                              stored=K.trust_setting(conn, state.store, user.id), requested=body.trust)


async def run_chat(request: Request, conn: sqlite3.Connection, user: User, prep: F.Prepared, body: ChatBody,
                   background: BackgroundTasks | None = None, *, trust: str = "ask") -> dict[str, Any]:
    """Consent → the person's slot → tool check → the step loop (:func:`app.ai.chat.converse`) with one unit of
    quota, one activity row and one provider timeout per model call → the checked answer.

    A save the model asks for follows ``trust``: ``ask`` saves nothing and answers ``confirm_save`` with the card; the
    other two save at once (all or nothing) and answer with what was saved. See :mod:`app.ai.chat_save`."""
    state = ai_state(request)
    client = _client_for(request)
    await run_in_threadpool(_check_consent, conn, user, prep)

    async def complete(request_body: dict[str, Any], index: int) -> C.CallResult:
        try:
            await run_in_threadpool(_take_quota, conn, state, user, prep.cfg)
        except ApiProblem as exc:
            if index > 0 and exc.extra.get("reason") == "quota_exhausted":
                raise CH.StopLoop("quota") from None  # the first call was allowed: end with the numbers gathered
            raise
        return await client.complete_json(prep.cfg, request_body, prep.validator)

    async def run_tool(name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        return await run_in_threadpool(_run_chat_tool, request, conn, user, name, arguments)

    async def record(result: C.CallResult, info: dict[str, Any]) -> int:
        return await run_in_threadpool(_finish_chat, conn, state, user, prep, result, info)

    request_id = body.request_id or uuid.uuid4().hex  # no id from the page: this request still saves at most once per call
    newest = body.messages[-1].text

    async def run_save(name: str, arguments: dict[str, Any], n: int) -> CH.SaveStep:
        return await run_in_threadpool(CS.run_save, request, conn, user, name, arguments, n, mode=trust,
                                       request_id=request_id, newest=newest)

    async with ai_slot(request, conn, user.id):
        await tool_gate(request, conn, prep, client)
        outcome = await CH.converse(
            prep.body, person_texts=[m.text for m in body.messages if m.role == "user"], newest=newest,
            complete=complete, run_tool=run_tool, record=record, fits=lambda request_body: F._fits(prep.cfg, request_body),
            run_save=run_save)
    text = outcome.text
    if outcome.kind == "error":
        text = guard.REFUSED_TEXT if outcome.refused else ERROR_TEXT.get(outcome.error or "", "The AI request failed.")
    if (background is not None and state.auto_reprobe and prep.cfg.scope == "shared"
            and await run_in_threadpool(_claim_reprobe, conn, state, prep.cfg.id)):
        background.add_task(maintenance_probe, request.app, prep.cfg.id, _server_port(request))
    log.info("ai call feature=chat provider=%s preset=%s model=%s host=%s model_calls=%d tool_calls=%d kind=%s reason=%s "
             "trust=%s saves=%d",
             prep.cfg.id, prep.cfg.preset, prep.model, prep.cfg.host, outcome.model_calls, outcome.tool_calls, outcome.kind,
             outcome.reason, trust, len(outcome.saves))
    shown_questions = outcome.questions if not outcome.saves and outcome.pending is None else []
    return _chat_answer(outcome.kind, text, numbers=CH.numbers_view(outcome.runs), notes=outcome.notes, cfg=prep.cfg,
                        model=prep.model, model_calls=outcome.model_calls, tool_calls=outcome.tool_calls,
                        audit_id=outcome.audit_id, trust=trust, pending_save=outcome.pending, saved=outcome.saves,
                        questions=shown_questions)


@router.post("/chat", dependencies=[Depends(require_chat_enabled)])
async def chat(body: ChatBody, request: Request, user: CurrentUser, background: BackgroundTasks,
               dry_run: bool = Query(False), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """One message of the Ask conversation: the rules answer a low or an emergency without the model; otherwise the
    model looks up the app's own numbers with its read-only tools and its answer is checked in code before it is shown."""
    rules = await run_in_threadpool(_chat_rules, request, conn, user, body.messages[-1].text)
    if rules is not None:
        return rules
    prep = await run_in_threadpool(_prepare_chat, request, conn, user, body)
    if dry_run:
        return prep.dry_run(request.app.version)
    trust = await run_in_threadpool(_trust_for, request, conn, user, body)
    return await run_chat(request, conn, user, prep, body, background, trust=trust)


@router.post("/consent")
def give_consent(body: ConsentBody, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Agree to send data to a provider that now serves a feature of this purpose (``text``: meal ideas and
    describe-a-meal, which may be routed to different providers; ``photos``; ``chat``), R9 step 3. ``voice`` is not
    routed: the recording goes to the transcription server (``STT_BASE_URL``), and the consent rides with Ask, keyed to
    the AI provider that serves Ask now (``chat``), so it follows Ask if Ask is moved to another provider."""
    if body.purpose == "voice":
        chat = _resolve(request, conn, user, "chat")
        if not chat.ok or chat.cfg is None:
            raise unavailable(chat.reason or "not_configured")
        voice = voice_config(request, conn)
        if voice is None:
            raise HTTPException(status_code=404, detail="Not Found")
        asked = stt.consent_request(voice, _policy_for(request), chat.cfg.id)
        if chat.cfg.id != body.provider_id:
            raise ApiProblem(409, "The AI provider changed; review what will be sent again.", consent=asked)
        given = stt.give_consent(conn, user.id, chat.cfg.id, voice)
        conn.commit()
        return {"consent": given, **asked}
    serving = [_resolve(request, conn, user, feature) for feature in R.features_for_purpose(body.purpose)]
    usable = [r.cfg for r in serving if r.cfg is not None]
    if not usable:
        raise unavailable(next((r.reason for r in serving if r.reason), None) or "not_configured")
    # A ``local_then_cloud`` feature also asks for the cloud AI it falls back to (the consent for that host is separate: without it
    # the cloud AI is never asked).
    fallbacks = [r.fallback.cfg for r in serving if r.fallback is not None and r.fallback.cfg is not None]
    cfg = next((c for c in [*usable, *fallbacks] if c.id == body.provider_id), None)
    if cfg is None:
        first = next(r for r in serving if r.cfg is not None)
        raise ApiProblem(409, "The AI provider changed; review what will be sent again.",
                         consent=K.consent_request(usable[0], body.purpose, fallback=first.fallback.cfg if first.fallback is not None else None))
    given = K.give_consent(conn, user.id, cfg, body.purpose, skip_preview=body.skip_preview)
    conn.commit()
    return {"consent": given, **K.consent_request(cfg, body.purpose)}


@router.delete("/consent/{provider_id}", status_code=204, response_class=Response)
def withdraw_consent(provider_id: Annotated[int, Path(ge=1, le=MAX_SQLITE_INT)], request: Request, user: CurrentUser,
                     purpose: Literal["text", "photos", "chat", "voice", "labs"] | None = None, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    if not K.withdraw_consent(conn, user.id, provider_id, purpose):
        raise HTTPException(status_code=404, detail="no consent for this provider")
    conn.commit()
    ai_state(request).answers.drop_user(user.id)  # no AI answer is shown again without consent
    return Response(status_code=204)


@router.get("/audit")
def my_ai_activity(user: CurrentUser, before: Annotated[int, Query(ge=1, le=MAX_SQLITE_INT)] | None = None,
                   limit: Annotated[int, Query(ge=1, le=200)] = 50, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's own AI activity: what was sent, what came back, what the rules decided (R9 step 5)."""
    return {"events": K.audit_rows(conn, user.id, before=before, limit=limit)}


@router.delete("/audit", status_code=204, response_class=Response)
def delete_my_ai_activity(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """"Delete my AI history" (R9 step 5), with the answers kept for reuse. Usage counts stay (they hold no content)."""
    conn.execute("DELETE FROM ai_audit WHERE user_id = ?", (user.id,))
    conn.commit()
    ai_state(request).answers.drop_user(user.id)
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
    trust: Annotated[str, StringConstraints(pattern=r"^(ask|conversation|always)$")] | None = None


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
    routes = R.resolve_all(conn, state.store, keyring, state.settings, state.policy, user_id=user.id,
                           can_use_shared=user.can_use_shared, require_opt_in=False) if enabled else None
    shared = [] if not user.can_use_shared else [
        {"id": int(r["id"]), "label": r["label"], "host": parse_base_url(r["base_url"]).display_host, "kind": P.get(r["preset"]).kind,
         "policy": P.policy_line(P.get(r["preset"]), scope="shared"), "photos": bool(r["vision_model"]), "usable": K.usable(r)}
        for r in K.shared_rows(conn)
    ]
    return {
        "enabled": enabled,
        "settings": K.ai_prefs(conn, state.store, user.id),
        "chat_enabled": bool(state.store.get(conn, "ai.chat_enabled")),
        "trusted_saves_allowed": bool(state.store.get(conn, "ai.allow_trusted_saves")),
        "user_keys_allowed": bool(state.store.get(conn, "ai.user_keys_allowed")),
        "allow_user_base_url": allow_custom,
        "own": None if own is None else K.provider_view(own, keyring, state.settings),
        "shared": shared,
        "routing": None if routes is None else {
            "mode": "as_before" if any(r.route == "any" for r in routes.values()) else "routed",
            "features": R.me_summary(routes, conn, user.id)},
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
    before = K.ai_prefs(conn, state.store, user.id)
    merged = {**before, **body.model_dump(exclude_none=True)}
    from ..settings_store import InvalidSettingValue

    try:
        state.store.set_user(conn, user.id, "ai", merged)
        K.audit_trust_change(conn, user.id, before.get("trust") or "ask", merged.get("trust") or "ask", ip=request_ip(request))
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
        cfg = await run_in_threadpool(R.pin_if_local, conn, state.store, state.settings, row, cfg)
    except InvalidToken:
        raise unavailable("own_key_unreadable" if row["scope"] == "user" else "provider_disabled") from None
    snippets: list[str] = []

    def snippet(data: bytes) -> None:
        from ..security import redact

        snippets.append(redact(data.decode("utf-8", "replace"))[:300])

    client = _client_for(request)
    async with ai_slot(request, conn, user.id):  # a refused (busy) test spends no quota
        await run_in_threadpool(_take_quota, conn, state, user, cfg, 1, not admin)
        result = await C.probe(client, cfg, error_snippet=snippet if admin and row["scope"] == "shared" else None)

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


def voice_admin_view(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """The transcription server as an admin sees it (read-only: it is set with ``STT_*``; the key is never shown)."""
    state = ai_state(request)
    cfg = getattr(request.app.state, "stt", None)
    out: dict[str, Any] = {"configured": cfg is not None, "enabled": bool(state.store.get(conn, "ai.voice_enabled"))}
    if cfg is None:
        return out
    problem = None
    try:
        check_url(cfg.base, "shared", _policy_for(request))
    except PolicyError as exc:
        problem = str(exc)
    return {**out, "host": cfg.host, "model": cfg.model, "key_set": bool(cfg.api_key), "local": stt.is_local(cfg, _policy_for(request)),
            "daily_limit": cfg.daily_limit or None, "max_seconds": stt.MAX_SECONDS, "max_bytes": cfg.max_audio_bytes, "problem": problem}


def admin_list(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    state = ai_state(request)
    keyring = _keyring(request)
    presets = K.presets_view(user=False, allow_custom=True)
    for p in presets:
        if p["tool_check"]:
            p["key_help"] = "Paste the key of the dedicated tool-free profile, never your main Hermes profile's key."
    return {
        "providers": [{**K.provider_view(r, keyring, state.settings), "role": R.role_of(conn, state.store, state.settings, r),
                       "private_host": R.is_private(r, state.policy)} for r in K.shared_rows(conn)],
        "presets": presets,
        "private_hosts": state.policy.private_hosts.entries(),  # AI_PRIVATE_HOSTS, read-only
        "deny_cidrs": [str(n) for n in state.policy.deny],
        "proxy": bool(state.policy.proxy),
        "env_provider": bool(state.settings.ai.provider),
        "writable": state.settings.auth_mode != "none",
        "voice": voice_admin_view(request, conn),
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
    if R.role_of(conn, state.store, state.settings, row) == "local" and not R.is_private_host(data.base_url, state.policy):
        raise ApiProblem(400, "This provider is your local AI, so its address must stay on your own network (listed in AI_PRIVATE_HOSTS). "
                         "Choose another local AI under Which AI does each feature use? first.", field="base_url", reason="not_private")
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
    roles = R.drop_role(conn, ai_state(request).store, provider_id, updated_by=admin.id)  # a role never points at a deleted provider
    audit(conn, admin.id, "ai_provider.changed", "ai_provider", provider_id, ip=request_ip(request), change="deleted", roles_cleared=roles)
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


StructuredRoute = Literal["local", "cloud", "off", "any", "local_then_cloud"]  # tier 3: local first, the cloud only if the answer fails the checks
LocalOnlyRoute = Literal["local", "off"]
ProviderId = Annotated[int, Field(ge=0, le=1_000_000_000)]


class RoutingBody(BaseModel):
    """Any subset: a route per feature, and the shared provider holding each role (0 clears it)."""

    model_config = ConfigDict(extra="forbid")
    photos: StructuredRoute | None = None
    meal_ideas: StructuredRoute | None = None
    describe: StructuredRoute | None = None
    chat: StructuredRoute | None = None  # read here so that R.plan refuses local_then_cloud for Ask with its own reason (400)
    labs: LocalOnlyRoute | None = None  # local or off only: a lab report photo never goes to a cloud AI
    local_provider: ProviderId | None = None
    cloud_provider: ProviderId | None = None


@admin_router.get("/ai-routing")
def read_ai_routing(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Which AI each feature uses and which shared provider is local or cloud (docs/ai.md)."""
    state = ai_state(request)
    return R.overview(conn, state.store, state.settings, state.policy)


@admin_router.put("/ai-routing")
def update_ai_routing(body: RoutingBody, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Change the routing. A provider whose host the network policy does not treat as private cannot be the local AI."""
    _none_mode_refusal(request)
    state = ai_state(request)
    given = body.model_dump(exclude_none=True)
    features = {f: given[f] for f in R.FEATURES if f in given}
    providers = {r: given[f"{r}_provider"] for r in R.ROLES if f"{r}_provider" in given}
    if not features and not providers:
        raise ApiProblem(400, "Nothing to change.")
    try:
        changed = R.apply(conn, state.store, R.plan(conn, state.store, state.settings, state.policy, features=features, providers=providers),
                          updated_by=admin.id)
    except R.RoutingError as exc:
        conn.rollback()
        raise ApiProblem(exc.status, str(exc), **({"field": exc.field} if exc.field else {}), **exc.extra) from None
    ip = request_ip(request)
    for key, old, new in changed:
        audit(conn, admin.id, "settings.changed", "setting", key, ip=ip, key=key, old=old, new=new)
    conn.commit()
    return R.overview(conn, state.store, state.settings, state.policy)


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
        resolved = R.resolve_feature(conn, state.store, keyring, state.settings, state.policy, user_id=user_id,
                                     can_use_shared=bool(row["can_use_shared"]) if row is not None else False, feature="meal_ideas")
        return {"available": resolved.ok, "provider_label": resolved.cfg.label if resolved.cfg else None}

    return provider


def install(app: FastAPI, settings: Settings, store: SettingsStore, *, app_version: str) -> AiState:
    """Check the AI environment (``ConfigError`` stops the start), create the client, add the routes,
    feed guidance's ``ai`` block. Nothing is contacted until a person asks."""
    for warning in K.check_env(settings):
        log.warning("configuration: %s", warning)
    import os

    policy = K.build_policy(settings, kubernetes_host=os.environ.get("KUBERNETES_SERVICE_HOST"))
    for warning in stt.check_env(settings, policy):  # the speech-to-text server (STT_*), under the same address rules
        log.warning("configuration: %s", warning)
    state = AiState(settings=settings, store=store, client=C.ChatClient(policy, app_version=app_version))
    app.state.ai = state
    app.state.stt = stt.load(settings)
    auth_housekeeping.register_daily("ai_retention", daily_retention)
    app.include_router(combined)
    ai_bridge.register_ai_status(status_provider(app))
    return state


def startup(app: FastAPI, conn: sqlite3.Connection) -> None:
    """At start-up: keep the env provider row in step with ``AI_PROVIDER`` and run the retention purge."""
    state: AiState = app.state.ai
    R.initialise(conn, state.store)  # before the environment provider is synced: it decides "upgraded" or "new" from what is stored
    K.sync_env_provider(conn, state.settings, getattr(app.state, "keyring", None))
    conn.commit()
    housekeeping(conn, state, force=True)


__all__ = ["AiState", "install", "startup", "run_call", "require_ai_enabled", "ai_state"]
