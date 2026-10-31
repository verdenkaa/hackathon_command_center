import pytest
from unittest.mock import MagicMock

from app.config import settings
from app.services.bootstrap import bootstrap


def test_managed_bootstrap_refuses_known_password(monkeypatch):
    monkeypatch.setattr(settings, "app_managed", True)
    monkeypatch.setattr(settings, "app_first_admin_password", "change-me")
    db = MagicMock()
    db.query.return_value.count.return_value = 0
    with pytest.raises(RuntimeError, match="оператора"):
        bootstrap(db)


def test_public_restore_disabled_for_managed_installation(client, monkeypatch):
    monkeypatch.setattr(settings, "app_managed", True)
    client.post("/api/v1/auth/login", json={"login": "admin", "password": "admin-pass-123"})
    response = client.post("/api/v1/admin/backups/1/restore", json={"confirm": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCAL_PANEL_REQUIRED"


def test_shared_tunnel_address_does_not_lock_other_logins(client, monkeypatch):
    monkeypatch.setattr(settings, "app_managed", True)
    for number in range(12):
        assert client.post('/api/v1/auth/login', json={'login': f'wrong-{number}', 'password': 'bad'}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'login':'admin','password':'admin-pass-123'}).status_code == 200


def test_managed_health_checks_writable_storage(client, monkeypatch):
    from app.services import portable
    monkeypatch.setattr(settings, 'app_managed', True)
    monkeypatch.setattr(portable, 'storage_ready', lambda: False)
    assert client.get('/health').status_code == 503
