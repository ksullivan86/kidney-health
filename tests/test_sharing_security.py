"""Security checks of sharing (design note 19, ``app/sharing.py``) that ``tests/test_sharing.py`` does not make.

* A share of one area opens that area's routes and no other, on every ``/api/shared/{id}/…`` route.
* The shared profile carries the owner's saved weight only when weight and blood pressure were shared.
* A share that ended, whichever way it ended, is the same 404 on every route.
* A used link does not work for a third person either.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import sharing
from conftest import USER_PASSWORD, add_user
from test_sharing import SAME, TODAY, code_of, fill, make_link, share, switch

START = (date.today() - timedelta(days=13)).isoformat()
ROUTES = [path.format(d=TODAY, s=START) for path, _own, _area in SAME]
AREA_OF = {path.format(d=TODAY, s=START): area for path, _own, area in SAME}


@pytest.fixture
def people(two_clients):
    """(ana: the admin, sam, kim) with sharing on, as in tests/test_sharing.py."""
    ana, sam = two_clients
    switch(ana)
    return ana, sam, add_user(ana, "kim")


def test_every_route_belongs_to_one_of_the_four_areas(people):
    """The list above covers every read under /api/shared/{id}: a new route must be added here, with its area."""
    ana, _, _ = people
    from test_auth_coverage import _walk

    reads = {p for m, p, _ in _walk(ana.app.routes) if m == "get" and p.startswith("/api/shared/{share_id}/")}
    listed = {"/api/shared/{share_id}/" + path.split("?")[0] for path in ROUTES} | {"/api/shared/{share_id}/profile"}
    assert reads == listed


@pytest.mark.parametrize("area", sharing.AREAS)
def test_a_share_of_one_area_opens_only_that_area(people, area):
    ana, sam, _ = people
    fill(ana)
    sid = share(ana, sam, [area])
    for path in ROUTES:
        r = sam.get(f"/api/shared/{sid}/{path}")
        if AREA_OF[path] == area:
            assert r.status_code == 200, (area, path, r.text)
        else:
            assert r.status_code == 404 and r.json() == {"detail": sharing.NOT_SHARED}, (area, path)


@pytest.mark.parametrize("areas,shown", [(["food"], False), (["labs"], False), (["symptoms"], False),
                                         (["food", "labs", "symptoms"], False), (["body"], True), (list(sharing.AREAS), True)])
def test_the_owners_weight_is_shared_only_with_weight_and_blood_pressure(people, areas, shown):
    ana, sam, _ = people
    profile = ana.get("/api/profile").json()
    assert ana.put("/api/profile", json={**profile, "weight_kg": 72.5}).status_code == 200
    sid = share(ana, sam, areas)
    got = sam.get(f"/api/shared/{sid}/profile")
    assert got.status_code == 200
    assert got.json()["weight_kg"] == (72.5 if shown else None)
    assert "72.5" not in got.text or shown


def _link_with_days(client, days):
    r = client.post("/api/me/shares", json={"areas": list(sharing.AREAS), "days": days})
    assert r.status_code == 201, r.text
    return r.json()


def _end(how, admin, owner, grantee, sid, fake_clock):
    """End share ``sid`` (``owner`` shares with ``grantee``; ``admin`` runs the server) in one of the ways a share ends."""
    if how == "owner":
        assert owner.delete(f"/api/me/shares/{sid}").status_code == 204
    elif how == "grantee":
        assert grantee.delete(f"/api/shared/{sid}").status_code == 204
    elif how == "admin":
        grantee_id = grantee.get("/api/me").json()["id"]
        assert admin.delete(f"/api/admin/users/{grantee_id}/shares").json() == {"ended": 1}
    elif how == "time":
        fake_clock.advance(days=7, seconds=1)
    elif how == "replaced":
        assert grantee.post("/api/shared/accept", json={"code": code_of(make_link(owner, ["labs"]))}).status_code == 201
    elif how == "owner disabled":
        owner_id = owner.get("/api/me").json()["id"]
        assert admin.patch(f"/api/admin/users/{owner_id}", json={"status": "disabled"}).status_code == 200
    else:
        raise AssertionError(how)


@pytest.mark.parametrize("how", ["owner", "grantee", "admin", "time", "replaced", "owner disabled"])
def test_an_ended_share_is_the_same_404_on_every_route(people, fake_clock, how):
    ana, sam, kim = people
    fill(kim)
    made = _link_with_days(kim, 7) if how == "time" else make_link(kim)
    accepted = sam.post("/api/shared/accept", json={"code": code_of(made)})
    assert accepted.status_code == 201
    sid = int(accepted.json()["id"])
    for path in [*ROUTES, "profile"]:
        assert sam.get(f"/api/shared/{sid}/{path}").status_code == 200, path
    _end(how, ana, kim, sam, sid, fake_clock)
    for path in [*ROUTES, "profile"]:
        r = sam.get(f"/api/shared/{sid}/{path}")
        assert r.status_code == 404 and r.json() == {"detail": sharing.NOT_SHARED}, (how, path)
    if how == "replaced":
        assert [p["areas"] for p in sam.get("/api/shared").json()["people"]] == [["labs"]]
    else:
        assert sam.get("/api/shared").json()["people"] == []


def test_a_used_link_does_not_work_for_anyone_else(people):
    ana, sam, kim = people
    made = make_link(ana)
    assert sam.post("/api/shared/accept", json={"code": code_of(made)}).status_code == 201
    for path in ("/api/shared/info", "/api/shared/accept"):
        r = kim.post(path, json={"code": code_of(made)})
        assert r.status_code == 404 and r.json()["detail"] == sharing.BAD_LINK
    assert kim.get("/api/shared").json()["people"] == []


def test_a_deleted_grantee_leaves_nothing_behind_for_a_new_account_with_the_same_name(people):
    """Ids are not reused for someone else's share: a new account called sam sees nothing of kim's."""
    ana, sam, kim = people
    share(kim, sam)
    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    new_sam = add_user(ana, "sam")
    assert new_sam.get("/api/shared").json()["people"] == []
    for sid in range(1, 5):
        assert new_sam.get(f"/api/shared/{sid}/profile").status_code == 404
