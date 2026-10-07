"""The real app, with USDA FoodData Central answered from the recorded fixtures (harnesses only).

    python -m uvicorn replay_app:app        # PYTHONPATH must include tools/e2e (khserver.Server does it)

FoodData Central has no base-URL setting (``app.foods.USDA_BASE_URL`` is fixed), so a harness that wants
the USDA steps without the network replaces ``app.foods.usda_client`` before the app starts: every request
is answered by an ``httpx2.MockTransport`` from ``tests/fixtures/usda/`` (recorded API answers, see the README
there). Branded searches by barcode find the recorded products; any other search finds nothing; an unknown
``/food/<id>`` is a 404. Every request is written to the server log, so a harness can count them. Nothing here
is imported by the app or the test suite, and Open Food Facts and AI keep their own settings (point
``OFF_BASE_URL`` and ``AI_BASE_URL`` at local fakes).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx2

import app.foods as foods

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "usda"
log = logging.getLogger("kidney_health.e2e.usda_replay")


def _fixture(name: str) -> dict[str, Any] | None:
    path = FIXTURES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _answer(doc: dict[str, Any]) -> httpx2.Response:
    body = doc.get("body")
    content = json.dumps(body).encode("utf-8") if body is not None else str(doc.get("text") or "").encode("utf-8")
    headers = {"Content-Type": doc.get("content_type") or "application/json", "X-RateLimit-Remaining": "999"}
    return httpx2.Response(int(doc["status"]), headers=headers, content=content)


def handle(request: httpx2.Request) -> httpx2.Response:
    """One FoodData Central request, answered from the fixtures (the API key is never looked at)."""
    path = request.url.path
    log.info("usda replay: %s %s", request.method, path)
    if path.endswith("/foods/search"):
        doc = _fixture(f"search_{request.url.params.get('query', '')}")
        if doc is not None and request.url.params.get("dataType") == "Branded":
            return _answer(doc)
        return httpx2.Response(200, json={"totalHits": 0, "currentPage": 1, "totalPages": 0, "foods": []},
                               headers={"X-RateLimit-Remaining": "999"})
    if "/food/" in path:
        doc = _fixture(f"food_{path.rsplit('/', 1)[-1]}")
        if doc is not None:
            return _answer(doc)
    return httpx2.Response(404, json={"error": "not found"}, headers={"X-RateLimit-Remaining": "999"})


def replay_client() -> httpx2.Client:
    """What ``app.foods.usda_client`` returns here: same base URL and headers, the replay transport."""
    return httpx2.Client(base_url=foods.USDA_BASE_URL, timeout=foods.USDA_TIMEOUT_S, follow_redirects=False,
                         trust_env=False, transport=httpx2.MockTransport(handle),
                         headers={"User-Agent": "kidney-health/0.3 (self-hosted food log)", "Accept": "application/json"})


def __getattr__(name: str) -> Any:
    """``replay_app:app`` (what uvicorn asks for): the real app, unchanged except that every FoodData Central
    request goes to :func:`handle`. Built on first access, so importing this module (the tests do) has no side
    effects."""
    if name != "app":
        raise AttributeError(name)
    foods.usda_client = replay_client
    from app.main import app as real_app

    globals()["app"] = real_app
    return real_app


__all__ = ["handle", "replay_client"]  # and ``app``, built on first access
