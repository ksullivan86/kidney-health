"""The first signal of "How well each AI is doing" (``app/ai/quality.py``, docs/ai.md): what the last calls of a feature to the
AI it uses really gave.

Pinned down here: how every status the app writes to the AI activity log is read for each feature (usable or not, and which of
the six reasons), the thresholds at their edges (fewer than 8 calls: counts and no verdict; 70 % or more without a usable result
from 8 calls), the window (14 days) and the cap (the newest 20 calls), that only counts leave (no body, no user, no time), and
the words a person reads. No network."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app import db
from app.ai import quality as Q
from app.ai.quality import BUCKETS, DROPPED, ERROR, INVALID, NO_FIT, REFUSED, UNREAD, USABLE
from conftest import insert_users

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# The outcome mapping
# --------------------------------------------------------------------------- #

MEAL_IDEAS = [
    ("ok", {}, USABLE), ("no_fit", {}, NO_FIT), ("dropped_all", {}, DROPPED), ("refused", {}, REFUSED), ("invalid", {}, INVALID),
    ("error:timeout", {}, ERROR), ("error:http_5xx", {}, ERROR), ("error:dns_failed", {}, ERROR), ("error", {}, ERROR),
]
DESCRIBE = [
    ("ok", {}, USABLE),  # a row from before the count was kept
    ("ok", {"shown": 2, "dropped": []}, USABLE), ("ok", {"shown": 1, "dropped": [{"index": 1, "reason": "text_policy:url"}]}, USABLE),
    ("ok", {"shown": 0, "dropped": [{"index": 0, "reason": "text_policy:url"}]}, DROPPED),  # every item thrown out by the checks
    ("ok", {"shown": 0, "dropped": []}, UNREAD),  # the model listed no foods
    ("refused", {}, REFUSED), ("invalid", {}, INVALID), ("error:timeout", {}, ERROR),
]
PHOTOS = [
    ("ok", {}, USABLE), ("ok", {"shown": 0, "dropped": [{"index": 0, "reason": "text_policy:url"}]}, DROPPED),
    ("not_a_label", {}, UNREAD), ("unreadable", {}, UNREAD), ("no_food", {}, UNREAD), ("unsure", {}, UNREAD),
    ("refused", {}, REFUSED), ("invalid", {}, INVALID), ("error:http_4xx", {}, ERROR),
]
LABS = [
    ("ok", {}, USABLE), ("no_results", {}, UNREAD), ("not_a_lab_report", {}, UNREAD), ("unreadable", {}, UNREAD),
    ("refused", {}, REFUSED), ("invalid", {}, INVALID), ("error:timeout", {}, ERROR),
]
CHAT = [
    ("ok", {"outcome": "answer"}, USABLE), ("ok", {"outcome": "call", "tool_ok": True}, USABLE), ("ok", {"outcome": "confirm_save"}, USABLE),
    ("ok", {"outcome": "withheld", "reason": "number"}, DROPPED), ("ok", {"outcome": "unfinished", "reason": "step_limit"}, INVALID),
    ("ok", {"outcome": "error", "reason": "empty"}, INVALID),
    ("refused", {"outcome": "refused"}, REFUSED), ("invalid", {"outcome": "invalid"}, INVALID), ("error:timeout", {"outcome": "error"}, ERROR),
]


@pytest.mark.parametrize("feature, table", [("meal_ideas", MEAL_IDEAS), ("describe", DESCRIBE), ("photos", PHOTOS), ("labs", LABS), ("chat", CHAT)])
def test_each_features_statuses_read_the_way_the_code_writes_them(feature, table):
    for status, verdict, bucket in table:
        assert Q.classify(feature, status, verdict) == bucket, (feature, status, verdict)


def test_a_cached_row_is_not_a_call_and_an_unknown_status_is_left_out():
    for feature in Q.AUDIT_FEATURES:
        assert Q.classify(feature, "cached", {}) is None
        assert Q.classify(feature, "something_new", {}) is None
    assert Q.classify("describe", "no_fit", {}) is None  # "nothing fits" is a meal-idea answer; describe never writes it
    assert Q.classify("unknown_feature", "ok", {}) is None


def test_every_bucket_but_usable_counts_against_a_feature_and_the_features_match_the_routed_ones():
    from app.ai import routing as R

    assert BUCKETS[0] == USABLE and set(Q.UNUSABLE) == set(BUCKETS) - {USABLE}
    assert set(Q.AUDIT_FEATURES) == set(R.FEATURES) == set(Q.OUTCOMES) | {"labs"} == set(Q.WORDS)


def test_the_shown_count_is_a_number_of_items_and_nothing_else():
    assert Q.shown_of({"status": "ok", "items": [{"text": "a"}, {"text": "b"}], "dropped": []}) == {"shown": 2}
    assert Q.shown_of({"status": "ok", "items": []}) == {"shown": 0}
    assert Q.shown_of({"status": "refused", "items": []}) == {}
    assert Q.shown_of({"status": "ok", "ideas": [{"title": "x"}]}) == {}
    assert Q.shown_of({"status": "ok", "draft": {"name": "x"}}) == {}


# --------------------------------------------------------------------------- #
# The thresholds
# --------------------------------------------------------------------------- #


def test_the_numbers_are_the_documented_ones():
    assert (Q.WINDOW_DAYS, Q.LAST_CALLS, Q.MIN_CALLS, Q.WARN_PERCENT) == (14, 20, 8, 70)


@pytest.mark.parametrize("calls, unusable, expected", [
    (0, 0, False), (1, 1, False), (7, 7, False), (7, 6, False),  # fewer than 8 calls: never a verdict, however bad
    (8, 8, True), (8, 6, True), (8, 5, False),  # 8 calls: 75 % warns, 62.5 % does not
    (10, 7, True), (10, 6, False),  # exactly 70 % warns
    (100, 70, True), (100, 69, False),  # 70 % warns, 69 % does not
    (13, 9, False), (20, 14, True), (20, 13, False), (20, 0, False),
])
def test_a_warning_needs_eight_calls_and_seventy_percent(calls, unusable, expected):
    assert Q.warns(calls, unusable) is expected


def counts(**given: int) -> dict[str, int]:
    return {**{b: 0 for b in BUCKETS}, **given}


def test_seven_calls_show_the_counts_and_no_verdict():
    view = Q.live_view("meal_ideas", "Meal ideas", "kidney-text", counts(no_fit=7))
    assert view["calls"] == 7 and view["unusable"] == 7 and view["warn"] is False and view["message"] is None
    assert view["summary"] == "Last 7 calls in 14 days: 0 usable, 7 'nothing fits'. Too few calls to judge (8 are needed)."


def test_eight_calls_at_the_edge():
    quiet = Q.live_view("meal_ideas", "Meal ideas", "kidney-text", counts(usable=3, no_fit=5))  # 62 %
    assert quiet["warn"] is False and quiet["message"] is None and "Too few" not in quiet["summary"]
    loud = Q.live_view("meal_ideas", "Meal ideas", "kidney-text", counts(usable=2, no_fit=6))  # 75 %
    assert loud["warn"] is True and loud["message"].startswith("Meal ideas: 6 of the last 8 calls to kidney-text had no usable idea")
    edge = Q.live_view("meal_ideas", "Meal ideas", "kidney-text", counts(usable=3, no_fit=7))  # exactly 70 %
    assert edge["warn"] is True and edge["unusable"] == 7


def test_the_warning_reads_like_the_example_and_names_what_to_do():
    view = Q.live_view("meal_ideas", "Meal ideas", "kidney-text", counts(usable=1, no_fit=8, invalid=1))
    assert view["message"] == ("Meal ideas: 9 of the last 10 calls to kidney-text had no usable idea (8 'nothing fits', 1 invalid). "
                               "The app showed the rule results instead. Check this model with scripts/ai_eval.py, "
                               "or route meal ideas to another AI.")
    assert view["summary"] == "Last 10 calls in 14 days: 1 usable, 8 'nothing fits', 1 invalid."


def test_every_reason_has_plain_words_and_only_the_ones_that_happened_are_named():
    view = Q.live_view("photos", "Photos (labels and plates)", "llava", counts(unread=2, refused=1, dropped=3, invalid=1, error=1))
    assert view["message"] == ("Photos (labels and plates): 8 of the last 8 calls to llava had no usable result "
                               "(2 could not read, 1 refused, 3 dropped by the checks, 1 invalid, 1 error). "
                               "Check this model with scripts/ai_eval.py, or route photos to another AI.")
    assert "nothing fits" not in view["message"] and "The app showed" not in view["message"]  # no claim about what the app did instead
    two = Q.live_view("chat", "Ask", "m", counts(error=8))
    assert "(8 errors)" in two["message"] and "route Ask to another AI" in two["message"] and "no usable answer" in two["message"]


def test_no_calls_at_all():
    view = Q.live_view("describe", "Describe a meal", "m", counts())
    assert view["calls"] == 0 and view["warn"] is False and view["summary"] == "No calls in the last 14 days."


# --------------------------------------------------------------------------- #
# The window, the cap and what is read
# --------------------------------------------------------------------------- #


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    path.parent.mkdir(parents=True)
    db.init_db(path)
    c = db.connect(path)
    insert_users(c, [(1, "admin"), (2, "sam")])
    c.commit()
    yield c
    c.close()


def stamp(days_ago: float = 0.0, minutes: int = 0) -> str:
    return (NOW - timedelta(days=days_ago, minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def audit(conn, *, status: str = "ok", feature: str = "next_meal:ideas", provider: int = 7, model: str = "m", user: int = 1, at: str | None = None,
          verdict: dict[str, Any] | None = None, request: Any = None, response: str | None = None) -> None:
    conn.execute(
        """INSERT INTO ai_audit (user_id, created_at, feature, provider_id, model, destination_host, prompt_version, request_json,
                                 response_text, verdict_json, latency_ms, status) VALUES (?, ?, ?, ?, ?, 'h:1', 'v', ?, ?, ?, 10, ?)""",
        (user, at or stamp(), feature, provider, model, None if request is None else json.dumps(request), response,
         json.dumps(verdict or {}), status))
    conn.commit()


def count(conn, feature: str = "meal_ideas", provider: int = 7, model: str = "m") -> dict[str, int]:
    return Q.live_counts(conn, feature=feature, provider_id=provider, model=model, now=NOW)


def test_only_the_newest_twenty_calls_count(conn):
    for i in range(5):
        audit(conn, status="no_fit", at=stamp(minutes=100 + i))  # the oldest five
    for i in range(20):
        audit(conn, status="ok", at=stamp(minutes=i))  # the newest twenty
    assert count(conn) == counts(usable=20)
    audit(conn, status="refused", at=stamp(minutes=-1))  # a newer one pushes the oldest usable one out
    assert count(conn) == counts(usable=19, refused=1)


def test_only_the_last_fourteen_days_count(conn):
    audit(conn, status="no_fit", at=stamp(days_ago=14, minutes=1))  # just outside
    audit(conn, status="no_fit", at=stamp(days_ago=30))
    audit(conn, status="ok", at=stamp(days_ago=13.9))  # inside
    audit(conn, status="invalid", at=stamp(days_ago=1))
    assert count(conn) == counts(usable=1, invalid=1)


def test_a_call_is_counted_for_its_feature_provider_and_model_only(conn):
    audit(conn, status="no_fit")
    audit(conn, status="ok", provider=8)  # another provider
    audit(conn, status="ok", model="other-model")  # another model
    audit(conn, status="ok", feature="parse_meal")  # another feature
    audit(conn, status="ok", feature="chat")
    audit(conn, status="cached")  # not a call to the model
    for mode in ("rerank", "swap", "plan"):  # every meal-idea mode is the same feature
        audit(conn, status="ok", feature=f"next_meal:{mode}")
    audit(conn, status="ok", feature="next_meal")
    assert count(conn) == counts(usable=4, no_fit=1)
    assert count(conn, "describe") == counts(usable=1)
    assert count(conn, "chat") == counts(usable=1)
    assert count(conn, "meal_ideas", provider=9) == counts()


def test_everyones_calls_count_together(conn):
    audit(conn, status="no_fit", user=1)
    audit(conn, status="no_fit", user=2)
    audit(conn, status="ok", user=2)
    assert count(conn) == counts(usable=1, no_fit=2)


def test_the_item_count_decides_between_usable_and_dropped_for_a_described_meal(conn):
    audit(conn, feature="parse_meal", verdict={"status": "ok", "shown": 0, "dropped": [{"index": 0, "reason": "text_policy:url"}]})
    audit(conn, feature="parse_meal", verdict={"status": "ok", "shown": 2, "dropped": []})
    audit(conn, feature="parse_meal", verdict={"status": "ok"})
    assert count(conn, "describe") == counts(usable=2, dropped=1)


def test_a_row_with_a_broken_verdict_still_counts_by_its_status(conn):
    conn.execute("INSERT INTO ai_audit (user_id, created_at, feature, provider_id, model, destination_host, prompt_version, verdict_json, status) "
                 "VALUES (1, ?, 'next_meal:ideas', 7, 'm', 'h:1', 'v', 'not json', 'no_fit')", (stamp(),))
    conn.commit()
    assert count(conn) == counts(no_fit=1)


def test_only_counts_are_read_never_a_body_or_a_person(conn):
    secret = "zebra-marker-4417"
    for i in range(10):
        audit(conn, status="no_fit", user=1 + i % 2, request={"messages": [{"role": "user", "content": secret}]}, response=secret,
              verdict={"status": "no_fit", "note": secret})
    result = count(conn)
    assert result == counts(no_fit=10) and all(isinstance(v, int) for v in result.values())
    view = Q.live_view("meal_ideas", "Meal ideas", "m", result)
    text = json.dumps(view)
    assert secret not in text and "user" not in text.lower().replace("usable", "") and set(view) == {
        "calls", "window_days", "counts", "unusable", "warn", "summary", "message"}
    import inspect

    source = inspect.getsource(Q.live_counts)  # the query names the status and the verdict, nothing else
    assert "SELECT status, verdict_json FROM ai_audit" in source and "request_json" not in source and "response_text" not in source
    assert "user_id" not in source
