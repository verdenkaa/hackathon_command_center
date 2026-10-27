"""Тесты доски и модулей."""
from __future__ import annotations

from tests.helpers import login

EXPECTED_COLUMNS = [
    "backlog",
    "todo",
    "specification_review",
    "in_progress",
    "testing",
    "review",
    "done",
    "realised",
    "trashed",
]


def test_default_columns_order(client):
    login(client)
    r = client.get("/api/v1/projects/1/columns")
    assert r.status_code == 200
    cols = r.json()
    assert [c["key"] for c in cols] == EXPECTED_COLUMNS
    assert [c["position"] for c in cols] == list(range(9))


def test_modules_crud(client):
    login(client)
    r = client.post("/api/v1/projects/1/modules", json={"name": "Backend", "description": "Сервер"})
    assert r.status_code == 200
    mid = r.json()["id"]

    r = client.get("/api/v1/projects/1/modules")
    assert r.status_code == 200
    assert [m["name"] for m in r.json()] == ["Backend"]

    r = client.patch(f"/api/v1/modules/{mid}", json={"name": "API"})
    assert r.status_code == 200
    assert r.json()["name"] == "API"


def test_participant_can_create_module(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "p", "password": "p-pass", "display_name": "P"})
    client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "participant"})
    login(client, login="p", password="p-pass")
    r = client.post("/api/v1/projects/1/modules", json={"name": "Front"})
    assert r.status_code == 200


def test_custom_column_auto_timer(client):
    login(client)
    r = client.post("/api/v1/projects/1/columns", json={"title": "Работа", "auto_start_timer": True})
    assert r.status_code == 200
    col = r.json()
    assert col["auto_start_timer"] is True

    t = client.post("/api/v1/projects/1/tasks", json={"title": "A"}).json()
    r = client.post(f"/api/v1/tasks/{t['id']}/move", json={"column_key": col["key"], "version": 1})
    assert r.status_code == 200
    assert r.json()["timer"]["state"] == "running"  # правило авто-старта сработало


def test_default_column_protected(client):
    login(client)
    cols = client.get("/api/v1/projects/1/columns").json()
    backlog = next(c for c in cols if c["key"] == "backlog")
    r = client.delete(f"/api/v1/columns/{backlog['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "COLUMN_PROTECTED"


def test_delete_custom_column_moves_tasks(client):
    login(client)
    col = client.post("/api/v1/projects/1/columns", json={"title": "Custom"}).json()
    t = client.post("/api/v1/projects/1/tasks", json={"title": "B", "column_key": col["key"]}).json()
    r = client.delete(f"/api/v1/columns/{col['id']}")
    assert r.status_code == 200
    # Задача вернулась в backlog.
    tasks = client.get("/api/v1/projects/1/tasks").json()
    moved = next(x for x in tasks if x["id"] == t["id"])
    assert moved["column_key"] == "backlog"
