"""Тесты ИИ-советника (mock)."""
from __future__ import annotations

from tests.helpers import login


def test_ai_default_disabled(client):
    login(client)
    r = client.get("/api/v1/projects/1/ai/settings")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_ai_run_requires_enabled(client):
    login(client)
    r = client.post("/api/v1/projects/1/ai/run", json={"trigger": "manual"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "AI_DISABLED"


def test_ai_run_mock(client):
    login(client)
    assert client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True}).status_code == 200
    r = client.post("/api/v1/projects/1/ai/run", json={"trigger": "manual"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "gemini"
    assert body["trigger"] == "manual"
    assert body["summary"]
    assert body["content"]

    recs = client.get("/api/v1/projects/1/ai/recommendations").json()
    assert len(recs) == 1


def test_ai_settings_requires_captain(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "p", "password": "p", "display_name": "P"})
    client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "participant"})
    login(client, login="p", password="p")
    r = client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True})
    assert r.status_code == 403


def test_ai_rate_limit(client):
    login(client)
    client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True, "interval_minutes": 60})
    # Ручной запуск не лимитируется.
    assert client.post("/api/v1/projects/1/ai/run", json={"trigger": "manual"}).status_code == 200
    # Событийный запуск сразу после — ограничен.
    r = client.post("/api/v1/projects/1/ai/run", json={"trigger": "overdue"})
    assert r.status_code == 429


def test_ai_exclude_recommendation(client):
    login(client)
    client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True})
    rid = client.post("/api/v1/projects/1/ai/run", json={"trigger": "manual"}).json()["id"]
    r = client.post(f"/api/v1/projects/1/ai/recommendations/{rid}/exclude")
    assert r.status_code == 200
    assert r.json()["excluded"] is True
