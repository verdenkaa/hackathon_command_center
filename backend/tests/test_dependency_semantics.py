from tests.helpers import login
from tests.test_planning import task, lane, place, command, row


def test_soft_link_can_overlap_but_blocker_cannot_start(client):
    login(client)
    a, b = task(client, 'A'), task(client, 'B')
    track = lane(client)
    place(client, a, track)
    place(client, b, track)
    assert command(client, 'link', source_id=a['id'], target_id=b['id']).status_code == 200
    assert row(client, b)['start'] >= row(client, a)['planned_end']
    place(client, b, track, '2026-10-28T08:15:00')
    assert row(client, b)['start'] == '2026-10-28T08:15:00'
    assert command(client, 'set_blocker', source_id=a['id'], target_id=b['id'], blocking=True).status_code == 200
    assert row(client, b)['start'] >= row(client, a)['planned_end']
    assert client.post(f"/api/v1/tasks/{b['id']}/timer/start").status_code == 409
    fresh = client.get(f"/api/v1/tasks/{b['id']}").json()
    columns = client.get('/api/v1/projects/1/columns').json()
    active = next(c for c in columns if c['semantic'] == 'active')
    assert client.post(f"/api/v1/tasks/{b['id']}/move", json={'version':fresh['version'], 'column_key':active['key']}).status_code == 409
    assert command(client, 'set_blocker', source_id=a['id'], target_id=b['id'], blocking=False).status_code == 200
    assert client.post(f"/api/v1/tasks/{b['id']}/timer/start").status_code == 200
    assert client.get(f"/api/v1/tasks/{b['id']}").json()['actual_started_at'] is not None


def test_completed_blocker_allows_start_and_both_ends_can_disconnect(client):
    login(client)
    a, b = task(client, 'Blocker'), task(client, 'Dependent')
    client.post(f"/api/v1/tasks/{b['id']}/dependencies", json={'predecessor_id':a['id'], 'link_type':'blocked_by'})
    columns = client.get('/api/v1/projects/1/columns').json()
    done = next(c for c in columns if c['semantic'] == 'done')
    client.post(f"/api/v1/tasks/{a['id']}/move", json={'version':client.get(f"/api/v1/tasks/{a['id']}").json()['version'], 'column_key':done['key']})
    assert client.post(f"/api/v1/tasks/{b['id']}/timer/start").status_code == 200
    assert client.delete(f"/api/v1/tasks/{b['id']}/dependencies/{a['id']}").status_code == 200
    assert not client.get(f"/api/v1/tasks/{b['id']}").json()['predecessors']


def test_incident_cascade_counts_unique_hard_and_potential_paths(client):
    login(client)
    a, b, c, d = [task(client, name) for name in ['A','B','C','D']]
    track = lane(client)
    for t, start in [(a,'08'),(b,'09'),(c,'09'),(d,'10')]:
        place(client,t,track,f'2026-10-28T{start}:00:00')
    for source,target,kind in [(a,b,'blocked_by'),(a,c,'after'),(b,d,'blocked_by'),(c,d,'after')]:
        assert client.post(f"/api/v1/tasks/{target['id']}/dependencies",json={'predecessor_id':source['id'],'link_type':kind}).status_code==200
    result=client.get(f"/api/v1/tasks/{a['id']}/incident-cascade").json()
    assert result['levels'][0]['hard_task_ids']==[b['id']]
    assert result['levels'][0]['potential_task_ids']==[c['id']]
    assert result['levels'][1]['hard_task_ids']==[b['id'],d['id']]
    assert result['levels'][1]['new_hard_count']==1
    assert len(result['scenarios'])==3
    assert result['scenarios'][1]['delay_seconds']==3600
    assert result['scenarios'][1]['task_ids']==[b['id'],d['id']]
    before=row(client,a)
    created=client.post('/api/v1/projects/1/incidents',json={'level':'yellow','title':'Cascade','source_task_id':a['id'],'cascade_depth':2,'targets':[{'target_type':'task','target_id':a['id']}]}).json()
    assert created['source_task_id']==a['id'] and created['cascade_depth']==2
    assert created['cascade']['levels'][1]['hard_task_ids']==[b['id'],d['id']]
    assert row(client,a)==before


def test_cascade_handles_slack_done_tasks_and_foreign_source(client):
    login(client)
    a,b=task(client,'A'),task(client,'B')
    track=lane(client)
    place(client,a,track,'2026-10-28T08:00:00')
    place(client,b,track,'2026-10-28T12:00:00')
    client.post(f"/api/v1/tasks/{b['id']}/dependencies",json={'predecessor_id':a['id'],'link_type':'blocked_by'})
    place(client,b,track,'2026-10-28T12:00:00')
    result=client.get(f"/api/v1/tasks/{a['id']}/incident-cascade").json()
    assert result['scenarios'][1]['task_ids']==[]
    assert result['scenarios'][1]['finish_shift_seconds']==0
    assert result['scenarios'][2]['task_ids']==[b['id']]
    other=client.post('/api/v1/projects',json={'name':'Other'}).json()['id']
    foreign=client.post(f'/api/v1/projects/{other}/tasks',json={'title':'Foreign'}).json()
    response=client.post('/api/v1/projects/1/incidents',json={'level':'yellow','title':'Invalid','source_task_id':foreign['id']})
    assert response.status_code==422
    for t in (a,b):
        fresh=client.get(f"/api/v1/tasks/{t['id']}").json()
        assert client.post(f"/api/v1/tasks/{t['id']}/move",json={'version':fresh['version'],'column_key':'done'}).status_code==200
    result=client.get(f"/api/v1/tasks/{a['id']}/incident-cascade").json()
    assert result['source_ids']==[] and result['levels']==[]
