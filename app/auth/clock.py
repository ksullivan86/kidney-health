"""The clock every auth module reads (tests replace :func:`now` with a fake clock).

Timestamps are stored as ISO-8601 UTC strings with microseconds and a ``Z`` suffix (the same
format as :func:`app.db.utcnow`), so they compare correctly as text in SQL.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def now() -> datetime:
    """Current UTC time (monkeypatch ``app.auth.clock.now`` in tests)."""
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO_FORMAT)


def now_iso() -> str:
    return iso(now())


def parse(value: str | None) -> datetime | None:
    """Parse a stored timestamp (``None`` and malformed values give ``None``)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def seconds() -> float:
    """``now()`` as a POSIX timestamp, for the in-memory limiters (follows a faked clock)."""
    return now().timestamp()


def later(**delta: float) -> datetime:
    return now() + timedelta(**delta)
