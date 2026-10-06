"""Chat Completions client: request body per preset, parsing, retries and repair, concurrency, probes
(note 04 R4 "Test connection", R6; §9 A1 for the Hermes tool check). ``httpx2`` only, no SDK.

* :func:`build_body` is the **one** producer of a request body: the dry run (R9) shows exactly what it
  returns, and :meth:`ChatClient.complete_json` sends exactly that.
* :meth:`ChatClient.complete_json` sends one call and allows **at most one extra request**: after a 429
  (``Retry-After`` honoured up to 10 s), after a 5xx or connection failure (after 1 s), or a repair turn
  when the answer was not valid JSON for the schema. 401, 403 and 404 are never retried. A refusal, a
  truncated answer (``finish_reason: "length"``) and reasoning text (never read) end the call.
* :class:`ConcurrencyGate`: at most ``ai.max_concurrency`` calls in flight on the server and one per
  person; extra calls are refused at once (the route answers 429 with ``Retry-After``).
* :func:`probe` is "Test connection": models list, structured-output mode, vision, and for ``hermes``
  the tool check of :func:`hermes_tools_check` (refuse when any **enabled** toolset lists tools, when
  the answer does not parse, or when the call fails).

Nothing here logs prompts, responses or keys (R6 "Logging").
"""
from __future__ import annotations

import base64
import json
import logging
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Mapping, Sequence

import anyio

from .netpolicy import BaseUrl, NetPolicy, Scope
from .presets import Preset, StructuredMode, get as get_preset
from .transport import AiTransportError, HttpResult, TransportFactory, send_json

log = logging.getLogger("kidney_health.ai")

APP_USER_AGENT = "kidney-health/{version}"
MAX_JSON_SCAN = 32 * 1024  # V1: the first balanced object within 32 KiB
RETRY_AFTER_MAX_S = 10.0
RETRY_5XX_DELAY_S = 1.0
REPAIR_TEXT = "Your previous reply was not valid: {summary}. Reply again with only the JSON object."
NEVER_RETRY = frozenset({"http_401", "http_403", "http_404", "blocked_address", "dns_failed", "invalid_url"})
RETRYABLE = frozenset({"http_429", "http_5xx", "connect_failed"})
HERMES_CHECK_TTL_S = 300.0  # §9 A1: re-check the tools at most 5 minutes before a call
HERMES_TOOLS_REASON = (
    "Hermes has tools enabled for its API server; create a tool-less profile (docs/ai.md, \"Hermes Agent\")."
)
HERMES_CHECK_FAILED = "The Hermes tool check failed, so the provider is off until a check passes (docs/ai.md)."


@dataclass(frozen=True)
class ProviderConfig:
    """Everything one call needs (built by :mod:`app.ai.config` from a provider row or the env)."""

    id: int
    scope: Scope
    preset: str
    label: str
    base: BaseUrl
    model: str
    api_key: str | None = field(default=None, repr=False)
    vision_model: str | None = None
    timeout_s: float = 60.0
    vision_timeout_s: float = 120.0
    max_tokens: int = 1500
    structured: StructuredMode = "prompt"
    reasoning_effort: str | None = None
    temperature: float | None = None
    extra_body: Mapping[str, Any] = field(default_factory=dict)
    context_tokens: int = 8192
    max_response_bytes: int = 262_144
    key_scope: Literal["own", "shared"] = "shared"
    safety_identifier: str | None = field(default=None, repr=False)

    @property
    def preset_def(self) -> Preset:
        return get_preset(self.preset)

    @property
    def host(self) -> str:
        """The destination host as consent and the audit log name it."""
        return self.base.display_host


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


