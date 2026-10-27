"""Журнал действий (аудит): чтение доступно всем авторизованным участникам."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.models import AuditEntry, AuditRevision
from app.deps import get_current_user, get_db, visible_project_ids, project_roles
from app.schemas import AuditEntryOut, AuditRevisionOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEntryOut])
def audit_list(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[AuditEntryOut]:
    from app.db.models import Role
    query = db.query(AuditEntry)
    if Role.admin not in project_roles(db, _user.id, None):
        query = query.filter(AuditEntry.project_id.in_(visible_project_ids(db, _user.id)))
    rows = query.order_by(AuditEntry.created_at.desc()).offset(offset).limit(limit).all()
    return [AuditEntryOut.model_validate(r) for r in rows]


@router.get("/{entry_id}/revisions", response_model=list[AuditRevisionOut])
def audit_revisions(
    entry_id: int,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
) -> list[AuditRevisionOut]:
    from app.db.models import Role
    from app.api.errors import api_error
    entry = db.get(AuditEntry, entry_id)
    if entry is None or (entry.project_id is None and Role.admin not in project_roles(db, _user.id, None)):
        raise api_error(404, 'NOT_FOUND', 'Запись не найдена')
    rows = (
        db.query(AuditRevision)
        .filter(AuditRevision.audit_entry_id == entry_id)
        .order_by(AuditRevision.edited_at)
        .all()
    )
    return [AuditRevisionOut.model_validate(r) for r in rows]
