"""Журнал действий (аудит): чтение доступно всем авторизованным участникам."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.models import AuditEntry, AuditRevision
from app.deps import get_current_user, get_db
from app.schemas import AuditEntryOut, AuditRevisionOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEntryOut])
def audit_list(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[AuditEntryOut]:
    rows = db.query(AuditEntry).order_by(AuditEntry.created_at.desc()).offset(offset).limit(limit).all()
    return [AuditEntryOut.model_validate(r) for r in rows]


@router.get("/{entry_id}/revisions", response_model=list[AuditRevisionOut])
def audit_revisions(
    entry_id: int,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
) -> list[AuditRevisionOut]:
    rows = (
        db.query(AuditRevision)
        .filter(AuditRevision.audit_entry_id == entry_id)
        .order_by(AuditRevision.edited_at)
        .all()
    )
    return [AuditRevisionOut.model_validate(r) for r in rows]