def response_format(mode: StructuredMode, schema: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    if mode == "json_schema":
        return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
    if mode == "json_object":
        return {"type": "json_object"}
    return None


def headers_for(cfg: ProviderConfig, app_version: str) -> dict[str, str]:
    """Request headers: the key (or a preset's placeholder), JSON, the app's User-Agent. Nothing about the person."""
    headers = {"User-Agent": APP_USER_AGENT.format(version=app_version)}
    key = cfg.api_key or cfg.preset_def.placeholder_key
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def shown_headers(cfg: ProviderConfig, app_version: str) -> dict[str, str]:
    """The headers for the dry run: the key is never shown, only whether one is sent (R9 step 4)."""
    out = headers_for(cfg, app_version)
    if "Authorization" in out:
        out["Authorization"] = "Bearer [your key, not shown]" if cfg.api_key else out["Authorization"]
    out["Content-Type"] = "application/json"
    out["Accept"] = "application/json"
    out["Accept-Encoding"] = "identity"
    return out


def build_body(
    cfg: ProviderConfig,
    *,
    system: str,
    user_text: str,
    images: Sequence[str] = (),
    schema: Mapping[str, Any],
    schema_name: str,
    mode: StructuredMode,
    vision: bool = False,
) -> dict[str, Any]:
    """The Chat Completions body (R6). ``images`` are ``data:image/...;base64,`` URLs (never http URLs)."""
    preset = cfg.preset_def
    if images:
        content: Any = [{"type": "text", "text": user_text}]
        content += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    else:
        content = user_text
    body: dict[str, Any] = {
        "model": cfg.vision_model if vision and cfg.vision_model else cfg.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "stream": False,
        preset.token_field: int(cfg.max_tokens),
    }
    fmt = response_format(mode, schema, schema_name)
    if fmt is not None:
        body["response_format"] = fmt
    if cfg.reasoning_effort:
        body["reasoning_effort"] = cfg.reasoning_effort
    temperature = 0.0 if vision and preset.temperature is not None else cfg.temperature
    if temperature is not None:
        body["temperature"] = temperature
    for key, value in cfg.extra_body.items():
        body[key] = json.loads(json.dumps(value))  # a deep copy: presets are shared
    if cfg.safety_identifier and preset.name == "openai" and cfg.key_scope == "shared":
        body["safety_identifier"] = cfg.safety_identifier
    return body


def repair_body(first: Mapping[str, Any], reply: str, summary: str) -> dict[str, Any]:
    """The repair turn: the first body plus the reply and one correction request."""
    body = json.loads(json.dumps(first))
    body["messages"] = [*body["messages"], {"role": "assistant", "content": reply[:4000]},
                        {"role": "user", "content": REPAIR_TEXT.format(summary=summary[:300])}]
    return body


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


@dataclass
class Reply:
    """``choices[0].message`` reduced to what the app reads."""

    content: str | None
    refusal: str | None
    finish_reason: str | None
    usage: dict[str, int]


def parse_reply(data: Any) -> Reply:
    """``content`` (a string or the text parts joined), ``refusal``, ``finish_reason`` and ``usage``.
    ``reasoning_content`` / ``reasoning`` are ignored: never shown, never stored (R6)."""
    if not isinstance(data, Mapping):
        raise AiTransportError("invalid_response", "the answer is not a JSON object")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise AiTransportError("invalid_response", "the answer has no choices")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise AiTransportError("invalid_response", "the answer has no message")
    raw = message.get("content")
    if isinstance(raw, list):
        content: str | None = "".join(
            str(part.get("text", "")) for part in raw if isinstance(part, Mapping) and part.get("type") in ("text", "output_text")
        )
    elif isinstance(raw, str):
        content = raw
    else:
        content = None
    refusal = message.get("refusal")
    usage_raw = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}
    usage = {}
    for key in ("prompt_tokens", "completion_tokens"):
        value = usage_raw.get(key) if isinstance(usage_raw, Mapping) else None
        usage[key] = int(value) if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**9 else 0
    finish = choice.get("finish_reason")
    return Reply(
        content=content,
        refusal=str(refusal)[:500] if isinstance(refusal, str) and refusal.strip() else None,
        finish_reason=str(finish) if isinstance(finish, str) else None,
        usage=usage,
    )


class JsonNotFound(ValueError):
    """V1: no JSON object could be taken from the reply."""


def extract_json(text: str | None) -> Any:
    """V1: strip a BOM and code fences, then parse the first balanced top-level ``{…}`` in 32 KiB."""
    if text is None or not text.strip():
        raise JsonNotFound("the reply was empty")
    s = text.lstrip("﻿").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s[:MAX_JSON_SCAN]
    start = s.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start : i + 1])
                    except ValueError:
                        break
        start = s.find("{", start + 1)
    raise JsonNotFound("no complete JSON object in the reply")


# --------------------------------------------------------------------------- #
# Calls
# --------------------------------------------------------------------------- #

