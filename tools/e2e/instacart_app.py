"""The real app, with Instacart answered by a fake inside the same process (harnesses only).

    python -m uvicorn instacart_app:app        # PYTHONPATH must include tools/e2e (khserver.Server does it)

The server never calls a private or local address for Instacart, so a fake on 127.0.0.1 would be refused (as it should be). This
wrapper keeps the app's real ``InstacartClient`` and its real checked transport, and only answers the requests: Instacart's host
resolves to a public test address (93.184.216.34) and the answer comes from :func:`handle` through ``httpx2.MockTransport``.
Each request's body is written to the server log as one ``instacart fake:`` line, so a harness can read exactly what was sent.
Nothing here is imported by the app or the test suite.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx2

log = logging.getLogger("kidney_health.e2e.instacart")

LINK = "https://customers.dev.instacart.tools/store/shopping_lists/e2e-123"
KEY = "instacart-e2e-key-0123456789abcdef"


def handle(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content or b"null")
    good_key = request.headers.get("authorization") == f"Bearer {KEY}"
    log.info("instacart fake: %s", json.dumps({"path": request.url.path, "host": request.headers.get("host"), "key_ok": good_key,
                                               "body": body}))
    if not good_key:
        return httpx2.Response(401, json={"error": {"message": "Unauthorized"}})
    return httpx2.Response(200, json={"products_link_url": LINK})


def resolve(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


def __getattr__(name: str) -> Any:
    """``instacart_app:app``: the real app with the fake Instacart behind its real client. Built on first access."""
    if name != "app":
        raise AttributeError(name)
    from app.main import app as real_app

    client = real_app.state.instacart
    client.resolver = resolve
    client.direct = httpx2.MockTransport(handle)
    client.use_env_proxy = False
    globals()["app"] = real_app
    return real_app


__all__ = ["KEY", "LINK", "handle", "resolve"]  # and ``app``, built on first access
