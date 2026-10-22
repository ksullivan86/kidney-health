#!/usr/bin/env python3
"""Write docs/api/openapi.json: the app's OpenAPI document, checked in (design note 14 change 2; docs/api/README.md).

    python scripts/gen_openapi.py           # rewrite the file
    python scripts/gen_openapi.py --check   # exit 1 (with a short summary of what differs) when the committed file is stale

The document is what ``create_app()`` serves at ``/openapi.json`` (that URL stays off unless ``ENABLE_API_DOCS``; this script does not need
it), built in this process with a temporary ``DATA_DIR``: no server is started, no network is used, nothing is written but the file.
Keys are sorted, the indent is two spaces and the file ends with a newline, so the same routes always give the same bytes.

Changed a route, a model or a status code? Run this, look at the diff, commit the file with the change. ``tests/test_openapi_snapshot.py``
runs the check, so a stale file fails the suite (and the API version rule in docs/api/README.md says when to raise it).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "api" / "openapi.json"
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
# What a command-line run keeps of the caller's environment: the document does not depend on any setting, and a half-configured shell
# (AUTH_MODE=proxy without its secrets, a bad INSTANCE_NAME) must not stop it from being written.
_KEEP_ENV = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "VIRTUAL_ENV", "PYTHONPATH",
             "PYTHONHOME", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"}


def _shown(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def build_document() -> dict[str, Any]:
    """The OpenAPI document of a fresh app (default settings, a temporary data directory that is never created)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.config import Settings
    from app.main import create_app

    with tempfile.TemporaryDirectory(prefix="kh-openapi-") as tmp:
        app = create_app(Settings(data_dir=Path(tmp) / "data", log_level="WARNING"))
        return json.loads(json.dumps(app.openapi()))


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def operations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{"GET /api/meta": operation}``."""
    return {
        f"{method.upper()} {path}": op
        for path, item in document.get("paths", {}).items()
        for method, op in item.items()
        if method in METHODS
    }


def summarize(old: dict[str, Any], new: dict[str, Any], limit: int = 25) -> list[str]:
    """A few lines on what differs between the committed document (``old``) and the current one (``new``)."""
    lines: list[str] = []
    old_ops, new_ops = operations(old), operations(new)
    for key in sorted(new_ops.keys() - old_ops.keys()):
        lines.append(f"+ operation {key} ({new_ops[key].get('operationId')})")
    for key in sorted(old_ops.keys() - new_ops.keys()):
        lines.append(f"- operation {key} ({old_ops[key].get('operationId')})")
    for key in sorted(old_ops.keys() & new_ops.keys()):
        if old_ops[key] == new_ops[key]:
            continue
        before, after = old_ops[key], new_ops[key]
        if before.get("operationId") != after.get("operationId"):
            lines.append(f"~ operation {key}: id {before.get('operationId')} -> {after.get('operationId')}")
            continue
        parts = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        lines.append(f"~ operation {key}: changed {', '.join(parts)}")
    for section in sorted(set(old.get("components", {})) | set(new.get("components", {}))):
        was, now = old.get("components", {}).get(section, {}), new.get("components", {}).get(section, {})
        for name in sorted(now.keys() - was.keys()):
            lines.append(f"+ components.{section}.{name}")
        for name in sorted(was.keys() - now.keys()):
            lines.append(f"- components.{section}.{name}")
        for name in sorted(was.keys() & now.keys()):
            if was[name] != now[name]:
                lines.append(f"~ components.{section}.{name}")
    for key in sorted((old.keys() | new.keys()) - {"paths", "components"}):
        if old.get(key) != new.get(key):
            lines.append(f"~ {key}")
    if len(lines) > limit:
        lines = lines[:limit] + [f"... and {len(lines) - limit} more"]
    return lines


def check(path: Path = OUT, document: dict[str, Any] | None = None) -> list[str]:
    """Empty when ``path`` holds exactly the current document; otherwise the lines that say why."""
    document = build_document() if document is None else document
    if not path.is_file():
        return [f"{path} does not exist"]
    committed = path.read_text(encoding="utf-8")
    if committed == render(document):
        return []
    try:
        lines = summarize(json.loads(committed), document)
    except ValueError:
        return [f"{path} is not valid JSON"]
    return lines or ["the content is the same but the formatting differs (sorted keys, 2-space indent, a trailing newline)"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args(argv)
    document = build_document()
    if args.check:
        problems = check(OUT, document)
        if problems:
            print(f"{_shown(OUT)} is stale:", file=sys.stderr)
            for line in problems:
                print(f"  {line}", file=sys.stderr)
            print("run: python scripts/gen_openapi.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(document), encoding="utf-8")
    print(f"wrote {_shown(OUT)} ({len(operations(document))} operations)")
    return 0


def _hermetic_environment(data_dir: str) -> None:
    """A command-line run: drop the caller's settings from the environment before the app is imported (``app.main`` builds an app at
    import time) and point ``DATA_DIR`` at a temporary directory. The tests call :func:`build_document` in-process and skip this."""
    kept = {k: v for k, v in os.environ.items() if k in _KEEP_ENV or k.startswith("LC_")}
    os.environ.clear()
    os.environ.update(kept)
    os.environ["DATA_DIR"] = data_dir
    os.environ["LOG_LEVEL"] = "WARNING"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="kh-openapi-env-") as scratch:
        _hermetic_environment(scratch)
        status = main()
    raise SystemExit(status)
