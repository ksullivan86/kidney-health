"""A backup restores into a fresh server (roadmap "First", item 3): take a backup with ``python -m app.admin backup`` of a server
with a person's data, check it with ``restore-check``, put it and the secret key into an empty data directory as the restore steps in
handbook/docs/self-hosting/backups.md say, start a new server on it, and find everything again. No network."""
from __future__ import annotations

import io
import shutil

from app import admin, brand
from app.config import SECRET_KEY_FILENAME
from conftest import make_settings, signed_in_client

DAY = "2026-10-05"


def test_a_backup_restores_into_a_fresh_server(tmp_path, foods_json):
    first = make_settings(tmp_path / "one", foods_json)
    with signed_in_client(first) as c:
        food = c.get("/api/foods", params={"limit": 1}).json()["foods"][0]
        entry = c.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"], "servings": 2}).json()
        meal = c.post("/api/meals", json={"name": "Restore me", "items": [{"food_id": food["id"], "servings": 1}]}).json()
        assert c.put("/api/profile", json={"targets": {"potassium_mg": 2500}}).status_code == 200

    backup = tmp_path / "kidney-backup.db"
    out = io.StringIO()
    assert admin.main(["backup", str(backup)], env={"DATA_DIR": str(first.data_dir)}, out=out) == 0, out.getvalue()
    out = io.StringIO()
    assert admin.main(["restore-check", str(backup)], env={"DATA_DIR": str(first.data_dir)}, out=out) == 0, out.getvalue()

    # The restore steps: an empty data directory, the backup as the database, and the secret key, which is not in the backup.
    second = make_settings(tmp_path / "two", foods_json, admin_password=None)
    second.data_dir.mkdir(parents=True)
    shutil.copyfile(backup, second.data_dir / brand.DB_FILENAME)
    shutil.copyfile(first.data_dir / SECRET_KEY_FILENAME, second.data_dir / SECRET_KEY_FILENAME)
    with signed_in_client(second) as c:  # the admin signs in with the password from the backup
        day = c.get("/api/log", params={"date": DAY}).json()
        assert [(e["id"], e["food_id"], e["servings"]) for e in day["entries"]] == [(entry["id"], food["id"], 2)]
        assert any(m["id"] == meal["id"] and m["name"] == "Restore me" for m in c.get("/api/meals").json()["meals"])
        assert c.get("/api/profile").json()["targets"]["potassium_mg"] == 2500


def test_the_admin_page_reminds_about_an_old_or_missing_backup():
    from pathlib import Path

    view = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    due = view[view.index("function backupDue"):view.index("// ---- About this server")]
    assert "const BACKUP_DUE_DAYS = 7;" in view and "if (days != null && days < BACKUP_DUE_DAYS) return null;" in due
    assert "No backup has been taken on this server yet." in due and "The last backup is ${days} days old." in due
    assert "KH.learn.href('self-hosting/backups/#restore')" in due and "'How to restore a backup'" in due
    assert "const due = backupDue(a.last_backup_at);" in view
