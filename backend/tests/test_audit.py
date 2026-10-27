"""Тесты журнала действий: чтение доступно всем, правка — только админу."""
from __future__ import annotations

from tests.helpers import login


def test_audit_readable_by_participant(client):
    login(client)  # админ
    client.post("/api/v1/admin/users", json={"login": "pete", "password": "pete-pass", "display_name": "Pete"})

    # Пользователь без ролей может читать журнал.
    login(client, login="pete", password="pete-pass")
    r = client.get("/api/v1/audit")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # Но не может его редактировать.
    r = client.patch("/api/v1/admin/audit/1", json={"field": "action", "new_value": "x"})
    assert r.status_code == 403


def test_audit_requires_auth(client):
    assert client.get("/api/v1/audit").status_code == 401
