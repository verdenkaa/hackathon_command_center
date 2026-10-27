"""Общие зависимости FastAPI: сессия БД, текущий пользователь, проверка ролей."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import Project, ProjectState, Role, RoleAssignment, Session as SessionModel, User
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
    return user


def require_role(*roles: Role):
    def _dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        user_roles = {a.role for a in active_roles(db, user.id)}
        if not user_roles.intersection(roles):
            raise api_error(403, "FORBIDDEN", "Недостаточно прав")
        return user

    return _dep


require_admin = require_role(Role.admin)
require_captain_or_admin = require_role(Role.captain, Role.admin)
require_member = require_role(Role.participant, Role.captain, Role.admin)


def ensure_project_active(db: Session, project_id: int) -> None:
    project = db.get(Project, project_id)
    if project is not None and project.state == ProjectState.completed:
        raise api_error(409, "PROJECT_COMPLETED", "Проект завершён — доступ только для чтения")
