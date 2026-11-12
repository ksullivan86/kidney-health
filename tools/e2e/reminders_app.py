"""The real app, with the push services answered by a fake inside the same process (harnesses only).

    python -m uvicorn reminders_app:app        # PYTHONPATH must include tools/e2e (khserver.Server does it)

The server never sends to a private or local address, and only to the known push hosts, so a fake on 127.0.0.1 would be refused
(as it should be). This wrapper keeps the app's real ``webpush.Sender`` and its real checked transport, and only answers the
requests: every push host resolves to a public test address (17.188.143.33) and the answer comes from :func:`handle` through
``httpx2.MockTransport``. The fake decrypts each message with the browser key below (the RFC 8291 example's receiver key, which
the walk's stubbed ``PushManager.subscribe`` hands to the app) and writes it to the server log as one ``push fake:`` line, so a
harness can read exactly what a phone would show. Nothing here is imported by the app or the test suite.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx2

log = logging.getLogger("kidney_health.e2e.push")

# RFC 8291 §5: the receiver's key pair and auth secret (test values, published in the RFC).
UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
ENDPOINT = "https://web.push.apple.com/e2e-walk-0123456789abcdef"


def handle(request: httpx2.Request) -> httpx2.Response:
    from cryptography.hazmat.primitives.asymmetric import ec

    from app import webpush

    key = ec.derive_private_key(int.from_bytes(webpush.b64url_decode(UA_PRIVATE), "big"), ec.SECP256R1())
    try:
        message = json.loads(webpush.decrypt(request.content, key, webpush.b64url_decode(AUTH)))
    except Exception as exc:  # noqa: BLE001 - logged for the harness
        message = {"error": type(exc).__name__}
    log.info("push fake: %s", json.dumps({"host": request.headers.get("host"), "path": request.url.path,
                                          "ttl": request.headers.get("ttl"), "urgency": request.headers.get("urgency"),
                                          "vapid": request.headers.get("authorization", "").startswith("vapid t="),
                                          "message": message}))
    return httpx2.Response(201)


def resolve(host: str, port: int) -> list[str]:
    return ["17.188.143.33"]


def __getattr__(name: str) -> Any:
    """``reminders_app:app``: the real app with the fake push services behind its real sender. Built on first access."""
    if name != "app":
        raise AttributeError(name)
    from app.main import app as real_app

    push = real_app.state.webpush
    push.resolver = resolve
    push.direct = httpx2.MockTransport(handle)
    push.use_env_proxy = False
    globals()["app"] = real_app
    return real_app


__all__ = ["AUTH", "ENDPOINT", "UA_PUBLIC", "handle", "resolve"]  # and ``app``, built on first access
