"""Административная песочница: симуляция работы команды на изолированном проекте."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import (
    BoardColumn,
    Incident,
    Project,
    ProjectState,
    RoleAssignment,
    SandboxRun,
    Task,
    TaskAssignee,
    TaskTimer,
    TimerSegment,
    User,
)
from app.security import hash_password, verify_password
from app.services.audit import write_audit
from app.services.board import create_default_columns
from app.services.incidents import create_incident
from app.timeutil import utcnow

SANDBOX_NAME = "Sandbox"

# Сценарии: имя → описание для интерфейса.
SCENARIOS: dict[str, str] = {
    'prepare_demo': 'Подготовить полный демо-набор без дубликатов: доска, связи, таймеры, светофор и ИИ',
    "create_team": "Создать тестовую команду (alice, bob — участники; cap — капитан)",
    "simulate_sprint": "Симулировать работу: задачи, таймеры, перемещения и инцидент от имени команды",
    "overdue_as_dev": "От имени alice просрочить задачу (дедлайн в прошлом)",
    "incident_as_dev": "От имени bob создать жёлтый инцидент",
    "timer_cycle": "Полный цикл таймера: start → pause → stop",
    "mock_notifications": "Мок Telegram: назначение задачи, блокер и просрочка (только Sandbox)",
    "integration_failure": "Проверить выключенный ИИ, неверные настройки и отключённые триггеры в изолированной БД",
}

TEAM = [("alice", "Alice", "participant"), ("bob", "Bob", "participant"), ("cap", "Captain", "captain")]


def get_sandbox_project(db: Session) -> Project:
    from app.services.sandbox_workspace import find_workspace
    project = find_workspace(db)
    if project is None:
        project = Project(name=SANDBOX_NAME, state=ProjectState.active, settings={'sandbox': True})
        db.add(project)
        db.flush()
        create_default_columns(db, project.id)
        db.commit()
        db.refresh(project)
    return project


def get_team(db: Session, project: Project) -> dict[str, User]:
    users: dict[str, User] = {}
    for login, name, role in TEAM:
        u = db.query(User).filter(User.login == login).first()
        # Never reactivate an account disabled by the administrator.
        suffix = 0
        while u is not None and (not u.active or not verify_password('sandbox-pass', u.password_hash)):
            suffix += 1
            candidate = f'sandbox_{login}' + (f'_{suffix}' if suffix > 1 else '')
            u = db.query(User).filter(User.login == candidate).first()
        test_login = candidate if suffix else login
        if u is None:
            u = User(login=test_login, password_hash=hash_password("sandbox-pass"), display_name=name, active=True)
            db.add(u)
            db.flush()
        assigned = db.query(RoleAssignment).filter(
            RoleAssignment.user_id == u.id,
            RoleAssignment.role == role,
            RoleAssignment.project_id == project.id,
        ).first()
        if assigned is None:
            db.add(RoleAssignment(user_id=u.id, role=role, project_id=project.id, granted_by=None))
        else:
            assigned.revoked_at = None
        users[login] = u
    project.settings = {**project.settings, 'sandbox_team': {key: user.id for key, user in users.items()}}
    db.commit()
    return users


def _column(db: Session, project_id: int, key: str) -> BoardColumn:
    return db.query(BoardColumn).filter(BoardColumn.project_id == project_id, BoardColumn.key == key).first()


def _make_task(db: Session, project: Project, title: str, column_key: str, assignee: User | None = None,
               deadline=None, primary: bool = True, actor_id: int | None = None) -> Task:
    task = Task(
        project_id=project.id,
        column_id=_column(db, project.id, column_key).id,
        title=title,
        deadline=deadline,
        priority="medium",
    )
    db.add(task)
    db.flush()
    if assignee is not None:
        db.add(TaskAssignee(task_id=task.id, user_id=assignee.id, is_primary=primary))
    write_audit(db, action="task.created", actor_id=actor_id, project_id=project.id,
                entity_type="task", entity_id=task.id, data={"title": title})
    if column_key in ("done", "realised"):
        write_audit(db, action="task.moved", actor_id=actor_id, project_id=project.id,
                    entity_type="task", entity_id=task.id, data={"key": column_key})
    return task


def run_scenario(db: Session, scenario: str, actor_id: int | None) -> tuple[bool, list[str]]:
    logs: list[str] = []
    project = get_sandbox_project(db)

    if scenario == 'prepare_demo':
        return prepare_demo(db, project)

    if scenario == "create_team":
        team = get_team(db, project)
        logs.append(f"Команда создана: {', '.join(f'{v.login} ({v.display_name})' for v in team.values())}")

    elif scenario == "simulate_sprint":
        from app.services import timers

        team = get_team(db, project)
        # Останавливаем старые запущенные таймеры проекта, чтобы не копились параллельные.
        now = utcnow()
        for old in (
            db.query(TaskTimer)
            .join(Task, Task.id == TaskTimer.task_id)
            .filter(Task.project_id == project.id, TaskTimer.state == "running")
            .all()
        ):
            seg = (
                db.query(TimerSegment)
                .filter(TimerSegment.task_id == old.task_id, TimerSegment.ended_at.is_(None))
                .first()
            )
            if seg is not None:
                seg.ended_at = now
                old.accumulated_seconds += max(0, int((now - seg.started_at).total_seconds()))
            old.state = "stopped"
            old.last_started_at = None

        # Активная задача alice с запущенным таймером.
        t1 = _make_task(db, project, "API эндпоинты", "in_progress", team["alice"])
        timers.start_timer(db, t1.id)
        # Просроченная задача bob.
        _make_task(db, project, "Форма входа", "todo", team["bob"], deadline=utcnow() - timedelta(hours=5))
        # Завершённая задача.
        _make_task(db, project, "Схема БД", "done", team["cap"])
        # Жёлтый инцидент от bob про его задачу.
        inc = create_incident(
            db, project_id=project.id, author_id=team["bob"].id, level="yellow",
            title="Не проходит авторизация", description="Симуляция спринта", impact="Блокирует форму входа",
            urgency="high", owner_id=team["bob"].id, targets=[],
        )
        db.commit()
        logs.append(f"Спринт сымитирован: 3 задачи (у alice — активный таймер), инцидент id={inc.id} от bob")

    elif scenario == "overdue_as_dev":
        team = get_team(db, project)
        task = _make_task(db, project, "Просроченная задача", "in_progress", team["alice"],
                          deadline=utcnow() - timedelta(days=1))
        db.commit()
        logs.append(f"alice получила просроченную задачу id={task.id}")

    elif scenario == "incident_as_dev":
        team = get_team(db, project)
        inc = create_incident(
            db, project_id=project.id, author_id=team["bob"].id, level="yellow",
            title="Блокер от bob", description="Симуляция", impact=None, urgency="medium",
            owner_id=team["bob"].id, targets=[],
        )
        db.commit()
        logs.append(f"bob создал жёлтый инцидент id={inc.id}")

    elif scenario == "timer_cycle":
        from app.services import timers

        task = _make_task(db, project, "Задача таймера", "backlog")
        timers.start_timer(db, task.id)
        timers.pause_timer(db, task.id)
        timers.stop_timer(db, task.id)
        db.commit()
        logs.append(f"Цикл таймера выполнен для задачи id={task.id}")

    elif scenario == 'mock_notifications':
        from app.services.notifications import notify_users, captains
        from app.services.jobs import check_overdue
        team = get_team(db, project)
        task = _make_task(db, project, 'Проверка уведомлений', 'todo', team['alice'],
                          deadline=utcnow() - timedelta(minutes=1))
        notify_users(db, project_id=project.id, user_ids=[team['alice'].id], ntype='task_assigned',
                     payload={'task_id': task.id, 'title': task.title}, telegram_text=f'📌 Назначена задача: {task.title}')
        incident = create_incident(db, project_id=project.id, author_id=team['bob'].id, level='yellow',
            title='Проверка уведомления о блокере', description=None, impact=None, urgency='medium',
            owner_id=team['bob'].id, targets=[])
        notify_users(db, project_id=project.id, user_ids=captains(db, project.id), ntype='incident_yellow_created',
                     payload={'incident_id': incident.id, 'title': incident.title}, telegram_text=f'🟡 Блокер: {incident.title}')
        db.commit()
        count = check_overdue(db, project.id)
        logs.append(f'Мок Telegram: назначение, блокер и {count} просрочек. Проект Sandbox #{project.id}; реальной отправки нет.')

    else:
        return False, [f"Неизвестный сценарий: {scenario}"]

    return True, logs


def record_run(db: Session, scenario: str, status: str, logs: list[str], actor_id: int | None,
               checks: list[dict] | None = None, duration_ms: int = 0) -> SandboxRun:
    run = SandboxRun(scenario=scenario, status=status, logs=logs, run_by=actor_id,
                     checks=checks or [], duration_ms=duration_ms)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def prepare_demo(db: Session, project: Project) -> tuple[bool, list[str]]:
    from app.db.models import Module, TaskDependency, ChecklistItem
    from app.schemas import IncidentTargetIn
    from app.services import timers, ai
    from app.services.incidents import confirm_red
    from app.services.notifications import notify_users, team as project_team

    if project.settings.get('demo_version') == 1:
        return True, [f'Демо уже подготовлено в проекте #{project.id}. Повторный запуск не создаёт дубликатов.']
    users = get_team(db, project)
    project.state = ProjectState.active
    project.deadline_msk = utcnow() + timedelta(hours=5)
    modules = [Module(project_id=project.id, name=name, description='Модуль демонстрационного проекта')
               for name in ['Backend', 'Frontend']]
    db.add_all(modules)
    db.flush()
    _column(db, project.id, 'in_progress').auto_start_timer = True
    _column(db, project.id, 'done').auto_stop_timer = True
    tasks: list[Task] = []
    titles = ['Идеи для демо', 'Исправить просроченную форму входа', 'Согласовать контракт API',
              'Реализовать авторизацию', 'Проверить интерфейс', 'Провести ревью',
              'Создать схему БД', 'Показать презентацию', 'Отменённый эксперимент']
    keys = ['backlog','todo','specification_review','in_progress','testing','review','done','realised','trashed']
    for index, (key, title) in enumerate(zip(keys, titles)):
        assignee = users[['alice','bob','cap'][index % 3]]
        task = _make_task(db, project, title, key, assignee, actor_id=assignee.id,
                          deadline=utcnow() - timedelta(hours=1) if key == 'todo' else None)
        task.module_id = modules[index % 2].id
        task.description = 'Тестовые данные: проверьте редактирование, назначения, статусы и историю.'
        task.priority = ['low','medium','high','critical'][index % 4]
        task.tags = ['sandbox_demo', 'api' if index % 2 == 0 else 'ui']
        task.estimate_seconds = 3600
        tasks.append(task)
    child = _make_task(db, project, 'Подзадача: проверка токена', 'todo', users['alice'], actor_id=users['alice'].id)
    child.parent_id = tasks[3].id
    db.add(TaskDependency(task_id=tasks[3].id, predecessor_id=tasks[2].id, link_type='blocked_by'))
    db.add_all([ChecklistItem(task_id=tasks[3].id, text=text, done=index == 0, position=index)
                for index, text in enumerate(['Контракт согласован', 'Проверить ошибки', 'Показать команде'])])
    timers.start_timer(db, tasks[3].id)
    timers.start_timer(db, tasks[4].id)
    timers.pause_timer(db, tasks[4].id)
    timers.get_timer(db, tasks[4].id).accumulated_seconds = 900
    yellow = create_incident(db, project_id=project.id, author_id=users['alice'].id, level='yellow',
        title='Локальный блокер API', description='Проверка жёлтого сигнала', impact='Задача заблокирована',
        urgency='high', owner_id=users['alice'].id,
        targets=[IncidentTargetIn(target_type='task', target_id=tasks[3].id),
                 IncidentTargetIn(target_type='user', target_id=users['alice'].id)])
    red = create_incident(db, project_id=project.id, author_id=users['bob'].id, level='red',
        title='Недоступен тестовый сервис', description='Подтверждённая эскалация', impact='Риск для демо',
        urgency='critical', owner_id=users['bob'].id,
        targets=[IncidentTargetIn(target_type='user', target_id=users['bob'].id),
                 IncidentTargetIn(target_type='module', target_id=modules[1].id)])
    confirm_red(db, red, users['cap'].id, True, 'Тестовое подтверждение капитана')
    notify_users(db, project_id=project.id, user_ids=project_team(db, project.id),
        ntype='incident_yellow_created', payload={'incident_id':yellow.id,'title':yellow.title},
        telegram_text=f'🟡 Блокер: {yellow.title}')
    notify_users(db, project_id=project.id, user_ids=project_team(db, project.id),
        ntype='incident_red_confirmed', payload={'incident_id':red.id,'title':red.title},
        telegram_text=f'🔴 Глобальная проблема: {red.title}')
    config = ai.get_settings(db, project.id)
    config.enabled = True
    ai.run_recommendation(db, project.id, 'manual', 'Проверь демонстрационный проект')
    project.settings = {**project.settings, 'demo_version':1}
    db.commit()
    return True, [f'Подготовлен проект #{project.id}: 10 задач, 2 модуля, чек-лист, зависимость и подзадача.',
                  'Есть активный и приостановленный таймеры, жёлтый блокер, красная эскалация и мок-рекомендация ИИ.']
