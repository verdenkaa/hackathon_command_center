"""Запись в журнал действий (аудит)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AuditEntry


def write_audit(
    db: Session,
    *,
    action: str,
    actor_id: int | None = None,
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    data: dict | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        action=action,
        actor_id=actor_id,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        data=data or {},
    )
    db.add(entry)
    db.flush()
    return entry
