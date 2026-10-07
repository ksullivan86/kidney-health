"""The AI client's network layer: resolve, check, pin, cap (note 04 R5 steps 2–6 and §9 A5).

Every AI request goes through :class:`PinnedTransport`, an ``httpx2`` async transport that

* resolves the host **at request time** (``socket.getaddrinfo`` in a worker thread) and checks
  **every** address with :mod:`app.ai.netpolicy` (one bad answer refuses the call);
* connects to the checked address itself, keeping the original ``Host`` header and TLS server name
  (``sni_hostname``), so a second DNS answer cannot move the connection (DNS rebinding);
* never reads ``HTTP(S)_PROXY`` from the environment (``trust_env=False``); only ``AI_HTTP_PROXY``
  routes calls through a proxy, and then only to public hosts (the proxy resolves those names, so
  pinning is its job; allowlisted private hosts are still reached directly and pinned);
* refuses a request outside the provider's own origin.

:func:`send_json` adds the rest of the rules: redirects are errors (``follow_redirects=False``), the
answer must be ``application/json``, the body is streamed and **decoded** bytes are counted against
``AI_MAX_RESPONSE_BYTES`` (``Accept-Encoding: identity`` is sent as well), the whole call has a
deadline of read timeout + 10 s, and every failure becomes one coarse :class:`AiTransportError`
category. Response bodies are never put into error messages.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import anyio
import httpx2

from .netpolicy import BaseUrl, NetPolicy, PolicyError, Scope, check_addresses, check_host_name, check_url, classify

log = logging.getLogger("kidney_health.ai")

Resolver = Callable[[str, int], list[str]]

CONNECT_TIMEOUT_S = 5.0
WRITE_TIMEOUT_S = 10.0
POOL_TIMEOUT_S = 5.0
DEADLINE_EXTRA_S = 10.0  # total deadline = read timeout + this


# Where truststore (httpx2's TLS verifier) finds CA certificates on Linux when OpenSSL's default paths are
# empty: the same candidates as truststore._openssl (from certifi-system-store), copied so a private name
# of that package is not imported.
CA_FILE_CANDIDATES: tuple[str, ...] = (
    "/etc/ssl/cert.pem",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/pki/tls/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/ca-bundle.pem",
)
_HASHED_CERT = re.compile(r"^[0-9a-fA-F]{8}\.[0-9]$")


def ca_store_problem(platform: str | None = None) -> str | None:
    """R12 start-up self-check: ``None`` when TLS verification has CA certificates to use, else the reason.

    On Linux, httpx2 verifies with ``truststore``, which reads OpenSSL's default CA file or directory
    (``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` included) and then a few well-known bundle paths. A minimal
    image without ``ca-certificates`` has none, and every https call would then fail with an opaque TLS
    error. On macOS and Windows truststore uses the system store, which always exists.
    """
    if not (platform or sys.platform).startswith("linux"):
        return None
    paths = ssl.get_default_verify_paths()
    try:
        if paths.cafile and os.path.getsize(paths.cafile) > 0:
            return None
        if paths.capath and os.path.isdir(paths.capath) and any(_HASHED_CERT.match(n) for n in os.listdir(paths.capath)):
            return None
        if any(os.path.isfile(p) and os.path.getsize(p) > 0 for p in CA_FILE_CANDIDATES):
            return None
    except OSError:
        pass
    return ("no CA certificates were found for TLS verification (OpenSSL's default file and directory and the usual "
            "bundle paths are empty): install the ca-certificates package in the image or set SSL_CERT_FILE")


class AiTransportError(Exception):
    """A failed AI request: ``category`` (netpolicy.ERROR_CATEGORIES), the HTTP status if any, and
    ``retry_after`` seconds from a 429. The message is safe to log and never holds a response body."""

    def __init__(self, category: str, message: str = "", *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message or category)
        self.category = category
        self.status = status
        self.retry_after = retry_after


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        if address not in out:
            out.append(address)
    return out


class PinnedTransport(httpx2.AsyncBaseTransport):
    """Resolve → check every address → connect to the first one, for one provider's base URL."""

    def __init__(
        self,
        base: BaseUrl,
        scope: Scope,
        policy: NetPolicy,
        *,
        resolver: Resolver | None = None,
        inner: httpx2.AsyncBaseTransport | None = None,
        proxied: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = base
        self.scope = scope
        self.policy = policy
        self._resolve = resolver or system_resolver
        self._inner = inner
        self._proxied = proxied

    def _direct(self) -> httpx2.AsyncBaseTransport:
        if self._inner is None:
            self._inner = httpx2.AsyncHTTPTransport(trust_env=False, retries=0)
        return self._inner

    def _proxy(self) -> httpx2.AsyncBaseTransport:
        if self._proxied is None:
            self._proxied = httpx2.AsyncHTTPTransport(proxy=self.policy.proxy, trust_env=False, retries=0)
        return self._proxied

    async def _addresses(self, host: str, port: int) -> list[str]:
        if self.base.ip is not None:
            return [str(self.base.ip)]
        try:
            return await anyio.to_thread.run_sync(self._resolve, host, port)
        except (OSError, UnicodeError) as exc:
            raise AiTransportError("dns_failed", f"{host} could not be resolved") from exc

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        url = request.url
        port = url.port or (443 if url.scheme == "https" else 80)
        # The ASCII (IDNA) form: ``url.host`` is decoded Unicode ("bücher.example"), while the base URL keeps
        # the punycode ("xn--bcher-kva.example") that DNS, the Host header and SNI use.
        host = url.raw_host.decode("ascii").lower()
        if (url.scheme, host, port) != (self.base.scheme, self.base.host, self.base.port):
            raise AiTransportError("blocked_address", "request outside the provider's base URL")
        try:
            check_host_name(self.base)
            check_url(self.base, self.scope, self.policy)
        except PolicyError as exc:
            raise AiTransportError(exc.category, str(exc)) from None
        try:
            raw = await self._addresses(host, port)
        except AiTransportError:
            # Behind AI_HTTP_PROXY the container may have no DNS for public names: the proxy resolves them.
            if self.policy.proxy and self.scope == "shared":
                return await self._proxy().handle_async_request(request)
            raise
        try:
            addresses = check_addresses(self.base, raw, self.scope, self.policy)
        except PolicyError as exc:
            log.warning("AI request refused: %s", exc)
            raise AiTransportError(exc.category, str(exc)) from None
        public = all(classify(a, self.policy) == "global" for a in addresses)
        if self.policy.proxy and public:
            return await self._proxy().handle_async_request(request)
        address = addresses[0]
        if str(address) != host:
            request.url = url.copy_with(host=str(address))
            if url.scheme == "https":
                request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._direct().handle_async_request(request)

    async def aclose(self) -> None:
        for transport in (self._inner, self._proxied):
            if transport is not None:
                await transport.aclose()


@dataclass
class HttpResult:
    status: int
    data: Any  # parsed JSON
    latency_ms: int
    headers: Mapping[str, str]


TransportFactory = Callable[[BaseUrl, Scope, NetPolicy], httpx2.AsyncBaseTransport]


def default_transport_factory(base: BaseUrl, scope: Scope, policy: NetPolicy) -> httpx2.AsyncBaseTransport:
    return PinnedTransport(base, scope, policy)


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def status_category(status: int) -> str:
    if status == 401:
        return "http_401"
    if status == 403:
        return "http_403"
    if status == 404:
        return "http_404"
    if status == 429:
        return "http_429"
    if 500 <= status <= 599:
        return "http_5xx"
    if 300 <= status <= 399:
        return "invalid_response"  # redirects are never followed
    return "http_4xx"


async def send_json(
    base: BaseUrl,
    scope: Scope,
    policy: NetPolicy,
    *,
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: Any | None = None,
    read_timeout_s: float,
    max_bytes: int,
    transport_factory: TransportFactory | None = None,
    error_snippet: Callable[[bytes], None] | None = None,
) -> HttpResult:
    """One request to ``{base}/{path}``; the parsed JSON answer or :class:`AiTransportError`.

    ``error_snippet`` (shared providers' admin probe only) receives at most the first 300 bytes of a
    non-2xx body; everyone else gets the category only (R5 step 6).
    """
    factory = transport_factory or default_transport_factory
    transport = factory(base, scope, policy)
    timeout = httpx2.Timeout(connect=CONNECT_TIMEOUT_S, read=read_timeout_s, write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S)
    send_headers = {"Accept": "application/json", "Accept-Encoding": "identity", **headers}
    started = time.monotonic()
    try:
        with anyio.fail_after(read_timeout_s + DEADLINE_EXTRA_S):
            async with httpx2.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False) as client:
                content = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if content is not None:
                    send_headers["Content-Type"] = "application/json"
                request = client.build_request(method, base.endpoint(path), content=content, headers=send_headers)
                response = await client.send(request, stream=True)
                try:
                    status = response.status_code
                    if status >= 300 or status < 200:
                        if error_snippet is not None and status >= 400:
                            chunk = b""
                            async for part in response.aiter_bytes():
                                chunk += part
                                if len(chunk) >= 300:
                                    break
                            error_snippet(chunk[:300])
                        raise AiTransportError(
                            status_category(status), f"HTTP {status}", status=status,
                            retry_after=_retry_after(response.headers.get("Retry-After")),
                        )
                    ctype = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if ctype != "application/json" and not ctype.endswith("+json"):
                        raise AiTransportError("invalid_response", "the answer is not JSON", status=status)
                    declared = response.headers.get("Content-Length")
                    if declared and declared.isdigit() and int(declared) > max_bytes and not response.headers.get("Content-Encoding"):
                        raise AiTransportError("invalid_response", "the answer is larger than AI_MAX_RESPONSE_BYTES", status=status)
                    total = 0
                    chunks: list[bytes] = []
                    async for part in response.aiter_bytes():  # decoded bytes (§9 A5 c)
                        total += len(part)
                        if total > max_bytes:
                            raise AiTransportError("invalid_response", "the answer is larger than AI_MAX_RESPONSE_BYTES", status=status)
                        chunks.append(part)
                    try:
                        data = json.loads(b"".join(chunks).decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        raise AiTransportError("invalid_response", "the answer is not valid JSON", status=status) from None
                    return HttpResult(status, data, int((time.monotonic() - started) * 1000), dict(response.headers))
                finally:
                    await response.aclose()
    except AiTransportError:
        raise
    except TimeoutError:
        raise AiTransportError("timeout", "the AI server did not answer in time") from None
    except httpx2.TimeoutException:
        raise AiTransportError("timeout", "the AI server did not answer in time") from None
    except httpx2.ConnectError as exc:
        raise AiTransportError("connect_failed", f"could not connect to {base.host_port}") from exc
    except (httpx2.TransportError, OSError) as exc:
        raise AiTransportError("connect_failed", f"the connection to {base.host_port} failed") from exc
