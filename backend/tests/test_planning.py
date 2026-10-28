"""Planning uses shared tasks, atomic previews and project scoped revisions."""
from datetime import datetime, timedelta

from tests.helpers import login

BASE = '/api/v1/projects/1/planning'


def state(client, project=1):
    response = client.get(f'/api/v1/projects/{project}/planning')
    assert response.status_code == 200, response.text
    return response.json()


def command(client, op, **values):
    revision = values.pop('revision', state(client)['revision'])
    return client.post(BASE, json={'revision': revision, 'op': op, **values})


def task(client, title='Task', estimate=3600, **values):
    return client.post('/api/v1/projects/1/tasks', json={'title': title, 'estimate_seconds': estimate, **values}).json()


def lane(client, name='Поток'):
    response = command(client, 'lane_create', name=name)
    assert response.status_code == 200, response.text
    return response.json()['lanes'][-1]['id']


def place(client, t, l, start='2026-10-28T08:00:00', **values):
    response = command(client, 'place', task_id=t['id'], lane_id=l, start=start, **values)
    assert response.status_code == 200, response.text
    return response.json()


def row(client, t):
    return next(x for x in state(client)['placements'] if x['task_id'] == t['id'])


def test_lanes_shared_tasks_and_revision(client):
    login(client)
    a = task(client, description='Сохранить', tags=['api'])
    l1, l2 = lane(client), lane(client, 'UI')
    old = state(client)['revision']
    place(client, a, l1)
    assert command(client, 'lane_rename', lane_id=l1, name='Stale', revision=old).status_code == 409
    assert command(client, 'lane_rename', lane_id=l1, name='Backend').status_code == 200
    assert command(client, 'lane_reorder', lane_ids=[l2, l1]).json()['lanes'][0]['id'] == l2
    assert command(client, 'lane_reorder', lane_ids=[l1]).status_code == 422
    assert command(client, 'lane_delete', lane_id=l1, target_lane_id=l2).status_code == 200
    assert row(client, a)['lane_id'] == l2
    assert command(client, 'lane_delete', lane_id=l2).status_code == 200
    assert not state(client)['placements']
    shared = client.get(f"/api/v1/tasks/{a['id']}").json()
    assert shared['description'] == 'Сохранить' and shared['tags'] == ['api']
    assert shared['column_title'] == 'Backlog'


def test_permissions_and_project_isolation(client):
    login(client)
    a, l = task(client), lane(client)
    other = client.post('/api/v1/projects', json={'name': 'Other'}).json()['id']
    foreign = client.post(f'/api/v1/projects/{other}/tasks', json={'title': 'Other'}).json()
    assert command(client, 'place', task_id=foreign['id'], lane_id=l, start='2026-10-28T08:00:00').status_code == 422
    assert command(client, 'link', source_id=a['id'], target_id=foreign['id']).status_code == 422
    assert state(client, other)['lanes'] == []
    user = client.post('/api/v1/admin/users', json={'login': 'reader', 'password': 'pass', 'display_name': 'Reader'}).json()
    client.post('/api/v1/admin/roles', json={'user_id': user['id'], 'role': 'participant', 'project_id': 1})
    login(client, 'reader', 'pass')
    assert state(client)['lanes']
    assert command(client, 'lane_create', name='Forbidden').status_code == 403
    assert client.get(f'/api/v1/projects/{other}/planning').status_code == 403


def test_estimate_resize_missing_and_trash_restore(client):
    login(client)
    a, missing, l = task(client), task(client, estimate=None), lane(client)
    assert command(client, 'place', task_id=missing['id'], lane_id=l, start='2026-10-28T08:00:00').status_code == 200
    place(client, a, l, estimate_seconds=7200)
    current = client.get(f"/api/v1/tasks/{a['id']}").json()
    assert current['estimate_seconds'] == 7200
    response = client.patch(f"/api/v1/tasks/{a['id']}", json={'version': current['version'], 'estimate_seconds': 1800})
    assert response.status_code == 200
    assert row(client, a)['end'] == '2026-10-28T08:30:00'
    current = response.json()
    trashed = client.post(f"/api/v1/tasks/{a['id']}/move", json={'version': current['version'], 'column_key': 'trashed'}).json()
    assert a['id'] not in [p['task_id'] for p in state(client)['placements']]
    assert a['id'] not in [t['id'] for t in state(client)['tasks']]
    client.post(f"/api/v1/tasks/{a['id']}/move", json={'version': trashed['version'], 'column_key': 'backlog'})
    assert row(client, a)['lane_id'] == l


