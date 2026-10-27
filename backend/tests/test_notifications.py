"""Тесты внутренних уведомлений."""
from __future__ import annotations

from tests.helpers import login


def _make_user(client, username: str, password: str, role: str | None = None) -> int:
    login(client)
    r = client.post("/api/v1/admin/users", json={"login": username, "password": password, "display_name": username})
    uid = r.json()["id"]
    if role:
        client.post("/api/v1/admin/roles", json={"user_id": uid, "role": role, "project_id": 1})
    return uid


def test_notification_on_yellow_incident(client):
    login(client)
    cid = _make_user(client, "cap", "cap-pass", "captain")
    login(client)
    client.post("/api/v1/projects/1/incidents", json={"level": "yellow", "title": "Блокер", "owner_id": cid})

    login(client, login="cap", password="cap-pass")
    types = [n["type"] for n in client.get("/api/v1/notifications").json()]
    assert "incident_yellow_created" in types


def test_notification_on_task_assignment(client):
    login(client)
    pid = _make_user(client, "part", "part-pass", "participant")
    login(client)
    tid = client.post("/api/v1/projects/1/tasks", json={"title": "T"}).json()["id"]
    client.put(f"/api/v1/tasks/{tid}/assignees", json={"assignees": [{"user_id": pid, "is_primary": True}]})

    login(client, login="part", password="part-pass")
    types = [n["type"] for n in client.get("/api/v1/notifications").json()]
    assert "task_assigned" in types


def test_mark_read(client):
    login(client)
    pid = _make_user(client, "part", "part-pass", "participant")
    login(client)
    tid = client.post("/api/v1/projects/1/tasks", json={"title": "T"}).json()["id"]
    client.put(f"/api/v1/tasks/{tid}/assignees", json={"assignees": [{"user_id": pid, "is_primary": True}]})

    login(client, login="part", password="part-pass")
    n = client.get("/api/v1/notifications").json()[0]
    r = client.post(f"/api/v1/notifications/{n['id']}/read")
    assert r.status_code == 200
    assert r.json()["read_at"] is not None

    unread = client.get("/api/v1/notifications", params={"unread_only": True}).json()
    assert all(x["id"] != n["id"] for x in unread)


def test_notification_requires_auth(client):
    assert client.get("/api/v1/notifications").status_code == 401
