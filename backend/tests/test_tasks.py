"""Тесты задач, зависимостей и чек-листа."""
from __future__ import annotations

from tests.helpers import login


def _create_task(client, title="Задача", **extra):
    return client.post("/api/v1/projects/1/tasks", json={"title": title, **extra})


def test_create_task_default_backlog(client):
    login(client)
    r = _create_task(client, title="Первая")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Первая"
    assert body["column_key"] == "backlog"
    assert body["version"] == 1
    assert body["assignees"] == []
    assert body["predecessors"] == []
    assert body["timer"] is None


def test_move_task(client):
    login(client)
    task_id = _create_task(client).json()["id"]
    r = client.post(f"/api/v1/tasks/{task_id}/move", json={"column_key": "in_progress", "version": 1})
    assert r.status_code == 200
    assert r.json()["column_key"] == "in_progress"
    assert r.json()["version"] == 2


def test_version_conflict(client):
    login(client)
    task_id = _create_task(client).json()["id"]
    # Сначала меняем (version -> 2).
    client.post(f"/api/v1/tasks/{task_id}/move", json={"column_key": "todo", "version": 1})
    # Повторное изменение со старым version -> конфликт.
    r = client.post(f"/api/v1/tasks/{task_id}/move", json={"column_key": "done", "version": 1})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "VERSION_CONFLICT"


def test_set_assignees(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "alice", "password": "a", "display_name": "Alice"})
    task_id = _create_task(client).json()["id"]
    r = client.put(
        f"/api/v1/tasks/{task_id}/assignees",
        json={"assignees": [{"user_id": 2, "is_primary": True}]},
    )
    assert r.status_code == 200
    assignees = r.json()["assignees"]
    assert len(assignees) == 1
    assert assignees[0]["user_id"] == 2
    assert assignees[0]["is_primary"] is True


def test_assignees_require_one_primary(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "bob", "password": "b", "display_name": "Bob"})
    task_id = _create_task(client).json()["id"]
    r = client.put(
        f"/api/v1/tasks/{task_id}/assignees",
        json={"assignees": [{"user_id": 2, "is_primary": False}]},
    )
    assert r.status_code == 422


def test_dependencies(client):
    login(client)
    t1 = _create_task(client, title="T1").json()["id"]
    t2 = _create_task(client, title="T2").json()["id"]
    r = client.post(f"/api/v1/tasks/{t2}/dependencies", json={"predecessor_id": t1, "link_type": "blocked_by"})
    assert r.status_code == 200
    assert r.json()["predecessors"] == [{"task_id": t1, "link_type": "blocked_by"}]

    r = client.delete(f"/api/v1/tasks/{t2}/dependencies/{t1}")
    assert r.status_code == 200
    assert r.json()["predecessors"] == []


def test_self_dependency_rejected(client):
    login(client)
    t = _create_task(client).json()["id"]
    r = client.post(f"/api/v1/tasks/{t}/dependencies", json={"predecessor_id": t})
    assert r.status_code == 422


def test_checklist(client):
    login(client)
    task_id = _create_task(client).json()["id"]
    r = client.post(f"/api/v1/tasks/{task_id}/checklist", json={"text": "Пункт 1"})
    assert r.status_code == 200
    item_id = r.json()["id"]

    r = client.patch(f"/api/v1/checklist/{item_id}", json={"done": True})
    assert r.status_code == 200
    assert r.json()["done"] is True

    r = client.delete(f"/api/v1/checklist/{item_id}")
    assert r.status_code == 200


def test_task_filters(client):
    login(client)
    t = _create_task(client, title="С тегом", tags=["api"]).json()
    _create_task(client, title="Без тега")
    r = client.get("/api/v1/projects/1/tasks", params={"tag": "api"})
    assert r.status_code == 200
    assert [x["title"] for x in r.json()] == ["С тегом"]


def test_participant_can_create_task(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "carol", "password": "c", "display_name": "Carol"})
    client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "participant"})
    login(client, login="carol", password="c")
    r = _create_task(client, title="От участника")
    assert r.status_code == 200
