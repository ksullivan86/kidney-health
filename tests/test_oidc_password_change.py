"""A forced password change applies to pending provider links and re-entry too."""
import pytest

from conftest import HTTPS_URL, add_user
from oidc_support import come_back
from test_oidc import app, admin, provider  # noqa: F401 - shared fixtures
from test_oidc import database


@pytest.mark.parametrize("purpose", ["link", "reauth"])
@pytest.mark.parametrize("change", ["before", "during", "none"])
def test_pending_provider_flow_respects_password_change(request, monkeypatch, purpose, change):
    admin_client = request.getfixturevalue("admin")
    idp = request.getfixturevalue("provider")
    person = add_user(admin_client, "member", base_url=HTTPS_URL)
    user_id = person.get("/api/me").json()["id"]
    if purpose == "reauth":
        response = person.post("/api/me/oidc/link")
        linked = come_back(person, idp, response.json()["url"], claims={"sub": "member-provider"})
        assert linked.headers["location"] == "/#/oidc/linked"
    path = "/api/me/oidc/link" if purpose == "link" else "/api/auth/reauth/oidc"
    response = person.post(path)
    assert response.status_code == 200, response.text
    url = response.json()["url"]
    with database(person) as conn:
        conn.execute("UPDATE sessions SET reauth_at = NULL WHERE user_id = ?", (user_id,))

    def force_password_change():
        updated = admin_client.patch(f"/api/admin/users/{user_id}", json={"must_change_password": True})
        assert updated.status_code == 200, updated.text

    if change == "before":
        force_password_change()
    elif change == "during":
        client = person.app.state.oidc
        exchange = client.exchange

        def exchange_and_change(*args, **kwargs):
            token = exchange(*args, **kwargs)
            force_password_change()
            return token

        monkeypatch.setattr(client, "exchange", exchange_and_change)
    result = come_back(person, idp, url, claims={"sub": "member-provider"})
    expected = ("linked" if purpose == "link" else "confirmed") if change == "none" else "expired"
    assert result.headers["location"] == f"/#/oidc/{expected}"
    with database(person) as conn:
        count = conn.execute("SELECT COUNT(*) FROM oidc_links WHERE user_id = ?", (user_id,)).fetchone()[0]
        assert count == int(purpose == "reauth" or change == "none")
        reentered = conn.execute("SELECT reauth_at FROM sessions WHERE user_id = ?", (user_id,)).fetchone()[0]
        assert bool(reentered) == (purpose == "reauth" and change == "none")
