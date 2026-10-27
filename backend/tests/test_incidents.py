"""Тесты инцидентов и светофора."""
from __future__ import annotations

from tests.helpers import login


def _make_user(client, username: str, password: str, role: str | None = None) -> int:
    login(client)
    r = client.post("/api/v1/admin/users", json={"login": username, "password": password, "display_name": username})
    uid = r.json()["id"]
    if role:
        client.post("/api/v1/admin/roles", json={"user_id": uid, "role": role, "project_id": 1})
    return uid


def test_create_yellow_incident(client):
    login(client)
    cid = _make_user(client, "cap", "cap-pass", "captain")
    login(client)
    r = client.post(
        "/api/v1/projects/1/incidents",
        json={"level": "yellow", "title": "Блокер", "description": "desc", "owner_id": cid,
              "targets": [{"target_type": "user", "target_id": cid}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["level"] == "yellow"
    assert body["status"] == "open"
    assert body["age_seconds"] >= 0
    assert len(body["targets"]) == 1
    assert body["events"][0]["event_type"] == "created"


def test_red_escalation_flow(client):
    login(client)
    _make_user(client, "cap", "cap-pass", "captain")
    _make_user(client, "part", "part-pass", "participant")

    # Участник создаёт красный запрос.
    login(client, login="part", password="part-pass")
    r = client.post("/api/v1/projects/1/incidents", json={"level": "red", "title": "Глобальная проблема"})
    assert r.status_code == 200
    iid = r.json()["id"]
    assert r.json()["status"] == "open"

    # Участник не может подтвердить.
    assert client.post(f"/api/v1/incidents/{iid}/confirm-red", json={"confirm": True}).status_code == 403

    # Капитан подтверждает.
    login(client, login="cap", password="cap-pass")
    r = client.post(f"/api/v1/incidents/{iid}/confirm-red", json={"confirm": True})
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    # Капитан закрывает.
    r = client.post(f"/api/v1/incidents/{iid}/resolve", json={"resolution": "Решено"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"
    assert r.json()["resolution"] == "Решено"


def test_red_reject_escalation(client):
    login(client)
    _make_user(client, "cap", "cap-pass", "captain")
    login(client)
    iid = client.post("/api/v1/projects/1/incidents", json={"level": "red", "title": "Проблема"}).json()["id"]
    login(client, login="cap", password="cap-pass")
    r = client.post(f"/api/v1/incidents/{iid}/confirm-red", json={"confirm": False, "comment": "Не критично"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"


def test_yellow_resolve_permission(client):
    login(client)
    cid = _make_user(client, "cap", "cap-pass", "captain")
    _make_user(client, "part", "part-pass", "participant")

    login(client, login="part", password="part-pass")
    iid = client.post(
        "/api/v1/projects/1/incidents", json={"level": "yellow", "title": "Блокер", "owner_id": cid}
    ).json()["id"]

    # Автор (не ответственный) не может закрыть.
    assert client.post(f"/api/v1/incidents/{iid}/resolve", json={"resolution": "x"}).status_code == 403

    # Ответственный (капитан) закрывает.
    login(client, login="cap", password="cap-pass")
    r = client.post(f"/api/v1/incidents/{iid}/resolve", json={"resolution": "Готово"})
    assert r.status_code == 200


def test_traffic_status(client):
    login(client)
    pid = _make_user(client, "part", "part-pass", "participant")
    login(client)
    client.post(
        "/api/v1/projects/1/incidents",
        json={"level": "yellow", "title": "Блокер", "targets": [{"target_type": "user", "target_id": pid}]},
    )
    parts = {p["id"]: p for p in client.get("/api/v1/projects/1/participants").json()}
    assert parts[pid]["traffic_status"] == "yellow"


def test_unconfirmed_red_does_not_color(client):
    login(client)
    pid = _make_user(client, "part", "part-pass", "participant")
    login(client)
    client.post(
        "/api/v1/projects/1/incidents",
        json={"level": "red", "title": "Проблема", "targets": [{"target_type": "user", "target_id": pid}]},
    )
    parts = {p["id"]: p for p in client.get("/api/v1/projects/1/participants").json()}
    assert parts[pid]["traffic_status"] == "green"


def test_comment_adds_event(client):
    login(client)
    iid = client.post("/api/v1/projects/1/incidents", json={"level": "yellow", "title": "Блокер"}).json()["id"]
    r = client.post(f"/api/v1/incidents/{iid}/events", json={"text": "Уточните"})
    assert r.status_code == 200
    events = r.json()["events"]
    assert events[-1]["event_type"] == "comment"
    assert events[-1]["data"]["text"] == "Уточните"
