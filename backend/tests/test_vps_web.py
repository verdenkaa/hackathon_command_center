"""Public VPS requests use the configured domain and secure login cookie."""
from fastapi.testclient import TestClient

from app.config import settings
from app.deps import get_db
from app.main import create_app
from app.services.portable import current_public_url


ORIGIN = "https://aion.example.com"


def test_web_login_and_origin_check(client, monkeypatch):
    monkeypatch.setattr(settings, "app_public_url", ORIGIN)
    web = create_app()
    web.dependency_overrides[get_db] = client.app.dependency_overrides[get_db]
    browser = TestClient(web, base_url=ORIGIN)
    payload = {"login": "admin", "password": "admin-pass-123"}
    wrong_origin = browser.post("/api/v1/auth/login", json=payload, headers={"Origin": "https://ops.example.com"})
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["error"]["code"] == "ORIGIN_MISMATCH"
    assert browser.get("/health", headers={"Host": "another.example.com"}).status_code == 400
    result = browser.post("/api/v1/auth/login", json=payload, headers={"Origin": ORIGIN})
    assert result.status_code == 200
    assert "Secure" in result.headers["set-cookie"]
    assert browser.get("/api/v1/auth/me").status_code == 200
    assert current_public_url() == ORIGIN
