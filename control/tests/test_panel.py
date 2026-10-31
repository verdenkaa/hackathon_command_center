import pytest
from fastapi.testclient import TestClient

from control.server import create_app


@pytest.fixture
def panel(tmp_path):
    app = create_app(tmp_path, token="test-local-capability", background=False)
    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        yield client


def login(client):
    return client.post("/api/session", json={"token": "test-local-capability"}, headers={"Origin": "http://127.0.0.1:8787"})


def test_panel_requires_a_capability_even_on_loopback(panel):
    assert panel.get("/").status_code == 200
    assert panel.get("/api/status").status_code == 401
    assert panel.post("/api/session", json={"token": "wrong"}, headers={"Origin": "http://127.0.0.1:8787"}).status_code == 401
    assert login(panel).status_code == 200
    assert panel.get("/api/status").status_code == 200


def test_cross_site_and_rebinding_requests_are_rejected(panel):
    login(panel)
    assert panel.post("/api/action/stop", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert panel.post("/api/action/stop").status_code == 403
    assert panel.get("/api/status", headers={"Host": "attacker.example"}).status_code == 403
    assert panel.post("/api/action/anything", headers={"Origin": "http://127.0.0.1:8787"}).status_code in {404, 422}


def test_secret_is_not_returned_by_status(panel):
    login(panel)
    response = panel.get("/api/status")
    assert "test-local-capability" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_autostart_preserves_identity_before_setup(panel, monkeypatch):
    import json
    login(panel)
    controller = panel.app.state.controller
    monkeypatch.setattr('control.server.autostart.set_enabled', lambda *args: None)
    monkeypatch.setattr('control.server.autostart.enabled', lambda *args: True)
    response = panel.post('/api/autostart', json={'enabled':True}, headers={'Origin':'http://127.0.0.1:8787'})
    assert response.status_code == 200
    assert json.loads((controller.folder / 'config.json').read_text())['id'] == controller.config['id']


def test_incomplete_restore_cannot_activate_external_actions(panel, monkeypatch):
    login(panel)
    controller = panel.app.state.controller
    controller.config.update(transfer_pending=True, restore_verified=False)
    monkeypatch.setattr(controller.docker, 'helper', lambda *args, **kwargs: pytest.fail('Unverified restore must remain stopped'))
    response = panel.post('/api/transfer/activate', json={'previous_server_stopped':True,'accept_quota_pause':True},
                          headers={'Origin':'http://127.0.0.1:8787'})
    assert response.status_code == 409
    assert controller.config['transfer_pending'] is True


def test_manual_telegram_cooldown_is_displayed_as_safe_event(panel):
    import time
    login(panel)
    controller = panel.app.state.controller
    controller.config['telegram_chat'] = '-100123'
    controller.history['records'] = [{'id':'new','file':'new.hcc','created':time.time()}]
    controller.history['telegram_attempt'] = time.time()
    assert panel.post('/api/action/telegram', headers={'Origin':'http://127.0.0.1:8787'}).status_code == 202
    for _ in range(100):
        if not controller.busy:
            break
        time.sleep(.01)
    assert any('30 минут' in event['message'] for event in controller.events)


def test_existing_installation_requires_explicit_attach(panel, tmp_path):
    login(panel)
    data = tmp_path / "existing"
    data.mkdir()
    (data / "hackathon.db").write_bytes(b"existing-database")
    result = panel.post("/api/setup", json={"data_dir": str(data), "mode": "new", "login": "operator"},
                        headers={"Origin": "http://127.0.0.1:8787"})
    assert result.status_code == 409
    assert (data / "hackathon.db").read_bytes() == b"existing-database"


def test_invalid_secret_input_is_not_echoed(panel):
    login(panel)
    response = panel.post("/api/settings", json={"telegram": "SYNTHETIC_SECRET", "telegram_chat": "bad"},
                          headers={"Origin": "http://127.0.0.1:8787"})
    assert response.status_code == 422
    assert "SYNTHETIC_SECRET" not in response.text


def test_mouse_action_waits_for_monitor_and_rejects_duplicate_booking(panel, monkeypatch):
    login(panel)
    controller = panel.app.state.controller
    monkeypatch.setattr(controller.docker, 'compose', lambda *args, **kwargs: b'')
    controller.lock.acquire()
    try:
        headers = {'Origin':'http://127.0.0.1:8787'}
        assert panel.post('/api/action/stop', headers=headers).status_code == 202
        assert controller.busy == 'stop'
        assert panel.post('/api/action/stop', headers=headers).status_code == 409
    finally:
        controller.lock.release()
    import time
    for _ in range(100):
        if not controller.busy:
            break
        time.sleep(.01)
    assert not controller.busy


def test_missing_restore_confirmation_does_not_consume_checked_archive(panel, tmp_path, monkeypatch):
    from control.tests.test_archives import data_at
    from control.archives import create_snapshot, encrypt_archive
    login(panel)
    controller = panel.app.state.controller
    controller.vault.put('operator', 'previous-synthetic-archive-key')
    monkeypatch.setattr(controller.docker, 'helper', lambda operation, **kwargs: b'["test-schema"]' if operation == 'schemas' else b'')
    monkeypatch.setattr(controller.docker, 'compose', lambda *args, **kwargs: b'')
    blob = encrypt_archive(create_snapshot(data_at(tmp_path / 'source'), 'test'), 'synthetic-archive-key')
    checked = panel.post('/api/restore/inspect', files={'file':('test.hcc', blob)}, data={'key':'synthetic-archive-key'},
                         headers={'Origin':'http://127.0.0.1:8787'})
    assert checked.status_code == 200
    ticket = checked.json()['ticket']
    assert panel.post('/api/restore/apply', json={'ticket':ticket, 'confirm':False}, headers={'Origin':'http://127.0.0.1:8787'}).status_code == 409
    assert panel.post('/api/restore/apply', json={'ticket':ticket, 'confirm':True}, headers={'Origin':'http://127.0.0.1:8787'}).status_code == 200
    assert 'previous-synthetic-archive-key' in controller.vault.get('operator_history')
