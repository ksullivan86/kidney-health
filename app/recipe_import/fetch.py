"""Reading a recipe page the person asked for (design note 30 §3.2). The server fetches it, never the browser.

* Only ``http`` and ``https`` links that pass :func:`app.models.check_source_url`, on the usual ports (80 and 443).
* Every request goes through :class:`app.egress.CheckedTransport` with private addresses refused: the address is checked when the
  request is made, so a name that resolves to a home or cloud-internal address is never contacted.
* Redirects are followed by hand, at most :data:`MAX_REDIRECTS`, each new link checked again as above.
* At most :data:`MAX_PAGE_BYTES` of page (counted after decompression) and :data:`DEADLINE_S` seconds in all; only HTML.
* The request carries no cookie, no key and nothing about the person. The page is returned as text to the caller and never kept.

Every refusal is a :class:`PageError` with a short code; its message is a constant sentence, never text from the page or the
address, and nothing here logs the link.
"""
from __future__ import annotations

import codecs
import logging
import re
import time
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx2

from .. import brand, egress
from ..models import SOURCE_URL_MAX, check_source_url

log = logging.getLogger(f"{brand.LOGGER_NAME}.recipe_import")

MAX_REDIRECTS = 3
MAX_PAGE_BYTES = 2 * 1024 * 1024
DEADLINE_S = 15.0
ALLOWED_PORTS = (80, 443)
HTML_TYPES = ("text/html", "application/xhtml+xml")

# code -> what the person reads (plain words; the code goes to the screen too).
MESSAGES = {
    "bad_link": "That link cannot be read. Use a web address that starts with http:// or https://.",
    "blocked": "This server does not open that address. It may be a private or local address.",
    "unreachable": "The page did not answer. Check the link, or paste the ingredients instead.",
    "timeout": "The page took too long to answer. Try again, or paste the ingredients instead.",
    "too_large": "That page is too large to read. Paste the ingredients instead.",
    "not_html": "That link is not a web page. Paste the ingredients instead.",
    "http_error": "The site did not give the page. Check the link, or paste the ingredients instead.",
    "too_many_redirects": "That link sends the app on to too many other addresses. Use the recipe page's own link.",
}


class PageError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code if code in MESSAGES else "unreachable"

    @property
    def message(self) -> str:
        return MESSAGES[self.code]


def check_page_url(url: str) -> str:
    """The link, if the server may open it (raises :class:`PageError` ``bad_link`` otherwise)."""
    if not isinstance(url, str) or not url or len(url) > SOURCE_URL_MAX:
        raise PageError("bad_link")
    try:
        check_source_url(url)
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise PageError("bad_link") from None
    if port is not None and port not in ALLOWED_PORTS:
        raise PageError("bad_link")
    return url


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_\-:.]+)""", re.IGNORECASE)


def _charset(content_type: str, head: bytes) -> str:
    for candidate in (re.search(r"charset\s*=\s*\"?([A-Za-z0-9_\-:.]+)", content_type or "", re.IGNORECASE),
                      _META_CHARSET.search(head[:4096])):
        if candidate is not None:
            name = candidate.group(1)
            name = name.decode("ascii", "replace") if isinstance(name, bytes) else name
            try:
                info = codecs.lookup(name)
            except LookupError:
                continue
            if getattr(info, "_is_text_encoding", True):
                return info.name
    return "utf-8"


class RecipeFetcher:
    """``app.state.recipe_fetcher``. ``resolver``, ``direct`` and ``use_env_proxy`` exist for tests (a fake site behind the real
    checked transport); ``clock`` for the deadline."""

    def __init__(self, *, resolver: Callable[[str, int], list[str]] | None = None, direct: httpx2.BaseTransport | None = None,
                 use_env_proxy: bool = True, clock: Callable[[], float] = time.monotonic,
                 deadline_s: float = DEADLINE_S, max_bytes: int = MAX_PAGE_BYTES) -> None:
        self.resolver = resolver
        self.direct = direct
        self.use_env_proxy = use_env_proxy
        self.clock = clock
        self.deadline_s = deadline_s
        self.max_bytes = max_bytes

    def _client(self) -> httpx2.Client:
        transport = egress.CheckedTransport(allow_private=False, resolver=self.resolver, use_env_proxy=self.use_env_proxy,
                                            direct=self.direct)
        timeout = httpx2.Timeout(self.deadline_s)
        return httpx2.Client(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False,
                             headers={"User-Agent": brand.USER_AGENT_RECIPES,
                                      "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"})

    def fetch(self, url: str) -> str:
        """The page as text. Raises :class:`PageError`. The whole fetch, headers and redirects included, has
        :data:`DEADLINE_S` seconds (:func:`app.egress.run_with_deadline`)."""
        check_page_url(url)
        try:
            return egress.run_with_deadline("recipe", lambda: self._fetch(url), self.deadline_s)
        except egress.DeadlineExceeded:
            raise PageError("timeout") from None

    def _fetch(self, url: str) -> str:
        current = check_page_url(url)
        started = self.clock()
        with self._client() as client:
            for _hop in range(MAX_REDIRECTS + 1):
                if self.clock() - started > self.deadline_s:
                    raise PageError("timeout")
                try:
                    with client.stream("GET", current) as response:
                        status = response.status_code
                        if 300 <= status < 400 and response.headers.get("Location"):
                            location = response.headers["Location"]
                            current = check_page_url(urljoin(current, location.strip()))
                            continue
                        if status != 200:
                            raise PageError("http_error")
                        kind = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        if kind and kind not in HTML_TYPES:
                            raise PageError("not_html")
                        raw = self._read(response, started)
                        charset = _charset(response.headers.get("Content-Type", ""), raw)
                except egress.BlockedAddress:
                    log.warning("recipe import: the server refused to open a page address (private, local or not resolving)")
                    raise PageError("blocked") from None
                except httpx2.TimeoutException:
                    raise PageError("timeout") from None
                except httpx2.HTTPError:
                    raise PageError("unreachable") from None
                try:
                    return raw.decode(charset, errors="replace")
                except LookupError:  # a "charset" that is not a text encoding (zlib, base64, ...)
                    return raw.decode("utf-8", errors="replace")
        raise PageError("too_many_redirects")

    def _read(self, response: httpx2.Response, started: float) -> bytes:
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes and not response.headers.get("Content-Encoding"):
            raise PageError("too_large")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise PageError("too_large")
            if self.clock() - started > self.deadline_s:
                raise PageError("timeout")
            chunks.append(chunk)
        return b"".join(chunks)
