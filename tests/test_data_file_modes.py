"""File modes under DATA_DIR (access-control audit, finding 2).

The process umask decided before: 0755 for the folder and 0644 for ``kidney.db`` under the usual 022, which lets every
local user outside a container read the health data. The folder is now 0770, the database and its ``-wal`` and
``-shm`` files 0600, like ``secret.key``.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

from app import config, db
from app.main import create_app

from conftest import TestClient, make_settings


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def umask():
    """Set the process umask for a test and put the old one back afterwards."""
    old = os.umask(0o022)

    def set_to(value: int) -> None:
        os.umask(value)

    yield set_to
    os.umask(old)


def write_through_the_pool(path: Path):
    """A connection kept open with a write, so the -wal and -shm files exist."""
    conn = db.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("INSERT INTO meta (key, value) VALUES ('probe', '1') ON CONFLICT(key) DO NOTHING")
    conn.commit()
    return conn


@pytest.mark.parametrize("mask", [0o022, 0o077, 0o002], ids=["umask022", "umask077", "umask002"])
def test_a_new_data_folder_and_database_are_private_whatever_the_umask(tmp_path, foods_json, umask, mask):
    umask(mask)
    settings = make_settings(tmp_path, foods_json)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/auth/status").status_code == 200
        data = settings.data_dir
        keep_open = write_through_the_pool(settings.db_path)
        try:
            names = sorted(p.name for p in data.iterdir())
            assert "kidney.db" in names and "kidney.db-wal" in names and "kidney.db-shm" in names
            assert mode_of(data) == 0o770
            for name in ("kidney.db", "kidney.db-wal", "kidney.db-shm"):
                assert mode_of(data / name) == 0o600, name
            assert mode_of(data / "secret.key") == 0o600
            # nothing else the app wrote is open to other users
            for p in data.iterdir():
                assert mode_of(p) & 0o007 == 0, p
        finally:
            keep_open.close()


def test_a_database_made_earlier_under_a_looser_umask_is_tightened(tmp_path, umask):
    umask(0o022)
    path = tmp_path / "kidney.db"
    db.init_db(path)
    path.chmod(0o644)
    keep_open = write_through_the_pool(path)
    try:
        for side in ("-wal", "-shm"):
            Path(f"{path}{side}").chmod(0o644)
        db.init_db(path)
        for name in ("kidney.db", "kidney.db-wal", "kidney.db-shm"):
            assert mode_of(tmp_path / name) == 0o600, name
    finally:
        keep_open.close()


def test_an_existing_folder_open_to_other_users_loses_that_access_and_says_so(tmp_path, foods_json, caplog):
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o755)
    with caplog.at_level(logging.WARNING, logger="kidney_health.config"):
        make_settings(tmp_path, foods_json).ensure_data_dir()
    assert mode_of(data) == 0o750
    assert any("was open to other users" in m and str(data) in m for m in caplog.messages)


def test_a_folder_the_app_does_not_own_is_left_alone_with_a_warning(tmp_path, foods_json, caplog, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o755)
    monkeypatch.setattr(config.os, "geteuid", lambda: os.stat(data).st_uid + 1)
    with caplog.at_level(logging.WARNING, logger="kidney_health.config"):
        make_settings(tmp_path, foods_json).ensure_data_dir()  # does not raise
    assert mode_of(data) == 0o755
    assert any("does not own it" in m and "chmod o-rwx" in m for m in caplog.messages)


def test_a_folder_that_cannot_be_changed_never_stops_the_start(tmp_path, foods_json, caplog, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o755)

    def refuse(self, *args, **kwargs):
        raise PermissionError("no")

    monkeypatch.setattr(Path, "chmod", refuse)
    with caplog.at_level(logging.WARNING, logger="kidney_health.config"):
        make_settings(tmp_path, foods_json).ensure_data_dir()
    assert any("could not check or set the mode" in m for m in caplog.messages)


def test_the_image_layout_is_left_as_it_is(tmp_path, foods_json, caplog, umask):
    """/data is 0770 in the image: no change, no warning. A database already at 0600 is not touched."""
    umask(0o022)
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o770)
    with caplog.at_level(logging.WARNING):
        make_settings(tmp_path, foods_json).ensure_data_dir()
        db.init_db(data / "kidney.db")
        db.init_db(data / "kidney.db")
    assert mode_of(data) == 0o770 and mode_of(data / "kidney.db") == 0o600
    assert not [m for m in caplog.messages if "other users" in m or "could not" in m]


def test_a_database_that_stays_open_to_other_users_is_reported_not_fatal(tmp_path, caplog, monkeypatch):
    path = tmp_path / "kidney.db"
    db.init_db(path)
    path.chmod(0o644)

    def refuse(*args, **kwargs):
        raise PermissionError("not yours")

    monkeypatch.setattr(db.os, "chmod", refuse)
    with caplog.at_level(logging.WARNING, logger="kidney_health.db"):
        assert db.init_db(path) == []  # the start goes on
    assert mode_of(path) == 0o644
    assert any("is readable by other users" in m and "chmod 600" in m and str(path) in m for m in caplog.messages)


def test_a_database_that_is_fine_gives_no_warning(tmp_path, caplog):
    path = tmp_path / "kidney.db"
    with caplog.at_level(logging.WARNING, logger="kidney_health.db"):
        db.init_db(path)
    assert not caplog.messages
