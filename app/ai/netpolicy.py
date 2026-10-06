"""Where the AI client may connect (note 04 R5 and §9 A5; OWASP SSRF cheat sheet). Pure, no I/O.

A provider's base URL is configurable, so it is an SSRF path: an admin could point it at the cloud
metadata service, a LAN admin panel or the Kubernetes API, and a person (with
``ai.allow_user_base_url``) at anything public. The rules:

1. **Parse** (:func:`parse_base_url`): ``https`` (``http`` only for hosts in ``AI_PRIVATE_HOSTS``); no
   user info, query or fragment; a path of at most 100 characters made of plain segments (no ``..``,
   no percent-encoding) that ends in ``/v1`` (``/api/v1``, ``/p/<profile>/v1`` …); the host
   IDNA-encoded; a host whose last label is numeric must be a strict dotted-quad IPv4 address, so
   ``2130706433``, ``0x7f.1``, ``127.1`` and ``0177.0.0.1`` are refused (WHATWG would read them as IPs).
2. **Classify every resolved address** (:func:`classify`), judging an IPv6 address that carries an
   IPv4 address (mapped, 6to4, Teredo, NAT64 ``64:ff9b::/96`` and ``64:ff9b:1::/48``, IPv4-compatible
   ``::/96``) by that IPv4 address (:func:`app.egress.embedded_ipv4`):

   * **always denied**: unspecified, multicast, broadcast and reserved addresses, the cloud metadata
     addresses (``169.254.169.254``, ``169.254.170.2``, ``fd00:ec2::254``, ``100.100.100.200``), the
     Kubernetes API service address, the addresses in ``AI_DENY_CIDRS`` (§9 A5 b: the instance's own
     WAN address) and this server's own port on loopback;
   * **global**: allowed;
   * **private** (RFC 1918, loopback, CGNAT, ULA, link-local such as ``169.254.1.2`` =
     ``host.containers.internal`` on rootless Podman): allowed only for a **shared** provider whose
     ``host:port`` (or ``ip:port``, or a containing CIDR) is listed in ``AI_PRIVATE_HOSTS``.

3. **A person's own URL** (scope ``user``): https on port 443 to global addresses only;
   ``AI_PRIVATE_HOSTS`` never applies.

There is no wildcard and no "allow all private" switch: ``*`` and ``/0`` networks are refused, and the
retired ``ALLOW_PRIVATE_AI_HOSTS`` stops the server at start-up (``app/config.py``).
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Iterable, Literal
from urllib.parse import urlsplit

from ..egress import METADATA_ADDRESSES, embedded_ipv4

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
Scope = Literal["shared", "user"]
Verdict = Literal["global", "private", "denied"]

# Coarse error categories (R5 step 6). Bodies from user-configured URLs are never echoed, so these
# words are all a caller learns about a failed request.
ERROR_CATEGORIES: tuple[str, ...] = (
    "invalid_url", "dns_failed", "blocked_address", "connect_failed", "timeout",
    "http_401", "http_403", "http_404", "http_429", "http_4xx", "http_5xx", "invalid_response",
)

MAX_PATH_CHARS = 100
DEFAULT_PORTS = {"http": 80, "https": 443}
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")
_LABEL = re.compile(r"^[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?$")
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$", re.IGNORECASE)
_BROADCAST = ipaddress.IPv4Address("255.255.255.255")
_THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")


class PolicyError(ValueError):
    """A URL or address the AI client must not use. ``category`` is one of :data:`ERROR_CATEGORIES`;
    the message is for logs and the admin form and never contains a response body."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


