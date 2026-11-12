"""``/api/reminders``: reminders by phone notification (design note 35).

Off unless ``REMINDERS_ENABLED`` is on (env only; :class:`app.config.RemindersEnv`). While it is off, ``GET /api/reminders``
answers ``enabled: false`` and every other route is ``404``. Every route needs a signed-in person and touches only that person's
own rows; another person's id is ``404``. Test accounts may look but not use it (``403``): the account is shared by testers.

* ``GET``: whether it is on, the server's public key, the kinds, the person's reminders and devices (never a device's keys).
* ``POST`` / ``PATCH /{id}`` / ``DELETE /{id}``: the reminders, at most :data:`MAX_REMINDERS`.
* ``POST /subscriptions``: this browser's ``PushSubscription.toJSON()``; only known push hosts (:mod:`app.webpush`), at most
  :data:`MAX_DEVICES`. ``DELETE /subscriptions/{id}`` removes one.
* ``POST /test``: one test notification to each of the person's devices, 5 an hour.

:func:`loop` runs once a minute: a reminder goes out at its time, in its own time zone, at most once a day. A meal reminder is
skipped when that meal already has eaten food logged today. The words are generic: no nutrient values, condition names, food
names or the person's name, and never anything about lows, insulin, medicines or glucose. **Reminders are a convenience; a CGM's
alerts are what to rely on for low blood sugar.**
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import brand, webpush
from .audit import audit
from .auth.context import auth_context, request_ip
from .auth.deps import CurrentUser
from .auth.errors import ApiProblem
from .auth.ratelimit import register_limit
from .db import connect, get_db, utcnow

log = logging.getLogger(f"{brand.LOGGER_NAME}.reminders")

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

MAX_REMINDERS = 10
MAX_DEVICES = 5
USER_AGENT_LIMIT = 300
WINDOW_MIN = 5  # a reminder goes out from its time to 5 minutes after, never later
TICK_S = 60
FIRST_TICK_S = 20
TESTS_PER_HOUR = 5
ALL_DAYS = 127
KINDS = ("log_meal", "plan_tomorrow", "weigh_in")
MEALS = ("breakfast", "lunch", "dinner", "snack")
DEFAULT_TITLE = "Food log"
SAFETY = "Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts."
TEST_BODY = "This is a test. Your reminders will look like this."
TEST_ACCOUNT = "Test accounts cannot use reminders. Sign in with your own account to set yours up."
TOO_MANY_REMINDERS = f"You have {MAX_REMINDERS} reminders, the most there can be. Remove one first."
TOO_MANY_DEVICES = f"Notifications are on for {MAX_DEVICES} devices, the most there can be. Remove one first."
NO_DEVICES = "Turn on notifications on this device first."
BAD_ENDPOINT = "This browser's push service is not one this server sends to. Try Safari, Chrome, Edge or Firefox."
BAD_KEYS = "This browser sent keys the server cannot use. Turn notifications off and on again."
BAD_TIME = "Enter a time such as 12:30."
BAD_DAYS = "Choose at least one day."
BAD_ZONE = "That time zone is not known. Reload the page and try again."
MEAL_NEEDED = "Choose which meal."
MEAL_NOT_HERE = "Only a meal reminder has a meal."
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
ZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-/]{0,63}$")
register_limit("reminders_test", TESTS_PER_HOUR, 3600, "You sent several tests this hour. Try again later.")

BODIES = {
    ("log_meal", "breakfast"): "Time to log breakfast.",
    ("log_meal", "lunch"): "Time to log lunch.",
    ("log_meal", "dinner"): "Time to log dinner.",
    ("log_meal", "snack"): "Time to log a snack.",
    ("plan_tomorrow", None): "Time to plan tomorrow's meals.",
    ("weigh_in", None): "Time to log your weight.",
}
PAGES = {"log_meal": "add", "plan_tomorrow": "plan", "weigh_in": "today"}
KIND_LABELS = {"log_meal": "Log a meal", "plan_tomorrow": "Plan tomorrow", "weigh_in": "Log your weight"}


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class ReminderIn(BaseModel):
    kind: Literal["log_meal", "plan_tomorrow", "weigh_in"]
    meal: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    time: str = Field(max_length=5)
    days: int = Field(default=ALL_DAYS, ge=0, le=ALL_DAYS)
    time_zone: str = Field(default="", max_length=64)
    enabled: bool = True


class ReminderPatch(BaseModel):
    kind: Literal["log_meal", "plan_tomorrow", "weigh_in"] | None = None
    meal: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    time: str | None = Field(default=None, max_length=5)
    days: int | None = Field(default=None, ge=0, le=ALL_DAYS)
    time_zone: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None


class ReminderOut(BaseModel):
    id: int
    kind: str
    meal: str | None
    time: str
    days: int
    time_zone: str
    enabled: bool
    created_at: str
    last_sent_on: str | None


class KeysIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscriptionIn(BaseModel):
    """``PushSubscription.toJSON()``; ``expirationTime`` and anything else is ignored."""

    model_config = ConfigDict(extra="ignore")
    endpoint: str = Field(max_length=webpush.MAX_ENDPOINT_CHARS + 100)
    keys: KeysIn


class DeviceOut(BaseModel):
    id: int
    user_agent: str | None
    created_at: str
    last_ok_at: str | None
    last_error: str | None


class KindOut(BaseModel):
    kind: str
    label: str
    meals: list[str]


class StatusOut(BaseModel):
    enabled: bool
    can_use: bool
    public_key: str | None
    max_reminders: int
    max_devices: int
    safety: str
    kinds: list[KindOut]
    reminders: list[ReminderOut]
    devices: list[DeviceOut]


class TestOut(BaseModel):
    devices: int
    sent: int
    failed: int
    removed: int


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def sender(request: Request) -> webpush.Sender:
    return request.app.state.webpush


def server_on(request: Request) -> bool:
    return bool(request.app.state.settings.reminders.enabled) and sender(request).vapid is not None


def _require_on(request: Request) -> None:
    if not server_on(request):
        raise HTTPException(status_code=404, detail="Not Found")


def _require_user(request: Request, user: Any) -> None:
    _require_on(request)
    if user.is_test_account:
        raise ApiProblem(403, TEST_ACCOUNT)


def reminder_view(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "kind": row["kind"], "meal": row["meal"], "time": row["time_local"], "days": row["days"],
            "time_zone": row["time_zone"], "enabled": bool(row["enabled"]), "created_at": row["created_at"],
            "last_sent_on": row["last_sent_on"]}


def device_view(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "user_agent": row["user_agent"], "created_at": row["created_at"], "last_ok_at": row["last_ok_at"],
            "last_error": row["last_error"]}


def reminders_of(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM reminders WHERE user_id = ? ORDER BY time_local, id", (int(user_id),)).fetchall()


def devices_of(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY id", (int(user_id),)).fetchall()


def _reminder(conn: sqlite3.Connection, user_id: int, reminder_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM reminders WHERE id = ? AND user_id = ?", (int(reminder_id), int(user_id))).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return row


def zone_of(name: str) -> tzinfo | None:
    """The time zone named ``name``; ``None`` for the server's own time (an empty name) or an unknown one."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _check(kind: str, meal: str | None, time_text: str, days: int, zone: str) -> None:
    if kind == "log_meal" and meal is None:
        raise ApiProblem(400, MEAL_NEEDED, field="meal")
    if kind != "log_meal" and meal is not None:
        raise ApiProblem(400, MEAL_NOT_HERE, field="meal")
    if not TIME_RE.match(time_text):
        raise ApiProblem(400, BAD_TIME, field="time")
    if not 1 <= days <= ALL_DAYS:
        raise ApiProblem(400, BAD_DAYS, field="days")
    if zone and (not ZONE_RE.match(zone) or zone_of(zone) is None):
        raise ApiProblem(400, BAD_ZONE, field="time_zone")


