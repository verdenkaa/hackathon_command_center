"""Логика аутентификации: вход, сессии, ограничения частоты."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.config import settings
from app.db.models import IpRule, LoginEvent, Session as SessionModel, User
from app.security import generate_token, hash_token, verify_password

FAILURE_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_LOGIN = 5
MAX_FAILURES_PER_IP = 10
SESSION_TTL = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_ip_blocked(db: Session, ip: str | None) -> bool:
    if not ip:
        return False
    return db.query(IpRule).filter(IpRule.ip == ip, IpRule.action == "block").first() is not None


def failure_counts(db: Session, ip: str | None, login: str) -> tuple[int, int]:
    since = _now() - FAILURE_WINDOW
    by_ip = (
        db.query(LoginEvent)
        .filter(LoginEvent.ip == ip, LoginEvent.success.is_(False), LoginEvent.created_at >= since)
        .filter(LoginEvent.login == login if settings.app_managed else True)
        .count()
    )
    by_login = (
        db.query(LoginEvent)
        .filter(LoginEvent.login == login, LoginEvent.success.is_(False), LoginEvent.created_at >= since)
        .count()
    )
    return by_ip, by_login


def record_login(
    db: Session,
    *,
    login: str,
    ip: str | None,
    user_id: int | None,
    success: bool,
    reason: str | None = None,
) -> None:
    db.add(LoginEvent(login=login, ip=ip, user_id=user_id, success=success, reason=reason))
    db.commit()


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> tuple[str, SessionModel]:
    raw_token = generate_token()
    session = SessionModel(
        token_hash=hash_token(raw_token),
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
        expires_at=_now() + SESSION_TTL,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_token, session


def authenticate(
    db: Session, login: str, password: str, ip: str | None, user_agent: str | None
) -> tuple[User, str]:
    if is_ip_blocked(db, ip):
        record_login(db, login=login, ip=ip, user_id=None, success=False, reason="ip_blocked")
        raise api_error(403, "IP_BLOCKED", "IP-адрес заблокирован")

    by_ip, by_login = failure_counts(db, ip, login)
    if by_ip >= MAX_FAILURES_PER_IP or by_login >= MAX_FAILURES_PER_LOGIN:
        record_login(db, login=login, ip=ip, user_id=None, success=False, reason="rate_limited")
        raise api_error(429, "RATE_LIMITED", "Слишком много неудачных попыток, попробуйте позже")

    user = db.query(User).filter(User.login == login).first()
    if user is None or user.deleted_identity or not verify_password(password, user.password_hash):
        record_login(db, login=login, ip=ip, user_id=None, success=False, reason="bad_credentials")
        raise api_error(401, "BAD_CREDENTIALS", "Неверный логин или пароль")

    if not user.active:
        record_login(db, login=login, ip=ip, user_id=user.id, success=False, reason="deactivated")
        raise api_error(403, "DEACTIVATED", "Аккаунт деактивирован")

    record_login(db, login=login, ip=ip, user_id=user.id, success=True)
    raw_token, _ = create_session(db, user, ip, user_agent)
    return user, raw_token


def revoke_session(db: Session, token_hash: str) -> None:
    session = db.query(SessionModel).filter(SessionModel.token_hash == token_hash).first()
    if session and session.revoked_at is None:
        session.revoked_at = _now()
        db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    db.query(SessionModel).filter(
        SessionModel.user_id == user_id, SessionModel.revoked_at.is_(None)
    ).update({SessionModel.revoked_at: _now()})
    db.commit()
