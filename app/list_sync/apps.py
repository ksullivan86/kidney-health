"""The three list apps a person can send the shopping list to: Grocy, KitchenOwl, Mealie (design note 30 §1, §2).

Each request goes through :class:`ListTransport`, an :class:`app.egress.CheckedTransport` that also allows a private address when
the admin listed its host, address or network in ``LIST_SYNC_ALLOWED_HOSTS``. Cloud metadata, link-local and reserved addresses
are always refused. A plain ``http`` request must stay on such a listed private address: on the internet the key travels only over
``https``. Redirects are never followed (a ``3xx`` is the error ``redirect``); at most 1 MiB of answer is read; 15 seconds per
request.

What is sent: the key in the app's header, and for each food on the list its name and amount. Nothing about the person. Every
failure is a :class:`ListAppError` with a short code; nothing here logs the key, the address or the answer.
"""
from __future__ import annotations

import ipaddress
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx2

from .. import brand, egress

log = logging.getLogger(f"{brand.LOGGER_NAME}.list_sync")

HTTP_TIMEOUT_S = 15.0
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_HOUSEHOLDS = 10
MEALIE_BATCH = 50
NAME_MAX = 128

APPS: dict[str, dict[str, str]] = {
    "grocy": {"name": "Grocy", "key_name": "API key",
              "key_help": "In Grocy, open Settings (the wrench), then Manage API keys, then Add."},
    "kitchenowl": {"name": "KitchenOwl", "key_name": "Long-lived token",
                   "key_help": "In KitchenOwl, open Settings, then your profile, then Sessions, and add a long-lived token."},
    "mealie": {"name": "Mealie", "key_name": "API token",
               "key_help": "In Mealie, open your profile, then API Tokens, and generate one."},
}
ERROR_CODES = ("unreachable", "blocked", "redirect", "auth", "not_found", "app_error")


class ListAppError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code if code in ERROR_CODES else "app_error"
        self.sent = 0  # items the app took before this failure (a send)


@dataclass(frozen=True)
class ListRef:
    id: str
    name: str


@dataclass(frozen=True)
class Item:
    food_id: int
    name: str
    amount: str
    text: str


# --------------------------------------------------------------------------- #
# Addresses
# --------------------------------------------------------------------------- #


IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class HostAllowlist:
    """``LIST_SYNC_ALLOWED_HOSTS``: host names, and addresses or networks."""

    names: frozenset[str]
    networks: tuple[IPNetwork, ...]

    @classmethod
    def parse(cls, entries: tuple[str, ...]) -> "HostAllowlist":
        names: set[str] = set()
        networks: list[IPNetwork] = []
        for entry in entries:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                names.add(entry.lower().rstrip("."))
        return cls(frozenset(names), tuple(networks))

    @property
    def empty(self) -> bool:
        return not self.names and not self.networks

    def allows(self, host: str, address: egress.IPAddress) -> bool:
        if host.lower().rstrip(".") in self.names:
            return True
        inner = egress.embedded_ipv4(address)
        for candidate in (address, inner):
            if candidate is not None and any(candidate.version == net.version and candidate in net for net in self.networks):
                return True
        return False


class ListTransport(egress.CheckedTransport):
    """The checked transport with the admin's private hosts allowed, and plain ``http`` kept on them."""

    def __init__(self, allowlist: HostAllowlist, **kwargs: Any) -> None:
        super().__init__(allow_private=True, **kwargs)
        self.allowlist = allowlist
        self._scheme = "https"

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self._scheme = request.url.scheme
        return super().handle_request(request)

    def checked_addresses(self, host: str, port: int) -> list[egress.IPAddress]:
        addresses = super().checked_addresses(host, port)  # denied addresses are refused there
        for address in addresses:
            private = egress.classify_address(address) == "private"
            if private and not self.allowlist.allows(host, address):
                log.warning("list sync: refused a private address that LIST_SYNC_ALLOWED_HOSTS does not list")
                raise egress.BlockedAddress("blocked_address: a private address that is not allowed")
            if self._scheme == "http" and not private:
                log.warning("list sync: refused plain http to a public address")
                raise egress.BlockedAddress("blocked_address: plain http to a public address")
        return addresses


def check_base_url(raw: str, allowlist: HostAllowlist) -> tuple[str | None, str | None]:
    """``(address, None)``: the list app's address without a trailing slash; or ``(None, problem)``, a plain sentence."""
    text = (raw or "").strip()
    if not text or len(text) > 500 or any(ch.isspace() or not ch.isprintable() for ch in text):
        return None, "Enter the address of your list app, such as https://grocy.example.com."
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None, "That address cannot be read. Enter it as https://your-server or http://192.168.1.20:9283."
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or port == 0:
        return None, "The address must start with http:// or https:// and name a server."
    if parts.username or parts.password:
        return None, "Leave the user name and password out of the address. The key goes in its own box."
    if parts.query or parts.fragment:
        return None, "Leave anything after ? or # out of the address."
    if parts.scheme.lower() == "http" and allowlist.empty:
        return None, "Plain http works only for a home address your admin allowed. Use https, or ask your admin."
    return f"{parts.scheme.lower()}://{parts.netloc}{parts.path.rstrip('/')}", None


# --------------------------------------------------------------------------- #
# The clients
# --------------------------------------------------------------------------- #


@dataclass
class Net:
    """How requests are made (``app.state.list_sync_net``). ``resolver``, ``direct`` and ``use_env_proxy`` exist for tests."""

    allowlist: HostAllowlist
    resolver: Callable[[str, int], list[str]] | None = None
    direct: httpx2.BaseTransport | None = None
    use_env_proxy: bool = True

    def client(self) -> httpx2.Client:
        transport = ListTransport(self.allowlist, resolver=self.resolver, use_env_proxy=self.use_env_proxy, direct=self.direct)
        return httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_S, follow_redirects=False, trust_env=False,
                             headers={"User-Agent": brand.USER_AGENT_LISTS, "Accept": "application/json"})


