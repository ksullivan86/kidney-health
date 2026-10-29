"""The pairing link of the iPhone app (design note 15 §4.3; ``app/pairing.py``): what the QR code that comes with a new device token holds.

Covered: the link is built only for an ``https://`` address the app can take, and reads back as what it was made from; the reading
refuses every link the server would not make (``tests/data/pairing_vectors.json``, replayed by ``ios/KidneyHealthCore``); the vectors
are fresh; ``POST /api/me/tokens`` returns ``pair_url`` for a device token only, built from ``PUBLIC_URL`` or the request's own
address. The QR code on the page is in ``tests/test_push_ui.py``; the app's side is in ``tests/test_ios_app.py``.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app import brand, pairing
from app.main import create_app
from conftest import TestClient, make_settings, sign_in
from test_api_tokens import make, switch
from test_push import make_device, push_switch

DATA = Path(__file__).resolve().parent / "data"
TOKEN = brand.DEVICE_TOKEN_PREFIX + "A" * 43


def test_the_link_holds_the_version_the_address_and_the_token() -> None:
    made = pairing.link("https://kidney.example.org", TOKEN)
    assert made == (f"{brand.PAIRING_SCHEME}://pair?v=1&server=https%3A%2F%2Fkidney.example.org&token={TOKEN}")
    parts = urlsplit(made)
    assert parse_qs(parts.query) == {"v": ["1"], "server": ["https://kidney.example.org"], "token": [TOKEN]}
    assert pairing.parse(made) == ("https://kidney.example.org", TOKEN)
    assert pairing.parse(pairing.link("https://example.org:8443", TOKEN) or "") == ("https://example.org:8443", TOKEN)


@pytest.mark.parametrize("server", ["http://kidney.example.org", "https://kidney.example.org/", "https://kidney.example.org/kidney",
                                    "https://[2001:db8::1]", "https://example.org:0", "https://example.org:65536", "https://",
                                    "https://ana@example.org", "https://kidney.example.org?x=1"])
def test_no_link_for_an_address_the_app_cannot_take(server: str) -> None:
    assert pairing.link(server, TOKEN) is None


def test_no_link_for_anything_but_a_device_token() -> None:
    for token in (brand.ASSISTANT_TOKEN_PREFIX + "A" * 43, TOKEN[:-1], TOKEN + "A", TOKEN[:-1] + "="):
        assert pairing.link("https://kidney.example.org", token) is None, token


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_pairing_vectors", DATA / "gen_pairing_vectors.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_vectors_are_fresh() -> None:
    assert (DATA / "pairing_vectors.json").read_text(encoding="utf-8") == _generator().render(), (
        "tests/data/pairing_vectors.json is stale: app/pairing.py changed. Run `python3 tests/data/gen_pairing_vectors.py`, then "
        "`swift test --package-path ios/KidneyHealthCore`.")


def test_the_vectors_refuse_the_ways_a_hostile_code_could_try() -> None:
    vectors = json.loads((DATA / "pairing_vectors.json").read_text(encoding="utf-8"))
    refused = [c["link"] for c in vectors["parse_cases"] if c.get("refused")]
    assert len(refused) >= 40
    joined = "\n".join(refused)
    for sign in ("#", "&server=https%3A%2F%2Fevil.example", "http%3A%2F%2F", "%2Fkidney.example.org", "v=2", "kha_", "%40"):
        assert sign in joined, sign
    for case in vectors["parse_cases"]:
        got = pairing.parse(case["link"])
        assert (got is None) == bool(case.get("refused")), case["link"]


# --------------------------------------------------------------------------- the route


def device_switches(client: TestClient) -> None:
    push_switch(client, True)
    switch(client, True)


def test_a_device_token_comes_with_its_pairing_link_from_public_url(tmp_path: Any, foods_json: Any) -> None:
    settings = make_settings(tmp_path, foods_json, public_url="https://food.example.org")
    with TestClient(create_app(settings), base_url="https://food.example.org") as c:
        sign_in(c)
        device_switches(c)
        made = make_device(c)
        assert pairing.parse(made["pair_url"]) == ("https://food.example.org", made["token"])
        listed = c.get("/api/me/tokens", params={"family": "device"}).json()["tokens"]
        assert listed and all("pair_url" not in t and "token" not in t for t in listed)  # shown once, like the token


def test_without_public_url_the_link_uses_the_address_the_page_came_from(tmp_path: Any, foods_json: Any) -> None:
    settings = make_settings(tmp_path, foods_json, allowed_hosts=("kidney.home.example",))
    with TestClient(create_app(settings), base_url="https://kidney.home.example:8443") as c:
        sign_in(c)
        device_switches(c)
        made = make_device(c)
        assert pairing.parse(made["pair_url"]) == ("https://kidney.home.example:8443", made["token"])


def test_a_plain_http_server_gets_no_link_and_an_assistant_token_never_has_one(client: TestClient) -> None:
    device_switches(client)
    assert make_device(client)["pair_url"] is None  # the test server is http://testserver
    assert "pair_url" not in make(client)
