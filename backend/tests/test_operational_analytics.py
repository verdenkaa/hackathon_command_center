"""Operational summary shares planning, escalation and AI facts."""
from datetime import datetime

import pytest

from tests.helpers import login
from tests.test_planning import lane, place, task, state


def summary(client):
    response = client.get('/api/v1/projects/1/analytics')
    assert response.status_code == 200, response.text
    return response.json()['summary']


def test_completed_tasks_do_not_count_as_operational_overlaps(client):
    login(client)
    from tests.conftest import TestingSessionLocal
    from app.db.models import Task, BoardColumn
    rows = [task(client, name) for name in ('First', 'Second', 'Finished')]
    track = lane(client)
    for t in rows:
        client.put(f"/api/v1/tasks/{t['id']}/assignees", json={'assignees':[{'user_id':1,'is_primary':True}]})
        place(client, t, track)
    with TestingSessionLocal() as db:
        db.get(Task, rows[2]['id']).column_id = db.query(BoardColumn).filter_by(project_id=1, semantic='done').first().id
        db.commit()
    result = summary(client)
    expected = [rows[0]['id'], rows[1]['id']]
    assert next(p for p in result['participants'] if p['id'] == 1)['overlaps'] == [expected]
    assert [a['task_ids'] for a in result['attention'] if a['code'] == 'overlap'] == [expected]


def test_project_period_validation_and_no_rescheduling(client):
    login(client)
    t, l = task(client), lane(client)
    place(client, t, l)
    before = state(client)['placements']
    assert client.get('/api/v1/projects/1').json()['start_msk'] is None
    for start in ['2026-10-29T12:00:00+03:00', '2026-10-30T12:00:00+03:00']:
        assert client.patch('/api/v1/projects/1', json={'start_msk': start, 'deadline_msk': '2026-10-29T12:00:00+03:00'}).status_code == 422
    r = client.patch('/api/v1/projects/1', json={'start_msk': '2026-10-28T12:00:00+03:00', 'deadline_msk': '2026-10-29T12:00:00+03:00'})
    assert r.status_code == 200
    assert r.json()['start_msk'] == '2026-10-28T09:00:00'
    assert [(p['start'],p['planned_end'],p['pinned']) for p in state(client)['placements']] == [(p['start'],p['planned_end'],p['pinned']) for p in before]
    assert client.patch('/api/v1/projects/1', json={'deadline_msk': '2026-10-27T00:00:00Z'}).status_code == 422
    assert client.patch('/api/v1/projects/1', json={'start_msk': None, 'deadline_msk': None}).status_code == 200


@pytest.mark.parametrize('now,phase,percent,left,late', [
    ('2026-10-28T08:00:00', 'before_start', 0, 7200, 0),
    ('2026-10-28T09:30:00', 'running', 50, 1800, 0),
    ('2026-10-28T11:00:00', 'overdue', 100, 0, 3600),
])
def test_calendar_period(client, monkeypatch, now, phase, percent, left, late):
    login(client)
    client.patch('/api/v1/projects/1', json={'start_msk': '2026-10-28T09:00:00Z', 'deadline_msk': '2026-10-28T10:00:00Z'})
    monkeypatch.setattr('app.services.operational.utcnow', lambda: datetime.fromisoformat(now))
    period = summary(client)['period']
    assert (period['phase'], period['percent'], period['remaining_seconds'], period['overdue_seconds']) == (phase, percent, left, late)


def test_progress_excludes_trash_and_does_not_consume_estimates(client):
    login(client)
    a, b = task(client, 'Done', 3600), task(client, 'Remaining', 7200)
    task(client, 'Unknown', None)
    trash = task(client, 'Trash', 9999)
    client.post(f"/api/v1/tasks/{a['id']}/move", json={'column_key': 'done', 'version': 1})
    client.post(f"/api/v1/tasks/{trash['id']}/move", json={'column_key': 'trashed', 'version': 1})
    client.post(f"/api/v1/tasks/{b['id']}/time-adjustment", json={'accumulated_seconds':9000})
    client.post(f"/api/v1/tasks/{trash['id']}/time-adjustment", json={'accumulated_seconds':1000})
    s = summary(client)
    assert s['progress']['tasks']['numerator'] == 1
    assert s['progress']['tasks']['denominator'] == 3
    assert s['progress']['duration']['numerator'] == 3600
    assert s['progress']['duration']['denominator'] == 10800
    assert s['progress']['duration']['missing_count'] == 1
    assert s['period']['percent'] is None
    assert s['plan']['status'] == 'no_deadline'
    assert s['tracks'][0]['id'] is None
    assert client.get('/api/v1/projects/1/analytics').json()['kpi']['actual_seconds'] == 9000


