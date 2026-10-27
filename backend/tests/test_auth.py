"""Тесты аутентификации и ограничений."""
from __future__ import annotations

from tests.helpers import ADMIN_LOGIN, ADMIN_PASSWORD, login


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_login_success(client):
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["login"] == ADMIN_LOGIN
    assert "password_hash" not in body


def test_login_wrong_password(client):
    r = login(client, password="wrong")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "BAD_CREDENTIALS"


def test_login_unknown_user(client):
    r = login(client, login="ghost")
    assert r.status_code == 401


def test_me_authenticated(client):
    login(client)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["login"] == ADMIN_LOGIN
    roles = {role["role"] for role in body["roles"]}
    assert "admin" in roles


def test_me_unauthenticated(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_logout(client):
    login(client)
    assert client.get("/api/v1/auth/me").status_code == 200
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_rate_limit_by_login(client):
    for _ in range(5):
        assert login(client, login="target", password="bad").status_code == 401
    r = login(client, login="target", password="bad")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_ip_blocked(client):
    login(client)
    r = client.post("/api/v1/admin/ip-rules", json={"ip": "testclient"})
    assert r.status_code == 200
    # Блокировка применяется на следующем входе.
    r = login(client, login="other", password="x")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "IP_BLOCKED"
