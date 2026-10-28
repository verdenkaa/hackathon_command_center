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
    from tests.conftest import TestingSessionLocal
    from app.services.ai import run_recommendation
    with TestingSessionLocal() as db:
        row = run_recommendation(db, 1, 'manual')
        rec = {'request_context': row.request_context}
        db.commit()
    # Separate snapshots have distinct calculation timestamps.
    rec['request_context']['snapshot']['analytics_summary'].pop('generated_at')
    body['snapshot']['analytics_summary'].pop('generated_at')
    assert rec['request_context'] == body
    assert client.post('/api/v1/projects/1/ai/run', json={'trigger': 'overdue'}).status_code == 422


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


def test_task_events_do_not_generate_mock_advice_or_call_provider(client):
    login(client)
    client.patch('/api/v1/projects/1/ai/settings', json={'enabled': True, 'triggers': {'blocker_created': True}})
    client.post('/api/v1/projects/1/incidents', json={'level': 'yellow', 'title': 'Новый блокер'})
    rows = client.get('/api/v1/projects/1/ai/recommendations').json()
    assert rows == []