def test_dag_fork_join_cycles_and_bidirectional_labels(client):
    login(client)
    a, b, c, d, l = task(client, 'A'), task(client, 'B'), task(client, 'C', 7200), task(client, 'D'), lane(client)
    for t in (a, b, c, d):
        place(client, t, l)
    for source, target in ((a,b),(a,c),(b,d),(c,d)):
        response = command(client, 'link', source_id=source['id'], target_id=target['id'])
        assert response.status_code == 200, response.text
    assert row(client, d)['start'] == '2026-10-28T11:00:00'
    assert command(client, 'link', source_id=d['id'], target_id=a['id']).status_code == 422
    assert command(client, 'link', source_id=a['id'], target_id=a['id']).status_code == 422
    assert command(client, 'link', source_id=a['id'], target_id=b['id']).status_code == 422
    btask = client.get(f"/api/v1/tasks/{b['id']}").json()
    assert {'task_id': a['id'], 'link_type': 'after'} in btask['predecessors']
    # The inverse is derived in the shared card, never a second independent edge.
    assert len(state(client)['edges']) == 4
    place(client, a, l, estimate_seconds=10800)
    # Soft recommendations no longer force the downstream plan to move.
    assert row(client, d)['start'] == '2026-10-28T11:00:00'
    assert command(client, 'unlink', source_id=a['id'], target_id=b['id']).status_code == 200
    assert len(state(client)['edges']) == 3
    # Same protection applies to links entered through Kanban.
    assert client.post(f"/api/v1/tasks/{a['id']}/dependencies", json={'predecessor_id': d['id'], 'link_type': 'after'}).status_code == 422


def test_autosave_recalculates_pinned_successors_and_rejects_stale_writer(client):
    login(client)
    a, b, l = task(client, 'A'), task(client, 'B'), lane(client)
    place(client, a, l)
    place(client, b, l, start='2026-10-28T09:00:00', pinned=True)
    command(client, 'link', source_id=a['id'], target_id=b['id'])
    command(client, 'set_blocker', source_id=a['id'], target_id=b['id'], blocking=True)
    revision = state(client)['revision']
    payload = {'revision': revision, 'op': 'place', 'task_id': a['id'], 'lane_id': l,
               'start': '2026-10-28T08:00:00', 'estimate_seconds': 7200}
    accepted = client.post(BASE, json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['warnings']
    assert row(client, b)['start'] == '2026-10-28T10:00:00'
    assert client.post(BASE, json=payload).status_code == 409
    assert client.get(f"/api/v1/tasks/{a['id']}").json()['estimate_seconds'] == 7200


def test_baseline_history_forecast_and_limits(client):
    login(client)
    a, l = task(client), lane(client)
    assert state(client)['forecast']['finish'] is None
    place(client, a, l)
    assert row(client, a)['deviation_seconds'] is None
    first = command(client, 'baseline').json()
    assert first['baseline']['created_at']
    place(client, a, l, estimate_seconds=7200)
    assert row(client, a)['deviation_seconds'] == 3600
    response = command(client, 'baseline')
    assert response.status_code == 409
    token = response.json()['error']['details']['token']
    response = client.post(BASE, json={'revision': state(client)['revision'], 'op': 'baseline'}, headers={'X-Planning-Confirm': token})
    assert response.status_code == 200
    assert response.json()['baseline_count'] == 2
    assert row(client, a)['deviation_seconds'] == 0
    task(client, 'Unknown', None)
    assert state(client)['forecast']['limitations']


def test_early_late_completion_preserves_timers(client, monkeypatch):
    from app.services import planning
    login(client)
    a, b, l = task(client, 'A'), task(client, 'B'), lane(client)
    place(client, a, l)
    place(client, b, l, start='2026-10-28T09:00:00')
    command(client, 'link', source_id=a['id'], target_id=b['id'])
    command(client, 'set_blocker', source_id=a['id'], target_id=b['id'], blocking=True)
    for hour, expected in ((8, '2026-10-28T08:30:00'), (10, '2026-10-28T10:30:00')):
        monkeypatch.setattr(planning, 'now', lambda: datetime(2026,10,28,hour,30))
        t = client.get(f"/api/v1/tasks/{a['id']}").json()
        response = client.post(f"/api/v1/tasks/{a['id']}/move", json={'version':t['version'], 'column_key':'done'})
        assert response.status_code == 200, response.text
        assert row(client, b)['start'] == expected
        t = response.json()
        if hour == 8:
            client.post(f"/api/v1/tasks/{a['id']}/move", json={'version':t['version'], 'column_key':'backlog'})
    assert client.get(f"/api/v1/tasks/{a['id']}").json()['timer'] is None


def test_started_successor_autosave_does_not_rewrite_history(client):
    login(client)
    a, b, l = task(client), task(client), lane(client)
    place(client, a, l)
    place(client, b, l, start='2026-10-28T09:00:00')
    command(client, 'link', source_id=a['id'], target_id=b['id'])
    client.post(f"/api/v1/tasks/{b['id']}/timer/start")
    command(client, 'set_blocker', source_id=a['id'], target_id=b['id'], blocking=True)
    response = command(client, 'place', task_id=a['id'], lane_id=l, start='2026-10-28T08:00:00', estimate_seconds=7200)
    assert response.status_code == 200
    assert 'начат' in str(response.json()['warnings']).lower()
    assert row(client, b)['start'] == '2026-10-28T09:00:00'
    assert client.get(f"/api/v1/tasks/{b['id']}").json()['timer']['state'] == 'running'


def test_active_column_is_started_even_without_timer_history(client):
    login(client)
    a, b, l = task(client), task(client, column_key='in_progress'), lane(client)
    place(client,a,l)
    # Existing active tasks may have no retained timer evidence.
    response = command(client,'place',task_id=b['id'],lane_id=l,start='2026-10-28T09:00:00')
    if response.status_code == 409:
        token=response.json()['error']['details']['token']
        client.post(BASE,json={'revision':state(client)['revision'],'op':'place','task_id':b['id'],'lane_id':l,'start':'2026-10-28T09:00:00'},headers={'X-Planning-Confirm':token})
    command(client,'link',source_id=a['id'],target_id=b['id'])
    response=command(client,'place',task_id=a['id'],lane_id=l,start='2026-10-28T08:00:00',estimate_seconds=7200)
    assert response.status_code==200
    assert row(client,b)['start']=='2026-10-28T09:00:00'


def test_real_concurrent_editors_and_overlap_signal(client):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from app.main import app
    login(client)
    l = lane(client)
    a, b = task(client), task(client)
    for t in (a,b):
        client.put(f"/api/v1/tasks/{t['id']}/assignees", json={'assignees':[{'user_id':1,'is_primary':True}]})
        place(client,t,l)
    assert state(client)['overlaps'][0]['task_ids'] == [a['id'],b['id']]
    revision = state(client)['revision']
    def edit(name):
        second = TestClient(app)
        second.cookies.update(client.cookies)
        return second.post(BASE, json={'revision':revision,'op':'lane_rename','lane_id':l,'name':name}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit,['One','Two'])) == [200,409]


