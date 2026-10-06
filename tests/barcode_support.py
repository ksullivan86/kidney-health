"""Helpers for the barcode tests: load the recorded fixtures and replay them without the network.

``tests/fixtures/off/*.json`` and ``tests/fixtures/usda/*.json`` were recorded by
``scripts/record_barcode_fixtures.py`` (see the READMEs next to them). :class:`Replay` is an
``httpx2.MockTransport`` that answers a request from the fixture whose recorded URL matches, records
every request it sees (the "transport spy") and answers 599 for anything it does not know, so a test
fails loudly instead of reaching the network.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import httpx2

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(service: str, name: str) -> dict[str, Any]:
    """A recorded exchange: ``{"request": {"url"}, "status", "content_type", "body"}``."""
    return json.loads((FIXTURES / service / f"{name}.json").read_text(encoding="utf-8"))


def product(name: str) -> dict[str, Any]:
    """The ``product`` object of an Open Food Facts fixture."""
    return load("off", name)["body"]["product"]


def response_for(doc: dict[str, Any]) -> httpx2.Response:
    body = doc.get("body")
    content = json.dumps(body).encode("utf-8") if body is not None else str(doc.get("text") or "").encode("utf-8")
    return httpx2.Response(doc["status"], headers={"Content-Type": doc.get("content_type") or "application/json"}, content=content)


def _key(url: str | httpx2.URL) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Host, path and the sorted query parameters (their order in the URL does not matter)."""
    from urllib.parse import parse_qsl

    u = httpx2.URL(str(url))
    query = u.query.decode() if isinstance(u.query, bytes) else str(u.query)
    return (u.host, u.path, tuple(sorted(parse_qsl(query, keep_blank_values=True))))


class Replay(httpx2.MockTransport):
    """Answers from recorded fixtures (then optional fallback handlers by URL prefix); remembers every request."""

    def __init__(self, *docs: dict[str, Any], handlers: dict[str, Callable[[httpx2.Request], httpx2.Response]] | None = None) -> None:
        self.requests: list[httpx2.Request] = []
        self._docs = {_key(doc["request"]["url"]): doc for doc in docs}
        self._handlers = handlers or {}
        super().__init__(self._handle)

    def add(self, doc: dict[str, Any]) -> None:
        self._docs[_key(doc["request"]["url"])] = doc

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        """A recorded exchange for this URL, else the first handler whose prefix matches, else 599."""
        self.requests.append(request)
        doc = self._docs.get(_key(request.url))
        if doc is not None:
            return response_for(doc)
        for prefix, handler in self._handlers.items():
            if str(request.url).startswith(prefix):
                return handler(request)
        return httpx2.Response(599, text=f"no fixture for {request.url}")

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]
