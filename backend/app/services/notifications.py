"""Внутренние уведомления и рассылка по участникам."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Notification, RoleAssignment, User, Role, TelegramDelivery
from app.integrations.telegram import telegram_client


def role_user_ids(db: Session, *roles: str, project_id: int | None = None) -> list[int]:
    rows = (
        db.query(RoleAssignment.user_id)
        .join(User, User.id == RoleAssignment.user_id)
        .filter(
            RoleAssignment.revoked_at.is_(None),
            RoleAssignment.role.in_(roles),
            User.active.is_(True),
            (RoleAssignment.project_id == project_id) | (RoleAssignment.role == Role.admin),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def captains(db: Session, project_id: int | None = None) -> list[int]:
    return role_user_ids(db, "captain", "admin", project_id=project_id)


def team(db: Session, project_id: int | None = None) -> list[int]:
    return role_user_ids(db, "participant", "captain", "admin", project_id=project_id)


def notify_users(
    db: Session,
    *,
    project_id: int | None,
    user_ids: list[int],
    ntype: str,
    payload: dict,
    telegram_text: str | None = None,
    mention_usernames: list[str] | None = None,
) -> None:
    for uid in set(user_ids):
        db.add(Notification(project_id=project_id, user_id=uid, type=ntype, payload=payload))
    db.flush()
    if telegram_text:
        db.add(TelegramDelivery(project_id=project_id, event_type=ntype, text=telegram_text,
                                mentions=mention_usernames or [], mode='mock'))
        db.flush()
