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
from app.security import hash_password
from app.services.audit import write_audit
from app.services.board import create_default_columns
from app.services.incidents import create_incident
from app.timeutil import utcnow

SANDBOX_NAME = "Sandbox"

# Сценарии: имя → описание для интерфейса.
SCENARIOS: dict[str, str] = {
    "create_team": "Создать тестовую команду (alice, bob — участники; cap — капитан)",
    "simulate_sprint": "Симулировать работу: задачи, таймеры, перемещения и инцидент от имени команды",
    "overdue_as_dev": "От имени alice просрочить задачу (дедлайн в прошлом)",
    "incident_as_dev": "От имени bob создать жёлтый инцидент",
    "timer_cycle": "Полный цикл таймера: start → pause → stop",
    "integration_failure": "Симулировать отказ внешних интеграций (без реальных вызовов)",
}

TEAM = [("alice", "Alice", "participant"), ("bob", "Bob", "participant"), ("cap", "Captain", "captain")]


def get_sandbox_project(db: Session) -> Project:
    project = db.query(Project).filter(Project.name == SANDBOX_NAME).first()
    if project is None:
        project = Project(name=SANDBOX_NAME, state=ProjectState.active)
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
        if u is None:
            u = User(login=login, password_hash=hash_password("sandbox-pass"), display_name=name, active=True)
            db.add(u)
            db.flush()
        assigned = db.query(RoleAssignment).filter(
            RoleAssignment.user_id == u.id,
            RoleAssignment.role == role,
            RoleAssignment.project_id == project.id,
            RoleAssignment.revoked_at.is_(None),
        ).first()
        if assigned is None:
            db.add(RoleAssignment(user_id=u.id, role=role, project_id=project.id, granted_by=None))
        users[login] = u
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

    if scenario == "create_team":
        team = get_team(db, project)
        logs.append(f"Команда создана: {', '.join(f'{k} ({v.display_name})' for k, v in team.items())}")

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

    elif scenario == "integration_failure":
        logs.append("Симулирован отказ Telegram/ИИ/Drive (внешние вызовы не выполнялись)")

    else:
        return False, [f"Неизвестный сценарий: {scenario}"]

    return True, logs


def record_run(db: Session, scenario: str, status: str, logs: list[str], actor_id: int | None) -> SandboxRun:
    run = SandboxRun(scenario=scenario, status=status, logs=logs, run_by=actor_id)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
