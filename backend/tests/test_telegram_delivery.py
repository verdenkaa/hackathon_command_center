from datetime import timedelta

from app.db.models import Notification, TelegramDelivery
from app.services.notifications import notify_users
from app.timeutil import utcnow
from tests.conftest import TestingSessionLocal
from tests.helpers import login
import pytest


def configure(client, project_id=1, chat='-100123', routes=None):
    return client.put(f'/api/v1/projects/{project_id}/telegram', json={
        'chat_id': chat, 'routes': routes or {'task_assigned': 12}, 'confirm_chat': True})


def test_queue_pins_destination_and_keeps_internal_notifications(client):
    login(client)
    assert configure(client).status_code == 200
    task = client.post('/api/v1/projects/1/tasks', json={'title': '<Задача & тест>'}).json()
    client.put(f"/api/v1/tasks/{task['id']}/assignees", json={'assignees': [{'user_id': 1, 'is_primary': True}]})
    # Unchanged assignees do not generate another assignment.
    client.put(f"/api/v1/tasks/{task['id']}/assignees", json={'assignees': [{'user_id': 1, 'is_primary': True}]})
    configure(client, chat='-100456')
    with TestingSessionLocal() as db:
        rows = db.query(TelegramDelivery).filter_by(state='pending').all()
        assert len(rows) == 1
        assert rows[0].chat_id == '-100123' and rows[0].thread_id == 12
        assert f"#{task['id']}" in rows[0].text
        assert db.query(Notification).filter_by(type='task_assigned').count() == 1


def test_worker_restart_retry_and_uncertain(client):
    from app.services import telegram as svc
    from app.integrations.telegram import TelegramError
    login(client)
    configure(client)
    with TestingSessionLocal() as db:
        svc.enqueue(db, 1, 'task_assigned', 'Hello', [])
        db.commit()
    calls = []
    def transient(*args):
        calls.append(args)
        raise TelegramError('RATE_LIMIT', retry_after=7)
    assert svc.work_once(TestingSessionLocal, transient)
    with TestingSessionLocal() as db:
        row = db.query(TelegramDelivery).one()
        assert row.state == 'pending' and row.attempts == 1
        assert row.next_attempt_at > utcnow()
        row.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert svc.work_once(TestingSessionLocal, lambda *args: 42)
    assert not svc.work_once(TestingSessionLocal, lambda *args: 99)
    with TestingSessionLocal() as db:
        row = db.query(TelegramDelivery).one()
        assert row.state == 'sent' and row.message_ids == [42]
        svc.enqueue(db, 1, 'task_assigned', 'Lost response', [])
        db.commit()
    def uncertain(*args):
        raise TelegramError('UNKNOWN_RESULT', uncertain=True)
    svc.work_once(TestingSessionLocal, uncertain)
    rows = client.get('/api/v1/projects/1/telegram/deliveries').json()
    row = rows[0]
    assert row['state'] == 'uncertain'
    assert client.post(f"/api/v1/projects/1/telegram/deliveries/{row['id']}/retry", json={}).status_code == 409
    assert client.post(f"/api/v1/projects/1/telegram/deliveries/{row['id']}/retry", json={'accept_duplicate_risk': True}).status_code == 200


def test_off_routes_isolation_and_permissions(client):
    login(client)
    configure(client, routes={'task_assigned': None})
    with TestingSessionLocal() as db:
        notify_users(db, project_id=1, user_ids=[1], ntype='task_assigned', payload={'title': 'T'})
        db.commit()
        assert db.query(Notification).count() == 1
        assert db.query(TelegramDelivery).filter_by(state='pending').count() == 0
    other = client.post('/api/v1/projects', json={'name': 'Other'}).json()['id']
    uid = client.post('/api/v1/admin/users', json={'login':'captain','password':'p','display_name':'Cap'}).json()['id']
    client.post('/api/v1/admin/roles', json={'user_id':uid,'role':'captain','project_id':1})
    login(client, 'captain', 'p')
    assert configure(client).status_code == 200
    assert configure(client, project_id=other).status_code == 403
    assert client.delete('/api/v1/telegram/bot/key').status_code == 403


def test_long_text_and_mentions(client):
    from app.services.telegram import split_text, mentions
    from app.db.models import User
    login(client)
    text = '🙂 <&>\n' * 4000
    parts = split_text(text)
    assert ''.join(parts) == text
    assert all(len(p.encode('utf-16-le')) // 2 <= 3800 for p in parts)
    with TestingSessionLocal() as db:
        db.get(User, 1).telegram_username = '@valid_name'
        db.flush()
        names, missing = mentions(db, [1, 1])
        assert names == ['valid_name'] and missing == []


def test_transaction_rollback_and_parallel_workers(client):
    from concurrent.futures import ThreadPoolExecutor
    from app.services import telegram as svc
    login(client)
    configure(client)
    with TestingSessionLocal() as db:
        notify_users(db, project_id=1, user_ids=[1], ntype='task_assigned', payload={'title':'Rollback'})
        db.rollback()
    with TestingSessionLocal() as db:
        assert db.query(Notification).count() == 0
        assert db.query(TelegramDelivery).count() == 0
        svc.enqueue(db, 1, 'task_assigned', 'One event', [])
        db.commit()
    calls=[]
    def sender(*args):
        calls.append(args)
        return 101
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:svc.work_once(TestingSessionLocal,sender), range(2)))
    assert len(calls) == 1
    with TestingSessionLocal() as db:
        assert db.query(TelegramDelivery).one().state == 'sent'