def title_of(conn: sqlite3.Connection, request_or_store: Any) -> str:
    """The server's name when the admin changed it; else "Food log" (the default name says "Kidney", and a lock screen is public)."""
    store = request_or_store
    try:
        name = str(store.get(conn, "instance.name") or "").strip()
    except Exception:  # pragma: no cover - a broken setting never stops a reminder
        name = ""
    return name if name and name != brand.NAME else DEFAULT_TITLE


def payload_for(public_url: str, title: str, kind: str, meal: str | None) -> dict[str, Any]:
    base = public_url.rstrip("/")
    return webpush.message(title, BODIES[(kind, meal if kind == "log_meal" else None)], f"{base}/#{PAGES[kind]}")


@dataclass
class Outcome:
    sent: int = 0
    failed: int = 0
    removed: int = 0


def deliver(conn: sqlite3.Connection, push: webpush.Sender, user_id: int, devices: list[sqlite3.Row], payload: dict[str, Any]) -> Outcome:
    """Send ``payload`` to each device (no transaction open while waiting), then record the results. A device the push service
    no longer knows (404 or 410) is deleted."""
    if conn.in_transaction:
        conn.commit()
    results = [(row["id"], push.send(webpush.Target(row["endpoint"], row["p256dh"], row["auth"]), payload)) for row in devices]
    out = Outcome()
    now = utcnow()
    for device_id, code in results:
        if code is None:
            out.sent += 1
            conn.execute("UPDATE push_subscriptions SET last_ok_at = ?, last_error = NULL WHERE id = ? AND user_id = ?",
                         (now, device_id, int(user_id)))
        elif code == "gone":
            out.removed += 1
            cur = conn.execute("DELETE FROM push_subscriptions WHERE id = ? AND user_id = ?", (device_id, int(user_id)))
            if cur.rowcount:
                audit(conn, int(user_id), "reminder.device_removed", "push_subscription", device_id, via="push_service")
        else:
            out.failed += 1
            conn.execute("UPDATE push_subscriptions SET last_error = ? WHERE id = ? AND user_id = ?", (code, device_id, int(user_id)))
    conn.commit()
    return out


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("", response_model=StatusOut)
def get_reminders(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    kinds = [{"kind": k, "label": KIND_LABELS[k], "meals": list(MEALS) if k == "log_meal" else []} for k in KINDS]
    base = {"max_reminders": MAX_REMINDERS, "max_devices": MAX_DEVICES, "safety": SAFETY, "kinds": kinds}
    if not server_on(request):  # answer, not 404: Settings asks on every open
        return {"enabled": False, "can_use": False, "public_key": None, **base, "reminders": [], "devices": []}
    return {"enabled": True, "can_use": not user.is_test_account, "public_key": sender(request).public_key, **base,
            "reminders": [reminder_view(r) for r in reminders_of(conn, user.id)],
            "devices": [device_view(r) for r in devices_of(conn, user.id)]}


@router.post("", response_model=ReminderOut, status_code=201)
def add_reminder(body: ReminderIn, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_user(request, user)
    _check(body.kind, body.meal, body.time, body.days, body.time_zone)
    count = conn.execute("SELECT COUNT(*) FROM reminders WHERE user_id = ?", (user.id,)).fetchone()[0]
    if count >= MAX_REMINDERS:
        raise ApiProblem(409, TOO_MANY_REMINDERS)
    cur = conn.execute(
        "INSERT INTO reminders (user_id, kind, meal, time_local, days, time_zone, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user.id, body.kind, body.meal, body.time, body.days, body.time_zone, int(body.enabled), utcnow()))
    rid = int(cur.lastrowid or 0)
    audit(conn, user.id, "reminder.set", "reminder", rid, ip=request_ip(request), kind=body.kind, new=True)
    conn.commit()
    return reminder_view(_reminder(conn, user.id, rid))


@router.patch("/{reminder_id}", response_model=ReminderOut)
def change_reminder(reminder_id: int, body: ReminderPatch, request: Request, user: CurrentUser,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_user(request, user)
    row = _reminder(conn, user.id, reminder_id)
    given = body.model_fields_set
    kind = body.kind if "kind" in given and body.kind is not None else row["kind"]
    meal = body.meal if "meal" in given else (row["meal"] if kind == "log_meal" else None)
    time_text = body.time if body.time is not None else row["time_local"]
    days = body.days if body.days is not None else row["days"]
    zone = body.time_zone if body.time_zone is not None else row["time_zone"]
    enabled = body.enabled if body.enabled is not None else bool(row["enabled"])
    _check(kind, meal, time_text, days, zone)
    # A new time or day may come round again today; anything else keeps today's "already sent".
    sent_on = row["last_sent_on"] if (time_text, days, zone) == (row["time_local"], row["days"], row["time_zone"]) else None
    conn.execute("UPDATE reminders SET kind = ?, meal = ?, time_local = ?, days = ?, time_zone = ?, enabled = ?, last_sent_on = ? "
                 "WHERE id = ? AND user_id = ?", (kind, meal, time_text, days, zone, int(enabled), sent_on, row["id"], user.id))
    audit(conn, user.id, "reminder.set", "reminder", row["id"], ip=request_ip(request), kind=kind, new=False)
    conn.commit()
    return reminder_view(_reminder(conn, user.id, row["id"]))


@router.delete("/{reminder_id}", status_code=204, response_class=Response)
def remove_reminder(reminder_id: int, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _require_on(request)
    row = _reminder(conn, user.id, reminder_id)
    conn.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (row["id"], user.id))
    audit(conn, user.id, "reminder.removed", "reminder", row["id"], ip=request_ip(request), kind=row["kind"])
    conn.commit()
    return Response(status_code=204)


@router.post("/subscriptions", response_model=DeviceOut, status_code=201)
def add_device(body: SubscriptionIn, request: Request, response: Response, user: CurrentUser,
               conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_user(request, user)
    endpoint = webpush.check_endpoint(body.endpoint)
    if endpoint is None:
        raise ApiProblem(400, BAD_ENDPOINT, field="endpoint")
    if webpush.check_keys(body.keys.p256dh, body.keys.auth) is None:
        raise ApiProblem(400, BAD_KEYS, field="keys")
    agent = (request.headers.get("user-agent") or "")[:USER_AGENT_LIMIT] or None
    row = conn.execute("SELECT * FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()
    if row is not None and row["user_id"] == user.id:  # the same browser again: keep the device, take the newest keys
        conn.execute("UPDATE push_subscriptions SET p256dh = ?, auth = ?, user_agent = ? WHERE id = ?",
                     (body.keys.p256dh, body.keys.auth, agent, row["id"]))
        conn.commit()
        response.status_code = 200
        return device_view(conn.execute("SELECT * FROM push_subscriptions WHERE id = ?", (row["id"],)).fetchone())
    count = conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?", (user.id,)).fetchone()[0]
    if count >= MAX_DEVICES:
        raise ApiProblem(409, TOO_MANY_DEVICES)
    if row is not None:  # another account signed in on this browser before: one browser, one subscription, so it moves here
        conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (row["id"],))
        audit(conn, row["user_id"], "reminder.device_removed", "push_subscription", row["id"], via="other_account")
    cur = conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (user.id, endpoint, body.keys.p256dh, body.keys.auth, agent, utcnow()))
    did = int(cur.lastrowid or 0)
    audit(conn, user.id, "reminder.device_added", "push_subscription", did, ip=request_ip(request))
    conn.commit()
    return device_view(conn.execute("SELECT * FROM push_subscriptions WHERE id = ?", (did,)).fetchone())


@router.delete("/subscriptions/{device_id}", status_code=204, response_class=Response)
def remove_device(device_id: int, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _require_on(request)
    cur = conn.execute("DELETE FROM push_subscriptions WHERE id = ? AND user_id = ?", (int(device_id), user.id))
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="Not Found")
    audit(conn, user.id, "reminder.device_removed", "push_subscription", int(device_id), ip=request_ip(request), via="person")
    conn.commit()
    return Response(status_code=204)


@router.post("/test", response_model=TestOut)
def send_test(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_user(request, user)
    devices = devices_of(conn, user.id)
    if not devices:
        raise ApiProblem(409, NO_DEVICES)
    auth_context(request).limits.take("reminders_test", user.id)
    settings = request.app.state.settings
    payload = webpush.message(title_of(conn, auth_context(request).store), TEST_BODY, f"{settings.public_url.rstrip('/')}/#settings")
    out = deliver(conn, sender(request), user.id, devices, payload)
    return {"devices": len(devices), "sent": out.sent, "failed": out.failed, "removed": out.removed}


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


def is_due(row: sqlite3.Row | dict[str, Any], now: datetime) -> str | None:
    """The local date (``YYYY-MM-DD``) when ``row`` should go out at ``now`` (an aware time), else ``None``."""
    zone = zone_of(row["time_zone"])
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    if not row["enabled"] or not int(row["days"]) & (1 << local.weekday()):
        return None
    match = TIME_RE.match(row["time_local"] or "")
    if match is None:
        return None
    late = local.hour * 60 + local.minute - (int(match.group(1)) * 60 + int(match.group(2)))
    today = local.date().isoformat()
    if not 0 <= late < WINDOW_MIN or row["last_sent_on"] == today:
        return None
    return today


def meal_logged(conn: sqlite3.Connection, user_id: int, day: str, meal: str) -> bool:
    return conn.execute("SELECT 1 FROM log_entries WHERE user_id = ? AND date = ? AND meal = ? AND status = 'eaten' LIMIT 1",
                        (int(user_id), day, meal)).fetchone() is not None


def run_due(conn: sqlite3.Connection, push: webpush.Sender, store: Any, public_url: str, now: datetime | None = None) -> int:
    """Send every reminder due at ``now``. Returns how many reminders went out (to at least one device)."""
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT r.* FROM reminders r JOIN users u ON u.id = r.user_id WHERE r.enabled = 1 AND u.status = 'active' "
        "AND COALESCE(u.is_test_account, 0) = 0 AND EXISTS (SELECT 1 FROM push_subscriptions p WHERE p.user_id = r.user_id)"
    ).fetchall()
    title = title_of(conn, store)
    sent = 0
    for row in rows:
        today = is_due(row, now)
        if today is None:
            continue
        # Claim it first: at most once a day, even with two workers or a crash while sending.
        claimed = conn.execute("UPDATE reminders SET last_sent_on = ? WHERE id = ? AND (last_sent_on IS NULL OR last_sent_on != ?)",
                               (today, row["id"], today)).rowcount
        conn.commit()
        if not claimed:
            continue
        if row["kind"] == "log_meal" and meal_logged(conn, row["user_id"], today, row["meal"]):
            continue
        devices = devices_of(conn, row["user_id"])
        if devices and deliver(conn, push, row["user_id"], devices, payload_for(public_url, title, row["kind"], row["meal"])).sent:
            sent += 1
    return sent


def _tick(app: Any) -> None:
    conn = connect(app.state.settings.db_path)
    try:
        run_due(conn, app.state.webpush, app.state.settings_store, app.state.settings.public_url or "")
    finally:
        conn.close()


async def loop(app: Any) -> None:
    """Once a minute, send what is due (in a worker thread; the server keeps answering requests). Started only when on."""
    from starlette.concurrency import run_in_threadpool

    await asyncio.sleep(FIRST_TICK_S)
    while True:
        try:
            await run_in_threadpool(_tick, app)
        except Exception:
            log.exception("reminders: the loop failed")
        await asyncio.sleep(TICK_S - datetime.now().second % TICK_S or TICK_S)
