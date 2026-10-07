"""The AI client's SSRF policy and pinned transport (note 04 R5, R11.3 and §9 A5). No network: the
resolver and the connection are fakes, and the fake connection records where it was told to go."""
from __future__ import annotations

import gzip
import ipaddress
import json
from typing import Any

import anyio
import httpx2
import pytest

from app.ai import netpolicy as N
from app.ai.transport import AiTransportError, PinnedTransport, send_json

PRIVATE = N.parse_private_hosts("ollama:11434, host.containers.internal:8643, 192.168.1.10:8643, [fd00::5]:11434, 10.20.0.0/16")
POLICY = N.NetPolicy(private_hosts=PRIVATE)


# --------------------------------------------------------------------------- #
# Base URL parsing (rule 1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url, host, port, path", [
    ("https://api.openai.com/v1", "api.openai.com", 443, "/v1"),
    ("https://openrouter.ai/api/v1/", "openrouter.ai", 443, "/api/v1"),
    ("http://ollama:11434/v1", "ollama", 11434, "/v1"),
    ("http://192.168.1.10:8643/p/kidney/v1", "192.168.1.10", 8643, "/p/kidney/v1"),
    ("https://[2001:db8::1]:8443/v1", "2001:db8::1", 8443, "/v1"),
    ("https://BÜCHER.example/v1", "xn--bcher-kva.example", 443, "/v1"),
    ("HTTPS://API.OpenAI.com:443/v1", "api.openai.com", 443, "/v1"),
])
def test_valid_base_urls(url, host, port, path):
    parsed = N.parse_base_url(url)
    assert (parsed.host, parsed.port, parsed.path) == (host, port, path)


@pytest.mark.parametrize("url", [
    "https://2130706433/v1",            # decimal IPv4
    "https://0x7f.1/v1",                # hex
    "https://0x7f000001/v1",
    "https://0177.0.0.1/v1",            # octal
    "https://127.1/v1",                 # short form
    "https://1.2.3.04/v1",              # leading zero
    "https://user:pw@api.openai.com/v1",
    "https://api.openai.com/v1?x=1",
    "https://api.openai.com/v1#frag",
    "https://api.openai.com/",          # must end in /v1
    "https://api.openai.com/v1/chat",
    "https://api.openai.com/a/../v1",
    "https://api.openai.com/%2e%2e/v1",
    "https://api.openai.com/v1%2F",
    "ftp://api.openai.com/v1",
    "file:///etc/passwd",
    "https:///v1",
    "https://[fe80::1%25eth0]/v1",      # zone id
    "https://api.openai.com:99999/v1",
    "https://exa mple.com/v1",
    "https://api.openai.com\\@evil/v1",
    "https://" + "a" * 64 + ".example/v1",  # label too long
    "https://x.example/" + "a/" * 60 + "v1",  # path too long
    "",
])
def test_invalid_base_urls(url):
    with pytest.raises(N.PolicyError) as info:
        N.parse_base_url(url)
    assert info.value.category == "invalid_url"


# --------------------------------------------------------------------------- #
# AI_PRIVATE_HOSTS / AI_DENY_CIDRS parsing
# --------------------------------------------------------------------------- #


def test_private_hosts_parse_names_addresses_and_networks():
    hosts = N.parse_private_hosts("ollama:11434,192.168.1.10:8643 [fd00::5]:11434\n10.0.0.0/8")
    assert hosts.allows_name("ollama", 11434) and not hosts.allows_name("ollama", 11435)
    assert hosts.allows_address(ipaddress.ip_address("192.168.1.10"), 8643)
    assert hosts.allows_address(ipaddress.ip_address("fd00::5"), 11434)
    assert hosts.allows_address(ipaddress.ip_address("10.9.9.9"), 1)
    assert hosts.allows_address(ipaddress.ip_address("::ffff:10.9.9.9"), 1)  # mapped form of an allowed address
    assert hosts.entries() == ["ollama:11434", "192.168.1.10:8643", "[fd00::5]:11434", "10.0.0.0/8"]
    assert not N.parse_private_hosts("") and not N.parse_private_hosts(None)


