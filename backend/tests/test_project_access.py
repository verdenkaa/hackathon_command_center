"""Общий аккаунт не получает права соседнего проекта."""
from __future__ import annotations

from tests.helpers import login


def setup_projects(client):
    login(client)
    other = client.post('/api/v1/projects', json={'name': 'Private'}).json()['id']
    user = client.post('/api/v1/admin/users', json={'login': 'member', 'password': 'test', 'display_name': 'Member'}).json()['id']
    client.post('/api/v1/admin/roles', json={'user_id': user, 'role': 'participant', 'project_id': 1})
    client.post('/api/v1/admin/roles', json={'user_id': user, 'role': 'captain', 'project_id': other})
    task = client.post(f'/api/v1/projects/{other}/tasks', json={'title': 'Secret'}).json()['id']
    return other, user, task


def test_project_list_and_object_access(client):
    other, user, task = setup_projects(client)
    client.post(f'/api/v1/admin/roles', json={'user_id': user, 'role': 'captain', 'project_id': other})
    roles = client.get('/api/v1/admin/roles').json()
    for role in roles:
        if role['user_id'] == user and role['project_id'] == other:
            client.delete(f"/api/v1/admin/roles/{role['id']}")
    login(client, 'member', 'test')
    assert [p['id'] for p in client.get('/api/v1/projects').json()] == [1]
    for path in [f'/projects/{other}/tasks', f'/projects/{other}/analytics', f'/tasks/{task}', f'/tasks/{task}/history']:
        assert client.get('/api/v1' + path).status_code == 403
    assert client.post(f'/api/v1/tasks/{task}/timer/start').status_code == 403


def test_captain_does_not_gain_rights_in_other_project(client):
    setup_projects(client)
    login(client, 'member', 'test')
    assert client.patch('/api/v1/projects/1/ai/settings', json={'enabled': True}).status_code == 403
    assert client.patch('/api/v1/projects/1', json={'name': 'Stolen'}).status_code == 403


def test_non_admin_role_requires_existing_project(client):
    login(client)
    assert client.post('/api/v1/admin/roles', json={'user_id': 1, 'role': 'captain'}).status_code == 422
    assert client.post('/api/v1/admin/roles', json={'user_id': 1, 'role': 'captain', 'project_id': 999}).status_code == 404


def test_participants_metrics_are_project_local(client):
    other, user, task = setup_projects(client)
    client.put(f'/api/v1/tasks/{task}/assignees', json={'assignees': [{'user_id': user, 'is_primary': True}]})
    client.post(f'/api/v1/tasks/{task}/timer/start')
    for path in ['/api/v1/projects/1/participants', '/api/v1/projects/1/analytics']:
        body = client.get(path).json()
        rows = body['participants'] if isinstance(body, dict) else body
        member = next(p for p in rows if p['id'] == user)
        assert member['active_tasks'] == 0
        assert member['active_timer_seconds'] == 0


def test_assignee_must_be_project_member(client):
    other, user, task = setup_projects(client)
    outsider = client.post('/api/v1/admin/users', json={'login': 'outsider', 'password': 'test', 'display_name': 'Outsider'}).json()['id']
    r = client.put(f'/api/v1/tasks/{task}/assignees', json={'assignees': [{'user_id': outsider, 'is_primary': True}]})
    assert r.status_code == 422


def test_revoked_project_role_can_be_granted_again(client):
    other, user, task = setup_projects(client)
    role = next(r for r in client.get('/api/v1/admin/roles').json() if r['user_id'] == user and r['project_id'] == 1)
    assert client.delete(f"/api/v1/admin/roles/{role['id']}").status_code == 200
    r = client.post('/api/v1/admin/roles', json={'user_id': user, 'role': 'participant', 'project_id': 1})
    assert r.status_code == 200


def test_revoked_member_cannot_read_project_notification_by_id(client):
    other, user, task = setup_projects(client)
    task = client.post('/api/v1/projects/1/tasks', json={'title': 'Private notification'}).json()['id']
    client.put(f'/api/v1/tasks/{task}/assignees', json={'assignees': [{'user_id': user, 'is_primary': True}]})
    login(client, 'member', 'test')
    notification = client.get('/api/v1/notifications').json()[0]
    login(client)
    role = next(r for r in client.get('/api/v1/admin/roles').json() if r['user_id'] == user and r['project_id'] == 1)
    client.delete(f"/api/v1/admin/roles/{role['id']}")
    login(client, 'member', 'test')
    assert client.post(f"/api/v1/notifications/{notification['id']}/read").status_code == 403
