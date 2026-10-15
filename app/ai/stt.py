"""Speech to text for the Ask screen's microphone (assistant step 2, part B; docs/dev/plans/assistant-step2.md).

The app never runs a speech model and never uses the browser's speech recognition (Chrome sends that audio to
Google, Safari to Apple). One recording goes from the page to ``POST /api/ai/transcribe``, from there to **one
OpenAI-compatible transcription server the admin chose** (``STT_BASE_URL``: a local Speaches or whisper.cpp
container, or a cloud service), and the text comes back to the person's input box to read and edit. Least trust:

* **Off by default, off the network until switched on.** Configuration is the environment only (``STT_BASE_URL``,
  ``STT_MODEL``, ``STT_API_KEY[_FILE]``, ``STT_TIMEOUT_S``, ``STT_DAILY_LIMIT``, ``STT_MAX_AUDIO_BYTES``) plus the
  admin switch ``ai.voice_enabled``. The key is write-only: it is never returned by any API.
* **The same address rules as an AI provider.** The call goes through :func:`app.ai.transport.send_json` (resolve,
  check every address, pin, no redirects, answer size cap), scope ``shared``: a LAN host such as ``stt:8000`` works
  only when ``AI_PRIVATE_HOSTS`` lists it, exactly like an Ollama host. There is no second outbound path.
* **Nothing is kept.** The audio exists in memory while it is checked and forwarded; it is never written to disk or
  to the database and never logged, and neither is the transcript. The activity row holds the host, the model, a
  length bucket and the outcome, nothing else.
* **Consent first.** The purpose ``voice`` has its own sheet ("Your recording is sent to <host> ... deleted").
  The consent row keeps the transcription *host* in ``host`` and, for its key, the id of the AI provider that
  serves the person (the Ask screen needs one); a changed host or provider asks again.

This module is pure (no FastAPI): :mod:`app.ai.voice` has the route.
"""
from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ..config import ConfigError, Settings
from ..db import utcnow
from ..security import register_secret
from .client import APP_USER_AGENT
from .netpolicy import BaseUrl, NetPolicy, PolicyError, check_url, may_use_http, parse_base_url
from .prompts import clean
from .transport import AiTransportError, TransportFactory, ca_store_problem, send_json

log = logging.getLogger("kidney_health.ai")

PURPOSE = "voice"
POLICY_VERSION = "2026-10-15.1"  # the wording of the voice consent below; a change asks everyone again
MAX_SECONDS = 60
MAX_TRANSCRIPT_CHARS = 2000
MIN_AUDIO_BYTES = 64
USAGE_PROVIDER_ID = 0  # ai_usage rows of the transcription server (no ai_providers row has id 0)
LABEL = "Speech to text"
AUDIT_PROMPT_VERSION = "stt-1"
DEFAULT_DAILY_LIMIT = 100

# The four clip types the page can produce (MediaRecorder: webm/opus in Chrome and Android, ogg/opus in Firefox,
# mp4/aac in Safari; wav for tools). The content type and the first bytes must agree.
KIND_BY_TYPE = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/wav": "wav"}
FILENAME = {"webm": "recording.webm", "ogg": "recording.ogg", "mp4": "recording.m4a", "wav": "recording.wav"}
SENT_TYPE = {"webm": "audio/webm", "ogg": "audio/ogg", "mp4": "audio/mp4", "wav": "audio/wav"}

ERROR_TEXT = {
    "dns_failed": "The transcription server could not be reached.",
    "connect_failed": "The transcription server could not be reached.",
    "timeout": "The transcription server took too long to answer.",
    "blocked_address": "This transcription server's address is not allowed on this server (docs/ai.md, \"Addresses\").",
    "invalid_url": "This transcription server's address is not valid.",
    "http_401": "The transcription server refused the key.",
    "http_403": "The transcription server refused the request (key or model not allowed).",
    "http_404": "The transcription server does not know this model or address.",
    "http_429": "The transcription server is busy. Try again in a moment.",
    "http_4xx": "The transcription server refused the recording.",
    "http_5xx": "The transcription server had an error.",
    "invalid_response": "The transcription server's answer could not be used.",
}


