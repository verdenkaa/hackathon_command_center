"""Административные эндпоинты: аккаунты, роли, входы, IP, аудит."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import (
    AuditEntry,
    AuditRevision,
    IpRule,
    LoginEvent,
    Role,
    RoleAssignment,
    User,
)
from app.deps import get_db, require_admin
from app.schemas import (
    AuditEdit,
    IpRuleCreate,
    LoginEventOut,
    PasswordReset,
    RoleAssign,
    RoleOut,
    UserCreate,
    UserOut,
    UserPatch,
)
from app.security import hash_password
from app.services.audit import write_audit
from app.services.auth_service import revoke_all_sessions

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def active_admin_ids(db: Session) -> list[int]:
    rows = (
        db.query(RoleAssignment.user_id)
        .join(User, User.id == RoleAssignment.user_id)
        .filter(
            RoleAssignment.role == Role.admin,
            RoleAssignment.revoked_at.is_(None),
            User.active.is_(True),
        )
        .all()
    )
    return [r[0] for r in rows]


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    rows = db.query(User).order_by(User.id).all()
    return [UserOut.model_validate(u) for u in rows]


@router.get("/roles")
def list_roles(db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(RoleAssignment)
        .filter(RoleAssignment.revoked_at.is_(None))
        .order_by(RoleAssignment.id)
        .all()
    )
    return [
        {"id": r.id, "user_id": r.user_id, "role": r.role.value, "project_id": r.project_id}
        for r in rows
    ]


@router.post("/users", response_model=UserOut)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> UserOut:
    if db.query(User).filter(User.login == body.login).first():
        raise api_error(409, "LOGIN_TAKEN", "Логин уже занят")
    user = User(
        login=body.login,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        telegram_username=body.telegram_username,
        active=True,
    )
    db.add(user)
    db.flush()
    write_audit(db, action="user.created", actor_id=admin.id, entity_type="user", entity_id=user.id,
                data={"login": user.login, "display_name": user.display_name})
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise api_error(404, "NOT_FOUND", "Пользователь не найден")
    if body.login is not None and body.login != user.login:
        if db.query(User).filter(User.login == body.login).first():
            raise api_error(409, "LOGIN_TAKEN", "Логин уже занят")
        write_audit(db, action="user.login_changed", actor_id=admin.id, entity_type="user", entity_id=user.id,
                    data={"old": user.login, "new": body.login})
        user.login = body.login
    if body.display_name is not None and body.display_name != user.display_name:
        write_audit(db, action="user.name_changed", actor_id=admin.id, entity_type="user", entity_id=user.id,
                    data={"old": user.display_name, "new": body.display_name})
        user.display_name = body.display_name
    if body.telegram_username is not None and body.telegram_username != user.telegram_username:
        user.telegram_username = body.telegram_username
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/password-reset", response_model=UserOut)
def password_reset(user_id: int, body: PasswordReset, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise api_error(404, "NOT_FOUND", "Пользователь не найден")
    user.password_hash = hash_password(body.new_password)
    revoke_all_sessions(db, user.id)
    write_audit(db, action="user.password_reset", actor_id=admin.id, entity_type="user", entity_id=user.id)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise api_error(404, "NOT_FOUND", "Пользователь не найден")
    if user.id in active_admin_ids(db) and len(set(active_admin_ids(db))) <= 1:
        raise api_error(409, "LAST_ADMIN", "Нельзя деактивировать последнего администратора")
    if user.active:
        user.active = False
        now = _now()
        db.query(RoleAssignment).filter(
            RoleAssignment.user_id == user.id, RoleAssignment.revoked_at.is_(None)
        ).update({RoleAssignment.revoked_at: now})
        revoke_all_sessions(db, user.id)
        write_audit(db, action="user.deactivated", actor_id=admin.id, entity_type="user", entity_id=user.id)
        db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/roles", response_model=RoleOut)
def assign_role(body: RoleAssign, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> RoleOut:
    user = db.get(User, body.user_id)
    if user is None:
        raise api_error(404, "NOT_FOUND", "Пользователь не найден")
    project_id = None if body.role == Role.admin else body.project_id
    if body.role != Role.admin:
        if project_id is None:
            raise api_error(422, "VALIDATION_ERROR", "Для роли нужен проект")
        from app.db.models import Project
        if db.get(Project, project_id) is None:
            raise api_error(404, "NOT_FOUND", "Проект не найден")
    if not user.active:
        raise api_error(422, "VALIDATION_ERROR", "Нельзя назначить роль отключённому пользователю")
    existing = (
        db.query(RoleAssignment)
        .filter(
            RoleAssignment.user_id == user.id,
            RoleAssignment.role == body.role,
            RoleAssignment.project_id == project_id,
        )
        .first()
    )
    if existing and existing.revoked_at is None:
        raise api_error(409, "ROLE_EXISTS", "Роль уже назначена")
    assignment = existing or RoleAssignment(user_id=user.id, role=body.role, project_id=project_id, granted_by=admin.id)
    assignment.revoked_at = None
    assignment.granted_by = admin.id
    assignment.granted_at = _now()
    db.add(assignment)
    db.flush()
    write_audit(db, action="role.granted", actor_id=admin.id, entity_type="role", entity_id=assignment.id,
                data={"user_id": user.id, "role": body.role.value, "project_id": project_id})
    db.commit()
    db.refresh(assignment)
    return RoleOut.model_validate(assignment)


@router.delete("/roles/{assignment_id}")
def revoke_role(assignment_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    assignment = db.get(RoleAssignment, assignment_id)
    if assignment is None or assignment.revoked_at is not None:
        raise api_error(404, "NOT_FOUND", "Назначение роли не найдено")
    if assignment.role == Role.admin and len(set(active_admin_ids(db))) <= 1:
        raise api_error(409, "LAST_ADMIN", "Нельзя отозвать роль последнего администратора")
    assignment.revoked_at = _now()
    write_audit(db, action="role.revoked", actor_id=admin.id, entity_type="role", entity_id=assignment.id,
                data={"user_id": assignment.user_id, "role": assignment.role.value})
    db.commit()
    return {"status": "ok"}


@router.get("/login-events", response_model=list[LoginEventOut])
def login_events(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[LoginEventOut]:
    rows = db.query(LoginEvent).order_by(LoginEvent.created_at.desc()).offset(offset).limit(limit).all()
    return [LoginEventOut.model_validate(r) for r in rows]


@router.post("/ip-rules", response_model=IpRuleCreate)
def block_ip(body: IpRuleCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> IpRuleCreate:
    if db.query(IpRule).filter(IpRule.ip == body.ip, IpRule.action == "block").first():
        raise api_error(409, "IP_ALREADY_BLOCKED", "IP уже заблокирован")
    db.add(IpRule(ip=body.ip, action="block", created_by=admin.id))
    write_audit(db, action="ip.blocked", actor_id=admin.id, entity_type="ip", entity_id=body.ip)
    db.commit()
    return body


@router.delete("/ip-rules/{rule_id}")
def unblock_ip(rule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    rule = db.get(IpRule, rule_id)
    if rule is None:
        raise api_error(404, "NOT_FOUND", "Правило не найдено")
    ip = rule.ip
    db.delete(rule)
    write_audit(db, action="ip.unblocked", actor_id=admin.id, entity_type="ip", entity_id=ip)
    db.commit()
    return {"status": "ok"}


@router.post("/ip-rules/reset")
def reset_ip_limit(ip: str = Query(...), db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    db.query(LoginEvent).filter(LoginEvent.ip == ip, LoginEvent.success.is_(False)).delete()
    write_audit(db, action="ip.limit_reset", actor_id=admin.id, entity_type="ip", entity_id=ip)
    db.commit()
    return {"status": "ok"}


@router.patch("/audit/{entry_id}")
def edit_audit(entry_id: int, body: AuditEdit, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    entry = db.get(AuditEntry, entry_id)
    if entry is None:
        raise api_error(404, "NOT_FOUND", "Запись журнала не найдена")
    field = body.field
    if field not in ("action", "entity_type", "entity_id"):
        raise api_error(422, "VALIDATION_ERROR", "Нельзя править это поле")
    old_value = getattr(entry, field)
    setattr(entry, field, body.new_value)
    db.add(AuditRevision(
        audit_entry_id=entry.id,
        field=field,
        old_value=old_value,
        new_value=body.new_value,
        edited_by=admin.id,
    ))
    db.commit()
    return {"status": "ok"}
