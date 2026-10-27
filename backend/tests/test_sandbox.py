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
    client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "participant", "project_id": 1})
    login(client, login="p", password="p")
    assert client.get("/api/v1/admin/sandbox/scenarios").status_code == 403


def test_sandbox_can_restore_revoked_test_role(client):
    login(client)
    client.post('/api/v1/admin/sandbox/run', json={'scenario': 'create_team'})
    cap = next(u for u in client.get('/api/v1/admin/users').json() if u['login'] == 'cap')
    role = next(r for r in client.get('/api/v1/admin/roles').json() if r['user_id'] == cap['id'])
    client.delete(f"/api/v1/admin/roles/{role['id']}")
    run = client.post('/api/v1/admin/sandbox/run', json={'scenario': 'mock_notifications'}).json()
    assert run['status'] == 'ok', run['logs']


def test_sandbox_preserves_deactivated_accounts(client):
    login(client)
    client.post('/api/v1/admin/sandbox/run', json={'scenario': 'create_team'})
    cap = next(u for u in client.get('/api/v1/admin/users').json() if u['login'] == 'cap')
    client.post(f"/api/v1/admin/users/{cap['id']}/deactivate")
    run = client.post('/api/v1/admin/sandbox/run', json={'scenario': 'create_team'}).json()
    assert run['status'] == 'ok'
    users = client.get('/api/v1/admin/users').json()
    assert next(u for u in users if u['login'] == 'cap')['active'] is False
    replacement = next(u for u in users if u['login'] == 'sandbox_cap')
    assert replacement['active'] is True
    assert login(client, 'sandbox_cap', 'sandbox-pass').status_code == 200