class AudioRejected(Exception):
    """A clip the app will not forward: ``status`` (400, 413 or 415), a short ``reason`` code and a plain message."""

    def __init__(self, status: int, reason: str, message: str):
        super().__init__(message)
        self.status = status
        self.reason = reason


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SttConfig:
    """The transcription server, from the environment (never from a request)."""

    base: BaseUrl
    model: str
    api_key: str | None = field(repr=False)
    timeout_s: float
    max_response_bytes: int
    max_audio_bytes: int
    daily_limit: int  # 0 = unlimited

    @property
    def host(self) -> str:
        """The destination as the consent sheet and the activity list name it."""
        return self.base.display_host


def load(settings: Settings) -> SttConfig | None:
    """The configuration, or ``None`` when ``STT_BASE_URL`` is not set. ``ConfigError`` if it is set and wrong."""
    env = settings.ai
    if not env.stt_base_url:
        return None
    try:
        base = parse_base_url(env.stt_base_url)
    except PolicyError as exc:
        raise ConfigError(f"STT_BASE_URL: {exc}") from None
    if not env.stt_model:
        raise ConfigError("STT_BASE_URL needs STT_MODEL (the model name the transcription server knows, such as whisper-1).")
    return SttConfig(base=base, model=env.stt_model, api_key=env.stt_api_key, timeout_s=float(env.stt_timeout_s),
                     max_response_bytes=min(int(env.max_response_bytes), 1_048_576), max_audio_bytes=int(settings.max_audio_bytes),
                     daily_limit=int(env.stt_daily_limit))


def check_env(settings: Settings, policy: NetPolicy) -> list[str]:
    """Start-up check: returns warnings and raises :class:`ConfigError` for a wrong ``STT_*`` value. Contacts nothing."""
    env = settings.ai
    warnings: list[str] = []
    cfg = load(settings)
    if cfg is None:
        stray = [n for n, v in (("STT_MODEL", env.stt_model), ("STT_API_KEY", env.stt_api_key)) if v]
        if stray:
            warnings.append(f"{', '.join(stray)} {'is' if len(stray) == 1 else 'are'} set but STT_BASE_URL is not, so voice input has no "
                            "transcription server.")
        return warnings
    register_secret(cfg.api_key)
    if cfg.base.scheme == "https":
        problem = ca_store_problem()
        if problem:
            raise ConfigError(f"STT_BASE_URL uses https, but {problem}.")
    try:
        check_url(cfg.base, "shared", policy)
    except PolicyError as exc:
        warnings.append(f"STT_BASE_URL {cfg.base.host_port} will be refused: {exc}. Voice input will not work until this is fixed.")
    return warnings


def is_local(cfg: SttConfig, policy: NetPolicy) -> bool:
    """Whether the server is one the operator listed as private (``AI_PRIVATE_HOSTS``), so on their own network."""
    return may_use_http(cfg.base, policy)


# --------------------------------------------------------------------------- #
# The clip: type, first bytes, length
# --------------------------------------------------------------------------- #


def content_type_kind(header: str | None) -> str:
    """``webm``, ``ogg``, ``mp4`` or ``wav`` from a ``Content-Type`` header (parameters such as ``;codecs=opus`` are
    fine), else :class:`AudioRejected` 415."""
    base = (header or "").split(";", 1)[0].strip().lower()
    kind = KIND_BY_TYPE.get(base)
    if kind is None:
        raise AudioRejected(415, "not_audio", "Send one recording as audio/webm, audio/ogg, audio/mp4 or audio/wav.")
    return kind


def sniff(data: bytes | bytearray) -> str | None:
    """The container named by the first bytes: ``webm`` (EBML), ``ogg`` (``OggS``), ``wav`` (``RIFF``..``WAVE``),
    ``mp4`` (``ftyp`` at 4), else ``None``."""
    head = bytes(data[:12])
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "mp4"
    return None


def wav_seconds(data: bytes | bytearray) -> float | None:
    """The length of a WAV clip from its header (``None`` when it cannot be read)."""
    pos = 12
    byte_rate = None
    while pos + 8 <= len(data):
        chunk = bytes(data[pos:pos + 4])
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        if chunk == b"fmt " and size >= 16 and pos + 20 <= len(data):
            byte_rate = int.from_bytes(data[pos + 16:pos + 20], "little")
        elif chunk == b"data":
            if not byte_rate:
                return None
            available = len(data) - (pos + 8)
            used = available if size in (0, 0xFFFFFFFF) else min(size, available)
            return used / byte_rate
        pos += 8 + size + (size & 1)
    return None


