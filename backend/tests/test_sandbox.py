"""Тесты административной песочницы."""
from __future__ import annotations

from tests.helpers import login


def test_sandbox_scenarios(client):
    login(client)
    scenarios = client.get("/api/v1/admin/sandbox/scenarios").json()
    assert isinstance(scenarios, dict)
    assert "simulate_sprint" in scenarios

    for s in scenarios:
        r = client.post("/api/v1/admin/sandbox/run", json={"scenario": s})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    assert len(client.get("/api/v1/admin/sandbox/runs").json()) >= len(scenarios)


def test_sandbox_requires_admin(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "p", "password": "p", "display_name": "P"})
    client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "participant"})
    login(client, login="p", password="p")
    assert client.get("/api/v1/admin/sandbox/scenarios").status_code == 403
