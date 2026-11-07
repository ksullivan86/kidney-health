"""Password reset by email (design note 34): start-up rules, the person's address and its confirmation, "Forgot your password?",
the rate limits, a reset with the emailed link from start to end, the admin's test email, and what the log may say.

Mail goes to :class:`fake_smtp.FakeSmtp`, a small SMTP server on 127.0.0.1 in this process. Nothing leaves the machine. TLS is
checked at the ``smtplib`` seam (``app.mail.smtplib``), since the fake server has no certificate.
"""
from __future__ import annotations

import email
import email.policy
import json
import logging
import re
import socket
import sqlite3
import ssl
from pathlib import Path
from typing import Any, Iterator

import pytest

from app import mail
from app.config import ConfigError, EmailEnv, load_settings
from app.main import create_app
from conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    HTTPS_URL,
    USER_PASSWORD,
    TestClient,
    add_user,
    make_settings,
    sign_in,
)
from fake_smtp import FakeSmtp

PUBLIC = "https://kidney.example.org"
SAM_MAIL = "sam@example.org"
NEW_PASSWORD = "a brand new pass phrase for sam"
FORGOT = {"detail": "If that account has a confirmed email, a link is on its way. It works for 1 hour."}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def smtp() -> Iterator[FakeSmtp]:
    with FakeSmtp() as server:
        yield server


def email_env(smtp: FakeSmtp, **kw: Any) -> EmailEnv:
    values: dict[str, Any] = {"enabled": True, "host": "127.0.0.1", "port": smtp.port, "security": "none",
                              "sender": "Kidney Health <kidney@example.org>", "timeout_s": 3}
    values.update(kw)
    return EmailEnv(**values)


@pytest.fixture
def pair(tmp_path: Path, foods_json: Path, smtp: FakeSmtp) -> Iterator[tuple[TestClient, TestClient]]:
    """(admin, sam) on one app with email on, over HTTPS."""
    settings = make_settings(tmp_path, foods_json, public_url=PUBLIC, email=email_env(smtp))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        yield admin, add_user(admin)


