"""SSRF-checked outbound HTTP for the server's calls to fixed provider hosts (USDA, Open Food Facts).

The app makes no outbound request until a feature is turned on (docs/network-allowlist.md). When it
does, every request goes through :class:`CheckedTransport`, which

* resolves the host **at request time** and checks **every** address it resolves to (DNS can change
  after start-up), unwrapping IPv4 addresses carried inside IPv6 forms (IPv4-mapped, 6to4, Teredo,
  the NAT64 prefixes ``64:ff9b::/96`` and ``64:ff9b:1::/48`` and IPv4-compatible ``::/96``), which
  Python's ``ipaddress`` would otherwise call global;
* always refuses unspecified, multicast, reserved and link-local addresses, the cloud metadata
  endpoints and the Kubernetes API service address;
* refuses private, loopback, CGNAT and unique-local addresses unless the operator configured that
  host explicitly (``allow_private=True``, for a self-hosted Open Food Facts on the LAN);
* connects to the checked IP address itself, with the original ``Host`` header and TLS server name
  (SNI and certificate check), so a second DNS answer cannot redirect the connection (no
  rebinding); redirects are never followed by the clients built here.

If the operator routes outbound traffic through an HTTP(S) proxy with the standard ``HTTPS_PROXY`` /
``ALL_PROXY`` / ``NO_PROXY`` variables, the request goes to that proxy instead: the proxy resolves the
name, so enforcing the allowlist is then the proxy's job (docs/security.md). Only fixed, operator-set
hosts use this module; the optional AI layer has its own policy for configurable base URLs
(note 04 R5).

:func:`read_capped` reads a streamed response body up to a limit of **decoded** bytes (httpx
decompresses gzip transparently, so counting raw bytes would let a small compressed body inflate in
memory; note 03 §9 B6).
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import urllib.request
from typing import Callable, Literal

import httpx2

log = logging.getLogger("kidney_health.egress")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], list[str]]
AddressClass = Literal["global", "private", "denied"]

# Cloud metadata services (AWS/GCP/Azure/OpenStack, ECS task metadata, AWS IPv6, Alibaba Cloud).
METADATA_ADDRESSES: frozenset[IPAddress] = frozenset(
    ipaddress.ip_address(a) for a in ("169.254.169.254", "169.254.170.2", "fd00:ec2::254", "100.100.100.200")
)
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_IPV4_COMPATIBLE = ipaddress.ip_network("::/96")
_THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")
DEFAULT_PORTS = {"http": 80, "https": 443}


class BlockedAddress(httpx2.ConnectError):
    """The host resolved to an address this server must not connect to (or did not resolve)."""


class ResponseTooLarge(Exception):
    """The response body is larger than the caller's limit (counted after decompression)."""


def embedded_ipv4(ip: IPAddress) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address carries (mapped, 6to4, Teredo client, NAT64, compatible), if any."""
    if not isinstance(ip, ipaddress.IPv6Address):
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if any(ip in net for net in _NAT64) or (ip in _IPV4_COMPATIBLE and int(ip) > 1):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _kubernetes_api_addresses() -> set[IPAddress]:
    out: set[IPAddress] = set()
    raw = os.environ.get("KUBERNETES_SERVICE_HOST", "")
    try:
        out.add(ipaddress.ip_address(raw.strip("[]")))
    except ValueError:
        pass
    return out


def classify_address(ip: IPAddress | str) -> AddressClass:
    """``global`` (may be contacted), ``private`` (only for an operator-configured host) or ``denied``."""
    address = ipaddress.ip_address(ip) if isinstance(ip, str) else ip
    # An IPv6 form that carries an IPv4 address is judged by that IPv4 address (the outer prefixes,
    # such as NAT64's 64:ff9b::/96, are not global themselves).
    inner = embedded_ipv4(address)
    candidates: list[IPAddress] = [address] if inner is None else [inner]
    if address in METADATA_ADDRESSES:
        return "denied"
    k8s = _kubernetes_api_addresses()
    verdict: AddressClass = "global"
    for a in candidates:
        if a in METADATA_ADDRESSES or a in k8s:
            return "denied"
        if a.is_loopback:  # before is_reserved: IPv6 ::1 sits in the reserved ::/8 block
            verdict = "private"
            continue
        if (
            a.is_unspecified
            or a.is_multicast
            or a.is_reserved
            or a.is_link_local
            or (isinstance(a, ipaddress.IPv4Address) and a in _THIS_NETWORK)
        ):
            return "denied"
        if not a.is_global:
            verdict = "private"
    return verdict


def system_resolver(host: str, port: int) -> list[str]:
    """Every address ``host`` resolves to (``socket.getaddrinfo``, TCP)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]  # drop an IPv6 zone id
        if address not in out:
            out.append(address)
    return out


