"""Sign-in with an OpenID Connect provider: discovery, PKCE, the token exchange and the ID token checks (design note 24 §3, §5).

Built on ``cryptography`` only (the roadmap's "Authlib or our own code" question; note 24 §5): JWS signatures RS256/384/512,
PS256/384/512, ES256/384 and EdDSA (Ed25519); ``none`` and the HMAC algorithms are refused. Every outbound request (discovery, the
JWKS, the token endpoint) goes through :class:`app.egress.CheckedTransport`: each address is checked when the request is made, a
private one only with ``OIDC_ALLOW_PRIVATE_ISSUER``, redirects are never followed and at most 256 KiB is read.

* :class:`OidcClient` (``app.state.oidc``): the provider's metadata (cached an hour), its keys (cached an hour, fetched again for an
  unknown ``kid`` at most once a minute), the authorization URL, the code exchange and :meth:`OidcClient.verify_id_token`.
* :class:`FlowStore`: the flows waiting at the providers, in memory, single use, 10 minutes (like the passkey challenges), one
  store for every provider. Each flow belongs to one provider and only that provider's way back can take it. At most
  ``MAX_FLOWS`` wait at once, an equal share of that per provider, and ``FLOWS_PER_KEY`` per address; when any is full a new start
  is refused (:class:`FlowStoreFull`), so a flood never pushes out someone else's waiting sign-in.
* :class:`OidcError`: a refusal with one of the short result words of :data:`RESULTS` (what the page shows) and a log reason.

Nothing here logs or keeps a token, a code, the state, the nonce or the client secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

import httpx2
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from .. import brand, egress
from ..config import OidcEnv
from . import clock

log = logging.getLogger(f"{brand.LOGGER_NAME}.auth.oidc")

CALLBACK_PATH = "/api/auth/oidc/callback"  # the first provider's; a named one adds /<name> (note 24 §13)
DEFAULT_ID = "default"
FLOW_TTL_S = 600
MAX_FLOWS = 10_000
FLOWS_PER_KEY = 10  # flows one address (or one person, for link and re-auth) may have waiting at once
METADATA_TTL_S = 3600
JWKS_TTL_S = 3600
JWKS_REFRESH_MIN_S = 60
HTTP_TIMEOUT_S = 10.0
MAX_RESPONSE_BYTES = 262_144
MAX_TOKEN_CHARS = 16_384
CLOCK_SKEW_S = 60
MAX_IAT_AGE_S = 600
MAX_SUBJECT = 255

# The result words the callback sends the page to (``/#/oidc/<word>``); js/views/oidc.js has the sentence for each.
RESULTS = (
    "failed", "expired", "cancelled", "unavailable", "busy", "full", "no_account", "domain", "disabled", "taken", "name", "invite",
    "https", "wrong_account", "linked", "confirmed",
)

_HASHES = {"256": hashes.SHA256, "384": hashes.SHA384, "512": hashes.SHA512}
ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "EdDSA")
_EC_CURVES = {"ES256": ("P-256", ec.SECP256R1, 32), "ES384": ("P-384", ec.SECP384R1, 48)}


class OidcError(Exception):
    """A refused sign-in. ``result`` is one of :data:`RESULTS`; ``reason`` a short word for the log and the audit row."""

    def __init__(self, result: str, reason: str) -> None:
        super().__init__(reason)
        self.result = result if result in RESULTS else "failed"
        self.reason = reason


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or not all(c.isalnum() or c in "-_" for c in text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_challenge(verifier: str) -> str:
    """RFC 7636 §4.2, S256."""
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def discovery_url(issuer: str) -> str:
    """OIDC Discovery §4: the issuer without one trailing ``/``, then ``/.well-known/openid-configuration``."""
    return issuer[:-1] + "/.well-known/openid-configuration" if issuer.endswith("/") else issuer + "/.well-known/openid-configuration"


def callback_path(name: str = "") -> str:
    """The way back from a provider: ``/api/auth/oidc/callback`` for the first one, ``…/callback/<name>`` for a named one. Each
    provider has its own exact redirect URI, so a code can only come back to the provider it was made for (RFC 9700 §4.4.2)."""
    return f"{CALLBACK_PATH}/{name}" if name else CALLBACK_PATH


def redirect_uri(public_origin: str, name: str = "") -> str:
    return public_origin.rstrip("/") + callback_path(name)


def _endpoint_ok(url: Any, issuer: str) -> bool:
    if not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if not parts.hostname or parts.fragment or parts.username is not None:
        return False
    if parts.scheme == "https":
        return True
    # plain http only when the issuer itself is a loopback http one (tests and the local walk)
    return parts.scheme == "http" and issuer.startswith("http://") and parts.hostname in ("localhost", "127.0.0.1", "::1")


# --------------------------------------------------------------------------- #
# Flows waiting at the provider
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Flow:
    purpose: str  # signin | link | reauth | invite
    nonce: str
    verifier: str  # the PKCE code_verifier
    binder_hash: bytes  # SHA-256 of the cookie value set at the start
    created: float  # clock.seconds()
    user_id: int | None = None  # link and reauth: who started it
    session_id: str | None = None  # link and reauth: the session that started it
    invite_id: str | None = None  # invite: the invite token's id
    expires: float = 0.0
    key: str = ""  # who started it, for the per-address cap
    provider: str = DEFAULT_ID  # the provider it was started with; only that provider's way back takes it


class FlowStoreFull(Exception):
    """Too many flows are waiting (in all, or for this address): the start is refused, nothing is dropped."""


class FlowStore:
    """Flows by the SHA-256 of their ``state``. :meth:`take` returns one at most once, before it expires, only to the browser
    holding its cookie (a wrong or missing cookie leaves the flow waiting for its own browser) and only at the way back of the
    provider it was started with (another provider's way back leaves it waiting too). At most ``max_items`` wait in all,
    ``per_provider`` for one provider and ``per_key`` per address; beyond that :meth:`issue` raises :class:`FlowStoreFull`.
    Expired flows are dropped as new ones come; a waiting flow is never pushed out by others."""

    def __init__(self, max_items: int = MAX_FLOWS, ttl_s: float = FLOW_TTL_S, per_key: int = FLOWS_PER_KEY,
                 per_provider: int | None = None) -> None:
        self._items: OrderedDict[bytes, Flow] = OrderedDict()
        self._per_key: dict[str, int] = {}
        self._per_provider: dict[str, int] = {}
        self._lock = threading.Lock()
        self._max, self._ttl, self._cap = max_items, ttl_s, per_key
        self._provider_cap = max_items if per_provider is None else per_provider

    @staticmethod
    def _drop(counts: dict[str, int], name: str) -> None:
        left = counts.get(name, 0) - 1
        if left > 0:
            counts[name] = left
        else:
            counts.pop(name, None)

    def _forget(self, flow: Flow) -> None:
        self._drop(self._per_key, flow.key)
        self._drop(self._per_provider, flow.provider)

    def issue(self, purpose: str, *, key: str = "", user_id: int | None = None, session_id: str | None = None,
              invite_id: str | None = None, provider: str = DEFAULT_ID) -> tuple[str, str, Flow]:
        """A new flow: ``(state, binder, flow)``. The binder goes into the cookie; only its hash is kept."""
        state = secrets.token_urlsafe(32)
        binder = secrets.token_urlsafe(32)
        now = clock.seconds()
        flow = Flow(purpose, secrets.token_urlsafe(32), secrets.token_urlsafe(32), hashlib.sha256(binder.encode()).digest(), now,
                    user_id, session_id, invite_id, now + self._ttl, key, provider)
        with self._lock:
            while self._items and next(iter(self._items.values())).expires < now:  # same lifetime for all: oldest first
                self._forget(self._items.popitem(last=False)[1])
            if (len(self._items) >= self._max or self._per_key.get(key, 0) >= self._cap
                    or self._per_provider.get(provider, 0) >= self._provider_cap):
                raise FlowStoreFull(key)
            self._items[hashlib.sha256(state.encode()).digest()] = flow
            self._per_key[key] = self._per_key.get(key, 0) + 1
            self._per_provider[provider] = self._per_provider.get(provider, 0) + 1
        return state, binder, flow

    def take(self, state: str | None, binder: str | None, provider: str = DEFAULT_ID) -> Flow | None:
        """The flow for ``state`` if the cookie's ``binder`` matches, it was started with ``provider`` and it has not expired; it is
        gone afterwards. An unknown state, a cookie that does not match or another provider's way back returns None and changes
        nothing."""
        if not isinstance(state, str) or not state or len(state) > 200 or not isinstance(binder, str):
            return None
        digest = hashlib.sha256(state.encode()).digest()
        with self._lock:
            flow = self._items.get(digest)
            if flow is None:
                return None
            if flow.expires < clock.seconds():
                self._forget(self._items.pop(digest))
                return None
            if not hmac.compare_digest(hashlib.sha256(binder.encode()).digest(), flow.binder_hash) or flow.provider != provider:
                return None
            self._forget(self._items.pop(digest))
        return flow

    def __len__(self) -> int:
        return len(self._items)

    def count(self, provider: str) -> int:
        return self._per_provider.get(provider, 0)


# --------------------------------------------------------------------------- #
# Keys and signatures
# --------------------------------------------------------------------------- #


def _int(value: Any) -> int:
    return int.from_bytes(b64url_decode(value), "big")


def jwk_fits(jwk: dict[str, Any], alg: str) -> bool:
    """Whether this JWK may check a signature made with ``alg`` (RFC 7517 §4: kty, crv, use, alg)."""
    if not isinstance(jwk, dict):
        return False
    if jwk.get("use") not in (None, "sig") or jwk.get("alg") not in (None, alg):
        return False
    kty = jwk.get("kty")
    if alg.startswith(("RS", "PS")):
        return kty == "RSA"
    if alg in _EC_CURVES:
        return kty == "EC" and jwk.get("crv") == _EC_CURVES[alg][0]
    if alg == "EdDSA":
        return kty == "OKP" and jwk.get("crv") == "Ed25519"
    return False


def public_key(jwk: dict[str, Any], alg: str) -> Any:
    """The ``cryptography`` public key of a JWK (ValueError when it is not usable for ``alg``)."""
    if not jwk_fits(jwk, alg):
        raise ValueError("key does not fit the algorithm")
    if jwk["kty"] == "RSA":
        key = rsa.RSAPublicNumbers(_int(jwk["e"]), _int(jwk["n"])).public_key()
        if key.key_size < 2048:
            raise ValueError("RSA key shorter than 2048 bits")
        return key
    if jwk["kty"] == "EC":
        _, curve, size = _EC_CURVES[alg]
        x, y = b64url_decode(jwk["x"]), b64url_decode(jwk["y"])
        if len(x) != size or len(y) != size:
            raise ValueError("EC point has the wrong size")
        return ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), curve()).public_key()
    raw = b64url_decode(jwk["x"])
    if len(raw) != 32:
        raise ValueError("Ed25519 key has the wrong size")
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)


def verify_signature(alg: str, key: Any, signing_input: bytes, signature: bytes) -> bool:
    try:
        if alg.startswith("RS"):
            key.verify(signature, signing_input, padding.PKCS1v15(), _HASHES[alg[2:]]())
        elif alg.startswith("PS"):
            h = _HASHES[alg[2:]]()
            key.verify(signature, signing_input, padding.PSS(mgf=padding.MGF1(h), salt_length=h.digest_size), h)
        elif alg in _EC_CURVES:
            size = _EC_CURVES[alg][2]
            if len(signature) != 2 * size:
                return False
            der = encode_dss_signature(int.from_bytes(signature[:size], "big"), int.from_bytes(signature[size:], "big"))
            key.verify(der, signing_input, ec.ECDSA(_HASHES[alg[2:]]()))
        elif alg == "EdDSA":
            key.verify(signature, signing_input)
        else:
            return False
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def split_jws(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    """``(header, claims, signing input, signature)`` of a compact JWS (ValueError when it is not one)."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS or token.count(".") != 2:
        raise ValueError("not a compact JWS")
    head_b64, body_b64, sig_b64 = token.split(".")
    header = json.loads(b64url_decode(head_b64))
    claims = json.loads(b64url_decode(body_b64))
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("header or claims are not objects")
    return header, claims, f"{head_b64}.{body_b64}".encode("ascii"), b64url_decode(sig_b64)


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #


@dataclass
class Metadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    token_auth: str  # client_secret_basic | client_secret_post | none
    fetched: float


@dataclass
class OidcClient:
    """One provider (``app.state.oidc_providers``; the first is also ``app.state.oidc``). Tests set ``resolver``, ``direct`` and ``use_env_proxy`` to talk to a fake provider through
    the same SSRF-checked transport."""

    env: OidcEnv
    public_origin: str | None
    resolver: Callable[[str, int], list[str]] | None = None
    direct: httpx2.BaseTransport | None = None
    use_env_proxy: bool = True
    flows: FlowStore = field(default_factory=FlowStore)
    _metadata: Metadata | None = field(default=None, init=False, repr=False)
    _jwks: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _jwks_fetched: float = field(default=0.0, init=False, repr=False)
    _jwks_refreshed: float = field(default=-1e9, init=False, repr=False)
    last_error: str | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def enabled(self) -> bool:
        return bool(self.env.enabled and self.env.issuer and self.env.client_id and self.public_origin)

    @property
    def issuer(self) -> str:
        return self.env.issuer or ""

    @property
    def id(self) -> str:
        return self.env.id

    @property
    def redirect_uri(self) -> str:
        return redirect_uri(self.public_origin or "", self.env.name)

    # ------------------------------------------------------------------ HTTP
    def _client(self) -> httpx2.Client:
        transport = egress.CheckedTransport(allow_private=self.env.allow_private_issuer, resolver=self.resolver,
                                            use_env_proxy=self.use_env_proxy, direct=self.direct)
        return httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_S, follow_redirects=False, trust_env=False,
                             headers={"User-Agent": brand.USER_AGENT_OIDC, "Accept": "application/json"})

    def _json(self, method: str, url: str, what: str, **kwargs: Any) -> tuple[int, Any]:
        try:
            with self._client() as client, client.stream(method, url, **kwargs) as response:
                body = egress.read_capped(response, MAX_RESPONSE_BYTES)
                status = response.status_code
        except egress.BlockedAddress as exc:
            reason = "blocked_address" if "blocked_address" in str(exc) else "dns_failed"
            log.warning("OIDC %s: refused to connect (%s)", what, reason)
            raise OidcError("unavailable", reason) from None
        except egress.ResponseTooLarge:
            raise OidcError("unavailable", "too_large") from None
        except httpx2.HTTPError as exc:
            log.warning("OIDC %s: %s", what, type(exc).__name__)
            raise OidcError("unavailable", "unreachable") from None
        try:
            data = json.loads(body) if body else None
        except ValueError:
            data = None
        return status, data

    # ------------------------------------------------------------------ discovery and keys
    def metadata(self, *, force: bool = False) -> Metadata:
        with self._lock:
            cached = self._metadata
        if cached is not None and not force and clock.seconds() - cached.fetched < METADATA_TTL_S:
            return cached
        try:
            meta = self._discover()
        except OidcError as exc:
            self.last_error = exc.reason
            raise
        self.last_error = None
        with self._lock:
            self._metadata = meta
        return meta

    def _discover(self) -> Metadata:
        status, doc = self._json("GET", discovery_url(self.issuer), "discovery")
        if status != 200 or not isinstance(doc, dict):
            raise OidcError("unavailable", f"discovery_http_{status}")
        if doc.get("issuer") != self.issuer:
            log.warning("OIDC discovery: the document names another issuer; OIDC_ISSUER must be exactly the provider's issuer")
            raise OidcError("unavailable", "issuer_mismatch")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not _endpoint_ok(doc.get(name), self.issuer):
                raise OidcError("unavailable", f"bad_{name}")
        methods = doc.get("code_challenge_methods_supported")
        if isinstance(methods, list) and "S256" not in methods:
            raise OidcError("unavailable", "no_pkce_s256")
        auth_methods = doc.get("token_endpoint_auth_methods_supported")
        if not self.env.secret_set:
            token_auth = "none"
        elif isinstance(auth_methods, list) and "client_secret_basic" not in auth_methods and "client_secret_post" in auth_methods:
            token_auth = "client_secret_post"
        else:
            token_auth = "client_secret_basic"
        return Metadata(self.issuer, doc["authorization_endpoint"], doc["token_endpoint"], doc["jwks_uri"], token_auth, clock.seconds())

    def _fetch_jwks(self, meta: Metadata) -> list[dict[str, Any]]:
        status, doc = self._json("GET", meta.jwks_uri, "keys")
        keys = doc.get("keys") if isinstance(doc, dict) else None
        if status != 200 or not isinstance(keys, list):
            raise OidcError("unavailable", f"jwks_http_{status}")
        return [k for k in keys[:100] if isinstance(k, dict)]

    def keys(self, meta: Metadata, *, unknown_kid: bool = False) -> list[dict[str, Any]]:
        """The provider's keys. Fetched when older than an hour, or (``unknown_kid``) again at most once a minute."""
        now = clock.seconds()
        with self._lock:
            fresh = self._jwks and now - self._jwks_fetched < JWKS_TTL_S
            may_refresh = now - self._jwks_refreshed >= JWKS_REFRESH_MIN_S
            if fresh and not (unknown_kid and may_refresh):
                return list(self._jwks)
            if unknown_kid:
                self._jwks_refreshed = now
        keys = self._fetch_jwks(meta)
        with self._lock:
            self._jwks, self._jwks_fetched = keys, clock.seconds()
        return list(keys)

    def _key_for(self, meta: Metadata, header: dict[str, Any], alg: str) -> Any:
        kid = header.get("kid")
        if kid is not None and not isinstance(kid, str):
            raise OidcError("failed", "bad_kid")

        def pick(keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if kid is not None:
                return [k for k in keys if k.get("kid") == kid]
            fitting = [k for k in keys if jwk_fits(k, alg)]
            return fitting if len(fitting) == 1 else []

        found = pick(self.keys(meta))
        if not found and kid is not None:
            found = pick(self.keys(meta, unknown_kid=True))  # the provider may have rotated its keys
        if len(found) != 1:
            raise OidcError("failed", "unknown_key")
        try:
            return public_key(found[0], alg)
        except (ValueError, KeyError, TypeError):
            raise OidcError("failed", "unusable_key") from None

    # ------------------------------------------------------------------ the flow
    def authorization_url(self, meta: Metadata, state: str, flow: Flow) -> str:
        params = {
            "response_type": "code",
            "client_id": self.env.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.env.scopes,
            "state": state,
            "nonce": flow.nonce,
            "code_challenge": pkce_challenge(flow.verifier),
            "code_challenge_method": "S256",
        }
        if flow.purpose == "reauth":
            params.update(prompt="login", max_age="0")
        sep = "&" if urlsplit(meta.authorization_endpoint).query else "?"
        return meta.authorization_endpoint + sep + urlencode(params)

    def exchange(self, meta: Metadata, code: str, flow: Flow) -> str:
        """The ``id_token`` for ``code``. The access and refresh tokens in the answer are dropped here."""
        if not isinstance(code, str) or not code or len(code) > 4096:
            raise OidcError("failed", "bad_code")
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri, "code_verifier": flow.verifier}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        client_id = self.env.client_id or ""
        if meta.token_auth == "client_secret_basic":
            # RFC 6749 §2.3.1: both parts form-encoded before the Basic header.
            from urllib.parse import quote_plus

            pair = f"{quote_plus(client_id)}:{quote_plus(self.env.client_secret or '')}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("ascii")
        else:
            form["client_id"] = client_id
            if meta.token_auth == "client_secret_post":
                form["client_secret"] = self.env.client_secret or ""
        status, data = self._json("POST", meta.token_endpoint, "token", content=urlencode(form).encode(), headers=headers)
        if status != 200 or not isinstance(data, dict):
            error = data.get("error") if isinstance(data, dict) and isinstance(data.get("error"), str) else ""
            reason = f"token_{error[:40]}" if error.replace("_", "").isalnum() else f"token_http_{status}"
            raise OidcError("failed", reason)
        token = data.get("id_token")
        if not isinstance(token, str):
            raise OidcError("failed", "no_id_token")
        return token

    def verify_id_token(self, meta: Metadata, token: str, flow: Flow) -> dict[str, Any]:
        """OIDC Core §3.1.3.7 (note 24 §5). The checked claims, or :class:`OidcError`."""
        try:
            header, claims, signing_input, signature = split_jws(token)
        except (ValueError, UnicodeDecodeError):
            raise OidcError("failed", "malformed_token") from None
        alg = header.get("alg")
        if alg not in ALGORITHMS:
            raise OidcError("failed", "bad_alg")
        if "crit" in header:
            raise OidcError("failed", "crit_header")
        key = self._key_for(meta, header, alg)
        if not verify_signature(alg, key, signing_input, signature):
            raise OidcError("failed", "bad_signature")
        client_id = self.env.client_id
        if claims.get("iss") != self.issuer:
            raise OidcError("failed", "bad_iss")
        aud = claims.get("aud")
        audiences = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        if client_id not in audiences or not all(isinstance(a, str) for a in audiences):
            raise OidcError("failed", "bad_aud")
        azp = claims.get("azp")
        if (len(audiences) > 1 and azp != client_id) or (azp is not None and azp != client_id):
            raise OidcError("failed", "bad_azp")
        now = clock.seconds()
        exp, iat = claims.get("exp"), claims.get("iat")
        if not _number(exp) or not _number(iat):
            raise OidcError("failed", "no_times")
        if now > exp + CLOCK_SKEW_S:
            raise OidcError("failed", "expired_token")
        if iat > now + CLOCK_SKEW_S or now - iat > MAX_IAT_AGE_S + CLOCK_SKEW_S:
            raise OidcError("failed", "bad_iat")
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not hmac.compare_digest(nonce.encode(), flow.nonce.encode()):
            raise OidcError("failed", "bad_nonce")
        sub = claims.get("sub")
        if not isinstance(sub, str) or not 1 <= len(sub) <= MAX_SUBJECT:
            raise OidcError("failed", "bad_sub")
        if flow.purpose == "reauth":
            auth_time = claims.get("auth_time")
            if not _number(auth_time) or auth_time < flow.created - CLOCK_SKEW_S:
                raise OidcError("failed", "not_fresh")
        return claims


