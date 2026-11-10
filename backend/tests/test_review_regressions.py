"""Regression coverage for atomic creation, retries and bounded task queries."""
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.helpers import login


def test_creation_is_atomic_and_retries_return_the_same_task(client):
    login(client)
    payload = {'title': 'Atomic', 'creation_key': '51a6bdab-d0f3-4e6d-9f1b-4bb20e154ad5',
               'assignees': [{'user_id': 1, 'is_primary': True}]}
    first = client.post('/api/v1/projects/1/tasks', json=payload)
    assert first.status_code == 200, first.text
    assert first.json()['assignees'][0]['user_id'] == 1
    again = client.post('/api/v1/projects/1/tasks', json=payload)
    assert again.status_code == 200 and again.json()['id'] == first.json()['id']
    assert len(client.get('/api/v1/projects/1/tasks').json()) == 1
    assert client.post('/api/v1/projects/1/tasks', json={**payload, 'title': 'Changed'}).status_code == 409
    invalid = client.post('/api/v1/projects/1/tasks', json={
        'title': 'Must roll back', 'assignees': [{'user_id': 99999, 'is_primary': True}],
    })
    assert invalid.status_code == 422
    assert len(client.get('/api/v1/projects/1/tasks').json()) == 1


def test_task_list_has_a_bounded_number_of_queries(client):
    from tests.conftest import TestingSessionLocal
    from app.db.models import BoardColumn, Task
    login(client)
    with TestingSessionLocal() as db:
        column = db.query(BoardColumn).filter_by(project_id=1, key='backlog').one()
        db.add_all([Task(project_id=1, column_id=column.id, title=f'Task {i}') for i in range(30)])
        db.commit()
    queries = []
    def count(*args):
        queries.append(args[2])
    event.listen(Engine, 'before_cursor_execute', count)
    try:
        response = client.get('/api/v1/projects/1/tasks')
    finally:
        event.remove(Engine, 'before_cursor_execute', count)
    assert response.status_code == 200 and len(response.json()) == 30
    assert 0 < len(queries) <= 15, len(queries)
