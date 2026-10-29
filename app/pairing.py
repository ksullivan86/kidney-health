"""The pairing link of the iPhone app (design note 15 §4.3; guide ``docs/push.md``).

When a person makes a device token, Settings → Phone shortcuts shows it once as text and as a QR code. The QR code holds one link:

    kidneyhealthsync://pair?v=1&server=https%3A%2F%2Fkidney.example.org&token=khd_…

The iPhone's Camera opens the app with it. The app asks "Pair with kidney.example.org?" before it saves anything, so a QR code made
by someone else cannot quietly point the app at their server.

``link`` builds it; ``parse`` is the reference reading that ``ios/KidneyHealthCore`` (``Pairing.parse``) must match, checked by
``tests/data/pairing_vectors.json``. Both sides accept only what the builder makes, written the same way:

* the scheme (``brand.PAIRING_SCHEME``, in any case), then exactly ``://pair?``, and no ``#`` anywhere;
* the parameters ``v``, ``server`` and ``token``, once each and nothing else; ``v`` is ``1``;
* ``server`` is ``https://`` and a host of letters, digits, dots and hyphens, with an optional port from 1 to 65535: no path, no
  trailing slash, no user, no IPv6 literal;
* ``token`` is a device token: ``khd_`` and 43 base64url characters;
* the whole link is printable ASCII with no spaces.

A server whose address does not fit (plain HTTP, an IPv6 literal) gets no link: the page says to type the address in the app instead.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlencode

from . import brand

VERSION = "1"
HOST = "pair"
FIELDS = ("v", "server", "token")

_SERVER = re.compile(r"https://([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?")
_TOKEN = re.compile(re.escape(brand.DEVICE_TOKEN_PREFIX) + r"[A-Za-z0-9_-]{43}")
_PRINTABLE = re.compile(r"[\x21-\x7e]+")


def server_ok(server: str) -> bool:
    """True for an address the app can pair with: ``https://host`` or ``https://host:port``, nothing more."""
    m = _SERVER.fullmatch(server)
    return bool(m) and (m.group(2) is None or 1 <= int(m.group(2)) <= 65535)


def token_ok(token: str) -> bool:
    return bool(_TOKEN.fullmatch(token))


def link(server: str, token: str) -> str | None:
    """The link for the QR code, or None when the address or the token is not one the app accepts."""
    if not server_ok(server) or not token_ok(token):
        return None
    return f"{brand.PAIRING_SCHEME}://{HOST}?" + urlencode({"v": VERSION, "server": server, "token": token}, quote_via=quote, safe="")


def parse(text: str) -> tuple[str, str] | None:
    """``(server, token)`` from a pairing link, or None when it is not one, exactly as the app reads it."""
    scheme = brand.PAIRING_SCHEME
    if (not _PRINTABLE.fullmatch(text) or text[:len(scheme)].lower() != scheme
            or not text[len(scheme):].startswith(f"://{HOST}?") or "#" in text):
        return None
    query = text[len(scheme) + len(HOST) + 4:]
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    names = [name for name, _ in pairs]
    if sorted(names) != sorted(FIELDS):
        return None
    values = dict(pairs)
    if values["v"] != VERSION or not server_ok(values["server"]) or not token_ok(values["token"]):
        return None
    return values["server"], values["token"]