@pytest.mark.parametrize("raw", ["*", "ollama", "ollama:0", "ollama:70000", "0.0.0.0/0", "::/0", "300.1.1.1:80",
                                 "[nope]:80", "a:b:c", "10.0.0.0/33", "*.lan:80"])
def test_private_hosts_refuse_wildcards_and_garbage(raw):
    with pytest.raises(N.PolicyError):
        N.parse_private_hosts(raw)


def test_deny_cidrs():
    assert N.parse_deny_cidrs("203.0.113.7, 2001:db8::/32") == (
        ipaddress.ip_network("203.0.113.7/32"), ipaddress.ip_network("2001:db8::/32"))
    with pytest.raises(N.PolicyError):
        N.parse_deny_cidrs("not-an-ip")


# --------------------------------------------------------------------------- #
# Address classes (rule 2), table-driven
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("address, verdict", [
    ("8.8.8.8", "global"),
    ("2606:4700::1111", "global"),
    ("10.1.2.3", "private"),
    ("192.168.1.10", "private"),
    ("172.16.0.1", "private"),
    ("100.64.1.1", "private"),            # CGNAT
    ("127.0.0.1", "private"),
    ("::1", "private"),
    ("fd00::5", "private"),               # ULA
    ("169.254.1.2", "private"),           # host.containers.internal (pasta)
    ("fe80::1", "private"),
    ("169.254.169.254", "denied"),        # metadata
    ("169.254.170.2", "denied"),
    ("fd00:ec2::254", "denied"),
    ("100.100.100.200", "denied"),
    ("0.0.0.0", "denied"),
    ("0.1.2.3", "denied"),
    ("::", "denied"),
    ("224.0.0.1", "denied"),
    ("ff02::1", "denied"),
    ("255.255.255.255", "denied"),
    ("240.0.0.1", "denied"),
    ("::ffff:169.254.169.254", "denied"),  # IPv4-mapped
    ("::ffff:127.0.0.1", "private"),
    ("::ffff:8.8.8.8", "global"),
    ("64:ff9b::a9fe:a9fe", "denied"),      # NAT64 carrying the metadata address (§9 A5 a)
    ("64:ff9b:1::a9fe:a9fe", "denied"),
    ("::a9fe:a9fe", "denied"),             # IPv4-compatible
    ("64:ff9b::7f00:1", "private"),        # NAT64 loopback
    ("64:ff9b::808:808", "global"),
    ("2002:a9fe:a9fe::", "denied"),        # 6to4 carrying the metadata address
    ("2002:c0a8:010a::", "private"),       # 6to4 carrying 192.168.1.10
])
def test_classify(address, verdict):
    assert N.classify(ipaddress.ip_address(address)) == verdict


def test_kubernetes_api_and_deny_cidrs_are_denied():
    policy = N.NetPolicy(kubernetes_api=N.kubernetes_api_addresses("10.96.0.1"), deny=N.parse_deny_cidrs("203.0.113.0/24"))
    assert N.classify(ipaddress.ip_address("10.96.0.1"), policy) == "denied"
    assert N.classify(ipaddress.ip_address("203.0.113.9"), policy) == "denied"
    assert N.classify(ipaddress.ip_address("::ffff:203.0.113.9"), policy) == "denied"
    with pytest.raises(N.PolicyError):
        N.check_host_name(N.parse_base_url("https://kubernetes.default.svc.cluster.local/v1"))


# --------------------------------------------------------------------------- #
# Scope rules (rule 2 + 3)
# --------------------------------------------------------------------------- #


def _check(url: str, addresses: list[str], scope: str = "shared", policy: N.NetPolicy = POLICY) -> None:
    base = N.parse_base_url(url)
    N.check_url(base, scope, policy)  # type: ignore[arg-type]
    N.check_addresses(base, addresses, scope, policy)  # type: ignore[arg-type]


