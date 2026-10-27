"""Общие помощники тестов."""
from __future__ import annotations

ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "admin-pass-123"


def login(client, login: str = ADMIN_LOGIN, password: str = ADMIN_PASSWORD):
    return client.post("/api/v1/auth/login", json={"login": login, "password": password})
