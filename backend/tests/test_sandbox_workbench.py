"""Изоляция, быстрый старт и очистка тестового стенда."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.helpers import login


def test_demo_is_repeatable_and_has_workspace_summary(client):
    login(client)
    for _ in range(2):
        r = client.post('/api/v1/admin/sandbox/run', json={'scenario': 'prepare_demo'})
        assert r.status_code == 200 and r.json()['status'] == 'ok', r.json()
    workspace = client.get('/api/v1/admin/sandbox/workspace').json()
    assert workspace['project_id'] != 1
    assert workspace['counts']['tasks'] >= 9
    assert workspace['counts']['incidents'] >= 2
    assert workspace['counts']['modules'] == 2
    assert len(workspace['team']) == 3
    pid = workspace['project_id']
    tasks = client.get(f'/api/v1/projects/{pid}/tasks').json()
    assert len({t['title'] for t in tasks}) == len(tasks)
    assert any(t['checklist'] for t in tasks)
    assert any(t['predecessors'] for t in tasks)
    assert any(t['parent_id'] for t in tasks)


def test_reset_requires_exact_workspace_and_confirmation(client):
    login(client)
    for body in [{'project_id': 1}, {'project_id': 1, 'confirm': True}]:
        assert client.post('/api/v1/admin/sandbox/reset', json=body).status_code in (409, 422)
    assert len(client.get('/api/v1/projects').json()) == 1


def test_reset_preserves_working_data_and_shared_accounts(client):
    login(client)
    working = client.post('/api/v1/projects/1/tasks', json={'title': 'Рабочая задача'}).json()
    client.post('/api/v1/admin/sandbox/run', json={'scenario': 'prepare_demo'})
    workspace = client.get('/api/v1/admin/sandbox/workspace').json()
    pid = workspace['project_id']
    users_before = client.get('/api/v1/admin/users').json()
    # Identity must survive a rename, rather than deleting an arbitrary project by name.
    client.patch(f'/api/v1/projects/{pid}', json={'name': 'Renamed test workspace'})
    r = client.post('/api/v1/admin/sandbox/reset', json={'project_id': pid, 'confirm': True})
    assert r.status_code == 200, r.json()
    archive = Path(r.json()['archive_path'])
    assert archive.is_file()
    with sqlite3.connect(archive) as saved:
        assert saved.execute('SELECT count(*) FROM tasks WHERE project_id=?', (pid,)).fetchone()[0] >= 9
    assert client.get('/api/v1/admin/users').json() == users_before
    assert client.get('/api/v1/projects/1/tasks').json()[0]['id'] == working['id']
    after = client.get('/api/v1/admin/sandbox/workspace').json()
    assert after['project_id'] == pid and after['counts']['tasks'] == 0
    assert after['counts']['incidents'] == 0 and after['counts']['telegram'] == 0
    assert len(client.get(f'/api/v1/projects/{pid}/columns').json()) == 9
    assert client.get('/api/v1/admin/sandbox/runs').json() == []
    assert client.post('/api/v1/admin/sandbox/run', json={'scenario': 'prepare_demo'}).json()['status'] == 'ok'


def test_diagnostics_use_isolated_database_and_return_real_checks(client):
    login(client)
    before = client.get('/api/v1/projects').json()
    r = client.post('/api/v1/admin/sandbox/run', json={'scenario': 'full_check'})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body['status'] == 'ok', (body['logs'], body['checks'])
    assert len(body['checks']) >= 7
    assert all(c['status'] == 'passed' for c in body['checks'])
    assert body['duration_ms'] > 0
    assert client.get('/api/v1/projects').json() == before
    assert len(client.get('/api/v1/admin/users').json()) == 1
    assert client.get('/api/v1/admin/sandbox/runs').json()[0]['checks'] == body['checks']


def test_unknown_scenario_does_not_create_workspace(client):
    login(client)
    assert client.post('/api/v1/admin/sandbox/run', json={'scenario': 'unknown'}).status_code == 422
    assert len(client.get('/api/v1/projects').json()) == 1


def test_workbench_and_reset_are_admin_only(client):
    login(client)
    uid = client.post('/api/v1/admin/users', json={'login':'p','password':'p','display_name':'P'}).json()['id']
    client.post('/api/v1/admin/roles', json={'user_id':uid,'role':'captain','project_id':1})
    login(client, 'p', 'p')
    assert client.get('/api/v1/admin/sandbox/workspace').status_code == 403
    assert client.post('/api/v1/admin/sandbox/reset', json={'project_id':1,'confirm':True}).status_code == 403


def test_test_accounts_do_not_reuse_someones_password(client):
    login(client)
    uid = client.post('/api/v1/admin/users', json={'login':'alice','password':'personal-secret','display_name':'Real Alice'}).json()['id']
    client.post('/api/v1/admin/sandbox/run', json={'scenario':'create_team'})
    team = client.get('/api/v1/admin/sandbox/workspace').json()['team']
    replacement = next(u for u in team if u['role']=='participant' and u['login'].startswith('sandbox_alice'))
    assert replacement['user_id'] != uid
    assert login(client,'alice','personal-secret').status_code == 200
    assert login(client,replacement['login'],'sandbox-pass').status_code == 200


def test_failure_scenario_performs_checks_instead_of_just_logging(client):
    login(client)
    result=client.post('/api/v1/admin/sandbox/run',json={'scenario':'integration_failure'}).json()
    assert result['status']=='ok' and result['checks']
    assert result['checks'][0]['name']=='ai'
    assert len(client.get('/api/v1/projects').json())==1


def test_reset_archives_only_sandbox_documents(client):
    from app.config import settings
    login(client)
    client.post('/api/v1/admin/sandbox/run',json={'scenario':'create_team'})
    pid=client.get('/api/v1/admin/sandbox/workspace').json()['project_id']
    client.post('/api/v1/projects/1/documents',json={'path':'workbench-preserved.md','content':'working'})
    client.post(f'/api/v1/projects/{pid}/documents',json={'path':'sandbox-file.md','content':'test'})
    r=client.post('/api/v1/admin/sandbox/reset',json={'project_id':pid,'confirm':True})
    assert r.status_code==200, r.json()
    archive=Path(r.json()['archive_path'])
    assert (archive.with_suffix('')/'documents/sandbox-file.md').read_text(encoding='utf-8')=='test'
    assert (settings.data_dir/'documents/1/workbench-preserved.md').read_text(encoding='utf-8')=='working'
    assert not (settings.data_dir/'documents'/str(pid)/'sandbox-file.md').exists()


def test_reset_rejects_legacy_cross_project_dependency(client):
    from tests.conftest import TestingSessionLocal
    from app.db.models import TaskDependency
    login(client)
    working=client.post('/api/v1/projects/1/tasks',json={'title':'Working'}).json()['id']
    client.post('/api/v1/admin/sandbox/run',json={'scenario':'prepare_demo'})
    pid=client.get('/api/v1/admin/sandbox/workspace').json()['project_id']
    test_task=client.get(f'/api/v1/projects/{pid}/tasks').json()[0]['id']
    with TestingSessionLocal() as db:
        db.add(TaskDependency(task_id=working,predecessor_id=test_task,link_type='after'))
        db.commit()
    r=client.post('/api/v1/admin/sandbox/reset',json={'project_id':pid,'confirm':True})
    assert r.status_code==409 and r.json()['error']['code']=='SANDBOX_REFERENCED'
    assert client.get(f'/api/v1/tasks/{test_task}').status_code==200
    assert client.get(f'/api/v1/tasks/{working}').status_code==200


def test_recovery_check_exercises_backup_api_in_separate_process(client):
    login(client)
    client.post('/api/v1/projects/1/tasks',json={'title':'Live sentinel'})
    run=client.post('/api/v1/admin/sandbox/run',json={'scenario':'check:recovery'}).json()
    assert run['status']=='ok', run
    assert 'API резервного копирования' in run['checks'][0]['detail']
    assert [t['title'] for t in client.get('/api/v1/projects/1/tasks').json()]==['Live sentinel']