@pytest.mark.parametrize("url, addresses", [
    ("https://api.openai.com/v1", ["162.159.140.245", "2606:4700::6812:1"]),
    ("http://ollama:11434/v1", ["10.89.0.5"]),
    ("http://host.containers.internal:8643/v1", ["169.254.1.2"]),
    ("http://192.168.1.10:8643/v1", ["192.168.1.10"]),
    ("http://llama.lan:8080/v1", ["10.20.3.4"]),          # inside the allowlisted CIDR
    ("https://[fd00::5]:11434/v1", ["fd00::5"]),
])
def test_shared_scope_allows_public_and_allowlisted(url, addresses):
    _check(url, addresses)


@pytest.mark.parametrize("url, addresses", [
    ("http://api.openai.com/v1", ["162.159.140.245"]),          # http to a public, unlisted host
    ("https://ollama:11435/v1", ["10.89.0.5"]),                  # wrong port
    ("http://host.containers.internal:1234/v1", ["169.254.1.2"]),
    ("https://evil.example/v1", ["8.8.8.8", "10.0.0.1"]),        # one private answer refuses the call
    ("https://evil.example/v1", ["169.254.169.254"]),
    ("http://ollama:11434/v1", ["169.254.169.254"]),             # allowlisted name, metadata answer
    ("https://[::1]/v1", ["::1"]),
    ("https://localhost/v1", ["127.0.0.1"]),
    ("https://evil.example/v1", ["64:ff9b::a9fe:a9fe"]),
    ("https://evil.example/v1", ["::ffff:10.0.0.1"]),
    ("http://llama.lan:8080/v1", ["10.30.0.1"]),                 # outside the CIDR
])
def test_shared_scope_refusals(url, addresses):
    with pytest.raises(N.PolicyError) as info:
        _check(url, addresses)
    assert info.value.category == "blocked_address"


def test_host_containers_internal_needs_the_allowlist():
    with pytest.raises(N.PolicyError):
        _check("http://host.containers.internal:8643/v1", ["169.254.1.2"], policy=N.NetPolicy())
    _check("http://host.containers.internal:8643/v1", ["169.254.1.2"])


@pytest.mark.parametrize("url, addresses", [
    ("http://api.example.com/v1", ["93.184.215.14"]),       # http
    ("https://api.example.com:8443/v1", ["93.184.215.14"]),  # not 443
    ("https://10.0.0.5/v1", ["10.0.0.5"]),                   # private literal
    ("https://ollama:443/v1", ["10.89.0.5"]),                # allowlist never applies to people
    ("https://host.containers.internal/v1", ["169.254.1.2"]),
    ("https://api.example.com/v1", ["93.184.215.14", "127.0.0.1"]),
])
def test_user_scope_is_https_443_public_only(url, addresses):
    with pytest.raises(N.PolicyError):
        _check(url, addresses, scope="user")


def test_user_scope_public_https_is_fine_but_not_behind_a_proxy():
    _check("https://api.example.com/v1", ["93.184.215.14"], scope="user")
    with pytest.raises(N.PolicyError):
        _check("https://api.example.com/v1", ["93.184.215.14"], scope="user", policy=N.NetPolicy(proxy="http://proxy:3128"))


def test_own_port_on_loopback_is_refused_even_when_allowlisted():
    policy = N.NetPolicy(private_hosts=N.parse_private_hosts("127.0.0.1:8000"), self_ports=frozenset({8000}))
    with pytest.raises(N.PolicyError):
        _check("http://127.0.0.1:8000/v1", ["127.0.0.1"], policy=policy)


# --------------------------------------------------------------------------- #
# The pinned transport and send_json (rules 4–6)
# --------------------------------------------------------------------------- #


