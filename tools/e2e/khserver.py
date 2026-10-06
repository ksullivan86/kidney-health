"""Shared helpers for the end-to-end harnesses: run the real server and sign in to it.

Used by ``parity.py``, ``sandbox.py`` and ``regress.py`` in this directory (see README.md). Nothing
here is imported by the app or the test suite.

* :class:`Server` starts ``uvicorn app.main:app`` with a fresh ``DATA_DIR`` and the image's flags
  (``--no-proxy-headers --no-server-header``), waits for ``/healthz`` and stops the whole process group.
* :func:`setup_code` reads the one-time first-run code from the server log (the line
  ``FIRST-RUN SETUP: open .../#/setup and enter the code XXXX-XXXX-XXXX-XXXX``).
* :class:`Api` is a small JSON client that sends the headers the app's CSRF checks require
  (``X-Requested-With: kidney-health`` and a same-origin ``Origin``) and keeps the session cookie.
* :func:`first_admin` finishes first-run setup; :func:`invite_user` registers a second person.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx2

REPO = Path(__file__).resolve().parents[2]

# A password that passes the policy (15+ characters, not on the blocklist, not a keyboard run).
DEFAULT_PASSWORD = "plum kettle orbit 7 lantern"
SETUP_LINE = re.compile(r"FIRST-RUN SETUP: open .+? and enter the code ([A-Z2-7]{4}(?:-[A-Z2-7]{4}){3})")

# Settings the harness owns; anything else from the caller's environment passes through.
_CLEARED_ENV = (
    "APP_PASSWORD", "APP_PASSWORD_FILE", "ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_PASSWORD_FILE",
    "USDA_API_KEY", "USDA_API_KEY_FILE", "FOODS_JSON", "AUTH_MODE", "PUBLIC_URL", "SECRET_KEY",
    "SECRET_KEY_FILE", "TRUSTED_PROXIES", "TRUSTED_PROXY_SECRET", "TRUSTED_PROXY_SECRET_FILE",
)


def free_dir(path: Path) -> Path:
    """Empty ``path`` (created if missing). Refuses paths inside the repository's app/ or data/."""
    path = path.resolve()
    for protected in (REPO / "app", REPO / "data", REPO / "tests"):
        if path == protected or protected in path.parents:
            raise SystemExit(f"refusing to wipe {path}: pick a scratch directory")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


class Server:
    """``uvicorn app.main:app`` on 127.0.0.1:<port> with its own DATA_DIR and log file."""

    def __init__(self, port: int, data_dir: Path, *, log_path: Path | None = None, env: dict[str, str] | None = None,
                 python: str | None = None, repo: Path = REPO, fresh: bool = True, host: str = "127.0.0.1") -> None:
        self.port = port
        self.host = host
        self.data_dir = free_dir(data_dir) if fresh else data_dir
        self.log_path = log_path or self.data_dir.with_name(self.data_dir.name + "-server.log")
        self.extra_env = dict(env or {})
        self.python = python or sys.executable
        self.repo = repo
        self.proc: subprocess.Popen | None = None

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, timeout: float = 60) -> "Server":
        env = {k: v for k, v in os.environ.items() if k not in _CLEARED_ENV}
        env.update(DATA_DIR=str(self.data_dir), PYTHONDONTWRITEBYTECODE="1", **self.extra_env)
        log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [self.python, "-m", "uvicorn", "app.main:app", "--host", self.host, "--port", str(self.port),
             "--no-proxy-headers", "--no-server-header"],
            cwd=self.repo, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        deadline = time.time() + timeout
        last: Exception | None = None
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited with {self.proc.returncode}:\n{self.log()}")
            try:
                if httpx2.get(f"{self.base}/healthz", timeout=2).status_code == 200:
                    return self
            except httpx2.HTTPError as exc:
                last = exc
            time.sleep(0.25)
        self.stop()
        raise RuntimeError(f"{self.base} did not come up: {last}\n{self.log()}")

    def log(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=5)

    def __enter__(self) -> "Server":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def setup_code(server: Server, timeout: float = 20) -> str:
    """The newest first-run setup code in the server log."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        codes = SETUP_LINE.findall(server.log())
        if codes:
            return codes[-1]
        time.sleep(0.2)
    raise RuntimeError(f"no FIRST-RUN SETUP line in {server.log_path}")


class ApiError(RuntimeError):
    def __init__(self, response: httpx2.Response) -> None:
        self.response = response
        super().__init__(f"{response.request.method} {response.request.url.path} -> {response.status_code} {response.text[:300]}")


class Api:
    """JSON client for one person (one cookie jar). ``call`` returns the response; ``json`` raises on errors."""

    def __init__(self, base: str, *, headers: dict[str, str] | None = None, **client_kw: Any) -> None:
        self.base = base
        hdrs = {"X-Requested-With": "kidney-health", "Origin": base}
        hdrs.update(headers or {})
        client_kw.setdefault("timeout", 60)
        self.client = httpx2.Client(base_url=base, headers=hdrs, trust_env=False, **client_kw)

    def call(self, method: str, path: str, body: Any = None, **kw: Any) -> httpx2.Response:
        if body is not None:
            kw["json"] = body
        return self.client.request(method, path, **kw)

    def json(self, method: str, path: str, body: Any = None, **kw: Any) -> Any:
        r = self.call(method, path, body, **kw)
        if r.status_code >= 400:
            raise ApiError(r)
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else None

    def login(self, username: str, password: str = DEFAULT_PASSWORD) -> dict:
        return self.json("POST", "/api/auth/login", {"username": username, "password": password})

    def cookies(self) -> dict[str, str]:
        return dict(self.client.cookies.items())

    def close(self) -> None:
        self.client.close()


def first_admin(server: Server, username: str = "mum", password: str = DEFAULT_PASSWORD, *,
                display_name: str | None = None, off_enabled: bool = False) -> Api:
    """Finish first-run setup with the logged code; returns the admin's signed-in client."""
    api = Api(server.base)
    body = {"code": setup_code(server), "username": username, "password": password, "off_enabled": off_enabled}
    if display_name:
        body["display_name"] = display_name
    api.json("POST", "/api/auth/setup", body)
    return api


def invite_token(admin: Api, role: str = "user") -> str:
    """Create an invite as ``admin``; returns the token from the ``/#/invite/<token>`` link."""
    url = admin.json("POST", "/api/admin/invites", {"role": role})["url"]
    return url.rsplit("/", 1)[-1]


def invite_user(server: Server, admin: Api, username: str, password: str = DEFAULT_PASSWORD, *, role: str = "user") -> Api:
    api = Api(server.base)
    api.json("POST", "/api/auth/register", {"token": invite_token(admin, role), "username": username, "password": password})
    return api


def chromium_executable() -> str | None:
    """A pre-installed Playwright Chromium (``PLAYWRIGHT_CHROMIUM`` or ``/opt/pw-browsers``), else None
    (Playwright's own download is used)."""
    explicit = os.environ.get("PLAYWRIGHT_CHROMIUM")
    if explicit:
        return explicit
    roots = sorted(Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")).glob("chromium-*/chrome-linux*/chrome"))
    return str(roots[-1]) if roots else None
