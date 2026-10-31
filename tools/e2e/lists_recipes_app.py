"""The real app, with recipe pages answered by a fake recipe site in the same process (harnesses only).

    python -m uvicorn lists_recipes_app:app        # PYTHONPATH must include tools/e2e (khserver.Server does it)

The server never opens a page on a private or local address, so a fake site on 127.0.0.1 would be refused (as it should be).
This wrapper keeps the app's real ``RecipeFetcher`` and its real checked transport, and only answers the requests: every host
resolves to a public test address (93.184.216.34) and the answer comes from :data:`PAGES` through ``httpx2.MockTransport``.
``https://home.test/...`` resolves to a private address instead, so a harness can see that one refused. Every request is
written to the server log. Nothing here is imported by the app or the test suite.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx2

log = logging.getLogger("kidney_health.e2e.recipe_site")

RECIPE = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "WebSite", "name": "A test recipe site"},
        {"@type": "Recipe", "name": "Garlic chicken and rice", "recipeYield": "4 servings",
         "recipeIngredient": ["1 lb boneless skinless chicken breast", "2 cups cooked white rice", "3 cloves garlic, minced",
                              "1 tbsp olive oil", "1 tsp dried thyme"],
         "recipeInstructions": [{"@type": "HowToStep", "text": "Cook the chicken and garlic in the oil."},
                                {"@type": "HowToStep", "text": "Serve over the rice."}],
         "nutrition": {"@type": "NutritionInformation", "calories": "390 kcal"}},
    ],
}
PAGES = {
    "/garlic-chicken": ("<!doctype html><html><head><title>Garlic chicken</title>"
                        f'<script type="application/ld+json">{json.dumps(RECIPE)}</script>'
                        "<script>window.ran = true;</script></head><body><h1>Garlic chicken</h1></body></html>"),
    "/no-recipe": "<!doctype html><html><head><title>News</title></head><body><p>No recipe here.</p></body></html>",
}


def handle(request: httpx2.Request) -> httpx2.Response:
    path = urlsplit(str(request.url)).path
    log.info("recipe site: %s %s", request.method, path)
    page = PAGES.get(path)
    if page is None:
        return httpx2.Response(404, headers={"Content-Type": "text/html"}, content=b"<p>Not found</p>")
    return httpx2.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, content=page.encode("utf-8"))


def resolve(host: str, port: int) -> list[str]:
    return ["192.168.1.30"] if host == "home.test" else ["93.184.216.34"]


def __getattr__(name: str) -> Any:
    """``lists_recipes_app:app``: the real app with the fake site behind its real fetcher. Built on first access."""
    if name != "app":
        raise AttributeError(name)
    from app.main import app as real_app

    fetcher = real_app.state.recipe_fetcher
    fetcher.resolver = resolve
    fetcher.direct = httpx2.MockTransport(handle)
    fetcher.use_env_proxy = False
    globals()["app"] = real_app
    return real_app


__all__ = ["PAGES", "handle", "resolve"]  # and ``app``, built on first access
