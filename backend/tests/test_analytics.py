"""Тесты аналитики, списка проектов и ролей."""
from __future__ import annotations

from tests.helpers import login


def test_analytics_endpoint(client):
    login(client)
    t = client.post("/api/v1/projects/1/tasks", json={"title": "A", "estimate_seconds": 3600}).json()
    client.post(f"/api/v1/tasks/{t['id']}/move", json={"column_key": "done", "version": 1})
    client.post("/api/v1/projects/1/tasks", json={"title": "B"})

    r = client.get("/api/v1/projects/1/analytics")
    assert r.status_code == 200
    body = r.json()
    assert body["kpi"]["total_tasks"] == 2
    assert body["kpi"]["completed_tasks"] == 1
    assert len(body["burn_down"]) >= 1
    assert isinstance(body["time_by_user"], list)


def test_projects_list(client):
    login(client)
    r = client.get("/api/v1/projects")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_project_rename(client):
    login(client)
    r = client.patch("/api/v1/projects/1", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"


def test_roles_list(client):
    login(client)
    r = client.get("/api/v1/admin/roles")
    assert r.status_code == 200
    assert any(x["role"] == "admin" for x in r.json())


def test_task_history(client):
    login(client)
    t = client.post("/api/v1/projects/1/tasks", json={"title": "H"}).json()
    client.post(f"/api/v1/tasks/{t['id']}/move", json={"column_key": "todo", "version": 1})
    r = client.get(f"/api/v1/tasks/{t['id']}/history")
    assert r.status_code == 200
    actions = [x["action"] for x in r.json()]
    assert "task.created" in actions
    assert "task.moved" in actions


def test_create_project(client):
    login(client)
    r = client.post("/api/v1/projects", json={"name": "Second"})
    assert r.status_code == 200
    pid = r.json()["id"]
    assert r.json()["name"] == "Second"
    # Колонки создаются автоматически.
    assert len(client.get(f"/api/v1/projects/{pid}/columns").json()) == 9


def test_delete_module(client):
    login(client)
    m = client.post("/api/v1/projects/1/modules", json={"name": "M"}).json()
    r = client.delete(f"/api/v1/modules/{m['id']}")
    assert r.status_code == 200
