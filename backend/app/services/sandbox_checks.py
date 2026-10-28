"""Actual HTTP API checks in a disposable SQLite database, never the live app DB."""
from __future__ import annotations

import time
import os
import sys
import json
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.base import Base
from app.db.models import Project, RoleAssignment, User
from app.deps import get_db
from app.security import hash_password
from app.services.board import create_default_columns


class CheckResult(BaseModel):
    name: str
    title: str
    status: Literal['passed', 'failed']
    detail: str
    duration_ms: int


CHECKS: dict[str, str] = {
    'auth': 'Вход, выход и проектные права',
    'board': 'Колонки, задачи, связи и чек-листы',
    'timers': 'Таймеры и корректировка времени',
    'incidents': 'Блокеры, эскалация и светофор',
    'ai': 'Контекст ИИ и уведомления Telegram',
    'completion': 'Завершение и повторное открытие',
    'recovery': 'Резервная копия и восстановление',
}


class CheckContext:
    def __init__(self, client: TestClient, database: Path, directory: Path) -> None:
        self.client = client
        self.database = database
        self.directory = directory

    def request(self, method: str, path: str, body: dict[str, Any] | None = None,
                status: int = 200) -> Any:
        response = self.client.request(method, '/api/v1' + path, json=body)
        if response.status_code != status:
            raise AssertionError(f'{method} {path}: ожидался HTTP {status}, получен {response.status_code}')
        return response.json()

    def login(self, role: str = 'admin') -> None:
        self.request('POST', '/auth/login', {'login': role, 'password': 'sandbox-pass'})

    def task(self, title: str) -> dict[str, Any]:
        return self.request('POST', '/projects/1/tasks', {'title': title})


@contextmanager
def isolated_context(directory: Path) -> Iterator[CheckContext]:
    from app.main import create_app
    from fastapi.testclient import TestClient

    database = directory / 'checks.db'
    engine = create_engine(f'sqlite:///{database.as_posix()}',
                           connect_args={'check_same_thread': False}, poolclass=NullPool)

    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute('PRAGMA foreign_keys=ON')

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        password_hash = hash_password('sandbox-pass')
        db.add_all([User(login=role, display_name=role, password_hash=password_hash)
                    for role in ['admin', 'member', 'captain']])
        db.add_all([Project(name='Isolated sandbox', state='active'), Project(name='Private project')])
        db.flush()
        for pid in [1, 2]:
            create_default_columns(db, pid)
        db.add_all([RoleAssignment(user_id=1, role='admin'),
                    RoleAssignment(user_id=2, role='participant', project_id=1),
                    RoleAssignment(user_id=3, role='captain', project_id=1)])
        db.commit()

    def test_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = test_db
    # Do not start lifespan: it migrates the live DB and starts background jobs.
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield CheckContext(client, database, directory)
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def check_auth(c: CheckContext) -> str:
    c.client.cookies.clear()
    c.request('GET', '/auth/me', status=401)
    c.request('POST', '/auth/login', {'login': 'member', 'password': 'wrong'}, status=401)
    c.login('member')
    projects = c.request('GET', '/projects')
    assert [p['id'] for p in projects] == [1], 'Участник видит чужой проект'
    c.request('GET', '/projects/2/tasks', status=403)
    c.request('GET', '/admin/users', status=403)
    c.request('POST', '/admin/backups', status=403)
    c.request('PATCH', '/projects/1/ai/settings', {'enabled': True}, status=403)
    c.request('POST', '/auth/logout')
    c.request('GET', '/auth/me', status=401)
    c.login('captain')
    c.request('PATCH', '/projects/1', {'name': 'Captain project'})
    c.request('PATCH', '/projects/2', {'name': 'Forbidden'}, status=403)
    return 'Проверены реальные сессии, отказ неверному паролю, роли и запрет чужого проекта/админки.'