def env_proxy_for(url: httpx2.URL) -> str | None:
    """The proxy the standard environment variables name for ``url`` (honouring ``NO_PROXY``), or ``None``."""
    proxies = urllib.request.getproxies_environment()
    if not proxies:
        return None
    host = url.host
    try:
        if urllib.request.proxy_bypass_environment(host, proxies):
            return None
    except Exception:  # a malformed NO_PROXY entry: fall back to using the proxy
        pass
    return proxies.get(url.scheme) or proxies.get("all")


class CheckedTransport(httpx2.BaseTransport):
    """An ``httpx2`` transport that resolves, checks and pins every request's address."""

    def __init__(
        self,
        *,
        allow_private: bool = False,
        resolver: Resolver | None = None,
        use_env_proxy: bool = True,
        direct: httpx2.BaseTransport | None = None,
        proxied: Callable[[str], httpx2.BaseTransport] | None = None,
    ) -> None:
        self.allow_private = allow_private
        self._resolve = resolver or system_resolver
        self._use_env_proxy = use_env_proxy
        self._direct = direct
        self._proxied_factory = proxied
        self._proxied: dict[str, httpx2.BaseTransport] = {}

    def _direct_transport(self) -> httpx2.BaseTransport:
        if self._direct is None:
            self._direct = httpx2.HTTPTransport(trust_env=False)
        return self._direct

    def _proxy_transport(self, proxy: str) -> httpx2.BaseTransport:
        transport = self._proxied.get(proxy)
        if transport is None:
            factory = self._proxied_factory or (lambda p: httpx2.HTTPTransport(proxy=p, trust_env=False))
            transport = self._proxied[proxy] = factory(proxy)
        return transport

    def checked_addresses(self, host: str, port: int) -> list[IPAddress]:
        """The addresses ``host`` resolves to, all allowed; raises :class:`BlockedAddress` otherwise."""
        try:
            raw = self._resolve(host, port)
        except (OSError, UnicodeError) as exc:
            raise BlockedAddress(f"dns_failed: {host} could not be resolved") from exc
        addresses: list[IPAddress] = []
        for item in raw:
            try:
                addresses.append(ipaddress.ip_address(item))
            except ValueError:
                raise BlockedAddress(f"dns_failed: {host} resolved to a malformed address") from None
        if not addresses:
            raise BlockedAddress(f"dns_failed: {host} has no address")
        for address in addresses:
            verdict = classify_address(address)
            if verdict == "denied" or (verdict == "private" and not self.allow_private):
                log.warning("refused an outbound request to %s: it resolves to a %s address", host, verdict)
                raise BlockedAddress(f"blocked_address: {host} resolves to an address this server does not contact")
        return addresses

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        url = request.url
        if url.scheme not in DEFAULT_PORTS:
            raise BlockedAddress(f"blocked_address: scheme {url.scheme!r} is not allowed")
        if self._use_env_proxy:
            proxy = env_proxy_for(url)
            if proxy:
                return self._proxy_transport(proxy).handle_request(request)
        host = url.raw_host.decode("ascii").lower()  # the IDNA form DNS and SNI use (``url.host`` is Unicode)
        port = url.port or DEFAULT_PORTS[url.scheme]
        address = self.checked_addresses(host, port)[0]
        if str(address) != host:
            request.url = url.copy_with(host=str(address))
            if url.scheme == "https":
                request.extensions = {**request.extensions, "sni_hostname": host}
        return self._direct_transport().handle_request(request)

    def close(self) -> None:
        for transport in [self._direct, *self._proxied.values()]:
            if transport is not None:
                transport.close()
        self._proxied.clear()


def read_capped(response: httpx2.Response, limit: int) -> bytes:
    """The decoded body of a streamed ``response``, or :class:`ResponseTooLarge` beyond ``limit`` bytes."""
    declared = response.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > limit and not response.headers.get("Content-Encoding"):
        raise ResponseTooLarge(f"declared {declared} bytes")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > limit:
            raise ResponseTooLarge(f"more than {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)

