"""Интеграционный тест: полный цикл работы команды через API."""
from __future__ import annotations

from tests.helpers import login


def _make_user(client, username: str, password: str, role: str) -> int:
    login(client)
    r = client.post("/api/v1/admin/users", json={"login": username, "password": password, "display_name": username})
    uid = r.json()["id"]
    client.post("/api/v1/admin/roles", json={"user_id": uid, "role": role})
    return uid


def test_full_cycle(client):
    # 1. Команда.
    login(client)
    cap = _make_user(client, "cap", "cap-pass", "captain")
    part = _make_user(client, "part", "part-pass", "participant")

    # 2. Задачи и зависимости.
    login(client)
    t1 = client.post("/api/v1/projects/1/tasks", json={"title": "Backend"}).json()
    t2 = client.post("/api/v1/projects/1/tasks", json={"title": "Frontend"}).json()
    client.put(f"/api/v1/tasks/{t1['id']}/assignees", json={"assignees": [{"user_id": cap, "is_primary": True}]})
    client.post(f"/api/v1/tasks/{t2['id']}/dependencies", json={"predecessor_id": t1["id"]})
    client.post(f"/api/v1/tasks/{t1['id']}/move", json={"column_key": "in_progress", "version": 1})

    # 3. Таймер.
    client.post(f"/api/v1/tasks/{t1['id']}/timer/start")
    client.post(f"/api/v1/tasks/{t1['id']}/timer/pause")

    # 4. Инциденты: жёлтый и красный.
    iid = client.post(
        "/api/v1/projects/1/incidents",
        json={"level": "red", "title": "Интеграция падает", "targets": [{"target_type": "task", "target_id": t1["id"]}]},
    ).json()["id"]
    login(client, login="cap", password="cap-pass")
    client.post(f"/api/v1/incidents/{iid}/confirm-red", json={"confirm": True})
    client.post(f"/api/v1/incidents/{iid}/resolve", json={"resolution": "Исправлено"})

    # 5. Документы.
    login(client)
    doc = client.post("/api/v1/projects/1/documents", json={"path": "notes.md", "content": "# Notes"}).json()
    client.put(f"/api/v1/documents/{doc['id']}/content", json={"content": "# Notes v2", "base_checksum": doc["checksum"]})

    # 6. Дашборд и ИИ.
    assert client.get("/api/v1/projects/1/dashboard").status_code == 200
    client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True})
    assert client.post("/api/v1/projects/1/ai/run", json={"trigger": "manual"}).status_code == 200

    # 7. Бэкап и восстановление.
    bid = client.post("/api/v1/admin/backups").json()["id"]
    client.post("/api/v1/projects/1/tasks", json={"title": "Лишняя"})
    assert client.post(f"/api/v1/admin/backups/{bid}/restore", json={"confirm": True}).status_code == 200

    # 8. Завершение (участник не голосует; капитаны единогласно).
    titles = [t["title"] for t in client.get("/api/v1/projects/1/tasks").json()]
    assert "Лишняя" not in titles  # восстановление вернуло состояние до «Лишняя»

    login(client)
    client.post("/api/v1/projects/1/completion-votes", json={"action": "complete"})
    login(client, login="cap", password="cap-pass")
    r = client.post("/api/v1/projects/1/completion-votes", json={"action": "complete"})
    assert r.json()["state"] == "completed"

    # 9. Завершённый проект — только чтение.
    assert client.post("/api/v1/projects/1/tasks", json={"title": "X"}).status_code == 409
