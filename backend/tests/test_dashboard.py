"""Тесты дашборда."""
from __future__ import annotations

from tests.helpers import login


def _create_task(client, title="T", column_key="backlog", **extra):
    return client.post("/api/v1/projects/1/tasks", json={"title": title, "column_key": column_key, **extra}).json()


def test_dashboard_empty(client):
    login(client)
    r = client.get("/api/v1/projects/1/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["total_tasks"] == 0
    assert body["progress_percent"] == 0.0
    assert body["project"]["name"] == "Hackathon"


def test_dashboard_progress(client):
    login(client)
    t1 = _create_task(client, "A")
    t2 = _create_task(client, "B")
    # Переместить одну в done.
    client.post(f"/api/v1/tasks/{t1['id']}/move", json={"column_key": "done", "version": 1})
    r = client.get("/api/v1/projects/1/dashboard").json()
    assert r["total_tasks"] == 2
    assert r["completed_tasks"] == 1
    assert r["progress_percent"] == 50.0


def test_dashboard_overdue(client):
    from datetime import datetime, timedelta, timezone

    login(client)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _create_task(client, "Просрочена", deadline=past)
    r = client.get("/api/v1/projects/1/dashboard").json()
    assert r["overdue_tasks"] == 1
    assert len(r["risks"]) == 1
    assert r["risks"][0]["type"] == "overdue"