def test_partial_report_resume_and_expired_lease(client):
    from app.services import telegram as svc
    from app.integrations.telegram import TelegramError
    login(client)
    configure(client)
    with TestingSessionLocal() as db:
        row=svc.enqueue(db,1,'task_assigned','long line\n'*1000,[])
        db.commit()
        row_id=row.id
    calls=[]
    def partial(*args):
        calls.append(args[2])
        if len(calls)==2:
            raise TelegramError('TEMPORARY')
        return 201
    svc.work_once(TestingSessionLocal,partial)
    with TestingSessionLocal() as db:
        row=db.get(TelegramDelivery,row_id)
        assert row.message_ids == [201] and row.state=='pending'
        row.next_attempt_at=utcnow()-timedelta(seconds=1)
        db.commit()
    resumed=[]
    svc.work_once(TestingSessionLocal,lambda *args:resumed.append(args[2]) or 202)
    assert resumed and resumed[0] == calls[1]
    with TestingSessionLocal() as db:
        row=svc.enqueue(db,1,'task_assigned','Interrupted',[])
        row.state='sending'
        row.lease_until=utcnow()-timedelta(seconds=1)
        db.commit()
        row_id=row.id
    assert not svc.work_once(TestingSessionLocal,lambda *_:pytest.fail('Must not resend'))
    with TestingSessionLocal() as db:
        assert db.get(TelegramDelivery,row_id).state=='uncertain'


@pytest.mark.parametrize(('data','expected'),[
    ({'ok':False,'error_code':401},'INVALID_TOKEN'),
    ({'ok':False,'error_code':403},'BOT_FORBIDDEN'),
    ({'ok':False,'error_code':400,'description':'message thread not found'},'TOPIC_UNAVAILABLE'),
    ({'ok':False,'error_code':429,'parameters':{'retry_after':17}},'RATE_LIMIT'),
])
def test_transport_maps_errors_without_secrets(monkeypatch,caplog,data,expected):
    import io,json,urllib.request
    from app.integrations.telegram import TelegramClient, TelegramError, vault
    secret='123456:synthetic_do_not_send_token'
    monkeypatch.setattr(vault,'load',lambda:secret)
    monkeypatch.setattr(urllib.request,'urlopen',lambda *args,**kwargs:io.BytesIO(json.dumps(data).encode()))
    with pytest.raises(TelegramError) as caught:
        TelegramClient().send('-100123',12,'<&> text')
    assert caught.value.code==expected
    assert secret not in str(caught.value) and secret not in caplog.text
    if expected=='RATE_LIMIT':
        assert caught.value.retry_after==17


def test_transport_plain_text_and_topic(monkeypatch):
    import io,json,urllib.request
    from app.integrations.telegram import TelegramClient,vault
    monkeypatch.setattr(vault,'load',lambda:'synthetic')
    requests=[]
    def response(request,**kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(b'{"ok":true,"result":{"message_id":7}}')
    monkeypatch.setattr(urllib.request,'urlopen',response)
    assert TelegramClient().send('-100123',42,'<b> & @username')==7
    assert requests[0]['message_thread_id']==42 and 'parse_mode' not in requests[0]


def test_routes_validation_and_test_delivery(client):
    login(client)
    assert configure(client, routes={'unknown':0}).status_code==422
    assert configure(client, routes={'task_assigned':-3}).status_code==422
    assert client.put('/api/v1/projects/1/telegram',json={'chat_id':'-10012'}).status_code==409
    assert configure(client,routes={'task_assigned':0}).status_code==200
    assert client.post('/api/v1/projects/1/telegram/test',json={'confirmed_chat_id':'-100other'}).status_code==409
    assert client.post('/api/v1/projects/1/telegram/test',json={'confirmed_chat_id':'-100123','thread_id':55}).status_code==202
    row=client.get('/api/v1/projects/1/telegram/deliveries').json()[0]
    assert row['event_type']=='test' and row['thread_id']==55
    assert client.put('/api/v1/projects/1/telegram',json={'public_url':'http://localhost:5173'}).status_code==422


def test_object_links_and_dpapi_storage(client, monkeypatch, tmp_path):
    from app.services import telegram_vault as vault
    if vault.available():
        path=tmp_path/'telegram.dpapi'
        monkeypatch.setattr(vault,'_path',lambda:path)
        secret='123456:synthetic_token_for_dpapi_testing'
        vault.save(secret)
        assert secret.encode() not in path.read_bytes()
        assert vault.load()==secret
        vault.delete()
        assert not vault.is_saved()
    login(client)
    client.put('/api/v1/projects/1/telegram',json={'chat_id':'-100123','confirm_chat':True,
        'routes':{'task_assigned':0},'public_url':'https://team.example/app'})
    task=client.post('/api/v1/projects/1/tasks',json={'title':'Object link'}).json()
    client.put(f"/api/v1/tasks/{task['id']}/assignees",json={'assignees':[{'user_id':1,'is_primary':True}]})
    with TestingSessionLocal() as db:
        row=db.query(TelegramDelivery).filter_by(state='pending').one()
        assert f"https://team.example/app?project=1&task={task['id']}" in row.text
