"""Интеграции можно проверить без внешних запросов."""
from __future__ import annotations

from tests.helpers import login


def test_ai_preview_and_saved_context(client):
    login(client)
    client.patch('/api/v1/projects/1/ai/settings', json={'enabled': True, 'prompt': 'Проверь риски', 'triggers': {'overdue': False}})
    client.post('/api/v1/projects/1/tasks', json={'title': 'Контекст задачи', 'description': 'Важное описание'})
    preview = client.get('/api/v1/projects/1/ai/preview')
    assert preview.status_code == 200
    body = preview.json()
    assert body['mode'] == 'mock'
    assert body['prompt'] == 'Проверь риски'
    assert body['snapshot']['tasks'][0]['description'] == 'Важное описание'
    rec = client.post('/api/v1/projects/1/ai/run', json={'trigger': 'manual'}).json()
    assert rec['request_context'] == body
    assert client.post('/api/v1/projects/1/ai/run', json={'trigger': 'overdue'}).status_code == 409


def test_telegram_mock_journal(client):
    login(client)
    r = client.post('/api/v1/projects/1/incidents', json={'level': 'yellow', 'title': 'Тест Telegram'})
    assert r.status_code == 200
    messages = client.get('/api/v1/admin/sandbox/telegram?project_id=1')
    assert messages.status_code == 200
    message = messages.json()[0]
    assert message['project_id'] == 1
    assert message['event_type'] == 'incident_yellow_created'
    assert message['mode'] == 'mock'
    assert 'Тест Telegram' in message['text']
    assert message['created_at']


def test_sandbox_notifications_do_not_touch_working_project(client):
    login(client)
    client.post('/api/v1/projects/1/tasks', json={'title': 'Рабочая просрочка', 'deadline': '2020-01-01T00:00:00'})
    r = client.post('/api/v1/admin/sandbox/run', json={'scenario': 'mock_notifications'})
    assert r.status_code == 200 and r.json()['status'] == 'ok'
    rows = client.get('/api/v1/admin/sandbox/telegram').json()
    assert rows and all(m['project_id'] != 1 for m in rows)
    assert {'task_assigned', 'incident_yellow_created', 'task_overdue'} <= {m['event_type'] for m in rows}


def test_enabled_ai_trigger_creates_saved_mock_recommendation(client):
    login(client)
    client.patch('/api/v1/projects/1/ai/settings', json={'enabled': True, 'triggers': {'blocker_created': True}})
    client.post('/api/v1/projects/1/incidents', json={'level': 'yellow', 'title': 'Новый блокер'})
    rows = client.get('/api/v1/projects/1/ai/recommendations').json()
    assert len(rows) == 1
    assert rows[0]['trigger'] == 'blocker_created'
    assert rows[0]['request_context']['snapshot']['active_incidents'][0]['title'] == 'Новый блокер'
