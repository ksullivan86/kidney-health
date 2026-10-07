"""GET /api/foods/builtin: the builtin list in one answer with an ETag (note 02 §6 item 9, R5; v0.3.0 review L9).

The route used to fall into ``/api/foods/{food_id}`` (400 "food_id: Input should be a valid integer"), and a device
refreshed its offline food list with one request per category every day. Now it asks once with the last ETag and
gets 304 with no body while the list is unchanged (js/offline.js ``downloadBuiltin``).
"""
from __future__ import annotations

from app import db, foods as foods_module


def test_the_builtin_list_comes_in_one_answer_with_an_etag(client) -> None:
    r = client.get("/api/foods/builtin")
    assert r.status_code == 200, r.text
    listed = r.json()["foods"]
    assert listed and all(f["source"] == "builtin" and not f["hidden"] for f in listed)
    assert [f["id"] for f in listed] == sorted(f["id"] for f in listed)
    by_search = {f["id"] for c in client.get("/api/foods/categories").json()["categories"]
                 for f in client.get("/api/foods", params={"category": c, "source": "builtin", "limit": 200}).json()["foods"]}
    assert {f["id"] for f in listed} == by_search  # the same foods the per-category search finds
    etag = r.headers["ETag"]
    assert etag.startswith('"') and etag.endswith('"') and "-" in etag
    assert r.headers["Cache-Control"] == "no-store"  # the device keeps the copy itself, never the browser cache


def test_if_none_match_with_the_etag_answers_304_without_a_body(client) -> None:
    etag = client.get("/api/foods/builtin").headers["ETag"]
    again = client.get("/api/foods/builtin", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b"" and again.headers["ETag"] == etag
    assert client.get("/api/foods/builtin", headers={"If-None-Match": f'"other", W/{etag}'}).status_code == 304
    assert client.get("/api/foods/builtin", headers={"If-None-Match": '"2026-01-01-0000"'}).status_code == 200


def test_the_etag_changes_when_the_list_changes(client, settings) -> None:
    first = client.get("/api/foods/builtin")
    target = first.json()["foods"][0]["id"]
    conn = db.connect(settings.db_path)
    try:
        conn.execute("UPDATE foods SET hidden = 1 WHERE id = ?", (target,))  # as an import that drops a food does
        conn.commit()
    finally:
        conn.close()
    second = client.get("/api/foods/builtin", headers={"If-None-Match": first.headers["ETag"]})
    assert second.status_code == 200 and second.headers["ETag"] != first.headers["ETag"]
    assert target not in {f["id"] for f in second.json()["foods"]}


def test_the_builtin_list_needs_a_signed_in_person(anon_client) -> None:
    assert anon_client.get("/api/foods/builtin").status_code == 401


def test_the_route_is_matched_before_the_food_id_route() -> None:
    paths = [getattr(r, "path", "") for r in foods_module.router.routes]
    assert paths.index("/api/foods/builtin") < paths.index("/api/foods/{food_id}")
