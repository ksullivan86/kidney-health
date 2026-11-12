"""Web Push for reminders (design note 35): the server's VAPID key, message encryption and the request to a push service.

No push library: the three standards are small and written here on the ``cryptography`` package, like the project's own OIDC and
passkey code.

* **VAPID** (RFC 8292): an ES256 JWT with ``aud`` (the push service's origin), ``exp`` 12 hours ahead (Apple allows at most 24)
  and ``sub`` (``VAPID_SUBJECT``), sent as ``Authorization: vapid t=<jwt>, k=<public key>``. A JWT is reused for up to 1 hour per
  push service, as Apple asks.
* **Encryption** (RFC 8291 with RFC 8188 ``aes128gcm``): one record, a new ephemeral key and salt for every message.
* **Push hosts.** The browser chooses the push service, so the endpoint is a URL a person controls. Only the fixed hosts in
  :data:`PUSH_HOSTS` and :data:`PUSH_HOST_SUFFIXES` are accepted, ``https`` on port 443, when a device is added and again
  before each send. Every request goes through :class:`app.egress.CheckedTransport` (private addresses refused, no redirects)
  inside :func:`app.egress.run_with_deadline`.

The private key is read from ``VAPID_PRIVATE_KEY_FILE`` (or made once, mode 0600, inside ``DATA_DIR``). It is registered with the
log redaction and never logged or returned; only the public key leaves the server.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import brand, egress
from .config import ConfigError
from .security import register_secret

log = logging.getLogger(f"{brand.LOGGER_NAME}.webpush")

KEY_FILENAME = "vapid_private.pem"
JWT_LIFETIME_S = 12 * 3600  # Apple: at most 1 day ahead
JWT_REUSE_S = 3600  # Apple: do not refresh more often than once an hour
RECORD_SIZE = 4096
MAX_PAYLOAD = 3993  # 4096 - 86 (header) - 16 (tag) - 1 (delimiter): Apple's 4 KB limit holds
MAX_ENDPOINT_CHARS = 1024
TTL_S = 3600
URGENCY = "normal"
MAX_RESPONSE_BYTES = 16 * 1024

# Push services this server sends to (docs/network-allowlist.md). Exact hosts, and suffixes that match one or more labels before them.
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com")
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com")

SEND_ERRORS = ("gone", "blocked", "timeout", "unreachable", "auth", "rejected", "busy", "bad_answer")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or not text or not all(c.isalnum() or c in "-_=" for c in text):
        raise ValueError("not base64url")
    text = text.rstrip("=")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    """The uncompressed point (65 bytes, starting 0x04)."""
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def load_public(raw: bytes) -> ec.EllipticCurvePublicKey:
    """A P-256 public key from its uncompressed point; ``ValueError`` when it is not one."""
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError("not an uncompressed P-256 point")
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)


# --------------------------------------------------------------------------- #
# Push hosts
# --------------------------------------------------------------------------- #


def allowed_host(host: str) -> bool:
    host = (host or "").lower()
    if host in PUSH_HOSTS:
        return True
    for suffix in PUSH_HOST_SUFFIXES:
        if host.endswith(suffix):
            label = host[: -len(suffix)]
            if label and all(part and all(c.isalnum() or c == "-" for c in part) for part in label.split(".")):
                return True
    return False


def check_endpoint(endpoint: Any) -> str | None:
    """The endpoint when this server may send to it: ``https``, port 443, a known push host, no user name. Else ``None``."""
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT_CHARS:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in endpoint):
        return None
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or port not in (None, 443):
        return None
    if parts.fragment or not allowed_host(parts.hostname or ""):
        return None
    return endpoint


def audience(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    return f"https://{(parts.hostname or '').lower()}"


def check_keys(p256dh: Any, auth: Any) -> tuple[bytes, bytes] | None:
    """The browser's public key (65 bytes, a P-256 point) and auth secret (16 bytes), or ``None``."""
    try:
        key = b64url_decode(p256dh)
        secret = b64url_decode(auth)
        load_public(key)
    except (ValueError, TypeError):
        return None
    if len(secret) != 16:
        return None
    return key, secret


