"""``POST /api/ai/transcribe``: one voice clip becomes text for the Ask input box (assistant step 2, part B).

The logic is in :mod:`app.ai.stt`; this module is the HTTP side. The order of the checks, each before the next
and all of them before the audio is read:

1. signed in (401) → ``ai.enabled`` (404) → ``ai.voice_enabled``, ``ai.chat_enabled`` and ``STT_BASE_URL`` (404, as if
   the route were not there);
2. the person can use the AI at all (503 ``not_opted_in`` and the like), the content type is one of four audio
   types (415) and a declared size is within ``STT_MAX_AUDIO_BYTES`` (413, also the body-limit middleware's job);
3. the person's consent for the purpose ``voice`` to this transcription host (409 ``consent_required``);
4. the person's one AI slot, then the body is read (at most ``STT_MAX_AUDIO_BYTES``, with a time limit), its first
   bytes must be the declared container (400) and a WAV must not be longer than 60 seconds (413);
5. the daily limit (429), the call through the SSRF-checked transport, one activity row **without content**.

The audio and the transcript are never written to disk or the database and never logged; only the text goes back.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import struct
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from ..auth.context import auth_context
from ..auth.deps import CurrentUser, RecentAdmin, current_user, require_admin
from ..auth.errors import ApiProblem
from ..auth.models import User
from ..db import get_db
from ..security import register_body_limit
from . import stt
from .routes import (PROBE_LIMIT_ADMIN, _client_for, _policy_for, _resolve, _seconds_to_midnight, ai_slot, ai_state, housekeeping,
                     require_ai_enabled, unavailable, voice_config)
from .transport import AiTransportError

log = logging.getLogger("kidney_health.ai")

router = APIRouter(prefix="/api/ai", tags=["ai", "voice"], dependencies=[Depends(current_user), Depends(require_ai_enabled)])
admin_router = APIRouter(prefix="/api/admin", tags=["admin", "ai", "voice"], dependencies=[Depends(require_admin)])
register_body_limit("/api/ai/transcribe", "max_audio_bytes")

READ_TIMEOUT_S = 30.0  # a clip at the size limit on a slow link; a slower upload must not hold the person's AI slot longer


def require_voice(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> None:
    """``/api/ai/transcribe`` behaves as unregistered (404) unless voice is on and configured (checked before the body)."""
    if voice_config(request, conn) is None:
        raise HTTPException(status_code=404, detail="Not Found")


def _too_large(limit: int) -> ApiProblem:
    return ApiProblem(413, f"The recording is larger than {limit // 1024} KiB.", reason="too_large")


def clip_headers(request: Request, limit: int) -> str:
    """Check the upload's headers without reading it: the container named by the content type (415) and a declared
    ``Content-Length`` within the limit (413)."""
    try:
        kind = stt.content_type_kind(request.headers.get("content-type"))
    except stt.AudioRejected as exc:
        raise ApiProblem(exc.status, str(exc), reason=exc.reason) from None
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _too_large(limit)
    return kind


async def read_clip(request: Request, limit: int) -> bytearray:
    """The request body in memory (never a file), at most ``limit`` bytes, within :data:`READ_TIMEOUT_S`."""
    declared = request.headers.get("content-length")
    data = bytearray()
    try:
        async with asyncio.timeout(READ_TIMEOUT_S):
            async for chunk in request.stream():
                if len(data) + len(chunk) > limit:
                    raise _too_large(limit)
                data += chunk
    except TimeoutError:
        raise ApiProblem(408, "The recording took too long to arrive. Try again on a faster connection.", reason="upload_timeout") from None
    if declared is not None and declared.isdigit() and int(declared) != len(data):
        raise ApiProblem(400, "The recording arrived incomplete. Try again.", reason="incomplete")
    return data


def _take_quota(conn: sqlite3.Connection, user: User, cfg: stt.SttConfig) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        ok = stt.take_quota(conn, user.id, cfg)
    except Exception:
        conn.rollback()
        raise
    if not ok:
        conn.rollback()
        raise ApiProblem(429, "Today's voice recordings are used up. They start again at midnight (UTC).",
                         headers={"Retry-After": str(_seconds_to_midnight())}, reason="quota_exhausted")
    conn.commit()


def _record(conn: sqlite3.Connection, request: Request, user: User, cfg: stt.SttConfig, bucket: str, status: str, latency_ms: int) -> None:
    """The activity row (no content) and nothing else."""
    stt.write_audit(conn, user.id, cfg, bucket=bucket, status=status, latency_ms=latency_ms)
    conn.commit()
    housekeeping(conn, ai_state(request))


def _consent_or_409(conn: sqlite3.Connection, request: Request, user: User, cfg: stt.SttConfig, ai_provider_id: int) -> None:
    if stt.consent(conn, user.id, ai_provider_id, cfg) is None:
        raise ApiProblem(409, "Agree to send your recording to the transcription server first.", consent_required=True,
                         consent=stt.consent_request(cfg, _policy_for(request), ai_provider_id))


@router.post("/transcribe", dependencies=[Depends(require_voice)])
async def transcribe(request: Request, user: CurrentUser, seconds: Annotated[int, Query(ge=0, le=stt.MAX_SECONDS)] | None = None,
                     conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """One recording (the request body, ``audio/webm``, ``audio/ogg``, ``audio/mp4`` or ``audio/wav``) → ``{"text": ...}``.

    ``seconds`` is the page's own measure of the length, used only for the activity row's coarse length bucket."""
    cfg = voice_config(request, conn)
    assert cfg is not None  # require_voice
    resolved = await run_in_threadpool(_resolve, request, conn, user, "chat")  # voice is part of Ask: it follows the chat route
    if not resolved.ok or resolved.cfg is None:
        raise unavailable(resolved.reason or "not_configured")
    kind = clip_headers(request, cfg.max_audio_bytes)
    await run_in_threadpool(_consent_or_409, conn, request, user, cfg, resolved.cfg.id)
    client = _client_for(request)
    async with ai_slot(request, conn, user.id):
        audio = await read_clip(request, cfg.max_audio_bytes)
        try:
            measured = stt.check_clip(kind, audio)
        except stt.AudioRejected as exc:
            raise ApiProblem(exc.status, str(exc), reason=exc.reason) from None
        bucket = stt.duration_bucket(measured if measured is not None else (float(seconds) if seconds is not None else None))
        await run_in_threadpool(_take_quota, conn, user, cfg)
        try:
            text, latency_ms = await stt.transcribe(cfg, _policy_for(request), client.transport_factory, kind, audio,
                                                    app_version=request.app.version)
        except AiTransportError as exc:
            await run_in_threadpool(_record, conn, request, user, cfg, bucket, f"error:{exc.category}", 0)
            log.info("ai call feature=voice host=%s model=%s duration=%s outcome=error:%s", cfg.host, cfg.model, bucket, exc.category)
            raise ApiProblem(502, stt.ERROR_TEXT.get(exc.category, "The transcription failed."), reason=exc.category) from None
        finally:
            del audio
    await run_in_threadpool(_record, conn, request, user, cfg, bucket, "ok", latency_ms)
    log.info("ai call feature=voice host=%s model=%s duration=%s outcome=ok", cfg.host, cfg.model, bucket)
    return {"text": text}


# --------------------------------------------------------------------------- #
# Admin: "Test transcription"
# --------------------------------------------------------------------------- #


def silent_wav(seconds: int = 1, rate: int = 16_000) -> bytes:
    """A 16-bit mono WAV of silence: all the admin's test sends (no recording of anybody, nothing to keep)."""
    data = b"\x00\x00" * (rate * seconds)
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
              + b"data" + struct.pack("<I", len(data)))
    return header + data


@admin_router.post("/ai-voice/probe")
async def probe_voice(request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Test transcription: one second of silence through the same transport and address rules. It needs AI on and
    ``STT_BASE_URL``; the answer's text is neither returned nor kept (a speech model may "hear" words in silence),
    only whether the server answered a transcription."""
    state = ai_state(request)
    cfg = getattr(request.app.state, "stt", None)
    if cfg is None or not await run_in_threadpool(state.store.get, conn, "ai.enabled"):
        raise HTTPException(status_code=404, detail="Not Found")
    auth_context(request).limits.take(PROBE_LIMIT_ADMIN, f"user:{admin.id}")
    client = _client_for(request)
    try:
        _, latency_ms = await stt.transcribe(cfg, _policy_for(request), client.transport_factory, "wav", silent_wav(),
                                             app_version=request.app.version)
    except AiTransportError as exc:
        log.info("voice test host=%s outcome=error:%s", cfg.host, exc.category)
        return {"probe": {"ok": False, "error": exc.category, "message": stt.ERROR_TEXT.get(exc.category, "The test failed.")}}
    log.info("voice test host=%s outcome=ok", cfg.host)
    return {"probe": {"ok": True, "latency_ms": latency_ms}}
