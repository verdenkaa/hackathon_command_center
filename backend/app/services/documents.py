"""Документы: файловое хранилище Markdown и блокировки редактирования."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.config import settings
from app.db.models import DocumentLock
from app.timeutil import utcnow

LOCK_TTL = timedelta(minutes=5)


def doc_root(project_id: int) -> Path:
    return settings.data_dir / "documents" / str(project_id)


def resolve_path(project_id: int, rel_path: str) -> Path:
    root = doc_root(project_id).resolve()
    p = (root / rel_path).resolve()
    if not str(p).startswith(str(root)):
        raise api_error(422, "VALIDATION_ERROR", "Некорректный путь документа")
    return p


def checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_file(project_id: int, rel_path: str) -> str:
    p = resolve_path(project_id, rel_path)
    if not p.exists():
        raise api_error(404, "NOT_FOUND", "Файл документа не найден")
    return p.read_text(encoding="utf-8")


def write_file(project_id: int, rel_path: str, content: str) -> None:
    p = resolve_path(project_id, rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def write_bytes(project_id: int, rel_path: str, data: bytes) -> None:
    p = resolve_path(project_id, rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def delete_file(project_id: int, rel_path: str) -> None:
    p = resolve_path(project_id, rel_path)
    if p.exists():
        p.unlink()


def active_lock(db: Session, document_id: int) -> DocumentLock | None:
    lock = db.query(DocumentLock).filter(DocumentLock.document_id == document_id).first()
    if lock is None:
        return None
    if (utcnow() - lock.last_activity_at) < LOCK_TTL:
        return lock
    # Истекшая блокировка снимается.
    db.delete(lock)
    db.flush()
    return None


def acquire_lock(db: Session, document_id: int, user_id: int) -> DocumentLock:
    lock = active_lock(db, document_id)
    if lock is not None and lock.user_id != user_id:
        raise api_error(409, "DOCUMENT_LOCKED", "Файл редактируется другим пользователем")
    if lock is None:
        lock = DocumentLock(document_id=document_id, user_id=user_id)
        db.add(lock)
        db.flush()
    else:
        lock.last_activity_at = utcnow()
        db.flush()
    return lock


def release_lock(db: Session, document_id: int, user_id: int) -> None:
    lock = db.query(DocumentLock).filter(DocumentLock.document_id == document_id).first()
    if lock is not None and lock.user_id == user_id:
        db.delete(lock)
        db.flush()


def heartbeat_lock(db: Session, document_id: int, user_id: int) -> None:
    lock = db.query(DocumentLock).filter(DocumentLock.document_id == document_id).first()
    if lock is not None and lock.user_id == user_id:
        lock.last_activity_at = utcnow()
        db.flush()