def db(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def actions(client: TestClient) -> list[tuple[str, str]]:
    conn = db(client)
    rows = [(r["action"], r["details_json"]) for r in conn.execute("SELECT action, details_json FROM audit_log ORDER BY id")]
    conn.close()
    return rows


def body_of(message: dict[str, Any]) -> str:
    return email.message_from_string(message["data"], policy=email.policy.default).get_content()


def header(message: dict[str, Any], name: str) -> str:
    return str(email.message_from_string(message["data"], policy=email.policy.default)[name])


def token_in(message: dict[str, Any], kind: str) -> str:
    found = re.search(rf"{re.escape(PUBLIC)}/#/{kind}/(\S+)", body_of(message))
    assert found, body_of(message)
    return found.group(1)


def confirm(client: TestClient, smtp: FakeSmtp, address: str = SAM_MAIL) -> None:
    before = len(smtp.messages)
    r = client.put("/api/me/email", json={"email": address})
    assert r.status_code == 200 and r.json()["sent"] is True, r.text
    message = smtp.wait(before + 1)[-1]
    anon = TestClient(client.app, base_url=HTTPS_URL)
    assert anon.post("/api/auth/email/confirm", json={"token": token_in(message, "confirm-email")}).status_code == 200


def forgot(app: Any, username: str) -> Any:
    return TestClient(app, base_url=HTTPS_URL).post("/api/auth/forgot", json={"username": username})


# --------------------------------------------------------------------------- #
# Start-up
# --------------------------------------------------------------------------- #


def test_start_up_refuses_what_cannot_work(tmp_path: Path) -> None:
    base = {"DATA_DIR": str(tmp_path), "EMAIL_ENABLED": "true", "PUBLIC_URL": PUBLIC, "SMTP_HOST": "smtp.example.org",
            "SMTP_FROM": "kidney@example.org"}
    s = load_settings(base)
    assert s.email.enabled and s.email.port == 587 and s.email.security == "starttls" and s.email.timeout_s == 15
    with pytest.raises(ConfigError, match="SMTP_PASSWORD_FILE"):
        load_settings({**base, "SMTP_PASSWORD": "hunter2-hunter2"})
    with pytest.raises(ConfigError, match="only allowed to a mail server on this machine"):
        load_settings({**base, "SMTP_SECURITY": "none"})
    for local in ("localhost", "127.0.0.1", "::1", "[::1]"):
        assert load_settings({**base, "SMTP_SECURITY": "none", "SMTP_HOST": local}).email.security == "none"
    with pytest.raises(ConfigError, match="needs PUBLIC_URL"):
        load_settings({k: v for k, v in base.items() if k != "PUBLIC_URL"})
    with pytest.raises(ConfigError, match="needs SMTP_FROM"):
        load_settings({k: v for k, v in base.items() if k != "SMTP_FROM"})
    with pytest.raises(ConfigError, match="needs SMTP_HOST"):
        load_settings({k: v for k, v in base.items() if k != "SMTP_HOST"})
    with pytest.raises(ConfigError, match="SMTP_FROM is not an email address"):
        load_settings({**base, "SMTP_FROM": "not an address"})
    with pytest.raises(ConfigError, match="AUTH_MODE=local"):
        load_settings({**base, "AUTH_MODE": "none"})
    with pytest.raises(ConfigError, match="SMTP_SECURITY"):
        load_settings({**base, "SMTP_SECURITY": "ssl"})
    with pytest.raises(ConfigError, match="SMTP_USERNAME"):
        password = tmp_path / "smtp.pw"
        password.write_text("pw-in-a-file-123\n", encoding="utf-8")
        load_settings({**base, "SMTP_PASSWORD_FILE": str(password)})
    # Off: a stray host is a warning, nothing more.
    off = load_settings({"DATA_DIR": str(tmp_path), "SMTP_HOST": "smtp.example.org"})
    assert not off.email.enabled and any("EMAIL_ENABLED" in w for w in off.warnings)


def test_the_password_is_read_from_a_file_and_kept_out_of_repr(tmp_path: Path) -> None:
    secret = "pw-in-a-file-0123456789"
    password = tmp_path / "smtp.pw"
    password.write_text(secret + "\n", encoding="utf-8")
    s = load_settings({"DATA_DIR": str(tmp_path), "EMAIL_ENABLED": "1", "PUBLIC_URL": PUBLIC, "SMTP_HOST": "Mail.Example.org",
                       "SMTP_PORT": "465", "SMTP_SECURITY": "tls", "SMTP_USERNAME": "kidney", "SMTP_PASSWORD_FILE": str(password),
                       "SMTP_FROM": "kidney@example.org", "SMTP_TIMEOUT_S": "9"})
    e = s.email
    assert (e.host, e.port, e.security, e.username, e.password, e.timeout_s) == ("mail.example.org", 465, "tls", "kidney", secret, 9)
    assert secret in s.secret_values() and secret not in repr(s) and secret not in repr(e)


def test_addresses_are_checked_and_lower_cased() -> None:
    assert mail.check_address("  Sam.Smith+kidney@Example.ORG ") == "sam.smith+kidney@example.org"
    for bad in ("", "sam", "sam@", "@example.org", "sam@example", "sam smith@example.org", "sam@example.org\r\nBcc: x@y.org",
                "sam@@example.org", "säm@example.org", "a" * 65 + "@example.org", "sam@" + "a" * 320 + ".org", "sam..x@example.org"):
        with pytest.raises(mail.AddressRejected):
            mail.check_address(bad)


def test_the_reset_email_says_only_what_it_must() -> None:
    letter = mail.reset_letter("sam@example.org", "sam", "Our kitchen", "https://kidney.example.org/#/reset/abc.def")
    assert letter.subject == "Reset your password on Our kitchen"
    assert letter.body.startswith("Someone asked to reset the password for sam on Our kitchen.\n\n"
                                  "Open this link within 1 hour to choose a new one:\n\nhttps://kidney.example.org/#/reset/abc.def\n")
    assert "If this was not you, ignore this email. Your password stays the same." in letter.body
    confirm_text = mail.confirm_letter("sam@example.org", "sam", "Our kitchen", "https://x/#/confirm-email/a.b").body
    assert "within 24 hours" in confirm_text and "no reset emails are sent" in confirm_text


# --------------------------------------------------------------------------- #
# Off
# --------------------------------------------------------------------------- #


def test_everything_is_off_without_email_enabled(client: TestClient) -> None:
    assert client.get("/api/auth/status").json()["email_reset"] is False
    assert client.get("/api/me/email").json() == {"available": False, "reason": "off", "email": None, "confirmed": False,
                                                  "confirmed_at": None}
    r = client.put("/api/me/email", json={"email": SAM_MAIL})
    assert r.status_code == 409 and "EMAIL_ENABLED" in r.json()["detail"]
    assert client.post("/api/auth/forgot", json={"username": ADMIN_USERNAME}).status_code == 404
    assert client.post("/api/auth/email/confirm", json={"token": "a.b"}).status_code == 404
    assert client.post("/api/admin/email/test").status_code == 409
    assert client.get("/api/admin/about").json()["email"]["enabled"] is False


# --------------------------------------------------------------------------- #
# The person's address
# --------------------------------------------------------------------------- #


def test_set_confirm_and_remove_the_address(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    admin, sam = pair
    assert sam.get("/api/auth/status").json()["email_reset"] is True
    assert sam.get("/api/me/email").json()["available"] is True
    assert sam.put("/api/me/email", json={"email": "not an address"}).status_code == 400
    r = sam.put("/api/me/email", json={"email": "  Sam@Example.ORG "})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["email"] == SAM_MAIL and out["confirmed"] is False and out["sent"] is True and SAM_MAIL in out["message"]
    message = smtp.wait(1)[0]
    assert message["rcpt"] == [SAM_MAIL] and message["mail_from"] == "kidney@example.org"
    assert header(message, "Subject").startswith("Confirm your email on ") and header(message, "To") == SAM_MAIL
    text = body_of(message)
    assert "for sam on" in text and "within 24 hours" in text
    token = token_in(message, "confirm-email")

    # Not confirmed yet: no reset email.
    assert forgot(sam.app, "sam").status_code == 202
    assert len(smtp.wait(2, timeout=0.5)) == 1

    anon = TestClient(sam.app, base_url=HTTPS_URL)
    r = anon.post("/api/auth/email/confirm", json={"token": token})
    assert r.status_code == 200 and r.json() == {"ok": True, "username": "sam"}
    assert anon.post("/api/auth/email/confirm", json={"token": token}).status_code == 400  # single use
    view = sam.get("/api/me/email").json()
    assert view["email"] == SAM_MAIL and view["confirmed"] is True and view["confirmed_at"]

    # The admin sees only "confirmed", never the address.
    users = admin.get("/api/admin/users")
    assert SAM_MAIL not in users.text
    assert {u["username"]: u["email_confirmed"] for u in users.json()["users"]} == {"admin": False, "sam": True}
    assert SAM_MAIL not in admin.get("/api/admin/audit").text and SAM_MAIL not in sam.get("/api/me/activity").text
    # The person's own export has it.
    exported = sam.get("/api/me/export.zip")
    assert exported.status_code == 200
    import io
    import zipfile

    doc = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("export.json"))
    assert doc["user"]["email"] == SAM_MAIL and doc["user"]["email_confirmed_at"]

    # Saving the same address again changes nothing.
    again = sam.put("/api/me/email", json={"email": SAM_MAIL}).json()
    assert again["confirmed"] is True and again["sent"] is False and len(smtp.wait(2, timeout=0.3)) == 1

    assert sam.delete("/api/me/email").status_code == 204
    assert sam.get("/api/me/email").json()["email"] is None
    assert sam.delete("/api/me/email").status_code == 204  # nothing to remove: still fine
    names = [a for a, _ in actions(sam)]
    assert names.count("email.set") == 1 and names.count("email.confirmed") == 1 and names.count("email.removed") == 1
    activity = [e["action"] for e in sam.get("/api/me/activity").json()["events"]]
    assert {"email.set", "email.confirmed", "email.removed"} <= set(activity)


def test_setting_the_address_needs_a_recent_password(pair: tuple[TestClient, TestClient], smtp: FakeSmtp, fake_clock: Any) -> None:
    _, sam = pair
    fake_clock.advance(minutes=11)
    r = sam.put("/api/me/email", json={"email": SAM_MAIL})
    assert r.status_code == 403 and r.json()["reauth_required"] is True
    assert sam.post("/api/auth/reauth", json={"password": USER_PASSWORD}).status_code == 200
    assert sam.put("/api/me/email", json={"email": SAM_MAIL}).status_code == 200
    fake_clock.advance(minutes=11)
    assert sam.delete("/api/me/email").status_code == 204  # removing needs no password


def test_a_link_for_an_older_address_does_not_confirm_a_newer_one(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    _, sam = pair
    sam.put("/api/me/email", json={"email": "old@example.org"})
    old = token_in(smtp.wait(1)[0], "confirm-email")
    sam.put("/api/me/email", json={"email": "new@example.org"})
    new = token_in(smtp.wait(2)[1], "confirm-email")
    anon = TestClient(sam.app, base_url=HTTPS_URL)
    assert anon.post("/api/auth/email/confirm", json={"token": old}).status_code == 400
    assert anon.post("/api/auth/email/confirm", json={"token": "nonsense.token"}).status_code == 400
    assert anon.post("/api/auth/email/confirm", json={"token": new}).status_code == 200
    assert sam.get("/api/me/email").json()["email"] == "new@example.org"


def test_typing_someone_elses_address_does_not_block_them(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    admin, sam = pair
    assert sam.put("/api/me/email", json={"email": "admin@example.org"}).status_code == 200
    sams_link = token_in(smtp.wait(1)[0], "confirm-email")
    confirm(admin, smtp, "admin@example.org")  # the real owner confirms it on their own account
    r = TestClient(sam.app, base_url=HTTPS_URL).post("/api/auth/email/confirm", json={"token": sams_link})
    assert r.status_code == 409 and "another account" in r.json()["detail"]
    assert sam.get("/api/me/email").json()["confirmed"] is False


def test_a_failed_send_keeps_the_address_and_says_so(tmp_path: Path, foods_json: Path, smtp: FakeSmtp) -> None:
    smtp.refuse.add(SAM_MAIL)
    settings = make_settings(tmp_path, foods_json, public_url=PUBLIC, email=email_env(smtp))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        out = admin.put("/api/me/email", json={"email": SAM_MAIL}).json()
        assert out["sent"] is False and "could not be sent" in out["message"] and out["email"] == SAM_MAIL


def test_a_test_account_cannot_have_an_address(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    admin, sam = pair
    confirm(sam, smtp)
    conn = db(admin)
    conn.execute("UPDATE users SET is_test_account = 1 WHERE username = 'sam'")
    conn.commit()
    conn.close()
    assert sam.get("/api/me/email").json()["reason"] == "test_account"
    assert sam.put("/api/me/email", json={"email": "other@example.org"}).status_code == 409
    before = len(smtp.messages)
    assert forgot(sam.app, "sam").json() == FORGOT
    assert len(smtp.wait(before + 1, timeout=0.5)) == before


# --------------------------------------------------------------------------- #
# Forgot your password?
# --------------------------------------------------------------------------- #


def test_forgot_answers_the_same_for_every_name(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    admin, sam = pair
    confirm(sam, smtp)
    admin.put("/api/me/email", json={"email": "admin@example.org"})  # set, not confirmed
    sent = len(smtp.wait(2))
    answers = [forgot(sam.app, name) for name in ("nobody-here", "admin", "SAM", "x")]
    assert {r.status_code for r in answers} == {202}
    assert all(r.json() == FORGOT for r in answers)
    assert len({r.headers.get("content-length") for r in answers}) == 1
    messages = smtp.wait(sent + 1)
    assert len(messages) == sent + 1 and messages[-1]["rcpt"] == [SAM_MAIL]
    assert len(smtp.wait(sent + 2, timeout=0.5)) == sent + 1  # nothing for the others


def test_reset_with_the_emailed_link_from_start_to_end(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    admin, sam = pair
    confirm(sam, smtp)
    sid = next(u["id"] for u in admin.get("/api/admin/users").json()["users"] if u["username"] == "sam")
    admins_link = admin.post(f"/api/admin/users/{sid}/reset-link").json()["url"].split("/#/reset/")[1]
    forgot(sam.app, "sam")
    first = token_in(smtp.wait(2)[-1], "reset")
    forgot(sam.app, "sam")
    message = smtp.wait(3)[-1]
    assert header(message, "Subject").startswith("Reset your password on ")
    assert "Someone asked to reset the password for sam on" in body_of(message) and "within 1 hour" in body_of(message)
    token = token_in(message, "reset")
    user_list = admin.get("/api/admin/users").json()["users"]
    link = next(u for u in user_list if u["username"] == "sam")["reset_link"]
    assert link["via"] == "email" and link["created_by"] == sid

    person = TestClient(sam.app, base_url=HTTPS_URL)
    for old in (admins_link, first):  # a newer request voids the older links
        assert person.post("/api/auth/reset/info", json={"token": old}).status_code == 400
    info = person.post("/api/auth/reset/info", json={"token": token}).json()
    assert info["username"] == "sam" and info["new_account"] is False
    r = person.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["username"] == "sam"
    assert sam.get("/api/me").status_code == 401  # the other session was signed out
    assert person.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD + "x"}).status_code == 400
    assert TestClient(sam.app, base_url=HTTPS_URL).post("/api/auth/login", json={"username": "sam", "password": NEW_PASSWORD}).status_code == 200
    rows = actions(admin)
    issued = [d for a, d in rows if a == "user.reset_link_issued" and '"via":"email"' in d]
    changed = [d for a, d in rows if a == "user.password_changed"]
    assert len(issued) == 2 and '"via":"email_link"' in changed[-1]


def test_forgot_is_rate_limited(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    _, sam = pair
    confirm(sam, smtp)
    sent = len(smtp.messages)
    for _ in range(4):  # 3 an hour per account, the 4th kept silently
        assert forgot(sam.app, "sam").json() == FORGOT
    assert len(smtp.wait(sent + 4, timeout=1.0)) == sent + 3
    codes = [forgot(sam.app, f"nobody{i}").status_code for i in range(7)]  # 10 an hour per address in all
    assert codes[:6] == [202] * 6 and codes[6] == 429


def test_there_is_nothing_to_reset_without_local_sign_in(tmp_path: Path, foods_json: Path, smtp: FakeSmtp) -> None:
    settings = make_settings(tmp_path, foods_json, auth_mode="none")
    with TestClient(create_app(settings)) as c:
        c.app.state.mailer.env = email_env(smtp)  # start-up refuses EMAIL_ENABLED here; the routes refuse it too
        assert c.post("/api/auth/forgot", json={"username": "admin"}).status_code == 404
        assert c.get("/api/me/email").json()["reason"] == "mode"
        assert c.put("/api/me/email", json={"email": SAM_MAIL}).status_code == 404


# --------------------------------------------------------------------------- #
# Admin test email
# --------------------------------------------------------------------------- #


def test_the_admin_test_email(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    admin, sam = pair
    about = admin.get("/api/admin/about").json()["email"]
    assert about == {"enabled": True, "configured": True, "host": "127.0.0.1", "port": smtp.port, "security": "none",
                     "sender": "Kidney Health <kidney@example.org>", "login": False}
    r = admin.post("/api/admin/email/test")
    assert r.status_code == 409 and "Settings → Account" in r.json()["detail"]
    assert sam.post("/api/admin/email/test").status_code == 403
    confirm(admin, smtp, "admin@example.org")
    r = admin.post("/api/admin/email/test")
    assert r.status_code == 200 and r.json() == {"sent": True, "to": "admin@example.org"}
    message = smtp.messages[-1]
    assert message["rcpt"] == ["admin@example.org"] and "test email" in body_of(message)
    admin.app.state.mailer.env = email_env(smtp, port=_closed_port())
    r = admin.post("/api/admin/email/test")
    assert r.status_code == 502 and r.json()["detail"] == "The test email was not sent. Could not connect to the mail server."


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# --------------------------------------------------------------------------- #
# The log, TLS and the deadline
# --------------------------------------------------------------------------- #


def test_the_log_holds_no_secret(tmp_path: Path, foods_json: Path, caplog: pytest.LogCaptureFixture) -> None:
    secret = "smtp-password-0123456789"
    with FakeSmtp(users={"kidney": secret}) as smtp:
        settings = make_settings(tmp_path, foods_json, public_url=PUBLIC,
                                 email=email_env(smtp, username="kidney", password=secret))
        with caplog.at_level(logging.DEBUG), TestClient(create_app(settings), base_url=HTTPS_URL) as admin:
            sign_in(admin)
            sam = add_user(admin)
            confirm(sam, smtp)
            forgot(sam.app, "sam")
            messages = smtp.wait(2)
            smtp.refuse.add("bad@example.org")
            sam.put("/api/me/email", json={"email": "bad@example.org"})
        assert all(m["auth"] == "kidney" for m in messages)
    text = caplog.text
    assert "email sent" in text and "email failed: SMTPRecipientsRefused" in text
    for leak in (secret, SAM_MAIL, "bad@example.org", token_in(messages[0], "confirm-email"), token_in(messages[1], "reset"),
                 "Someone asked", ADMIN_PASSWORD):
        assert leak not in text, leak


class _Recorder:
    """Stands in for smtplib.SMTP / SMTP_SSL and records what the mailer asked for."""

    calls: list[tuple[str, Any]] = []

    def __init__(self, host: str, port: int, **kw: Any) -> None:
        self.calls.append(("open", (host, port, kw)))

    def ehlo(self) -> None:
        self.calls.append(("ehlo", None))

    def starttls(self, context: ssl.SSLContext) -> None:
        self.calls.append(("starttls", context))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user))

    def send_message(self, msg: Any) -> None:
        self.calls.append(("send", msg["To"]))

    def quit(self) -> None:
        self.calls.append(("quit", None))

    def close(self) -> None:
        pass


def test_tls_is_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail.smtplib, "SMTP", _Recorder)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", _Recorder)
    env = EmailEnv(enabled=True, host="smtp.example.org", port=587, sender="kidney@example.org", username="k", password="p")
    _Recorder.calls = []
    mail.Mailer(env, ehlo_name="kidney.example.org").send(mail.test_letter(SAM_MAIL, "admin", "Home"))
    kinds = [k for k, _ in _Recorder.calls]
    assert kinds == ["open", "ehlo", "starttls", "ehlo", "login", "send", "quit"]
    context = dict(_Recorder.calls)["starttls"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    assert dict(_Recorder.calls)["open"][2]["local_hostname"] == "kidney.example.org"

    _Recorder.calls = []
    mail.Mailer(EmailEnv(enabled=True, host="smtp.example.org", port=465, security="tls", sender="kidney@example.org")).send(
        mail.test_letter(SAM_MAIL, "admin", "Home"))
    opened = dict(_Recorder.calls)["open"][2]
    assert opened["context"].verify_mode == ssl.CERT_REQUIRED and opened["context"].check_hostname is True
    assert "starttls" not in dict(_Recorder.calls) and "login" not in dict(_Recorder.calls)


def test_starttls_against_a_server_without_it_sends_nothing(smtp: FakeSmtp) -> None:
    mailer = mail.Mailer(email_env(smtp, security="starttls"))
    with pytest.raises(mail.MailFailed) as caught:
        mailer.send(mail.test_letter(SAM_MAIL, "admin", "Home"))
    assert caught.value.kind == "SMTPNotSupportedError" and smtp.messages == []


def test_a_slow_mail_server_is_given_up_on() -> None:
    import time

    with FakeSmtp(greeting_delay=3) as slow:
        mailer = mail.Mailer(email_env(slow, timeout_s=1))
        start = time.monotonic()
        with pytest.raises(mail.MailFailed) as caught:
            mailer.send(mail.test_letter(SAM_MAIL, "admin", "Home"))
        assert time.monotonic() - start < 2.5
        assert caught.value.message == "The mail server did not answer in time."


def test_a_link_confirms_only_its_own_account_and_goes_with_it(pair: tuple[TestClient, TestClient], smtp: FakeSmtp) -> None:
    # email_tokens (schema step 34) in the isolation matrix: one person's link never touches another's account.
    admin, sam = pair
    assert admin.put("/api/me/email", json={"email": "admin@example.org"}).status_code == 200
    assert sam.put("/api/me/email", json={"email": SAM_MAIL}).status_code == 200
    by_to = {m["rcpt"][0]: m for m in smtp.wait(2)}
    anon = TestClient(sam.app, base_url=HTTPS_URL)
    assert anon.post("/api/auth/email/confirm", json={"token": token_in(by_to[SAM_MAIL], "confirm-email")}).status_code == 200
    assert sam.get("/api/me/email").json()["confirmed"] is True
    assert admin.get("/api/me/email").json()["confirmed"] is False  # sam's link did nothing to the admin's address
    assert SAM_MAIL not in admin.get("/api/me/email").text
    sam_id = sam.get("/api/me").json()["id"]
    conn = db(admin)
    open_links = "SELECT COUNT(*) FROM email_tokens WHERE user_id = ? AND used_at IS NULL"
    assert conn.execute(open_links, (sam_id,)).fetchone()[0] == 0  # the used link works no more
    assert sam.put("/api/me/email", json={"email": "sam2@example.org"}).status_code == 200
    assert conn.execute(open_links, (sam_id,)).fetchone()[0] == 1
    conn.close()
    from conftest import USER_PASSWORD

    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    conn = db(admin)
    assert conn.execute("SELECT COUNT(*) FROM email_tokens WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM email_tokens WHERE used_at IS NULL").fetchone()[0] == 1  # the admin's own stays
    conn.close()