# --------------------------------------------------------------------------- #
# The server's key (VAPID)
# --------------------------------------------------------------------------- #


def load_or_create_key(path: Path, data_dir: Path) -> ec.EllipticCurvePrivateKey:
    """The P-256 key in ``path``. A missing file inside ``data_dir`` is made once, mode 0600; elsewhere it is a ``ConfigError``."""
    if not path.exists():
        try:
            inside = path.resolve().is_relative_to(data_dir.resolve())
        except OSError:
            inside = False
        if not inside:
            raise ConfigError(f"VAPID_PRIVATE_KEY_FILE points to {path}, which does not exist. Leave it unset to have the server "
                              "make one in DATA_DIR, or put the key there.")
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # made by another worker meanwhile: read that one
            return load_or_create_key(path, data_dir)
        try:
            os.write(fd, pem)
        finally:
            os.close(fd)
        log.info("reminders: made a new push key in %s", path)
        register_secret(pem.decode("ascii").strip())
        return key
    try:
        pem = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"VAPID_PRIVATE_KEY_FILE: cannot read {path}: {exc.strerror or exc}") from None
    register_secret(pem.decode("ascii", "replace").strip())
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError):
        raise ConfigError(f"VAPID_PRIVATE_KEY_FILE: {path} is not a PEM private key without a password.") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ConfigError(f"VAPID_PRIVATE_KEY_FILE: {path} must hold a P-256 (prime256v1) key.")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = 0
    if mode & 0o077:
        log.warning("reminders: %s is readable by other users (mode %o); run: chmod 600 %s", path, mode, path)
    return key


