"""``POST /api/vision/label`` and ``POST /api/vision/plate``: the two photo features (note 03 R8, R9 and
§9 B1, B10; note 04 R3 read-label / identify-food and §9 A4). One set of routes, no duplicates under
``/api/ai``; backed by :func:`app.ai.features.prepare_read_label` and :func:`app.ai.features.prepare_plate`.

* Registered with the AI routes and like them **404 while ``ai.enabled`` is off**; a signed-in person
  only. ``503`` (with ``reason``) when no vision model is set (``vision_not_configured``), plate photos
  are off (``plate_disabled``, the default), or the provider is a Hermes agent and
  ``ai.vision_allow_agent`` is off (``agent_not_allowed``); a Hermes provider is also tool-checked
  before **every** photo (§9 A1, B10).
* The body is the raw JPEG (``Content-Type: image/jpeg``; no multipart, so nothing is spooled to
  ``/tmp``): ``Content-Length`` over ``MAX_IMAGE_BYTES`` → 413 before reading, and the streamed bytes
  are counted too (``app/security.py`` gives ``/api/vision`` that limit instead of ``MAX_BODY_BYTES``).
  :func:`app.imagecheck.check_jpeg` then refuses anything but a plain JPEG (415/422) and removes
  metadata; only the rewritten bytes are sent, base64 in a ``data:`` URL. Photos are never written to
  disk, stored or logged (the AI activity log keeps their SHA-256, size and dimensions).
* **Nothing is read before the cheap refusals.** The order is: switches and vision model (503) →
  content type and declared size (415/413) → the person's consent for **photos** to that provider
  (409) → the person's AI slot and a server slot (429 ``busy_person``/``busy_server``) → only then
  the body, into one buffer, within ``PHOTO_READ_TIMEOUT_S`` (408). So the photos held in memory at
  any moment are bounded by ``ai.max_concurrency``, not by the number of open connections (a 512 MiB
  container must survive one person sending 64 photos at once). The slot is held through the call;
  the Hermes tool check runs inside it (:func:`app.ai.routes.run_call`).
* Photos count against ``ai.shared_daily_limit``; ``?dry_run=true`` shows the request without the
  photo's bytes (no consent needed to look, but it takes the slot like a real call).
* Upstream failures answer **502** ``{"detail", "reason"}`` (there is no rule result to fall back to).
  The label answer is a Quick-add **draft** (never saved); the plate answer is a checklist of matches
  from the person's own food search with a fixed warning banner.
"""
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from .ai import features as F
from .ai.routes import _resolve, ai_slot, ai_state, check_consent, require_ai_enabled, run_call, unavailable
from .auth.deps import CurrentUser, current_user
from .auth.errors import ApiProblem
from .auth.models import User
from .db import get_db
from .imagecheck import CheckedImage, ImageRejected, check_jpeg
from .security import register_body_limit

router = APIRouter(prefix="/api/vision", tags=["vision"], dependencies=[Depends(current_user), Depends(require_ai_enabled)])
register_body_limit("/api/vision", "max_image_bytes")

JPEG_TYPES = frozenset({"image/jpeg"})
PHOTO_READ_TIMEOUT_S = 60.0  # a 4 MiB photo at ~70 KB/s; a slower upload must not hold an AI slot for longer


def _too_large(limit: int) -> ApiProblem:
    return ApiProblem(413, f"The photo is larger than {limit // 1024} KiB.", reason="too_large")


def photo_headers(request: Request) -> tuple[int, int | None]:
    """Check the upload's headers without reading it: 415 unless ``image/jpeg``, 413 when the declared
    ``Content-Length`` is over ``MAX_IMAGE_BYTES``. Returns ``(limit, declared length or None)``."""
    limit = int(request.app.state.settings.max_image_bytes)
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if ctype not in JPEG_TYPES:
        raise ApiProblem(415, "Send the photo as a JPEG (Content-Type: image/jpeg).", reason="not_jpeg")
    declared = request.headers.get("content-length")
    length = int(declared) if declared is not None and declared.isdigit() else None
    if length is not None and length > limit:
        raise _too_large(limit)
    return limit, length


