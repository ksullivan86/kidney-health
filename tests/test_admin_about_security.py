"""``GET /api/admin/about`` holds no secret, and only an admin reads it (``app/auth/admin_api.py`` ``about``).

The page says where the secret key comes from and how many stored secrets it opens: never the key, a key derived from it, the
admin's password or a sealed value. ``record-backup`` (``python -m app.admin``) adds only the time of a backup.
"""
from __future__ import annotations

import base64
import io

from app import admin as admin_cli
from conftest import ADMIN_PASSWORD, add_user, make_settings, signed_in_client

SECRET = "an-operator-secret-key-of-enough-length-for-the-keyring-0123456789"


def _forbidden_texts(client) -> list[str]:
    ring = client.app.state.auth.require_keyring()
    texts = [ADMIN_PASSWORD, SECRET]
    for master in ring._masters:  # the SECRET_KEY lines and the key file's content
        texts.append(master.decode("utf-8"))
    for fernet in ring._fernets:  # the keys derived from them
        for raw in (fernet._signing_key, fernet._encryption_key):
            texts += [raw.hex(), base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")]
    return [t for t in texts if t]


def test_about_holds_no_key_or_password(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, secret_key=SECRET, secret_key_source="env")
    with signed_in_client(settings) as client:
        assert client.put("/api/me/ai/provider", json={"preset": "openai", "model": "m", "api_key": "sk-" + "x" * 40}).status_code == 200
        r = client.get("/api/admin/about")
        assert r.status_code == 200
        about = r.json()
        assert about["secret_key"]["source"] == "env" and about["secret_key"]["secrets"]["current"] >= 1
        for text in _forbidden_texts(client):
            assert text not in r.text
        assert "sk-" + "x" * 40 not in r.text


def test_about_with_the_key_on_the_volume_holds_no_key(client):
    r = client.get("/api/admin/about")
    assert r.status_code == 200 and r.json()["secret_key"]["on_data_volume"] is True
    for text in _forbidden_texts(client):
        assert text not in r.text
    key_file = client.app.state.settings.secret_key_path
    assert key_file.read_text().strip() not in r.text


def test_only_an_admin_reads_about(https_client):
    sam = add_user(https_client)
    assert sam.get("/api/admin/about").status_code == 403


def test_record_backup_adds_only_the_time(client):
    before = client.get("/api/admin/about").json()["last_backup_at"]
    out = io.StringIO()
    settings = client.app.state.settings
    assert admin_cli.main(["record-backup"], env={"DATA_DIR": str(settings.data_dir)}, out=out) == 0
    about = client.get("/api/admin/about").json()
    assert before is None and about["last_backup_at"] is not None
    events = [e for e in client.get("/api/admin/audit").json()["events"] if e["action"] == "backup.created"]
    assert len(events) == 1 and events[0]["details"] == {"target": "outside"} and events[0]["actor_user_id"] is None
