"""Disposable browser QA server. Fake provider only; never opens the real vault."""
from pathlib import Path
import os
import sys
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
directory = root / 'tests' / '.tmp' / ('advisor-preview-' + uuid4().hex)
directory.mkdir(parents=True)
os.environ.update(APP_DATA_DIR=str(directory), DATABASE_URL=f'sqlite:///{(directory / "preview.db").as_posix()}',
                  APP_FIRST_ADMIN_LOGIN='preview-admin', APP_FIRST_ADMIN_PASSWORD='preview-only',
                  APP_FIRST_ADMIN_NAME='QA Admin', APP_ENV='test')

from app.main import app, run_migrations
from app.db.session import SessionLocal
from app.services.bootstrap import bootstrap
from app.services import advisor
from app.db.models import AiSettings, Project, Task, BoardColumn

key_state = {'saved': True}
advisor.vault.is_saved = lambda: key_state['saved']
advisor.vault.available = lambda: True
advisor.vault.delete = lambda: key_state.update(saved=False)
run_migrations()
with SessionLocal() as db:
    bootstrap(db)
    project = db.get(Project, 1)
    project.state = 'active'
    column = db.query(BoardColumn).filter_by(project_id=1).first()
    db.add(Task(project_id=1, title='Подготовить демонстрацию', description='Фиктивная задача для UI-проверки',
                column_id=column.id, priority='high', tags=['demo'], estimate_seconds=3600))
    from app.services.ai import get_settings
    settings = get_settings(db, 1)
    settings.enabled = True
    db.commit()


def fake_provider(_cfg, kind, _system, content):
    import json
    payload = json.loads(content)
    question = payload['question']
    task = payload['snapshot']['summary']['tasks'][0]
    related = {'task_ids': [task['id']], 'track_ids': [], 'user_ids': [1], 'incident_ids': []}
    if 'ошибка' in question.lower():
        raise advisor.ProviderError('INVALID_RESPONSE')
    if kind == 'question':
        return advisor.ProviderReply({'answer': 'План неполный. Уточните размещение задачи и доступность команды.',
            'grounds': ['У задачи нет размещения в плане'], 'limitations': ['Навыки и доступность не подтверждены'],
            'related': related}, 200, 80, 0)
    return advisor.ProviderReply({'captain_intervention': 'required', 'result': 'recommendations', 'recommendations': [{
        'title': 'Уточните план демонстрации', 'situation': 'Есть незавершённая задача без размещения.',
        'grounds': ['Серверный план отмечает неполный охват'], 'consequence': 'Нельзя подтвердить срок завершения.',
        'action': 'Обсудите размещение задачи с командой.', 'limitations': ['Навыки и доступность людей неизвестны'],
        'related': related, 'significance': 'warning', 'freshness': 'current'}]}, 300, 120, 0)


original_work = advisor.work_once
advisor.work_once = lambda factory: original_work(factory, provider=fake_provider)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