async def read_photo(request: Request) -> CheckedImage:
    """The checked, rewritten JPEG from the raw request body (408 / 413 / 415 / 422 otherwise).

    The body goes into one buffer (sized from ``Content-Length`` when it is declared), is checked in
    place and dropped as soon as the rewritten copy exists; no list of chunks, no joined copy."""
    limit, length = photo_headers(request)
    buf = bytearray(length) if length is not None else bytearray()
    used = 0
    try:
        async with asyncio.timeout(PHOTO_READ_TIMEOUT_S):
            async for chunk in request.stream():
                end = used + len(chunk)
                if end > limit:
                    raise _too_large(limit)
                if end <= len(buf):
                    buf[used:end] = chunk
                else:  # more than declared (no Content-Length, or a chunked body)
                    del buf[used:]
                    buf += chunk
                used = end
    except TimeoutError:
        raise ApiProblem(408, f"The photo took longer than {int(PHOTO_READ_TIMEOUT_S)} seconds to arrive. Try again on a "
                         "faster connection.", reason="upload_timeout") from None
    if used < len(buf):
        del buf[used:]
    try:
        return check_jpeg(buf, max_bytes=limit)
    except ImageRejected as exc:
        raise ApiProblem(exc.status, str(exc), reason=exc.reason) from None
    finally:
        del buf


def _vision_config(request: Request, conn: sqlite3.Connection, user: User, *, plate: bool):  # noqa: ANN202 - ProviderConfig
    state = ai_state(request)
    if plate and not state.store.get(conn, "ai.vision_plate_enabled"):
        raise ApiProblem(503, "Plate photos are switched off on this server.", reason="plate_disabled")
    resolved = _resolve(request, conn, user)
    if not resolved.ok:
        raise unavailable(resolved.reason or "not_configured")
    cfg = resolved.cfg
    assert cfg is not None
    if not cfg.vision_model:
        raise ApiProblem(503, "Photo features need a vision model; your admin has not set one.", reason="vision_not_configured")
    if not cfg.preset_def.photos_by_default and not state.store.get(conn, "ai.vision_allow_agent"):
        raise ApiProblem(503, "Photos are not sent to an agent provider on this server (AI_VISION_ALLOW_AGENT).", reason="agent_not_allowed")
    return cfg


def _upstream_error(result: dict[str, Any]) -> None:
    if result.get("status") == "error":
        raise ApiProblem(502, str(result.get("message") or "The AI request failed."), reason=result.get("reason"),
                         audit_id=result.get("audit_id"))


async def _before_reading(request: Request, conn: sqlite3.Connection, user: User, *, plate: bool, dry_run: bool):  # noqa: ANN202
    """Every refusal that needs no photo bytes: switches and vision model, headers, photo consent."""
    cfg = await run_in_threadpool(_vision_config, request, conn, user, plate=plate)
    photo_headers(request)
    if not dry_run:
        await run_in_threadpool(check_consent, conn, user, cfg, "photos")
    return cfg


@router.post("/label")
async def read_label(request: Request, user: CurrentUser, background: BackgroundTasks, dry_run: bool = Query(False),
                     conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Read a nutrition label: printed values only, a Quick-add draft the person checks (never saved)."""
    cfg = await _before_reading(request, conn, user, plate=False, dry_run=dry_run)
    async with ai_slot(request, conn, user.id):
        prep = F.prepare_read_label(cfg, await read_photo(request))
        if dry_run:
            return prep.dry_run(request.app.version)
        result = await run_call(request, conn, user, prep, background, slot_held=True)
    _upstream_error(result)
    return result


@router.post("/plate")
async def plate(request: Request, user: CurrentUser, background: BackgroundTasks, dry_run: bool = Query(False),
                conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """What is on this plate: names and a rough weight, matched to the person's own foods (off by default)."""
    cfg = await _before_reading(request, conn, user, plate=True, dry_run=dry_run)
    async with ai_slot(request, conn, user.id):
        prep = F.prepare_plate(cfg, await read_photo(request), search=F.search_function(conn, user.id))
        if dry_run:
            return prep.dry_run(request.app.version)
        result = await run_call(request, conn, user, prep, background, slot_held=True)
    _upstream_error(result)
    return result