class Recorder:
    """The fake connection: records each request and answers with ``answer(request)``."""

    def __init__(self, answer=None):
        self.requests: list[httpx2.Request] = []
        self.answer = answer or (lambda r: httpx2.Response(200, json={"ok": True}))

    def transport(self) -> httpx2.MockTransport:
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            return self.answer(request)
        return httpx2.MockTransport(handler)


def _send(url: str, *, scope: str = "shared", policy: N.NetPolicy = POLICY, resolver=None, recorder: Recorder | None = None,
          proxied: Recorder | None = None, max_bytes: int = 262144, read_timeout: float = 5.0) -> Any:
    base = N.parse_base_url(url)
    recorder = recorder or Recorder()

    def factory(b, s, p):
        return PinnedTransport(b, s, p, resolver=resolver or (lambda h, port: ["93.184.215.14"]),
                               inner=recorder.transport(), proxied=proxied.transport() if proxied else None)

    async def run():
        return await send_json(base, scope, policy, method="POST", path="chat/completions", headers={"Authorization": "Bearer k"},
                               body={"x": 1}, read_timeout_s=read_timeout, max_bytes=max_bytes, transport_factory=factory)

    return anyio.run(run)


def test_requests_are_pinned_to_the_checked_address_with_host_and_sni():
    rec = Recorder()
    result = _send("https://api.example.com/v1", recorder=rec, resolver=lambda h, p: ["93.184.215.14", "2606:2800::1"])
    assert result.data == {"ok": True}
    request = rec.requests[0]
    assert request.url.host == "93.184.215.14" and request.url.path == "/v1/chat/completions"
    assert request.headers["Host"] == "api.example.com"
    assert request.extensions["sni_hostname"] == "api.example.com"
    assert request.headers["Accept-Encoding"] == "identity"
    assert json.loads(request.content) == {"x": 1}


def test_an_internationalised_base_url_is_pinned_by_its_ascii_form():
    """Review L2: httpx2's ``url.host`` is the Unicode form, so every request to an IDN base URL was refused
    as "outside the provider's base URL". The origin check, DNS and SNI now use the punycode."""
    rec = Recorder()
    asked: list[str] = []

    def resolver(h, p):  # noqa: ANN001, ANN202
        asked.append(h)
        return ["93.184.215.14"]

    result = _send("https://bücher.example/v1", recorder=rec, resolver=resolver)
    assert result.data == {"ok": True} and asked == ["xn--bcher-kva.example"]
    request = rec.requests[0]
    assert request.url.host == "93.184.215.14"
    assert request.headers["Host"] == "xn--bcher-kva.example"
    assert request.extensions["sni_hostname"] == "xn--bcher-kva.example"
    # Another IDN host is still outside the base URL.
    base = N.parse_base_url("https://bücher.example/v1")
    transport = PinnedTransport(base, "shared", POLICY, resolver=lambda h, p: ["93.184.215.14"], inner=Recorder().transport())

    async def other():
        async with httpx2.AsyncClient(transport=transport) as client:
            await client.get("https://bücherei.example/v1/models")

    with pytest.raises(AiTransportError) as info:
        anyio.run(other)
    assert info.value.category == "blocked_address"


def test_dns_rebinding_each_request_is_checked_again():
    answers = iter([["93.184.215.14"], ["169.254.169.254"]])
    resolver = lambda h, p: next(answers)  # noqa: E731
    _send("https://rebind.example/v1", resolver=resolver)
    with pytest.raises(AiTransportError) as info:
        _send("https://rebind.example/v1", resolver=resolver)
    assert info.value.category == "blocked_address"


def test_dns_failure_is_a_category():
    def boom(h, p):
        raise OSError("nope")
    with pytest.raises(AiTransportError) as info:
        _send("https://nowhere.example/v1", resolver=boom)
    assert info.value.category == "dns_failed"


@pytest.mark.parametrize("status, category", [(301, "invalid_response"), (302, "invalid_response"), (401, "http_401"),
                                              (403, "http_403"), (404, "http_404"), (429, "http_429"), (500, "http_5xx"),
                                              (503, "http_5xx"), (418, "http_4xx")])