def _number(value: Any) -> bool:
    """A JSON number that is finite (``json.loads`` reads ``Infinity`` and ``NaN``, which would pass every time check)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# --------------------------------------------------------------------------- #
# Claims the account rules read
# --------------------------------------------------------------------------- #


GOOGLE_ISSUER = "https://accounts.google.com"


def verified_email(claims: dict[str, Any]) -> str | None:
    """The email, lower case, only when ``email_verified`` is the boolean ``true``."""
    email = claims.get("email")
    if claims.get("email_verified") is not True or not isinstance(email, str) or "@" not in email or len(email) > 320:
        return None
    return email.strip().lower()


def any_email(claims: dict[str, Any]) -> str | None:
    email = claims.get("email")
    return email.strip()[:320] if isinstance(email, str) and "@" in email else None


def groups(claims: dict[str, Any]) -> set[str] | None:
    """The ``groups`` claim, or None when there is none (no information: the role is left alone)."""
    raw = claims.get("groups")
    if not isinstance(raw, list):
        return None
    return {g for g in raw if isinstance(g, str)}


def domain_allowed(claims: dict[str, Any], domains: list[str], issuer: str = "") -> bool:
    """With allowed domains set: a verified email in one of them, and Google's ``hd`` (when sent) in them too. With Google as the
    issuer ``hd`` is required: a personal Google account can carry any address as its email, and only ``hd`` says the account
    belongs to that Workspace domain."""
    if not domains:
        return True
    allowed = {d.lower().lstrip("@") for d in domains}
    email = verified_email(claims)
    if email is None or email.rsplit("@", 1)[1] not in allowed:
        return False
    hd = claims.get("hd")
    if hd is None:
        return issuer != GOOGLE_ISSUER
    return isinstance(hd, str) and hd.lower() in allowed