def check_board(c: CheckContext) -> str:
    c.login()
    module = c.request('POST', '/projects/1/modules', {'name': 'API'})
    col = c.request('POST', '/projects/1/columns', {'title': 'Custom work', 'auto_start_timer': True})
    task = c.request('POST', '/projects/1/tasks', {'title': 'API task', 'module_id': module['id'], 'tags': ['sandbox'], 'estimate_seconds': 3600})
    tid = task['id']
    c.request('PUT', f'/tasks/{tid}/assignees', {'assignees': [{'user_id': 2, 'is_primary': True}]})
    sub = c.request('POST', '/projects/1/tasks', {'title': 'Subtask', 'parent_id': tid})
    c.request('POST', f'/tasks/{tid}/dependencies', {'predecessor_id': sub['id'], 'link_type': 'after'})
    item = c.request('POST', f'/tasks/{tid}/checklist', {'text': 'API check'})
    assert c.request('PATCH', f"/checklist/{item['id']}", {'done': True})['done']
    task = c.request('GET', f'/tasks/{tid}')
    moved = c.request('POST', f'/tasks/{tid}/move', {'column_key': col['key'], 'version': task['version']})
    assert moved['timer']['state'] == 'running', 'Автостарт таймера не сработал'
    c.request('PATCH', f'/tasks/{tid}', {'title': 'Conflict', 'version': task['version']}, status=409)
    columns = c.request('GET', '/projects/1/columns')
    done = next(x for x in columns if x['key'] == 'done')
    c.request('PATCH', f"/columns/{done['id']}", {'auto_stop_timer': True})
    moved = c.request('POST', f'/tasks/{tid}/move', {'column_key': 'done', 'version': moved['version']})
    assert moved['timer']['state'] == 'stopped', 'Автостоп таймера не сработал'
    c.request('DELETE', f"/columns/{done['id']}", status=409)
    c.request('DELETE', f"/columns/{col['id']}")
    assert c.request('GET', f'/tasks/{tid}')['predecessors'], 'Связь задачи потеряна'
    return 'Создание, назначения, подзадачи, зависимости, чек-лист, пользовательская колонка и конфликт версий.'


def check_timers(c: CheckContext) -> str:
    c.login()
    tid = c.task('Timer check')['id']
    assert c.request('POST', f'/tasks/{tid}/timer/start')['state'] == 'running'
    c.request('POST', f'/tasks/{tid}/timer/start', status=409)
    assert c.request('POST', f'/tasks/{tid}/timer/pause')['state'] == 'paused'
    c.request('POST', f'/tasks/{tid}/timer/start')
    assert c.request('POST', f'/tasks/{tid}/timer/stop')['state'] == 'stopped'
    c.login('captain')
    assert c.request('POST', f'/tasks/{tid}/time-adjustment', {'accumulated_seconds':3600})['total_seconds'] == 3600
    c.login('member')
    c.request('POST', f'/tasks/{tid}/time-adjustment', {'accumulated_seconds':0}, status=403)
    return 'Старт → пауза → продолжение → стоп, защита от двойного старта и права на корректировку.'


def check_incidents(c: CheckContext) -> str:
    c.login('member')
    yellow = c.request('POST', '/projects/1/incidents', {'title':'Yellow check', 'level':'yellow', 'owner_id':2,
        'targets':[{'target_type':'user','target_id':2}]})
    c.request('POST', f"/incidents/{yellow['id']}/events", {'text':'Investigating'})
    assert next(p for p in c.request('GET','/projects/1/participants') if p['id']==2)['traffic_status']=='yellow'
    c.request('POST', f"/incidents/{yellow['id']}/resolve", {'resolution':'Fixed'})
    red = c.request('POST', '/projects/1/incidents', {'title':'Red check','level':'red',
        'targets':[{'target_type':'user','target_id':2}]})
    c.request('POST', f"/incidents/{red['id']}/confirm-red", {'confirm':True}, status=403)
    c.login('captain')
    c.request('POST', f"/incidents/{red['id']}/confirm-red", {'confirm':True})
    assert next(p for p in c.request('GET','/projects/1/participants') if p['id']==2)['traffic_status']=='red'
    resolved = c.request('POST', f"/incidents/{red['id']}/resolve", {'resolution':'Recovered'})
    assert resolved['status']=='resolved'
    assert next(p for p in c.request('GET','/projects/1/participants') if p['id']==2)['traffic_status']=='green'
    return 'Жёлтый блокер, комментарий, красная эскалация, полномочия капитана и возврат светофора к зелёному.'


