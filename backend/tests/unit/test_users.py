"""Unit tests: user endpoints (DESIGN.md §3)."""
from __future__ import annotations


def test_create_user_returns_userout(client):
    resp = client.post(
        "/api/users",
        json={"name": "Ada Lovelace", "target_roles": ["Algorithm Researcher"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"]
    assert data["name"] == "Ada Lovelace"
    assert data["target_roles"] == ["Algorithm Researcher"]
    assert data["created_at"]


def test_get_user_roundtrip(client, make_user):
    user = make_user(name="Roundtrip User")
    resp = client.get("/api/users/{0}".format(user["id"]))
    assert resp.status_code == 200
    assert resp.json()["id"] == user["id"]
    assert resp.json()["name"] == "Roundtrip User"


def test_get_unknown_user_404(client):
    resp = client.get("/api/users/does-not-exist")
    assert resp.status_code == 404


def test_create_user_rejects_empty_name(client):
    resp = client.post("/api/users", json={"name": "", "target_roles": []})
    assert resp.status_code == 422


def test_create_user_rejects_bad_role(client):
    resp = client.post(
        "/api/users", json={"name": "X", "target_roles": ["Astronaut"]}
    )
    assert resp.status_code == 422


def test_list_user_sessions(client, make_user, make_session):
    user = make_user()
    resp = client.get("/api/users/{0}/sessions".format(user["id"]))
    assert resp.status_code == 200
    assert resp.json() == []

    sess = make_session(user_id=user["id"])
    resp = client.get("/api/users/{0}/sessions".format(user["id"]))
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert sess["id"] in ids


def test_list_sessions_unknown_user_404(client):
    resp = client.get("/api/users/nope/sessions")
    assert resp.status_code == 404
