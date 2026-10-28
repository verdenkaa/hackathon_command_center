from tests.helpers import login


def test_demo_is_separate_idempotent_and_shows_progress_and_burndown(client):
    from tests.conftest import TestingSessionLocal
    from app.services.analytics_demo import prepare_analytics_demo
    login(client)
    before=client.get('/api/v1/projects/1/tasks').json()
    with TestingSessionLocal() as db:
        project=prepare_analytics_demo(db,1)
        pid=project.id
        assert prepare_analytics_demo(db,1).id==pid
    assert client.get('/api/v1/projects/1/tasks').json()==before
    data=client.get(f'/api/v1/projects/{pid}/analytics').json()
    assert data['kpi']['total_tasks']==12
    assert data['kpi']['completed_tasks']==7
    assert data['kpi']['active_timers']==3
    assert data['kpi']['estimate_seconds']==86400
    assert data['kpi']['actual_seconds']>=30600
    assert data['burn_down'][0]['remaining']==12
    assert data['burn_down'][0]['ideal']==12
    assert data['burn_down'][-1]['remaining']==5
    assert len({p['date'] for p in data['burn_down']})>=8
