"""A tiny in-process SMTP server for the email tests (design note 34). Standard library only, on 127.0.0.1, no TLS.

``FakeSmtp`` keeps every message it accepted (``messages``: ``{mail_from, rcpt, data, auth}``). Options: ``users`` (AUTH PLAIN and
LOGIN check these), ``refuse`` (recipients answered with 550), ``greeting_delay`` (seconds before the greeting, for deadlines).
It never offers STARTTLS, so a client that asks for it fails the way it should against such a server.
"""
from __future__ import annotations

import base64
import socketserver
import threading
import time
from typing import Any


class _Handler(socketserver.StreamRequestHandler):
    server: "_Server"

    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("ascii"))
        self.wfile.flush()

    def _line(self) -> str | None:
        raw = self.rfile.readline(65536)
        if not raw:
            return None
        return raw.decode("utf-8", "replace").rstrip("\r\n")

    def _check(self, user: str, password: str) -> bool:
        ok = self.server.fake.users.get(user) == password
        self.auth = user if ok else None
        return ok

    def handle(self) -> None:  # noqa: C901 - one small state machine
        fake = self.server.fake
        if fake.greeting_delay:
            time.sleep(fake.greeting_delay)
        self.auth: str | None = None
        mail_from, rcpt = None, []
        self._send("220 fake.smtp ESMTP ready")
        while True:
            line = self._line()
            if line is None:
                return
            verb = line.split(" ", 1)[0].upper()
            arg = line[len(verb):].strip()
            if verb == "EHLO":
                fake.ehlo_names.append(arg)
                self._send("250-fake.smtp")
                if fake.users:
                    self._send("250-AUTH PLAIN LOGIN")
                self._send("250 8BITMIME")
            elif verb == "HELO":
                self._send("250 fake.smtp")
            elif verb == "AUTH":
                parts = arg.split()
                if parts and parts[0].upper() == "PLAIN":
                    blob = parts[1] if len(parts) > 1 else None
                    if blob is None:
                        self._send("334 ")
                        blob = self._line() or ""
                    _, user, password = base64.b64decode(blob).decode("utf-8").split("\0", 2)
                elif parts and parts[0].upper() == "LOGIN":
                    self._send("334 " + base64.b64encode(b"Username:").decode())
                    user = base64.b64decode(self._line() or "").decode("utf-8")
                    self._send("334 " + base64.b64encode(b"Password:").decode())
                    password = base64.b64decode(self._line() or "").decode("utf-8")
                else:
                    self._send("504 unknown mechanism")
                    continue
                self._send("235 ok" if self._check(user, password) else "535 authentication failed")
            elif verb == "MAIL":
                if fake.users and self.auth is None:
                    self._send("530 authentication required")
                    continue
                mail_from, rcpt = arg.partition(":")[2].strip().strip("<>").split(">")[0], []
                self._send("250 ok")
            elif verb == "RCPT":
                address = arg.partition(":")[2].strip().strip("<>").split(">")[0]
                if address in fake.refuse:
                    self._send("550 no such user")
                    continue
                rcpt.append(address)
                self._send("250 ok")
            elif verb == "DATA":
                self._send("354 go ahead")
                lines = []
                while True:
                    part = self._line()
                    if part is None:
                        return
                    if part == ".":
                        break
                    lines.append(part[1:] if part.startswith("..") else part)
                with fake.lock:
                    fake.messages.append({"mail_from": mail_from, "rcpt": list(rcpt), "data": "\n".join(lines), "auth": self.auth})
                self._send("250 queued")
            elif verb in ("RSET", "NOOP"):
                self._send("250 ok")
            elif verb == "QUIT":
                self._send("221 bye")
                return
            else:
                self._send("502 not implemented")


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    fake: "FakeSmtp"


class FakeSmtp:
    def __init__(self, *, users: dict[str, str] | None = None, refuse: set[str] | None = None, greeting_delay: float = 0) -> None:
        self.users = dict(users or {})
        self.refuse = set(refuse or ())
        self.greeting_delay = greeting_delay
        self.messages: list[dict[str, Any]] = []
        self.ehlo_names: list[str] = []
        self.lock = threading.Lock()
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.fake = self
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, name="fake-smtp", daemon=True)

    def __enter__(self) -> "FakeSmtp":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    def wait(self, count: int, timeout: float = 5.0) -> list[dict[str, Any]]:
        """The messages once at least ``count`` arrived (or what there is after ``timeout`` seconds)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if len(self.messages) >= count:
                    return list(self.messages)
            time.sleep(0.02)
        with self.lock:
            return list(self.messages)
