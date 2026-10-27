"""Reading the reports that ``scripts/ai_eval.py`` writes (docs/ai.md "How well each AI is doing").

``AI_EVAL_REPORTS_DIR`` names a folder, mounted read-only, that holds the ``*.json`` files of live evaluations. This module
reads them so that Server administration can say, for the AI a feature uses now, whether that model passed the evaluation
for this version of the prompts. It only reads, and it never fails the app: a missing folder, a file that is too big, a
symlink that points out of the folder or a file that is not a report is counted and left out.

What is read, and what is not:

* at most :data:`MAX_FILES` files whose names end in ``.json``, newest name first (the script starts a name with the date), each
  at most :data:`MAX_BYTES` bytes. A hidden name (starting with a dot) is not a report; Kubernetes puts its own bookkeeping
  folders there.
* a symlink is followed only when its target is inside the folder (a Kubernetes ConfigMap mount is made of such links). The
  target is opened with ``O_NOFOLLOW`` and must be a regular file, so a link swapped in after the check, a pipe or a device is
  refused too.
* of a report only the fields below are kept: the date, the prompt version, which provider and model it was for, the gates
  (name → passed), a few summary numbers, and how many calls it made. The ``calls`` themselves (outcomes per case) are never
  kept or returned.
* a report is shown by its file name only, never its path.
"""
from __future__ import annotations

import json
import math
import os
import stat
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Any, Mapping

from .netpolicy import PolicyError, parse_base_url

MAX_FILES = 200
MAX_BYTES = 1024 * 1024
MAX_ENTRIES = 5000  # directory entries looked at, so a folder with a million names cannot stall a request
IGNORED = ("malformed", "too_big", "outside_folder", "unreadable", "over_limit")

# The summary numbers a message may quote (all from ``report["summary"]`` except the limit); anything else is dropped.
METRICS = ("schema_valid_rate", "next_meal_with_idea_rate", "safety_refusal_rate", "unsafe_text_shown", "chat_pass_rate",
           "chat_unsafe_text_shown")


@dataclass
class Report:
    """One report, reduced to what the app needs."""

    file: str
    date: str | None  # YYYY-MM-DD
    prompt_version: str
    preset: str
    host_port: str | None  # of the provider's base_url, as ``host:port``
    model: str
    vision_model: str | None
    gates: dict[str, bool]
    metrics: dict[str, float]
    p95_ms: int | None
    p95_limit_ms: int | None
    calls: int
    role: str | None = None  # ``provider.role`` (local | cloud): written by newer versions of the script; shown, never needed
    upstream: str | None = None  # ``provider.upstream``: the model behind a proxy, when the script names it; shown, never needed

    @property
    def newest_first(self) -> tuple[str, str]:
        return (self.date or "", self.file)


@dataclass
class Folder:
    """What reading ``AI_EVAL_REPORTS_DIR`` found."""

    configured: bool
    readable: bool = False
    files: int = 0  # ``*.json`` files looked at (at most MAX_FILES)
    reports: list[Report] = field(default_factory=list)
    ignored: dict[str, int] = field(default_factory=lambda: {key: 0 for key in IGNORED})

    def summary(self) -> dict[str, Any]:
        """The part of the admin answer about the folder: counts only."""
        return {"configured": self.configured, "readable": self.readable, "files": self.files, "reports": len(self.reports),
                "ignored": dict(self.ignored)}


def load(path: str | None) -> Folder:
    """Read the folder ``path`` (``AI_EVAL_REPORTS_DIR``). Never raises."""
    if not path:
        return Folder(configured=False)
    folder = Folder(configured=True)
    try:
        root = os.path.realpath(path)
        names: list[str] = []
        with os.scandir(root) as entries:
            for seen, entry in enumerate(entries):
                if seen >= MAX_ENTRIES:
                    break
                if entry.name.endswith(".json") and not entry.name.startswith("."):
                    names.append(entry.name)
    except (OSError, ValueError):
        return folder
    folder.readable = True
    names.sort(reverse=True)
    folder.ignored["over_limit"] = max(0, len(names) - MAX_FILES)
    for name in names[:MAX_FILES]:
        folder.files += 1
        report, why = _read(root, name)
        if report is not None:
            folder.reports.append(report)
        elif why is not None:
            folder.ignored[why] += 1
    folder.reports.sort(key=lambda r: r.newest_first, reverse=True)
    return folder


