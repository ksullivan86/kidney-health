"""Email for password resets (design note 34): the three plain-text emails and how they are sent.

The server sends email only to the mail server the person who runs it set (``SMTP_HOST``, env only), never to a host taken from
a request, so this is not the SSRF-checked HTTP transport of :mod:`app.egress`. Only the recipient comes from a person, and it is
checked first (:func:`check_address`: plain ASCII, no spaces, no line breaks, at most 320 characters).

Sending uses the standard library (``smtplib``) with verified TLS (:func:`ssl.create_default_context`): ``starttls`` (the default)
or ``tls`` from the first byte. ``none`` is allowed only to this machine (checked at start-up in :mod:`app.config`). The work runs
in a small pool of its own with a hard deadline (:func:`app.egress.run_with_deadline`), so a slow mail server never holds a request
thread for long.

The log says only ``email sent`` or ``email failed: <error class>``: never the password, the address, the text or the link.

The emails hold no health data and no name beyond the user name.
"""
from __future__ import annotations

import concurrent.futures
import logging
import re
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import TYPE_CHECKING, Callable

from . import brand, egress

if TYPE_CHECKING:  # pragma: no cover
    from .config import EmailEnv

log = logging.getLogger(f"{brand.LOGGER_NAME}.mail")

MAX_ADDRESS = 320
RESET_HOURS = 1
CONFIRM_HOURS = 24

_LOCAL = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")

ADDRESS_HELP = "Enter an email address such as name@example.org."


class AddressRejected(ValueError):
    """The typed address cannot be used; the message says why in plain words."""


def check_address(raw: str | None) -> str:
    """The address in its stored form (trimmed, lower-cased), or :class:`AddressRejected`."""
    text = (raw or "").strip().lower()
    if not text:
        raise AddressRejected(ADDRESS_HELP)
    if len(text) > MAX_ADDRESS:
        raise AddressRejected("That address is too long. Use at most 320 characters.")
    local, at, domain = text.rpartition("@")
    if not at or not local or len(local) > 64 or not _LOCAL.match(local) or not _DOMAIN.match(domain):
        raise AddressRejected(ADDRESS_HELP)
    return text


def check_sender(raw: str) -> str:
    """``SMTP_FROM``: an address, or ``Name <address>``; raises :class:`app.config.ConfigError`."""
    from .config import ConfigError

    if any(c in raw for c in "\r\n"):
        raise ConfigError("SMTP_FROM must be on one line.")
    _, address = parseaddr(raw)
    try:
        check_address(address)
    except AddressRejected:
        raise ConfigError(f"SMTP_FROM is not an email address: {raw!r}. Use kidney@example.org or "
                          "Kidney Health <kidney@example.org>.") from None
    return raw


# --------------------------------------------------------------------------- #
# The three emails
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Letter:
    to: str
    subject: str
    body: str


def _one_line(text: str, limit: int = 80) -> str:
    return " ".join(str(text or "").split())[:limit]


def reset_letter(to: str, username: str, instance: str, link: str) -> Letter:
    name, place = _one_line(username, 255), _one_line(instance) or brand.NAME
    return Letter(to, f"Reset your password on {place}", (
        f"Someone asked to reset the password for {name} on {place}.\n\n"
        f"Open this link within {RESET_HOURS} hour to choose a new one:\n\n{link}\n\n"
        "The link works once. Choosing a new password signs you out on your other devices.\n\n"
        "If this was not you, ignore this email. Your password stays the same.\n"
    ))


def confirm_letter(to: str, username: str, instance: str, link: str) -> Letter:
    name, place = _one_line(username, 255), _one_line(instance) or brand.NAME
    return Letter(to, f"Confirm your email on {place}", (
        f"Someone asked to use this email address for password resets for {name} on {place}.\n\n"
        f"Open this link within {CONFIRM_HOURS} hours to confirm it:\n\n{link}\n\n"
        "Until you confirm it, no reset emails are sent here.\n\n"
        "If this was not you, ignore this email. Nothing changes.\n"
    ))


def test_letter(to: str, username: str, instance: str) -> Letter:
    name, place = _one_line(username, 255), _one_line(instance) or brand.NAME
    return Letter(to, f"Test email from {place}", (
        f"This is a test email from {place}, sent by {name} from Server administration.\n\n"
        "If you can read it, email for password resets works.\n"
    ))


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #


class MailFailed(Exception):
    """Sending did not work. ``kind`` is the error class (what the log shows); ``message`` is for people."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


def _plain_reason(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "The mail server did not accept the user name or password."
    if isinstance(exc, ssl.SSLError):
        return "The mail server's certificate could not be checked, so nothing was sent."
    timed_out = (egress.DeadlineExceeded, socket.timeout, TimeoutError)
    if isinstance(exc, timed_out) or isinstance(exc.__context__, timed_out):  # smtplib turns a timeout into "disconnected"
        return "The mail server did not answer in time."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "The mail server did not accept that address."
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return "The mail server does not offer what SMTP_SECURITY asks for (for example STARTTLS)."
    if isinstance(exc, smtplib.SMTPException):
        return "The mail server did not accept the email."
    return "Could not connect to the mail server."


class Mailer:
    """Sends through the configured mail server. ``app.state.mailer``; tests point it at a fake server."""

    def __init__(self, env: "EmailEnv", *, ehlo_name: str | None = None) -> None:
        self.env = env
        self.ehlo_name = ehlo_name or "localhost"  # no DNS lookup for our own name (smtplib would ask socket.getfqdn)
        self.sent = 0
        self.failed = 0
        self._background = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="email-later")

    @property
    def enabled(self) -> bool:
        return bool(self.env.enabled and self.env.host and self.env.sender)

    @property
    def deadline_s(self) -> float:
        return float(self.env.timeout_s) * 2

    def _message(self, letter: Letter) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.env.sender or ""
        msg["To"] = letter.to
        msg["Subject"] = letter.subject
        msg["Date"] = formatdate(usegmt=True)
        domain = parseaddr(self.env.sender or "")[1].rpartition("@")[2] or "localhost"
        msg["Message-ID"] = make_msgid(domain=domain)
        msg["Auto-Submitted"] = "auto-generated"
        msg.set_content(letter.body)  # text/plain; utf-8
        return msg

    def _connect(self) -> smtplib.SMTP:
        e = self.env
        tls = ssl.create_default_context()  # verifies the certificate and the host name
        if e.security == "tls":
            return smtplib.SMTP_SSL(e.host or "", e.port, local_hostname=self.ehlo_name, timeout=e.timeout_s, context=tls)
        smtp = smtplib.SMTP(e.host or "", e.port, local_hostname=self.ehlo_name, timeout=e.timeout_s)
        try:
            smtp.ehlo()
            if e.security == "starttls":
                smtp.starttls(context=tls)
                smtp.ehlo()
        except BaseException:
            smtp.close()
            raise
        return smtp

    def _deliver(self, msg: EmailMessage) -> None:
        smtp = self._connect()
        try:
            if self.env.username and self.env.password:
                smtp.login(self.env.username, self.env.password)
            smtp.send_message(msg)
            try:
                smtp.quit()
            except (smtplib.SMTPException, OSError):
                pass  # the mail was accepted; a lost goodbye changes nothing
        finally:
            smtp.close()

    def send(self, letter: Letter) -> None:
        """Send now and wait (at most :attr:`deadline_s`); raises :class:`MailFailed`."""
        if not self.enabled:
            raise MailFailed("EmailOff", "Email is off on this server.")
        msg = self._message(letter)
        try:
            egress.run_with_deadline("email", lambda: self._deliver(msg), self.deadline_s, workers=2)
        except Exception as exc:  # noqa: BLE001 - every failure is told the same way, by class only
            self.failed += 1
            log.warning("email failed: %s", type(exc).__name__)
            raise MailFailed(type(exc).__name__, _plain_reason(exc)) from None
        self.sent += 1
        log.info("email sent")

    def send_later(self, letter: Letter, done: Callable[[bool], None] | None = None) -> concurrent.futures.Future[bool]:
        """Send without waiting: the caller's answer does not depend on the mail server. The future says whether it went."""
        def work() -> bool:
            try:
                self.send(letter)
            except MailFailed:
                ok = False
            else:
                ok = True
            if done is not None:
                done(ok)
            return ok

        return self._background.submit(work)
