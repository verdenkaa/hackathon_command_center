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


def test_legacy_mock_history_remains_readable(client):
    login(client)
    assert client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True}).status_code == 200
    from tests.conftest import TestingSessionLocal
    from app.services.ai import run_recommendation
    with TestingSessionLocal() as db:
        rec = run_recommendation(db, 1, 'manual')
        assert rec.summary and rec.content
        db.commit()

    recs = client.get("/api/v1/projects/1/ai/recommendations").json()
    assert len(recs) == 1


def test_ai_settings_requires_captain(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "p", "password": "p", "display_name": "P"})
    client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "participant", "project_id": 1})
    login(client, login="p", password="p")
    r = client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True})
    assert r.status_code == 403


def test_ai_rate_limit(client):
    login(client)
    client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True, "interval_minutes": 60})
    # An API caller cannot impersonate the automatic scheduler.
    r = client.post("/api/v1/projects/1/ai/run", json={"trigger": "overdue"})
    assert r.status_code == 422


def test_ai_exclude_recommendation(client):
    login(client)
    client.patch("/api/v1/projects/1/ai/settings", json={"enabled": True})
    from tests.conftest import TestingSessionLocal
    from app.services.ai import run_recommendation
    with TestingSessionLocal() as db:
        rid = run_recommendation(db, 1, 'manual').id
        db.commit()
    r = client.post(f"/api/v1/projects/1/ai/recommendations/{rid}/exclude")
    assert r.status_code == 200
    assert r.json()["excluded"] is True
