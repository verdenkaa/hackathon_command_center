"""Проект: сводка, дедлайн (только админ), колонки и модули."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import (
    BoardColumn,
    Module,
    Project,
    ProjectState,
    Role,
    RoleAssignment,
    Task,
    TaskAssignee,
    TaskTimer,
    User,
)
from app.deps import active_roles, get_current_user, get_db, require_admin, require_member
from app.schemas import (
    ColumnCreate,
    ColumnOut,
    ColumnPatch,
    ModuleCreate,
    ModuleOut,
    ModulePatch,
    ParticipantOut,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
)
from app.services.audit import write_audit
from app.services.board import create_default_columns
from app.services.incidents import traffic_status
from app.services.timers import current_elapsed
from app.timeutil import to_naive_utc

router = APIRouter(tags=["project"])


def _get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise api_error(404, "NOT_FOUND", "Проект не найден")
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), _u=Depends(get_current_user)) -> list[ProjectOut]:
    rows = db.query(Project).order_by(Project.id).all()
    return [ProjectOut.model_validate(p) for p in rows]


@router.post("/projects", response_model=ProjectOut)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    roles = {a.role for a in active_roles(db, user.id)}
    if Role.admin not in roles:
        raise api_error(403, "FORBIDDEN", "Создавать проекты может только администратор")
    project = Project(name=body.name, state=ProjectState.preparation)
    db.add(project)
    db.flush()
    create_default_columns(db, project.id)
    write_audit(db, action="project.created", actor_id=user.id, project_id=project.id,
                entity_type="project", entity_id=project.id, data={"name": project.name})
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> ProjectOut:
    return ProjectOut.model_validate(_get_project(db, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def patch_project(
    project_id: int,
    body: ProjectPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    project = _get_project(db, project_id)
    updates = body.model_dump(exclude_unset=True)
    roles = {a.role for a in active_roles(db, user.id)}

    if "deadline_msk" in updates:
        if Role.admin not in roles:
            raise api_error(403, "FORBIDDEN", "Дедлайн меняет только администратор")
        old = project.deadline_msk
        project.deadline_msk = to_naive_utc(updates["deadline_msk"]) if updates["deadline_msk"] else None
        write_audit(db, action="project.deadline_changed", actor_id=user.id, project_id=project.id,
                    entity_type="project", entity_id=project.id,
                    data={"old": old.isoformat() if old else None, "new": project.deadline_msk.isoformat() if project.deadline_msk else None})
    if "name" in updates and updates["name"] is not None:
        if not (roles & {Role.captain, Role.admin}):
            raise api_error(403, "FORBIDDEN", "Название меняет капитан или администратор")
        project.name = updates["name"]
        write_audit(db, action="project.renamed", actor_id=user.id, project_id=project.id,
                    entity_type="project", entity_id=project.id, data={"name": project.name})
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}/columns", response_model=list[ColumnOut])
def list_columns(project_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> list[ColumnOut]:
    _get_project(db, project_id)
    rows = (
        db.query(BoardColumn)
        .filter(BoardColumn.project_id == project_id)
        .order_by(BoardColumn.position)
        .all()
    )
    return [ColumnOut.model_validate(c) for c in rows]


DEFAULT_COLUMN_KEYS = {
    "backlog", "todo", "specification_review", "in_progress", "testing", "review", "done", "realised", "trashed",
}


def _slug(title: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
    return slug or "custom"


@router.post("/projects/{project_id}/columns", response_model=ColumnOut)
def create_column(
    project_id: int,
    body: ColumnCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> ColumnOut:
    _get_project(db, project_id)
    key = _slug(body.title)
    i = 2
    while db.query(BoardColumn).filter(BoardColumn.project_id == project_id, BoardColumn.key == key).first():
        key = f"{_slug(body.title)}_{i}"
        i += 1
    max_pos = max(
        (c.position for c in db.query(BoardColumn).filter(BoardColumn.project_id == project_id).all()),
        default=-1,
    )
    column = BoardColumn(
        project_id=project_id, key=key, title=body.title, position=max_pos + 1,
        auto_start_timer=body.auto_start_timer, auto_stop_timer=body.auto_stop_timer,
    )
    db.add(column)
    db.flush()
    write_audit(db, action="column.created", actor_id=user.id, project_id=project_id,
                entity_type="column", entity_id=column.id, data={"title": body.title})
    db.commit()
    db.refresh(column)
    return ColumnOut.model_validate(column)


@router.patch("/columns/{column_id}", response_model=ColumnOut)
def patch_column(
    column_id: int,
    body: ColumnPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> ColumnOut:
    column = db.get(BoardColumn, column_id)
    if column is None:
        raise api_error(404, "NOT_FOUND", "Колонка не найдена")
    if body.title is not None:
        column.title = body.title
    if body.auto_start_timer is not None:
        column.auto_start_timer = body.auto_start_timer
    if body.auto_stop_timer is not None:
        column.auto_stop_timer = body.auto_stop_timer
    write_audit(db, action="column.updated", actor_id=user.id, project_id=column.project_id,
                entity_type="column", entity_id=column.id)
    db.commit()
    db.refresh(column)
    return ColumnOut.model_validate(column)


@router.delete("/columns/{column_id}")
def delete_column(column_id: int, db: Session = Depends(get_db), user: User = Depends(require_member)) -> dict:
    column = db.get(BoardColumn, column_id)
    if column is None:
        raise api_error(404, "NOT_FOUND", "Колонка не найдена")
    if column.key in DEFAULT_COLUMN_KEYS:
        raise api_error(409, "COLUMN_PROTECTED", "Стартовые колонки удалять нельзя")
    backlog = db.query(BoardColumn).filter(
        BoardColumn.project_id == column.project_id, BoardColumn.key == "backlog"
    ).first()
    db.query(Task).filter(Task.column_id == column.id).update({Task.column_id: backlog.id})
    db.delete(column)
    write_audit(db, action="column.deleted", actor_id=user.id, project_id=column.project_id,
                entity_type="column", entity_id=column_id)
    db.commit()
    return {"status": "ok"}


@router.get("/projects/{project_id}/modules", response_model=list[ModuleOut])
def list_modules(project_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> list[ModuleOut]:
    _get_project(db, project_id)
    rows = db.query(Module).filter(Module.project_id == project_id).order_by(Module.id).all()
    return [ModuleOut.model_validate(m) for m in rows]


@router.post("/projects/{project_id}/modules", response_model=ModuleOut)
def create_module(
    project_id: int,
    body: ModuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> ModuleOut:
    _get_project(db, project_id)
    module = Module(project_id=project_id, name=body.name, description=body.description)
    db.add(module)
    db.flush()
    write_audit(db, action="module.created", actor_id=user.id, project_id=project_id, entity_type="module", entity_id=module.id,
                data={"name": module.name})
    db.commit()
    db.refresh(module)
    return ModuleOut.model_validate(module)


@router.patch("/modules/{module_id}", response_model=ModuleOut)
def patch_module(
    module_id: int,
    body: ModulePatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> ModuleOut:
    module = db.get(Module, module_id)
    if module is None:
        raise api_error(404, "NOT_FOUND", "Модуль не найден")
    if body.name is not None:
        module.name = body.name
    if body.description is not None:
        module.description = body.description
    write_audit(db, action="module.updated", actor_id=user.id, project_id=module.project_id, entity_type="module", entity_id=module.id)
    db.commit()
    db.refresh(module)
    return ModuleOut.model_validate(module)


@router.delete("/modules/{module_id}")
def delete_module(module_id: int, db: Session = Depends(get_db), user: User = Depends(require_member)) -> dict:
    module = db.get(Module, module_id)
    if module is None:
        raise api_error(404, "NOT_FOUND", "Модуль не найден")
    db.query(Task).filter(Task.module_id == module_id).update({Task.module_id: None})
    db.delete(module)
    write_audit(db, action="module.deleted", actor_id=user.id, project_id=module.project_id, entity_type="module", entity_id=module_id)
    db.commit()
    return {"status": "ok"}


@router.get("/projects/{project_id}/participants", response_model=list[ParticipantOut])
def list_participants(project_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> list[ParticipantOut]:
    _get_project(db, project_id)
    member_ids = {
        r[0]
        for r in db.query(RoleAssignment.user_id)
        .join(User, User.id == RoleAssignment.user_id)
        .filter(RoleAssignment.revoked_at.is_(None), User.active.is_(True))
        .all()
    }
    done_cols = [
        c.id
        for c in db.query(BoardColumn)
        .filter(BoardColumn.project_id == project_id, BoardColumn.key.in_(["done", "realised", "trashed"]))
        .all()
    ]

    result: list[ParticipantOut] = []
    for uid in member_ids:
        user = db.get(User, uid)
        assignee_task_ids = [a.task_id for a in db.query(TaskAssignee).filter(TaskAssignee.user_id == uid).all()]
        running = (
            db.query(TaskTimer)
            .filter(TaskTimer.task_id.in_(assignee_task_ids), TaskTimer.state == "running")
            .all()
            if assignee_task_ids
            else []
        )
        running_seconds = sum(
            current_elapsed(t) for t in running
        )
        active_tasks = (
            db.query(Task)
            .filter(Task.id.in_(assignee_task_ids), Task.column_id.notin_(done_cols))
            .count()
            if assignee_task_ids
            else 0
        )
        result.append(
            ParticipantOut(
                id=user.id,
                login=user.login,
                display_name=user.display_name,
                telegram_username=user.telegram_username,
                traffic_status=traffic_status(db, "user", user.id),
                active_tasks=active_tasks,
                active_timer_seconds=running_seconds,
            )
        )
    return result
