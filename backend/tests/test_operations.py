"""Тесты операций: бэкапы, восстановление, завершение, фоновые задачи."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.helpers import login


def _make_user(client, username: str, password: str, role: str | None = None) -> int:
    login(client)
    r = client.post("/api/v1/admin/users", json={"login": username, "password": password, "display_name": username})
    uid = r.json()["id"]
    if role:
        client.post("/api/v1/admin/roles", json={"user_id": uid, "role": role, "project_id": 1})
    return uid


def test_backup_and_restore(client):
    login(client)
    client.post("/api/v1/projects/1/tasks", json={"title": "A"})
    bid = client.post("/api/v1/admin/backups").json()["id"]

    client.post("/api/v1/projects/1/tasks", json={"title": "B"})
    assert len(client.get("/api/v1/projects/1/tasks").json()) == 2

    r = client.post(f"/api/v1/admin/backups/{bid}/restore", json={"confirm": True})
    assert r.status_code == 200

    titles = [t["title"] for t in client.get("/api/v1/projects/1/tasks").json()]
    assert titles == ["A"]


def test_restore_requires_confirmation(client):
    login(client)
    bid = client.post("/api/v1/admin/backups").json()["id"]
    r = client.post(f"/api/v1/admin/backups/{bid}/restore", json={"confirm": False})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_completion_unanimous_and_readonly(client):
    login(client)
    c1 = _make_user(client, "cap1", "p1", "captain")
    assert c1 == 2

    # Админ голосует (captains() = admin + captain).
    login(client)
    r = client.post("/api/v1/projects/1/completion-votes", json={"action": "complete"})
    assert r.json()["state"] == "preparation"

    # Второй капитан голосует → единогласно.
    login(client, login="cap1", password="p1")
    r = client.post("/api/v1/projects/1/completion-votes", json={"action": "complete"})
    assert r.json()["state"] == "completed"

    # Завершённый проект — только чтение.
    r = client.post("/api/v1/projects/1/tasks", json={"title": "X"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROJECT_COMPLETED"


def test_completion_reopen(client):
    login(client)
    _make_user(client, "cap1", "p1", "captain")

    login(client)
    client.post("/api/v1/projects/1/completion-votes", json={"action": "complete"})
    login(client, login="cap1", password="p1")
    assert client.post("/api/v1/projects/1/completion-votes", json={"action": "complete"}).json()["state"] == "completed"

    # Повторное открытие.
    login(client)
    client.post("/api/v1/projects/1/completion-votes", json={"action": "reopen"})
    login(client, login="cap1", password="p1")
    r = client.post("/api/v1/projects/1/completion-votes", json={"action": "reopen"})
    assert r.json()["state"] == "preparation"


def test_jobs_overdue_notification(client):
    login(client)
    pid = _make_user(client, "part", "p", "participant")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    client.post("/api/v1/projects/1/tasks", json={"title": "Old", "deadline": past})

    r = client.post("/api/v1/admin/jobs/run")
    assert r.status_code == 200

    login(client, login="part", password="p")
    types = [n["type"] for n in client.get("/api/v1/notifications").json()]
    assert "task_overdue" in types
