"""How well each AI is doing: two signals for Server administration → AI providers (docs/ai.md "How well each AI is doing").

A model can be set up correctly and still be a poor fit. The owner's small local model answered "nothing fits" to almost every
meal-idea request, in about a second, and nothing in the app said so. This module puts two facts next to each routed feature:

1. **What happened in real use.** The last :data:`LAST_CALLS` calls (within :data:`WINDOW_DAYS` days, from all people) of the feature to
   the provider and model it uses now, read from ``ai_audit``. Counts only: no body, no user, no time. With at least
   :data:`MIN_CALLS` calls, :data:`WARN_PERCENT` percent or more without a usable result is a warning.
2. **What the live evaluation said.** The newest report for this provider, model and prompt version in ``AI_EVAL_REPORTS_DIR``
   (:mod:`app.ai.eval_reports`): passed, failed (which gates), or none.

Nothing here sends anything, takes quota or changes a setting. It reads the settings and the activity log only.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .. import brand
from ..config import Settings
from ..settings_store import SettingsStore
from . import config as K
from . import eval_reports as E
from . import routing as R
from .netpolicy import NetPolicy, PolicyError, parse_base_url
from .prompts import PROMPT_VERSION

log = logging.getLogger(f"{brand.LOGGER_NAME}.ai")

# --------------------------------------------------------------------------- #
# What happened in real use
# --------------------------------------------------------------------------- #

WINDOW_DAYS = 14  # only calls this recent count
LAST_CALLS = 20  # and only the newest of them
MIN_CALLS = 8  # fewer calls than this: show the counts, give no verdict
WARN_PERCENT = 70  # this share of the counted calls (or more) without a usable result is a warning

USABLE, NO_FIT, UNREAD, REFUSED, DROPPED, INVALID, ERROR = "usable", "no_fit", "unread", "refused", "dropped", "invalid", "error"
BUCKETS = (USABLE, NO_FIT, UNREAD, REFUSED, DROPPED, INVALID, ERROR)
UNUSABLE = BUCKETS[1:]

# The feature names ``ai_audit.feature`` holds for each routed feature (``routes._finish`` writes ``<feature>:<mode>`` for
# next-meal; ``_finish_chat`` writes ``chat``; the photo and lab routes write the prepared feature).
AUDIT_FEATURES: dict[str, tuple[str, ...]] = {
    "meal_ideas": ("next_meal", "next_meal:ideas", "next_meal:rerank", "next_meal:swap", "next_meal:plan"),
    "describe": ("parse_meal",),
    "photos": ("read_label", "plate"),
    "chat": ("chat",),
    "labs": ("read_lab_report",),
}

# What each feature's ``ai_audit.status`` means for the person, from what the code really writes:
#   guard.judge_*  (meal ideas)   ok | no_fit (the model said nothing fits) | dropped_all (the checks threw every idea out) | refused
#   features.prepare_parse_meal   ok | refused
#   features.label_draft          ok | not_a_label | unreadable
#   features.prepare_plate        ok | no_food | unsure
#   lab_report.judge              ok | no_results | not_a_lab_report | unreadable
#   chat._finish_chat             ok (and ``verdict.outcome``, below) | refused
# and for every feature (routes._verdict_of, _finish_chat): invalid (not the expected JSON, even after the repair turn), error
# (a judge that crashed) and error:<reason> (timeout, connection, HTTP). ``cached`` is not a call to the model: it is not counted.
OUTCOMES: dict[str, dict[str, str]] = {
    "meal_ideas": {"ok": USABLE, "no_fit": NO_FIT, "dropped_all": DROPPED, "refused": REFUSED},
    "describe": {"ok": USABLE, "refused": REFUSED},
    "photos": {"ok": USABLE, "not_a_label": UNREAD, "unreadable": UNREAD, "no_food": UNREAD, "unsure": UNREAD, "refused": REFUSED},
    "chat": {"ok": USABLE, "refused": REFUSED},
    "labs": {"ok": USABLE, "no_results": UNREAD, "not_a_lab_report": UNREAD, "unreadable": UNREAD, "refused": REFUSED},
}
# An Ask call that parsed (status ok) is a step: a tool call and a card to confirm are fine; so is the answer. What the app
# withheld (a dose or a number it could not check) is dropped by the checks; an empty answer, or no answer within the step limit,
# is the model failing the protocol.
CHAT_OUTCOMES = {"answer": USABLE, "call": USABLE, "confirm_save": USABLE, "withheld": DROPPED, "unfinished": INVALID, "error": INVALID}


def shown_of(verdict: Mapping[str, Any]) -> dict[str, int]:
    """``{"shown": n}`` for a checked list of items (a described meal, a plate photo): how many the person was offered.

    The activity row keeps it (a count, nothing else) so that "every item was dropped by the checks" can be told from "some
    were". Other verdicts have no such list or cannot be empty when ``ok``, and give ``{}``."""
    items = verdict.get("items")
    if verdict.get("status") == "ok" and isinstance(items, list):
        return {"shown": len(items)}
    return {}


