"""``python -m app.healthcheck``: stdlib only, ignores HTTP(S)_PROXY, exits 0 only on a 200 from /healthz."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

from app import healthcheck

REPO = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(status: int) -> tuple[ThreadingHTTPServer, list[str]]:
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            seen.append(f"{self.path} host={self.headers.get('Host')}")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","foods":1}')

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


@pytest.fixture
def healthy() -> Iterator[tuple[int, list[str]]]:
    server, seen = serve(200)
    yield server.server_address[1], seen
    server.shutdown()
    server.server_close()


def test_ok_on_200(healthy):
    port, seen = healthy
    assert healthcheck.main([], env={"PORT": str(port)}) == 0
    assert seen == [f"/healthz host=127.0.0.1:{port}"]


def test_fails_on_error_status():
    server, _ = serve(503)
    try:
        assert healthcheck.main([], env={"PORT": str(server.server_address[1])}) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_fails_when_nothing_listens_or_port_is_bad():
    assert healthcheck.main([], env={"PORT": str(free_port())}) == 1
    assert healthcheck.main([], env={"PORT": "not-a-port"}) == 1


def test_module_ignores_proxy_settings_and_uses_only_the_stdlib(healthy):
    port, _ = healthy
    env = {**os.environ, "PORT": str(port), "PYTHONPATH": str(REPO),
           "HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "NO_PROXY": "", "no_proxy": ""}
    proc = subprocess.run([sys.executable, "-m", "app.healthcheck"], cwd=REPO, env=env, timeout=30)
    assert proc.returncode == 0
    probe = (
        "import sys, app.healthcheck; "
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('fastapi', 'starlette', 'pydantic', 'httpx', 'httpx2', 'uvicorn', 'cryptography')); "
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-c", probe], cwd=REPO, env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout.strip() == ""


def test_against_the_real_server(tmp_path):
    """uvicorn --no-proxy-headers serving the app; the probe passes the Host allowlist and the stack."""
    port = free_port()
    env = {**os.environ, "DATA_DIR": str(tmp_path / "data"), "PYTHONPATH": str(REPO), "PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--no-proxy-headers", "--no-server-header", "--log-level", "warning"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if healthcheck.main([], env={"PORT": str(port)}) == 0:
                break
            if proc.poll() is not None:
                pytest.fail(proc.stderr.read().decode() if proc.stderr else "server exited")
            time.sleep(0.2)
        else:
            pytest.fail("server did not become healthy")
        result = subprocess.run([sys.executable, "-m", "app.healthcheck"], cwd=REPO, env=env, timeout=30)
        assert result.returncode == 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    assert healthcheck.main([], env={"PORT": str(port)}) == 1