# --------------------------------------------------------------------------- #
# Base URLs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BaseUrl:
    """A checked base URL. ``host`` is lower-case ASCII (IDNA) or an IP literal without brackets."""

    scheme: Literal["http", "https"]
    host: str
    port: int
    path: str  # "/v1", "/api/v1", "/p/kidney/v1" (no trailing slash)
    ip: IPAddress | None = None  # set when the host is an IP literal

    @property
    def netloc(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        if self.port == DEFAULT_PORTS[self.scheme]:
            return host
        return f"{host}:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.netloc}{self.path}"

    @property
    def host_port(self) -> str:
        """``host:port`` as ``AI_PRIVATE_HOSTS`` entries name it (the consent sheet's "destination host")."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def display_host(self) -> str:
        """What a person is told the data goes to: the host, plus the port when it is not the default."""
        return self.netloc

    def endpoint(self, suffix: str) -> str:
        """``{base}/{suffix}`` (``chat/completions``, ``models``, ``toolsets``)."""
        return f"{self.url}/{suffix.lstrip('/')}"


def _idna_host(host: str) -> str:
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise PolicyError("invalid_url", "the host name is not a valid internationalised domain name") from None
    ascii_host = ascii_host.rstrip(".")
    if not ascii_host or len(ascii_host) > 253:
        raise PolicyError("invalid_url", "the host name is empty or too long")
    for label in ascii_host.split("."):
        if not _LABEL.match(label):
            raise PolicyError("invalid_url", f"the host name has an invalid label {label[:20]!r}")
    return ascii_host


def parse_base_url(raw: str) -> BaseUrl:
    """Check ``raw`` against rule 1 and return its parts (:class:`PolicyError` ``invalid_url`` otherwise)."""
    if not isinstance(raw, str):
        raise PolicyError("invalid_url", "the base URL must be text")
    text = raw.strip()
    if not text or len(text) > 300 or any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise PolicyError("invalid_url", "the base URL must be one line without spaces, at most 300 characters")
    if "\\" in text:
        raise PolicyError("invalid_url", "the base URL must not contain backslashes")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise PolicyError("invalid_url", "the base URL has an invalid port or host") from None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise PolicyError("invalid_url", "the base URL must start with https:// (or http:// for a private host)")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise PolicyError("invalid_url", "the base URL must not contain a user name or password")
    if parts.query or parts.fragment or "?" in text or "#" in text:
        raise PolicyError("invalid_url", "the base URL must not contain a ?query or #fragment")
    raw_host = parts.hostname or ""
    if not raw_host:
        raise PolicyError("invalid_url", "the base URL has no host")
    if "%" in raw_host:
        raise PolicyError("invalid_url", "IPv6 zone ids and percent-encoded hosts are not allowed")

    ip: IPAddress | None = None
    if parts.netloc.split("@")[-1].startswith("["):
        try:
            ip = ipaddress.IPv6Address(raw_host)
        except ValueError:
            raise PolicyError("invalid_url", "the bracketed host is not an IPv6 address") from None
        host = str(ip)
    else:
        last = raw_host.rstrip(".").rsplit(".", 1)[-1]
        if _NUMERIC_LABEL.match(last):
            # Numeric-looking: only a strict dotted quad is accepted (no decimal, octal, hex or short forms).
            if not re.fullmatch(r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}", raw_host):
                raise PolicyError("invalid_url", "a numeric host must be a plain dotted IPv4 address such as 192.0.2.10")
            ip = ipaddress.IPv4Address(raw_host)
            host = str(ip)
        else:
            host = _idna_host(raw_host)

    path = parts.path or ""
    if len(path) > MAX_PATH_CHARS:
        raise PolicyError("invalid_url", f"the base URL path is longer than {MAX_PATH_CHARS} characters")
    if "%" in path:
        raise PolicyError("invalid_url", "the base URL path must not be percent-encoded")
    segments = [s for s in path.strip("/").split("/")] if path.strip("/") else []
    for s in segments:
        if s in (".", "..") or not _SEGMENT.match(s):
            raise PolicyError("invalid_url", "the base URL path may only contain plain segments such as /api/v1")
    if not segments or segments[-1] != "v1":
        raise PolicyError("invalid_url", "the base URL must end in /v1 (for example https://api.openai.com/v1)")
    return BaseUrl(
        scheme=scheme,  # type: ignore[arg-type]
        host=host,
        port=port if port is not None else DEFAULT_PORTS[scheme],
        path="/" + "/".join(segments),
        ip=ip,
    )


# --------------------------------------------------------------------------- #
# AI_PRIVATE_HOSTS and AI_DENY_CIDRS
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PrivateHosts:
    """Parsed ``AI_PRIVATE_HOSTS``: names with ports, addresses with ports, and networks."""

    names: frozenset[tuple[str, int]] = frozenset()
    addresses: frozenset[tuple[IPAddress, int]] = frozenset()
    networks: tuple[IPNetwork, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.names or self.addresses or self.networks)

    def allows_name(self, host: str, port: int) -> bool:
        return (host.lower(), port) in self.names

    def allows_address(self, ip: IPAddress, port: int) -> bool:
        inner = embedded_ipv4(ip)
        for candidate in (ip, inner) if inner is not None else (ip,):
            if (candidate, port) in self.addresses:
                return True
            if any(candidate.version == net.version and candidate in net for net in self.networks):
                return True
        return False

    def entries(self) -> list[str]:
        """Canonical text of every entry (Settings → Admin shows them read-only)."""
        out = [f"{h}:{p}" for h, p in sorted(self.names)]
        out += [f"[{a}]:{p}" if a.version == 6 else f"{a}:{p}" for a, p in sorted(self.addresses, key=lambda x: (x[0].version, int(x[0]), x[1]))]
        out += [str(n) for n in self.networks]
        return out


def _split(raw: str | Iterable[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [p for p in re.split(r"[,\s]+", raw) if p]
    out: list[str] = []
    for item in raw:
        out += _split(item)
    return out


def _port(text: str, entry: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise PolicyError("invalid_url", f"AI_PRIVATE_HOSTS entry {entry!r} needs a port between 1 and 65535")
    return int(text)


def parse_private_hosts(raw: str | Iterable[str] | None) -> PrivateHosts:
    """``host:port``, ``ip:port``, ``[ipv6]:port`` or a CIDR network, separated by commas or spaces.

    Refused: ``*``, a bare host without a port, a ``/0`` network and anything that does not parse
    (:class:`PolicyError`; the server does not start).
    """
    names: set[tuple[str, int]] = set()
    addresses: set[tuple[IPAddress, int]] = set()
    networks: list[IPNetwork] = []
    for entry in _split(raw):
        if "*" in entry:
            raise PolicyError("invalid_url", "AI_PRIVATE_HOSTS has no wildcard; list each host:port (for example ollama:11434)")
        if "/" in entry:
            try:
                net = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                raise PolicyError("invalid_url", f"AI_PRIVATE_HOSTS entry {entry!r} is not a valid network") from None
            if net.prefixlen == 0:
                raise PolicyError("invalid_url", f"AI_PRIVATE_HOSTS entry {entry!r} would allow every address")
            networks.append(net)
            continue
        if entry.startswith("["):
            match = re.fullmatch(r"\[([0-9A-Fa-f:.]+)\]:(\d+)", entry)
            if not match:
                raise PolicyError("invalid_url", f"AI_PRIVATE_HOSTS entry {entry!r} must look like [fd00::5]:11434")
            try:
                addresses.add((ipaddress.IPv6Address(match.group(1)), _port(match.group(2), entry)))
            except ValueError:
                raise PolicyError("invalid_url", f"AI_PRIVATE_HOSTS entry {entry!r} is not an IPv6 address") from None
            continue
        if entry.count(":") != 1:
            raise PolicyError("invalid_url", f"AI_PRIVATE_HOSTS entry {entry!r} needs a port, for example ollama:11434")
        host, port_text = entry.rsplit(":", 1)
        port = _port(port_text, entry)
        last = host.rstrip(".").rsplit(".", 1)[-1]
        if _NUMERIC_LABEL.match(last):
            try:
                addresses.add((ipaddress.IPv4Address(host), port))
            except ValueError:
                raise PolicyError("invalid_url", f"AI_PRIVATE_HOSTS entry {entry!r} is not a dotted IPv4 address") from None
            continue
        names.add((_idna_host(host), port))
    return PrivateHosts(frozenset(names), frozenset(addresses), tuple(networks))


def parse_deny_cidrs(raw: str | Iterable[str] | None) -> tuple[IPNetwork, ...]:
    """``AI_DENY_CIDRS``: addresses or networks no AI call may reach, in any scope (§9 A5 b)."""
    out: list[IPNetwork] = []
    for entry in _split(raw):
        try:
            out.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            raise PolicyError("invalid_url", f"AI_DENY_CIDRS entry {entry!r} is not an IP address or network") from None
    return tuple(out)


# --------------------------------------------------------------------------- #
# The policy
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NetPolicy:
    private_hosts: PrivateHosts = field(default_factory=PrivateHosts)
    deny: tuple[IPNetwork, ...] = ()
    kubernetes_api: frozenset[IPAddress] = frozenset()
    self_ports: frozenset[int] = frozenset()  # this server's listen port(s): refused on loopback
    proxy: str | None = None  # AI_HTTP_PROXY: user base URLs are off, the proxy resolves public names

    def with_self_port(self, port: int | None) -> "NetPolicy":
        if not port or port in self.self_ports:
            return self
        return NetPolicy(self.private_hosts, self.deny, self.kubernetes_api, self.self_ports | {int(port)}, self.proxy)


def classify(ip: IPAddress, policy: NetPolicy | None = None) -> Verdict:
    """``global``, ``private`` (allowlistable) or ``denied`` for one address (rule 2)."""
    policy = policy or NetPolicy()
    inner = embedded_ipv4(ip)
    judged: list[IPAddress] = [ip] if inner is None else [inner]
    if ip in METADATA_ADDRESSES or ip in policy.kubernetes_api:
        return "denied"
    for net in policy.deny:
        if any(a.version == net.version and a in net for a in (ip, *judged)):
            return "denied"
    verdict: Verdict = "global"
    for a in judged:
        if a in METADATA_ADDRESSES or a in policy.kubernetes_api:
            return "denied"
        if a.is_loopback:  # before is_reserved: ::1 sits in the reserved ::/8 block
            verdict = "private"
            continue
        if a.is_link_local:  # 169.254.0.0/16 and fe80::/10: host.containers.internal on rootless Podman
            verdict = "private"
            continue
        if (
            a.is_unspecified
            or a.is_multicast
            or a.is_reserved
            or a == _BROADCAST
            or (isinstance(a, ipaddress.IPv4Address) and a in _THIS_NETWORK)
        ):
            return "denied"
        if not a.is_global:
            verdict = "private"
    return verdict


def check_url(url: BaseUrl, scope: Scope, policy: NetPolicy) -> None:
    """Rules that need no DNS: scheme, port and IP-literal hosts for ``scope`` (:class:`PolicyError`)."""
    if scope == "user":
        if policy.proxy:
            raise PolicyError("blocked_address", "personal AI servers are switched off on this server (AI_HTTP_PROXY is set)")
        if url.scheme != "https" or url.port != 443:
            raise PolicyError("blocked_address", "a personal AI server must use https on port 443")
        if url.ip is not None and classify(url.ip, policy) != "global":
            raise PolicyError("blocked_address", "a personal AI server must have a public address")
        return
    if url.ip is not None:
        verdict = classify(url.ip, policy)
        if verdict == "denied":
            raise PolicyError("blocked_address", "this address is never contacted (metadata, reserved or denied)")
        if verdict == "private" and not policy.private_hosts.allows_address(url.ip, url.port):
            raise PolicyError("blocked_address", f"{url.host_port} is private; add it to AI_PRIVATE_HOSTS to use it")
    if url.scheme == "http" and not may_use_http(url, policy):
        raise PolicyError("blocked_address", f"http:// is only allowed for hosts in AI_PRIVATE_HOSTS; use https for {url.host_port}")


def may_use_http(url: BaseUrl, policy: NetPolicy) -> bool:
    """Plain http is for allowlisted private hosts only (a name entry, an address entry or a CIDR)."""
    hosts = policy.private_hosts
    if url.ip is not None:
        return hosts.allows_address(url.ip, url.port)
    return hosts.allows_name(url.host, url.port) or bool(hosts.networks)


def check_address(url: BaseUrl, ip: IPAddress, scope: Scope, policy: NetPolicy) -> None:
    """Rule 2 and 3 for one resolved address of ``url`` (:class:`PolicyError` ``blocked_address``)."""
    verdict = classify(ip, policy)
    if verdict == "denied":
        raise PolicyError("blocked_address", f"{url.host} resolves to an address that is never contacted")
    inner = embedded_ipv4(ip) or ip
    if inner.is_loopback and url.port in policy.self_ports:
        raise PolicyError("blocked_address", "the AI server cannot be this app itself")
    if scope == "user":
        if verdict != "global":
            raise PolicyError("blocked_address", f"{url.host} resolves to a private address; a personal AI server must be public")
        return
    allowlisted = policy.private_hosts.allows_name(url.host, url.port) or policy.private_hosts.allows_address(ip, url.port)
    if verdict == "private" and not allowlisted:
        raise PolicyError("blocked_address", f"{url.host_port} resolves to a private address; add it to AI_PRIVATE_HOSTS")
    if url.scheme == "http" and not allowlisted:
        raise PolicyError("blocked_address", f"http:// is only allowed for hosts in AI_PRIVATE_HOSTS ({url.host_port} is not)")


def check_addresses(url: BaseUrl, addresses: Iterable[str | IPAddress], scope: Scope, policy: NetPolicy) -> list[IPAddress]:
    """Every address must pass (one bad DNS answer refuses the call); returns them parsed."""
    parsed: list[IPAddress] = []
    for item in addresses:
        try:
            ip = item if isinstance(item, (ipaddress.IPv4Address, ipaddress.IPv6Address)) else ipaddress.ip_address(str(item).split("%", 1)[0])
        except ValueError:
            raise PolicyError("dns_failed", f"{url.host} resolved to a malformed address") from None
        parsed.append(ip)
    if not parsed:
        raise PolicyError("dns_failed", f"{url.host} has no address")
    for ip in parsed:
        check_address(url, ip, scope, policy)
    return parsed


def kubernetes_api_addresses(env_host: str | None) -> frozenset[IPAddress]:
    """``KUBERNETES_SERVICE_HOST`` as an address set (empty outside Kubernetes)."""
    try:
        return frozenset({ipaddress.ip_address((env_host or "").strip("[]"))})
    except ValueError:
        return frozenset()


KUBERNETES_NAMES = ("kubernetes", "kubernetes.default", "kubernetes.default.svc")


def check_host_name(url: BaseUrl) -> None:
    """The Kubernetes API by name (``kubernetes.default.svc*``) is refused before any lookup."""
    host = url.host
    if host in KUBERNETES_NAMES or host.startswith("kubernetes.default.svc"):
        raise PolicyError("blocked_address", "the Kubernetes API is never contacted")