def check_ai(c: CheckContext) -> str:
    c.login()
    c.task('AI context check')
    c.request('POST','/projects/1/ai/run',{'trigger':'manual'},status=409)
    c.request('PATCH','/projects/1/ai/settings',{'priority_provider':'unknown'},status=422)
    c.request('PATCH','/projects/1/ai/settings',{'enabled':True,'prompt':'Sandbox prompt','triggers':{'overdue':False}})
    preview = c.request('POST','/projects/1/ai/preview',{'question':'What is blocked?'})
    assert preview['mode']=='mock' and preview['prompt']=='Sandbox prompt'
    # Exercise legacy history only inside this disposable DB; no credential or provider use.
    from app.services.ai import run_recommendation
    engine = create_engine(f'sqlite:///{c.database.as_posix()}')
    with Session(engine) as db:
        row = run_recommendation(db, 1, 'manual', 'What is blocked?')
        db.commit()
        rec = {'id': row.id, 'request_context': row.request_context}
    engine.dispose()
    rec['request_context']['snapshot']['analytics_summary'].pop('generated_at', None)
    preview['snapshot']['analytics_summary'].pop('generated_at', None)
    assert rec['request_context']==preview, 'Сохранённый контекст отличается от запроса'
    c.request('POST',f"/projects/1/ai/recommendations/{rec['id']}/exclude")
    preview = c.request('GET','/projects/1/ai/preview')
    assert preview['snapshot']['previous_recommendations']==[], 'Исключённая рекомендация осталась в контексте'
    c.request('POST','/projects/1/ai/run',{'trigger':'overdue'},status=422)
    messages = c.request('GET','/admin/sandbox/telegram?project_id=1')
    assert any(m['event_type']=='ai_recommendation' and m['mode']=='mock' for m in messages)
    c.login('member')
    notifications=c.request('GET','/notifications')
    assert notifications, 'Нет внутреннего уведомления участнику'
    c.request('POST',f"/notifications/{notifications[0]['id']}/read")
    return 'Выключенный ИИ, неверные настройки, промпт/вопрос, сохранённый контекст, исключение рекомендации, отключённый триггер и журналы моков.'


def check_completion(c: CheckContext) -> str:
    c.login()
    c.request('POST','/projects/1/completion-votes',{'action':'complete'})
    c.login('captain')
    assert c.request('POST','/projects/1/completion-votes',{'action':'complete'})['state']=='completed'
    c.request('POST','/projects/1/tasks',{'title':'Forbidden mutation'},status=409)
    c.request('POST','/projects/1/completion-votes',{'action':'reopen'})
    c.login()
    assert c.request('POST','/projects/1/completion-votes',{'action':'reopen'})['state']=='preparation'
    c.task('Reopened project task')
    return 'Единогласное голосование, режим чтения и восстановление записи после повторного открытия.'


def check_recovery(c: CheckContext) -> str:
    directory = (c.directory / 'recovery-process').resolve()
    directory.mkdir()
    environment = {**os.environ, 'APP_ENV':'sandbox_check', 'APP_DATA_DIR':str(directory),
        'DATABASE_URL':f"sqlite:///{(directory / 'database.db').as_posix()}",
        'APP_FIRST_ADMIN_LOGIN':'sandbox-admin','APP_FIRST_ADMIN_PASSWORD':'sandbox-pass',
        'APP_FIRST_ADMIN_NAME':'Sandbox admin', 'APP_SECRET_KEY':'sandbox-check-only',
        'PYTHONIOENCODING':'utf-8', 'TELEGRAM_BOT_TOKEN':'', 'TELEGRAM_CHAT_ID':'',
        'AI_GEMINI_API_KEY':'', 'AI_DEEPSEEK_API_KEY':'', 'GOOGLE_DRIVE_FOLDER_ID':'','FXTUNNEL_TOKEN':''}
    result = subprocess.run([sys.executable,'-m','app.services.sandbox_storage_check',str(directory)],
        cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True,
        text=True, encoding='utf-8', timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise RuntimeError('Изолированная проверка восстановления не вернула отчёт')
    if result.returncode != 0 or report.get('status') != 'passed':
        raise AssertionError(report.get('detail','Ошибка проверки восстановления'))
    return str(report['detail'])


RUNNERS: dict[str, Callable[[CheckContext], str]] = {
    'auth':check_auth, 'board':check_board, 'timers':check_timers, 'incidents':check_incidents,
    'ai':check_ai, 'completion':check_completion, 'recovery':check_recovery,
}


def run_checks(group: str | None = None) -> list[CheckResult]:
    root = settings.data_dir / 'sandbox-checks'
    root.mkdir(parents=True, exist_ok=True)
    results: list[CheckResult] = []
    with TemporaryDirectory(prefix='run-', dir=root) as temporary:
        with isolated_context(Path(temporary)) as context:
            for name in ([group] if group else list(CHECKS)):
                started=time.perf_counter()
                try:
                    detail=RUNNERS[name](context)
                    status: Literal['passed','failed']='passed'
                except Exception as exc:
                    detail=f'{type(exc).__name__}: {exc}'[:600]
                    status='failed'
                results.append(CheckResult(name=name,title=CHECKS[name],status=status,detail=detail,
                                           duration_ms=max(1,int((time.perf_counter()-started)*1000))))
    return results