def test_status_categories_and_redirects_are_not_followed(status, category):
    rec = Recorder(lambda r: httpx2.Response(status, headers={"Location": "http://169.254.169.254/", "Retry-After": "3"},
                                             json={"secret": "body"}))
    with pytest.raises(AiTransportError) as info:
        _send("https://api.example.com/v1", recorder=rec)
    assert info.value.category == category and len(rec.requests) == 1
    assert "secret" not in str(info.value)  # bodies are never echoed
    if status == 429:
        assert info.value.retry_after == 3.0


def test_non_json_and_oversized_answers_are_refused():
    rec = Recorder(lambda r: httpx2.Response(200, text="<html>hi</html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(AiTransportError) as info:
        _send("https://api.example.com/v1", recorder=rec)
    assert info.value.category == "invalid_response"
    big = json.dumps({"pad": "x" * 300_000})
    rec = Recorder(lambda r: httpx2.Response(200, text=big, headers={"Content-Type": "application/json"}))
    with pytest.raises(AiTransportError):
        _send("https://api.example.com/v1", recorder=rec)


def test_compressed_bombs_count_decoded_bytes():
    payload = gzip.compress(json.dumps({"pad": "0" * 1_000_000}).encode())
    assert len(payload) < 10_000
    rec = Recorder(lambda r: httpx2.Response(200, content=payload,
                                             headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}))
    with pytest.raises(AiTransportError) as info:
        _send("https://api.example.com/v1", recorder=rec)
    assert "AI_MAX_RESPONSE_BYTES" in str(info.value)


def test_timeouts_are_a_category():
    def slow(request):
        raise httpx2.ReadTimeout("slow", request=request)
    with pytest.raises(AiTransportError) as info:
        _send("https://api.example.com/v1", recorder=Recorder(slow))
    assert info.value.category == "timeout"


def test_connect_errors_are_a_category():
    def down(request):
        raise httpx2.ConnectError("refused", request=request)
    with pytest.raises(AiTransportError) as info:
        _send("https://api.example.com/v1", recorder=Recorder(down))
    assert info.value.category == "connect_failed"


def test_a_request_outside_the_base_origin_is_refused():
    base = N.parse_base_url("https://api.example.com/v1")
    transport = PinnedTransport(base, "shared", POLICY, resolver=lambda h, p: ["93.184.215.14"], inner=Recorder().transport())

    async def run():
        async with httpx2.AsyncClient(transport=transport) as client:
            await client.get("https://other.example/v1/models")

    with pytest.raises(AiTransportError):
        anyio.run(run)


def test_proxy_takes_public_hosts_and_private_hosts_stay_pinned():
    policy = N.NetPolicy(private_hosts=PRIVATE, proxy="http://proxy.internal:3128")
    direct, proxied = Recorder(), Recorder()
    _send("https://api.example.com/v1", policy=policy, recorder=direct, proxied=proxied)
    assert len(proxied.requests) == 1 and not direct.requests
    assert proxied.requests[0].url.host == "api.example.com"  # the proxy resolves public names
    _send("http://ollama:11434/v1", policy=policy, recorder=direct, proxied=proxied, resolver=lambda h, p: ["10.89.0.5"])
    assert direct.requests[0].url.host == "10.89.0.5"


def test_proxy_without_local_dns_still_refuses_names_that_resolve_badly():
    policy = N.NetPolicy(proxy="http://proxy.internal:3128")
    with pytest.raises(AiTransportError):
        _send("https://evil.example/v1", policy=policy, resolver=lambda h, p: ["10.0.0.1"], proxied=Recorder())

    def no_dns(h, p):
        raise OSError("no DNS in this container")
    proxied = Recorder()
    _send("https://api.example.com/v1", policy=policy, resolver=no_dns, proxied=proxied)
    assert len(proxied.requests) == 1
