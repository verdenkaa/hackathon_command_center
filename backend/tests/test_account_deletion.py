from app.db.models import User, TaskAssignee, Incident, IncidentEvent, TaskTimer, RoleAssignment, Session
from tests.conftest import TestingSessionLocal
from tests.helpers import login
import pytest
from sqlalchemy import event, text
from tests.conftest import engine


@pytest.fixture(autouse=True)
def foreign_keys():
    def enable(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    event.listen(engine,'connect',enable)
    yield
    event.remove(engine,'connect',enable)


def create(client, name):
    return client.post('/api/v1/admin/users', json={'login':name,'password':'p','display_name':name}).json()['id']


def test_snapshot_user_references_do_not_match_dates_or_task_ids():
    from app.services.account_deletion import references_user
    assert not references_user({'generated_at':'2026-10-29','tasks':[{'id':2}]},2)
    assert references_user({'summary':{'participants':[{'id':2}]}},2)
    assert references_user({'related':{'user_ids':[2]}},2)


def test_username_normalize_clear_validate_audit(client):
    login(client)
    uid = create(client, 'person')
    url = f'/api/v1/admin/users/{uid}'
    assert client.patch(url, json={'telegram_username':' @Valid_name '}).json()['telegram_username'] == 'valid_name'
    assert client.patch(url, json={'telegram_username':'bad name'}).status_code == 422
    assert client.patch(url, json={'telegram_username':None}).json()['telegram_username'] is None
    assert any(e['action'] == 'user.telegram_changed' for e in client.get('/api/v1/audit').json())


def test_delete_preview_replacements_and_preserved_history(client):
    login(client)
    uid, cap, other = [create(client, name) for name in ['remove_me','captain','remaining']]
    for who, role in [(uid,'participant'), (cap,'captain'), (other,'participant')]:
        client.post('/api/v1/admin/roles', json={'user_id':who,'role':role,'project_id':1})
    task = client.post('/api/v1/projects/1/tasks', json={'title':'Keep task'}).json()
    client.post(f"/api/v1/tasks/{task['id']}/timer/start")
    client.put(f"/api/v1/tasks/{task['id']}/assignees", json={'assignees':[
        {'user_id':uid,'is_primary':True}, {'user_id':other,'is_primary':False}]})
    inc = client.post('/api/v1/projects/1/incidents', json={'title':'Keep incident','level':'yellow','owner_id':uid}).json()
    url = f'/api/v1/admin/users/{uid}'
    assert client.request('DELETE',url,json={'confirm':True,'preview_version':'unused'}).status_code==409
    assert client.request('DELETE',url,json={'confirm':False,'preview_version':'unused'}).status_code==422
    assert client.get(url+'/deletion-preview').status_code == 409
    client.post(url+'/deactivate')
    preview = client.get(url+'/deletion-preview').json()
    assert preview['tasks'][0]['needs_primary']
    assert preview['projects'][0]['captains'][0]['id'] == cap
    body = {'confirm':True,'preview_version':preview['version'],'incident_captains':{'1':cap},'task_primaries':{str(task['id']):other}}
    assert client.request('DELETE', url, json={**body,'incident_captains':{'1':other}}).status_code == 409
    with TestingSessionLocal() as db:
        assert db.get(User, uid) is not None
        assert db.get(Incident, inc['id']).owner_id == uid
    assert client.request('DELETE', url, json=body).status_code == 200
    with TestingSessionLocal() as db:
        assert db.get(User, uid) is None
        assert db.query(RoleAssignment).filter_by(user_id=uid).count() == 0
        assert db.query(Session).filter_by(user_id=uid).count() == 0
        assert db.query(TaskAssignee).filter_by(task_id=task['id']).one().is_primary
        assert db.get(Incident, inc['id']).owner_id == cap
        assert db.query(IncidentEvent).filter_by(incident_id=inc['id'], event_type='owner_reassigned').count() == 1
        assert db.query(TaskTimer).filter_by(task_id=task['id']).count() == 1
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
    assert all(u['id'] != uid and u['display_name'] != 'Удалённый пользователь' for u in client.get('/api/v1/admin/users').json())


def test_no_captain_blocks_and_confirmation_required(client):
    login(client)
    uid = create(client, 'owner')
    client.post('/api/v1/admin/roles', json={'user_id':uid,'role':'participant','project_id':1})
    client.post('/api/v1/projects/1/incidents', json={'title':'Open','level':'yellow','owner_id':uid})
    url = f'/api/v1/admin/users/{uid}'
    client.post(url+'/deactivate')
    p = client.get(url+'/deletion-preview').json()
    assert p['blocked']
    assert client.request('DELETE',url,json={'confirm':True,'preview_version':p['version']}).status_code == 409


def test_rollback_scrub_and_stale_preview(client,monkeypatch):
    from app.services import account_deletion as svc
    from app.db.models import AdvisorJob, IncidentTarget, AuditEntry
    from app.telegram_schemas import DeleteAccount
    login(client)
    uid=create(client,'private_person')
    client.patch(f'/api/v1/admin/users/{uid}',json={'login':'new_login','display_name':'Renamed Account'})
    client.patch(f'/api/v1/admin/users/{uid}',json={'telegram_username':'private_name'})
    with TestingSessionLocal() as db:
        db.add(AdvisorJob(project_id=1,user_id=uid,kind='analysis',trigger='manual',state='succeeded',
            snapshot={'participants':[{'id':uid,'display_name':'private_person','telegram_username':'private_name'}]},
            answer={'user_ids':[uid]},question='Ask private_person'))
        db.commit()
    client.post(f'/api/v1/admin/users/{uid}/deactivate')
    p=client.get(f'/api/v1/admin/users/{uid}/deletion-preview').json()
    original=svc.write_audit
    def fail(*args,**kwargs):
        if kwargs['action']=='user.deleted':
            raise RuntimeError('injected failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(svc,'write_audit',fail)
    with TestingSessionLocal() as db:
        with pytest.raises(RuntimeError):
            svc.erase(db,uid,DeleteAccount(confirm=True,preview_version=p['version']),1)
        db.rollback()
    with TestingSessionLocal() as db:
        assert db.get(User,uid) and db.query(User).filter_by(deleted_identity=True).count()==0
        assert db.query(AdvisorJob).one().snapshot['participants'][0]['display_name']=='private_person'
    monkeypatch.setattr(svc,'write_audit',original)
    client.patch(f'/api/v1/admin/users/{uid}',json={'display_name':'Changed private_person'})
    assert client.request('DELETE',f'/api/v1/admin/users/{uid}',json={'confirm':True,'preview_version':p['version']}).status_code==409
    p=client.get(f'/api/v1/admin/users/{uid}/deletion-preview').json()
    assert client.request('DELETE',f'/api/v1/admin/users/{uid}',json={'confirm':True,'preview_version':p['version']}).status_code==200
    with TestingSessionLocal() as db:
        assert db.get(User,uid) is None
        job=db.query(AdvisorJob).one()
        assert 'private_person' not in str(job.snapshot) and 'private_name' not in str(job.snapshot)
        assert 'private_person' not in job.question
        assert not db.execute(text('PRAGMA foreign_key_check')).all()


def test_partial_delivery_pauses_after_identity_redaction(client):
    from app.db.models import TelegramDelivery
    login(client)
    uid=create(client,'redact_person')
    with TestingSessionLocal() as db:
        db.add(TelegramDelivery(project_id=1,event_type='ai_report',text='Action for redact_person',
            mentions=[],mode='live',state='pending',chat_id='-100123',message_ids=[70]))
        db.commit()
    client.post(f'/api/v1/admin/users/{uid}/deactivate')
    p=client.get(f'/api/v1/admin/users/{uid}/deletion-preview').json()
    assert client.request('DELETE',f'/api/v1/admin/users/{uid}',json={'confirm':True,'preview_version':p['version']}).status_code==200
    with TestingSessionLocal() as db:
        row=db.query(TelegramDelivery).one()
        assert row.state=='uncertain' and row.error_code=='CONTENT_CHANGED' and row.message_ids==[70]
    assert client.post(f'/api/v1/projects/1/telegram/deliveries/{row.id}/retry',json={'accept_duplicate_risk':True}).status_code==200
    with TestingSessionLocal() as db:
        assert db.query(TelegramDelivery).one().message_ids==[]


def test_closed_incident_history_displays_deleted_identity(client):
    from app.db.models import AiRecommendation
    login(client)
    uid=create(client,'closed_author')
    with TestingSessionLocal() as db:
        incident=Incident(project_id=1,number=1,level='yellow',status='resolved',title='Keep closed',author_id=uid,owner_id=uid)
        db.add(incident)
        db.flush()
        iid=incident.id
        db.add(IncidentEvent(incident_id=iid,actor_id=uid,event_type='resolved',data={}))
        db.add(AiRecommendation(project_id=1,provider='gemini',summary='Keep',content='Keep',status_by=uid))
        db.commit()
    client.post(f'/api/v1/admin/users/{uid}/deactivate')
    p=client.get(f'/api/v1/admin/users/{uid}/deletion-preview').json()
    assert client.request('DELETE',f'/api/v1/admin/users/{uid}',json={'confirm':True,'preview_version':p['version']}).status_code==200
    result=client.get(f'/api/v1/incidents/{iid}').json()
    assert result['deleted_user_ids']==[result['author_id']]
    assert result['owner_id']==result['author_id']==result['events'][0]['actor_id']
    assert client.get('/api/v1/projects/1/ai/recommendations').json()[0]['status_by_name']=='Удалённый пользователь'
