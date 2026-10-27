"""Тесты администрирования: пользователи, роли, журнал, аудит."""
from __future__ import annotations

from tests.helpers import ADMIN_LOGIN, ADMIN_PASSWORD, login


def test_create_user_and_login(client):
    login(client)
    r = client.post(
        "/api/v1/admin/users",
        json={"login": "alice", "password": "alice-pass", "display_name": "Alice", "telegram_username": "@alice"},
    )
    assert r.status_code == 200
    assert r.json()["login"] == "alice"
    assert "password_hash" not in r.json()

    # Новый пользователь может войти.
    assert login(client, login="alice", password="alice-pass").status_code == 200


def test_create_duplicate_login(client):
    login(client)
    payload = {"login": "bob", "password": "bob-pass", "display_name": "Bob"}
    assert client.post("/api/v1/admin/users", json=payload).status_code == 200
    r = client.post("/api/v1/admin/users", json=payload)
    assert r.status_code == 409


def test_password_reset(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "carol", "password": "old", "display_name": "Carol"})
    r = client.post("/api/v1/admin/users/2/password-reset", json={"new_password": "new-pass"})
    assert r.status_code == 200
    assert login(client, login="carol", password="old").status_code == 401
    assert login(client, login="carol", password="new-pass").status_code == 200


def test_deactivate_revokes_access(client):
    from fastapi.testclient import TestClient

    from app.main import app

    login(client)
    client.post("/api/v1/admin/users", json={"login": "dave", "password": "dave-pass", "display_name": "Dave"})

    # Отдельный клиент с собственной сессией dave.
    dave_c = TestClient(app)
    login(dave_c, login="dave", password="dave-pass")
    assert dave_c.get("/api/v1/auth/me").json()["login"] == "dave"

    login(client)  # снова админ
    r = client.post("/api/v1/admin/users/2/deactivate")
    assert r.status_code == 200
    assert r.json()["active"] is False

    # Сессия dave отозвана.
    assert dave_c.get("/api/v1/auth/me").status_code == 401
    # Повторный вход деактивированному запрещён.
    assert login(dave_c, login="dave", password="dave-pass").status_code == 403


def test_last_admin_cannot_deactivate(client):
    login(client)
    r = client.post("/api/v1/admin/users/1/deactivate")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "LAST_ADMIN"


def test_assign_and_revoke_role(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "eve", "password": "eve-pass", "display_name": "Eve"})
    r = client.post("/api/v1/admin/roles", json={"user_id": 2, "role": "captain"})
    assert r.status_code == 200
    assignment_id = r.json()["id"]

    login(client, login="eve", password="eve-pass")
    me = client.get("/api/v1/auth/me").json()
    assert {role["role"] for role in me["roles"]} == {"captain"}

    login(client)
    r = client.delete(f"/api/v1/admin/roles/{assignment_id}")
    assert r.status_code == 200

    login(client, login="eve", password="eve-pass")
    assert client.get("/api/v1/auth/me").json()["roles"] == []


def test_last_admin_role_cannot_revoke(client):
    login(client)
    # Бутстрап создаёт роль admin с id=1; отзыв последнего админа запрещён.
    r = client.delete("/api/v1/admin/roles/1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "LAST_ADMIN"


def test_login_events_require_admin(client):
    assert client.get("/api/v1/admin/login-events").status_code == 401
    login(client)
    r = client.get("/api/v1/admin/login-events")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_audit_edit_creates_revision(client):
    login(client)
    # Создаём запись в аудите.
    client.post("/api/v1/admin/users", json={"login": "frank", "password": "p", "display_name": "Frank"})
    entries = client.get("/api/v1/audit").json()
    target = entries[0]
    r = client.patch(f"/api/v1/admin/audit/{target['id']}", json={"field": "action", "new_value": "user.edited"})
    assert r.status_code == 200
    revisions = client.get(f"/api/v1/audit/{target['id']}/revisions").json()
    assert len(revisions) == 1
    assert revisions[0]["old_value"] == target["action"]
    assert revisions[0]["new_value"] == "user.edited"


def test_reset_ip_limit(client):
    login(client)
    for _ in range(5):
        login(client, login="target2", password="bad")
    r = client.post("/api/v1/admin/ip-rules/reset?ip=testclient")
    assert r.status_code == 200
    # Лимит снят: попытка снова даёт 401, а не 429.
    assert login(client, login="target2", password="bad").status_code == 401
