"""Внутренние уведомления и рассылка по участникам."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Notification, RoleAssignment, User
from app.integrations.telegram import telegram_client


def role_user_ids(db: Session, *roles: str) -> list[int]:
    rows = (
        db.query(RoleAssignment.user_id)
        .join(User, User.id == RoleAssignment.user_id)
        .filter(
            RoleAssignment.revoked_at.is_(None),
            RoleAssignment.role.in_(roles),
            User.active.is_(True),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def captains(db: Session) -> list[int]:
    return role_user_ids(db, "captain", "admin")


def team(db: Session) -> list[int]:
    return role_user_ids(db, "participant", "captain", "admin")


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
        telegram_client.send(telegram_text, mention_usernames)
