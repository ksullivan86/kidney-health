"""The SSRF-checked transport for the server's own outbound calls (USDA, Open Food Facts)."""
from __future__ import annotations

import gzip

import httpx2
import pytest

from app import egress
from app.egress import BlockedAddress, CheckedTransport, classify_address


@pytest.mark.parametrize("address, expected", [
    ("8.8.8.8", "global"), ("2606:4700::1111", "global"), ("::ffff:8.8.8.8", "global"),
    ("10.0.0.1", "private"), ("172.16.5.4", "private"), ("192.168.1.10", "private"), ("127.0.0.1", "private"),
    ("::1", "private"), ("100.64.0.1", "private"), ("fd12:3456::1", "private"), ("::ffff:127.0.0.1", "private"),
    ("169.254.169.254", "denied"), ("169.254.170.2", "denied"), ("fd00:ec2::254", "denied"), ("100.100.100.200", "denied"),
    ("169.254.1.2", "denied"), ("fe80::1", "denied"), ("0.0.0.0", "denied"), ("0.1.2.3", "denied"), ("::", "denied"),
    ("224.0.0.1", "denied"), ("ff02::1", "denied"), ("255.255.255.255", "denied"), ("240.0.0.1", "denied"),
    # IPv4 carried inside IPv6 forms that ipaddress calls global (note 04 R5)
    ("::ffff:169.254.169.254", "denied"), ("64:ff9b::a9fe:a9fe", "denied"), ("64:ff9b:1::a9fe:a9fe", "denied"),
    ("::a9fe:a9fe", "denied"), ("2002:a9fe:a9fe::1", "denied"), ("64:ff9b::a00:1", "private"),
])
def test_classify(address: str, expected: str) -> None:
    assert classify_address(address) == expected


def test_kubernetes_api_address_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    assert classify_address("10.96.0.1") == "denied"
    assert classify_address("10.96.0.2") == "private"


class Capture(httpx2.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json={"ok": True})


def transport(addresses: list[str], **kwargs) -> tuple[CheckedTransport, Capture]:
    capture = Capture()
    return CheckedTransport(resolver=lambda host, port: addresses, direct=capture, use_env_proxy=False, **kwargs), capture


def test_connects_to_the_checked_address_with_the_original_host_and_sni() -> None:
    t, capture = transport(["2606:4700::6810:1"])
    with httpx2.Client(transport=t) as client:
        assert client.get("https://world.openfoodfacts.org/api/v3.4/product/1?fields=a").status_code == 200
    sent = capture.requests[0]
    assert sent.url.host == "2606:4700::6810:1" and sent.url.path == "/api/v3.4/product/1"
    assert sent.headers["Host"] == "world.openfoodfacts.org"
    assert sent.extensions["sni_hostname"] == "world.openfoodfacts.org"


@pytest.mark.parametrize("addresses", [["10.0.0.5"], ["127.0.0.1"], ["169.254.169.254"], ["8.8.8.8", "192.168.0.1"], ["8.8.8.8", "::ffff:169.254.169.254"]])
def test_every_resolved_address_must_be_allowed(addresses: list[str]) -> None:
    t, capture = transport(addresses)
    with httpx2.Client(transport=t) as client, pytest.raises(BlockedAddress):
        client.get("https://world.openfoodfacts.org/")
    assert capture.requests == []


def test_private_addresses_only_for_an_operator_configured_host() -> None:
    t, capture = transport(["192.168.1.20"], allow_private=True)
    with httpx2.Client(transport=t) as client:
        client.get("https://off.lan/api")
    assert capture.requests[0].url.host == "192.168.1.20"
    t, capture = transport(["169.254.169.254"], allow_private=True)
    with httpx2.Client(transport=t) as client, pytest.raises(BlockedAddress):
        client.get("https://off.lan/api")


def test_dns_failure_and_garbage() -> None:
    def fail(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    for resolver in (fail, lambda h, p: [], lambda h, p: ["not-an-ip"]):
        t = CheckedTransport(resolver=resolver, direct=Capture(), use_env_proxy=False)
        with httpx2.Client(transport=t) as client, pytest.raises(BlockedAddress) as info:
            client.get("https://world.openfoodfacts.org/")
        assert str(info.value).startswith("dns_failed")


def test_only_http_and_https() -> None:
    t, _ = transport(["8.8.8.8"])
    with pytest.raises(BlockedAddress):
        t.handle_request(httpx2.Request("GET", "ftp://example.org/x"))


def clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)


def test_env_proxy_is_used_when_the_operator_set_one(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("NO_PROXY", "localhost")
    used: list[str] = []
    capture = Capture()

    def proxied(proxy: str) -> httpx2.BaseTransport:
        used.append(proxy)
        return capture

    t = CheckedTransport(resolver=lambda h, p: ["10.0.0.1"], direct=Capture(), proxied=proxied)
    with httpx2.Client(transport=t) as client:
        client.get("https://world.openfoodfacts.org/x")
    assert used == ["http://proxy.internal:3128"]
    assert capture.requests[0].url.host == "world.openfoodfacts.org"  # the proxy resolves the name
    with httpx2.Client(transport=t) as client, pytest.raises(BlockedAddress):
        client.get("https://localhost/x")  # NO_PROXY: direct, and 10.0.0.1 is private


def test_no_proxy_means_a_direct_checked_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_proxy_env(monkeypatch)
    capture = Capture()
    t = CheckedTransport(resolver=lambda h, p: ["8.8.4.4"], direct=capture, proxied=lambda p: pytest.fail("no proxy expected"))
    with httpx2.Client(transport=t) as client:
        client.get("https://api.nal.usda.gov/fdc/v1/foods/search?query=1")
    assert capture.requests[0].url.host == "8.8.4.4"


def test_read_capped_counts_decoded_bytes() -> None:
    body = b"a" * 300_000
    compressed = gzip.compress(body)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"Content-Encoding": "gzip"}, content=compressed)

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        with client.stream("GET", "https://x.org/") as response:
            assert egress.read_capped(response, 400_000) == body
        with client.stream("GET", "https://x.org/") as response, pytest.raises(egress.ResponseTooLarge):
            egress.read_capped(response, 100_000)