class Vapid:
    """The server's key and the JWTs made with it, one per push service, each reused for up to an hour."""

    def __init__(self, key: ec.EllipticCurvePrivateKey, subject: str, *, clock: Callable[[], float] = time.time) -> None:
        self._key = key
        self.subject = subject
        self.public_key = b64url(public_bytes(key.public_key()))
        self._clock = clock
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:  # never the private key
        return f"Vapid(public_key={self.public_key!r})"

    def token(self, aud: str) -> str:
        now = self._clock()
        with self._lock:
            hit = self._cache.get(aud)
            if hit is not None and now - hit[0] < JWT_REUSE_S:
                return hit[1]
            claims = {"aud": aud, "exp": int(now) + JWT_LIFETIME_S, "sub": self.subject}
            jwt = self._sign(claims)
            self._cache[aud] = (now, jwt)
            return jwt

    def _sign(self, claims: dict[str, Any]) -> str:
        header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps(claims, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        r, s = decode_dss_signature(self._key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        return f"{header}.{body}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

    def authorization(self, endpoint: str) -> str:
        return f"vapid t={self.token(audience(endpoint))}, k={self.public_key}"


# --------------------------------------------------------------------------- #
# Encryption (RFC 8291, aes128gcm)
# --------------------------------------------------------------------------- #


def encrypt(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *, as_private: ec.EllipticCurvePrivateKey | None = None,
            salt: bytes | None = None) -> bytes:
    """The ``aes128gcm`` body for one push message. ``as_private`` and ``salt`` are fixed only by tests (RFC 8291 Appendix A)."""
    if len(plaintext) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    salt = salt if salt is not None else os.urandom(16)
    as_public = public_bytes(as_private.public_key())
    ecdh_secret = as_private.exchange(ec.ECDH(), load_public(ua_public))
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hkdf(auth_secret, ecdh_secret, key_info, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)


def decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth_secret: bytes) -> bytes:
    """What a browser does with :func:`encrypt`'s output (one record). For tests and the fake push service."""
    salt, idlen = body[:16], body[20]
    as_public = body[21:21 + idlen]
    ua_public = public_bytes(ua_private.public_key())
    ecdh_secret = ua_private.exchange(ec.ECDH(), load_public(as_public))
    ikm = _hkdf(auth_secret, ecdh_secret, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    padded = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    end = padded.rstrip(b"\x00")
    if not end.endswith(b"\x02"):
        raise ValueError("not a last record")
    return end[:-1]


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #


def message(title: str, body: str, navigate: str) -> dict[str, Any]:
    """Declarative Web Push (iOS 18.4+ shows it without the service worker; sw.js shows the same elsewhere)."""
    return {"web_push": 8030, "notification": {"title": title, "body": body, "navigate": navigate, "lang": "en"}}


@dataclass(frozen=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


class Sender:
    """``app.state.webpush``. ``resolver``, ``direct`` and ``use_env_proxy`` exist for tests (a fake push service behind the real
    checked transport)."""

    def __init__(self, vapid: Vapid | None, *, timeout_s: float = 10.0, resolver: Callable[[str, int], list[str]] | None = None,
                 direct: httpx2.BaseTransport | None = None, use_env_proxy: bool = True) -> None:
        self.vapid = vapid
        self.timeout_s = float(timeout_s)
        self.resolver = resolver
        self.direct = direct
        self.use_env_proxy = use_env_proxy

    @property
    def public_key(self) -> str | None:
        return self.vapid.public_key if self.vapid else None

    def _client(self) -> httpx2.Client:
        transport = egress.CheckedTransport(allow_private=False, resolver=self.resolver, use_env_proxy=self.use_env_proxy,
                                            direct=self.direct)
        return httpx2.Client(transport=transport, timeout=self.timeout_s, follow_redirects=False, trust_env=False,
                             headers={"User-Agent": brand.USER_AGENT_PUSH})

    def send(self, target: Target, payload: dict[str, Any]) -> str | None:
        """Send one message. ``None`` when the push service took it, else an error code from :data:`SEND_ERRORS`
        (``gone``: the device is no longer subscribed, so the caller deletes it)."""
        if self.vapid is None:
            return "auth"
        endpoint = check_endpoint(target.endpoint)
        keys = check_keys(target.p256dh, target.auth)
        if endpoint is None or keys is None:
            return "blocked"
        body = encrypt(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), keys[0], keys[1])
        headers = {"Authorization": self.vapid.authorization(endpoint), "TTL": str(TTL_S), "Urgency": URGENCY,
                   "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream"}
        try:
            return egress.run_with_deadline("webpush", lambda: self._post(endpoint, body, headers), self.timeout_s * 2)
        except egress.DeadlineExceeded:
            log.warning("reminders: a push service took too long")
            return "timeout"

    def _post(self, endpoint: str, body: bytes, headers: dict[str, str]) -> str | None:
        try:
            with self._client() as client, client.stream("POST", endpoint, content=body, headers=headers) as response:
                status = response.status_code
                egress.read_capped(response, MAX_RESPONSE_BYTES)
        except egress.BlockedAddress:
            log.warning("reminders: refused the address a push service resolves to")
            return "blocked"
        except egress.ResponseTooLarge:
            return "bad_answer"
        except httpx2.TimeoutException:
            log.warning("reminders: a push service did not answer in time")
            return "timeout"
        except httpx2.HTTPError:
            log.warning("reminders: a push service did not answer")
            return "unreachable"
        code = status_code(status)
        if code is not None:
            log.warning("reminders: a push service answered %s (HTTP %d)", code, status)
        return code


def status_code(status: int) -> str | None:
    if 200 <= status < 300:
        return None
    if status in (404, 410):
        return "gone"
    if status in (401, 403):
        return "auth"
    if status == 429 or status >= 500:
        return "busy"
    if status in (400, 413):
        return "rejected"
    return "bad_answer"  # a redirect (never followed) or anything else
