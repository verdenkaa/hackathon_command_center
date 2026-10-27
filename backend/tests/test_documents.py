"""Тесты документов и блокировок."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import login


def test_document_crud(client):
    login(client)
    r = client.post("/api/v1/projects/1/documents", json={"path": "docs/readme.md", "content": "# Hello"})
    assert r.status_code == 200
    doc = r.json()
    assert doc["path"] == "docs/readme.md"
    assert doc["trashed"] is False
    checksum = doc["checksum"]

    assert len(client.get("/api/v1/projects/1/documents").json()) == 1
    assert client.get(f"/api/v1/documents/{doc['id']}/content").json()["content"] == "# Hello"

    # Сохранение с корректным base_checksum.
    r = client.put(f"/api/v1/documents/{doc['id']}/content", json={"content": "# Updated", "base_checksum": checksum})
    assert r.status_code == 200
    assert r.json()["checksum"] != checksum

    # Конфликт при устаревшем checksum.
    r = client.put(f"/api/v1/documents/{doc['id']}/content", json={"content": "x", "base_checksum": checksum})
    assert r.status_code == 409

    # Корзина и восстановление.
    assert client.delete(f"/api/v1/documents/{doc['id']}").status_code == 200
    assert len(client.get("/api/v1/projects/1/documents/trash").json()) == 1
    assert client.post(f"/api/v1/documents/{doc['id']}/restore").status_code == 200
    assert len(client.get("/api/v1/projects/1/documents").json()) == 1


def test_document_reject_non_markdown(client):
    login(client)
    r = client.post("/api/v1/projects/1/documents", json={"path": "file.txt", "content": ""})
    assert r.status_code == 422


def test_document_lock_flow(client):
    login(client)
    doc = client.post("/api/v1/projects/1/documents", json={"path": "a.md", "content": ""}).json()
    did = doc["id"]

    r = client.post(f"/api/v1/documents/{did}/lock")
    assert r.status_code == 200
    assert r.json()["locked_by"] == 1

    r = client.post(f"/api/v1/documents/{did}/heartbeat")
    assert r.status_code == 200

    r = client.delete(f"/api/v1/documents/{did}/lock")
    assert r.status_code == 200
    assert r.json()["locked_by"] is None


def test_document_lock_conflict(client):
    login(client)
    client.post("/api/v1/admin/users", json={"login": "u2", "password": "p", "display_name": "U2"})
    doc = client.post("/api/v1/projects/1/documents", json={"path": "b.md", "content": ""}).json()
    did = doc["id"]

    client.post(f"/api/v1/documents/{did}/lock")  # админ держит блокировку

    u2 = TestClient(app)
    u2.post("/api/v1/auth/login", json={"login": "u2", "password": "p"})
    r = u2.post(f"/api/v1/documents/{did}/lock")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DOCUMENT_LOCKED"