Validator = Callable[[Any], Any]  # returns the parsed object or raises ValueError (a Pydantic error is one)


@dataclass
class CallResult:
    status: Literal["ok", "refused", "invalid", "error"]
    error: str | None = None  # a netpolicy category, or "no_json", "schema", "truncated", "empty"
    parsed: Any = None
    text: str | None = None  # the last reply's content (for the person's own AI activity page)
    refusal: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    latency_ms: int = 0
    http_status: int | None = None
    bodies: list[dict[str, Any]] = field(default_factory=list)  # every body sent, in order
    repaired: bool = False
    retried: bool = False


def summarize_error(exc: Exception) -> str:
    """A short reason for a repair turn, never the offending input (Pydantic's ``errors(include_input=False)``)."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            items = errors(include_input=False, include_url=False)
        except TypeError:
            items = errors()
        parts = []
        for item in items[:5]:
            loc = ".".join(str(p) for p in item.get("loc", ()))
            parts.append(f"{loc}: {item.get('msg', 'invalid')}" if loc else str(item.get("msg", "invalid")))
        return "; ".join(parts) or "the JSON did not match the schema"
    return str(exc)[:200] or "the JSON did not match the schema"


class ChatClient:
    """Sends Chat Completions requests through the pinned transport."""

    def __init__(
        self,
        policy: NetPolicy,
        *,
        app_version: str,
        transport_factory: TransportFactory | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.policy = policy
        self.app_version = app_version
        self.transport_factory = transport_factory
        self._sleep = sleep or anyio.sleep

    async def request(self, cfg: ProviderConfig, method: str, path: str, body: Any | None = None, *,
                      timeout_s: float | None = None, error_snippet: Callable[[bytes], None] | None = None) -> HttpResult:
        return await send_json(
            cfg.base, cfg.scope, self.policy, method=method, path=path, headers=headers_for(cfg, self.app_version),
            body=body, read_timeout_s=timeout_s or cfg.timeout_s, max_bytes=cfg.max_response_bytes,
            transport_factory=self.transport_factory, error_snippet=error_snippet,
        )

    async def complete_json(self, cfg: ProviderConfig, body: dict[str, Any], validate: Validator, *, vision: bool = False) -> CallResult:
        """Send ``body`` (from :func:`build_body`) and validate the reply; at most one extra request."""
        result = CallResult(status="error")
        timeout = cfg.vision_timeout_s if vision else cfg.timeout_s
        current = body
        extra_used = False
        started = time.monotonic()
        while True:
            result.bodies.append(current)
            try:
                http = await self.request(cfg, "POST", "chat/completions", current, timeout_s=timeout)
            except AiTransportError as exc:
                result.http_status = exc.status
                if not extra_used and exc.category in RETRYABLE:
                    extra_used = True
                    result.retried = True
                    delay = RETRY_5XX_DELAY_S
                    if exc.category == "http_429":
                        delay = min(RETRY_AFTER_MAX_S, exc.retry_after if exc.retry_after is not None else RETRY_5XX_DELAY_S)
                    await self._sleep(delay)
                    continue
                result.status, result.error = "error", exc.category
                break
            result.http_status = http.status
            try:
                reply = parse_reply(http.data)
            except AiTransportError as exc:
                result.status, result.error = "invalid", exc.category
                break
            for key, value in reply.usage.items():
                result.usage[key] = result.usage.get(key, 0) + value
            result.text, result.finish_reason = reply.content, reply.finish_reason
            if reply.refusal is not None:
                result.status, result.refusal = "refused", reply.refusal
                break
            if reply.finish_reason == "length":
                result.status, result.error = "invalid", "truncated"
                break
            try:
                data = extract_json(reply.content)
                result.parsed = validate(data)
            except JsonNotFound as exc:
                problem, summary = ("empty" if not (reply.content or "").strip() else "no_json"), str(exc)
            except ValueError as exc:  # pydantic.ValidationError is a ValueError
                problem, summary = "schema", summarize_error(exc)
            else:
                result.status = "ok"
                break
            if extra_used:
                result.status, result.error = "invalid", problem
                break
            extra_used = True
            result.repaired = True
            current = repair_body(body, reply.content or "", summary)
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result


# --------------------------------------------------------------------------- #
# Concurrency (R6): AI_MAX_CONCURRENCY in flight, one per person
# --------------------------------------------------------------------------- #


class Busy(Exception):
    """No slot free; ``scope`` is ``server`` or ``person``."""

    def __init__(self, scope: str, retry_after: int = 5):
        super().__init__(scope)
        self.scope = scope
        self.retry_after = retry_after


class ConcurrencyGate:
    """Non-blocking slots: extra calls are refused at once instead of queueing behind a slow model."""

    def __init__(self, limit: int = 2) -> None:
        self.limit = max(1, int(limit))
        self._lock = threading.Lock()
        self._active = 0
        self._people: set[int] = set()

    def enter(self, user_id: int, limit: int | None = None) -> None:
        with self._lock:
            if limit is not None:
                self.limit = max(1, int(limit))
            if user_id in self._people:
                raise Busy("person")
            if self._active >= self.limit:
                raise Busy("server")
            self._active += 1
            self._people.add(user_id)

    def leave(self, user_id: int) -> None:
        with self._lock:
            if user_id in self._people:
                self._people.discard(user_id)
                self._active = max(0, self._active - 1)

    @property
    def active(self) -> int:
        with self._lock:
            return self._active


# --------------------------------------------------------------------------- #
# Test connection (R4 probe) and the Hermes tool check (§9 A1)
# --------------------------------------------------------------------------- #

PROBE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"],
                "properties": {"ok": {"type": "string", "enum": ["yes"]}}}
VISION_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["color"],
                 "properties": {"color": {"type": "string", "enum": ["red", "green", "blue", "other"]}}}
PROBE_SYSTEM = "You are a connection test. Reply with exactly one JSON object and nothing else."
PROBE_TEXT = 'Reply with the JSON object {"ok": "yes"}.'
VISION_TEXT = 'What colour is this square? Reply with the JSON object {"color": "<red|green|blue|other>"}.'


def red_square_png(size: int = 32) -> bytes:
    """A ``size``×``size`` red PNG for the vision probe (made here, so nothing is downloaded)."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _schema_text(schema: Mapping[str, Any]) -> str:
    return "RESPONSE SCHEMA: " + json.dumps(schema, sort_keys=True, separators=(",", ":"))


