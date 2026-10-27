"""Общие зависимости FastAPI: сессия БД, текущий пользователь, проверка ролей."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import (Project, ProjectState, Role, RoleAssignment, Session as SessionModel, User,
                           Task, Incident, BoardColumn, Module, Document, ChecklistItem, AuditEntry, Notification)
from app.db.session import SessionLocal
from app.security import hash_token

SESSION_COOKIE = "session"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def active_roles(db: Session, user_id: int) -> list[RoleAssignment]:
    return (
        db.query(RoleAssignment)
        .filter(RoleAssignment.user_id == user_id, RoleAssignment.revoked_at.is_(None))
        .all()
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise api_error(401, "UNAUTHENTICATED", "Требуется вход")
    session = (
        db.query(SessionModel)
        .filter(SessionModel.token_hash == hash_token(token), SessionModel.revoked_at.is_(None))
        .first()
    )
    if session is None or session.expires_at < _now():
        raise api_error(401, "UNAUTHENTICATED", "Сессия недействительна или истекла")
    user = db.get(User, session.user_id)
    if user is None:
        raise api_error(401, "UNAUTHENTICATED", "Пользователь не найден")
    if not user.active:
        raise api_error(403, "DEACTIVATED", "Аккаунт деактивирован")
    project_id = request_project_id(request, db)
    if project_id is not None:
        if not project_roles(db, user.id, project_id):
            raise api_error(403, "FORBIDDEN", "Нет доступа к этому проекту")
        if (request.method not in {"GET", "HEAD", "OPTIONS"}
                and not request.url.path.endswith('/completion-votes')
                and '/notifications/' not in request.url.path):
            ensure_project_active(db, project_id)
    return user


def require_role(*roles: Role):
    def _dep(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        project_id = request_project_id(request, db)
        user_roles = project_roles(db, user.id, project_id)
        if not user_roles.intersection(roles):
            raise api_error(403, "FORBIDDEN", "Недостаточно прав")
        return user

    return _dep


require_admin = require_role(Role.admin)
require_captain_or_admin = require_role(Role.captain, Role.admin)
require_member = require_role(Role.participant, Role.captain, Role.admin)


def project_roles(db: Session, user_id: int, project_id: int | None) -> set[Role]:
    return {a.role for a in active_roles(db, user_id)
            if a.role == Role.admin or (project_id is not None and a.project_id == project_id)}


def project_member_ids(db: Session, project_id: int) -> list[int]:
    return [row[0] for row in db.query(RoleAssignment.user_id).join(User, User.id == RoleAssignment.user_id)
            .filter(RoleAssignment.revoked_at.is_(None), User.active.is_(True),
                    (RoleAssignment.project_id == project_id) | (RoleAssignment.role == Role.admin))
            .distinct().all()]


def visible_project_ids(db: Session, user_id: int) -> list[int]:
    roles = active_roles(db, user_id)
    if any(a.role == Role.admin for a in roles):
        return [p[0] for p in db.query(Project.id).all()]
    return list({a.project_id for a in roles if a.project_id is not None})


def request_project_id(request: Request, db: Session) -> int | None:
    """Resolve project ownership for both project URLs and object URLs."""
    project_ids: set[int] = set()
    raw_project = request.path_params.get('project_id')
    if raw_project is not None:
        try:
            project_id = int(raw_project)
        except (ValueError, TypeError):
            raise api_error(422, "VALIDATION_ERROR", "Неверный ID проекта")
        if db.get(Project, project_id) is None:
            raise api_error(404, "NOT_FOUND", "Проект не найден")
        project_ids.add(project_id)
    for key, model in [('task_id', Task), ('incident_id', Incident), ('column_id', BoardColumn),
                       ('module_id', Module), ('document_id', Document), ('entry_id', AuditEntry),
                       ('notification_id', Notification)]:
        raw_id = request.path_params.get(key)
        if raw_id is not None:
            try:
                entity = db.get(model, int(raw_id))
            except (ValueError, TypeError):
                raise api_error(422, "VALIDATION_ERROR", "Неверный ID объекта")
            if entity is None:
                raise api_error(404, "NOT_FOUND", "Объект не найден")
            if entity.project_id is not None:
                project_ids.add(entity.project_id)
    if 'item_id' in request.path_params:
        try:
            item = db.get(ChecklistItem, int(request.path_params['item_id']))
        except (ValueError, TypeError):
            raise api_error(422, "VALIDATION_ERROR", "Неверный ID пункта")
        if item is None:
            raise api_error(404, "NOT_FOUND", "Пункт не найден")
        project_ids.add(db.get(Task, item.task_id).project_id)
    if len(project_ids) > 1:
        raise api_error(404, "NOT_FOUND", "Объект не принадлежит проекту")
    return next(iter(project_ids), None)


def ensure_project_active(db: Session, project_id: int) -> None:
    project = db.get(Project, project_id)
    if project is not None and project.state == ProjectState.completed:
        raise api_error(409, "PROJECT_COMPLETED", "Проект завершён — доступ только для чтения")
