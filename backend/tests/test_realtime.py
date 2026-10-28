"""Committed changes wake every viewer; rejected and rolled back edits do not."""
import asyncio

from tests.helpers import login


def test_revision_tracks_board_timer_and_checklist_commits(client):
    login(client)
    from tests.test_planning import state, task
    revision = state(client)['revision']
    t = task(client)
    assert state(client)['revision'] > revision
    for path, body in [(f"/api/v1/tasks/{t['id']}/timer/start", None),
                       (f"/api/v1/tasks/{t['id']}/checklist", {'text':'Shared item'})]:
        revision = state(client)['revision']
        assert client.post(path, json=body).status_code == 200
        assert state(client)['revision'] > revision
    revision = state(client)['revision']
    assert client.post(f"/api/v1/tasks/{t['id']}/move", json={'version':0,'column_key':'done'}).status_code == 409
    assert state(client)['revision'] == revision


def test_event_feed_authentication_and_isolation(client):
    assert client.get('/api/v1/projects/1/events').status_code == 401
    login(client)
    other = client.post('/api/v1/projects', json={'name':'Private'}).json()['id']
    u = client.post('/api/v1/admin/users', json={'login':'reader','password':'pass','display_name':'Reader'}).json()
    client.post('/api/v1/admin/roles', json={'user_id':u['id'],'role':'participant','project_id':1})
    login(client,'reader','pass')
    assert client.get(f'/api/v1/projects/{other}/events').status_code == 403


def test_two_event_streams_receive_same_committed_revision_and_reconnect(client):
    from starlette.requests import Request
    from tests.conftest import engine
    from tests.test_planning import task
    from app.api.realtime import project_events
    login(client)
    cookie = '; '.join(f'{k}={v}' for k,v in client.cookies.items())
    def request():
        return Request({'type':'http','method':'GET','path':'/api/v1/projects/1/events',
                        'headers':[(b'cookie',cookie.encode())],'path_params':{'project_id':1}}, receive)
    async def receive():
        return {'type':'http.request'}
    async def scenario():
        one, two = project_events(request(),engine,1), project_events(request(),engine,1)
        try:
            initial = await anext(one)
            assert initial == await anext(two)
            await asyncio.to_thread(task,client,'Live change')
            updated = await asyncio.wait_for(anext(one),2)
            assert updated != initial and 'event: change' in updated
            assert updated == await asyncio.wait_for(anext(two),2)
            reconnect = project_events(request(),engine,1)
            try:
                assert await anext(reconnect) == updated
            finally:
                await reconnect.aclose()
            client.post('/api/v1/auth/logout')
            assert 'event: access-lost' in await asyncio.wait_for(anext(one),2)
        finally:
            await one.aclose()
            await two.aclose()
    asyncio.run(scenario())
