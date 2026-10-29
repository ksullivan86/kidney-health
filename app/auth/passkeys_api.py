"""Passkey routes (design note 18 §5): ``/api/me/passkeys*`` to add, rename and remove them, and the public
``/api/auth/passkey*`` to sign in with one.

Local accounts in ``AUTH_MODE=local`` only: everywhere else every route answers 404 (the sign-in proxy does sign-in). Adding and
removing need a recent password (re-auth). Every ``/api/me`` route acts on ``user.id`` only; another person's passkey is 404.
A failed passkey sign-in counts against the address like a wrong password and gets one generic answer.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..audit import audit
from ..db import get_db
from . import passkeys, webauthn
from .accounts import require_secure_enough
from .context import AuthContext, auth_context, public_base, request_ip
from .deps import CurrentUser, RecentUser, current_user, ensure_setup_done
from .errors import ApiProblem, too_many
from .models import load_user, me_dict
from .ratelimit import register_limit

me_router = APIRouter(prefix="/api/me/passkeys", tags=["me"], dependencies=[Depends(current_user)])
auth_router = APIRouter(prefix="/api/auth/passkey", tags=["auth"])

register_limit("passkey_options", 30, 60, "Too many tries. Wait a minute and try again.")

TIMEOUT_MS = passkeys.CHALLENGE_TTL_S * 1000
SIGN_IN_FAILED = "That passkey did not work. Try again, or sign in with your password."
TOO_MANY = f"You have {passkeys.MAX_PER_PERSON} passkeys, the most one account can have. Remove one first."
ALREADY = "This passkey is already added."
START_AGAIN = "That took too long or was already used. Tap Add a passkey again."
IP_HOST = ("This server is opened by its IP address. Passkeys need a name for the server, like kidney.example.org, "
           "set in PUBLIC_URL.")


# --------------------------------------------------------------------------- #
# Bodies: the shape of PublicKeyCredential.toJSON(). Browsers add more keys (transports, clientExtensionResults, ...), which
# are ignored.
# --------------------------------------------------------------------------- #


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", str_max_length=65536)


class PasskeyAttestationResponse(_Lenient):
    clientDataJSON: str = Field(min_length=1)
    attestationObject: str = Field(min_length=1)


class PasskeyAssertionResponse(_Lenient):
    clientDataJSON: str = Field(min_length=1)
    authenticatorData: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    userHandle: str | None = None


class RegistrationCredential(_Lenient):
    rawId: str = Field(min_length=1, max_length=1400)
    type: str = "public-key"
    response: PasskeyAttestationResponse


class AssertionCredential(_Lenient):
    rawId: str = Field(min_length=1, max_length=1400)
    type: str = "public-key"
    response: PasskeyAssertionResponse


class PasskeyAddBody(_Lenient):
    challenge_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=200)
    credential: RegistrationCredential


class PasskeyNameBody(_Lenient):
    name: str = Field(min_length=1, max_length=200)


class PasskeySignInBody(_Lenient):
    challenge_id: str = Field(min_length=1, max_length=64)
    credential: AssertionCredential


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #


def _challenges(ctx: AuthContext) -> passkeys.ChallengeStore:
    return ctx.passkey_challenges


def _local_mode(ctx: AuthContext) -> None:
    if ctx.settings.auth_mode != "local":
        raise HTTPException(status_code=404, detail="Not Found")


def _only_local(request: Request, user) -> None:
    if not available(request, user):
        raise HTTPException(status_code=404, detail="Not Found")


def available(request: Request, user) -> bool:
    return auth_context(request).settings.auth_mode == "local" and user.auth_source == "local"


def relying_party(request: Request) -> tuple[str, str]:
    return passkeys.rp_id_and_origin(public_base(request, auth_context(request).settings))


def _decode(text: str | None) -> bytes:
    return webauthn.b64url_decode(text or "")


# --------------------------------------------------------------------------- #
# /api/me/passkeys
# --------------------------------------------------------------------------- #


@me_router.get("")
def list_passkeys(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's passkeys (names and dates only). ``usable`` is false, with ``reason``, when this server's address cannot carry
    passkeys (an IP address)."""
    if not available(request, user):
        return {"available": False, "usable": False, "reason": None, "passkeys": [], "max": passkeys.MAX_PER_PERSON}
    rp_id, _ = relying_party(request)
    ip_host = passkeys.host_is_ip(rp_id)
    return {"available": True, "usable": not ip_host, "reason": IP_HOST if ip_host else None,
            "passkeys": [passkeys.item(r) for r in passkeys.list_for(conn, user.id)], "max": passkeys.MAX_PER_PERSON}