def _read(root: str, name: str) -> tuple[Report | None, str | None]:
    """One file → ``(report, None)`` or ``(None, why it was left out)``."""
    try:
        real = os.path.realpath(os.path.join(root, name))
        if os.path.commonpath([root, real]) != root or real == root:
            return None, "outside_folder"
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(real, flags)
    except (OSError, ValueError):
        return None, "unreadable"
    try:
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None, "unreadable"
            if info.st_size > MAX_BYTES:
                return None, "too_big"
            data = handle.read(MAX_BYTES + 1)
    except OSError:
        return None, "unreadable"
    if len(data) > MAX_BYTES:
        return None, "too_big"
    try:
        parsed = json.loads(data.decode("utf-8"), parse_constant=_no_constants)
    except (ValueError, RecursionError):
        return None, "malformed"
    report = parse_report(name, parsed)
    return (report, None) if report is not None else (None, "malformed")


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def _text(value: Any, limit: int = 200) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= limit and value.isprintable() else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def parse_report(name: str, data: Any) -> Report | None:
    """A report from parsed JSON, or None when it is not one (wrong shape, missing fields, odd types)."""
    if not isinstance(data, Mapping):
        return None
    provider = data.get("provider")
    gates = data.get("gates")
    version = _text(data.get("prompt_version"), 64)
    if not isinstance(provider, Mapping) or not isinstance(gates, Mapping) or version is None:
        return None
    preset, model = _text(provider.get("preset"), 64), _text(provider.get("model"))
    if preset is None or model is None or not 0 < len(gates) <= 64:
        return None
    clean_gates: dict[str, bool] = {}
    for key, passed in gates.items():
        if _text(key, 64) is None or not isinstance(passed, bool):
            return None
        clean_gates[key] = passed
    vision = provider.get("vision_model")
    if vision in (None, ""):
        vision = None
    elif _text(vision) is None:
        return None
    base = provider.get("base_url")
    host_port = None
    if isinstance(base, str):
        try:
            host_port = parse_base_url(base).host_port
        except PolicyError:
            host_port = None
    elif base is not None:
        return None
    raw_date = data.get("date")
    day = None
    if isinstance(raw_date, str) and len(raw_date) >= 10:
        try:
            day = _date.fromisoformat(raw_date[:10]).isoformat()
        except ValueError:
            day = None
    summary = data.get("summary") if isinstance(data.get("summary"), Mapping) else {}
    metrics = {key: n for key in METRICS if (n := _number(summary.get(key))) is not None}
    latency = summary.get("latency_ms") if isinstance(summary.get("latency_ms"), Mapping) else {}
    p95, limit = _number(latency.get("p95")), _number(data.get("p95_limit_ms"))
    role = provider.get("role")
    upstream = _text(provider.get("upstream"), 120)
    calls = data.get("calls")
    return Report(
        file=_text(name, 120) or "report.json", date=day, prompt_version=version, preset=preset, host_port=host_port, model=model,
        vision_model=vision, gates=clean_gates, metrics=metrics, p95_ms=None if p95 is None else int(p95),
        p95_limit_ms=None if limit is None else int(limit), calls=len(calls) if isinstance(calls, list) else 0,
        role=role if role in ("local", "cloud") else None, upstream=upstream)


def matching(reports: list[Report], *, preset: str, host_port: str | None, model: str, vision_model: str | None,
             photos: bool) -> list[Report]:
    """The reports made for this provider and model, newest first.

    A report belongs to a provider when the preset, the ``host:port`` of the base URL and the model are the same; for a
    photo feature the vision model must be the same too (the golden photo cases run only when the script was given one).
    ``provider.role`` and ``provider.upstream`` take no part in the match."""
    found = [r for r in reports if r.preset == preset and r.host_port is not None and r.host_port == host_port and r.model == model
             and (not photos or r.vision_model == vision_model)]
    return sorted(found, key=lambda r: r.newest_first, reverse=True)
