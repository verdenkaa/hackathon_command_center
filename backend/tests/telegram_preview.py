"""Disposable UI QA. Both providers are fake; never opens Telegram credentials."""
from tests.advisor_preview import app, SessionLocal, advisor
from app.db.models import User, RoleAssignment, TaskAssignee, Task, TelegramSettings
from app.services import telegram_vault
from app.integrations.telegram import telegram_client, TelegramError
from app.services.incidents import create_incident

telegram_vault.is_saved = lambda: True
telegram_vault.available = lambda: True
telegram_vault.delete = lambda: None


def fake_send(chat: str, thread: int | None, text: str) -> int:
    if thread == 999:
        raise TelegramError('TOPIC_UNAVAILABLE')
    return 100


telegram_client.send = fake_send
with SessionLocal() as db:
    captain = User(login='qa-captain', password_hash='', display_name='Тестовый капитан', telegram_username='qa_captain')
    former = User(login='qa-former', password_hash='', display_name='Отключённый участник', active=False)
    db.add_all([captain, former])
    db.flush()
    db.add(RoleAssignment(user_id=captain.id, role='captain', project_id=1))
    task = db.query(Task).first()
    db.add_all([TaskAssignee(task_id=task.id, user_id=former.id, is_primary=True),
                TaskAssignee(task_id=task.id, user_id=captain.id, is_primary=False)])
    create_incident(db, project_id=1, author_id=1, owner_id=former.id, level='yellow',
                    title='Тестовый открытый блокер', description=None, impact=None, urgency='medium', targets=[])
    db.add(TelegramSettings(project_id=1, chat_id='-100000001', routes={'ai_report':10,'task_assigned':0}))
    db.commit()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