@me_router.post("/options")
def passkey_creation_options(request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Options for ``navigator.credentials.create``, with a single-use challenge for this person (5 minutes)."""
    _only_local(request, user)
    ctx = auth_context(request)
    ctx.limits.take("passkey_options", f"user:{user.id}")
    rows = passkeys.list_for(conn, user.id)
    if len(rows) >= passkeys.MAX_PER_PERSON:
        raise ApiProblem(409, TOO_MANY)
    rp_id, _ = relying_party(request)
    if passkeys.host_is_ip(rp_id):
        raise ApiProblem(409, IP_HOST)
    handle = bytes(rows[0]["user_handle"]) if rows else passkeys.user_handle_for(conn, user.id)
    cid, challenge = _challenges(ctx).issue("create", user.id, handle)
    name = str(ctx.store.get(conn, "instance.name")).strip() or "Kidney Health"
    return {
        "challenge_id": cid,
        "publicKey": {
            "challenge": webauthn.b64url(challenge.value),
            "rp": {"id": rp_id, "name": name},
            "user": {"id": webauthn.b64url(handle), "name": user.username, "displayName": user.display_name or user.username},
            "pubKeyCredParams": [{"type": "public-key", "alg": alg} for alg in webauthn.ALGORITHMS],
            "timeout": TIMEOUT_MS,
            "excludeCredentials": [{"type": "public-key", "id": webauthn.b64url(bytes(r["credential_id"]))} for r in rows],
            "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True, "userVerification": "required"},
            "attestation": "none",
            "hints": [],
        },
    }


@me_router.post("", status_code=201)
def add_passkey(body: PasskeyAddBody, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Check what ``navigator.credentials.create`` returned (note 18 §3) and store the passkey."""
    _only_local(request, user)
    ctx = auth_context(request)
    challenge = _challenges(ctx).take(body.challenge_id, "create", user.id)
    if challenge is None or challenge.user_handle is None:
        raise ApiProblem(400, START_AGAIN)
    rp_id, origin = relying_party(request)
    try:
        if body.credential.type != "public-key":
            raise webauthn.WebAuthnError("That is not a passkey.")
        got = webauthn.verify_registration(client_data_json=_decode(body.credential.response.clientDataJSON),
                                           attestation_object=_decode(body.credential.response.attestationObject),
                                           challenge=challenge.value, origins=(origin,), rp_id=rp_id)
        if _decode(body.credential.rawId) != got.credential_id:
            raise webauthn.WebAuthnError("The passkey's ID does not match.")
    except webauthn.WebAuthnError as exc:
        raise ApiProblem(400, f"The passkey was not added: {exc}") from None
    if passkeys.count_for(conn, user.id) >= passkeys.MAX_PER_PERSON:
        raise ApiProblem(409, TOO_MANY)
    if passkeys.find_by_credential(conn, got.credential_id) is not None:
        raise ApiProblem(409, ALREADY)
    try:
        row = passkeys.add(conn, user.id, credential_id=got.credential_id, public_key=got.public_key, alg=got.alg,
                           user_handle=challenge.user_handle, sign_count=got.sign_count, name=passkeys.clean_name(body.name),
                           backed_up=got.backed_up)
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ApiProblem(409, ALREADY) from None
    audit(conn, user.id, "passkey.added", "user", user.id, ip=request_ip(request), passkey=int(row["id"]), synced=got.backed_up)
    conn.commit()
    return passkeys.item(row)


@me_router.patch("/{passkey_id}")
def rename_passkey(passkey_id: int, body: PasskeyNameBody, request: Request, user: CurrentUser,
                   conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _only_local(request, user)
    if not passkeys.rename(conn, user.id, passkey_id, passkeys.clean_name(body.name)):
        raise HTTPException(status_code=404, detail="Not Found")
    conn.commit()
    row = passkeys.get_for(conn, user.id, passkey_id)
    assert row is not None
    return passkeys.item(row)


@me_router.delete("/{passkey_id}", status_code=204, response_class=Response)
def remove_passkey(passkey_id: int, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _only_local(request, user)
    if not passkeys.remove(conn, user.id, passkey_id):
        raise HTTPException(status_code=404, detail="Not Found")
    audit(conn, user.id, "passkey.removed", "user", user.id, ip=request_ip(request), via="self", count=1)
    conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# /api/auth/passkey (public)
# --------------------------------------------------------------------------- #


def _sign_in_gate(request: Request, conn: sqlite3.Connection, ctx: AuthContext) -> str | None:
    _local_mode(ctx)
    ensure_setup_done(conn, ctx)
    ip = request_ip(request)
    th = ctx.throttle
    wait = th.ip_wait(ip)
    if wait:
        raise too_many(wait)
    try:
        require_secure_enough(conn, ctx.settings, request)
    except ApiProblem:
        th.ip_failure(ip)
        raise
    return ip


@auth_router.post("/options")
def passkey_request_options(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Options for ``navigator.credentials.get``: a challenge (5 minutes, single use), no list of passkeys, so the device offers
    the ones it holds for this server and nothing here says which accounts have one."""
    ctx = auth_context(request)
    ip = _sign_in_gate(request, conn, ctx)
    ctx.limits.take("passkey_options", f"ip:{ip}")
    rp_id, _ = relying_party(request)
    cid, challenge = _challenges(ctx).issue("get")
    return {"challenge_id": cid, "publicKey": {"challenge": webauthn.b64url(challenge.value), "rpId": rp_id,
                                               "timeout": TIMEOUT_MS, "userVerification": "required", "allowCredentials": []}}


@auth_router.post("")
def passkey_sign_in(body: PasskeySignInBody, request: Request, response: Response,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Sign in with a passkey: the same session as a password sign-in, without the two-step code (the device checked a
    fingerprint, face or PIN). Every failure is the same 401 and counts against the address."""
    from .routes import _reset_notice, start_session

    ctx = auth_context(request)
    ip = _sign_in_gate(request, conn, ctx)
    th = ctx.throttle
    wait = th.ip_attempt(ip)
    if wait:
        th.ip_failure(ip)
        raise too_many(wait)
    row = None

    def failed(reason: str) -> ApiProblem:
        th.ip_failure(ip)
        if row is not None:
            audit(conn, None, "login.failed", "user", int(row["user_id"]), ip=ip, via="passkey", reason=reason[:120])
        conn.commit()
        return ApiProblem(401, SIGN_IN_FAILED)

    challenge = _challenges(ctx).take(body.challenge_id, "get")
    if challenge is None:
        raise failed("challenge")
    try:
        credential_id = _decode(body.credential.rawId)
    except webauthn.WebAuthnError:
        raise failed("id") from None
    row = passkeys.find_by_credential(conn, credential_id)
    if row is None:
        raise failed("unknown passkey")
    user = load_user(conn, int(row["user_id"]))
    if user is None or not user.is_active or user.auth_source != "local":
        raise failed("account not active")
    rp_id, origin = relying_party(request)
    try:
        if body.credential.type != "public-key":
            raise webauthn.WebAuthnError("That is not a passkey.")
        handle = body.credential.response.userHandle
        if handle and _decode(handle) != bytes(row["user_handle"]):
            raise webauthn.WebAuthnError("The passkey is for a different account.")
        got = webauthn.verify_authentication(
            client_data_json=_decode(body.credential.response.clientDataJSON),
            authenticator_data=_decode(body.credential.response.authenticatorData),
            signature=_decode(body.credential.response.signature), challenge=challenge.value, origins=(origin,), rp_id=rp_id,
            public_key=bytes(row["public_key"]), stored_sign_count=int(row["sign_count"]))
    except webauthn.WebAuthnError as exc:
        raise failed(str(exc)) from None
    if got.counter_went_back:
        audit(conn, None, "passkey.counter_went_back", "user", user.id, ip=ip, passkey=int(row["id"]),
              stored=int(row["sign_count"]), sent=got.sign_count)
        raise failed("counter")
    passkeys.used(conn, int(row["id"]), sign_count=got.sign_count, backed_up=got.backed_up)
    notice = _reset_notice(conn, user.id)
    start_session(request, response, conn, ctx, user.id)
    audit(conn, user.id, "login.succeeded", "user", user.id, ip=ip, via="passkey")
    conn.commit()
    fresh = load_user(conn, user.id)
    return {"user": me_dict(fresh), "notice": notice}
