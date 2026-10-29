#!/usr/bin/env python3
"""Generate tests/data/pairing_vectors.json: the link in the QR code that pairs the iPhone app, for a native client.

    python3 tests/data/gen_pairing_vectors.py           # rewrite the file
    python3 tests/data/gen_pairing_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code (``app/pairing.py``) and replayed by the Swift package ``ios/KidneyHealthCore`` (``Pairing``,
design note 15 §4.3):

* ``constants``: the link's scheme, its fixed start and its version;
* ``link_cases``: an address and a token, and the link the server puts in the QR code (``null`` when it makes none);
* ``parse_cases``: a link, and the address and token the app reads from it, or ``refused``. The refused links are the ways a
  QR code made by someone else could try to get past the checks.

Needs nothing but the standard library and ``app/pairing.py``. No server is started.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "pairing_vectors.json"
sys.path.insert(0, str(ROOT))

from app import brand, pairing  # noqa: E402

TOKEN = brand.DEVICE_TOKEN_PREFIX + "Zm9vYmFyLWJhei1xdXV4LTAxMjM0NTY3ODlfLWFiY2Rl"[:43]
OTHER = brand.DEVICE_TOKEN_PREFIX + "_-" * 21 + "A"

SERVERS = [
    "https://kidney.example.org",
    "https://Kidney.Example.ORG",
    "https://example.org:8443",
    "https://192.168.1.20:8000",
    "https://my-home-server.local",
    "https://example.org:1",
    "https://example.org:65535",
    "http://kidney.example.org",
    "https://kidney.example.org/",
    "https://kidney.example.org/kidney",
    "https://[2001:db8::1]",
    "https://example.org:0",
    "https://example.org:65536",
    "https://example.org:",
    "https://ana@example.org",
    "https://",
    "kidney.example.org",
    "https://kidney.example.org?x=1",
    "https://kidney.example.org#top",
]
TOKENS = [TOKEN, OTHER, TOKEN[:-1], TOKEN + "A", "kha_" + TOKEN[4:], TOKEN[:10] + "+" + TOKEN[11:], " " + TOKEN]


def good(server: str = "https://kidney.example.org", token: str = TOKEN) -> str:
    made = pairing.link(server, token)
    assert made is not None
    return made


def refused_links() -> list[str]:
    base = good()
    scheme = brand.PAIRING_SCHEME
    query = base.split("?", 1)[1]
    enc_server = "https%3A%2F%2Fkidney.example.org"
    return [
        base.replace(f"{scheme}://", "https://", 1),          # another scheme
        base.replace(f"{scheme}://", f"{scheme}x://", 1),
        base.replace("://pair?", "://PAIR?", 1),               # the fixed part is exact
        base.replace("://pair?", "://pair/?", 1),              # a path
        base.replace("://pair?", "://pair:80?", 1),            # a port
        base.replace("://pair?", "://pair:?", 1),
        base.replace("://pair?", "://ana@pair?", 1),           # a user
        base.replace("://pair?", "://p%61ir?", 1),
        base.replace("://pair?", ":pair?", 1),
        f"{scheme}://pair",                                    # no query
        f"{scheme}://pair?",
        base + "#",                                            # a fragment, even an empty one
        base + "#x",
        base + "&v=1",                                         # a field twice
        base + "&token=" + OTHER,
        base + "&server=https%3A%2F%2Fevil.example",
        base + "&name=phone",                                  # a field more
        base + "&",                                            # an empty field
        f"{scheme}://pair?server={enc_server}&token={TOKEN}",  # a field missing
        f"{scheme}://pair?v=1&token={TOKEN}",
        f"{scheme}://pair?v=1&server={enc_server}",
        base.replace("v=1", "v=2", 1),                         # another version
        base.replace("v=1", "v=01", 1),
        base.replace("v=1", "v", 1),
        base.replace("v=1", "V=1", 1),                         # names are exact
        base.replace(enc_server, "https%3A%2F%2Fkidney.example.org%2F", 1),
        base.replace(enc_server, "http%3A%2F%2Fkidney.example.org", 1),
        base.replace(enc_server, "https%3A%2F%2Fevil.example%2Fkidney.example.org", 1),
        base.replace(enc_server, "https%3A%2F%2Fana%40kidney.example.org", 1),
        base.replace(enc_server, "https%3A%2F%2Fkidney.example.org%23x", 1),
        base.replace(enc_server, "https%3A%2F%2Fkidney.example.org%3Fx%3D1", 1),
        base.replace(enc_server, "https%3A%2F%2Fkidney%20example.org", 1),
        base.replace(enc_server, "https%3A%2F%2Fkidney+example.org", 1),
        base.replace(enc_server, "https%3A%2F%2Fkidney.example.org%zz", 1),
        base.replace(enc_server, "https%3A%2F%2Fkidn%C3%A9y.example.org", 1),
        base.replace(enc_server, "https%3A%2F%2F%5B2001%3Adb8%3A%3A1%5D", 1),
        base.replace(enc_server, "https%3A%2F%2Fexample.org%3A99999", 1),
        base.replace(TOKEN, TOKEN[:-1], 1),                    # not a device token
        base.replace(TOKEN, TOKEN + "A", 1),
        base.replace(TOKEN, "kha_" + TOKEN[4:], 1),
        base.replace(TOKEN, TOKEN[:-1] + "%3D", 1),
        base.replace(TOKEN, TOKEN[:-1] + "+", 1),
        base.replace(TOKEN, TOKEN + "%0A", 1),
        base.replace("token=", "token=%20", 1),
        " " + base,                                            # spaces or controls around it
        base + " ",
        base + "\n",
        base.replace("&", " &", 1),
        "",
        f"{scheme}://pair?{query}?",
    ]


def accepted_links() -> list[str]:
    base = good()
    scheme = brand.PAIRING_SCHEME
    enc_server = "https%3A%2F%2Fkidney.example.org"
    v, server, token = "v=1", f"server={enc_server}", f"token={TOKEN}"
    return [
        base,
        base.replace(f"{scheme}://", f"{scheme.upper()}://", 1),  # the scheme in any case
        f"{scheme}://pair?{token}&{server}&{v}",                 # any order
        f"{scheme}://pair?v=1&server=https://kidney.example.org&token={TOKEN}",  # not escaped
        f"{scheme}://pair?%76=1&{server}&{token}",               # an escaped name
        base.replace(TOKEN, "khd%5F" + TOKEN[4:], 1),             # an escaped token
        good("https://example.org:8443", OTHER),
        good("https://192.168.1.20:8000"),
    ]


def build() -> dict[str, Any]:
    links = [{"server": s, "token": t, "link": pairing.link(s, t)} for s in SERVERS for t in TOKENS[:2]]
    links += [{"server": SERVERS[0], "token": t, "link": pairing.link(SERVERS[0], t)} for t in TOKENS[2:]]
    parse: list[dict[str, Any]] = []
    for text in accepted_links() + refused_links():
        got = pairing.parse(text)
        parse.append({"link": text, "server": got[0], "token": got[1]} if got else {"link": text, "refused": True})
    assert sum("refused" not in c for c in parse) == len(accepted_links()), "an accepted case was refused or the reverse"
    for case in links:  # every link the server makes reads back as what it was made from
        if case["link"] is not None:
            assert pairing.parse(case["link"]) == (case["server"], case["token"]), case
    return {
        "about": "Made by tests/data/gen_pairing_vectors.py from app/pairing.py. Replayed by ios/KidneyHealthCore (Pairing). "
                 "Do not edit by hand.",
        "constants": {"scheme": brand.PAIRING_SCHEME, "start": f"://{pairing.HOST}?", "version": pairing.VERSION,
                      "fields": list(pairing.FIELDS), "token_prefix": brand.DEVICE_TOKEN_PREFIX},
        "link_cases": links,
        "parse_cases": parse,
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = ap.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_pairing_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
