"""An overlapping forgot request cannot undo revocation of an email reset link."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, Lock

import pytest

from app.auth import email_api
from conftest import HTTPS_URL, USER_PASSWORD, TestClient
from test_reset_email import FORGOT, NEW_PASSWORD, PUBLIC, confirm, db
from test_reset_email import pair, smtp  # noqa: F401 - shared mail fixtures


def overlap(sam, monkeypatch, other):
    """Pause after the target read; let the other request commit or wait for the write lock.

    Both orders are valid. Once both requests finish, a revocation must cover every link
    issued before it, and two forgot requests must leave only the newest link usable.
    """
    reached, release, claim = Event(), Event(), Lock()
    held = False
    original = email_api._forgot_target

    def read_and_hold(*args):
        nonlocal held
        snapshot = original(*args)
        with claim:
            first = not held
            held = True
        if first:
            reached.set()
            assert release.wait(15), "forgot target was not released"
        return snapshot

    monkeypatch.setattr(email_api, "_forgot_target", read_and_hold)
    with TestClient(sam.app, base_url=HTTPS_URL, raise_server_exceptions=False) as anon:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(anon.post, "/api/auth/forgot", json={"username": "sam"})
            try:
                assert reached.wait(10), "forgot did not read its target"
                second = pool.submit(other)
                try:
                    second.result(timeout=0.5)
                except TimeoutError:
                    pass  # the fixed handler holds the write lock until its token is saved
            finally:
                release.set()
            return first.result(timeout=15), second.result(timeout=15)


@pytest.mark.parametrize("change", ["remove", "change", "password", "disable", "delete", "unchanged"])
def test_forgot_racing_revocation_cannot_leave_a_usable_link(pair, smtp, monkeypatch, change):  # noqa: F811
    admin, sam = pair
    confirm(sam, smtp)
    user_id = sam.get("/api/me").json()["id"]
    letters = []
    monkeypatch.setattr(sam.app.state.mailer, "send_later", letters.append)

    def change_account():
        if change == "remove":
            return sam.delete("/api/me/email")
        if change == "change":
            return sam.put("/api/me/email", json={"email": "new@example.org"})
        if change == "password":
            return sam.post("/api/me/password", json={"current_password": USER_PASSWORD, "new_password": NEW_PASSWORD})
        if change == "disable":
            return admin.patch(f"/api/admin/users/{user_id}", json={"status": "disabled"})
        if change == "delete":
            return admin.request("DELETE", f"/api/admin/users/{user_id}", json={"confirm_username": "sam"})
        return sam.get("/api/me/email")

    first, second = overlap(sam, monkeypatch, change_account)
    assert first.status_code == 202 and first.json() == FORGOT, first.text
    assert second.status_code in (200, 204), second.text
    if change == "disable":
        # Disabled accounts already reject reset links. Reactivating must not resurrect one
        # issued after the disabling request voided its predecessors.
        assert admin.patch(f"/api/admin/users/{user_id}", json={"status": "active"}).status_code == 200
    with db(admin) as conn:
        count = conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE user_id = ? AND purpose = 'reset' "
                             "AND used_at IS NULL", (user_id,)).fetchone()[0]
    assert count == int(change == "unchanged")
    with TestClient(sam.app, base_url=HTTPS_URL) as anon:
        for letter in letters:
            token = letter.body.split(f"{PUBLIC}/#/reset/", 1)[1].split()[0]
            response = anon.post("/api/auth/reset/info", json={"token": token})
            assert response.status_code == (200 if change == "unchanged" else 400), response.text


def test_overlapping_forgot_requests_leave_only_one_live_link(pair, smtp, monkeypatch):  # noqa: F811
    _, sam = pair
    confirm(sam, smtp)
    letters = []
    monkeypatch.setattr(sam.app.state.mailer, "send_later", letters.append)

    def again():
        with TestClient(sam.app, base_url=HTTPS_URL) as anon:
            return anon.post("/api/auth/forgot", json={"username": "sam"})

    responses = overlap(sam, monkeypatch, again)
    assert all(r.status_code == 202 and r.json() == FORGOT for r in responses), [r.text for r in responses]
    assert len(letters) == 2
    with TestClient(sam.app, base_url=HTTPS_URL) as anon:
        statuses = [anon.post("/api/auth/reset/info", json={
            "token": letter.body.split(f"{PUBLIC}/#/reset/", 1)[1].split()[0],
        }).status_code for letter in letters]
    assert sorted(statuses) == [200, 400]
