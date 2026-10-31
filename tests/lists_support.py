"""Fakes for design note 30: a list app that answers like Grocy, KitchenOwl or Mealie, and a web site with recipe pages. Both
answer through ``httpx2.MockTransport`` behind the app's real checked transports (a fake resolver gives each host an address), so
no test touches the network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx2

PUBLIC = "93.184.216.34"
HOME = "192.168.1.20"
KEY = "list-app-key-0123456789abcdef-test"


@dataclass
class FakeListApp:
    """One list app. ``app`` picks the API it answers; every request is recorded (path, headers, JSON body)."""

    app: str = "grocy"
    key: str = KEY
    prefix: str = ""  # a list app behind a path, e.g. "/grocy"
    lists: list[dict[str, Any]] = field(default_factory=lambda: [{"id": 1, "name": "Groceries"}])
    fail_after: int | None = None  # answer 500 after this many items were added
    redirect: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)
    added: list[Any] = field(default_factory=list)

    def _authorised(self, request: httpx2.Request) -> bool:
        if self.app == "grocy":
            return request.headers.get("grocy-api-key") == self.key
        return request.headers.get("authorization") == f"Bearer {self.key}"

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = urlsplit(str(request.url)).path
        body = json.loads(request.content) if request.content else None
        self.calls.append({"method": request.method, "path": path, "host": request.headers.get("host"), "body": body,
                           "headers": dict(request.headers), "query": urlsplit(str(request.url)).query})
        if self.redirect:
            return httpx2.Response(302, headers={"Location": "https://elsewhere.example/api"})
        if not path.startswith(self.prefix):
            return httpx2.Response(404)
        path = path[len(self.prefix):]
        if not self._authorised(request):
            return httpx2.Response(401, json={"error": "nope"})
        handler = getattr(self, f"_{self.app}")
        return handler(request.method, path, body)

    def _take(self, item: Any) -> httpx2.Response | None:
        if self.fail_after is not None and len(self.added) >= self.fail_after:
            return httpx2.Response(500, json={"error": "full"})
        self.added.append(item)
        return None

    def _grocy(self, method: str, path: str, body: Any) -> httpx2.Response:
        if method == "GET" and path == "/api/system/info":
            return httpx2.Response(200, json={"grocy_version": {"Version": "4.5.0", "ReleaseDate": "2025-01-01"}})
        if method == "GET" and path == "/api/objects/shopping_lists":
            return httpx2.Response(200, json=self.lists)
        if method == "POST" and path == "/api/objects/shopping_list":
            return self._take(body) or httpx2.Response(200, json={"created_object_id": len(self.added)})
        return httpx2.Response(404)

    def _kitchenowl(self, method: str, path: str, body: Any) -> httpx2.Response:
        if method == "GET" and path == "/api/user":
            return httpx2.Response(200, json={"id": 1, "username": "kim"})
        if method == "GET" and path == "/api/household":
            return httpx2.Response(200, json=[{"id": 3, "name": "Home"}])
        if method == "GET" and path == "/api/household/3/shoppinglist":
            return httpx2.Response(200, json=[{**x, "items": [], "recentItems": []} for x in self.lists])
        if method == "POST" and path.startswith("/api/shoppinglist/") and path.endswith("/add-item-by-name"):
            return self._take({"list": path.split("/")[3], **(body or {})}) or httpx2.Response(200, json={"id": 9, "name": body["name"]})
        return httpx2.Response(404)

    def _mealie(self, method: str, path: str, body: Any) -> httpx2.Response:
        if method == "GET" and path == "/api/users/self":
            return httpx2.Response(200, json={"id": "u1", "username": "kim"})
        if method == "GET" and path == "/api/households/shopping/lists":
            return httpx2.Response(200, json={"page": 1, "per_page": 50, "items": self.lists})
        if method == "POST" and path == "/api/households/shopping/items/create-bulk":
            for item in body:
                failed = self._take(item)
                if failed is not None:
                    return failed
            return httpx2.Response(201, json={"createdItems": body, "updatedItems": [], "deletedItems": []})
        return httpx2.Response(404)


def attach_list_app(app: Any, fake: FakeListApp, address: str | Callable[[str], str] = PUBLIC) -> FakeListApp:
    net = app.state.list_sync_net
    net.resolver = (lambda host, port: [address(host)]) if callable(address) else (lambda host, port: [address])
    net.direct = httpx2.MockTransport(fake.handler)
    net.use_env_proxy = False
    return fake


# --------------------------------------------------------------------------- #
# Recipe pages
# --------------------------------------------------------------------------- #


def recipe_jsonld(**changes: Any) -> dict[str, Any]:
    recipe: dict[str, Any] = {
        "@context": "https://schema.org", "@type": "Recipe", "name": "Lemon chicken &amp; rice",
        "recipeYield": ["4", "4 servings"],
        "recipeIngredient": ["1 lb chicken breast", "2 cups water", "3 large egg whites", "1/2 cup apple juice",
                             "1 tsp dried thyme", "Salt to taste"],
        "recipeInstructions": [{"@type": "HowToStep", "text": "Rinse the <b>rice</b>."},
                               {"@type": "HowToSection", "name": "Cook", "itemListElement": [
                                   {"@type": "HowToStep", "text": "Simmer for 20 minutes."}]}],
        "nutrition": {"@type": "NutritionInformation", "calories": "420 kcal", "sodiumContent": "300 mg"},
    }
    recipe.update(changes)
    return recipe


def page_html(*blocks: Any, extra: str = "") -> str:
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b) if not isinstance(b, str) else b}</script>'
                      for b in blocks)
    return (f"<!doctype html><html><head><title>Recipe</title>{scripts}<script>window.evil = 1;</script></head>"
            f"<body><h1>Recipe</h1>{extra}</body></html>")


@dataclass
class FakeSite:
    """A web site: ``pages`` maps a path to ``(status, headers, body)``; every request is recorded."""

    pages: dict[str, tuple[int, dict[str, str], bytes]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def add(self, path: str, html: str, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.pages[path] = (status, {"Content-Type": "text/html; charset=utf-8", **(headers or {})}, html.encode("utf-8"))

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        parts = urlsplit(str(request.url))
        self.calls.append({"host": request.headers.get("host"), "path": parts.path, "headers": dict(request.headers)})
        status, headers, body = self.pages.get(parts.path, (404, {"Content-Type": "text/html"}, b"<p>Not found</p>"))
        return httpx2.Response(status, headers=headers, content=body)


def attach_site(app: Any, site: FakeSite, address: str | Callable[[str], str] = PUBLIC) -> FakeSite:
    fetcher = app.state.recipe_fetcher
    fetcher.resolver = (lambda host, port: [address(host)]) if callable(address) else (lambda host, port: [address])
    fetcher.direct = httpx2.MockTransport(site.handler)
    fetcher.use_env_proxy = False
    return site