def _ok_validator(expected: Mapping[str, Any]) -> Validator:
    def check(data: Any) -> Any:
        if not isinstance(data, Mapping) or {k: data.get(k) for k in expected} != dict(expected):
            raise ValueError("unexpected answer")
        return dict(data)
    return check


@dataclass
class ToolCheck:
    ok: bool
    reason: str | None
    toolsets: list[dict[str, Any]] = field(default_factory=list)


def judge_toolsets(data: Any) -> ToolCheck:
    """§9 A1: ``GET {base}/toolsets`` must be a JSON list of ``{name, enabled, tools}`` entries and no
    **enabled** entry may list tools. A disabled toolset that still lists its tools is fine."""
    items = data.get("data") if isinstance(data, Mapping) and isinstance(data.get("data"), list) else data
    if not isinstance(items, list):
        return ToolCheck(False, HERMES_CHECK_FAILED)
    summary: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("enabled"), bool):
            return ToolCheck(False, HERMES_CHECK_FAILED)
        tools = entry.get("tools", [])
        if not isinstance(tools, list):
            return ToolCheck(False, HERMES_CHECK_FAILED)
        name = str(entry.get("name", ""))[:60]
        summary.append({"name": name, "enabled": entry["enabled"], "tools": len(tools)})
        if entry["enabled"] and tools:
            return ToolCheck(False, HERMES_TOOLS_REASON, summary)
    return ToolCheck(True, None, summary)


async def hermes_tools_check(client: ChatClient, cfg: ProviderConfig) -> ToolCheck:
    """Ask Hermes which toolsets its API server resolves; any failure counts as "tools may be on"."""
    try:
        http = await client.request(cfg, "GET", "toolsets", timeout_s=min(cfg.timeout_s, 15.0))
    except AiTransportError as exc:
        return ToolCheck(False, f"{HERMES_CHECK_FAILED} ({exc.category})")
    return judge_toolsets(http.data)


