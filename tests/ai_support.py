"""Helpers for the AI tests: the response fixtures, a fake provider that records every request, and a
signed-in app with AI on. Nothing here reaches the network: the resolver is fake and every request
ends in an ``httpx2.MockTransport`` handler."""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import httpx2

from app.ai.client import ProviderConfig
from app.ai.netpolicy import NetPolicy, parse_base_url, parse_private_hosts
from app.ai.presets import get as get_preset
from app.ai.transport import PinnedTransport

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ai"
PUBLIC_IP = "162.159.140.245"
PRIVATE_POLICY = NetPolicy(private_hosts=parse_private_hosts("ollama:11434, host.containers.internal:8643, llama:8080"))


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def response_from(item: Mapping[str, Any]) -> httpx2.Response:
    """An ``httpx2.Response`` from a fixture item ``{"status", "headers", "body"}``."""
    headers = dict(item.get("headers") or {"Content-Type": "application/json"})
    body = item.get("body")
    content = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return httpx2.Response(int(item.get("status", 200)), headers=headers, content=content)


def chat(content: Any, *, finish: str = "stop", refusal: str | None = None, usage: tuple[int, int] = (1000, 100),
         extra_message: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A Chat Completions fixture item whose message content is ``content`` (dicts are JSON-encoded)."""
    text = content if isinstance(content, str) or content is None else json.dumps(content, separators=(",", ":"))
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if refusal is not None:
        message["refusal"] = refusal
    message.update(extra_message or {})
    return {"status": 200, "headers": {"Content-Type": "application/json"},
            "body": {"id": "chatcmpl-test", "object": "chat.completion", "model": "test-model",
                     "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                     "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}}}


class FakeProvider:
    """Answers queued fixture items in order (or ``route(request)`` when set) and records each request.

    ``calls`` counts chat requests; ``requests`` keeps every request (``GET /models``, toolsets, …)."""

    def __init__(self, answers: list[Any] | None = None, *, route: Callable[[httpx2.Request], Any] | None = None,
                 address: str = PUBLIC_IP) -> None:
        self.answers = list(answers or [])
        self.route = route
        self.address = address
        self.requests: list[httpx2.Request] = []
        self.resolved: list[str] = []

    @property
    def chat_requests(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path.endswith("/chat/completions")]

    @property
    def calls(self) -> int:
        return len(self.chat_requests)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.chat_requests]

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        item = self.route(request) if self.route is not None else None
        if item is None:
            if not self.answers:
                raise AssertionError(f"unexpected request {request.method} {request.url}")
            item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx2.Response):
            return item
        return response_from(item)

    def resolver(self, host: str, port: int) -> list[str]:
        self.resolved.append(host)
        return [self.address]

    def factory(self, base: Any, scope: Any, policy: Any) -> PinnedTransport:
        return PinnedTransport(base, scope, policy, resolver=self.resolver, inner=httpx2.MockTransport(self.handler))


def make_cfg(preset: str = "openai", *, base_url: str | None = None, scope: str = "shared", model: str = "test-model",
             api_key: str | None = "sk-test-0123456789abcdefghijkl", structured: str | None = None, **extra: Any) -> ProviderConfig:
    p = get_preset(preset)
    values: dict[str, Any] = dict(
        id=1, scope=scope, preset=preset, label=p.label, base=parse_base_url(base_url or p.base_url or "https://ai.example.com/v1"),
        model=model, api_key=api_key, timeout_s=p.timeout_s, max_tokens=1500,
        structured=structured or p.default_structured, reasoning_effort=p.reasoning_effort, temperature=p.temperature,
        extra_body=dict(p.extra_body), context_tokens=p.context_tokens, key_scope="own" if scope == "user" else "shared",
    )
    values.update(extra)
    return ProviderConfig(**values)


async def no_sleep(seconds: float) -> None:
    SLEEPS.append(seconds)


SLEEPS: list[float] = []


@contextmanager
def attach(app: Any, provider: FakeProvider) -> Iterator[FakeProvider]:
    """Point the app's AI client at ``provider`` (and make retries instant) for the duration."""
    state = app.state.ai
    old_factory, old_sleep = state.client.transport_factory, state.client._sleep
    state.client.transport_factory = provider.factory
    state.client._sleep = no_sleep
    try:
        yield provider
    finally:
        state.client.transport_factory, state.client._sleep = old_factory, old_sleep
