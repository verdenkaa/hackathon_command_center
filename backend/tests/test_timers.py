"""Тесты таймеров и модели пересечений."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.timers import merge_intervals
from tests.helpers import login


def _create_task(client, title="T"):
    return client.post("/api/v1/projects/1/tasks", json={"title": title}).json()["id"]


def test_start_pause_stop(client):
    login(client)
    task_id = _create_task(client)
    r = client.post(f"/api/v1/tasks/{task_id}/timer/start")
    assert r.status_code == 200
    assert r.json()["state"] == "running"

    r = client.post(f"/api/v1/tasks/{task_id}/timer/pause")
    assert r.status_code == 200
    assert r.json()["state"] == "paused"

    r = client.post(f"/api/v1/tasks/{task_id}/timer/stop")
    assert r.status_code == 200
    assert r.json()["state"] == "stopped"


def test_double_start_conflict(client):
    login(client)
    task_id = _create_task(client)
    client.post(f"/api/v1/tasks/{task_id}/timer/start")
    r = client.post(f"/api/v1/tasks/{task_id}/timer/start")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TIMER_RUNNING"


def test_pause_requires_running(client):
    login(client)
    task_id = _create_task(client)
    r = client.post(f"/api/v1/tasks/{task_id}/timer/pause")
    assert r.status_code == 409


def test_parallel_timers_across_tasks(client):
    login(client)
    t1 = _create_task(client, "A")
    t2 = _create_task(client, "B")
    assert client.post(f"/api/v1/tasks/{t1}/timer/start").status_code == 200
    assert client.post(f"/api/v1/tasks/{t2}/timer/start").status_code == 200


def test_time_adjustment_requires_captain(client):
    login(client)
    task_id = _create_task(client)
    # Админ — тоже капитан/админ, поэтому разрешено.
    r = client.post(f"/api/v1/tasks/{task_id}/time-adjustment", json={"accumulated_seconds": 3600})
    assert r.status_code == 200
    assert r.json()["accumulated_seconds"] == 3600


def test_time_adjustment_denied_for_participant(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "p", "password": "p", "display_name": "P"})
    client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "participant"})
    task_id = _create_task(client)
    login(client, login="p", password="p")
    r = client.post(f"/api/v1/tasks/{task_id}/time-adjustment", json={"accumulated_seconds": 60})
    assert r.status_code == 403


def test_merge_intervals():
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    intervals = [
        (t0, t0 + timedelta(hours=1)),
        (t0 + timedelta(minutes=30), t0 + timedelta(hours=1, minutes=30)),
        (t0 + timedelta(hours=2), t0 + timedelta(hours=3)),
    ]
    # 0–1.5h (1.5h) + 2–3h (1h) = 2.5h = 9000с.
    assert merge_intervals(intervals) == 9000


def test_merge_intervals_empty():
    assert merge_intervals([]) == 0