async def probe(client: ChatClient, cfg: ProviderConfig, *, error_snippet: Callable[[bytes], None] | None = None) -> dict[str, Any]:
    """Test connection (R4 steps 1–4). Returns the ``probe_json`` record:

    ``{"at", "ok", "models": {"listed", "model_listed"}, "structured", "vision", "tools", "capabilities",
    "warnings": [...], "errors": [...], "requests"}`` (``requests``: how many calls it made).
    """
    out: dict[str, Any] = {"at": time.time(), "ok": False, "models": None, "structured": None, "vision": None,
                           "tools": None, "capabilities": None, "warnings": [], "errors": [], "requests": 0}
    preset = cfg.preset_def

    if preset.tool_check:  # before anything is sent to Hermes
        out["requests"] += 1
        check = await hermes_tools_check(client, cfg)
        out["tools"] = {"ok": check.ok, "reason": check.reason, "toolsets": check.toolsets}
        if not check.ok:
            out["errors"].append(check.reason)
            return out
        out["requests"] += 1
        try:
            caps = await client.request(cfg, "GET", "capabilities", timeout_s=15.0)
            out["capabilities"] = caps.data if isinstance(caps.data, (dict, list)) else None
        except AiTransportError as exc:
            out["warnings"].append(f"capabilities: {exc.category}")

    out["requests"] += 1
    try:
        models = await client.request(cfg, "GET", "models", timeout_s=15.0, error_snippet=error_snippet)
        ids = []
        listing = models.data.get("data") if isinstance(models.data, Mapping) else None
        if isinstance(listing, list):
            ids = [str(m.get("id")) for m in listing if isinstance(m, Mapping) and m.get("id")]
        listed = cfg.model in ids
        out["models"] = {"listed": len(ids), "model_listed": listed}
        if ids and not listed:
            out["warnings"].append(f"the model {cfg.model!r} is not in the server's model list")
        if cfg.vision_model and ids and cfg.vision_model not in ids:
            out["warnings"].append(f"the vision model {cfg.vision_model!r} is not in the server's model list")
    except AiTransportError as exc:
        if exc.category == "http_404":
            out["models"] = {"listed": None, "model_listed": None}
        elif exc.category in ("http_401", "http_403"):
            out["errors"].append(f"the server refused the key ({exc.category})")
            return out
        else:
            out["errors"].append(f"models: {exc.category}")
            return out

    for mode in ("json_schema", "json_object", "prompt"):
        user = PROBE_TEXT if mode == "json_schema" else f"{PROBE_TEXT}\n{_schema_text(PROBE_SCHEMA)}"
        body = build_body(cfg, system=PROBE_SYSTEM, user_text=user, schema=PROBE_SCHEMA, schema_name="probe", mode=mode)  # type: ignore[arg-type]
        body[cfg.preset_def.token_field] = 50
        result = await client.complete_json(cfg, body, _ok_validator({"ok": "yes"}))
        out["requests"] += len(result.bodies)
        if result.status == "ok":
            out["structured"] = mode
            break
        if result.error in ("http_401", "http_403"):
            out["errors"].append(f"the server refused the key ({result.error})")
            return out
        if result.error not in ("http_4xx", "schema", "no_json", "empty", "invalid_response"):
            out["errors"].append(f"chat: {result.error or result.status}")
            return out
    if out["structured"] is None:
        out["errors"].append("the model did not return valid JSON in any mode")
        return out

    if cfg.vision_model:
        image = "data:image/png;base64," + base64.b64encode(red_square_png()).decode("ascii")
        mode = out["structured"]
        user = VISION_TEXT if mode == "json_schema" else f"{VISION_TEXT}\n{_schema_text(VISION_SCHEMA)}"
        body = build_body(cfg, system=PROBE_SYSTEM, user_text=user, images=[image], schema=VISION_SCHEMA,
                          schema_name="vision_probe", mode=mode, vision=True)
        body[cfg.preset_def.token_field] = 50
        result = await client.complete_json(cfg, body, _ok_validator({"color": "red"}), vision=True)
        out["requests"] += len(result.bodies)
        out["vision"] = {"ok": result.status == "ok", "error": None if result.status == "ok" else (result.error or result.status)}
        if result.status != "ok":
            out["warnings"].append("the vision model did not recognise a red square; photo features may not work")
    out["ok"] = not out["errors"]
    return out
