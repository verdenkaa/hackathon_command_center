"""Advisor contracts use a fake provider and isolated SQLite only."""
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from tests.helpers import login
from tests.conftest import TestingSessionLocal


def test_reply_contract():
    from app.advisor_schemas import AnalysisReply
    assert AnalysisReply.model_validate({'captain_intervention': 'not_required', 'result': 'no_new_recommendations', 'recommendations': []})
    with pytest.raises(ValidationError):
        AnalysisReply.model_validate({'captain_intervention': 'required', 'result': 'recommendations', 'recommendations': []})
    with pytest.raises(ValidationError):
        AnalysisReply.model_validate({'captain_intervention': 'not_required', 'result': 'no_new_recommendations', 'recommendations': [], 'thoughts': 'private'})


def test_pacific_reset_dst():
    from app.services.advisor import day_window
    start, end = day_window(datetime(2026, 3, 8, 12))
    assert end - start == timedelta(hours=23)
    start, end = day_window(datetime(2026, 11, 1, 12))
    assert end - start == timedelta(hours=25)


def setup_advisor(client, monkeypatch):
    from app.services import advisor
    monkeypatch.setattr(advisor.vault, 'available', lambda: True)
    monkeypatch.setattr(advisor.vault, 'is_saved', lambda: True)
    login(client)
    assert client.patch('/api/v1/projects/1/ai/settings', json={'enabled': True}).status_code == 200
    return advisor


def test_questions_analysis_and_history(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    job = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'question', 'question': 'Что неизвестно?'}).json()
    assert job['state'] == 'queued'
    svc.work_once(TestingSessionLocal, provider=lambda *_: svc.ProviderReply(
        {'answer': 'Нет сведений о навыках.', 'grounds': ['Доступность не задана'],
         'limitations': ['Нужно уточнить у команды'], 'related': {}}))
    result = client.get(f"/api/v1/projects/1/ai/requests/{job['id']}").json()
    assert result['state'] == 'succeeded' and result['answer']['answer']
    analysis = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).json()
    svc.work_once(TestingSessionLocal, provider=lambda *_: svc.ProviderReply(
        {'captain_intervention': 'not_required', 'result': 'no_new_recommendations', 'recommendations': []}))
    assert client.get(f"/api/v1/projects/1/ai/requests/{analysis['id']}").json()['state'] == 'succeeded'
    assert client.get('/api/v1/projects/1/ai/recommendations').json() == []


def test_permissions_and_project_isolation(client, monkeypatch):
    setup_advisor(client, monkeypatch)
    client.post('/api/v1/admin/users', json={'login': 'reader', 'password': 'p', 'display_name': 'Reader'})
    client.post('/api/v1/admin/roles', json={'user_id': 2, 'role': 'participant', 'project_id': 1})
    other = client.post('/api/v1/projects', json={'name': 'Other'}).json()['id']
    login(client, login='reader', password='p')
    assert client.get('/api/v1/projects/1/ai/recommendations').status_code == 200
    assert client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).status_code == 403
    assert client.post('/api/v1/projects/1/ai/run', json={}).status_code == 403
    assert client.get(f'/api/v1/projects/{other}/ai/requests').status_code == 403
    assert client.get('/api/v1/ai/provider').status_code == 403


def recommendation(task_ids=None):
    return {'title': 'Уточните план', 'situation': 'План неполный', 'grounds': ['Нет размещений'],
            'consequence': 'Срок неизвестен', 'action': 'Обсудите размещение',
            'limitations': ['Доступность людей неизвестна'], 'related': {'task_ids': task_ids or []},
            'significance': 'warning', 'freshness': 'current'}


def test_invalid_ids_and_safe_errors(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    job = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).json()
    svc.work_once(TestingSessionLocal, provider=lambda *_: svc.ProviderReply(
        {'captain_intervention': 'required', 'result': 'recommendations', 'recommendations': [recommendation([99999])]}))
    result = client.get(f"/api/v1/projects/1/ai/requests/{job['id']}").json()
    assert result['state'] == 'failed' and result['error_code'] == 'INVALID_RESPONSE'
    assert not client.get('/api/v1/projects/1/ai/recommendations').json()


def test_dedup_status_and_exclusion(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    provider = lambda *_: svc.ProviderReply({'captain_intervention': 'required', 'result': 'recommendations', 'recommendations': [recommendation()]})
    for _ in range(2):
        client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'})
        svc.work_once(TestingSessionLocal, provider=provider)
    recs = client.get('/api/v1/projects/1/ai/recommendations').json()
    assert len(recs) == 1
    rid = recs[0]['id']
    changed = client.patch(f'/api/v1/projects/1/ai/recommendations/{rid}',
                           json={'status': 'accepted', 'comment': 'Обсудим'}).json()
    assert changed['status'] == 'accepted' and changed['status_by'] == 1
    client.post(f'/api/v1/projects/1/ai/recommendations/{rid}/exclude')
    with TestingSessionLocal() as db:
        snap = svc.snapshot(db, 1)
        assert not snap['history']
        assert snap['version'] and snap['generated_at']
        assert 'skills' not in str(snap['summary']['participants'])


def test_reservation_concurrency_and_restart(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    client.patch('/api/v1/ai/provider', json={'rpm': 1, 'rpd': 5, 'tpm': 1000})
    def reserve(_):
        with TestingSessionLocal() as db:
            return svc.reserve(db, 1, 100)[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sum(x is not None for x in results) == 1
    with TestingSessionLocal() as db:
        assert svc.quota(db)['day_used'] == 1


def test_minimum_context_too_large(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    with pytest.raises(svc.ContextTooLarge):
        svc.prepare({'history': [], 'summary': {'huge': 'x' * 10000}}, 'question', 'Q', '', 50)


def test_retry_accounting_and_manual_priority(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from app.db.models import AdvisorJob
    with TestingSessionLocal() as db:
        auto = svc.enqueue(db, 1, None, 'analysis', '', 'automatic')
        auto_id = auto.id
    question = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'question', 'question': 'Q'}).json()
    def fail(*_):
        raise svc.ProviderError('TEMPORARY', retry_after=2)
    svc.work_once(TestingSessionLocal, provider=fail)
    with TestingSessionLocal() as db:
        assert db.get(AdvisorJob, auto_id).attempts == 0
        assert db.get(AdvisorJob, question['id']).attempts == 1
        assert svc.quota(db)['day_used'] == 1


def test_schedule_coalesces_and_stops(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from app.db.models import AiSettings, Project, AdvisorJob
    with TestingSessionLocal() as db:
        db.get(Project, 1).state = 'active'
        settings = db.query(AiSettings).filter_by(project_id=1).one()
        settings.auto_enabled = True
        settings.next_run_at = datetime(2000, 1, 1)
        db.commit()
        svc.schedule(db)
        svc.schedule(db)
        assert db.query(AdvisorJob).count() == 1
        db.get(Project, 1).state = 'completed'
        db.commit()
        svc.schedule(db)
        assert db.query(AdvisorJob).count() == 1


def test_missing_key_never_calls_provider(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    monkeypatch.setattr(svc.vault, 'is_saved', lambda: False)
    assert client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).status_code == 409