def test_plan_and_ai_share_summary_and_boundaries(client):
    login(client)
    t, l = task(client), lane(client)
    place(client, t, l, start='2030-01-01T08:00:00')
    client.put(f"/api/v1/tasks/{t['id']}/assignees", json={'assignees':[{'user_id':1,'is_primary':True}]})
    client.patch('/api/v1/projects/1', json={'start_msk': '2030-01-01T09:00:00Z', 'deadline_msk': '2030-01-01T12:00:00Z'})
    s = summary(client)
    assert s['plan']['finish'] == state(client)['forecast']['finish']
    assert s['plan']['status'] == 'on_track'
    assert any(p['code'] == 'before_start' for p in s['attention'])
    from tests.conftest import TestingSessionLocal
    from app.services.ai import build_snapshot
    with TestingSessionLocal() as db:
        ai = build_snapshot(db, 1)['analytics_summary']
    assert ai['plan'] == s['plan']
    assert ai['progress'] == s['progress']
    task(client, 'Unplaced')
    assert summary(client)['plan']['status'] == 'incomplete'


def test_period_rights_and_project_isolation(client):
    login(client)
    uid = client.post('/api/v1/admin/users', json={'login': 'reader', 'password': 'test', 'display_name': 'Reader'}).json()['id']
    client.post('/api/v1/admin/roles', json={'user_id': uid, 'role': 'participant', 'project_id': 1})
    other = client.post('/api/v1/projects', json={'name': 'Secret'}).json()['id']
    login(client, 'reader', 'test')
    assert client.patch('/api/v1/projects/1', json={'start_msk': '2030-01-01T00:00:00Z'}).status_code == 403
    assert client.get(f'/api/v1/projects/{other}/analytics').status_code == 403
    assert summary(client)['project_id'] == 1


def test_dependencies_incidents_shared_work_and_unique_impact(client):
    login(client)
    from tests.conftest import TestingSessionLocal
    from app.db.models import TaskDependency, TaskAssignee, IncidentEvent
    a, b, c, d = [task(client, name) for name in ('Root', 'Hard', 'Soft', 'Diamond')]
    uid = client.post('/api/v1/admin/users', json={'login':'helper', 'password':'test', 'display_name':'Helper'}).json()['id']
    client.post('/api/v1/admin/roles', json={'user_id':uid, 'role':'participant', 'project_id':1})
    with TestingSessionLocal() as db:
        db.add_all([TaskDependency(task_id=b['id'],predecessor_id=a['id'],link_type='blocked_by'),
                    TaskDependency(task_id=c['id'],predecessor_id=a['id'],link_type='after'),
                    TaskDependency(task_id=d['id'],predecessor_id=b['id'],link_type='blocked_by'),
                    TaskDependency(task_id=d['id'],predecessor_id=c['id'],link_type='after')])
        db.add_all([TaskAssignee(task_id=a['id'],user_id=1,is_primary=True),TaskAssignee(task_id=a['id'],user_id=uid,is_primary=False)])
        db.commit()
    first = client.post('/api/v1/projects/1/incidents', json={'title':'Root issue','level':'yellow','source_task_id':a['id'],'cascade_depth':4,'targets':[{'target_type':'task','target_id':a['id']}]}).json()
    client.post('/api/v1/projects/1/incidents', json={'title':'Second issue','level':'red','targets':[{'target_type':'task','target_id':a['id']}]})
    s = summary(client)
    states = {t['id']:t for t in s['tasks']}
    assert states[b['id']]['availability'] == 'waiting'
    assert states[c['id']]['availability'] == 'ready'  # Soft edges do not prohibit start.
    assert len(states[a['id']]['blocking_incidents']) == 2
    impact = next(i for i in s['incidents'] if i['id'] == first['id'])
    assert impact['hard_task_ids'] == [b['id'],d['id']]
    assert impact['potential_task_ids'] == [c['id']]
    assert all(a['id'] in p['task_ids'] for p in s['participants'] if p['id'] in (1,uid))
    assert client.post(f"/api/v1/tasks/{b['id']}/timer/start").status_code == 409
    # Older creation metadata must produce an explicit limitation.
    with TestingSessionLocal() as db:
        event = db.query(IncidentEvent).filter_by(incident_id=first['id'],event_type='created').one()
        event.data = {}
        db.commit()
    old = next(i for i in summary(client)['incidents'] if i['id'] == first['id'])
    assert old['source_task_id'] is None and old['limitations']


def test_overdue_and_completed_precedence_and_zero_denominators(client, monkeypatch):
    login(client)
    monkeypatch.setattr('app.services.operational.utcnow', lambda: datetime(2031,1,1))
    client.patch('/api/v1/projects/1', json={'deadline_msk':'2030-01-01T00:00:00Z'})
    s = summary(client)
    assert s['plan']['status'] == 'overdue'
    assert s['progress']['duration']['percent'] is None
    assert s['progress']['tasks']['percent'] is None
    assert s['plan']['incomplete'] is True
    from app.db.models import Project, ProjectState
    from tests.conftest import TestingSessionLocal
    with TestingSessionLocal() as db:
        db.get(Project,1).state = ProjectState.completed
        db.commit()
    assert summary(client)['plan']['status'] == 'completed'