def test_kanban_autosave_is_atomic_including_auto_timer(client, monkeypatch):
    from app.services import planning
    login(client)
    a, b, l = task(client), task(client), lane(client)
    place(client,a,l)
    place(client,b,l,start='2026-10-28T09:00:00',pinned=True)
    command(client,'link',source_id=a['id'],target_id=b['id'])
    column=next(c for c in client.get('/api/v1/projects/1/columns').json() if c['key']=='done')
    client.patch(f"/api/v1/columns/{column['id']}",json={'auto_stop_timer':True})
    client.post(f"/api/v1/tasks/{a['id']}/timer/start")
    before=client.get(f"/api/v1/tasks/{a['id']}").json()
    monkeypatch.setattr(planning,'now',lambda:datetime(2026,10,28,10))
    path=f"/api/v1/tasks/{a['id']}/move"
    payload={'version':before['version'],'column_key':'done'}
    accepted=client.post(path,json=payload)
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['timer']['state']=='stopped'
    assert row(client,a)['actual_completed_at']=='2026-10-28T10:00:00'


def test_sandbox_cleanup_accepts_planned_tasks(client):
    login(client)
    client.post('/api/v1/admin/sandbox/run',json={'scenario':'create_team'})
    pid=client.get('/api/v1/admin/sandbox/workspace').json()['project_id']
    endpoint=f'/api/v1/projects/{pid}/planning'
    t=client.post(f'/api/v1/projects/{pid}/tasks',json={'title':'Planned sandbox task','estimate_seconds':3600}).json()
    def edit(op,**values):
        revision=client.get(endpoint).json()['revision']
        result=client.post(endpoint,json={'revision':revision,'op':op,**values})
        assert result.status_code==200,result.text
        return result.json()
    l=edit('lane_create',name='Demo')['lanes'][0]['id']
    edit('place',task_id=t['id'],lane_id=l,start='2026-10-28T08:00:00')
    edit('baseline')
    response=client.post('/api/v1/admin/sandbox/reset',json={'project_id':pid,'confirm':True})
    assert response.status_code==200,response.text
    result=client.get(endpoint).json()
    assert result['lanes']==[] and result['placements']==[] and result['baseline_count']==0


def test_hundred_tasks_overlap_and_critical_chain(client, monkeypatch):
    from app.services import planning
    monkeypatch.setattr(planning, 'now', lambda: datetime(2026,10,28,7))
    login(client)
    lanes = [lane(client, f'Lane {i}') for i in range(5)]
    tasks = [task(client, f'Task {i}') for i in range(100)]
    for i, t in enumerate(tasks):
        place(client, t, lanes[i % 5], start=(datetime(2026,10,28,8)+timedelta(hours=i//5)).isoformat())
    for i in range(1, 12):
        assert command(client, 'link', source_id=tasks[(i-1)//2]['id'], target_id=tasks[i]['id']).status_code == 200
    result = state(client)
    assert len(result['placements']) == 100
    assert result['forecast']['critical_chain']


def test_placement_invalidates_board_version_and_board_write_invalidates_plan(client):
    login(client)
    a, l = task(client), lane(client)
    place(client, a, l)
    board = client.get(f"/api/v1/tasks/{a['id']}").json()
    place(client, a, l, start='2026-10-28T10:00:00')
    assert client.post(f"/api/v1/tasks/{a['id']}/move", json={'version':board['version'], 'column_key':'done'}).status_code == 409
    revision = state(client)['revision']
    task(client, 'Created on board')
    assert command(client, 'lane_rename', lane_id=l, name='Stale', revision=revision).status_code == 409