class ListApp:
    """One person's list app. ``key`` is used only in the request header."""

    app = ""
    test_path = ""

    def __init__(self, net: Net, base_url: str, key: str) -> None:
        self.net = net
        self.base_url = base_url.rstrip("/")
        self._key = key

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    def request(self, method: str, path: str, *, body: Any = None, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            with self.net.client() as client, client.stream(method, url, json=body, params=params, headers=self.headers()) as response:
                raw = egress.read_capped(response, MAX_RESPONSE_BYTES)
                status = response.status_code
        except egress.BlockedAddress:
            raise ListAppError("blocked") from None
        except egress.ResponseTooLarge:
            log.warning("list sync: the list app's answer was too large")
            raise ListAppError("app_error") from None
        except httpx2.HTTPError:
            log.warning("list sync: the list app did not answer")
            raise ListAppError("unreachable") from None
        if 300 <= status < 400:
            raise ListAppError("redirect")
        if status in (401, 403):
            raise ListAppError("auth")
        if status == 404:
            raise ListAppError("not_found")
        if not 200 <= status < 300:
            log.warning("list sync: the list app answered with an error")
            raise ListAppError("app_error")
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise ListAppError("app_error") from None

    def test(self) -> list[ListRef]:
        self.request("GET", self.test_path)
        return self.lists()

    def lists(self) -> list[ListRef]:  # pragma: no cover - each app has its own
        raise NotImplementedError

    def send(self, list_id: str, items: list[Item]) -> int:  # pragma: no cover - each app has its own
        raise NotImplementedError


def _name(value: Any, fallback: str) -> str:
    return str(value)[:200] if isinstance(value, (str, int)) and str(value).strip() else fallback


class Grocy(ListApp):
    """``GROCY-API-KEY``; a shopping list item may be a note alone (``grocy.openapi.json``)."""

    app = "grocy"
    test_path = "api/system/info"

    def headers(self) -> dict[str, str]:
        return {"GROCY-API-KEY": self._key}

    def lists(self) -> list[ListRef]:
        data = self.request("GET", "api/objects/shopping_lists")
        if not isinstance(data, list):
            raise ListAppError("app_error")
        return [ListRef(str(x["id"]), _name(x.get("name"), f"List {x['id']}")) for x in data
                if isinstance(x, dict) and isinstance(x.get("id"), int)]

    def send(self, list_id: str, items: list[Item]) -> int:
        sent = 0
        try:
            for item in items:
                self.request("POST", "api/objects/shopping_list", body={"shopping_list_id": int(list_id), "note": item.text})
                sent += 1
        except ListAppError as exc:
            exc.sent = sent
            raise
        return sent


class KitchenOwl(ListApp):
    """A long-lived token; an item is added by name to a household's list, with the amount as its description."""

    app = "kitchenowl"
    test_path = "api/user"

    def lists(self) -> list[ListRef]:
        households = self.request("GET", "api/household")
        if not isinstance(households, list):
            raise ListAppError("app_error")
        out: list[ListRef] = []
        for house in households[:MAX_HOUSEHOLDS]:
            if not isinstance(house, dict) or not isinstance(house.get("id"), int):
                continue
            lists = self.request("GET", f"api/household/{house['id']}/shoppinglist")
            for x in lists if isinstance(lists, list) else []:
                if isinstance(x, dict) and isinstance(x.get("id"), int):
                    out.append(ListRef(str(x["id"]), f"{_name(house.get('name'), 'Household')}: {_name(x.get('name'), 'List')}"))
        return out

    def send(self, list_id: str, items: list[Item]) -> int:
        sent = 0
        try:
            for item in items:
                self.request("POST", f"api/shoppinglist/{int(list_id)}/add-item-by-name",
                             body={"name": item.name[:NAME_MAX], "description": item.amount})
                sent += 1
        except ListAppError as exc:
            exc.sent = sent
            raise
        return sent


class Mealie(ListApp):
    """An API token; items are added in bulk with the line as the note and quantity 0, so the item shows exactly the line."""

    app = "mealie"
    test_path = "api/users/self"

    def lists(self) -> list[ListRef]:
        data = self.request("GET", "api/households/shopping/lists", params={"page": 1, "perPage": 50})
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ListAppError("app_error")
        return [ListRef(str(x["id"]), _name(x.get("name"), "List")) for x in items
                if isinstance(x, dict) and isinstance(x.get("id"), str) and x["id"]]

    def send(self, list_id: str, items: list[Item]) -> int:
        sent = 0
        try:
            for start in range(0, len(items), MEALIE_BATCH):
                batch = items[start:start + MEALIE_BATCH]
                self.request("POST", "api/households/shopping/items/create-bulk",
                             body=[{"shoppingListId": list_id, "note": item.text, "quantity": 0} for item in batch])
                sent += len(batch)
        except ListAppError as exc:
            exc.sent = sent
            raise
        return sent


CLIENTS: dict[str, type[ListApp]] = {"grocy": Grocy, "kitchenowl": KitchenOwl, "mealie": Mealie}


def client_for(net: Net, app: str, base_url: str, key: str) -> ListApp:
    return CLIENTS[app](net, base_url, key)


def valid_list_id(app: str, list_id: str) -> bool:
    if app in ("grocy", "kitchenowl"):
        return list_id.isdigit() and 0 < len(list_id) <= 18
    return 0 < len(list_id) <= 64 and all(ch.isalnum() or ch == "-" for ch in list_id)
