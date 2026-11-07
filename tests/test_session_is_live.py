"""One rule for a live session: sessions.validate and a device sign-in finishing under a write lock both use it."""
from datetime import datetime, timedelta, timezone

import pytest

from app.auth import clock, sessions

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def info(*, seen_days_ago: float, expires_in_days: float) -> sessions.SessionInfo:
    return sessions.SessionInfo(id="s", user_id=1, created_at=clock.iso(NOW - timedelta(days=30)),
                                last_seen_at=clock.iso(NOW - timedelta(days=seen_days_ago)),
                                expires_at=clock.iso(NOW + timedelta(days=expires_in_days)), reauth_at=None,
                                user_agent=None, ip_prefix=None)


@pytest.mark.parametrize("seen, expires, live", [
    (0, 1, True),            # in use, not expired
    (13.9, 1, True),         # just inside a 14-day idle limit
    (14, 1, False),          # idle too long
    (0, 0, False),           # the absolute limit reached
    (0, -1, False),          # past it
])
def test_a_session_is_live_only_inside_both_limits(seen, expires, live):
    assert sessions.is_live(info(seen_days_ago=seen, expires_in_days=expires), idle_days=14, now=NOW) is live


def test_the_device_sign_in_check_uses_the_same_rule():
    import inspect

    from app.devices import api
    assert "sessions.is_live(" in inspect.getsource(api._person_still_current)
