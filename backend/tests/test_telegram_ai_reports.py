import pytest
from pydantic import ValidationError
from app.advisor_schemas import AnalysisReply
from app.db.models import AdvisorJob, TelegramDelivery, User, RoleAssignment
from tests.conftest import TestingSessionLocal
from tests.helpers import login


def test_captain_decision_required_and_consistent():
    with pytest.raises(ValidationError):
        AnalysisReply.model_validate({'result':'no_new_recommendations','recommendations':[]})
    with pytest.raises(ValidationError):
        AnalysisReply.model_validate({'result':'recommendations','captain_intervention':'not_required','recommendations':[{}]})
    assert AnalysisReply.model_validate({'result':'no_new_recommendations','captain_intervention':'required',
        'summary':'Остаётся открытый вопрос для капитана, новых советов нет.','recommendations':[]})


def test_automatic_missing_key_reports_failure(client,monkeypatch):
    from app.services import advisor
    from app.db.models import Project,AiSettings
    from app.timeutil import utcnow
    from datetime import timedelta
    login(client)
    client.put('/api/v1/projects/1/telegram',json={'chat_id':'-10077','confirm_chat':True,'routes':{'ai_report':0}})
    client.patch('/api/v1/projects/1/ai/settings',json={'enabled':True,'auto_enabled':True})
    monkeypatch.setattr(advisor.vault,'is_saved',lambda:False)
    with TestingSessionLocal() as db:
        db.get(Project,1).state='active'
        db.query(AiSettings).one().next_run_at=utcnow()-timedelta(seconds=1)
        db.commit()
        advisor.schedule(db)
    advisor.work_once(TestingSessionLocal,provider=lambda *_:pytest.fail('No provider without key'))
    with TestingSessionLocal() as db:
        row=db.query(TelegramDelivery).filter_by(event_type='ai_report').one()
        assert 'автоматический' in row.text and 'KEY_MISSING' in row.text


def test_finished_runs_report_no_new_and_failure_but_not_questions(client, monkeypatch):
    from app.services import advisor
    monkeypatch.setattr(advisor.vault, 'is_saved', lambda: True)
    login(client)
    client.put('/api/v1/projects/1/telegram', json={'chat_id':'-100999','confirm_chat':True,'routes':{'ai_report':18}})
    client.patch('/api/v1/projects/1/ai/settings', json={'enabled':True})
    client.post('/api/v1/projects/1/ai/requests', json={'kind':'analysis'})
    advisor.work_once(TestingSessionLocal, provider=lambda *_: advisor.ProviderReply({
        'result':'no_new_recommendations','recommendations':[],'captain_intervention':'not_required'}))
    with TestingSessionLocal() as db:
        row = db.query(TelegramDelivery).filter_by(event_type='ai_report').one()
        assert 'Новых рекомендаций нет' in row.text
        assert not row.mentions
    client.post('/api/v1/projects/1/ai/requests', json={'kind':'analysis'})
    advisor.work_once(TestingSessionLocal, provider=lambda *_: advisor.ProviderReply({
        'result':'no_new_recommendations','recommendations':[]}))
    with TestingSessionLocal() as db:
        assert db.query(AdvisorJob).order_by(AdvisorJob.id.desc()).first().state == 'failed'
        rows = db.query(TelegramDelivery).filter_by(event_type='ai_report').all()
        assert len(rows) == 2 and 'не выполнен' in rows[1].text
    client.post('/api/v1/projects/1/ai/requests', json={'kind':'question','question':'Почему?'})
    advisor.work_once(TestingSessionLocal, provider=lambda *_: advisor.ProviderReply({
        'answer':'Ответ','grounds':['Факт'],'limitations':['Неизвестно'],'related':{}}))
    with TestingSessionLocal() as db:
        assert db.query(TelegramDelivery).filter_by(event_type='ai_report').count() == 2


def test_full_report_dedup_mentions_and_no_new_rec_still_reports(client, monkeypatch):
    from app.services import advisor
    from tests.test_advisor import recommendation
    monkeypatch.setattr(advisor.vault,'is_saved',lambda:True)
    login(client)
    client.patch('/api/v1/admin/users/1',json={'telegram_username':'admin_user'})
    cap=client.post('/api/v1/admin/users',json={'login':'cap','password':'p','display_name':'Cap','telegram_username':'captain_user'}).json()['id']
    client.post('/api/v1/admin/roles',json={'user_id':cap,'role':'captain','project_id':1})
    client.put('/api/v1/projects/1/telegram',json={'chat_id':'-10099','confirm_chat':True,'routes':{'ai_report':5}})
    client.patch('/api/v1/projects/1/ai/settings',json={'enabled':True})
    item=recommendation()
    item['action_user_ids']=[1,1,cap]
    for _ in range(2):
        client.post('/api/v1/projects/1/ai/requests',json={'kind':'analysis'})
        advisor.work_once(TestingSessionLocal,provider=lambda *_:advisor.ProviderReply({
            'captain_intervention':'required','result':'recommendations','recommendations':[item]}))
    with TestingSessionLocal() as db:
        rows=db.query(TelegramDelivery).filter_by(event_type='ai_report').all()
        assert len(rows)==2
        assert rows[0].text.count('@admin_user')==1 and rows[0].text.count('@captain_user')==1
        assert item['action'] in rows[1].text and item['consequence'] in rows[1].text
    assert len(client.get('/api/v1/projects/1/ai/recommendations').json())==1
    item['action_user_ids']=[999999]
    client.post('/api/v1/projects/1/ai/requests',json={'kind':'analysis'})
    advisor.work_once(TestingSessionLocal,provider=lambda *_:advisor.ProviderReply({
        'captain_intervention':'required','result':'recommendations','recommendations':[item]}))
    with TestingSessionLocal() as db:
        assert db.query(AdvisorJob).order_by(AdvisorJob.id.desc()).first().state=='failed'
