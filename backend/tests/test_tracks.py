from tests.helpers import login
from tests.test_planning import state, command


def test_track_task_is_scheduled_with_default_hour_and_shared_deadline(client):
    login(client)
    track = client.post('/api/v1/projects/1/modules', json={'name':'Backend'}).json()
    t = client.post('/api/v1/projects/1/tasks', json={'title':'API','module_id':track['id']}).json()
    plan = state(client)
    p = next(p for p in plan['placements'] if p['task_id']==t['id'])
    assert p['lane_id']==track['id']
    assert t['estimate_seconds']==3600 and t['deadline']==p['planned_end']
    result = command(client,'place',task_id=t['id'],lane_id=track['id'],start=p['start'],estimate_seconds=900)
    assert result.status_code==200
    saved = client.get(f"/api/v1/tasks/{t['id']}").json()
    p = next(p for p in result.json()['placements'] if p['task_id']==t['id'])
    assert saved['deadline']==p['planned_end'] and saved['estimate_seconds']==900
    assert saved['timer'] is None
    from datetime import datetime, timedelta
    deadline=(datetime.fromisoformat(saved['deadline'])+timedelta(hours=2)).isoformat()
    response=client.patch(f"/api/v1/tasks/{t['id']}",json={'version':saved['version'],'deadline':deadline})
    assert response.status_code==200
    p=next(p for p in state(client)['placements'] if p['task_id']==t['id'])
    assert p['planned_end']==deadline


def test_new_track_task_respects_dependencies_and_resize_keeps_timer(client):
    login(client)
    track=client.post('/api/v1/projects/1/modules',json={'name':'Flow'}).json()['id']
    tasks=[client.post('/api/v1/projects/1/tasks',json={'title':name,'module_id':track}).json() for name in ['A','B']]
    a,b=tasks
    client.post(f"/api/v1/tasks/{b['id']}/dependencies",json={'predecessor_id':a['id'],'link_type':'after'})
    plan=state(client)
    placements={p['task_id']:p for p in plan['placements']}
    assert placements[b['id']]['start']>=placements[a['id']]['planned_end']
    client.post(f"/api/v1/tasks/{a['id']}/timer/start")
    response=command(client,'place',task_id=a['id'],lane_id=track,start=placements[a['id']]['start'],estimate_seconds=4500)
    assert response.status_code==200
    saved=client.get(f"/api/v1/tasks/{a['id']}").json()
    assert saved['timer']['state']=='running' and saved['estimate_seconds']==4500


def test_track_change_and_deletion_are_shared(client):
    login(client)
    a,b = [client.post('/api/v1/projects/1/modules',json={'name':name}).json()['id'] for name in ['A','B']]
    t=client.post('/api/v1/projects/1/tasks',json={'title':'Task','module_id':a}).json()
    response=client.patch(f"/api/v1/tasks/{t['id']}",json={'version':t['version'],'module_id':b})
    assert response.status_code==200
    assert state(client)['placements'][0]['lane_id']==b
    client.delete(f'/api/v1/modules/{b}')
    assert t['id'] in state(client)['unplaced_ids']
