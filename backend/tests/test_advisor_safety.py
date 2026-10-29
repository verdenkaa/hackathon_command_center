"""Failure boundaries and persistence for the advisor, without network calls."""
from datetime import timedelta
import json

import pytest

from tests.conftest import TestingSessionLocal
from tests.helpers import login
from tests.test_advisor import setup_advisor, recommendation


def test_trim_marks_partial_coverage_without_mutating_history(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    with TestingSessionLocal() as db:
        snap = svc.snapshot(db, 1)
    snap['history'] = [{'content': 'old model text ' * 10000}]
    _, content, _ = svc.prepare(snap, 'analysis', '', '', 20000)
    sent = json.loads(content)['snapshot']
    assert sent['coverage']['incomplete'] and not sent['history']
    assert snap['history']


def test_minute_sum_and_daily_limit(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    client.patch('/api/v1/ai/provider', json={'tpm': 1000, 'rpm': 10, 'rpd': 2})
    from app.db.models import AdvisorAttempt
    from app.timeutil import utcnow
    with TestingSessionLocal() as db:
        assert svc.reserve(db, 1, 500)[0]
        assert svc.reserve(db, 2, 401)[1] == 'MINUTE_LIMIT'
        assert svc.reserve(db, 2, 400)[0]
        db.query(AdvisorAttempt).update({'created_at': utcnow()-timedelta(minutes=2)})
        db.commit()
        assert svc.reserve(db, 3, 1)[1] == 'DAILY_LIMIT'
        assert svc.quota(db)['day_used'] == 2


def test_interrupted_lease_keeps_attempt_charged(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from app.db.models import AdvisorJob
    from app.timeutil import utcnow
    job = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).json()
    with TestingSessionLocal() as db:
        row = db.get(AdvisorJob, job['id'])
        row.state = 'running'
        row.lease_until = utcnow()-timedelta(seconds=1)
        db.commit()
        svc.reserve(db, row.id, 100)
    svc.work_once(TestingSessionLocal, provider=lambda *_: pytest.fail('No repeated external call'))
    with TestingSessionLocal() as db:
        row = db.get(AdvisorJob, job['id'])
        assert row.state == 'failed' and row.error_code == 'INTERRUPTED'
        assert svc.quota(db)['day_used'] == 1


def test_wrong_project_job_and_status_forbidden(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    job = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).json()
    svc.work_once(TestingSessionLocal, provider=lambda *_: svc.ProviderReply(
        {'captain_intervention': 'required', 'result': 'recommendations', 'recommendations': [recommendation()]}))
    rid = client.get('/api/v1/projects/1/ai/recommendations').json()[0]['id']
    other = client.post('/api/v1/projects', json={'name': 'Other'}).json()['id']
    assert client.get(f"/api/v1/projects/{other}/ai/requests/{job['id']}").status_code == 404
    assert client.patch(f'/api/v1/projects/{other}/ai/recommendations/{rid}', json={'status': 'accepted'}).status_code == 404
    client.post('/api/v1/admin/users', json={'login': 'reader', 'password': 'p', 'display_name': 'R'})
    client.post('/api/v1/admin/roles', json={'user_id': 2, 'role': 'participant', 'project_id': 1})
    login(client, login='reader', password='p')
    assert client.patch(f'/api/v1/projects/1/ai/recommendations/{rid}', json={'status': 'accepted'}).status_code == 403
    assert client.delete('/api/v1/ai/provider/key').status_code == 403


def test_raw_errors_and_thoughts_are_never_saved(client, monkeypatch, caplog):
    svc = setup_advisor(client, monkeypatch)
    secret = 'synthetic-private-provider-error'
    job = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).json()
    def failure(*_):
        raise RuntimeError(secret)
    svc.work_once(TestingSessionLocal, provider=failure)
    body = client.get(f"/api/v1/projects/1/ai/requests/{job['id']}").text
    assert secret not in body and secret not in caplog.text
    from app.db.models import AdvisorJob
    with TestingSessionLocal() as db:
        row = db.get(AdvisorJob, job['id'])
        assert row.error_code == 'TEMPORARY' and row.answer is None


def test_dpapi_round_trip_and_ciphertext_only(tmp_path, monkeypatch):
    from app.services import advisor_vault as vault
    if not vault.available():
        pytest.skip('Windows DPAPI only')
    path = tmp_path / 'test.dpapi'
    monkeypatch.setattr(vault, '_path', lambda: path)
    synthetic = 'synthetic-key-for-dpapi-unit-test'
    vault.save(synthetic)
    assert vault.is_saved() and synthetic.encode() not in path.read_bytes()
    assert vault.load() == synthetic
    vault.delete()
    assert not vault.is_saved()


def test_sdk_config_and_response_filtering(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from google import genai
    from types import SimpleNamespace
    captures = {}
    class FakeClient:
        def __init__(self, **kwargs):
            captures.update(kwargs)
            self.models = self
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def generate_content(self, **kwargs):
            captures.update(kwargs)
            return SimpleNamespace(text='{"captain_intervention":"not_required","result":"no_new_recommendations","recommendations":[]}',
                usage_metadata=SimpleNamespace(prompt_token_count=15, candidates_token_count=8, thoughts_token_count=2))
    monkeypatch.setattr(genai, 'Client', FakeClient)
    monkeypatch.setattr(svc.vault, 'load', lambda: 'synthetic-sdk-key')
    with TestingSessionLocal() as db:
        cfg = svc.config(db)
        result = svc.gemini(cfg, 'analysis', 'trusted', '{}')
    assert captures['http_options'].retry_options.attempts == 1
    assert captures['config'].thinking_config.include_thoughts is False
    assert result.input_tokens == 15 and 'thoughts' not in result.data


def test_provider_daily_exhaustion_stops_other_projects(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from app.db.models import AdvisorAttempt
    with TestingSessionLocal() as db:
        db.add(AdvisorAttempt(job_id=1, reserved_tokens=100, outcome='PROVIDER_DAILY_LIMIT'))
        db.commit()
        assert svc.reserve(db, 2, 100)[1] == 'PROVIDER_DAILY_LIMIT'


def test_revoked_permission_cancels_before_provider(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from app.db.models import User, AdvisorJob
    job = client.post('/api/v1/projects/1/ai/requests', json={'kind': 'analysis'}).json()
    with TestingSessionLocal() as db:
        db.get(User, 1).active = False
        db.commit()
    svc.work_once(TestingSessionLocal, provider=lambda *_: pytest.fail('Revoked account must not call provider'))
    with TestingSessionLocal() as db:
        assert db.get(AdvisorJob, job['id']).state == 'cancelled'


def test_snapshot_serializes_plan_and_live_incident(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from tests.test_planning import task, lane, place
    first = task(client, 'Unfinished')
    track = lane(client)
    place(client, first, track, start='2030-01-01T08:00:00')
    assert client.post(f"/api/v1/tasks/{first['id']}/timer/start").status_code == 200
    incident = client.post('/api/v1/projects/1/incidents', json={'title': 'Open incident', 'level': 'yellow',
        'targets': [{'target_type': 'task', 'target_id': first['id']}]}).json()
    with TestingSessionLocal() as db:
        snap = svc.snapshot(db, 1)
        svc.prepare(snap, 'analysis', '', '', 100000)
    assert snap['planning']['placements'][0]['actual_started_at']
    assert snap['summary']['incidents'][0]['id'] == incident['id']
    assert snap['incident_details'][0]['created_at']
    assert snap['summary']['plan']['incomplete']


def test_sandbox_reset_clears_requests_but_keeps_budget(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from app.db.models import AdvisorJob
    client.post('/api/v1/admin/sandbox/run', json={'scenario': 'prepare_demo'})
    pid = client.get('/api/v1/admin/sandbox/workspace').json()['project_id']
    job = client.post(f'/api/v1/projects/{pid}/ai/requests', json={'kind': 'analysis'}).json()
    with TestingSessionLocal() as db:
        assert svc.reserve(db, job['id'], 100)[0]
    assert client.post('/api/v1/admin/sandbox/reset', json={'project_id': pid, 'confirm': True}).status_code == 200
    with TestingSessionLocal() as db:
        assert db.get(AdvisorJob, job['id']) is None
        assert svc.quota(db)['day_used'] == 1


def test_partial_context_is_reported_even_if_provider_omits_warning(client, monkeypatch):
    svc = setup_advisor(client, monkeypatch)
    from app.db.models import AdvisorJob
    with TestingSessionLocal() as db:
        snap = svc.snapshot(db, 1)
        snap['coverage'] = {'incomplete': True, 'omissions': ['Старая история сокращена']}
        job = AdvisorJob(project_id=1, kind='question', trigger='manual', snapshot=snap)
        svc._save_result(db, job, {'answer': 'Ответ', 'grounds': ['Снимок проекта'],
            'limitations': ['Доступность неизвестна'], 'related': {}})
        assert 'Неполный контекст' in job.answer['limitations'][-1]
