"""Dependency policy (note 01 §5.1, note 04 F14, note 07 §4.2): httpx2 only, hash-locked requirements."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_no_module_imports_httpx():
    pattern = re.compile(r"^\s*(import httpx\b(?!2)|from httpx\b(?!2))", re.M)
    offenders = [
        str(path.relative_to(REPO))
        for folder in ("app", "tests", "scripts", "tools")
        for path in (REPO / folder).rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def requirement_names(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def test_locks_pin_every_package_with_hashes():
    for name in ("requirements.lock", "requirements-dev.lock"):
        text = (REPO / name).read_text(encoding="utf-8")
        blocks = [b for b in re.split(r"\n(?=[A-Za-z0-9])", text) if re.match(r"^[A-Za-z0-9]", b)]
        assert blocks, name
        for block in blocks:
            assert "==" in block.splitlines()[0], block.splitlines()[0]
            assert "--hash=sha256:" in block, block.splitlines()[0]


def test_runtime_lock_contents():
    pins = requirement_names(REPO / "requirements.lock")
    assert pins["cryptography"] == "50.0.2"
    for needed in ("fastapi", "starlette", "uvicorn", "pydantic", "httpx2", "h11"):
        assert needed in pins, needed
    for unwanted in ("httpx", "httpcore", "python-multipart", "argon2-cffi", "openai", "uvloop", "httptools", "watchfiles", "websockets", "pytest"):
        assert unwanted not in pins, unwanted
    major, minor, *_ = (int(x) for x in pins["h11"].split("."))
    assert (major, minor) >= (0, 16)
    dev = requirement_names(REPO / "requirements-dev.lock")
    assert "pytest" in dev
    assert all(dev[name] == version for name, version in pins.items()), "dev lock must use the runtime pins"


def test_requirements_in_has_no_uvicorn_extras_and_txt_points_at_the_lock():
    text = (REPO / "requirements.in").read_text(encoding="utf-8")
    assert re.search(r"^uvicorn(?!\[)", text, re.M) and "uvicorn[" not in text
    assert "-r requirements.lock" in (REPO / "requirements.txt").read_text(encoding="utf-8")
    assert "-r requirements-dev.lock" in (REPO / "requirements-dev.txt").read_text(encoding="utf-8")