def check_clip(kind: str, data: bytes | bytearray) -> float | None:
    """Refuse a clip whose first bytes are not the declared container (400), an empty one (400) or a WAV longer than
    :data:`MAX_SECONDS` (413). Returns the length in seconds when the header tells it (WAV), else ``None``.

    The 60-second limit of the other containers is the page's recording limit and the byte limit (a clip of the
    allowed size is about a minute of speech at the page's bitrate); the server cannot read it without decoding."""
    if len(data) < MIN_AUDIO_BYTES:
        raise AudioRejected(400, "empty", "The recording is empty.")
    found = sniff(data)
    if found != kind:
        raise AudioRejected(400, "not_audio", "The recording is not a valid audio file of the type it says.")
    if kind == "wav":
        seconds = wav_seconds(data)
        if seconds is not None and seconds > MAX_SECONDS + 1:
            raise AudioRejected(413, "too_long", f"The recording is longer than {MAX_SECONDS} seconds.")
        return seconds
    return None


def duration_bucket(seconds: float | None) -> str:
    """A coarse length for the activity row: the exact length is not needed and not kept."""
    if seconds is None:
        return "unknown"
    if seconds < 10:
        return "under 10 s"
    if seconds < 30:
        return "10 to 30 s"
    return "30 to 60 s"


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


def multipart(kind: str, data: bytes | bytearray, fields: Mapping[str, str]) -> tuple[bytes, str]:
    """``(body, content type)`` of the OpenAI transcription form: the text fields, then ``file``. The file name and
    type are the app's own (never the browser's)."""
    while True:
        boundary = "kh" + secrets.token_hex(16)
        marker = boundary.encode("ascii")
        if marker not in data:
            break
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{FILENAME[kind]}"\r\n'
                 f"Content-Type: {SENT_TYPE[kind]}\r\n\r\n".encode("ascii"))
    parts.append(bytes(data))
    parts.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def clean_transcript(value: Any) -> str:
    """The transcript as it may reach the input box: the chat's text policy (NFKC, control and format characters out,
    runs of spaces collapsed) and at most :data:`MAX_TRANSCRIPT_CHARS` characters."""
    return clean(value, MAX_TRANSCRIPT_CHARS) if isinstance(value, str) else ""


def request_headers(cfg: SttConfig, app_version: str) -> dict[str, str]:
    headers = {"User-Agent": APP_USER_AGENT.format(version=app_version)}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    return headers


async def transcribe(cfg: SttConfig, policy: NetPolicy, factory: TransportFactory | None, kind: str, data: bytes | bytearray,
                     *, app_version: str) -> tuple[str, int]:
    """Send the clip to ``{STT_BASE_URL}/audio/transcriptions`` and return ``(clean transcript, milliseconds)``.

    Raises :class:`AiTransportError` (a coarse category; no response body is ever put into the message)."""
    body, content_type = multipart(kind, data, {"model": cfg.model, "response_format": "json"})
    result = await send_json(
        cfg.base, "shared", policy, method="POST", path="audio/transcriptions", headers=request_headers(cfg, app_version),
        read_timeout_s=cfg.timeout_s, max_bytes=cfg.max_response_bytes, transport_factory=factory,
        content=body, content_type=content_type,
    )
    payload = result.data
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise AiTransportError("invalid_response", "the transcription answer has no text")
    return clean_transcript(payload["text"]), result.latency_ms


# --------------------------------------------------------------------------- #
# Consent (ai_consents, purpose 'voice')
# --------------------------------------------------------------------------- #


def policy_line(cfg: SttConfig, policy: NetPolicy) -> str:
    where = ("This server is on your own network." if is_local(cfg, policy)
             else "This is an online service; what it does with the recording while it works on it is governed by its own terms.")
    return f"Your recording is sent to {cfg.host} to turn it into text, then deleted. Nothing is kept. {where}"


