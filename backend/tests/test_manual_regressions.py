"""Правила сценариев ручной проверки; только изолированная тестовая база."""
from tests.helpers import login


def task(client, title='A', project=1, **kwargs):
    response = client.post(f'/api/v1/projects/{project}/tasks', json={'title': title, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def test_columns_isolated_transfer_and_last_column(client):
    login(client)
    pid = client.post('/api/v1/projects', json={'name': 'Second'}).json()['id']
    cols = client.get('/api/v1/projects/1/columns').json()
    other = client.get(f'/api/v1/projects/{pid}/columns').json()
    t = task(client)
    assert client.delete(f"/api/v1/columns/{cols[0]['id']}?target_column_id={other[0]['id']}").status_code == 422
    assert client.patch(f"/api/v1/columns/{cols[0]['id']}", json={'title': 'Очередь', 'position': 5}).status_code == 200
    assert client.get(f'/api/v1/projects/{pid}/columns').json() == other
    assert client.delete(f"/api/v1/columns/{cols[0]['id']}?target_column_id={cols[1]['id']}").status_code == 200
    moved = client.get(f"/api/v1/tasks/{t['id']}").json()
    assert moved['column_id'] == cols[1]['id'] and moved['version'] == 2
    # Default creation still works after deleting backlog.
    task(client, 'Without backlog')
    for col in cols[2:]:
        assert client.delete(f"/api/v1/columns/{col['id']}").status_code == 200
    assert client.delete(f"/api/v1/columns/{cols[1]['id']}").status_code == 409


def test_estimate_history_and_trash_links(client):
    login(client)
    t = task(client, estimate_seconds=600)
    client.post(f"/api/v1/tasks/{t['id']}/time-adjustment", json={'accumulated_seconds': 123})
    updated = client.patch(f"/api/v1/tasks/{t['id']}", json={'version': 1, 'estimate_seconds': 900}).json()
    assert updated['estimate_seconds'] == 900 and updated['timer']['total_seconds'] == 123
    history = client.get(f"/api/v1/tasks/{t['id']}/history").json()
    change = next(h for h in history if h['action'] == 'task.updated')
    assert change['data']['changes']['estimate_seconds'] == {'old': 600, 'new': 900}
    assert 'оценк' in change['text'].lower()
    deleted = task(client, 'Trash', column_key='trashed')
    assert client.post(f"/api/v1/tasks/{t['id']}/dependencies", json={'predecessor_id': deleted['id']}).status_code == 422
    assert client.patch(f"/api/v1/tasks/{t['id']}", json={'version': 2, 'title': ''}).status_code == 422


def test_directed_propagation_saved_selection_and_multiple_blockers(client):
    login(client)
    a, b, c, d = [task(client, name) for name in 'ABCD']
    for child, parent, link in [(b,a,'after'),(c,b,'blocked_by'),(d,a,'before')]:
        client.post(f"/api/v1/tasks/{child['id']}/dependencies", json={'predecessor_id': parent['id'], 'link_type': link})
    # before means D -> A, so D must never appear downstream of A.
    preview = client.get(f"/api/v1/tasks/{a['id']}/incident-impact?depth=1").json()
    assert preview['task_ids'] == [a['id'], b['id']]
    assert client.get(f"/api/v1/tasks/{a['id']}/incident-impact?depth=2").json()['task_ids'] == [a['id'], b['id'], c['id']]
    client.post(f"/api/v1/tasks/{b['id']}/timer/start")
    def incident():
        return client.post('/api/v1/projects/1/incidents', json={'level':'red','title':'Block', 'targets':[{'target_type':'task','target_id':b['id']}]}).json()
    first, second = incident(), incident()
    assert first['owner_id'] == first['author_id']
    assert first['number'] == 1 and second['number'] == 2
    saved = client.get(f"/api/v1/tasks/{b['id']}").json()
    assert len(saved['blocking_incidents']) == 2 and saved['timer']['state'] == 'running'
    assert client.get(f"/api/v1/tasks/{c['id']}").json()['blocking_incidents'] == []
    client.post(f"/api/v1/incidents/{first['id']}/resolve", json={'resolution':'OK'})
    assert len(client.get(f"/api/v1/tasks/{b['id']}").json()['blocking_incidents']) == 1
    pid = client.post('/api/v1/projects', json={'name':'Other'}).json()['id']
    assert client.post(f'/api/v1/projects/{pid}/incidents', json={'level':'yellow','title':'New'}).json()['number'] == 1


def test_analytics_remaining_deviations_and_short_burndown(client):
    login(client)
    t = task(client, estimate_seconds=600)
    client.post(f"/api/v1/tasks/{t['id']}/time-adjustment", json={'accumulated_seconds':900})
    task(client, 'Trash', column_key='trashed', estimate_seconds=99999)
    data = client.get('/api/v1/projects/1/analytics').json()
    assert data['kpi']['estimate_seconds'] == 600
    assert data['forecast']['remaining_seconds'] == 600
    assert data['forecast']['status'] == 'no_deadline'
    assert data['deviations'][0]['overrun_seconds'] == 300
    assert len(data['burn_down']) >= 2
    assert 'T' in data['burn_down'][0]['date']


def test_notification_navigation_checks_object_and_project(client):
    from tests.conftest import TestingSessionLocal
    from app.db.models import Notification
    login(client)
    t = task(client)
    with TestingSessionLocal() as db:
        rows = [Notification(user_id=1,project_id=1,type=kind,payload=payload) for kind,payload in [
            ('task_assigned',{'task_id':t['id']}), ('task_assigned',{'task_id':99999}), ('unknown',{'task_id':t['id']})]]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
    good = client.post(f'/api/v1/notifications/{ids[0]}/open').json()
    assert good['target'] == {'type':'task','id':t['id'],'project_id':1}
    for nid in ids[1:]:
        result = client.post(f'/api/v1/notifications/{nid}/open').json()
        assert result['target'] is None and result['message']
    assert all(n['read_at'] for n in client.get('/api/v1/notifications').json())


def test_concurrent_incident_numbers_are_unique_and_not_reused(client):
    from concurrent.futures import ThreadPoolExecutor
    from tests.conftest import TestingSessionLocal
    from app.services.incidents import create_incident
    from app.db.models import Incident, IncidentEvent
    login(client)
    def create(_: int) -> int:
        with TestingSessionLocal() as db:
            row = create_incident(db,project_id=1,author_id=1,level='yellow',title='Concurrent',description=None,impact=None,urgency=None,owner_id=None,targets=[])
            db.commit()
            return row.number
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(create, range(4))) == [1,2,3,4]
    with TestingSessionLocal() as db:
        latest = db.query(Incident).filter_by(number=4).one()
        db.query(IncidentEvent).filter_by(incident_id=latest.id).delete()
        db.delete(latest)
        db.commit()
    assert create(0) == 5


def test_branching_cycles_trash_and_project_boundaries(client):
    login(client)
    a,b,c,d,trash = [task(client,name) for name in ['a','b','c','d','trash']]
    for child,parent in [(b,a),(c,a),(d,b),(d,c),(trash,a)]:
        assert client.post(f"/api/v1/tasks/{child['id']}/dependencies", json={'predecessor_id':parent['id']}).status_code == 200
    assert client.post(f"/api/v1/tasks/{a['id']}/dependencies", json={'predecessor_id':d['id']}).status_code == 422
    current = client.get(f"/api/v1/tasks/{trash['id']}").json()
    client.post(f"/api/v1/tasks/{trash['id']}/move", json={'version':current['version'],'column_key':'trashed'})
    impact = client.get(f"/api/v1/tasks/{a['id']}/incident-impact?depth=100").json()
    assert impact['task_ids'] == [a['id'],b['id'],c['id'],d['id']]
    pid = client.post('/api/v1/projects',json={'name':'Foreign'}).json()['id']
    foreign = task(client,project=pid)
    assert client.post(f"/api/v1/tasks/{a['id']}/dependencies",json={'predecessor_id':foreign['id']}).status_code == 422
    assert client.post('/api/v1/projects/1/incidents',json={'level':'yellow','title':'Invalid','targets':[{'target_type':'task','target_id':trash['id']}]}).status_code == 422


def test_custom_column_semantics_and_parent_cycle(client):
    login(client)
    col = client.post('/api/v1/projects/1/columns', json={'title':'Результат'}).json()
    client.patch(f"/api/v1/columns/{col['id']}",json={'semantic':'done'})
    a = task(client,column_key=col['key'],estimate_seconds=600)
    b = task(client,'Child',parent_id=a['id'])
    assert client.get('/api/v1/projects/1/analytics').json()['kpi']['completed_tasks'] == 1
    assert client.get('/api/v1/projects/1/dashboard').json()['completed_tasks'] == 1
    assert client.get('/api/v1/projects/1/analytics').json()['deviations'] == []  # No timer is not proof of zero work.
    assert client.patch(f"/api/v1/tasks/{a['id']}",json={'version':1,'parent_id':b['id']}).status_code == 422
    assert client.patch(f"/api/v1/tasks/{a['id']}",json={'version':1,'title':None}).status_code == 422


def test_calendar_counts_intervals_not_assignees_and_ignores_adjustments(client, monkeypatch):
    from datetime import datetime, timedelta
    from app.services import timers
    login(client)
    a,b = task(client),task(client,'B')
    for t in (a,b):
        client.put(f"/api/v1/tasks/{t['id']}/assignees",json={'assignees':[{'user_id':1,'is_primary':True}]})
    clock=datetime(2026,10,28)
    monkeypatch.setattr(timers,'_now',lambda:clock)
    client.post(f"/api/v1/tasks/{a['id']}/timer/start")
    clock += timedelta(seconds=10)
    client.post(f"/api/v1/tasks/{b['id']}/timer/start")
    clock += timedelta(seconds=10)
    client.post(f"/api/v1/tasks/{a['id']}/timer/pause")
    clock += timedelta(seconds=10)
    client.post(f"/api/v1/tasks/{b['id']}/timer/stop")
    k = client.get('/api/v1/projects/1/analytics').json()['kpi']
    assert k['actual_seconds'] == 40 and k['calendar_seconds'] == 30
    client.post(f"/api/v1/tasks/{a['id']}/time-adjustment",json={'accumulated_seconds':100})
    k = client.get('/api/v1/projects/1/analytics').json()['kpi']
    assert k['actual_seconds'] == 120 and k['calendar_seconds'] == 30


def test_legacy_missing_initial_status_does_not_invent_burndown(client):
    from tests.conftest import TestingSessionLocal
    from app.db.models import AuditEntry
    login(client)
    task(client, column_key='done')
    with TestingSessionLocal() as db:
        event=db.query(AuditEntry).filter_by(action='task.created').one()
        event.data={'title':'Legacy'}  # Old records did not record the initial column.
        db.commit()
    points=client.get('/api/v1/projects/1/analytics').json()['burn_down']
    assert len(points) == 1 and points[0]['remaining'] == 0
    assert points[0]['observation_only'] is True