def classify(feature: str, status: str, verdict: Mapping[str, Any] | None = None) -> str | None:
    """The bucket one activity row falls in, or None when it is not a call to count (``cached``, or a status this code does not know)."""
    if status == "cached":
        return None
    if status == "invalid":
        return INVALID
    if status == "error" or status.startswith("error:"):
        return ERROR
    verdict = verdict or {}
    if feature == "chat" and status == "ok":
        return CHAT_OUTCOMES.get(str(verdict.get("outcome")), USABLE)
    bucket = OUTCOMES.get(feature, {}).get(status)
    shown = verdict.get("shown")
    if bucket == USABLE and isinstance(shown, int) and not isinstance(shown, bool) and shown == 0:
        return DROPPED if verdict.get("dropped") else UNREAD  # ok, but nothing was left to show
    return bucket


def _verdict(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def live_counts(conn: sqlite3.Connection, *, feature: str, provider_id: int, model: str, now: datetime | None = None) -> dict[str, int]:
    """Counts of the newest calls of ``feature`` to ``provider_id`` and ``model``, by bucket (everyone's calls; nothing else is read).

    Only the status and the verdict of each row are read, never the request or the answer, and no user."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    names = AUDIT_FEATURES[feature]
    rows = conn.execute(
        f"""SELECT status, verdict_json FROM ai_audit
            WHERE provider_id = ? AND model = ? AND created_at >= ? AND status != 'cached' AND feature IN ({", ".join("?" for _ in names)})
            ORDER BY created_at DESC, id DESC LIMIT ?""",
        (int(provider_id), model, since, *names, LAST_CALLS)).fetchall()
    counts = {bucket: 0 for bucket in BUCKETS}
    for row in rows:
        bucket = classify(feature, str(row["status"]), _verdict(row["verdict_json"]))
        if bucket is not None:
            counts[bucket] += 1
    return counts


def warns(calls: int, unusable: int) -> bool:
    """Enough calls to judge, and :data:`WARN_PERCENT` percent or more of them without a usable result."""
    return calls >= MIN_CALLS and unusable * 100 >= WARN_PERCENT * calls


# What a person reads. ``noun`` completes "had no usable …"; ``consequence`` is what the app did instead, when that is certain;
# ``route`` completes "or route … to another AI".
WORDS: dict[str, dict[str, str]] = {
    "meal_ideas": {"noun": "idea", "route": "meal ideas", "consequence": "The app showed the rule results instead. "},
    "describe": {"noun": "result", "route": "describing a meal", "consequence": ""},
    "photos": {"noun": "result", "route": "photos", "consequence": ""},
    "chat": {"noun": "answer", "route": "Ask", "consequence": ""},
    "labs": {"noun": "result", "route": "lab report photos", "consequence": ""},
}
PART_TEXT = {NO_FIT: "{n} 'nothing fits'", UNREAD: "{n} could not read", REFUSED: "{n} refused", DROPPED: "{n} dropped by the checks",
             INVALID: "{n} invalid"}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _parts(counts: Mapping[str, int]) -> str:
    out = []
    for bucket in UNUSABLE:
        n = counts.get(bucket, 0)
        if not n:
            continue
        out.append(_plural(n, "error", "errors") if bucket == ERROR else PART_TEXT[bucket].format(n=n))
    return ", ".join(out)


def live_view(feature: str, label: str, model: str, counts: Mapping[str, int]) -> dict[str, Any]:
    """The live signal for one feature: the counts, a line that always reads well, and a warning when the rule says so."""
    calls = sum(counts.values())
    unusable = calls - counts.get(USABLE, 0)
    warn = warns(calls, unusable)
    if not calls:
        summary = f"No calls in the last {WINDOW_DAYS} days."
    else:
        tail = f", {_parts(counts)}" if unusable else ""
        summary = f"Last {_plural(calls, 'call', 'calls')} in {WINDOW_DAYS} days: {counts.get(USABLE, 0)} usable{tail}."
        if calls < MIN_CALLS:
            summary += f" Too few calls to judge ({MIN_CALLS} are needed)."
    message = None
    if warn:
        words = WORDS[feature]
        message = (f"{label}: {unusable} of the last {calls} calls to {model} had no usable {words['noun']} ({_parts(counts)}). "
                   f"{words['consequence']}Check this model with scripts/ai_eval.py, or route {words['route']} to another AI.")
    return {"calls": calls, "window_days": WINDOW_DAYS, "counts": dict(counts), "unusable": unusable, "warn": warn,
            "summary": summary, "message": message}


# --------------------------------------------------------------------------- #
# What the live evaluation said
# --------------------------------------------------------------------------- #

# Which of the report's gates say something about each feature. The report is about a model, not a feature, and a gate about
# another feature is not held against this one (the meal-idea rate says nothing about reading a label).
GATES_FOR: dict[str, tuple[str, ...]] = {
    "meal_ideas": ("schema_valid_rate", "next_meal_with_idea_rate", "p95_latency", "no_unsafe_text"),
    "describe": ("schema_valid_rate", "safety_refusal_rate", "p95_latency", "no_unsafe_text"),
    "photos": ("schema_valid_rate", "p95_latency", "no_unsafe_text"),
    "chat": ("chat_pass_rate", "chat_no_unsafe_text"),
}
# Gate → (what it measures, the share it needs). ``tests/test_ai_quality_reports.py`` keeps the shares equal to ``scripts/ai_eval.py``.
RATE_GATES: dict[str, tuple[str, int]] = {
    "schema_valid_rate": ("answers in the format the app expects", 95),
    "next_meal_with_idea_rate": ("meal-idea cases with at least one idea that passed the checks", 80),
    "safety_refusal_rate": ("dose and medicine questions refused", 90),
    "chat_pass_rate": ("Ask questions answered as expected", 80),
}
UNSAFE_GATES = {"no_unsafe_text": ("unsafe_text_shown", "unsafe text was shown"),
                "chat_no_unsafe_text": ("chat_unsafe_text_shown", "unsafe text was shown in Ask")}
NO_EVAL = "No ai_eval report for this model and prompt version."
LABS_TEXT = "Not covered by ai_eval; check a real report by hand (docs/maintainers.md)."


def gate_text(gate: str, report: E.Report) -> str:
    """A failed gate in plain words, with the number the report measured when it has one."""
    if gate in RATE_GATES:
        what, need = RATE_GATES[gate]
        value = report.metrics.get(gate)
        if value is None:
            return f"{what}: not measured in that run"
        return f"{what}: {int(value * 100)} % (needs {need} % or more)"
    if gate == "p95_latency":
        if report.p95_ms is None:
            return "answers were too slow, or their speed was not measured"
        limit = f" (the limit is {report.p95_limit_ms / 1000:.0f} s)" if report.p95_limit_ms else ""
        return f"the slowest answers took {report.p95_ms / 1000:.0f} s{limit}"
    if gate in UNSAFE_GATES:
        key, words = UNSAFE_GATES[gate]
        n = report.metrics.get(key)
        return f"{words} ({_plural(int(n), 'time', 'times')})" if n else words
    return gate.replace("_", " ")


def _version_key(version: str) -> tuple[int, ...] | None:
    """``2026-10-21.1`` → (2026, 10, 21, 1), or None for a version this cannot read."""
    try:
        day, _, step = version.partition(".")
        return (*(int(p) for p in day.split("-")), int(step or 0))
    except ValueError:
        return None


def _when(report: E.Report) -> str:
    return f" on {report.date}" if report.date else ""


def _evaluation(state: str, message: str, *, warn: bool = False, report: E.Report | None = None, failed: list[str] | None = None) -> dict[str, Any]:
    return {"state": state, "warn": warn, "message": message, "date": report.date if report else None,
            "prompt_version": report.prompt_version if report else None, "file": report.file if report else None,
            "failed": failed or [], "role": report.role if report else None, "upstream": report.upstream if report else None}


def evaluate(feature: str, ident: Mapping[str, Any], folder: E.Folder) -> dict[str, Any]:
    """The evaluation status of ``feature`` on the provider and model ``ident`` names (``preset``, ``host_port``, ``model``,
    ``vision_model``): one of ``passed``, ``failed``, ``none``, ``older`` (a report exists, for an older prompt version),
    ``not_covered`` (lab reports), ``off`` (a photo feature with no vision model), ``no_folder`` or ``unreadable_folder``."""
    photos = feature in ("photos", "labs")
    if photos and not ident["vision_model"]:
        return _evaluation("off", "No vision model is set for this AI, so photo reading is off.")
    if feature == "labs":
        return _evaluation("not_covered", LABS_TEXT)
    if not folder.configured:
        return _evaluation("no_folder", "No reports folder is set (AI_EVAL_REPORTS_DIR), so the evaluation cannot be checked.")
    if not folder.readable:
        return _evaluation("unreadable_folder", "The reports folder (AI_EVAL_REPORTS_DIR) cannot be read, so the evaluation cannot be checked.")
    found = E.matching(folder.reports, preset=ident["preset"], host_port=ident["host_port"], model=ident["model"],
                       vision_model=ident["vision_model"], photos=feature == "photos")
    if feature == "chat":  # the Ask questions are a separate run (--chat): a report without their gates says nothing about Ask
        with_chat = [r for r in found if "chat_pass_rate" in r.gates]
        if found and not with_chat:
            return _evaluation("none", f"{NO_EVAL} A report exists, but without the Ask questions: run scripts/ai_eval.py --chat.", warn=True)
        found = with_chat
    current = [r for r in found if r.prompt_version == PROMPT_VERSION]
    if current:
        report = current[0]
        failed = [g for g in GATES_FOR[feature] if report.gates.get(g) is not True]
        behind = f" It reached {report.upstream}." if report.upstream else ""
        if not failed:
            return _evaluation("passed", f"Passed ai_eval{_when(report)} (prompt version {report.prompt_version}).{behind}", report=report)
        words = [gate_text(g, report) for g in failed]
        return _evaluation("failed", f"Failed ai_eval{_when(report)}: {'; '.join(words)}.{behind}", warn=True, report=report, failed=failed)
    if found:
        report = found[0]
        mine, theirs = _version_key(PROMPT_VERSION), _version_key(report.prompt_version)
        kind = "an older" if mine is not None and theirs is not None and theirs < mine else "a different"
        return _evaluation("older", f"{NO_EVAL} The newest one{_when(report)} is for {kind} prompt version ({report.prompt_version}). "
                                    "Run scripts/ai_eval.py again.", warn=True, report=report)
    return _evaluation("none", f"{NO_EVAL} Run scripts/ai_eval.py with this model and put the report in the reports folder.", warn=True)


# --------------------------------------------------------------------------- #
# The answer of GET /api/admin/ai-quality
# --------------------------------------------------------------------------- #


def routed_row(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, policy: NetPolicy, feature: str) -> tuple[str, sqlite3.Row] | None:
    """``(route, provider row)`` for a feature that is on and has a usable shared provider, else None.

    The same choice as :func:`app.ai.routing.resolve_feature` makes for a person who uses the shared AI, without a person: for
    ``any`` the first usable shared provider; for ``local``, ``cloud`` and ``local_then_cloud`` the provider that holds the role
    (the local one first for ``local_then_cloud``). A person's own provider is theirs, not the server's, and is not rated here."""
    route = str(store.get(conn, R.route_key(feature)))
    if route == "off" or (feature in R.LOCAL_ONLY and route != "local"):
        return None
    if route == "any":
        row = next((r for r in K.shared_rows(conn) if K.usable(r)), None)
    else:
        role = "local" if route in ("local", R.FALLBACK_ROUTE) else route
        row = R.role_row(conn, store, settings, role)
        if row is not None and (not K.usable(row) or (role == "local" and not R.is_private(row, policy))):
            row = None
    return None if row is None else (route, row)


def _identity(feature: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """What a report is matched on, and the model whose calls are counted (the vision model for photos, as ``ai_audit.model`` holds)."""
    try:
        host_port: str | None = parse_base_url(row["base_url"]).host_port
        host = parse_base_url(row["base_url"]).display_host
    except PolicyError:
        host_port, host = None, str(row["base_url"])
    vision = row["vision_model"] or None
    model = (vision or "") if feature in ("photos", "labs") else row["model"]
    return {"preset": row["preset"], "host_port": host_port, "host": host, "model": row["model"], "vision_model": vision, "used": model}


def overview(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, policy: NetPolicy, *, now: datetime | None = None) -> dict[str, Any]:
    """``GET /api/admin/ai-quality``: per routed feature, the live counts and the evaluation status (see the module doc)."""
    enabled = bool(store.get(conn, "ai.enabled"))
    folder = E.load(settings.ai.eval_reports_dir) if enabled else E.Folder(configured=bool(settings.ai.eval_reports_dir))
    features: list[dict[str, Any]] = []
    for feature in R.FEATURES if enabled else ():
        picked = routed_row(conn, store, settings, policy, feature)
        if picked is None:
            continue
        route, row = picked
        ident = _identity(feature, row)
        label = R.LABEL[feature]
        counts = live_counts(conn, feature=feature, provider_id=int(row["id"]), model=ident["used"], now=now) if ident["used"] else {b: 0 for b in BUCKETS}
        features.append({
            "feature": feature, "label": label, "route": route,
            "provider": {"id": int(row["id"]), "label": row["label"], "preset": row["preset"], "host": ident["host"], "model": ident["used"] or None},
            "live": live_view(feature, label, ident["used"], counts),
            "evaluation": evaluate(feature, ident, folder),
        })
    return {"enabled": enabled, "window_days": WINDOW_DAYS, "last_calls": LAST_CALLS, "min_calls": MIN_CALLS, "warn_percent": WARN_PERCENT,
            "prompt_version": PROMPT_VERSION, "reports": folder.summary(), "features": features}


def startup_lines(data: Mapping[str, Any]) -> list[str]:
    """One warning per routed feature whose evaluation failed or is missing (only with ``AI_EVAL_REPORTS_DIR`` set), for the log.

    A feature that is off has no row and is never named. The live counts are not part of this: they need calls first."""
    reports = data["reports"]
    if not data["enabled"] or not reports["configured"]:
        return []
    lines = []
    if not reports["readable"]:
        lines.append("AI_EVAL_REPORTS_DIR is set but the folder cannot be read, so no model can be checked against ai_eval.")
    for item in data["features"]:
        evaluation = item["evaluation"]
        if evaluation["warn"]:
            provider = item["provider"]
            lines.append(f"{item['label']} uses {provider['model']} on {provider['label']} ({provider['host']}). {evaluation['message']}")
    return lines


def log_startup(conn: sqlite3.Connection, store: SettingsStore, settings: Settings, policy: NetPolicy) -> None:
    """Write :func:`startup_lines` to the log. Never raises: this is advice, and a start-up must not depend on it."""
    if not settings.ai.eval_reports_dir:
        return
    try:
        for line in startup_lines(overview(conn, store, settings, policy)):
            log.warning("AI quality: %s", line)
    except Exception:  # advice only: see the docstring
        log.exception("AI quality: the evaluation check at start-up failed")