def consent_request(cfg: SttConfig, policy: NetPolicy, ai_provider_id: int) -> dict[str, Any]:
    """What the consent sheet shows before the first recording is sent (the same shape as the AI sheets)."""
    return {"provider_id": int(ai_provider_id), "provider_label": LABEL, "host": cfg.host, "purpose": PURPOSE,
            "policy": policy_line(cfg, policy), "policy_version": POLICY_VERSION, "kind": "local" if is_local(cfg, policy) else "cloud"}


def consent(conn: sqlite3.Connection, user_id: int, ai_provider_id: int, cfg: SttConfig) -> dict[str, Any] | None:
    """The person's consent for this transcription host, or ``None`` (none given, another host, an older wording)."""
    row = conn.execute("SELECT * FROM ai_consents WHERE user_id = ? AND provider_id = ? AND purpose = ?",
                       (int(user_id), int(ai_provider_id), PURPOSE)).fetchone()
    if row is None or row["host"] != cfg.host or row["policy_version"] != POLICY_VERSION:
        return None
    return {"host": row["host"], "policy_version": row["policy_version"], "skip_preview": True, "at": row["created_at"]}


def give_consent(conn: sqlite3.Connection, user_id: int, ai_provider_id: int, cfg: SttConfig) -> dict[str, Any]:
    now = utcnow()
    conn.execute(
        """INSERT INTO ai_consents (user_id, provider_id, purpose, host, policy_version, skip_preview, created_at)
           VALUES (?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT (user_id, provider_id, purpose) DO UPDATE SET host = excluded.host,
             policy_version = excluded.policy_version, skip_preview = 1, created_at = excluded.created_at""",
        (int(user_id), int(ai_provider_id), PURPOSE, cfg.host, POLICY_VERSION, now),
    )
    return {"host": cfg.host, "policy_version": POLICY_VERSION, "skip_preview": True, "at": now}


# --------------------------------------------------------------------------- #
# Daily limit (ai_usage, provider 0) and the activity row
# --------------------------------------------------------------------------- #


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def used_today(conn: sqlite3.Connection, user_id: int, day: str | None = None) -> int:
    row = conn.execute("SELECT requests FROM ai_usage WHERE user_id = ? AND day = ? AND provider_id = ?",
                       (int(user_id), day or today(), USAGE_PROVIDER_ID)).fetchone()
    return int(row[0]) if row else 0


def remaining_today(conn: sqlite3.Connection, user_id: int, cfg: SttConfig) -> int | None:
    return None if cfg.daily_limit <= 0 else max(0, cfg.daily_limit - used_today(conn, user_id))


def take_quota(conn: sqlite3.Connection, user_id: int, cfg: SttConfig, *, day: str | None = None) -> bool:
    """Count one recording for ``user_id`` (no commit); ``False`` (nothing counted) at the daily limit. The rows use
    ``key_scope = 'own'`` and provider 0, so the shared AI calls of ``ai.shared_daily_limit`` never include them.
    Run inside ``BEGIN IMMEDIATE`` so two requests cannot both take the last one."""
    day = day or today()
    if cfg.daily_limit > 0 and used_today(conn, user_id, day) + 1 > cfg.daily_limit:
        return False
    conn.execute(
        """INSERT INTO ai_usage (user_id, day, provider_id, key_scope, requests) VALUES (?, ?, ?, 'own', 1)
           ON CONFLICT (user_id, day, provider_id) DO UPDATE SET requests = requests + 1""",
        (int(user_id), day, USAGE_PROVIDER_ID),
    )
    return True


def write_audit(conn: sqlite3.Connection, user_id: int, cfg: SttConfig, *, bucket: str, status: str, latency_ms: int) -> int:
    """One activity row, no content: the host, the model, a length bucket and the outcome (no commit)."""
    verdict = {"duration": bucket, "outcome": "transcribed" if status == "ok" else status}
    cur = conn.execute(
        """INSERT INTO ai_audit (user_id, created_at, feature, provider_id, model, destination_host, prompt_version,
             request_json, response_text, verdict_json, latency_ms, status) VALUES (?, ?, 'voice', NULL, ?, ?, ?, NULL, NULL, ?, ?, ?)""",
        (int(user_id), utcnow(), cfg.model, cfg.host, AUDIT_PROMPT_VERSION,
         json.dumps(verdict, separators=(",", ":")), int(latency_ms), status),
    )
    return int(cur.lastrowid)
